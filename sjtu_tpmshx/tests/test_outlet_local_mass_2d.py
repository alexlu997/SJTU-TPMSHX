"""Pressure-reference outlet cells still need local mass closure."""
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.solvers._kernels_simple_2d import _correct_jit
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver


@pytest.mark.parametrize('east_factor', [-1., 1., 3.])
def test_pressure_outlet_includes_transverse_flux(east_factor):
    # Middle outlet CV: Fs=2.04, Fw=.54, Fe=1.8 kg/s/m.
    # Thus Fn must be .78, giving v_out=.78/(4.8*.3)=13/24.
    rho = np.array([[2., 4.], [4., 6.], [6., 8.]])
    eps = np.array([[.4, .6], [.5, .8], [.7, .9]])
    u = np.zeros((4, 2))
    v = np.zeros((3, 3))
    u[1, -1], u[2, -1] = .25, .5 * east_factor
    v[1, -2] = 2.
    P = np.zeros((3, 2))
    _correct_jit(u, v, P, np.zeros_like(P), np.zeros_like(u), np.zeros_like(v),
                 np.ones(3), np.ones(3), np.array([0., 1., 0.]),
                 3, 2, np.array([.2, .3, .5]), np.array([.4, .6]), .3, rho, eps)
    expected_flux = 2.04 + .54 - 1.8 * east_factor
    assert v[1, -1] == pytest.approx(expected_flux / (4.8 * .3), rel=1e-13)
    assert v[0, -1] == v[2, -1] == 0.

    # Exercise the real solve closeout, not just its preceding kernel.
    # Inlet mass is .8*.2 + 2*.3 + 4.2*.5 = 2.86 kg/s/m, unlike Fn.
    # Scaling Fn to that total would hide the interior defect and undo this CV.
    solver = SimpleNamespace(
        Nx=3, Ny=2, u=u, v=v, rho_field=rho, eps_field=eps,
        dx_arr=np.array([.2, .3, .5]), dy_arr=np.array([.4, .6]),
        outlet_frac=np.array([0., 1., 0.]))
    assert not np.isclose(expected_flux, 2.86)
    SIMPLESolver._enforce_mass_conservation(solver, verbose=False)
    assert solver.v[1, -1] * 4.8 * .3 == pytest.approx(expected_flux, rel=1e-13)
    assert solver.v[0, -1] == solver.v[2, -1] == 0.
