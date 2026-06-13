"""Unit tests for solvers.coupling_skeleton — the shared outer-coupling
convergence tracker (OuterConvergence).

These lock the tracker contract that pipelines.stages_2d (dual ΔT + Δρ)
and pipelines.stages_3d (single ΔT) both drive their convergence through.
Bit-identical-to-legacy behaviour is gated end-to-end by _golden_2d.py /
_golden_3d.py; this file pins the unit-level semantics.
"""
from __future__ import annotations

import numpy as np
import pytest

from solvers.coupling_skeleton import OuterConvergence


def _f(val, shape=(3, 3)):
    return np.full(shape, float(val))


# ── OuterConvergence ────────────────────────────────────────────────


def test_first_call_never_converges_and_reports_inf():
    c = OuterConvergence(tol_T=0.5, track=('Ta',))
    converged, deltas = c.check({'Ta': _f(400.0)})
    assert converged is False
    assert deltas['Ta'] == float('inf')


def test_single_field_converges_when_delta_below_tol():
    c = OuterConvergence(tol_T=0.5, track=('Ta',))
    c.check({'Ta': _f(400.0)})                      # seed prev
    converged, deltas = c.check({'Ta': _f(400.2)})  # ΔT = 0.2 < 0.5
    assert converged is True
    assert deltas['Ta'] == pytest.approx(0.2)


def test_single_field_not_converged_when_delta_above_tol():
    c = OuterConvergence(tol_T=0.5, track=('Ta',))
    c.check({'Ta': _f(400.0)})
    converged, deltas = c.check({'Ta': _f(401.0)})  # ΔT = 1.0 > 0.5
    assert converged is False
    assert deltas['Ta'] == pytest.approx(1.0)


def test_dual_field_requires_both_below_tol():
    c = OuterConvergence(tol_T=1.0, track=('Ta', 'Tb'))
    c.check({'Ta': _f(400.0), 'Tb': _f(300.0)})
    # Ta moves 0.3 (ok), Tb moves 2.0 (not ok) → AND-gate fails.
    converged, deltas = c.check({'Ta': _f(400.3), 'Tb': _f(302.0)})
    assert converged is False
    assert deltas['Ta'] == pytest.approx(0.3)
    assert deltas['Tb'] == pytest.approx(2.0)


def test_extra_criterion_blocks_convergence_even_if_temperature_ok():
    c = OuterConvergence(tol_T=1.0, track=('Ta',))
    c.check({'Ta': _f(400.0)})
    # ΔT = 0.1 < 1.0 but extra (e.g. drho) 0.05 > extra_tol 0.01.
    converged, _ = c.check({'Ta': _f(400.1)},
                           extra=(0.05,), extra_tol=0.01)
    assert converged is False
    # Same temperature step, extra now below tol → converges.
    c2 = OuterConvergence(tol_T=1.0, track=('Ta',))
    c2.check({'Ta': _f(400.0)})
    conv2, _ = c2.check({'Ta': _f(400.1)}, extra=(0.005,), extra_tol=0.01)
    assert conv2 is True


def test_extra_without_tol_raises():
    c = OuterConvergence(tol_T=1.0, track=('Ta',))
    c.check({'Ta': _f(400.0)})
    with pytest.raises(ValueError):
        c.check({'Ta': _f(400.1)}, extra=(0.01,))


def test_prev_is_copied_not_aliased():
    """In-place mutation of the passed field after check() must not corrupt
    the tracker's stored prev (it copies)."""
    c = OuterConvergence(tol_T=0.5, track=('Ta',))
    arr = _f(400.0)
    c.check({'Ta': arr})
    arr += 100.0                       # mutate the SAME array in place
    converged, deltas = c.check({'Ta': _f(400.2)})
    # If prev had aliased `arr`, prev would now read 500 and ΔT would be ~100.
    assert deltas['Ta'] == pytest.approx(0.2)
    assert converged is True
