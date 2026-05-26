"""嵌套二分定尺: 内层 Lx (冷却), 外层 s (dP-active)。单模块 ≤ 450mm。"""
from __future__ import annotations
from dataclasses import dataclass

from solvers.tpms_calc import geometry as tpms_geometry
from .fluids import fluid_props
from .forward import forward, dP_fracs, K_STEEL

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

RHO_S = 7900.0          # 304 SS [kg/m³]

@dataclass
class Design:
    feasible: bool
    topo: str = ""; l: float = 0.0; t: float = 0.0
    s: float = 0.0; Lx: float = 0.0; arrangement: str = "cross"
    V: float = 0.0; weight: float = 0.0
    dP_hot_max: float = 0.0; dP_cold_max: float = 0.0
    T_out_hot_max: float = 0.0; reason: str = ""

def _cool_proxy(case) -> float:
    """0-D 冷却难度代理 (无解): 所需效能 × 热侧流量 (越大越难冷→需更长 Lx)。"""
    denom = case.T_in_h - case.T_in_c
    eps_req = (case.T_in_h - t_target(case)) / denom if abs(denom) > 1e-9 else 0.0
    return eps_req * case.mdot_h

def _maxnorm_dP(cases, topo, l, t, s, Lx, arrangement) -> float:
    """全 K 工况两侧归一化 dP 的最大值 (纯解析, 无 LTNE 解)。"""
    w = 0.0
    for c in cases:
        dh, dc = dP_fracs(c, topo, l, t, s, Lx, arrangement)
        w = max(w, dh / c.dPlim_h, dc / c.dPlim_c)
    return w

def _Lx_all(cases, topo, l, t, s, arrangement):
    """全 K 工况冷却所需 Lx 的最大 (governing 终验)。任一不可达 → None。"""
    mx = 0.0
    for c in cases:
        Lx, _ = solve_Lx(c, topo, l, t, s, arrangement)
        if Lx is None:
            return None
        mx = max(mx, Lx)
    return mx

def size_fixed_cell(cases, topo, l, t, arrangement="cross") -> Design:
    """外层二分 s 使 max-归一化 dP (全K, 两侧, 解析) = 1 (min-V);
    s-loop 内只对 cooling-governing 工况跑 2D 冷却解; s* 处对全 K 终验。"""
    geo = tpms_geometry(topo, l, t, K_STEEL); EPS = geo["epsilon"]
    cool_gov = max(cases, key=_cool_proxy)              # 0-D 预选 (无解)
    s_lo = max(0.010, N_MIN * l / 1000.0); s_hi = S_MAX

    def lx_dp(s):                                       # governing 冷却 + 全K解析 dP
        Lx, _ = solve_Lx(cool_gov, topo, l, t, s, arrangement)
        if Lx is None or Lx > LX_MAX:
            return None, None
        return Lx, _maxnorm_dP(cases, topo, l, t, s, Lx, arrangement)

    Lx_hi, dn_hi = lx_dp(s_hi)
    if Lx_hi is None:
        return Design(False, reason="cooling-unreachable")
    if dn_hi > 1.0:
        return Design(False, reason="dP>lim@s_max")     # 450 内压损都超
    _, dn_lo = lx_dp(s_lo)
    if dn_lo is not None and dn_lo <= 1.0:
        s_star = s_lo                                   # dP 不约束 → 下界
    else:
        a, b = s_lo, s_hi
        for _ in range(BISECT_IT):
            m = 0.5 * (a + b)
            _, dnm = lx_dp(m)
            if dnm is None or dnm > 1.0: a = m
            else: b = m
            if b - a < TOL: break
        s_star = b                                      # 取可行侧上界
    # s* 处全 K 冷却终验 (governing 预选可能漏个别工况); Lx_star ≥ 各工况所需 → 全冷够
    Lx_star = _Lx_all(cases, topo, l, t, s_star, arrangement)
    if Lx_star is None or Lx_star > LX_MAX:
        return Design(False, reason="Lx>envelope")
    dPh = max(dP_fracs(c, topo, l, t, s_star, Lx_star, arrangement)[0] for c in cases)
    dPc = max(dP_fracs(c, topo, l, t, s_star, Lx_star, arrangement)[1] for c in cases)
    feasible = _maxnorm_dP(cases, topo, l, t, s_star, Lx_star, arrangement) <= 1.0 + 1e-6
    Tout_max = max(forward(c, topo, l, t, s_star, Lx_star, arrangement).T_out_hot
                   for c in cases)                      # 报告 (各工况已 ≤ 各自目标)
    V = s_star * s_star * Lx_star
    return Design(feasible, topo, l, t, s_star, Lx_star, arrangement,
                  V, (1.0 - EPS) * V * RHO_S, dPh, dPc, Tout_max,
                  reason="" if feasible else "dP>lim@final")
