"""
diag_near_wall_BL.py — 检查域外壁 Brinkman 边界层在 SIMPLE 解中的数值可见性

Shanghai Case 8 (中 Re)。在 x=L/2 处提取 u 的横向分布，看：
1. bulk 是否均匀（plug flow）
2. 最靠近壁 1-3 格是否有速度衰减（数值可分辨的 BL 痕迹）
3. 算边界层厚度理论估计 vs 实际网格分辨
"""
import os, sys, warnings
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
rho_A = air_density(T_Ain_K, P_Ain); mu_A = air_viscosity(T_Ain_K)
u_A = m_air / (rho_A * A_FLOW)

K_pred, cF_pred = predict_K_cF(TPMS, L_CELL, T_WALL, EPS/2.0)
G = m_air / A_FLOW
C = mu_A*G/K_pred + cF_pred*G**2
P_out_sq = P_Ain**2 - 2*R_AIR*T_Ain_K*C*L_DOM
P_out_est = float(np.sqrt(max(P_out_sq, 1e4)))

print(f"=== Shanghai Case {CASE} 域外壁 Brinkman BL 诊断 ===")
print(f"Grid: Nx={N_X} × Ny={N_Y}")
print(f"Domain: {L_DOM*1000:.0f}×{H_DOM*1000:.0f} mm")
print(f"Cell size (cross-stream, real y): {H_DOM/N_Y*1000:.3f} mm")
print(f"u_A = {u_A:.2f} m/s, T = {T_Ain_K:.1f} K")
print(f"K = {K_pred:.3e}, c_F = {cF_pred:.1f}")
print()

# 理论 BL 厚度
mu_eff_val = mu_A / EPS
delta_Darcy = np.sqrt(K_pred / EPS)
delta_Forch = np.sqrt(mu_eff_val / (rho_A * cF_pred * u_A))
print(f"理论 Brinkman BL 厚度：")
print(f"  Darcy 主导: δ = sqrt(K/ε) = {delta_Darcy*1000:.3f} mm")
print(f"  Forchheimer 主导: δ = sqrt(μ_eff/(ρ·c_F·u)) = {delta_Forch*1000:.3f} mm")
print(f"  网格单元: {H_DOM/N_Y*1000:.3f} mm")
print(f"  BL/cell 比: Darcy {delta_Darcy/(H_DOM/N_Y):.2f}, Forch {delta_Forch/(H_DOM/N_Y):.2f}")
print()

# 跑 SIMPLE (等温)
sA = SIMPLESolver(
    H_DOM, L_DOM, N_Y, N_X, TPMS, L_CELL, T_WALL,
    EPS, R_H, rho_A, mu_A, T_Ain_K,
    0.0, H_DOM, u_A,
    outlet_lo=0.0, outlet_hi=H_DOM,
    closure='df', P_ref_abs=P_out_est,
)
sA.solve(max_iter=3000, tol=1e-4, verbose=False)

# SIMPLE 内部坐标：
#   sA.u shape = (Nx+1=N_Y+1, Ny=N_X)  — x-face velocities (cross-stream)
#   sA.v shape = (Nx=N_Y, Ny+1=N_X+1)  — y-face velocities (streamwise, real x)
# SIMPLE's x-axis (Nx) = real y (cross-stream, from 0 to H_DOM)
# SIMPLE's y-axis (Ny) = real x (streamwise, from 0 to L_DOM)
# 所以 sA.v[i, j] 其中 i 是 real y 索引 (0..N_Y-1), j 是 real x 索引 (0..N_X)

# 取 x = L_DOM/2 处的 streamwise 速度剖面（沿 real y）
j_mid = N_X // 2  # 中段 real x 索引
# Cell-centered v 沿 real y (索引 i, 即 SIMPLE 的 Nx 方向, 长度 N_Y)
v_mid_profile = 0.5 * (sA.v[:, j_mid] + sA.v[:, j_mid + 1])  # length N_Y
# v_mid_profile 就是 x=L/2 处沿 real y 的流向速度分布

print(f"流向速度 u(y) 在 x=L/2 处的横截面剖面：")
print(f"(real y=0 是域下壁，real y=H_DOM={H_DOM*1000:.0f}mm 是域上壁)")
print()
print(f"{'i':>3} {'y(mm)':>8} {'u(m/s)':>10} {'u/u_avg':>10}  {'bar':<50}")

u_avg = v_mid_profile.mean()
u_max = v_mid_profile.max()
dy_cell = H_DOM / N_Y
for i in range(N_Y):
    y_mm = (i + 0.5) * dy_cell * 1000
    u_here = v_mid_profile[i]
    u_rel = u_here / u_avg
    bar_len = int(50 * u_here / max(u_max, 1e-6))
    bar = '█' * bar_len
    # 标出最近壁 3 格
    marker = ''
    if i < 3:
        marker = '← 近下壁'
    elif i >= N_Y - 3:
        marker = '← 近上壁'
    print(f"{i:>3} {y_mm:>8.2f} {u_here:>10.3f} {u_rel:>10.4f}  {bar:<50}  {marker}")

print()
print(f"统计：")
print(f"  u_avg = {u_avg:.3f} m/s (设定 {u_A:.3f})")
print(f"  u_max = {u_max:.3f} m/s (格 i={np.argmax(v_mid_profile)})")
print(f"  u_min = {v_mid_profile.min():.3f} m/s (格 i={np.argmin(v_mid_profile)})")
print(f"  u 相对变化 (max-min)/avg = {(u_max - v_mid_profile.min())/u_avg*100:.2f}%")

# 计算相对内部 bulk 的边缘衰减
bulk_avg = v_mid_profile[N_Y//4 : 3*N_Y//4].mean()
edge_attenuation_bot = 1.0 - v_mid_profile[0] / bulk_avg
edge_attenuation_top = 1.0 - v_mid_profile[-1] / bulk_avg
print(f"  bulk (中间 50% 格) 平均 = {bulk_avg:.3f} m/s")
print(f"  下壁第一格衰减 = {edge_attenuation_bot*100:.2f}%")
print(f"  上壁第一格衰减 = {edge_attenuation_top*100:.2f}%")

print()
print("=== 解释 ===")
if max(abs(edge_attenuation_bot), abs(edge_attenuation_top)) < 0.005:
    print("近壁格衰减 < 0.5%，BL 数值上不可见（完全被网格离散化平均掉）")
    print("理论 BL 厚度 ~0.05 mm << 网格 0.69 mm，符合预期")
else:
    print("近壁格有可见衰减，数值上捕捉到了部分 BL 效应")
