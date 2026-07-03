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


def test_empty_state_has_three_steps_and_preset(win):
    from PySide6.QtWidgets import QLabel
    box = getattr(win, "_empty_state_label", None)   # container since batch2
    assert box is not None and box.isVisibleTo(win)
    txt = " ".join(l.text() for l in box.findChildren(QLabel))
    for marker in (">1<", ">2<", ">3<", "计算"):
        assert marker in txt, f"empty state missing {marker!r}"
    btn = getattr(win, "_empty_state_preset_btn", None)
    assert btn is not None and btn.isVisibleTo(win)


def test_empty_state_preset_button_applies_shanghai(win):
    app = QApplication.instance()
    win._empty_state_preset_btn.click()
    app.processEvents()
    assert getattr(win, "_active_preset_name", None) == "Shanghai (3D Gyroid)"


def test_sticky_cta_outside_scroll(win):
    """btn_compute lives in the fixed bottom bar, not inside the scroll —
    it stays visible however far the params scroll."""
    from PySide6.QtWidgets import QScrollArea
    assert win.btn_compute.isVisibleTo(win)
    p = win.btn_compute.parentWidget()
    inside_scroll = False
    while p is not None:
        if isinstance(p, QScrollArea):
            inside_scroll = True
            break
        p = p.parentWidget()
    assert not inside_scroll
    assert getattr(win, "_cta_bar", None) is not None


# ── ui-ia-batch1: four workflow accordion groups ─────────────────────

_EXPECTED_GROUPS = {
    "几何与结构": True,
    "流体": True,
    "网格与求解器": False,
    "边界细节与高级": False,
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


def test_group_badge_counts_empty_field(win):
    """ui-batch3 IA-4: clearing a field inside a collapsed group surfaces
    a ⚠N badge in that group's title; fixing it clears the badge."""
    from ui.ui_builders import refresh_group_badges
    grp = win._accordion_groups["网格与求解器"]
    old = win.le_Nx.text()
    win.le_Nx.setText("")
    refresh_group_badges(win)
    assert "⚠" in grp.title(), grp.title()
    assert win._group_badge_counts["网格与求解器"] >= 1
    win.le_Nx.setText(old or "40")
    refresh_group_badges(win)
    assert "⚠" not in grp.title(), grp.title()


def test_group_badge_updates_via_validator_debounce(win):
    """End-to-end: editingFinished → validator cb → debounce timer →
    badge repaint, without calling refresh directly. Uses le_L — it has a
    validator handler attached (positive+unit field); le_Nx does not."""
    import time
    app = QApplication.instance()
    grp = win._accordion_groups["几何与结构"]
    old = win.le_L.text()
    win.le_L.setText("")
    win.le_L.editingFinished.emit()
    deadline = time.monotonic() + 2.0
    while "⚠" not in grp.title() and time.monotonic() < deadline:
        app.processEvents()
    assert "⚠" in grp.title(), grp.title()
    win.le_L.setText(old or "0.182")
    win.le_L.editingFinished.emit()
    deadline = time.monotonic() + 2.0
    while "⚠" in grp.title() and time.monotonic() < deadline:
        app.processEvents()
    assert "⚠" not in grp.title(), grp.title()


def test_group_badge_survives_toggle(win):
    from ui.ui_builders import refresh_group_badges
    grp = win._accordion_groups["网格与求解器"]
    old = win.le_Nx.text()
    win.le_Nx.setText("")
    refresh_group_badges(win)
    assert "⚠" in grp.title()
    grp.setChecked(True)     # expand — toggle handler re-renders title
    assert "⚠" in grp.title(), "badge wiped by expand"
    grp.setChecked(False)
    assert "⚠" in grp.title(), "badge wiped by collapse"
    win.le_Nx.setText(old or "40")
    refresh_group_badges(win)


def test_2d_field_segment_drives_combo(win):
    """ui-batch4 ③: the 温度/速度/压力 segmented buttons drive the hidden
    combo (state source); reverse-sync repaints the buttons."""
    btns = getattr(win, "_2d_field_btns", None)
    assert btns and len(btns) == 3
    assert not win.combo_2d_field.isVisible()   # demoted to state source
    win._2d_field_seg.setEnabled(True)
    btns[2].click()                             # 压力
    assert win.combo_2d_field.currentIndex() == 2
    assert win._resolve_2d_view_card() == 'pres'
    win.combo_2d_field.setCurrentIndex(0)       # reverse path
    assert win._resolve_2d_view_card() == 'temp'


def test_copy_figure_clipboard_no_data_safe(win):
    """No drawn canvas → status message, no exception, clipboard untouched."""
    win._active_tab = 'layout'
    win._drawn_tabs = set()
    win._copy_figure_clipboard()                # must not raise


# ── ui-plan3a: design-token discipline ───────────────────────────────

_UI_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "ui")

