"""Unit tests for ui.math_symbols Unicode rendering helpers (Phase 3)."""
from __future__ import annotations

import pytest

from ui.math_symbols import to_unicode, greek


# ─── Greek lookup ──────────────────────────────────────────────────


def test_greek_lower_basic():
    assert greek('mu') == 'μ'
    assert greek('rho') == 'ρ'
    assert greek('epsilon') == 'ε'
    assert greek('alpha') == 'α'


def test_greek_upper():
    assert greek('Delta') == 'Δ'
    assert greek('Sigma') == 'Σ'
    assert greek('Pi') == 'Π'


def test_greek_unknown_returns_empty():
    assert greek('made_up_letter') == ''
    assert greek('') == ''


def test_greek_eps_alias():
    """'eps' should resolve to ε (alias for 'epsilon')."""
    assert greek('eps') == 'ε'


# ─── Unicode subscript replacement ─────────────────────────────────


def test_to_unicode_D_h_becomes_subscript_h():
    """D_h → Dₕ (Unicode lower-h subscript)."""
    out = to_unicode("D_h = 0.42 mm")
    assert 'Dₕ' in out
    assert 'D_h' not in out
    assert '0.42' in out


def test_to_unicode_rho_s_becomes_greek_rho_subscript_s():
    out = to_unicode("rho_s = 7900")
    assert 'ρₛ' in out
    assert 'rho_s' not in out


def test_to_unicode_m_dot_becomes_m_with_dot_overhead():
    out = to_unicode("m_dot inlet = 0.5 kg/s")
    assert 'ṁ' in out
    assert 'm_dot' not in out


def test_to_unicode_eps_f_becomes_greek_eps():
    """eps_f → ε_f (no Unicode 'f' subscript so '_f' literal)."""
    out = to_unicode("eps_f = 0.35")
    assert 'ε' in out


def test_to_unicode_no_match_passes_through():
    """Strings without project tokens come back unchanged."""
    s = "Pareto front 12 / 32 evals"
    assert to_unicode(s) == s


def test_to_unicode_multiple_replacements_in_one_string():
    out = to_unicode("D_h vs rho_s comparison")
    assert 'Dₕ' in out and 'ρₛ' in out


def test_to_unicode_longest_first_priority():
    """'T_inA' should NOT collide with 'T' or '_inA' — the project map
    handles it as a literal pass-through (T_inA → T_inA)."""
    out = to_unicode("T_inA = 350 K")
    # Currently passes through (no Unicode upper-A subscript)
    assert 'T_inA' in out


def test_to_unicode_A_0_becomes_subscript_zero():
    """A_0 → A₀."""
    out = to_unicode("A_0 = 1500 m^-1")
    assert 'A₀' in out


def test_to_unicode_idempotent():
    """Running to_unicode twice yields the same result."""
    s = "D_h, rho_s, m_dot"
    out1 = to_unicode(s)
    out2 = to_unicode(out1)
    assert out1 == out2
