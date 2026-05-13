"""runs/test_ui_smoke_offscreen.py — Phase A: Qt offscreen smoke.

Boots MainWindow with QT_QPA_PLATFORM=offscreen, simulates user flow:
  1. Construct window (catches __init__ crashes / missing imports)
  2. List all visible buttons + their text + enabled state
  3. Switch tabs programmatically
  4. Click a few non-destructive buttons
  5. Verify no exceptions / unhandled errors
"""
from __future__ import annotations
import os, sys, traceback

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QPushButton, QToolButton, QTabBar, QComboBox
from PySide6.QtCore import Qt, QTimer

app = QApplication.instance() or QApplication(sys.argv)

# Capture any unhandled exception
caught = []
def _hook(exctype, value, tb):
    caught.append((exctype.__name__, str(value), ''.join(traceback.format_tb(tb))))
sys.excepthook = _hook


def main():
    from main import Main_Menu
    print("[1/5] Constructing Main_Menu ... ", end='', flush=True)
    win = Main_Menu()
    print("OK", flush=True)
    win.show()
    app.processEvents()
    print(f"      window title: {win.windowTitle()}", flush=True)
    print(f"      size: {win.size().width()}x{win.size().height()}", flush=True)

    # Enumerate buttons
    print("\n[2/5] Enumerating QPushButton + QToolButton:", flush=True)
    btns = win.findChildren(QPushButton) + win.findChildren(QToolButton)
    print(f"      total: {len(btns)} buttons", flush=True)
    visible_enabled = sum(1 for b in btns if b.isVisible() and b.isEnabled())
    visible_disabled = sum(1 for b in btns if b.isVisible() and not b.isEnabled())
    hidden = sum(1 for b in btns if not b.isVisible())
    print(f"      visible+enabled:  {visible_enabled}", flush=True)
    print(f"      visible+disabled: {visible_disabled}", flush=True)
    print(f"      hidden:           {hidden}", flush=True)

    # List visible-enabled non-toolbar buttons by text
    interesting = []
    for b in btns:
        if not (b.isVisible() and b.isEnabled()): continue
        text = b.text() or b.toolTip() or repr(b.objectName())
        interesting.append((text, b))
    print(f"\n      first 15 visible+enabled by text:", flush=True)
    for text, b in interesting[:15]:
        oname = b.objectName() or '<no-name>'
        print(f"        - {text!r:<35} obj={oname}", flush=True)

    # Combo enumeration
    combos = win.findChildren(QComboBox)
    print(f"\n[3/5] QComboBox count: {len(combos)}", flush=True)
    for c in combos:
        if c.isVisible() and c.isEnabled():
            print(f"      {c.objectName() or '<no-name>'}: "
                  f"current = {c.currentText()!r}, items = {c.count()}", flush=True)

    # Tab switching — try by attribute names
    print(f"\n[4/5] Tab navigation test", flush=True)
    tab_attrs = ['btn_tab_params', 'btn_tab_temp', 'btn_tab_pres', 'btn_tab_vel',
                  'btn_tab_3d', 'btn_tab_optimize', 'btn_tab_2d_view']
    for t in tab_attrs:
        b = getattr(win, t, None)
        if b is None:
            print(f"      {t}: <missing>", flush=True); continue
        state = 'visible' if b.isVisible() else 'hidden'
        en = 'enabled' if b.isEnabled() else 'DISABLED'
        print(f"      {t}: {state} {en}  text={b.text()!r}", flush=True)
        if b.isVisible() and b.isEnabled():
            try:
                b.click()
                app.processEvents()
            except Exception as e:
                print(f"        ! click crash: {type(e).__name__}: {e}", flush=True)
        else:
            pass

    # Combo dim switch (2D ↔ 3D)
    print(f"\n[5/5] 2D ↔ 3D switching", flush=True)
    combo_dim = getattr(win, 'combo_dim', None)
    if combo_dim:
        n = combo_dim.count()
        for i in range(n):
            t = combo_dim.itemText(i)
            try:
                combo_dim.setCurrentIndex(i)
                app.processEvents()
                print(f"      combo_dim[{i}] = {t!r}  -> set OK", flush=True)
            except Exception as e:
                print(f"      combo_dim[{i}] = {t!r}  -> CRASH {type(e).__name__}: {e}", flush=True)
    else:
        print("      no combo_dim found", flush=True)

    # Summary
    print("\n=== UNHANDLED EXCEPTIONS ===", flush=True)
    if caught:
        for n, v, tb in caught:
            print(f"  {n}: {v}\n{tb}", flush=True)
    else:
        print("  none", flush=True)

    win.close()
    app.processEvents()
    print("\nSmoke pass DONE", flush=True)


if __name__ == '__main__':
    main()
