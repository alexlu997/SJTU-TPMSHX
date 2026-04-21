"""
test_2d_zone_dP.py — 2D 分区 + 渐变几何端到端验证

Step 1: 2-zone Gyroid (y 上半 L=5, 下半 L=8) + SIMPLE 检查 _K_arr/_cF_arr
Step 2: sigmoid 渐变 L(y) 从 5 → 8 的 K/c_F 投影一致性
Step 3: 混合 TPMS 类型（Gyroid + Diamond 分区）—— 预期发现 tpms_type 单标量限制
"""
import os, sys, warnings
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.simple_solver import SIMPLESolver
from solvers.zone_config import Zone, ZoneConfig
from solvers.tpms_calc import geometry as tpms_geometry, air_density, air_viscosity, P_atm
from df_fit.surrogate_v3 import SurrogateV3
from df_fit.predict import predict_K_cF

R_AIR = 287.05

# ────────────────────────────────────────────────────────────────
# Step 1: 2-zone SIMPLE + v3 (Gyroid, y 上半 L=5, 下半 L=8)
# ────────────────────────────────────────────────────────────────
print("=" * 60)
print("Step 1: 2-zone Gyroid SIMPLE + SurrogateV3")
print("=" * 60)

TPMS = 'Gyroid'; K_S = 16.0
t_mm = 0.4
# 2 zones
zone_top = Zone(name='top', y_frac_start=0.5, y_frac_end=1.0, L_mm=5.0, t_mm=t_mm)
zone_bot = Zone(name='bot', y_frac_start=0.0, y_frac_end=0.5, L_mm=8.0, t_mm=t_mm)
zc = ZoneConfig(zones=[zone_bot, zone_top], tpms_type=TPMS, k_s=K_S)

u_air, T_in = 10.0, 300.0
rho_val = air_density(T_in, P_atm); mu_val = air_viscosity(T_in)
zc.compute_properties(u_A=u_air, u_B=u_air, T_inA=T_in, T_inB=T_in, P_in=P_atm)

# 用 L=5 的 geometry 作为 baseline 传入 SIMPLE (实际会被 zone_config override)
g_base = tpms_geometry(TPMS, 5.0, t_mm, K_S)
eps_base = g_base['epsilon']; r_h_base = g_base['D_h'] / 2

L_DOM = 0.06; H_DOM = 0.04
Nx_s = 30; Ny_s = 20

# 1D P² 初猜 (粗略，用 L=6.5 平均)
K_mid, cF_mid = predict_K_cF(TPMS, 6.5, t_mm, (zone_top.props_A['epsilon']+zone_bot.props_A['epsilon'])/4.0)
G = rho_val * u_air
C = mu_val * G / K_mid + cF_mid * G**2
P_out_sq = P_atm**2 - 2 * R_AIR * T_in * C * L_DOM
P_out_est = float(np.sqrt(max(P_out_sq, 1e4)))

sA = SIMPLESolver(
    H_DOM, L_DOM, Ny_s, Nx_s, TPMS, 5.0, t_mm,  # baseline L=5 (被 zone_config 覆盖)
    eps_base, r_h_base, rho_val, mu_val, T_in,
    0.0, H_DOM, u_air,
    outlet_lo=0.0, outlet_hi=H_DOM,
    P_ref_abs=P_out_est,
    zone_config=zc,  # 关键：传入 zone_config
)

# 检查 _K_arr / _cF_arr
print(f"\nSIMPLE 网格: Nx={Nx_s}, Ny={Ny_s}")
print(f"SIMPLE _K_arr shape: {sA._K_arr.shape}")
print(f"SIMPLE _cF_arr shape: {sA._cF_arr.shape}")

# SIMPLE 的 Ny 对应 zone_config 的 y 轴
# 这里 SIMPLE 是标准坐标：W=H_DOM, H=L_DOM (传的是 Ny_s=Ny, Nx_s=Nx)
# 等一下——SIMPLE 的 y_frac 对应 zone_config 的 y_frac
# 让我看每一行的 L 到底 assign 的是什么
print()
print("每行的 L 来自哪个 zone（通过 _K_arr 值反查）:")
m_surr = SurrogateV3(TPMS)
K_top, cF_top = m_surr.predict(5.0, t_mm, zone_top.props_A['epsilon']/2.0)
K_bot, cF_bot = m_surr.predict(8.0, t_mm, zone_bot.props_A['epsilon']/2.0)
print(f"  zone top (y∈[0.5,1]): L=5, K={K_top:.3e}, c_F={cF_top:.2f}")
print(f"  zone bot (y∈[0,0.5]): L=8, K={K_bot:.3e}, c_F={cF_bot:.2f}")
print()

