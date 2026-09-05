"""Real Qt pool/window regressions; only expensive numerical work is stubbed."""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from shiboken6 import isValid

from sjtu_tpmshx.controllers.compute_orchestrator import ComputeOrchestrator
from sjtu_tpmshx.controllers.compute_pipeline import (
    CancelledError, Pipeline2D, Pipeline3D,
)
from sjtu_tpmshx.domain.compute_config import ComputeConfig, SolverConfig
from sjtu_tpmshx.domain.compute_result import ComputeResult


def _wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.001)
    assert predicate(), 'Qt worker/lifecycle did not finish'


@pytest.fixture
def win(tmp_path, monkeypatch):
    from sjtu_tpmshx.controllers.session_manager import SessionManager
    from sjtu_tpmshx.main import Main_Menu

    original_init = SessionManager.__init__
    monkeypatch.setattr(SessionManager, '__init__',
                        lambda self, parent=None: original_init(
                            self, base_dir=tmp_path, parent=parent))
    monkeypatch.setenv('SJTU_TPMSHX_DISABLE_3D_PANEL', '1')
    monkeypatch.setattr(Main_Menu, '_maybe_show_onboarding', lambda self: None)
    window = Main_Menu()
    window._K_ffA = window._K_ffB = 1e-8
    monkeypatch.setattr(window, '_validate_inputs_preflight', lambda: True)
    monkeypatch.setattr(window, '_preflight_grid', lambda: True)
    monkeypatch.setattr(window, '_preflight_3d', lambda: (True, 8, '2×2×2'))
    monkeypatch.setattr(window, '_finalize_plots', lambda: None)
    monkeypatch.setattr('sjtu_tpmshx.ui.plot_3d_results.finalize_plots_3d',
                        lambda _window: False)
    window._test_error_dialogs = []
    monkeypatch.setattr(QMessageBox, 'critical',
                        lambda *args: window._test_error_dialogs.append(args))
    yield window
    if isValid(window):
        window.compute.cancel()
        _wait_for(window.compute.is_idle)
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _configure(win, monkeypatch, mode):
    cfg = ComputeConfig(solver=SolverConfig(Nz=2 if mode == '3d' else 1))
    win.combo_shape.setCurrentIndex(0)
    win.combo_dim.setCurrentIndex(1 if mode == '3d' else 0)
    monkeypatch.setattr('sjtu_tpmshx.ui.window_config.config_from_window',
                        lambda *args, **kwargs: cfg)
    return cfg


@pytest.mark.parametrize('mode', ['2d', '3d'])
def test_worker_publishes_payload_on_gui_thread_without_reentry(win, monkeypatch, mode):
    cfg = _configure(win, monkeypatch, mode)
    gui_thread = threading.get_ident()
    release = threading.Event()
    result = ComputeResult(
        Q_W=123.5, dP_A_Pa=42.0, dP_B_Pa=7.0, T_out_A_K=310.0,
        T_out_B_K=300.0, fields={'Ta': np.ones((2, 2))},
        diagnostics={'mode': mode}, metadata={'run': 'complete payload'})
    worker_seen, writes, cache_writes, rendered, payloads = [], [], [], [], []
    progress, iterations = [], []
    win.compute.finished.connect(payloads.append)
    win.progress.valueChanged.connect(
        lambda p: progress.append((threading.get_ident(), p)))
    win.compute.iteration.connect(lambda s: iterations.append((threading.get_ident(), s)))

    def run(pipe):
        pipe.progress_cb(37)
        if mode == '2d':
            pipe.ui_hooks['live_residuals']['A'].append((1, 1e-3))
            pipe.ui_hooks['iter_label_cb']('iter 1/2')
        else:
            pipe.ui_hooks['iter_cb'](1, 2)
        assert release.wait(10)
        worker_seen.append((threading.get_ident(), pipe.cfg, pipe.cfg.solver.Nz))
        return result

    monkeypatch.setattr(Pipeline2D if mode == '2d' else Pipeline3D, 'run', run)
    original_write = win.write_result
    original_cache = win.cache.set_result

    def write(payload):
        writes.append((threading.get_ident(), payload, win.compute.is_running()))
        original_write(payload)

    def cache_write(*args):
        cache_writes.append(threading.get_ident())
        original_cache(*args)

    def render():
        # Recreate nested event processing during an expensive render.
        def restart():
            rendered.append((win.compute.start('2d', lambda *a, **k: None, {}),
                             win._compute_running, win.btn_compute.isEnabled()))
        QTimer.singleShot(0, restart)
        QApplication.processEvents()
        return True

    monkeypatch.setattr(win, 'write_result', write)
    monkeypatch.setattr(win.cache, 'set_result', cache_write)
    monkeypatch.setattr(win, '_render_compute_result', render)
    try:
        win.run_calculation()
        _wait_for(lambda: bool(iterations))
        assert win._compute_progress == 37
        assert win._iter_label_now == ('iter 1/2' if mode == '2d' else 'outer 1/2')
        if mode == '2d':
            assert win._live_residuals['A'] == [(1, 1e-3)]
        assert not writes and not cache_writes
        win.le_Nz.setText('99')  # UI edits cannot change the in-flight config.
    finally:
        release.set()
    _wait_for(win.compute.is_idle)

    assert worker_seen[0][0] != gui_thread
    assert worker_seen[0][1] is cfg
    assert worker_seen[0][2] == (2 if mode == '3d' else 1)
    assert writes == [(gui_thread, result, True)]
    assert cache_writes == [gui_thread]
    assert payloads == [result] and payloads[0] is result
    assert win.compute.last_result() is result
    assert (gui_thread, 37) in progress
    assert iterations[0][0] == gui_thread
    assert rendered == [(False, True, False)]
    assert win.compute.current_mode() == mode
    if mode == '3d':
        assert win.cache.get_result(mode) is result
    else:
        assert win._compute_results['Ta'] is result.fields['Ta']
        assert win._compute_results['Q_total'] == result.Q_W
    assert not win._compute_running
    assert win.btn_compute.isEnabled()
    assert win._compute_btn_handler == win.run_calculation


