"""物性模型 const/mean: const=入口温(默认), mean=均温 2-pass。

const 必须与历史一致 (回归); mean 在大 ΔT 改变结果、小 ΔT 收敛回 const;
prop_model 须穿过 solve_Lx 且二分仍收敛。"""
from __future__ import annotations
from design.cases import DesignCase
from design.forward import forward


def _case(dT):  # 单工况空气-空气, 可调热侧温降 ΔT
    return DesignCase(1, "air", 900., 4e5, 0.05, "air", 300., 4e5, 0.05,
                      None, 0.08, 0.08, dT=dT)


def test_const_is_default_and_unchanged():
    c = _case(300.)
    r0 = forward(c, "Diamond", 7., 0.5, 0.084, 0.084, "cross")
    r1 = forward(c, "Diamond", 7., 0.5, 0.084, 0.084, "cross", prop_model="const")
    assert r0.T_out_hot == r1.T_out_hot          # 默认 == const


def test_mean_differs_for_large_dT():
    c = _case(300.)
    rc = forward(c, "Diamond", 7., 0.5, 0.084, 0.084, "cross", prop_model="const")
    rm = forward(c, "Diamond", 7., 0.5, 0.084, 0.084, "cross", prop_model="mean")
    assert abs(rm.T_out_hot - rc.T_out_hot) > 0.1   # mean 确改变结果


def test_mean_approx_const_for_small_dT():
    # forward 按几何解实际物理 (case.dT 只是 sizing 目标, forward 不用)。
    # 短 Lx=1mm → 实际 ΔT 小 (~29K) → film≈inlet → mean 收敛回 const。
    c = _case(300.)
    rc = forward(c, "Diamond", 7., 0.5, 0.084, 0.001, "cross", prop_model="const")
    rm = forward(c, "Diamond", 7., 0.5, 0.084, 0.001, "cross", prop_model="mean")
    assert abs(rm.T_out_hot - rc.T_out_hot) < 0.5  # 小 ΔT 收敛到一致


def test_mean_threads_solve_Lx_and_converges():
    from design.sizing import solve_Lx
    c = _case(300.)
    Lx, r = solve_Lx(c, "Diamond", 7., 0.5, 0.084, "cross", prop_model="mean")
    assert Lx is not None                          # mean 下二分收敛
