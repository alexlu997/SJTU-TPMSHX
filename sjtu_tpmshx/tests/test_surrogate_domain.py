"""Sanity tests for df_surrogate.surrogate_domain.check_surrogate_domain_at_point.

Covers:
  * In-window inputs return empty list
  * Out-of-window L raises ValueError when allow_extrap=False
  * Out-of-window L returns reason list (no raise) when allow_extrap=True
  * Out-of-window t same behavior
  * Out-of-window Re (via velocity) same behavior
  * Env var TPMSHX_ALLOW_EXTRAP=1 forces allow_extrap=True
  * side='A' / 'B' label propagates to reason text
"""
from __future__ import annotations

import os
import pytest

from df_surrogate.surrogate_domain import (
    check_surrogate_domain_at_point,
    _SURROGATE_L_MM, _SURROGATE_T_MM, _SURROGATE_RE,
)


# ─── In-window — clean pass ────────────────────────────────────────


def test_in_window_returns_empty():
    """Reasonable Shanghai inputs (mid-window) → no reasons."""
    reasons = check_surrogate_domain_at_point(
        'Diamond', L_mm=6.0, t_mm=0.4, k_s=16.0,
        u=5.0, T=350.0, P=101325.0, side='A',
        allow_extrap=False)
    assert reasons == []


# ─── Out-of-window — raise vs warn ─────────────────────────────────


def test_oow_L_below_min_raises_default():
    """L = 3 mm < 4 mm window → ValueError when allow_extrap=False."""
    with pytest.raises(ValueError):
        check_surrogate_domain_at_point(
            'Diamond', L_mm=3.0, t_mm=0.4, k_s=16.0,
            u=5.0, T=350.0, side='A')


def test_oow_L_above_max_raises_default():
    """L = 10 mm > 8 mm window."""
    with pytest.raises(ValueError):
        check_surrogate_domain_at_point(
            'Diamond', L_mm=10.0, t_mm=0.4, k_s=16.0,
            u=5.0, T=350.0, side='A')


def test_oow_t_above_max_raises_default():
    """t = 0.6 mm > 0.5 mm window (the original Shanghai 't=0.6 dead-end')."""
    with pytest.raises(ValueError):
        check_surrogate_domain_at_point(
            'Diamond', L_mm=6.0, t_mm=0.6, k_s=16.0,
            u=5.0, T=350.0, side='A')


def test_oow_L_with_allow_extrap_returns_reasons():
    """allow_extrap=True converts raise → warn + return reason list."""
    with pytest.warns(UserWarning):
        reasons = check_surrogate_domain_at_point(
            'Diamond', L_mm=10.0, t_mm=0.4, k_s=16.0,
            u=5.0, T=350.0, side='A', allow_extrap=True)
    assert len(reasons) >= 1
    assert any('L_cell' in r for r in reasons)


def test_oow_t_with_allow_extrap_returns_reasons():
    with pytest.warns(UserWarning):
        reasons = check_surrogate_domain_at_point(
            'Diamond', L_mm=6.0, t_mm=0.6, k_s=16.0,
            u=5.0, T=350.0, side='B', allow_extrap=True)
    assert len(reasons) >= 1
    assert any('Wall thickness' in r or 't =' in r for r in reasons)


def test_oow_velocity_too_low_raises():
    """Very low u → Re below window minimum 400."""
    with pytest.raises(ValueError):
        check_surrogate_domain_at_point(
            'Diamond', L_mm=6.0, t_mm=0.4, k_s=16.0,
            u=0.1, T=350.0, side='A')


# ─── side label propagation ────────────────────────────────────────


def test_side_label_in_reason():
    """side='B' should appear in any Re-related failure message."""
    with pytest.warns(UserWarning):
        reasons = check_surrogate_domain_at_point(
            'Diamond', L_mm=6.0, t_mm=0.4, k_s=16.0,
            u=0.1, T=350.0, side='B', allow_extrap=True)
    re_reasons = [r for r in reasons if 'Re' in r]
    assert any('B' in r for r in re_reasons), \
        f"side='B' label missing in: {re_reasons}"


# ─── Env var override ──────────────────────────────────────────────


def test_env_var_forces_allow_extrap(monkeypatch):
    """TPMSHX_ALLOW_EXTRAP=1 should let oow inputs pass with warning."""
    monkeypatch.setenv('TPMSHX_ALLOW_EXTRAP', '1')
    with pytest.warns(UserWarning):
        reasons = check_surrogate_domain_at_point(
            'Diamond', L_mm=10.0, t_mm=0.4, k_s=16.0,
            u=5.0, T=350.0, side='A', allow_extrap=False)
    assert len(reasons) >= 1


def test_env_var_off_still_raises(monkeypatch):
    """No env var + default allow_extrap=False → raise as usual."""
    monkeypatch.delenv('TPMSHX_ALLOW_EXTRAP', raising=False)
    with pytest.raises(ValueError):
        check_surrogate_domain_at_point(
            'Diamond', L_mm=10.0, t_mm=0.4, k_s=16.0,
            u=5.0, T=350.0, side='A')


# ─── Boundary cases ────────────────────────────────────────────────


def test_exactly_at_L_lower_bound():
    """L = 4.0 (lower bound exactly) — should not produce an L-related reason.
    Use u high enough to also keep Re inside [400, 16000]."""
    reasons = check_surrogate_domain_at_point(
        'Diamond', L_mm=_SURROGATE_L_MM[0], t_mm=0.4, k_s=16.0,
        u=10.0, T=350.0, side='A', allow_extrap=True)
    L_reasons = [r for r in reasons if 'L_cell' in r]
    assert L_reasons == []


def test_exactly_at_t_upper_bound():
    """t = 0.5 (upper bound exactly) — inside."""
    reasons = check_surrogate_domain_at_point(
        'Diamond', L_mm=6.0, t_mm=_SURROGATE_T_MM[1], k_s=16.0,
        u=5.0, T=350.0, side='A', allow_extrap=False)
    t_reasons = [r for r in reasons if 'thickness' in r or 't =' in r]
    assert t_reasons == []
