"""Dump SIMPLE solver fields for Shanghai Case 16 and diagnose the 17pp
mystery gap between 1D analytical and SIMPLE's dP_sim.

Checks:
  1. Is u uniform in the cross-stream direction? (1D assumption)
  2. Is v ~ 0? (no lateral flow)
  3. What does the inlet/outlet pressure profile look like?
  4. What does u_avg look like along the flow direction? (shows compressibility)
  5. What is u compared to u_A = m_dot/(rho*A)?  (catches velocity-convention bugs)
"""
import sys, warnings
import numpy as np
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.tpms_calc import geometry as tpms_geometry, air_density, air_viscosity, P_atm, adaptive_grid
from solvers.simple_solver import SIMPLESolver
from df_fit.predict import predict_K_cF

TPMS, L_CELL, T_WALL, K_S = 'Gyroid', 7.0, 0.6, 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']; D_H = g['D_h']; R_H = D_H / 2; A0 = g['A_0']
L_DOM = 0.231; H_DOM = 0.042
N_UNITS = 36
A_FLOW = N_UNITS * 18.0565e-6
N_X, N_Y = adaptive_grid(L_DOM, H_DOM, D_H, alpha=0.4)

# Case 16 inputs (raw from validate_shanghai.py Excel read)
DATA = r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
raw = pd.read_excel(DATA, engine='openpyxl', sheet_name='Sheet1', header=None, skiprows=2)
ci = 15   # case 16
m_air  = float(raw.iloc[ci, 5])
T_in_K = float(raw.iloc[ci, 28]) + 273.15
P_in_g = float(raw.iloc[ci, 30])
P_Ain  = P_atm + P_in_g
rho_A  = air_density(T_in_K, P_Ain)
mu_A   = air_viscosity(T_in_K)
u_A    = m_air / (rho_A * A_FLOW)
dP_exp = P_in_g - float(raw.iloc[ci, 31])

K_pred, cF_pred = predict_K_cF(TPMS, L_CELL, T_WALL, EPS/2)

print(f"=== Case 16 setup ===")
print(f"  m_air = {m_air:.4f} kg/s   T_in = {T_in_K-273.15:.1f}°C")
print(f"  P_in  = {P_Ain:.0f} Pa     rho_A = {rho_A:.3f}   mu_A = {mu_A:.3e}")
print(f"  u_A   = {u_A:.3f} m/s  (= m_air / (rho*A_flow))")
print(f"  N_X × N_Y = {N_X} × {N_Y}")
print(f"  K (ConstDF) = {K_pred:.4e}   c_F = {cF_pred:.4e}")
print(f"  dP_exp = {dP_exp:.0f} Pa")
print()

# Build SIMPLE solver exactly as validate_shanghai.py does (with P_ref_abs fix)
R_AIR_VAL = 287.05
G_est = m_air / A_FLOW
C_est = mu_A * G_est / K_pred + cF_pred * G_est**2
P_out_sq = P_Ain**2 - 2.0 * R_AIR_VAL * T_in_K * C_est * L_DOM
P_out_est = float(np.sqrt(max(P_out_sq, 1.0e4)))
print(f"  P_ref_abs seed = {P_out_est:.0f} Pa (1D closed-form outlet estimate)")

sA = SIMPLESolver(H_DOM, L_DOM, N_Y, N_X, TPMS, L_CELL, T_WALL,
                  EPS, R_H, rho_A, mu_A, T_in_K,
                  0.0, H_DOM, u_A, outlet_lo=0.0, outlet_hi=H_DOM,
                  P_ref_abs=P_out_est)

