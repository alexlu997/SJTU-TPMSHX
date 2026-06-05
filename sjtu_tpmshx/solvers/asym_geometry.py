"""
asym_geometry.py — 非对称孔隙率 PoC 核心（Phase 0）。

偏移等值面分相：固体带 solid = {δ−C ≤ φ ≤ δ+C}，δ 为中心偏移。
  void_A (得益, 气侧) = {φ < δ−C};  void_B (挤压, 液侧) = {φ > δ+C}
δ=0 退化为 tpms_geometry 的对称 50/50（见 tests）。

只读复用 tpms_geometry；不修改任何生产路径（Phase 2 才集成）。
计划：vault/reports/engineering/2026-06-05-asym-porosity-phase0-PLAN-CN.md
"""
import numpy as np

# 与 tpms_geometry._A0_from_C 内的体素面积校正常量一致（来源：该函数注释）。
_AREA_CORRECTION = 1.553


def eps_sides(phi: np.ndarray, C: float, delta: float = 0.0):
    """偏移带孔隙切分。返回 (eps_A, eps_B, eps_total)。

    eps_A = mean(phi < delta - C)  # 得益侧（大通道, 气侧）
    eps_B = mean(phi > delta + C)  # 挤压侧（小通道, 液侧）
    delta=0 时由 φ→−φ 对称给出 eps_A == eps_B == eps/2。
    """
    eps_A = float(np.mean(phi < (delta - C)))
    eps_B = float(np.mean(phi > (delta + C)))
    return eps_A, eps_B, eps_A + eps_B
