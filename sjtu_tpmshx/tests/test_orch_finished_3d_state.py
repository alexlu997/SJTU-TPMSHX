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
        from sjtu_tpmshx.domain.compute_result import ComputeResult
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


class _CacheBridgeWindow(_DummyWindow):
    """Models the REAL ``main.Main_Menu`` ResultCache bridge instead of plain
    attrs: ``_result_3d`` is property-backed, and the ``_has_results_3d`` setter
    NULLS ``_result_3d`` when set False (getter = result-present). The plain-attr
    ``_DummyWindow`` decoupled the flag from the result, which HID the U1 bug
    where a soft viz-fail destroyed a valid solve's result (audit 2026-06-28)."""

    def __init__(self):
        self._cache_3d = None          # backing store, must exist before setters
        super().__init__()

    @property
    def _result_3d(self):
        return self._cache_3d

    @_result_3d.setter
    def _result_3d(self, v):
        self._cache_3d = v

    @property
    def _has_results_3d(self):
        return self._cache_3d is not None

    @_has_results_3d.setter
    def _has_results_3d(self, v):
        if not v:                       # the result-nulling coupling (real bridge)
            self._cache_3d = None


# ── tests ───────────────────────────────────────────────────────────


def _run_finished(win, finalize_behavior):
    """Drive Main_Menu._on_orch_finished with finalize_plots_3d patched."""
    import sjtu_tpmshx.main as main
    if isinstance(finalize_behavior, BaseException):
        def _fb(_w):
            raise finalize_behavior
        patch_fin = patch('sjtu_tpmshx.ui.plot_3d_results.finalize_plots_3d', _fb)
    else:
        patch_fin = patch('sjtu_tpmshx.ui.plot_3d_results.finalize_plots_3d',
                          return_value=finalize_behavior)
    with patch_fin, patch('PySide6.QtWidgets.QApplication') as qapp_mock:
        qapp_mock.processEvents = MagicMock()
        try:
            main.Main_Menu._on_orch_finished(win, {})
        except Exception:
            pass


def test_3d_finalize_crash_gates_tab_off_but_keeps_result():
    """When ``finalize_plots_3d`` raises, the 3D View tab must be gated off
    (``_3d_view_ready`` False) — but the valid solver result must SURVIVE so it
    stays exportable (U1: was destroyed via the result-nulling bridge)."""
    win = _CacheBridgeWindow()
    assert win._result_3d is not None and win._has_results_3d is True

    _run_finished(win, RuntimeError("PyVista context lost"))

    # Tab gated off (panel never populated) — the H5 invariant, now carried by
    # the dedicated flag instead of the result-nulling _has_results_3d.
    assert getattr(win, '_3d_view_ready', False) is False
    # U1: result preserved — Export / status read _result_3d.
    assert win._result_3d is not None, "finalize crash destroyed the 3D result"


def test_3d_finalize_success_marks_view_ready_and_keeps_result():
    """Happy path: finalize returns True → tab ready + result present."""
    win = _CacheBridgeWindow()

    _run_finished(win, True)

    assert getattr(win, '_3d_view_ready', False) is True
    assert win._result_3d is not None


def test_3d_soft_vis_fail_preserves_result_for_export():
    """U1 (audit 2026-06-28): on the REAL ResultCache bridge a soft viz failure
    (finalize returns False — offscreen/headless/GL/TPMSHX_DISABLE_3D_PANEL)
    must NOT destroy the freshly-computed 3D result. The valid Q/dP must survive
    so the 'visualisation failed' status branch + Export work; tab-readiness is
    carried by ``_3d_view_ready`` instead of the result-nulling flag."""
    win = _CacheBridgeWindow()
    assert win._result_3d is not None

    _run_finished(win, False)

    # The bug: line 566 wrote _has_results_3d=False -> bridge nulled _result_3d.
    assert win._result_3d is not None, "soft viz-fail destroyed the 3D result"
    # Tab gated off so the user is not routed to a blank canvas.
    assert getattr(win, '_3d_view_ready', False) is False