print(f"=== Solver internal state after construction ===")
print(f"  sum(dx_arr) (cross-stream W, physical y) = {sA.dx_arr.sum():.4f} m")
print(f"  sum(dy_arr) (stream H, physical x)       = {sA.dy_arr.sum():.4f} m")
print(f"  Nx (across W) = {sA.Nx}   Ny (along H) = {sA.Ny}")
print(f"  v_inlet (target stream velocity) = {sA.v_inlet:.3f} m/s")
print(f"  inlet_frac: min={sA.inlet_frac.min():.4f} max={sA.inlet_frac.max():.4f} mean={sA.inlet_frac.mean():.4f}")
print(f"  outlet_frac: min={sA.outlet_frac.min():.4f} max={sA.outlet_frac.max():.4f} mean={sA.outlet_frac.mean():.4f}")
print(f"  K_arr[0]    = {sA._K_arr[0]:.4e}     (should match {K_pred:.4e})")
print(f"  cF_arr[0]   = {sA._cF_arr[0]:.4e}    (should match {cF_pred:.4e})")
print()

# Solve — full outer SIMPLE ↔ solve_full non-isothermal coupling loop
cA, nA = sA.solve(max_iter=5000, tol=1e-5, verbose=False)
print(f"=== Solve (iter 0, isothermal) ===   converged={cA}   iters={nA}")

from solvers.tpms_calc import air_conductivity, air_cp, compute as tpms_compute
from solvers.solve_full import solve_full_domain

T_Bin_K = float(raw.iloc[ci, 24]) + 273.15
T_Bout_K = float(raw.iloc[ci, 25]) + 273.15
k_A = air_conductivity(T_in_K); cp_A = air_cp(T_in_K)
eps_f = EPS/2; K_ffA = eps_f*k_A; K_ffB = eps_f*air_conductivity(T_Bin_K); K_ss = (1-EPS)*K_S
r_A = tpms_compute(TPMS, L_CELL, T_WALL, u_A, T_in_K, P_Ain, K_S)
h_vA = A0 * r_A['H_sf']; h_vB = 1e10
rho_cp_A = rho_A * cp_A; rho_cp_B = 999.0 * 4182

y_centers = (np.arange(N_Y) + 0.5) * (H_DOM / N_Y)
Tb_1d = T_Bout_K + (T_Bin_K - T_Bout_K) * (y_centers / H_DOM)
Tb_prescribed = np.broadcast_to(Tb_1d[None, :], (N_X, N_Y)).copy()
ucB = np.zeros((N_X, N_Y)); vcB = np.zeros((N_X, N_Y)); vcA_real = np.zeros((N_X, N_Y))

print(f"\n=== Outer coupling loop (MAX_OUTER=8, tol=0.5 K, alpha_T=0.6) ===")
Ta_prev = None
for outer_iter in range(8):
    v_cell = 0.5 * (sA.v[:, :-1] + sA.v[:, 1:])
    ucA_real = np.ascontiguousarray(v_cell.T, dtype=np.float64)
    Ta, Tb, Ts, info = solve_full_domain(L_DOM, H_DOM, N_X, N_Y,
        T_in_K, T_Bin_K, K_ffA, K_ffB, K_ss, h_vA, h_vB, rho_cp_A, rho_cp_B,
        EPS, ucA_real, vcA_real, ucB, vcB, dir_A=0, dir_B=3,
        Tb_prescribed=Tb_prescribed, max_iter=50000, tol=1e-6, return_info=True)

    dT_max = float('nan')
    if Ta_prev is not None:
        dT_max = float(np.abs(Ta - Ta_prev).max())
    print(f"  outer_iter={outer_iter}  Ta[0,:].mean={Ta[0,:].mean():.2f} "
          f" Ta[-1,:].mean={Ta[-1,:].mean():.2f}  dT_max={dT_max}  "
          f"dP_sim={(sA.P[:,0].mean() - sA.P[:,-1].mean()):.0f}")
    if Ta_prev is not None and dT_max < 0.5:
        break
    Ta_prev = Ta.copy()

    T_field_new = np.ascontiguousarray(Ta.T, dtype=np.float64)
    if outer_iter > 0:
        T_field_mixed = 0.6 * T_field_new + 0.4 * sA.T_field
        sA.update_T_field(T_field_mixed)
    else:
        sA.update_T_field(T_field_new)

    T_avg = float(sA.T_field.mean())
    mu_avg = air_viscosity(T_avg)
    C_avg = mu_avg * G_est / K_pred + cF_pred * G_est**2
    P_out_sq_new = P_Ain**2 - 2.0 * R_AIR_VAL * T_avg * C_avg * L_DOM
    sA.P_ref_abs = float(np.sqrt(max(P_out_sq_new, 1.0e4)))
    cA, nA = sA.solve(max_iter=5000, tol=1e-5, verbose=False)

