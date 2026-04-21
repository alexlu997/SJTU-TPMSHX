"""
test_wall_refined.py — 近壁加密网格 proof-of-concept

Shanghai Case 8 对比：
  (A) uniform 网格 (61 cells × 0.69 mm)
  (B) 近壁加密网格 (6 层指数加密 + uniform bulk)

比较：
  - dP 差异
  - 边界层是否可见
  - SIMPLE 收敛性 / 耗时
"""
import os, sys, time, warnings
import numpy as np
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.tpms_calc import (
    geometry as tpms_geometry,
    air_density, air_viscosity, P_atm,
)
from solvers.simple_solver import SIMPLESolver
from df_fit.predict import predict_K_cF

R_AIR = 287.05


def build_wall_refined_1d(W, N_bulk, n_refine=6, first_cell=None, growth=2.0):
    """构造两端壁面加密的 1D 网格。

    dx_arr = [first_cell, first_cell·r, first_cell·r²,  ...  (refine),
              uniform_bulk ..., (bulk)
              first_cell·r^(n-1), ..., first_cell (refine)]

    返回 dx_arr(np.float64)，sum(dx_arr) == W
    """
    if first_cell is None:
        first_cell = 0.02 * (W / N_bulk)  # 默认 = 2% of uniform bulk cell

    refine_sizes = np.array([first_cell * growth**k for k in range(n_refine)], dtype=np.float64)
    total_refine = 2.0 * refine_sizes.sum()
    bulk_width = W - total_refine
    if bulk_width <= 0:
        raise ValueError(f"Too much refinement: {total_refine:.4f} >= W={W:.4f}")
    bulk_cell = bulk_width / N_bulk
    bulk = np.full(N_bulk, bulk_cell, dtype=np.float64)
    # 顺序：小→大→bulk→大→小
    dx = np.concatenate([refine_sizes, bulk, refine_sizes[::-1]])
    # Sanity
    assert abs(dx.sum() - W) < 1e-10
    return dx


# ── Shanghai Case 8 parameters ──
CASE = 8
TPMS = 'Gyroid'; L_CELL = 7.0; T_WALL = 0.6; K_S = 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']; D_H = g['D_h']; R_H = D_H / 2
L_DOM = 0.231; H_DOM = 0.042
N_UNITS = 36
A_FLOW = N_UNITS * 18.0565e-6

from solvers.tpms_calc import adaptive_grid
N_X, N_Y = adaptive_grid(L_DOM, H_DOM, D_H, alpha=0.2)

DATA = r'D:\Postgraduate\均质化\ThermoNAS\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
df = pd.read_excel(DATA, engine='openpyxl', sheet_name='Sheet1', header=None, skiprows=2)

ci = CASE - 1
m_air = float(df.iloc[ci, 5])
T_Ain_K = float(df.iloc[ci, 28]) + 273.15
P_Ain = P_atm + float(df.iloc[ci, 30])
dP_exp = float(df.iloc[ci, 30]) - float(df.iloc[ci, 31])
rho_A = air_density(T_Ain_K, P_Ain); mu_A = air_viscosity(T_Ain_K)
u_A = m_air / (rho_A * A_FLOW)

K_pred, cF_pred = predict_K_cF(TPMS, L_CELL, T_WALL, EPS/2.0)
G = m_air / A_FLOW
C = mu_A*G/K_pred + cF_pred*G**2
P_out_sq = P_Ain**2 - 2*R_AIR*T_Ain_K*C*L_DOM
P_out_est = float(np.sqrt(max(P_out_sq, 1e4)))

print(f"=== Shanghai Case {CASE} 近壁加密网格对比 ===")
print(f"Domain: {L_DOM*1000:.0f}×{H_DOM*1000:.0f} mm, u={u_A:.2f} m/s, T={T_Ain_K:.1f} K")
print(f"K={K_pred:.3e}, c_F={cF_pred:.1f}")
print(f"δ_B (Forchheimer): {np.sqrt((mu_A/EPS)/(rho_A*cF_pred*u_A))*1000:.3f} mm")
print(f"dP_exp = {dP_exp:.0f} Pa")
print()


