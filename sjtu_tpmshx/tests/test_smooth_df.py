"""Tests for df_surrogate.smooth_df — unified smooth-wall D-F model.

Scope guard: SmoothDF is the SMOOTH-wall engine (water+air CFD). It does
NOT replace the production rough surrogate (predict.predict_K_cF) — a full
swap was gate-tested 2026-06-11: Shanghai 3D dP RMSRE 7.19% -> 58.78%.
"""
import numpy as np
import pytest

from df_surrogate.smooth_df import SmoothDF, PREBUILT_CSV, _geom

pytestmark = pytest.mark.skipif(
    not PREBUILT_CSV.exists(),
    reason="prebuilt smooth_df_coeffs.csv missing — run python -m df_surrogate.smooth_df")


@pytest.fixture(scope="module")
def mdl():
    return SmoothDF()


def test_prebuilt_table_shape(mdl):
    t = mdl.table
    assert len(t) == 40
    assert set(t.tp.unique()) == {"Diamond", "Gyroid"}
    assert (t.m_lat > 0).all()
    assert t.logK.notna().all() and t.logB.notna().all()


def test_K_follows_dh2_trend(mdl):
    """K surface is pure physical trend: K ratio == (Dh ratio)^2."""
    for tp in ["Diamond", "Gyroid"]:
        K4, _ = mdl.predict_K_B(tp, 4.0, 0.4)
        K8, _ = mdl.predict_K_B(tp, 8.0, 0.4)
        _, Dh4 = _geom(tp, 4.0, 0.4)
        _, Dh8 = _geom(tp, 8.0, 0.4)
        assert K8 / K4 == pytest.approx((Dh8 / Dh4) ** 2, rel=1e-9)


def test_B_positive_finite_on_grid(mdl):
    for tp in ["Diamond", "Gyroid"]:
        for L in [4, 5, 6, 7, 8]:
            for t in [0.3, 0.4, 0.5, 0.6]:
                K, B = mdl.predict_K_B(tp, float(L), float(t))
                assert np.isfinite(K) and K > 0
                assert np.isfinite(B) and 10.0 < B < 5000.0


def test_cF_decreases_with_Re(mdl):
    cf_lo = mdl.predict_cF("Gyroid", 6.0, 0.4, 500)
    cf_hi = mdl.predict_cF("Gyroid", 6.0, 0.4, 20000)
    assert cf_lo > cf_hi > 0


def test_dp_positive_and_increasing_in_u(mdl):
    dps = [mdl.predict_dP("Diamond", 5.0, 0.4, u, 998.0, 8.9e-4, 0.06)
           for u in (0.05, 0.5, 2.0)]
    assert all(d > 0 for d in dps)
    assert dps[0] < dps[1] < dps[2]


def test_extrapolation_bounded(mdl):
    """Outside the hull the trust region decays to the physical trend —
    values stay sane (the pure-RBF pathology gave cF ~ 1 at L=12)."""
    K, B = mdl.predict_K_B("Gyroid", 12.0, 0.6)
    assert 20.0 < B < 2000.0
    assert 1e-9 < K < 1e-5


def test_regression_pin_shanghai_geom(mdl):
    """Pin smooth-wall values at the Shanghai geometry (G7/t0.6).
    These are SMOOTH values (~3x below the rough production cF=535) —
    if this pin moves, the prebuilt table changed."""
    K, B = mdl.predict_K_B("Gyroid", 7.0, 0.6)
    assert K == pytest.approx(1.327e-07, rel=5e-3)
    assert B == pytest.approx(301.6, rel=5e-3)
    cf2000 = mdl.predict_cF("Gyroid", 7.0, 0.6, 2000)
    assert cf2000 == pytest.approx(280.2, rel=5e-3)
    assert cf2000 < 400.0   # smooth stays smooth — never the rough 535
