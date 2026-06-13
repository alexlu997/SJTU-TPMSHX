"""Test for ``Main_Menu._on_orch_finished`` 3D branch — audit C5 H5 fix.

The pre-fix code only reset ``_has_results_3d`` *after* a successful
``finalize_plots_3d`` call.  If the embedded PyVistaQt panel crashed
the function returned early without resetting, leaving a stale
``True`` from a prior 3D run.  The next 2D compute could then route
the user to a blank canvas via tab auto-switch.

Fix: init ``_has_results_3d = False`` at the *top* of the 3D branch,
flip ``True`` only after ``finalize_plots_3d`` returns truthy.

This test mocks finalize_plots_3d to raise, verifies
``_has_results_3d`` ends ``False`` even though the prior state was
``True``.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── ultra-lite Main_Menu stub ───────────────────────────────────────


class _ComputeStub:
    """Tiny ``self.compute`` stub for the orchestrator-finished slot."""

    def __init__(self, mode='3d'):
        self._mode = mode

    def current_mode(self):
        return self._mode

    def last_log(self):
        return ''


class _StatusBarStub:
    def showMessage(self, *_a, **_kw):
        pass


class _DummyWindow:
    """Lite ``Main_Menu`` stand-in carrying just the attrs the 3D branch
    of ``_on_orch_finished`` touches."""

    def __init__(self):
        self.compute = _ComputeStub()
        # Stale prior 3D state we want to see reset.
        self._has_results_3d = True
        self._has_results = False
        # B3 C5: window._result_3d is the ComputeResult (raw_3d dict retired);
        # _on_orch_finished reads res.Q_W / res.dP_A_Pa / res.diagnostics.
        from controllers.compute_pipeline import ComputeResult
        self._result_3d = ComputeResult(Q_W=100.0, dP_A_Pa=50.0,
                                        diagnostics={'mode': '3d'})
        self._rendered_3d_slices = False
        self._drawn_tabs = set()
        self._compute_running = True
        self._last_solve_log = ''
        self._compute_poll_timer = None
        self._compute_3d_watchdog = None

    def _end_compute_ui(self, *, success):
        self._end_compute_ui_success = success

    def _push_recent_run(self):
        pass

    def _update_tab_visibility(self):
        pass

    def _switch_tab(self, _name):
        pass

    def statusBar(self):
        return _StatusBarStub()


# ── tests ───────────────────────────────────────────────────────────


def test_3d_finalize_crash_resets_has_results_3d():
    """When ``finalize_plots_3d`` raises, the H5 fix must leave
    ``_has_results_3d`` at ``False`` even though it was ``True`` from
    a prior successful 3D run."""
    import main

    win = _DummyWindow()
    assert win._has_results_3d is True  # stale prior state

    # Patch finalize_plots_3d to crash.
    def _boom(_w):
        raise RuntimeError("PyVista context lost")

    # Patch QApplication.processEvents (called inside the slot) so the
    # absent QApplication doesn't blow up.
    with patch('ui.plot_3d_results.finalize_plots_3d', _boom), \
         patch('PySide6.QtWidgets.QApplication') as qapp_mock:
        qapp_mock.processEvents = MagicMock()
        try:
            main.Main_Menu._on_orch_finished(win, {})
        except Exception:
            # The slot itself does not raise — but if some patched
            # path leaks an exception, we still want the H5 invariant
            # checked below.
            pass

    # H5 invariant: stale True must not survive a finalize crash.
    assert win._has_results_3d is False, (
        f"H5 leak: _has_results_3d stayed {win._has_results_3d!r} "
        f"after finalize_plots_3d crash")


def test_3d_finalize_success_sets_has_results_3d_true():
    """Happy path: finalize returns True → ``_has_results_3d`` ends
    ``True``."""
    import main

    win = _DummyWindow()
    win._has_results_3d = False  # clean prior state

    with patch('ui.plot_3d_results.finalize_plots_3d',
                return_value=True), \
         patch('PySide6.QtWidgets.QApplication') as qapp_mock:
        qapp_mock.processEvents = MagicMock()
        try:
            main.Main_Menu._on_orch_finished(win, {})
        except Exception:
            pass

    assert win._has_results_3d is True


def test_3d_finalize_returns_false_keeps_has_results_3d_false():
    """When ``finalize_plots_3d`` returns falsy (viz panel did not
    populate), ``_has_results_3d`` must stay ``False`` regardless of
    prior value."""
    import main

    win = _DummyWindow()
    win._has_results_3d = True  # stale True

    with patch('ui.plot_3d_results.finalize_plots_3d',
                return_value=False), \
         patch('PySide6.QtWidgets.QApplication') as qapp_mock:
        qapp_mock.processEvents = MagicMock()
        try:
            main.Main_Menu._on_orch_finished(win, {})
        except Exception:
            pass

    assert win._has_results_3d is False
