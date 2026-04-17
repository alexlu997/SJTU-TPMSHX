"""
test_optimizer_dP_heterogeneous.py — 验证异质设计下 Task 3 的修复

构造一个非均匀设计（inlet 用 L=4 强化换热、outlet 用 L=8 降压损），
确认 optimizer 的 SIMPLE+zone 投影给出与直接调用一致的 dP 物理行为。
"""
import os, sys, warnings
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.tpms_calc import geometry as tpms_geometry
from optimization import optimizer

TPMS = 'Gyroid'
L0 = 6.0; T0 = 0.4
K_S = 16.0
u_A = 10.0; u_B = 10.0
T_inA = 350.0; T_inB = 300.0
L_DOM = 0.10; H_DOM = 0.05

# 均匀设计
x_uniform = np.array([L0, T0] * 18)

# 异质设计：inlet 用 L=4（小孔，阻力大），outlet 用 L=8（大孔，阻力小），中间 uniform L=6
x_hetero = np.array([4.0, 0.4] * 9 + [8.0, 0.4] * 9)

cfg = {
    'L_domain': L_DOM, 'H_domain': H_DOM,
    'tpms_type': TPMS, 'k_s': K_S,
    'u_A': u_A, 'u_B': u_B,
    'T_inA': T_inA, 'T_inB': T_inB,
    'L0': L0, 't0': T0,
    'y_trans': 0.2,
    'dir_A': 0, 'dir_B': 3,
    'use_continuous': False,  # grid_cells 路径
    'cp_f': 1007.0, 'rho_s': 2700.0,
    'pipe_frac_A': 1.0, 'pipe_frac_B': 1.0,
}

print("=" * 60)
print("均匀设计（全 L=6, t=0.4）")
print("=" * 60)
optimizer._clear_simple_cache()
Q_neg, dP_u, mass = optimizer.evaluate(x_uniform, config=cfg)
print(f"  Q = {-Q_neg:.1f} W")
print(f"  dP = {dP_u:.1f} Pa")
print(f"  mass = {mass:.4f} kg")

print()
print("=" * 60)
print("异质设计（inlet L=4 强化，outlet L=8 降压损）")
print("=" * 60)
optimizer._clear_simple_cache()
Q_neg, dP_h, mass = optimizer.evaluate(x_hetero, config=cfg)
print(f"  Q = {-Q_neg:.1f} W")
print(f"  dP = {dP_h:.1f} Pa")
print(f"  mass = {mass:.4f} kg")

print()
print("=" * 60)
print("对比")
print("=" * 60)
print(f"  均匀 dP (全 L=6): {dP_u:.1f} Pa")
print(f"  异质 dP (L=4+L=8): {dP_h:.1f} Pa")
print(f"  比值 = {dP_h / dP_u:.3f}")
print()

# 物理判断
# L=4 的 c_F 是 L=6 的 ~3x（训练数据显示 1249→535）
# L=8 的 c_F 只有 L=6 的 ~35%（535→187）
# 异质设计 = 50% L=4 + 50% L=8，c_F 加权平均约 (1249+187)/2 ≈ 718
# 均匀 L=6 c_F ≈ 535
# 异质预期 dP 应该比均匀高（因为 c_F 加权平均高），但不多
# 又因为 L=4 D_h 更小，u 更大，流向积分贡献也变化
print("物理预期：")
print("  异质设计 L=4 段 c_F ≈ 1249（大阻力），L=8 段 c_F ≈ 187（小阻力）")
print("  加权平均 c_F ≈ 718（高于均匀 L=6 的 535）")
print(f"  因此异质 dP 应该略高于均匀 → 实测比值 {dP_h/dP_u:.2f}")
print()
print("如果比值明显 >1，说明 zone 投影正常工作")
print("如果接近 1，说明投影可能有问题（全部按 L_avg 计算忽略了非线性）")
