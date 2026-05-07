"""Coarse-grid bootstrap (Phase C) regression tests."""
from __future__ import annotations
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

warnings.filterwarnings('ignore')

from solvers.coarse_bootstrap_3d import (
    bootstrap_simple_3d, _block_average_2d, _block_average_3d,
    _trilinear_zoom)
from solvers.simple_solver_3d import SIMPLESolver3D


def _build_solver():
    # All axes ≥ 8 so coarse 2× halving stays ≥ 4 (min_coarse_axis gate).
    Nx, Ny, Nz = 16, 12, 8
    K_arr = np.full((Ny, Nz), 1e-7, dtype=np.float64)
    cF_arr = np.full((Ny, Nz), 340.0, dtype=np.float64)
    return SIMPLESolver3D(
        Lx=0.1, Ly=0.04, Lz=0.02,
        Nx=Nx, Ny=Ny, Nz=Nz,
        rho=1.0, mu=2e-5, T_in=350.0, v_inlet=3.0,
        eps=0.78, K_arr=K_arr, cF_arr=cF_arr,
        P_ref_abs=101325.0)


def test_block_average_2d_shape_and_value():
    arr = np.ones((8, 6))
    out = _block_average_2d(arr, 2, 2)
    assert out.shape == (4, 3)
    np.testing.assert_allclose(out, 1.0)


def test_block_average_3d_shape():
    arr = np.arange(2 * 4 * 6, dtype=float).reshape(2, 4, 6)
    out = _block_average_3d(arr, 1, 2, 2)
    assert out.shape == (2, 2, 3)


def test_trilinear_zoom_preserves_constant():
    arr = np.full((6, 4, 3), 7.5)
    out = _trilinear_zoom(arr, (12, 8, 6))
    assert out.shape == (12, 8, 6)
    np.testing.assert_allclose(out, 7.5, atol=1e-9)


def test_bootstrap_skips_too_small_grid():
    """Coarse axis < 4 → bootstrap skipped, no exception."""
    Nx, Ny, Nz = 6, 6, 4   # Nz//2=2 < min_coarse_axis=4
    K_arr = np.full((Ny, Nz), 1e-7, dtype=np.float64)
    cF_arr = np.full((Ny, Nz), 340.0, dtype=np.float64)
    s = SIMPLESolver3D(
        Lx=0.1, Ly=0.04, Lz=0.02,
        Nx=Nx, Ny=Ny, Nz=Nz,
        rho=1.0, mu=2e-5, T_in=350.0, v_inlet=3.0,
        eps=0.78, K_arr=K_arr, cF_arr=cF_arr,
        P_ref_abs=101325.0)
    info = bootstrap_simple_3d(s)
    assert info['applied'] is False
    assert info['reason'] == 'coarse-too-small'


def test_bootstrap_seeds_fine_velocity_field():
    """After bootstrap, fine v[:, 0, :] equals inlet BC and field is
    not all-zero (cold-start would leave it zero outside the inlet)."""
    s = _build_solver()
    info = bootstrap_simple_3d(s, max_iter_coarse=50, tol_coarse=1e-2)
    assert info['applied'] is True
    assert info['coarse_shape'] == (8, 6, 4)
    # Fine v field should not be all zeros after prolongation.
    assert np.any(np.abs(s.v) > 1e-6)
    # Inlet BC re-imposed exactly.
    np.testing.assert_allclose(s.v[:, 0, :], s.v_inlet_field, atol=1e-12)


def test_bootstrap_solver_matches_baseline_converged_state():
    """Bootstrapped solver must reach the same converged state as the
    cold-start baseline (zero precision loss)."""
    s_cold = _build_solver()
    conv_c, it_c = s_cold.solve(max_iter=400, tol=1e-4)
    assert conv_c, "Cold-start baseline did not converge"

    s_warm = _build_solver()
    s_warm.use_coarse_bootstrap = True
    s_warm.coarse_bootstrap_max_iter = 80
    s_warm.coarse_bootstrap_tol = 1e-3
    conv_w, it_w = s_warm.solve(max_iter=400, tol=1e-4)
    assert conv_w, "Bootstrap-warmed solver did not converge"

    # Coarse bootstrap should at minimum not slow cold-start; ideally faster.
    # Allow some slack since this is a small test grid.
    assert it_w <= it_c + 30, (
        f"Bootstrap slowed solver: warm {it_w} vs cold {it_c} iters")

    # Final fields must agree (Anderson rollback / Phase A both preserve
    # final attractor; bootstrap is only an init perturbation).
    np.testing.assert_allclose(s_cold.u, s_warm.u, rtol=2e-2, atol=1e-3)
    np.testing.assert_allclose(s_cold.v, s_warm.v, rtol=2e-2, atol=1e-3)
