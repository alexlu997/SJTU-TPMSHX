"""GUI smoke test for B (main refactor).

Verifies that Main_Menu can be instantiated and its UI built without
exceptions. Does NOT check specific widget behavior — just 'doesn't crash'.
Runs with QT_QPA_PLATFORM=offscreen so it works headless.

Run with:
    cd D:/Postgraduate/均质化/ThermoNAS/thermoNas
    python test_main_smoke.py
"""
import sys
import os

# Qt requires a platform plugin; offscreen works on both headless and desktop
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def test_main_menu_startup():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from main import Main_Menu
    w = Main_Menu()
    # Key widgets that every refactor step must preserve
    assert hasattr(w, 'combo_tpms'), "combo_tpms missing after refactor"
    assert hasattr(w, 'le_L'), "le_L missing after refactor"
    assert hasattr(w, 'le_H'), "le_H missing after refactor"
    assert hasattr(w, 'canvas_temp'), "canvas_temp missing after refactor"
    assert hasattr(w, 'progress'), "progress bar missing"
    w.close()
    print("test_main_menu_startup PASS")


if __name__ == '__main__':
    test_main_menu_startup()
    print("\nAll smoke tests PASS")
