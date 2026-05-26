"""定尺: 每个 s 内定 Lx = max(冷却所需, 满足两侧 dP 所需), 对 s 求 min-V。
单模块 ≤ 450mm。叉流冷侧迎风 = Lx·s (随 Lx 变) → 冷侧 dP 紧时须加厚 Lx,
不能只取冷却最小值 (否则薄板憋水, 误报不可行)。逆流冷侧迎风 = s² (与 Lx 无关)。"""
from __future__ import annotations
from dataclasses import dataclass

from solvers.tpms_calc import geometry as tpms_geometry
from .fluids import fluid_props
from .forward import forward, dP_fracs, K_STEEL

S_MAX = 0.450          # build envelope [m]
LX_MAX = 0.450
N_MIN = 4              # 每向最少晶胞 (均质化)
BISECT_IT, TOL = 28, 1e-4
NS = 20                # min-V over s 扫描点数
N_DP = 40              # 内定 Lx 的解析 dP 扫描点数

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

def _min_Lx_for_dP(cases, topo, l, t, s, arrangement, Lx_floor):
    """返回 ≥ Lx_floor 的最小 Lx ∈ [Lx_floor, LX_MAX] 使全K两侧归一化 dP ≤ 1
    (纯解析, 无 LTNE 解)。叉流: 冷侧 dP 随 Lx↓ (迎风 Lx·s 变大), 热侧 dP 随 Lx↑
    (流程变长) → 升序扫描取首个达标点 = 该 s 下 min-V 的 Lx。无可行 → None。"""
    if Lx_floor > LX_MAX:
        return None
    for i in range(N_DP + 1):
        Lx = Lx_floor + (LX_MAX - Lx_floor) * i / N_DP
        if _maxnorm_dP(cases, topo, l, t, s, Lx, arrangement) <= 1.0 + 1e-6:
            return Lx
    return None

def size_fixed_cell(cases, topo, l, t, arrangement="cross", rho_s=RHO_S) -> Design:
    """min-V over s: 每个 s 内定 Lx = max(冷却所需, 满足两侧 dP 所需) (≤450),
    取 V=s²·Lx 最小者。s-loop 冷却只跑 cooling-governing 工况 (其余 dP 解析),
    s* 处对全 K 冷却终验。叉流冷侧迎风=Lx·s → 冷侧 dP 紧时加厚 Lx (而非误判不可行)。"""
    geo = tpms_geometry(topo, l, t, K_STEEL); EPS = geo["epsilon"]
    cool_gov = max(cases, key=_cool_proxy)              # 0-D 预选 (无解)
    s_lo = max(0.010, N_MIN * l / 1000.0); s_hi = S_MAX

    lo_lx = max(2.0 * l / 1000.0, 1e-3)                 # 最小流向晶胞长 (= solve_Lx 下界)
    best = None                                         # (V, s, Lx)
    any_cool = False                                    # 是否存在能冷却的 s
    for i in range(NS):
        s = s_lo + (s_hi - s_lo) * i / (NS - 1)
        # 廉价预筛: 热侧 dP 随 Lx 单调↑, 最小在 Lx=lo_lx; 若此处已超限则该 s 任何 Lx 不可行
        dh_min = max(dP_fracs(c, topo, l, t, s, lo_lx, arrangement)[0] / c.dPlim_h
                     for c in cases)
        if dh_min > 1.0:
            continue                                    # 跳过 (省去昂贵冷却解)
        Lx_cool, _ = solve_Lx(cool_gov, topo, l, t, s, arrangement)
        if Lx_cool is None:                             # governing 此 s 冷不到
            continue
        any_cool = True
        Lx = _min_Lx_for_dP(cases, topo, l, t, s, arrangement, Lx_cool)
        if Lx is None:                                  # 此 s 无 Lx 同时满足冷却+dP
            continue
        V = s * s * Lx
        if best is None or V < best[0]:
            best = (V, s, Lx)

    if best is None:
        return Design(False, reason="cooling-unreachable" if not any_cool
                      else "dP>lim@s_max")
    _, s_star, _ = best
    # s* 处全 K 冷却终验 (governing 预选可能漏个别更难冷工况); 以全K冷却为 Lx 下界重定
    Lx_floor = _Lx_all(cases, topo, l, t, s_star, arrangement)
    if Lx_floor is None or Lx_floor > LX_MAX:
        return Design(False, reason="cooling-unreachable")
    Lx_star = _min_Lx_for_dP(cases, topo, l, t, s_star, arrangement, Lx_floor)
    if Lx_star is None:
        return Design(False, reason="dP>lim@final")     # 全K冷却长度下两侧 dP 无法同时达标
    dPh = max(dP_fracs(c, topo, l, t, s_star, Lx_star, arrangement)[0] for c in cases)
    dPc = max(dP_fracs(c, topo, l, t, s_star, Lx_star, arrangement)[1] for c in cases)
    Tout_max = max(forward(c, topo, l, t, s_star, Lx_star, arrangement).T_out_hot
                   for c in cases)                      # 报告 (各工况已 ≤ 各自目标)
    V = s_star * s_star * Lx_star
    return Design(True, topo, l, t, s_star, Lx_star, arrangement,
                  V, (1.0 - EPS) * V * rho_s, dPh, dPc, Tout_max, reason="")
