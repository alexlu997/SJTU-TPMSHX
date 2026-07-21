"""Unit tests for controllers.result_cache.ResultCache.

Phase 2 of 2026-05-06 main.py refactor (audit fix #4).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication

from sjtu_tpmshx.controllers.result_cache import ResultCache


def _app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


# ---------------------------------------------------------------- result API


def test_set_get_result_per_mode():
    _app()
    c = ResultCache()
    assert c.get_result('2d') is None
    payload = {'Q': 1234.5, 'dP': 6789.0}
    c.set_result('2d', payload)
    assert c.get_result('2d') == payload
    assert c.get_result('3d') is None   # mode isolation


def test_set_result_with_none_clears():
    _app()
    c = ResultCache()
    c.set_result('2d', {'a': 1})
    assert c.has_results('2d')
    c.set_result('2d', None)
    assert not c.has_results('2d')


def test_invalid_mode_raises():
    _app()
    c = ResultCache()
    with pytest.raises(ValueError, match='unknown mode'):
        c.set_result('quantum', {})
    with pytest.raises(ValueError, match='unknown mode'):
        c.get_result('quantum')


def test_has_results_aggregate():
    _app()
    c = ResultCache()
    assert not c.has_any_results()
    assert not c.has_results()
    c.set_result('3d', {'x': 1})
    assert c.has_any_results()
    assert c.has_results('3d')
    assert not c.has_results('2d')


def test_clear_one_or_all():
    _app()
    c = ResultCache()
    c.set_result('2d', {'a': 1})
    c.set_result('3d', {'b': 2})

    c.clear('2d')
    assert not c.has_results('2d')
    assert c.has_results('3d')

    c.clear()   # clear all
    assert not c.has_any_results()


# ---------------------------------------------------------------- signals


def test_results_changed_signal_emits():
    _app()
    c = ResultCache()
    received = []
    c.results_changed.connect(lambda m: received.append(m))

    c.set_result('2d', {'a': 1})
    c.set_result('3d', {'b': 2})
    c.clear('2d')

    assert received == ['2d', '3d', '2d']


# ---------------------------------------------------------------- dirty + tabs


def test_dirty_flag_lifecycle():
    _app()
    c = ResultCache()
    assert not c.is_dirty('2d')
    c.set_result('2d', {'x': 1})
    assert c.is_dirty('2d')
    c.mark_clean('2d')
    assert not c.is_dirty('2d')
    # New result re-dirties
    c.set_result('2d', {'y': 2})
    assert c.is_dirty('2d')


def test_drawn_tabs_tracking():
    _app()
    c = ResultCache()
    c.set_result('2d', {'a': 1})

    assert c.get_drawn_tabs() == set()
    assert not c.is_drawn('temp')
    c.mark_drawn('temp')
    c.mark_drawn('pres')
    assert c.is_drawn('temp')
    assert c.is_drawn('pres')
    assert c.get_drawn_tabs() == {'temp', 'pres'}


def test_set_result_clears_drawn_tabs():
    """New results invalidate prior tab renders."""
    _app()
    c = ResultCache()
    c.set_result('2d', {'a': 1})
    c.mark_drawn('temp')
    c.mark_drawn('vel')
    assert c.get_drawn_tabs() == {'temp', 'vel'}

    c.set_result('2d', {'a': 2})
    assert c.get_drawn_tabs() == set()


def test_replace_drawn_tabs_legacy():
    """Legacy assignment pattern: window._drawn_tabs = some_set."""
    _app()
    c = ResultCache()
    c.replace_drawn_tabs({'temp', 'pres', '3d'})
    assert c.get_drawn_tabs() == {'temp', 'pres', '3d'}


# ---------------------------------------------------------------- recent ring


def test_push_recent_ring_bounded():
    _app()
    c = ResultCache(max_recent=3)
    for i in range(5):
        c.push_recent({'idx': i})
    runs = c.get_recent()
    assert len(runs) == 3
    # newest 3 = idx 2, 3, 4 (FIFO eviction)
    assert [r['idx'] for r in runs] == [2, 3, 4]


def test_recent_pushed_signal_emits():
    _app()
    c = ResultCache()
    received = []
    c.recent_pushed.connect(lambda meta: received.append(meta))
    c.push_recent({'Q': 100})
    c.push_recent({'Q': 200})
    assert len(received) == 2
    assert received[0]['Q'] == 100


def test_replace_recent_session_restore():
    _app()
    c = ResultCache(max_recent=5)
    c.replace_recent([{'i': 1}, {'i': 2}])
    assert [r['i'] for r in c.get_recent()] == [1, 2]


def test_push_recent_isolated_from_caller_dict():
    """Caller mutating the dict after push should not affect the ring."""
    _app()
    c = ResultCache()
    payload = {'Q': 100}
    c.push_recent(payload)
    payload['Q'] = 999   # mutate caller's dict
    assert c.get_recent()[0]['Q'] == 100   # ring unaffected


# ---------------------------------------------------------------- repr


def test_repr_shows_state():
    _app()
    c = ResultCache()
    s = repr(c)
    assert '2d=-' in s and '3d=-' in s
    c.set_result('2d', {'x': 1})
    s = repr(c)
    assert '2d=+d' in s   # has result + dirty
    c.mark_clean('2d')
    s = repr(c)
    assert '2d=+' in s and '2d=+d' not in s
