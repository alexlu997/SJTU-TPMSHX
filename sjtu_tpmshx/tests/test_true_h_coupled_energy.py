"""The 2D EOS balance gate must supplement, not replace, the h/Q stop."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
from sjtu_tpmshx.solvers.ltne_enthalpy_2d import solve_enthalpy_2d


def run_driver(**kwargs):
    cell = np.ones((2, 1, 1))
    options = dict(fluid_A='air', fluid_B='air', n_outer=2, n_sweep=3, tol=.001)
    options.update(kwargs)
    return ent.solve_ltne_enthalpy_3d_pipeline(
        2, 1, 1, [1., 1.], [1.], [1.], cell * .7, cell * 0.,
        cell, cell, 0., 0., 350., 300., 2e5, 2e5, 0, 1, **options)


@pytest.mark.parametrize('limit, gate, expected_iterations, expected_ok', [
    (2, None, 1, True), (1, .001, 1, False), (2, .001, 2, True),
])
def test_driver_continues_for_uncancelled_solid_residual(
        monkeypatch, limit, gate, expected_iterations, expected_ok):
    calls, final_states, checked_states, finite_states = [], [], [], []
    original_eos = ent._T_of_h_field
    original_balance = ent._coupled_energy_balance
    original_finite = ent.check_finite_temperatures

    def finite(Ta, Tb, Ts, **kw):
        if kw['where'] == 'enthalpy final return':
            finite_states.append((Ta, Tb))
        return original_finite(Ta, Tb, Ts, **kw)

    def balance(Ta, Tb, *args):
        checked_states.append((Ta, Tb))
        return original_balance(Ta, Tb, *args)

    def eos(h, p, fluid, **kw):
        value = original_eos(h, p, fluid, **kw)
        if 'final' in kw.get('where', ''):
            final_states.append(value)
        return value

    def sweep(hA, hB, Ts, *args):
        calls.append(1)
        Ts[:] = .5 * (args[4] + args[5])  # Actual iteration EOS temperatures.
        if len(calls) == 1:
            Ts[:, 0, 0] += [-1., 1.]  # sum(Rs)=0, sum(abs(Rs))=4.

    monkeypatch.setattr(ent, '_T_of_h_field', eos)
    monkeypatch.setattr(ent, '_coupled_energy_balance', balance)
    monkeypatch.setattr(ent, 'check_finite_temperatures', finite)
    monkeypatch.setattr(ent, '_gs_enthalpy_sweeps_3d', sweep)
    Ta, Tb, _, info = run_driver(n_outer=limit, coupled_energy_tol=gate)
    assert info['iterations'] == expected_iterations
    assert info['converged'] is expected_ok
    assert info['residual'] == 0 and info['energy_imbalance_rel'] == 0
    assert Ta is final_states[-2] and Tb is final_states[-1]
    assert len(finite_states) == len(final_states) // 2
    assert all(a is final_states[2*i] and b is final_states[2*i+1]
               for i, (a, b) in enumerate(finite_states))
    if gate is None:
        assert 'coupled_energy_balance' not in info
    else:
        assert Ta is checked_states[-1][0] and Tb is checked_states[-1][1]
        assert info['coupled_energy_balance']['ratio'] == pytest.approx(
            0. if expected_ok else 4.)


@pytest.mark.parametrize('old_gate', ['h', 'Q'])
def test_new_gate_cannot_replace_old_conditions(monkeypatch, old_gate):
    def sweep(hA, hB, Ts, *args):
        if old_gate == 'h':
            hA[:] += 1000.
        Ts[:] = .5 * (ent._T_of_h_field(hA, 2e5, 'air')
                       + ent._T_of_h_field(hB, 2e5, 'air'))

    monkeypatch.setattr(ent, '_gs_enthalpy_sweeps_3d', sweep)
    if old_gate == 'Q':
        duties = iter([1e-4, 0.])
        monkeypatch.setattr(ent, '_boundary_enthalpy_duty', lambda *a: next(duties))
    *_, info = run_driver(n_outer=1, coupled_energy_tol=.001)
    assert info['coupled_energy_balance']['ratio'] <= .001
    assert not info['converged']


@pytest.mark.parametrize('bad_state', ['hB', 'Ts', 'qB'])
def test_driver_rejects_nan_before_max_can_hide_it(monkeypatch, bad_state):
    def sweep(hA, hB, Ts, *args):
        if bad_state != 'qB':
            (hB if bad_state == 'hB' else Ts)[-1] = np.nan

    monkeypatch.setattr(ent, '_gs_enthalpy_sweeps_3d', sweep)
    if bad_state == 'qB':
        duties = iter([0., np.nan])
        monkeypatch.setattr(ent, '_boundary_enthalpy_duty', lambda *a: next(duties))
    with pytest.raises(FloatingPointError, match='Non-finite coupled energy'):
        run_driver(n_outer=1, coupled_energy_tol=.001)


def test_residual_uses_nonuniform_face_conduction_and_absolute_sum():
    # Two cells: harmonic(2,6)=3; distance=1.5; area=3; flux=12.
    Ts = np.array([0., 2.]).reshape(2, 1, 1)
    Kss = np.array([2., 6.]).reshape(2, 1, 1)
    balance = ent._coupled_energy_balance(
        Ts, Ts, Ts, np.ones_like(Ts), np.ones_like(Ts), Kss,
        np.array([1., 2.]), np.array([3.]), np.ones(1), 100., -100.)
    assert balance == dict(net=0., solid_abs_sum=24., denominator=100., ratio=.24)
    for bad in [np.nan, np.inf]:
        with pytest.raises(FloatingPointError):
            ent._coupled_energy_balance(
                Ts, Ts, Ts, np.ones_like(Ts), np.ones_like(Ts), Kss,
                np.array([1., 2.]), np.array([3.]), np.ones(1), 100., bad)


@pytest.mark.parametrize('pair', [('sco2', 'sco2'), ('sco2', 'air'),
                                  ('sco2', 'water'), ('air', 'sco2'),
                                  ('water', 'sco2')])
def test_2d_adapter_explicitly_enables_gate_for_true_h_pairs(monkeypatch, pair):
    seen = []
    real_driver = ent.solve_ltne_enthalpy_3d_pipeline

    def driver(*args, **kw):
        seen.append(kw)
        return real_driver(*args, **kw)

    def sweep(hA, hB, Ts, *args):
        Ts[:] = .5 * (args[4] + args[5])

    monkeypatch.setattr(ent, 'solve_ltne_enthalpy_3d_pipeline', driver)
    monkeypatch.setattr(ent, '_gs_enthalpy_sweeps_3d', sweep)
    flux = (np.zeros((3, 1)), np.zeros((2, 2)))
    *_, info = solve_enthalpy_2d(
        350., 300., 12e6, 12e6, flux, flux, 1., 1., 0., .35, .35,
        [1., 1.], [1.], P_inA=12e6, P_inB=12e6,
        fluid_A=pair[0], fluid_B=pair[1], max_iter=1, tol=.1)
    assert seen[0]['coupled_energy_tol'] == .001
    assert (seen[0]['n_outer'], seen[0]['n_sweep'], seen[0]['tol']) == (1, 3, .001)
    assert info['converged']


@pytest.mark.parametrize('field', ['Ta_init', 'Tb_init', 'Ts_init'])
def test_nonfinite_warm_state_precedes_warm_enthalpy(monkeypatch, field):
    def forbidden(*args):
        pytest.fail('invalid warm state reached field enthalpy conversion')
    monkeypatch.setattr(ent, '_prop_field', forbidden)
    with pytest.raises(ValueError, match='enthalpy warm start: .*non-finite'):
        run_driver(**{field: np.full((2, 1, 1), np.inf)})


@pytest.mark.parametrize('gate, old_h_failure', [(None, False), (.001, False), (.001, True)])
def test_nonfinite_final_eos_precedes_balance_or_return(monkeypatch, gate, old_h_failure):
    original_eos = ent._T_of_h_field
    final_order = []

    def eos(*args, **kw):
        value = original_eos(*args, **kw)
        where = kw.get('where', '')
        if 'final' in where:
            final_order.append(where[-1])
            if where.endswith('B'):
                value[-1] = np.inf
        return value

    def sweep(hA, *args):
        if old_h_failure:
            hA[:] += 1000.

    def forbidden(*args):
        pytest.fail('invalid final EOS reached coupled budget')

    monkeypatch.setattr(ent, '_T_of_h_field', eos)
    monkeypatch.setattr(ent, '_gs_enthalpy_sweeps_3d', sweep)
    monkeypatch.setattr(ent, '_coupled_energy_balance', forbidden)
    with pytest.raises(ValueError, match='enthalpy final return: B temperature'):
        run_driver(n_outer=1, coupled_energy_tol=gate)
    assert final_order == ['A', 'B']


def test_standalone_rejects_nonfinite_solid_before_dict(monkeypatch):
    def sweep(hA, hB, Ts, *args):
        Ts[-1] = np.inf
    monkeypatch.setattr(ent, '_gs_enthalpy_sweeps_3d', sweep)
    with pytest.raises(ValueError, match='enthalpy final return: solid temperature'):
        ent.solve_ltne_enthalpy_3d(
            2, 1, 1, 2., 1., 1., .7, 0., 0., 0., 1., 1.,
            350., 300., 2e5, fluid_A='air', fluid_B='air', n_outer=1)
