"""
eval_arms.py — Unified 3-metric evaluation framework for ConstDF-v2
candidate arms.

Metrics
-------
1. **LOO Gyroid DP MAPE** — leave-one-geometry-out (12 folds)
2. **Shanghai 16-case RMSRE** — full non-isothermal SIMPLE coupling
3. **c_F(t) trend** — L=7, t=0.3->0.7 sweep

Interface
---------
Each candidate arm provides two callables:

    train_predict_fn(train_df, L_mm, t_mm, eps_f) -> (K, c_F)
        Train on a data subset, predict one held-out geometry.
        train_df: output of load_all() filtered to training geometries.

    predict_fn(L_mm, t_mm, eps_f) -> (K, c_F)
        Predict using a model already trained on all data.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

_THIS = Path(__file__).resolve()
_DF_FIT = _THIS.parent
_PROJECT_ROOT = _DF_FIT.parent
_PROJECT = _PROJECT_ROOT.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from .load_data import load_all  # noqa: E402
from .fit_df_per_geom import K_S_CELLS, _wls_momentum, _nnls_momentum  # noqa: E402

from solvers.tpms_calc import (  # noqa: E402
    geometry as tpms_geometry,
    compute as tpms_compute,
    air_density, air_viscosity, air_conductivity, air_cp,
    P_atm, adaptive_grid, Pr, Sa_mm,
)
from solvers.simple_solver import SIMPLESolver  # noqa: E402
from solvers.solve_full import solve_full_domain  # noqa: E402

# Type aliases
TrainPredictFn = Callable[[pd.DataFrame, float, float, float],
                           tuple[float, float]]
PredictFn = Callable[[float, float, float], tuple[float, float]]

# Constants
R_AIR = 287.05
MAX_OUTER = 8
OUTER_TOL = 0.5
ALPHA_T = 0.6

# Shanghai geometry
SH_TPMS = "Gyroid"
SH_L = 7.0
SH_T = 0.6
SH_KS = 16.0

FIG_DIR = _PROJECT / "reports" / "figs" / "arms"


# ==================================================================
# Shared helper
# ==================================================================

def per_geom_reference(df: pd.DataFrame) -> pd.DataFrame:
    """Per-geometry 2-param WLS (K, c_F) with geometry columns."""
    recs: list[dict] = []
    for (tpms, L, t), g in df.groupby(["tpms", "L_mm", "t_mm"]):
        u = g["u_mps"].to_numpy(dtype=float)
        dP = g["dP_Pa"].to_numpy(dtype=float)
        mu = g["mu"].to_numpy(dtype=float)
        rho = g["rho"].to_numpy(dtype=float)
        L_ch = K_S_CELLS * float(L) * 1e-3
        inv_K, cF = _wls_momentum(u, dP, mu, rho, L_ch)
        if inv_K < 0.0 or cF < 0.0:
            inv_K, cF = _nnls_momentum(u, dP, mu, rho, L_ch)
        K = 1.0 / max(inv_K, 1e-30)
        recs.append({
            "tpms": tpms, "L_mm": float(L), "t_mm": float(t),
            "eps_f": float(g["eps_f"].iloc[0]),
            "r_h_m": float(g["r_h_m"].iloc[0]),
            "K": K, "c_F": cF,
        })
    return pd.DataFrame(recs)


# ==================================================================
# 1. LOO Gyroid
# ==================================================================

def eval_loo_gyroid(train_predict_fn: TrainPredictFn,
                    df_all: pd.DataFrame | None = None,
                    ) -> tuple[float, pd.DataFrame]:
    """Leave-one-geometry-out on Gyroid 12 geometries.

    Returns (mean_MAPE%, per_geometry_df).
    """
    if df_all is None:
        df_all = load_all()
    sub = df_all[df_all["tpms"] == "Gyroid"].reset_index(drop=True)
    ref = per_geom_reference(sub).sort_values(
        ["L_mm", "t_mm"]).reset_index(drop=True)

    rows: list[dict] = []
    for idx in range(len(ref)):
        r = ref.iloc[idx]
        L_out, t_out = float(r["L_mm"]), float(r["t_mm"])
        eps_f_out = float(r["eps_f"])

        mask_out = (sub["L_mm"] == L_out) & (sub["t_mm"] == t_out)
        train_rows = sub[~mask_out].reset_index(drop=True)
        test_rows = sub[mask_out].reset_index(drop=True)

        K_pred, cF_pred = train_predict_fn(train_rows, L_out, t_out, eps_f_out)

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
        print(f"  LOO {idx + 1}/{len(ref)}: L={L_out:.0f} t={t_out:.1f} "
              f"K={K_pred:.3e} cF={cF_pred:.1f} -> MAPE={dP_mape:.1f}%")

    loo_df = pd.DataFrame(rows)
    mape = float(loo_df["dP_MAPE"].mean())
    return mape, loo_df


# ==================================================================
# 2. Shanghai 16-case RMSRE
# ==================================================================

_SH_CACHE: dict | None = None


def _load_shanghai() -> dict:
    """Lazy-load Shanghai 16-case infrastructure."""
    global _SH_CACHE
    if _SH_CACHE is not None:
        return _SH_CACHE

    g = tpms_geometry(SH_TPMS, SH_L, SH_T, SH_KS)
    EPS, D_H, A0 = g["epsilon"], g["D_h"], g["A_0"]
    R_H = D_H / 2
    L_DOM, H_DOM = 0.231, 0.042
    A_FLOW = 36 * 18.0565e-6
    N_X, N_Y = adaptive_grid(L_DOM, H_DOM, D_H, alpha=0.2)

    DATA = (_PROJECT / "data" / "raw_data"
            / "20260401-上海电气天然气加热器实验工况.xlsx")
    raw = pd.read_excel(str(DATA), engine="openpyxl",
                        sheet_name="Sheet1", header=None, skiprows=2)

    cases: list[dict] = []
    for ci in range(16):
        m_air = float(raw.iloc[ci, 5])
        T_Ain_K = float(raw.iloc[ci, 28]) + 273.15
        P_Ain = P_atm + float(raw.iloc[ci, 30])
        T_Bin_K = float(raw.iloc[ci, 24]) + 273.15
        T_Bout_K = float(raw.iloc[ci, 25]) + 273.15
        dP_exp = float(raw.iloc[ci, 30]) - float(raw.iloc[ci, 31])

        rho_A = air_density(T_Ain_K, P_Ain)
        mu_A = air_viscosity(T_Ain_K)
        k_A = air_conductivity(T_Ain_K)
        cp_A = air_cp(T_Ain_K)
        u_A = m_air / (rho_A * A_FLOW)

        eps_f = EPS / 2.0
        K_ffA = eps_f * k_A
        K_ffB = eps_f * air_conductivity(T_Bin_K)
        K_ss = (1.0 - EPS) * SH_KS
        r_A = tpms_compute(SH_TPMS, SH_L, SH_T, u_A, T_Ain_K, P_Ain, SH_KS)
        h_vA_scalar = A0 * r_A["H_sf"]

        y_c = (np.arange(N_Y) + 0.5) * (H_DOM / N_Y)
        Tb_1d = T_Bout_K + (T_Bin_K - T_Bout_K) * (y_c / H_DOM)
        Tb_pre = np.broadcast_to(Tb_1d[None, :], (N_X, N_Y)).copy()

        cases.append(dict(
            ci=ci, m_air=m_air, T_Ain_K=T_Ain_K, P_Ain=P_Ain,
            rho_A=rho_A, mu_A=mu_A, u_A=u_A,
            K_ffA=K_ffA, K_ffB=K_ffB, K_ss=K_ss,
            h_vA_scalar=h_vA_scalar, h_vB=1.0e10,
            rho_cp_A=rho_A * cp_A, rho_cp_B=999.84 * 4182.0,
            T_Bin_K=T_Bin_K, Tb_pre=Tb_pre, dP_exp=dP_exp,
        ))

    _SH_CACHE = dict(
        cases=cases, EPS=EPS, D_H=D_H, A0=A0, R_H=R_H,
        L_DOM=L_DOM, H_DOM=H_DOM, N_X=N_X, N_Y=N_Y, A_FLOW=A_FLOW,
    )
    return _SH_CACHE


def _sh_h_vA_field(Ta, ucA, sA, sh):
    """Local h_vA from (T, v, P) fields — Gyroid Nu correlation."""
    P_abs = np.ascontiguousarray(
        (sA.P_ref_abs + sA.P).T, dtype=np.float64)
    rho = P_abs / (R_AIR * Ta)
    mu = air_viscosity(Ta)
    k = air_conductivity(Ta)
    Re = np.clip(rho * np.abs(ucA) * sh["D_H"] / mu, 1.0, None)
    n = 0.177 * Re ** 0.1 * sh["EPS"] ** (-2.0 / 3.0)
    Nu = (0.17 * Pr ** (1.0 / 3.0) * Re ** n
          * sh["EPS"] ** 2.25 * (SH_L / (1000.0 * Sa_mm)) ** (-2.01))
    return sh["A0"] * Nu * k / sh["D_H"]


def _run_one_shanghai(c: dict, K_val: float, cF_val: float,
                      sh: dict) -> float:
    """Full non-isothermal SIMPLE for one Shanghai case. Returns dP_sim."""
    L_DOM, H_DOM = sh["L_DOM"], sh["H_DOM"]
    N_X, N_Y = sh["N_X"], sh["N_Y"]
    A_FLOW = sh["A_FLOW"]

    G = c["m_air"] / A_FLOW
    C_est = c["mu_A"] * G / K_val + cF_val * G ** 2
    P_out_sq = c["P_Ain"] ** 2 - 2.0 * R_AIR * c["T_Ain_K"] * C_est * L_DOM
    P_out_est = float(np.sqrt(max(P_out_sq, 1.0e4)))

    sA = SIMPLESolver(
        H_DOM, L_DOM, N_Y, N_X, SH_TPMS, SH_L, SH_T,
        sh["EPS"], sh["R_H"], c["rho_A"], c["mu_A"], c["T_Ain_K"],
        0.0, H_DOM, c["u_A"], outlet_lo=0.0, outlet_hi=H_DOM,
        P_ref_abs=P_out_est,
    )
    sA._K_arr[:] = K_val
    sA._cF_arr[:] = cF_val
    sA.solve(max_iter=3000, tol=1e-4, verbose=False)

    vcA = np.zeros((N_X, N_Y))
    ucB = np.zeros((N_X, N_Y))
    vcB = np.zeros((N_X, N_Y))
    Ta = None
    Ta_prev = None
    h_vA = c["h_vA_scalar"]

    for outer in range(MAX_OUTER):
        v_cell = 0.5 * (sA.v[:, :-1] + sA.v[:, 1:])
        ucA = np.ascontiguousarray(v_cell.T, dtype=np.float64)
        if Ta is not None:
            h_vA = _sh_h_vA_field(Ta, ucA, sA, sh)
        Ta, Tb, Ts, info = solve_full_domain(
            L_DOM, H_DOM, N_X, N_Y,
            c["T_Ain_K"], c["T_Bin_K"],
            c["K_ffA"], c["K_ffB"], c["K_ss"],
            h_vA, c["h_vB"],
            c["rho_cp_A"], c["rho_cp_B"], sh["EPS"],
            ucA, vcA, ucB, vcB,
            dir_A=0, dir_B=3, Tb_prescribed=c["Tb_pre"],
            max_iter=50000, tol=1e-6, return_info=True,
        )
        if Ta_prev is not None and float(np.abs(Ta - Ta_prev).max()) < OUTER_TOL:
            break
        Ta_prev = Ta.copy()
        T_new = np.ascontiguousarray(Ta.T, dtype=np.float64)
        if outer > 0:
            T_new = ALPHA_T * T_new + (1.0 - ALPHA_T) * sA.T_field
        sA.update_T_field(T_new)
        T_avg = float(sA.T_field.mean())
        mu_avg = air_viscosity(T_avg)
        C_avg = mu_avg * G / K_val + cF_val * G ** 2
        sA.P_ref_abs = float(np.sqrt(max(
            c["P_Ain"] ** 2 - 2 * R_AIR * T_avg * C_avg * L_DOM, 1e4)))
        sA.solve(max_iter=3000, tol=1e-4, verbose=False)

    wA_in = sA.inlet_frac
    wA_out = sA.outlet_frac
    mA_in = wA_in > 0.01
    mA_out = wA_out > 0.5
    return float(
        np.average(sA.P[mA_in, 0], weights=wA_in[mA_in])
        - np.average(sA.P[mA_out, -1], weights=wA_out[mA_out])
    )


def eval_shanghai(K: float, cF: float) -> tuple[float, list[dict]]:
    """Run all 16 Shanghai cases. Returns (RMSRE%, per_case_list)."""
    sh = _load_shanghai()
    results: list[dict] = []
    err_sq_sum = 0.0
    for i, c in enumerate(sh["cases"]):
        try:
            dP_sim = _run_one_shanghai(c, K, cF, sh)
            rel = (dP_sim - c["dP_exp"]) / c["dP_exp"]
            err_sq_sum += rel ** 2
            results.append(dict(case=i + 1, dP_exp=c["dP_exp"],
                                dP_sim=dP_sim, err_pct=rel * 100))
        except Exception as e:
            err_sq_sum += 1.0
            results.append(dict(case=i + 1, dP_exp=c["dP_exp"],
                                dP_sim=0.0, err_pct=100.0, error=str(e)))
        r = results[-1]
        print(f"  SH {i + 1:2d}/16: exp={c['dP_exp']:8.0f}  "
              f"sim={r['dP_sim']:8.0f}  err={r['err_pct']:+6.1f}%")
    rmsre = float(np.sqrt(err_sq_sum / 16) * 100)
    return rmsre, results


# ==================================================================
# 3. c_F(t) trend
# ==================================================================

def eval_cF_trend(predict_fn: PredictFn, L_mm: float = 7.0,
                  t_lo: float = 0.3, t_hi: float = 0.7, n_pts: int = 50,
                  ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sweep t for fixed L. Returns (t_arr, K_arr, cF_arr)."""
    t_arr = np.linspace(t_lo, t_hi, n_pts)
    K_arr = np.empty(n_pts)
    cF_arr = np.empty(n_pts)
    for i, t in enumerate(t_arr):
        g = tpms_geometry(SH_TPMS, L_mm, float(t), SH_KS)
        eps_f = g["epsilon"] / 2.0
        K_arr[i], cF_arr[i] = predict_fn(L_mm, float(t), eps_f)
    return t_arr, K_arr, cF_arr


