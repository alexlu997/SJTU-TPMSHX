"""runs/smoke_ui_screenshots.py — Phase E: offscreen render screenshots."""
from __future__ import annotations
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from runs import _smoke_boot   # sets QT_QPA=offscreen BEFORE any Qt import

from PySide6.QtCore import QSize
from pathlib import Path


def main():
    out = Path('vault/diagrams/ui_screenshots_2026-05-13')
    out.mkdir(parents=True, exist_ok=True)

    app = _smoke_boot.get_app()
    from main import Main_Menu
    win = Main_Menu()
    win.resize(1600, 1000)
    win.show()
    app.processEvents()

    # 1. Full window
    pix = win.grab()
    p = out / '01_full_window_default_3d.png'
    pix.save(str(p)); print(f"saved {p}", flush=True)

    # 2. Switch to 2D
    if hasattr(win, 'combo_dim'):
        for i in range(win.combo_dim.count()):
            if win.combo_dim.itemText(i) == '2D':
                win.combo_dim.setCurrentIndex(i)
                app.processEvents()
                break
        pix = win.grab()
        p = out / '02_full_window_2d_mode.png'
        pix.save(str(p)); print(f"saved {p}", flush=True)

    # 3. Switch back to 3D
    if hasattr(win, 'combo_dim'):
        for i in range(win.combo_dim.count()):
            if win.combo_dim.itemText(i) == '3D':
                win.combo_dim.setCurrentIndex(i)
                app.processEvents()
                break
        pix = win.grab()
        p = out / '03_full_window_3d_mode.png'
        pix.save(str(p)); print(f"saved {p}", flush=True)

    # 4. Show Optimize panel if accessible
    btn_opt = getattr(win, 'btn_tab_optimize_panel', None) or getattr(win, 'btn_optimize', None)
    if btn_opt and btn_opt.isVisible():
        btn_opt.click()
        app.processEvents()
        pix = win.grab()
        p = out / '04_optimize_panel.png'
        pix.save(str(p)); print(f"saved {p}", flush=True)

    win.close()
    print(f"\nAll screenshots in: {out}", flush=True)


if __name__ == '__main__':
    main()
