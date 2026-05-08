"""
ui/optimize_panel.py — UI bindings for the continuous-field qNEHVI optimizer.

Replaces the retired patch-zoning panel. Public surface preserved so main.py's
lazy-imported handler methods (``_run_optimize``, ``_cancel_optimize``,
``_reshow_pareto``, ``_show_pareto``, ``_on_pareto_pick``,
``_save_opt_results``, ``_load_pareto_solution``) remain valid bind points.

This is a minimal but functional first cut:

  * background QThread runs ``run_qnehvi`` so the UI stays responsive;
  * progress callback updates a status string + the live history scatter;
  * Pareto front is rendered on whichever matplotlib canvas is available
    on the window (``window.canvas_pareto`` if present, otherwise printed);
  * picking a Pareto point pushes its decoded ``L_ctrl`` / ``t_ctrl`` back
    onto the window so the user can re-run a Compute on that design.

Heavier polish (rich Pareto interactions, design-preview heatmaps, side-by-
side L(x,y)/t(x,y) panels) is deliberately deferred — first prove the
end-to-end loop works, then make it pretty.
"""

from __future__ import annotations

import os
import time
import warnings
from typing import Optional

import numpy as np

# Qt imports are kept lazy so this module can be imported by non-GUI tools
# (CLI scripts, headless tests) without forcing a Qt dependency.


# ─── Background worker thread (lazy QtCore import) ──────────────────


def _make_worker_class():
    """Return a QThread subclass that runs the BO loop. Constructed at first
    call to keep import-time cheap and avoid Qt at module import."""
    from PyQt6.QtCore import QThread, pyqtSignal

    class _OptimizeWorker(QThread):
        finished_with_result = pyqtSignal(object)
        progress_signal = pyqtSignal(int, int, float)  # count, total, best_Q
        error_signal = pyqtSignal(str)

        def __init__(self, cfg, n_init, n_iter, q_batch, seed, save_dir):
            super().__init__()
            self.cfg = cfg
            self.n_init = n_init
            self.n_iter = n_iter
            self.q_batch = q_batch
            self.seed = seed
            self.save_dir = save_dir

        def run(self):
            try:
                from optimization.optimizer_qnehvi import run_qnehvi

                def _cb(count, total, prog):
                    self.progress_signal.emit(int(count), int(total),
                                               float(prog['best_Q']))

                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    res = run_qnehvi(
                        config=self.cfg,
                        n_init=self.n_init, n_iter=self.n_iter,
                        q_batch=self.q_batch, seed=self.seed,
                        verbose=True,
                        save_dir=self.save_dir,
                        progress_cb=_cb,
                    )
                self.finished_with_result.emit(res)
            except Exception as e:
                self.error_signal.emit(f"{type(e).__name__}: {e}")

    return _OptimizeWorker


# ─── Window-side helpers ────────────────────────────────────────────


def _gather_cfg(window) -> dict:
    """Read the cfg fields off the window into a plain dict. Falls back to
    evaluator.DEFAULT_CONFIG keys when a widget is missing.
    """
    from optimization.evaluator import DEFAULT_CONFIG as EVAL_DEFAULT

    cfg = dict(EVAL_DEFAULT)

    def _get(attr, cast=float, key=None):
        if hasattr(window, attr):
            try:
                cfg[key or attr] = cast(getattr(window, attr).text())
            except (ValueError, AttributeError):
                pass

    # Geometry (m) — UI defaults match Shanghai's cross-flow HX
    # (0.182 × 0.042 × 0.042 m³). Without these reads the optimizer would
    # silently fall back to the evaluator's hard-coded 0.10 × 0.05 m generic
    # case regardless of what the user typed in the Compute fields.
    _get('le_L',      float, 'L_domain')
    _get('le_H',      float, 'H_domain')
    _get('le_Lz',     float, 'Lz')

    _get('le_Lcell',  float, 'L_avg_init')   # not used directly but useful seed
    _get('le_t',      float, 't_avg_init')
    _get('le_ks',     float, 'k_s')
    _get('le_uA',     float, 'u_A')
    _get('le_uB',     float, 'u_B')
    _get('le_PinA',   float, 'P_inA')
    _get('le_PinB',   float, 'P_inB')

    if hasattr(window, '_temp_to_K'):
        try:
            cfg['T_inA'] = float(window._temp_to_K(window.le_TinA))
            cfg['T_inB'] = float(window._temp_to_K(window.le_TinB))
        except (ValueError, AttributeError):
            pass

    if hasattr(window, 'combo_tpms'):
        cfg['tpms_type'] = window.combo_tpms.currentText()

    return cfg


