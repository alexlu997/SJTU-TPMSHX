"""runs/smoke_ui_3d_pipeline.py — offscreen end-to-end 3D compute smoke.

Added with the B2 2.1c traffic switch (2026-06-13): boots Main_Menu
offscreen, drives the REAL 3D Compute path (run_calculation →
_run_calculation_3d → ComputeOrchestrator worker → Pipeline3D →
write_result raw_3d carrier). Asserts window._result_3d holds the raw
dict with every renderer-consumed key. finalize_plots_3d runs too — the
PyVista panel cannot initialise offscreen (logged + tolerated), but the
2D mid-z slice canvases and result labels exercise the carrier.
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

    win.combo_dim.setCurrentIndex(1)            # force 3D
    win.le_Nx.setText('12'); win.le_Ny.setText('10'); win.le_Nz.setText('4')
    win.auto_fill_fluid_a(); win.auto_fill_fluid_b()
    app.processEvents()
    print('[1/3] autofill OK', flush=True)

    # Offscreen quirk: _on_orch_finished sets `_has_results_3d = _3d_vis_ok`
    # and the PyVista panel cannot init offscreen, so the cached result is
    # CLEARED right after finalize (pre-existing behaviour, identical on
    # the legacy path). Capture the raw_3d carrier at publish time instead.
    captured = {}
    _orig_write = win.write_result
    def _spy_write(result):
        captured['raw'] = result.diagnostics.get('raw_3d')
        captured['extrap'] = list(result.extrap_reasons)
        return _orig_write(result)
    win.write_result = _spy_write

    win.run_calculation()
    assert win.compute.is_running(), 'orchestrator did not start'
    print('[2/3] compute started (Pipeline3D worker)', flush=True)
    t0 = time.time()
    while win.compute.is_running() and time.time() - t0 < 900:
        app.processEvents(); time.sleep(0.05)
    app.processEvents(); time.sleep(0.3); app.processEvents()

    r = captured.get('raw')
    assert r is not None, 'raw_3d carrier never published via write_result'
    assert win._compute_error is None, f"worker error: {win._compute_error}"
    needed = {'Ta', 'Tb', 'Ts', 'vmag', 'P_kPa', 'dx', 'dy', 'dz',
              'Lx', 'Ly', 'Lz', 'dP', 'dP_B', 'dir_A', 'dir_B',
              'extrapolated', 'extrap_reasons'}
    missing = needed - set(r)
    assert not missing, f'raw_3d carrier missing keys: {sorted(missing)}'
    assert r['Ta'] is not None and r['Ta'].ndim == 3
    print(f"[3/3] PASS in {time.time()-t0:.0f}s — "
          f"Q={float(r.get('Q_total', r.get('Q'))):.1f} W  "
          f"dP_A={float(r.get('dP_A', r.get('dP'))):.0f} Pa  "
          f"Ta{r['Ta'].shape}  extrap={r['extrapolated']}", flush=True)


if __name__ == '__main__':
    main()
