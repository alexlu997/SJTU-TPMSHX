import sys
import json
import warnings
import numpy as np
import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.ticker import FormatStrFormatter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QGridLayout,
    QMessageBox, QFrame, QLabel, QLineEdit, QPushButton, QComboBox,
    QScrollArea, QSplitter, QWidget, QSlider, QSizePolicy, QFileDialog,
    QProgressBar, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QStackedWidget, QInputDialog,
)

from mainui import Ui_MainWindow
from tpms_calc import compute as tpms_compute, geometry as tpms_geometry, compute_pressure_field, adaptive_grid
from simple_solver import SIMPLESolver
from solve_full import solve_full_domain
from matplotlib_canvas import MatplotlibCanvas, _label_axes
from theme import _THEMES, _build_styles

# Theme dict and _build_styles moved to theme.py (Task B.3).
# Light-only as of D-1 (dark mode + toggle removed).

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
        self.setWindowTitle("Homogenization")
        self.resize(1350, 1100)
        self.setMinimumSize(900, 720)
        self.showMaximized()

        # App icon
        import os
        from PySide6.QtGui import QIcon
        _icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings_options_preferences_gears_icon_124617.ico')
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

    # ─────────────────────────────────────────────────────────
    #  Top-level layout
    # ─────────────────────────────────────────────────────────
    def _build_ui(self):
        from ui_builders import build_ui
        return build_ui(self)

    # ─────────────────────────────────────────────────────────
    #  Param tabs container (3 tab buttons + QStackedWidget)
    # ─────────────────────────────────────────────────────────
    def _build_param_tabs(self) -> QWidget:
        from ui_builders import build_param_tabs
        return build_param_tabs(self)

    def _switch_param_tab(self, index):
        from ui_builders import switch_param_tab
        return switch_param_tab(self, index)

    # ─────────────────────────────────────────────────────────
    #  Page 1 — Domain / TPMS / Material / Grid / Results
    # ─────────────────────────────────────────────────────────
    def _build_page_domain(self) -> QScrollArea:
        from ui_builders import build_page_domain
        return build_page_domain(self)

    # ─────────────────────────────────────────────────────────
    #  Page 2 — Fluid A / Fluid B config + pipe geometry
    # ─────────────────────────────────────────────────────────
    def _build_page_fluids(self) -> QScrollArea:
        from ui_builders import build_page_fluids
        return build_page_fluids(self)

    # ─────────────────────────────────────────────────────────
    #  Page 3 — Zone configuration (expanding height)
    # ─────────────────────────────────────────────────────────
    def _build_page_zones(self) -> QScrollArea:
        from ui_builders import build_page_zones
        return build_page_zones(self)

    # ─────────────────────────────────────────────────────────
    #  Canvas area — tab-switched, vertical scrolling
    # ─────────────────────────────────────────────────────────
    def _build_canvas_area(self) -> QWidget:
        from ui_builders import build_canvas_area
        return build_canvas_area(self)

    def _canvas_zoom(self, factor):
        from ui_builders import canvas_zoom
        return canvas_zoom(self, factor)

    def _canvas_zoom_reset(self):
        from ui_builders import canvas_zoom_reset
        return canvas_zoom_reset(self)

    def _canvas_wheel_zoom(self, event, canvas, key):
        from ui_builders import canvas_wheel_zoom
        return canvas_wheel_zoom(self, event, canvas, key)

    def _switch_tab(self, tab: str):
        self._active_tab = tab
        tabs = [
            ('temp',   self.btn_tab_temp),
            ('pres',   self.btn_tab_pres),
            ('vel',    self.btn_tab_vel),
            ('layout', self.btn_tab_layout),
            ('pareto', self.btn_tab_pareto),
        ]
        for key, btn in tabs:
            card = self._canvas_cards.get(key)
            if key == tab:
                # Show if: has compute results, or this canvas was drawn individually
                drawn = getattr(self, '_drawn_tabs', set())
                if card and (getattr(self, '_has_results', False) or key in drawn):
                    card.show()
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
        from optimize_panel import run_optimize
        return run_optimize(self)

    def _reshow_pareto(self):
        from optimize_panel import reshow_pareto
        return reshow_pareto(self)

    def _show_pareto(self, res):
        from optimize_panel import show_pareto
        return show_pareto(self, res)

    def _on_pareto_pick(self, event):
        from optimize_panel import on_pareto_pick
        return on_pareto_pick(self, event)

    def _save_opt_results(self, res, cfg):
        from optimize_panel import save_opt_results
        return save_opt_results(self, res, cfg)

    def _load_pareto_solution(self, x):
        from optimize_panel import load_pareto_solution
        return load_pareto_solution(self, x)

    # ─────────────────────────────────────────────────────────
    #  Layout helpers
    # ─────────────────────────────────────────────────────────
    def _section(self, parent_lay, title, title_style, frame_style):
        from ui_builders import section
        return section(self, parent_lay, title, title_style, frame_style)

    def _row(self, g, row, text, default) -> QLineEdit:
        from ui_builders import row as _row_impl
        return _row_impl(self, g, row, text, default)

    def _res_row(self, g, row, text, col=0) -> QLabel:
        from ui_builders import res_row
        return res_row(self, g, row, text, col)

    def _add_row(self, g, row, text, widget):
        from ui_builders import add_row
        return add_row(self, g, row, text, widget)

    # ─────────────────────────────────────────────────────────
    #  Zone configuration helpers
    # ─────────────────────────────────────────────────────────
    def _zone_mode_changed(self, idx):
        from zone_editor import zone_mode_changed
        return zone_mode_changed(self, idx)

    def _zone_is_grid(self):
        from zone_editor import zone_is_grid
        return zone_is_grid(self)

    def _zone_init_1d(self, n):
        from zone_editor import zone_init_1d
        return zone_init_1d(self, n)

    def _zone_add_row(self):
        from zone_editor import zone_add_row
        return zone_add_row(self)

    def _zone_remove_row(self):
        from zone_editor import zone_remove_row
        return zone_remove_row(self)

    def _zone_add_col(self):
        from zone_editor import zone_add_col
        return zone_add_col(self)

    def _zone_remove_col(self):
        from zone_editor import zone_remove_col
        return zone_remove_col(self)

    def _zone_rebuild_grid(self, ny=None):
        from zone_editor import zone_rebuild_grid
        return zone_rebuild_grid(self, ny)

    def _zone_resize(self):
        from zone_editor import zone_resize
        return zone_resize(self)

    def _zone_axis(self):
        from zone_editor import zone_axis
        return zone_axis(self)

    def _build_zone_config(self):
        from zone_editor import build_zone_config
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

        # Auto-update suggested grid from D_h (alpha=0.4 → ~5% Q accuracy)
        try:
            L_dom = float(self.le_L.text())
            H_dom = float(self.le_H.text())
            Nx_sug, Ny_sug = adaptive_grid(L_dom, H_dom, r['D_h'], alpha=0.4)
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

        self.statusBar().showMessage(f"Fluid {fluid} filled.  Re={Re:.0f}{re_tag}  Nu={r['Nu']:.2f}  f={r['f']:.4f}", 5000)
        if fluid == 'A':
            self._mu_A, self._h_vA, self._K_ffA, self._rho_A = r['mu'], h_v_vol, r['K_ff'], r['rho']
            self._v_rhoA.setText(f"{r['rho']:.4f}")
            self._v_ReA.setText(f"{Re:.1f}{re_tag}")
            self._v_ReA.setStyleSheet(re_style)
            self._v_NuA.setText(f"{r['Nu']:.4f}")
            self._v_fA.setText(f"{r['f']:.4f}")
            self._v_dPLA.setText(f"{r['dP_per_L']:.1f}")
        else:
            self._mu_B, self._h_vB, self._K_ffB, self._rho_B = r['mu'], h_v_vol, r['K_ff'], r['rho']
            self._v_rhoB.setText(f"{r['rho']:.4f}")
            self._v_ReB.setText(f"{Re:.1f}{re_tag}")
            self._v_ReB.setStyleSheet(re_style)
            self._v_NuB.setText(f"{r['Nu']:.4f}")
            self._v_fB.setText(f"{r['f']:.4f}")
            self._v_dPLB.setText(f"{r['dP_per_L']:.1f}")

    def auto_fill_fluid_a(self): self._auto_fill_fluid('A')
    def auto_fill_fluid_b(self): self._auto_fill_fluid('B')

    # ─────────────────────────────────────────────────────────
    #  Save / Load configuration
    # ─────────────────────────────────────────────────────────
    def save_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Config", "thermonas_config.json",
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
    _DIR_MAP = {0: '+x', 1: '-x', 2: '+y', 3: '-y'}

    def _dir_int(self, combo):
        return combo.currentIndex()           # 0=+x, 1=-x, 2=+y, 3=-y

    def _is_x_dir(self, d): return d <= 1
    def _is_y_dir(self, d): return d >= 2

    def _inlet_wall(self, d):
        return {0: 'left', 1: 'right', 2: 'bottom', 3: 'top'}[d]
    def _outlet_wall(self, d):
        return {0: 'right', 1: 'left', 2: 'top', 3: 'bottom'}[d]

    def _on_dir_changed(self):
        """Called when a flow-direction combo changes."""
        pass

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
        """Read config for fluid A or B. Returns dict."""
        if which == 'A':
            d = self._dir_int(self.combo_dirA)
            return dict(dir=d,
                in_ctr=float(self.le_pipeA_in_ctr.text()),
                in_w=float(self.le_pipeA_in_w.text()),
                out_ctr=float(self.le_pipeA_out_ctr.text()),
                out_w=float(self.le_pipeA_out_w.text()))
        else:
            d = self._dir_int(self.combo_dirB)
            return dict(dir=d,
                in_ctr=float(self.le_pipeB_in_ctr.text()),
                in_w=float(self.le_pipeB_in_w.text()),
                out_ctr=float(self.le_pipeB_out_ctr.text()),
                out_w=float(self.le_pipeB_out_w.text()))

    def _update_edge_combos(self):
        """Populate edge combo boxes with readable edge descriptions."""
        import unstructured_mesh as um
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
        from layout_drawer import draw_layout
        return draw_layout(self)

    def _draw_layout_rect(self, ax, L, H, Lmm, Hmm):
        from layout_drawer import draw_layout_rect
        return draw_layout_rect(self, ax, L, H, Lmm, Hmm)

    def _draw_layout_polygon(self, ax, L, H, Lmm, Hmm):
        from layout_drawer import draw_layout_polygon
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
                self._switch_tab('temp')
                self.statusBar().showMessage("Done.", 5000)
        timer.timeout.connect(_check)
        timer.start(200)

    def _run_calculation_inner(self):
        """Thin wrapper — delegates to run_calculation module (Task B.9)."""
        from run_calculation import run_calculation_inner
        return run_calculation_inner(self)

    def _finalize_plots(self):
        """Thin wrapper — delegates to run_calculation module (Task B.9)."""
        from run_calculation import finalize_plots
        return finalize_plots(self)

    # ─────────────────────────────────────────────────────────
    #  Polygon domain solver
    # ─────────────────────────────────────────────────────────
    def _run_polygon_calculation(self):
        from polygon_calc import run_polygon_calculation
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
        default = f"ThermoNAS_{key}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Figure", default,
            "PNG (*.png);;SVG (*.svg);;PDF (*.pdf);;All Files (*)")
        if path:
            canvas.fig.savefig(path, dpi=300, bbox_inches='tight',
                               facecolor=canvas.fig.get_facecolor())
            self.statusBar().showMessage(f"Exported: {path}", 5000)


# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    window = Main_Menu()
    window.show()
    sys.exit(app.exec())
