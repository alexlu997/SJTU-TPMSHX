"""runs/smoke_ui_3d_pipeline.py — offscreen end-to-end 3D compute smoke.

Boots Main_Menu offscreen, drives the REAL 3D Compute path
(run_calculation → _run_calculation_3d → ComputeOrchestrator worker →
Pipeline3D → write_result). Since B3 C5 (2026-06-13) write_result
publishes the ComputeResult itself as window._result_3d (the raw_3d dict
carrier was retired), so this smoke asserts the ComputeResult carries the
full renderer/export contract.

TPMSHX_EAGER_3D_SLICES=1 is forced so finalize_plots_3d actually runs the
2D mid-z slice renderer offscreen (_render_2d_slices_from_3d) — the
PyVistaQt volume panel cannot init offscreen (logged + tolerated), but the
slice path exercises the ComputeResult consumer surface end to end.
"""
import os
import sys
import time

os.environ['TPMSHX_EAGER_3D_SLICES'] = '1'   # run the 2D slice renderer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
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
    # the legacy path). Capture the ComputeResult at publish time instead.
    captured = {}
    _orig_write = win.write_result
    def _spy_write(result):
        captured['result'] = result
        return _orig_write(result)
    win.write_result = _spy_write

    win.run_calculation()
    assert win.compute.is_running(), 'orchestrator did not start'
    print('[2/3] compute started (Pipeline3D worker)', flush=True)
    t0 = time.time()
    while win.compute.is_running() and time.time() - t0 < 900:
        app.processEvents(); time.sleep(0.05)
    app.processEvents(); time.sleep(0.3); app.processEvents()

    res = captured.get('result')
    assert res is not None, 'ComputeResult never published via write_result'
    assert win._compute_error is None, f"worker error: {win._compute_error}"
    assert res.diagnostics.get('mode') == '3d', \
        f"expected 3D ComputeResult, got mode={res.diagnostics.get('mode')!r}"

    # Full render/export contract — every key the 3D renderer + export read.
    f = res.fields
    needed_fields = {'Ta', 'Tb', 'Ts', 'vmag_A', 'vmag_B', 'P_fA', 'P_fB',
                     'L_mm', 'dx', 'dy', 'dz', 'Lx', 'Ly', 'Lz',
                     'dir_A', 'dir_B', 'ucA', 'vcA', 'wcA'}
    missing = needed_fields - set(f)
    assert not missing, f'ComputeResult.fields missing keys: {sorted(missing)}'
    assert f['Ta'] is not None and f['Ta'].ndim == 3
    assert 'u_A_in_mps' in res.props and 'T_in_A_K' in res.props
    print(f"[3/3] PASS in {time.time()-t0:.0f}s — "
          f"Q={res.Q_W:.1f} W  dP_A={res.dP_A_Pa:.0f} Pa  "
          f"Ta{f['Ta'].shape}  extrap={bool(res.extrap_reasons)}", flush=True)


if __name__ == '__main__':
    main()
