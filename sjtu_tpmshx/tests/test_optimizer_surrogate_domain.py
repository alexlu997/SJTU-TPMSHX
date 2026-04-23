"""Guard: optimizer refuses flow conditions that push Re outside the
ConstDF-v1 surrogate training window. Silent extrapolation → bogus
designs that pareto-dominate real ones for the wrong reasons.
"""
import pytest
from optimization.optimizer import (
    _check_surrogate_domain, _make_problem, DEFAULT_CONFIG,
    _SURROGATE_RE,
)


def test_default_config_inside_domain():
    # DEFAULT_CONFIG (u_A=10, T_inA=350) should be well inside training Re.
    cfg = dict(DEFAULT_CONFIG)
    _check_surrogate_domain(cfg)  # no raise


def test_too_fast_u_raises():
    cfg = dict(DEFAULT_CONFIG)
    cfg['u_A'] = 500.0  # far above any sensible air velocity for TPMS
    with pytest.raises(ValueError, match="training window"):
        _check_surrogate_domain(cfg)


def test_too_slow_u_raises():
    cfg = dict(DEFAULT_CONFIG)
    cfg['u_A'] = 0.01  # Re way below 400
    with pytest.raises(ValueError, match="training window"):
        _check_surrogate_domain(cfg)


def test_make_problem_propagates_check():
    with pytest.raises(ValueError, match="training window"):
        _make_problem({'u_A': 500.0})


def test_re_bounds_are_positive():
    lo, hi = _SURROGATE_RE
    assert 0 < lo < hi