def run_and_profile(label, dx_arr_cross=None):
    """用给定的 cross-stream dx_arr 跑 SIMPLE Case 8。
    SIMPLE 的 x 轴 = 实际 y（cross-stream），Nx_sim = N_Y = cell 数"""
    if dx_arr_cross is None:
        Nx_sim = N_Y
        label_cells = f"uniform {Nx_sim} cells"
    else:
        Nx_sim = len(dx_arr_cross)
        label_cells = f"refined {Nx_sim} cells"

    t0 = time.time()
    sA = SIMPLESolver(
        H_DOM, L_DOM, Nx_sim, N_X, TPMS, L_CELL, T_WALL,
        EPS, R_H, rho_A, mu_A, T_Ain_K,
        0.0, H_DOM, u_A,
        outlet_lo=0.0, outlet_hi=H_DOM,
        P_ref_abs=P_out_est,
        wall_refine=False,  # manually managed grid via override
    )
    # 覆盖 cross-stream 网格（full-width inlet/outlet 下 inlet_frac/outlet_frac 仍全为 1）
    if dx_arr_cross is not None:
        sA.dx_arr = dx_arr_cross.copy()
    converged, n_iter = sA.solve(max_iter=3000, tol=1e-4, verbose=False)
    t_solve = time.time() - t0

    # 提取 dP
    wI = sA.inlet_frac; wO = sA.outlet_frac
    mI = wI > 0.01; mO = wO > 0.5
    dP = float(np.average(sA.P[mI, 0], weights=wI[mI])
             - np.average(sA.P[mO, -1], weights=wO[mO]))

    # x=L/2 处 u 剖面
    j_mid = N_X // 2
    v_mid = 0.5 * (sA.v[:, j_mid] + sA.v[:, j_mid + 1])

    # y 坐标（cell center）
    dx_a = sA.dx_arr
    y_edges = np.concatenate([[0.0], np.cumsum(dx_a)])
    y_centers = (y_edges[:-1] + y_edges[1:]) / 2

    print(f"--- {label} ({label_cells}) ---")
    print(f"  converged: {converged}, iters: {n_iter}, time: {t_solve:.1f}s")
    print(f"  dP = {dP:.0f} Pa (err vs exp: {(dP-dP_exp)/dP_exp*100:+.1f}%)")
    print(f"  u_avg = {v_mid.mean():.2f} m/s, u_min/max = {v_mid.min():.2f}/{v_mid.max():.2f}")

    # 打印近壁 10 格 u 剖面
    print(f"  近下壁 10 格 u(y):")
    for k in range(min(10, len(y_centers))):
        y_mm = y_centers[k] * 1000
        dx_mm = dx_a[k] * 1000
        u_here = v_mid[k]
        rel = u_here / v_mid.mean()
        print(f"    i={k:2d}  y={y_mm:6.3f}mm  cell={dx_mm:6.4f}mm  u={u_here:.3f}  u/u_avg={rel:.4f}")

    return dP, n_iter, t_solve, v_mid, y_centers, dx_a


# 跑 uniform
dP_u, n_u, t_u, v_u, y_u, dx_u = run_and_profile("A. Uniform")
print()

# 跑 refined
dx_refined = build_wall_refined_1d(H_DOM, N_bulk=55, n_refine=8, first_cell=0.02e-3, growth=1.8)
print(f"Refined grid: {len(dx_refined)} cells total")
print(f"  最小 cell: {dx_refined.min()*1000:.4f} mm")
print(f"  最大 cell: {dx_refined.max()*1000:.4f} mm")
print(f"  近壁前 4 层: {dx_refined[:4]*1000}")
print()
dP_r, n_r, t_r, v_r, y_r, dx_r = run_and_profile("B. Wall-refined", dx_refined)
print()

# 对比
print("=" * 60)
print("对比")
print("=" * 60)
print(f"              uniform        refined         Δ")
print(f"  Cells:      {len(dx_u):>3}           {len(dx_r):>3}")
print(f"  min cell:   {dx_u.min()*1000:.4f} mm   {dx_r.min()*1000:.4f} mm   {dx_r.min()/dx_u.min():.1%}")
print(f"  dP (Pa):    {dP_u:.0f}          {dP_r:.0f}          {dP_r-dP_u:+.0f} ({(dP_r-dP_u)/dP_u*100:+.2f}%)")
print(f"  iters:      {n_u:>3}           {n_r:>3}")
print(f"  time (s):   {t_u:.1f}          {t_r:.1f}          {t_r/t_u:.2f}x")
print(f"  vs exp err: {(dP_u-dP_exp)/dP_exp*100:+.1f}%      {(dP_r-dP_exp)/dP_exp*100:+.1f}%")
print()

# BL 可见性诊断
print("BL 可见性（refined 网格第一格 vs bulk）：")
bulk_u = v_r[len(dx_r)//4 : 3*len(dx_r)//4].mean()
edge_u = v_r[0]
print(f"  bulk u (中间 50%): {bulk_u:.3f} m/s")
print(f"  edge u (第一格):   {edge_u:.3f} m/s")
print(f"  衰减:              {(1-edge_u/bulk_u)*100:.2f}%")
