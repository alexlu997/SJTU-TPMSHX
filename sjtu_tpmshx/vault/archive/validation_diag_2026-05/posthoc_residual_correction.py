"""posthoc_residual_correction.py — Apply ResidualCorrector to existing
Shanghai validation results.

Reads `shanghai_validation_aligned.xlsx` (baseline 2D validation), looks up
each case's Re/eps_f, multiplies dP_sim by (1 + g(Re, eps_f)), recomputes
err_dP and RMSRE_dP. Q is unaffected.

This is a quick test of corrector value WITHOUT re-running SIMPLE 2D.
True effectiveness depends on whether the corrector approximates the SIMPLE
solver's dP behavior (it should, since both use the same K, c_F).
"""
from __future__ import annotations

import sys
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import geometry as tpms_geometry  # noqa: E402
from df_fit.residual_correction import get_corrector  # noqa: E402

R_AIR = 287.05

# Shanghai geometry (matches validate_shanghai_aligned.py)
TPMS = "Gyroid"
L_CELL = 7.0
T_WALL = 0.6


def main():
    in_path = _PROJECT / "data" / "shanghai_validation_aligned.xlsx"
    df = pd.read_excel(in_path, engine="openpyxl")

    # Geometry once
    geom = tpms_geometry(TPMS, L_CELL, T_WALL, 16.0)
    D_h = float(geom["D_h"])
    eps_f = float(geom["epsilon"]) / 2.0

    # Corrector
    corr = get_corrector(TPMS)

    print(f"=== Post-hoc residual correction on existing Shanghai run ===")
    print(f"  TPMS={TPMS}, L={L_CELL}, t={T_WALL}, eps_f={eps_f:.4f}")
    print(f"  D_h={D_h*1000:.3f}mm")
    print()
    print(f"  Case  Re      g       dP_exp  dP_sim_base  dP_sim_corr  "
          f"err_base%  err_corr%")

    rows_new = []
    for _, row in df.iterrows():
        case = int(row["Case"])
        u_air = float(row["u_air"])
        T_air_in_C = float(row["T_air_in"])
        T_air_in_K = T_air_in_C + 273.15
        P_in_kPa = float(row["P_in_abs_kPa"])
        P_in = P_in_kPa * 1000.0
        dP_exp = float(row["dP_air_exp"])
        dP_sim_base = float(row["dP_air_sim"])

        rho_in = P_in / (R_AIR * T_air_in_K)
        # Air viscosity at T_air_in (Sutherland)
        T_ref = 273.15; mu_ref = 1.716e-5; S = 110.4
        mu = mu_ref * ((T_air_in_K / T_ref) ** 1.5) * (T_ref + S) / (T_air_in_K + S)
        Re = rho_in * u_air * D_h / mu

        g = corr.correction(Re, eps_f)
        dP_sim_corr = dP_sim_base * (1.0 + g)

        err_base = (dP_sim_base - dP_exp) / dP_exp * 100
        err_corr = (dP_sim_corr - dP_exp) / dP_exp * 100

        print(f"  {case:3d}  {Re:6.0f}  {g:+.3f}  {dP_exp:6.0f}  "
              f"{dP_sim_base:11.0f}  {dP_sim_corr:11.0f}  "
              f"{err_base:+8.1f}%  {err_corr:+8.1f}%")
        rows_new.append(dict(Case=case, u_air=u_air, Re=Re, g=g,
                             dP_exp=dP_exp, dP_sim_base=dP_sim_base,
                             dP_sim_corr=dP_sim_corr,
                             err_base=err_base, err_corr=err_corr))

    df_new = pd.DataFrame(rows_new)
    err_b = df_new["err_base"].to_numpy()
    err_c = df_new["err_corr"].to_numpy()

    rmsre_b = float(np.sqrt(np.mean(err_b ** 2)))
    rmsre_c = float(np.sqrt(np.mean(err_c ** 2)))
    bias_b = float(np.mean(err_b))
    bias_c = float(np.mean(err_c))
    maxabs_b = float(np.max(np.abs(err_b)))
    maxabs_c = float(np.max(np.abs(err_c)))

    print()
    print("=" * 70)
    print(f"  Baseline RMSRE_dP:   {rmsre_b:.2f}%   bias: {bias_b:+.2f}%   "
          f"max|err|: {maxabs_b:.1f}%")
    print(f"  Corrected RMSRE_dP:  {rmsre_c:.2f}%   bias: {bias_c:+.2f}%   "
          f"max|err|: {maxabs_c:.1f}%")
    delta_rmsre = rmsre_b - rmsre_c
    print(f"  ΔRMSRE_dP: {delta_rmsre:+.2f}pp "
          f"({'improvement' if delta_rmsre > 0 else 'regression'})")
    print("=" * 70)

    out_path = _PROJECT / "data" / "shanghai_validation_aligned_corrected.csv"
    df_new.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    main()
