"""Refined duty must use physical ports and a converged energy solve."""
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
from sjtu_tpmshx.domain.compute_config import PartialBCConfig
from sjtu_tpmshx.pipelines import solve_2d
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.tests.test_port_grid_alignment_2d import _case, _expected_profile


def _arguments(monkeypatch, directions=(1, 3), full=False):
    cfg = _case(directions)
    if full:
        cfg.bc_A = PartialBCConfig(dir=directions[0])
        cfg.bc_B = PartialBCConfig(dir=directions[1])
        cfg.validate()
    pipe = Pipeline2D(cfg)
    fields = pipe.build_fields()
    captured = []

    class BeforeIteration(Exception):
        pass

    def capture(s, **kwargs):
        captured.append(s)
        raise BeforeIteration

    with monkeypatch.context() as patch:
        patch.setattr(SIMPLESolver, 'solve', capture)
        for side in ('A', 'B'):
            with pytest.raises(BeforeIteration):
                fields['_run_simple'](pipe._parsed[f'cfg{side}'], 1., 1e-5,
                                      400., 1., side, fluid_type='incompressible')
    dx, dy = fields['energy_dx'], fields['energy_dy']
    shape = len(dx), len(dy)
    props = dict(name='air', rho=lambda *a: 1., cp=lambda *a: 1.)
    args = dict(
        Ta=np.full(shape, 400.), Tb=np.full(shape, 300.), Ts=np.full(shape, 350.),
        ucA=np.ones(shape), vcA=np.ones(shape), ucB=np.ones(shape), vcB=np.ones(shape),
        rho_cp_A=1., rho_cp_B=1., simpA=captured[0], simpB=captured[1],
        N_x=shape[0], N_y=shape[1], L=.182, H=.042,
        dir_A=directions[0], dir_B=directions[1], energy_dx=dx, energy_dy=dy,
        _x_breaks=fields['_x_breaks'], _y_breaks=fields['_y_breaks'],
        T_inA=400., T_inB=300., P_inA_val=101325., P_inB_val=101325., eps=.7,
        za=None, window=SimpleNamespace(_h_vA=1., _h_vB=1., _K_ffA=1.,
                                       _K_ffB=1., _K_ss=1.),
        _pA=props, _pB=props, cfgA=pipe._parsed['cfgA'], cfgB=pipe._parsed['cfgB'],
        u_A=1., u_B=1., warnings_list=[])
    return cfg, args


def _finite_refined(args, kwargs, converged):
    shape = args[2], args[3]
    fields = tuple(np.full(shape, t) for t in (390., 310., 350.))
    info = dict(converged=converged, iterations=5000, residual=2.)
    return (*fields, info) if kwargs.get('return_info') else fields


@pytest.mark.parametrize('directions', [(1, 3), (3, 1)])
@pytest.mark.parametrize('full', [False, True])
def test_refined_profiles_use_physical_coordinates(monkeypatch, directions, full):
    _, arguments = _arguments(monkeypatch, directions, full)
    observed = {}
    balances = []

    def refined(*args, **kwargs):
        observed.update(kwargs)
        return _finite_refined(args, kwargs, True)

    def balance(*args, **kwargs):
        balances.append((args, kwargs))
        return 10.

    monkeypatch.setattr(solve_2d, 'solve_full_domain', refined)
    monkeypatch.setattr(solve_2d, '_enthalpy_balance_2d', balance)
    solve_2d._compute_Q_richardson(**arguments)
    assert observed.get('return_info') is True
    for side, direction, (_, duty_kwargs) in zip(('A', 'B'), directions, balances[-2:]):
        widths = observed['dy_arr' if direction in (0, 1) else 'dx_arr']
        bc = arguments[f'cfg{side}']
        lo, hi = bc['in_ctr'] - bc['in_w'] / 2, bc['in_ctr'] + bc['in_w'] / 2
        out_lo = bc['out_ctr'] - bc['out_w'] / 2
        out_hi = bc['out_ctr'] + bc['out_w'] / 2
        expected_in = _expected_profile(widths, lo, hi)
        expected_out = _expected_profile(widths, out_lo, out_hi)
        if full:
            np.testing.assert_allclose(expected_in, 1., atol=1e-13)
        else:
            assert not np.array_equal(widths, widths[::-1])
        np.testing.assert_allclose(observed[f'inlet_mask_{side}'], expected_in, atol=1e-13)
        np.testing.assert_array_equal(duty_kwargs['inlet_mask'], observed[f'inlet_mask_{side}'])
        np.testing.assert_allclose(duty_kwargs['outlet_mask'], expected_out, atol=1e-13)


