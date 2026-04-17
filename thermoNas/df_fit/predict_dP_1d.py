"""
predict_dP_1d.py — 1D compressible Darcy-Forchheimer pressure drop.

Physics:
    Ideal gas in a porous channel with constant mass flux G = rho*u.
    Momentum:  -dP/dx = mu*u/K + rho*c_F*u^2
    With rho = P/(RT) and u = G*R*T/P:
        -P dP = R*T*(mu*G/K + c_F*G^2) dx
    Integrating (isothermal):
        P_in^2 - P_out^2 = 2*R*T*(mu*G/K + c_F*G^2)*L

    When dP/P << 1 this reduces to the incompressible formula:
        dP = (mu*u/K + rho*c_F*u^2)*L
"""
from __future__ import annotations

import sys
from pathlib import Path
from math import sqrt

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_THERMONAS = _THIS.parent.parent
_PROJECT = _THERMONAS.parent

if str(_THERMONAS) not in sys.path:
    sys.path.insert(0, str(_THERMONAS))

from solvers.tpms_calc import air_density, air_viscosity, P_atm  # noqa: E402
from .fit_df_per_geom import K_S_CELLS  # noqa: E402
from .load_data import load_all  # noqa: E402


R_AIR = 287.05  # J/(kg·K)


# ==================================================================
# Core formulas
# ==================================================================

def dP_incompressible(K: float, c_F: float, u: float, rho: float,
                      mu: float, L: float) -> float:
    """Incompressible analytical D-F: dP = (mu*u/K + rho*c_F*u^2)*L."""
    return (mu * u / K + rho * c_F * u ** 2) * L


def dP_1d_compressible(K: float, c_F: float, G: float, T: float,
                       P_in: float, mu: float, L: float) -> float:
    """1D isothermal compressible D-F.

    Parameters
    ----------
    K, c_F : D-F parameters
    G : mass flux rho*u [kg/(m^2·s)], constant along channel
    T : temperature [K] (isothermal or average)
    P_in : inlet absolute pressure [Pa]
    mu : dynamic viscosity [Pa·s]
    L : channel length [m]
    """
    C = mu * G / K + c_F * G ** 2
    P_out_sq = P_in ** 2 - 2.0 * R_AIR * T * C * L
    if P_out_sq <= 0.0:
        return P_in  # fully choked
    return P_in - sqrt(P_out_sq)


# ==================================================================
# Shanghai 16-case evaluation
# ==================================================================

_SH_XLSX = (_PROJECT / "data" / "raw_data"
            / "20260401-上海电气天然气加热器实验工况.xlsx")
A_FLOW = 36 * 18.0565e-6
L_DOM = 0.231


def eval_shanghai_1d(K: float, c_F: float,
                     compressible: bool = True) -> tuple[float, list[dict]]:
    """Evaluate Shanghai 16 cases with 1D D-F formula.

    Returns (RMSRE%, per_case_list).
    """
    raw = pd.read_excel(str(_SH_XLSX), engine="openpyxl",
                        sheet_name="Sheet1", header=None, skiprows=2)
    results = []
    err_sq = 0.0

    for ci in range(16):
        m_air = float(raw.iloc[ci, 5])
        T_Ain_K = float(raw.iloc[ci, 28]) + 273.15
        P_Ain = P_atm + float(raw.iloc[ci, 30])
        dP_exp = float(raw.iloc[ci, 30]) - float(raw.iloc[ci, 31])
        rho_A = air_density(T_Ain_K, P_Ain)
        mu_A = air_viscosity(T_Ain_K)
        u_A = m_air / (rho_A * A_FLOW)
        G = m_air / A_FLOW

        if compressible:
            dP_pred = dP_1d_compressible(K, c_F, G, T_Ain_K, P_Ain,
                                         mu_A, L_DOM)
        else:
            dP_pred = dP_incompressible(K, c_F, u_A, rho_A, mu_A, L_DOM)

        rel = (dP_pred - dP_exp) / dP_exp
        err_sq += rel ** 2
        results.append(dict(case=ci + 1, dP_exp=dP_exp,
                            dP_pred=dP_pred, err_pct=rel * 100))

    rmsre = float(np.sqrt(err_sq / 16) * 100)
    return rmsre, results


# ==================================================================
# Training data validation
# ==================================================================

def validate_training(compressible: bool = True) -> pd.DataFrame:
    """Compare 1D formula dP with CFD dP on training data."""
    df = load_all()
    gyr = df[df["tpms"] == "Gyroid"].reset_index(drop=True)

    rows = []
    for _, r in gyr.iterrows():
        L_ch = K_S_CELLS * r["L_mm"] * 1e-3
        u, mu, rho = r["u_mps"], r["mu"], r["rho"]
        dP_cfd = r["dP_Pa"]

        dP_incomp = dP_incompressible(
            1.0, 1.0, u, rho, mu, L_ch)  # dummy, not used directly

        # For training data: P_in = P_atm (CFD is near-atmospheric)
        # Incompressible
        # We need per-geometry K, c_F — but for this validation we use
        # the WLS-fitted values. Caller should provide them.
        rows.append(dict(
            L_mm=r["L_mm"], t_mm=r["t_mm"], Re=r["Re"],
            u=u, mu=mu, rho=rho, dP_cfd=dP_cfd, L_ch=L_ch,
        ))
    return pd.DataFrame(rows)


