"""Bookmarks dock — star-list of saved configurations on a right-side
dock. Backed by the same `_user_presets.json` the preset combo uses, so
every bookmark automatically appears in the preset dropdown too.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QInputDialog, QMessageBox,
)

from .theme import get_theme


class BookmarksDock(QDockWidget):
    def __init__(self, window):
        super().__init__("Bookmarks", window)
        self.setObjectName("Bookmarks")
        self._w = window
        self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea
                             | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable
                         | QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)

        t = get_theme()
        root = QWidget()
        root.setStyleSheet(
            f"background:{t.get('surface_raised', t['card_bg'])};"
            f"color:{t['fg']};"
            f"border-left:1px solid {t.get('border_subtle', t['card_border'])};")
        v = QVBoxLayout(root)
        v.setContentsMargins(12, 10, 12, 10); v.setSpacing(8)

        hdr = QLabel("★ BOOKMARKS")
        hdr.setStyleSheet(
            f"color:{t.get('sub_fg', t['fg'])}; font-size:8pt; font-weight:700;"
            "letter-spacing:1.4px; background:transparent; border:none;")
        v.addWidget(hdr)

        self._list = QListWidget()
        self._list.setStyleSheet(
            f"QListWidget{{background:{t.get('surface_elevated', t['card_bg'])};"
            f"color:{t['fg']}; border:1px solid {t.get('border_subtle', t['card_border'])};"
            "border-radius:6px; padding:4px; font-size:10pt;}"
            "QListWidget::item{padding:6px 8px; border-radius:4px;}"
            f"QListWidget::item:selected{{"
            f"background:{t.get('accent_primary', '#3B82F6')}; color:white;}}"
            f"QListWidget::item:hover{{background:{t.get('btn_sec_hover_bg', 'rgba(59,130,246,0.12)')};}}")
        self._list.setMinimumHeight(220)
        self._list.itemDoubleClicked.connect(self._load_selected)
        v.addWidget(self._list, 1)

        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        import main as _m
        btn_save = QPushButton("★  Save current")
        btn_load = QPushButton("↥ Load")
        btn_del  = QPushButton("✕ Delete")
        for b in (btn_save, btn_load, btn_del):
            b.setFixedHeight(28)
        btn_save.setStyleSheet(_m._BTN_PRIMARY)
        btn_load.setStyleSheet(_m._BTN_SECONDARY)
        btn_del.setStyleSheet(_m._BTN_TERTIARY)
        btn_save.clicked.connect(self._save_current)
        btn_load.clicked.connect(self._load_selected)
        btn_del.clicked.connect(self._delete_selected)
        btn_row.addWidget(btn_save, 1)
        btn_row.addWidget(btn_load)
        btn_row.addWidget(btn_del)
        v.addLayout(btn_row)

        self.setWidget(root)
        self.setMinimumWidth(280)
        self.refresh()

    def refresh(self):
        self._list.clear()
        presets = self._w._load_user_presets()
        for p in presets:
            name = p.get('name', '(unnamed)')
            item = QListWidgetItem(f"★  {name}")
            item.setData(Qt.ItemDataRole.UserRole, p)
            self._list.addItem(item)
        if not presets:
            hint = QListWidgetItem("(no bookmarks yet)")
            hint.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._list.addItem(hint)

    def _save_current(self):
        name, ok = QInputDialog.getText(
            self, "Save bookmark", "Name:")
        if not ok or not name.strip():
            return
        payload = self._w._capture_current_preset(name.strip())
        presets = self._w._load_user_presets()
        # Replace existing with same name.
        presets = [p for p in presets if p.get('name') != name.strip()]
        presets.append(payload)
        self._w._save_user_presets(presets)
        if hasattr(self._w, '_rebuild_preset_combo'):
            self._w._rebuild_preset_combo()
        self.refresh()
        self._w.statusBar().showMessage(
            f"Bookmark saved: {name.strip()}", 4000)

    def _load_selected(self, _item=None):
        item = self._list.currentItem()
        if item is None:
            return
        preset = item.data(Qt.ItemDataRole.UserRole)
        if preset is None:
            return
        self._w._apply_user_preset(preset)
        self._w.statusBar().showMessage(
            f"Bookmark loaded: {preset.get('name', '?')}", 4000)

    def _delete_selected(self):
        item = self._list.currentItem()
        if item is None:
            return
        preset = item.data(Qt.ItemDataRole.UserRole)
        if preset is None:
            return
        confirm = QMessageBox.question(
            self, "Delete bookmark",
            f"Remove bookmark '{preset.get('name', '?')}'?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        presets = self._w._load_user_presets()
        presets = [p for p in presets if p.get('name') != preset.get('name')]
        self._w._save_user_presets(presets)
        if hasattr(self._w, '_rebuild_preset_combo'):
            self._w._rebuild_preset_combo()
        self.refresh()


def install_bookmarks(window):
    dock = BookmarksDock(window)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    dock.hide()
    window._bookmarks_dock = dock
