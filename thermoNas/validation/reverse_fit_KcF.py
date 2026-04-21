"""Reverse-fit (K, c_F) from Shanghai 16-case dP_exp using SIMPLE as the
forward model. No simplifications — SIMPLE runs full non-isothermal
compressible coupling for each (K, c_F) trial, giving exact dP_sim.

Uses scipy.optimize.minimize to find (K, c_F) that minimizes
    Σ_i [ (dP_sim_i(K, c_F) - dP_exp_i) / dP_exp_i ]²
i.e. relative error squared, so low-dP and high-dP cases are weighted equally.
"""
import sys, os, warnings
import numpy as np
import pandas as pd
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.tpms_calc import (
    geometry as tpms_geometry, compute as tpms_compute,
    air_density, air_viscosity, air_conductivity, air_cp, P_atm,
    adaptive_grid, Pr, Sa_mm,
)
from solvers.simple_solver import SIMPLESolver
from solvers.solve_full import solve_full_domain

R_AIR = 287.05
MAX_OUTER = 8; OUTER_TOL = 0.5; ALPHA_T = 0.6

# ── Geometry ──
TPMS, L_CELL, T_WALL, K_S = 'Gyroid', 7.0, 0.6, 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS, D_H, A0 = g['epsilon'], g['D_h'], g['A_0']; R_H = D_H / 2
L_DOM, H_DOM = 0.231, 0.042
A_FLOW = 36 * 18.0565e-6
N_X, N_Y = adaptive_grid(L_DOM, H_DOM, D_H, alpha=0.2)

# ── Load Shanghai data ──
DATA = r'D:\Postgraduate\均质化\ThermoNAS\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
raw = pd.read_excel(DATA, engine='openpyxl', sheet_name='Sheet1', header=None, skiprows=2)

# Pre-compute per-case constants (don't recompute each optimization step)
cases = []
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
    rho_B = 999.84
    cp_B = 4182.0
    k_B = air_conductivity(T_Bin_K)

    # Temperature solver constants
    eps_f = EPS / 2.0
    K_ffA = eps_f * k_A
    K_ffB = eps_f * k_B
    K_ss = (1.0 - EPS) * K_S
    r_A = tpms_compute(TPMS, L_CELL, T_WALL, u_A, T_Ain_K, P_Ain, K_S)
    h_vA_scalar = A0 * r_A['H_sf']
    h_vB = 1.0e10
    rho_cp_A = rho_A * cp_A
    rho_cp_B = rho_B * cp_B

    # Tb_prescribed
    y_c = (np.arange(N_Y) + 0.5) * (H_DOM / N_Y)
    Tb_1d = T_Bout_K + (T_Bin_K - T_Bout_K) * (y_c / H_DOM)
    Tb_pre = np.broadcast_to(Tb_1d[None, :], (N_X, N_Y)).copy()

    cases.append(dict(
        ci=ci, m_air=m_air, T_Ain_K=T_Ain_K, P_Ain=P_Ain,
        rho_A=rho_A, mu_A=mu_A, k_A=k_A, cp_A=cp_A, u_A=u_A,
        T_Bin_K=T_Bin_K, T_Bout_K=T_Bout_K, dP_exp=dP_exp,
        K_ffA=K_ffA, K_ffB=K_ffB, K_ss=K_ss,
        h_vA_scalar=h_vA_scalar, h_vB=h_vB,
        rho_cp_A=rho_cp_A, rho_cp_B=rho_cp_B,
        Tb_pre=Tb_pre,
    ))


def compute_h_vA_field(Ta, ucA, sA):
    """Vectorized h_vA from local (T, v, P)."""
    P_abs_sf = np.ascontiguousarray(
        (sA.P_ref_abs + sA.P).T, dtype=np.float64)
    rho_loc = P_abs_sf / (R_AIR * Ta)
    mu_loc = air_viscosity(Ta)
    k_loc = air_conductivity(Ta)
    Re_loc = np.clip(rho_loc * np.abs(ucA) * D_H / mu_loc, 1.0, None)
    n_f = 0.177 * Re_loc**0.1 * EPS**(-2.0/3.0)
    Nu_f = (0.17 * Pr**(1.0/3.0) * Re_loc**n_f
            * EPS**2.25 * (L_CELL / (1000.0 * Sa_mm))**(-2.01))
    return A0 * Nu_f * k_loc / D_H


