import sys
import json
from pathlib import Path as _PathBoot

# Make both import styles work regardless of launch mode:
#   python main.py                    -> from solvers..., from runs...
#   python -m sjtu_tpmshx.main        -> from sjtu_tpmshx...
_BOOT_PATH = _PathBoot(__file__).resolve().parent
_BOOT_DIR = str(_BOOT_PATH)
_PROJECT_PARENT = str(_BOOT_PATH.parent)
for _p in (_BOOT_DIR, _PROJECT_PARENT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np
import matplotlib
matplotlib.use("QtAgg")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
    QMessageBox, QLabel, QLineEdit, QPushButton,
    QScrollArea, QWidget, QFileDialog,
    QInputDialog,
)

from solvers.tpms_calc import compute as tpms_compute, geometry as tpms_geometry, adaptive_grid
from ui.matplotlib_canvas import _label_axes
from ui.theme import (
    _THEMES, _build_styles, get_theme, get_theme_name, set_theme,
    apply_mpl_theme, get_density, set_density,
)

__version__ = "1.0.8"


def _git_commit_hash():
    """Return short commit hash (7-char) of the running tree, or '' if git
    metadata is absent. Read from `.git/HEAD` + refs so users on source
    checkouts see a real hash; frozen builds silently fall back to ''.
    """
    import os as _os_gh
    root = _os_gh.path.dirname(_os_gh.path.dirname(_os_gh.path.abspath(__file__)))
    git_dir = _os_gh.path.join(root, '.git')
    if not _os_gh.path.isdir(git_dir):
        return ''
    try:
        with open(_os_gh.path.join(git_dir, 'HEAD'), 'r', encoding='utf-8') as f:
            head = f.read().strip()
        if head.startswith('ref: '):
            ref = head[5:]
            ref_path = _os_gh.path.join(git_dir, *ref.split('/'))
            if _os_gh.path.exists(ref_path):
                with open(ref_path, 'r', encoding='utf-8') as f:
                    return f.read().strip()[:7]
            # Packed refs fallback
            packed = _os_gh.path.join(git_dir, 'packed-refs')
            if _os_gh.path.exists(packed):
                with open(packed, 'r', encoding='utf-8') as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) == 2 and parts[1] == ref:
                            return parts[0][:7]
            return ''
        return head[:7]
    except Exception:
        return ''

_S = _build_styles()
_BG = _S['BG']; _LBL = _S['LBL']; _VAL = _S['VAL']; _VAL_WARN = _S['VAL_WARN']
_INP = _S['INP']; _COMBO = _S['COMBO']
_T_NEUTRAL = _S['T_NEUTRAL']; _T_A = _S['T_A']; _T_B = _S['T_B']
_F_NEUTRAL = _S['F_NEUTRAL']; _F_A = _S['F_A']; _F_B = _S['F_B']
_BTN_BASE = "border-radius:5px; color:white; font-weight:bold; font-size:9pt;"
_BTN_A = _S['BTN_A']; _BTN_B = _S['BTN_B']
_BTN_TPMS = _S['BTN_TPMS']; _BTN_RUN = _S['BTN_RUN']
_BTN_PRIMARY = _S['BTN_PRIMARY']; _BTN_SECONDARY = _S['BTN_SECONDARY']
_BTN_TERTIARY = _S['BTN_TERTIARY']; _BTN_LONG = _S['BTN_LONG']
_TOOLBTN_SPLIT = _S.get('TOOLBTN_SPLIT', '')


