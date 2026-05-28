"""Tests for the dynamic PyAMG rebuild trigger added in phase L-d (audit P4).

The pressure-correction solver caches a PyAMG hierarchy in
`SIMPLESolver3D._ml_cache` and rebuilds it on (a) the first SIMPLE iter,
(b) cadence hits (`it % pyamg_rebuild_every == 0`), or (c) when the
diagonal-norm drift on the assembled `A` exceeds
`pyamg_rebuild_drift_thresh`. These tests cover the bookkeeping and the
trigger-vs-skip decision on an AMG-active grid (`N > 30000`).

Grids small enough to fall under the spsolve branch (`N <= 30000`) are
exercised indirectly by `tests/test_simple_solver_3d.py`; the cache stays
empty on that path so the counters tested here are zero.
"""
import sys
import warnings
from pathlib import Path

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

warnings.filterwarnings('ignore')

import numpy as np
import pytest

from solvers.simple_solver_3d import SIMPLESolver3D


# 60x60x10 = 36 000 cells > 30 000 AMG gate.
_NX, _NY, _NZ = 60, 60, 10


def _make_solver(drift_thresh=0.05, rebuild_every=100,
                 use_coarse_bootstrap=False):
    """Default `use_coarse_bootstrap=False` to keep drift-trigger tests
    isolated from Option B warm-start side effects. Option B auto-enables
    bootstrap on N>30 k by default, but bootstrap shrinks the iter-to-iter
    A drift to ~1e-15 (already steady-state after warm guess) which would
    suppress the drift_thresh=1e-12 trigger this file asserts on."""
    K_arr = np.full((_NY, _NZ), 5e-9, dtype=np.float64)
    cF_arr = np.full((_NY, _NZ), 250.0, dtype=np.float64)
    return SIMPLESolver3D(
        Lx=0.06, Ly=0.06, Lz=0.01,
        Nx=_NX, Ny=_NY, Nz=_NZ,
        rho=1.0, mu=2e-5, T_in=300.0, v_inlet=5.0,
        eps=0.78, K_arr=K_arr, cF_arr=cF_arr,
        P_ref_abs=101325.0,
        pyamg_rebuild_every=rebuild_every,
        pyamg_rebuild_drift_thresh=drift_thresh,
        use_coarse_bootstrap=use_coarse_bootstrap)


@pytest.mark.slow
def test_static_K_only_rebuilds_at_first_iter():
    """K_arr / cF_arr fixed → drift stays below 5 % after cold start.

    Expected: hierarchy rebuilt once at it=1 (cold-start bypass branch
    also builds it for iter=2+), then reused (skip_count grows). Drift-
    triggered rebuilds should not fire.
    """
    s = _make_solver(drift_thresh=0.05)
    s.solve(max_iter=20, tol=1e-6)
    c = s._ml_cache
    assert c.get('rebuild_count', 0) == 1, (
        f"expected exactly 1 rebuild (cold-start), "
        f"got {c.get('rebuild_count')}")
    assert c.get('skip_count', 0) >= 5, (
        f"expected drift-skip to fire on >=5 iters, "
        f"got {c.get('skip_count')}")
    assert c.get('drift_rebuild_count', 0) == 0, (
        f"drift-rebuild should not fire on static K case, got "
        f"{c.get('drift_rebuild_count')}")
    assert c.get('last_drift', 1.0) < 0.05, (
        f"final drift should be < 5 %, got {c.get('last_drift')}")


@pytest.mark.slow
def test_cold_start_bypass_skips_bicgstab_on_first_iter():
    """Cold-start fix: iter=1 in AMG path goes spsolve-direct, never enters
    BiCGStab. Hierarchy still built so iter=2+ takes AMG-BiCGStab path.
    """
    s = _make_solver(drift_thresh=0.05)
    s.solve(max_iter=5, tol=1e-6)
    c = s._ml_cache
    # Cold-start fired exactly once
    assert c.get('cold_start_count', 0) == 1, (
        f"expected exactly 1 cold-start bypass, "
        f"got {c.get('cold_start_count')}")
    assert c.get('cold_start_done', False) is True
    # Hierarchy got built (for iter=2+ to use)
    assert c.get('rebuild_count', 0) == 1
    assert 'ml' in c
    # BiCGStab calls fewer than outer iter count by 1 (skipped iter=1)
    assert c.get('bcg_calls', 0) <= 4, (
        f"bcg_calls should be <= outer_iters - 1 (cold-start skipped), "
        f"got {c.get('bcg_calls')}")
    # No BiCGStab fail expected on warm iters with stable cached hierarchy
    assert c.get('bcg_fail_count', 0) == 0, (
        f"bcg_fail should be 0 after cold-start bypass, "
        f"got {c.get('bcg_fail_count')}")


