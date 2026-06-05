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


def _count_interface(a: np.ndarray, b: np.ndarray) -> int:
    """数 a-区 与 b-区 相邻的体素面数（每面一次，三轴求和）。"""
    n = 0
    for ax in range(3):
        sl0 = [slice(None)] * 3
        sl1 = [slice(None)] * 3
        sl0[ax] = slice(None, -1)
        sl1[ax] = slice(1, None)
        s0, s1 = tuple(sl0), tuple(sl1)
        n += int(np.sum(a[s0] & b[s1])) + int(np.sum(b[s0] & a[s1]))
    return n


def a0_sides(phi: np.ndarray, C: float, delta: float, L_m: float, N: int):
    """per-side 单侧比表面积 [1/m]。

    A0_side = F_side · dx² / (L³ · corr)，F_side = solid↔void_side 面数（每面一次）。
    δ=0 时 A0_A == A0_B == tpms_geometry._A0_from_C（无额外 ÷2；F_side=F_total/2，
    抵消了 _A0_from_C 里的 /2）。返回 (A0_A, A0_B)。
    """
    solid = (phi >= (delta - C)) & (phi <= (delta + C))
    void_A = phi < (delta - C)
    void_B = phi > (delta + C)
    dx = L_m / N
    norm = (L_m ** 3) * _AREA_CORRECTION
    A0_A = _count_interface(solid, void_A) * dx ** 2 / norm
    A0_B = _count_interface(solid, void_B) * dx ** 2 / norm
    return A0_A, A0_B


def dh_sides(phi: np.ndarray, C: float, delta: float, L_m: float, N: int):
    """per-side 水力直径 [m]：D_h = 4·ε_side / A0_side（教科书 4，单股 sheet）。

    返回 (Dh_A, Dh_B)。δ=0 时与 tpms_geometry.compute_geometry 的 D_h 一致。
    """
    eps_A, eps_B, _ = eps_sides(phi, C, delta)
    A0_A, A0_B = a0_sides(phi, C, delta, L_m, N)
    Dh_A = 4.0 * eps_A / A0_A if A0_A > 0 else 0.0
    Dh_B = 4.0 * eps_B / A0_B if A0_B > 0 else 0.0
    return Dh_A, Dh_B