# SIMPLE's internal Ny = _K_arr shape[0] (here = Nx_s = 30 because of coord swap)
Ny_sim = sA._K_arr.shape[0]
wrong = 0
for j in range(Ny_sim):
    y_frac = (j + 0.5) / Ny_sim
    expected_K = K_top if y_frac >= 0.5 else K_bot
    expected_cF = cF_top if y_frac >= 0.5 else cF_bot
    K_ok = abs(sA._K_arr[j] - expected_K) / expected_K < 1e-6
    cF_ok = abs(sA._cF_arr[j] - expected_cF) / expected_cF < 1e-6
    if not (K_ok and cF_ok):
        wrong += 1
        print(f"  ✗ j={j:2d} y_frac={y_frac:.3f}: K_arr={sA._K_arr[j]:.3e} (exp {expected_K:.3e}), cF_arr={sA._cF_arr[j]:.1f} (exp {expected_cF:.1f})")

if wrong == 0:
    print(f"  ✓ 所有 {Ny_sim} 行 K/c_F 匹配 SurrogateV3 的区域预测")

# 跑 SIMPLE 看是否稳定收敛
print()
converged, n_iter = sA.solve(max_iter=3000, tol=1e-4, verbose=False)
print(f"SIMPLE 收敛: {converged}, 迭代 {n_iter} 步")
wI = sA.inlet_frac; wO = sA.outlet_frac
mI = wI > 0.01; mO = wO > 0.5
dP_2zone = float(np.average(sA.P[mI, 0], weights=wI[mI])
               - np.average(sA.P[mO, -1], weights=wO[mO]))
print(f"2-zone dP = {dP_2zone:.1f} Pa")

# 对比：全 L=5 和全 L=8 的 dP
sA_L5 = SIMPLESolver(
    H_DOM, L_DOM, Ny_s, Nx_s, TPMS, 5.0, t_mm,
    eps_base, r_h_base, rho_val, mu_val, T_in,
    0.0, H_DOM, u_air, outlet_lo=0.0, outlet_hi=H_DOM,
    P_ref_abs=P_out_est)
sA_L5.solve(max_iter=3000, tol=1e-4, verbose=False)
dP_L5 = float(np.average(sA_L5.P[mI, 0], weights=wI[mI]) - np.average(sA_L5.P[mO, -1], weights=wO[mO]))

g_L8 = tpms_geometry(TPMS, 8.0, t_mm, K_S)
sA_L8 = SIMPLESolver(
    H_DOM, L_DOM, Ny_s, Nx_s, TPMS, 8.0, t_mm,
    g_L8['epsilon'], g_L8['D_h']/2, rho_val, mu_val, T_in,
    0.0, H_DOM, u_air, outlet_lo=0.0, outlet_hi=H_DOM,
    P_ref_abs=P_out_est)
sA_L8.solve(max_iter=3000, tol=1e-4, verbose=False)
wI8 = sA_L8.inlet_frac; wO8 = sA_L8.outlet_frac
mI8 = wI8 > 0.01; mO8 = wO8 > 0.5
dP_L8 = float(np.average(sA_L8.P[mI8, 0], weights=wI8[mI8]) - np.average(sA_L8.P[mO8, -1], weights=wO8[mO8]))

print(f"  参考 全 L=5: dP = {dP_L5:.1f} Pa")
print(f"  参考 全 L=8: dP = {dP_L8:.1f} Pa")
print(f"  预期 2-zone dP 在 ({min(dP_L5, dP_L8):.0f}, {max(dP_L5, dP_L8):.0f}) 之间")
if min(dP_L5, dP_L8) <= dP_2zone <= max(dP_L5, dP_L8):
    print(f"  ✓ 2-zone dP 落在合理区间")
else:
    print(f"  ✗ 2-zone dP 不在合理区间")

# ────────────────────────────────────────────────────────────────
# Step 2: sigmoid 渐变 L(y) 投影一致性
# ────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("Step 2: sigmoid 渐变几何 → SIMPLE K/c_F 投影一致性")
print("=" * 60)

# 用 optimizer 的 _project_fields_to_streamwise_K_cF 做一次投影对比
from optimization.optimizer import _project_fields_to_streamwise_K_cF

