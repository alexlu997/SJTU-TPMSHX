"""B-plan B1/B2 — strict energy-conservation golden.

Conservation contract (vault: 2026-06-03-3d-strict-energy-conservation-B-plan-CN.md):
  the discrete FV energy balance per phase must satisfy ∮_∂Ω F·n dA = ∫_Ω S dV
  for BOTH full-face cross-flow (T2) and offset partial-B (T4).

Metric — `eps_B_strict` (and `eps_A_strict`), computed by the solver when
cfg['conservative_ltne']=True. It is the residual of the *conservative*
discretisation evaluated on the converged field, summed over interior cells:

    r[c] = a_P·T_c − Σ a_nb·T_nb − h_v·V·Ts        (a_P carries the (F_e−F_w+…) net-out term)
    eps_strict = |Σ_interior r| / |∫_interior S|

Because the conservative kernel uses the SAME shared SIMPLE face flux for the
two cells adjacent to every face, internal faces telescope, so Σ_interior r =
∮_∂(interior) flux − ∫ source. A solution that actually solves the conservative
balance drives this to ~0 (solver tol); a non-conservative solution evaluated
against the same discretisation leaves it large. This supersedes the earlier
`compute_phase2a_interior` heuristic (advective enthalpy m·cp·ΔT vs interior
source), which silently dropped the boundary-diffusion term and so read ~8.5 %
for the cold fluid even when the scheme conserved — a metric artifact, not a
conservation failure.

The legacy cell-local-|u_c| upwind kernel (cfg default) does NOT satisfy this
balance: the shared face carries two different fluxes in the two adjacent
cells' equations. The face-centered Patankar rewrite (SIMPLE staggered fluxes,
(F_e−F_w) telescoping in a_P, MAC projection to discrete solenoidality) drives
both T2 and T4 < 1 %.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validation.audit_3d_conservation import make_T2, make_T4
from runs.run_calculation_3d import _run_3d_stack

_EPS_GATE = 0.01  # < 1 %


def _strict_eps(maker, grid=20):
    cfg = maker(grid)
    cfg["conservative_ltne"] = True
    res = _run_3d_stack(cfg)
    return res["eps_A_strict"], res["eps_B_strict"]


def test_conservative_ltne_T2_full_face():
    """Full-face cross-flow: conservative discretisation balances per phase."""
    eps_A, eps_B = _strict_eps(make_T2)
    assert eps_A is not None and eps_B is not None, \
        "conservative_ltne path did not emit strict-conservation metrics"
    assert eps_A < _EPS_GATE, f"T2 ε_A_strict={eps_A*100:.3f}% not < 1%"
    assert eps_B < _EPS_GATE, f"T2 ε_B_strict={eps_B*100:.3f}% not < 1%"


def test_conservative_ltne_T4_partial_offset():
    """Offset partial-B (Shanghai-like): conservative discretisation balances."""
    eps_A, eps_B = _strict_eps(make_T4)
    assert eps_A is not None and eps_B is not None, \
        "conservative_ltne path did not emit strict-conservation metrics"
    assert eps_A < _EPS_GATE, f"T4 ε_A_strict={eps_A*100:.3f}% not < 1%"
    assert eps_B < _EPS_GATE, f"T4 ε_B_strict={eps_B*100:.3f}% not < 1%"
