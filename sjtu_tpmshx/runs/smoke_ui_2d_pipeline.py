"""runs/smoke_ui_2d_pipeline.py — offscreen end-to-end 2D compute smoke.

Added with the B2 2.1b traffic switch (2026-06-13): boots Main_Menu
offscreen, auto-fills both fluids, forces 2D mode and drives the REAL
Compute path (run_calculation → ComputeOrchestrator worker → Pipeline2D
→ write_result → finalize_plots). Asserts results + render caches land.

All modals are auto-accepted — including INSTANCE QMessageBox(...).exec()
(main._preflight_grid), which a class-method patch alone does not catch;
that exact gap hung the first version of this smoke for 20 minutes.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runs import _smoke_boot   # sets QT_QPA=offscreen BEFORE any Qt import

from PySide6.QtWidgets import QMessageBox


def _patch_modals():
    def _auto(*a, **k):
        print('  [dialog auto-Yes]', flush=True)
        return QMessageBox.StandardButton.Yes
    QMessageBox.question = staticmethod(_auto)
    QMessageBox.warning = staticmethod(_auto)
    QMessageBox.information = staticmethod(_auto)
    QMessageBox.exec = lambda self: (print('  [instance modal auto-Yes]',
                                           flush=True)
                                     or QMessageBox.StandardButton.Yes)


def main():
    app = _smoke_boot.get_app()
    _patch_modals()
    from main import Main_Menu
    win = Main_Menu()
    app.processEvents()

    win.combo_dim.setCurrentIndex(0)            # force 2D
    win.le_Nx.setText('16'); win.le_Ny.setText('24')
    win.auto_fill_fluid_a(); win.auto_fill_fluid_b()
    app.processEvents()
    print('[1/3] autofill OK', flush=True)

    win.run_calculation()
    assert win.compute.is_running(), 'orchestrator did not start'
    print('[2/3] compute started (Pipeline2D worker)', flush=True)
    t0 = time.time()
    while win.compute.is_running() and time.time() - t0 < 600:
        app.processEvents(); time.sleep(0.05)
    app.processEvents(); time.sleep(0.3); app.processEvents()

    r = win._compute_results
    assert r is not None and r.get('Ta') is not None, 'no results written'
    assert r['Q_total'] > 0, f"non-physical Q_total {r['Q_total']!r}"
    assert win.T_fA is not None and win.T_fA.ndim == 3, 'T_fA cache missing'
    assert win._compute_error is None, f"worker error: {win._compute_error}"
    print(f"[3/3] PASS in {time.time()-t0:.0f}s — "
          f"Q={r['Q_total']:.1f} W  dP_A={r['dP_A']:.0f} Pa  "
          f"dP_B={r['dP_B']:.0f} Pa  T_fA{win.T_fA.shape}", flush=True)


if __name__ == '__main__':
    main()
