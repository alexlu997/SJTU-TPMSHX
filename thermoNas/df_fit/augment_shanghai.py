"""
augment_shanghai.py — Generate synthetic training rows for Shanghai
Gyroid L=7, t=0.6 using reverse-fitted (K, c_F) parameters.

The reverse_fit_KcF.py optimization found:
    K_opt  = 8.26e-8 m²
    c_F_opt = 463.0  1/m
    RMSRE  = 5.5% across 16 experimental cases

Synthetic dP is computed analytically from the D-F equation (not from
experimental dP_exp) to guarantee self-consistency: WLS on these rows
must recover (K_opt, c_F_opt) exactly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import (  # noqa: E402
    geometry as tpms_geometry,
    air_density, air_viscosity, P_atm,
)
from .fit_df_per_geom import K_S_CELLS, _wls_momentum  # noqa: E402
from .load_data import load_all  # noqa: E402

# Reverse-fitted optimal D-F parameters for Shanghai Gyroid L=7, t=0.6
K_OPT = 8.26e-8       # m²
C_F_OPT = 463.0       # 1/m

# Shanghai geometry
SH_TPMS = "Gyroid"
SH_L = 7.0            # mm
SH_T = 0.6            # mm
SH_KS = 16.0

# Prototype flow area (36 parallel unit cells)
A_FLOW = 36 * 18.0565e-6  # m²

# Shanghai Excel
_SH_XLSX = (_PROJECT / "data" / "raw_data"
            / "20260401-上海电气天然气加热器实验工况.xlsx")


def shanghai_synth_rows(K: float = K_OPT,
                        cF: float = C_F_OPT,
                        n_cases: int | None = None,
                        ) -> pd.DataFrame:
    """Generate synthetic training rows for Shanghai geometry.

    Parameters
    ----------
    K, cF : reverse-fitted D-F parameters
    n_cases : how many of the 16 cases to include (None = all 16).
              Subsamples uniformly across the Re range for ablation.

    Returns
    -------
    DataFrame with exact same schema as load_all().
    """
    # Geometry
    g = tpms_geometry(SH_TPMS, SH_L, SH_T, SH_KS)
    eps = g["epsilon"]
    D_h = g["D_h"]
    eps_f = eps / 2.0
    r_h_m = D_h / 2.0

    # Channel length (training convention: K_S_CELLS unit cells)
    L_ch = K_S_CELLS * SH_L * 1e-3  # 0.07 m

    # Read Shanghai Excel for operating conditions
    raw = pd.read_excel(str(_SH_XLSX), engine="openpyxl",
                        sheet_name="Sheet1", header=None, skiprows=2)

    rows: list[dict] = []
    for ci in range(16):
        m_air = float(raw.iloc[ci, 5])
        T_Ain_K = float(raw.iloc[ci, 28]) + 273.15
        P_Ain = P_atm + float(raw.iloc[ci, 30])

        rho_A = air_density(T_Ain_K, P_Ain)
        mu_A = air_viscosity(T_Ain_K)
        u_A = m_air / (rho_A * A_FLOW)
        Re = rho_A * u_A * D_h / mu_A

        # Analytical D-F pressure drop (self-consistent with K, cF)
        dP = (mu_A * u_A / K + rho_A * cF * u_A ** 2) * L_ch

        rows.append({
            "tpms": SH_TPMS,
            "L_mm": SH_L,
            "t_mm": SH_T,
            "eps": eps,
            "eps_f": eps_f,
            "r_h_m": r_h_m,
            "Re": Re,
            "u_mps": u_A,
            "dP_Pa": dP,
            "rho": rho_A,
            "mu": mu_A,
            "label": "SH_7_06",
        })

    df = pd.DataFrame(rows)

    # Subsample if requested (stratified across Re range)
    if n_cases is not None and n_cases < 16:
        idx = np.round(np.linspace(0, 15, n_cases)).astype(int)
        df = df.iloc[idx].reset_index(drop=True)

    return df


def load_augmented(n_cases: int | None = None) -> pd.DataFrame:
    """Return load_all() + Shanghai synthetic rows."""
    base = load_all()
    synth = shanghai_synth_rows(n_cases=n_cases)
    return pd.concat([base, synth], ignore_index=True)


# ==================================================================
# Self-check
# ==================================================================

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    synth = shanghai_synth_rows()
    print(f"Generated {len(synth)} synthetic rows for {SH_TPMS} "
          f"L={SH_L} t={SH_T}")
    print(f"  eps_f = {synth['eps_f'].iloc[0]:.6f}")
    print(f"  r_h_m = {synth['r_h_m'].iloc[0]:.6f} m")
    print(f"  Re range: {synth['Re'].min():.0f} - {synth['Re'].max():.0f}")
    print(f"  u range:  {synth['u_mps'].min():.2f} - "
          f"{synth['u_mps'].max():.2f} m/s")
    print(f"  dP range: {synth['dP_Pa'].min():.0f} - "
          f"{synth['dP_Pa'].max():.0f} Pa")
    print()

    # WLS self-consistency check
    u = synth["u_mps"].to_numpy(dtype=float)
    dP = synth["dP_Pa"].to_numpy(dtype=float)
    mu = synth["mu"].to_numpy(dtype=float)
    rho = synth["rho"].to_numpy(dtype=float)
    L_ch = K_S_CELLS * SH_L * 1e-3

    inv_K, cF_rec = _wls_momentum(u, dP, mu, rho, L_ch)
    K_rec = 1.0 / inv_K

    err_K = abs(K_rec - K_OPT) / K_OPT
    err_cF = abs(cF_rec - C_F_OPT) / C_F_OPT
    print(f"WLS recovery check:")
    print(f"  K_opt = {K_OPT:.4e},  K_rec = {K_rec:.4e},  "
          f"rel_err = {err_K:.2e}")
    print(f"  cF_opt = {C_F_OPT:.2f},  cF_rec = {cF_rec:.2f},  "
          f"rel_err = {err_cF:.2e}")

    if err_K < 1e-6 and err_cF < 1e-6:
        print("  PASS: self-consistent")
    else:
        print("  WARN: WLS recovery mismatch > 1e-6")

    # Compare with training data
    print()
    base = load_all()
    gyr = base[base["tpms"] == "Gyroid"]
    print(f"Training Gyroid: {len(gyr)} rows, "
          f"Re {gyr['Re'].min():.0f}-{gyr['Re'].max():.0f}")
    print(f"Shanghai synth:  {len(synth)} rows, "
          f"Re {synth['Re'].min():.0f}-{synth['Re'].max():.0f}")

    aug = load_augmented()
    n_geoms = aug[aug["tpms"] == "Gyroid"].groupby(
        ["L_mm", "t_mm"]).ngroups
    print(f"Augmented Gyroid: {n_geoms} geometries, "
          f"{len(aug[aug['tpms'] == 'Gyroid'])} rows")


if __name__ == "__main__":
    main()
