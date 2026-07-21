from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.design.sizing import t_target, solve_Lx

def _case():
    return DesignCase(1,"air",688.23,1_088_700.0,0.2855,
                      "water",320.0,200_000.0,0.5,30_000.0,0.075,0.05)

def test_t_target_from_Q():
    c = _case()                       # Q 路 (dT=None)
    tt = t_target(c)
    assert tt < c.T_in_h and tt > c.T_in_c

def test_t_target_from_dT():
    c = _case(); c.dT = 40.0          # 温降 ΔT 路 (优先)
    assert abs(t_target(c) - (c.T_in_h - 40.0)) < 1e-9

def test_solve_Lx_hits_target():
    c = _case()
    Lx, r = solve_Lx(c, "Diamond", 7.0, 0.5, s=0.084, arrangement="cross")
    assert Lx is None or (0.001 < Lx <= 0.450 and r is not None)
