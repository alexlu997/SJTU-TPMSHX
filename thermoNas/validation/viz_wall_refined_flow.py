"""
viz_wall_refined_flow.py — Shanghai Case 8 加密网格下的速度场可视化

输出：
  1. 全域 u(x,y) 2D 分布图
  2. 近下壁放大图（y ∈ [0, 1mm]）展示 BL 细节
  3. x=L/2 横截面 u(y) 剖面
  4. 压力场 P(x,y) 分布

保存 PNG 到 data/plots/
"""
import os, sys, warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

mpl.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial']
mpl.rcParams['axes.unicode_minus'] = False

from solvers.tpms_calc import (
    geometry as tpms_geometry, air_density, air_viscosity, P_atm,
)
from solvers.simple_solver import SIMPLESolver
from df_fit.predict import predict_K_cF

R_AIR = 287.05


def build_wall_refined_1d(W, N_bulk, n_refine=8, first_cell=0.02e-3, growth=1.8):
    refine_sizes = np.array([first_cell * growth**k for k in range(n_refine)], dtype=np.float64)
    total_refine = 2.0 * refine_sizes.sum()
    bulk_width = W - total_refine
    bulk = np.full(N_bulk, bulk_width / N_bulk, dtype=np.float64)
    dx = np.concatenate([refine_sizes, bulk, refine_sizes[::-1]])
    return dx


# ── Shanghai Case 8 ──
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

# ── Build refined mesh (cross-stream only) ──
dx_refined = build_wall_refined_1d(H_DOM, N_bulk=55, n_refine=8, first_cell=0.02e-3, growth=1.8)
Nx_sim = len(dx_refined)
print(f"Refined cross-stream mesh: {Nx_sim} cells")
print(f"  min cell: {dx_refined.min()*1000:.4f} mm")
print(f"  max cell: {dx_refined.max()*1000:.4f} mm")
print(f"  理论 δ_B (Forch) = {np.sqrt((mu_A/EPS)/(rho_A*cF_pred*u_A))*1000:.3f} mm")

# Run SIMPLE with refined grid
sA = SIMPLESolver(
    H_DOM, L_DOM, Nx_sim, N_X, TPMS, L_CELL, T_WALL,
    EPS, R_H, rho_A, mu_A, T_Ain_K,
    0.0, H_DOM, u_A,
    outlet_lo=0.0, outlet_hi=H_DOM,
    closure='df', P_ref_abs=P_out_est,
    wall_refine=False,  # manually providing refined grid via dx_arr override
)
sA.dx_arr = dx_refined.copy()
conv, n_it = sA.solve(max_iter=3000, tol=1e-4, verbose=False)
print(f"SIMPLE: conv={conv}, iters={n_it}")

# Extract cell-centered streamwise velocity v (shape Nx_sim, N_X)
v_cc = 0.5 * (sA.v[:, :-1] + sA.v[:, 1:])  # (Nx_sim, N_X) = (cross, stream)
P_cc = sA.P                                  # (Nx_sim, N_X)

# Cell-center coords
y_edges = np.concatenate([[0.0], np.cumsum(dx_refined)])
y_centers_mm = 1000 * (y_edges[:-1] + y_edges[1:]) / 2

x_edges = np.concatenate([[0.0], np.cumsum(sA.dy_arr)])
x_centers_mm = 1000 * (x_edges[:-1] + x_edges[1:]) / 2

# dP from P field
wI = sA.inlet_frac; wO = sA.outlet_frac
mI = wI > 0.01; mO = wO > 0.5
dP_sim = float(np.average(sA.P[mI, 0], weights=wI[mI])
             - np.average(sA.P[mO, -1], weights=wO[mO]))
print(f"dP_sim = {dP_sim:.0f} Pa (exp {dP_exp:.0f}, err {(dP_sim-dP_exp)/dP_exp*100:+.1f}%)")

# ────────────────────────────────────────────────────────────────
# 绘图
# ────────────────────────────────────────────────────────────────
os.makedirs(r'D:\Postgraduate\均质化\ThermoNAS\data\plots', exist_ok=True)

fig = plt.figure(figsize=(14, 10))
gs = fig.add_gridspec(3, 2, height_ratios=[1, 1, 1], hspace=0.4, wspace=0.3)

# ── (1) 全域 u(x,y) 热图 ──
ax1 = fig.add_subplot(gs[0, :])
X_mesh, Y_mesh = np.meshgrid(x_centers_mm, y_centers_mm)
im1 = ax1.pcolormesh(X_mesh, Y_mesh, v_cc, cmap='viridis', shading='auto')
plt.colorbar(im1, ax=ax1, label='u (m/s)')
ax1.set_xlabel('streamwise x (mm)')
ax1.set_ylabel('cross-stream y (mm)')
ax1.set_title(f'Shanghai Case {CASE}: 全域流向速度 u(x, y)\n'
              f'加密网格 {Nx_sim}×{N_X}, min cell={dx_refined.min()*1000:.3f}mm, dP_sim={dP_sim:.0f} Pa (err {(dP_sim-dP_exp)/dP_exp*100:+.1f}%)')