def _rebuild_styles(theme_name=None):
    """Rebuild module-level style vars after theme switch.

    Phase 3 refactor (2026-05-06 plan #4): the module-globals refresh is
    now performed by :class:`controllers.theme_manager.ThemeManager` via
    ``bind_to_module``. We still call ``ui.theme.set_theme`` here for
    backward compat (the persistent ``.theme`` marker), then delegate
    the rebuild to the active manager if a window has constructed one;
    otherwise fall back to the legacy inline rebuild so import-time
    ordering in ``__main__`` keeps working.
    """
    global _S
    if theme_name is not None:
        try:
            from ui.theme import set_theme as _st
            _st(theme_name)
        except Exception:
            pass
    # Prefer the live window's ThemeManager if one exists.
    try:
        import sys as _sys_rs
        win = None
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                for w in app.topLevelWidgets():
                    if w.__class__.__name__ == 'Main_Menu':
                        win = w
                        break
        except Exception:
            pass
        if win is not None and getattr(win, 'theme', None) is not None:
            win.theme.rebuild()
            _S = _sys_rs.modules[__name__]._S
            apply_mpl_theme()
            return
    except Exception:
        pass
    # Legacy fallback (only used before any Main_Menu has been built).
    global _BG, _LBL, _VAL, _VAL_WARN, _INP, _COMBO
    global _T_NEUTRAL, _T_A, _T_B, _F_NEUTRAL, _F_A, _F_B
    global _BTN_A, _BTN_B, _BTN_TPMS, _BTN_RUN
    global _BTN_PRIMARY, _BTN_SECONDARY, _BTN_TERTIARY, _BTN_LONG
    global _TOOLBTN_SPLIT
    _S = _build_styles(theme_name)
    _BG = _S['BG']; _LBL = _S['LBL']; _VAL = _S['VAL']; _VAL_WARN = _S['VAL_WARN']
    _INP = _S['INP']; _COMBO = _S['COMBO']
    _T_NEUTRAL = _S['T_NEUTRAL']; _T_A = _S['T_A']; _T_B = _S['T_B']
    _F_NEUTRAL = _S['F_NEUTRAL']; _F_A = _S['F_A']; _F_B = _S['F_B']
    _BTN_A = _S['BTN_A']; _BTN_B = _S['BTN_B']
    _BTN_TPMS = _S['BTN_TPMS']; _BTN_RUN = _S['BTN_RUN']
    _BTN_PRIMARY = _S['BTN_PRIMARY']; _BTN_SECONDARY = _S['BTN_SECONDARY']
    _BTN_TERTIARY = _S['BTN_TERTIARY']; _BTN_LONG = _S['BTN_LONG']
    _TOOLBTN_SPLIT = _S.get('TOOLBTN_SPLIT', '')
    apply_mpl_theme()


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
        # Central widget created directly — the old `Ui_MainWindow` /
        # `mainui.py` scaffolding (auto-generated from Designer and then
        # fully hidden at startup) has been dropped. QMainWindow auto-
        # creates menuBar() + statusBar() on first access, so no extra
        # wiring is needed here.
        self.setCentralWidget(QWidget())
        self.setWindowTitle("SJTU-TPMSHX")
        self.resize(1350, 1100)
        self.setMinimumSize(900, 720)
        # Showing the window is the entry-point's responsibility —
        # `window.showMaximized()` at the bottom of this file. Keeping
        # that concern out of __init__ avoids a double show + the
        # timing race with `_maybe_show_onboarding`.

        # App icon
        import os
        from PySide6.QtGui import QIcon
        _icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sjtulogosilver.png')
        if os.path.exists(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))

        # Stored solver state
        self._eps_A = self._h_vA = None
        self._K_ffA = self._K_ffB = self._K_ss = None
        self._rho_A = self._rho_B = self._h_vB = None
        self._mu_A  = self._mu_B  = None
        self.T_fA   = self.T_fB   = self.T_s = None

        # Widgets to show/hide based on domain shape
        self._rect_only_widgets = []
        self._poly_only_widgets = []

        # Temperature unit state — toggled by the header K/°C button. All
        # compute paths read temperatures via `_temp_to_K(le)` which honours
        # this flag, so internal physics always runs in Kelvin regardless of
        # what the user is typing.
        self._temp_unit = 'K'

        # Compute lifecycle state (P0 re-entrancy guard, 2026-05-05 audit).
        # Explicit init at construction time so `getattr(self, ..., False)`
        # fallbacks elsewhere can't accidentally surface a stale value if a
        # future refactor removes the getattr safety nets.
        self._compute_running = False
        self._compute_poll_timer = None
        self._compute_thread = None
        self._compute_btn_handler = None
        self._cancel_token = None  # set by ComputeOrchestrator on each start

        # Controllers — Phase 1+2+3 of 2026-05-06 main.py refactor (#4).
        # See vault/reports/refactor/2026-05-06-main-py-refactor-plan-CN.md.
        from controllers import (ComputeOrchestrator, ResultCache,
                                  SessionManager, ThemeManager, SignalRouter)

        # Phase 3: ThemeManager owns the style dict; bind it back onto this
        # module so legacy call sites (`import main as _m; m._BG`) keep
        # working unchanged. SignalRouter records connections for bulk
        # disconnect on closeEvent.
        self.theme = ThemeManager(self)
        import sys as _sys_tm
        self.theme.bind_to_module(_sys_tm.modules[__name__])
        self.signals = SignalRouter(self)

        # Phase 1: solver lifecycle (refactor-p1-done).
        self.compute = ComputeOrchestrator(self)
        self.signals.connect(self.compute.started, self._on_orch_started,
                             tag='compute.started', sender=self.compute)
        self.signals.connect(self.compute.progress, self._on_orch_progress,
                             tag='compute.progress', sender=self.compute)
        self.signals.connect(self.compute.finished, self._on_orch_finished,
                             tag='compute.finished', sender=self.compute)
        self.signals.connect(self.compute.error, self._on_orch_error,
                             tag='compute.error', sender=self.compute)
        self.signals.connect(self.compute.cancelled, self._on_orch_cancelled,
                             tag='compute.cancelled', sender=self.compute)

        # Phase 2: result + session aggregation. SessionManager now owns
        # all .last_session_*.json / .user_presets.json / .workspace IO.
        # ResultCache is instantiated for new code; legacy result attrs
        # (_compute_results / _recent_runs / _has_results_*) stay in place
        # and will migrate incrementally in later phases to avoid touching
        # runs/run_calculation*.py call sites in this commit.
        self.sm = SessionManager(parent=self)
        self.cache = ResultCache(self)

        # Active workspace loaded from disk via SessionManager (replaces
        # the legacy inline .workspace marker read). Defaults to 'A' if
        # the marker file is missing or contains garbage.
        self._active_workspace = self.sm.get_active_workspace()

        self._build_ui()
        self._apply_accessibility()
        # Tooltips must be attached BEFORE the validators so the validator
        # captures the help HTML as its baseline tooltip (saved and later
        # restored when the field returns to a valid value).
        self._install_field_help()
        self._attach_input_validators()
        self._install_status_log()
        self._rebuild_preset_combo()
        self._install_undo_stack()
        # First-run guidance. Deferred 1.2 s after showMaximized so the window
        # is already on screen when the overlay appears.
        from PySide6.QtCore import QTimer as _QT
        _QT.singleShot(1200, self._maybe_show_onboarding)
        if get_theme_name() == 'dark':
            from ui.glass_panel import generate_blurred_bg
            from PySide6.QtGui import QPalette, QBrush
            _bg_pix = generate_blurred_bg(1920, 1080)
            pal = self.palette()
            pal.setBrush(QPalette.ColorRole.Window, QBrush(_bg_pix))
            self.setPalette(pal)
            self.setAutoFillBackground(True)
        self._apply_shanghai_defaults()
        # Restore the last-used field state on top of the Shanghai baseline
        # so returning users see exactly what they had, while the Reset
        # button still snaps back to the canonical preset.
        self._restore_session()
        # Track manual grid edits so `compute_tpms` (invoked by Auto-fill)
        # does NOT overwrite user-customised Nx/Ny/Nz. textEdited fires on
        # keyboard input only, not on programmatic `setText`. NB: do NOT
        # reset _user_edited_grid here — `_apply_shanghai_defaults` and
        # `_restore_session` both raise it to True so preset/saved Nx/Ny/Nz
        # survive the next compute_tpms call. Resetting it here would let
        # auto-suggest stomp the user-visible defaults.
        for le in (self.le_Nx, self.le_Ny, self.le_Nz):
            le.textEdited.connect(self._mark_grid_edited)
        self._setup_shortcuts()
        # PyVista/VTK context creation costs 1-2 s and was running 500 ms
        # after startup. Keep it lazy unless explicitly opted in for demos.
        import os as _os_perf
        if _os_perf.environ.get('TPMSHX_PREINIT_3D', '0') == '1':
            self._schedule_3d_preinit()
        self._schedule_tpms_geometry_prewarm()
        self._install_inline_unit_parser()
        self._wire_fluid_defaults()
        self._install_status_bar_widgets()
        from ui.command_palette import install_command_palette
        install_command_palette(self)
        from ui.coord_inspector import install_coord_inspector
        install_coord_inspector(self)
        from ui.param_search import install_param_search
        install_param_search(self)
        from ui.zone_editor import ZoneHandleManager
        self._zone_handle_mgr = ZoneHandleManager(self)
        self._zone_handle_mgr.wire()
        from ui.field_menu import install_field_menus
        install_field_menus(self)
        from ui.expr_eval import install_expression_eval
        install_expression_eval(self)
        from ui.quick_sliders import install_quick_sliders
        install_quick_sliders(self)
        from ui.canvas_tools import install_canvas_tools
        install_canvas_tools(self)
        from ui.bookmarks import install_bookmarks
        install_bookmarks(self)
        from ui.repl_dock import install_repl_dock
        install_repl_dock(self)
        # Accept file drops on the whole window — users can drag a saved
        # `.json` preset onto the app to load it without going through the
        # preset combo. Only .json with the expected preset/session shape
        # is honoured; anything else is rejected with a status message.
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() and any(
                u.toLocalFile().lower().endswith('.json')
                for u in mime.urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return
        paths = [u.toLocalFile() for u in mime.urls()
                 if u.toLocalFile().lower().endswith('.json')]
        if not paths:
            event.ignore()
            return
        import json as _j_dnd
        loaded = 0
        for p in paths[:1]:  # only the first dropped file is applied
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = _j_dnd.load(f)
                if isinstance(data, dict) and 'line_edits' in data:
                    self._apply_user_preset(data)
                    loaded += 1
                elif isinstance(data, dict) and 'presets' in data:
                    # Full user-preset file — pick the first entry.
                    presets = list(data.get('presets') or [])
                    if presets:
                        self._apply_user_preset(presets[0])
                        loaded += 1
            except Exception as e:
                QMessageBox.warning(
                    self, "Preset Load Failed",
                    f"Could not load {p}:\n{e}")
                event.ignore()
                return
        if loaded:
            self.statusBar().showMessage(
                f"Loaded preset from {paths[0]}.", 5000)
            event.acceptProposedAction()
        else:
            self.statusBar().showMessage(
                "Dropped file did not contain a recognizable preset.", 5000)
            event.ignore()

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
        # Immersive 3D: F key when 3D tab active expands the 3D card and
        # collapses the left parameter panel so the volume fills the screen.
        # Second press restores the previous layout. Scoped to 3D tab so the
        # F key doesn't collide with other focused widgets.
        QShortcut(QKeySequence("F"), self).activated.connect(
            self._toggle_3d_immersive)
        QShortcut(QKeySequence("Ctrl+?"), self).activated.connect(
            self._show_shortcuts)
        QShortcut(QKeySequence("Ctrl+/"), self).activated.connect(
            self._show_shortcuts)
        # D12 — quick fluid preset: digit keys route to Fluid A combo.
        for digit, fluid in ((1, 'Air'), (2, 'Water'), (3, 'sCO₂')):
            QShortcut(QKeySequence(f"Alt+{digit}"), self).activated.connect(
                lambda f=fluid: self._keyboard_set_fluid('A', f))
            QShortcut(QKeySequence(f"Alt+Shift+{digit}"), self).activated.connect(
                lambda f=fluid: self._keyboard_set_fluid('B', f))
        # D13 — density cycle
        QShortcut(QKeySequence("["), self).activated.connect(
            lambda: self._cycle_density(-1))
        QShortcut(QKeySequence("]"), self).activated.connect(
            lambda: self._cycle_density(+1))
        # D14 — Alt+↑/↓ scrub through recent runs
        QShortcut(QKeySequence("Alt+Up"), self).activated.connect(
            lambda: self._scrub_recent(-1))
        QShortcut(QKeySequence("Alt+Down"), self).activated.connect(
            lambda: self._scrub_recent(+1))
        # D7 — Ctrl+D opens the overview dashboard dialog.
        QShortcut(QKeySequence("Ctrl+D"), self).activated.connect(
            self._show_overview)
        # Launch NSGA-II search without leaving the keyboard.
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(
            self._run_optimize)
        QShortcut(QKeySequence("Ctrl+Enter"), self).activated.connect(
            self._run_optimize)
        # E18 — Ctrl+↑/↓ cycle through enabled tabs
        QShortcut(QKeySequence("Ctrl+Up"), self).activated.connect(
            lambda: self._cycle_tab(-1))
        QShortcut(QKeySequence("Ctrl+Down"), self).activated.connect(
            lambda: self._cycle_tab(+1))

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
        self._active_preset_name = "Shanghai (3D Gyroid)"
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
            'le_L':     '0.182',  # L domain [m]
            'le_H':     '0.042',
            'le_Lz':    '0.042',
            'le_Lcell': '7.0',
            'le_t':     '0.6',
            'le_ks':    '16.0',   # Shanghai SS solid k_s
            'le_uA':    '20.0',   # Fluid A (air) interstitial, back-calc Re=5000
            'le_TinA':  '422.0',  # Fluid A inlet (Excel col 28: 148.908 °C)
            'le_PinA':  '192362', # Fluid A inlet absolute (Excel 91037 Pa gauge + atm)
            'le_uB':    '0.133',  # Fluid B (water) — Shanghai case 8 Re_water=400
            'le_TinB':  '300.0',  # Fluid B inlet (Excel col 24: 26.89 °C)
            'le_PinB':  '101973', # Fluid B inlet absolute (Excel 647.6 Pa gauge + atm)
            # 3D grid: wall-refine expands +16 per axis, so 30/20/5 →
            # refined 46×36×21 = ~35k cells, compressible dual-fluid
            # solve ~2–3 min. Keeping the 2D default 100/50 here would
            # push refined 3D to ~160k cells and 10+ min.
            'le_Nx':    '20',
            'le_Ny':    '20',
            'le_Nz':    '20',
            # Shanghai pipe inlet/outlet: A full-width (42 mm strip), B
            # staggered cross-flow (water enters top-right +x end, exits
            # bottom-left -x end; inlet/outlet 42 mm strips along real x).
            # A flows +x: full H=42mm face inlet/outlet.
            # B flows -y: staggered cross-flow, inlet at x=133mm (w=42mm),
            # outlet at x=7mm (w=42mm).
            'le_pipeA_in_ctr':  '0.021', 'le_pipeA_in_w':  '0.042',
            'le_pipeA_out_ctr': '0.021', 'le_pipeA_out_w': '0.042',
            'le_pipeB_in_ctr':  '0.154', 'le_pipeB_in_w':  '0.042',
            'le_pipeB_out_ctr': '0.028', 'le_pipeB_out_w': '0.042',
        }
        # Temperature fields are authored in Kelvin. If the UI is currently
        # showing °C, convert on write so the displayed digits match the
        # user's current unit (avoids the silent 273.15 bug where a preset
        # dumps "422" into a °C field and compute then reads 695 K).
        temp_fields = {'le_TinA', 'le_TinB'}
        unit = getattr(self, '_temp_unit', 'K')
        for attr, val in presets.items():
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                if attr in temp_fields and val != '':
                    # Unified temp setter — handles K/°C dispatch in one
                    # place so preset load can never disagree with session
                    # restore on the 273.15 sign (latent bug fixed
                    # 2026-05-05 audit).
                    self._set_temp_K(w, val)
                else:
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
        # Treat preset Nx/Ny/Nz as authoritative — without this flag the next
        # `compute_tpms` call would auto-overwrite the preset values with
        # D_h-derived suggestions (e.g. 20/20/20 → 14/25/25).
        self._user_edited_grid = True
        self.statusBar().showMessage(
            "Loaded Shanghai Electric preset (3D, Gyroid L=7 t=0.6, 182×42×42 mm).",
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

    def _schedule_tpms_geometry_prewarm(self):
        """Warm the current TPMS geometry cache off the UI thread.

        Auto-fill calls compute_tpms(), whose first exact geometry evaluation
        builds a 256^3 voxel grid. Doing that in the background keeps the
        first Auto-fill click from paying the full cold-cache cost.
        """
        from PySide6.QtCore import QTimer

        def _start():
            try:
                args = (
                    self.combo_tpms.currentText(),
                    float(self.le_Lcell.text()),
                    float(self.le_t.text()),
                    float(self.le_ks.text()),
                )
            except Exception:
                return

            def _worker():
                try:
                    tpms_geometry(*args)
                except Exception:
                    pass

            import threading
            threading.Thread(
                target=_worker, name="tpms-geometry-prewarm",
                daemon=True).start()

        QTimer.singleShot(900, _start)

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
            # D-plan: Optimize tab is the entry point for NSGA-II — must be
            # reachable before any compute so the user can click Launch.
            # The Pareto plot stays empty until a run completes; the
            # launch/status/progress header is always shown.
            'pareto': True,
        }
        btn_map = {
            'layout': self.btn_tab_layout,
            'temp':   self.btn_tab_temp,
            'pres':   self.btn_tab_pres,
            'vel':    self.btn_tab_vel,
            '3d':     self.btn_tab_3d,
            'pareto': self.btn_tab_pareto,
        }
        for key, enabled in rules.items():
            btn = btn_map[key]
            btn.setEnabled(enabled)
            if not enabled and key != 'layout':
                btn.setStyleSheet(self._PTAB_DISABLED)
            card = self._canvas_cards.get(key)
            if card is not None and not enabled:
                card.hide()
        # Fall back to Layout if active tab just became disabled
        if not rules.get(getattr(self, '_active_tab', 'layout'), True):
            self._switch_tab('layout')

    def _split_with_current(self, tab):
        """Enter split-view pairing the currently active tab with `tab`.
        No-op if the shifted tab is the one already active (user would
        end up pairing X with X, which is just a single view). The split
        view persists until any normal (non-shifted) tab click."""
        cur = getattr(self, '_active_tab', None)
        if cur is None or cur == tab:
            return
        # Both tabs must be enabled (e.g., can't split into temp before
        # Compute has populated it).
        def _en(k):
            btn = {
                'temp': self.btn_tab_temp, 'pres': self.btn_tab_pres,
                'vel': self.btn_tab_vel, 'layout': self.btn_tab_layout,
                'pareto': self.btn_tab_pareto, '3d': self.btn_tab_3d,
            }.get(k)
            return btn is not None and btn.isEnabled()
        if not (_en(cur) and _en(tab)):
            self.statusBar().showMessage(
                "Split view requires both tabs to have data.", 4000)
            return
        from ui.ui_builders import _layout_split_cards
        _layout_split_cards(self, [cur, tab])
        # Paint both tab buttons as active, others inactive.
        for k, btn in (('temp', self.btn_tab_temp),
                        ('pres', self.btn_tab_pres),
                        ('vel',  self.btn_tab_vel),
                        ('layout', self.btn_tab_layout),
                        ('pareto', self.btn_tab_pareto),
                        ('3d',   self.btn_tab_3d)):
            if k in (cur, tab):
                btn.setStyleSheet(self._PTAB_ON)
            elif btn.isEnabled():
                btn.setStyleSheet(self._PTAB_OFF)
        self._active_tab = cur  # keep primary tab as "active"
        self.statusBar().showMessage(
            f"Split view: {cur} ↔ {tab}. Click any tab to return "
            "to single view.", 5000)

    def _switch_tab(self, tab: str):
        # Exiting split view — a plain tab click means "back to single".
        if getattr(self, '_split_tabs', None):
            self._split_tabs = None
            from ui.ui_builders import _relayout_canvas_cards
            _relayout_canvas_cards(self, 1)
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
        if target_btn is not None and not target_btn.isEnabled() and tab != 'layout':
            tab = 'layout'

        # Tab-switch fast path: no-op only when the active card is visible.
        # Preview can draw layout while the startup-hidden layout card is
        # still marked active, so visibility must be part of the guard.
        if tab == getattr(self, '_active_tab', None) \
                and not getattr(self, '_split_tabs', None):
            card = getattr(self, '_canvas_cards', {}).get(tab)
            if card is not None and card.isVisible():
                return

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
        showed_any = False
        # Batch show/hide under a single repaint: setUpdatesEnabled(False) on
        # the scroll viewport suppresses N intermediate layout invalidations
        # (one per card toggle). With 6 cards this alone cuts tab-switch lag
        # from ~120 ms → <20 ms on refined 3D grids.
        _scroll = getattr(self, '_canvas_scroll', None)
        _viewport = _scroll.viewport() if _scroll is not None else None
        if _viewport is not None:
            _viewport.setUpdatesEnabled(False)
        for key, btn in tabs:
            card = self._canvas_cards.get(key)
            if key == tab:
                # D-plan: the Optimize tab always shows its card so the
                # Launch button + status header are reachable before the
                # first compute.  Other tabs still require results.
                if card and (key == 'pareto'
                             or getattr(self, '_has_results', False)
                             or key in drawn):
                    card.show()
                    showed_any = True
                elif key == '3d':
                    # No 3D compute yet — hide card. _empty_state_label below
                    # at line ~762 already covers the "Configure + Compute"
                    # hint centrally; previously we also showed a status-bar
                    # message here, which duplicated the central placeholder
                    # for ~6s. Removed 2026-04-29 to de-duplicate.
                    if card:
                        card.hide()
                btn.setStyleSheet(self._PTAB_ON)
            else:
                if card: card.hide()
                if btn.isEnabled():
                    btn.setStyleSheet(self._PTAB_OFF)
                else:
                    btn.setStyleSheet(self._PTAB_DISABLED)
        # Toggle empty-state placeholder visibility based on whether any real
        # card is on screen. Kept in sync here so draw-layout, Compute, or
        # Pareto flows all hide the hint once their card lands.
        if hasattr(self, '_empty_state_label'):
            self._empty_state_label.setVisible(not showed_any)
        self._hover_label.setText("")
        if _viewport is not None:
            _viewport.setUpdatesEnabled(True)

    def _on_hover(self, event):
        """Show data value at mouse position on contour plots."""
        # Feed the dockable coord inspector first — it reads the full
        # compute-results stack, not just the single canvas field.
        inspector = getattr(self, '_coord_inspector', None)
        if inspector is not None and inspector.isVisible():
            try:
                inspector.update_from_event(event)
            except Exception:
                pass

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

    def _cancel_optimize(self):
        from ui.optimize_panel import cancel_optimize
        return cancel_optimize(self)

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
                # Cap to keep refined total cells under ~50k for fast UX
                # (user_cells + 16 per axis tensor-product when wall_refine ON).
                # Previous cap 150k led to 116k cells = 12 min compute on
                # Shanghai-scale domains. 50k → ~3-5 min wall_refine, ~30s flat.
                while ((Nx_sug + 16) * (Ny_sug + 16) * (Nz_sug + 16)
                       > 50_000 and Nx_sug > 14):
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
            T_K = self._temp_to_K(le_Tin)
            r = tpms_compute(
                self.combo_tpms.currentText(),
                float(self.le_Lcell.text()), float(self.le_t.text()),
                float(le_u.text()), T_K,
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
            # Solid
            "rho_s":     self.le_rho_s.text(),
            # Solver
            "Nx":        self.le_Nx.text(),
            "Ny":        self.le_Ny.text(),
            # TPMS
            "tpms_type": self.combo_tpms.currentText(),
            "L_cell":    self.le_Lcell.text(),
            "t":         self.le_t.text(),
            "k_s":       self.le_ks.text(),
            # Solid initial temperature (optional; empty = legacy seed)
            "T_s_init":  self.le_TsInit.text() if hasattr(self, 'le_TsInit') else "",
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
        _set(self.le_rho_s,    "rho_s")
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
        if hasattr(self, 'le_TsInit'):
            _set(self.le_TsInit, "T_s_init")
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
    # ─────────────────────────────────────────────────────────
    #  Input validation (red border on blur when value is bad)
    # ─────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────
    #  Temperature unit handling
    # ─────────────────────────────────────────────────────────
    def _temp_to_K(self, le):
        """Return the float value of a temperature QLineEdit in Kelvin,
        honouring the current `_temp_unit` flag. Callers anywhere in the
        compute path should go through this rather than `float(le.text())`
        so the K/°C toggle stays sound.
        """
        v = float(le.text())
        if getattr(self, '_temp_unit', 'K') == 'C':
            v += 273.15
        return v

    def _set_temp_K(self, le, kelvin_value, fmt='{:.2f}'):
        """Write a Kelvin temperature into a QLineEdit, converting to the
        currently displayed unit. Single source of truth — replaces ad-hoc
        `setText(f"{val - 273.15:.2f}")` snippets in preset-load and
        session-restore that previously had drift potential (one would
        subtract, another would add, depending on _temp_unit timing).
        """
        if le is None or kelvin_value is None or kelvin_value == '':
            return
        try:
            v = float(kelvin_value)
        except (TypeError, ValueError):
            return
        if getattr(self, '_temp_unit', 'K') == 'C':
            v -= 273.15
        try:
            le.setText(fmt.format(v))
        except Exception:
            pass

    def _sync_temp_unit_labels(self):
        """Refresh the `[K]`/`[°C]` suffix on the three temperature row
        labels (T_inA, T_inB) + the header button caption to
        match `self._temp_unit`. Call whenever the unit changes, whether via
        the toggle button, preset load, or session restore — prevents the
        value-vs-label mismatch the user reported."""
        unit_display = "°C" if getattr(self, '_temp_unit', 'K') == 'C' else "K"
        # Swap the trailing " [K]"/" [°C]" on each label. The label text uses
        # QLabel rich-text HTML so we replace both variants.
        for attr in ('_lbl_TinA_unit', '_lbl_TinB_unit', '_lbl_TsInit_unit'):
            lbl = getattr(self, attr, None)
            if lbl is None:
                continue
            try:
                txt = lbl.text()
                txt = (txt.replace("[K]", f"[{unit_display}]")
                          .replace("[°C]", f"[{unit_display}]"))
                lbl.setText(txt)
            except Exception:
                pass
        if hasattr(self, 'btn_temp_unit'):
            self.btn_temp_unit.setText(unit_display)
            self.btn_temp_unit.setToolTip(
                f"Temperatures currently in {unit_display}. Click to switch.")

    def _toggle_temp_unit(self):
        """Flip between Kelvin and Celsius display for the three main
        temperature fields. Converts the displayed text AND rewrites the
        label suffixes (`[K]` ↔ `[°C]`) so the UI is self-consistent.
        """
        cur = getattr(self, '_temp_unit', 'K')
        fields = [
            getattr(self, 'le_TinA', None),
            getattr(self, 'le_TinB', None),
            getattr(self, 'le_TsInit', None),
        ]
        def _fmt(v):
            return f"{v:.2f}"
        if cur == 'K':
            # K → °C
            for le in fields:
                if le is None:
                    continue
                try:
                    v = float(le.text())
                    le.setText(_fmt(v - 273.15))
                except Exception:
                    pass
            self._temp_unit = 'C'
        else:
            # °C → K
            for le in fields:
                if le is None:
                    continue
                try:
                    v = float(le.text())
                    le.setText(_fmt(v + 273.15))
                except Exception:
                    pass
            self._temp_unit = 'K'
        self._sync_temp_unit_labels()
        self.statusBar().showMessage(
            f"Temperature display switched to {self._temp_unit}.", 3000)

    # Auto-defaults applied when the user swaps the fluid type for a given
    # side. Values are conservative "typical operating point" numbers; the
    # user can still edit afterwards. Temperature stored in K; the parser
    # converts to °C if the header toggle is currently °C.
    _FLUID_DEFAULTS = {
        'Air':   {'u': 20.0,  'T': 422.0, 'P': 101325.0},
        'Water': {'u': 0.15,  'T': 300.0, 'P': 101325.0},
        'sCO₂':  {'u': 2.0,   'T': 350.0, 'P': 8000000.0},
    }

    def _apply_fluid_defaults(self, side):
        """Push typical u / T / P defaults into the given side's inputs when
        the fluid-type combo changes. `side` is 'A' or 'B'."""
        if side not in ('A', 'B'):
            return
        combo = getattr(self, f'combo_fluid{side}', None)
        if combo is None:
            return
        name = combo.currentText().strip()
        defaults = self._FLUID_DEFAULTS.get(name)
        if defaults is None:
            return
        # Honour the current temperature display unit.
        T_val = defaults['T']
        if getattr(self, '_temp_unit', 'K') == 'C':
            T_val = T_val - 273.15
        targets = (
            (f'le_u{side}',  f"{defaults['u']:.3g}"),
            (f'le_Tin{side}', f"{T_val:.2f}"),
            (f'le_Pin{side}', f"{defaults['P']:.0f}"),
        )
        for attr, txt in targets:
            le = getattr(self, attr, None)
            if le is None:
                continue
            try:
                le.setText(txt)
            except Exception:
                continue
        self.statusBar().showMessage(
            f"Fluid {side} → {name}: applied u={defaults['u']:.3g} m/s · "
            f"T={defaults['T']:.1f} K · P={defaults['P']:.0f} Pa.", 5000)

    def _wire_fluid_defaults(self):
        for side in ('A', 'B'):
            combo = getattr(self, f'combo_fluid{side}', None)
            if combo is None:
                continue
            combo.currentIndexChanged.connect(
                lambda _i, s=side: self._apply_fluid_defaults(s))

    # Detached 3D panel — right-click the "3D View" tab offers "Open in
    # new window". The panel widget is reparented to a borderless QDialog
    # so users on multi-monitor setups can drag it to a second screen.
    # Closing the detached window reattaches to the card.
    _3d_detached_window = None

    def _detach_3d_window(self):
        """Reparent canvas_3d into a standalone QDialog and show it."""
        panel = getattr(self, 'canvas_3d', None)
        if panel is None:
            QMessageBox.information(
                self, "3D panel", "3D panel is not initialised yet. "
                "Click the 3D tab first.")
            return
        if getattr(self, '_3d_detached_window', None) is not None:
            self._3d_detached_window.raise_()
            self._3d_detached_window.activateWindow()
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("SJTU-TPMSHX — 3D View (detached)")
        dlg.resize(1200, 800)
        dlg.setModal(False)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(4, 4, 4, 4); lay.setSpacing(0)
        # Remember previous parent & layout position so re-docking restores
        # the widget to exactly where it came from.
        self._3d_prev_parent = panel.parentWidget()
        self._3d_prev_parent_layout = None
        card = self._canvas_cards.get('3d') if hasattr(self, '_canvas_cards') else None
        if card is not None:
            self._3d_prev_parent_layout = card.layout()
        panel.setParent(None)
        lay.addWidget(panel)
        self._3d_detached_window = dlg

        # Wire reattach on close instead of destroying the window, so the
        # OpenGL context lives inside a Qt object continuously.
        def _on_close(ev):
            self._reattach_3d_window()
            ev.accept()
        dlg.closeEvent = _on_close
        dlg.show()
        self.statusBar().showMessage(
            "3D view detached — close the window to re-dock.", 5000)

    def _reattach_3d_window(self):
        """Put canvas_3d back into its original card and close the dialog."""
        dlg = getattr(self, '_3d_detached_window', None)
        panel = getattr(self, 'canvas_3d', None)
        if dlg is None or panel is None:
            return
        # Move the widget back into its old layout before destroying dialog.
        prev_layout = getattr(self, '_3d_prev_parent_layout', None)
        if prev_layout is not None:
            panel.setParent(None)
            prev_layout.addWidget(panel)
        self._3d_detached_window = None
        # Avoid recursion: clear the overridden closeEvent before invoking it.
        try:
            dlg.close()
        except Exception:
            pass
        self.statusBar().showMessage("3D view re-docked.", 3000)

    # ─── D17 — generic any-canvas detach ─────────────────────────────
    _detached_canvases = {}

    def _canvas_for_key(self, key):
        mapping = {
            'temp':   getattr(self, 'canvas_temp', None),
            'pres':   getattr(self, 'canvas_pres', None),
            'vel':    getattr(self, 'canvas_vel', None),
            'layout': getattr(self, 'canvas_layout', None),
            'pareto': getattr(self, 'canvas_pareto', None),
        }
        return mapping.get(key)

    def _detach_canvas(self, key):
        """Reparent any 2D matplotlib canvas into a floating QDialog.
        3D uses the dedicated path (`_detach_3d_window`) because
        PyVistaQt's OpenGL context needs more careful handling."""
        if key == '3d':
            self._detach_3d_window()
            return
        canvas = self._canvas_for_key(key)
        if canvas is None:
            return
        if self._detached_canvases.get(key) is not None:
            self._detached_canvases[key].raise_()
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle(f"SJTU-TPMSHX — {key} (detached)")
        dlg.resize(1200, 800)
        dlg.setModal(False)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(4, 4, 4, 4); lay.setSpacing(0)
        card = self._canvas_cards.get(key)
        prev_layout = card.layout() if card is not None else None
        canvas._prev_layout = prev_layout
        canvas.setParent(None)
        lay.addWidget(canvas)
        self._detached_canvases[key] = dlg

        def _on_close(ev, _k=key):
            self._reattach_canvas(_k)
            ev.accept()
        dlg.closeEvent = _on_close
        dlg.show()
        self.statusBar().showMessage(
            f"{key} canvas detached — close the window to re-dock.", 5000)

    def _reattach_canvas(self, key):
        if key == '3d':
            self._reattach_3d_window()
            return
        dlg = self._detached_canvases.pop(key, None)
        canvas = self._canvas_for_key(key)
        if dlg is None or canvas is None:
            return
        prev_layout = getattr(canvas, '_prev_layout', None)
        if prev_layout is not None:
            canvas.setParent(None)
            prev_layout.addWidget(canvas)
        try:
            dlg.close()
        except Exception:
            pass
        self.statusBar().showMessage(f"{key} canvas re-docked.", 3000)

    # ─────────────────────────────────────────────────────────
    #  Status bar — persistent context strip (IDE-style)
    # ─────────────────────────────────────────────────────────
    def _install_status_bar_widgets(self):
        """Mount permanent status-bar widgets on the right edge of the
        QMainWindow status bar: [Preset] | [Workspace] | [Re_A / Re_B] |
        [last compute clock]. These are **permanent widgets** — they
        survive transient showMessage() calls, giving the user a constant
        context strip like VSCode / JetBrains IDEs.
        """
        from ui.theme import get_theme as _gt_sb
        _t = _gt_sb()
        _mono_css = (
            f"color:{_t.get('sub_fg', _t['fg'])};"
            f"font-family:'Fira Code','Consolas',monospace;"
            f"font-size:9pt; font-weight:500;"
            f"background:transparent; border:none; padding:0 6px;")

        def _mk(initial=""):
            l = QLabel(initial)
            l.setStyleSheet(_mono_css)
            return l

        sb = self.statusBar()
        sb.setStyleSheet(
            f"QStatusBar{{background:{_t.get('surface_raised', _t['card_bg'])};"
            f"border-top:1px solid {_t['card_border']};}}"
            f"QStatusBar QLabel{{color:{_t['fg']};}}"
            "QStatusBar::item{border:none;}")
        self._sb_preset = _mk("Preset: —")
        self._sb_ws = _mk(f"WS: {getattr(self, '_active_workspace', 'A')}")
        self._sb_re = _mk("Re: —")
        self._sb_clock = _mk("⏱ —")

        # Visual separator pill between groups. Three identical widgets
        # (not one reused) because Qt requires each addPermanentWidget
        # call to get a distinct widget pointer.
        def _sep():
            s = QLabel("│")
            s.setStyleSheet(
                f"color:{_t.get('sub_fg', '#888')}; background:transparent;"
                "border:none; padding:0 2px; font-size:10pt;")
            return s

        # Tiny live-residual sparkline — shown while a compute is in
        # flight so users can eyeball convergence without waiting for the
        # pressure-tab residual plot. Fluid A only (keep footprint small);
        # the full A+B semilog plot remains on Pressure tab post-run.
        from ui.sparkline import Sparkline as _LiveSpark
        self._sb_live_resid = _LiveSpark(height=20)
        self._sb_live_resid.setFixedWidth(120)
        self._sb_live_resid.hide()

        # Test-coverage badge — mouse-click opens a summary dialog. Count
        # is sampled from the project's known pytest collection; update
        # here when the suite grows significantly.
        self._sb_tests = _mk("✓ 37 tests")
        self._sb_tests.setStyleSheet(
            _mono_css.replace(
                f"color:{_t.get('sub_fg', _t['fg'])};",
                f"color:{_t.get('accent_green', '#22C55E')};")
            + "font-weight:bold;")
        self._sb_tests.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sb_tests.setToolTip(
            "37 pytest tests pass locally — click for details")
        self._sb_tests.mousePressEvent = (
            lambda _ev: self._show_test_info())

        for w in (self._sb_preset, _sep(), self._sb_ws, _sep(),
                  self._sb_re, _sep(), self._sb_clock,
                  _sep(), self._sb_tests,
                  _sep(), self._sb_live_resid):
            sb.addPermanentWidget(w)
        self._refresh_status_bar()

    def _refresh_status_bar(self):
        """Re-read preset / workspace / Re / clock values and repaint the
        persistent status-bar widgets. Safe to call before the widgets
        exist (early startup) — silently no-ops."""
        if not hasattr(self, '_sb_preset'):
            return
        preset_name = getattr(self, '_active_preset_name', None) or "—"
        try:
            self._sb_preset.setText(f"Preset: {preset_name}")
        except Exception:
            pass
        try:
            self._sb_ws.setText(
                f"WS: {getattr(self, '_active_workspace', 'A')}")
        except Exception:
            pass
        # Re values come from the `_v_ReA`/`_v_ReB` result labels when a
        # compute has populated them. Fall back to "—" before first run.
        try:
            ra = self._v_ReA.text().strip() if hasattr(self, '_v_ReA') else '—'
            rb = self._v_ReB.text().strip() if hasattr(self, '_v_ReB') else '—'
            self._sb_re.setText(f"Re: A={ra or '—'} · B={rb or '—'}")
        except Exception:
            pass
        try:
            hist = getattr(self, '_compute_times', {}) or {}
            mode = self._active_compute_mode()
            last = None
            if hist.get(mode):
                last = hist[mode][-1]
            if last is None:
                self._sb_clock.setText("⏱ —")
            else:
                from ui.fmt import duration as _fmt_dur
                self._sb_clock.setText(
                    f"⏱ {_fmt_dur(last)} · {mode.upper()}")
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────
    #  Optimize tab — stage machine + KPI pump + summary banner
    # ─────────────────────────────────────────────────────────
    def _opt_set_stage(self, stage):
        """Paint the stage strip so `stage` ('config'/'running'/'result')
        reads as current, the preceding stages as done, and the rest as
        idle. No-op if the UI is not yet built."""
        pills = getattr(self, '_opt_stage_pills', None)
        styles = getattr(self, '_opt_pill_styles', None)
        if pills is None or styles is None:
            return
        idle, active, done = styles
        order = ('config', 'running', 'result')
        try:
            cur_idx = order.index(stage)
        except ValueError:
            return
        for i, key in enumerate(order):
            pill = pills.get(key)
            if pill is None:
                continue
            if i < cur_idx:
                pill.setStyleSheet(done)
            elif i == cur_idx:
                pill.setStyleSheet(active)
            else:
                pill.setStyleSheet(idle)

    def _opt_reset_panel(self):
        """Clear every live widget in the Optimize header so a fresh run
        starts from a clean slate (called at the top of run_optimize)."""
        for attr, default in (('_opt_kpi_gen', '—'),
                                 ('_opt_kpi_q',   '—'),
                                 ('_opt_kpi_dp',  '—'),
                                 ('_opt_kpi_eta', '—')):
            w = getattr(self, attr, None)
            if w is not None:
                w.setText(default)
        spark = getattr(self, '_opt_sparkline', None)
        if spark is not None:
            spark.clear_data()
        banner = getattr(self, '_opt_summary_banner', None)
        if banner is not None:
            banner.hide()

    def _opt_update_kpis(self, gen=None, gen_total=None,
                          best_q=None, best_dp=None, eta=None):
        """Update the hero KPI values from the poll tick. None → skip."""
        if gen is not None and hasattr(self, '_opt_kpi_gen'):
            txt = f"{gen}" + (f" / {gen_total}" if gen_total else "")
            self._opt_kpi_gen.setText(txt)
        if best_q is not None and hasattr(self, '_opt_kpi_q'):
            self._opt_kpi_q.setText(f"{best_q:.1f}")
            spark = getattr(self, '_opt_sparkline', None)
            if spark is not None:
                spark.push(float(best_q))
        if best_dp is not None and hasattr(self, '_opt_kpi_dp'):
            self._opt_kpi_dp.setText(f"{best_dp:.0f}")
        if eta is not None and hasattr(self, '_opt_kpi_eta'):
            self._opt_kpi_eta.setText(eta)

    def _opt_show_summary(self, n_solutions, q_lo, q_hi, elapsed_s,
                           extra_tag=""):
        """Paint the green post-run banner at the top of the Optimize tab.
        Called from show_pareto once the Pareto plot has data."""
        banner = getattr(self, '_opt_summary_banner', None)
        if banner is None:
            return
        if elapsed_s < 60:
            dur = f"{int(elapsed_s)}s"
        elif elapsed_s < 3600:
            dur = f"{int(elapsed_s // 60)}m{int(elapsed_s % 60):02d}s"
        else:
            dur = f"{int(elapsed_s // 3600)}h{int((elapsed_s % 3600) // 60):02d}m"
        tag = f"  ·  {extra_tag}" if extra_tag else ""
        banner.setText(
            f"  ✓  Done — {n_solutions} Pareto solutions  ·  "
            f"Q ∈ [{q_lo:.0f}, {q_hi:.0f}] W/m  ·  {dur}{tag}")
        banner.show()

    def _redraw_temp_if_ready(self):
        """Re-render the temperature tab using stored compute results.
        Invoked by the Sync-colorbar toggle on canvas_temp's mini toolbar.
        """
        try:
            from runs.run_calculation import redraw_temperature_panel
            redraw_temperature_panel(self)
        except Exception:
            pass

    def _keyboard_set_fluid(self, side, fluid_name):
        """Alt+digit quick-switch. Reuses `_apply_fluid_defaults` side-effect."""
        combo = getattr(self, f'combo_fluid{side}', None)
        if combo is None:
            return
        idx = combo.findText(fluid_name)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _cycle_density(self, step):
        """`[` / `]` cycle compact ↔ cozy ↔ comfortable with wraparound."""
        from ui.theme import get_density
        order = ('compact', 'cozy', 'comfortable')
        cur = get_density()
        try:
            i = order.index(cur)
        except ValueError:
            i = 1
        self._set_density(order[(i + step) % len(order)])

    def _validate_inputs_preflight(self):
        """Return True if all session inputs pass the validator; False +
        show a modal listing every bad field otherwise. Reuses the
        `inpError` dynamic property set by `_attach_input_validators`."""
        bad = []
        for name in self._SESSION_LINE_EDITS:
            le = getattr(self, name, None)
            if le is None:
                continue
            if le.property('inpError') == 'true':
                label = (le.accessibleName() or name)
                val = le.text() or '(empty)'
                bad.append((label, name, val))
            elif not le.text().strip():
                # Empty strict-positive fields are bad too.
                label = (le.accessibleName() or name)
                bad.append((label, name, '(empty)'))
        if not bad:
            return True
        # Escape user-typed text before interpolating into RichText HTML.
        # Without escape, a user typing `<img>` / `&` / quote characters
        # into a LineEdit would either break the table layout or render
        # arbitrary HTML in the modal. (Qt RichText doesn't run JS but
        # still parses tags; we escape every cell to be safe.) — 2026-04-29
        import html as _html_esc
        rows = "".join(
            f"<tr><td style='padding:4px 14px 4px 0;'>{_html_esc.escape(str(lbl))}</td>"
            f"<td style='padding:4px 14px 4px 0; color:#6b7280;'>"
            f"<code>{_html_esc.escape(str(name))}</code></td>"
            f"<td style='padding:4px 0; color:#DC2626; font-family:monospace;'>"
            f"{_html_esc.escape(str(val))}</td></tr>"
            for lbl, name, val in bad[:30])
        html = (
            f"<h3 style='margin:0 0 8px 0;'>"
            f"{len(bad)} invalid input{'s' if len(bad)!=1 else ''}</h3>"
            "<p style='margin:0 0 10px 0; color:#6b7280;'>"
            "Fix each field below before running Compute. "
            "Hover the field to see why.</p>"
            "<table style='border-collapse:collapse;'>"
            f"{rows}</table>")
        msg = QMessageBox(self)
        msg.setWindowTitle("Check inputs")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
        # Focus the first invalid field so Tab navigation works from there.
        first_attr = bad[0][1]
        le = getattr(self, first_attr, None)
        if le is not None:
            try:
                le.setFocus(); le.selectAll()
            except Exception:
                pass
        return False

    def _preflight_grid(self):
        """Grid-legality preflight (runs after field-level validator).

        Previews the refined grid, checks inlet/outlet cell coverage, and
        warns when Richardson doubling would blow up runtime. Returns True
        if OK to continue (no errors AND user acknowledged any warnings).
        """
        from ui.preflight import FluidCfg, compute_preflight

        def _f(attr, default=0.0):
            le = getattr(self, attr, None)
            if le is None:
                return default
            try:
                return float(le.text())
            except (TypeError, ValueError):
                return default

        def _i(attr, default=0):
            le = getattr(self, attr, None)
            if le is None:
                return default
            try:
                return int(le.text())
            except (TypeError, ValueError):
                return default

        L = _f('le_L'); H = _f('le_H'); Lz = _f('le_Lz')
        Nx = _i('le_Nx'); Ny = _i('le_Ny'); Nz = _i('le_Nz', 1)
        is_3d = (hasattr(self, 'combo_dim')
                 and self.combo_dim.currentIndex() == 1)
        wall_refine_3d = True
        if is_3d and hasattr(self, 'chk_wall_refine_3d'):
            wall_refine_3d = bool(self.chk_wall_refine_3d.isChecked())

        def _cfg(which):
            try:
                raw = self._fluid_config(which)
            except Exception:
                return None
            return FluidCfg(
                dir=raw['dir'],
                in_ctr=raw['in_ctr'], in_w=raw['in_w'],
                out_ctr=raw.get('out_ctr', raw['in_ctr']),
                out_w=raw.get('out_w', raw['in_w']),
                z_in_ctr=raw.get('in_z_ctr'),
                z_in_w=raw.get('in_z_w'))

        def _t_k(attr):
            le = getattr(self, attr, None)
            if le is None or not le.text().strip():
                return None
            try:
                return self._temp_to_K(le)
            except (TypeError, ValueError):
                return None

        report = compute_preflight(
            L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
            is_3d=is_3d, wall_refine_3d=wall_refine_3d,
            fluid_A=_cfg('A'), fluid_B=_cfg('B'),
            T_inA=_t_k('le_TinA'), T_inB=_t_k('le_TinB'))

        if not report.errors and not report.warnings:
            # Still surface info in the status bar so the user knows the
            # effective grid size even when everything passes.
            if report.info:
                self.statusBar().showMessage(
                    " · ".join(report.info[:2]), 6000)
            return True

        import html as _h

        def _rows(items, color):
            return "".join(
                f"<li style='margin:4px 0; color:{color};'>{_h.escape(s)}</li>"
                for s in items)

        sev_html = []
        if report.errors:
            sev_html.append(
                f"<h4 style='margin:8px 0 4px 0; color:#DC2626;'>"
                f"{len(report.errors)} error"
                f"{'s' if len(report.errors) != 1 else ''}</h4>"
                f"<ul style='margin:0;'>{_rows(report.errors, '#DC2626')}</ul>")
        if report.warnings:
            sev_html.append(
                f"<h4 style='margin:8px 0 4px 0; color:#B45309;'>"
                f"{len(report.warnings)} warning"
                f"{'s' if len(report.warnings) != 1 else ''}</h4>"
                f"<ul style='margin:0;'>{_rows(report.warnings, '#B45309')}</ul>")
        if report.info:
            sev_html.append(
                f"<h4 style='margin:8px 0 4px 0; color:#6b7280;'>Info</h4>"
                f"<ul style='margin:0;'>{_rows(report.info, '#6b7280')}</ul>")

        html = (
            "<h3 style='margin:0 0 8px 0;'>Grid preflight</h3>"
            "<p style='margin:0 0 8px 0; color:#6b7280;'>"
            "Reviewed wall-refine fit, inlet/outlet coverage, "
            "and Richardson budget.</p>" + "".join(sev_html))

        msg = QMessageBox(self)
        msg.setWindowTitle("Grid preflight")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html)
        if report.errors:
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
            return False
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        return msg.exec() == QMessageBox.StandardButton.Yes

    def _cycle_tab(self, step):
        """Ctrl+↑/↓ — walk through enabled tabs in toolbar order."""
        order = ('layout', 'temp', 'pres', 'vel', 'pareto', '3d')
        btn_map = {
            'layout': getattr(self, 'btn_tab_layout', None),
            'temp':   getattr(self, 'btn_tab_temp', None),
            'pres':   getattr(self, 'btn_tab_pres', None),
            'vel':    getattr(self, 'btn_tab_vel', None),
            'pareto': getattr(self, 'btn_tab_pareto', None),
            '3d':     getattr(self, 'btn_tab_3d', None),
        }
        enabled = [k for k in order if btn_map.get(k) is not None
                    and btn_map[k].isEnabled()]
        if not enabled:
            return
        cur = getattr(self, '_active_tab', enabled[0])
        try:
            i = enabled.index(cur)
        except ValueError:
            i = 0
        new_tab = enabled[(i + step) % len(enabled)]
        self._switch_tab(new_tab)

    def _scrub_recent(self, step):
        """Alt+↑/↓ walk through `_recent_runs`, loading each as a preset."""
        recents = list(getattr(self, '_recent_runs', []) or [])
        if not recents:
            self.statusBar().showMessage(
                "No recent runs to scrub through.", 3000)
            return
        idx = getattr(self, '_scrub_idx', -1)
        idx = max(0, min(len(recents) - 1, idx + step))
        self._scrub_idx = idx
        entry = recents[idx]
        try:
            self._apply_user_preset(entry.get('preset') or {})
            self.statusBar().showMessage(
                f"Recent #{idx + 1}/{len(recents)} — {entry.get('label','?')}"
                f"  ·  Q={entry.get('Q','?')}", 4000)
        except Exception:
            pass

    def _pick_accent_color(self):
        """E13 — let user choose a custom accent_primary override.
        Stored to `.accent` next to main.py; read at startup."""
        from PySide6.QtWidgets import QColorDialog
        from ui.theme import set_accent_override
        cur = get_theme().get('accent_primary', '#3B82F6')
        from PySide6.QtGui import QColor
        col = QColorDialog.getColor(QColor(cur), self, "Pick accent colour")
        if not col.isValid():
            return
        hex_ = col.name()
        set_accent_override(hex_)
        import os as _os_ac
        try:
            with open(_os_ac.path.join(
                    _os_ac.path.dirname(_os_ac.path.abspath(__file__)),
                    '.accent'), 'w', encoding='utf-8') as f:
                f.write(hex_)
        except Exception:
            pass
        msg = QMessageBox(self)
        msg.setWindowTitle("Accent changed")
        msg.setText(
            f"Accent set to {hex_}. "
            "Restart the app to apply everywhere.")
        restart = msg.addButton("Restart now",
                                 QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is restart:
            self._save_session()
            import sys as _sys
            _os_ac.execv(_sys.executable, [_sys.executable] + _sys.argv)

    def _set_density(self, name):
        """Switch display density (compact / cozy / comfortable). Same
        restart pattern as `_toggle_theme` because padded QSS is captured
        at widget build time."""
        if name not in ('compact', 'cozy', 'comfortable'):
            return
        try:
            set_density(name)
        except Exception as e:
            QMessageBox.warning(self, "Density switch failed", str(e))
            return
        import os as _os_d
        try:
            with open(_os_d.path.join(
                    _os_d.path.dirname(_os_d.path.abspath(__file__)),
                    '.density'), 'w', encoding='utf-8') as f:
                f.write(name)
        except Exception:
            pass
        msg = QMessageBox(self)
        msg.setWindowTitle("Density changed")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(
            f"Display density set to {name}. "
            "Restart the app to apply everywhere.")
        restart = msg.addButton("Restart now",
                                 QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is restart:
            self._save_session()
            import sys as _sys
            try:
                _os_d.execv(_sys.executable, [_sys.executable] + _sys.argv)
            except Exception as e:
                QMessageBox.warning(
                    self, "Restart failed",
                    f"Automatic restart failed ({e}).")

    def _toggle_theme(self):
        """Swap the active theme. Offers a "Restart now" path that saves the
        current session, writes the new theme to `.theme`, and relaunches
        the process in-place so every widget picks up the new palette.

        A live in-place rebuild is intentionally not attempted: QMatplotlib
        canvases, PyVistaQt's OpenGL context, the status-log message-hook,
        and the undo stack all hold token values captured at build time,
        and re-seating them cleanly is a larger engineering undertaking
        than re-exec'ing the process.
        """
        current = get_theme_name()
        new = 'light' if current == 'dark' else 'dark'
        try:
            set_theme(new)
        except Exception as e:
            QMessageBox.warning(self, "Theme switch failed", str(e))
            return
        import os as _os_t
        try:
            cfg_dir = _os_t.path.dirname(_os_t.path.abspath(__file__))
            with open(_os_t.path.join(cfg_dir, '.theme'), 'w',
                      encoding='utf-8') as f:
                f.write(new)
        except Exception:
            pass

        msg = QMessageBox(self)
        msg.setWindowTitle("Theme changed")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(
            f"Theme switched to {new}. "
            "Restart the app to apply the new palette everywhere.")
        restart = msg.addButton("Restart now",
                                 QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is restart:
            self._save_session()
            import sys as _sys
            # os.execv replaces the current process image, so the new app
            # starts with a clean QApplication and the .theme file we just
            # wrote. Works on Windows via the CRT shim.
            try:
                _os_t.execv(_sys.executable, [_sys.executable] + _sys.argv)
            except Exception as e:
                QMessageBox.warning(
                    self, "Restart failed",
                    f"Automatic restart failed ({e}). Please relaunch "
                    "the app manually.")

    def _toggle_3d_immersive(self):
        """Full-bleed 3D: collapse left panel + expand 3D card to a tall
        immersive height. Pressing F again restores both. Scoped by
        `_active_tab == '3d'` so the shortcut is a no-op elsewhere.
        """
        if getattr(self, '_active_tab', None) != '3d':
            return
        card = self._canvas_cards.get('3d')
        if card is None:
            return
        default_h = self._canvas_default_h.get('3d', 1100)
        immersive_h = 1800
        if not getattr(self, '_3d_immersive', False):
            # Remember so we can restore left panel only if it was visible.
            self._3d_prev_left_collapsed = getattr(self, '_left_collapsed', False)
            if not self._3d_prev_left_collapsed:
                self._toggle_left_panel()
            card.setFixedHeight(immersive_h)
            self._3d_immersive = True
            self.statusBar().showMessage(
                "3D immersive mode — press F to exit.", 4000)
        else:
            card.setFixedHeight(default_h)
            if not getattr(self, '_3d_prev_left_collapsed', True):
                self._toggle_left_panel()
            self._3d_immersive = False
            self.statusBar().showMessage(
                "3D immersive mode off.", 3000)

    def _toggle_left_panel(self):
        """Collapse / restore the left parameter panel.

        Hides the splitter's first widget rather than zero-sizing it, because
        build_ui pins `setChildrenCollapsible(False)` to prevent accidental
        drag-collapse. Tracks state in `_left_collapsed` so the toggle works
        even before the window is mapped to the screen (when `isVisible()`
        would otherwise lie).
        """
        if not hasattr(self, '_splitter'):
            return
        left_widget = self._splitter.widget(0)
        if left_widget is None:
            return
        collapsed = getattr(self, '_left_collapsed', False)
        if not collapsed:
            left_widget.hide()
            self._left_collapsed = True
            if hasattr(self, 'btn_toggle_left'):
                self.btn_toggle_left.setText("›")
                self.btn_toggle_left.setToolTip("Restore parameter panel")
        else:
            left_widget.show()
            self._left_collapsed = False
            if hasattr(self, 'btn_toggle_left'):
                self.btn_toggle_left.setText("‹")
                self.btn_toggle_left.setToolTip("Collapse parameter panel")

    # Canonical presets shipped with the app; user presets append after
    # these. Index 0 is the prompt placeholder managed by the combo itself.
    _BUILTIN_PRESETS = [
        "Shanghai (3D Gyroid)",
        "Shanghai (2D Gyroid)",
        "Shanghai (3D Diamond)",
    ]
    _SAVE_PRESET_LABEL = "— Save current as preset… —"

    def _user_presets_path(self):
        """Legacy shim — delegates to SessionManager.presets_path()."""
        return str(self.sm.presets_path())

    def _load_user_presets(self):
        """Return the list of user-defined preset dicts (possibly empty).

        Delegates to SessionManager (Plan #4 P2.3).
        """
        return self.sm.load_user_presets()

    def _save_user_presets(self, presets):
        """Persist user preset list. Delegates to SessionManager (P2.3)."""
        self.sm.save_user_presets(presets)

    def _rebuild_preset_combo(self):
        """Refresh the header preset dropdown with builtins + user presets +
        the trailing 'Save current…' action row. Called on startup and after
        any save operation.
        """
        if not hasattr(self, 'combo_preset'):
            return
        combo = self.combo_preset
        blocker = combo.blockSignals(True)
        combo.clear()
        combo.addItem("Preset…")
        for name in self._BUILTIN_PRESETS:
            combo.addItem(name)
        user = self._load_user_presets()
        for p in user:
            n = p.get('name')
            if n:
                combo.addItem(f"★ {n}")
        combo.addItem(self._SAVE_PRESET_LABEL)
        combo.blockSignals(blocker)

    def _apply_user_preset(self, preset):
        """Apply a saved preset payload (shape matches _save_session output).

        Widget names are filtered through the SESSION allow-lists so a tampered
        or malicious share-link cannot address arbitrary window attributes.
        """
        unit = preset.get('temp_unit', 'K')
        if unit in ('K', 'C'):
            self._temp_unit = unit
            if hasattr(self, '_sync_temp_unit_labels'):
                self._sync_temp_unit_labels()
        allowed_edits = set(self._SESSION_LINE_EDITS)
        allowed_combos = set(self._SESSION_COMBOS)
        allowed_checks = set(self._SESSION_CHECKS)
        for name, txt in (preset.get('line_edits') or {}).items():
            if name not in allowed_edits:
                continue
            w = getattr(self, name, None)
            if w is not None:
                try: w.setText(str(txt))
                except Exception: pass
        for name, idx in (preset.get('combos') or {}).items():
            if name not in allowed_combos:
                continue
            c = getattr(self, name, None)
            if c is not None:
                try:
                    if 0 <= int(idx) < c.count():
                        c.setCurrentIndex(int(idx))
                except Exception: pass
        for name, val in (preset.get('checks') or {}).items():
            if name not in allowed_checks:
                continue
            b = getattr(self, name, None)
            if b is not None:
                try: b.setChecked(bool(val))
                except Exception: pass

    def _capture_current_preset(self, name):
        """Build a preset payload from the current field state."""
        payload = {'name': name,
                   'temp_unit': getattr(self, '_temp_unit', 'K'),
                   'line_edits': {}, 'combos': {}, 'checks': {}}
        for n in self._SESSION_LINE_EDITS:
            w = getattr(self, n, None)
            if w is not None:
                try: payload['line_edits'][n] = w.text()
                except Exception: pass
        for n in self._SESSION_COMBOS:
            c = getattr(self, n, None)
            if c is not None:
                try: payload['combos'][n] = int(c.currentIndex())
                except Exception: pass
        for n in self._SESSION_CHECKS:
            b = getattr(self, n, None)
            if b is not None:
                try: payload['checks'][n] = bool(b.isChecked())
                except Exception: pass
        return payload

    def _on_preset_selected(self, idx):
        """Header preset dropdown handler.

        Layout of the combo:
          0                  prompt ("Preset…") — no-op
          1..N_BUILTIN       canonical Shanghai variants
          N_BUILTIN+1..M     user-saved presets (prefixed ★)
          last               'Save current as preset…' action
        """
        if idx == 0:
            return
        combo = self.combo_preset
        label = combo.itemText(idx)
        # Reset combo back to prompt regardless of what happens below.
        def _debounce():
            blocker = combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(blocker)
        try:
            if label == self._SAVE_PRESET_LABEL:
                self._save_current_as_preset()
                return
            n_builtin = len(self._BUILTIN_PRESETS)
            if 1 <= idx <= n_builtin:
                name = self._BUILTIN_PRESETS[idx - 1]
                self._active_preset_name = name
                if hasattr(self, '_refresh_status_bar'):
                    self._refresh_status_bar()
                if name == "Shanghai (3D Gyroid)":
                    self._apply_shanghai_defaults()
                elif name == "Shanghai (2D Gyroid)":
                    self._apply_shanghai_defaults()
                    self.combo_dim.setCurrentIndex(0)
                    self.statusBar().showMessage(
                        "Preset: Shanghai (2D Gyroid).", 5000)
                elif name == "Shanghai (3D Diamond)":
                    self._apply_shanghai_defaults()
                    self.combo_tpms.setCurrentIndex(0)
                    self.statusBar().showMessage(
                        "Preset: Shanghai (3D Diamond).", 5000)
                return
            # User preset: star-prefixed item past the builtin block
            user = self._load_user_presets()
            u_idx = idx - 1 - n_builtin
            if 0 <= u_idx < len(user):
                self._apply_user_preset(user[u_idx])
                self.statusBar().showMessage(
                    f"Loaded preset: {user[u_idx].get('name', '?')}.", 5000)
        finally:
            _debounce()

    def _save_current_as_preset(self):
        """Prompt for a name and persist the full current field state as a
        user preset. Overwrites silently on duplicate name."""
        name, ok = QInputDialog.getText(
            self, "Save Preset",
            "Preset name:", text="my_preset")
        if not ok or not name.strip():
            return
        name = name.strip()
        presets = self._load_user_presets()
        presets = [p for p in presets if p.get('name') != name]  # overwrite
        presets.append(self._capture_current_preset(name))
        self._save_user_presets(presets)
        self._rebuild_preset_combo()
        self.statusBar().showMessage(
            f"Saved preset: {name}.", 5000)

    # ─────────────────────────────────────────────────────────
    #  Session auto-persist (restores last-used field state)
    # ─────────────────────────────────────────────────────────
    _SESSION_LINE_EDITS = (
        'le_L', 'le_H', 'le_Lz', 'le_Lcell', 'le_t', 'le_ks',
        'le_uA', 'le_TinA', 'le_PinA', 'le_uB', 'le_TinB', 'le_PinB',
        # le_TsInit removed 2026-04-29 (numerical seed only, not physical)
        'le_Nx', 'le_Ny', 'le_Nz',
        'le_rho_s',
        'le_pipeA_in_ctr', 'le_pipeA_in_w',
        'le_pipeA_out_ctr', 'le_pipeA_out_w',
        'le_pipeB_in_ctr', 'le_pipeB_in_w',
        'le_pipeB_out_ctr', 'le_pipeB_out_w',
        'le_pipeA_in_z_ctr', 'le_pipeA_in_z_w',
        'le_pipeA_out_z_ctr', 'le_pipeA_out_z_w',
        'le_pipeB_in_z_ctr', 'le_pipeB_in_z_w',
        'le_pipeB_out_z_ctr', 'le_pipeB_out_z_w',
        'le_mesh_density',
    )
    _SESSION_COMBOS = (
        'combo_shape', 'combo_dim', 'combo_tpms',
        'combo_fluidA', 'combo_fluidB',
        'combo_dirA', 'combo_dirB',
    )
    _SESSION_CHECKS = ('chk_zones', 'chk_wall_refine_3d')

    _WORKSPACES = ('A', 'B', 'C')

    def _session_path(self, workspace=None):
        """Legacy shim — delegates to SessionManager.session_path() (P2.3).

        Workspaces let users park 2–3 independent parameter sets and flip
        between them without losing state. Workspace A keeps the legacy
        `.last_session.json` filename so existing users aren't reset.
        """
        ws = workspace or getattr(self, '_active_workspace', 'A')
        return str(self.sm.session_path(ws))

    def _switch_workspace(self, new):
        """Persist the current workspace, activate `new`, and reload it."""
        if new not in self._WORKSPACES:
            return
        cur = getattr(self, '_active_workspace', 'A')
        if cur == new:
            return
        try:
            self._save_session()  # saves to the current workspace path
        except Exception:
            pass
        self._active_workspace = new
        try:
            self._apply_shanghai_defaults()
            self._restore_session()
        except Exception as e:
            QMessageBox.warning(self, "Workspace switch", str(e))
        if hasattr(self, '_rebuild_workspace_menu'):
            self._rebuild_workspace_menu()
        if hasattr(self, '_refresh_status_bar'):
            self._refresh_status_bar()
        # Persist the choice so the next launch re-opens the same workspace.
        # Delegates to SessionManager (P2.3).
        self.sm.set_active_workspace(new)
        self.statusBar().showMessage(f"Workspace {new} loaded.", 4000)

    def _rebuild_workspace_menu(self):
        """Refresh the header Workspace ▾ menu to reflect the active tab."""
        from PySide6.QtWidgets import QMenu
        if not hasattr(self, 'btn_workspace'):
            return
        active = getattr(self, '_active_workspace', 'A')
        self.btn_workspace.setText(f"WS: {active} ▾")
        menu = QMenu(self)
        for ws in self._WORKSPACES:
            mark = "● " if ws == active else "   "
            act = menu.addAction(f"{mark}Workspace {ws}")
            act.triggered.connect(
                lambda _checked=False, name=ws: self._switch_workspace(name))
        self.btn_workspace.setMenu(menu)

    def _save_session(self):
        """Dump every input field's current value via SessionManager (P2.3).

        Best-effort: any attribute that is missing or that throws on read
        is silently skipped — partial sessions still reload cleanly
        (missing keys fall back to the Shanghai preset).
        """
        payload = {'temp_unit': getattr(self, '_temp_unit', 'K')}
        lines = {}
        for name in self._SESSION_LINE_EDITS:
            w = getattr(self, name, None)
            if w is None:
                continue
            try:
                lines[name] = w.text()
            except Exception:
                continue
        payload['line_edits'] = lines
        combos = {}
        for name in self._SESSION_COMBOS:
            c = getattr(self, name, None)
            if c is None:
                continue
            try:
                combos[name] = int(c.currentIndex())
            except Exception:
                continue
        payload['combos'] = combos
        checks = {}
        for name in self._SESSION_CHECKS:
            b = getattr(self, name, None)
            if b is None:
                continue
            try:
                checks[name] = bool(b.isChecked())
            except Exception:
                continue
        payload['checks'] = checks
        # Window geometry + state (maximised, size, position). Store as
        # base64 so the JSON stays readable when the rest is inspected.
        try:
            import base64 as _b64
            geo = bytes(self.saveGeometry())
            st = bytes(self.saveState())
            payload['geometry'] = _b64.b64encode(geo).decode('ascii')
            payload['win_state'] = _b64.b64encode(st).decode('ascii')
        except Exception:
            pass
        # SessionManager handles IO failure silently + stamps schema_version.
        self.sm.save_session(payload, getattr(self, '_active_workspace', 'A'))

    def _restore_session(self):
        """Load values saved by `_save_session` on top of the Shanghai
        defaults. Silently no-ops if the file doesn't exist or is malformed.

        Delegates IO to SessionManager (P2.3).
        """
        ws = getattr(self, '_active_workspace', 'A')
        payload = self.sm.load_session(ws)
        if payload is None:
            return
        # Apply temp_unit first so we can interpret text correctly. The JSON
        # stores text as the user saw it, so matching units is the safe path.
        saved_unit = payload.get('temp_unit', 'K')
        if saved_unit in ('K', 'C'):
            self._temp_unit = saved_unit
            # Header button + row labels need to match the restored unit so
            # the restored text ("148.85") is not misread as Kelvin.
            if hasattr(self, '_sync_temp_unit_labels'):
                self._sync_temp_unit_labels()
        # User preference: app must open with temperature unit = K. If the
        # saved session was authored in °C, the line-edit text below is in
        # °C — restore it as-is, then convert + flip the unit to K so the
        # initial view is always Kelvin.
        _temp_field_names = {'le_TinA', 'le_TinB'}
        for name, txt in (payload.get('line_edits') or {}).items():
            w = getattr(self, name, None)
            if w is None:
                continue
            try:
                w.setText(str(txt))
            except Exception:
                continue
        if saved_unit == 'C':
            for name in _temp_field_names:
                w = getattr(self, name, None)
                if w is None:
                    continue
                try:
                    val = float(w.text())
                    w.setText(f"{val + 273.15:.2f}")
                except (ValueError, TypeError):
                    continue
            self._temp_unit = 'K'
            if hasattr(self, '_sync_temp_unit_labels'):
                self._sync_temp_unit_labels()
        for name, idx in (payload.get('combos') or {}).items():
            # User preference: app must open with both fluids defaulted to
            # Air, regardless of what the previous session stored. Skip
            # restoring combo_fluidA/B and let the construction-time index 0
            # (Air) stand.
            if name in ('combo_fluidA', 'combo_fluidB'):
                continue
            c = getattr(self, name, None)
            if c is None:
                continue
            try:
                if 0 <= int(idx) < c.count():
                    c.setCurrentIndex(int(idx))
            except Exception:
                continue
        for name, val in (payload.get('checks') or {}).items():
            b = getattr(self, name, None)
            if b is None:
                continue
            try:
                b.setChecked(bool(val))
            except Exception:
                continue
        # Restore window geometry / dock state last so it doesn't fight the
        # `showMaximized()` the constructor already called. Pass-through:
        # if the payload is missing or corrupt, the explicit showMaximized
        # wins and the user sees the standard maximised window.
        import base64 as _b64
        from PySide6.QtCore import QByteArray
        geo_b64 = payload.get('geometry')
        if geo_b64:
            try:
                self.restoreGeometry(QByteArray(_b64.b64decode(geo_b64)))
            except Exception:
                pass
        st_b64 = payload.get('win_state')
        if st_b64:
            try:
                self.restoreState(QByteArray(_b64.b64decode(st_b64)))
            except Exception:
                pass
        # User preference: both fluid-type combos open as Air. Combos stay
        # at construction-time index 0; if the saved session had a *non-Air*
        # selection (Water / sCO₂), the line-edits are now in that fluid's
        # value range — push Air defaults to keep u/T/P consistent with the
        # forced Air combo. If the saved combo was already Air, leave the
        # restored line-edits alone so user customisations survive.
        _saved_combos = payload.get('combos') or {}
        for _side in ('A', 'B'):
            try:
                _saved_idx = int(_saved_combos.get(f'combo_fluid{_side}', 0))
            except (ValueError, TypeError):
                _saved_idx = 0
            if _saved_idx != 0:
                try:
                    self._apply_fluid_defaults(_side)
                except Exception:
                    pass
        # User preference: grid defaults Nx=Ny=Nz=20 must win on every
        # startup, even when a previous session saved different values, AND
        # must survive a subsequent "Compute TPMS Geometry" call which would
        # otherwise auto-suggest D_h-derived Nx/Ny/Nz. Setting the
        # `_user_edited_grid` sentinel makes compute_tpms skip its
        # auto-fill block so the 20/20/20 default is sticky.
        # Detect if any reset diverges from saved state — if so, show a
        # one-shot status message so the user knows their session was NOT
        # fully restored (was previously silent — auditor's "feels like a
        # bug" concern, 2026-05-05 audit).
        _saved_grid = (payload.get('line_edits') or {})
        _grid_was_custom = any(
            (str(_saved_grid.get(_n, '20')).strip() not in ('', '20'))
            for _n in ('le_Nx', 'le_Ny', 'le_Nz'))
        for _attr in ('le_Nx', 'le_Ny', 'le_Nz'):
            _le = getattr(self, _attr, None)
            if _le is not None:
                try:
                    _le.setText('20')
                except Exception:
                    pass
        self._user_edited_grid = True
        # Surface reset notices via deferred status bar — wait until the
        # window is shown so the message isn't eaten by subsequent renders.
        from PySide6.QtCore import QTimer as _QT_msg
        _msgs = []
        if _grid_was_custom:
            _msgs.append("Grid reset to 20×20×20 (default; saved values discarded)")
        _saved_combos2 = payload.get('combos') or {}
        if any(int(_saved_combos2.get(f'combo_fluid{_s}', 0) or 0) != 0
               for _s in ('A', 'B')):
            _msgs.append("Fluid type reset to Air (default; saved selection discarded)")
        if _msgs:
            def _flash():
                try:
                    self.statusBar().showMessage(" · ".join(_msgs), 8000)
                except Exception:
                    pass
            _QT_msg.singleShot(800, _flash)

    def closeEvent(self, event):
        # Persist session first — the legacy contract expected this.
        try:
            self._save_session()
        except Exception:
            pass
        # Phase 3 (2026-05-06 #4): bulk-disconnect router-tracked signal
        # connections. Belt-and-braces against bound-method slots that
        # close over ``self`` and outlive the C++ widget destruction.
        try:
            if getattr(self, 'signals', None) is not None:
                self.signals.disconnect_all()
        except Exception:
            pass
        super().closeEvent(event)

    def _maybe_show_onboarding(self):
        """First-run only: surface a 3-step guidance dialog pointing at the
        parameter panel, Compute button, and result tabs. Dismissal writes
        `.first_run_done` next to the executable; future launches skip.
        """
        import os as _os_ob
        flag = _os_ob.path.join(
            _os_ob.path.dirname(_os_ob.path.abspath(__file__)),
            '.first_run_done')
        if _os_ob.path.exists(flag):
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Welcome to SJTU-TPMSHX")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(
            "Quick tour\n\n"
            "1.  Left panel — configure Geometry, Boundary Conditions, "
            "Zone Layout.\n"
            "2.  Header ▶ Compute — run a single-point solve "
            "(menu → Optimize for NSGA-II).\n"
            "3.  Right canvas — explore Temperature / Pressure / "
            "Velocity / 3D View tabs once compute finishes.\n\n"
            "Presets, theme toggle (☀/☾), and K/°C units live in the "
            "header. This hint will not show again.")
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
        try:
            with open(flag, 'w', encoding='utf-8') as _f:
                _f.write("1")
        except Exception:
            pass  # best-effort; next launch may show again

    # ─────────────────────────────────────────────────────────
    #  Help surface — About dialog + keyboard shortcut cheat sheet
    # ─────────────────────────────────────────────────────────
    def _apply_accessibility(self):
        """Set AccessibleName/AccessibleDescription on main controls for
        screen readers. Tooltips are already AT-accessible but explicit
        accessible text lets NVDA/JAWS announce *purpose* (e.g., "Run
        heat-transfer solve") distinct from the visible label.
        """
        _A = [
            ('btn_compute', "Compute",
             "Run heat-transfer and pressure-drop solve for current parameters"),
            ('btn_theme', "Theme",
             "Toggle light and dark application theme"),
            ('btn_temp_unit', "Temperature unit",
             "Switch temperature display between Kelvin and Celsius"),
            ('btn_help', "Help",
             "Open help menu — About, keyboard shortcuts, and quick tour"),
            ('btn_toggle_left', "Parameter panel",
             "Collapse or expand the left parameter panel"),
            ('combo_preset', "Preset picker",
             "Load a canonical or user-saved case preset"),
            ('combo_tpms', "TPMS type",
             "Triply-Periodic Minimal Surface lattice type"),
            ('combo_dim', "Dimensionality",
             "Switch between 2D planar and 3D volumetric solve"),
            ('combo_fluidA', "Fluid A type",
             "Working fluid for channel A (hot side)"),
            ('combo_fluidB', "Fluid B type",
             "Working fluid for channel B (cold side)"),
            ('combo_dirA', "Flow direction A",
             "Principal flow axis for channel A"),
            ('combo_dirB', "Flow direction B",
             "Principal flow axis for channel B"),
            ('btn_tab_temp', "Temperature tab",
             "Show temperature contour results"),
            ('btn_tab_pres', "Pressure tab",
             "Show pressure-field results"),
            ('btn_tab_vel',  "Velocity tab",
             "Show velocity-magnitude results"),
            ('btn_tab_3d',   "3D tab",
             "Show 3D volumetric view"),
            ('btn_tab_layout', "Layout tab",
             "Show zone layout preview"),
            ('btn_tab_pareto', "Pareto tab",
             "Show Pareto-front optimisation results"),
            ('_opt_btn', "Optimize",
             "Start NSGA-II multi-objective search — runs for minutes to hours"),
            ('progress', "Computation progress",
             "Current solve progress as a percentage"),
            ('zone_table', "Zone table",
             "Per-zone start, end, L, t parameters. Tab to navigate cells."),
        ]
        for attr, name, desc in _A:
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                w.setAccessibleName(name)
                w.setAccessibleDescription(desc)
            except Exception:
                continue
        # LineEdits: rough accessible name from their row label. Reads the
        # label text stripped of HTML and unit brackets so a screen reader
        # hears "domain length" rather than "L [m]". Attach only to the
        # ones we know have a corresponding stored `_lbl_<name>` or which
        # map clearly to a physical quantity.
        _INP_A11Y = {
            'le_L': ("Domain length", "Overall domain length in metres"),
            'le_H': ("Domain height", "Overall domain height in metres"),
            'le_Lz': ("Domain depth",  "Domain extent in the z direction in metres"),
            'le_Lcell': ("TPMS cell size", "Unit-cell edge length in millimetres"),
            'le_t': ("Wall thickness",  "TPMS solid wall thickness in millimetres"),
            'le_ks': ("Solid conductivity",
                      "Thermal conductivity of the solid phase, W/m-K"),
            'le_uA': ("Fluid A velocity", "Interstitial velocity, m/s"),
            'le_uB': ("Fluid B velocity", "Interstitial velocity, m/s"),
            'le_TinA': ("Fluid A inlet temperature", "Inlet temperature of fluid A"),
            'le_TinB': ("Fluid B inlet temperature", "Inlet temperature of fluid B"),
            'le_PinA': ("Fluid A inlet pressure", "Absolute inlet pressure, Pa"),
            'le_PinB': ("Fluid B inlet pressure", "Absolute inlet pressure, Pa"),
            'le_Nx': ("Grid Nx", "Number of mesh cells in x direction"),
            'le_Ny': ("Grid Ny", "Number of mesh cells in y direction"),
            'le_Nz': ("Grid Nz", "Number of mesh cells in z direction"),
        }
        for attr, (name, desc) in _INP_A11Y.items():
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                w.setAccessibleName(name)
                w.setAccessibleDescription(desc)
            except Exception:
                continue

    def _show_about(self):
        """Report version, commit, Python/Qt/NumPy/SciPy versions, author."""
        lines = [f"<b>SJTU-TPMSHX</b> v{__version__}"]
        commit = _git_commit_hash()
        if commit:
            lines.append(f"Commit: <code>{commit}</code>")
        lines.append("")
        lines.append("TPMS heat-exchanger homogenised solver for SJTU.")
        lines.append(
            "2D/3D compressible D-F + SIMPLE with NSGA-II zoning search.")
        lines.append("")
        import sys as _sys_ab, platform as _plat
        try:
            from PySide6 import __version__ as _qt_ver
        except Exception:
            _qt_ver = "?"
        try:
            import numpy as _np_ab
            _np_v = _np_ab.__version__
        except Exception:
            _np_v = "?"
        try:
            import scipy as _sp_ab
            _sp_v = _sp_ab.__version__
        except Exception:
            _sp_v = "?"
        try:
            import matplotlib as _mpl_ab
            _mpl_v = _mpl_ab.__version__
        except Exception:
            _mpl_v = "?"
        lines.append(f"Python {_sys_ab.version.split()[0]} · {_plat.system()} {_plat.release()}")
        lines.append(
            f"PySide6 {_qt_ver} · NumPy {_np_v} · SciPy {_sp_v} · Matplotlib {_mpl_v}")
        lines.append("")
        lines.append("Author: alexlu997 &lt;alexlu997@hotmail.com&gt;")
        lines.append("Repo: github.com/alexlu997/SJTU-TPMSHX")
        msg = QMessageBox(self)
        msg.setWindowTitle("About SJTU-TPMSHX")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText("<br>".join(lines))
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    _SHORTCUT_ROWS = (
        ("Command palette",        "Ctrl+K"),
        ("Overview dashboard",     "Ctrl+D"),
        ("Coordinate inspector",   "Ctrl+I"),
        ("Filter parameters",      "Ctrl+F"),
        ("Launch NSGA-II",         "Ctrl+Enter"),
        ("Cycle tabs",             "Ctrl+↑ / Ctrl+↓"),
        ("Quick fluid (A / B)",    "Alt+1/2/3  ·  Alt+Shift+1/2/3"),
        ("Cycle density",          "[  /  ]"),
        ("Scrub recent runs",      "Alt+↑ / Alt+↓"),
        ("Compute",                "Ctrl+R"),
        ("Reset parameters",       "Ctrl+Shift+R"),
        ("Undo field edit",        "Ctrl+Z"),
        ("Redo field edit",        "Ctrl+Y"),
        ("Tab — Layout",           "Ctrl+1"),
        ("Tab — Temperature",      "Ctrl+2"),
        ("Tab — Pressure",         "Ctrl+3"),
        ("Tab — Velocity",         "Ctrl+4"),
        ("Tab — 3D View",          "Ctrl+5"),
        ("3D immersive toggle",    "F  (in 3D tab)"),
        ("Keyboard cheat sheet",   "Ctrl+?"),
        ("Compute button",         "Alt+C"),
        ("Reset button",           "Alt+R"),
        ("Export results",         "Alt+E"),
        ("Preview layout",         "Alt+P"),
        ("Optimize (NSGA-II)",     "Alt+O"),
    )

    def _show_shortcuts(self):
        """Popup dialog listing all keyboard shortcuts as a two-column table."""
        rows_html = "".join(
            f"<tr><td style='padding:4px 16px 4px 0;'>{label}</td>"
            f"<td style='padding:4px 0; font-family:monospace;'><b>{key}</b></td></tr>"
            for label, key in self._SHORTCUT_ROWS)
        html = (
            "<h3 style='margin:0 0 8px 0;'>Keyboard shortcuts</h3>"
            "<table style='border-collapse:collapse;'>"
            f"{rows_html}"
            "</table>"
            "<p style='margin-top:12px; color:#888;'>Alt-mnemonics activate "
            "the underlined letter on any button when Alt is held.</p>")
        msg = QMessageBox(self)
        msg.setWindowTitle("Keyboard Shortcuts")
        msg.setIcon(QMessageBox.Icon.NoIcon)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _show_help_menu(self, anchor_btn=None):
        """Pop a menu at the Help button with About / Shortcuts / Quick tour."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        act_cmd = menu.addAction("&Command palette…\tCtrl+K")
        act_cmd.triggered.connect(self._open_command_palette)
        menu.addSeparator()
        act_about = menu.addAction("&About SJTU-TPMSHX…")
        act_about.triggered.connect(self._show_about)
        act_kb = menu.addAction("&Keyboard shortcuts…\tCtrl+?")
        act_kb.triggered.connect(self._show_shortcuts)
        menu.addSeparator()
        act_tour = menu.addAction("Quick &tour")
        act_tour.triggered.connect(self._show_quick_tour)
        if anchor_btn is not None:
            from PySide6.QtCore import QPoint
            pos = anchor_btn.mapToGlobal(QPoint(0, anchor_btn.height()))
            menu.exec(pos)
        else:
            menu.exec()

    def _open_command_palette(self):
        """Open the Ctrl+K command palette menu-driven (Help menu entry)."""
        pal = getattr(self, '_command_palette', None)
        if pal is None:
            from ui.command_palette import CommandPalette
            pal = CommandPalette(self)
            self._command_palette = pal
        pal.open_palette()

    def _show_quick_tour(self):
        """Re-show the first-run onboarding dialog (clears the flag)."""
        import os as _os_qt
        flag = _os_qt.path.join(
            _os_qt.path.dirname(_os_qt.path.abspath(__file__)),
            '.first_run_done')
        try:
            if _os_qt.path.exists(flag):
                _os_qt.remove(flag)
        except Exception:
            pass
        self._maybe_show_onboarding()

    # ─────────────────────────────────────────────────────────
    #  Undo/Redo for input field edits (Ctrl+Z / Ctrl+Y)
    # ─────────────────────────────────────────────────────────
    def _install_undo_stack(self):
        """Track every value change on a numeric input and push it onto a
        QUndoStack so Ctrl+Z / Ctrl+Y can sweep back and forth across
        *cross-field* edits. Qt's built-in per-widget undo only covers the
        currently focused field; this extends it to the whole form.
        """
        from PySide6.QtGui import QUndoStack, QUndoCommand, QShortcut, QKeySequence

        class _FieldEditCmd(QUndoCommand):
            def __init__(self, le, old, new, cache, name):
                super().__init__(f"edit {name}")
                self._le = le
                self._old = old
                self._new = new
                self._cache = cache
                self._name = name

            def undo(self):
                self._le.blockSignals(True)
                self._le.setText(self._old)
                self._le.blockSignals(False)
                self._cache[self._name] = self._old

            def redo(self):
                self._le.blockSignals(True)
                self._le.setText(self._new)
                self._le.blockSignals(False)
                self._cache[self._name] = self._new

        self._undo_stack = QUndoStack(self)
        self._undo_stack.setUndoLimit(200)
        self._undo_last = {}

        for name in self._SESSION_LINE_EDITS:
            le = getattr(self, name, None)
            if le is None:
                continue
            self._undo_last[name] = le.text()

            def _on_finished(le=le, name=name):
                cur = le.text()
                prev = self._undo_last.get(name, cur)
                if cur != prev:
                    self._undo_stack.push(
                        _FieldEditCmd(le, prev, cur, self._undo_last, name))
            le.editingFinished.connect(_on_finished)

        QShortcut(QKeySequence.StandardKey.Undo, self).activated.connect(
            self._undo_stack.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self).activated.connect(
            self._undo_stack.redo)

    _FIELD_HELP = {
        'le_L': (
            "<b>Domain length <i>L</i></b> [m]<br/>"
            "Flow-direction extent of the TPMS heat-exchanger block. "
            "Excludes any external piping."),
        'le_H': (
            "<b>Domain width <i>H</i></b> [m]<br/>"
            "Cross-flow extent."),
        'le_Lz': (
            "<b>Domain depth <i>L<sub>z</sub></i></b> [m] (3D only)<br/>"
            "Out-of-plane extent. 2D runs treat Lz as unit depth."),
        'le_Lcell': (
            "<b>TPMS unit-cell edge <i>L<sub>cell</sub></i></b> [mm]<br/>"
            "Typical 4 – 8 mm. Drives D<sub>h</sub>, porosity, permeability "
            "via the ConstDF-v1 surrogate."),
        'le_t': (
            "<b>TPMS wall thickness <i>t</i></b> [mm]<br/>"
            "Training range [0.3, 0.5] mm. Values outside extrapolate — Shanghai"
            " t = 0.6 mm is a known hard extrapolation."),
        'le_ks': (
            "<b>Solid thermal conductivity <i>k<sub>s</sub></i></b> "
            "[W/(m·K)]<br/>"
            "SS316L ≈ 16, Inconel 625 ≈ 12, copper ≈ 390."),
        'le_uA': (
            "<b>Fluid A interstitial velocity <i>u<sub>A</sub></i></b> [m/s]"
            "<br/>Through-pore superficial / ε<sub>f</sub>. "
            "Target 600 &lt; Re &lt; 30000."),
        'le_uB': (
            "<b>Fluid B interstitial velocity <i>u<sub>B</sub></i></b> [m/s]"
            "<br/>Typical cross-flow water: 0.1 – 0.2 m/s."),
        'le_TinA': (
            "<b>Fluid A inlet temperature <i>T<sub>in,A</sub></i></b><br/>"
            "Physics uses K internally. K/°C toggle lives in the header."),
        'le_TinB': (
            "<b>Fluid B inlet temperature <i>T<sub>in,B</sub></i></b><br/>"
            "Physics uses K internally. K/°C toggle lives in the header."),
        'le_PinA': (
            "<b>Fluid A inlet absolute pressure <i>P<sub>in,A</sub></i></b> "
            "[Pa]<br/>101 325 = 1 atm. Gauge + atm."),
        'le_PinB': (
            "<b>Fluid B inlet absolute pressure <i>P<sub>in,B</sub></i></b> "
            "[Pa]"),
        'le_Nx': (
            "<b>Grid count along <i>x</i></b><br/>"
            "3D refinement adds +8 cells per wall on each axis."),
        'le_Ny': "<b>Grid count along <i>y</i></b>",
        'le_Nz': (
            "<b>Grid count along <i>z</i></b> (3D only)<br/>"
            "Wall-refine multiplies actual cells; keep modest for interactive runs."),
    }

    def _install_field_help(self):
        """Attach rich HTML tooltips to physics inputs. Tooltips include the
        symbol, units, typical range, and any surrogate-training caveats —
        the things the user can't derive from the UI label alone.
        """
        for attr, html in self._FIELD_HELP.items():
            le = getattr(self, attr, None)
            if le is None:
                continue
            try:
                le.setToolTip(html)
            except Exception:
                pass

    def _install_status_log(self):
        """Capture every statusBar().showMessage into a rolling log and add a
        collapsible ▲ toggle on the right edge so users can review messages
        they missed during a long compute.

        Zero-touch for existing callers: QStatusBar emits `messageChanged`
        when showMessage is used, so we just listen for it.
        """
        from collections import deque
        from datetime import datetime
        from PySide6.QtWidgets import QPushButton
        self._log_history = deque(maxlen=50)

        def _on_msg(txt):
            if not txt:
                return
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_history.append(f"[{ts}] {txt}")

        self.statusBar().messageChanged.connect(_on_msg)

        btn = QPushButton("▲  Log")
        btn.setFixedHeight(18)
        btn.setFixedWidth(70)
        btn.setStyleSheet(
            "QPushButton{background:transparent; border:none;"
            f"color:{get_theme().get('sub_fg', '#888')}; font-size:8pt;"
            "padding:0 6px;}"
            "QPushButton:hover{color:" + get_theme()['fg'] + ";}")
        btn.setToolTip("Show recent status messages")
        btn.clicked.connect(self._show_status_log)
        self.statusBar().addPermanentWidget(btn)
        self._btn_status_log = btn

    def _show_status_log(self):
        """Pop up the last 50 status-bar messages in a read-only dialog."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QPlainTextEdit,
                                        QDialogButtonBox)
        dlg = QDialog(self)
        dlg.setWindowTitle("Status Log")
        dlg.resize(640, 380)
        lay = QVBoxLayout(dlg)
        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setStyleSheet(
            f"QPlainTextEdit{{background:{get_theme()['inp_bg']};"
            f"color:{get_theme()['inp_fg']};"
            f"border:1px solid {get_theme()['card_border']};"
            "font-family:'Fira Code', 'Consolas', monospace; font-size:9pt;}}")
        lines = list(getattr(self, '_log_history', []))
        txt.setPlainText("\n".join(lines) if lines
                         else "(no status messages yet)")
        lay.addWidget(txt)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        btns.button(QDialogButtonBox.StandardButton.Close).clicked.connect(
            dlg.accept)
        lay.addWidget(btns)
        dlg.exec()

    def _attach_input_validators(self):
        """Wire blur-time numeric validation on the main input fields.

        Fields fall into three groups: strictly-positive (L, H, Lcell, t, ks,
        u, T, P, Nx/Ny/Nz); non-negative (init temps); and free-form ("auto"
        accepted, e.g. mesh_density). Anything that fails float() or breaches
        its sign rule flips the `inpError` property — the `_INP` stylesheet
        paints a red border until the user corrects.
        """
        positive = [
            'le_L', 'le_H', 'le_Lz', 'le_Lcell', 'le_t', 'le_ks',
            'le_uA', 'le_uB',
            'le_TinA', 'le_TinB', 'le_PinA', 'le_PinB',
            'le_Nx', 'le_Ny', 'le_Nz',
            'le_rho_s',
        ]
        def _validator(le, strict_positive=True):
            # Preserve the field's baseline tooltip so we can restore it when
            # the value returns to valid — prevents leaking the error text
            # into a healthy field.
            base_tip = le.toolTip() or ""
            def _on_blur():
                txt = le.text().strip()
                bad = False
                reason = ""
                try:
                    v = float(txt)
                    if strict_positive and v <= 0:
                        bad = True
                        reason = "Must be > 0"
                except Exception:
                    bad = True
                    reason = "Must be a number"
                current = le.property('inpError')
                new = 'true' if bad else 'false'
                if current != new:
                    le.setProperty('inpError', new)
                    le.style().unpolish(le); le.style().polish(le)
                # Non-color error indication (a11y): tooltip carries the
                # reason, status bar flashes a warning icon + message.
                if bad:
                    le.setToolTip(f"⚠ {reason}"
                                  + (f"\n{base_tip}" if base_tip else ""))
                    self.statusBar().showMessage(
                        f"⚠  Invalid input: {le.objectName() or 'field'} — {reason}",
                        4000)
                else:
                    le.setToolTip(base_tip)
            return _on_blur
        for name in positive:
            le = getattr(self, name, None)
            if le is not None:
                cb = _validator(le, strict_positive=True)
                le.editingFinished.connect(cb)

    # Native unit each input field expects, used by the inline unit parser
    # below. Family keys: length (→ m or mm), pressure (→ Pa), speed (→ m/s),
    # temp (→ K or °C — honours current _temp_unit), count (reject units).
    _FIELD_UNITS = {
        # geometry — metres
        'le_L': ('length', 'm'), 'le_H': ('length', 'm'),
        'le_Lz': ('length', 'm'),
        'le_pipeA_in_ctr': ('length', 'm'), 'le_pipeA_in_w':  ('length', 'm'),
        'le_pipeA_out_ctr':('length', 'm'), 'le_pipeA_out_w': ('length', 'm'),
        'le_pipeB_in_ctr': ('length', 'm'), 'le_pipeB_in_w':  ('length', 'm'),
        'le_pipeB_out_ctr':('length', 'm'), 'le_pipeB_out_w': ('length', 'm'),
        # TPMS geometry — millimetres
        'le_Lcell': ('length', 'mm'), 'le_t': ('length', 'mm'),
        # flow / thermo
        'le_uA': ('speed', 'm/s'), 'le_uB': ('speed', 'm/s'),
        'le_PinA': ('pressure', 'Pa'), 'le_PinB': ('pressure', 'Pa'),
        'le_TinA': ('temp', None), 'le_TinB': ('temp', None),
        # counts (no unit allowed)
        'le_Nx': ('count', None), 'le_Ny': ('count', None),
        'le_Nz': ('count', None), 'le_mesh_density': ('count', None),
    }

    _UNIT_LENGTH = {
        'm': 1.0, 'cm': 1e-2, 'mm': 1e-3, 'μm': 1e-6, 'um': 1e-6,
        'in': 0.0254, 'inch': 0.0254, 'ft': 0.3048,
    }
    _UNIT_PRESSURE = {
        'pa': 1.0, 'kpa': 1e3, 'mpa': 1e6, 'bar': 1e5, 'mbar': 1e2,
        'psi': 6894.757, 'atm': 101325.0, 'torr': 133.322, 'mmhg': 133.322,
    }
    _UNIT_SPEED = {
        'm/s': 1.0, 'cm/s': 1e-2, 'mm/s': 1e-3,
        'km/h': 1.0 / 3.6, 'kph': 1.0 / 3.6,
        'mph': 0.44704, 'ft/s': 0.3048,
    }

    def _install_inline_unit_parser(self):
        """On editingFinished, scan each field for a trailing unit token
        ("150 mm", "5 bar", "148.9 °C"). If the token matches a known
        family for that field, convert to the field's native unit and
        rewrite the text — the validator then sees the canonical number
        and the rest of the app stays unit-naive.
        """
        import re as _re_up
        num_unit = _re_up.compile(
            r"\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*"
            r"([A-Za-zμΜ°/··]+[A-Za-z0-9/··]*)\s*$")

        def _convert(family, target_unit, val, unit_txt):
            u = unit_txt.strip().lower().replace('·', '').replace('·', '')
            if family == 'length':
                if u in self._UNIT_LENGTH:
                    si = val * self._UNIT_LENGTH[u]
                    return si / self._UNIT_LENGTH[target_unit]
            elif family == 'pressure':
                if u in self._UNIT_PRESSURE:
                    si = val * self._UNIT_PRESSURE[u]
                    return si / self._UNIT_PRESSURE.get(
                        (target_unit or 'pa').lower(), 1.0)
            elif family == 'speed':
                if u in self._UNIT_SPEED:
                    si = val * self._UNIT_SPEED[u]
                    return si / self._UNIT_SPEED[target_unit]
            elif family == 'temp':
                # Target unit follows the current display toggle (_temp_unit).
                want_K = getattr(self, '_temp_unit', 'K') == 'K'
                if u in ('k', 'kelvin'):
                    return val if want_K else val - 273.15
                if u in ('c', '°c', 'celsius', 'degc'):
                    return val + 273.15 if want_K else val
                if u in ('f', '°f', 'fahrenheit', 'degf'):
                    K = (val - 32.0) * 5.0 / 9.0 + 273.15
                    return K if want_K else K - 273.15
            elif family == 'count':
                # Counts don't take units; strip the unit if it's "cells".
                if u in ('cells', 'cell', 'pts', 'points', 'nodes'):
                    return val
            return None

        def _on_commit(le=None, fam=None, target=None):
            def _cb():
                txt = le.text().strip()
                if not txt:
                    return
                # Try float-with-unit first; bare numbers fall through.
                m = num_unit.match(txt)
                if not m:
                    return
                raw = m.group(1)
                unit_txt = m.group(2)
                try:
                    raw_val = float(raw)
                except ValueError:
                    return
                new_val = _convert(fam, target, raw_val, unit_txt)
                if new_val is None:
                    return
                # Pretty format: drop trailing zeros for tiny/normal values.
                if fam == 'count':
                    fmt = f"{int(round(new_val))}"
                elif abs(new_val) >= 1000 or abs(new_val) < 0.01:
                    fmt = f"{new_val:.6g}"
                else:
                    fmt = f"{new_val:.4g}"
                # Avoid an endless loop by suppressing our own signal fire.
                was = le.blockSignals(True)
                le.setText(fmt)
                le.blockSignals(was)
                self.statusBar().showMessage(
                    f"Converted {raw} {unit_txt} → {fmt} "
                    f"({target or fam})", 4000)
            return _cb

        for attr, (fam, target) in self._FIELD_UNITS.items():
            le = getattr(self, attr, None)
            if le is None:
                continue
            le.editingFinished.connect(_on_commit(le, fam, target))

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
            self._btn_compute_text_saved = self.btn_compute.text()
            eta = self._compute_eta_for_active_mode()
            self.btn_compute.setText(
                f"Cancel  (Computing… ETA ~{eta})" if eta else "Cancel  (Computing…)")
            self.btn_compute.setEnabled(True)
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

    def _compute_eta_for_active_mode(self):
        """Return a human-readable ETA string ('12s', '2m05s') derived from
        the median of the most recent successful runs in the same mode.
        Returns '' when no history is available yet."""
        import statistics as _stat
        from ui.fmt import duration as _fmt_dur
        mode = self._active_compute_mode()
        hist = getattr(self, '_compute_times', {}).get(mode)
        if not hist:
            return ''
        try:
            med = _stat.median(hist)
        except Exception:
            return ''
        return _fmt_dur(med)

    def _record_compute_elapsed(self, elapsed, mode=None):
        """Push `elapsed` (seconds) into the mode-specific history ring so
        future clicks surface a usable ETA. Bounded maxlen keeps the median
        responsive to the current workload rather than permanently anchored
        to an old baseline."""
        import collections as _col
        if mode is None:
            mode = self._active_compute_mode()
        hist = getattr(self, '_compute_times', None)
        if hist is None:
            hist = self._compute_times = {
                '2d': _col.deque(maxlen=7),
                '3d': _col.deque(maxlen=5),
                'poly': _col.deque(maxlen=5),
            }
        hist.setdefault(mode, _col.deque(maxlen=7))
        hist[mode].append(float(elapsed))
        # Refresh the button tooltip so a pre-compute hover shows the
        # predicted duration without waiting for the next click.
        if hasattr(self, 'btn_compute'):
            eta = self._compute_eta_for_active_mode()
            if eta:
                self.btn_compute.setToolTip(
                    f"Run single-point compute (Ctrl+R) — ETA ~{eta} "
                    f"based on median of {len(hist[mode])} recent "
                    f"{mode.upper()} runs")

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
        self._result_summary_bar.setVisible(shown_any)

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

    def _on_cancel_compute(self):
        """User clicked the Compute button while a solve was running, so it
        is currently labelled "Cancel". Set the flag the worker polls; the
        button stays disabled until the worker reaches the next checkpoint
        and returns through `_check`."""
        self._compute_cancel = True
        if hasattr(self, 'btn_compute'):
            self.btn_compute.setEnabled(False)
            self.btn_compute.setText("Cancelling…")
        self.statusBar().showMessage(
            "Cancel requested — waiting for solver to finish current sweep…",
            6000)

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
            # Record the elapsed wall-clock so future clicks can surface
            # an ETA next to the Compute button.
            import time as _t_end
            t0 = getattr(self, '_compute_t0', None)
            elapsed = None
            if t0 is not None:
                elapsed = _t_end.time() - t0
                self._record_compute_elapsed(elapsed)
            self._refresh_status_bar()
            try:
                from ui.ui_builders import refresh_workflow_breadcrumb
                refresh_workflow_breadcrumb(self)
            except Exception:
                pass
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
                    if elapsed < 60:
                        dur = f"{elapsed:.1f}s"
                    else:
                        dur = f"{int(elapsed // 60)}m{int(elapsed % 60):02d}s"
                    toast(self, f"Compute done · {dur}", kind='success')
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

    # -------------------------------------------------------------------
    # ComputeOrchestrator signal handlers (Plan #4 Phase 1.2 — A.2 wiring).
    # Replace the raw threading.Thread + QTimer poll pattern in
    # run_calculation. orchestrator's signals auto-marshal to the GUI thread,
    # so these handlers run on the main thread (Qt-safe).
    # -------------------------------------------------------------------

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

        mode = self.compute.current_mode()
        if mode == '3d':
            from runs.run_calculation_3d import finalize_plots_3d
            _finalize_ok = False
            try:
                finalize_plots_3d(self)
                try:
                    self._push_recent_run()
                except Exception:
                    pass
                _finalize_ok = True
            finally:
                self._end_compute_ui(success=_finalize_ok)
            if not _finalize_ok:
                return
            self._has_results = True
            self._has_results_3d = True
            for _bname in ('btn_export_results', 'btn_export_figure'):
                if hasattr(self, _bname):
                    getattr(self, _bname).setEnabled(True)
            drawn = getattr(self, '_drawn_tabs', set())
            drawn.add('3d')
            if getattr(self, '_rendered_3d_slices', False):
                for k in ('temp', 'pres', 'vel'):
                    drawn.add(k)
            self._drawn_tabs = drawn
            self._update_tab_visibility()
            self._switch_tab('3d')
            res = getattr(self, '_result_3d', {})
            if res:
                try:
                    self.statusBar().showMessage(
                        f"3D done — Q={res.get('Q', 0):.1f} W  "
                        f"dP={res.get('dP', 0):.0f} Pa", 6000)
                except Exception:
                    pass
            return

        # 2D mode (default)
        self._finalize_plots()
        self._end_compute_ui(success=True)
        self._has_results = True
        self._has_results_2d = True
        self._update_tab_visibility()
        for _bname in ('btn_export_results', 'btn_export_figure'):
            if hasattr(self, _bname):
                getattr(self, _bname).setEnabled(True)
        self._switch_tab('temp')
        self.statusBar().showMessage("Done.", 5000)

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
            for _bname in ('btn_export_results', 'btn_export_figure'):
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
        for _bname in ('btn_export_results', 'btn_export_figure'):
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
        self.statusBar().showMessage("Cancelled.", 3000)

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
        # Mark the compute start so `_end_compute_ui` can push the wall
        # clock into the ETA history ring. Set regardless of 2D/3D/poly
        # branch — the 3D branch overwrites this with its own clock anyway.
        import time as _t_run
        self._compute_t0 = _t_run.time()
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

        # Worker function for orchestrator. Wraps run_calculation_inner so
        # solver runs on the QRunnable thread; result lands in
        # window._compute_results (existing convention, finalize_plots reads
        # from there). Cancel token is parked on `self` so future solver
        # kernels can poll it at epoch boundaries (cooperative cancel).
        def _2d_worker(cfg, cancel_token, progress_cb):
            self._cancel_token = cancel_token
            from runs.run_calculation import run_calculation_inner
            run_calculation_inner(self)
            # Result already on self._compute_results; orchestrator's finished
            # signal payload can be empty.
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

    def _run_calculation_inner(self):
        """Thin wrapper — delegates to run_calculation module (Task B.9)."""
        from runs.run_calculation import run_calculation_inner
        return run_calculation_inner(self)

    def _finalize_plots(self):
        """Thin wrapper — delegates to run_calculation module (Task B.9).
        Freezes repaints around the multi-canvas population so the user
        sees one clean frame flip instead of five intermediate paints."""
        from runs.run_calculation import finalize_plots
        self.setUpdatesEnabled(False)
        try:
            out = finalize_plots(self)
        finally:
            self.setUpdatesEnabled(True)
        self._push_recent_run()
        return out

    _MAX_RECENT_RUNS = 5

    def _push_recent_run(self):
        """Record the current field snapshot + headline numbers in a bounded
        ring buffer. The header "Recent ▾" menu reads from this so users can
        jump back to an earlier parameter set without hunting through undo.
        """
        import datetime as _dt, collections as _col
        if not hasattr(self, '_recent_runs'):
            self._recent_runs = _col.deque(maxlen=self._MAX_RECENT_RUNS)
        try:
            Q = self._r_Q.text() if hasattr(self, '_r_Q') else '—'
            dP_A = self._r_dP_A.text() if hasattr(self, '_r_dP_A') else '—'
            dP_B = self._r_dP_B.text() if hasattr(self, '_r_dP_B') else '—'
        except Exception:
            Q = dP_A = dP_B = '—'
        snap = self._capture_current_preset(
            f"Recent @ {_dt.datetime.now().strftime('%H:%M:%S')}")
        # Grab T_out values too — delta-capable metrics read from the same
        # entry shape, so store every headline number here with a stable
        # key name (`Q`, `dP_A`, `dP_B`, `ToutA`, `ToutB`).
        try:
            ToutA = self._r_ToutA.text() if hasattr(self, '_r_ToutA') else '—'
        except Exception:
            ToutA = '—'
        try:
            ToutB = self._r_ToutB.text() if hasattr(self, '_r_ToutB') else '—'
        except Exception:
            ToutB = '—'
        entry = {
            'ts': _dt.datetime.now().isoformat(timespec='seconds'),
            'label': _dt.datetime.now().strftime('%H:%M:%S'),
            'Q': Q, 'dP_A': dP_A, 'dP_B': dP_B,
            'ToutA': ToutA, 'ToutB': ToutB,
            'preset': snap,
        }
        self._recent_runs.appendleft(entry)
        # E15 — append the full entry (minus the preset payload, which is
        # large) to a persistent JSONL so the history dialog can surface
        # the entire research-session log, not just the last 5.
        try:
            import os as _os_tl, json as _j_tl
            path = _os_tl.path.join(
                _os_tl.path.dirname(_os_tl.path.abspath(__file__)),
                '.session_timeline.jsonl')
            slim = {k: v for k, v in entry.items() if k != 'preset'}
            with open(path, 'a', encoding='utf-8') as f:
                f.write(_j_tl.dumps(slim) + '\n')
        except Exception:
            pass
        # Rebuild header menu if the button exists — keeps chip order fresh
        # after every successful finalize.
        if hasattr(self, 'btn_recent'):
            self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        """Populate the Recent ▾ header menu with up to N entries."""
        from PySide6.QtWidgets import QMenu
        if not hasattr(self, 'btn_recent'):
            return
        menu = QMenu(self)
        entries = getattr(self, '_recent_runs', None) or []
        if not entries:
            empty = menu.addAction("(no recent runs)")
            empty.setEnabled(False)
        else:
            for i, e in enumerate(entries):
                label = (f"#{i+1}  {e['label']}   "
                         f"Q={e['Q']} · ΔP(A)={e['dP_A']}")
                act = menu.addAction(label)
                act.triggered.connect(
                    lambda _checked=False, entry=e: self._load_recent_run(entry))
            menu.addSeparator()
            if len(entries) >= 2:
                diff = menu.addAction("Compare last 2 runs…")
                diff.triggered.connect(self._open_run_diff)
            clr = menu.addAction("Clear recent")
            clr.triggered.connect(self._clear_recent_runs)
        self.btn_recent.setMenu(menu)

    def _load_recent_run(self, entry):
        """Restore inputs from a recent-run snapshot and optionally recompute.
        Current behaviour: load inputs, flash status; user hits Compute to
        re-run (same pattern as preset load)."""
        try:
            self._apply_user_preset(entry.get('preset') or {})
            self.statusBar().showMessage(
                f"Restored run from {entry.get('ts', '?')}.", 5000)
        except Exception as e:
            QMessageBox.warning(
                self, "Recent load failed", str(e))

    def _open_run_diff(self):
        """Open the Compare-runs dialog for the two most recent entries."""
        from ui.run_diff import open_diff_of_recent
        open_diff_of_recent(self)

    def _show_overview(self):
        """Open the D7 overview dashboard dialog."""
        from ui.overview import open_overview
        open_overview(self)

    def _show_test_info(self):
        """Static info about the project's test suite. The count on the
        status-bar badge is hand-maintained; this dialog surfaces the file
        list for users curious about coverage."""
        import os as _os_ti
        tests_dir = _os_ti.path.join(
            _os_ti.path.dirname(_os_ti.path.abspath(__file__)), 'tests')
        files = []
        try:
            for f in sorted(_os_ti.listdir(tests_dir)):
                if f.startswith('test_') and f.endswith('.py'):
                    files.append(f)
        except Exception:
            pass
        lines = [f"<b>{len(files)} test modules</b>", ""]
        for f in files:
            lines.append(f"<code>{f}</code>")
        lines.append("")
        lines.append("Run locally:")
        lines.append(
            "<code>QT_QPA_PLATFORM=offscreen pytest tests/ -q</code>")
        msg = QMessageBox(self)
        msg.setWindowTitle("Test suite")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText("<br>".join(lines))
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _show_solve_log(self):
        """Modal text viewer for the last captured solver stdout."""
        text = getattr(self, '_last_solve_log', None) or ""
        if not text.strip():
            QMessageBox.information(
                self, "Solve log",
                "No solve log captured yet — run Compute first.")
            return
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QPlainTextEdit, QPushButton, QHBoxLayout)
        dlg = QDialog(self)
        dlg.setWindowTitle("Solve log — SIMPLE / coupling output")
        dlg.resize(820, 640)
        v = QVBoxLayout(dlg)
        edit = QPlainTextEdit(text)
        edit.setReadOnly(True)
        from ui.theme import get_theme as _gt_sl
        _tsl = _gt_sl()
        edit.setStyleSheet(
            f"QPlainTextEdit{{background:{_tsl.get('surface_raised', _tsl['card_bg'])};"
            f"color:{_tsl['fg']}; border:1px solid {_tsl['card_border']};"
            f"font-family:'Fira Code','Consolas',monospace; font-size:10pt;"
            "padding:8px;}}")
        v.addWidget(edit, 1)
        btn_row = QHBoxLayout(); btn_row.addStretch(1)
        btn_copy = QPushButton("Copy all")
        btn_copy.clicked.connect(
            lambda: (QApplication.clipboard().setText(text),
                     self.statusBar().showMessage(
                         "Log copied to clipboard.", 3000)))
        btn_close = QPushButton("Close"); btn_close.clicked.connect(dlg.accept)
        btn_copy.setStyleSheet(_BTN_TERTIARY)
        btn_close.setStyleSheet(_BTN_SECONDARY)
        btn_row.addWidget(btn_copy); btn_row.addWidget(btn_close)
        v.addLayout(btn_row)
        dlg.exec()

    def _show_full_timeline(self):
        """E15 — viewer for the persistent .session_timeline.jsonl log."""
        import os as _os_tv, json as _j_tv
        path = _os_tv.path.join(
            _os_tv.path.dirname(_os_tv.path.abspath(__file__)),
            '.session_timeline.jsonl')
        entries = []
        if _os_tv.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entries.append(_j_tv.loads(line))
                        except Exception:
                            continue
            except Exception:
                pass
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
            QHeaderView, QHBoxLayout, QPushButton)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Session timeline — {len(entries)} runs")
        dlg.resize(760, 520)
        v = QVBoxLayout(dlg)
        table = QTableWidget(len(entries), 4)
        table.setHorizontalHeaderLabels(
            ["Timestamp", "Q [W/m]", "ΔP_A [Pa]", "ΔP_B [Pa]"])
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        for r, e in enumerate(reversed(entries)):
            table.setItem(r, 0, QTableWidgetItem(str(e.get('ts', '—'))))
            table.setItem(r, 1, QTableWidgetItem(str(e.get('Q', '—'))))
            table.setItem(r, 2, QTableWidgetItem(str(e.get('dP_A', '—'))))
            table.setItem(r, 3, QTableWidgetItem(str(e.get('dP_B', '—'))))
        v.addWidget(table)
        btn_row = QHBoxLayout(); btn_row.addStretch(1)
        btn_clear = QPushButton("Clear timeline")
        btn_close = QPushButton("Close")
        btn_clear.setStyleSheet(_BTN_TERTIARY)
        btn_close.setStyleSheet(_BTN_SECONDARY)
        def _clear():
            try:
                if _os_tv.path.exists(path):
                    _os_tv.remove(path)
            except Exception:
                pass
            dlg.accept()
            self.statusBar().showMessage("Timeline cleared.", 3000)
        btn_clear.clicked.connect(_clear)
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_clear); btn_row.addWidget(btn_close)
        v.addLayout(btn_row)
        dlg.exec()

    def _copy_reproducible_link(self):
        """E14 — encode current inputs as a compact base64 string and copy
        to clipboard. Paste-able into another TPMSHX window via
        `Load reproducible link…` palette action."""
        import base64 as _b64_rl, json as _j_rl, zlib as _z_rl
        preset = self._capture_current_preset("Repro link")
        blob = _j_rl.dumps(preset, separators=(',', ':')).encode('utf-8')
        compressed = _z_rl.compress(blob, level=9)
        b64 = _b64_rl.urlsafe_b64encode(compressed).decode('ascii').rstrip('=')
        token = f"TPMSHX::{b64}"
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(token)
        self.statusBar().showMessage(
            f"Reproducible link copied ({len(token)} chars).", 5000)

    def _load_reproducible_link(self):
        """Inverse of `_copy_reproducible_link` — decode + apply a token
        fetched via QInputDialog."""
        from PySide6.QtWidgets import QInputDialog
        txt, ok = QInputDialog.getText(
            self, "Load reproducible link",
            "Paste a TPMSHX::... token:")
        if not ok or not txt.strip():
            return
        token = txt.strip()
        if not token.startswith("TPMSHX::"):
            QMessageBox.warning(self, "Bad token", "Expected TPMSHX:: prefix.")
            return
        try:
            import base64 as _b64_rl, json as _j_rl, zlib as _z_rl
            payload = token[len("TPMSHX::"):]
            # Restore stripped base64 padding.
            pad = '=' * (-len(payload) % 4)
            compressed = _b64_rl.urlsafe_b64decode(payload + pad)
            preset = _j_rl.loads(_z_rl.decompress(compressed))
            self._apply_user_preset(preset)
            self.statusBar().showMessage(
                "Reproducible link loaded. Click Compute to run.", 5000)
        except Exception as e:
            QMessageBox.warning(self, "Load failed", str(e))

    def _stamp_result_provenance(self, elapsed):
        """Tooltip every result label with 'computed @ HH:MM:SS · 8.4s ·
        grid 30×20×5 · commit 720ba8c' so a glance explains the number."""
        import datetime as _dt_pv
        ts = _dt_pv.datetime.now().strftime('%H:%M:%S')
        commit = _git_commit_hash()
        try:
            nx = self.le_Nx.text(); ny = self.le_Ny.text()
            nz = self.le_Nz.text() if self.combo_dim.currentIndex() == 1 else None
            grid = f"{nx}×{ny}" + (f"×{nz}" if nz else "")
        except Exception:
            grid = "?"
        if elapsed < 60:
            dur = f"{elapsed:.1f}s"
        else:
            dur = f"{int(elapsed // 60)}m{int(elapsed % 60):02d}s"
        preset = getattr(self, '_active_preset_name', '—') or '—'
        tip = (f"Computed @ {ts}  ·  {dur}  ·  grid {grid}  "
                f"·  preset: {preset}"
                + (f"  ·  commit: {commit}" if commit else ""))
        for attr in ('_r_Q', '_r_dP_A', '_r_dP_B',
                      '_r_ToutA', '_r_ToutB'):
            lbl = getattr(self, attr, None)
            if lbl is not None:
                try: lbl.setToolTip(tip)
                except Exception: pass

    def _copy_inputs_as_python(self):
        """Serialise the current left-panel inputs as a runnable Python
        snippet: a `cfg = {...}` dict plus a `run_calculation_inner(cfg)`
        call. Copied to the system clipboard for pasting into Jupyter or
        reproducibility bundles."""
        lines = ["# Generated by SJTU-TPMSHX — reproducible input bundle"]
        commit = _git_commit_hash()
        if commit:
            lines.append(f"# commit: {commit}")
        import datetime as _dt_cp
        lines.append(f"# exported: {_dt_cp.datetime.now().isoformat(timespec='seconds')}")
        lines.append("")
        lines.append("cfg = {")
        for attr in self._SESSION_LINE_EDITS:
            le = getattr(self, attr, None)
            if le is None:
                continue
            try:
                v = le.text().strip()
            except Exception:
                continue
            if not v:
                continue
            lines.append(f"    {attr!r}: {v!r},")
        lines.append("    # combos")
        for attr in self._SESSION_COMBOS:
            cb = getattr(self, attr, None)
            if cb is None:
                continue
            try:
                lines.append(f"    {attr!r}: {int(cb.currentIndex())},"
                              f"  # {cb.currentText()!r}")
            except Exception:
                continue
        for attr in self._SESSION_CHECKS:
            cbx = getattr(self, attr, None)
            if cbx is None:
                continue
            try:
                lines.append(f"    {attr!r}: {bool(cbx.isChecked())!r},")
            except Exception:
                continue
        lines.append("}")
        lines.append("")
        lines.append("# Apply to a running SJTU-TPMSHX window:")
        lines.append("# window._apply_user_preset({'line_edits': {k: v for k, v in cfg.items()"
                      " if k.startswith('le_')}})")
        text = "\n".join(lines)
        from PySide6.QtWidgets import QApplication as _QApp
        _QApp.clipboard().setText(text)
        self.statusBar().showMessage(
            "Copied current inputs as Python snippet to clipboard.", 5000)

    def _clear_recent_runs(self):
        if hasattr(self, '_recent_runs'):
            self._recent_runs.clear()
        self._rebuild_recent_menu()
        self.statusBar().showMessage("Recent runs cleared.", 3000)

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

        # Large-grid warning (wall-refine expands cells ~6-9x)
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
            return
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

        import time as _time
        self._compute_t0 = _time.time()
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
        est_cells_r = Nx_r * Ny_r * Nz_r
        self._begin_compute_ui(
            status=f"Computing 3D ({_cell_label} = "
                   f"{est_cells_r:,} cells, compressible dual-fluid SIMPLE; "
                   f"typical ~2-10 min)…")

        # ComputeOrchestrator path (Plan #4 P1.3 — A.3, 2026-05-06).
        # Replaces the legacy threading.Thread + 600 s poll _check closure.
        # Hard wall-clock budget (10 min) implemented as a separate QTimer
        # that calls self.compute.cancel() — orchestrator forwards as
        # cooperative cancel to the worker, which exits at next checkpoint.
        from PySide6.QtCore import QTimer

        def _3d_worker(cfg, cancel_token, progress_cb):
            self._cancel_token = cancel_token
            from runs.run_calculation_3d import run_calculation_3d_inner
            run_calculation_3d_inner(self)
            return {}

        self._compute_error = None
        if not self.compute.start('3d', _3d_worker, cfg={'est_cells': est_cells_r}):
            QMessageBox.information(
                self, "Compute Busy",
                "3D compute orchestrator rejected start — already running.")
            return

        # ETA / status updater on a separate QTimer (orchestrator handles
        # the thread; this is a UI-only ticker that polls solver progress
        # + reports elapsed wall-clock + ETA).
        wd = QTimer(self)
        self._compute_3d_watchdog = wd
        _hard_timeout_s = 600.0
        _ref_cells = 35000
        _ref_sec = 150.0

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
            eta_total = max(10.0, est_cells_r / _ref_cells * _ref_sec)
            eta_remain = eta_total - elapsed
            from ui.fmt import duration as _fmt
            if eta_remain > 0:
                eta_txt = f"ETA ~{_fmt(eta_remain)}"
            else:
                over = elapsed - eta_total
                eta_txt = f"past estimate by {_fmt(over)} — solver still running"
            self.statusBar().showMessage(
                f"Computing 3D… {_fmt(elapsed)} elapsed "
                f"({est_cells_r:,} cells) • {eta_txt}")
        wd.timeout.connect(_tick_3d)
        wd.start(500)
        return

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
        kw_s = dict(levels=100, cmap="turbo",
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
        """Export a chosen figure to PNG/SVG/PDF with user-selected DPI
        and embedded reproducibility metadata (preset, commit, timestamp,
        grid). Pops a 2-step picker: figure → format/DPI → save path."""
        all_items = [("Temperature", 'temp'), ("Pressure", 'pres'),
                     ("Velocity", 'vel'), ("Geometry", 'layout'),
                     ("Pareto / Optimize", 'pareto')]
        tab_canvas = {'temp': self.canvas_temp, 'pres': self.canvas_pres,
                      'vel': self.canvas_vel, 'layout': self.canvas_layout,
                      'pareto': self.canvas_pareto}
        drawn = getattr(self, '_drawn_tabs', set())
        items = [name for name, key in all_items if key in drawn]
        tab_keys = [key for name, key in all_items if key in drawn]
        if not items:
            self.statusBar().showMessage("No figures to export yet.", 3000)
            return
        choice, ok = QInputDialog.getItem(
            self, "Export Figure", "Select figure to export:",
            items, 0, False)
        if not ok:
            return
        key = tab_keys[items.index(choice)]
        canvas = tab_canvas[key]

        # DPI picker — common research-paper presets.
        dpi_items = ["150 (screen)", "300 (print)",
                     "450 (publication)", "600 (poster)"]
        dpi_choice, ok2 = QInputDialog.getItem(
            self, "Resolution", "DPI:", dpi_items, 1, False)
        if not ok2:
            return
        dpi = int(dpi_choice.split()[0])

        default = f"SJTU-TPMSHX_{key}_{dpi}dpi.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Figure", default,
            "PNG (*.png);;SVG (*.svg);;PDF (*.pdf);;All Files (*)")
        if not path:
            return
        try:
            # Build reproducibility metadata embedded in PNG tEXt / PDF
            # keywords. Matplotlib respects this via savefig's `metadata`
            # kwarg.
            import datetime as _dt_ef
            meta = {
                'Title': f"SJTU-TPMSHX {key}",
                'Author': 'alexlu997',
                'Software': f"SJTU-TPMSHX v{__version__}",
                'CreationDate': _dt_ef.datetime.now().isoformat(timespec='seconds'),
                'Source': 'github.com/alexlu997/SJTU-TPMSHX',
            }
            commit = _git_commit_hash()
            if commit:
                meta['Keywords'] = f"commit={commit}"
            preset = getattr(self, '_active_preset_name', None)
            if preset:
                meta['Subject'] = f"Preset: {preset}"

            ext = path.lower().rsplit('.', 1)[-1] if '.' in path else 'png'
            save_kwargs = dict(dpi=dpi, bbox_inches='tight',
                                facecolor=canvas.fig.get_facecolor())
            if ext in ('png', 'pdf'):
                save_kwargs['metadata'] = meta
            canvas.fig.savefig(path, **save_kwargs)
            self.statusBar().showMessage(
                f"Exported {dpi} DPI → {path}", 6000)
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))


