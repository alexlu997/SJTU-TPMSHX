"""扫描 K 钳位值，跑上海 16 case 非等温 SIMPLE"""
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
from df_fit import surrogate_v3 as sv3
from df_fit.predict import _CACHE

R_AIR = 287.05
TPMS = 'Gyroid'; L_CELL = 7.0; T_WALL = 0.6; K_S = 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']; D_H = g['D_h']; R_H = D_H / 2; A0 = g['A_0']
L_DOM = 0.231; H_DOM = 0.042
N_UNITS = 36
A_FLOW = N_UNITS * 18.0565e-6

from solvers.tpms_calc import adaptive_grid
N_X, N_Y = adaptive_grid(L_DOM, H_DOM, D_H, alpha=0.2)

DATA = r'D:\Postgraduate\均质化\ThermoNAS\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
df = pd.read_excel(DATA, engine='openpyxl', sheet_name='Sheet1', header=None, skiprows=2)

def water_rho(T): return 999.84 - 0.05*(T-273.15) - 0.004*(T-273.15)**2
def water_mu(T):  return 1.79e-3 * np.exp(-0.035*(T-273.15))
def water_k(T):   return 0.569 + 0.0019*(T-273.15) - 8e-6*(T-273.15)**2

def run_one_case(ci, K_override, cF_override):
    m_air = float(df.iloc[ci, 5])
    T_Ain_K = float(df.iloc[ci, 28]) + 273.15
    P_Ain = P_atm + float(df.iloc[ci, 30])
    rho_A = air_density(T_Ain_K, P_Ain); mu_A = air_viscosity(T_Ain_K)
    k_A = air_conductivity(T_Ain_K); cp_A = air_cp(T_Ain_K)
    u_A = m_air / (rho_A * A_FLOW)
    m_water = float(df.iloc[ci, 7])
    T_Bin_K = float(df.iloc[ci, 24]) + 273.15
    T_Bout_K = float(df.iloc[ci, 25]) + 273.15
    rho_B = water_rho(T_Bin_K); mu_B = water_mu(T_Bin_K)
    k_B = water_k(T_Bin_K); cp_B = 4182.0
    dP_exp = float(df.iloc[ci, 30]) - float(df.iloc[ci, 31])

    # 1D P_ref_abs seed
    G_est = m_air / A_FLOW
    C_est = mu_A * G_est / K_override + cF_override * G_est**2
    P_out_sq = P_Ain**2 - 2*R_AIR*T_Ain_K*C_est*L_DOM
    P_out_est = float(np.sqrt(max(P_out_sq, 1e4)))

    sA = SIMPLESolver(H_DOM, L_DOM, N_Y, N_X, TPMS, L_CELL, T_WALL,
                      EPS, R_H, rho_A, mu_A, T_Ain_K,
                      0.0, H_DOM, u_A, outlet_lo=0.0, outlet_hi=H_DOM,
                      P_ref_abs=P_out_est)
    # Override K/cF arrays (SIMPLE populated them from predict_K_cF during init)
    sA._K_arr[:] = K_override
    sA._cF_arr[:] = cF_override
    sA.solve(max_iter=3000, tol=1e-4, verbose=False)

    # solve_full + outer coupling
    eps_f = EPS/2.0
    K_ffA = eps_f*k_A; K_ffB = eps_f*k_B; K_ss = (1.0-EPS)*K_S
    r_A = tpms_compute(TPMS, L_CELL, T_WALL, u_A, T_Ain_K, P_Ain, K_S)
    h_vA = A0 * r_A['H_sf']; h_vB = 1.0e10
    rho_cp_A = rho_A*cp_A; rho_cp_B = rho_B*cp_B
    dy = H_DOM/N_Y
    yc = (np.arange(N_Y)+0.5)*dy
    Tb_1d = T_Bout_K + (T_Bin_K - T_Bout_K) * (yc/H_DOM)
    Tb_pre = np.broadcast_to(Tb_1d[None,:], (N_X, N_Y)).copy()

    def _ucA(s):
        vc = 0.5*(s.v[:,:-1] + s.v[:,1:])
        return np.ascontiguousarray(vc.T, dtype=np.float64)
    def _hvAf(Ta, uc, s):
        Pabs = np.ascontiguousarray((s.P_ref_abs + s.P).T, dtype=np.float64)
        rl = Pabs/(R_AIR*Ta); ml = air_viscosity(Ta); kl = air_conductivity(Ta)
        Re = np.clip(rl*np.abs(uc)*D_H/ml, 1.0, None)
        n_f = 0.177*Re**0.1 * EPS**(-2.0/3.0)
        Nu = 0.17*Pr**(1.0/3.0)*Re**n_f * EPS**2.25 * (L_CELL/(1000.0*Sa_mm))**(-2.01)
        return A0*Nu*kl/D_H

    Ta=None; Ta_prev=None
    for outer in range(8):
        uc = _ucA(sA)
        if Ta is not None:
            h_vA = _hvAf(Ta, uc, sA)
        zero = np.zeros((N_X, N_Y))
        result = solve_full_domain(
            L_DOM, H_DOM, N_X, N_Y, T_Ain_K, T_Bin_K,
            K_ffA, K_ffB, K_ss, h_vA, h_vB,
            rho_cp_A, rho_cp_B, EPS, uc, zero, zero, zero,
            dir_A=0, dir_B=3, Tb_prescribed=Tb_pre,
            max_iter=50000, tol=1e-6, return_info=True)
        Ta, Tb, Ts = result[:3]
        if Ta_prev is not None and float(np.abs(Ta-Ta_prev).max()) < 0.5:
            break
        Ta_prev = Ta.copy()
        T_new = np.ascontiguousarray(Ta.T, dtype=np.float64)
        if outer > 0:
            T_mix = 0.6*T_new + 0.4*sA.T_field
            sA.update_T_field(T_mix)
        else:
            sA.update_T_field(T_new)
        T_avg = float(sA.T_field.mean())
        mu_avg = air_viscosity(T_avg)
        C_avg = mu_avg*G_est/K_override + cF_override*G_est**2
        P_out_sq2 = P_Ain**2 - 2*R_AIR*T_avg*C_avg*L_DOM
        sA.P_ref_abs = float(np.sqrt(max(P_out_sq2, 1e4)))
        sA._K_arr[:] = K_override; sA._cF_arr[:] = cF_override
        sA.solve(max_iter=3000, tol=1e-4, verbose=False)

    wA_in = sA.inlet_frac; wA_out = sA.outlet_frac
    mI = wA_in > 0.01; mO = wA_out > 0.5
    dP_sim = (np.average(sA.P[mI, 0], weights=wA_in[mI])
            - np.average(sA.P[mO, -1], weights=wA_out[mO]))
    Re_val = rho_A * u_A * D_H / mu_A
    return Re_val, dP_exp, dP_sim

