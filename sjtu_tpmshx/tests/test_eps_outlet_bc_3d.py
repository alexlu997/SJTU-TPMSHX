"""N1 (full-debug audit 2026-06-28): the 3D SIMPLE continuity operator is the
macroscopic porous form ∇·(ε·ρ·u)=0 (the PPE/residual receive ε·ρ), but the
outlet velocity extrapolation that closes mass at the open boundary rescaled by
the PLAIN ρ ratio, conserving ρ·v instead of ε·ρ·v. For y-zoned ε that leaves a
persistent outlet-cell divergence 0.5·v·ρ·(ε_{Ny-1}−ε_{Ny-2}). The fix rescales
by the ε·ρ ratio; it reduces EXACTLY to the old code for uniform ε (golden
bit-identical).
"""
import numpy as np
import pytest

from sjtu_tpmshx.solvers.simple_solver_3d import _v_bc_3d, _correct_jit_3d


def test_v_bc_outlet_uses_eps_rho_ratio_when_zoned():
    Nx, Ny, Nz = 1, 3, 1
    v = np.zeros((Nx, Ny + 1, Nz))
    v[0, Ny - 1, 0] = 2.0
    vin = np.zeros((Nx, Nz))
    rho = np.ones((Nx, Ny, Nz)); rho[0, 1, 0] = 1.2; rho[0, 2, 0] = 1.0
    eps = np.ones((Nx, Ny, Nz)); eps[0, 1, 0] = 0.6; eps[0, 2, 0] = 0.4  # zoned y
    of = np.ones((Nx, Nz))
    _v_bc_3d(v, vin, rho, eps, of, Nx, Ny, Nz)
    er_in = 0.5 * (eps[0, 1, 0] * rho[0, 1, 0] + eps[0, 2, 0] * rho[0, 2, 0])
    er_out = eps[0, 2, 0] * rho[0, 2, 0]
    assert v[0, Ny, 0] == pytest.approx(2.0 * er_in / er_out)


def test_v_bc_outlet_uniform_eps_reduces_to_rho_ratio():
    """Uniform ε -> the ε·ρ ratio collapses to the plain ρ ratio (the old code
    path) -> bit-identical golden."""
    Nx, Ny, Nz = 1, 3, 1
    v = np.zeros((Nx, Ny + 1, Nz)); v[0, Ny - 1, 0] = 2.0
    vin = np.zeros((Nx, Nz))
    rho = np.ones((Nx, Ny, Nz)); rho[0, 1, 0] = 1.2; rho[0, 2, 0] = 1.0
    eps = np.full((Nx, Ny, Nz), 0.5)             # uniform
    of = np.ones((Nx, Nz))
    _v_bc_3d(v, vin, rho, eps, of, Nx, Ny, Nz)
    rho_in = 0.5 * (rho[0, 1, 0] + rho[0, 2, 0]); rho_out = rho[0, 2, 0]
    assert v[0, Ny, 0] == pytest.approx(2.0 * rho_in / rho_out)


def test_v_bc_outlet_wall_cell_pins_zero():
    Nx, Ny, Nz = 1, 3, 1
    v = np.zeros((Nx, Ny + 1, Nz)); v[0, Ny - 1, 0] = 2.0
    vin = np.zeros((Nx, Nz))
    rho = np.ones((Nx, Ny, Nz)); eps = np.full((Nx, Ny, Nz), 0.5)
    of = np.zeros((Nx, Nz))                       # wall (closed)
    _v_bc_3d(v, vin, rho, eps, of, Nx, Ny, Nz)
    assert v[0, Ny, 0] == 0.0


def test_correct_outlet_uses_eps_rho_ratio_when_zoned():
    """_correct_jit_3d carries the identical outlet block — same ε·ρ fix."""
    Nx, Ny, Nz = 1, 3, 1
    u = np.zeros((Nx + 1, Ny, Nz)); w = np.zeros((Nx, Ny, Nz + 1))
    v = np.zeros((Nx, Ny + 1, Nz)); v[0, Ny - 1, 0] = 2.0
    P = np.zeros((Nx, Ny, Nz)); Pp = np.zeros((Nx, Ny, Nz))
    d_u = np.zeros((Nx + 1, Ny, Nz)); d_v = np.zeros((Nx, Ny + 1, Nz))
    d_w = np.zeros((Nx, Ny, Nz + 1))
    vin = np.zeros((Nx, Nz))
    rho = np.ones((Nx, Ny, Nz)); rho[0, 1, 0] = 1.2; rho[0, 2, 0] = 1.0
    eps = np.ones((Nx, Ny, Nz)); eps[0, 1, 0] = 0.6; eps[0, 2, 0] = 0.4
    omask = np.ones((Nx, Nz), dtype=np.bool_)
    _correct_jit_3d(u, v, w, P, Pp, d_u, d_v, d_w, vin, Nx, Ny, Nz, 0.5,
                    rho, eps, omask)
    er_in = 0.5 * (eps[0, 1, 0] * rho[0, 1, 0] + eps[0, 2, 0] * rho[0, 2, 0])
    er_out = eps[0, 2, 0] * rho[0, 2, 0]
    assert v[0, Ny, 0] == pytest.approx(2.0 * er_in / er_out)
