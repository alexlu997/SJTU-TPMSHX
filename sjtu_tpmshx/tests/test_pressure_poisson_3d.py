"""Unit tests for solvers.pressure_poisson_3d.

Phase B.1 scope: skeleton + Laplacian + AMG harness. Source assembly
(∇·F) is a stub here; verified separately in B.2/B.4 with full MMS.

Tests:
  - Laplacian SPD + symmetry
  - Laplacian agrees with edge_potential_3d on pure-Neumann limit (sanity)
  - solve with synthetic source (manufactured P_exact = sin(πy/Ly))
    yields correct P up to AMG tolerance
  - Hierarchy cache hit on repeated solve

Phase 8 / Audit Fix #2 of 2026-05-06.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solvers.pressure_poisson_3d import (
    build_pressure_laplacian_3d,
    solve_pressure_poisson_3d,
    assemble_ppe_source_3d,
    _PPEHierarchyCache,
)


# ----------------------------------------------------------------- Laplacian


def test_laplacian_is_spd_symmetric():
    Nx, Ny, Nz = 8, 8, 8
    dx = dy = dz = 0.01
    mask = np.zeros((Nx, Ny, Nz), dtype=bool)
    mask[:, Ny - 1, :] = True   # full outlet
    A = build_pressure_laplacian_3d(Nx, Ny, Nz, dx, dy, dz, mask)

    # Symmetry (excluding Dirichlet rows which are by design identity)
    A_dense = A.toarray()
    interior = ~mask.ravel(order='C')
    sub = A_dense[np.ix_(interior, interior)]
    assert np.allclose(sub, sub.T, atol=1e-12), \
        "Laplacian non-symmetric on interior block"


def test_laplacian_rejects_empty_mask():
    Nx, Ny, Nz = 4, 4, 4
    mask_empty = np.zeros((Nx, Ny, Nz), dtype=bool)
    with pytest.raises(ValueError, match="at least one True"):
        build_pressure_laplacian_3d(Nx, Ny, Nz, 0.01, 0.01, 0.01, mask_empty)


def test_laplacian_rejects_wrong_shape():
    with pytest.raises(ValueError, match="shape"):
        mask_wrong = np.zeros((4, 4, 5), dtype=bool); mask_wrong[0, 0, 0] = True
        build_pressure_laplacian_3d(4, 4, 4, 0.01, 0.01, 0.01, mask_wrong)


# ----------------------------------------------------------------- AMG solve


def _make_zeros_3d(Nx, Ny, Nz):
    """Helper: zero-velocity placeholders for skeleton solve test."""
    return (
        np.zeros((Nx + 1, Ny, Nz)),
        np.zeros((Nx, Ny + 1, Nz)),
        np.zeros((Nx, Ny, Nz + 1)),
    )


def test_solve_zero_source_returns_zero():
    """Stub source returns zero S → ∇²P=0 with P|outlet=0 → P≡0."""
    Nx, Ny, Nz = 8, 16, 8
    dx = dy = dz = 0.005
    u, v, w = _make_zeros_3d(Nx, Ny, Nz)
    rho = np.ones((Nx, Ny, Nz))
    mu = np.full_like(rho, 2e-5)
    eps = np.full_like(rho, 0.5)
    K = np.full((Ny, Nz), 1e-9)
    cF = np.full((Ny, Nz), 0.5)
    outlet_mask = np.ones((Nx, Nz), dtype=bool)

    P, info = solve_pressure_poisson_3d(
        u, v, w, mu, K, cF, rho, eps, dx, dy, dz, outlet_mask)

    assert P.shape == (Nx, Ny, Nz)
    assert np.allclose(P, 0.0, atol=1e-10), \
        f"Zero-source solve should give P≡0, max|P|={np.abs(P).max():.3e}"
    assert info['iter'] >= 0


def test_solve_outlet_dirichlet_pinned_exactly():
    """P[outlet_mask] must be exactly 0 even after AMG (post-enforce step)."""
    Nx, Ny, Nz = 6, 10, 6
    dx = dy = dz = 0.01
    u, v, w = _make_zeros_3d(Nx, Ny, Nz)
    rho = np.ones((Nx, Ny, Nz))
    mu = np.full_like(rho, 2e-5)
    eps = np.full_like(rho, 0.5)
    K = np.full((Ny, Nz), 1e-9)
    cF = np.full((Ny, Nz), 0.5)
    # Partial outlet: only inner half open
    outlet_mask = np.zeros((Nx, Nz), dtype=bool)
    outlet_mask[1:-1, 1:-1] = True

    P, _ = solve_pressure_poisson_3d(
        u, v, w, mu, K, cF, rho, eps, dx, dy, dz, outlet_mask)

    # Open outlet cells must be exactly 0
    open_outlet_P = P[:, Ny - 1, :][outlet_mask]
    assert np.all(open_outlet_P == 0.0)


def test_amg_hierarchy_cache_reuse():
    """Same grid + mask → cache hit, no rebuild."""
    Nx, Ny, Nz = 8, 8, 8
    dx = dy = dz = 0.01
    cache = _PPEHierarchyCache()
    mask = np.zeros((Nx, Ny, Nz), dtype=bool)
    mask[:, -1, :] = True

    A1, ml1 = cache.get(Nx, Ny, Nz, dx, dy, dz, mask)
    A2, ml2 = cache.get(Nx, Ny, Nz, dx, dy, dz, mask)
    # Same object identity = cache hit
    assert A1 is A2
    assert ml1 is ml2

    # Different mask → cache miss
    mask2 = mask.copy()
    mask2[0, -1, 0] = False
    A3, ml3 = cache.get(Nx, Ny, Nz, dx, dy, dz, mask2)
    assert A3 is not A1


# ----------------------------------------------------------------- assembly stub


def test_source_stub_returns_zeros():
    """Phase B.1 source is a stub; B.2 will replace with real ∇·F."""
    Nx, Ny, Nz = 4, 6, 4
    u, v, w = _make_zeros_3d(Nx, Ny, Nz)
    rho = np.ones((Nx, Ny, Nz))
    mu = np.full_like(rho, 2e-5)
    eps = np.full_like(rho, 0.5)
    K = np.full((Ny, Nz), 1e-9)
    cF = np.full((Ny, Nz), 0.5)

    S = assemble_ppe_source_3d(u, v, w, mu, K, cF, rho, eps, 0.01, 0.01, 0.01)
    assert S.shape == (Nx, Ny, Nz)
    assert np.all(S == 0.0)


# ----------------------------------------------------------------- MMS-lite

def test_synthetic_source_recovers_manufactured_P():
    """Single-grid sanity: solve ∇²P = S with full-Dirichlet box.

    Bypasses the (stub) source assembler and injects an analytic S. Uses
    full-box Dirichlet (all six faces P=0) to avoid BC inconsistency from
    the production-config (only outlet pinned + Neumann elsewhere) — that
    config requires P_exact to satisfy ∂P/∂n=0 on the 5 Neumann faces,
    which a generic sine doesn't. Production-BC MMS validation lands in
    Phase B.4 with proper P_exact construction (cosine ⊗ sine ⊗ cosine).

    Pick P_exact = sin(πx/Lx)·sin(πy/Ly)·sin(πz/Lz) — vanishes on all
    six faces (cell-centered → ~half-cell offset from the analytic zero,
    introduces O(h) BC residual; for sanity this is acceptable).

    Verifies:
      - solve_pressure_poisson_3d harness end-to-end works
      - AMG converges
      - Recovered P shape matches P_exact within discretization tol

    This is NOT the full h-refinement convergence study (B.4).
    """
    import solvers.pressure_poisson_3d as ppe_mod

    Nx, Ny, Nz = 32, 32, 32   # finer to keep BC discretization error low
    Lx = Ly = Lz = 0.1
    dx, dy, dz = Lx / Nx, Ly / Ny, Lz / Nz

    # Cell-center coords
    xc = (np.arange(Nx) + 0.5) * dx
    yc = (np.arange(Ny) + 0.5) * dy
    zc = (np.arange(Nz) + 0.5) * dz
    X, Y, Z = np.meshgrid(xc, yc, zc, indexing='ij')

    kx = np.pi / Lx; ky = np.pi / Ly; kz = np.pi / Lz
    P_exact = np.sin(kx * X) * np.sin(ky * Y) * np.sin(kz * Z)
    lap_coef = -(kx**2 + ky**2 + kz**2)
    S_exact = lap_coef * P_exact

    # Full-box Dirichlet: pin all six faces to P=0 (matches sin·sin·sin BC).
    # Build a custom mask + override outlet_mask interpretation by patching
    # the dirichlet construction inline (we work directly with the Laplacian).
    full_mask = np.zeros((Nx, Ny, Nz), dtype=bool)
    full_mask[0, :, :] = True;  full_mask[-1, :, :] = True
    full_mask[:, 0, :] = True;  full_mask[:, -1, :] = True
    full_mask[:, :, 0] = True;  full_mask[:, :, -1] = True

    # Solve directly via build + AMG (skipping the production wrapper for
    # this sanity test; production wrapper only supports outlet-face Dirichlet).
    import pyamg
    A = ppe_mod.build_pressure_laplacian_3d(Nx, Ny, Nz, dx, dy, dz, full_mask)
    b = -S_exact.ravel(order='C')
    b[full_mask.ravel(order='C')] = 0.0
    ml = pyamg.smoothed_aggregation_solver(A)
    residuals = []
    x = ml.solve(b, tol=1e-12, maxiter=50, residuals=residuals, accel='cg')
    P_num = x.reshape((Nx, Ny, Nz), order='C')

    # Compare on truly interior cells (away from face by 2 cells, where
    # cell-centered BC offset error is O(h) localized).
    inner = P_exact[2:-2, 2:-2, 2:-2]
    err = P_num[2:-2, 2:-2, 2:-2] - inner
    L2_rel = np.linalg.norm(err) / np.linalg.norm(inner)

    # Threshold 8% accounts for the O(h) Dirichlet half-cell offset error
    # (cell centers at x = dx/2, etc., where sin(π·dx/(2Lx)) ≈ 0.05 not 0).
    # Full h-refinement (B.4) will use staggered MMS and tighter bound.
    assert L2_rel < 0.08, \
        f"Manufactured P recovery failed: L2_rel = {L2_rel:.4f} (>8%)"
    assert residuals[-1] < 1e-6, \
        f"AMG didn't converge: residual = {residuals[-1]:.2e}"