# ── Entry point ───────────────────────────────────────────────
def _apply_app_font(app):
    """Pick Fira Sans > Inter > Segoe UI for labels, Fira Code for numbers."""
    from PySide6.QtGui import QFont, QFontDatabase
    candidates = [
        "Fira Sans", "Inter", "Inter Display",
        "Segoe UI", "Segoe UI Variable",
        "Roboto", "Helvetica Neue", "Arial",
    ]
    families = set(QFontDatabase.families())
    chosen = next((n for n in candidates if n in families), None)
    if chosen is None:
        print("[font] no sans-serif candidate found; system default")
        return None
    app.setFont(QFont(chosen, 10))
    mono = next((n for n in ["Fira Code", "JetBrains Mono", "Consolas", "Courier New"]
                 if n in families), None)
    if mono:
        app._mono_font_family = mono
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

    # ── i18n translator install (scaffolding) ──────────────────
    # Loads `i18n/sjtu_tpmshx_<locale>.qm` if present — e.g.
    # `i18n/sjtu_tpmshx_zh_CN.qm`. Produce .qm files with:
    #   pylupdate6 main.py ui/*.py -ts i18n/sjtu_tpmshx_zh_CN.ts
    #   lrelease   i18n/sjtu_tpmshx_zh_CN.ts
    # All user-visible strings are expected to be wrapped with `self.tr("…")`
    # (QObject.tr) or `QApplication.translate("ctx", "…")`. The current
    # codebase is English-only; this block lays the groundwork for a
    # contributor to add translations without further code changes.
    from PySide6.QtCore import QLocale, QTranslator
    import os as _os_i18n
    _i18n_dir = _os_i18n.path.join(
        _os_i18n.path.dirname(_os_i18n.path.abspath(__file__)), 'i18n')
    _translator = QTranslator()
    _loc = QLocale.system().name()  # e.g. "zh_CN", "en_US"
    _candidates = [f"sjtu_tpmshx_{_loc}.qm",
                   f"sjtu_tpmshx_{_loc.split('_')[0]}.qm"]
    for _qm in _candidates:
        _qm_path = _os_i18n.path.join(_i18n_dir, _qm)
        if _os_i18n.path.exists(_qm_path) and _translator.load(_qm_path):
            app.installTranslator(_translator)
            print(f"[i18n] loaded {_qm}")
            break

    # Load persisted theme choice (from a previous `_toggle_theme`) before
    # styles rebuild — falls back to the hard-coded default if absent.
    import os as _os_boot
    _theme_file = _os_boot.path.join(
        _os_boot.path.dirname(_os_boot.path.abspath(__file__)), '.theme')
    if _os_boot.path.exists(_theme_file):
        try:
            with open(_theme_file, 'r', encoding='utf-8') as _fth:
                _saved_theme = _fth.read().strip()
            if _saved_theme in ('dark', 'light'):
                set_theme(_saved_theme)
        except Exception:
            pass
    # Density persistence — same pattern as theme.
    _density_file = _os_boot.path.join(
        _os_boot.path.dirname(_os_boot.path.abspath(__file__)), '.density')
    if _os_boot.path.exists(_density_file):
        try:
            with open(_density_file, 'r', encoding='utf-8') as _fd:
                _saved_density = _fd.read().strip()
            if _saved_density in ('compact', 'cozy', 'comfortable'):
                set_density(_saved_density)
        except Exception:
            pass
    # Accent override — E13 custom brand colour.
    _accent_file = _os_boot.path.join(
        _os_boot.path.dirname(_os_boot.path.abspath(__file__)), '.accent')
    if _os_boot.path.exists(_accent_file):
        try:
            with open(_accent_file, 'r', encoding='utf-8') as _fac:
                _saved_accent = _fac.read().strip()
            if _saved_accent.startswith('#') and len(_saved_accent) == 7:
                from ui.theme import set_accent_override
                set_accent_override(_saved_accent)
        except Exception:
            pass
    # Force grayscale anti-aliasing to eliminate sub-pixel color fringing
    from PySide6.QtGui import QFont
    font = app.font()
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    _apply_app_font(app)
    apply_mpl_theme()
    _rebuild_styles()
    window = Main_Menu()
    window.showMaximized()
    sys.exit(app.exec())
