"""Real closure warnings: ownership, deduplication and numerical transparency."""
import threading
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.domain.run_warnings import current_warnings, warning_scope
from sjtu_tpmshx.solvers import fluid_props, nu_correlations as nu, tpms_props
from sjtu_tpmshx.tests.test_compute_pipeline import _RecordingPipeline
from sjtu_tpmshx.domain.compute_config import ComputeConfig


@pytest.fixture
def standalone_registries(monkeypatch):
    """Isolate the public once-per-session state without changing its behavior."""
    registries = []
    for module, names in (
        (nu, ('_EXTRAP_WARNED', '_WATER_NU_WARNED', '_SCO2_NU_WARNED')),
        (tpms_props, ('_range_warnings_emitted', '_WATER_TWO_PHASE_WARNED')),
    ):
        for name in names:
            registry = set()
            monkeypatch.setattr(module, name, registry)
            registries.append(registry)
    return registries


@pytest.mark.parametrize('fluid', ['air', 'water', 'sco2'])
def test_real_nu_standalone_then_repeated_runs(fluid, standalone_registries):
    model = fluid_props.get(fluid)

    def evaluate(re):
        return model.nu('Gyroid', re, 0.35, 7.0, 2.0, 3.0)

    re = np.array([1.0, 1e6])
    with pytest.warns(UserWarning):
        expected = evaluate(re)
    standalone_before = [s.copy() for s in standalone_registries]
    previous = None
    for _ in range(2):
        with warnings.catch_warnings(record=True) as emitted:
            warnings.simplefilter('always')
            with warning_scope({}) as records:
                np.testing.assert_array_equal(evaluate(re), expected)
                evaluate(re + 1)
        assert not emitted
        assert list(records) == [('nu', fluid, 'Gyroid', 'lo'),
                                 ('nu', fluid, 'Gyroid', 'hi')]
        assert all(extrap for _, extrap in records.values())
        if previous is not None:
            assert records == previous
        previous = records
        assert standalone_registries == standalone_before
        assert current_warnings() is None


def test_later_opposite_nu_and_property_bounds(standalone_registries):
    with warning_scope({}) as records:
        nu.nu_from_Re('Diamond', 100, 0.35, 7, 2)
        nu.nu_from_Re('Diamond', 101, 0.35, 7, 2)
        nu.nu_from_Re('Diamond', 20000, 0.35, 7, 2)
        tpms_props.air_cp(200)
        tpms_props.air_cp(201)
        tpms_props.air_cp(1100)
        tpms_props.water_density(380)
        tpms_props.water_density(381)
    assert len(records) == 6
    assert records[('property', 'air_cp', 'lo')][0].startswith('air_cp: T=[200.0')
    assert records[('property', 'air_cp', 'hi')][1]
    assert not records[('water_phase',)][1]
    assert all(not s for s in standalone_registries)
    # A run must not consume the next standalone call's first warning.
    with pytest.warns(UserWarning, match='Nu extrap'):
        nu.nu_from_Re('Diamond', 100, 0.35, 7, 2)


@pytest.mark.parametrize('name,temperature', [
    ('air_viscosity', 1200), ('air_conductivity', 1200), ('air_cp', 1100),
    ('water_density', 370), ('water_viscosity', 370),
    ('water_conductivity', 370), ('water_cp', 370),
])
def test_property_values_and_standalone_warning_location(name, temperature,
                                                        standalone_registries):
    function = getattr(tpms_props, name)
    with pytest.warns(UserWarning) as emitted:
        expected = function(temperature)
    assert emitted[0].filename == __file__  # preserve public stacklevel
    with warning_scope({}) as records:
        actual = function(temperature)
        function(temperature + 0.1)
    np.testing.assert_array_equal(actual, expected)
    assert list(records) == [('property', name, 'hi')]


def test_compute_uses_underlying_nu_notice_once(standalone_registries):
    from sjtu_tpmshx.solvers.tpms_calc import compute

    with warning_scope({}) as records:
        result = compute('Gyroid', 7, 0.6, 0.001, 300, 101325, 16,
                         fluid_type='water')
    assert result['Nu'] > 0
    assert list(records) == [('nu', 'water', 'Gyroid', 'lo')]


