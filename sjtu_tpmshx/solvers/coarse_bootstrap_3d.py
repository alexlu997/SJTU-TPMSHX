"""Coarse-grid bootstrap for 3D SIMPLE solver (Phase C acceleration).

Strategy: build a half-resolution SIMPLE solver (Nx//2, Ny//2, Nz//2),
solve to a loose mass-residual tol (1e-3), trilinear-interpolate the
converged (u, v, w, P) onto the fine staggered grid, and inject as
the initial guess for the fine solve. The fine solver then reaches
its tight tol in ~half the outer iterations because the cold-start
transient is already absorbed at coarse resolution.

Geometry coefficients (K_arr, cF_arr, eps, v_inlet_field) are
block-averaged onto the coarse grid — geometry is NOT re-evaluated via
the TPMS sigmoid because the coarse grid is purely a bootstrap
device, not a physical answer.

Final correctness is preserved: the fine solver still converges to its
own tol gate. Coarse bootstrap is opt-in via `solver_fine.use_coarse_bootstrap`.

Skips silently if the coarse grid would be too small to be useful
(any axis < 4 cells).
"""
from __future__ import annotations
import numpy as np


def _block_average_2d(arr: np.ndarray, fy: int, fz: int) -> np.ndarray:
    """Average non-overlapping (fy × fz) blocks of a 2-D array."""
    Ny, Nz = arr.shape
    Ny_c = Ny // fy
    Nz_c = Nz // fz
    trim = arr[:Ny_c * fy, :Nz_c * fz]
    return trim.reshape(Ny_c, fy, Nz_c, fz).mean(axis=(1, 3))


def _block_average_2d_xz(arr: np.ndarray, fx: int, fz: int) -> np.ndarray:
    """Average (fx × fz) blocks for a (Nx, Nz) face-centred field."""
    Nx, Nz = arr.shape
    Nx_c = Nx // fx
    Nz_c = Nz // fz
    trim = arr[:Nx_c * fx, :Nz_c * fz]
    return trim.reshape(Nx_c, fx, Nz_c, fz).mean(axis=(1, 3))


def _block_average_3d(arr: np.ndarray, fx: int, fy: int, fz: int) -> np.ndarray:
    """Average non-overlapping (fx × fy × fz) blocks of a 3-D array."""
    Nx, Ny, Nz = arr.shape
    Nx_c = Nx // fx
    Ny_c = Ny // fy
    Nz_c = Nz // fz
    trim = arr[:Nx_c * fx, :Ny_c * fy, :Nz_c * fz]
    return trim.reshape(Nx_c, fx, Ny_c, fy, Nz_c, fz).mean(axis=(1, 3, 5))


def _trilinear_zoom(arr: np.ndarray, target_shape: tuple) -> np.ndarray:
    """Trilinear interpolate ``arr`` to the requested target shape."""
    from scipy.ndimage import zoom
    factors = tuple(t / s for t, s in zip(target_shape, arr.shape))
    return zoom(arr, factors, order=1, mode='nearest')


