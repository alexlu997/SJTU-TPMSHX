"""Quick-sliders dock — pull-to-right dock with slider+number combo for
the most-swept parameters (L_cell, t, u_A). Complements the left panel
inputs without disrupting their layout."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QLineEdit, QFrame,
)

from .theme import get_theme


# (attr, label, unit, min, max, step, scale factor)
_SLIDER_FIELDS = [
    ('le_Lcell', 'TPMS cell L',      'mm',  4.0,   8.0,  0.1, 10),
    ('le_t',    'Wall thickness t', 'mm',  0.3,   0.8,  0.01, 100),
    ('le_uA',   'Fluid A velocity', 'm/s', 0.1,  30.0,  0.1, 10),
    ('le_uB',   'Fluid B velocity', 'm/s', 0.01,  5.0,  0.01, 100),
]


class QuickSliders(QDockWidget):
    def __init__(self, window):
        super().__init__("Quick sliders", window)
        self.setObjectName("QuickSliders")
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
        v.setContentsMargins(14, 12, 14, 12); v.setSpacing(12)

        hdr = QLabel("QUICK SLIDERS")
        hdr.setStyleSheet(
            f"color:{t.get('sub_fg', t['fg'])}; font-size:8pt; font-weight:700;"
            "letter-spacing:1.4px; background:transparent; border:none;")
        v.addWidget(hdr)

        for attr, label, unit, lo, hi, step, scale in _SLIDER_FIELDS:
            self._build_row(v, attr, label, unit, lo, hi, step, scale, t)

        v.addStretch(1)
        self.setWidget(root)
        self.setMinimumWidth(280)

    def _build_row(self, parent_lay, attr, label, unit, lo, hi, step,
                     scale, t):
        le = getattr(self._w, attr, None)
        if le is None:
            return
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:transparent;"
            f"border:1px solid {t.get('border_subtle', t['card_border'])};"
            "border-radius:8px; padding:4px;}")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 8, 10, 8); cl.setSpacing(4)

        cap = QLabel(f"{label}  [{unit}]")
        cap.setStyleSheet(
            f"color:{t['fg']}; font-size:9pt; font-weight:600;"
            "background:transparent; border:none;")
        cl.addWidget(cap)

        row = QHBoxLayout(); row.setSpacing(8)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(int(lo * scale))
        slider.setMaximum(int(hi * scale))
        val_label = QLabel(le.text())
        val_label.setFixedWidth(64)
        val_label.setAlignment(Qt.AlignmentFlag.AlignRight
                                | Qt.AlignmentFlag.AlignVCenter)
        val_label.setStyleSheet(
            f"color:{t['fg']}; font-family:'Fira Code',monospace;"
            "font-size:10pt; font-weight:700;"
            "background:transparent; border:none;")

        # Sync: slider → LineEdit + label
        def _on_slider(v, _le=le, _lbl=val_label, _s=scale):
            real = v / _s
            txt = f"{real:.3g}"
            _le.setText(txt)
            _lbl.setText(txt)

        # Sync LineEdit → slider on editingFinished. If user types a value
        # outside the slider bounds, clamp the slider visually but DO NOT
        # rewrite the LineEdit (avoids the silent-clamp drift bug — typed
        # 0.05 m/s would otherwise lose information when slider min is 0.1).
        # Show the real value in the label with a leading "!" marker so the
        # mismatch is visible.
        def _on_edit(_le=le, _sl=slider, _lbl=val_label, _lo=lo, _hi=hi,
                      _s=scale):
            try:
                v = float(_le.text())
            except ValueError:
                return
            if v < _lo or v > _hi:
                # Out of slider range — clamp slider, mark label, keep LE.
                v_clamp = max(_lo, min(_hi, v))
                _sl.blockSignals(True)
                _sl.setValue(int(v_clamp * _s))
                _sl.blockSignals(False)
                _lbl.setText(f"!{v:.3g}")
                _lbl.setToolTip(
                    f"Value {v:.3g} is outside the slider range "
                    f"[{_lo}, {_hi}]. The slider is pinned at its limit; the "
                    f"line-edit retains the typed value.")
            else:
                _sl.blockSignals(True)
                _sl.setValue(int(v * _s))
                _sl.blockSignals(False)
                _lbl.setText(f"{v:.3g}")
                _lbl.setToolTip("")

        slider.valueChanged.connect(_on_slider)
        le.editingFinished.connect(_on_edit)
        # Seed slider from current field value.
        try:
            v = float(le.text())
            slider.setValue(int(max(lo, min(hi, v)) * scale))
        except Exception:
            slider.setValue(int((lo + hi) / 2 * scale))

        _on_edit()
        slider.setStyleSheet(
            f"QSlider::groove:horizontal{{background:{t.get('slider_groove', '#aaa')};"
            "height:4px; border-radius:2px;}"
            f"QSlider::handle:horizontal{{background:{t.get('slider_handle', '#3B82F6')};"
            "width:16px; height:16px; margin:-6px 0; border-radius:8px;}"
            f"QSlider::sub-page:horizontal{{background:{t.get('slider_sub', '#3B82F6')};"
            "border-radius:2px;}")

        row.addWidget(slider, 1)
        row.addWidget(val_label, 0)
        cl.addLayout(row)
        parent_lay.addWidget(card)


def install_quick_sliders(window):
    dock = QuickSliders(window)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    dock.hide()
    window._quick_sliders_dock = dock
