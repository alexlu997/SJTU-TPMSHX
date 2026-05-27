from design.cases import DesignCase
from design.sizing import size_fixed_cell

def _cases():
    return [DesignCase(1,"air",688.23,1_088_700.0,0.2855,
                       "water",320.0,200_000.0,0.5,30_000.0,0.075,0.05)]

def test_size_returns_feasible_within_envelope():
    d = size_fixed_cell(_cases(), "Diamond", 7.0, 0.5, arrangement="cross")
    if d.feasible:
        assert 0 < d.s <= 0.450 and 0 < d.Lx <= 0.450
        assert d.dP_hot_max <= 0.075 + 1e-6          # 热侧 ≤ dPlim_h
        assert d.dP_cold_max <= 0.05 + 1e-6          # 冷侧 ≤ dPlim_c
        assert d.weight > 0                          # (1-ε)·V·ρ_s
    else:
        assert d.reason in ("dP>lim@s_max", "dP>lim@final",
                            "cooling-unreachable", "Lx>envelope")

def test_size_counter_flow():
    # 逆流 (Nz=2 内核 + 低 α, 不再极限环): 整条定尺管线应给出可行或带 reason
    d = size_fixed_cell(_cases(), "Diamond", 7.0, 0.5, arrangement="counter")
    if d.feasible:
        assert 0 < d.s <= 0.450 and 0 < d.Lx <= 0.450
        assert d.dP_hot_max <= 0.075 + 1e-6
        assert d.dP_cold_max <= 0.05 + 1e-6
        assert d.weight > 0
    else:
        assert d.reason in ("dP>lim@s_max", "dP>lim@final",
                            "cooling-unreachable", "Lx>envelope")

def test_infeasible_carries_identity():
    # 不可行件须带 topo/l/t/arrangement (否则汇总表全塌成 _l0_t0/cross, 看不出哪个构型为何失败)。
    # 物理不可能: dT=400 → 目标出口 288K < 冷侧入口 320K (违反二定律) → 任何几何冷却不可达。
    c = [DesignCase(1, "air", 688.0, 1_089_000.0, 0.2855,
                    "air", 320.0, 300_000.0, 0.3, None, 0.075, 0.05, dT=400.0)]
    d = size_fixed_cell(c, "Gyroid", 8.0, 0.6, arrangement="counter")
    assert not d.feasible                      # 冷却不可达 → 不可行
    assert d.topo == "Gyroid" and d.l == 8.0 and d.t == 0.6   # 身份保留
    assert d.arrangement == "counter"          # 布置非默认 cross
    assert d.reason                            # 有失败原因


def test_golden_finds_feasible_min_v():
    # 黄金分割 s-搜索 (C) 应找到可行 min-V, 且优于旧 20 点网格 (步长 22mm 漏真min)。
    # 空气-空气 ΔT=300 工况: golden 解 ~0.193L (旧网格 0.222L)。锚定改进 + 可行性。
    c = [DesignCase(1, "air", 900., 4e5, 0.05, "air", 300., 4e5, 0.05,
                    None, 0.08, 0.08, dT=300.)]
    d = size_fixed_cell(c, "Diamond", 7.0, 0.5, arrangement="cross")
    assert d.feasible
    assert d.dP_hot_max <= 0.08 + 1e-6 and d.dP_cold_max <= 0.08 + 1e-6
    assert d.T_out_hot_max <= 600.0 + 0.5            # 冷到目标
    assert d.V * 1e3 < 0.210                         # 优于旧网格 0.222L (golden ≈0.193)


def test_size_two_cases_governing():
    # 多工况: governing 0-D 预选 + 全 K 终验; 返回的单 (s,Lx) 须满足两工况
    cases = [
        DesignCase(1,"air",688.23,1_088_700.0,0.2855,
                   "water",320.0,200_000.0,0.5,30_000.0,0.075,0.05),
        DesignCase(2,"air",700.0,1_050_000.0,0.30,
                   "water",325.0,200_000.0,0.55,34_000.0,0.075,0.05),
    ]
    d = size_fixed_cell(cases, "Diamond", 7.0, 0.5, arrangement="cross")
    if d.feasible:
        assert 0 < d.s <= 0.450 and 0 < d.Lx <= 0.450
        assert d.dP_hot_max <= 0.075 + 1e-6          # 全K 热侧 max ≤ lim
        assert d.dP_cold_max <= 0.05 + 1e-6          # 全K 冷侧 max ≤ lim
        assert d.T_out_hot_max < 700.0               # 两工况都被冷却
        assert d.weight > 0
    else:
        assert d.reason in ("dP>lim@s_max", "dP>lim@final",
                            "cooling-unreachable", "Lx>envelope")
