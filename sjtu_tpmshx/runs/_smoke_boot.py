"""Offscreen UI-smoke boot invariants (B2 2.6, 2026-06-13).

IMPORT THIS MODULE BEFORE ANY PySide6 IMPORT: it sets
``QT_QPA_PLATFORM=offscreen`` at import time, which Qt only honours
before the platform plugin loads, and puts the package root on
``sys.path``. Window construction stays per-script — the smokes differ
deliberately in show/resize/diagnostic-print order; only these
import-order-critical lines were copy-paste invariants.
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def get_app():
    """The shared offscreen QApplication (created on first call)."""
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def patch_modals():
    """Auto-accept pipeline smoke dialogs, including instance exec calls."""
    from PySide6.QtWidgets import QMessageBox

    def _auto(*a, **k):
        print('  [dialog auto-Yes]', flush=True)
        return QMessageBox.StandardButton.Yes
    QMessageBox.question = staticmethod(_auto)
    QMessageBox.warning = staticmethod(_auto)
    QMessageBox.information = staticmethod(_auto)
    QMessageBox.exec = lambda self: (print('  [instance modal auto-Yes]',
                                           flush=True)
                                     or QMessageBox.StandardButton.Yes)
