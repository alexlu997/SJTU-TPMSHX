import numpy as np

from sjtu_tpmshx.solvers import sco2_props
from sjtu_tpmshx.solvers.ltne_enthalpy_2d import solve_sco2_enthalpy_2d


def test_fullface_counterflow_conserves_true_enthalpy():
    nx, ny = 24, 3
    dx = np.full(nx, 0.21 / nx)
    dy = np.full(ny, 0.03 / ny)
    PA = np.linspace(12.0e6, 11.99e6, nx)[:, None]
    PB = np.linspace(11.99e6, 12.0e6, nx)[:, None]
    rho_A = sco2_props.sco2_density(500.0, 12.0e6)
    rho_B = sco2_props.sco2_density(330.0, 12.0e6)
    mA = np.full(ny, 0.35 * rho_A * 0.8 * dy[0])
    mB = np.full(ny, 0.35 * rho_B * 0.5 * dy[0])
    Ta, Tb, Ts, info = solve_sco2_enthalpy_2d(
        500.0, 330.0, PA, PB, mA, mB, 8.0e5, 8.0e5, 5.0,
        dx, dy, max_iter=3000, tol=1e-3,
    )
    assert info["converged"]
    assert info["energy_imbalance_rel"] < 0.05
    assert np.all(np.isfinite(Ta)) and np.all(np.isfinite(Tb))
    assert Ta[-1].mean() < 500.0
    assert Tb[0].mean() > 330.0
    assert Tb.min() <= Ts.mean() <= Ta.max()
