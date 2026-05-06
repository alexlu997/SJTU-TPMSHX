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


def _face_to_center_3d(u_face, v_face, w_face):
    """Average staggered face velocities to cell centers.

    Inputs (staggered, MAC layout):
      u_face : (Nx+1, Ny, Nz)   — x-component on x-faces
      v_face : (Nx, Ny+1, Nz)   — y-component on y-faces
      w_face : (Nx, Ny, Nz+1)   — z-component on z-faces

    Returns (uc, vc, wc) all shape (Nx, Ny, Nz) at cell centers.
    """
    uc = 0.5 * (u_face[:-1, :, :] + u_face[1:, :, :])
    vc = 0.5 * (v_face[:, :-1, :] + v_face[:, 1:, :])
    wc = 0.5 * (w_face[:, :, :-1] + w_face[:, :, 1:])
    return uc, vc, wc


def _laplacian_centered_3d(field, dx, dy, dz):
    """Cell-centered ∇²(field) via 7-point stencil with one-sided BC.

    At interior cells: standard central differences.
    At boundary cells: copy-edge (zero-gradient ghost), which yields the
    homogeneous Neumann ∂/∂n = 0 limit. Adequate for source assembly where
    the goal is ∇·F at interior cells; the divergence operator already
    masks boundary cells via central-difference stencil reach.
    """
    f = field
    out = np.zeros_like(f)
    out[1:-1, :, :] += (f[2:, :, :] - 2 * f[1:-1, :, :] + f[:-2, :, :]) / (dx * dx)
    out[:, 1:-1, :] += (f[:, 2:, :] - 2 * f[:, 1:-1, :] + f[:, :-2, :]) / (dy * dy)
    out[:, :, 1:-1] += (f[:, :, 2:] - 2 * f[:, :, 1:-1] + f[:, :, :-2]) / (dz * dz)
    # Boundary rows: copy nearest-interior Laplacian (one-sided extrapolation).
    # Acceptable for the ∇·F outer divergence, which uses central differences
    # that themselves reach boundary cells only at the second row inward.
    out[0, :, :] = out[1, :, :];  out[-1, :, :] = out[-2, :, :]
    out[:, 0, :] = out[:, 1, :];  out[:, -1, :] = out[:, -2, :]
    out[:, :, 0] = out[:, :, 1];  out[:, :, -1] = out[:, :, -2]
    return out


def _convective_uDel_u_3d(uc, vc, wc, dx, dy, dz):
    """Compute (u·∇)u component-wise at cell centers, central differences.

    Returns (Cx, Cy, Cz) where:
        Cx = u·∂u/∂x + v·∂u/∂y + w·∂u/∂z
        Cy = u·∂v/∂x + v·∂v/∂y + w·∂v/∂z
        Cz = u·∂w/∂x + v·∂w/∂y + w·∂w/∂z

    Boundary rows: one-sided difference (nearest interior gradient copied
    onto the boundary cell — equivalent to ∂u/∂n=0 ghost).

    Note: SOU/MINMOD upwind would be more consistent with the momentum
    sweep. For B.2 we use central differences (simpler, matches MMS
    smooth solutions). Phase B.4 will benchmark against MINMOD.
    """
    def _grad_x(f):
        g = np.zeros_like(f)
        g[1:-1, :, :] = (f[2:, :, :] - f[:-2, :, :]) / (2 * dx)
        g[0, :, :] = (f[1, :, :] - f[0, :, :]) / dx
        g[-1, :, :] = (f[-1, :, :] - f[-2, :, :]) / dx
        return g

    def _grad_y(f):
        g = np.zeros_like(f)
        g[:, 1:-1, :] = (f[:, 2:, :] - f[:, :-2, :]) / (2 * dy)
        g[:, 0, :] = (f[:, 1, :] - f[:, 0, :]) / dy
        g[:, -1, :] = (f[:, -1, :] - f[:, -2, :]) / dy
        return g

    def _grad_z(f):
        g = np.zeros_like(f)
        g[:, :, 1:-1] = (f[:, :, 2:] - f[:, :, :-2]) / (2 * dz)
        g[:, :, 0] = (f[:, :, 1] - f[:, :, 0]) / dz
        g[:, :, -1] = (f[:, :, -1] - f[:, :, -2]) / dz
        return g

    Cx = uc * _grad_x(uc) + vc * _grad_y(uc) + wc * _grad_z(uc)
    Cy = uc * _grad_x(vc) + vc * _grad_y(vc) + wc * _grad_z(vc)
    Cz = uc * _grad_x(wc) + vc * _grad_y(wc) + wc * _grad_z(wc)
    return Cx, Cy, Cz


