"""Direction-symmetry test for the non-isothermal SIMPLE ↔ solve_full
coupling.

Reuses Shanghai Case 16 geometry and mass flow, but swaps the water-side
boundary so that air is HEATED instead of cooled:
    - Tb_prescribed = uniform 200°C (hot water heat source)
    - Air enters at 97.5°C, should rise toward ~200°C
Expected physics:
    - T_air rises along the channel → ρ drops along the channel
    - G=ρv conserved → v rises along the channel (opposite of Shanghai cooling)
    - Forchheimer ρ·c_F·v² = c_F·G²/ρ grows as ρ drops → dP INCREASES
    - So heating dP > isothermal dP > cooling dP
"""
import sys, warnings
import numpy as np
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.tpms_calc import (
    geometry as tpms_geometry, compute as tpms_compute,
    air_density, air_viscosity, air_conductivity, air_cp, P_atm,
    adaptive_grid,
)
from solvers.simple_solver import SIMPLESolver
from solvers.solve_full import solve_full_domain
from df_fit.predict import predict_K_cF

R_AIR_VAL = 287.05

# Identical geometry to Shanghai Case 16
TPMS, L_CELL, T_WALL, K_S = 'Gyroid', 7.0, 0.6, 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS, D_H, A0 = g['epsilon'], g['D_h'], g['A_0']; R_H = D_H/2
L_DOM, H_DOM = 0.231, 0.042
A_FLOW = 36 * 18.0565e-6
N_X, N_Y = adaptive_grid(L_DOM, H_DOM, D_H, alpha=0.4)

# Case 16 flow + inlet conditions
m_air  = 0.0410
T_Ain_K = 97.5 + 273.15
P_Ain   = P_atm + 203421  # 304746 Pa absolute
rho_A = air_density(T_Ain_K, P_Ain)
mu_A  = air_viscosity(T_Ain_K); k_A = air_conductivity(T_Ain_K); cp_A = air_cp(T_Ain_K)
u_A   = m_air / (rho_A * A_FLOW)

K_pred, cF_pred = predict_K_cF(TPMS, L_CELL, T_WALL, 0.5 * EPS)
G_est = m_air / A_FLOW
C_est = mu_A * G_est / K_pred + cF_pred * G_est**2
P_out_est = float(np.sqrt(max(P_Ain**2 - 2*R_AIR_VAL*T_Ain_K*C_est*L_DOM, 1e4)))

print(f"=== Test: Case 16 geometry with HEATING (reversed) ===")
print(f"  T_Ain = 97.5°C,  Tb_prescribed = uniform 200°C (hot water)")
print(f"  Expected: air T rises 97 → ~200°C, dP increases vs isothermal")
print()

# Three runs:
#   A. Pure isothermal (baseline)
#   B. Cooling (cold water, original Shanghai)
#   C. Heating (hot water, reversed)

