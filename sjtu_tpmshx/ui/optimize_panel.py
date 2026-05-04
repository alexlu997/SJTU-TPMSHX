"""Optimization panel + Pareto front interaction.

Extracted from main.py (Task B.7). All functions take `window` (Main_Menu
instance) as first argument.
"""
import numpy as np
from PySide6.QtWidgets import QMessageBox, QComboBox, QTableWidgetItem

from .theme import get_theme


def run_optimize(window):
    """Ex-Main_Menu._run_optimize(self)."""
    from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                                    QSpinBox, QDoubleSpinBox)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    # Config dialog
    dlg = QDialog(window)
    dlg.setWindowTitle("Optimize Configuration")
    import os
    from PySide6.QtGui import QIcon
    _gear_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'settings_options_preferences_gears_icon_124617.ico')
    if os.path.exists(_gear_path):
        dlg.setWindowIcon(QIcon(_gear_path))
    form = QFormLayout(dlg)

    # Optimization direction
    combo_opt_axis = QComboBox()
    combo_opt_axis.addItems(["Along Y", "Along X"])
    form.addRow("Optimize direction:", combo_opt_axis)

    # Transition zone fractions
    sp_inlet = QDoubleSpinBox(); sp_inlet.setRange(5, 45); sp_inlet.setValue(20); sp_inlet.setSuffix("%")
    sp_outlet = QDoubleSpinBox(); sp_outlet.setRange(5, 45); sp_outlet.setValue(20); sp_outlet.setSuffix("%")
    form.addRow("Inlet transition:", sp_inlet)
    form.addRow("Outlet transition:", sp_outlet)

    # Optimization variables
    combo_vars = QComboBox()
    combo_vars.addItems(["Optimize L + t", "Fix L (optimize t only)", "Fix t (optimize L only)"])
    form.addRow("Variables:", combo_vars)

    # Algorithm selection
    combo_algo = QComboBox()
    combo_algo.addItems(["NSGA-II (pymoo)", "MOEA/D (pymoo)", "qNEHVI (BoTorch, Bayesian)"])
    form.addRow("Algorithm:", combo_algo)

    # Generations / population (used by NSGA-II / MOEA/D; qNEHVI ignores)
    sp_gen = QSpinBox(); sp_gen.setRange(5, 500); sp_gen.setValue(20)
    sp_pop = QSpinBox(); sp_pop.setRange(10, 200); sp_pop.setValue(20)
    form.addRow("Generations:", sp_gen)
    form.addRow("Population:", sp_pop)

    btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                            QDialogButtonBox.StandardButton.Cancel)
    btns.accepted.connect(dlg.accept)
    btns.rejected.connect(dlg.reject)
    form.addRow(btns)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return

    opt_axis = 'y' if combo_opt_axis.currentIndex() == 0 else 'x'
    y_trans_inlet = sp_inlet.value() / 100.0
    y_trans_outlet = sp_outlet.value() / 100.0

    n_gen = sp_gen.value()
    pop_size = sp_pop.value()
    total = n_gen * pop_size
    algo_idx = combo_algo.currentIndex()
    algo_name = ('nsga2', 'moead', 'qnehvi')[algo_idx]

    # Build config from current UI
    try:
        # Read inlet config from UI
        cfgA = window._fluid_config('A')
        cfgB = window._fluid_config('B')
        L_dom = float(window.le_L.text())
        H_dom = float(window.le_H.text())

        cfg = {
            'L_domain': L_dom,
            'H_domain': H_dom,
            # Nx, Ny: computed adaptively from D_h in optimizer
            'tpms_type': window.combo_tpms.currentText(),
            'k_s': float(window.le_ks.text()),
            'u_A': float(window.le_uA.text()),
            'u_B': float(window.le_uB.text()),
            # K/°C display toggle → always pass K to the optimizer
            'T_inA': (window._temp_to_K(window.le_TinA)
                      if hasattr(window, '_temp_to_K')
                      else float(window.le_TinA.text())),
            'T_inB': (window._temp_to_K(window.le_TinB)
                      if hasattr(window, '_temp_to_K')
                      else float(window.le_TinB.text())),
            # Pass UI inlet pressures so the optimizer matches the Compute
            # tab's operating point — previously hardcoded 1 atm (#7, #8).
            'P_inA': float(window.le_PinA.text()),
            'P_inB': float(window.le_PinB.text()),
            # cp_f removed (#1) — solver uses air_cp(T) per cell.
            'rho_s': float(window.le_rho_s.text()),
            'L0': float(window.le_Lcell.text()),
            't0': float(window.le_t.text()),
            'opt_axis': opt_axis,
            'y_trans_inlet': y_trans_inlet,
            'y_trans_outlet': y_trans_outlet,
            'fix_L': combo_vars.currentIndex() == 1,
            'fix_t': combo_vars.currentIndex() == 2,
            # Inlet bounds (same as Compute path)
            'pipe_lo_A': cfgA['in_ctr'] - cfgA['in_w'] / 2,
            'pipe_hi_A': cfgA['in_ctr'] + cfgA['in_w'] / 2,
            'pipe_lo_B': cfgB['in_ctr'] - cfgB['in_w'] / 2,
            'pipe_hi_B': cfgB['in_ctr'] + cfgB['in_w'] / 2,
            # Outlet bounds
            'outlet_lo_A': cfgA['out_ctr'] - cfgA['out_w'] / 2,
            'outlet_hi_A': cfgA['out_ctr'] + cfgA['out_w'] / 2,
            'outlet_lo_B': cfgB['out_ctr'] - cfgB['out_w'] / 2,
            'outlet_hi_B': cfgB['out_ctr'] + cfgB['out_w'] / 2,
        }
    except ValueError:
        QMessageBox.warning(window, "Error", "Check input fields."); return

    window._opt_cfg = cfg  # store for _load_pareto_solution
    window._opt_status.setText(f"Optimizing… 0/{total}")
    window._opt_total = total
    window._opt_total_gen = int(n_gen)
    import time as _t_run_opt
    window._opt_wall_t0 = _t_run_opt.time()
    # Reset hero stats + clear sparkline from any previous run.
    if hasattr(window, '_opt_reset_panel'):
        window._opt_reset_panel()
    if hasattr(window, '_opt_set_stage'):
        window._opt_set_stage('running')
    _set_optimize_running(window, True)
    QApplication.processEvents()

    import threading
    from optimization.optimizer import clear_cancel
    clear_cancel()

    def _opt_thread():
        try:
            from optimization.optimizer import run_optimization
            res = run_optimization(cfg, n_gen, pop_size, verbose=False,
                                   algorithm=algo_name)
            window._opt_result = res
            window._opt_error = None
        except Exception as e:
            window._opt_result = None
            window._opt_error = str(e)
            import traceback; traceback.print_exc()

    window._opt_result = None
    window._opt_error = None
    t = threading.Thread(target=_opt_thread, daemon=True)
    t.start()

    # Poll for completion using QTimer — parent to window for proper lifetime.
    window._opt_timer = QTimer(window)
    window._opt_thread_ref = t
    window._opt_tick = [0]

    def _check():
        window._opt_tick[0] += 1
        if window._opt_thread_ref.is_alive():
            from optimization.optimizer import _progress
            phase = _progress.get('phase', 'optimize')
            if phase == 'reeval':
                rc = _progress.get('reeval_count', 0)
                rt = _progress.get('reeval_total', 0)
                window._opt_status.setText(
                    f"Re-evaluating Pareto at fine grid: {rc}/{rt}")
                return
            cnt = _progress['count']
            tot = _progress['total']
            best = _progress['best_Q']
            best_dp = _progress.get('best_dP', float('inf'))
            if best_dp == float('inf'):
                best_dp = None
            pct = int(cnt / max(tot, 1) * 100)
            elapsed = window._opt_tick[0] * 0.5  # seconds
            if cnt > 0:
                eta = (tot - cnt) * elapsed / cnt
                eta_str = f"{int(eta//60)}m{int(eta%60)}s" if eta > 60 else f"{int(eta)}s"
            else:
                eta_str = "..."
            window._opt_status.setText(
                f"{cnt}/{tot} evaluations  ·  {pct}% complete")
            # Pump the progress bar next to the Optimize tab header.
            bar = getattr(window, '_opt_progress', None)
            if bar is not None:
                bar.setValue(pct)
            # Pump hero KPIs + sparkline.
            if hasattr(window, '_opt_update_kpis'):
                total_gen = getattr(window, '_opt_total_gen', 0) or 1
                # Derive pop_size from the eval total when the optimizer
                # doesn't surface it directly.
                pop_sz = max(1, int(round(tot / total_gen)))
                gen_idx = min(int(total_gen), cnt // pop_sz + 1) if cnt else 0
                window._opt_update_kpis(
                    gen=gen_idx, gen_total=int(total_gen),
                    best_q=float(best),
                    best_dp=(float(best_dp) if best_dp is not None else None),
                    eta=eta_str)
            return
        # Thread finished
        window._opt_timer.stop()
        _set_optimize_running(window, False)
        if window._opt_error:
            window._opt_status.setText(f"Error: {window._opt_error}")
            if hasattr(window, '_opt_set_stage'):
                window._opt_set_stage('config')
            QMessageBox.critical(window, "Optimization Error", window._opt_error)
        elif window._opt_result:
            res = window._opt_result
            n_sol = len(res['X'])
            Q_lo = -res['F'][:, 0].max()
            Q_hi = -res['F'][:, 0].min()
            tag_bits = []
            if res.get('cancelled'):
                tag_bits.append("cancelled")
            if 'F_coarse' in res:
                tag_bits.append("fine grid")
            tag = f" ({', '.join(tag_bits)})" if tag_bits else ""
            window._opt_status.setText(
                f"Done  ·  {n_sol} Pareto solutions{tag}  ·  "
                f"Q [{Q_lo:.0f}, {Q_hi:.0f}] W/m")
            if hasattr(window, '_opt_set_stage'):
                window._opt_set_stage('result')
            if hasattr(window, '_opt_show_summary'):
                import time as _t_done
                elapsed = _t_done.time() - getattr(
                    window, '_opt_wall_t0', _t_done.time())
                extra = ", ".join(tag_bits) if tag_bits else ""
                window._opt_show_summary(n_sol, Q_lo, Q_hi, elapsed, extra)

            # Results already saved by optimizer per-generation
            sd = res.get('save_dir', '')
            window.statusBar().showMessage(f"Results saved to: {sd}", 8000)
            show_pareto(window, res)

    window._opt_timer.timeout.connect(_check)
    window._opt_timer.start(500)  # check every 0.5s


def _set_optimize_running(window, running):
    """Toggle the Optimize tab header between idle and running states.

    New D-plan layout: a dedicated Cancel button sits beside Launch, so we
    just disable Launch + enable Cancel + surface the progress bar rather
    than swapping the button's role (previous behaviour).
    """
    btn = getattr(window, '_opt_btn', None)
    cancel = getattr(window, '_opt_cancel_btn', None)
    bar = getattr(window, '_opt_progress', None)
    if btn is not None:
        btn.setEnabled(not running)
        btn.setToolTip(
            "Search already running — use Cancel to stop." if running
            else "Launch NSGA-II Pareto search (minutes to hours). "
                 "Progress + live Pareto render in this tab.")
    if cancel is not None:
        cancel.setEnabled(bool(running))
    if bar is not None:
        if running:
            bar.setValue(0)
            bar.show()
        else:
            bar.hide()


def cancel_optimize(window):
    """Request cancellation of the running optimization (hooked from the
    button swap in `_set_optimize_running`). Flips the button back to its
    idle style on the next poll tick in `run_optimize._check`."""
    from optimization.optimizer import request_cancel
    request_cancel()
    window._opt_status.setText(
        "Cancelling — waiting for current evaluation to finish…")


def reshow_pareto(window):
    """Ex-Main_Menu._reshow_pareto(self)."""
    if hasattr(window, '_opt_result') and window._opt_result:
        show_pareto(window, window._opt_result)
    else:
        QMessageBox.information(window, "No Results",
            "Run Optimize first to generate a Pareto front.")


def show_pareto(window, res):
    """Ex-Main_Menu._show_pareto(self, res)."""
    from .theme import get_theme
    import main as _main_mod
    # Reveal Pareto tab — visibility is gated on _has_pareto
    window._has_pareto = True
    # Skeleton placeholder retires once real data lands.
    sk = getattr(window, '_pareto_skeleton', None)
    if sk is not None:
        try: sk.stop()
        except Exception: pass
    if hasattr(window, '_update_tab_visibility'):
        window._update_tab_visibility()
    _t = get_theme()
    F = res['F']; X = res['X']
    Q = -F[:, 0]; dP = F[:, 1]

    fig = window.canvas_pareto.fig
    fig.clear()
    fig.patch.set_facecolor(_t['fig_bg'])

    # Use gridspec: main plot left, colorbar+legend right
    import matplotlib.gridspec as gs
    gspec = gs.GridSpec(1, 2, width_ratios=[1, 0.05], wspace=0.02)
    ax = fig.add_subplot(gspec[0])
    cax = fig.add_subplot(gspec[1])
    ax.set_facecolor(_t['ax_bg'])

    F_coarse = res.get('F_coarse', None)

    # Coarse-grid values as small faded markers
    if F_coarse is not None:
        Q_c = -F_coarse[:, 0]; dP_c = F_coarse[:, 1]
        ax.scatter(dP_c, Q_c, c=_t['mpl_subtitle'], s=12, alpha=0.25,
                   marker='x', zorder=1, label='Optimizer grid')

    # Main scatter (fine-grid)
    sc = ax.scatter(dP, Q, c=Q/(dP+1e-10), cmap='viridis', s=50,
                    edgecolors=_t['ax_text'], linewidths=0.5, picker=True,
                    zorder=3)

    # ── TOPSIS ──
    Q_min, Q_max = Q.min(), Q.max()
    dP_min, dP_max = dP.min(), dP.max()
    Q_range = Q_max - Q_min if Q_max > Q_min else 1.0
    dP_range = dP_max - dP_min if dP_max > dP_min else 1.0
    Q_norm = (Q - Q_min) / Q_range
    dP_norm = (dP_max - dP) / dP_range

    dist = np.sqrt((1.0 - Q_norm)**2 + (1.0 - dP_norm)**2)
    best_idx = np.argmin(dist)
    best_radius = dist[best_idx]

    theta = np.linspace(0, np.pi/2, 100)
    circle_Q = (1.0 - best_radius * np.sin(theta)) * Q_range + Q_min
    circle_dP = dP_max - (1.0 - best_radius * np.cos(theta)) * dP_range
    ax.plot(circle_dP, circle_Q, '--', color=_t['pareto_accent'], linewidth=1.5,
            alpha=0.7, zorder=2, label='Equal-preference arc')

    ax.scatter([dP[best_idx]], [Q[best_idx]], s=200, facecolors='none',
               edgecolors=_t['pareto_accent'], linewidths=2.5, zorder=4,
               label='Best compromise')
    ax.scatter([dP_min], [Q_max], s=100, marker='*', c=_t['pareto_accent'],
               zorder=5, label='Utopia point')

    # ── Axis ranges: tight with 5% margin ──
    margin_x = dP_range * 0.05 if dP_range > 0 else 100
    margin_y = Q_range * 0.05 if Q_range > 0 else 100
    ax.set_xlim(dP_min - margin_x, dP_max + margin_x)
    ax.set_ylim(Q_min - margin_y, Q_max + margin_y)

    # ── Labels ──
    ax.set_xlabel('Total Pressure Drop \u0394P [Pa]', fontsize=11, color=_t['ax_text'])
    ax.set_ylabel('Total Heat Transfer Q [W/m]', fontsize=11, color=_t['ax_text'])

    # ── Title: bold main + gray subtitle ──
    ax.set_title('Pareto Front', fontsize=13, fontweight='bold',
                 color=_t['ax_text'], loc='left')
    if F_coarse is not None:
        ax.text(1.0, 1.01, 're-evaluated (fine grid)',
                transform=ax.transAxes, fontsize=9, color=_t['mpl_subtitle'],
                ha='right', va='bottom', style='italic')

    # ── Colorbar in dedicated axis ──
    cb = fig.colorbar(sc, cax=cax)
    cb.set_label('Q/\u0394P [W/m/Pa]', fontsize=9, color=_t['ax_text'])
    cb.ax.tick_params(labelsize=8, colors=_t['ax_text'])

    # ── Legend: below colorbar area, unified style ──
    leg = ax.legend(fontsize=8, loc='upper right', framealpha=0.9,
                    edgecolor=_t['ax_spine'], fancybox=False)
    leg.get_frame().set_linewidth(0.5)

    # ── Info box: right-bottom, consistent style ──
    ax.text(0.98, 0.02,
            f'Best: Q={Q[best_idx]:.0f} W/m, \u0394P={dP[best_idx]:.0f} Pa\n'
            f'{len(Q)} solutions',
            transform=ax.transAxes, fontsize=8, color=_t['ax_text'],
            va='bottom', ha='right',
            bbox=dict(boxstyle='round,pad=0.3', facecolor=_t['ax_bg'],
                      edgecolor=_t['ax_spine'], linewidth=0.5, alpha=0.9))

    # ── Bottom hint ──
    ax.text(0.5, -0.08, 'Click a point to load parameters',
            transform=ax.transAxes, fontsize=8, color=_t['mpl_subtitle'],
            ha='center', va='top', style='italic')

    ax.tick_params(labelsize=9, colors=_t['ax_text'])
    ax.grid(True, alpha=0.2, linewidth=0.5)
    for sp in ax.spines.values():
        sp.set_edgecolor(_t['ax_spine'])
    fig.subplots_adjust(left=0.12, right=0.92, top=0.92, bottom=0.14)

    # Store data for pick event
    window._pareto_X = X
    window._pareto_Q = Q
    window._pareto_dP = dP

    # Connect pick event (disconnect old one first)
    if hasattr(window, '_pareto_cid'):
        window.canvas_pareto.mpl_disconnect(window._pareto_cid)
    window._pareto_cid = window.canvas_pareto.mpl_connect(
        'pick_event', lambda ev: on_pareto_pick(window, ev))

    # Hover annotation — shows Q / ΔP / design-index for the scatter point
    # under the cursor. Stored on the axes so we can update its text in
    # place instead of recreating on every motion event.
    annot = ax.annotate(
        "", xy=(0, 0), xytext=(12, 12), textcoords="offset points",
        bbox=dict(boxstyle="round,pad=0.35", fc=_t['ax_bg'],
                  ec=_t['ax_spine'], lw=0.7, alpha=0.95),
        fontsize=8, color=_t['ax_text'],
        arrowprops=dict(arrowstyle="->", color=_t['ax_spine'], lw=0.6))
    annot.set_visible(False)
    window._pareto_hover_annot = annot
    window._pareto_hover_sc = sc

    def _on_motion(event, window=window, sc=sc, Q=Q, dP=dP, X=X, annot=annot):
        if event.inaxes is None or event.inaxes is not sc.axes:
            if annot.get_visible():
                annot.set_visible(False)
                window.canvas_pareto.draw_idle()
            return
        cont, info = sc.contains(event)
        if not cont:
            if annot.get_visible():
                annot.set_visible(False)
                window.canvas_pareto.draw_idle()
            return
        i = int(info['ind'][0])
        annot.xy = (dP[i], Q[i])
        ratio = Q[i] / dP[i] if dP[i] > 1e-10 else 0.0
        lines = [
            f"#{i}",
            f"Q  = {Q[i]:.1f} W/m",
            f"ΔP = {dP[i]:.0f} Pa",
            f"Q/ΔP = {ratio:.4g}",
        ]
        try:
            xi = np.asarray(X[i]).ravel()
            if xi.size <= 6:
                lines.append("x = [" + ", ".join(f"{v:.3g}" for v in xi) + "]")
            else:
                lines.append(f"x ({xi.size}-d): "
                              f"min {xi.min():.3g} / max {xi.max():.3g}")
        except Exception:
            pass
        annot.set_text("\n".join(lines))
        annot.set_visible(True)
        window.canvas_pareto.draw_idle()

    if hasattr(window, '_pareto_hover_cid'):
        window.canvas_pareto.mpl_disconnect(window._pareto_hover_cid)
    window._pareto_hover_cid = window.canvas_pareto.mpl_connect(
        'motion_notify_event', _on_motion)

    window.canvas_pareto.draw()
    if not hasattr(window, '_drawn_tabs'):
        window._drawn_tabs = set()
    window._drawn_tabs.add('pareto')
    window._switch_tab('pareto')


def on_pareto_pick(window, event):
    """Ex-Main_Menu._on_pareto_pick(self, event)."""
    if not hasattr(window, '_pareto_X'):
        return
    idx = event.ind[0]
    x = window._pareto_X[idx]
    Q = window._pareto_Q[idx]
    dP = window._pareto_dP[idx]
    window.statusBar().showMessage(
        f"Solution {idx}: Q={Q:.0f} W/m, \u0394P={dP:.0f} Pa — "
        f"loaded into zone table. Click Compute to see cloud plots.", 8000)
    load_pareto_solution(window, x)


def save_opt_results(window, res, cfg):
    """Ex-Main_Menu._save_opt_results(self, res, cfg)."""
    import os, json, time
    save_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # Save Pareto front (CSV)
    csv_path = os.path.join(save_dir, f"pareto_{timestamp}.csv")
    F = res['F']; X = res['X']
    with open(csv_path, 'w') as f:
        # Header
        cols = ['Q_total_W_m', 'dP_total_Pa']
        for i in range(18):
            zone = 'inlet' if i < 9 else 'outlet'
            idx = i if i < 9 else i - 9
            cols += [f'{zone}_{idx}_L_mm', f'{zone}_{idx}_t_mm']
        f.write(','.join(cols) + '\n')
        # Data
        for i in range(len(X)):
            row = [f"{-F[i,0]:.2f}", f"{F[i,1]:.2f}"]
            for v in X[i]:
                row.append(f"{v:.3f}")
            f.write(','.join(row) + '\n')

    # Save config (JSON)
    json_path = os.path.join(save_dir, f"pareto_{timestamp}_config.json")
    with open(json_path, 'w') as f:
        json.dump(cfg, f, indent=2)

    window.statusBar().showMessage(f"Results saved: {csv_path}", 8000)
    print(f"[Optimizer] Saved {len(X)} solutions to {csv_path}")
    return csv_path


def load_pareto_solution(window, x):
    """Ex-Main_Menu._load_pareto_solution(self, x)."""
    from optimization.optimizer import build_grid_cells

    L0 = float(window.le_Lcell.text())
    t0 = float(window.le_t.text())
    # Use stored optimization config if available
    opt_cfg = getattr(window, '_opt_cfg', {})
    y_trans_in = opt_cfg.get('y_trans_inlet', 0.2)
    y_trans_out = opt_cfg.get('y_trans_outlet', 0.2)
    cells = build_grid_cells(x, L0, t0, y_trans_in, y_trans_out,
                             opt_cfg.get('opt_axis', 'y'))

    # Store decision vector for Sigmoid continuous field in Compute
    window._pareto_x_decision = np.array(x, dtype=np.float64)
    window._pareto_y_trans_inlet = y_trans_in
    window._pareto_y_trans_outlet = y_trans_out

    # Switch to grid mode and populate table
    window.chk_zones.setChecked(True)
    window.combo_zone_axis.setCurrentIndex(2)  # Grid Y×X

    ncols = 6
    window.zone_table.setColumnCount(ncols)
    window.zone_table.setHorizontalHeaderLabels(
        ["y0%", "y1%", "x0%", "x1%", "L [mm]", "t [mm]"])
    window.zone_table.setRowCount(len(cells))
    for r, gc in enumerate(cells):
        vals = [f"{gc['y0']*100:.1f}", f"{gc['y1']*100:.1f}",
                f"{gc['x0']*100:.1f}", f"{gc['x1']*100:.1f}",
                f"{gc['L']:.1f}", f"{gc['t']:.2f}"]
        for c, v in enumerate(vals):
            window.zone_table.setItem(r, c, QTableWidgetItem(v))

    window._switch_param_tab(2)  # Switch to Zone Layout tab
    window.statusBar().showMessage(
        "Pareto solution loaded. Click Compute to see contour plots.", 5000)
