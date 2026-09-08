"""Vectorised T(h,P) inverse for the Option B enthalpy-form 3D LTNE rewrite.

The conservative enthalpy kernel keeps h as the primary fluid unknown; the
pipeline (stages_3d) must invert T = T(h,P) each outer iteration to feed the
diffusion/inter-phase coupling. sco2_temperature_field is the field counterpart
of the scalar sco2_temperature (the per-cell array form the kernel refresh needs).
"""
import numpy as np
import pytest

from sjtu_tpmshx.solvers import sco2_props

pytestmark = pytest.mark.skipif(
    not sco2_props._HAVE_COOLPROP, reason="CoolProp required for sCO2 tests")

_P = 8.0e6


def test_temperature_field_round_trips_enthalpy_field():
    """T(h(T)) == T over a field spanning the pseudocritical line."""
    T = np.array([[290.0, 307.0], [312.0, 360.0]])
    h = sco2_props.sco2_enthalpy_field(T, _P)
    T_back = sco2_props.sco2_temperature_field(h, _P)
    assert T_back.shape == T.shape
    assert np.allclose(T_back, T, atol=1e-3)


def test_temperature_field_matches_scalar():
    """Field query agrees with the scalar sco2_temperature element-wise."""
    h = np.array([sco2_props.sco2_enthalpy(300.0, _P),
                  sco2_props.sco2_enthalpy(330.0, _P)])
    Tf = sco2_props.sco2_temperature_field(h, _P)
    assert Tf[0] == pytest.approx(sco2_props.sco2_temperature(float(h[0]), _P), rel=1e-9)
    assert Tf[1] == pytest.approx(sco2_props.sco2_temperature(float(h[1]), _P), rel=1e-9)


@pytest.mark.parametrize('temperature,pressure', [(279., 12e6), (701., 12e6),
                                                 (330., 7.9e6), (330., 16.1e6)])
def test_true_h_rejects_normal_eos_outside_model(temperature, pressure):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    # A normal EOS value is not proof that the production model supports it.
    h = ent._h_scalar(temperature, pressure, 'sco2')
    with pytest.raises(ValueError, match='enthalpy EOS return B.*index='):
        ent._T_of_h_field(np.array([h]), pressure, 'sco2',
                          where='enthalpy EOS return B')


@pytest.mark.parametrize('temperature,pressure', [(np.nan, 12e6), (330., np.inf),
                                                 (701., 12e6), (330., 7.9e6)])
def test_true_h_property_field_checks_paired_states_before_eos(monkeypatch, temperature, pressure):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    def unexpected_eos(*args):
        pytest.fail('invalid actual state reached EOS')
    monkeypatch.setattr(ent, '_PropsSI', unexpected_eos)
    with pytest.raises(ValueError, match=r'index=\(1,\).*T=.* K, P=.* Pa'):
        ent._prop_field('H', np.array([320., temperature]),
                        np.array([8e6, pressure]), 'sco2')


def _guard_pipeline(**kwargs):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    cell = np.ones((1, 1, 1))
    values = dict(Nx=1, Ny=1, Nz=1, dx=[.01], dy=[.01], dz=[.01],
                  eps_arr=cell*.7, K_ss=cell*5., h_vA_field=cell*100.,
                  h_vB_field=cell*100., m_dot_A=.01, m_dot_B=.01,
                  T_inA=330., T_inB=320., P_A=12e6, P_B=12e6,
                  dir_A=0, dir_B=1, n_outer=1)
    values.update(kwargs)
    return ent.solve_ltne_enthalpy_3d_pipeline(**values)


@pytest.mark.parametrize('side', ['A', 'B'])
def test_true_h_inlet_rejects_before_eos(monkeypatch, side):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    def unexpected_eos(*args):
        pytest.fail('invalid inlet reached EOS')
    monkeypatch.setattr(ent, '_PropsSI', unexpected_eos)
    with pytest.raises(ValueError, match='inlet ' + side):
        _guard_pipeline(**{'T_in' + side: 701.})