def _divergence_centered_3d(Fx, Fy, Fz, dx, dy, dz):
    """∇·F at cell centers via central differences. Boundary one-sided."""
    div = np.zeros_like(Fx)
    div[1:-1, :, :] += (Fx[2:, :, :] - Fx[:-2, :, :]) / (2 * dx)
    div[:, 1:-1, :] += (Fy[:, 2:, :] - Fy[:, :-2, :]) / (2 * dy)
    div[:, :, 1:-1] += (Fz[:, :, 2:] - Fz[:, :, :-2]) / (2 * dz)
    # Boundary one-sided
    div[0, :, :] += (Fx[1, :, :] - Fx[0, :, :]) / dx
    div[-1, :, :] += (Fx[-1, :, :] - Fx[-2, :, :]) / dx
    div[:, 0, :] += (Fy[:, 1, :] - Fy[:, 0, :]) / dy
    div[:, -1, :] += (Fy[:, -1, :] - Fy[:, -2, :]) / dy
    div[:, :, 0] += (Fz[:, :, 1] - Fz[:, :, 0]) / dz
    div[:, :, -1] += (Fz[:, :, -1] - Fz[:, :, -2]) / dz
    return div


def assemble_ppe_source_3d(
    u_face: np.ndarray, v_face: np.ndarray, w_face: np.ndarray,
    mu_field: np.ndarray, K_arr: np.ndarray, cF_arr: np.ndarray,
    rho_field: np.ndarray, eps_field: np.ndarray,
    dx: float, dy: float, dz: float,
) -> np.ndarray:
    """Assemble S = ∇·F on cell centers.

    F = μ·∇²u − (μ/K)·u − ρ·c_F·|u|·u − ρ·(u·∇)u

    Each term is a 3-vector at cell centers. The PPE source is the
    divergence of this composite force field.

    Discretization
    --------------
    - Face → center via 0.5·(u_left + u_right) (MAC standard).
    - μ∇²u : 7-point cell-centered Laplacian, one-sided at boundaries.
    - (μ/K)·u : algebraic, K_arr broadcast across i.
    - ρ·c_F·|u|·u : algebraic.
    - ρ(u·∇)u : central differences (B.2 first-pass; SOU/MINMOD in B.4).
    - ∇·F : central differences, one-sided at boundaries.

    Phase B.2 (this commit) implements the full source pipeline using
    pure NumPy. Phase B.4 may replace inner kernels with numba for speed
    once MMS h-refinement validates correctness.

    Parameters
    ----------
    u_face, v_face, w_face : staggered face velocities.
    mu_field, rho_field, eps_field : (Nx, Ny, Nz) cell-centered.
    K_arr, cF_arr : (Ny, Nz). Broadcast across the i-axis.
    dx, dy, dz : uniform grid spacing.

    Returns
    -------
    S : (Nx, Ny, Nz) cell-centered scalar source.
    """
    Nx, Ny, Nz = rho_field.shape

    # Step 1 — face → cell-center velocities
    uc, vc, wc = _face_to_center_3d(u_face, v_face, w_face)

    # Step 2 — viscous term μ∇²u (per component, cell-center)
    Lap_u = _laplacian_centered_3d(uc, dx, dy, dz)
    Lap_v = _laplacian_centered_3d(vc, dx, dy, dz)
    Lap_w = _laplacian_centered_3d(wc, dx, dy, dz)
    Vx = mu_field * Lap_u
    Vy = mu_field * Lap_v
    Vz = mu_field * Lap_w

    # Step 3 — Brinkman drag −(μ/K)·u
    K_3d = np.broadcast_to(K_arr[None, :, :], (Nx, Ny, Nz))
    inv_K = 1.0 / np.maximum(K_3d, 1e-30)
    Bx = -mu_field * inv_K * uc
    By = -mu_field * inv_K * vc
    Bz = -mu_field * inv_K * wc

    # Step 4 — Forchheimer drag −ρ·c_F·|u|·u
    cF_3d = np.broadcast_to(cF_arr[None, :, :], (Nx, Ny, Nz))
    umag = np.sqrt(uc * uc + vc * vc + wc * wc)
    Forch = rho_field * cF_3d * umag
    Fx_forch = -Forch * uc
    Fy_forch = -Forch * vc
    Fz_forch = -Forch * wc

    # Step 5 — convection −ρ(u·∇)u
    Cx, Cy, Cz = _convective_uDel_u_3d(uc, vc, wc, dx, dy, dz)
    Fx_conv = -rho_field * Cx
    Fy_conv = -rho_field * Cy
    Fz_conv = -rho_field * Cz

    # Step 6 — assemble F
    Fx = Vx + Bx + Fx_forch + Fx_conv
    Fy = Vy + By + Fy_forch + Fy_conv
    Fz = Vz + Bz + Fz_forch + Fz_conv

    # Step 7 — divergence S = ∇·F
    S = _divergence_centered_3d(Fx, Fy, Fz, dx, dy, dz)
    return S


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
