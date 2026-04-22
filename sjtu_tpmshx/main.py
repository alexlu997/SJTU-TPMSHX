import sys
import json
import warnings
import numpy as np
import matplotlib
matplotlib.use("QtAgg")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QGridLayout,
    QMessageBox, QFrame, QLabel, QLineEdit, QPushButton, QComboBox,
    QScrollArea, QSplitter, QWidget, QSlider, QSizePolicy, QFileDialog,
    QProgressBar, QCheckBox, QTableWidget, QTableWidgetItem,
    QInputDialog,
)

from ui.mainui import Ui_MainWindow
from solvers.tpms_calc import compute as tpms_compute, geometry as tpms_geometry, adaptive_grid
from ui.matplotlib_canvas import MatplotlibCanvas, _label_axes
from ui.theme import _THEMES, _build_styles

# Theme dict and _build_styles moved to theme.py (Task B.3).

_S = _build_styles()
_BG = _S['BG']; _LBL = _S['LBL']; _VAL = _S['VAL']; _VAL_WARN = _S['VAL_WARN']
_INP = _S['INP']; _COMBO = _S['COMBO']
_T_NEUTRAL = _S['T_NEUTRAL']; _T_HOT = _S['T_HOT']; _T_COLD = _S['T_COLD']
_F_NEUTRAL = _S['F_NEUTRAL']; _F_HOT = _S['F_HOT']; _F_COLD = _S['F_COLD']
_BTN_BASE = "border-radius:5px; color:white; font-weight:bold; font-size:9pt;"
_BTN_HOT = _S['BTN_HOT']; _BTN_COLD = _S['BTN_COLD']
_BTN_TPMS = _S['BTN_TPMS']; _BTN_RUN = _S['BTN_RUN']


# ── Auto-select delegate for zone table editing ─────────────
from PySide6.QtWidgets import QStyledItemDelegate
class _SelectAllDelegate(QStyledItemDelegate):
    """When editing starts, auto-select all text so user can type to replace."""
    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if hasattr(editor, 'selectAll'):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, editor.selectAll)
        return editor


