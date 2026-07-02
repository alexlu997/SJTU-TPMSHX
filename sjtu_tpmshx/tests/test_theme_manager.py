"""Unit tests for ui.theme_manager.ThemeManager.

Phase 3 of 2026-05-06 main.py refactor (audit fix #4).
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication

from ui.theme_manager import ThemeManager, _LEGACY_GLOBALS


def _app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


# ---------------------------------------------------------------- basics


def test_lazy_styles_build_on_first_call():
    _app()
    tm = ThemeManager()
    assert tm._styles is None
    s = tm.current_styles()
    assert isinstance(s, dict)
    assert 'BG' in s
    assert tm._styles is s   # cached


def test_style_accessor_returns_default_for_missing_key():
    _app()
    tm = ThemeManager()
    assert tm.style('NOPE_DOES_NOT_EXIST', 'fallback') == 'fallback'


def test_current_theme_name_returns_string():
    _app()
    tm = ThemeManager()
    assert isinstance(tm.current_theme_name(), str)


def test_palette_is_dict():
    _app()
    tm = ThemeManager()
    p = tm.palette()
    assert isinstance(p, dict)
    assert 'bg' in p


# ---------------------------------------------------------------- bind


def test_bind_to_module_writes_legacy_globals():
    _app()
    tm = ThemeManager()
    mod = types.ModuleType('mock_main')
    tm.bind_to_module(mod)
    # Every legacy global must exist on the bound module
    for key in _LEGACY_GLOBALS:
        assert hasattr(mod, f'_{key}'), f'missing _{key}'
    # Master dict also exposed
    assert hasattr(mod, '_S')
    assert isinstance(mod._S, dict)


def test_bind_idempotent():
    _app()
    tm = ThemeManager()
    mod = types.ModuleType('mock_main')
    tm.bind_to_module(mod)
    tm.bind_to_module(mod)   # second time should not duplicate
    assert tm._bound.count(mod) == 1


def test_rebuild_refreshes_bound_modules():
    _app()
    tm = ThemeManager()
    mod = types.ModuleType('mock_main')
    tm.bind_to_module(mod)
    bg_before = mod._BG
    tm.rebuild()
    # BG may be unchanged value-wise (same theme) but the dict ref must
    # reflect a freshly built instance.
    assert tm.current_styles() is mod._S
    assert isinstance(mod._BG, str)
    _ = bg_before   # silence linter — we kept reference for symmetry


# ---------------------------------------------------------------- signal


def test_set_theme_emits_signal_on_success():
    _app()
    tm = ThemeManager()
    received = []
    tm.theme_changed.connect(lambda name: received.append(name))
    # Switching to current theme is fine — set_theme accepts both names.
    cur = tm.current_theme_name()
    target = 'light' if cur == 'dark' else 'dark'
    ok = tm.set_theme(target)
    assert ok
    assert received == [target]
    # Restore so the test doesn't leak state across runs.
    tm.set_theme(cur)


def test_set_theme_rejects_garbage_name_and_no_signal():
    _app()
    tm = ThemeManager()
    received = []
    tm.theme_changed.connect(lambda name: received.append(name))
    ok = tm.set_theme('not-a-real-theme-name-xyz')
    assert ok is False
    assert received == []


# ---------------------------------------------------------------- repr


def test_repr_safe():
    _app()
    tm = ThemeManager()
    s = repr(tm)
    assert 'ThemeManager' in s
    assert 'bound_modules' in s
