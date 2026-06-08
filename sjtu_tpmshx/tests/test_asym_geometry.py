"""Phase 0 — 非对称孔隙率 offset-band 几何核 TDD。

只读复用 tpms_geometry；不碰生产路径。δ=0 必须退化回现状（见 Task 2 锚）。
"""
import numpy as np
import pytest

from solvers.asym_geometry import (
    eps_sides, a0_sides, dh_sides, percolates_z, wall_thickness, find_delta_max,
)
from solvers.tpms_geometry import _phi_grid, compute_geometry, _C_from_tL

N = 64  # 测试用小网格（快）


def test_eps_sides_delta0_splits_evenly():
    phi = _phi_grid('Gyroid', N)
    C = 0.5
    eps_A, eps_B, eps = eps_sides(phi, C, delta=0.0)
    assert eps_A == pytest.approx(eps_B, rel=1e-9)      # 对称 → 均分
    assert eps == pytest.approx(eps_A + eps_B, rel=1e-12)


def test_eps_sides_positive_delta_grows_A():
    phi = _phi_grid('Gyroid', N)
    C = 0.5
    eps_A0, eps_B0, _ = eps_sides(phi, C, 0.0)
    eps_A1, eps_B1, eps1 = eps_sides(phi, C, 0.3)
    assert eps_A1 > eps_A0      # δ>0 → 得益侧 A 增大
    assert eps_B1 < eps_B0      # 挤压侧 B 减小


def test_eps_total_conserved_to_second_order():
    # ε(δ) 应在 δ=0 驻点：小 δ 漂移 << δ 本身
    phi = _phi_grid('Gyroid', N)
    C = 0.5
    _, _, e0 = eps_sides(phi, C, 0.0)
    _, _, e1 = eps_sides(phi, C, 0.1)
    assert abs(e1 - e0) / e0 < 0.02     # O(δ²) 微漂，<2%


def test_a0_sides_delta0_matches_compute_geometry():
    """δ=0 硬锚：per-side A0 必复现 compute_geometry 的单侧 A_0。"""
    L_mm, t_mm, Nf = 5.0, 0.4, 128
    phi = _phi_grid('Gyroid', Nf)
    C = _C_from_tL('Gyroid', t_mm / L_mm)
    L_m = L_mm / 1000.0
    A0_A, A0_B = a0_sides(phi, C, 0.0, L_m, Nf)
    ref = compute_geometry('Gyroid', L_mm, t_mm, Nf)['A_0']
    assert A0_A == pytest.approx(A0_B, rel=2e-2)        # 对称 → 两侧相等
    assert A0_A == pytest.approx(ref, rel=2e-2)         # 退化锚：== 单侧 A_0


def test_dh_sides_delta0_matches_compute_geometry():
    """δ=0 硬锚：per-side D_h 必复现 compute_geometry 的 D_h。"""
    L_mm, t_mm, Nf = 5.0, 0.4, 128
    phi = _phi_grid('Gyroid', Nf)
    C = _C_from_tL('Gyroid', t_mm / L_mm)
    L_m = L_mm / 1000.0
    Dh_A, Dh_B = dh_sides(phi, C, 0.0, L_m, Nf)
    ref = compute_geometry('Gyroid', L_mm, t_mm, Nf)['D_h']
    assert Dh_A == pytest.approx(ref, rel=3e-2)


def test_percolates_z_delta0_both_sides_open():
    """δ=0 两侧空腔都沿流向贯穿（双连通 sheet 拓扑）。"""
    phi = _phi_grid('Gyroid', N)
    C = 0.5
    assert percolates_z(phi < -C) is True
    assert percolates_z(phi > C) is True


def test_percolates_z_solid_block_is_false():
    """全固体 → 无通道 → 不贯穿。"""
    block = np.zeros((8, 8, 8), dtype=bool)
    assert percolates_z(block) is False


def test_wall_thickness_delta0_positive_subcell():
    """壁厚为正且薄于胞元。"""
    Nf = 128
    phi = _phi_grid('Gyroid', Nf)
    C = _C_from_tL('Gyroid', 0.4 / 5.0)
    L_m = 0.005
    t = wall_thickness(phi, C, 0.0, L_m, Nf)
    assert 0.0 < t < L_m


def test_find_delta_max_returns_positive_band():
    """δ=0 周围存在可行偏移带（壁=2C 常数，δ_max 纯连通极限）。"""
    phi = _phi_grid('Gyroid', N)
    C = 0.5
    dmax = find_delta_max(phi, C)
    assert dmax > 0.0
