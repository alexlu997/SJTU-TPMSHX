"""Read-only info / help dialogs for ``Main_Menu``.

Extracted from the ``main`` god object: the overview-dashboard launcher and
the solve-log viewer. Pure presentation glue — no solver / numeric path.
Adopted via ``class Main_Menu(RunHistoryMixin, DialogsMixin, ..., QMainWindow)``;
methods resolve on the live window through the MRO, so external callers
(command palette, Ctrl+D shortcut) keep working unchanged.

Host contract: ``_last_solve_log`` (str, optional) and ``statusBar()``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox


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
        from ui.theme import get_theme as _gt_sl
        _tsl = _gt_sl()
        # Theme the dialog chrome too, not just the editor (else the surround
        # falls back to the parent palette and mismatches on the light theme).
        dlg.setStyleSheet(f"QDialog{{background:{_tsl['bg']};}}")
        v = QVBoxLayout(dlg)
        edit = QPlainTextEdit(text)
        edit.setReadOnly(True)
        edit.setStyleSheet(
            f"QPlainTextEdit{{background:{_tsl.get('surface_raised', _tsl['card_bg'])};"
            f"color:{_tsl['fg']}; border:1px solid {_tsl['card_border']};"
            f"font-family:'Fira Code','Consolas',monospace; font-size:10pt;"
            "padding:8px;}")
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