ax1.set_aspect('equal')

# ── (2) 近下壁放大图 u(x, y<3mm) ──
ax2 = fig.add_subplot(gs[1, 0])
y_zoom_mask = y_centers_mm < 3.0
im2 = ax2.pcolormesh(X_mesh[y_zoom_mask, :], Y_mesh[y_zoom_mask, :], v_cc[y_zoom_mask, :],
                     cmap='viridis', shading='auto')
plt.colorbar(im2, ax=ax2, label='u (m/s)')
ax2.set_xlabel('streamwise x (mm)')
ax2.set_ylabel('y (mm)')
ax2.set_title('近下壁放大 (y < 3mm)：BL 结构')
# 画网格线展示加密
for y_edge in y_edges[:-1]*1000:
    if y_edge < 3.0:
        ax2.axhline(y_edge, color='white', lw=0.2, alpha=0.5)

# ── (3) x=L/2 横截面 u(y) 剖面 ──
ax3 = fig.add_subplot(gs[1, 1])
j_mid = N_X // 2
u_profile = v_cc[:, j_mid]
ax3.plot(u_profile, y_centers_mm, 'b-o', ms=2, lw=0.8)
ax3.set_xlabel('u (m/s)')
ax3.set_ylabel('y (mm)')
ax3.set_title(f'x=L/2 横截面 u(y) 剖面')
ax3.grid(True, alpha=0.3)
ax3.axhline(H_DOM*1000, color='red', ls='--', label='上壁')
ax3.axhline(0, color='red', ls='--', label='下壁')
ax3.legend(loc='center right')

# ── (4) 近下壁放大剖面（y<1mm）──
ax4 = fig.add_subplot(gs[2, 0])
near_wall_mask = y_centers_mm < 1.0
ax4.plot(u_profile[near_wall_mask], y_centers_mm[near_wall_mask], 'g-o', ms=4, lw=1.2)
ax4.axhline(0, color='red', ls='--', label='下壁 (u=0)')
ax4.set_xlabel('u (m/s)')
ax4.set_ylabel('y (mm)')
ax4.set_title('近下壁 BL 剖面 (y<1mm): u 从 0 过渡到 bulk ~27 m/s')
ax4.grid(True, alpha=0.3)
ax4.legend()
# 标注理论 δ_B
delta_B = np.sqrt((mu_A/EPS)/(rho_A*cF_pred*u_A)) * 1000
ax4.axhline(delta_B, color='orange', ls=':', lw=1.5, label=f'理论 δ_B={delta_B:.3f}mm')
ax4.legend()

# ── (5) 压力场 ──
ax5 = fig.add_subplot(gs[2, 1])
P_abs = P_cc + sA.P_ref_abs  # absolute pressure
im5 = ax5.pcolormesh(X_mesh, Y_mesh, P_abs/1000, cmap='RdBu_r', shading='auto')
plt.colorbar(im5, ax=ax5, label='P (kPa)')
ax5.set_xlabel('x (mm)')
ax5.set_ylabel('y (mm)')
ax5.set_title(f'绝对压力 P(x, y) 分布\n进口 {(P_abs[:,0].mean()/1000):.1f} kPa → 出口 {(P_abs[:,-1].mean()/1000):.1f} kPa')
ax5.set_aspect('equal')

plt.suptitle(f'Shanghai Case 8 (Re={rho_A*u_A*D_H/mu_A:.0f}): 近壁加密网格下的 2D 流场诊断', fontsize=14, y=0.995)

out_path = r'D:\Postgraduate\均质化\ThermoNAS\data\plots\wall_refined_case8.png'
plt.savefig(out_path, dpi=120, bbox_inches='tight')
print(f"\n已保存：{out_path}")
print()
print("数值摘要：")
print(f"  u_bulk (中心) = {u_profile[Nx_sim//2]:.2f} m/s")
print(f"  u_edge (第1格) = {u_profile[0]:.3f} m/s")
print(f"  u_edge/u_bulk = {u_profile[0]/u_profile[Nx_sim//2]*100:.1f}%")
print(f"  BL 形状（近下壁前 5 格）:")
for k in range(5):
    print(f"    y={y_centers_mm[k]:.4f}mm  u={u_profile[k]:.3f} m/s  u/u_bulk={u_profile[k]/u_profile[Nx_sim//2]*100:.1f}%")
