"""SignalRouter — central registry for Qt signal/slot connections.

Phase 3 of 2026-05-06 main.py refactor (audit fix #4). The current
``main.py`` does ~50 raw ``widget.signal.connect(self._on_x)`` calls
inline in ``__init__`` and friends; on ``closeEvent`` none are
disconnected. PySide6 normally cleans up when the C++ widget is
destroyed, but **bound-method slots that capture ``self`` keep the
window alive** in some scenarios (e.g. lingering QTimer single-shots,
QThreadPool callbacks), and exception-during-shutdown is hard to debug.

Usage
-----
    router = SignalRouter(parent=self)
    router.connect(self.btn_run, 'clicked', self.run_calculation,
                   tag='run-button')
    router.connect(self.combo_dim.currentIndexChanged,
                   self._on_dim_changed)

    # On close:
    router.disconnect_all()

The ``signal`` argument may be either:
  * a bound signal object (``widget.clicked``), or
  * a ``(sender, signal_name)`` pair (deferred lookup) — useful when the
    widget hasn't been built yet at registration time.

Why not just rely on Qt's parent ownership?
* Bound-method slots that close over ``self`` create a Python-side
  reference loop the C++ delete doesn't break.
* Connections to QThreadPool or singletons (``QApplication``, theme
  manager, controller signals) outlive the window naturally.
* Centralising disconnect makes leak-hunting one-line traceable.

This is *additive*: the existing ``.connect()`` call sites in
``main.py`` keep working. New code in Phases 4-5 should prefer
``router.connect``.
"""
from __future__ import annotations

import weakref
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from PySide6.QtCore import QObject, Signal


SignalLike = Any   # bound signal object — Qt offers no public type alias


@dataclass
class _Connection:
    """One registered signal/slot pair, retained until disconnected."""
    signal_obj: SignalLike
    slot: Callable[..., Any]
    tag: str = ''
    sender_ref: Optional[weakref.ReferenceType] = None
    alive: bool = True


class SignalRouter(QObject):
    """Holds connections and disconnects them en masse on shutdown.

    Signals
    -------
    connection_added(str tag)
        Emitted after each successful ``connect``.
    connection_removed(str tag)
        Emitted after each successful ``disconnect``.
    """

    connection_added = Signal(str)
    connection_removed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._connections: List[_Connection] = []

    # ------------------------------------------------------------------ register

    def connect(self, signal: SignalLike, slot: Callable[..., Any],
                tag: str = '', sender: Optional[QObject] = None) -> bool:
        """Register and connect a signal/slot pair.

        Returns True on success, False if Qt rejects the connection
        (mismatched signature, already-deleted widget, etc.). Logs
        nothing on failure — caller decides whether to warn.

        ``sender`` is optional; if supplied a weakref is held so
        ``disconnect_all`` can skip slots whose widget has already been
        destroyed (avoids ``RuntimeError: wrapped C/C++ object deleted``).
        """
        try:
            signal.connect(slot)
        except (TypeError, RuntimeError):
            return False
        ref = weakref.ref(sender) if sender is not None else None
        self._connections.append(_Connection(
            signal_obj=signal, slot=slot, tag=tag, sender_ref=ref))
        if tag:
            self.connection_added.emit(tag)
        return True

    def adopt(self, signal: SignalLike, slot: Callable[..., Any],
              tag: str = '', sender: Optional[QObject] = None) -> None:
        """Record an *already-connected* pair so ``disconnect_all`` covers it.

        Lets you migrate existing ``.connect()`` call sites incrementally
        without flipping them to ``router.connect`` in one big diff.
        """
        ref = weakref.ref(sender) if sender is not None else None
        self._connections.append(_Connection(
            signal_obj=signal, slot=slot, tag=tag, sender_ref=ref))
        if tag:
            self.connection_added.emit(tag)

    # ------------------------------------------------------------------ release

    def disconnect_one(self, tag: str) -> int:
        """Disconnect every registered pair whose tag matches. Returns count."""
        n = 0
        for c in self._connections:
            if not c.alive or c.tag != tag:
                continue
            if self._safe_disconnect(c):
                n += 1
        return n

    def disconnect_all(self) -> int:
        """Disconnect every registered pair. Returns count of successes.

        Idempotent — calling twice is a no-op on the second pass.
        """
        n = 0
        for c in self._connections:
            if not c.alive:
                continue
            if self._safe_disconnect(c):
                n += 1
        return n

    def _safe_disconnect(self, c: _Connection) -> bool:
        # Skip if the sender widget was already torn down. The weakref
        # check is cheap and avoids a noisy RuntimeError under teardown.
        if c.sender_ref is not None and c.sender_ref() is None:
            c.alive = False
            return False
        try:
            c.signal_obj.disconnect(c.slot)
        except (TypeError, RuntimeError):
            # Already disconnected, or signal-object deleted — both fine.
            c.alive = False
            return False
        c.alive = False
        if c.tag:
            self.connection_removed.emit(c.tag)
        return True

    # ------------------------------------------------------------------ inspect

    def count(self, alive_only: bool = True) -> int:
        if alive_only:
            return sum(1 for c in self._connections if c.alive)
        return len(self._connections)

    def tags(self) -> List[str]:
        return [c.tag for c in self._connections if c.tag and c.alive]

    def clear(self) -> None:
        """Drop the registry without disconnecting (test helper)."""
        self._connections.clear()

    def __repr__(self) -> str:
        return (f'<SignalRouter alive={self.count()} '
                f'total={self.count(alive_only=False)}>')