# cF from RBF (fixed)
from df_fit.surrogate_v3 import SurrogateV3
m = SurrogateV3("Gyroid")
K_rbf, cF_rbf = m.predict(7.0, 0.6)
print(f"RBF baseline: K={K_rbf:.3e}, c_F={cF_rbf:.2f}")
print(f"(K_rbf 是钳位值，RBF 原始对数值可能更小)")

K_sweep = [1e-7, 3e-8, 1e-8, 5e-9, 3e-9, 1e-9]
all_results = {}
for K_try in K_sweep:
    print(f"\n=== K = {K_try:.1e}, c_F = {cF_rbf:.1f} ===")
    rows = []
    err_sq_all = 0.0
    err_sq_hi = 0.0; n_hi = 0
    for ci in range(16):
        Re, dPe, dPs = run_one_case(ci, K_try, cF_rbf)
        err = (dPs - dPe) / dPe * 100
        rows.append((ci+1, Re, dPe, dPs, err))
        err_sq_all += err**2
        if Re > 600:
            err_sq_hi += err**2; n_hi += 1
        print(f"  Case {ci+1:2d}: Re={Re:6.0f}  dP {dPe:6.0f}/{dPs:6.0f}  err={err:+6.1f}%")
    rmsre_all = np.sqrt(err_sq_all/16)
    rmsre_hi = np.sqrt(err_sq_hi/n_hi) if n_hi > 0 else 0
    all_results[K_try] = (rmsre_all, rmsre_hi, rows)
    print(f"  RMSRE 全 16 case: {rmsre_all:.1f}%")
    print(f"  RMSRE (Re>600, n={n_hi}): {rmsre_hi:.1f}%")

print("\n\n=== 总结 ===")
print(f"{'K':>10} {'RMSRE_全':>10} {'RMSRE_高Re':>12}")
for K, (r_all, r_hi, _) in all_results.items():
    print(f"{K:10.1e} {r_all:10.1f}% {r_hi:12.1f}%")
