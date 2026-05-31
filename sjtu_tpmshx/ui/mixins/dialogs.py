"""Read-only info / help dialogs for ``Main_Menu``.

Extracted from the ``main`` god object: the overview-dashboard launcher,
the test-suite info box, and the solve-log viewer. Pure presentation glue —
no solver / numeric path. Adopted via
``class Main_Menu(RunHistoryMixin, DialogsMixin, ..., QMainWindow)``; methods
resolve on the live window through the MRO, so external callers (command
palette, Ctrl+D shortcut, status-bar badge) keep working unchanged.

Host contract: ``_last_solve_log`` (str, optional), ``statusBar()``, and a
``tests/`` dir at the package root (anchored via ``_PKG_ROOT`` below, NOT via
``__file__`` — which from here would resolve to ui/mixins/, not the package
root the original main.py used).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

# tests/ lives at the package root: ui/mixins/dialogs.py -> parents[2].
_PKG_ROOT = Path(__file__).resolve().parents[2]


def _btn_styles() -> dict:
    """Resolve button stylesheets from the *current* theme at call time, so a
    dialog respects a live ``ThemeManager.rebuild()`` instead of the stale
    module-global ``_BTN_*`` snapshot the original main.py read once at import."""
    try:
        from ui.theme import _build_styles
        s = _build_styles()
        return {"tertiary": s.get("BTN_TERTIARY", ""),
                "secondary": s.get("BTN_SECONDARY", "")}
    except Exception:
        return {"tertiary": "", "secondary": ""}


class DialogsMixin:
    """Overview / test-info / solve-log modal dialogs."""

    def _show_overview(self):
        """Open the D7 overview dashboard dialog."""
        from ui.overview import open_overview
        open_overview(self)

    def _show_test_info(self):
        """Static info about the project's test suite. The count on the
        status-bar badge is hand-maintained; this dialog surfaces the file
        list for users curious about coverage."""
        import os as _os_ti
        tests_dir = str(_PKG_ROOT / 'tests')
        files = []
        try:
            for f in sorted(_os_ti.listdir(tests_dir)):
                if f.startswith('test_') and f.endswith('.py'):
                    files.append(f)
        except Exception:
            pass
        lines = [f"<b>{len(files)} test modules</b>", ""]
        for f in files:
            lines.append(f"<code>{f}</code>")
        lines.append("")
        lines.append("Run locally:")
        lines.append(
            "<code>QT_QPA_PLATFORM=offscreen pytest tests/ -q</code>")
        msg = QMessageBox(self)
        msg.setWindowTitle("Test suite")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText("<br>".join(lines))
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _show_solve_log(self):
        """Modal text viewer for the last captured solver stdout."""
        text = getattr(self, '_last_solve_log', None) or ""
        if not text.strip():
            QMessageBox.information(
                self, "Solve log",
                "No solve log captured yet — run Compute first.")
            return
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QPlainTextEdit, QPushButton, QHBoxLayout)
        dlg = QDialog(self)
        dlg.setWindowTitle("Solve log — SIMPLE / coupling output")
        dlg.resize(820, 640)
        v = QVBoxLayout(dlg)
        edit = QPlainTextEdit(text)
        edit.setReadOnly(True)
        from ui.theme import get_theme as _gt_sl
        _tsl = _gt_sl()
        edit.setStyleSheet(
            f"QPlainTextEdit{{background:{_tsl.get('surface_raised', _tsl['card_bg'])};"
            f"color:{_tsl['fg']}; border:1px solid {_tsl['card_border']};"
            f"font-family:'Fira Code','Consolas',monospace; font-size:10pt;"
            "padding:8px;}}")
        v.addWidget(edit, 1)
        btn_row = QHBoxLayout(); btn_row.addStretch(1)
        btn_copy = QPushButton("Copy all")
        btn_copy.clicked.connect(
            lambda: (QApplication.clipboard().setText(text),
                     self.statusBar().showMessage(
                         "Log copied to clipboard.", 3000)))
        btn_close = QPushButton("Close"); btn_close.clicked.connect(dlg.accept)
        _bs = _btn_styles()
        btn_copy.setStyleSheet(_bs['tertiary'])
        btn_close.setStyleSheet(_bs['secondary'])
        btn_row.addWidget(btn_copy); btn_row.addWidget(btn_close)
        v.addLayout(btn_row)
        dlg.exec()
