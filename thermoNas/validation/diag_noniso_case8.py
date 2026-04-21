"""
diag_noniso_case8.py — 对比 Case 8 的等温 vs 非等温 SIMPLE 内部场
目的：定位非等温耦合 dP 系统性低估 ~33% 的原因
"""
import os, sys, warnings
import numpy as np
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.tpms_calc import (
    geometry as tpms_geometry, compute as tpms_compute,
    air_density, air_viscosity, air_conductivity, air_cp, P_atm,
    Sa_mm, Pr,
)
from solvers.simple_solver import SIMPLESolver
from solvers.solve_full import solve_full_domain
from df_fit.predict import predict_K_cF

R_AIR = 287.05
CASE = 8  # 中 Re，代表性

# Geometry
TPMS = 'Gyroid'; L_CELL = 7.0; T_WALL = 0.6; K_S = 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']; D_H = g['D_h']; R_H = D_H / 2; A0 = g['A_0']
L_DOM = 0.231; H_DOM = 0.042
N_UNITS = 36
A_FLOW = N_UNITS * 18.0565e-6

from solvers.tpms_calc import adaptive_grid
N_X, N_Y = adaptive_grid(L_DOM, H_DOM, D_H, alpha=0.2)

# Load data
DATA_PATH = r'D:\Postgraduate\均质化\ThermoNAS\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
df = pd.read_excel(DATA_PATH, engine='openpyxl', sheet_name='Sheet1', header=None, skiprows=2)

ci = CASE - 1
m_air = float(df.iloc[ci, 5])
T_Ain_C = float(df.iloc[ci, 28]); T_Ain_K = T_Ain_C + 273.15
P_Ain_g = float(df.iloc[ci, 30])
P_Ain = P_atm + P_Ain_g
rho_A = air_density(T_Ain_K, P_Ain)
mu_A = air_viscosity(T_Ain_K)
k_A = air_conductivity(T_Ain_K)
cp_A = air_cp(T_Ain_K)
u_A = m_air / (rho_A * A_FLOW)
m_water = float(df.iloc[ci, 7])
T_Bin_C = float(df.iloc[ci, 24]); T_Bin_K = T_Bin_C + 273.15
T_Bout_C = float(df.iloc[ci, 25]); T_Bout_K = T_Bout_C + 273.15
P_Aout_g = float(df.iloc[ci, 31])
dP_A_exp = P_Ain_g - P_Aout_g

def water_rho(T_K):
    T_C = T_K - 273.15
    return 999.84 - 0.05 * T_C - 0.004 * T_C**2
def water_mu(T_K):
    T_C = T_K - 273.15
    return 1.79e-3 * np.exp(-0.035 * T_C)
def water_k(T_K):
    T_C = T_K - 273.15
    return 0.569 + 0.0019 * T_C - 8e-6 * T_C**2

rho_B = water_rho(T_Bin_K); mu_B = water_mu(T_Bin_K); k_B = water_k(T_Bin_K); cp_B = 4182.0
u_B = m_water / (rho_B * A_FLOW)

print(f"=== Case {CASE} ===")
print(f"  T_air_in = {T_Ain_C:.1f}°C ({T_Ain_K:.1f}K)")
print(f"  T_water_in = {T_Bin_C:.1f}°C, T_water_out = {T_Bout_C:.1f}°C")
print(f"  u_A = {u_A:.3f} m/s, m_air = {m_air:.4f} kg/s")
print(f"  P_Ain_abs = {P_Ain:.0f} Pa  (P_atm={P_atm:.0f}, P_gauge_in={P_Ain_g:.0f})")
print(f"  rho_A = {rho_A:.3f} kg/m³, mu_A = {mu_A:.3e} Pa·s")
print(f"  dP_A_exp = {dP_A_exp:.0f} Pa")
print()

K_pred, cF_pred = predict_K_cF(TPMS, L_CELL, T_WALL, EPS/2.0)
print(f"SurrogateV3: K = {K_pred:.3e} m², c_F = {cF_pred:.3f}")
print()

# 1D compressible formula baseline
G_est = m_air / A_FLOW
C_iso_in = mu_A * G_est / K_pred + cF_pred * G_est**2
P_out_sq_iso = P_Ain**2 - 2 * R_AIR * T_Ain_K * C_iso_in * L_DOM
P_out_iso = np.sqrt(max(P_out_sq_iso, 1e4))
dP_1d_iso_Tin = P_Ain - P_out_iso
print(f"1D formula (T=T_in={T_Ain_K:.1f}K):")
print(f"  dP = {dP_1d_iso_Tin:.0f} Pa  err = {(dP_1d_iso_Tin-dP_A_exp)/dP_A_exp*100:+.1f}%")