print(f"=== Final coupled state ===   converged={cA}   last_inner_iters={nA}")

u = sA.u   # shape (Nx+1, Ny)  — cross-stream face velocity
v = sA.v   # shape (Nx, Ny+1)  — stream face velocity
P = sA.P   # shape (Nx, Ny)    — cell pressure
rho_field = sA.rho_field  # shape (Nx, Ny) — density field

print(f"\n=== Field shapes ===")
print(f"  u: {u.shape}  (stream, 'y'-internal direction)")
print(f"  v: {v.shape}  (cross-stream, 'x'-internal direction)")
print(f"  P: {P.shape}")

# IMPORTANT: validate_shanghai calls SIMPLESolver(H_DOM, L_DOM, N_Y, N_X, ...)
# so SIMPLE internal 'i' axis = physical y (cross-stream), 'j' axis = physical x (stream).
# → Stream velocity lives in `v` (y-faces), not `u`. u is cross-stream ~0.

# --- Check 1: is stream velocity v uniform across cross-stream at mid-channel? ---
j_mid = sA.Ny // 2
v_profile_mid = v[:, j_mid]   # v[i, j_mid], varies in i (cross-stream)
print(f"\n=== Check 1: stream v cross-stream profile at mid-channel (j={j_mid}) ===")
print(f"  min    = {v_profile_mid.min():.3f}")
print(f"  max    = {v_profile_mid.max():.3f}")
print(f"  mean   = {v_profile_mid.mean():.3f}")
print(f"  std    = {v_profile_mid.std():.3f}")
print(f"  u_A    = {u_A:.3f}  ← target from m_dot/(ρA) at inlet")
print(f"  ratio  = {v_profile_mid.mean()/u_A:.3f}")

# --- Check 2: cross-stream u magnitude (should be ~0) ---
print(f"\n=== Check 2: cross-stream u magnitude ===")
print(f"  |u| max  = {np.abs(u).max():.4e}")
print(f"  |u| mean = {np.abs(u).mean():.4e}")
print(f"  (should be ~0 for 1D full-width flow)")

# --- Check 3: cross-stream-averaged v along the stream direction ---
v_avg_along = v.mean(axis=0)   # (Ny+1,)
print(f"\n=== Check 3: <v>_cross along stream direction ===")
# 1D compressible prediction
R_AIR_VAL_LOCAL = 287.05
G_pred = m_air / A_FLOW
C_pred = mu_A * G_pred / K_pred + cF_pred * G_pred**2
# At x=0 (inlet): P=P_Ain, rho=rho_A, v=u_A
# At x=L (outlet): P=P_out_est, rho=P_out_est/(RT), v=G/rho_out
rho_out_pred = P_out_est / (R_AIR_VAL_LOCAL * T_in_K)
v_out_pred   = G_pred / rho_out_pred
print(f"  at j=0       (inlet): {v_avg_along[0]:.3f} m/s   target = {u_A:.3f}")
print(f"  at j=Ny//4:           {v_avg_along[sA.Ny//4]:.3f} m/s")
print(f"  at j=Ny//2:           {v_avg_along[sA.Ny//2]:.3f} m/s")
print(f"  at j=3Ny//4:          {v_avg_along[3*sA.Ny//4]:.3f} m/s")
print(f"  at j=Ny    (outlet):  {v_avg_along[-1]:.3f} m/s   target = {v_out_pred:.3f}")