# ==================================================================
# Reverse fit using analytical formula (no SIMPLE)
# ==================================================================

def reverse_fit_analytical(compressible: bool = True,
                           ) -> tuple[float, float, float]:
    """Find (K, c_F) that minimize Shanghai dP error using 1D formula.

    Returns (K_opt, c_F_opt, RMSRE%).
    """
    from scipy.optimize import minimize

    raw = pd.read_excel(str(_SH_XLSX), engine="openpyxl",
                        sheet_name="Sheet1", header=None, skiprows=2)

    cases = []
    for ci in range(16):
        m_air = float(raw.iloc[ci, 5])
        T_Ain_K = float(raw.iloc[ci, 28]) + 273.15
        P_Ain = P_atm + float(raw.iloc[ci, 30])
        dP_exp = float(raw.iloc[ci, 30]) - float(raw.iloc[ci, 31])
        rho_A = air_density(T_Ain_K, P_Ain)
        mu_A = air_viscosity(T_Ain_K)
        u_A = m_air / (rho_A * A_FLOW)
        G = m_air / A_FLOW
        cases.append(dict(G=G, T=T_Ain_K, P_in=P_Ain, mu=mu_A,
                          u=u_A, rho=rho_A, dP_exp=dP_exp))

    def objective(params):
        K_val, cF_val = 10.0 ** params[0], 10.0 ** params[1]
        total = 0.0
        for c in cases:
            if compressible:
                dp = dP_1d_compressible(K_val, cF_val, c["G"], c["T"],
                                        c["P_in"], c["mu"], L_DOM)
            else:
                dp = dP_incompressible(K_val, cF_val, c["u"], c["rho"],
                                       c["mu"], L_DOM)
            total += ((dp - c["dP_exp"]) / c["dP_exp"]) ** 2
        return total

    x0 = [np.log10(2e-8), np.log10(65)]
    res = minimize(objective, x0, method="Nelder-Mead",
                   options={"maxiter": 200, "xatol": 0.01, "fatol": 1e-4,
                            "adaptive": True})
    K_opt = 10.0 ** res.x[0]
    cF_opt = 10.0 ** res.x[1]
    rmsre = float(np.sqrt(res.fun / 16) * 100)
    return K_opt, cF_opt, rmsre


# ==================================================================
# CLI
# ==================================================================

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    from .predict import predict_K_cF
    from solvers.tpms_calc import geometry as tpms_geometry

    # --- Shanghai 三方法对比 ---
    g = tpms_geometry("Gyroid", 7.0, 0.6, 16.0)
    K_mlp, cF_mlp = predict_K_cF("Gyroid", 7.0, 0.6, g["epsilon"] / 2)

    print("=" * 70)
    print("  Shanghai 16 case: MLP 参数三方法对比")
    print(f"  K={K_mlp:.4e}, c_F={cF_mlp:.2f}")
    print("=" * 70)

    rmsre_i, res_i = eval_shanghai_1d(K_mlp, cF_mlp, compressible=False)
    rmsre_c, res_c = eval_shanghai_1d(K_mlp, cF_mlp, compressible=True)

    print(f"\n{'Case':>4} {'dP_exp':>9} {'不可压':>9} {'1D可压':>9} "
          f"{'不可压err':>9} {'1D可压err':>9}")
    print("-" * 55)
    for ri, rc in zip(res_i, res_c):
        print(f"{ri['case']:4d} {ri['dP_exp']:9.0f} {ri['dP_pred']:9.0f} "
              f"{rc['dP_pred']:9.0f} {ri['err_pct']:+9.1f}% "
              f"{rc['err_pct']:+9.1f}%")
    print(f"\nRMSRE: 不可压={rmsre_i:.2f}%  1D可压={rmsre_c:.2f}%")

    # --- 解析逆拟合 ---
    print("\n" + "=" * 70)
    print("  解析公式逆拟合 (不经过 SIMPLE)")
    print("=" * 70)

    for comp, label in [(False, "不可压"), (True, "1D可压")]:
        K_a, cF_a, rmsre_a = reverse_fit_analytical(compressible=comp)
        print(f"\n  [{label}] K={K_a:.4e}, c_F={cF_a:.2f}, RMSRE={rmsre_a:.2f}%")
        print(f"  对比 SIMPLE 逆拟合: K=8.26e-8, c_F=463, RMSRE=5.5%")


if __name__ == "__main__":
    main()