def bootstrap_simple_3d(solver_fine, max_iter_coarse: int = 200,
                         tol_coarse: float = 1e-3,
                         min_coarse_axis: int = 4,
                         verbose: bool = False) -> dict:
    """Run a coarse SIMPLE solve, prolongate (u,v,w,P) into ``solver_fine``.

    Parameters
    ----------
    solver_fine : SIMPLESolver3D
        The fine-grid solver instance to seed. Modified in-place: u, v, w,
        P arrays are overwritten with prolongated coarse fields.
    max_iter_coarse : int
        Cap on coarse SIMPLE iterations.
    tol_coarse : float
        Mass-residual gate for coarse solve. Loose by design (1e-3).
    min_coarse_axis : int
        Skip bootstrap if any coarse axis would be smaller than this.
    verbose : bool
        Print coarse solve summary.

    Returns
    -------
    info : dict with keys 'applied' (bool), 'coarse_iters' (int),
        'coarse_converged' (bool), 'coarse_residual' (float),
        'coarse_shape' (tuple), 'reason' (str if not applied).
    """
    Nx_c = solver_fine.Nx // 2
    Ny_c = solver_fine.Ny // 2
    Nz_c = solver_fine.Nz // 2

    if min(Nx_c, Ny_c, Nz_c) < min_coarse_axis:
        return {'applied': False, 'reason': 'coarse-too-small',
                'coarse_shape': (Nx_c, Ny_c, Nz_c)}

    # Defer import to dodge circular import (anderson lives in same package)
    from .simple_solver_3d import SIMPLESolver3D

    fx = solver_fine.Nx // Nx_c   # exactly 2 by construction
    fy = solver_fine.Ny // Ny_c
    fz = solver_fine.Nz // Nz_c

    # Block-average geometry coefficients onto coarse grid.
    K_arr_c = _block_average_2d(solver_fine.K_arr, fy, fz)
    cF_arr_c = _block_average_2d(solver_fine.cF_arr, fy, fz)

    # v_inlet_field is shaped (Nx, Nz) on solver — average accordingly.
    v_inlet_c = _block_average_2d_xz(solver_fine.v_inlet_field, fx, fz)

    # eps may be uniform (scalar) or zoned (3D array).
    eps_uniform = float(solver_fine.eps)
    has_zoned_eps = (solver_fine.eps_field.std() > 1e-12)
    if has_zoned_eps:
        eps_c_field = _block_average_3d(solver_fine.eps_field, fx, fy, fz)
        eps_scalar = float(eps_c_field.mean())
    else:
        eps_c_field = None
        eps_scalar = eps_uniform

    # Reuse mean rho for ideal-gas init (compressible re-establishes inside).
    rho_init = float(solver_fine.rho_field.mean())

    solver_coarse = SIMPLESolver3D(
        Lx=solver_fine.Lx, Ly=solver_fine.Ly, Lz=solver_fine.Lz,
        Nx=Nx_c, Ny=Ny_c, Nz=Nz_c,
        rho=rho_init, mu=solver_fine.mu,
        T_in=solver_fine.T_in,
        v_inlet=v_inlet_c,
        eps=eps_scalar,
        K_arr=K_arr_c, cF_arr=cF_arr_c,
        P_ref_abs=solver_fine.P_ref_abs,
        alpha_u=solver_fine.alpha_u,
        alpha_p=solver_fine.alpha_p,
        fluid_type=solver_fine.fluid_type,
        R_gas=solver_fine.R_gas,
        alpha_rho=solver_fine.alpha_rho,
    )
    if eps_c_field is not None:
        solver_coarse.eps_field = np.ascontiguousarray(
            eps_c_field, dtype=np.float64)
        solver_coarse._mu_eff_field = np.ascontiguousarray(
            solver_fine.mu / eps_c_field, dtype=np.float64)

    # Inherit Phase A adaptive AMG; do NOT enable Phase B Anderson on coarse
    # (less benefit, more risk for short solve).
    solver_coarse.use_adaptive_amg_tol = getattr(
        solver_fine, 'use_adaptive_amg_tol', True)
    solver_coarse.use_anderson = False

    converged, iters = solver_coarse.solve(
        max_iter=max_iter_coarse, tol=tol_coarse, verbose=verbose)
    res_final = float(solver_coarse.residuals[-1]) if solver_coarse.residuals else float('nan')

    # Prolongate (u, v, w, P) onto fine staggered shapes.
    solver_fine.u[:] = _trilinear_zoom(solver_coarse.u, solver_fine.u.shape)
    solver_fine.v[:] = _trilinear_zoom(solver_coarse.v, solver_fine.v.shape)
    solver_fine.w[:] = _trilinear_zoom(solver_coarse.w, solver_fine.w.shape)
    solver_fine.P[:] = _trilinear_zoom(solver_coarse.P, solver_fine.P.shape)

    # Re-impose inlet BC on fine (prolongation may smear it).
    solver_fine.v[:, 0, :] = solver_fine.v_inlet_field

    # Refresh fine ρ field from prolongated P + T_in. Compressible-only;
    # incompressible solvers leave rho_field untouched here.
    if solver_fine.fluid_type == 'ideal_gas':
        solver_fine._update_density()

    return {
        'applied': True,
        'coarse_iters': int(iters),
        'coarse_converged': bool(converged),
        'coarse_residual': res_final,
        'coarse_shape': (Nx_c, Ny_c, Nz_c),
    }
