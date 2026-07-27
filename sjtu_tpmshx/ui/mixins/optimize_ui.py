"""Multi-objective optimization + quick-design launchers for ``Main_Menu``.

Extracted from the ``main`` god object: the qNEHVI zone-optimization panel
handlers (run/cancel, Pareto show/reshow/pick, save, load-solution) — all thin
delegators to ``ui.optimize_panel`` — plus the quick-design dialog launcher.

Pure UI glue, no solver / numeric path. Adopted via
``class Main_Menu(..., OptimizeUIMixin, ..., QMainWindow)``; external callers
(ui/ui_builders.py button wiring, ui/command_palette.py, the Ctrl+Enter
shortcut, ui/optimize_panel.py's own getattr bind points) keep working because
the names still resolve on the live window through the MRO.

No module-level imports — every handler lazy-imports its callable exactly as
the originals did.
"""

from __future__ import annotations


class OptimizeUIMixin:
    """Zone-optimization panel handlers + quick-design launcher."""

    # ── multi-objective optimization (delegate to ui.optimize_panel) ──────
    def _run_optimize(self):
        from sjtu_tpmshx.ui.optimize_panel import run_optimize
        return run_optimize(self)

    def _cancel_optimize(self):
        from sjtu_tpmshx.ui.optimize_panel import cancel_optimize
        return cancel_optimize(self)

    def _reshow_pareto(self):
        from sjtu_tpmshx.ui.optimize_panel import reshow_pareto
        return reshow_pareto(self)

    def _show_pareto(self, res):
        from sjtu_tpmshx.ui.optimize_panel import show_pareto
        return show_pareto(self, res)

    def _on_pareto_pick(self, event):
        from sjtu_tpmshx.ui.optimize_panel import on_pareto_pick
        return on_pareto_pick(self, event)

    def _save_opt_results(self, res, cfg):
        from sjtu_tpmshx.ui.optimize_panel import save_opt_results
        return save_opt_results(self, res, cfg)

    def _load_pareto_solution(self, x):
        from sjtu_tpmshx.ui.optimize_panel import load_pareto_solution
        return load_pareto_solution(self, x)

    # ── quick-design tool (Phase 2 Task 4) ───────────────────────────────
    def _open_quick_design(self):
        from sjtu_tpmshx.ui.quick_design_panel import build_quick_design_dialog
        if getattr(self, "_qd_dialog", None) is None:
            self._qd_dialog = build_quick_design_dialog(self)
        self._qd_dialog.show()
        self._qd_dialog.raise_()
