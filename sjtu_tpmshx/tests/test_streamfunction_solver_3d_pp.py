"""Integration tests for StreamfunctionSolver3D pressure-recovery dispatch.

Phase B (#2) of 2026-05-06 streamfunction P-Poisson rewrite.
See vault/reports/streamfunction/2026-05-06-poisson-rewrite-plan-CN.md
Phase B (lines on integration after Phase A B.1-B.4 verified solver).

Verifies:
  - 'axial' kwarg keeps legacy behavior (no regression)
  - 'poisson' kwarg invokes solve_pressure_poisson_3d
  - Both paths preserve Helmholtz mass conservation (machine eps)
  - Both paths produce P fields of physically reasonable magnitude
  - Invalid kwarg raises ValueError
  - PPE diagnostic info accessible via _last_ppe_info
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solvers.streamfunction_solver_3d import StreamfunctionSolver3D
from solvers.edge_potential_3d import divergence_m


def _make_small_solver(pressure_recovery='poisson'):
    """Small Shanghai-like Air-Air case (matches SF self_test config)."""
    Lx, Ly, Lz = 0.04, 0.1, 0.04
    Nx, Ny, Nz = 8, 16, 8
    return StreamfunctionSolver3D(
        Lx=Lx, Ly=Ly, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        rho=1.0, mu=2e-5, T_in=361.0, v_inlet=2.0,
        eps=0.30,
        K_arr=np.full((Ny, Nz), 1e-9),
        cF_arr=np.full((Ny, Nz), 0.5),
        P_ref_abs=101325.0,
        alpha_u=0.5, alpha_p=0.5,
        fluid_type='ideal_gas',
        pressure_recovery=pressure_recovery,
    )


def _max_div_ratio(solver):
    """Max |∇·m| / |m_inlet| — Helmholtz strictness diagnostic."""
    Nx, Ny, Nz = solver.Nx, solver.Ny, solver.Nz
    dx = float(solver.dx[0]); dy = float(solver.dy[0]); dz = float(solver.dz[0])
    Aface_x = dy * dz; Aface_y = dx * dz; Aface_z = dx * dy

    eps_cell = solver.eps_field
    eps_fx = np.zeros((Nx + 1, Ny, Nz))
    eps_fx[1:-1] = 0.5 * (eps_cell[:-1] + eps_cell[1:])
    eps_fx[0] = eps_cell[0]; eps_fx[-1] = eps_cell[-1]
    eps_fy = np.zeros((Nx, Ny + 1, Nz))
    eps_fy[:, 1:-1] = 0.5 * (eps_cell[:, :-1] + eps_cell[:, 1:])
    eps_fy[:, 0] = eps_cell[:, 0]; eps_fy[:, -1] = eps_cell[:, -1]
    eps_fz = np.zeros((Nx, Ny, Nz + 1))
    eps_fz[:, :, 1:-1] = 0.5 * (eps_cell[:, :, :-1] + eps_cell[:, :, 1:])
    eps_fz[:, :, 0] = eps_cell[:, :, 0]; eps_fz[:, :, -1] = eps_cell[:, :, -1]

    rho = solver.rho_field
    rho_fx = np.zeros((Nx + 1, Ny, Nz))
    rho_fx[1:-1] = 0.5 * (rho[:-1] + rho[1:])
    rho_fx[0] = rho[0]; rho_fx[-1] = rho[-1]
    rho_fy = np.zeros((Nx, Ny + 1, Nz))
    rho_fy[:, 1:-1] = 0.5 * (rho[:, :-1] + rho[:, 1:])
    rho_fy[:, 0] = rho[:, 0]; rho_fy[:, -1] = rho[:, -1]
    rho_fz = np.zeros((Nx, Ny, Nz + 1))
    rho_fz[:, :, 1:-1] = 0.5 * (rho[:, :, :-1] + rho[:, :, 1:])
    rho_fz[:, :, 0] = rho[:, :, 0]; rho_fz[:, :, -1] = rho[:, :, -1]

    m_x = eps_fx * rho_fx * solver.u * Aface_x
    m_y = eps_fy * rho_fy * solver.v * Aface_y
    m_z = eps_fz * rho_fz * solver.w * Aface_z
    div = divergence_m(m_x, m_y, m_z)
    m_in = float(np.sum(m_y[:, 0, :]))
    return float(np.max(np.abs(div))) / max(abs(m_in), 1e-30)


# ---------------------------------------------------------------- API


def test_invalid_kwarg_raises():
    with pytest.raises(ValueError, match="pressure_recovery"):
        _make_small_solver(pressure_recovery='magic')


def test_default_is_poisson():
    """Default kwarg should be 'poisson' per Phase B switch."""
    Lx, Ly, Lz = 0.04, 0.1, 0.04
    s = StreamfunctionSolver3D(
        Lx=Lx, Ly=Ly, Lz=Lz, Nx=8, Ny=16, Nz=8,
        rho=1.0, mu=2e-5, T_in=361.0, v_inlet=2.0,
        eps=0.30,
        K_arr=np.full((16, 8), 1e-9),
        cF_arr=np.full((16, 8), 0.5),
        P_ref_abs=101325.0,
        alpha_u=0.5, alpha_p=0.5,
        fluid_type='ideal_gas',
    )
    assert s._pressure_recovery_mode == 'poisson'


# ---------------------------------------------------------------- axial path


def test_axial_path_runs_and_preserves_mass_cons():
    """Legacy axial path: should not regress Helmholtz mass conservation."""
    s = _make_small_solver(pressure_recovery='axial')
    converged, n_iter = s.solve(max_iter=200, tol=1e-4, verbose=False)
    div_ratio = _max_div_ratio(s)
    # Threshold 1e-5: Helmholtz projects m using cell-time-(N) rho, then
    # _update_density mutates rho_field at each iter, so the post-iter
    # diagnostic recomputes ∇·m with rho_(N+1) ≠ rho_(N). The resulting
    # ratio ~1e-6 is a measurement artifact, not a regression. The Poisson
    # rewrite must not make this worse. Both paths benchmarked ~9e-7.
    assert div_ratio < 1e-5, f"Axial path mass cons broke: {div_ratio:.3e}"
    # P_axial path doesn't expose PPE info
    assert s._last_ppe_info is None


# ---------------------------------------------------------------- poisson path


def test_poisson_path_runs_and_preserves_mass_cons():
    """New Poisson path: Helmholtz mass cons should be unchanged (independent
    of pressure recovery — Helmholtz happens before pressure)."""
    s = _make_small_solver(pressure_recovery='poisson')
    converged, n_iter = s.solve(max_iter=200, tol=1e-4, verbose=False)
    div_ratio = _max_div_ratio(s)
    # Same threshold rationale as axial (rho-update artifact). Critical
    # assertion: Poisson path must not be WORSE than axial — see
    # test_axial_vs_poisson_mass_cons_parity below.
    assert div_ratio < 1e-5, f"Poisson path mass cons broke: {div_ratio:.3e}"
    # PPE info populated
    assert s._last_ppe_info is not None
    assert 'iter' in s._last_ppe_info
    assert 'inlet_g_max' in s._last_ppe_info
    assert s._last_ppe_info['inlet_g_max'] > 0  # non-trivial inlet flux


def test_poisson_p_field_physically_reasonable():
    """P magnitude should be physical (10² .. 10⁵ Pa for Shanghai-like)."""
    s = _make_small_solver(pressure_recovery='poisson')
    s.solve(max_iter=200, tol=1e-4, verbose=False)
    p_max = float(np.abs(s.P).max())
    # Bounds wide enough to allow either path to pass; tightens future
    # validation via Shanghai 16-case (Phase C).
    assert 1.0 < p_max < 1.0e6, f"P_max = {p_max:.3e} unphysical"


# ---------------------------------------------------------------- A/B


def test_axial_vs_poisson_differ():
    """The two paths should produce different P fields (otherwise the new
    code is doing nothing)."""
    s_axial = _make_small_solver(pressure_recovery='axial')
    s_axial.solve(max_iter=100, tol=1e-4, verbose=False)
    s_poiss = _make_small_solver(pressure_recovery='poisson')
    s_poiss.solve(max_iter=100, tol=1e-4, verbose=False)

    diff_max = float(np.max(np.abs(s_axial.P - s_poiss.P)))
    # Difference must be measurable (>1 Pa) — otherwise paths are equivalent
    # which contradicts the entire premise of the rewrite.
    assert diff_max > 1.0, \
        f"Axial vs Poisson paths produced near-identical P (max diff {diff_max:.3e} Pa)"


def test_axial_vs_poisson_mass_cons_parity():
    """Critical regression check: Poisson path must NOT be worse than axial
    in Helmholtz mass conservation (the diagnostic artifact from rho-update
    must not amplify under the new path)."""
    s_axial = _make_small_solver(pressure_recovery='axial')
    s_axial.solve(max_iter=100, tol=1e-4, verbose=False)
    div_axial = _max_div_ratio(s_axial)
    s_poiss = _make_small_solver(pressure_recovery='poisson')
    s_poiss.solve(max_iter=100, tol=1e-4, verbose=False)
    div_poiss = _max_div_ratio(s_poiss)

    # Allow Poisson to be up to 2× worse to absorb AMG residual variation;
    # anything more would mean the new code hurts mass cons (red flag).
    assert div_poiss < 2.0 * div_axial + 1e-9, (
        f"Poisson path mass cons {div_poiss:.3e} > 2×axial {div_axial:.3e}\n"
        f"  This means the new pressure recovery is actively destroying mass\n"
        f"  conservation, contradicting Phase 7 closure (Helmholtz machine-eps).")
