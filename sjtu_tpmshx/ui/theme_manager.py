"""ThemeManager — singleton-style wrapper around ui.theme primitives.

Phase 3 of 2026-05-06 main.py refactor (audit fix #4). Aggregates the
theme state that was previously inlined as module-level globals in
``main.py`` (``_S``, ``_BG``, ``_LBL``, …) and the rebuild step in
``main._rebuild_styles``.

Design constraints
------------------
* **Backward compatible**: ``ui_builders.py`` and 5 other UI modules read
  styles via ``import main as _m; m._BG``. Those callers are not migrated
  in this phase; instead, ``bind_to_module(mod)`` mirrors the manager's
  current style dict onto a module so the legacy access pattern keeps
  working. After ``set_theme``, the bound module's globals refresh in
  place, so old call sites stay valid without code changes.
* **Signal-driven**: emits ``theme_changed(str name)`` — new code (Phase 5)
  can subscribe instead of polling globals.
* **Single source of truth**: under the hood, ``ui.theme.set_theme`` is
  still the actual writer for the persistent ``.theme`` marker; the
  manager just shields callers from importing it directly.

See ``vault/reports/refactor/2026-05-06-main-py-refactor-plan-CN.md`` §
Phase 3 for the deeper context.
"""
from __future__ import annotations

import types
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal


# Style-dict keys that historically lived as module-level globals on
# main.py. Listed here so ``bind_to_module`` can mirror them with a
# single source of truth.
_LEGACY_GLOBALS = (
    'BG', 'LBL', 'VAL', 'VAL_WARN', 'INP', 'COMBO',
    'T_NEUTRAL', 'T_A', 'T_B',
    'F_NEUTRAL', 'F_A', 'F_B',
    'BTN_A', 'BTN_B', 'BTN_TPMS', 'BTN_RUN',
    'BTN_PRIMARY', 'BTN_SECONDARY', 'BTN_TERTIARY', 'BTN_LONG',
    'TOOLBTN_SPLIT',
)


class ThemeManager(QObject):
    """Centralised theme state with change notification.

    Construct once per process. Pass to consumers explicitly (DI) or call
    ``bind_to_module(main)`` to keep the legacy ``main._BG`` access path
    working unchanged.

    Signals
    -------
    theme_changed(str name)
        Emitted when ``set_theme`` succeeds. Payload = new theme name.
    """

    theme_changed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        # Lazy-import the theme module so that this controller can be
        # imported even before Qt is initialised (e.g. during pytest
        # collection). The first ``current_styles`` call materialises it.
        self._styles: Optional[Dict[str, Any]] = None
        self._bound: List[types.ModuleType] = []

    # ------------------------------------------------------------------ helpers

    def _theme_module(self):
        from ui import theme as _theme
        return _theme

    # ------------------------------------------------------------------ state

    def current_styles(self) -> Dict[str, Any]:
        """Return the latest style dict; builds it lazily on first call."""
        if self._styles is None:
            self._styles = self._theme_module()._build_styles()
        return self._styles

    def current_theme_name(self) -> str:
        return self._theme_module().get_theme_name()

    def palette(self) -> Dict[str, Any]:
        """Raw colour palette (``ui.theme.get_theme()``) — separate from
        the *style* dict (which is fully-formed QSS strings).
        """
        return self._theme_module().get_theme()

    def style(self, key: str, default: Any = '') -> Any:
        """Single-key accessor: ``manager.style('BG')`` ≡ ``_S['BG']``.

        Returns ``default`` if missing rather than raising — keeps optional
        keys (``TOOLBTN_SPLIT``, future additions) safe.
        """
        return self.current_styles().get(key, default)

    # ------------------------------------------------------------------ rebuild

    def rebuild(self) -> Dict[str, Any]:
        """Re-evaluate ``_build_styles()`` and refresh bound modules.

        Called after a theme switch or font/density change. Does **not**
        emit ``theme_changed`` by itself — that's reserved for explicit
        ``set_theme`` calls so that swap-and-restart prompts don't fire on
        every density tweak.
        """
        self._styles = self._theme_module()._build_styles()
        self._sync_bound()
        # mpl theme follows palette
        try:
            self._theme_module().apply_mpl_theme()
        except Exception:
            pass
        return self._styles

    def set_theme(self, name: str) -> bool:
        """Persist + activate the named theme. Returns True on success.

        On success: rebuilds style dict, syncs bound modules, fires
        ``theme_changed``. The actual GUI repaint is *not* automatic —
        callers must restart or rebuild widgets (Qt cannot live-swap QSS
        across all already-constructed widgets cleanly; see ``main.py``
        comment around ``toggle_theme``).
        """
        try:
            self._theme_module().set_theme(name)
        except Exception:
            return False
        self.rebuild()
        self.theme_changed.emit(name)
        return True

    # ------------------------------------------------------------------ binding

    def bind_to_module(self, mod: types.ModuleType) -> None:
        """Mirror current style entries onto ``mod`` as ``_<KEY>`` globals.

        Backward-compat hatch for ``main.py``-era code that reads
        ``main._BG`` etc. After binding, every ``rebuild`` call refreshes
        these globals in place.
        """
        if mod not in self._bound:
            self._bound.append(mod)
        self._sync_one(mod)

    def _sync_bound(self) -> None:
        for mod in self._bound:
            self._sync_one(mod)

    def _sync_one(self, mod: types.ModuleType) -> None:
        styles = self.current_styles()
        for key in _LEGACY_GLOBALS:
            setattr(mod, f'_{key}', styles.get(key, ''))
        # Also expose the master dict so rare consumers can introspect.
        setattr(mod, '_S', styles)

    # ------------------------------------------------------------------ misc

    def __repr__(self) -> str:
        return (f'<ThemeManager theme={self.current_theme_name()!r} '
                f'bound_modules={len(self._bound)}>')