@pytest.mark.parametrize('mode', ['2d', '3d'])
@pytest.mark.parametrize('outcome', ['error', 'cancel', 'render_error'])
def test_terminal_paths_restore_ui(win, monkeypatch, mode, outcome):
    _configure(win, monkeypatch, mode)
    observed = []
    win.compute.error.connect(lambda *args: observed.append('error'))
    win.compute.cancelled.connect(lambda *args: observed.append('cancel'))
    win.compute.finished.connect(lambda *args: observed.append('finished'))

    def run(pipe):
        if outcome == 'error':
            raise RuntimeError('solver failed')
        if outcome == 'cancel':
            assert pipe.cancel.is_set()
            raise CancelledError('cancel checkpoint')
        return ComputeResult(Q_W=123, diagnostics={'mode': mode})

    def bad_render():
        raise RuntimeError('render failed')

    monkeypatch.setattr(Pipeline2D if mode == '2d' else Pipeline3D, 'run', run)
    if outcome == 'cancel':
        win.compute.started.connect(lambda _mode: win._on_cancel_compute())
    if outcome == 'render_error':
        monkeypatch.setattr(win, '_render_compute_result', bad_render)
    win.run_calculation()
    _wait_for(win.compute.is_idle)

    assert observed == ['finished' if outcome == 'render_error' else outcome]
    assert not win._compute_running
    assert win.btn_compute.isEnabled()
    assert win._compute_btn_handler == win.run_calculation
    assert not win._btn_ticker_timer.isActive()
    assert not win._live_resid_timer.isActive()
    assert not win.progress.isVisible()
    if mode == '3d':
        assert not win._compute_3d_watchdog.isActive()
    if outcome == 'render_error':
        assert win.cache.has_results(mode), 'render failure destroyed valid data'
    assert bool(win._test_error_dialogs) == (outcome == 'error')


@pytest.mark.parametrize('outcome', ['success', 'error', 'cancel'])
def test_close_waits_for_terminal_delivery_and_runnable_exit(win, monkeypatch, outcome):
    from sjtu_tpmshx.controllers.compute_orchestrator import _ComputeRunnable

    release, terminal_sent = threading.Event(), threading.Event()
    tail_errors, writes = [], []
    original_run = _ComputeRunnable.run

    def held_run(runnable):
        original_run(runnable)
        terminal_sent.set()
        try:
            assert release.wait(10)
            # The pool still owns this active runnable after terminal delivery.
            runnable._orch.progress.emit(95)
        except Exception as exc:
            tail_errors.append(exc)

    def worker(cfg, cancel, progress_cb):
        if outcome == 'error':
            raise RuntimeError('failure while closing')
        if outcome == 'cancel':
            raise ComputeOrchestrator.CancelledError()
        return ComputeResult(Q_W=123)

    monkeypatch.setattr(_ComputeRunnable, 'run', held_run)
    monkeypatch.setattr(win, 'write_result', writes.append)
    win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    orch, cache = win.compute, win.cache
    try:
        orch.start('2d', worker, ComputeConfig())
        assert terminal_sent.wait(5)  # Deliberately do not drain Qt yet.
        t0 = time.monotonic()
        assert not win.close()
        assert time.monotonic() - t0 < 0.5, 'close blocked the GUI thread'
        assert isValid(win) and isValid(orch) and isValid(cache)
        assert win._close_pending and not win.isEnabled()
        _wait_for(lambda: not orch.is_running())
        assert not orch.is_idle(), 'terminal signal is not runnable completion'
        assert not win.close()
        assert isValid(win) and not writes
        assert not win._test_error_dialogs
    finally:
        release.set()
    _wait_for(lambda: not isValid(win))
    assert not isValid(orch) and not isValid(cache)
    assert not tail_errors, 'worker accessed a deleted QObject'


@pytest.mark.parametrize('mode', ['2d', '3d'])
def test_close_cancels_live_pipeline_without_destroying_its_callbacks(win, monkeypatch, mode):
    _configure(win, monkeypatch, mode)
    release, entered = threading.Event(), threading.Event()
    cancellation_seen = []

    def run(pipe):
        entered.set()
        assert release.wait(10)
        cancellation_seen.append(pipe.cancel.cancelled)
        pipe.progress_cb(90)
        if mode == '2d':
            pipe.ui_hooks['iter_label_cb']('last checkpoint')
        else:
            pipe.ui_hooks['iter_cb'](2, 2)
        pipe._check_cancel()

    monkeypatch.setattr(Pipeline2D if mode == '2d' else Pipeline3D, 'run', run)
    win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    try:
        win.run_calculation()
        assert entered.wait(5)
        assert not win.close()
        assert isValid(win.compute) and win.compute.is_running()
        assert win._close_pending
    finally:
        release.set()
    _wait_for(lambda: not isValid(win))
    assert cancellation_seen == [True]
