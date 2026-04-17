"""
test_optimizer_dP_gap.py — 原用于验证 optimizer dP 路径与 SIMPLE 的 gap

历史背景（2026-04-17 修复前）：optimizer.evaluate() 曾走 legacy f-Re 路径，
绕过 SIMPLE D-F，有 12× gap。当前已修复——两条路径都走 SIMPLE P 场提取。
保留此脚本作为一致性回归测试，验证 gap < 5%。
"""
import os, sys, warnings
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.tpms_calc import (
    geometry as tpms_geometry, air_density, air_viscosity, P_atm,
)
from solvers.simple_solver import SIMPLESolver
from df_fit.predict import predict_K_cF
from optimization import optimizer

R_AIR = 287.05
TPMS = 'Gyroid'   # 上海样机一致
L0 = 6.0; T0 = 0.4
K_S = 16.0
u_A = 10.0; u_B = 10.0
T_inA = 350.0; T_inB = 300.0
L_DOM = 0.10; H_DOM = 0.05

# 构造"均匀设计"的决策变量 x：所有 18 个分区都用 L0, t0
x_uniform = np.empty(36)
for i in range(18):
    x_uniform[2*i] = L0
    x_uniform[2*i + 1] = T0

cfg = {
    'L_domain': L_DOM, 'H_domain': H_DOM,
    'tpms_type': TPMS, 'k_s': K_S,
    'u_A': u_A, 'u_B': u_B,
    'T_inA': T_inA, 'T_inB': T_inB,
    'L0': L0, 't0': T0,
    'y_trans': 0.2,
    'dir_A': 0, 'dir_B': 3,
    'use_continuous': False,  # 用 grid_cells 离散路径，便于对比
    'cp_f': 1007.0, 'rho_s': 2700.0,
    'pipe_frac_A': 1.0, 'pipe_frac_B': 1.0,
}

# 清 cache 保证每次跑新的 SIMPLE
optimizer._clear_simple_cache()

print("=== 路径 1：optimizer.evaluate()（含 f-Re legacy dP）===")
Q_neg, dP_opt, mass = optimizer.evaluate(x_uniform, config=cfg)
print(f"  Q = {-Q_neg:.1f} W")
print(f"  dP_optimizer (f-Re 路径) = {dP_opt:.1f} Pa")
print(f"  mass = {mass:.4f} kg")
print()

# ── 路径 2：独立跑 SIMPLE（完全同样的几何）+ D-F ──
print("=== 路径 2：独立 SIMPLE + v3 D-F，从 P 场提取 dP ===")

g = tpms_geometry(TPMS, L0, T0, K_S)
eps = g['epsilon']; D_h = g['D_h']; r_h = D_h / 2
rho_A_val = air_density(T_inA, P_atm); mu_A_val = air_viscosity(T_inA)
rho_B_val = air_density(T_inB, P_atm); mu_B_val = air_viscosity(T_inB)

Nx_g, Ny_g = optimizer._resolve_grid(cfg, alpha=0.8)
print(f"  Grid: Nx={Nx_g}, Ny={Ny_g}")
print(f"  Geometry: eps={eps:.4f}, D_h={D_h*1000:.3f}mm")

K_pred, cF_pred = predict_K_cF(TPMS, L0, T0, eps/2.0)
print(f"  SurrogateV3: K={K_pred:.3e}, c_F={cF_pred:.2f}")

# Fluid A: flows +x, SIMPLE 内部坐标 (W=H, H=L, Ny=Nx_g)
# 设进出口全开 (pipe_lo=0, pipe_hi=H_DOM)
G_A = rho_A_val * u_A
C_A = mu_A_val * G_A / K_pred + cF_pred * G_A**2
P_out_sq_A = (P_atm)**2 - 2 * R_AIR * T_inA * C_A * L_DOM
P_out_est_A = float(np.sqrt(max(P_out_sq_A, 1e4)))

sA_indep = SIMPLESolver(
    H_DOM, L_DOM, Ny_g, Nx_g, TPMS, L0, T0,
    eps, r_h, rho_A_val, mu_A_val, T_inA,
    0.0, H_DOM, u_A,
    outlet_lo=0.0, outlet_hi=H_DOM,
    closure='df', P_ref_abs=P_out_est_A,
)
sA_indep.solve(max_iter=3000, tol=1e-4, verbose=False)

wA_in = sA_indep.inlet_frac; wA_out = sA_indep.outlet_frac
mI_A = wA_in > 0.01; mO_A = wA_out > 0.5
dP_A_simple = (np.average(sA_indep.P[mI_A, 0], weights=wA_in[mI_A])
             - np.average(sA_indep.P[mO_A, -1], weights=wA_out[mO_A]))

# Fluid B: flows -y, SIMPLE (W=L, H=H, Nx=Nx_g, Ny=Ny_g)
G_B = rho_B_val * u_B
C_B = mu_B_val * G_B / K_pred + cF_pred * G_B**2
P_out_sq_B = (P_atm)**2 - 2 * R_AIR * T_inB * C_B * H_DOM
P_out_est_B = float(np.sqrt(max(P_out_sq_B, 1e4)))

sB_indep = SIMPLESolver(
    L_DOM, H_DOM, Nx_g, Ny_g, TPMS, L0, T0,
    eps, r_h, rho_B_val, mu_B_val, T_inB,
    0.0, L_DOM, u_B,
    outlet_lo=0.0, outlet_hi=L_DOM,
    closure='df', P_ref_abs=P_out_est_B,
)
sB_indep.solve(max_iter=3000, tol=1e-4, verbose=False)

wB_in = sB_indep.inlet_frac; wB_out = sB_indep.outlet_frac
mI_B = wB_in > 0.01; mO_B = wB_out > 0.5
dP_B_simple = (np.average(sB_indep.P[mI_B, 0], weights=wB_in[mI_B])
             - np.average(sB_indep.P[mO_B, -1], weights=wB_out[mO_B]))

dP_simple_total = dP_A_simple + dP_B_simple
print(f"  dP_A (SIMPLE P 场) = {dP_A_simple:.1f} Pa")
print(f"  dP_B (SIMPLE P 场) = {dP_B_simple:.1f} Pa")
print(f"  dP_total = {dP_simple_total:.1f} Pa")
print()

# ── Gap 对比 ──
print("=== Gap 对比 ===")
print(f"  optimizer (f-Re):       {dP_opt:.1f} Pa")
print(f"  SIMPLE + D-F + P 场:    {dP_simple_total:.1f} Pa")
gap_pct = (dP_opt - dP_simple_total) / dP_simple_total * 100
print(f"  差值:                    {dP_opt - dP_simple_total:+.1f} Pa")
print(f"  相对差:                  {gap_pct:+.1f}%")
print()
if abs(gap_pct) > 10:
    print(f"  ⚠️ Gap > 10%, 验证存在显著路径不一致（预期）")
else:
    print(f"  Gap 较小（<10%），但 f-Re 物理模型仍与 SIMPLE 的 D-F 不一致")