Nx_f = 30; Ny_f = 40
# 构造简化 sigmoid L: y<0.5 → L=8, y>0.5 → L=5，过渡宽度 0.1
y_frac = np.linspace(0.5/Ny_f, 1 - 0.5/Ny_f, Ny_f)
x_frac = np.linspace(0.5/Nx_f, 1 - 0.5/Nx_f, Nx_f)
XF, YF = np.meshgrid(x_frac, y_frac, indexing='ij')  # (Nx_f, Ny_f)
L_field = 8.0 - 3.0 / (1.0 + np.exp(-20 * (YF - 0.5)))  # 8 → 5 as y goes 0→1
t_field = np.full_like(L_field, 0.4)

# 投影到 SIMPLE 的 Ny 轴（fluid A 方向，streamwise = x）
# 对 fluid A，投影是沿 y 平均 → 每个 x 一个 L 值 → 重采样到 Ny_sim
# 对 fluid B，投影是沿 x 平均 → 每个 y 一个 L 值，然后翻转
K_A, cF_A = _project_fields_to_streamwise_K_cF(
    L_field, t_field, TPMS, K_S, Nx_f, Ny_f, Ny_sim=30, fluid='A')
K_B, cF_B = _project_fields_to_streamwise_K_cF(
    L_field, t_field, TPMS, K_S, Nx_f, Ny_f, Ny_sim=30, fluid='B')

print(f"Fluid A (+x 流向): K_A range=[{K_A.min():.3e}, {K_A.max():.3e}], cF_A range=[{cF_A.min():.1f}, {cF_A.max():.1f}]")
print(f"   — L_field 沿 y 均匀所以沿 x 也均匀，K_A 应几乎常数")
print(f"   — K_A std / K_A mean = {K_A.std() / K_A.mean():.3e}")
if K_A.std() / K_A.mean() < 0.01:
    print(f"   ✓ Fluid A 投影给出均匀 K (因 L_field 沿 x 不变)")

print()
print(f"Fluid B (-y 流向): K_B range=[{K_B.min():.3e}, {K_B.max():.3e}], cF_B range=[{cF_B.min():.1f}, {cF_B.max():.1f}]")
print(f"   — L_field 沿 y 从 8 → 5，投影后 cF_B 应从 L=5（高 cF）过渡到 L=8（低 cF）")
print(f"   — (SIMPLE y=0 对应 fluid B 的入口 = 实际 y=1 = L=5)")
# SIMPLE j=0 → L=5 (大 cF)，SIMPLE j=Ny-1 → L=8 (小 cF)
print(f"   — cF_B[0] = {cF_B[0]:.1f} (SIMPLE 入口，对应 L=5 区), cF_B[-1] = {cF_B[-1]:.1f} (SIMPLE 出口，对应 L=8 区)")
if cF_B[0] > cF_B[-1]:
    print(f"   ✓ Fluid B 投影方向正确（入口 L=5 段 cF 较大，出口 L=8 段 cF 较小）")

# ────────────────────────────────────────────────────────────────
# Step 3: 混合 TPMS 限制确认
# ────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("Step 3: 混合 TPMS 类型限制")
print("=" * 60)
print("""
SIMPLE.__init__() 的 tpms_type 参数是单标量，不支持分区混合 TPMS 类型
（例如上半 Gyroid、下半 Diamond）。

两种应对：
  (a) 扩展 predict_K_cF_vec 支持 per-row tpms_type 列表 — 如果优化器设计
      允许混合 TPMS；
  (b) 维持现状，文档声明优化器只做单 TPMS 类型优化（全 Gyroid 或全 Diamond）。

当前 optimizer.DEFAULT_CONFIG 的 tpms_type 是单值，推断采用方案 (b)。
""")

# 总结
print("=" * 60)
print("Task 2 总结")
print("=" * 60)
print(f"  2-zone SIMPLE K/c_F 加载正确性: {'✓' if wrong == 0 else '✗'}")
print(f"  2-zone SIMPLE 收敛稳定性: {'✓ ' if converged else '✗ '}")
print(f"  2-zone dP 落在合理区间: {'✓' if min(dP_L5, dP_L8) <= dP_2zone <= max(dP_L5, dP_L8) else '✗'}")
print(f"  sigmoid Fluid A 投影正确性: {'✓' if K_A.std() / K_A.mean() < 0.01 else '✗'}")
print(f"  sigmoid Fluid B 投影方向正确性: {'✓' if cF_B[0] > cF_B[-1] else '✗'}")
print(f"  混合 TPMS 限制: 方案 (b) 文档化")
