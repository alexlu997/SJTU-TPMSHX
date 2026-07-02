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


# ── ui-ia-batch1: four workflow accordion groups ─────────────────────

_EXPECTED_GROUPS = {
    "Geometry & Structure": True,
    "Fluids": True,
    "Grid & Solver": False,
    "Boundary Details & Advanced": False,
}


def test_four_workflow_groups_with_default_states(win):
    groups = getattr(win, "_accordion_groups", {})
    assert set(groups) == set(_EXPECTED_GROUPS)
    for name, open_ in _EXPECTED_GROUPS.items():
        assert groups[name].isChecked() == open_, name


def test_left_panel_has_single_scroll_area(win):
    """Nested page scroll shells were dropped — one outer scroll only."""
    outer = win._splitter.widget(0) if hasattr(win, "_splitter") else None
    assert outer is not None
    scrolls = [s for s in outer.findChildren(QScrollArea) if s.isVisible()]
    assert len(scrolls) <= 1, [s.objectName() or repr(s) for s in scrolls]


def test_tpms_computed_collapsed_then_autoexpands(win):
    app = QApplication.instance()
    sec = win._ia_sections["tpms_computed"]
    frame = sec.layout().itemAt(1).widget()
    assert not frame.isVisible()          # starts collapsed
    assert win.compute_tpms()             # default inputs are valid
    app.processEvents()
    # group ① is open, so the expanded card becomes visible-to-window
    assert frame.isVisibleTo(win)
    assert win._v_eps.text() not in ("—", "")


def test_mode_gates_survive_group_toggle(win):
    """Expanding a collapsed group must not resurrect 3D-only widgets in
    2D mode (blanket-show + re-assert)."""
    app = QApplication.instance()
    win.combo_dim.setCurrentIndex(0)      # force 2D
    app.processEvents()
    grp = win._accordion_groups["Grid & Solver"]
    grp.setChecked(True)
    app.processEvents()
    assert not win.le_Nz.isVisibleTo(win), "3D-only Nz visible in 2D mode"
    grp.setChecked(False)
    app.processEvents()
