"""嵌套二分定尺: 内层 Lx (冷却), 外层 s (dP-active)。单模块 ≤ 450mm。"""
from __future__ import annotations
from dataclasses import dataclass

from .fluids import fluid_props
from .forward import forward, dP_fracs

S_MAX = 0.450          # build envelope [m]
LX_MAX = 0.450
N_MIN = 4              # 每向最少晶胞 (均质化)
BISECT_IT, TOL = 28, 1e-4

def t_target(case) -> float:
    """热侧出口温目标: 优先用温降 ΔT, 否则由换热量 Q 反推。"""
    if case.dT is not None:
        return case.T_in_h - case.dT
    cp_h = fluid_props(case.hot_fluid, case.T_in_h, case.P_in_h).cp
    return case.T_in_h - case.Q / (case.mdot_h * cp_h)

def solve_Lx(case, topo, l, t, s, arrangement, target=None):
    """二分 Lx ∈ (0, LX_MAX] 使 T_out_hot = target (T_out 随 Lx 单调↓)。
    warm-start: 用上一次解的 fields 续解, 大幅减 LTNE 迭代。
    返回 (Lx, ForwardResult)。不可达 (LX_MAX 仍欠冷) → (None, None)。"""
    tgt = target if target is not None else t_target(case)
    prev = {"f": None}
    def ev(Lx):
        r = forward(case, topo, l, t, s, Lx, arrangement, init=prev["f"])
        prev["f"] = r.fields                # 续解种子
        return r
    lo, hi = max(2.0 * l / 1000.0, 1e-3), LX_MAX
    r_hi = ev(hi)
    if r_hi.T_out_hot > tgt:                 # 最长也欠冷
        return None, None
    r_lo = ev(lo)
    if r_lo.T_out_hot <= tgt:                # 最短已够
        return lo, r_lo
    rb = r_hi
    for _ in range(BISECT_IT):
        m = 0.5 * (lo + hi)
        rb = ev(m)
        if rb.T_out_hot > tgt: lo = m
        else: hi = m
        if hi - lo < TOL: break
    return 0.5 * (lo + hi), rb
