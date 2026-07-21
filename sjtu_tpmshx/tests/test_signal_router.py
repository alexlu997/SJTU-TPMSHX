"""Unit tests for controllers.signal_router.SignalRouter.

Phase 3 of 2026-05-06 main.py refactor (audit fix #4).
"""
from __future__ import annotations

import os


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QObject, Signal

from sjtu_tpmshx.controllers.signal_router import SignalRouter


def _app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


class _Emitter(QObject):
    """Minimal signal-emitting object for tests."""
    fired = Signal(int)


# ---------------------------------------------------------------- connect


def test_connect_records_and_invokes_slot():
    _app()
    em = _Emitter()
    router = SignalRouter()
    received = []
    ok = router.connect(em.fired, lambda i: received.append(i),
                        tag='primary', sender=em)
    assert ok
    em.fired.emit(7)
    assert received == [7]
    assert router.count() == 1


def test_connect_records_no_tag_anonymous():
    _app()
    em = _Emitter()
    router = SignalRouter()
    router.connect(em.fired, lambda i: None)
    assert router.count() == 1
    assert router.tags() == []   # no tag → empty


def test_connect_added_signal_emits_for_tagged():
    _app()
    em = _Emitter()
    router = SignalRouter()
    received = []
    router.connection_added.connect(lambda t: received.append(t))
    router.connect(em.fired, lambda i: None, tag='alpha', sender=em)
    router.connect(em.fired, lambda i: None)   # untagged — no emit
    assert received == ['alpha']


# ---------------------------------------------------------------- disconnect


def test_disconnect_all_breaks_connection():
    _app()
    em = _Emitter()
    router = SignalRouter()
    received = []
    router.connect(em.fired, lambda i: received.append(i), sender=em)
    em.fired.emit(1)
    n = router.disconnect_all()
    assert n == 1
    em.fired.emit(2)
    assert received == [1]   # second emit did not fire


def test_disconnect_all_idempotent():
    _app()
    em = _Emitter()
    router = SignalRouter()
    router.connect(em.fired, lambda i: None, sender=em)
    assert router.disconnect_all() == 1
    # Second pass: nothing alive, returns 0
    assert router.disconnect_all() == 0


def test_disconnect_one_only_targets_matching_tag():
    _app()
    em = _Emitter()
    router = SignalRouter()
    a, b = [], []
    router.connect(em.fired, lambda i: a.append(i), tag='A', sender=em)
    router.connect(em.fired, lambda i: b.append(i), tag='B', sender=em)
    n = router.disconnect_one('A')
    assert n == 1
    em.fired.emit(99)
    assert a == []
    assert b == [99]


def test_disconnect_signal_emits_removed():
    _app()
    em = _Emitter()
    router = SignalRouter()
    seen = []
    router.connection_removed.connect(lambda t: seen.append(t))
    router.connect(em.fired, lambda i: None, tag='x', sender=em)
    router.disconnect_all()
    assert seen == ['x']


# ---------------------------------------------------------------- adopt


def test_adopt_existing_connection_then_disconnect_all():
    """`.connect()` directly first, register via adopt, expect disconnect."""
    _app()
    em = _Emitter()
    router = SignalRouter()
    received = []

    def slot(i):
        received.append(i)

    em.fired.connect(slot)
    router.adopt(em.fired, slot, tag='legacy', sender=em)

    em.fired.emit(1)
    n = router.disconnect_all()
    assert n == 1
    em.fired.emit(2)
    assert received == [1]


# ---------------------------------------------------------------- weakref


def test_weakref_skips_destroyed_sender():
    _app()
    em = _Emitter()
    router = SignalRouter()
    router.connect(em.fired, lambda i: None, tag='ephemeral', sender=em)
    # Drop the sender. weakref should now be dead.
    em.deleteLater()
    em = None
    import gc
    gc.collect()
    # Pumping the event loop for deleteLater — offscreen is fine without.
    # disconnect_all should not raise; sender_ref returns None → skipped.
    n = router.disconnect_all()
    # Either skipped (n==0) or success (n==1) acceptable depending on GC
    # timing; the key invariant is "no crash".
    assert n in (0, 1)


# ---------------------------------------------------------------- introspect


def test_count_alive_vs_total():
    _app()
    em = _Emitter()
    router = SignalRouter()
    router.connect(em.fired, lambda i: None, sender=em)
    router.connect(em.fired, lambda i: None, sender=em)
    assert router.count() == 2
    assert router.count(alive_only=False) == 2
    router.disconnect_all()
    assert router.count() == 0
    assert router.count(alive_only=False) == 2


def test_clear_drops_registry_without_disconnect():
    _app()
    em = _Emitter()
    router = SignalRouter()
    received = []
    router.connect(em.fired, lambda i: received.append(i), sender=em)
    router.clear()
    em.fired.emit(5)
    # Connection still active at the Qt level since we only cleared the
    # registry — slot still fires.
    assert received == [5]


def test_repr_safe():
    _app()
    router = SignalRouter()
    s = repr(router)
    assert 'SignalRouter' in s
    assert 'alive=0' in s