# --- NEW Check 3b: mass flux conservation along stream direction ---
print(f"\n=== Check 3b: mass flux ∫ρ·v·dx along stream direction ===")
target_mdot = m_air  # should be constant
# Mass flux at each j: sum_i rho(i,j) * v(i, j) * dx_arr[i]
dx_arr = sA.dx_arr
for label, j in [("inlet (j=0)", 0),
                 ("j=Ny//4", sA.Ny//4),
                 ("j=Ny//2", sA.Ny//2),
                 ("j=3Ny//4", 3*sA.Ny//4),
                 ("outlet (j=Ny-1)", sA.Ny-1)]:
    # Use face v at j+1/2 (v[i, j+1] or v[i, j])  — for interior cells take v[i, j+1]
    vj = v[:, min(j+1, sA.Ny)]  # stream face after cell j
    rhoj = rho_field[:, j]
    mdot_j = (rhoj * vj * dx_arr).sum()
    print(f"  {label:<22s}  ṁ = {mdot_j:.6f} kg/s   err = {(mdot_j-target_mdot)/target_mdot*100:+.3f}%")
print(f"  target m_air = {target_mdot:.6f} kg/s")

# --- Check 4: P at inlet and outlet (cross-stream average) ---
P_inlet_col  = P[:, 0]
P_outlet_col = P[:, -1]
print(f"\n=== Check 4: P profile at inlet (j=0) and outlet (j=Ny-1) columns ===")
print(f"  P[j=0]  min={P_inlet_col.min():.0f}  max={P_inlet_col.max():.0f}  mean={P_inlet_col.mean():.0f}")
print(f"  P[j=-1] min={P_outlet_col.min():.0f}  max={P_outlet_col.max():.0f}  mean={P_outlet_col.mean():.0f}")
print(f"  simple dP_sim (mean-mean) = {P_inlet_col.mean() - P_outlet_col.mean():.0f} Pa")
print(f"  dP_exp = {dP_exp:.0f} Pa")

# How validate_shanghai.py computes it
wA_in = sA.inlet_frac; wA_out = sA.outlet_frac
mA_in = wA_in > 0.01; mA_out = wA_out > 0.5
dP_A_sim = (np.average(P[mA_in, 0], weights=wA_in[mA_in])
          - np.average(P[mA_out, -1], weights=wA_out[mA_out]))
print(f"  dP_A_sim (weighted, as in validate_shanghai) = {dP_A_sim:.0f} Pa")

# --- Check 5: rho_field, to see if compressibility is active ---
rho_field = sA.rho_field
print(f"\n=== Check 5: rho field (compressibility marker) ===")
print(f"  rho at j=0       = {rho_field[:,0].mean():.4f}  (inlet)")
print(f"  rho at j=-1      = {rho_field[:,-1].mean():.4f}  (outlet)")
print(f"  expected (isothermal): rho_out/rho_in ≈ P_out/P_in")
print(f"  observed: {rho_field[:,-1].mean()/rho_field[:,0].mean():.4f}")
P_ratio = (P_outlet_col.mean() + P_atm) / (P_inlet_col.mean() + P_atm) if False else None
# P is likely gauge or absolute? Let me just print raw
print(f"  P[j=0]  mean = {P_inlet_col.mean():.0f}")
print(f"  P[j=-1] mean = {P_outlet_col.mean():.0f}")

# --- Save fields ---
import os
out_path = r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\simple_case16_dump.npz'
os.makedirs(os.path.dirname(out_path), exist_ok=True)
np.savez(out_path,
         u=u, v=v, P=P, rho=rho_field,
         K_arr=sA._K_arr, cF_arr=sA._cF_arr,
         inlet_frac=sA.inlet_frac, outlet_frac=sA.outlet_frac,
         u_A=u_A, rho_A_inlet=rho_A, mu_A=mu_A, P_in=P_Ain,
         m_air=m_air, T_in_K=T_in_K, dP_exp=dP_exp, dP_A_sim=dP_A_sim,
         K_pred=K_pred, cF_pred=cF_pred)
print(f"\nSaved: {out_path}")
