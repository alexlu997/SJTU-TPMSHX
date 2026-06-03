"""B-plan B1 — strict energy-conservation golden (RED until face-centered kernel lands).

Conservation contract (vault: 2026-06-03-3d-strict-energy-conservation-B-plan-CN.md):
  discrete FV energy balance per phase ⇒ ε_B (volumetric source vs enthalpy) < 1%
  for BOTH full-face cross-flow (T2) and offset partial-B (T4).

Current cell-local-|u_c| upwind kernel: ε_B = 8.35% (T2) / 78.99% (T4) — NOT
conservative (the shared face carries two different fluxes in the two adjacent
cells' equations). The face-centered Patankar rewrite, selected by
cfg['conservative_ltne']=True, must drive both < 1% by using the SIMPLE
staggered face fluxes + the (F_e - F_w) telescoping term in a_P.

These tests are RED now (flag unimplemented ⇒ ε_B unchanged) and GREEN after B2.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validation.audit_3d_conservation import (
    make_T2, make_T4, compute_phase2a_interior,
)
from runs.run_calculation_3d import _run_3d_stack

_EPS_B_GATE = 0.01  # < 1 %


def _eps_B_conservative(maker, grid=20):
    cfg = maker(grid)
    cfg["conservative_ltne"] = True  # B2 wires the face-centered kernel here
    res = _run_3d_stack(cfg)
    return compute_phase2a_interior(res)["eps_B_kernel"]


def test_conservative_ltne_T2_full_face():
    """Full-face cross-flow: conservative kernel ⇒ ε_B < 1% (now 8.35%)."""
    eps_B = _eps_B_conservative(make_T2)
    assert eps_B < _EPS_B_GATE, f"T2 ε_B={eps_B*100:.2f}% not < 1%"


def test_conservative_ltne_T4_partial_offset():
    """Offset partial-B (Shanghai-like): conservative kernel ⇒ ε_B < 1% (now 78.99%)."""
    eps_B = _eps_B_conservative(make_T4)
    assert eps_B < _EPS_B_GATE, f"T4 ε_B={eps_B*100:.2f}% not < 1%"
