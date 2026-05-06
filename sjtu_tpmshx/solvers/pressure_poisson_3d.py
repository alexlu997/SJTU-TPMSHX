"""3D Pressure-Poisson solver — replacement for 1D axial P-recovery.

Phase 8 / Audit Fix #2 of 2026-05-06.
See vault/reports/streamfunction/2026-05-06-poisson-rewrite-plan-CN.md.

Solves the cell-centered Pressure-Poisson Equation (PPE):

    ∇²P = ∇·F

where F is the Brinkman-Forchheimer-corrected momentum residual:

    F = μ∇²u - (μ/K)·u - ρ·c_F·|u|·u - ρ(u·∇)u

Applied AFTER Helmholtz projection has produced a mass-conserving velocity
field. The PPE then yields a pressure consistent with the porous-medium
momentum equation (vs the legacy 1D axial Brinkman integration which
assumed plug flow and dropped lateral pressure gradients — root cause of
the SF Shanghai dP 47% > SIMPLE 38% gap).

Boundary conditions
-------------------
- Outlet (outlet_mask_ij = True): Dirichlet P = 0 (gauge anchor).
- Walls + closed outlet + inlet: Neumann ∂P/∂n = 0 (homogeneous).
  Phase B.3 will extend this to non-homogeneous Neumann derived from the
  momentum equation normal projection at the inlet.

Skeleton scope (B.1)
--------------------
This commit ships:
  - mixed-BC Laplacian builder (Dirichlet + homogeneous Neumann)
  - AMG hierarchy cache
  - solve_pressure_poisson_3d() public entry point
  - source-term stub (returns zeros; filled in by B.2 next commit)

So the wiring + linear-solve harness can be unit-tested in isolation
before the full ∇·F assembly lands.
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pyamg
from scipy.sparse import csr_matrix


# ----------------------------------------------------------------- Laplacian


def build_pressure_laplacian_3d(
    Nx: int, Ny: int, Nz: int,
    dx: float, dy: float, dz: float,
    dirichlet_mask: np.ndarray,
) -> csr_matrix:
    """Build SPD ``-∇²`` operator (cell-centered, mixed BC).

    Caller solves ``-∇²P = -S`` (equivalent to ``∇²P = S``).
    Sign convention matches edge_potential_3d.build_cell_laplacian_3d
    (positive diag, negative off-diag).

    Parameters
    ----------
    Nx, Ny, Nz : grid size
    dx, dy, dz : uniform spacing
    dirichlet_mask : (Nx, Ny, Nz) bool array
        True at cells where P is pinned to 0 (outlet anchoring).
        At least one True cell required to make the system non-singular
        (avoids the pure-Neumann nullspace).

    Returns
    -------
    A : csr_matrix, shape (Nx*Ny*Nz, Nx*Ny*Nz)
        SPD operator with Dirichlet rows replaced by identity (b_i = 0).
        Homogeneous Neumann at all other boundaries (face term simply
        omitted — equivalent to ghost-cell mirror with zero gradient).

    Notes
    -----
    - For a uniform 16×16×16 grid the assembly is ~5 ms — acceptable for
      a one-time build per case. Caching done at the caller (AMG hierarchy
      reuse).
    - Phase B.3 will extend with non-homogeneous Neumann (RHS contribution)
      for the inlet face. That is additive: adjust ``b`` not ``A``.
    """
    if dirichlet_mask.shape != (Nx, Ny, Nz):
        raise ValueError(
            f"dirichlet_mask shape {dirichlet_mask.shape} != ({Nx},{Ny},{Nz})")
    if not np.any(dirichlet_mask):
        raise ValueError(
            "dirichlet_mask must have at least one True cell to anchor P "
            "(pure-Neumann system is singular).")

    n = Nx * Ny * Nz
    inv_dx2 = 1.0 / (dx * dx)
    inv_dy2 = 1.0 / (dy * dy)
    inv_dz2 = 1.0 / (dz * dz)

    # Pre-allocate (max 7 nnz per row: 6 neighbors + 1 diag)
    rows = np.empty(7 * n, dtype=np.int32)
    cols = np.empty(7 * n, dtype=np.int32)
    vals = np.empty(7 * n, dtype=np.float64)
    nnz = 0

    def idx(i, j, k):
        return (i * Ny + j) * Nz + k

    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                p = idx(i, j, k)

                if dirichlet_mask[i, j, k]:
                    # Pinned: row = identity, RHS will be 0
                    rows[nnz] = p; cols[nnz] = p; vals[nnz] = 1.0
                    nnz += 1
                    continue

                diag = 0.0
                # SPD form: -∇²; diag positive, off-diag negative.
                # Boundary stencil omission ≡ homogeneous Neumann.
                if i > 0:
                    rows[nnz] = p; cols[nnz] = idx(i-1, j, k); vals[nnz] = -inv_dx2
                    nnz += 1
                    diag += inv_dx2
                if i < Nx - 1:
                    rows[nnz] = p; cols[nnz] = idx(i+1, j, k); vals[nnz] = -inv_dx2
                    nnz += 1
                    diag += inv_dx2
                if j > 0:
                    rows[nnz] = p; cols[nnz] = idx(i, j-1, k); vals[nnz] = -inv_dy2
                    nnz += 1
                    diag += inv_dy2
                if j < Ny - 1:
                    rows[nnz] = p; cols[nnz] = idx(i, j+1, k); vals[nnz] = -inv_dy2
                    nnz += 1
                    diag += inv_dy2
                if k > 0:
                    rows[nnz] = p; cols[nnz] = idx(i, j, k-1); vals[nnz] = -inv_dz2
                    nnz += 1
                    diag += inv_dz2
                if k < Nz - 1:
                    rows[nnz] = p; cols[nnz] = idx(i, j, k+1); vals[nnz] = -inv_dz2
                    nnz += 1
                    diag += inv_dz2

                rows[nnz] = p; cols[nnz] = p; vals[nnz] = diag
                nnz += 1

    return csr_matrix(
        (vals[:nnz], (rows[:nnz], cols[:nnz])),
        shape=(n, n))


# ----------------------------------------------------------------- source stub


def assemble_ppe_source_3d(
    u_face: np.ndarray, v_face: np.ndarray, w_face: np.ndarray,
    mu_field: np.ndarray, K_arr: np.ndarray, cF_arr: np.ndarray,
    rho_field: np.ndarray, eps_field: np.ndarray,
    dx: float, dy: float, dz: float,
) -> np.ndarray:
    """Assemble S = ∇·F on cell centers.

    F = μ∇²u - (μ/K)u - ρ·c_F·|u|·u - ρ(u·∇)u

    STUB (Phase B.1): returns zeros. Real assembly lands in Phase B.2.
    Once filled in, the pure-Poisson harness here will deliver a true
    PPE solution; for now the harness is testable against synthetic S.

    Returns
    -------
    S : (Nx, Ny, Nz) cell-centered source field.
    """
    Nx, Ny, Nz = rho_field.shape
    return np.zeros((Nx, Ny, Nz), dtype=np.float64)


# ----------------------------------------------------------------- public solve


class _PPEHierarchyCache:
    """One-slot AMG hierarchy + matrix cache.

    The Laplacian + AMG hierarchy depend only on grid geometry and the
    Dirichlet mask. Cache by (Nx, Ny, Nz, dx, dy, dz, mask_hash) so that
    iterating outer non-iso loops doesn't rebuild AMG every time.
    """

    def __init__(self):
        self._key = None
        self._A: Optional[csr_matrix] = None
        self._ml: Optional[object] = None

    def get(self, Nx, Ny, Nz, dx, dy, dz, dirichlet_mask):
        mask_hash = hash(dirichlet_mask.tobytes())
        key = (Nx, Ny, Nz, dx, dy, dz, mask_hash)
        if self._key != key:
            A = build_pressure_laplacian_3d(
                Nx, Ny, Nz, dx, dy, dz, dirichlet_mask)
            ml = pyamg.smoothed_aggregation_solver(A)
            self._key = key
            self._A = A
            self._ml = ml
        return self._A, self._ml


# Module-level cache (process-wide). Solver instances can carry their own
# if isolation is needed.
_default_cache = _PPEHierarchyCache()


def solve_pressure_poisson_3d(
    u_face: np.ndarray, v_face: np.ndarray, w_face: np.ndarray,
    mu_field: np.ndarray, K_arr: np.ndarray, cF_arr: np.ndarray,
    rho_field: np.ndarray, eps_field: np.ndarray,
    dx: float, dy: float, dz: float,
    outlet_mask_ij: np.ndarray,
    *,
    cache: Optional[_PPEHierarchyCache] = None,
    tol: float = 1e-10,
    max_v_cycles: int = 50,
) -> Tuple[np.ndarray, dict]:
    """Solve ∇²P = ∇·F for cell-centered P (gauge, P_outlet = 0).

    Parameters
    ----------
    u_face, v_face, w_face : staggered face velocities, shapes
        (Nx+1, Ny, Nz), (Nx, Ny+1, Nz), (Nx, Ny, Nz+1).
    mu_field, rho_field, eps_field : cell-centered (Nx, Ny, Nz).
    K_arr, cF_arr : (Ny, Nz). Broadcast across i.
    dx, dy, dz : uniform spacing.
    outlet_mask_ij : (Nx, Nz) bool. Mask of OPEN outlet cells at j=Ny-1
        (compatible with SIMPLESolver3D / StreamfunctionSolver3D conv).
    cache : optional hierarchy cache. Pass a per-instance cache to share
        AMG hierarchy across multiple outer iterations.
    tol : AMG residual tolerance (relative).
    max_v_cycles : AMG iteration cap.

    Returns
    -------
    P : (Nx, Ny, Nz) gauge pressure field, P[outlet_mask] = 0.
    info : dict with keys 'iter', 'residual_rel', 'residual_abs'.
    """
    Nx, Ny, Nz = rho_field.shape

    # Build the 3D Dirichlet mask from the (i, k) outlet mask:
    # only cells at j=Ny-1 AND outlet_mask_ij[i, k] are pinned.
    dirichlet_mask = np.zeros((Nx, Ny, Nz), dtype=bool)
    if outlet_mask_ij.shape != (Nx, Nz):
        raise ValueError(
            f"outlet_mask_ij shape {outlet_mask_ij.shape} != ({Nx},{Nz})")
    dirichlet_mask[:, Ny - 1, :] = outlet_mask_ij

    # If no outlet cells are open (degenerate), pin the corner so AMG
    # has a non-singular system. This shouldn't happen in normal Shanghai
    # runs but guards against pathological config.
    if not np.any(dirichlet_mask):
        dirichlet_mask[0, 0, 0] = True

    # Get / build cached hierarchy.
    c = cache or _default_cache
    A, ml = c.get(Nx, Ny, Nz, dx, dy, dz, dirichlet_mask)

    # Assemble RHS: solver form is -∇²P = -S; both sides flipped.
    S = assemble_ppe_source_3d(
        u_face, v_face, w_face, mu_field, K_arr, cF_arr,
        rho_field, eps_field, dx, dy, dz)
    b = -S.ravel(order='C').astype(np.float64)
    # Dirichlet rows: b = 0 (pin to gauge zero).
    b[dirichlet_mask.ravel(order='C')] = 0.0

    # AMG V-cycles
    residuals = []
    x = ml.solve(b, tol=tol, maxiter=max_v_cycles, residuals=residuals,
                 accel='cg')

    P = x.reshape((Nx, Ny, Nz), order='C')

    # Enforce Dirichlet exactly (defense-in-depth; AMG should hit ~1e-15).
    P[dirichlet_mask] = 0.0

    info = {
        'iter': len(residuals),
        'residual_rel': float(residuals[-1] / max(residuals[0], 1e-30))
                        if residuals else 0.0,
        'residual_abs': float(residuals[-1]) if residuals else 0.0,
    }
    return P, info
