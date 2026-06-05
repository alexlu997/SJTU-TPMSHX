"""Phase 0 — 非对称孔隙率 offset-band 几何核 TDD。

只读复用 tpms_geometry；不碰生产路径。δ=0 必须退化回现状（见 Task 2 锚）。
"""
import numpy as np
import pytest

from solvers.asym_geometry import eps_sides
from solvers.tpms_geometry import _phi_grid

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