# ── Run isothermal SIMPLE (no outer coupling) ──
print("\n--- ISOTHERMAL SIMPLE (T_field = T_in) ---")
sA_iso = SIMPLESolver(H_DOM, L_DOM, N_Y, N_X, TPMS, L_CELL, T_WALL,
                     EPS, R_H, rho_A, mu_A, T_Ain_K,
                     0.0, H_DOM, u_A, outlet_lo=0.0, outlet_hi=H_DOM,
                     P_ref_abs=P_out_iso)
sA_iso.solve(max_iter=3000, tol=1e-4, verbose=False)

wA_in = sA_iso.inlet_frac; wA_out = sA_iso.outlet_frac
mA_in = wA_in > 0.01; mA_out = wA_out > 0.5
dP_iso = (np.average(sA_iso.P[mA_in, 0], weights=wA_in[mA_in])
        - np.average(sA_iso.P[mA_out, -1], weights=wA_out[mA_out]))
print(f"  dP_sim = {dP_iso:.0f} Pa  err = {(dP_iso-dP_A_exp)/dP_A_exp*100:+.1f}%")
print(f"  T_field: min={sA_iso.T_field.min():.1f} max={sA_iso.T_field.max():.1f} mean={sA_iso.T_field.mean():.1f}")
print(f"  rho_field: min={sA_iso.rho_field.min():.3f} max={sA_iso.rho_field.max():.3f} mean={sA_iso.rho_field.mean():.3f}")
print(f"  mu_field: min={sA_iso.mu_field.min():.3e} max={sA_iso.mu_field.max():.3e}")
print(f"  P_ref_abs (outlet) = {sA_iso.P_ref_abs:.0f} Pa")
print(f"  v_inlet = {sA_iso.v_inlet:.3f}, G_inlet = {sA_iso.G_inlet:.3f}")

# ── Run non-isothermal coupled SIMPLE ──
print("\n--- NON-ISOTHERMAL SIMPLE (coupled with solve_full) ---")
sA = SIMPLESolver(H_DOM, L_DOM, N_Y, N_X, TPMS, L_CELL, T_WALL,
                  EPS, R_H, rho_A, mu_A, T_Ain_K,
                  0.0, H_DOM, u_A, outlet_lo=0.0, outlet_hi=H_DOM,
                  P_ref_abs=P_out_iso)
sA.solve(max_iter=3000, tol=1e-4, verbose=False)

# Setup solve_full inputs
eps_f = EPS / 2.0
K_ffA = eps_f * k_A; K_ffB = eps_f * k_B; K_ss = (1.0 - EPS) * K_S
r_A = tpms_compute(TPMS, L_CELL, T_WALL, u_A, T_Ain_K, P_Ain, K_S)
h_vA = A0 * r_A['H_sf']
h_vB = 1.0e10
rho_cp_A = rho_A * cp_A; rho_cp_B = rho_B * cp_B

dy_cell = H_DOM / N_Y
y_centers = (np.arange(N_Y) + 0.5) * dy_cell
Tb_1d = T_Bout_K + (T_Bin_K - T_Bout_K) * (y_centers / H_DOM)
Tb_prescribed = np.broadcast_to(Tb_1d[None, :], (N_X, N_Y)).copy()

def _sA_to_ucA(s):
    v_cell = 0.5 * (s.v[:, :-1] + s.v[:, 1:])
    return np.ascontiguousarray(v_cell.T, dtype=np.float64)

def _h_vA_field(Ta, ucA, s):
    P_abs_sf = np.ascontiguousarray((s.P_ref_abs + s.P).T, dtype=np.float64)
    rho_local = P_abs_sf / (R_AIR * Ta)
    mu_local  = air_viscosity(Ta)
    k_local   = air_conductivity(Ta)
    Re_local  = np.clip(rho_local * np.abs(ucA) * D_H / mu_local, 1.0, None)
    n_f = 0.177 * Re_local**0.1 * EPS**(-2.0/3.0)
    Nu_f = (0.17 * Pr**(1.0/3.0) * Re_local**n_f
            * EPS**2.25 * (L_CELL / (1000.0 * Sa_mm))**(-2.01))
    return A0 * Nu_f * k_local / D_H