def test_compute_cache_hit_replays_warnings_without_recomputation(standalone_registries):
    from sjtu_tpmshx.solvers import tpms_calc
    compute = tpms_calc.compute

    args = ('Diamond', 6.9, 0.59, 0.00123, 370.12, 101325, 16)
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter('always')
        expected = compute(*args, fluid_type='water')
    notices = [w for w in emitted if 'outside the validated range' in str(w.message)]
    # Cold standalone warning still points at the public wrapper, not domain.
    if notices:  # an earlier invocation may already have warmed this cache
        assert notices[0].filename == tpms_calc.__file__
    misses = compute.cache_info().misses
    for _ in range(2):
        with warning_scope({}) as records:
            assert compute(*args, fluid_type='water') == expected
        assert ('nu', 'water', 'Diamond', 'lo') in records
        assert ('property', 'water_viscosity', 'hi') in records
        assert compute.cache_info().misses == misses


def test_failed_cache_miss_restores_recording_context(monkeypatch):
    from sjtu_tpmshx.domain import run_warnings
    from sjtu_tpmshx.solvers import tpms_calc

    def fail(*args, **kwargs):
        raise ValueError('DF failure after properties and Nu')

    with monkeypatch.context() as patch:
        patch.setattr(tpms_calc, 'predict_K_cF', fail)
        with warning_scope({}), pytest.raises(ValueError, match='DF failure'):
            tpms_calc.compute('Diamond', 6.91, 0.59, 0.00123, 370.12,
                              101325, 16, 'water')
    assert current_warnings() is None
    assert run_warnings._cache_records.get() is None
    with warning_scope({}) as records:
        tpms_calc.compute('Diamond', 6.91, 0.59, 0.00123, 370.12,
                          101325, 16, 'water')
    assert ('nu', 'water', 'Diamond', 'lo') in records


def test_choke_is_general_warning_and_keeps_return_contract(monkeypatch):
    from sjtu_tpmshx.df_surrogate import predict

    monkeypatch.setattr(predict, '_CHOKE_WARNED', set())
    args = ('Gyroid', 7, 0.6, 0.35, 1e5, 400, 101325, 2e-5, 0.1)
    with warning_scope({}) as records:
        assert predict.predict_dP_compressible(*args) == 101325
        assert np.isnan(predict.predict_dP_compressible(*args, strict=True))
    assert len(records) == 1
    assert not next(iter(records.values()))[1]
    assert not predict._CHOKE_WARNED
    with pytest.warns(UserWarning, match='D-F choke'):
        predict.predict_dP_compressible(*args)


@pytest.mark.parametrize('error', [ValueError, InterruptedError])
def test_pipeline_exception_restores_scope_and_next_run(monkeypatch, error):
    pipe = _RecordingPipeline(ComputeConfig())
    original = pipe.build_fields

    def fail():
        nu.nu_water_topo('Gyroid', 1, 3)
        raise error('failure after real warning')

    monkeypatch.setattr(pipe, 'build_fields', fail)
    with pytest.raises(error):
        pipe.run()
    assert current_warnings() is None

    def build():
        nu.nu_water_topo('Gyroid', 1, 3)
        return original()

    monkeypatch.setattr(pipe, 'build_fields', build)
    result = pipe.run()
    assert len(result.warnings) == len(result.extrap_reasons) == 1


def test_parallel_worker_scopes_merge_in_side_order():
    from sjtu_tpmshx.pipelines.run_stack_3d_stages import _run_two_simple_parallel

    b_done = threading.Event()

    class Side:
        def __init__(self, fluid):
            self.fluid = fluid

        def solve(self, **kwargs):
            if self.fluid == 'air':
                assert b_done.wait(10)
            model = fluid_props.get(self.fluid)
            model.nu('Gyroid', 1, 0.35, 7, 2, 3)
            b_done.set()
            return True, 1

    with warning_scope({}) as records:
        _run_two_simple_parallel(Side('air'), Side('water'))
    assert [key[1] for key in records] == ['air', 'water']


def test_concurrent_pipeline_runs_do_not_share_records(monkeypatch):
    barrier = threading.Barrier(2, timeout=10)
    results, errors = {}, []

    def run(fluid):
        pipe = _RecordingPipeline(ComputeConfig())
        original = pipe.build_fields

        def build():
            barrier.wait()
            fluid_props.get(fluid).nu('Gyroid', 1, 0.35, 7, 2, 3)
            return original()

        monkeypatch.setattr(pipe, 'build_fields', build)
        try:
            results[fluid] = pipe.run()
            assert current_warnings() is None
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(fluid,)) for fluid in ('water', 'sco2')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    for fluid, result in results.items():
        assert len(result.warnings) == 1
        assert result.warnings[0].startswith('[water' if fluid == 'water' else '[sCO2')
