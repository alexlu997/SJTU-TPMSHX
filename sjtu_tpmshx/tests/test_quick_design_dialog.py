"""Construction tests for build_quick_design_dialog.

Verifies:
  - All contract attributes exist on the returned QDialog instance.
  - The run button calls run_quick_design.
  - Switching combo_qd_mode between "auto" and "fixed" toggles group visibility.

Run from repo root:
    python -m pytest sjtu_tpmshx/tests/test_quick_design_dialog.py -v
"""
from unittest.mock import patch
from ui.quick_design_panel import build_quick_design_dialog

CONTRACT = [
    "le_qd_file", "combo_qd_mode", "combo_qd_arr", "le_qd_rho",
    "le_qd_topo", "le_qd_l", "le_qd_t", "chk_qd_refine",
    "combo_qd_cell_topo", "le_qd_cell_l", "le_qd_cell_t",
    "_qd_table", "_qd_status",
]


def test_dialog_builds_with_contract_attrs():
    dlg = build_quick_design_dialog()
    for a in CONTRACT:
        assert hasattr(dlg, a), f"missing contract attr {a}"
    assert dlg.combo_qd_mode.currentText() in ("auto", "fixed")
    assert dlg.combo_qd_arr.currentText() in ("counter", "cross")
    dlg.deleteLater()


def test_run_button_invokes_run_quick_design():
    dlg = build_quick_design_dialog()
    with patch("ui.quick_design_panel.run_quick_design") as m:
        dlg._qd_run_btn.click()   # expose the run button as dlg._qd_run_btn
        assert m.called
    dlg.deleteLater()


def test_mode_toggle_switches_groups():
    dlg = build_quick_design_dialog()
    dlg.combo_qd_mode.setCurrentText("fixed")
    assert dlg._qd_fixed_group.isVisibleTo(dlg) or not dlg._qd_auto_group.isVisibleTo(dlg)
    dlg.combo_qd_mode.setCurrentText("auto")
    assert dlg._qd_auto_group.isVisibleTo(dlg) or not dlg._qd_fixed_group.isVisibleTo(dlg)
    dlg.deleteLater()