Ta = None; Ta_prev = None
for outer in range(8):
    ucA = _sA_to_ucA(sA)
    if Ta is not None:
        h_vA = _h_vA_field(Ta, ucA, sA)
    zero_B = np.zeros((N_X, N_Y))
    result = solve_full_domain(
        L_DOM, H_DOM, N_X, N_Y,
        T_Ain_K, T_Bin_K,
        K_ffA, K_ffB, K_ss, h_vA, h_vB,
        rho_cp_A, rho_cp_B, EPS,
        ucA, zero_B, zero_B, zero_B,
        dir_A=0, dir_B=3,
        Tb_prescribed=Tb_prescribed,
        max_iter=50000, tol=1e-6, return_info=True,
    )
    Ta, Tb, Ts = result[:3]

    if Ta_prev is not None:
        dT_max = float(np.abs(Ta - Ta_prev).max())
        if dT_max < 0.5:
            print(f"  [outer {outer+1}] converged, dT_max = {dT_max:.2f}")
            break
    Ta_prev = Ta.copy()

    T_new = np.ascontiguousarray(Ta.T, dtype=np.float64)
    if outer > 0:
        T_mix = 0.6 * T_new + 0.4 * sA.T_field
        sA.update_T_field(T_mix)
    else:
        sA.update_T_field(T_new)

    T_avg = float(sA.T_field.mean())
    mu_avg = air_viscosity(T_avg)
    C_avg = mu_avg * G_est / K_pred + cF_pred * G_est**2
    P_out_sq_new = P_Ain**2 - 2 * R_AIR * T_avg * C_avg * L_DOM
    sA.P_ref_abs = float(np.sqrt(max(P_out_sq_new, 1e4)))

    sA.solve(max_iter=3000, tol=1e-4, verbose=False)

    dP_now = (np.average(sA.P[mA_in, 0], weights=wA_in[mA_in])
            - np.average(sA.P[mA_out, -1], weights=wA_out[mA_out]))
    print(f"  [outer {outer+1}] T_avg={T_avg:.1f}  mu_avg={mu_avg:.3e}  "
          f"P_ref_abs={sA.P_ref_abs:.0f}  dP_sim={dP_now:.0f}  "
          f"err={(dP_now-dP_A_exp)/dP_A_exp*100:+.1f}%")

# Final
dP_noniso = (np.average(sA.P[mA_in, 0], weights=wA_in[mA_in])
           - np.average(sA.P[mA_out, -1], weights=wA_out[mA_out]))
print(f"\n  FINAL dP_sim = {dP_noniso:.0f} Pa  err = {(dP_noniso-dP_A_exp)/dP_A_exp*100:+.1f}%")
print(f"  T_field: min={sA.T_field.min():.1f} max={sA.T_field.max():.1f} mean={sA.T_field.mean():.1f}")
print(f"  rho_field: min={sA.rho_field.min():.3f} max={sA.rho_field.max():.3f} mean={sA.rho_field.mean():.3f}")
print(f"  mu_field: min={sA.mu_field.min():.3e} max={sA.mu_field.max():.3e}")
print(f"  P_ref_abs (outlet) = {sA.P_ref_abs:.0f} Pa")
print(f"  v_inlet = {sA.v_inlet:.3f}, G_inlet = {sA.G_inlet:.3f}")

# 1D formula with T_avg of non-isothermal
T_avg_final = float(sA.T_field.mean())
mu_avg_final = air_viscosity(T_avg_final)
C_noniso = mu_avg_final * G_est / K_pred + cF_pred * G_est**2
P_out_sq_noniso = P_Ain**2 - 2 * R_AIR * T_avg_final * C_noniso * L_DOM
dP_1d_noniso = P_Ain - np.sqrt(max(P_out_sq_noniso, 1e4))
print(f"\n1D formula (T=T_avg={T_avg_final:.1f}K, mu_avg):")
print(f"  dP = {dP_1d_noniso:.0f} Pa  err = {(dP_1d_noniso-dP_A_exp)/dP_A_exp*100:+.1f}%")

print(f"\n=== SUMMARY ===")
print(f"  Experiment:        dP = {dP_A_exp:.0f} Pa")
print(f"  1D (T=T_in):       dP = {dP_1d_iso_Tin:.0f}  ({(dP_1d_iso_Tin-dP_A_exp)/dP_A_exp*100:+.1f}%)")
print(f"  SIMPLE 等温 T_in:  dP = {dP_iso:.0f}  ({(dP_iso-dP_A_exp)/dP_A_exp*100:+.1f}%)")
print(f"  1D (T=T_avg):      dP = {dP_1d_noniso:.0f}  ({(dP_1d_noniso-dP_A_exp)/dP_A_exp*100:+.1f}%)")
print(f"  SIMPLE 非等温耦合: dP = {dP_noniso:.0f}  ({(dP_noniso-dP_A_exp)/dP_A_exp*100:+.1f}%)")
