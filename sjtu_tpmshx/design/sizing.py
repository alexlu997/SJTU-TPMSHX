"""定尺: 每个 s 内定 Lx = max(冷却所需, 满足两侧 dP 所需), 对 s 求 min-V。
单模块 ≤ 450mm。叉流冷侧迎风 = Lx·s (随 Lx 变) → 冷侧 dP 紧时须加厚 Lx,
不能只取冷却最小值 (否则薄板憋水, 误报不可行)。逆流冷侧迎风 = s² (与 Lx 无关)。"""
from __future__ import annotations
from dataclasses import dataclass, field

from scipy.optimize import brentq

from solvers.tpms_calc import geometry as tpms_geometry
from .fluids import fluid_props
from .forward import forward, dP_fracs, K_STEEL, GEOM_N, LTNE_TOL

S_MAX = 0.450          # build envelope [m]
LX_MAX = 0.450
N_MIN = 4              # 每向最少晶胞 (均质化)
BISECT_IT, TOL = 28, 1e-4
SIZING_TOL = 1e-4      # 定尺搜索期放松 LTNE 残差 (终点再用 LTNE_TOL 收紧)
GOLDEN_IT = 10         # min-V over s 黄金分割步数 (~12 解, s 分辨率 <5mm; 优于旧 20 网格 22mm)
S_REFINE_TOL = 0.004   # s 区间收敛阈 [m] (4mm)
N_DP = 40              # 内定 Lx 的解析 dP 扫描点数

def t_target(case) -> float:
    """热侧出口温目标: 优先用温降 ΔT, 否则由换热量 Q 反推。"""
    if case.dT is not None:
        return case.T_in_h - case.dT
    cp_h = fluid_props(case.hot_fluid, case.T_in_h, case.P_in_h).cp
    return case.T_in_h - case.Q / (case.mdot_h * cp_h)

def solve_Lx(case, topo, l, t, s, arrangement, target=None, k_s=K_STEEL,
             prop_model="const", seed=None):
    """求 Lx ∈ (0, LX_MAX] 使 T_out_hot = target (T_out 随 Lx 单调↓)。
    B: 用 brentq (超线性) 代替二分 → ~3× 少解。
    A: seed=(Ta,Tb,Ts) 跨-s 续解种子 (s 平滑变, 场近似); ev 内每步续解。
    D: 搜索用 SIZING_TOL (松), 终点用 LTNE_TOL (紧) → 渐进收紧。
    返回 (Lx, ForwardResult)。不可达 (LX_MAX 仍欠冷) → (None, None)。"""
    tgt = target if target is not None else t_target(case)
    prev = {"f": seed, "last": None}
    def ev(Lx, tol):
        r = forward(case, topo, l, t, s, Lx, arrangement, init=prev["f"],
                    k_s=k_s, prop_model=prop_model, tol=tol)
        prev["f"] = r.fields                # 续解种子 (链式)
        prev["last"] = r
        return r
    lo, hi = max(2.0 * l / 1000.0, 1e-3), LX_MAX
    f_hi = ev(hi, SIZING_TOL).T_out_hot - tgt
    if f_hi > 0:                             # 最长也欠冷
        return None, None
    f_lo = ev(lo, SIZING_TOL).T_out_hot - tgt
    if f_lo <= 0:                            # 最短已够
        return lo, ev(lo, LTNE_TOL)          # 终点收紧
    # f_lo>0>f_hi 已 bracket → brentq 超线性求根 (T_out 单调)
    Lx_root = brentq(lambda Lx: ev(Lx, SIZING_TOL).T_out_hot - tgt,
                     lo, hi, xtol=TOL, maxiter=BISECT_IT)
    return Lx_root, ev(Lx_root, LTNE_TOL)    # 终点收紧

RHO_S = 7900.0          # 304 SS [kg/m³]