# ==================================================================
# Full arm evaluation
# ==================================================================

def evaluate_arm(name: str,
                 train_predict_fn: TrainPredictFn,
                 predict_fn: PredictFn,
                 df_all: pd.DataFrame | None = None,
                 skip_shanghai: bool = False,
                 ) -> dict:
    """Run all 3 metrics for one arm. Returns result dict."""
    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")

    if df_all is None:
        df_all = load_all()

    # 1. LOO
    print("\n[1/3] LOO Gyroid")
    loo_mape, loo_df = eval_loo_gyroid(train_predict_fn, df_all)
    print(f"  >> LOO MAPE = {loo_mape:.2f}%")

    # 2. Shanghai
    rmsre = float("nan")
    sh_results: list[dict] = []
    K_sh = cF_sh = float("nan")
    if not skip_shanghai:
        print("\n[2/3] Shanghai 16-case")
        g = tpms_geometry(SH_TPMS, SH_L, SH_T, SH_KS)
        K_sh, cF_sh = predict_fn(SH_L, SH_T, g["epsilon"] / 2.0)
        print(f"  K={K_sh:.4e}  c_F={cF_sh:.2f}")
        rmsre, sh_results = eval_shanghai(K_sh, cF_sh)
        print(f"  >> Shanghai RMSRE = {rmsre:.2f}%")
    else:
        print("\n[2/3] Shanghai -- skipped")

    # 3. Trend
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


