"""
eval_augmented.py — Evaluate surrogates trained on augmented data
(12 original Gyroid + Shanghai synthetic rows).

Metrics:
    1. LOO MAPE on original 12 Gyroid geometries (Shanghai always in training)
    2. Shanghai 16-case RMSRE (full non-isothermal SIMPLE)
    3. c_F(t) trend (L=7, t=0.3->0.7)
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_THERMONAS = _THIS.parent.parent
if str(_THERMONAS) not in sys.path:
    sys.path.insert(0, str(_THERMONAS))

from .augment_shanghai import load_augmented, shanghai_synth_rows, SH_L, SH_T
from .eval_arms import (
    per_geom_reference, eval_shanghai, eval_cF_trend, compare_arms,
    TrainPredictFn, PredictFn, FIG_DIR,
)
from .fit_df_per_geom import K_S_CELLS
from .train_surrogate import (
    _per_geom_reference, _norm_from_ref, _train_ensemble,
    _predict_KcF_vec, SEED,
)
from .train_arm1 import make_arm1, CONFIGS as ARM1_CONFIGS

from solvers.tpms_calc import geometry as tpms_geometry  # noqa: E402

# Shanghai geometry for predict_fn
_SH_KS = 16.0

# Original 12 Gyroid (L, t) combos — for LOO iteration
_ORIG_LT = [(L, t) for L in (4, 5, 6, 8) for t in (0.3, 0.4, 0.5)]


# ==================================================================
# Custom LOO: iterate over original 12 only, Shanghai always in train
# ==================================================================

def eval_loo_original_12(train_predict_fn: TrainPredictFn,
                         df_aug: pd.DataFrame,
                         ) -> tuple[float, pd.DataFrame]:
    """LOO on original 12 Gyroid geometries.
    Shanghai synthetic rows stay in every training fold."""
    sub = df_aug[df_aug["tpms"] == "Gyroid"].reset_index(drop=True)
    ref = per_geom_reference(sub).sort_values(
        ["L_mm", "t_mm"]).reset_index(drop=True)

    rows: list[dict] = []
    fold = 0
    for L_out, t_out in _ORIG_LT:
        ref_row = ref[(ref["L_mm"] == L_out) & (ref["t_mm"] == t_out)]
        if ref_row.empty:
            continue
        r = ref_row.iloc[0]
        eps_f_out = float(r["eps_f"])

        # Hold out only the original geometry; Shanghai rows stay
        mask_out = ((sub["L_mm"] == L_out) & (sub["t_mm"] == t_out)
                    & (sub["label"] != "SH_7_06"))
        train_rows = sub[~mask_out].reset_index(drop=True)
        test_rows = sub[mask_out].reset_index(drop=True)

        if test_rows.empty:
            continue
        fold += 1

        K_pred, cF_pred = train_predict_fn(
            train_rows, L_out, t_out, eps_f_out)

        u = test_rows["u_mps"].to_numpy(dtype=float)
        dP_obs = test_rows["dP_Pa"].to_numpy(dtype=float)
        mu = test_rows["mu"].to_numpy(dtype=float)
        rho = test_rows["rho"].to_numpy(dtype=float)
        L_ch = K_S_CELLS * L_out * 1e-3
        dP_pred = (mu * u / K_pred + rho * cF_pred * u ** 2) * L_ch
        rel = np.abs(dP_pred - dP_obs) / dP_obs
        dP_mape = float(rel.mean() * 100.0)

        rows.append({
            "L_mm": L_out, "t_mm": t_out,
            "K_ref": float(r["K"]), "K_pred": K_pred,
            "cF_ref": float(r["c_F"]), "cF_pred": cF_pred,
            "dP_MAPE": dP_mape,
        })
        print(f"  LOO {fold}/12: L={L_out:.0f} t={t_out:.1f} "
              f"K={K_pred:.3e} cF={cF_pred:.1f} -> MAPE={dP_mape:.1f}%")

    loo_df = pd.DataFrame(rows)
    mape = float(loo_df["dP_MAPE"].mean())
    return mape, loo_df


# ==================================================================
# Full arm evaluation (augmented)
# ==================================================================

def evaluate_augmented(name: str,
                       train_predict_fn: TrainPredictFn,
                       predict_fn: PredictFn,
                       df_aug: pd.DataFrame,
                       skip_shanghai: bool = False,
                       ) -> dict:
    """Run 3-metric evaluation on augmented data."""
    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")

    # 1. LOO on original 12
    print("\n[1/3] LOO on original 12 Gyroid (Shanghai in training)")
    loo_mape, loo_df = eval_loo_original_12(train_predict_fn, df_aug)
    print(f"  >> LOO MAPE = {loo_mape:.2f}%")

    # 2. Shanghai RMSRE
    rmsre = float("nan")
    sh_results: list[dict] = []
    K_sh = cF_sh = float("nan")
    if not skip_shanghai:
        print("\n[2/3] Shanghai 16-case RMSRE")
        g = tpms_geometry("Gyroid", SH_L, SH_T, _SH_KS)
        K_sh, cF_sh = predict_fn(SH_L, SH_T, g["epsilon"] / 2.0)
        print(f"  K={K_sh:.4e}  c_F={cF_sh:.2f}")
        rmsre, sh_results = eval_shanghai(K_sh, cF_sh)
        print(f"  >> Shanghai RMSRE = {rmsre:.2f}%")
    else:
        print("\n[2/3] Shanghai -- skipped")

    # 3. c_F trend
    print("\n[3/3] c_F(t) trend")
    t_arr, K_trend, cF_trend = eval_cF_trend(predict_fn)
    print(f"  c_F range: {cF_trend.min():.1f} -> {cF_trend.max():.1f}")

    return dict(
        name=name,
        loo_mape=loo_mape, loo_df=loo_df,
        shanghai_rmsre=rmsre, shanghai_results=sh_results,
        K_shanghai=K_sh, cF_shanghai=cF_sh,
        t_arr=t_arr, K_trend=K_trend, cF_trend=cF_trend,
    )


# ==================================================================
# Build callables for v1-augmented
# ==================================================================

def _make_v1_aug(df_aug: pd.DataFrame,
                 ) -> tuple[TrainPredictFn, PredictFn]:
    """v1 MLP (L, t, eps_f) trained on augmented data."""
    sub = df_aug[df_aug["tpms"] == "Gyroid"].reset_index(drop=True)
    ref_full = _per_geom_reference(sub)
    norm_full = _norm_from_ref(ref_full)
    models_full, _ = _train_ensemble(sub, norm_full, base_seed=SEED)

    def train_predict(train_df, L_mm, t_mm, eps_f):
        ref = _per_geom_reference(train_df)
        norm = _norm_from_ref(ref)
        models, _ = _train_ensemble(train_df, norm, base_seed=SEED)
        K_arr, cF_arr = _predict_KcF_vec(
            models, norm,
            np.array([L_mm]), np.array([t_mm]), np.array([eps_f]))
        return float(K_arr[0]), float(cF_arr[0])

    def predict(L_mm, t_mm, eps_f):
        K_arr, cF_arr = _predict_KcF_vec(
            models_full, norm_full,
            np.array([L_mm]), np.array([t_mm]), np.array([eps_f]))
        return float(K_arr[0]), float(cF_arr[0])

    return train_predict, predict


# ==================================================================
# CLI
# ==================================================================

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    warnings.filterwarnings("ignore")

    skip_sh = "--skip-shanghai" in sys.argv
    df_aug = load_augmented()
    print(f"Augmented data: {len(df_aug)} rows, "
          f"{df_aug[df_aug['tpms']=='Gyroid'].groupby(['L_mm','t_mm']).ngroups} "
          f"Gyroid geometries")

    results = []

    # v1 augmented
    print("\nBuilding v1-augmented...")
    tp_v1, pred_v1 = _make_v1_aug(df_aug)
    r_v1 = evaluate_augmented("v1 + Shanghai", tp_v1, pred_v1,
                              df_aug, skip_shanghai=skip_sh)
    results.append(r_v1)

    # Arm 1c augmented
    print("\nBuilding Arm1c-augmented...")
    tp_1c, pred_1c = make_arm1("1c", df_aug)
    r_1c = evaluate_augmented("Arm1c + Shanghai", tp_1c, pred_1c,
                              df_aug, skip_shanghai=skip_sh)
    results.append(r_1c)

    compare_arms(results)


if __name__ == "__main__":
    main()
