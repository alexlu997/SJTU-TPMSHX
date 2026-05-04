"""Skeleton shimmer placeholder — shown in canvases that don't have data yet.

Beats an empty axes frame or a blank canvas by signalling "this area is ready,
just waiting on a compute". Inspired by Grafana / Linear / Figma skeletons.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPainter, QColor, QBrush, QLinearGradient, QPen
from PySide6.QtWidgets import QWidget

from .theme import get_theme


class Skeleton(QWidget):
    """Shimmer placeholder with stylised axes + legend blocks.

    Animates a highlight band left→right at ~40 FPS while visible; stops
    the timer on hide so idle tabs cost nothing. `kind` chooses the layout:
      'pareto' — scatter axes + legend row
      '3d'     — a cube wireframe + floor + side bars
    """

    def __init__(self, kind='pareto', parent=None):
        super().__init__(parent)
        self._kind = kind
        self._phase = 0.0
        self._should_run = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def start(self):
        self._should_run = True
        if not self._timer.isActive() and self.isVisible():
            # 14 ms ≈ 70 Hz — buttery on a 144 Hz display without burning
            # CPU when the user's not looking at the skeleton tab.
            self._timer.start(14)
        self.show()
        self.raise_()
        self._sync_timer()

    def stop(self):
        self._should_run = False
        self._timer.stop()
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _sync_timer(self):
        if self._should_run and self.isVisible():
            if not self._timer.isActive():
                # 14 ms ~= 70 Hz; only run while the parent card is visible.
                self._timer.start(14)
        else:
            self._timer.stop()

    def _tick(self):
        self._phase = (self._phase + 0.015) % 1.2
        self.update()

    def paintEvent(self, event):
        t = get_theme()
        _base = QColor(t.get('surface_raised', t['card_bg']))
        _edge = QColor(t.get('border_subtle', t['card_border']))
        _accent = QColor(t.get('accent_primary', '#3B82F6'))

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        if w < 40 or h < 40:
            p.end(); return

        def _block(x, y, bw, bh, radius=6, alpha=255):
            col = QColor(_base); col.setAlpha(alpha)
            p.fillRect(QRect(int(x), int(y), int(bw), int(bh)), col)

        # Draw the structural blocks based on kind
        if self._kind == 'pareto':
            # Title row + sub row
            _block(40, 40, w * 0.25, 20, alpha=200)
            _block(40, 68, w * 0.15, 14, alpha=140)
            # Axes area
            ax_x = 80; ax_y = 110
            ax_w = w - 160; ax_h = h - 200
            _block(ax_x, ax_y, ax_w, ax_h, radius=8, alpha=180)
            # Legend strip bottom
            _block(40, h - 60, w * 0.45, 18, alpha=150)
            # Colour bar sliver right
            _block(w - 60, ax_y, 20, ax_h, alpha=200)
        else:  # 3d
            # Outline wireframe cube
            pen = QPen(_edge); pen.setWidthF(1.2)
            p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
            cx, cy = w / 2, h / 2
            s = min(w, h) * 0.42
            dx, dy = s * 0.25, -s * 0.16
            front = QRect(int(cx - s/2), int(cy - s/2), int(s), int(s))
            back_x = int(cx - s/2 + dx); back_y = int(cy - s/2 + dy)
            back = QRect(back_x, back_y, int(s), int(s))
            p.drawRect(front); p.drawRect(back)
            # Connect corners
            for (fx, fy), (bx, by) in (
                    (front.topLeft().toTuple(), back.topLeft().toTuple()),
                    (front.topRight().toTuple(), back.topRight().toTuple()),
                    (front.bottomLeft().toTuple(), back.bottomLeft().toTuple()),
                    (front.bottomRight().toTuple(), back.bottomRight().toTuple())):
                p.drawLine(fx, fy, bx, by)
            # Caption strip
            _block(40, h - 60, w * 0.35, 18, alpha=160)

        # Shimmer sweep — a diagonal gradient that moves phase → 1 across width
        shimmer_x = int(-w * 0.3 + self._phase * (w * 1.3))
        band_w = int(w * 0.30)
        grad = QLinearGradient(shimmer_x, 0, shimmer_x + band_w, 0)
        trans = QColor(_accent); trans.setAlpha(0)
        mid = QColor(_accent); mid.setAlpha(38)
        grad.setColorAt(0.0, trans)
        grad.setColorAt(0.5, mid)
        grad.setColorAt(1.0, trans)
        p.fillRect(self.rect(), QBrush(grad))

        # Caption hint text
        msg = ("Pareto scatter will appear here after NSGA-II finishes."
               if self._kind == 'pareto' else
               "Volumetric view loads after the first 3D compute.")
        pen = QPen(QColor(t.get('sub_fg', '#94A3B8')))
        p.setPen(pen)
        f = p.font(); f.setPointSize(9); f.setItalic(True); p.setFont(f)
        p.drawText(QRect(40, h - 32, w - 80, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   msg)

        p.end()
