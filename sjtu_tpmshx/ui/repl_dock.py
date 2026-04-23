"""Python REPL dock — advanced users can prototype live against the
running Main_Menu instance. Namespace: `window` (the Main_Menu), `np`,
`pv` (pyvista if available), `plt` (matplotlib.pyplot).

Intentionally uses unguarded `exec` / `eval` — this is a desktop tool
on the user's own machine, and the REPL's whole point is scripting.
Security note: do NOT expose this dock over a network / remote session.
"""
from __future__ import annotations

import io
import sys
import traceback
import contextlib

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QPlainTextEdit, QLineEdit, QLabel,
)

from .theme import get_theme


class ReplDock(QDockWidget):
    def __init__(self, window):
        super().__init__("Python REPL", window)
        self.setObjectName("ReplDock")
        self._w = window
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable
                         | QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)

        t = get_theme()
        root = QWidget()
        root.setStyleSheet(
            f"background:{t.get('surface_raised', t['card_bg'])};"
            f"color:{t['fg']};")
        v = QVBoxLayout(root); v.setContentsMargins(10, 8, 10, 8); v.setSpacing(6)

        hdr = QLabel("PYTHON  REPL  ·  window, np, pv, plt ready")
        hdr.setStyleSheet(
            f"color:{t.get('sub_fg', t['fg'])}; font-size:8pt; font-weight:700;"
            "letter-spacing:1.4px; background:transparent; border:none;"
            "font-family:'Fira Sans','Inter',sans-serif;")
        v.addWidget(hdr)

        _mono = "'Fira Code','JetBrains Mono','Consolas',monospace"
        self._out = QPlainTextEdit()
        self._out.setReadOnly(True)
        self._out.setStyleSheet(
            f"background:{t.get('surface_elevated', t['card_bg'])};"
            f"color:{t['fg']};"
            f"border:1px solid {t.get('border_subtle', t['card_border'])};"
            f"border-radius:6px; padding:6px;"
            f"font-family:{_mono}; font-size:9pt;")
        self._out.setMinimumHeight(160)
        v.addWidget(self._out, 1)

        self._in = QLineEdit()
        self._in.setPlaceholderText(
            ">>> enter an expression or statement (↑/↓ history) …")
        self._in.setStyleSheet(
            f"background:{t.get('inp_bg', t['card_bg'])};"
            f"color:{t['fg']};"
            f"border:1px solid {t.get('border_subtle', t['card_border'])};"
            f"border-radius:6px; padding:6px 10px;"
            f"font-family:{_mono}; font-size:10pt;")
        self._in.returnPressed.connect(self._on_submit)
        v.addWidget(self._in)

        self._history: list[str] = []
        self._hist_idx = 0

        # ↑/↓ history navigation scoped to the input line.
        QShortcut(QKeySequence(Qt.Key.Key_Up), self._in).activated.connect(
            lambda: self._history_walk(-1))
        QShortcut(QKeySequence(Qt.Key.Key_Down), self._in).activated.connect(
            lambda: self._history_walk(+1))

        self.setWidget(root)
        self.setMinimumHeight(240)

        # Prepare namespace.
        import numpy as _np
        ns = {'window': window, 'self': window, 'np': _np}
        try:
            import pyvista as _pv
            ns['pv'] = _pv
        except Exception:
            ns['pv'] = None
        try:
            import matplotlib.pyplot as _plt
            ns['plt'] = _plt
        except Exception:
            ns['plt'] = None
        self._ns = ns
        self._append(
            f"Ready — objects: {', '.join(sorted(ns))}\n"
            "Tips:  window._r_Q.text() · np.linspace(0,1,5) · "
            "window.combo_tpms.currentText()\n")

    # ── History nav ───────────────────────────────────────────────
    def _history_walk(self, step):
        if not self._history:
            return
        self._hist_idx = max(
            0, min(len(self._history), self._hist_idx + step))
        if self._hist_idx >= len(self._history):
            self._in.setText("")
        else:
            self._in.setText(self._history[self._hist_idx])

    # ── Execute ───────────────────────────────────────────────────
    def _on_submit(self):
        code = self._in.text()
        if not code.strip():
            return
        self._history.append(code)
        self._hist_idx = len(self._history)
        self._in.clear()
        self._append(f"\n>>> {code}\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                # Try `eval` first for expression values.
                try:
                    val = eval(code, self._ns)
                    if val is not None:
                        print(repr(val))
                except SyntaxError:
                    exec(code, self._ns)
            except Exception:
                traceback.print_exc()
        out = buf.getvalue()
        if out:
            self._append(out)
        self._out.moveCursor(QTextCursor.MoveOperation.End)

    def _append(self, text):
        self._out.moveCursor(QTextCursor.MoveOperation.End)
        self._out.insertPlainText(text)
        self._out.moveCursor(QTextCursor.MoveOperation.End)


def install_repl_dock(window):
    dock = ReplDock(window)
    window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
    dock.hide()
    window._repl_dock = dock
