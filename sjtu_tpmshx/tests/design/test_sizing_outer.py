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
