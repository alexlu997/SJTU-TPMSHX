"""smoke_ui_3d_tab.py — headless check that 3D tab wires correctly.

Creates the main window off-screen, verifies:
  - `canvas_3d` attribute exists and is a `ThreeDVisPanel`
  - `btn_tab_3d` exists
  - `_canvas_cards['3d']` is a QFrame
  - `_switch_tab('3d')` doesn't raise

Does NOT launch PyVista interactor fully; just checks the Qt wiring.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Use real Windows display — offscreen fails VTK OpenGL init

from PySide6.QtWidgets import QApplication, QFrame
from PySide6.QtCore import QTimer


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    from main import Main_Menu
    w = Main_Menu()

    # Assertions
    assert hasattr(w, 'btn_tab_3d'), "btn_tab_3d missing"
    assert w.btn_tab_3d.text() == '3D View', f"got: {w.btn_tab_3d.text()!r}"
    assert hasattr(w, 'canvas_3d'), "canvas_3d missing"

    # Lazy: canvas_3d is None until first 3D tab switch
    from ui.panel_vis_3d import ThreeDVisPanel
    assert w.canvas_3d is None, "canvas_3d should start None (lazy)"
    assert '3d' in w._canvas_cards, f"card keys: {list(w._canvas_cards)}"
    assert isinstance(w._canvas_cards['3d'], QFrame)

    # First 3D tab switch triggers lazy init
    w._switch_tab('3d')
    assert w._active_tab == '3d', f"_active_tab = {w._active_tab!r}"
    assert not w._canvas_cards['3d'].isHidden()
    assert isinstance(w.canvas_3d, ThreeDVisPanel), \
        f"canvas_3d after switch is {type(w.canvas_3d).__name__}"

    # Dimensionality controls
    assert hasattr(w, 'combo_dim'), "combo_dim missing"
    assert hasattr(w, 'le_Lz'), "le_Lz missing"
    assert hasattr(w, 'le_Nz'), "le_Nz missing"
    assert w.combo_dim.count() == 2
    # Default 2D → Lz/Nz hidden
    assert w.le_Lz.isHidden(), "le_Lz should be hidden in 2D"
    assert w.le_Nz.isHidden(), "le_Nz should be hidden in 2D"
    # Flip to 3D → Lz/Nz visible
    w.combo_dim.setCurrentIndex(1)
    assert not w.le_Lz.isHidden(), "le_Lz should show in 3D"
    assert not w.le_Nz.isHidden(), "le_Nz should show in 3D"

    # Runner module imports cleanly
    from runs.run_calculation_3d import run_calculation_3d_inner, finalize_plots_3d
    assert callable(run_calculation_3d_inner)
    assert callable(finalize_plots_3d)

    # Main dispatcher exposes 3D path
    assert hasattr(w, '_run_calculation_3d'), "_run_calculation_3d method missing"

    # End-to-end sync 3D compute with tiny grid (no threading)
    w.le_Nx.setText('14')
    w.le_Ny.setText('8')
    w.le_Nz.setText('3')
    print("Running sync 3D compute smoke (14x8x3)...")
    run_calculation_3d_inner(w)
    res = w._result_3d
    assert res is not None
    for key in ('Ta', 'vmag', 'P_kPa', 'L_mm', 'dx', 'dy', 'dz', 'Q', 'dP'):
        assert key in res, f"result missing {key}"
    print(f"  Q = {res['Q']:.2f} W   dP = {res['dP']:.0f} Pa")
    print(f"  Ta range [{res['Ta'].min():.1f}, {res['Ta'].max():.1f}] K")
    # Push into panel
    finalize_plots_3d(w)

    print("SMOKE PASS: 3D tab wired.")
    print(f"  btn_tab_3d  : {w.btn_tab_3d.text()}")
    print(f"  canvas_3d   : {type(w.canvas_3d).__name__}")
    print(f"  active tab  : {w._active_tab}")

    # Auto-close after 1.2 s so we verify no crash on teardown
    def _quit():
        try:
            w.canvas_3d.cleanup()
        except Exception:
            pass
        w.close()
        app.quit()
    QTimer.singleShot(1200, _quit)
    app.exec()
    print("Exited cleanly.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