@pytest.mark.slow
def test_aggressive_thresh_triggers_drift_rebuilds():
    """Very tight drift threshold (1e-12) → any movement triggers extra
    rebuild on iters where the drift check ran. Asserts the drift branch
    can fire, not exact counts (depends on how many SIMPLE iters converge).
    """
    s = _make_solver(drift_thresh=1e-12)
    s.solve(max_iter=10, tol=1e-6)
    c = s._ml_cache
    assert c.get('rebuild_count', 0) >= 2, (
        f"expected cold + drift rebuilds (>=2), "
        f"got {c.get('rebuild_count')}")
    # Either drift_rebuild_count > 0 OR skip_count > 0 (drift check ran).
    assert (c.get('drift_rebuild_count', 0) + c.get('skip_count', 0)) >= 1


@pytest.mark.slow
def test_legacy_mode_disable_drift_check():
    """drift_thresh=0 → drift check disabled → cadence-only behaviour.

    With max_iter=20 < pyamg_rebuild_every=100, no cadence hits after
    it=1 → exactly 1 rebuild, 0 skips (drift check did not run, so
    skip_count never gets set).
    """
    s = _make_solver(drift_thresh=0.0)
    s.solve(max_iter=20, tol=1e-6)
    c = s._ml_cache
    assert c.get('rebuild_count', 0) == 1
    assert c.get('skip_count', 0) == 0
    assert c.get('drift_rebuild_count', 0) == 0
    # Drift-check internal key never written
    assert 'diag_norm_now' not in c


@pytest.mark.slow
def test_instrumentation_keys_populated():
    """Verify the _ml_cache contains the documented diagnostic keys."""
    s = _make_solver(drift_thresh=0.05)
    s.solve(max_iter=5, tol=1e-6)
    c = s._ml_cache
    for key in ('rebuild_count', 'rebuild_time', 'bcg_time', 'bcg_calls'):
        assert key in c, f"missing instrumentation key {key!r}"
    assert c['rebuild_time'] > 0.0
    assert c['bcg_time'] > 0.0
    assert c['bcg_calls'] >= 1


def test_constructor_accepts_drift_kwarg():
    """Smoke: new kwarg accepted + persisted as float on the instance."""
    s = SIMPLESolver3D(
        Lx=0.01, Ly=0.01, Lz=0.01, Nx=4, Ny=4, Nz=4,
        rho=1.0, mu=2e-5, T_in=300.0, v_inlet=1.0,
        pyamg_rebuild_drift_thresh=0.07)
    assert s.pyamg_rebuild_drift_thresh == pytest.approx(0.07)


def test_coarse_bootstrap_init_param_passthrough():
    """Option B: `use_coarse_bootstrap` constructor kwarg persists on the
    instance, None is the default sentinel (auto-resolve in solve())."""
    # Default: None (auto-resolve in solve based on N)
    s = SIMPLESolver3D(
        Lx=0.01, Ly=0.01, Lz=0.01, Nx=4, Ny=4, Nz=4,
        rho=1.0, mu=2e-5, T_in=300.0, v_inlet=1.0)
    assert s.use_coarse_bootstrap is None
    # Explicit True/False honoured
    s2 = SIMPLESolver3D(
        Lx=0.01, Ly=0.01, Lz=0.01, Nx=4, Ny=4, Nz=4,
        rho=1.0, mu=2e-5, T_in=300.0, v_inlet=1.0,
        use_coarse_bootstrap=True)
    assert s2.use_coarse_bootstrap is True
    s3 = SIMPLESolver3D(
        Lx=0.01, Ly=0.01, Lz=0.01, Nx=4, Ny=4, Nz=4,
        rho=1.0, mu=2e-5, T_in=300.0, v_inlet=1.0,
        use_coarse_bootstrap=False)
    assert s3.use_coarse_bootstrap is False


@pytest.mark.slow
def test_coarse_bootstrap_auto_enables_on_large_grid():
    """Option B: Default `use_coarse_bootstrap=None` triggers bootstrap on
    N>30 k grids. Asserts `_coarse_bootstrap_info['applied']` True after solve."""
    # 36 k cells: above AMG gate, auto-enable expected
    s = _make_solver(use_coarse_bootstrap=None)  # None → auto
    s.solve(max_iter=5, tol=1e-6)
    bs_info = getattr(s, '_coarse_bootstrap_info', {})
    assert bs_info.get('applied', False) is True, (
        f"bootstrap should auto-enable on 36 k grid, info={bs_info}")


@pytest.mark.slow
def test_coarse_bootstrap_explicit_false_disables_auto():
    """Option B: Explicit `use_coarse_bootstrap=False` overrides auto-enable
    even on large grids."""
    s = _make_solver(use_coarse_bootstrap=False)
    s.solve(max_iter=5, tol=1e-6)
    # _coarse_bootstrap_info either missing or applied=False
    bs_info = getattr(s, '_coarse_bootstrap_info', {})
    assert bs_info.get('applied', False) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