def compare_arms(results: list[dict], out_dir: Path | None = None) -> None:
    """Print comparison table and save c_F trend figure."""
    if out_dir is None:
        out_dir = FIG_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- Summary table ----
    print(f"\n{'=' * 72}")
    hdr = f"{'Arm':<30} {'LOO MAPE%':>10} {'SH RMSRE%':>10} {'c_F range':>16}"
    print(hdr)
    print(f"{'-' * 30} {'-' * 10} {'-' * 10} {'-' * 16}")
    print(f"{'ConstDF-v1 (baseline)':<30} {'16.95':>10} {'81.7':>10} "
          f"{'43 -> 54':>16}")
    for r in results:
        cf_lo = r["cF_trend"].min()
        cf_hi = r["cF_trend"].max()
        sh = (f"{r['shanghai_rmsre']:.1f}"
              if not np.isnan(r["shanghai_rmsre"]) else "--")
        print(f"{r['name']:<30} {r['loo_mape']:>10.2f} {sh:>10} "
              f"{cf_lo:>7.0f} -> {cf_hi:.0f}")
    print(f"{'=' * 72}")

    # ---- c_F trend figure ----
    fig, ax = plt.subplots(figsize=(8, 5), dpi=120)
    for r in results:
        ax.plot(r["t_arr"], r["cF_trend"], lw=1.5, label=r["name"])
    ax.axvline(0.5, ls=":", color="gray", alpha=0.6,
               label="training boundary (t=0.5)")
    ax.set_xlabel("t [mm]")
    ax.set_ylabel(r"$c_F$ [1/m]")
    ax.set_title(r"$c_F(t)$ trend — L=7 mm, Gyroid")
    ax.legend(fontsize=8)
    ax.grid(True, ls=":", alpha=0.4)
    fig.tight_layout()
    path = out_dir / "cF_trend_comparison.png"
    fig.savefig(path)
    plt.close(fig)
    print(f"Saved: {path}")