def _set_status(window, text: str) -> None:
    """Push a one-line status onto whichever label the window exposes."""
    for attr in ('lbl_opt_status', 'lbl_status', 'statusBar'):
        target = getattr(window, attr, None)
        if target is None:
            continue
        try:
            if callable(target):
                target().showMessage(text)
            elif hasattr(target, 'setText'):
                target.setText(text)
            return
        except Exception:
            pass
    print(f"[optimize] {text}")


# ─── Public API (called by main.py) ─────────────────────────────────


def run_optimize(window) -> None:
    """Kick off a qNEHVI optimization in a background thread."""
    if getattr(window, '_opt_worker', None) is not None and window._opt_worker.isRunning():
        _set_status(window, 'optimizer already running')
        return

    cfg = _gather_cfg(window)

    # n_init / n_iter / q_batch sourced from window if present, else defaults
    n_init  = int(getattr(window, 'opt_n_init',  None).text()) \
              if hasattr(window, 'opt_n_init')  else 32
    n_iter  = int(getattr(window, 'opt_n_iter',  None).text()) \
              if hasattr(window, 'opt_n_iter')  else 24
    q_batch = int(getattr(window, 'opt_q_batch', None).text()) \
              if hasattr(window, 'opt_q_batch') else 2
    seed    = int(getattr(window, 'opt_seed',    None).text()) \
              if hasattr(window, 'opt_seed')    else 42

    save_dir = os.path.join('opt_runs',
                             f"qnehvi_{time.strftime('%Y%m%d_%H%M%S')}")

    Worker = _make_worker_class()
    worker = Worker(cfg, n_init, n_iter, q_batch, seed, save_dir)

    def _on_progress(count, total, best_Q):
        _set_status(window,
                    f"qNEHVI {count}/{total}  best Q = {best_Q:.0f} W/m")

    def _on_done(res):
        window._last_opt_result = res
        window._last_opt_cfg = cfg
        _set_status(window,
                    f"qNEHVI DONE: {len(res['X'])} Pareto / {res['n_evals']} evals "
                    f"→ {res['save_dir']}")
        try:
            show_pareto(window, res)
        except Exception as e:
            print(f"[optimize] show_pareto failed: {e}")
        try:
            save_opt_results(window, res, cfg)
        except Exception as e:
            print(f"[optimize] save_opt_results failed: {e}")

    def _on_error(msg):
        _set_status(window, f"qNEHVI ERROR: {msg}")
        print(f"[optimize] worker error: {msg}")

    worker.progress_signal.connect(_on_progress)
    worker.finished_with_result.connect(_on_done)
    worker.error_signal.connect(_on_error)
    window._opt_worker = worker
    worker.start()
    _set_status(window, 'qNEHVI running …')


def cancel_optimize(window) -> None:
    """Request graceful cancel of the running optimizer."""
    from optimization.optimizer_qnehvi import request_cancel
    request_cancel()
    _set_status(window, 'cancel requested — stopping at next iteration boundary')


