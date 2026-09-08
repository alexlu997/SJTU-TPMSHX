"""Actual 3D guard boundaries with numerical sweeps replaced, not full solves."""
import inspect

import numpy as np
import pytest

from sjtu_tpmshx.pipelines import run_stack_3d_stages as stages
from sjtu_tpmshx.solvers import fluid_props, ltne_enthalpy_3d as ent
from sjtu_tpmshx.tests.test_3d_model_enthalpy_transport import _pipeline_cfg
from sjtu_tpmshx.domain.run_warnings import warning_scope, range_context


@pytest.mark.parametrize('side', range(3))
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_finite_temperature_reports_first_c_index_and_original_value(side, bad):
    fields = [np.full((2, 3, 2), 300., order='F') for _ in range(3)]
    fields[side][0, 2, 1] = bad
    fields[side][1, 0, 0] = np.nan  # earlier in Fortran order, later in C order
    with pytest.raises(ValueError) as error:
        fluid_props.check_finite_temperatures(*fields, where='test real-cell')
    assert type(error.value) is ValueError
    assert str(error.value) == (
        f'test real-cell: {("A", "B", "solid")[side]} temperature '
        f'index=(0, 2, 1), T={bad:g} K is non-finite')
    assert np.isnan(fields[side][0, 2, 1]) if np.isnan(bad) else fields[side][0, 2, 1] == bad


def test_finite_temperature_none_and_finite_values_do_not_query_eos(monkeypatch):
    def forbidden(*args):
        pytest.fail('finite check must not query EOS')
    monkeypatch.setattr(fluid_props.CP, 'AbstractState', forbidden)
    field = np.array([[-1., 0., 1.]])  # finite check is not a new physical range
    original = field.copy()
    fluid_props.check_finite_temperatures(None, None, None, where='cold start')
    fluid_props.check_finite_temperatures(300., field, None, where='warm start')
    np.testing.assert_array_equal(field, original)
    with pytest.raises(ValueError, match=r'A temperature index=\(\), T=inf'):
        fluid_props.check_finite_temperatures(np.inf, np.nan, np.nan, where='scalar')


def _problem(monkeypatch, pair):
    cfg = _pipeline_cfg(pair)
    for side, fluid in zip(('A', 'B'), pair):
        if fluid == 'sco2':
            cfg['P_in' + side] = 12e6
    monkeypatch.setattr(stages.SIMPLESolver3D, 'solve', lambda *a, **k: (True, 0))
    prob = stages._build_3d_problem(cfg)
    return prob, stages._build_hv_machinery(prob)


@pytest.mark.parametrize('fluid', ['air', 'water', 'sco2'])
@pytest.mark.parametrize('zoned', [False, True])
def test_local_hv_records_full_raw_field_and_preserves_values(monkeypatch, fluid, zoned):
    prob, hv = _problem(monkeypatch, (fluid, fluid))
    shape = (prob.Nx, prob.Ny, prob.Nz)
    length = np.full(shape, prob.Lcell) if zoned else None
    thickness = np.full(shape, prob.t_wall) if zoned else None
    if zoned:
        length[1:] += .1
    velocity = np.zeros(shape)
    velocity[-1] = .001
    args = (length, thickness, velocity, prob.T_inA, prob.P_inA, fluid)
    with warning_scope({}):
        expected = hv._build_hv_local_3d(*args)
    labels = ('A', 'main', 'real-cell(x,y,z)-hv-stream')
    with warning_scope({}) as records, range_context(side=labels[0], stage=labels[1], layout=labels[2]):
        for _ in range(2):
            actual = hv._build_hv_local_3d(*args)
    np.testing.assert_array_equal(actual, expected)
    raw = records[('nu_raw', fluid, prob.tpms_type, shape, labels)]
    assert raw.size == velocity.size
    assert raw.minimum[1] == (0, 0, 0) and 0 < raw.minimum[0] < 1.
    source_shape = () if zoned else shape
    source_labels = ('A', 'main', 'scalar-zoned-call') if zoned else labels
    source = records[('nu', fluid, prob.tpms_type, source_shape, source_labels)]
    assert source.size == (1 if zoned else velocity.size)
    assert source.minimum[0] == 1.


