"""Mass-flux inlet BC (Part 2 fix, 2026-06-04).

Velocity-inlet (fixed v) + compressible (ρ=P/RT) + Forchheimer (dP∝ρ·u² at
fixed u) forms a POSITIVE feedback: dP↑→P↑→ρ↑→dP↑. For high-resistance
configs (air-air narrow offset outlet) the gain exceeds 1 → the SIMPLE solve
runs away (v_out~2912 m/s, P~120 atm) and never converges.

Mass-flux inlet holds G=ρ·v constant instead of v: ρ↑→v=G/ρ↓→dP∝1/ρ↓, a
NEGATIVE feedback → stable. It is also the physically-correct compressible
inlet (velocity-inlet is ambiguous about density). For low-dP cases (water,
aligned air) ρ≈ρ_ref so v≈v_specified → behaviour ≈ velocity-inlet.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solvers.simple_solver_3d import SIMPLESolver3D


def _mock(rho_inlet, v_inlet=20.0, target_at_rho=1.0, flag=True,
          fluid='ideal_gas'):
    """Mock with a captured target G = v_inlet·target_at_rho and a current
    inlet density rho_inlet (the runaway-elevated value)."""
    m = SimpleNamespace(
        fluid_type=fluid, massflux_inlet=flag,
        v_inlet_field=np.full((3, 3), v_inlet),
        rho_field=np.ones((3, 5, 3)),
    )
    m.rho_field[:, 0, :] = rho_inlet
    m._massflux_target = np.full((3, 3), v_inlet * target_at_rho)
    return m


def test_holds_rho_v_constant_when_density_rises():
    # target G = 20·1.0 = 20; inlet density ran up to 4.0 -> v should be 20/4=5
    m = _mock(rho_inlet=4.0, v_inlet=20.0, target_at_rho=1.0)
    SIMPLESolver3D._apply_massflux_inlet(m)
    assert np.allclose(m.v_inlet_field, 5.0), \
        f"v_inlet should be G/rho=5, got {m.v_inlet_field.mean()}"


def test_noop_when_density_at_reference():
    # rho == reference -> v unchanged (=v_specified)
    m = _mock(rho_inlet=1.0, v_inlet=20.0, target_at_rho=1.0)
    SIMPLESolver3D._apply_massflux_inlet(m)
    assert np.allclose(m.v_inlet_field, 20.0)


def test_disabled_flag_is_noop():
    m = _mock(rho_inlet=4.0, v_inlet=20.0, target_at_rho=1.0, flag=False)
    SIMPLESolver3D._apply_massflux_inlet(m)
    assert np.allclose(m.v_inlet_field, 20.0), "flag off -> must not touch v_inlet"
