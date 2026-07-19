"""P1.3 slice-A guards: the 3D evaluator's 1D D-F seed must come from the
solvers/envelope authority, not a local copy of the algebra (architecture
audit 2026-07 §2 — the copies are how evaluator/pipeline physics drifted in
the C8 era), and a BO campaign must start with fresh warn-dedup registries
(audit §5 — latched warnings from a previous campaign silence this one).

Wiring/identity tests only — cheap and grid-independent. The NUMBER lock for
the evaluators is test_evaluator_frozen_values (rel=1e-12) in the same suite.
"""
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_seed_algebra_bitwise_matches_envelope():
    """The swap is a pure refactor ONLY if the authority computes the exact
    same float — same op order, same constant. Lock the bitwise equality."""
    from solvers.envelope import predict_outlet_p_sq, R_AIR_DEFAULT
    for P_in, T, C, L in [
        (101325.0, 350.0, 1.7e4, 0.182),
        (304746.0, 370.7, 8.3e5, 0.042),
        (1.01e5, 293.15, 2.4e3, 0.05),
    ]:
        manual = P_in ** 2 - 2.0 * R_AIR_DEFAULT * T * C * L
        assert predict_outlet_p_sq(P_in, T, C, L) == manual


def test_evaluate_3d_has_no_local_seed_algebra():
    """All three historical hand-copy sites (cold A/B seeds + hot var-rho
    reseed) must call predict_outlet_p_sq; the inline algebra must be gone."""
    import core.evaluators as ev
    src = inspect.getsource(ev)
    assert src.count('predict_outlet_p_sq(') >= 3, (
        "cold-A, cold-B and hot-reseed sites must all use the envelope "
        "authority")
    assert '2.0 * R_AIR *' not in src, (
        "hand-copied 1D D-F seed algebra crept back into core/evaluators "
        "(P1.3 regression)")


def test_evaluators_R_AIR_is_envelope_value():
    """R_AIR stays exported (verify_pareto_3d imports it) but its value is
    the envelope authority's constant."""
    import core.evaluators as ev
    from solvers.envelope import R_AIR_DEFAULT
    assert ev.R_AIR == R_AIR_DEFAULT


class _FakeSolver3D:
    """Minimal staggered-field stand-in for the post-solve gate unit tests.

    grid = (n0, n1, n2) in the SOLVER frame; u/v/w staggered MAC-style on
    axes 0/1/2 respectively; P is the gauge cell field.
    """
    def __init__(self, grid, speed, P_gauge_min, P_ref_abs=101325.0):
        import numpy as np
        n0, n1, n2 = grid
        self.u = np.full((n0 + 1, n1, n2), speed)
        self.v = np.zeros((n0, n1 + 1, n2))
        self.w = np.zeros((n0, n1, n2 + 1))
        self.P = np.full((n0, n1, n2), 0.0)
        self.P[0, 0, 0] = P_gauge_min
        self.P_ref_abs = P_ref_abs


def _gate_with_fakes(speed_A=5.0, speed_B=5.0,
                     P_gauge_min_A=0.0, P_gauge_min_B=0.0):
    import numpy as np
    from core.evaluators import _post_solve_gate_3d
    # Real grid (Nx, Ny, Nz) = (3, 2, 2); solver-A frame = (Ny, Nx, Nz).
    sA = _FakeSolver3D((2, 3, 2), speed_A, P_gauge_min_A)
    sB = _FakeSolver3D((3, 2, 2), speed_B, P_gauge_min_B)
    Ta = np.full((3, 2, 2), 350.0)
    Tb = np.full((3, 2, 2), 300.0)
    return _post_solve_gate_3d(sA, sB, Ta, Tb)


def test_post_solve_gate_passes_clean_fields():
    ok, reasons = _gate_with_fakes()
    assert ok and reasons == []


def test_post_solve_gate_flags_supersonic():
    """|v| past the local sound speed must invalidate — Mach is the
    load-bearing signal (the pressure floor bounds the stored gauge, but a
    choked solve still drives v = G/rho supersonic)."""
    ok, reasons = _gate_with_fakes(speed_A=500.0)   # a ≈ 375 m/s @ 350 K
    assert not ok
    assert any('[A]' in r and 'supersonic' in r for r in reasons)


def test_post_solve_gate_flags_floor_clipped_pressure():
    from solvers.envelope import PRESSURE_FLOOR_PA
    ok, reasons = _gate_with_fakes(
        P_gauge_min_B=-(101325.0 - PRESSURE_FLOOR_PA))  # abs P at the floor
    assert not ok
    assert any('[B]' in r and 'floor' in r for r in reasons)


def test_evaluate_3d_wires_post_solve_gate():
    """The gate must run in evaluate_3d before the result dict is built."""
    import core.evaluators as ev
    src = inspect.getsource(ev.evaluate_3d)
    assert '_post_solve_gate_3d(' in src, (
        "evaluate_3d lost its post-solve envelope gate (P1.3-B regression)")


def test_qnehvi_campaign_resets_warn_registries(monkeypatch):
    """_reset_warn_registries clears both process-global registries, and
    run_qnehvi calls it at campaign entry (per-campaign granularity — a
    500-eval campaign still dedups; mirrors ComputePipeline.run)."""
    import optimization.optimizer_qnehvi as oq
    import solvers.nu_correlations as nc
    import df_surrogate.predict as dp

    calls = []
    monkeypatch.setattr(nc, 'reset_extrap_warn_registry',
                        lambda: calls.append('extrap'))
    monkeypatch.setattr(dp, 'reset_choke_warn_registry',
                        lambda: calls.append('choke'))
    oq._reset_warn_registries()
    assert calls == ['extrap', 'choke']

    src = inspect.getsource(oq.run_qnehvi)
    assert '_reset_warn_registries()' in src, (
        "run_qnehvi must reset the warn registries at campaign entry")