def test_temperature_warning_states_keep_warm_return_final_and_face_separate(monkeypatch):
    prob, hv = _problem(monkeypatch, ('air', 'air'))
    shape = (prob.Nx, prob.Ny, prob.Nz)
    fields = [np.full(shape, t) for t in (1150., 1200., 325.)]
    monkeypatch.setattr(stages, 'solve_full_domain_3d', lambda *a, **k: (
        *fields, dict(converged=True, iterations=1, residual=0.)))

    def drive(*, step, **kwargs):
        state = inspect.getclosurevars(step).nonlocals
        state['Ta'][:] = 1100.
        state['Tb'][:] = 1120.
        step(0)
        return 0, True

    monkeypatch.setattr(stages, 'run_outer_coupling', drive)
    with warning_scope({}) as records:
        outer = stages._run_outer_coupling_3d(prob, hv)
        stages._extract_3d_metrics(prob, hv, outer)
    for side, warm, final in (('A', 1100., 1150.), ('B', 1120., 1200.)):
        for stage, layout, value in (
            ('main', 'real-cell(x,y,z)-warm', warm),
            ('main', 'real-cell(x,y,z)-return', final),
            ('final', 'real-cell(x,y,z)', final),
            ('final', 'outlet-cell-face(real-transverse-axes)', final),
        ):
            record_shape = shape[:2] if layout.startswith('outlet') else shape
            record = records[('property_state', 'air_cp', record_shape, (side, stage, layout))]
            assert record.minimum[0] == record.maximum[0] == value
            assert record.size == np.prod(record_shape)
    assert all(key[-1][0] != 'solid' for key in records)


def test_true_h_air_return_does_not_use_empirical_temperature_windows(monkeypatch):
    prob, hv = _problem(monkeypatch, ('air', 'sco2'))
    shape = (prob.Nx, prob.Ny, prob.Nz)
    fields = [np.full(shape, t) for t in (1200., 310., 325.)]
    info = dict(converged=True, iterations=1, residual=0., Q_A=1., Q_B=1.)
    monkeypatch.setattr(stages, 'solve_full_domain_3d', lambda *a, **k: (*fields, info))
    monkeypatch.setattr(ent, 'solve_ltne_enthalpy_3d_pipeline', lambda *a, **k: (*fields, info))
    from sjtu_tpmshx.solvers import ltne_energy_3d
    monkeypatch.setattr(ltne_energy_3d, '_project_faces_div_free', lambda u, v, w, *a: (u, v, w))

    def drive(*, step, **kwargs):
        step(0)
        return 0, True

    monkeypatch.setattr(stages, 'run_outer_coupling', drive)
    with warning_scope({}) as records:
        stages._run_outer_coupling_3d(prob, hv)
    assert not any(key[0] == 'property_state' for key in records)


@pytest.mark.parametrize('fluid', ['air', 'water'])
def test_zoned_bulk_re_has_cell_denominator_and_scalar_source(monkeypatch, fluid):
    prob, _ = _problem(monkeypatch, (fluid, fluid))
    shape = (prob.Nx, prob.Ny, prob.Nz)
    prob.L_mm_field = np.full(shape, prob.Lcell)
    prob.L_mm_field[1:] += .1
    prob.t_field_3d = np.full(shape, prob.t_wall)
    with warning_scope({}) as records:
        stages._build_hv_machinery(prob)
    for side in ('A', 'B'):
        raw = records[('nu_raw', fluid, prob.tpms_type, shape,
                       (side, 'inlet', 'real-cell(x,y,z)-bulk-Re'))]
        source = records[('nu', fluid, prob.tpms_type, (),
                          (side, 'inlet', 'scalar-zoned-call'))]
        assert raw.size == np.prod(shape) and source.size == 1