# Micro-controls whose radius is proportional to the element (sliders,
# checkbox indicators, progress chunks, scrollbar handles) and semantic
# pills/toasts are exempt — see theme.py radius policy comment.
_RADIUS_EXEMPT_FILES = {"panel_vis_3d.py", "theme.py"}


def _ui_sources():
    import glob
    for p in (glob.glob(os.path.join(_UI_DIR, "*.py"))
              + glob.glob(os.path.join(_UI_DIR, "mixins", "*.py"))):
        yield p, open(p, encoding="utf-8").read()


def test_no_stray_card_radii():
    """Card/control-level radii are 6px; 8/10/12px strays are regressions.
    Pills (14/18) and micro-controls (1-3px on tiny elements) are exempt."""
    import re
    bad = []
    for p, src in _ui_sources():
        name = os.path.basename(p)
        if name in _RADIUS_EXEMPT_FILES:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            m = re.search(r"border-radius:\s*(8|10|12)px", line)
            # builders_canvas pill badge (padding 5px 14px chip) is the one
            # sanctioned 12px pill outside the exempt files.
            if m and "padding:5px 14px" not in line:
                bad.append(f"{name}:{i}: {line.strip()}")
    assert not bad, "stray card radii:\n" + "\n".join(bad)


def test_no_raw_hex_outside_theme():
    """UI colors flow through theme tokens. Allowed: token fallbacks in
    `t.get('x', '#…')`, glass_panel's dark-art gradient, microanim's deep
    glow hints, docstrings/comments."""
    import re
    allow_files = {"theme.py", "glass_panel.py"}
    bad = []
    for p, src in _ui_sources():
        name = os.path.basename(p)
        if name in allow_files:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            code = line.split("#")[0] if not re.search(
                r"['\"]#[0-9A-Fa-f]{6}", line) else line
            for m in re.finditer(r"['\"](#[0-9A-Fa-f]{6})['\"]", code):
                seg = code[:m.start()]
                # token fallback pattern: .get('tok', '#hex') — compliant
                if re.search(r"\.get\(\s*['\"][\w]+['\"]\s*,\s*$", seg):
                    continue
                # microanim deep glow hints tuple: ('#tok-resolved', '#deep', '…')
                if name == "microanim.py":
                    continue
                bad.append(f"{name}:{i}: {line.strip()[:90]}")
    assert not bad, "raw hex outside theme:\n" + "\n".join(bad)


def test_numeric_inputs_right_aligned(win):
    from PySide6.QtCore import Qt as _Qt
    assert win.le_L.alignment() & _Qt.AlignmentFlag.AlignRight
    assert win.le_Nx.alignment() & _Qt.AlignmentFlag.AlignRight


def test_mode_gates_survive_group_toggle(win):
    """Expanding a collapsed group must not resurrect 3D-only widgets in
    2D mode (blanket-show + re-assert)."""
    app = QApplication.instance()
    win.combo_dim.setCurrentIndex(0)      # force 2D
    app.processEvents()
    grp = win._accordion_groups["网格与求解器"]
    grp.setChecked(True)
    app.processEvents()
    assert not win.le_Nz.isVisibleTo(win), "3D-only Nz visible in 2D mode"
    grp.setChecked(False)
    app.processEvents()
