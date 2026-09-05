"""A converged LTNE chunk must not hide alternating single-sweep updates."""

import inspect

import numpy as np
import pytest

from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
from sjtu_tpmshx.solvers import ltne_energy
from sjtu_tpmshx.tests.test_port_grid_alignment_2d import _case


@pytest.mark.parametrize('kernel_name', ['_gs_full_chunk', '_gs_full_chunk_rb'])
@pytest.mark.parametrize('direction', [0, 1, 2, 3])
def test_outlet_solid_consumes_unrelaxed_a_candidate(kernel_name, direction):
    # No transport: A's candidate is old Ts=350. The solid must consume that
    # candidate before the outlet copy, so Ts_out=(2*350+300)/3, not (2*365+300)/3.
    n = 4
    zero = np.zeros((n, n))
    one = np.ones((n, n))
    Ta, Tb, Ts = (np.full((n, n), value) for value in (400.0, 300.0, 350.0))
    getattr(ltne_energy, kernel_name)(
        Ta, Tb, Ts, n, n, np.ones(n), np.ones(n),
        zero, zero, zero, 2 * one, one, one, one, one, one,
        zero, zero, zero, zero, direction, 0,
        np.full(n, 400.0), np.full(n, 300.0), np.ones(n), np.ones(n),
        1, 1, 0)
    outlet = ((-1, slice(None)), (0, slice(None)),
              (slice(None), -1), (slice(None), 0))[direction]
    np.testing.assert_allclose(Ts[outlet], (2 * 350.0 + 300.0) / 3, atol=1e-12, rtol=0)
    # The final A outlet still copies its relaxed interior neighbour.
    np.testing.assert_allclose(Ta[outlet], 365.0, atol=1e-12, rtol=0)
    np.testing.assert_array_equal(Tb, np.full((n, n), 300.0))


@pytest.mark.slow
def test_swapped_port_ltne_settles_between_consecutive_sweeps(monkeypatch):
    kernel = ltne_energy._gs_full_chunk
    signature = inspect.signature(kernel.py_func)
    final_main = {}

    def capture(*args, **kwargs):
        result = kernel(*args, **kwargs)
        bound = signature.bind(*args, **kwargs).arguments
        if (bound['Nx'], bound['Ny']) == (40, 40):
            final_main.update({key: value.copy() if isinstance(value, np.ndarray) else value
                               for key, value in bound.items()})
        return result

    monkeypatch.setattr(ltne_energy, '_gs_full_chunk', capture)
    cfg = _case((2, 0))
    cfg.geometry.t_wall_mm = 0.4
    cfg.fluid_A.u_mps = cfg.fluid_B.u_mps = 10.0
    cfg.fluid_A.T_in_K = 600.0
    cfg.fluid_B.T_in_K = 300.0
    result = Pipeline2D(cfg).run()
    assert final_main

    # Observe detached fields every sweep, not only at the even 500-step gate.
    final_main['n_iters'] = 1
    for step in range(20):
        previous = [final_main[key].copy() for key in ('Ta', 'Tb', 'Ts')]
        kernel(*final_main.values())
        changes = [float(np.max(np.abs(final_main[key] - old)))
                   for key, old in zip(('Ta', 'Tb', 'Ts'), previous)]
        assert max(changes) < 0.01, (step, changes)
    assert result.converged, result.diagnostics['convergence_detail']