# ── Main window ───────────────────────────────────────────────
class Main_Menu(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.setWindowTitle("SJTU-TPMSHX")
        self.resize(1350, 1100)
        self.setMinimumSize(900, 720)
        self.showMaximized()

        # App icon
        import os
        from PySide6.QtGui import QIcon
        _icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sjtulogosilver.png')
        if os.path.exists(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))

        # Hide ALL legacy mainui.py content
        for w in (self.ui.frame1, self.ui.frame2,
                  self.ui.pushButton_2, self.ui.label_49, self.ui.label_50,
                  self.ui.widget, self.ui.horizontalSlider):
            w.hide()

        # Stored solver state
        self._eps_A = self._h_vA = None
        self._K_ffA = self._K_ffB = self._K_ss = None
        self._rho_A = self._rho_B = self._h_vB = None
        self._mu_A  = self._mu_B  = None
        self.T_fA   = self.T_fB   = self.T_s = None

        # Widgets to show/hide based on domain shape
        self._rect_only_widgets = []
        self._poly_only_widgets = []

        self._build_ui()
        self._apply_shanghai_defaults()
        # Track manual grid edits so `compute_tpms` (invoked by Auto-fill)
        # does NOT overwrite user-customised Nx/Ny/Nz. textEdited fires on
        # keyboard input only, not on programmatic `setText`.
        self._user_edited_grid = False
        for le in (self.le_Nx, self.le_Ny, self.le_Nz):
            le.textEdited.connect(self._mark_grid_edited)
        self._setup_shortcuts()
        self._schedule_3d_preinit()

    def _mark_grid_edited(self, _txt=None):
        self._user_edited_grid = True

    def _reset_defaults(self):
        """Reset all parameters to Shanghai Electric preset."""
        self._user_edited_grid = False
        self._apply_shanghai_defaults()
        self.statusBar().showMessage("Parameters reset to Shanghai Electric preset.", 5000)

    def _setup_shortcuts(self):
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(self.run_calculation)
        QShortcut(QKeySequence("Ctrl+Shift+R"), self).activated.connect(self._reset_defaults)
        QShortcut(QKeySequence("Ctrl+1"), self).activated.connect(lambda: self._switch_tab('layout'))
        QShortcut(QKeySequence("Ctrl+2"), self).activated.connect(lambda: self._switch_tab('temp'))
        QShortcut(QKeySequence("Ctrl+3"), self).activated.connect(lambda: self._switch_tab('pres'))
        QShortcut(QKeySequence("Ctrl+4"), self).activated.connect(lambda: self._switch_tab('vel'))
        QShortcut(QKeySequence("Ctrl+5"), self).activated.connect(lambda: self._switch_tab('3d'))

    def _export_results(self):
        """Export last compute results to CSV + optional NPZ."""
        import os, csv
        res_3d = getattr(self, '_result_3d', None)
        has_2d = getattr(self, '_has_results_2d', False)
        has_3d = getattr(self, '_has_results_3d', False)
        if not has_2d and not has_3d:
            QMessageBox.information(self, "No Results",
                "Run Compute first to generate exportable results.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Results", "results.csv",
            "CSV (*.csv);;All Files (*)")
        if not path:
            return
        try:
            rows = []
            if res_3d is not None:
                rows.append(["Q [W]", f"{res_3d.get('Q', 0):.4f}"])
                rows.append(["dP_A [Pa]", f"{res_3d.get('dP', 0):.2f}"])
                rows.append(["dP_B [Pa]", f"{res_3d.get('dP_B', 0):.2f}"])
                rows.append(["T_inA [K]", f"{res_3d.get('T_in', 0):.2f}"])
                rows.append(["u_A [m/s]", f"{res_3d.get('u_A', 0):.4f}"])
                Ta = res_3d.get('Ta')
                if Ta is not None:
                    rows.append(["Ta_min [K]", f"{float(Ta.min()):.2f}"])
                    rows.append(["Ta_max [K]", f"{float(Ta.max()):.2f}"])
                    rows.append(["Grid Nx", str(Ta.shape[0])])
                    rows.append(["Grid Ny", str(Ta.shape[1])])
                    rows.append(["Grid Nz", str(Ta.shape[2])])
                rows.append(["Lx [m]", f"{res_3d.get('Lx', 0):.6f}"])
                rows.append(["Ly [m]", f"{res_3d.get('Ly', 0):.6f}"])
                rows.append(["Lz [m]", f"{res_3d.get('Lz', 0):.6f}"])
            with open(path, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(["Parameter", "Value"])
                w.writerows(rows)
            # Optional: save 3D fields as NPZ alongside
            npz_path = os.path.splitext(path)[0] + '_fields.npz'
            if res_3d is not None:
                save_dict = {}
                for k in ('Ta', 'Tb', 'Ts', 'vmag', 'P_kPa', 'L_mm',
                          'dx', 'dy', 'dz'):
                    v = res_3d.get(k)
                    if v is not None:
                        save_dict[k] = v
                if save_dict:
                    import numpy as _np_exp
                    _np_exp.savez_compressed(npz_path, **save_dict)
            self.statusBar().showMessage(f"Exported: {path}", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    # ─────────────────────────────────────────────────────────
    #  Shanghai presets + deferred 3D init
    # ─────────────────────────────────────────────────────────
    def _apply_shanghai_defaults(self):
        """Overwrite default text fields with Shanghai Electric case-8 params
        and switch to 3D mode. Single-call post-build_ui, users can edit after.
        """
        presets = {
            # Shanghai Electric gas-heater experimental log (工况8, Re_air=5000,
            # Re_water=400) — raw values from `data/raw_data/
            # 20260401-上海电气天然气加热器实验工况.xlsx` Sheet1 row 9:
            #   col 24 water_in  = 26.89 °C   → 300.04 K
            #   col 26 water_P   = 647.60 Pa (gauge)  → 101972.60 abs
            #   col 28 air_in    = 148.908 °C → 422.06 K
            #   col 30 air_P     = 91037.40 Pa (gauge) → 192362.40 abs
            #   col 10 air_SLM   = 1057  → u_A ~20 m/s interstitial (Gyroid L7/t0.6)
            #   col 11 water_flow= 5193 ml/min → u_B ~0.114 m/s (Re=400, D_h~3 mm)
            'le_L':     '0.231',  # L domain [m]
            'le_H':     '0.042',
            'le_Lz':    '0.020',
            'le_Lcell': '7.0',
            'le_t':     '0.6',
            'le_ks':    '16.0',   # Shanghai SS solid k_s
            'le_uA':    '20.0',   # Fluid A (air) interstitial, back-calc Re=5000
            'le_TinA':  '422.0',  # Fluid A inlet (Excel col 28: 148.908 °C)
            'le_PinA':  '192362', # Fluid A inlet absolute (Excel 91037 Pa gauge + atm)
            'le_uB':    '10.0',   # Fluid B (air) — symmetric cross-flow
            'le_TinB':  '300.0',  # Fluid B inlet (Excel col 24: 26.89 °C)
            'le_PinB':  '101973', # Fluid B inlet absolute (Excel 647.6 Pa gauge + atm)
            # 3D grid: wall-refine expands +16 per axis, so 30/20/5 →
            # refined 46×36×21 = ~35k cells, compressible dual-fluid
            # solve ~2–3 min. Keeping the 2D default 100/50 here would
            # push refined 3D to ~160k cells and 10+ min.
            'le_Nx':    '30',
            'le_Ny':    '20',
            'le_Nz':    '5',
            # Shanghai pipe inlet/outlet: A full-width (42 mm strip), B
            # staggered cross-flow (water enters top-right +x end, exits
            # bottom-left -x end; inlet/outlet 42 mm strips along real x).
            'le_pipeA_in_ctr':  '0.021', 'le_pipeA_in_w':  '0.042',
            'le_pipeA_out_ctr': '0.021', 'le_pipeA_out_w': '0.042',
            'le_pipeB_in_ctr':  '0.203', 'le_pipeB_in_w':  '0.042',
            'le_pipeB_out_ctr': '0.028', 'le_pipeB_out_w': '0.042',
        }
        for attr, val in presets.items():
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    w.setText(val)
                except Exception:
                    pass
        # TPMS type → Gyroid (index 1)
        try:
            if hasattr(self, 'combo_tpms'):
                self.combo_tpms.setCurrentIndex(1)
        except Exception:
            pass
        # Dimensionality → 3D (index 1)
        try:
            if hasattr(self, 'combo_dim'):
                self.combo_dim.setCurrentIndex(1)
        except Exception:
            pass
        self.statusBar().showMessage(
            "Loaded Shanghai Electric preset (3D, Gyroid L=7 t=0.6, 231×42×20 mm).",
            5000)

    def _schedule_3d_preinit(self):
        """Pre-initialise PyVistaQt panel 500 ms after window.show() so the
        first click on '3D View' tab is responsive. Runs on main thread but
        deferred → UI is already visible, user sees brief status blip."""
        from PySide6.QtCore import QTimer
        def _preinit():
            if getattr(self, 'canvas_3d', None) is not None:
                return
            self.statusBar().showMessage("Preparing 3D viewer…")
            QApplication.processEvents()
            try:
                self._lazy_init_3d_panel()
            except Exception as e:
                self.statusBar().showMessage(
                    f"3D viewer init deferred (will retry on first click): {e}",
                    5000)
                return
            self.statusBar().showMessage("3D viewer ready.", 2000)
        QTimer.singleShot(500, _preinit)

    # ─────────────────────────────────────────────────────────
    #  Top-level layout
    # ─────────────────────────────────────────────────────────
    def _build_ui(self):
        from ui.ui_builders import build_ui
        return build_ui(self)

    # ─────────────────────────────────────────────────────────
    #  Param tabs container (3 tab buttons + QStackedWidget)
    # ─────────────────────────────────────────────────────────
    def _build_param_tabs(self) -> QWidget:
        from ui.ui_builders import build_param_tabs
        return build_param_tabs(self)

    def _switch_param_tab(self, index):
        from ui.ui_builders import switch_param_tab
        return switch_param_tab(self, index)

    # ─────────────────────────────────────────────────────────
    #  Page 1 — Domain / TPMS / Material / Grid / Results
    # ─────────────────────────────────────────────────────────
    def _build_page_domain(self) -> QScrollArea:
        from ui.ui_builders import build_page_domain
        return build_page_domain(self)

    # ─────────────────────────────────────────────────────────
    #  Page 2 — Fluid A / Fluid B config + pipe geometry
    # ─────────────────────────────────────────────────────────
    def _build_page_fluids(self) -> QScrollArea:
        from ui.ui_builders import build_page_fluids
        return build_page_fluids(self)

    # ─────────────────────────────────────────────────────────
    #  Page 3 — Zone configuration (expanding height)
    # ─────────────────────────────────────────────────────────
    def _build_page_zones(self) -> QScrollArea:
        from ui.ui_builders import build_page_zones
        return build_page_zones(self)

    # ─────────────────────────────────────────────────────────
    #  Canvas area — tab-switched, vertical scrolling
    # ─────────────────────────────────────────────────────────
    def _build_canvas_area(self) -> QWidget:
        from ui.ui_builders import build_canvas_area
        return build_canvas_area(self)

    def _canvas_zoom(self, factor):
        from ui.ui_builders import canvas_zoom
        return canvas_zoom(self, factor)

    def _canvas_zoom_reset(self):
        from ui.ui_builders import canvas_zoom_reset
        return canvas_zoom_reset(self)

    def _canvas_wheel_zoom(self, event, canvas, key):
        from ui.ui_builders import canvas_wheel_zoom
        return canvas_wheel_zoom(self, event, canvas, key)

    def _update_tab_visibility(self):
        """Show/hide tab buttons based on available results and current mode.

        Rules (finalized 2026-04-21):
          - Layout : always
          - Temp/Pres/Vel : 2D mode AND _has_results_2d
          - 3D View : 3D mode AND _has_results_3d
          - Pareto  : _has_pareto (independent of mode)

        If the currently active tab disappears, fall back to Layout.
        Safe to call before ui_builders finishes — returns if buttons absent.
        """
        if not hasattr(self, 'btn_tab_layout'):
            return  # Tab buttons not yet constructed (early _on_dim_changed)
        is_3d = (hasattr(self, 'combo_dim')
                 and self.combo_dim.currentIndex() == 1)
        rules = {
            'layout': True,
            'temp':   (not is_3d) and getattr(self, '_has_results_2d', False),
            'pres':   (not is_3d) and getattr(self, '_has_results_2d', False),
            'vel':    (not is_3d) and getattr(self, '_has_results_2d', False),
            '3d':     is_3d and getattr(self, '_has_results_3d', False),
            'pareto': getattr(self, '_has_pareto', False),
        }
        btn_map = {
            'layout': self.btn_tab_layout,
            'temp':   self.btn_tab_temp,
            'pres':   self.btn_tab_pres,
            'vel':    self.btn_tab_vel,
            '3d':     self.btn_tab_3d,
            'pareto': self.btn_tab_pareto,
        }
        for key, visible in rules.items():
            btn_map[key].setVisible(visible)
            card = self._canvas_cards.get(key)
            if card is not None and not visible:
                card.hide()
        # Fall back to Layout if active tab just vanished
        if not rules.get(getattr(self, '_active_tab', 'layout'), True):
            self._switch_tab('layout')

    def _switch_tab(self, tab: str):
        # Reject clicks on hidden tabs (defensive — buttons are hidden anyway)
        btn_lookup = {
            'layout': getattr(self, 'btn_tab_layout', None),
            'temp':   getattr(self, 'btn_tab_temp', None),
            'pres':   getattr(self, 'btn_tab_pres', None),
            'vel':    getattr(self, 'btn_tab_vel', None),
            '3d':     getattr(self, 'btn_tab_3d', None),
            'pareto': getattr(self, 'btn_tab_pareto', None),
        }
        target_btn = btn_lookup.get(tab)
        if target_btn is not None and target_btn.isHidden() and tab != 'layout':
            tab = 'layout'

        self._active_tab = tab
        tabs = [
            ('temp',   self.btn_tab_temp),
            ('pres',   self.btn_tab_pres),
            ('vel',    self.btn_tab_vel),
            ('layout', self.btn_tab_layout),
            ('pareto', self.btn_tab_pareto),
            ('3d',     self.btn_tab_3d),
        ]
        drawn = getattr(self, '_drawn_tabs', set())
        for key, btn in tabs:
            card = self._canvas_cards.get(key)
            if key == tab:
                if card and (getattr(self, '_has_results', False)
                             or key in drawn):
                    card.show()
                elif key == '3d':
                    # No 3D compute yet — hide card + gentle hint instead of
                    # rendering a heavyweight placeholder (which was what made
                    # the first tab-click feel slow). User runs Compute →
                    # finalize_plots_3d will populate + show.
                    if card:
                        card.hide()
                    self.statusBar().showMessage(
                        "3D view is empty — switch to 3D mode in Domain panel "
                        "and click Run Calculation to populate.", 6000)
                btn.setStyleSheet(self._PTAB_ON)
            else:
                if card: card.hide()
                btn.setStyleSheet(self._PTAB_OFF)
        self._hover_label.setText("")

    def _on_hover(self, event):
        """Show data value at mouse position on contour plots."""
        if event.inaxes is None or event.xdata is None:
            self._hover_label.setText("")
            return

        # Find which canvas this event belongs to
        canvas = event.canvas
        hd = getattr(canvas, '_hover_data', None)
        if not hd:
            return

        # Convert mm coordinates to grid indices
        x_mm, y_mm = event.xdata, event.ydata
        L, H = hd['L'], hd['H']
        Nx, Ny = hd['Nx'], hd['Ny']
        i = int(x_mm / 1000 / L * Nx)
        j = int(y_mm / 1000 / H * Ny)
        i = max(0, min(i, Nx - 1))
        j = max(0, min(j, Ny - 1))

        # Find which subplot the mouse is in
        axes = [ax for row in canvas.axes for ax in row]
        ax_idx = -1
        for k, ax in enumerate(axes):
            if event.inaxes is ax:
                ax_idx = k
                break

        if ax_idx < 0 or ax_idx >= len(hd['fields']):
            self._hover_label.setText(f"x={x_mm:.1f}mm, y={y_mm:.1f}mm")
            return

        val = hd['fields'][ax_idx][i, j]
        name = hd['names'][ax_idx]
        unit = hd['unit']
        self._hover_label.setText(
            f"x={x_mm:.1f}mm, y={y_mm:.1f}mm  |  {name} = {val:.2f} {unit}")

    # ─────────────────────────────────────────────────────────
    #  Theme toggle
    # ─────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────
    #  Multi-objective optimization
    # ─────────────────────────────────────────────────────────
    def _run_optimize(self):
        from ui.optimize_panel import run_optimize
        return run_optimize(self)

    def _reshow_pareto(self):
        from ui.optimize_panel import reshow_pareto
        return reshow_pareto(self)

    def _show_pareto(self, res):
        from ui.optimize_panel import show_pareto
        return show_pareto(self, res)

    def _on_pareto_pick(self, event):
        from ui.optimize_panel import on_pareto_pick
        return on_pareto_pick(self, event)

    def _save_opt_results(self, res, cfg):
        from ui.optimize_panel import save_opt_results
        return save_opt_results(self, res, cfg)

    def _load_pareto_solution(self, x):
        from ui.optimize_panel import load_pareto_solution
        return load_pareto_solution(self, x)

    # ─────────────────────────────────────────────────────────
    #  Layout helpers
    # ─────────────────────────────────────────────────────────
    def _section(self, parent_lay, title, title_style, frame_style):
        from ui.ui_builders import section
        return section(self, parent_lay, title, title_style, frame_style)

    def _row(self, g, row, text, default) -> QLineEdit:
        from ui.ui_builders import row as _row_impl
        return _row_impl(self, g, row, text, default)

    def _res_row(self, g, row, text, col=0) -> QLabel:
        from ui.ui_builders import res_row
        return res_row(self, g, row, text, col)

    def _add_row(self, g, row, text, widget):
        from ui.ui_builders import add_row
        return add_row(self, g, row, text, widget)

    # ─────────────────────────────────────────────────────────
    #  Zone configuration helpers
    # ─────────────────────────────────────────────────────────
    def _zone_mode_changed(self, idx):
        from solvers.zone_editor import zone_mode_changed
        return zone_mode_changed(self, idx)

    def _zone_is_grid(self):
        from solvers.zone_editor import zone_is_grid
        return zone_is_grid(self)

    def _zone_init_1d(self, n):
        from solvers.zone_editor import zone_init_1d
        return zone_init_1d(self, n)

    def _zone_add_row(self):
        from solvers.zone_editor import zone_add_row
        return zone_add_row(self)

    def _zone_remove_row(self):
        from solvers.zone_editor import zone_remove_row
        return zone_remove_row(self)

    def _zone_add_col(self):
        from solvers.zone_editor import zone_add_col
        return zone_add_col(self)

    def _zone_remove_col(self):
        from solvers.zone_editor import zone_remove_col
        return zone_remove_col(self)

    def _zone_rebuild_grid(self, ny=None):
        from solvers.zone_editor import zone_rebuild_grid
        return zone_rebuild_grid(self, ny)

    def _zone_resize(self):
        from solvers.zone_editor import zone_resize
        return zone_resize(self)

    def _zone_axis(self):
        from solvers.zone_editor import zone_axis
        return zone_axis(self)

    def _build_zone_config(self):
        from solvers.zone_editor import build_zone_config
        return build_zone_config(self)

    # ─────────────────────────────────────────────────────────
    #  TPMS geometry + time-constant helpers
    # ─────────────────────────────────────────────────────────
    def compute_tpms(self) -> bool:
        """Compute pure geometry (ε, A₀, D_h, K_ss) from TPMS inputs. Returns True on success."""
        self.statusBar().showMessage("Computing TPMS geometry...")
        QApplication.processEvents()
        try:
            r = tpms_geometry(
                self.combo_tpms.currentText(),
                float(self.le_Lcell.text()),
                float(self.le_t.text()),
                float(self.le_ks.text()))
        except Exception as e:
            QMessageBox.critical(self, "TPMS Geometry Error", str(e))
            return False

        self._eps_A = r['epsilon']
        self._K_ss  = r['K_ss']

        self._v_eps.setText(f"{r['epsilon']:.5f}")
        self._v_A0.setText(f"{r['A_0']:.2f}")
        self._v_Dh.setText(f"{r['D_h'] * 1000:.4f}")
        self._v_Kss.setText(f"{r['K_ss']:.5f}")

        # Auto-update suggested grid from D_h.
        #   2D: alpha=0.4 (~5% Q accuracy)
        #   3D: alpha=1.0 (streamwise x), 0.5 (cross-stream y, z) — with
        #       wall-refine adding 16 BL cells/axis, N_user ~ 2-3x Nx_target
        #       gives "paper-run" ~90k-cell refined grid matching Shanghai
        #       17.83% RMSRE baseline without runaway timing.
        is_3d = (hasattr(self, 'combo_dim')
                 and self.combo_dim.currentIndex() == 1)
        try:
            L_dom = float(self.le_L.text())
            H_dom = float(self.le_H.text())
            if is_3d:
                try:
                    Lz_dom = float(self.le_Lz.text())
                except ValueError:
                    Lz_dom = 0.02
                D_h = r['D_h']
                # Stream axis coarser (flow is near-1D), cross-axes finer for BL
                Nx_sug = max(14, round(L_dom / (1.0 * D_h)))
                Ny_sug = max(8,  round(H_dom / (0.5 * D_h)))
                Nz_sug = max(3,  round(Lz_dom / (0.5 * D_h)))
                # Cap to keep refined total cells under ~100k
                # (user_cells + 16 per axis tensor-product)
                while ((Nx_sug + 16) * (Ny_sug + 16) * (Nz_sug + 16)
                       > 150_000 and Nx_sug > 14):
                    Nx_sug = max(14, int(Nx_sug * 0.8))
                # Only overwrite if user hasn't manually edited grid fields —
                # otherwise Auto-fill (which calls compute_tpms) would stomp
                # on user's custom Nx/Ny/Nz between TPMS Compute and Run.
                if not getattr(self, '_user_edited_grid', False):
                    self.le_Nx.setText(str(Nx_sug))
                    self.le_Ny.setText(str(Ny_sug))
                    self.le_Nz.setText(str(Nz_sug))
            else:
                Nx_sug, Ny_sug = adaptive_grid(L_dom, H_dom, r['D_h'], alpha=0.4)
                if not getattr(self, '_user_edited_grid', False):
                    self.le_Nx.setText(str(Nx_sug))
                    self.le_Ny.setText(str(Ny_sug))
        except ValueError:
            pass  # L or H not yet filled

        self.statusBar().showMessage(
            f"TPMS geometry: eps={r['epsilon']:.4f}  A_0={r['A_0']:.1f}  D_h={r['D_h']*1000:.3f}mm", 5000)
        return True

    def _update_tout(self, t_idx: int):
        """Update outlet temperature display using actual flow directions."""
        dir_A = self._dir_int(self.combo_dirA)
        dir_B = self._dir_int(self.combo_dirB)
        # Fluid A outlet
        if dir_A == 0:   ta = np.mean(self.T_fA[t_idx, -1, :])
        elif dir_A == 1: ta = np.mean(self.T_fA[t_idx, 0, :])
        elif dir_A == 2: ta = np.mean(self.T_fA[t_idx, :, -1])
        else:            ta = np.mean(self.T_fA[t_idx, :, 0])
        self._r_ToutA.setText(f"{ta:.2f}")
        # Fluid B outlet
        if dir_B == 0:   tb = np.mean(self.T_fB[t_idx, -1, :])
        elif dir_B == 1: tb = np.mean(self.T_fB[t_idx, 0, :])
        elif dir_B == 2: tb = np.mean(self.T_fB[t_idx, :, -1])
        else:            tb = np.mean(self.T_fB[t_idx, :, 0])
        self._r_ToutB.setText(f"{tb:.2f}")

    # ─────────────────────────────────────────────────────────
    #  Auto-fill callbacks
    # ─────────────────────────────────────────────────────────
    def _auto_fill_fluid(self, fluid: str):
        if not self.compute_tpms():
            return
        le_u, le_Tin, le_Pin = {
            'A': (self.le_uA, self.le_TinA, self.le_PinA),
            'B': (self.le_uB, self.le_TinB, self.le_PinB),
        }[fluid]
        try:
            r = tpms_compute(
                self.combo_tpms.currentText(),
                float(self.le_Lcell.text()), float(self.le_t.text()),
                float(le_u.text()), float(le_Tin.text()),
                float(le_Pin.text()), float(self.le_ks.text()))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return

        # Convert face HTC [W/(m2K)] to volumetric HTC [W/(m3K)]
        h_v_vol = r['A_0'] * r['H_sf']    # h_v = H_sf_face * A_0
        u_val = float(le_u.text())
        U_sf = u_val * r['epsilon']

        # Re range check
        Re = r['Re']
        re_style = _VAL
        re_tag = ""
        if Re < 600:
            re_style = _VAL_WARN
            re_tag = "  (< 600!)"
        elif Re > 30000:
            re_style = _VAL_WARN
            re_tag = "  (> 30000!)"

        self.statusBar().showMessage(f"Fluid {fluid} filled.  Re={Re:.0f}{re_tag}  Nu={r['Nu']:.2f}  dP/L={r['dP_per_L']:.1f} Pa/m", 5000)
        if fluid == 'A':
            self._mu_A, self._h_vA, self._K_ffA, self._rho_A = r['mu'], h_v_vol, r['K_ff'], r['rho']
            self._v_rhoA.setText(f"{r['rho']:.4f}")
            self._v_ReA.setText(f"{Re:.1f}{re_tag}")
            self._v_ReA.setStyleSheet(re_style)
            self._v_NuA.setText(f"{r['Nu']:.4f}")
            self._v_dPLA.setText(f"{r['dP_per_L']:.1f}")
        else:
            self._mu_B, self._h_vB, self._K_ffB, self._rho_B = r['mu'], h_v_vol, r['K_ff'], r['rho']
            self._v_rhoB.setText(f"{r['rho']:.4f}")
            self._v_ReB.setText(f"{Re:.1f}{re_tag}")
            self._v_ReB.setStyleSheet(re_style)
            self._v_NuB.setText(f"{r['Nu']:.4f}")
            self._v_dPLB.setText(f"{r['dP_per_L']:.1f}")

    def auto_fill_fluid_a(self): self._auto_fill_fluid('A')
    def auto_fill_fluid_b(self): self._auto_fill_fluid('B')

    # ─────────────────────────────────────────────────────────
    #  Save / Load configuration
    # ─────────────────────────────────────────────────────────
    def save_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Config", "SJTU-TPMSHX_config.json",
            "JSON Files (*.json)")
        if not path:
            return
        cfg = {
            # Domain
            "L":         self.le_L.text(),
            "H":         self.le_H.text(),
            "T_init_s":  self.le_T_init_s.text(),
            # Solid
            "rho_s":     self.le_rho_s.text(),
            "cp_s":      self.le_cp_s.text(),
            # Fluid
            "cp_f":      self.le_cp_f.text(),
            # Solver
            "Nx":        self.le_Nx.text(),
            "Ny":        self.le_Ny.text(),
            # TPMS
            "tpms_type": self.combo_tpms.currentText(),
            "L_cell":    self.le_Lcell.text(),
            "t":         self.le_t.text(),
            "k_s":       self.le_ks.text(),
            # Fluid A
            "u_A":       self.le_uA.text(),
            "T_inA":     self.le_TinA.text(),
            "P_inA":     self.le_PinA.text(),
            # Fluid B
            "u_B":       self.le_uB.text(),
            "T_inB":     self.le_TinB.text(),
            "P_inB":     self.le_PinB.text(),
            # Direction & pipe geometry
            "dir_A": self.combo_dirA.currentIndex(),
            "dir_B": self.combo_dirB.currentIndex(),
            "pipeA_in_ctr":  self.le_pipeA_in_ctr.text(),
            "pipeA_in_w":    self.le_pipeA_in_w.text(),
            "pipeA_out_ctr": self.le_pipeA_out_ctr.text(),
            "pipeA_out_w":   self.le_pipeA_out_w.text(),
            #"transA": removed (full-domain solve)
            "pipeB_in_ctr":  self.le_pipeB_in_ctr.text(),
            "pipeB_in_w":    self.le_pipeB_in_w.text(),
            "pipeB_out_ctr": self.le_pipeB_out_ctr.text(),
            "pipeB_out_w":   self.le_pipeB_out_w.text(),
            #"transB": removed (full-domain solve)
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def load_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Config", "",
            "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e)); return

        def _set(le, key):
            if key in cfg: le.setText(str(cfg[key]))

        _set(self.le_L,        "L")
        _set(self.le_H,        "H")
        _set(self.le_T_init_s, "T_init_s")
        _set(self.le_rho_s,    "rho_s")
        _set(self.le_cp_s,     "cp_s")
        _set(self.le_cp_f,     "cp_f")
        _set(self.le_Nx,       "Nx")
        _set(self.le_Ny,       "Ny")
        _set(self.le_Lcell,    "L_cell")
        _set(self.le_t,        "t")
        _set(self.le_ks,       "k_s")
        _set(self.le_uA,       "u_A")
        _set(self.le_TinA,     "T_inA")
        _set(self.le_PinA,     "P_inA")
        _set(self.le_uB,       "u_B")
        _set(self.le_TinB,     "T_inB")
        _set(self.le_PinB,     "P_inB")
        # Pipe geometry
        _set(self.le_pipeA_in_ctr,  "pipeA_in_ctr")
        _set(self.le_pipeA_in_w,    "pipeA_in_w")
        _set(self.le_pipeA_out_ctr, "pipeA_out_ctr")
        _set(self.le_pipeA_out_w,   "pipeA_out_w")
        # transA/B removed (full-domain solve)
        _set(self.le_pipeB_in_ctr,  "pipeB_in_ctr")
        _set(self.le_pipeB_in_w,    "pipeB_in_w")
        _set(self.le_pipeB_out_ctr, "pipeB_out_ctr")
        _set(self.le_pipeB_out_w,   "pipeB_out_w")
        # (see above)

        if "tpms_type" in cfg:
            idx = self.combo_tpms.findText(cfg["tpms_type"])
            if idx >= 0: self.combo_tpms.setCurrentIndex(idx)
        if "dir_A" in cfg:
            self.combo_dirA.setCurrentIndex(int(cfg["dir_A"]))
        if "dir_B" in cfg:
            self.combo_dirB.setCurrentIndex(int(cfg["dir_B"]))

    # ─────────────────────────────────────────────────────────
    #  Inlet / Outlet helpers (unified)
    # ─────────────────────────────────────────────────────────
    _DIR_MAP = {0: '+x', 1: '-x', 2: '+y', 3: '-y', 4: '+z', 5: '-z'}

    def _dir_int(self, combo):
        # 0=+x 1=-x 2=+y 3=-y 4=+z 5=-z (z-dirs: 3D only)
        return combo.currentIndex()

    def _is_x_dir(self, d): return d in (0, 1)
    def _is_y_dir(self, d): return d in (2, 3)
    def _is_z_dir(self, d): return d in (4, 5)

    def _inlet_wall(self, d):
        return {0: 'left', 1: 'right', 2: 'bottom', 3: 'top',
                4: 'front', 5: 'back'}[d]
    def _outlet_wall(self, d):
        return {0: 'right', 1: 'left', 2: 'top', 3: 'bottom',
                4: 'back', 5: 'front'}[d]

    def _on_dir_changed(self):
        """Relabel inlet/outlet fields to match selected flow-axis.

        dir 0/1 (±x) stream → cross1 = Y, cross2 = Z
        dir 2/3 (±y) stream → cross1 = X, cross2 = Z
        dir 4/5 (±z) stream → cross1 = X, cross2 = Y
        The UI fields `in_ctr/in_w/out_ctr/out_w` always control cross1;
        `in_z_ctr` etc. always control cross2 — labels show the real axis
        so user knows which coord they're editing.
        """
        _axis_by_dir = {
            0: ('Y', 'Z'), 1: ('Y', 'Z'),
            2: ('X', 'Z'), 3: ('X', 'Z'),
            4: ('X', 'Y'), 5: ('X', 'Y'),
        }
        for combo, prefix in [(self.combo_dirA, 'pipeA'),
                              (self.combo_dirB, 'pipeB')]:
            c1, c2 = _axis_by_dir.get(combo.currentIndex(), ('Y', 'Z'))
            for io, cap in (('in', 'Inlet'), ('out', 'Outlet')):
                for kind, suffix in (('ctr', 'centre'), ('w', 'width')):
                    lbl1 = getattr(self, f'_lbl_{prefix}_{io}_{kind}', None)
                    if lbl1 is not None:
                        lbl1.setText(f"{cap} {c1}-{suffix} [m]")
                    lbl2 = getattr(self, f'_lbl_{prefix}_{io}_z_{kind}', None)
                    if lbl2 is not None:
                        lbl2.setText(f"{cap} {c2}-{suffix} [m] (3D)")

    def _on_shape_changed(self, idx):
        """Show/hide controls based on domain shape (Rectangle vs Polygon)."""
        is_poly = idx > 0
        # Show polygon pipe edge config
        self._poly_pipe_frame.setVisible(is_poly)
        self._poly_pipe_label.setVisible(is_poly)
        # Hide rect-only controls
        for w in self._rect_only_widgets:
            w.setVisible(not is_poly)
        # Show polygon-only controls
        for w in self._poly_only_widgets:
            w.setVisible(is_poly)
        if is_poly:
            self._update_edge_combos()

    def _fluid_config(self, which):
        """Read config for fluid A or B. Returns dict (optional z-partial keys
        for fluid A: `in_z_ctr`, `in_z_w`, `out_z_ctr`, `out_z_w`)."""
        if which == 'A':
            d = self._dir_int(self.combo_dirA)
            cfg = dict(dir=d,
                in_ctr=float(self.le_pipeA_in_ctr.text()),
                in_w=float(self.le_pipeA_in_w.text()),
                out_ctr=float(self.le_pipeA_out_ctr.text()),
                out_w=float(self.le_pipeA_out_w.text()))
            # z-partial (only when 3D mode shows the fields)
            if (hasattr(self, 'le_pipeA_in_z_ctr')
                    and not self.le_pipeA_in_z_ctr.isHidden()):
                try:
                    cfg['in_z_ctr']  = float(self.le_pipeA_in_z_ctr.text())
                    cfg['in_z_w']    = float(self.le_pipeA_in_z_w.text())
                    cfg['out_z_ctr'] = float(self.le_pipeA_out_z_ctr.text())
                    cfg['out_z_w']   = float(self.le_pipeA_out_z_w.text())
                except ValueError:
                    pass
            return cfg
        else:
            d = self._dir_int(self.combo_dirB)
            cfg = dict(dir=d,
                in_ctr=float(self.le_pipeB_in_ctr.text()),
                in_w=float(self.le_pipeB_in_w.text()),
                out_ctr=float(self.le_pipeB_out_ctr.text()),
                out_w=float(self.le_pipeB_out_w.text()))
            # z-partial (only when 3D mode shows the fields)
            if (hasattr(self, 'le_pipeB_in_z_ctr')
                    and not self.le_pipeB_in_z_ctr.isHidden()):
                try:
                    cfg['in_z_ctr']  = float(self.le_pipeB_in_z_ctr.text())
                    cfg['in_z_w']    = float(self.le_pipeB_in_z_w.text())
                    cfg['out_z_ctr'] = float(self.le_pipeB_out_z_ctr.text())
                    cfg['out_z_w']   = float(self.le_pipeB_out_z_w.text())
                except ValueError:
                    pass
            return cfg

    def _update_edge_combos(self):
        """Populate edge combo boxes with readable edge descriptions."""
        from solvers import unstructured_mesh as um
        try:
            L = float(self.le_L.text())
            H = float(self.le_H.text())
        except ValueError:
            return
        shape = self.combo_shape.currentText()
        if shape == 'Hexagon':
            verts = um.hexagon(L, H)
        elif shape == 'Octagon':
            verts = um.octagon(L, H)
        else:
            return
        n_v = len(verts)
        cx, cy = verts[:, 0].mean(), verts[:, 1].mean()

        items = []
        for i in range(n_v):
            p0, p1 = verts[i], verts[(i + 1) % n_v]
            mid = 0.5 * (p0 + p1)
            # Descriptive direction label
            dx, dy = mid[0] - cx, mid[1] - cy
            if abs(dx) > abs(dy):
                side = "Right" if dx > 0 else "Left"
            else:
                side = "Top" if dy > 0 else "Bottom"
            edge = p1 - p0
            elen = np.linalg.norm(edge) * 1000
            items.append(f"E{i}: {side} ({elen:.1f} mm)")

        for cb in (self.combo_edge_inA, self.combo_edge_outA,
                   self.combo_edge_inB, self.combo_edge_outB):
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(items)
            cb.blockSignals(False)
        # Defaults: A left->right, B bottom->top
        if shape == 'Octagon' and n_v == 8:
            self.combo_edge_inA.setCurrentIndex(6)
            self.combo_edge_outA.setCurrentIndex(2)
            self.combo_edge_inB.setCurrentIndex(0)
            self.combo_edge_outB.setCurrentIndex(4)
        elif shape == 'Hexagon' and n_v == 6:
            self.combo_edge_inA.setCurrentIndex(5)
            self.combo_edge_outA.setCurrentIndex(2)
            self.combo_edge_inB.setCurrentIndex(0)
            self.combo_edge_outB.setCurrentIndex(3)

    def _draw_layout(self):
        from ui.layout_drawer import draw_layout
        return draw_layout(self)

    def _draw_layout_rect(self, ax, L, H, Lmm, Hmm):
        from ui.layout_drawer import draw_layout_rect
        return draw_layout_rect(self, ax, L, H, Lmm, Hmm)

    def _draw_layout_polygon(self, ax, L, H, Lmm, Hmm):
        from ui.layout_drawer import draw_layout_polygon
        return draw_layout_polygon(self, ax, L, H, Lmm, Hmm)

    # ─────────────────────────────────────────────────────────
    #  Solver
    # ─────────────────────────────────────────────────────────
    def run_calculation(self):
        """Full-domain solve: SIMPLE velocity → coupled energy on L × H."""
        # Polygon solver runs on main thread (has its own processEvents)
        if self.combo_shape.currentIndex() > 0:
            self._run_polygon_calculation()
            return

        # 3D dispatch: uniform MVP path (no zoning, Shanghai-style uniform TPMS)
        if hasattr(self, 'combo_dim') and self.combo_dim.currentIndex() == 1:
            self._run_calculation_3d()
            return

        # Validate inputs BEFORE launching thread (Qt-safe on main thread)
        if self._K_ffA is None:
            QMessageBox.warning(self, "Missing Input",
                                "Please click 'Auto-fill Fluid A' first."); return
        if self._K_ffB is None:
            QMessageBox.warning(self, "Missing Input",
                                "Please click 'Auto-fill Fluid B' first."); return

        self.progress.show()
        self.progress.setValue(10)
        self.statusBar().showMessage("Computing...")
        QApplication.processEvents()

        import threading
        from PySide6.QtCore import QTimer

        self._compute_progress = 10  # shared progress value for worker thread

        def _worker():
            try:
                self._run_calculation_inner()
                self._compute_error = None
            except Exception as e:
                self._compute_error = str(e)
                import traceback; traceback.print_exc()

        self._compute_error = None
        t = threading.Thread(target=_worker, daemon=True)
        t.start()

        # Poll for completion — ALL Qt updates happen here (main thread)
        timer = QTimer()
        def _check():
            if t.is_alive():
                self.progress.setValue(min(90, self._compute_progress))
                return
            timer.stop()
            if self._compute_error:
                self.progress.hide()
                QMessageBox.critical(self, "Compute Error", self._compute_error)
            else:
                # Render plots on main thread using stored results
                self._finalize_plots()
                self.progress.setValue(100)
                from PySide6.QtCore import QTimer as QT
                QT.singleShot(500, self.progress.hide)
                self._has_results = True
                self._has_results_2d = True
                self._update_tab_visibility()
                self._switch_tab('temp')
                self.statusBar().showMessage("Done.", 5000)
        timer.timeout.connect(_check)
        timer.start(200)

    def _run_calculation_inner(self):
        """Thin wrapper — delegates to run_calculation module (Task B.9)."""
        from runs.run_calculation import run_calculation_inner
        return run_calculation_inner(self)

    def _finalize_plots(self):
        """Thin wrapper — delegates to run_calculation module (Task B.9)."""
        from runs.run_calculation import finalize_plots
        return finalize_plots(self)

    # ─────────────────────────────────────────────────────────
    #  3D compute pipeline (uniform MVP)
    # ─────────────────────────────────────────────────────────
    def closeEvent(self, event):
        """Tear down PyVistaQt GL context before Qt destroys the widgets."""
        panel = getattr(self, 'canvas_3d', None)
        if panel is not None:
            try:
                panel.cleanup()
            except Exception:
                pass
        super().closeEvent(event)

    def _lazy_init_3d_panel(self):
        """Create PyVistaQt panel on first 3D tab click. ~1-2 s hit amortised."""
        if getattr(self, '_vis3d_import_error', None):
            return      # Offscreen / disabled — leave placeholder
        try:
            from ui.panel_vis_3d import ThreeDVisPanel
            panel = ThreeDVisPanel()
        except Exception as e:
            self._vis3d_import_error = str(e)
            return
        # Swap placeholder → real panel in the card layout
        card = self._canvas_cards.get('3d')
        if card is None:
            return
        placeholder = getattr(self, '_canvas_3d_placeholder', None)
        lay = card.layout()
        if placeholder is not None and lay is not None:
            lay.replaceWidget(placeholder, panel)
            placeholder.deleteLater()
        self._canvas_3d_placeholder = None
        self.canvas_3d = panel
        self.statusBar().showMessage("3D view initialised.", 2000)

    def _run_calculation_3d(self):
        """Threaded 3D solve → auto-switch to 3D View tab on success."""
        # Lazy-init 3D panel if user never clicked 3D tab before
        if self.canvas_3d is None:
            self._lazy_init_3d_panel()
        if self.canvas_3d is None:
            err = getattr(self, '_vis3d_import_error',
                          'PyVistaQt unavailable (headless or missing pyvistaqt)')
            QMessageBox.warning(
                self, "3D View Unavailable",
                f"The embedded 3D viewer is not available:\n\n{err}\n\n"
                "Run `pip install pyvistaqt` or use the standalone script\n"
                "`python -u ui/demo_vis_3d_interactive.py` instead.")
            return

        # Large-grid warning (wall-refine expands cells ~6-9x)
        try:
            Nx_u = int(self.le_Nx.text()); Ny_u = int(self.le_Ny.text())
            Nz_u = int(self.le_Nz.text())
            est_cells = (Nx_u + 16) * (Ny_u + 16) * (Nz_u + 16)
        except Exception:
            est_cells = 0
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
                return

        self.progress.show()
        self.progress.setValue(10)
        import time as _time
        self._compute_t0 = _time.time()
        Nx_r, Ny_r, Nz_r = Nx_u + 16, Ny_u + 16, Nz_u + 16
        est_cells_r = Nx_r * Ny_r * Nz_r
        self.statusBar().showMessage(
            f"Computing 3D (refined {Nx_r}×{Ny_r}×{Nz_r} = {est_cells_r:,} cells, "
            f"compressible dual-fluid SIMPLE; typical ~2–10 min)…")
        QApplication.processEvents()

        import threading
        from PySide6.QtCore import QTimer

        self._compute_progress = 10

        def _worker():
            try:
                from runs.run_calculation_3d import run_calculation_3d_inner
                run_calculation_3d_inner(self)
                self._compute_error = None
            except Exception as e:
                self._compute_error = str(e)
                import traceback; traceback.print_exc()

        self._compute_error = None
        t = threading.Thread(target=_worker, daemon=True)
        t.start()

        timer = QTimer()
        def _check():
            if t.is_alive():
                self.progress.setValue(min(90, self._compute_progress))
                elapsed = _time.time() - self._compute_t0
                self.statusBar().showMessage(
                    f"Computing 3D… {elapsed:5.0f} s elapsed ({est_cells_r:,} cells)")
                return
            timer.stop()
            if self._compute_error:
                self.progress.hide()
                QMessageBox.critical(self, "3D Compute Error", self._compute_error)
            else:
                from runs.run_calculation_3d import finalize_plots_3d
                finalize_plots_3d(self)
                self.progress.setValue(100)
                from PySide6.QtCore import QTimer as QT
                QT.singleShot(500, self.progress.hide)
                self._has_results = True
                self._has_results_3d = True
                drawn = getattr(self, '_drawn_tabs', set())
                # All 2D canvases also populated via mid-z slice — mark drawn
                for k in ('3d', 'temp', 'pres', 'vel'):
                    drawn.add(k)
                self._drawn_tabs = drawn
                self._update_tab_visibility()
                self._switch_tab('3d')
                res = getattr(self, '_result_3d', {})
                self.statusBar().showMessage(
                    f"3D done — Q={res.get('Q', 0):.1f} W  dP={res.get('dP', 0):.0f} Pa",
                    6000,
                )
        timer.timeout.connect(_check)
        timer.start(200)

    # ─────────────────────────────────────────────────────────
    #  Polygon domain solver
    # ─────────────────────────────────────────────────────────
    def _run_polygon_calculation(self):
        from solvers.polygon_calc import run_polygon_calculation
        return run_polygon_calculation(self)

    # ─────────────────────────────────────────────────────────
    #  Slider callback
    # ─────────────────────────────────────────────────────────
    def update_graph_from_slider(self, value):
        if self.T_fA is None:
            return
        c = self.canvas_temp
        if c.X is None or c.time_text is None:
            return
        t = 0  # steady-state only; slider is legacy
        for ax in c.axes[0]:
            ax.cla()
        kw_f = dict(levels=100, cmap="turbo",
                    vmin=c.min_temp, vmax=c.max_temp)
        kw_s = dict(levels=100, cmap="coolwarm",
                    vmin=c.min_s, vmax=c.max_s)
        c.axes[0][0].contourf(c.X, c.Y, self.T_fA[value], **kw_f)
        c.axes[0][1].contourf(c.X, c.Y, self.T_fB[value], **kw_f)
        c.axes[0][2].contourf(c.X, c.Y, self.T_s[value],  **kw_s)
        mode_label = f"A:{self._DIR_MAP[self._dir_int(self.combo_dirA)]} " \
                     f"B:{self._DIR_MAP[self._dir_int(self.combo_dirB)]}"
        _label_axes(c.axes[0], c.L, c.H, mode_label)
        c.fig.canvas.draw_idle()
        c.time_text.set_text(rf"$\mathbf{{t = {t:.4f}}}$ s")
        self._update_tout(value)

    def _export_figure(self):
        """Export a chosen figure to PNG/SVG/PDF."""
        items = ["Temperature", "Pressure", "Velocity", "Geometry"]
        tab_keys = ['temp', 'pres', 'vel', 'layout']
        tab_canvas = {'temp': self.canvas_temp, 'pres': self.canvas_pres,
                      'vel': self.canvas_vel, 'layout': self.canvas_layout}
        choice, ok = QInputDialog.getItem(
            self, "Export Figure", "Select figure to export:",
            items, 0, False)
        if not ok:
            return
        key = tab_keys[items.index(choice)]
        canvas = tab_canvas[key]
        default = f"SJTU-TPMSHX_{key}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Figure", default,
            "PNG (*.png);;SVG (*.svg);;PDF (*.pdf);;All Files (*)")
        if path:
            canvas.fig.savefig(path, dpi=300, bbox_inches='tight',
                               facecolor=canvas.fig.get_facecolor())
            self.statusBar().showMessage(f"Exported: {path}", 5000)


# ── Entry point ───────────────────────────────────────────────
def _apply_app_font(app):
    """Pick modern sans-serif (Inter / Segoe UI / Roboto) for UI chrome.

    Monospace (JetBrainsMono) is reserved for chart tick labels only; UI chrome
    uses sans-serif per 2026-04-21 redesign request.
    """
    from PySide6.QtGui import QFont, QFontDatabase
    candidates = [
        "Inter", "Inter Display",
        "Segoe UI", "Segoe UI Variable",
        "Roboto",
        "Helvetica Neue", "Arial",
    ]
    families = set(QFontDatabase.families())
    chosen = next((n for n in candidates if n in families), None)
    if chosen is None:
        print("[font] no sans-serif candidate found; system default")
        return None
    app.setFont(QFont(chosen, 10))
    print(f"[font] using {chosen!r}")
    return chosen


if __name__ == "__main__":
    # High-DPI + font smoothing before QApplication instantiation
    from PySide6.QtCore import Qt as _Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        _Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    import os as _os_main
    _os_main.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')
    app = QApplication.instance() or QApplication(sys.argv)
    # Force grayscale anti-aliasing to eliminate sub-pixel color fringing
    from PySide6.QtGui import QFont
    font = app.font()
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    _apply_app_font(app)
    window = Main_Menu()
    window.show()
    sys.exit(app.exec())
