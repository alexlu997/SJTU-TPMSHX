"""Layout-hygiene locks (openspec ui-layout-fixes, 2026-07-03).

1. Param pages never scroll horizontally (labels word-wrap instead of
   widening the grid past the panel viewport).
2. The Fluid A/B ResponsiveRow stacks below its width threshold.
3. The canvas empty state carries the structured 3-step guidance.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QBoxLayout, QScrollArea  # noqa: E402


@pytest.fixture(scope="module")
def win():
    app = QApplication.instance() or QApplication([])
    from main import Main_Menu
    w = Main_Menu()
    w.resize(1600, 1000)
    w.show()
    app.processEvents()
    yield w
    w.close()
    app.processEvents()


def test_param_pages_have_no_horizontal_scroll(win):
    app = QApplication.instance()
    app.processEvents()
    scrolls = win.findChildren(QScrollArea)
    assert scrolls, "no scroll areas found"
    offenders = [
        s.objectName() or repr(s.widget())
        for s in scrolls
        if s.isVisible() and s.horizontalScrollBar().maximum() > 0
        and s.horizontalScrollBarPolicy().name != 'ScrollBarAlwaysOff'
    ]
    assert not offenders, f"horizontal scroll present in: {offenders}"


def test_fluids_row_is_responsive(win):
    from ui.responsive import ResponsiveRow
    assert isinstance(getattr(win, "_fluids_row", None), ResponsiveRow)


def test_responsive_row_direction_flips():
    """Standalone instance — a layout-managed widget can't be resized freely
    (the parent layout re-imposes geometry), so the flip is tested on a
    top-level ResponsiveRow."""
    from PySide6.QtWidgets import QLabel
    from ui.responsive import ResponsiveRow
    app = QApplication.instance() or QApplication([])
    row = ResponsiveRow(threshold=520)
    row.addWidget(QLabel("A"))
    row.addWidget(QLabel("B"))
    row.show()
    row.resize(400, 200)
    app.processEvents()
    assert row.direction == QBoxLayout.Direction.TopToBottom
    row.resize(800, 200)
    app.processEvents()
    assert row.direction == QBoxLayout.Direction.LeftToRight
    row.close()


def test_empty_state_has_three_steps(win):
    lbl = getattr(win, "_empty_state_label", None)
    assert lbl is not None and lbl.isVisibleTo(win)
    txt = lbl.text()
    for marker in (">1<", ">2<", ">3<", "Compute"):
        assert marker in txt, f"empty state missing {marker!r}"
