"""Exercise the wired outer property refresh without running numerical sweeps."""
import inspect

import numpy as np
import pytest

from sjtu_tpmshx.pipelines import run_stack_3d_stages as stages


@pytest.mark.parametrize('fluid', ['air', 'water', 'sco2'])
@pytest.mark.parametrize('direction', range(6))
def test_outer_temperature_properties_share_simple_frame(monkeypatch, fluid, direction):
    # Unequal dimensions and a gradient on every axis expose wrong permutations
    # as well as missing reflections. Both A and B visit all six directions.
    shape = (4, 5, 6)
    lengths = (.04, .05, .06)
    directions = (direction, (direction + 2) % 6)
    pressure = 12e6 if fluid == 'sco2' else 2e6

    def port(d):
        cross1 = 1 if d < 2 else 0
        cross2 = 1 if d >= 4 else 2
        w, wz = lengths[cross1], lengths[cross2]
        return dict(dir=d, in_ctr=w/2, in_w=w, out_ctr=w/2, out_w=w,
                    in_z_ctr=wz/2, in_z_w=wz, out_z_ctr=wz/2, out_z_w=wz)

    cfg = dict(L=lengths[0], H=lengths[1], Lz=lengths[2],
               Nx=shape[0], Ny=shape[1], Nz=shape[2],
               u_A=.02, u_B=.02, T_inA=350., T_inB=300.,
               P_inA=pressure, P_inB=pressure, T_s_init=325.,
               tpms_type='Gyroid', Lcell=7., t_wall=.6, k_s=16.,
               eps=stages.tpms_geometry('Gyroid', 7., .6, 16.)['epsilon'],
               fluid_type_A=fluid, fluid_type_B=fluid,
               fluid_A_cfg=port(directions[0]), fluid_B_cfg=port(directions[1]),
               wall_refine_3d=False, outer_anderson=False, p_in_shooting=False)
    monkeypatch.delenv('TPMSHX_SCO2_COMPRESSIBLE', raising=False)
    observations = {}

    def solve(solver, **kwargs):
        # The real update_T_field and all post-refresh code execute; only the
        # expensive SIMPLE sweeps are replaced by an observation at entry.
        if id(solver) in observations:
            observations[id(solver)].append(tuple(
                getattr(solver, name).copy()
                for name in ('T_field', 'rho_field', 'mu_field', '_mu_eff_field')))
        return True, 0

    monkeypatch.setattr(stages.SIMPLESolver3D, 'solve', solve)
    prob = stages._build_3d_problem(cfg)
    hv = stages._build_hv_machinery(prob)
    model = stages.fluid_props.get(fluid)

    def drive(*, post, **kwargs):
        state = inspect.getclosurevars(post).nonlocals
        solvers = (prob.sA, prob.sB)
        for solver in solvers:
            observations[id(solver)] = []
            solver.P[:] = np.arange(solver.P.size).reshape(solver.P.shape) * 10.
        i, j, k = np.indices(shape)
        marker = i + 2*j + .5*k
        # Use existing mutable thermal warm-start fields to feed the actual
        # callback; no copied source or stand-alone mapping helper is tested.
        for outer in (0, 1):
            state['Ta'][:] = 340. - marker - outer
            state['Tb'][:] = 310. + marker + 2*outer
            expected = []
            for solver, d, temperature in zip(solvers, directions,
                                               (state['Ta'], state['Tb'])):
                mapped = np.empty_like(solver.T_field)
                # Independent index oracle: SIMPLE j is the stream coordinate.
                for x, y, z in np.ndindex(mapped.shape):
                    real = [y, x, z] if d < 2 else ([x, y, z] if d < 4 else [x, z, y])
                    if d % 2:
                        real[d//2] = shape[d//2] - 1 - real[d//2]
                    mapped[x, y, z] = temperature[tuple(real)]
                rho = ((solver.P_ref_abs + solver.P) / (stages.R_AIR * mapped)
                       if model.compressible else model.rho(mapped, pressure))
                mu = model.mu(mapped, pressure)
                if outer:
                    rho = stages._ALPHA_T*rho + (1-stages._ALPHA_T)*solver.rho_field
                    # update_T_field refreshes air mu before A's blend and
                    # after B's blend. Preserve that existing ordering.
                    if not model.compressible:
                        mu = stages._ALPHA_T*mu + (1-stages._ALPHA_T)*solver.mu_field
                expected.append((mapped, rho, mu, mu/solver.eps_field))
            post(outer, None)
            for solver, fields in zip(solvers, expected):
                assert len(observations[id(solver)]) == outer + 1
                for actual, wanted in zip(observations[id(solver)][-1], fields):
                    np.testing.assert_allclose(actual, wanted, rtol=2e-15, atol=0.)
                    assert actual.flags.c_contiguous
        return 1, False

    monkeypatch.setattr(stages, 'run_outer_coupling', drive)
    stages._run_outer_coupling_3d(prob, hv)
