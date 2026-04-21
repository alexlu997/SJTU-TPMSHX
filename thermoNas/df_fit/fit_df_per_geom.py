"""
Step 2: direct per-geometry Darcy-Forchheimer extraction from raw CFD
pressure-loss data. Friction factor is deliberately NOT involved.

Physical model
--------------
The Darcy-Forchheimer momentum equation for incompressible flow through
a homogenised porous section of length ``L_ch`` is

    ΔP = ( μ·u / K  +  ρ·c_F·u² ) · L_ch                               (1)

We fit (1) row-by-row on the per-geometry (u, ΔP) samples from the
training Excel, with μ and ρ taken per-row to respect the temperature
dependence of air properties. K [m²] and c_F [1/m] are the two fit
parameters.

Channel length
--------------
The training CFD stacks ``K_S_CELLS`` = 10 unit cells along the flow
direction (user-confirmed), so

    L_ch = K_S_CELLS · L_cell_m                                        (2)

K and c_F extracted here are in SI units and stay valid when the
surrogate is used in any downstream solver with any channel length,
because K, c_F are *intrinsic* porous-media properties (like resistivity,
not total resistance).

Loss function
-------------
Weighted least squares with w_i = 1/ΔP_i², which turns the loss into

    minimise Σ ( (ΔP_pred,i − ΔP_obs,i) / ΔP_obs,i )²

i.e. the mean squared relative ΔP error. Low-Re and high-Re points
contribute equally regardless of the Re range covered by each geometry.

NNLS fallback
-------------
Both parameters are physically non-negative. If plain WLS drives 1/K or
c_F negative (noisy high-Re-only data with a tiny Darcy contribution),
the fit is redone with scipy.optimize.nnls which clamps both coefficients
to ≥ 0.

3-parameter note
----------------
An earlier experiment added a transitional γ·√(μρ)·u^(3/2) term on top
of the two D-F terms, either jointly or sequentially on the 2-term
residual. Both variants were discarded:
  - Joint fit was ill-conditioned because u^(3/2) is near-collinear with
    (u, u²) on the 600–16000 Re span, collapsing K and c_F to zero.
  - Sequential fit preserved physical (K, c_F) but cut MAPE by only
    0.15–0.3 % because the 2-term residual is a non-monotonic "hump"
    shape (peaks around Re≈1600), which no u^x power term can absorb.
    The hump is a real feature of the data — it is the laminar/turbulent
    transition "drag crisis" in the TPMS pores — and lies outside the
    D-F closure's descriptive range.

We therefore stay at 2 parameters and treat 10 % per-geometry dP MAPE
as the physical floor on this data.

Output
------
``data/df_fit/per_geom_fits.csv`` with one row per (tpms, L, t) group:

    tpms, L_mm, t_mm, eps, eps_f, r_h_m,
    n_points, Re_min, Re_max,
    L_channel_m,
    K, c_F,
    dP_MAPE, dP_max_err,          # relative errors in ΔP space
    inv_K_unconstrained_negative  # diagnostic flag
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from .load_data import load_all

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent

OUT_CSV = _PROJECT / "data" / "df_fit" / "per_geom_fits.csv"

# CFD domain configuration (user-confirmed): every training geometry stacks
# exactly this many unit cells along the streamwise direction.
K_S_CELLS = 10


def _wls_momentum(u: np.ndarray, dP: np.ndarray,
                   mu: np.ndarray, rho: np.ndarray,
                   L_ch: float) -> tuple[float, float]:
    """Weighted least squares solution to ΔP = (μu/K + ρc_Fu²)·L_ch.

    Weights w_i = 1/ΔP_i² make the objective equal to the mean squared
    relative ΔP error, so low-Re and high-Re points contribute equally.
    """
    X1 = mu * L_ch * u          # basis for 1/K
    X2 = rho * L_ch * u ** 2    # basis for c_F
    X = np.column_stack([X1, X2])
    w = 1.0 / dP
    Xw = X * w[:, None]
    yw = dP * w  # == 1 identically, but keep explicit for clarity
    coef, *_ = np.linalg.lstsq(Xw, yw, rcond=None)
    return float(coef[0]), float(coef[1])


def _nnls_momentum(u: np.ndarray, dP: np.ndarray,
                    mu: np.ndarray, rho: np.ndarray,
                    L_ch: float) -> tuple[float, float]:
    """Non-negative least squares fallback — same system, w=1/ΔP weighting."""
    X1 = mu * L_ch * u
    X2 = rho * L_ch * u ** 2
    X = np.column_stack([X1, X2])
    w = 1.0 / dP
    Xw = X * w[:, None]
    yw = dP * w
    coef, _ = nnls(Xw, yw)
    return float(coef[0]), float(coef[1])


def _residual_stats(u: np.ndarray, dP: np.ndarray, mu: np.ndarray,
                     rho: np.ndarray, L_ch: float,
                     inv_K: float, c_F: float) -> tuple[float, float]:
    """Return (MAPE%, max_err%) in physical ΔP space."""
    dP_pred = (inv_K * mu * u + c_F * rho * u ** 2) * L_ch
    rel = np.abs(dP_pred - dP) / np.maximum(np.abs(dP), 1e-12)
    return float(rel.mean() * 100.0), float(rel.max() * 100.0)


def _fit_group(g: pd.DataFrame) -> dict:
    u = g["u_mps"].to_numpy(dtype=float)
    dP = g["dP_Pa"].to_numpy(dtype=float)
    mu = g["mu"].to_numpy(dtype=float)
    rho = g["rho"].to_numpy(dtype=float)
    r_h = float(g["r_h_m"].iloc[0])
    L_mm = float(g["L_mm"].iloc[0])
    L_ch = K_S_CELLS * L_mm * 1e-3

    inv_K_raw, c_F_raw = _wls_momentum(u, dP, mu, rho, L_ch)
    neg_flag = inv_K_raw < 0.0 or c_F_raw < 0.0
    if neg_flag:
        inv_K, c_F = _nnls_momentum(u, dP, mu, rho, L_ch)
    else:
        inv_K, c_F = inv_K_raw, c_F_raw

    mape, max_err = _residual_stats(u, dP, mu, rho, L_ch, inv_K, c_F)
    mape_raw, _ = _residual_stats(u, dP, mu, rho, L_ch, inv_K_raw, c_F_raw)

    K = 1.0 / inv_K if inv_K > 1e-30 else float("nan")

    return {
        "tpms": g["tpms"].iloc[0],
        "L_mm": L_mm,
        "t_mm": float(g["t_mm"].iloc[0]),
        "eps": float(g["eps"].iloc[0]),
        "eps_f": float(g["eps_f"].iloc[0]),
        "r_h_m": r_h,
        "n_points": int(len(g)),
        "Re_min": float(g["Re"].min()),
        "Re_max": float(g["Re"].max()),
        "L_channel_m": L_ch,
        "K": K,
        "c_F": c_F,
        "dP_MAPE": mape_raw,                  # headline = unconstrained residual
        "dP_MAPE_phys": mape,                 # residual after NNLS if triggered
        "dP_max_err": max_err,
        "inv_K_unconstrained_negative": bool(neg_flag),
    }


def fit_all() -> pd.DataFrame:
    df = load_all()
    records: list[dict] = []
    for _, group in df.groupby(["tpms", "L_mm", "t_mm"], sort=False):
        records.append(_fit_group(group))
    out = pd.DataFrame.from_records(records)
    return out.sort_values(["tpms", "L_mm", "t_mm"]).reset_index(drop=True)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    fits = fit_all()
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fits.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV.relative_to(_PROJECT)} ({len(fits)} rows)")
    print(f"L_channel convention: {K_S_CELLS} × L_cell")
    print()

    cols = ["tpms", "L_mm", "t_mm", "n_points", "Re_min", "Re_max",
            "L_channel_m", "K", "c_F", "dP_MAPE", "dP_max_err",
            "inv_K_unconstrained_negative"]
    with pd.option_context("display.width", 150, "display.max_columns", None,
                            "display.float_format", lambda v: f"{v:.4g}"):
        print(fits[cols].to_string(index=False))

    print()
    print("Summary by tpms:")
    print(fits.groupby("tpms")[["dP_MAPE", "dP_max_err"]].agg(["mean", "max"]))

    n_bad = int(fits["inv_K_unconstrained_negative"].sum())
    print(f"\nGeometries with 1/K or c_F < 0 before NNLS: {n_bad}")
    if n_bad:
        bad = fits[fits["inv_K_unconstrained_negative"]][
            ["tpms", "L_mm", "t_mm", "K", "c_F", "dP_MAPE"]
        ]
        print(bad.to_string(index=False))


if __name__ == "__main__":
    main()
