"""Custom Qt item delegates for table editing.

Phase 5 follow-up: extracts ``_SelectAllDelegate`` out of ``main.py`` so
the last ``import main`` reference in ``ui_builders.py`` (zone_table
delegate) goes away. Pure Qt, no ThemeManager / FieldFactory deps.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QStyledItemDelegate


class SelectAllDelegate(QStyledItemDelegate):
    """When editing starts on a QTableWidget cell, auto-select all text so
    the user can type to replace rather than appending to the existing
    value.
    """

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if hasattr(editor, 'selectAll'):
            QTimer.singleShot(0, editor.selectAll)
        return editor
