"""responsive.py — width-aware layout containers (ui-layout-fixes, 2026-07-03).

Qt has no CSS-style container queries; ``ResponsiveRow`` is the minimal
deterministic substitute: a QWidget whose QBoxLayout flips between
side-by-side (LeftToRight) and stacked (TopToBottom) at a width threshold,
driven by ``resizeEvent``. Used for the Fluid A / Fluid B card pair, whose
hard QHBoxLayout used to clip both cards on narrow panels
(builders_fluids.py had promised this "resize-to-stack responsive pass").
"""
from __future__ import annotations

from PySide6.QtWidgets import QBoxLayout, QWidget


class ResponsiveRow(QWidget):
    """Two-or-more children side by side when wide, stacked when narrow.

    ``threshold``: available width (px) below which children stack.
    The flip is idempotent (direction only set when it changes), so
    repeated resize events are cheap and never thrash the layout.
    """

    def __init__(self, threshold: int = 520, spacing: int = 10,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._threshold = int(threshold)
        self.setStyleSheet("background:transparent;")
        self._lay = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(spacing)

    def layout(self):  # noqa: D102 — QWidget override, returns the box layout
        return self._lay

    def addWidget(self, w: QWidget) -> None:
        self._lay.addWidget(w)

    @property
    def direction(self) -> QBoxLayout.Direction:
        return self._lay.direction()

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt override
        want = (QBoxLayout.Direction.TopToBottom
                if event.size().width() < self._threshold
                else QBoxLayout.Direction.LeftToRight)
        if self._lay.direction() != want:
            self._lay.setDirection(want)
        super().resizeEvent(event)
