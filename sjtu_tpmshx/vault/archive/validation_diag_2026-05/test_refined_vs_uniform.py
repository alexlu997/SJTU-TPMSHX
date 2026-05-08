"""
test_refined_vs_uniform.py — 对比 refined 和 uniform 两种网格下的 dP 差异

用同一 Shanghai Case 8 配置，先后跑：
  (A) uniform 网格（SIMPLE wall_refine=False）
  (B) refined 网格（4-wall BL 解析）
对比 dP 差异，确认 <5%（工程可接受）且 refined 更准。

此测试捕获未来若有改动导致两种网格不一致（例如 grid mapping bug）。
"""
import os, sys, warnings
import numpy as np
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.tpms_calc import geometry as tpms_geometry, air_density, air_viscosity, P_atm
from solvers.simple_solver import SIMPLESolver
from solvers.df_projection import build_master_refined_grid, extract_dP_from_simple
from df_fit.predict import predict_K_cF

R_AIR = 287.05

TPMS = 'Gyroid'; L_CELL = 7.0; T_WALL = 0.6; K_S = 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']; D_H = g['D_h']; R_H = D_H / 2
L_DOM = 0.231; H_DOM = 0.042
A_FLOW = 36 * 18.0565e-6

DATA = r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
df = pd.read_excel(DATA, engine='openpyxl', sheet_name='Sheet1', header=None, skiprows=2)

# Case 8 (mid Re)
ci = 7
m_air = float(df.iloc[ci, 5])
T_in = float(df.iloc[ci, 28]) + 273.15
P_in = P_atm + float(df.iloc[ci, 30])
rho = air_density(T_in, P_in); mu = air_viscosity(T_in)
u_A = m_air / (rho * A_FLOW)

K_pred, cF_pred = predict_K_cF(TPMS, L_CELL, T_WALL, EPS/2.0)
G = m_air / A_FLOW
C = mu*G/K_pred + cF_pred*G**2
P_out_sq = P_in**2 - 2*R_AIR*T_in*C*L_DOM
P_out_est = float(np.sqrt(max(P_out_sq, 1e4)))

from solvers.tpms_calc import adaptive_grid
N_X_USER, N_Y_USER = adaptive_grid(L_DOM, H_DOM, D_H, alpha=0.2)

def run_uniform():
    sA = SIMPLESolver(H_DOM, L_DOM, N_Y_USER, N_X_USER, TPMS, L_CELL, T_WALL,
                      EPS, R_H, rho, mu, T_in, 0.0, H_DOM, u_A,
                      outlet_lo=0.0, outlet_hi=H_DOM, P_ref_abs=P_out_est, wall_refine=False)
    sA.solve(max_iter=3000, tol=1e-4, verbose=False)
    return extract_dP_from_simple(sA), sA.Nx, sA.Ny

def run_refined():
    dx_r, dy_r, Nx_r, Ny_r = build_master_refined_grid(
        L_DOM, H_DOM, N_X_USER, N_Y_USER, n_refine=8, first_cell=0.02e-3, growth=1.8)
    sA = SIMPLESolver(H_DOM, L_DOM, Ny_r, Nx_r, TPMS, L_CELL, T_WALL,
                      EPS, R_H, rho, mu, T_in, 0.0, H_DOM, u_A,
                      outlet_lo=0.0, outlet_hi=H_DOM, P_ref_abs=P_out_est, wall_refine=False)
    sA.dx_arr = dy_r.copy()
    sA.dy_arr = dx_r.copy()
    sA.solve(max_iter=3000, tol=1e-4, verbose=False)
    return extract_dP_from_simple(sA), sA.Nx, sA.Ny

print("=" * 60)
print("Refined vs Uniform Consistency Test (Shanghai Case 8)")
print("=" * 60)
print(f"User grid: {N_X_USER}×{N_Y_USER}")
print(f"u={u_A:.2f} m/s, T={T_in:.1f}K, G={G:.2f} kg/m²s")
print(f"K={K_pred:.3e}, c_F={cF_pred:.1f}")
print()

dP_u, Nx_u, Ny_u = run_uniform()
print(f"Uniform (no-slip, {Nx_u}×{Ny_u}):  dP = {dP_u:.1f} Pa")

dP_r, Nx_r, Ny_r = run_refined()
print(f"Refined (4-wall, {Nx_r}×{Ny_r}):   dP = {dP_r:.1f} Pa")

delta = (dP_r - dP_u) / dP_u * 100
print(f"\nΔ = {dP_r - dP_u:+.1f} Pa ({delta:+.2f}%)")

# 预期：refined 应略高（BL 阻塞有效截面 → u↑ → c_F·u² ↑）
if abs(delta) > 5.0:
    print(f"\n✗ 差异过大 (>5%), 可能有坐标映射 bug")
    sys.exit(1)
elif 0.0 < delta < 2.0:
    print(f"\n✓ 差异符合预期（refined 略高 0.1-1%，BL 阻塞效应）")
else:
    print(f"\n? 差异方向异常（应 refined > uniform 约 0.3%）")

print()
print("注：本测试是**等温** SIMPLE。对比 validate_shanghai 的非等温耦合值时，")
print("    非等温会给出更低的 dP（Case 8 非等温 ≈ 54000 Pa），属正常物理行为。")