@dataclass
class Design:
    feasible: bool
    topo: str = ""; l: float = 0.0; t: float = 0.0
    s: float = 0.0; Lx: float = 0.0; arrangement: str = "cross"
    V: float = 0.0; weight: float = 0.0
    dP_hot_max: float = 0.0; dP_cold_max: float = 0.0
    T_out_hot_max: float = 0.0; reason: str = ""
    percase: list = field(default_factory=list)   # 每工况明细 @ 定尺几何 (供工况明细表)

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

def _Lx_all(cases, topo, l, t, s, arrangement, k_s=K_STEEL, prop_model="const",
            seed=None):
    """全 K 工况冷却所需 Lx 的最大 (governing 终验)。任一不可达 → None。
    seed: 跨工况续解种子 (链式, 减 LTNE 迭代)。"""
    mx = 0.0
    for c in cases:
        Lx, r = solve_Lx(c, topo, l, t, s, arrangement, k_s=k_s,
                         prop_model=prop_model, seed=seed)
        if Lx is None:
            return None
        if r is not None:
            seed = r.fields                 # 链式续解
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

def size_fixed_cell(cases, topo, l, t, arrangement="cross", rho_s=RHO_S,
                    k_s=K_STEEL, prop_model="const") -> Design:
    """min-V over s: 每个 s 内定 Lx = max(冷却所需, 满足两侧 dP 所需) (≤450),
    取 V=s²·Lx 最小者。s-loop 冷却只跑 cooling-governing 工况 (其余 dP 解析),
    s* 处对全 K 冷却终验。叉流冷侧迎风=Lx·s → 冷侧 dP 紧时加厚 Lx (而非误判不可行)。
    k_s: 固体热导率 [W/(m·K)], 默认 16 (304SS); 入 LTNE 固体能量 K_ss=(1-ε)·k_s。"""
    geo = tpms_geometry(topo, l, t, k_s, N=GEOM_N); EPS = geo["epsilon"]
    cool_gov = max(cases, key=_cool_proxy)              # 0-D 预选 (无解)
    s_lo = max(0.010, N_MIN * l / 1000.0); s_hi = S_MAX

    lo_lx = max(2.0 * l / 1000.0, 1e-3)                 # 最小流向晶胞长 (= solve_Lx 下界)

    def _dh_min(s):                                     # 全 K 热侧归一化 dP @Lx=lo_lx (解析, 无解)
        return max(dP_fracs(c, topo, l, t, s, lo_lx, arrangement)[0] / c.dPlim_h
                   for c in cases)

    state = {"seed": None, "cooled": False}             # warm-start 链 + 是否曾冷到

    def _eval_s(s):
        """该 s 的 (V, Lx); 不可行→(None,None)。热侧 dP 预筛 + governing 冷却 + 两侧 dP 定 Lx。"""
        if _dh_min(s) > 1.0:                            # 热侧 dP 超限 (任何 Lx 不可行)
            return None, None
        Lx_cool, r = solve_Lx(cool_gov, topo, l, t, s, arrangement, k_s=k_s,
                              prop_model=prop_model, seed=state["seed"])
        if Lx_cool is None:                             # governing 冷不到
            return None, None
        state["cooled"] = True
        if r is not None:
            state["seed"] = r.fields                    # 携带场 (跨 s 平滑变)
        Lx = _min_Lx_for_dP(cases, topo, l, t, s, arrangement, Lx_cool)
        if Lx is None:
            return None, None
        return s * s * Lx, Lx

    # C: min-V over s 用黄金分割 (代替 20 点网格)。V(s)=s²·Lx(s), Lx(s) 随 s↓ →
    # U 形单峰; 可行区为上区间 (大 s 更易冷 + dP 更松)。先解析定热侧 dP 可行下界
    # (无 LTNE), 黄金分割于 [a, s_hi]; 不可行点 V=+inf, 两点皆 inf 时推向更大 s。
    if _dh_min(s_hi) > 1.0:                             # 最大迎风热侧 dP 仍超 → 无解
        return Design(False, topo, l, t, arrangement=arrangement, reason="dP>lim@s_max")
    a = s_lo
    if _dh_min(s_lo) > 1.0:                             # 解析二分热侧 dP 可行下界 (廉价)
        a_lo, a_hi = s_lo, s_hi
        for _ in range(30):
            m = 0.5 * (a_lo + a_hi)
            if _dh_min(m) > 1.0: a_lo = m
            else: a_hi = m
        a = a_hi
    b = s_hi
    GR, INF = 0.6180339887498949, float("inf")
    best = None                                         # (V, s, Lx)
    def _upd(sv, vv, lv):
        nonlocal best
        if vv is not None and (best is None or vv < best[0]):
            best = (vv, sv, lv)
    c = b - GR * (b - a); d = a + GR * (b - a)
    Vc, Lc = _eval_s(c); Vd, Ld = _eval_s(d)
    _upd(c, Vc, Lc); _upd(d, Vd, Ld)
    for _ in range(GOLDEN_IT):
        fc = Vc if Vc is not None else INF
        fd = Vd if Vd is not None else INF
        if fc == INF and fd == INF:                     # 皆不可行 → 推向更大 s (冷却随 s↑ 改善)
            a, c, Vc, Lc = c, d, Vd, Ld
            d = a + GR * (b - a); Vd, Ld = _eval_s(d); _upd(d, Vd, Ld)
        elif fc <= fd:                                  # min 在 [a,d] 内 → 收右界
            b, d, Vd, Ld = d, c, Vc, Lc
            c = b - GR * (b - a); Vc, Lc = _eval_s(c); _upd(c, Vc, Lc)
        else:                                           # min 在 [c,b] 内 → 收左界
            a, c, Vc, Lc = c, d, Vd, Ld
            d = a + GR * (b - a); Vd, Ld = _eval_s(d); _upd(d, Vd, Ld)
        if b - a < S_REFINE_TOL:
            break

    if best is None:
        return Design(False, topo, l, t, arrangement=arrangement,
                      reason="cooling-unreachable" if not state["cooled"]
                      else "dP>lim@s_max")
    _, s_star, _ = best
    s_seed = state["seed"]
    # s* 处全 K 冷却终验 (governing 预选可能漏个别更难冷工况); 以全K冷却为 Lx 下界重定
    Lx_floor = _Lx_all(cases, topo, l, t, s_star, arrangement, k_s=k_s,
                       prop_model=prop_model, seed=s_seed)
    if Lx_floor is None or Lx_floor > LX_MAX:
        return Design(False, topo, l, t, arrangement=arrangement, reason="cooling-unreachable")
    Lx_star = _min_Lx_for_dP(cases, topo, l, t, s_star, arrangement, Lx_floor)
    if Lx_star is None:
        return Design(False, topo, l, t, arrangement=arrangement,
                      reason="dP>lim@final")             # 全K冷却长度下两侧 dP 无法同时达标
    # 全 K 工况终验 (一次 forward/工况, 既出 percase 明细又汇总; 不再重复 dP_fracs)
    percase, dPh, dPc, Tout_max = [], 0.0, 0.0, 0.0
    for c in cases:
        r = forward(c, topo, l, t, s_star, Lx_star, arrangement, k_s=k_s,
                    prop_model=prop_model)
        percase.append(dict(
            case=c.case, hot_fluid=c.hot_fluid, cold_fluid=c.cold_fluid,
            T_air_out=r.T_out_hot, T_cold_out=r.T_out_cold, Q_W=r.Q_hot,
            dP_hot_frac=r.dP_hot_frac, dP_hot_pa=r.dP_hot_frac * c.P_in_h,
            dP_cold_frac=r.dP_cold_frac, dP_cold_pa=r.dP_cold_frac * c.P_in_c,
            Re_hot=r.Re_hot, Re_cold=r.Re_cold))
        dPh = max(dPh, r.dP_hot_frac); dPc = max(dPc, r.dP_cold_frac)
        Tout_max = max(Tout_max, r.T_out_hot)
    V = s_star * s_star * Lx_star
    return Design(True, topo, l, t, s_star, Lx_star, arrangement,
                  V, (1.0 - EPS) * V * rho_s, dPh, dPc, Tout_max, reason="",
                  percase=percase)