@pytest.mark.parametrize('warm_start', [False, True])
@pytest.mark.parametrize('side', ['A', 'B'])
def test_true_h_initial_state_checks_local_pressure(side, warm_start):
    fields = {'pressure_' + side + '_field': np.full((1, 1, 1), 7.9e6)}
    if warm_start:
        fields['T' + side.lower() + '_init'] = np.full((1, 1, 1), 330.)
    with pytest.raises(ValueError, match='warm start ' + side + r'.*P=7900000.0 Pa'):
        _guard_pipeline(**fields)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('iterations', [1, 2])
def test_true_h_refresh_and_final_return_reject(monkeypatch, dimension, side, iterations):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    from sjtu_tpmshx.solvers.ltne_enthalpy_2d import solve_enthalpy_2d
    h_bad = ent._h_scalar(701., 12e6, 'sco2')
    def invalid_after_sweep(hA, hB, *args):
        (hA if side == 'A' else hB)[:] = h_bad
    monkeypatch.setattr(ent, '_gs_enthalpy_sweeps_3d', invalid_after_sweep)
    stage = 'final' if iterations == 1 else 'iteration'
    with pytest.raises(ValueError, match=f'enthalpy {stage} EOS return {side}'):
        if dimension == 3:
            _guard_pipeline(n_outer=iterations)
        else:
            flux = (np.full((2, 1), .01), np.zeros((1, 2)))
            solve_enthalpy_2d(330., 320., 12e6, 12e6, flux, flux,
                100., 100., 5., .35, .35, [.01], [.01],
                P_inA=12e6, P_inB=12e6, max_iter=iterations)


@pytest.mark.parametrize('temperature', [280., 700.])
def test_true_h_boundary_allows_mathematical_bracket_outside_model(monkeypatch, temperature):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    original = ent._PropsSI
    bracket_queries = []

    def eos(key, input_key, value, *args):
        if key == 'T':
            return np.full(np.shape(value), temperature)
        if key == 'H' and input_key == 'T':
            bracket_queries.append(float(value))
        return original(key, input_key, value, *args)

    monkeypatch.setattr(ent, '_PropsSI', eos)
    Ta, Tb, _, _ = _guard_pipeline(T_inA=temperature, T_inB=temperature)
    assert max(temperature - 60., 230.) in bracket_queries
    assert temperature + 60. in bracket_queries
    np.testing.assert_array_equal(Ta, temperature)
    np.testing.assert_array_equal(Tb, temperature)


@pytest.mark.parametrize('temperature', [280., 700.])
def test_true_h_real_boundary_roundtrip_obeys_strict_return_domain(temperature):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    h = np.array([ent._h_scalar(temperature, 12e6, 'sco2')])
    raw = np.asarray(ent._PropsSI('T', 'H', h, 'P', np.array([12e6]), 'CO2')).reshape(1)
    # Exact-boundary inputs can round-trip outside the domain on some platforms.
    if raw[0] < 280. or raw[0] > 700.:
        with pytest.raises(ValueError, match='temperature must be within 280..700 K'):
            ent._T_of_h_field(h, 12e6, 'sco2')
    else:
        np.testing.assert_array_equal(ent._T_of_h_field(h, 12e6, 'sco2'), raw)


@pytest.mark.parametrize('boundary,direction', [(280., -np.inf), (700., np.inf)])
def test_true_h_one_ulp_outside_boundary_is_rejected(monkeypatch, boundary, direction):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    raw = np.array([np.nextafter(boundary, direction)])
    monkeypatch.setattr(ent, '_PropsSI', lambda *args: raw)
    with pytest.raises(ValueError, match='temperature must be within 280..700 K'):
        ent._T_of_h_field(np.ones(1), 12e6, 'sco2')
    assert raw[0] == np.nextafter(boundary, direction)


@pytest.mark.parametrize('returned', [np.nan, np.inf])
def test_true_h_nonfinite_eos_return_is_rejected(monkeypatch, returned):
    from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
    monkeypatch.setattr(ent, '_PropsSI', lambda *args: [330., returned])
    with pytest.raises(ValueError, match=r'must be finite.*index=\(1,\)'):
        ent._T_of_h_field(np.ones(2), np.array([8e6, 16e6]), 'sco2')
