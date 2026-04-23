"""Floating parameter search bar (Ctrl+F).

Scans every session-persisted QLineEdit on the left panel and highlights
those whose attr name, accessible-name, or tooltip contains the query.
Enter jumps to the first match; Esc resets and closes.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QLabel, QPushButton, QApplication,
)

from .theme import get_theme


class ParamSearch(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._attrs = list(getattr(window, '_SESSION_LINE_EDITS', ()))
        self._matches: list[str] = []

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.hide()

        t = get_theme()
        _surface = t.get('surface_elevated', t['card_bg'])
        _border = t.get('border_strong', t['card_border'])
        _sub = t.get('sub_fg', t['fg'])
        self.setStyleSheet(
            f"QWidget#paramSearchBar{{background:{_surface};"
            f"border:1px solid {_border}; border-radius:10px;}}")
        self.setObjectName("paramSearchBar")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 8, 8); lay.setSpacing(8)

        icon = QLabel("⌕")
        icon.setStyleSheet(
            f"color:{t.get('accent_primary', '#3B82F6')};"
            "font-size:14pt; font-weight:800; background:transparent;"
            "border:none; padding:0;")
        lay.addWidget(icon)

        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "Filter parameters by name, unit, or description…")
        self._input.setStyleSheet(
            f"QLineEdit{{background:transparent;"
            f"color:{t['fg']}; border:none;"
            f"font-size:11pt; font-weight:500;"
            f"font-family:'Fira Sans','Inter','Segoe UI',sans-serif;}}"
            f"QLineEdit:focus{{outline:none;}}")
        lay.addWidget(self._input, 1)

        self._count = QLabel("")
        self._count.setStyleSheet(
            f"color:{_sub}; font-size:9pt; font-family:'Fira Code',monospace;"
            "background:transparent; border:none; padding:0 8px;")
        lay.addWidget(self._count)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 26)
        btn_close.setStyleSheet(
            f"QPushButton{{background:transparent;"
            f"color:{_sub}; border:none; border-radius:4px;"
            f"font-size:10pt;}}"
            f"QPushButton:hover{{background:{t.get('scroll_bg', '#eee')};}}")
        btn_close.setToolTip("Close search (Esc)")
        btn_close.clicked.connect(self.close_search)
        lay.addWidget(btn_close)

        self._input.textChanged.connect(self._on_query)
        self._input.returnPressed.connect(self._jump_first)

        # Global shortcuts scoped to the window
        self._sh_open = QShortcut(QKeySequence("Ctrl+F"), window)
        self._sh_open.activated.connect(self.open_search)
        self._sh_esc = QShortcut(
            QKeySequence(Qt.Key.Key_Escape), self._input)
        self._sh_esc.activated.connect(self.close_search)

    # ── Public ──────────────────────────────────────────────────────
    def open_search(self):
        self._reposition()
        self.show()
        self.raise_()
        self._input.setFocus()
        self._input.selectAll()

    def close_search(self):
        self.hide()
        self._input.clear()
        self._clear_highlights()

    # ── Positioning ────────────────────────────────────────────────
    def _reposition(self):
        """Anchor the search bar near the top of the left-panel scroll
        area so it hovers inside the param region rather than at the
        window edge."""
        host = None
        # The splitter's first widget is the left-panel scroll container.
        sp = getattr(self._window, '_splitter', None)
        if sp is not None:
            host = sp.widget(0)
        if host is None:
            host = self._window.centralWidget()
        if host is None:
            return
        # Map host top-left into our parent (window) coords.
        top_left = host.mapTo(self._window, QPoint(0, 0))
        pad = 10
        w = max(360, host.width() - 2 * pad)
        self.setFixedWidth(min(w, 520))
        self.move(top_left.x() + pad, top_left.y() + pad)

    # ── Filtering ──────────────────────────────────────────────────
    def _on_query(self, text):
        q = text.strip().lower()
        self._clear_highlights()
        if not q:
            self._count.setText("")
            return
        matches: list[str] = []
        for attr in self._attrs:
            le = getattr(self._window, attr, None)
            if le is None:
                continue
            hay = (
                attr.lower() + " "
                + (le.accessibleName() or "").lower() + " "
                + (le.accessibleDescription() or "").lower() + " "
                + (le.toolTip() or "").lower()
            )
            if q in hay:
                matches.append(attr)
                le.setProperty('searchMatch', 'true')
                le.style().unpolish(le); le.style().polish(le)
        self._matches = matches
        self._count.setText(f"{len(matches)} match"
                             + ("" if len(matches) == 1 else "es"))

    def _clear_highlights(self):
        for attr in self._attrs:
            le = getattr(self._window, attr, None)
            if le is None:
                continue
            if le.property('searchMatch'):
                le.setProperty('searchMatch', None)
                le.style().unpolish(le); le.style().polish(le)
        self._matches = []

    def _jump_first(self):
        if not self._matches:
            return
        le = getattr(self._window, self._matches[0], None)
        if le is None:
            return
        # Scroll into view by asking the left-panel scroll area.
        sp = getattr(self._window, '_splitter', None)
        if sp is not None:
            host = sp.widget(0)
            # Walk ancestors to find QScrollArea child.
            from PySide6.QtWidgets import QScrollArea
            for sa in host.findChildren(QScrollArea):
                if sa.isAncestorOf(le):
                    sa.ensureWidgetVisible(le, 0, 50)
                    break
        le.setFocus()
        le.selectAll()


def install_param_search(window):
    bar = ParamSearch(window)
    window._param_search = bar
