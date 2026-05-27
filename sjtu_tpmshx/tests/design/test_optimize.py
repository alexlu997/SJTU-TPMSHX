import pytest
from design.cases import DesignCase
from design.sizing import size_fixed_cell
from design.optimize import warm_start_joint

def _cases():
    return [DesignCase(1,"air",688.23,1_088_700.0,0.2855,
                       "water",320.0,200_000.0,0.5,30_000.0,0.075,0.05)]

def test_warmstart_not_worse_than_baseline():
    cs = _cases()
    base = size_fixed_cell(cs, "Diamond", 6.0, 0.4, "cross")
    if not base.feasible:
        pytest.skip("baseline infeasible in this config")
    ref = warm_start_joint(cs, base, "cross", maxiter=15)
    assert ref.feasible
    assert ref.V <= base.V + 1e-9                 # 精修 ≥ baseline (下界对照)
    assert 4.0 <= ref.l <= 8.0 and 0.3 <= ref.t <= 0.5   # 留凸包内
