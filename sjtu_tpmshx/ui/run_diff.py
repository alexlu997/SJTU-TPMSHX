"""Run-diff modal — side-by-side compare of two recent compute runs.

Shows parameter-level changes + KPI deltas so users can answer
"what did I change between run #1 and #2?" without mental bookkeeping.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QWidget, QFrame,
)

from .theme import get_theme


def _parse_number(s):
    if s is None:
        return None
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def _fmt_delta_pct(old_v, new_v):
    if old_v is None or new_v is None:
        return "—", 'neutral'
    if abs(old_v) < 1e-12:
        return "—", 'neutral'
    pct = (new_v - old_v) / abs(old_v) * 100.0
    if abs(pct) < 1e-3:
        return "·0%", 'neutral'
    arrow = '↑' if pct > 0 else '↓'
    return f"{arrow}{abs(pct):.2f}%", ('up' if pct > 0 else 'down')


class RunDiffDialog(QDialog):
    """Compare two entries from the _recent_runs ring buffer."""

    def __init__(self, window, newer, older):
        super().__init__(window)
        self._window = window
        self.setWindowTitle("Compare recent runs")
        self.resize(860, 640)

        t = get_theme()
        _surface = t.get('surface_raised', t['card_bg'])
        _elev = t.get('surface_elevated', t['card_bg'])
        _border = t.get('border_subtle', t['card_border'])
        _sub = t.get('sub_fg', t['fg'])
        _mono = "'Fira Code','JetBrains Mono','Consolas',monospace"

        self.setStyleSheet(
            f"QDialog{{background:{_surface}; color:{t['fg']};}}")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # Header: timestamps + role labels
        hdr = QHBoxLayout(); hdr.setSpacing(18)
        def _stamp(label, entry):
            col = QVBoxLayout(); col.setSpacing(2)
            cap = QLabel(label)
            cap.setStyleSheet(
                f"color:{_sub}; font-size:8pt; font-weight:700;"
                "letter-spacing:1.4px; background:transparent; border:none;")
            val = QLabel(entry.get('ts') or entry.get('label') or '—')
            val.setStyleSheet(
                f"color:{t['fg']}; font-family:{_mono};"
                "font-size:11pt; font-weight:700; background:transparent;"
                "border:none;")
            col.addWidget(cap); col.addWidget(val)
            host = QWidget(); host.setLayout(col)
            return host
        hdr.addWidget(_stamp("NEWER (A)", newer))
        arrow = QLabel("⇆")
        arrow.setStyleSheet(
            f"color:{t.get('accent_primary', '#3B82F6')};"
            "font-size:20pt; font-weight:600; background:transparent;"
            "border:none; padding:0 12px;")
        hdr.addWidget(arrow, 0, Qt.AlignmentFlag.AlignVCenter)
        hdr.addWidget(_stamp("OLDER (B)", older))
        hdr.addStretch(1)
        root.addLayout(hdr)

        # KPI delta row
        kpi_row = QHBoxLayout(); kpi_row.setSpacing(10)
        def _kpi_card(label, new_v, old_v, better_dir):
            nf = _parse_number(new_v); of = _parse_number(old_v)
            pct_txt, direction = _fmt_delta_pct(of, nf)
            good = (better_dir == 'up' and direction == 'up') or \
                   (better_dir == 'down' and direction == 'down')
            col_ok = t.get('accent_green', '#22C55E')
            col_bad = '#F87171'
            col_neu = _sub
            col = col_ok if (direction != 'neutral' and good) else (
                col_bad if direction != 'neutral' else col_neu)
            card = QFrame()
            card.setStyleSheet(
                f"QFrame{{background:{_elev}; border:1px solid {_border};"
                "border-radius:10px;}}")
            card.setFixedHeight(94)
            card.setMinimumWidth(180)
            v = QVBoxLayout(card)
            v.setContentsMargins(14, 10, 14, 10); v.setSpacing(2)
            cap = QLabel(label)
            cap.setStyleSheet(
                f"color:{_sub}; font-size:8pt; font-weight:700;"
                "letter-spacing:1.4px; background:transparent; border:none;")
            val = QLabel(
                f"A = {new_v or '—'}   B = {old_v or '—'}")
            val.setStyleSheet(
                f"color:{t['fg']}; font-family:{_mono};"
                "font-size:10pt; font-weight:700; background:transparent;"
                "border:none;")
            delta = QLabel(pct_txt)
            delta.setStyleSheet(
                f"color:{col}; font-family:{_mono};"
                "font-size:16pt; font-weight:800; background:transparent;"
                "border:none;")
            v.addWidget(cap); v.addWidget(val); v.addWidget(delta)
            return card

        kpi_row.addWidget(_kpi_card(
            "Q  [W/m]", newer.get('Q'), older.get('Q'), 'up'))
        kpi_row.addWidget(_kpi_card(
            "ΔP_A [Pa]", newer.get('dP_A'), older.get('dP_A'), 'down'))
        kpi_row.addWidget(_kpi_card(
            "ΔP_B [Pa]", newer.get('dP_B'), older.get('dP_B'), 'down'))
        kpi_row.addStretch(1)
        root.addLayout(kpi_row)

        # Parameter diff table
        lbl = QLabel("Parameter diff")
        lbl.setStyleSheet(
            f"color:{_sub}; font-size:8pt; font-weight:700;"
            "letter-spacing:1.4px; background:transparent; border:none;"
            "padding-top:6px;")
        root.addWidget(lbl)

        self._build_param_table(window, newer, older, t, _elev, _border,
                                  _sub, _mono)
        root.addWidget(self._table, 1)

        # Footer buttons
        ftr = QHBoxLayout(); ftr.addStretch(1)
        btn_use_a = QPushButton("Load A into inputs")
        btn_use_b = QPushButton("Load B into inputs")
        btn_close = QPushButton("Close")
        for btn in (btn_use_a, btn_use_b, btn_close):
            btn.setFixedHeight(32)
            btn.setMinimumWidth(140)
        import main as _m
        btn_use_a.setStyleSheet(_m._BTN_SECONDARY)
        btn_use_b.setStyleSheet(_m._BTN_SECONDARY)
        btn_close.setStyleSheet(_m._BTN_TERTIARY)
        btn_use_a.clicked.connect(
            lambda: self._load_into_inputs(newer))
        btn_use_b.clicked.connect(
            lambda: self._load_into_inputs(older))
        btn_close.clicked.connect(self.accept)
        ftr.addWidget(btn_use_a)
        ftr.addWidget(btn_use_b)
        ftr.addWidget(btn_close)
        root.addLayout(ftr)

    def _build_param_table(self, window, newer, older, t, elev, border,
                             sub, mono):
        table = QTableWidget()
        self._table = table
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(
            ["Parameter", "A (newer)", "B (older)", "Δ"])
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setStyleSheet(
            f"QTableWidget{{background:{t['card_bg']}; color:{t['fg']};"
            f"alternate-background-color:{elev};"
            f"border:1px solid {border}; border-radius:6px;"
            "gridline-color:transparent;}}"
            f"QHeaderView::section{{background:transparent; color:{sub};"
            "font-size:9pt; font-weight:700; letter-spacing:1.1px;"
            "padding:8px 6px; border:none;"
            f"border-bottom:2px solid {t.get('accent_primary', '#3B82F6')};}}"
            f"QTableWidget::item{{padding:6px 10px; font-family:{mono};}}"
        )

        # Merge all param keys across both presets, stable sorted.
        n_le = (newer.get('preset') or {}).get('line_edits') or {}
        o_le = (older.get('preset') or {}).get('line_edits') or {}
        n_co = (newer.get('preset') or {}).get('combos') or {}
        o_co = (older.get('preset') or {}).get('combos') or {}
        n_ch = (newer.get('preset') or {}).get('checks') or {}
        o_ch = (older.get('preset') or {}).get('checks') or {}

        rows = []
        for k in sorted(set(n_le) | set(o_le)):
            rows.append((k, n_le.get(k, '—'), o_le.get(k, '—'), 'num'))
        for k in sorted(set(n_co) | set(o_co)):
            rows.append((k, n_co.get(k, '—'), o_co.get(k, '—'), 'idx'))
        for k in sorted(set(n_ch) | set(o_ch)):
            rows.append((k, n_ch.get(k, '—'), o_ch.get(k, '—'), 'bool'))

        table.setRowCount(len(rows))
        _changed = QColor(t.get('accent_primary', '#3B82F6'))
        _changed.setAlpha(36)
        _up = QColor(t.get('accent_green', '#22C55E'))
        _down = QColor('#F87171')
        for r, (key, a, b, kind) in enumerate(rows):
            same = str(a) == str(b)
            item_k = QTableWidgetItem(key)
            item_a = QTableWidgetItem(str(a))
            item_b = QTableWidgetItem(str(b))
            delta_text = ""
            delta_color = None
            if kind == 'num' and not same:
                af = _parse_number(a); bf = _parse_number(b)
                if af is not None and bf is not None:
                    txt, dire = _fmt_delta_pct(bf, af)  # A vs B
                    delta_text = txt
                    if dire == 'up':
                        delta_color = _up
                    elif dire == 'down':
                        delta_color = _down
            elif not same:
                delta_text = "≠"
                delta_color = QColor(t.get('accent_primary', '#3B82F6'))
            item_d = QTableWidgetItem(delta_text)
            if delta_color is not None:
                item_d.setForeground(QBrush(delta_color))
                item_d.setFont(_bold_font(item_d.font()))
            if not same:
                for it in (item_k, item_a, item_b, item_d):
                    it.setBackground(QBrush(_changed))
            for col, it in enumerate((item_k, item_a, item_b, item_d)):
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(r, col, it)

    def _load_into_inputs(self, entry):
        preset = entry.get('preset') or {}
        self._window._apply_user_preset(preset)
        self._window.statusBar().showMessage(
            "Inputs restored from diff view — click Compute to recompute.",
            5000)
        self.accept()


def _bold_font(base):
    f = base
    f.setBold(True)
    return f


def open_diff_of_recent(window):
    """Open diff of _recent_runs[0] vs _recent_runs[1]. Requires ≥ 2
    entries; otherwise surfaces a friendly message."""
    recents = list(getattr(window, '_recent_runs', []) or [])
    if len(recents) < 2:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            window, "Compare runs",
            "Need at least two recent runs to compare.\n"
            "Run Compute twice then try again.")
        return
    dlg = RunDiffDialog(window, recents[0], recents[1])
    dlg.exec()