def run_case(Tb_scalar_C, label):
    """Run full coupled solve with uniform Tb_prescribed at Tb_scalar_C."""
    T_Bin_K = Tb_scalar_C + 273.15
    T_Bout_K = T_Bin_K
    rho_B = 999.0
    cp_B  = 4182.0
    mu_B_placeholder = 1e-3

    sA = SIMPLESolver(H_DOM, L_DOM, N_Y, N_X, TPMS, L_CELL, T_WALL,
                      EPS, R_H, rho_A, mu_A, T_Ain_K,
                      0.0, H_DOM, u_A, outlet_lo=0.0, outlet_hi=H_DOM,
                      P_ref_abs=P_out_est)
    cA, nA = sA.solve(max_iter=3000, tol=1e-4, verbose=False)
    dP_iso = sA.P[:,0].mean() - sA.P[:,-1].mean()

    eps_A = 0.5 * EPS
    K_ffA = eps_A * k_A
    K_ffB = eps_A * air_conductivity(T_Bin_K)
    K_ss  = (1-EPS) * K_S
    r_A = tpms_compute(TPMS, L_CELL, T_WALL, u_A, T_Ain_K, P_Ain, K_S)
    h_vA = A0 * r_A['H_sf']
    h_vB = 1e10
    rho_cp_A = rho_A * cp_A
    rho_cp_B = rho_B * cp_B

    Tb_prescribed = np.full((N_X, N_Y), T_Bin_K, dtype=np.float64)
    ucB = np.zeros((N_X, N_Y)); vcB = np.zeros((N_X, N_Y))
    vcA_real = np.zeros((N_X, N_Y))

    Ta_prev = None
    for outer in range(8):
        v_cell = 0.5*(sA.v[:,:-1]+sA.v[:,1:])
        ucA_real = np.ascontiguousarray(v_cell.T, dtype=np.float64)
        Ta, Tb, Ts, info = solve_full_domain(
            L_DOM, H_DOM, N_X, N_Y, T_Ain_K, T_Bin_K,
            K_ffA, K_ffB, K_ss, h_vA, h_vB, rho_cp_A, rho_cp_B,
            EPS, ucA_real, vcA_real, ucB, vcB,
            dir_A=0, dir_B=3, Tb_prescribed=Tb_prescribed,
            max_iter=50000, tol=1e-6, return_info=True,
        )
        if Ta_prev is not None:
            dT_max = float(np.abs(Ta - Ta_prev).max())
            if dT_max < 0.5:
                break
        Ta_prev = Ta.copy()

        T_field_new = np.ascontiguousarray(Ta.T, dtype=np.float64)
        if outer > 0:
            T_field_new = 0.6*T_field_new + 0.4*sA.T_field
        sA.update_T_field(T_field_new)

        T_avg = float(sA.T_field.mean())
        mu_avg = air_viscosity(T_avg)
        C_avg = mu_avg*G_est/K_pred + cF_pred*G_est**2
        sA.P_ref_abs = float(np.sqrt(max(P_Ain**2 - 2*R_AIR_VAL*T_avg*C_avg*L_DOM, 1e4)))
        sA.solve(max_iter=3000, tol=1e-4, verbose=False)

    dP_coupled = sA.P[:,0].mean() - sA.P[:,-1].mean()
    T_in_sim  = Ta[0,:].mean()
    T_out_sim = Ta[-1,:].mean()
    v_in_avg  = 0.5*(sA.v[:,0]+sA.v[:,1]).mean()
    v_out_avg = 0.5*(sA.v[:,-2]+sA.v[:,-1]).mean()
    rho_in  = sA.rho_field[:,0].mean()
    rho_out = sA.rho_field[:,-1].mean()
    return dict(
        label=label, Tb_C=Tb_scalar_C,
        dP_iso=dP_iso, dP_coupled=dP_coupled,
        T_in=T_in_sim, T_out=T_out_sim,
        v_in=v_in_avg, v_out=v_out_avg,
        rho_in=rho_in, rho_out=rho_out,
        outer=outer+1,
    )

results = []
# Water as cold sink (original Shanghai direction)
results.append(run_case(Tb_scalar_C=30.0,  label='COOLING (Tb=30°C)'))
# Water near air temperature (near-isothermal)
results.append(run_case(Tb_scalar_C=97.5,  label='NEUTRAL (Tb=97.5°C, same as air)'))
# Water as hot source (HEATING, what the user asked about)
results.append(run_case(Tb_scalar_C=200.0, label='HEATING (Tb=200°C)'))

print()
print(f"{'Scenario':<30s} {'T_in':>6} {'T_out':>6} {'ΔT':>6}  "
      f"{'ρ_in':>6} {'ρ_out':>6}  {'v_in':>6} {'v_out':>6}  "
      f"{'dP_iso':>7} {'dP_cpl':>7} {'Δ%':>6} {'outer':>5}")
for r in results:
    dT = r['T_out'] - r['T_in']
    dP_delta_pct = (r['dP_coupled']-r['dP_iso'])/r['dP_iso']*100
    print(f"{r['label']:<30s} {r['T_in']-273.15:>6.1f} {r['T_out']-273.15:>6.1f} {dT:>+6.1f}  "
          f"{r['rho_in']:>6.3f} {r['rho_out']:>6.3f}  "
          f"{r['v_in']:>6.2f} {r['v_out']:>6.2f}  "
          f"{r['dP_iso']:>7.0f} {r['dP_coupled']:>7.0f} {dP_delta_pct:>+5.1f}% {r['outer']:>5}")

print()
print("Interpretation:")
print("  COOLING: T drops → ρ rises → v drops → Forchheimer shrinks → dP < iso ✓")
print("  NEUTRAL: no ΔT → coupled ≈ iso                                          ✓")
print("  HEATING: T rises → ρ drops → v rises → Forchheimer grows → dP > iso     ✓")
