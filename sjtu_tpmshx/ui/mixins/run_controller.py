"""Compute-run orchestration handlers for ``Main_Menu``.

Extracted verbatim from the ``main`` god object: the Compute entry
points (run_calculation / _run_calculation_3d / _run_polygon_calculation),
the ComputeOrchestrator signal handlers (_on_orch_started / _progress /
_finished / _error / _cancelled), the result writer + plot finalizer
(write_result / _finalize_plots), and the compute-UI lifecycle helpers
(_begin_compute_ui / _end_compute_ui / _on_cancel_compute /
_active_compute_mode / _update_result_summary / _begin_btn_ticker /
_tick_btn / _drain_live_residuals). 18 methods.

UI-orchestration only: the numeric solve lives in runs/run_calculation*.py
(reached via ComputeOrchestrator workers), not here. Deps are stable
imports (PySide6 widgets, ui.fmt._fmt_dur, ui.ui_constants constants,
time) — no main.py module state. Adopted via
``class Main_Menu(..., RunControllerMixin, QMainWindow)``; external wiring
(ui_builders btn_run, command_palette, signal_router, orch signal
connections) resolves on the live window through the MRO.
"""

from __future__ import annotations

import time as _time

from PySide6.QtWidgets import QApplication, QMessageBox

from ui.fmt import duration as _fmt_dur
from ui.ui_constants import VV_VELOCITY_LIMIT_MS, TOAST_MS_MED, TOAST_MS_SHORT


