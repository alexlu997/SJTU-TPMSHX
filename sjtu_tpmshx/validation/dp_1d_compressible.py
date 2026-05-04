"""1D compressible Darcy-Forchheimer baseline for Shanghai 16 cases.

Solves the 1D isothermal ideal-gas ODE for pressure along the channel, using
the same (K, c_F) that ConstDF-v1 gives SIMPLE. Purpose: decouple the D-F
closure error from the SIMPLE solver error, so we can tell which layer the
dP mismatch lives in.

Physics: dP/dx = -(μ/K)·u(P) - ρ(P)·c_F·u(P)²
         with ρ = P/(RT), u = G/ρ = G·RT/P, G = m_dot/A_flow = const
Closed form (isothermal, low Mach):
         P_out² = P_in² - 2·R·T·[μG/K + c_F·G²]·L_dom
"""
import sys, warnings
import numpy as np
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.tpms_calc import geometry as tpms_geometry, air_density, air_viscosity, P_atm
from df_fit.predict import predict_K_cF

R_AIR = 287.05  # J/(kg·K), dry air specific gas constant

# Geometry (identical to validate_shanghai.py)
TPMS, L_CELL, T_WALL, K_S = 'Gyroid', 7.0, 0.6, 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']; EPS_A = g['epsilon_A']
L_DOM = 0.231
A_FLOW = 36 * 18.0565e-6

K, cF = predict_K_cF(TPMS, L_CELL, T_WALL, EPS_A)
print(f"ConstDF-v1:  K = {K:.4e} m²   c_F = {cF:.4e} 1/m")
print(f"Geometry:    L_dom = {L_DOM} m   A_flow = {A_FLOW*1e4:.3f} cm²")
print()