# ==================================================================
# Convenience: ConstDF-v1 baseline callables
# ==================================================================

def make_v1_baseline() -> tuple[TrainPredictFn, PredictFn]:
    """Return (train_predict_fn, predict_fn) for ConstDF-v1 MLP baseline."""
    from .train_surrogate import (
        _per_geom_reference, _norm_from_ref, _train_ensemble,
        _predict_KcF_vec, SEED,
    )
    from .predict import predict_K_cF as _v1_predict

    def train_predict(train_df: pd.DataFrame,
                      L_mm: float, t_mm: float, eps_f: float,
                      ) -> tuple[float, float]:
        ref = _per_geom_reference(train_df)
        norm = _norm_from_ref(ref)
        models, _ = _train_ensemble(train_df, norm, base_seed=SEED)
        K_arr, cF_arr = _predict_KcF_vec(
            models, norm,
            np.array([L_mm]), np.array([t_mm]), np.array([eps_f]),
        )
        return float(K_arr[0]), float(cF_arr[0])

    def predict(L_mm: float, t_mm: float, eps_f: float,
                ) -> tuple[float, float]:
        return _v1_predict("Gyroid", L_mm, t_mm, eps_f)

    return train_predict, predict


# ==================================================================
# CLI entry point
# ==================================================================

def main() -> None:
    """Evaluate ConstDF-v1 baseline as a smoke test of the framework."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    warnings.filterwarnings("ignore")

    skip_sh = "--skip-shanghai" in sys.argv

    train_fn, pred_fn = make_v1_baseline()
    result = evaluate_arm("ConstDF-v1 (baseline)", train_fn, pred_fn,
                          skip_shanghai=skip_sh)
    compare_arms([result])


if __name__ == "__main__":
    main()