def show_pareto(window, res: dict) -> None:
    """Plot the Pareto front (Q vs dP) on the window's matplotlib canvas
    if available; print to stdout otherwise.
    """
    F_min = res['F']                  # (-Q, dP)  shape (P, 2)
    Q  = -F_min[:, 0]
    dP =  F_min[:, 1]
    F_hist = res.get('history_F')

    canvas = getattr(window, 'canvas_pareto', None)
    if canvas is None:
        print("[optimize] Pareto front (no canvas; showing top 10):")
        order = np.argsort(Q)[::-1][:10]
        for i in order:
            print(f"  Q = {Q[i]:8.0f} W/m   dP = {dP[i]:8.0f} Pa")
        return

    fig = canvas.figure
    fig.clear()
    ax = fig.add_subplot(111)
    if F_hist is not None and F_hist.size:
        Qh = -F_hist[:, 0]; dPh = F_hist[:, 1]
        ax.scatter(dPh, Qh, c='lightgray', s=14, alpha=0.6,
                   label=f'history (n={len(Qh)})')
    order = np.argsort(dP)
    ax.plot(dP[order], Q[order], 'o-', color='C1', lw=1.5, ms=6,
            label=f'Pareto (n={len(Q)})', picker=True, pickradius=6)
    ax.set_xlabel('dP [Pa]')
    ax.set_ylabel('Q [W/m]')
    ax.set_title(f"qNEHVI Pareto front  ({res['n_evals']} evals)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    canvas.draw()

    # Cache the Pareto data on the window for click-pick decoding
    window._pareto_X = res['X']
    window._pareto_F = F_min


def reshow_pareto(window) -> None:
    """Re-render the most recent Pareto result. Useful after a window resize
    or theme change."""
    res = getattr(window, '_last_opt_result', None)
    if res is None:
        _set_status(window, 'no optimizer result to reshow')
        return
    show_pareto(window, res)


def on_pareto_pick(window, event) -> None:
    """Matplotlib pick_event handler. Decodes the picked design back to its
    control-point grids and forwards to ``load_pareto_solution``.
    """
    if not hasattr(event, 'ind') or len(event.ind) == 0:
        return
    idx = int(event.ind[0])
    X = getattr(window, '_pareto_X', None)
    F = getattr(window, '_pareto_F', None)
    if X is None or F is None or idx >= len(X):
        return

    # The Pareto plot was drawn in dP-sorted order; map the click index back.
    F_dP = F[:, 1]
    order = np.argsort(F_dP)
    real_idx = int(order[idx])
    x_decision = X[real_idx]
    Q = -F[real_idx, 0]; dP = F[real_idx, 1]
    _set_status(window,
                f"Pareto pick: Q={Q:.0f} W/m  dP={dP:.0f} Pa  → loading design")
    load_pareto_solution(window, x_decision)


def save_opt_results(window, res: dict, cfg: dict) -> None:
    """Persist Pareto + history CSVs (already done by run_qnehvi via
    save_dir) and dump cfg as JSON for traceability.
    """
    save_dir = res['save_dir']
    try:
        import json
        with open(os.path.join(save_dir, 'cfg_used.json'), 'w') as f:
            json.dump({k: v for k, v in cfg.items()
                       if isinstance(v, (int, float, str, bool, type(None)))},
                      f, indent=2)
    except Exception as e:
        print(f"[optimize] cfg dump failed: {e}")
    _set_status(window, f'results saved → {save_dir}')


def load_pareto_solution(window, x_decision: np.ndarray) -> None:
    """Decode a 16-D decision vector and apply its average L / t back onto
    the window's Compute fields (``le_Lcell`` / ``le_t``).

    The continuous-field design is heterogeneous; only the spatial average is
    pushed back to scalar Compute inputs. The full graded geometry lives in
    the Pareto CSV under ``opt_runs/.../pareto_final.csv``.
    """
    from solvers.field_param import decode_decision_vector

    cfg_full = _gather_cfg(window)
    L_ctrl, t_ctrl = decode_decision_vector(
        np.asarray(x_decision, dtype=np.float64),
        n_ctrl_x=cfg_full.get('n_ctrl_x', 4),
        n_ctrl_y=cfg_full.get('n_ctrl_y', 4),
        symmetric_y=cfg_full.get('symmetric_y', True),
    )
    L_avg = float(L_ctrl.mean())
    t_avg = float(t_ctrl.mean())

    if hasattr(window, 'le_Lcell'):
        window.le_Lcell.setText(f"{L_avg:.3f}")
    if hasattr(window, 'le_t'):
        window.le_t.setText(f"{t_avg:.3f}")

    # Stash the full grid on the window so a Compute path could opt-in to the
    # heterogeneous design later.
    window._pareto_selected_L_ctrl = L_ctrl
    window._pareto_selected_t_ctrl = t_ctrl
    _set_status(window,
                f"loaded Pareto solution: L_avg = {L_avg:.3f} mm, "
                f"t_avg = {t_avg:.3f} mm  (full grid stashed on window)")
