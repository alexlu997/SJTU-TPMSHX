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
