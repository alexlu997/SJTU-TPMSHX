"""Real closure warnings: ownership, deduplication and numerical transparency."""
import threading
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.domain.run_warnings import (
    current_warnings, warning_scope, range_context, warning_messages, merge_warnings,
)
from sjtu_tpmshx.solvers import fluid_props, nu_correlations as nu, tpms_props
from sjtu_tpmshx.tests.test_compute_pipeline import _RecordingPipeline
from sjtu_tpmshx.domain.compute_config import ComputeConfig


@pytest.fixture
def standalone_registries(monkeypatch):
    """Isolate the public once-per-session state without changing its behavior."""
    registries = []
    for module, names in (
        (nu, ('_EXTRAP_WARNED', '_WATER_NU_WARNED', '_SCO2_NU_WARNED')),
        (tpms_props, ('_range_warnings_emitted',)),
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
        assert list(records) == [('nu', fluid, 'Gyroid', (2,),
                                 ('unbound', 'unbound', 'source'))]
        record = next(iter(records.values()))
        assert record.minimum == (1.0, (0,))
        assert record.maximum == (1e6 + 1, (1,))
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
    assert len(records) == 3
    cp = records[('property', 'air_cp', (), ('unbound', 'unbound', 'source'))]
    assert cp.minimum == (200.0, ())
    assert cp.maximum == (1100.0, ())
    assert (cp.low, cp.high, cp.size) == (1, 0, 1)  # first equal-fraction snapshot
    assert any('water_density:' in message for message in warning_messages(records))
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
    assert list(records) == [('property', name, (), ('unbound', 'unbound', 'source'))]


def test_compute_uses_underlying_nu_notice_once(standalone_registries):
    from sjtu_tpmshx.solvers.tpms_calc import compute

    with warning_scope({}) as records:
        result = compute('Gyroid', 7, 0.6, 0.001, 300, 101325, 16,
                         fluid_type='water')
    assert result['Nu'] > 0
    assert len(list(warning_messages(records))) == 1
    assert ('nu', 'water', 'Gyroid', (), ('unbound', 'unbound', 'source')) in records


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
        assert ('nu', 'water', 'Diamond', (), ('unbound', 'unbound', 'source')) in records
        assert ('property', 'water_viscosity', (), ('unbound', 'unbound', 'source')) in records
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
    assert ('nu', 'water', 'Diamond', (), ('unbound', 'unbound', 'source')) in records


def test_choke_is_general_warning_and_keeps_return_contract(monkeypatch):
    from sjtu_tpmshx.df_surrogate import predict

    monkeypatch.setattr(predict, '_CHOKE_WARNED', set())
    args = ('Gyroid', 7, 0.6, 0.35, 1e5, 400, 101325, 2e-5, 0.1)
    with warning_scope({}) as records:
        assert predict.predict_dP_compressible(*args) == 101325
        assert np.isnan(predict.predict_dP_compressible(*args, strict=True))
    assert len(records) == 1
    assert next(iter(records.values())).startswith('[D-F choke]')
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
    assert len(result.warnings) == 1
    assert result.extrap_reasons == []


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


def test_range_snapshots_keep_extrema_separate_and_nonfinite_visible():
    with warning_scope({}) as records:
        for temperatures in ([200., 1100., 300.], [190., 300., 300.],
                             [300., 300., 1200.], [np.nan, np.inf, 300.]):
            tpms_props.air_cp(np.array(temperatures))
    value = next(iter(records.values()))
    assert (value.minimum, value.maximum) == ((190., (0,)), (1200., (2,)))
    assert (value.low, value.high, value.size, value.nonfinite) == (1, 1, 3, 2)
    message, = warning_messages(records)
    assert 'outside=2/3 (66.67%' in message
    assert 'peak nonfinite in one snapshot=2/3' in message
    with warning_scope({}) as invalid:
        tpms_props.air_cp(np.array([np.nan]))
    value = next(iter(invalid.values()))
    assert value.minimum is value.maximum is None
    assert value.nonfinite == 1
    assert len(list(warning_messages(invalid))) == 1


def test_side_stage_layout_and_shape_isolation_and_scope_restore():
    with warning_scope({}) as records:
        for side, stage, layout, values in (
            ('A', 'refresh', 'grid', np.array([200., 300.])),
            ('B', 'refresh', 'grid', np.array([200., 300.])),
            ('A', 'inlet', 'grid', np.array([200., 300.])),
            ('A', 'refresh', 'mean', 200.),
            ('A', 'refresh', 'grid', np.array([[200., 300.]])),
        ):
            with range_context(side=side, stage=stage, layout=layout):
                tpms_props.air_cp(values)
        with pytest.raises(ValueError), range_context(side='B', stage='inlet'):
            with range_context(side='A'):
                raise ValueError('restore nested context')
        tpms_props.air_cp(200.)
    assert len(records) == 6
    assert ('property', 'air_cp', (), ('unbound', 'unbound', 'source')) in records
    assert all(value.low == 1 for value in records.values())


@pytest.mark.parametrize('prewarm', [False, True])
def test_cache_facts_bind_to_each_run_context(prewarm, standalone_registries):
    from sjtu_tpmshx.solvers.tpms_calc import compute

    compute.cache_clear()
    args = ('Gyroid', 7., .6, .001, 300., 101325., 16., 'water')
    if prewarm:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with range_context(side='old', stage='old', layout='old'):
                compute(*args)
    with warning_scope({}) as records:
        for side in ('A', 'B'):
            with range_context(side=side, stage='inlet', layout='mean'):
                compute(*args)
    assert compute.cache_info().misses == 1
    a = {key[:-1]: value for key, value in records.items()
         if key[-1] == ('A', 'inlet', 'mean')}
    b = {key[:-1]: value for key, value in records.items()
         if key[-1] == ('B', 'inlet', 'mean')}
    assert a and a == b
    assert len(records) == len(a) + len(b)
    assert len(list(warning_messages(records))) == 2


def test_worker_merge_keeps_single_snapshot_counts_and_does_not_mutate_source():
    sources = []
    for temperatures in ([200., 300.], [190., 1200.]):
        with warning_scope({}) as worker, range_context(side='A', stage='refresh'):
            tpms_props.air_cp(np.array(temperatures))
        sources.append(worker)
    before = sources[0].copy()
    merged = {}
    merge_warnings(merged, sources)
    merge_warnings(merged, sources)
    value, = merged.values()
    assert (value.low, value.high, value.size) == (1, 1, 2)
    assert sources[0] == before