DATA = r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
raw = pd.read_excel(DATA, engine='openpyxl', sheet_name='Sheet1', header=None, skiprows=2)
sim_df = pd.read_excel(r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\shanghai_validation.xlsx', engine='openpyxl')

def integrate_dp_1d_profile(P_in, G, L_dom, K, cF, T_profile_fn, n_steps=500):
    """Numerical 1D compressible D-F integration along an arbitrary T(x)
    profile. T_profile_fn is a callable x (meters) -> T (K).

    Forward Euler on the ODE:
        dP/dx = -(RT(x)/P) · [μ(T(x))·G/K + cF·G²]
    """
    dx = L_dom / n_steps
    P = P_in
    for n in range(n_steps):
        x = (n + 0.5) * dx
        T_x = T_profile_fn(x)
        mu_x = air_viscosity(T_x)
        C_x = mu_x * G / K + cF * G**2
        dPdx = -(R_AIR * T_x / P) * C_x
        P = P + dPdx * dx
    return P_in - P


print("1D compressible D-F integration vs SIMPLE (same K, c_F):\n")
print(f"{'C':>2} {'G':>6} {'P_in':>7} {'Tin':>5} {'Tout':>5} "
      f"{'dP_1Dc':>8} {'dP_1Dnc':>8} {'dP_1Dexp':>9} {'dP_sim':>8} {'dP_exp':>8} "
      f"{'exp/sim':>7} {'err_exp%':>9} {'err_sim%':>8}")

# Shanghai air cp (matches validate_shanghai.py), needed to compute T_out from Q_exp
def air_cp_simple(T_K):
    return 1004.5 + 0.00017 * T_K**1.3   # approximate, sufficient for 1D ref

rows = []
for ci in range(16):
    m_air = float(raw.iloc[ci, 5])
    T_in_K = float(raw.iloc[ci, 28]) + 273.15
    P_in  = P_atm + float(raw.iloc[ci, 30])
    Q_exp = float(raw.iloc[ci, 33])  # air-side Q [W], positive when air loses heat

    G      = m_air / A_FLOW
    rho_in = P_in / (R_AIR * T_in_K)

    # ── 1D compressible ISOTHERMAL closed-form (reference point for audit) ──
    mu_in = air_viscosity(T_in_K)
    K_iso  = mu_in * G / K
    F_iso  = cF * G**2
    P_out_sq_iso = P_in**2 - 2.0 * R_AIR * T_in_K * (K_iso + F_iso) * L_DOM
    dP_1Dc = P_in - np.sqrt(max(P_out_sq_iso, 1.0))

    # ── 1D compressible NON-ISOTHERMAL, linear T profile approx ──
    cp_in = air_cp_simple(T_in_K)
    T_out_K = T_in_K - Q_exp / (m_air * cp_in)
    T_avg = 0.5 * (T_in_K + T_out_K)
    mu_avg = air_viscosity(T_avg)
    K_nc = mu_avg * G / K
    F_nc = cF * G**2
    P_out_sq_nc = P_in**2 - 2.0 * R_AIR * T_avg * (K_nc + F_nc) * L_DOM
    dP_1Dnc = P_in - np.sqrt(max(P_out_sq_nc, 1.0))

    # ── 1D compressible NON-ISOTHERMAL, exponential-approach T profile
    #    (LTNE high-NTU: air rapidly approaches solid/wall temperature,
    #    direction-symmetric — works for both cooling AND heating) ──
    # T(x) = T_wall + (T_in - T_wall) · exp(-x/L_decay)
    # For cooling  (T_in > T_wall):  T drops monotonically from T_in to T_wall
    # For heating  (T_in < T_wall):  T rises monotonically from T_in to T_wall
    # (T_in - T_wall) has the correct sign in either case.
    T_wall = T_out_K
    if abs(T_in_K - T_wall) > 0.5:
        L_decay = L_DOM / 5.0  # reaches ~99% of (T_wall - T_in) at x = L_dom
    else:
        L_decay = L_DOM * 1e6  # essentially isothermal (ΔT < 0.5 K)
    def T_profile(x, T0=T_in_K, Tw=T_wall, Ld=L_decay):
        return Tw + (T0 - Tw) * np.exp(-x / Ld)
    dP_1Dexp = integrate_dp_1d_profile(P_in, G, L_DOM, K, cF, T_profile)

    dP_exp = float(raw.iloc[ci, 30]) - float(raw.iloc[ci, 31])
    dP_sim = float(sim_df.iloc[ci]['dP_air_sim'])

    ratio_exp_sim = dP_1Dexp / dP_sim if dP_sim else float('nan')
    err_exp  = (dP_1Dexp - dP_exp)/dP_exp*100
    err_sim  = (dP_sim  - dP_exp)/dP_exp*100

    print(f"{ci+1:>2} {G:>6.2f} {P_in:>7.0f} {T_in_K-273.15:>5.0f} {T_out_K-273.15:>5.0f} "
          f"{dP_1Dc:>8.0f} {dP_1Dnc:>8.0f} {dP_1Dexp:>9.0f} {dP_sim:>8.0f} {dP_exp:>8.0f} "
          f"{ratio_exp_sim:>7.3f} {err_exp:>+8.1f}% {err_sim:>+7.1f}%")
    rows.append(dict(case=ci+1, dP_1Dc=dP_1Dc, dP_1Dnc=dP_1Dnc, dP_1Dexp=dP_1Dexp,
                     dP_sim=dP_sim, dP_exp=dP_exp, T_in_C=T_in_K-273.15,
                     T_out_C=T_out_K-273.15))

print()
print("Column meanings:")
print("  dP_1Dc   = isothermal 1D closed-form (T frozen at T_in)")
print("  dP_1Dnc  = non-iso 1D closed-form (T_avg = (T_in+T_out)/2 linear profile)")
print("  dP_1Dexp = non-iso 1D numerical integration (exponential decay T profile)")
print("  dP_sim   = SIMPLE 2D solver output (non-isothermal coupled)")
print("  dP_exp   = Shanghai experimental measurement")
print("  exp/sim  = dP_1Dexp / dP_sim — should be ≈ 1.0 if SIMPLE coupling is right")