@pytest.mark.parametrize('phase', ['warm', 'temperature', 'enthalpy'])
@pytest.mark.parametrize('side', range(3))
def test_wired_nonfinite_boundaries_precede_post_and_result(monkeypatch, phase, side):
    prob, hv = _problem(monkeypatch, ('air', 'sco2') if phase == 'enthalpy' else ('air', 'air'))
    shape = (prob.Nx, prob.Ny, prob.Nz)
    fields = [np.full(shape, t) for t in (350., 300., 325.)]
    fields[side][1, 2, 1] = np.inf

    def thermal(*args, **kwargs):
        output = fields if phase == 'temperature' else [np.full(shape, t) for t in (350., 300., 325.)]
        return (*output, dict(converged=True, iterations=1, residual=0.))

    monkeypatch.setattr(stages, 'solve_full_domain_3d', thermal)
    monkeypatch.setattr(ent, 'solve_ltne_enthalpy_3d_pipeline', lambda *a, **k: (*fields, {}))
    # Projection is unrelated to the return guard; keep this a no-sweep test.
    from sjtu_tpmshx.solvers import ltne_energy_3d
    monkeypatch.setattr(ltne_energy_3d, '_project_faces_div_free', lambda u, v, w, *a: (u, v, w))

    def drive(*, step, **kwargs):
        if phase == 'warm':
            state = inspect.getclosurevars(step).nonlocals
            state[('Ta', 'Tb', 'Ts')[side]][:] = fields[side]
        step(0)
        pytest.fail('invalid temperature reached normal outer return')

    monkeypatch.setattr(stages, 'run_outer_coupling', drive)
    where = '3D temperature warm start' if phase == 'warm' else f'3D {phase} return'
    with pytest.raises(ValueError) as error:
        stages._run_outer_coupling_3d(prob, hv)
    assert type(error.value) is ValueError
    assert str(error.value) == (
        f'{where}: {("A", "B", "solid")[side]} temperature '
        'index=(1, 2, 1), T=inf K is non-finite')


@pytest.mark.parametrize('warm', [False, True])
def test_water_error_still_precedes_generic_finite_error(monkeypatch, warm):
    prob, hv = _problem(monkeypatch, ('air', 'water'))
    fields = [np.full((prob.Nx, prob.Ny, prob.Nz), t) for t in (350., 300., 325.)]
    fields[0][0, 0, 0] = np.inf
    fields[1][1, 2, 1] = np.nan
    monkeypatch.setattr(stages, 'solve_full_domain_3d', lambda *a, **k: (*fields, {}))

    def drive(*, step, **kwargs):
        if warm:
            state = inspect.getclosurevars(step).nonlocals
            state['Ta'][:] = fields[0]
            state['Tb'][:] = fields[1]
        step(0)
        pytest.fail('invalid water was accepted')

    monkeypatch.setattr(stages, 'run_outer_coupling', drive)
    with pytest.raises(fluid_props.WaterStateError, match='3D temperature .* B: water index='):
        stages._run_outer_coupling_3d(prob, hv)


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('converged', [False, True])
@pytest.mark.parametrize('invalid', [False, True])
def test_final_co2_guard_uses_report_pressure_after_either_exit(monkeypatch, side, converged, invalid):
    prob, hv = _problem(monkeypatch, ('sco2', 'sco2'))
    original_outer = stages.run_outer_coupling
    checked = []
    validate = stages.sco2_props._validate_state
    expected = None

    def check(t, p, *, where=None):
        if where and where.startswith('3D final report state'):
            checked.append(where)
            if where.endswith(side):
                np.testing.assert_array_equal(p, expected)
        return validate(t, p, where=where)

    def drive(**kwargs):
        nonlocal expected
        solver = prob.sA if side == 'A' else prob.sB
        solver.P_ref_abs = 11e6  # deliberately different from kernel's inlet anchor
        solver.P[:] = 0.
        def inject():
            if invalid:
                solver.P[1, 2, 1] = -4e6  # interior report P=7 MPa; outlet stays valid
        def step(_):
            if converged:
                inject()
            return converged, None
        def post(*_):
            inject()
        terminal = original_outer(max_iter=1, step=step, post=post)
        # _pipeline_cfg uses real +y for A and -y for B.
        expected = (11e6 + solver.P).copy()
        if side == 'B':
            expected = expected[:, ::-1, :].copy()
        def forbidden(*a, **k):
            pytest.fail('final range check must not query EOS')
        monkeypatch.setattr(stages.sco2_props, '_PropsSI', forbidden)
        return terminal

    monkeypatch.setattr(stages.sco2_props, '_validate_state', check)
    monkeypatch.setattr(stages, 'run_outer_coupling', drive)
    if invalid:
        with pytest.raises(ValueError) as error:
            stages._run_outer_coupling_3d(prob, hv)
        index = '(1, 2, 1)' if side == 'A' else '(1, 1, 1)'
        assert f'3D final report state {side}, index={index}' in str(error.value)
        assert 'P=7000000.0 Pa' in str(error.value)
    else:
        result = stages._run_outer_coupling_3d(prob, hv)
        np.testing.assert_array_equal(result.Ta, np.full_like(result.Ta, 350.))
        np.testing.assert_array_equal(result.Tb, np.full_like(result.Tb, 300.))
    assert checked.count(f'3D final report state {side}') == 1