@pytest.mark.parametrize('converged', [False, True])
def test_finite_refined_verdict_controls_extrapolation(monkeypatch, converged):
    _, arguments = _arguments(monkeypatch)
    monkeypatch.setattr(solve_2d, 'solve_full_domain',
                        lambda *a, **k: _finite_refined(a, k, converged))
    duties = iter([10., -8., 20., -12.])
    monkeypatch.setattr(solve_2d, '_enthalpy_balance_2d', lambda *a, **k: next(duties))
    result = solve_2d._compute_Q_richardson(**arguments)
    assert result[0] == pytest.approx(70. / 3 if converged else 10.)
    assert result[1:3] == (10., -8.)
    assert result[5]['converged'] is converged
    assert result[5]['extrapolated'] is converged
    assert result[5]['iterations'] == 5000
    if not converged:
        assert any('未外推' in text for text in arguments['warnings_list'])


@pytest.mark.parametrize('directions', [(0, 1), (2, 3)])
def test_refined_initial_fields_preserve_physical_coordinates_and_frozen_inlets(monkeypatch, directions):
    _, arguments = _arguments(monkeypatch, directions)
    x = np.cumsum(arguments['energy_dx']) - arguments['energy_dx'] / 2
    y = np.cumsum(arguments['energy_dy']) - arguments['energy_dy'] / 2
    seeds = {}
    for name, base in (('Ta', 360.), ('Tb', 320.), ('Ts', 340.)):
        arguments[name] = base + 70. * x[:, None] + 90. * y[None, :]
        seeds[name] = arguments[name].copy()
    observed = {}

    def refined(*args, **kwargs):
        observed.update(kwargs)
        return _finite_refined(args, kwargs, True)

    monkeypatch.setattr(solve_2d, 'solve_full_domain', refined)
    solve_2d._compute_Q_richardson(**arguments)
    xf = np.cumsum(observed['dx_arr']) - observed['dx_arr'] / 2
    yf = np.cumsum(observed['dy_arr']) - observed['dy_arr'] / 2
    for name, base in (('Ta', 360.), ('Tb', 320.), ('Ts', 340.)):
        expected = base + 70. * xf[:, None] + 90. * yf[None, :]
        if name != 'Ts':
            side = 'A' if name == 'Ta' else 'B'
            direction = arguments[f'dir_{side}']
            assert np.any(observed[f'inlet_mask_{side}'] <= .01)
            if direction == 0:
                expected[0, :] = arguments[f'T_in{side}']
            elif direction == 1:
                expected[-1, :] = arguments[f'T_in{side}']
            elif direction == 2:
                expected[:, 0] = arguments[f'T_in{side}']
            else:
                expected[:, -1] = arguments[f'T_in{side}']
        np.testing.assert_allclose(observed[f'{name}_init'], expected, rtol=0, atol=1e-12)
        np.testing.assert_array_equal(arguments[name], seeds[name])


def test_one_invalid_refined_duty_falls_back_both_sides(monkeypatch):
    _, arguments = _arguments(monkeypatch)
    monkeypatch.setattr(solve_2d, 'solve_full_domain',
                        lambda *a, **k: _finite_refined(a, k, True))
    duties = iter([10., -8., float('nan'), -12.])
    monkeypatch.setattr(solve_2d, '_enthalpy_balance_2d', lambda *a, **k: next(duties))
    result = solve_2d._compute_Q_richardson(**arguments)
    assert result[0] == 10.
    assert result[1:3] == (10., -8.)
    assert result[3] == pytest.approx(50. * .182 * .042)
    assert result[5]['extrapolated'] is False
    assert any('主网格值' in text and '未外推' in text for text in arguments['warnings_list'])


def test_failed_refinement_preserves_main_fields_and_rejects_overall(monkeypatch):
    from sjtu_tpmshx.tests.test_cooperative_cancel import _cfg

    original = solve_2d._compute_Q_richardson
    main = {}

    def richardson(*args, **kwargs):
        before = [a.copy() for a in args[:3]]
        with monkeypatch.context() as patch:
            patch.setattr(solve_2d, 'solve_full_domain',
                          lambda *a, **k: _finite_refined(a, k, False))
            result = original(*args, **kwargs)
        for old, actual in zip(before, args[:3]):
            np.testing.assert_array_equal(actual, old)
        main['Q'] = max(abs(result[1]), abs(result[2]))
        return result

    monkeypatch.setattr(solve_2d, '_compute_Q_richardson', richardson)
    result = Pipeline2D(_cfg()).run()
    detail = result.diagnostics['convergence_detail']
    for gate in ('outer_converged', 'simple_ok', 'ltne_ok', 'envelope_ok'):
        assert detail[gate] is True
    assert detail['energy_nan_hit'] is False
    assert detail['richardson_ok'] is False
    assert result.converged is False
    assert result.Q_W == main['Q']
    assert result.diagnostics['richardson_info']['extrapolated'] is False
    assert any('未外推' in text for text in result.warnings)
    for key in ('Ta', 'Tb', 'Ts'):
        assert np.all(np.isfinite(result.fields[key]))