def run_one_case(c, K_val, cF_val):
    """Run full non-isothermal coupled SIMPLE for one case with given (K, c_F).
    Returns dP_sim."""
    G = c['m_air'] / A_FLOW
    C_est = c['mu_A'] * G / K_val + cF_val * G**2
    P_out_sq = c['P_Ain']**2 - 2.0 * R_AIR * c['T_Ain_K'] * C_est * L_DOM
    P_out_est = float(np.sqrt(max(P_out_sq, 1.0e4)))

    # Build SIMPLE with the trial (K, c_F) — override _K_arr and _cF_arr
    sA = SIMPLESolver(H_DOM, L_DOM, N_Y, N_X, TPMS, L_CELL, T_WALL,
                      EPS, R_H, c['rho_A'], c['mu_A'], c['T_Ain_K'],
                      0.0, H_DOM, c['u_A'], outlet_lo=0.0, outlet_hi=H_DOM,
                      P_ref_abs=P_out_est)
    # Override MLP's K/cF with trial values
    sA._K_arr[:] = K_val
    sA._cF_arr[:] = cF_val
    sA.solve(max_iter=3000, tol=1e-4, verbose=False)

    # Outer coupling
    ucB = np.zeros((N_X, N_Y)); vcB = np.zeros((N_X, N_Y))
    vcA = np.zeros((N_X, N_Y))
    Ta = None; Ta_prev = None; h_vA = c['h_vA_scalar']

    for outer in range(MAX_OUTER):
        v_cell = 0.5 * (sA.v[:, :-1] + sA.v[:, 1:])
        ucA = np.ascontiguousarray(v_cell.T, dtype=np.float64)
        if Ta is not None:
            h_vA = compute_h_vA_field(Ta, ucA, sA)
        Ta, Tb, Ts, info = solve_full_domain(
            L_DOM, H_DOM, N_X, N_Y,
            c['T_Ain_K'], c['T_Bin_K'],
            c['K_ffA'], c['K_ffB'], c['K_ss'],
            h_vA, c['h_vB'],
            c['rho_cp_A'], c['rho_cp_B'], EPS,
            ucA, vcA, ucB, vcB,
            dir_A=0, dir_B=3, Tb_prescribed=c['Tb_pre'],
            max_iter=50000, tol=1e-6, return_info=True,
        )
        if Ta_prev is not None:
            if float(np.abs(Ta - Ta_prev).max()) < OUTER_TOL:
                break
        Ta_prev = Ta.copy()
        T_new = np.ascontiguousarray(Ta.T, dtype=np.float64)
        if outer > 0:
            T_new = ALPHA_T * T_new + (1.0 - ALPHA_T) * sA.T_field
        sA.update_T_field(T_new)
        T_avg = float(sA.T_field.mean())
        mu_avg = air_viscosity(T_avg)
        C_avg = mu_avg * G / K_val + cF_val * G**2
        sA.P_ref_abs = float(np.sqrt(max(c['P_Ain']**2 - 2*R_AIR*T_avg*C_avg*L_DOM, 1e4)))
        sA.solve(max_iter=3000, tol=1e-4, verbose=False)

    wA_in = sA.inlet_frac; wA_out = sA.outlet_frac
    mA_in = wA_in > 0.01; mA_out = wA_out > 0.5
    dP_sim = (np.average(sA.P[mA_in, 0], weights=wA_in[mA_in])
            - np.average(sA.P[mA_out, -1], weights=wA_out[mA_out]))
    return float(dP_sim)


eval_count = [0]

def objective(params):
    """Minimize sum of squared relative dP errors across all 16 cases."""
    log_K, log_cF = params
    K_val = 10.0 ** log_K
    cF_val = 10.0 ** log_cF
    total_err_sq = 0.0
    for c in cases:
        try:
            dP_sim = run_one_case(c, K_val, cF_val)
            rel_err = (dP_sim - c['dP_exp']) / c['dP_exp']
            total_err_sq += rel_err**2
        except Exception:
            total_err_sq += 100.0  # penalty for failure
    eval_count[0] += 1
    rmse = np.sqrt(total_err_sq / 16) * 100
    print(f"  eval {eval_count[0]:3d}: K={K_val:.4e}  c_F={cF_val:.2f}  RMSRE={rmse:.2f}%")
    return total_err_sq


# ── Initial guess: MLP values ──
K_mlp, cF_mlp = 1.7288e-8, 49.54
print(f"=== Reverse-fit (K, c_F) using SIMPLE as forward model ===")
print(f"  Grid: {N_X}×{N_Y},  16 cases,  non-isothermal coupled")
print(f"  Initial guess (MLP): K={K_mlp:.4e}, c_F={cF_mlp:.2f}")
print(f"  Optimizing in log10 space: [log10(K), log10(c_F)]")
print()

x0 = [np.log10(K_mlp), np.log10(cF_mlp)]

result = minimize(objective, x0, method='Nelder-Mead',
                  options={'maxiter': 60, 'xatol': 0.02, 'fatol': 0.001,
                           'adaptive': True})

K_opt = 10.0 ** result.x[0]
cF_opt = 10.0 ** result.x[1]

print()
print(f"=== Optimization result ===")
print(f"  K_opt  = {K_opt:.4e} m²   (MLP: {K_mlp:.4e}, ratio: {K_opt/K_mlp:.2f})")
print(f"  cF_opt = {cF_opt:.2f} 1/m   (MLP: {cF_mlp:.2f}, ratio: {cF_opt/cF_mlp:.2f})")
print(f"  RMSRE  = {np.sqrt(result.fun/16)*100:.2f}%")
print()

# Per-case breakdown with optimal (K, c_F)
print(f"{'C':>2} {'Re':>6} {'dP_exp':>8} {'dP_opt':>8} {'err_opt%':>9} {'dP_mlp':>8} {'err_mlp%':>9}")
sim_df = pd.read_excel(r'D:\Postgraduate\均质化\ThermoNAS\data\shanghai_validation.xlsx', engine='openpyxl')
for i, c in enumerate(cases):
    dP_opt = run_one_case(c, K_opt, cF_opt)
    dP_mlp = float(sim_df.iloc[i]['dP_air_sim'])
    Re = c['rho_A'] * c['u_A'] * D_H / c['mu_A']
    err_opt = (dP_opt - c['dP_exp'])/c['dP_exp']*100
    err_mlp = (dP_mlp - c['dP_exp'])/c['dP_exp']*100
    print(f"{i+1:>2} {Re:>6.0f} {c['dP_exp']:>8.0f} {dP_opt:>8.0f} {err_opt:>+8.1f}% {dP_mlp:>8.0f} {err_mlp:>+8.1f}%")
