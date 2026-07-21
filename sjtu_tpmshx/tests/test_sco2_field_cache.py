"""E3 (full-debug audit 2026-06-28): sco2_field memoizes identical (key, T, P)
field queries so the conductivity/cp fields recomputed at the SAME (Ta, P)
between _outer_post_3d and the next _outer_step_3d (h_v build) are not re-run
through CoolProp. Content-keyed -> bit-identical; cached arrays are read-only so
any accidental in-place mutation fails loud.
"""
import numpy as np
import pytest
from unittest.mock import patch

from sjtu_tpmshx.solvers import sco2_props

pytestmark = pytest.mark.skipif(
    not sco2_props._HAVE_COOLPROP, reason="CoolProp required for sCO2 tests")

_P = 8.0e6


def test_sco2_field_cache_hit_skips_propsi():
    """A second query at identical (key, T-content, P) must hit the cache and
    NOT re-call PropsSI (a new array object with equal content still hits)."""
    sco2_props.clear_field_cache()
    T = np.linspace(300.0, 360.0, 64).reshape(8, 8)
    calls = {'n': 0}
    real = sco2_props._PropsSI

    def _counting(*a, **k):
        calls['n'] += 1
        return real(*a, **k)

    with patch.object(sco2_props, '_PropsSI', _counting):
        a = sco2_props.sco2_conductivity_field(T, _P)
        b = sco2_props.sco2_conductivity_field(T.copy(), _P)  # equal content
    assert calls['n'] == 1, f"expected 1 PropsSI call (cache hit), got {calls['n']}"
    np.testing.assert_array_equal(np.asarray(a), np.asarray(b))


def test_sco2_field_cache_distinguishes_content():
    """Different T content must NOT return a stale cached field."""
    sco2_props.clear_field_cache()
    T1 = np.full((4, 4), 310.0)
    T2 = np.full((4, 4), 320.0)
    k1 = np.asarray(sco2_props.sco2_conductivity_field(T1, _P)).copy()
    k2 = np.asarray(sco2_props.sco2_conductivity_field(T2, _P)).copy()
    assert not np.allclose(k1, k2)


def test_sco2_field_cache_distinguishes_key_and_pressure():
    """The cache key includes the property key and pressure."""
    sco2_props.clear_field_cache()
    T = np.full((4, 4), 330.0)
    k = np.asarray(sco2_props.sco2_conductivity_field(T, _P)).copy()
    cp = np.asarray(sco2_props.sco2_cp_field(T, _P)).copy()
    assert not np.allclose(k, cp)                      # different key
    k_hi = np.asarray(sco2_props.sco2_conductivity_field(T, _P * 1.5)).copy()
    assert not np.allclose(k, k_hi)                    # different P


def test_sco2_field_cached_array_is_read_only():
    """Cached fields are returned read-only so an accidental in-place mutation
    fails loud instead of corrupting another caller's view."""
    sco2_props.clear_field_cache()
    T = np.full((4, 4), 315.0)
    k = sco2_props.sco2_conductivity_field(T, _P)
    with pytest.raises((ValueError, RuntimeError)):
        k[0, 0] = -1.0


def test_sco2_field_value_matches_uncached():
    """Bit-identical: a cached query equals a fresh PropsSI evaluation."""
    sco2_props.clear_field_cache()
    T = np.array([[290.0, 307.0], [312.0, 360.0]])
    cached = np.asarray(sco2_props.sco2_conductivity_field(T, _P))
    fresh = np.asarray(
        sco2_props._PropsSI("L", "T", T.ravel(), "P", float(_P), "CO2")
    ).reshape(T.shape)
    np.testing.assert_array_equal(cached, fresh)
