"""2D 双流股路径 B 前向: solve_full_domain_3d 塌 Nz=1 → 2D x-y (无 SIMPLE 动量,
plug 速度)。叉流 Nx×Ny×1 (A+x/B+y); 逆流 Nx×1×1 (B−x)。dP 解析 (dP_fracs, 无解)。"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

from solvers.tpms_calc import geometry as tpms_geometry
from solvers.solve_full_3d import solve_full_domain_3d
from df_fit.predict import predict_dP_compressible, predict_dP
from .fluids import fluid_props, fluid_nu

K_STEEL = 16.0
NX, NY_CROSS = 60, 40
LTNE_TOL = 1e-5
# G2 自适应早停: 收敛即停 (代替烧满 max_iter)。内核默认收敛阈 (2D 2e-7 / 3D 1e-3)
# 对 sizing 要么太严永不触发 (2D → 烧满 8000 sweep, 实需 ~200), 要么 chunk=500 太粗。
# 设计路径传有意义且会触发的阈: Q 相对变化 <1e-4 + (2D 还需) T 漂移 <0.01K, 每 100
# sweep 查一次 → T_out 在 ~200 sweep 即定, 同收敛解但 ~5-10× 少 sweep。仅 design opt-in;
# 内核默认 (None) 对 Shanghai/MMS/优化器逐位不变。
SIZING_QTOL = 1e-4
SIZING_CHUNK = 100
# 几何体素化分辨率。设计路径只需标量 (eps/A_0/D_h), N=128 vs 256 误差 eps<0.08%
# / A_0<0.5% (远低于模型 ~10% Nu/dP 不确定度), 但内存 8×↓ (128MiB→16MiB phi grid)。
# 关键: enumerate_select 全核 loky 并行, 各进程 lru_cache 不共享 → 各自重建 phi grid;
# N=256 时 16 进程 × 2 拓扑 × 128MiB ≈ 4GiB 常驻 → MemoryError。N=128 解此瓶颈。
GEOM_N = 128
# dir 编码 (verified vs solve_full_3d docstring): 0=+x, 1=−x, 2=+y, 3=−y
# 内核选择: 叉流走 2D 内核 (Nz=1, 垂直流股稳定快)。逆流两股同轴反向, 2D 内核
# solve_full_domain 无欠松弛 → 极限环 (水出口 347↔357 跳, 能量不平衡 7-33%);
# 改走 3D 内核 (Nz=2) + 低 α 欠松弛阻尼 → 稳定收敛 (实证 α=0.3 gap 0.4%, 各
# max_iter 字节一致)。详见 vault .../2026-05-26-quick-design-tool-plan §执行修正。
# qtol/chunk = G2 自适应早停参数 (传入 LTNE 内核)。
# cross (2D 内核): 旧默认收敛阈 2e-7 永不触发 → 烧满 8000; 传 (1e-4, 100) 早停 ~200 sweep。
# counter (3D 内核, α=0.3 欠松弛): 旧默认 (q_rel=1e-3@tol1e-4, chunk500) 已正常早停 ~2000
#   sweep; 小 chunk 会在欠松弛慢漂中误判早停 (实测 3.3K 偏差) → 保持 None (内核默认不变)。
_ARR = {
    "cross":   dict(dirB=2, ny=NY_CROSS, nz=1, alpha=0.7, maxit=8000,
                    qtol=SIZING_QTOL, chunk=SIZING_CHUNK),
    "counter": dict(dirB=1, ny=1,        nz=2, alpha=0.3, maxit=20000,
                    qtol=None, chunk=None),
}

@dataclass
class ForwardResult:
    T_out_hot: float; T_out_cold: float
    Q_hot: float; Q_cold: float
    dP_hot_frac: float; dP_cold_frac: float
    Re_hot: float; Re_cold: float
    fields: tuple | None = field(default=None, repr=False)  # (Ta,Tb,Ts) 供 warm-start

def _hvol(fluid, topo, l, t, A0, D_h, eps_A, mdot, span1, span2, T, P):
    """span1, span2: the two cross-sectional dimensions of the inlet face [m]."""
    p = fluid_props(fluid, T, P)
    A_flow = eps_A * span1 * span2
    u = mdot / (p.rho * A_flow)
    Re = p.rho * abs(u) * D_h / p.mu
    Nu = fluid_nu(fluid, topo, Re, eps_A, l, D_h * 1e3)
    return A0 * Nu * p.k / D_h, Re, u, p

def _dp_one(fluid, topo, l, t, eps_A, mdot, A_flow, T, P, props, L_chan):
    """单股压损 [Pa]。air→可压缩理想气体 D-F (predict_dP_compressible);
    water/不可压→不可压 D-F (predict_dP)。两者共用同一 K/c_F 几何闭合, 仅密度处理不同:
    可压版内嵌 ρ=P/(R_AIR·T) (气体专用), 不可压版传入常数 ρ。A_flow=开口迎风面积 ε_A·迎风。"""
    G = mdot / A_flow                              # 质量通量 [kg/(m²·s)]
    if fluid == "air":
        return predict_dP_compressible(topo, l, t, eps_A, G, T, P, props.mu, L_chan)
    u = G / props.rho                              # 孔隙内速度
    return predict_dP(topo, l, t, eps_A, u, props.rho, props.mu, L_chan)

def dP_fracs(case, topo, l, t, s, Lx, arrangement="cross", height=None):
    """两侧归一化前压损分数 (纯解析 D-F, 不触发 LTNE 解)。返回 (dP_h_frac, dP_c_frac)。
    按流体分派 (air 可压 / water 不可压); 迎风面积按流向取 (叉流冷侧 +y → Lx·s)。
    height: 矩形迎风时高(z)向尺寸 [m]; None → 方形 (s_z=s, 现状/UI 默认)。"""
    sz = s if height is None else height          # z(高)向跨度
    geo = tpms_geometry(topo, l, t, K_STEEL, N=GEOM_N); EPS_A = geo["epsilon_A"]
    pA = fluid_props(case.hot_fluid, case.T_in_h, case.P_in_h)
    pB = fluid_props(case.cold_fluid, case.T_in_c, case.P_in_c)
    # 热侧 A 沿 +x: 迎风面 = y×z = s×sz, 流程 Lx
    A_h = EPS_A * s * sz
    dP_h = _dp_one(case.hot_fluid, topo, l, t, EPS_A, case.mdot_h, A_h,
                   case.T_in_h, case.P_in_h, pA, Lx)
    # 冷侧 B: 叉流 +y 迎风 = x×z = Lx×sz, 流程 s; 逆流 −x 迎风 = y×z = s×sz, 流程 Lx
    if arrangement == "cross":
        A_c, L_c = EPS_A * Lx * sz, s
    else:
        A_c, L_c = EPS_A * s * sz, Lx
    dP_c = _dp_one(case.cold_fluid, topo, l, t, EPS_A, case.mdot_c, A_c,
                   case.T_in_c, case.P_in_c, pB, L_c)
    return dP_h / case.P_in_h, dP_c / case.P_in_c

def _cold_outlet(Tb, arrangement):
    Tb = np.asarray(Tb)
    return float(Tb[:, -1, :].mean()) if arrangement == "cross" \
        else float(Tb[0, :, :].mean())            # cross:+y 末 / counter:−x 末 (i=0)

def forward(case, topo: str, l: float, t: float, s: float, Lx: float,
            arrangement: str = "cross", init=None, k_s: float = K_STEEL,
            prop_model: str = "const", tol: float = LTNE_TOL,
            height=None) -> ForwardResult:
    """prop_model: 'const' = 物性在入口温取值 (现状, 最快); 'mean' = 2-pass
    均温 (入口解→出口温→(T_in+T_out)/2 重取物性→warm-start 重解), 消大-ΔT 系统偏置。
    dP 始终用入口物性 (冷却空气入口 μ/ρ 偏高 = 保守安全)。
    tol: LTNE 收敛残差 (默认 1e-5); 定尺搜索阶段可放松 (sizing 渐进收紧)。
    height: 矩形迎风高(z)向尺寸 [m]; None → 方形 (s_z=s, 现状/UI 默认)。
    叉流 nz=1 → 2D x-y 物理, z 仅经迎风面积影响流速; height 与宽 s 解耦不破方形。"""
    sz = s if height is None else height           # z(高)向跨度
    geo = tpms_geometry(topo, l, t, k_s, N=GEOM_N)
    EPS, EPS_A, A0, D_h = (geo["epsilon"], geo["epsilon_A"],
                           geo["A_0"], geo["D_h"])
    arr = _ARR[arrangement]
    Ny, Nz = arr["ny"], arr["nz"]
    shp = (NX, Ny, Nz); z = np.zeros(shp)
    # B 迎风首维: cross (+y) = Lx×sz; counter (−x) = s×sz
    span_c1 = Lx if arrangement == "cross" else s

    def _one_pass(Th_eval, Tc_eval, seed):
        """在指定取值温 (Th_eval/Tc_eval) 取物性, 解一次 LTNE。seed=(Ta,Tb,Ts) 续解。"""
        h_vA, Re_h, u_h, pA = _hvol(case.hot_fluid, topo, l, t, A0, D_h, EPS_A,
                                    case.mdot_h, s, sz, Th_eval, case.P_in_h)
        h_vB, Re_c, u_c, pB = _hvol(case.cold_fluid, topo, l, t, A0, D_h, EPS_A,
                                    case.mdot_c, span_c1, sz, Tc_eval, case.P_in_c)
        ucA = np.full(shp, u_h)
        if arrangement == "cross":
            vcB, ucB = np.full(shp, u_c), z
        else:
            ucB, vcB = np.full(shp, -u_c), z
        Ta0 = Tb0 = Ts0 = None
        if seed is not None:
            Ta0, Tb0, Ts0 = seed                   # warm-start 续解
        Ta, Tb, Ts = solve_full_domain_3d(
            Lx, s, sz, NX, Ny, Nz, case.T_in_h, case.T_in_c,
            np.full(shp, EPS_A * pA.k), np.full(shp, EPS_A * pB.k),
            np.full(shp, (1.0 - EPS) * k_s),
            np.full(shp, h_vA), np.full(shp, h_vB),
            pA.rho * pA.cp, pB.rho * pB.cp, np.full(shp, EPS),
            ucA, z, z, ucB, vcB, z, dir_A=0, dir_B=arr["dirB"],
            dx_arr=np.full(NX, Lx / NX), dy_arr=np.full(Ny, s / Ny),
            dz_arr=np.full(Nz, sz / Nz),
            Ta_init=Ta0, Tb_init=Tb0, Ts_init=Ts0,
            max_iter=arr["maxit"], tol=tol, alpha_T=arr["alpha"],
            q_rel_tol=arr["qtol"], conv_chunk=arr["chunk"])  # 双股都解 + (cross) 自适应早停
        Toh = float(np.asarray(Ta)[-1, :, :].mean())
        Toc = _cold_outlet(Tb, arrangement)
        return (Ta, Tb, Ts), Toh, Toc, pA, pB, Re_h, Re_c

    fld, T_out_h, T_out_c, pA, pB, Re_h, Re_c = _one_pass(
        case.T_in_h, case.T_in_c, init)
    if prop_model == "mean":                       # 第二趟: 均温物性 + warm-start
        Th = 0.5 * (case.T_in_h + T_out_h); Tc = 0.5 * (case.T_in_c + T_out_c)
        fld, T_out_h, T_out_c, pA, pB, Re_h, Re_c = _one_pass(Th, Tc, fld)
    Q_h = case.mdot_h * pA.cp * (case.T_in_h - T_out_h)
    Q_c = case.mdot_c * pB.cp * (T_out_c - case.T_in_c)
    dPh, dPc = dP_fracs(case, topo, l, t, s, Lx, arrangement, height=height)  # 始终入口物性 (保守)
    return ForwardResult(T_out_h, T_out_c, Q_h, Q_c, dPh, dPc, Re_h, Re_c, fld)
