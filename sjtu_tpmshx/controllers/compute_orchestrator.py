"""ComputeOrchestrator — solver thread lifecycle as a QObject.

Replaces the raw `threading.Thread(daemon=True)` + QTimer-poll pattern in
`main.py:run_calculation` with a Qt-native QThreadPool + QRunnable + signals
pattern. Provides:

  - re-entrancy guard (refuse to start while running)
  - cooperative cancel via cancel_token (worker checks at epoch boundaries)
  - structured signals (started / progress / finished / error / cancelled)
  - ETA history per mode (2d / 3d / poly)
  - solver stdout capture into a 500 KB ring (for the D9 solve-log viewer)

The actual solver work runs in `worker_fn(cfg, cancel_token, progress_cb)`.
Caller passes a callable that does the compute and returns a result dict.
The orchestrator handles thread spawn / lifecycle / signal dispatch.

Phase 1 of 2026-05-06 main.py refactor (audit fix #4).
See vault/reports/refactor/2026-05-06-main-py-refactor-plan-CN.md.
"""
from __future__ import annotations

import io
import sys
import time
import threading
import traceback
import contextlib
from collections import deque
from typing import Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


# ---------------------------------------------------------------- public types


class CancelToken:
    """Cooperative cancel flag. Solver checks `.is_set()` at epoch boundaries.

    Thread-safe via threading.Event; readable from worker, settable from UI.
    """

    def __init__(self):
        self._evt = threading.Event()

    def is_set(self) -> bool:
        return self._evt.is_set()

    def cancel(self) -> None:
        self._evt.set()

    def reset(self) -> None:
        self._evt.clear()


# ---------------------------------------------------------------- runnable


class _ComputeRunnable(QRunnable):
    """QRunnable wrapper that drives `worker_fn` and forwards stdout / events.

    Internal — instantiated by ComputeOrchestrator.start(). Not part of the
    public API. Communicates back via the orchestrator's signals.
    """

    def __init__(self, orchestrator: 'ComputeOrchestrator',
                 worker_fn: Callable, cfg: dict,
                 cancel_token: CancelToken):
        super().__init__()
        self.setAutoDelete(True)
        self._orch = orchestrator
        self._worker_fn = worker_fn
        self._cfg = cfg
        self._cancel = cancel_token

    def run(self):
        orch = self._orch
        log_buf = io.StringIO()

        # Tee solver stdout: terminal + capture buffer (for solve-log viewer)
        class _Tee:
            def __init__(self, *streams):
                self._s = streams

            def write(self, x):
                for s in self._s:
                    try:
                        s.write(x)
                    except Exception:
                        pass

            def flush(self):
                for s in self._s:
                    try:
                        s.flush()
                    except Exception:
                        pass

        t0 = time.time()
        try:
            with contextlib.redirect_stdout(_Tee(sys.__stdout__, log_buf)):
                result = self._worker_fn(
                    self._cfg, self._cancel,
                    progress_cb=lambda p: orch.progress.emit(int(p)))

            elapsed = time.time() - t0
            # Cap log at 500 KB to bound memory.
            log_text = log_buf.getvalue()[:500_000]
            orch._on_worker_finished(result, log_text, elapsed)
        except _CancelledError:
            elapsed = time.time() - t0
            log_text = log_buf.getvalue()[:500_000]
            orch._on_worker_cancelled(log_text, elapsed)
        except Exception as e:
            log_text = log_buf.getvalue()[:500_000]
            tb = traceback.format_exc()
            log_text = log_text + "\n" + tb
            orch._on_worker_error(str(e), log_text)


class _CancelledError(Exception):
    """Raised from inside worker_fn when cancel_token observed.

    Workers should `if cancel_token.is_set(): raise CancelledError` at epoch
    boundaries. Re-exported as `ComputeOrchestrator.CancelledError`.
    """


# ---------------------------------------------------------------- orchestrator


