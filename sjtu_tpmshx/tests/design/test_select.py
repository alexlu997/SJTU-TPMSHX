from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.design.select import enumerate_select


def _cases():
    return [DesignCase(1,"air",688.23,1_088_700.0,0.2855,
                       "water",320.0,200_000.0,0.5,30_000.0,0.075,0.05)]

def test_enumerate_returns_pareto_and_best():
    feas, best = enumerate_select(_cases(), arrangement="cross",
                                  nodes={"topo":["Diamond"],"l":[6.0,7.0],"t":[0.5]})
    assert isinstance(feas, list)
    if best is not None:
        assert best.feasible and best.V > 0
        assert "min-V" in best_tags(feas, best)  # 最小体积件被标

def best_tags(feas, d):
    from sjtu_tpmshx.design.select import pareto_tags
    return pareto_tags(feas).get(id(d), [])