class RunControllerMixin:
    """Compute entry points + orchestrator signal handlers + UI lifecycle."""

    def run_calculation(self):
        """Full-domain solve: SIMPLE velocity → coupled energy on L × H.

        2026-05-06 refactor (audit fix #4 / Plan #4 Phase 1.2): solver thread
        lifecycle delegated to ComputeOrchestrator. Re-entrancy guard, cancel,
        result distribution, error handling all flow through orch signals.
        """
        # Re-entrancy guard — orchestrator rejects start() while running, but
        # we surface it as a user-visible modal here for parity with the prior
        # UX (memory: 2026-05-05 audit user pain point).
        if self.compute.is_running() or getattr(self, '_compute_running', False):
            QMessageBox.information(
                self, "Compute Busy",
                "A computation is already running.\n\n"
                "Click Cancel (the Compute button while it's red) and wait "
                "for the solver to reach its next checkpoint, then re-Compute.")
            return
        # E10 — pre-flight: if the user has any invalid fields flagged by
        # the inline validator, surface them together in a modal instead
        # of letting the solver hit them one at a time.
        if not self._validate_inputs_preflight():
            return
        # Grid-legality preflight — refined shape, inlet/outlet coverage,
        # Richardson budget. Errors block, warnings prompt continue?.
        if not self._preflight_grid():
            return
        # 2026-05-07: high-velocity notice (UI report 2). V&V Standard
        # Tier domain sweep validated u ≤ 10 m/s; above that, SIMPLE
        # outer iterations need ~5-10× the converge time on the
        # Forchheimer branch. Demoted from blocking dialog to non-modal
        # status-bar message on 2026-05-14 — user complained the modal
        # interrupts every run when exploring off-domain configurations.
        # The information remains transparent (paper V&V scope unchanged)
        # but no longer steals focus.
        try:
            uA = float(self.le_uA.text())
            uB = float(self.le_uB.text())
        except (ValueError, AttributeError):
            uA = uB = 0.0
        if uA > VV_VELOCITY_LIMIT_MS or uB > VV_VELOCITY_LIMIT_MS:
            slow = max(uA, uB)
            lo = int(5 * (slow / VV_VELOCITY_LIMIT_MS) ** 2)
            hi = int(10 * (slow / VV_VELOCITY_LIMIT_MS) ** 2)
            self.statusBar().showMessage(
                f"u_A={uA:.1f}, u_B={uB:.1f} m/s outside V&V domain "
                f"(u≤{VV_VELOCITY_LIMIT_MS:.0f} m/s validated). "
                f"Forchheimer-dominated; expect {lo}–{hi}× runtime.",
                15000)
        # Mark compute start so `_end_compute_ui` records elapsed for the
        # status bar clock. 3D branch overwrites with its own clock.
        self._compute_t0 = _time.time()
        # Polygon solver runs on main thread (has its own processEvents)
        if self.combo_shape.currentIndex() > 0:
            self._run_polygon_calculation()
            return

        # 3D dispatch: uniform MVP path (no zoning, Shanghai-style uniform TPMS)
        if hasattr(self, 'combo_dim') and self.combo_dim.currentIndex() == 1:
            self._run_calculation_3d()
            return

        # Validate inputs BEFORE launching solver (Qt-safe on main thread)
        if self._K_ffA is None:
            QMessageBox.warning(self, "Missing Input",
                                "Please click 'Auto-fill Fluid A' first."); return
        if self._K_ffB is None:
            QMessageBox.warning(self, "Missing Input",
                                "Please click 'Auto-fill Fluid B' first."); return

        # B2 2.1b (2026-06-13): the 2D compute path now drives Pipeline2D —
        # the legacy run_calculation_inner(window) entrypoint is deleted.
        # Qt widgets are read EXACTLY ONCE here on the main thread; the
        # worker thread only ever sees the pure ComputeConfig. strict=True
        # reproduces the legacy blank/non-numeric widget validation.
        from controllers.compute_config import ComputeConfig
        try:
            compute_cfg = ComputeConfig.from_qt_window(self, strict=True,
                                                       force_3d=False)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Input", str(e))
            return

        def _2d_worker(cfg, cancel_token, progress_cb):
            self._cancel_token = cancel_token
            from controllers.compute_pipeline import (Pipeline2D,
                                                      CancelledError)
            pipe = Pipeline2D(
                compute_cfg,
                # solver-internal progress writes land on the window attr
                # the ticker polls (same convention the legacy path used)
                progress_cb=lambda p: setattr(self, '_compute_progress',
                                              int(p)),
                cancel_token=cancel_token,
                ui_hooks={
                    'live_residuals': getattr(self, '_live_residuals', None),
                    'iter_label_cb': lambda s: setattr(self,
                                                       '_iter_label_now', s),
                })
            try:
                result = pipe.run()
            except CancelledError:
                # Translate to the orchestrator's own cancel exception so
                # it emits `cancelled` (a foreign exception type would be
                # routed to the error dialog instead).
                raise self.compute.CancelledError()
            self.write_result(result)
            return {}

        self._compute_error = None
        if not self.compute.start('2d', _2d_worker, cfg={}):
            # Should be unreachable due to is_running() guard above; defensive.
            QMessageBox.information(
                self, "Compute Busy",
                "Compute orchestrator rejected start — already running.")
            return
        # Lifecycle now driven entirely by orchestrator signals; the legacy
        # threading.Thread + QTimer poll block is gone (~100 lines deleted).
        return

    def _preflight_3d(self):
        """3D-only input guards (B1 1.4 — extracted from
        _run_calculation_3d so future preflights have ONE home).
        Returns (proceed, est_cells_refined, cell_label).
        """
        # 2026-05-20 UI sweep (Tier 22): pre-initialise Nx_u/Ny_u/Nz_u
        # BEFORE the try. Previously a parse failure (empty field, stray
        # unit text) left `Nz_u` undefined and the guard below raised
        # NameError — turning a bad-input case into a hard crash.
        Nx_u = Ny_u = Nz_u = 0
        try:
            Nx_u = int(self.le_Nx.text()); Ny_u = int(self.le_Ny.text())
            Nz_u = int(self.le_Nz.text())
            est_cells = (Nx_u + 16) * (Ny_u + 16) * (Nz_u + 16)
        except Exception:
            est_cells = 0

        # Nz guard: Nz=1 under 3D dispatch degenerates the z-momentum / z-energy
        # transport and returns a z-uniform field that looks like "T_a = T_inA
        # everywhere" — the user sees a flat-colour cube with scalar-bar min==max
        # and mistakes it for a broken solver. Force at least 2 z-cells for the
        # 3D path; suggest 2D mode otherwise.
        if Nz_u < 2:
            QMessageBox.warning(
                self, "Nz too small for 3D",
                f"Grid Nz = {Nz_u} is too small for 3D compute — the solver "
                f"degenerates to a z-uniform slab and fields look flat.\n\n"
                "Options:\n"
                "  • Increase Nz to 5 or more for a real 3D run (recommended).\n"
                "  • Switch Dimensionality to 2D for single-layer homogeneous cases.")
            return False, 0, ''
        # Large-grid warning (wall-refine expands cells ~6-9x)
        if est_cells > 100_000:
            reply = QMessageBox.question(
                self, "Large 3D Grid",
                f"Estimated refined cells: ~{est_cells:,}\n\n"
                f"With user grid {Nx_u}x{Ny_u}x{Nz_u}, wall-refine expands to "
                f"~{Nx_u+16}x{Ny_u+16}x{Nz_u+16}. This can take many minutes.\n\n"
                "Suggested 3D defaults: Nx=30, Ny=20, Nz=5 (~30 s).\n\n"
                "Proceed anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return False, 0, ''

        # Cell count must reflect the actual refine setting — adding +16 per
        # axis unconditionally inflated the displayed grid by ~5x when refine
        # was OFF and made the ETA estimate way too generous.
        _refine_on = bool(getattr(self, 'chk_wall_refine_3d', None)
                          and self.chk_wall_refine_3d.isChecked())
        if _refine_on:
            Nx_r, Ny_r, Nz_r = Nx_u + 16, Ny_u + 16, Nz_u + 16
            _cell_label = f"refined {Nx_r}×{Ny_r}×{Nz_r}"
        else:
            Nx_r, Ny_r, Nz_r = Nx_u, Ny_u, Nz_u
            _cell_label = f"{Nx_r}×{Ny_r}×{Nz_r}"
        return True, Nx_r * Ny_r * Nz_r, _cell_label

    def _run_calculation_3d(self):
        """Threaded 3D solve → auto-switch to 3D View tab on success."""
        # Re-entrancy guard — same rationale as 2D run_calculation. Without
        # this a fast re-Compute spawned two QTimer instances + two threads,
        # both alive, racing to call _finalize_plots_3d().
        if getattr(self, '_compute_running', False):
            QMessageBox.information(
                self, "Compute Busy",
                "A 3D computation is already running.\n\n"
                "Click Cancel (red Compute button) and wait for the solver "
                "to reach its next checkpoint, then re-Compute.")
            return
        # Do not initialise PyVista/VTK on button click. The GL context is
        # expensive and made Compute feel frozen before progress appeared;
        # finalize_plots_3d creates/populates the panel after the solve.

        ok, est_cells_r, _cell_label = self._preflight_3d()
        if not ok:
            return

        # B2 2.1c (2026-06-13): the 3D compute path drives Pipeline3D —
        # the legacy run_calculation_3d_inner(window) entrypoint is
        # deleted. Qt widgets are read exactly once HERE on the main
        # thread (before the UI locks, so a validation error leaves the
        # window usable).
        from controllers.compute_config import ComputeConfig
        try:
            compute_cfg = ComputeConfig.from_qt_window(self, strict=True,
                                                       force_3d=True)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Input", str(e))
            return

        self._compute_t0 = _time.time()
        self._begin_compute_ui(
            status=f"Computing 3D ({_cell_label} = "
                   f"{est_cells_r:,} cells, compressible dual-fluid SIMPLE; "
                   f"typical ~2-10 min)…")

        # ComputeOrchestrator path (Plan #4 P1.3 — A.3, 2026-05-06).
        # Replaces the legacy threading.Thread + 600 s poll _check closure.
        # Hard wall-clock budget implemented as a separate QTimer
        # that calls self.compute.cancel() — orchestrator forwards as
        # cooperative cancel to the worker, which exits at next checkpoint.
        from PySide6.QtCore import QTimer

        def _3d_worker(cfg, cancel_token, progress_cb):
            self._cancel_token = cancel_token
            from controllers.compute_pipeline import (Pipeline3D,
                                                      CancelledError)
            pipe = Pipeline3D(
                compute_cfg,
                progress_cb=lambda p: setattr(self, '_compute_progress',
                                              int(p)),
                cancel_token=cancel_token,
                ui_hooks={'iter_cb': lambda k, n: setattr(
                    self, '_iter_label_now', f"outer {k}/{n}")})
            try:
                result = pipe.run()
            except CancelledError:
                raise self.compute.CancelledError()
            self.write_result(result)
            return {}

        self._compute_error = None
        if not self.compute.start('3d', _3d_worker, cfg={'est_cells': est_cells_r}):
            QMessageBox.information(
                self, "Compute Busy",
                "3D compute orchestrator rejected start — already running.")
            return

        # Status updater on a separate QTimer (orchestrator handles the
        # thread; this is a UI-only ticker that reports elapsed wall-clock +
        # the solver's outer-iteration label, and enforces a hard wall-clock
        # budget). ETA *prediction* was dropped 2026-06-01 — see _tick_3d.
        wd = QTimer(self)
        self._compute_3d_watchdog = wd
        _hard_timeout_s = 1800.0   # 30 min — generous for high-u + dense grids

        def _tick_3d():
            if not self.compute.is_running():
                wd.stop()
                return
            elapsed = _time.time() - self._compute_t0
            if elapsed > _hard_timeout_s:
                self.statusBar().showMessage(
                    f"3D compute exceeded {int(_hard_timeout_s)}s budget "
                    "— auto-cancelling at next checkpoint.", 8000)
                self.compute.cancel()
                wd.stop()
                return
            # ETA prediction removed 2026-06-01: the linear cell-scaling model
            # (cells/35k × 150s × (u/10)²) was calibrated on low-Re Shanghai
            # cases and wildly under-estimated high-u / dense-3D runs (e.g.
            # 8k cells @ u=20 estimated ~2 min, actually 8 min+). 3D LTNE wall-
            # clock is non-linear in cells AND Re, so any cheap projection
            # misleads. Show honest live progress instead: elapsed + cells +
            # the outer-iteration label (set by the solver via _iter_label_now).
            from ui.fmt import duration as _fmt
            label = getattr(self, '_iter_label_now', None)
            iter_txt = f" • {label}" if label else ""
            self.statusBar().showMessage(
                f"Computing 3D… {_fmt(elapsed)} elapsed "
                f"({est_cells_r:,} cells){iter_txt} • solver running")
        wd.timeout.connect(_tick_3d)
        wd.start(500)
        return

    def _run_polygon_calculation(self):
        from runs.polygon_calc import run_polygon_calculation
        return run_polygon_calculation(self)

    def _finalize_plots(self):
        """Thin wrapper — delegates to run_calculation module (Task B.9).
        Freezes repaints around the multi-canvas population so the user
        sees one clean frame flip instead of five intermediate paints."""
        from ui.plot_2d_results import finalize_plots
        self.setUpdatesEnabled(False)
        try:
            out = finalize_plots(self)
        finally:
            self.setUpdatesEnabled(True)
        # 2026-05-22 (UI report point 1): finalize_plots renders the
        # temp/pres/vel canvases but never recorded them in _drawn_tabs, so
        # Export Figure's picker only listed "Geometry" after a 2D compute.
        # Mark them here (mirrors the 3D path's drawn.add at main.py ~4207).
        # layout/pareto are marked by their own draw routines.
        drawn = getattr(self, '_drawn_tabs', set())
        drawn.update({'temp', 'pres', 'vel'})
        self._drawn_tabs = drawn
        self._push_recent_run()
        return out

    def write_result(self, result):
        """Copy a :class:`controllers.compute_pipeline.ComputeResult`
        onto the legacy window attributes (``_compute_results`` dict,
        ``_compute_warnings``, ``_extrap_reasons``, ``_K_ff*``,
        ``_rho_*``, ``_mu_*``, ``_h_v*``, ``_zone_*``) so the existing
        finalize_plots / redraw_temperature_panel renderers keep
        working when the compute path runs via
        :class:`controllers.compute_pipeline.Pipeline2D` instead of
        the legacy ``runs.run_calculation.run_calculation_inner``.

        Audit C4 (L-a-2, 2026-05-28). This is the *UI adapter*
        counterpart to ``_finalize_cfg`` — together they replace the
        pre-C4 ``runs.run_calculation._store_results(window, cfg, raw)``
        which conflated UI writes with result assembly. Since B2 2.1b/c
        (2026-06-13) this is the ONLY ComputeResult→window copy: the GUI
        worker drives Pipeline2D/3D and the legacy
        ``run_calculation_inner`` / ``run_calculation_3d_inner`` paths
        are deleted.
        """
        # ── 3D branch: the renderer (ui/plot_3d_results) consumes the
        # raw _run_3d_stack dict directly; publish the transitional
        # carrier by reference and stop — no key loss possible.
        raw3d = result.diagnostics.get('raw_3d')
        if raw3d is not None:
            self._result_3d = raw3d
            self._extrap_reasons = list(result.extrap_reasons)
            self._has_extrap = bool(result.extrap_reasons)
            return

        f = result.fields
        self._compute_results = {
            'Ta': f.get('Ta'), 'Tb': f.get('Tb'), 'Ts': f.get('Ts'),
            'ucA': f.get('ucA'), 'vcA': f.get('vcA'),
            'ucB': f.get('ucB'), 'vcB': f.get('vcB'),
            'P_fA': f.get('P_fA'), 'P_fB': f.get('P_fB'),
            'dP_A': result.dP_A_Pa, 'dP_B': result.dP_B_Pa,
            'Q_total': result.Q_W,
            'N_x': f.get('N_x'), 'N_y': f.get('N_y'),
            'L': f.get('L'), 'H': f.get('H'),
            'dir_A': f.get('dir_A'), 'dir_B': f.get('dir_B'),
            'zone_config': f.get('zone_config'),
            'za': f.get('za'),
            'dx_arr': f.get('dx_arr'), 'dy_arr': f.get('dy_arr'),
            # (residuals_A/B snapshots dropped — they only fed the removed 2D
            # convergence plot; the solver still tracks residuals internally.)
            'Q_A': result.residuals.get('Q_A', float('nan')),
            'Q_B': result.residuals.get('Q_B', float('nan')),
            'Q_net': result.residuals.get('Q_net', float('nan')),
            'energy_imbalance_rel': result.residuals.get(
                'energy_imbalance_rel', float('nan')),
        }
        # Slider/export caches — the legacy _run_solvers wrote these
        # directly onto the window (run_calculation.py Step-2 tail); on
        # the Pipeline path those writes land on the shim and vanish, so
        # mirror them here ([np.newaxis] wrap = legacy 3D-compat shape).
        import numpy as _np
        self.T_fA = (f['Ta'][_np.newaxis] if f.get('Ta') is not None
                     else None)
        self.T_fB = (f['Tb'][_np.newaxis] if f.get('Tb') is not None
                     else None)
        self.T_s = (f['Ts'][_np.newaxis] if f.get('Ts') is not None
                    else None)
        self._compute_warnings = list(result.warnings)
        self._extrap_reasons = list(result.extrap_reasons)
        self._has_extrap = bool(result.extrap_reasons)

        # Fluid + porous coefficients — UI Fluids panel reads these
        # after Auto-Fill; Pipeline path recomputes them from cfg, so
        # forward to keep the read-out panel consistent.
        for _key in ('K_ffA', 'K_ffB', 'K_ss', 'h_vA', 'h_vB'):
            _val = result.coeffs.get(_key)
            if _val is not None:
                setattr(self, f'_{_key}', _val)
        for _key in ('rho_A', 'rho_B', 'mu_A', 'mu_B'):
            _val = result.props.get(_key)
            if _val is not None:
                setattr(self, f'_{_key}', _val)

        # Zone stats (None when zones disabled).
        if result.zones is not None:
            self._zone_axis_dir = result.zones.get('axis_dir')
            self._zone_stats = result.zones.get('stats')
            self._zone_boundaries = result.zones.get('boundaries')
            self._zone_boundaries_x = result.zones.get('boundaries_x')
            self._zone_boundaries_y = result.zones.get('boundaries_y')
        else:
            self._zone_stats = None
            self._zone_axis_dir = None
            self._zone_boundaries = None
            self._zone_boundaries_x = None
            self._zone_boundaries_y = None

    def _on_orch_started(self, mode):
        """Compute kicked off. Lock UI + start progress widgets."""
        self._begin_compute_ui()
        # Backwards-compat: tests / external code still read _compute_running.
        # We mirror it from the orchestrator's authoritative flag.
        self._compute_running = True
        # Fresh per-run log buffer for the D9 solve-log viewer.
        self._last_solve_log = ""
        # Start a small UI-only progress poll (orchestrator handles thread
        # lifecycle; this just renders self._compute_progress on the bar).
        # Live residuals already drained separately via _drain_live_residuals.
        from PySide6.QtCore import QTimer
        self._compute_progress = 10
        if getattr(self, '_compute_poll_timer', None) is not None:
            try:
                self._compute_poll_timer.stop()
            except Exception:
                pass
        timer = QTimer(self)
        self._compute_poll_timer = timer

        def _tick_progress():
            if not self.compute.is_running():
                timer.stop()
                return
            self.progress.setValue(min(90, self._compute_progress))
        timer.timeout.connect(_tick_progress)
        timer.start(200)

    def _on_orch_progress(self, percent):
        """Worker emitted explicit progress (rare for current solver). Render."""
        self.progress.setValue(min(100, max(0, int(percent))))

    def _on_orch_finished(self, _result_dict):
        """Compute succeeded. Render plots + push to recent runs ring.

        Mode-aware: 2D path calls _finalize_plots (matplotlib canvases).
        3D path calls finalize_plots_3d (PyVista panel) + sets _has_results_3d.
        Polygon path runs on main thread (does not pass through orch).
        """
        self._compute_running = False
        self._last_solve_log = self.compute.last_log()
        # Stop the progress timer if still running.
        t = getattr(self, '_compute_poll_timer', None)
        if t is not None:
            try:
                t.stop()
            except Exception:
                pass
        # Stop any 3D wall-clock budget watchdog that may still be alive.
        wd = getattr(self, '_compute_3d_watchdog', None)
        if wd is not None:
            try:
                wd.stop()
            except Exception:
                pass

        # Flip the Compute button back to "▶ Compute" BEFORE running the
        # plot finalisation — otherwise heavy 3D PyVista rendering or 2D
        # matplotlib draw blocks the main thread for 1-2 s and the user
        # sees stale "Cancel (Computing…)" label even after the solver
        # has finished. The button repaint only flushes when the event
        # loop ticks, so we let it tick first via processEvents().
        # (UI report 2026-05-07 issues #2 + #3.)
        self._end_compute_ui(success=True)
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
        except Exception:
            pass

        mode = self.compute.current_mode()
        if mode == '3d':
            from ui.plot_3d_results import finalize_plots_3d
            # 2026-06-02 fix: do NOT pre-clear ``_has_results_3d`` here. In the
            # live window that flag is a ResultCache bridge whose setter
            # (main.Main_Menu._has_results_3d) DELETES ``_result_3d`` — which
            # finalize_plots_3d must read to render the panel. The old C5 H5
            # line ``self._has_results_3d = False`` destroyed the freshly-
            # computed result *before* finalize ran, so finalize saw
            # ``_result_3d is None`` and every 3D run rendered nothing. The
            # worker always writes a fresh result before this slot fires, so
            # there is no "stale True from a prior run" to guard against here;
            # the H5 invariant (no stale flag after a finalize *crash*) is now
            # enforced in the except branch below. (The H5 unit test passed
            # despite the prod bug because its DummyWindow used plain attrs,
            # decoupling the flag from the result — the real bridge couples
            # them.)
            _finalize_ok = False
            _3d_vis_ok = False
            try:
                # 2026-05-20 UI sweep: finalize_plots_3d now returns a bool
                # indicating whether the embedded PyVistaQt panel was
                # populated. Previously it returned None and all visualisation
                # failures were silently swallowed inside the function,
                # producing a "status bar says done but canvas is blank"
                # mismatch. We gate `_has_results_3d` + tab auto-switch on
                # the returned flag so the user is no longer routed to an
                # empty 3D tab.
                _3d_vis_ok = bool(finalize_plots_3d(self))
                try:
                    self._push_recent_run()
                except Exception:
                    pass
                _finalize_ok = True
            except Exception as _fe3d:
                # If finalise crashes, walk the button text back to a
                # benign state — _end_compute_ui already restored it but
                # the flag must reflect failure for downstream gating.
                # Surface the traceback (the 3D path used to swallow it,
                # leaving "status bar says done / canvas blank" with no
                # console clue — matches the 2D path's diagnostics now).
                import traceback
                traceback.print_exc()
                # H5 invariant: a finalize crash must not leave a stale
                # ``_has_results_3d == True`` (which would auto-switch the next
                # run to a blank 3D tab). Clear it here — in the live window
                # this also drops the now-unrenderable result via the bridge,
                # which is correct since the panel never populated.
                self._has_results_3d = False
                self._end_compute_ui(success=False)
                self.statusBar().showMessage(
                    f"3D visualisation failed: {_fe3d!r} — solver finished, "
                    f"render crashed; check console.", 12000)
            if not _finalize_ok:
                return
            self._has_results = True
            # Only mark the 3D View tab as ready if the PyVistaQt panel
            # actually populated. Otherwise leave the flag False so the
            # tab stays disabled and the user is not silently switched
            # to a blank canvas.
            self._has_results_3d = _3d_vis_ok
            for _bname in ('btn_export',):
                if hasattr(self, _bname):
                    getattr(self, _bname).setEnabled(True)
            drawn = getattr(self, '_drawn_tabs', set())
            if _3d_vis_ok:
                drawn.add('3d')
            if getattr(self, '_rendered_3d_slices', False):
                for k in ('temp', 'pres', 'vel'):
                    drawn.add(k)
            self._drawn_tabs = drawn
            self._update_tab_visibility()
            if _3d_vis_ok:
                self._switch_tab('3d')
            res = getattr(self, '_result_3d', {})
            # Outer-coupling convergence note: the SIMPLE↔LTNE loop exits
            # early once max|ΔTa| < tol, so it usually stops before the cap
            # (e.g. "3/5"). Surface that as "converged after k/N" instead of a
            # bare count, so the user does not read an early exit as an
            # unfinished run. len(_ltne_info) = outers actually executed.
            def _outer_note(r):
                try:
                    info = r.get('_ltne_info') or []
                    n_run = len(info)
                    n_max = int(r.get('_max_outer', n_run) or n_run)
                    if n_run and n_run < n_max:
                        return f"  ·  converged after {n_run}/{n_max} outer"
                    if n_run:
                        return f"  ·  ran full {n_run}/{n_max} outer (cap)"
                except Exception:
                    pass
                return ""
            try:
                if res and _3d_vis_ok:
                    self.statusBar().showMessage(
                        f"3D done — Q={res.get('Q', 0):.1f} W  "
                        f"dP={res.get('dP', 0):.0f} Pa{_outer_note(res)}", 8000)
                elif res:
                    # Solver succeeded but visualisation did not — surface
                    # explicitly so the user knows numbers are valid but the
                    # rendered canvas is not.
                    self.statusBar().showMessage(
                        f"3D solve done (Q={res.get('Q', 0):.1f} W  "
                        f"dP={res.get('dP', 0):.0f} Pa) — visualisation "
                        f"failed; check console.", 10000)
                else:
                    # finalize returned False with no stashed result dict —
                    # always clear the frozen "outer k/N running" left by the
                    # last _tick_3d paint so the status bar reflects reality.
                    self.statusBar().showMessage(
                        "3D compute finished but produced no result — "
                        "visualisation unavailable; check console.", 10000)
            except Exception:
                pass
            return

        # 2D mode (default) — _end_compute_ui already called above.
        # 2026-05-09 — wrap finalize_plots so a panel crash (e.g. NaN
        # contourf, water-side LTNE divergence) does NOT block 2D View
        # from unlocking. The user still benefits from valid velocity /
        # pressure canvases even when one panel fails to render.
        _finalize_ok = True
        try:
            self._finalize_plots()
        except Exception as _fe:
            _finalize_ok = False
            import traceback
            traceback.print_exc()
            self.statusBar().showMessage(
                f"Plot finalize failed: {_fe!r} — partial 2D View available.",
                8000)
        self._has_results = True
        self._has_results_2d = True
        self._update_tab_visibility()
        for _bname in ('btn_export',):
            if hasattr(self, _bname):
                getattr(self, _bname).setEnabled(True)
        self._switch_tab('temp')
        if _finalize_ok:
            self.statusBar().showMessage("Done.", TOAST_MS_MED)

    def _on_orch_error(self, message, log_text):
        """Compute raised. Show error + drop stale results (mode-aware)."""
        self._compute_running = False
        self._compute_error = message
        self._last_solve_log = log_text
        t = getattr(self, '_compute_poll_timer', None)
        if t is not None:
            try:
                t.stop()
            except Exception:
                pass
        wd = getattr(self, '_compute_3d_watchdog', None)
        if wd is not None:
            try:
                wd.stop()
            except Exception:
                pass

        mode = self.compute.current_mode()
        if mode == '3d':
            self._result_3d = None
            self._has_results_3d = False
            if not getattr(self, '_has_results_2d', False):
                self._has_results = False
            for _bname in ('btn_export',):
                if hasattr(self, _bname):
                    getattr(self, _bname).setEnabled(False)
            self._update_tab_visibility()
            self._end_compute_ui(success=False)
            # User-cancel or timeout already surfaced as cancelled signal —
            # if we reach here it's a real error.
            QMessageBox.critical(self, "3D Compute Error", message)
            return

        # 2D / poly fallback
        self._compute_results = {}
        self._has_results_2d = False
        if not getattr(self, '_has_results_3d', False):
            self._has_results = False
        for _bname in ('btn_export',):
            if hasattr(self, _bname):
                getattr(self, _bname).setEnabled(False)
        self._update_tab_visibility()
        self._end_compute_ui(success=False)
        QMessageBox.critical(self, "Compute Error", message)
        try:
            from ui.microanim import toast as _toast
            _toast(self, f"Compute failed — {message[:80]}",
                   kind='error',
                   copy_payload=log_text or message)
        except Exception:
            pass

    def _on_orch_cancelled(self, log_text):
        """Worker observed cancel_token. Treat as soft completion (mode-aware)."""
        self._compute_running = False
        self._last_solve_log = log_text
        t = getattr(self, '_compute_poll_timer', None)
        if t is not None:
            try:
                t.stop()
            except Exception:
                pass
        wd = getattr(self, '_compute_3d_watchdog', None)
        if wd is not None:
            try:
                wd.stop()
            except Exception:
                pass

        mode = self.compute.current_mode()
        if mode == '3d':
            # 3D-specific: drop result + status message
            self._result_3d = None
            self._has_results_3d = False
            self._update_tab_visibility()
            self._end_compute_ui(success=False)
            self.statusBar().showMessage(
                "3D compute aborted (cancelled or timed-out).", 6000)
            return

        self._end_compute_ui(success=False)
        self.statusBar().showMessage("Cancelled.", TOAST_MS_SHORT)

    def _begin_compute_ui(self, status="Computing…"):
        """Lock the header Compute button + surface the progress bar so the
        user sees an obvious "I'm working" signal. Also hides the canvas
        empty-state hint in case it was still showing."""
        self.progress.show()
        self.progress.setValue(10)
        # Reset + reveal the live residual sparkline. A timer drains the
        # shared buffer every 300 ms while the compute thread runs.
        self._live_residuals = {'A': [], 'B': []}
        if hasattr(self, '_sb_live_resid'):
            self._sb_live_resid.clear_data()
            self._sb_live_resid.show()
        if not hasattr(self, '_live_resid_timer'):
            from PySide6.QtCore import QTimer as _QT_lr
            t = _QT_lr(self)
            # 120 ms poll (~8 Hz) — frequent enough that the sparkline
            # tracks the solver within a frame-ish budget on a 144 Hz
            # display, cheap enough that the drain is a no-op most ticks.
            t.setInterval(120)
            t.timeout.connect(self._drain_live_residuals)
            self._live_resid_timer = t
        self._live_resid_timer.start()
        # Cooperative cancel: clear the flag at compute start, then repurpose
        # the Compute button as a Cancel button. The worker polls
        # `_compute_cancel` at outer-iteration boundaries (the only safe
        # interrupt point — JIT'd inner sweeps can't be killed mid-run).
        self._compute_cancel = False
        if hasattr(self, 'btn_compute'):
            # Idempotent re-save guard: _begin_compute_ui is called twice per
            # run — once directly from run_calculation/_run_calculation_3d, then
            # again from _on_orch_started (the orchestrator's `started` signal,
            # which fires BEFORE _compute_running is set). Never save a
            # "Cancel…" string as the "original" text, else _end_compute_ui
            # restores the button to "Cancel · 0.0s" instead of "▶ Compute"
            # (button stuck frozen after the run). The real Compute label never
            # starts with "Cancel", so this is order-independent.
            _cur_btn_text = self.btn_compute.text()
            if not _cur_btn_text.startswith("Cancel"):
                self._btn_compute_text_saved = _cur_btn_text
            # ETA text removed 2026-05-14 — median-of-history misled when
            # config changed. Live elapsed + iter counter via _tick_btn.
            self._iter_label_now = None
            self.btn_compute.setText("Cancel  ·  0.0s")
            self.btn_compute.setEnabled(True)
            self._begin_btn_ticker()
            # Surgical disconnect of the *exact* current handler (run_calculation
            # or a stale Cancel handler from prior run). disconnect() with no
            # args was nuking *all* clicked slots, which let stray reconnects
            # accumulate after a failed compute (compute hang on re-click).
            prev = getattr(self, '_compute_btn_handler', None)
            if prev is not None:
                try:
                    self.btn_compute.clicked.disconnect(prev)
                except (TypeError, RuntimeError):
                    pass
            else:
                # First-time path — drop the constructor's run_calculation
                # connection (we'll re-add via _end_compute_ui).
                try:
                    self.btn_compute.clicked.disconnect(self.run_calculation)
                except (TypeError, RuntimeError):
                    pass
            self._compute_btn_handler = self._on_cancel_compute
            self.btn_compute.clicked.connect(self._compute_btn_handler)
        if hasattr(self, '_empty_state_label'):
            self._empty_state_label.setVisible(False)
        self.statusBar().showMessage(status)
        QApplication.processEvents()

    def _end_compute_ui(self, success):
        """Restore Compute button and either fade out progress (success) or
        hide immediately (failure). On success also refreshes the headline
        result summary bar from the detail-value labels.

        Idempotent on re-entrancy: also clears the compute-running flag and
        stops/clears the polling timer + thread refs so a second click on
        Compute starts cleanly without orphan timers polling stale closures.
        """
        # Tear down compute lifecycle state FIRST so a fast re-click doesn't
        # see _compute_running == True and bail out.
        self._compute_running = False
        old_timer = getattr(self, '_compute_poll_timer', None)
        if old_timer is not None:
            try:
                old_timer.stop()
            except Exception:
                pass
        self._compute_poll_timer = None
        self._compute_thread = None
        # Stop the elapsed/iter button-text ticker (paired with
        # _begin_btn_ticker). Idempotent — silently no-ops when absent.
        bt = getattr(self, '_btn_ticker_timer', None)
        if bt is not None:
            try:
                bt.stop()
            except Exception:
                pass
        self._iter_label_now = None
        if hasattr(self, 'btn_compute'):
            self.btn_compute.setEnabled(True)
            self.btn_compute.setText(
                getattr(self, '_btn_compute_text_saved', '▶  &Compute'))
            # Restore the original Compute click handler. Surgical
            # disconnect of the *exact* current handler avoids dropping
            # third-party connections (e.g. shortcut bridges).
            prev = getattr(self, '_compute_btn_handler', None)
            if prev is not None:
                try:
                    self.btn_compute.clicked.disconnect(prev)
                except (TypeError, RuntimeError):
                    pass
            self._compute_btn_handler = self.run_calculation
            self.btn_compute.clicked.connect(self._compute_btn_handler)
        if success:
            self.progress.setValue(100)
            from PySide6.QtCore import QTimer as _QT
            _QT.singleShot(500, self.progress.hide)
            self._update_result_summary()
            # Record the elapsed wall-clock for the status bar clock.
            t0 = getattr(self, '_compute_t0', None)
            elapsed = None
            if t0 is not None:
                elapsed = _time.time() - t0
                self._last_elapsed_s = elapsed
            self._refresh_status_bar()
            # D8 — stamp provenance tooltip on every result label so users
            # can trace "where did this number come from" without guessing.
            self._stamp_result_provenance(elapsed or 0.0)
            # Stop the live-residual sparkline timer + hide widget.
            lrt = getattr(self, '_live_resid_timer', None)
            if lrt is not None:
                lrt.stop()
            if hasattr(self, '_sb_live_resid'):
                self._sb_live_resid.hide()
            self._live_resid_cursor = 0
            # Micro-anim polish: pulse the result chips + floating toast.
            try:
                from ui.microanim import pulse_glow, toast
                for key in ('Q', 'dPA', 'dPB'):
                    chip = self._res_chips.get(key) if hasattr(
                        self, '_res_chips') else None
                    if chip is not None:
                        pulse_glow(chip, color='#22C55E',
                                    blur_peak=20, duration_ms=550)
                if elapsed is not None:
                    toast(self, f"Compute done · {_fmt_dur(elapsed)}", kind='success')
                else:
                    toast(self, "Compute done", kind='success')
                # E4 — if user is still on Geometry tab, nudge them to
                # look at results by pulsing the first available result tab.
                if getattr(self, '_active_tab', None) == 'layout':
                    is_3d = (hasattr(self, 'combo_dim')
                              and self.combo_dim.currentIndex() == 1)
                    nxt = self.btn_tab_3d if is_3d else self.btn_tab_temp
                    if nxt is not None and nxt.isEnabled():
                        pulse_glow(nxt, color='#3B82F6',
                                    blur_peak=22, duration_ms=700)
            except Exception:
                pass
        else:
            self.progress.hide()
            lrt = getattr(self, '_live_resid_timer', None)
            if lrt is not None:
                lrt.stop()
            if hasattr(self, '_sb_live_resid'):
                self._sb_live_resid.hide()
            self._live_resid_cursor = 0

    def _on_cancel_compute(self):
        """User clicked the Compute button while a solve was running, so it
        is currently labelled "Cancel". Set the flag the worker polls; the
        button stays disabled until the worker reaches the next checkpoint
        and returns through `_check`."""
        self._compute_cancel = True
        # B2 2.1c: the Pipeline path polls the orchestrator CancelToken
        # (token.cancelled), not the window flag — bridge both cancel
        # mechanisms onto the token so either converges.
        try:
            self.compute.cancel()
        except Exception:
            pass
        if hasattr(self, 'btn_compute'):
            self.btn_compute.setEnabled(False)
            self.btn_compute.setText("Cancelling…")
        self.statusBar().showMessage(
            "Cancel requested — waiting for solver to finish current sweep…",
            6000)

    def _active_compute_mode(self):
        """'2d' / '3d' / 'poly' depending on current UI selection. Used by
        the ETA helper so 2D reheats don't skew 3D predictions."""
        try:
            if hasattr(self, 'combo_shape') and self.combo_shape.currentIndex() > 0:
                return 'poly'
            if hasattr(self, 'combo_dim') and self.combo_dim.currentIndex() == 1:
                return '3d'
        except Exception:
            pass
        return '2d'

    def _update_result_summary(self):
        """Mirror the headline numbers from the detail result labels into the
        prominent canvas-top summary bar. No-op if the bar was not built.

        Pro-Max upgrade: each chip compares against the previous successful
        run (stored in `_recent_runs[1]` — index 0 is the run just pushed
        by `_finalize_plots`). Positive deltas green for Q (more heat is
        better), negative deltas green for ΔP (lower drop is better).
        Neutral gray when no prior run exists or values are identical.
        """
        if not hasattr(self, '_res_chips') or not hasattr(self, '_result_summary_bar'):
            return
        chips = self._res_chips
        def _get(attr):
            w = getattr(self, attr, None)
            if w is None:
                return None
            t = w.text().strip()
            return t if t and t != '—' else None

        # Direction: which way is "good"?  "up" → green when increased.
        pairs = [
            ('Q',     '_r_Q',     'up',      'Q'),
            ('dPA',   '_r_dP_A',  'down',    'dP_A'),
            ('dPB',   '_r_dP_B',  'down',    'dP_B'),
            ('ToutA', '_r_ToutA', 'neutral', 'ToutA'),
            ('ToutB', '_r_ToutB', 'neutral', 'ToutB'),
        ]

        prev = None
        recents = getattr(self, '_recent_runs', None)
        if recents is not None and len(recents) >= 2:
            prev = recents[1]  # index 0 is the run we just finalised

        from ui.theme import get_theme as _gt
        _t = _gt()
        _up_good = _t.get('accent_green', '#22C55E')
        _bad = '#F87171'
        _neutral = _t.get('sub_fg', '#94A3B8')

        shown_any = False
        for key, attr, direction, rec_key in pairs:
            chip = chips.get(key)
            if chip is None:
                continue
            v = _get(attr)
            if not v:
                chip.setText('—')
                # Clear any previously rendered delta label.
                _dl = getattr(chip, '_delta_label', None)
                if _dl is not None:
                    _dl.setText('')
                continue
            shown_any = True
            chip.setText(v)
            _dl = getattr(chip, '_delta_label', None)
            if _dl is None or prev is None or direction == 'neutral':
                if _dl is not None:
                    _dl.setText('')
                continue
            try:
                cur_f = float(v)
                prev_txt = (prev.get(rec_key) or '').strip()
                prev_f = float(prev_txt)
                if abs(prev_f) < 1e-12:
                    _dl.setText('')
                    continue
                pct = (cur_f - prev_f) / abs(prev_f) * 100.0
                arrow = '↑' if pct > 0 else ('↓' if pct < 0 else '·')
                good = (direction == 'up' and pct > 0) or \
                       (direction == 'down' and pct < 0)
                col = _up_good if good else (_bad if abs(pct) > 1e-3 else _neutral)
                _dl.setText(f"{arrow}{abs(pct):.1f}%")
                _dl.setStyleSheet(
                    f"color:{col}; font-size:8pt; font-weight:bold;"
                    "background:transparent; border:none; padding-left:4px;")
            except Exception:
                _dl.setText('')
        # UI report 2026-05-07 issue #5: the headline summary chips (Q /
        # ΔP A / ΔP B / T_out A / T_out B) are redundant with the detail
        # result frame on the Geometry page (build_page_domain). Suppress
        # the chip strip when the user is on the Geometry tab — it adds
        # value as a persistent reminder on Temperature/Pressure/Velocity/
        # 3D tabs where the inputs aren't visible.
        on_geom = (getattr(self, '_active_tab', None) == 'layout')
        self._result_summary_bar.setVisible(shown_any and not on_geom)

    def _begin_btn_ticker(self):
        """500 ms ticker driving the Compute/Cancel button live text."""
        from PySide6.QtCore import QTimer as _QT_btn
        t = getattr(self, '_btn_ticker_timer', None)
        if t is None:
            t = _QT_btn(self)
            t.setInterval(500)
            t.timeout.connect(self._tick_btn)
            self._btn_ticker_timer = t
        t.start()

    def _tick_btn(self):
        """Refresh button text with `Cancel · <dur> [· iter k/N]`. The iter
        suffix is omitted when the solver has not published a label
        (e.g. 3D path before its coupling loop starts)."""
        if not hasattr(self, 'btn_compute'):
            return
        t0 = getattr(self, '_compute_t0', None)
        if t0 is None:
            return
        elapsed = _time.time() - t0
        label = getattr(self, '_iter_label_now', None)
        suffix = f"  ·  {label}" if label else ""
        new_text = f"Cancel  ·  {_fmt_dur(elapsed)}{suffix}"
        # Skip setText when nothing changed — saves Qt repaint churn at
        # 500 ms tick when sub-second elapsed rounds to same string.
        if self.btn_compute.text() != new_text:
            self.btn_compute.setText(new_text)

    def _drain_live_residuals(self):
        """Timer tick — push the Fluid A residual trail (log scale) into
        the status-bar sparkline. Reads + clears any new samples from
        `_live_residuals['A']` to bound memory."""
        buf = getattr(self, '_live_residuals', None) or {}
        spark = getattr(self, '_sb_live_resid', None)
        if spark is None or not buf:
            return
        lst = buf.get('A') or []
        # Grab what's new since last drain; cursor stored on the timer.
        cursor = getattr(self, '_live_resid_cursor', 0)
        new_items = lst[cursor:]
        self._live_resid_cursor = len(lst)
        import math as _math_lr
        for _it, r in new_items:
            # Log10 transform so the 6-decade convergence fan fits into
            # the 20-pixel sparkline height usefully.
            try:
                spark.push(_math_lr.log10(max(r, 1e-20)))
            except Exception:
                pass