class ComputeOrchestrator(QObject):
    """Qt-native solver lifecycle controller.

    Signals
    -------
    started(str mode)
        Emitted right before worker dispatch. mode in {'2d', '3d', 'poly'}.
    progress(int percent)
        Emitted as the worker reports progress. 0..100. Solver controls cadence.
    finished(dict result)
        Worker returned cleanly. result is whatever the worker_fn returned
        (caller-defined). Emitted on the GUI thread (Qt auto-marshals).
    error(str message, str log)
        Worker raised an exception. message = str(exc); log = captured stdout.
    cancelled(str log)
        Worker observed cancel_token and raised CancelledError.

    Usage
    -----
    >>> orch = ComputeOrchestrator(parent=main_window)
    >>> orch.started.connect(_begin_compute_ui)
    >>> orch.progress.connect(progress_bar.setValue)
    >>> orch.finished.connect(_finalize_plots)
    >>> orch.error.connect(_show_error_dialog)
    >>> orch.cancelled.connect(_show_cancel_toast)
    >>> orch.start('2d', _run_calculation_inner_2d, cfg)
    >>> # later, on user click:
    >>> orch.cancel()
    """

    # Qt signals (always declared at class level)
    started = Signal(str)
    progress = Signal(int)
    finished = Signal(dict)
    error = Signal(str, str)
    cancelled = Signal(str)

    CancelledError = _CancelledError

    def __init__(self, parent: Optional[QObject] = None,
                 max_threads: int = 1):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        # Solver runs are heavy; only one at a time. UI keeps responsiveness
        # via Qt event loop, not via additional pool slots.
        self._pool.setMaxThreadCount(max_threads)
        self._cancel_token: Optional[CancelToken] = None
        self._mode: Optional[str] = None
        self._is_running = False
        # Latest run snapshot — populated when worker finishes / errors.
        self._last_result: Optional[dict] = None
        self._last_error: Optional[str] = None
        self._last_log: str = ""
        self._last_elapsed: float = 0.0
        # Per-mode wall-clock history for ETA prediction.
        self._eta_history = {
            '2d': deque(maxlen=10),
            '3d': deque(maxlen=10),
            'poly': deque(maxlen=10),
        }

    # ---- introspection -----------------------------------------------------

    def is_running(self) -> bool:
        return self._is_running

    def current_mode(self) -> Optional[str]:
        return self._mode

    def last_result(self) -> Optional[dict]:
        return self._last_result

    def last_error(self) -> Optional[str]:
        return self._last_error

    def last_log(self) -> str:
        return self._last_log

    def last_elapsed(self) -> float:
        return self._last_elapsed

    def eta_seconds(self, mode: str) -> Optional[float]:
        """Median wall-clock for `mode` from history, or None if no samples."""
        hist = self._eta_history.get(mode)
        if not hist:
            return None
        srt = sorted(hist)
        n = len(srt)
        return srt[n // 2] if n % 2 == 1 else 0.5 * (srt[n // 2 - 1] + srt[n // 2])

    # ---- control -----------------------------------------------------------

    def start(self, mode: str, worker_fn: Callable, cfg: dict) -> bool:
        """Start a compute. Returns True if dispatched, False if rejected.

        worker_fn signature:
            worker_fn(cfg: dict, cancel_token: CancelToken,
                      progress_cb: Callable[[int], None]) -> dict
        Worker should poll cancel_token at epoch boundaries and raise
        ComputeOrchestrator.CancelledError when set, OR simply return early
        with whatever partial state is reasonable.

        Re-entrancy: rejects with False if a compute is already running.
        Caller should display "compute busy" feedback in that case.
        """
        if self._is_running:
            return False
        if mode not in ('2d', '3d', 'poly'):
            raise ValueError(f"unknown compute mode: {mode!r}")

        self._mode = mode
        self._cancel_token = CancelToken()
        self._is_running = True
        self._last_result = None
        self._last_error = None
        self._last_log = ""

        runnable = _ComputeRunnable(self, worker_fn, cfg, self._cancel_token)
        self.started.emit(mode)
        self._pool.start(runnable)
        return True

    def cancel(self) -> None:
        """Signal the worker to stop at its next epoch boundary.

        Idempotent. Worker decides what 'stop' means (mid-iteration return
        with partial result, or raise CancelledError). The orchestrator does
        NOT force-kill the thread — that would corrupt numba state.
        """
        if self._cancel_token is not None:
            self._cancel_token.cancel()

    # ---- worker callbacks (thread-safe via Qt signal auto-marshal) ---------
    #
    # These are called from the QRunnable thread. Emitting Qt signals from a
    # worker thread is safe — Qt marshals slot calls to the receiver's owning
    # thread (typically the GUI thread). State writes here happen-before the
    # signal emit, so slot handlers see consistent state.

    def _on_worker_finished(self, result: dict, log: str, elapsed: float):
        self._last_result = result
        self._last_log = log
        self._last_elapsed = elapsed
        if self._mode is not None:
            self._eta_history[self._mode].append(elapsed)
        self._is_running = False
        self.finished.emit(result if result is not None else {})

    def _on_worker_error(self, message: str, log: str):
        self._last_error = message
        self._last_log = log
        self._is_running = False
        self.error.emit(message, log)

    def _on_worker_cancelled(self, log: str, elapsed: float):
        self._last_log = log
        self._last_elapsed = elapsed
        self._is_running = False
        self.cancelled.emit(log)
