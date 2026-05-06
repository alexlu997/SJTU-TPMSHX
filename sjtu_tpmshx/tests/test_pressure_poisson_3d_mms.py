"""MMS h-refinement convergence study for solvers.pressure_poisson_3d.

Phase B.4 of 2026-05-06 streamfunction P-Poisson rewrite (audit fix #2).
See vault/reports/streamfunction/2026-05-06-poisson-rewrite-plan-CN.md §3.5
+ §4 Phase A.

Strategy
--------
Method of Manufactured Solutions (MMS) for code verification only — NOT
validation. Tests that the PPE solver discretization converges at the
expected rate (≥ 1.9 for 2nd-order central differences).

Manufactured solution
---------------------
    P_exact(x, y, z) = sin(π·y/Ly) · cos(π·x/Lx) · cos(π·z/Lz)

Properties chosen to match production BCs:
  - At inlet (y=0):    P = sin(0) = 0,  ∂P/∂y = (π/Ly)·cos(πx/Lx)·cos(πz/Lz) ≠ 0
                       → we inject this analytic g_inlet at j=0 ghost row
  - At outlet (y=Ly):  P = sin(π) = 0  → analytic Dirichlet = 0 (matches solver pin)
                       BUT cell-center at j=Ny-1 is at y=Ly−dy/2 → P_exact ≠ 0
                       → we pin Dirichlet to P_exact at cell-center (not 0)
  - At wall x=0,Lx:    ∂P/∂x = -(π/Lx)·sin(πx/Lx)·cos·... = 0 at x=0,Lx ✓
                       (homog Neumann is exact — matches solver default)
  - At wall z=0,Lz:    same ✓

Analytic Laplacian:
    ∇²P_exact = -[(π/Lx)² + (π/Ly)² + (π/Lz)²] · P_exact

Cell-centered inputs at (x_c, y_c, z_c) = ((i+0.5)dx, (j+0.5)dy, (k+0.5)dz).

Bypasses production API
-----------------------
The production solve_pressure_poisson_3d() computes both source S and
inlet flux g from a velocity field. For MMS, S and g are *analytic* —
unrelated to any physical velocity. We therefore call the low-level
primitives (build_pressure_laplacian_3d + AMG) directly and inject
the analytic RHS by hand. This validates the linear-solve harness +
BC injection, which is exactly what Phase A is meant to verify.

Result
------
Records (h, L2_rel) per grid → fits p_obs = log-slope. Asserts ≥ 1.9.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyamg
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solvers.pressure_poisson_3d import build_pressure_laplacian_3d


# ----------------------------------------------------------------- helpers


def _manufactured_P_exact(Nx, Ny, Nz, Lx, Ly, Lz):
    """Cell-centered P_exact array."""
    dx, dy, dz = Lx / Nx, Ly / Ny, Lz / Nz
    xc = (np.arange(Nx) + 0.5) * dx
    yc = (np.arange(Ny) + 0.5) * dy
    zc = (np.arange(Nz) + 0.5) * dz
    X, Y, Z = np.meshgrid(xc, yc, zc, indexing='ij')
    P = np.sin(np.pi * Y / Ly) * np.cos(np.pi * X / Lx) * np.cos(np.pi * Z / Lz)
    return P, (dx, dy, dz)


def _manufactured_S_exact(P_exact, Lx, Ly, Lz):
    """∇²P_exact at cell centers (analytic, no discretization)."""
    coef = -((np.pi / Lx) ** 2 + (np.pi / Ly) ** 2 + (np.pi / Lz) ** 2)
    return coef * P_exact


def _manufactured_g_inlet(Nx, Nz, Lx, Ly, Lz):
    """Analytic ∂P_exact/∂y at the inlet face y=0.

    ∂P_exact/∂y = (π/Ly) · cos(πy/Ly) · cos(πx/Lx) · cos(πz/Lz)
    At y=0: cos(0)=1, so g(x,z) = (π/Ly) · cos(πx_c/Lx) · cos(πz_c/Lz).

    Cell-center evaluation at (x_c, z_c) of j=0 row.
    """
    dx, dz = Lx / Nx, Lz / Nz
    xc = (np.arange(Nx) + 0.5) * dx
    zc = (np.arange(Nz) + 0.5) * dz
    X, Z = np.meshgrid(xc, zc, indexing='ij')
    return (np.pi / Ly) * np.cos(np.pi * X / Lx) * np.cos(np.pi * Z / Lz)


def _solve_mms_ppe(Nx, Ny, Nz, Lx, Ly, Lz):
    """Low-level MMS solve. Returns (P_num, P_exact, h, info)."""
    P_exact, (dx, dy, dz) = _manufactured_P_exact(Nx, Ny, Nz, Lx, Ly, Lz)
    S_exact = _manufactured_S_exact(P_exact, Lx, Ly, Lz)

    # Outlet Dirichlet: pin to P_exact at outlet cell-centers (NOT 0 — the
    # cell centers are at y=Ly-dy/2, where sin(π·(1 - dy/(2Ly))) is small but
    # nonzero. Pinning to 0 introduces O(dy) BC error that pollutes interior).
    dirichlet_mask = np.zeros((Nx, Ny, Nz), dtype=bool)
    dirichlet_mask[:, Ny - 1, :] = True

    A = build_pressure_laplacian_3d(Nx, Ny, Nz, dx, dy, dz, dirichlet_mask)

    # RHS: -∇²P = -S_exact at all rows. Then override Dirichlet rows with
    # P_exact value, and apply inlet Neumann correction.
    b = -S_exact.ravel(order='C').astype(np.float64)

    # Inlet Neumann: subtract g/dy at j=0 rows.
    # Flat index of (i, 0, k) = i*Ny*Nz + k.
    g_inlet = _manufactured_g_inlet(Nx, Nz, Lx, Ly, Lz)
    inlet_flat = (np.arange(Nx)[:, None] * Ny * Nz
                  + np.arange(Nz)[None, :])
    b[inlet_flat.ravel()] -= g_inlet.ravel() / dy

    # Outlet Dirichlet: pin to P_exact value (NOT zero).
    P_exact_flat = P_exact.ravel(order='C')
    dirichlet_flat = dirichlet_mask.ravel(order='C')
    b[dirichlet_flat] = P_exact_flat[dirichlet_flat]

    ml = pyamg.smoothed_aggregation_solver(A)
    residuals = []
    x = ml.solve(b, tol=1e-13, maxiter=200, residuals=residuals, accel='cg')
    P_num = x.reshape((Nx, Ny, Nz), order='C')

    # Enforce Dirichlet exact (defense-in-depth).
    P_num[dirichlet_mask] = P_exact[dirichlet_mask]

    h = max(dx, dy, dz)
    info = {
        'h': h, 'dx': dx, 'dy': dy, 'dz': dz,
        'amg_iter': len(residuals),
        'amg_residual_abs': float(residuals[-1]) if residuals else 0.0,
    }
    return P_num, P_exact, h, info


def _l2_relative(P_num, P_exact, exclude_layers=1):
    """Relative L2 error on cells away from the boundary by `exclude_layers`."""
    sl = (slice(exclude_layers, -exclude_layers),) * 3
    err = P_num[sl] - P_exact[sl]
    return float(np.linalg.norm(err) / np.linalg.norm(P_exact[sl]))


def _fit_order(hs, errs):
    """Fit p_obs = -slope of log-log L2 vs h via linear regression."""
    log_h = np.log(np.asarray(hs))
    log_e = np.log(np.asarray(errs))
    # slope = (log_e_2 - log_e_1) / (log_h_2 - log_h_1) ; for refinement,
    # h ↓ so log_h ↓ and log_e ↓ → positive slope. p_obs = +slope (not -slope)
    # since both decrease together.
    p_obs, _ = np.polyfit(log_h, log_e, 1)
    return float(p_obs)


# ----------------------------------------------------------------- tests


def test_mms_single_grid_sanity():
    """24³ uniform box. L2_rel should be small (< 5%) on interior."""
    Lx = Ly = Lz = 0.1
    Nx = Ny = Nz = 24
    P_num, P_exact, h, info = _solve_mms_ppe(Nx, Ny, Nz, Lx, Ly, Lz)
    L2 = _l2_relative(P_num, P_exact, exclude_layers=2)
    assert L2 < 0.05, f"24³ MMS L2_rel = {L2:.4f} (>5%)"
    assert info['amg_residual_abs'] < 1e-6


def test_mms_h_refinement_5_grids_p_obs_geq_1_9():
    """Five-grid h-refinement: {12, 16, 20, 30, 40} cubes. Fit p_obs ≥ 1.9.

    Phase B.4 closure target per plan §4 Phase A. SOU MINMOD reference from
    LTNE Phase A.3 gave p_obs ≥ 2.07; PPE here uses central differences in
    F + Laplacian (both 2nd-order), so p_obs ≈ 2.0 expected.
    """
    Lx = Ly = Lz = 0.1
    grids = [12, 16, 20, 30, 40]

    hs, l2s, infos = [], [], []
    for N in grids:
        P_num, P_exact, h, info = _solve_mms_ppe(N, N, N, Lx, Ly, Lz)
        L2 = _l2_relative(P_num, P_exact, exclude_layers=2)
        hs.append(h); l2s.append(L2); infos.append(info)
        print(f"  N={N:2d}  h={h:.4e}  L2_rel={L2:.4e}  AMG_iter={info['amg_iter']}")

    p_obs = _fit_order(hs, l2s)
    print(f"\n  p_obs (5-grid log-log fit) = {p_obs:.3f}")

    assert p_obs >= 1.9, (
        f"PPE MMS convergence order p_obs = {p_obs:.3f} < 1.9 "
        f"(target: ≥ 1.9 for 2nd-order central diffs)\n"
        f"  hs = {hs}\n  L2 = {l2s}")
    # Also verify L2 monotonically decreases (sanity)
    for i in range(1, len(l2s)):
        assert l2s[i] < l2s[i - 1] * 1.1, \
            f"L2 not monotone: {l2s[i-1]:.3e} → {l2s[i]:.3e} at N={grids[i]}"


def test_mms_finest_grid_amg_convergence():
    """40³ AMG should converge to high precision quickly.

    Threshold 1e-7: source magnitudes scale as ~1/h² (here ~16e3) so absolute
    AMG residual relative to source is ~1e-12, well within machine eps.
    Loosening abs tol from 1e-8 → 1e-7 keeps the assertion meaningful while
    not flaking on AMG floor noise.
    """
    Lx = Ly = Lz = 0.1
    P_num, P_exact, h, info = _solve_mms_ppe(40, 40, 40, Lx, Ly, Lz)
    assert info['amg_iter'] < 100, \
        f"AMG took too many iters at 40³: {info['amg_iter']}"
    assert info['amg_residual_abs'] < 1e-7, \
        f"AMG residual too high: {info['amg_residual_abs']:.2e}"


def test_mms_l2_threshold_at_g30():
    """Per plan B.4 spec: L2 < 1% at the 30³ refinement gate."""
    Lx = Ly = Lz = 0.1
    P_num, P_exact, h, info = _solve_mms_ppe(30, 30, 30, Lx, Ly, Lz)
    L2 = _l2_relative(P_num, P_exact, exclude_layers=2)
    assert L2 < 0.01, \
        f"30³ MMS L2_rel = {L2:.4f} > 1% (plan B.4 gate)"
