"""Mass-flow mapping used by the sCO2 experimental-Q validation."""

import numpy as np
import pytest

from sjtu_tpmshx.df_surrogate.predict import SCO2_DF_METHOD
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.validation.cases.validate_sco2_exp_q import (
    GROSS_FACE_M2,
    _flow_velocity,
    _solver_geometry,
)


@pytest.mark.parametrize("topology", ["Diamond", "Gyroid"])
def test_solver_velocity_reconstructs_measured_mass_flow(topology):
    mdot = 0.05
    rho_in = 125.0
    geo = _solver_geometry(topology)
    u_in = _flow_velocity(mdot, rho_in, geo["void_area_m2"])

    assert geo["void_area_m2"] == pytest.approx(
        0.5 * geo["epsilon"] * GROSS_FACE_M2)
    assert rho_in * u_in * geo["void_area_m2"] == pytest.approx(
        mdot, rel=1e-12)


def test_explicit_reference_keeps_variable_density_inlet_mass_flux():
    rho = np.full((4, 5), 100.0)
    rho[:, 0] = 110.0
    solver = SIMPLESolver(
        W=0.04, H=0.05, Nx=4, Ny=5,
        tpms_type="Gyroid", L_cell_mm=7.0, t_mm=0.6,
        eps=0.7, r_h=1.0e-3, rho=rho, mu=2.0e-5, T_in=400.0,
        inlet_lo=0.0, inlet_hi=0.04, v_inlet=0.5,
        wall_refine=False, fluid_type="incompressible",
        rho_inlet_ref=125.0, df_method=SCO2_DF_METHOD,
    )
    solver.solve(max_iter=1, tol=0.0, verbose=False)

    assert np.allclose(solver.rho_field[:, 0] * solver.v[:, 0], 62.5)
