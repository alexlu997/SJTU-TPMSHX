"""
Arm 3: MLP + physics constraints.

Same MLP architecture as ConstDF-v1, with three penalty terms added to the
training loss:

1. D_h monotonicity: c_F(D_h_small) > c_F(D_h_large) for virtual point pairs
2. Boundary floor: c_F(t>0.5) >= c_F(t=0.5) for each L in training set
3. Asymptotic: c_F -> large when eps_f -> 0

Loss = L_data + lam1*L_mono + lam2*L_bnd + lam3*L_asym
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.optim import Adam

_THIS = Path(__file__).resolve()
_THERMONAS = _THIS.parent.parent
if str(_THERMONAS) not in sys.path:
    sys.path.insert(0, str(_THERMONAS))

from solvers.tpms_calc import geometry as tpms_geometry  # noqa: E402

from .fit_df_per_geom import K_S_CELLS  # noqa: E402
from .eval_arms import (  # noqa: E402
    per_geom_reference, evaluate_arm, compare_arms, load_all,
    TrainPredictFn, PredictFn,
)
from .train_surrogate import (  # noqa: E402
    DFMLP, FEATURES, HIDDEN, DROPOUT, LR, WEIGHT_DECAY,
    EPOCHS, PATIENCE, GRAD_CLIP, SEED, N_ENSEMBLE, INPUT_DIM,
    _per_geom_reference, _norm_from_ref, _rows_to_tensors,
    _forward_K_cF, _predict_KcF_vec,
)

_KS = 16.0
TPMS = "Gyroid"

# Constraint hyper-parameters (tunable)
LAM1 = 1.0      # D_h monotonicity
LAM2 = 1.0      # boundary floor
LAM3 = 0.3      # asymptotic


# ==================================================================
# Constraint point generation
# ==================================================================

def _make_constraint_points(ref: pd.DataFrame, norm: dict,
                            ) -> dict[str, torch.Tensor]:
    """Pre-compute constraint tensors from the training reference table."""
    pts: dict[str, torch.Tensor] = {}

    # ---- 1. D_h monotonicity pairs ----
    # For each pair of geometries with different D_h, require:
    #   c_F(smaller D_h) > c_F(larger D_h)
    # We generate pairs across different L values at same t, and
    # virtual pairs by interpolating between training points.
    L_vals = sorted(ref["L_mm"].unique())
    t_vals = sorted(ref["t_mm"].unique())

    z_small_list, z_large_list = [], []
    for t in t_vals:
        sub = ref[ref["t_mm"] == t].sort_values("L_mm")
        if len(sub) < 2:
            continue
        for i in range(len(sub)):
            for j in range(i + 1, len(sub)):
                ri, rj = sub.iloc[i], sub.iloc[j]
                # Smaller L -> smaller D_h -> should have higher c_F
                if ri["L_mm"] < rj["L_mm"]:
                    small_row, large_row = ri, rj
                else:
                    small_row, large_row = rj, ri
                x_s = np.log10([[small_row["L_mm"], small_row["t_mm"],
                                 small_row["eps_f"]]])
                x_l = np.log10([[large_row["L_mm"], large_row["t_mm"],
                                 large_row["eps_f"]]])
                z_small_list.append(
                    (x_s - norm["x_log_mean"]) / norm["x_log_std"])
                z_large_list.append(
                    (x_l - norm["x_log_mean"]) / norm["x_log_std"])

    if z_small_list:
        pts["z_mono_small"] = torch.tensor(
            np.concatenate(z_small_list, axis=0), dtype=torch.float32)
        pts["z_mono_large"] = torch.tensor(
            np.concatenate(z_large_list, axis=0), dtype=torch.float32)

    # ---- 2. Boundary floor points ----
    # For each L in training set, the boundary is t=0.5 (max training t).
    # Virtual points at t=0.55, 0.60, 0.65 should have c_F >= c_F(t=0.5).
    t_boundary = max(t_vals)  # typically 0.5
    t_extra = [t_boundary + dt for dt in (0.05, 0.10, 0.15)]
    z_bnd_list = []
    z_anchor_list = []
    for L in L_vals:
        # Anchor: (L, t_boundary)
        row_bnd = ref[(ref["L_mm"] == L) & (ref["t_mm"] == t_boundary)]
        if row_bnd.empty:
            continue
        eps_f_bnd = float(row_bnd.iloc[0]["eps_f"])
        x_anc = np.log10([[L, t_boundary, eps_f_bnd]])
        z_anc = (x_anc - norm["x_log_mean"]) / norm["x_log_std"]

        for t_v in t_extra:
            g = tpms_geometry(TPMS, L, t_v, _KS)
            eps_f_v = g["epsilon"] / 2.0
            if eps_f_v < 0.01:
                continue  # geometry closes up, skip
            x_v = np.log10([[L, t_v, eps_f_v]])
            z_v = (x_v - norm["x_log_mean"]) / norm["x_log_std"]
            z_bnd_list.append(z_v)
            z_anchor_list.append(z_anc)

    if z_bnd_list:
        pts["z_bnd_virtual"] = torch.tensor(
            np.concatenate(z_bnd_list, axis=0), dtype=torch.float32)
        pts["z_bnd_anchor"] = torch.tensor(
            np.concatenate(z_anchor_list, axis=0), dtype=torch.float32)

    # ---- 3. Asymptotic points ----
    # Virtual points with very low eps_f -> c_F should be large.
    # Use (L, t) from training set but artificially reduce eps_f.
    z_asym_list = []
    for L in L_vals:
        for t in t_vals:
            row = ref[(ref["L_mm"] == L) & (ref["t_mm"] == t)]
            if row.empty:
                continue
            eps_f_real = float(row.iloc[0]["eps_f"])
            # Push eps_f down to 30% of real value
            eps_f_low = max(eps_f_real * 0.3, 0.02)
            x_a = np.log10([[L, t, eps_f_low]])
            z_a = (x_a - norm["x_log_mean"]) / norm["x_log_std"]
            z_asym_list.append(z_a)

    if z_asym_list:
        pts["z_asym"] = torch.tensor(
            np.concatenate(z_asym_list, axis=0), dtype=torch.float32)
        # Target: c_F should be at least 2× the training max
        cF_max = ref["c_F"].max()
        pts["cF_asym_floor"] = float(cF_max * 2.0)

    return pts


# ==================================================================
# Constraint losses
# ==================================================================

def _loss_monotone(model, pts, ym, ys):
    """c_F(small D_h) > c_F(large D_h) — hinge loss."""
    if "z_mono_small" not in pts:
        return torch.tensor(0.0)
    _, cF_s = _forward_K_cF(model, pts["z_mono_small"], ym, ys)
    _, cF_l = _forward_K_cF(model, pts["z_mono_large"], ym, ys)
    # Penalize when cF_small < cF_large (violation)
    margin = 0.1 * (cF_s + cF_l)  # relative margin
    violation = torch.clamp(cF_l - cF_s + margin, min=0.0)
    return torch.mean(violation ** 2 / (cF_s.detach() ** 2 + 1e-6))


def _loss_boundary(model, pts, ym, ys):
    """c_F(t>0.5) >= c_F(t=0.5) — hinge loss."""
    if "z_bnd_virtual" not in pts:
        return torch.tensor(0.0)
    _, cF_virt = _forward_K_cF(model, pts["z_bnd_virtual"], ym, ys)
    _, cF_anc = _forward_K_cF(model, pts["z_bnd_anchor"], ym, ys)
    # Penalize when c_F at virtual point < c_F at boundary
    violation = torch.clamp(cF_anc - cF_virt, min=0.0)
    return torch.mean(violation ** 2 / (cF_anc.detach() ** 2 + 1e-6))


def _loss_asymptote(model, pts, ym, ys):
    """c_F at low eps_f should be large."""
    if "z_asym" not in pts:
        return torch.tensor(0.0)
    _, cF_a = _forward_K_cF(model, pts["z_asym"], ym, ys)
    floor = pts["cF_asym_floor"]
    shortfall = torch.clamp(floor - cF_a, min=0.0)
    return torch.mean(shortfall ** 2 / (floor ** 2 + 1e-6))


# ==================================================================
# Constrained training
# ==================================================================

def _train_constrained(rows: pd.DataFrame, norm: dict,
                       constraint_pts: dict,
                       lam1: float = LAM1, lam2: float = LAM2,
                       lam3: float = LAM3, seed: int = SEED,
                       ) -> DFMLP:
    torch.manual_seed(seed)
    np.random.seed(seed)
    data = _rows_to_tensors(rows, norm)
    ym = torch.tensor(norm["y_log_mean"], dtype=torch.float32)
    ys = torch.tensor(norm["y_log_std"], dtype=torch.float32)

    model = DFMLP()
    opt = Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(
        opt, "min", factor=0.5, patience=PATIENCE // 4, min_lr=1e-6)

    best_loss, best_sd, wait = float("inf"), None, 0
    for ep in range(EPOCHS):
        model.train()
        opt.zero_grad()

        # Data loss (same as v1)
        K, cF = _forward_K_cF(model, data["z"], ym, ys)
        dP_p = (data["mu"] * data["u"] / K
                + data["rho"] * cF * data["u"] ** 2) * data["L_ch"]
        L_data = torch.mean(((dP_p - data["dP"]) / data["dP"]) ** 2)

        # Constraint losses
        L_mono = _loss_monotone(model, constraint_pts, ym, ys)
        L_bnd = _loss_boundary(model, constraint_pts, ym, ys)
        L_asym = _loss_asymptote(model, constraint_pts, ym, ys)

        loss = L_data + lam1 * L_mono + lam2 * L_bnd + lam3 * L_asym
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP)
        opt.step()

        lv = float(loss.item())
        sched.step(lv)
        if lv < best_loss - 1e-8:
            best_loss = lv
            best_sd = {k: v.clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= PATIENCE:
                break

    if best_sd is not None:
        model.load_state_dict(best_sd)
    model.eval()
    return model


def _train_ensemble_c(rows, norm, cpts, lam1=LAM1, lam2=LAM2, lam3=LAM3,
                      base_seed=SEED):
    return [_train_constrained(rows, norm, cpts, lam1, lam2, lam3,
                               seed=base_seed + k * 101)
            for k in range(N_ENSEMBLE)]


# ==================================================================
# eval_arms-compatible callables
# ==================================================================

def make_arm3(df_all: pd.DataFrame | None = None, tpms: str = "Gyroid",
              lam1: float = LAM1, lam2: float = LAM2, lam3: float = LAM3,
              ) -> tuple[TrainPredictFn, PredictFn]:
    if df_all is None:
        df_all = load_all()
    sub = df_all[df_all["tpms"] == tpms].reset_index(drop=True)

    # Full-data training
    ref_full = _per_geom_reference(sub)
    norm_full = _norm_from_ref(ref_full)
    cpts_full = _make_constraint_points(ref_full, norm_full)
    models_full = _train_ensemble_c(sub, norm_full, cpts_full,
                                    lam1, lam2, lam3, base_seed=SEED)
    print(f"  [Arm 3] lam=({lam1},{lam2},{lam3}), "
          f"mono_pairs={cpts_full.get('z_mono_small', torch.empty(0)).shape[0]}, "
          f"bnd_pts={cpts_full.get('z_bnd_virtual', torch.empty(0)).shape[0]}, "
          f"asym_pts={cpts_full.get('z_asym', torch.empty(0)).shape[0]}")

    def train_predict(train_df: pd.DataFrame,
                      L_mm: float, t_mm: float, eps_f: float,
                      ) -> tuple[float, float]:
        ref = _per_geom_reference(train_df)
        norm = _norm_from_ref(ref)
        cpts = _make_constraint_points(ref, norm)
        models = _train_ensemble_c(train_df, norm, cpts,
                                   lam1, lam2, lam3, base_seed=SEED)
        K_arr, cF_arr = _predict_KcF_vec(
            models, norm,
            np.array([L_mm]), np.array([t_mm]), np.array([eps_f]))
        return float(K_arr[0]), float(cF_arr[0])

    def predict(L_mm: float, t_mm: float, eps_f: float,
                ) -> tuple[float, float]:
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
    df_all = load_all()

    tp, pred = make_arm3(df_all)
    r = evaluate_arm("Arm 3: Physics-constrained MLP", tp, pred,
                     df_all=df_all, skip_shanghai=skip_sh)
    compare_arms([r])


if __name__ == "__main__":
    main()
