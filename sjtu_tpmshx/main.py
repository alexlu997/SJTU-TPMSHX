import sys
import json
import time as _time
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
from ui.fmt import duration as _fmt_dur
from ui.matplotlib_canvas import _label_axes
from ui.mixins import RunHistoryMixin, DialogsMixin, ZonePanelMixin, OptimizeUIMixin
from ui.ui_constants import (
    TOAST_MS_BRIEF, TOAST_MS_SHORT, TOAST_MS_MED,
    VV_VELOCITY_LIMIT_MS, RE_NU_LO, RE_NU_HI,
)
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
# Moved to ui/delegates.py (Phase 5 follow-up). Re-exported here for
# any historical callers that imported `main._SelectAllDelegate`.
from ui.delegates import SelectAllDelegate as _SelectAllDelegate  # noqa: F401


# ── Main window ───────────────────────────────────────────────
class Main_Menu(RunHistoryMixin, DialogsMixin, ZonePanelMixin, OptimizeUIMixin, QMainWindow):
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

        # Phase 5: install a process-wide FieldFactory backed by the live
        # ThemeManager so ui_builders helpers (section/row/res_row/add_row)
        # build widgets through DI rather than module globals.
        from ui.field_factory import FieldFactory, set_default_factory
        set_default_factory(FieldFactory(self.theme))

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
        # Audit C5 H4 fix: unified parse → validate handler replaces
        # the pre-Phase-5 split (``_attach_input_validators`` +
        # ``_install_inline_unit_parser``). The single connection
        # eliminates the order-sensitive dual-editingFinished race
        # that left ``inpError`` red borders stuck on freshly-valid
        # converted fields.
        self._attach_field_validation()
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
            self.signals.adopt(le.textEdited, self._mark_grid_edited,
                                tag=f'grid-edited-{le.objectName() or id(le)}',
                                sender=le)
        self._setup_shortcuts()
        # PyVista/VTK context creation costs 1-2 s and was running 500 ms
        # after startup. Keep it lazy unless explicitly opted in for demos.
        import os as _os_perf
        if _os_perf.environ.get('TPMSHX_PREINIT_3D', '0') == '1':
            self._schedule_3d_preinit()
        self._schedule_tpms_geometry_prewarm()
        # Note: ``_install_inline_unit_parser`` was merged into
        # ``_attach_field_validation`` at line 257 (audit C5 H4 fix).
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
        # Tier 25: a reset changes every input, so the prior compute
        # result is stale — invalidate it (disables result tabs + export,
        # clears cached fields) before re-seeding defaults. Without this
        # the old Temperature/Pressure/Velocity/3D plots stayed visible
        # next to freshly-reset inputs.
        self._invalidate_results_for_preset_load()
        self._apply_shanghai_defaults()
        self.statusBar().showMessage("Parameters reset to Shanghai Electric preset.", TOAST_MS_MED)

    def _track_shortcut(self, key, slot, tag):
        """QShortcut + connect + SignalRouter.adopt — one call.

        Phase 5 follow-up (Plan #4 connect-migration). Builds a
        QShortcut parented on ``self`` (so its lifetime matches the
        window's), wires ``slot``, and registers the connection with
        ``self.signals`` so closeEvent's bulk disconnect covers it.
        Returns the QShortcut for further configuration.
        """
        from PySide6.QtGui import QShortcut, QKeySequence
        sc = QShortcut(QKeySequence(key), self)
        sc.activated.connect(slot)
        self.signals.adopt(sc.activated, slot, tag=tag, sender=sc)
        return sc

    def _setup_shortcuts(self):
        # Phase 5 follow-up: every shortcut routed through _track_shortcut
        # so closeEvent's signals.disconnect_all() picks them up. Lambdas
        # are bound to local names (not inline) so adopt() can hold them
        # for later disconnect.
        ts = self._track_shortcut
        ts("Ctrl+R", self.run_calculation, tag='sc-run')
        ts("Ctrl+Shift+R", self._reset_defaults, tag='sc-reset')
        for key, name in (('Ctrl+1', 'layout'), ('Ctrl+2', 'temp'),
                          ('Ctrl+3', 'pres'), ('Ctrl+4', 'vel'),
                          ('Ctrl+5', '3d')):
            ts(key, (lambda n=name: self._switch_tab(n)),
                tag=f'sc-tab-{name}')
        # Immersive 3D toggle (F key)
        ts("F", self._toggle_3d_immersive, tag='sc-immersive')
        ts("Ctrl+?", self._show_shortcuts, tag='sc-help-q')
        ts("Ctrl+/", self._show_shortcuts, tag='sc-help-s')
        # D12 — fluid quick-presets
        for digit, fluid in ((1, 'Air'), (2, 'Water'), (3, 'sCO₂')):
            ts(f"Alt+{digit}",
                (lambda f=fluid: self._keyboard_set_fluid('A', f)),
                tag=f'sc-fluid-A-{digit}')
            ts(f"Alt+Shift+{digit}",
                (lambda f=fluid: self._keyboard_set_fluid('B', f)),
                tag=f'sc-fluid-B-{digit}')
        # D13 — density cycle
        ts("[", (lambda: self._cycle_density(-1)),
            tag='sc-density-prev')
        ts("]", (lambda: self._cycle_density(+1)),
            tag='sc-density-next')
        # D14 — Alt+↑/↓ scrub recent runs
        ts("Alt+Up", (lambda: self._scrub_recent(-1)),
            tag='sc-scrub-prev')
        ts("Alt+Down", (lambda: self._scrub_recent(+1)),
            tag='sc-scrub-next')
        # D7 — Ctrl+D overview dashboard
        ts("Ctrl+D", self._show_overview, tag='sc-overview')
        # NSGA-II launch
        ts("Ctrl+Return", self._run_optimize, tag='sc-opt-return')
        ts("Ctrl+Enter", self._run_optimize, tag='sc-opt-enter')
        # E18 — Ctrl+↑/↓ cycle tabs
        ts("Ctrl+Up", (lambda: self._cycle_tab(-1)),
            tag='sc-cycle-tab-prev')
        ts("Ctrl+Down", (lambda: self._cycle_tab(+1)),
            tag='sc-cycle-tab-next')

    def _export_results(self):
        """Export last compute results to CSV + optional NPZ."""
        import os, csv
        res_3d = getattr(self, '_result_3d', None)
        has_2d = getattr(self, '_has_results_2d', False)
        # 2026-05-20 UI sweep (Tier 14, user re-audit): previously this
        # gate used `_has_results_3d`, which only goes True if the 3D
        # PyVistaQt panel rendered successfully. When the solver
        # succeeded but visualisation failed, the export button was
        # enabled (gated on `_has_results`) yet clicking it landed on
        # the "No Results" dialog because both `has_2d` and `has_3d`
        # were False. Switch to a data-presence check: numerical results
        # are exportable independent of whether the 3D scene rendered.
        has_3d = res_3d is not None
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
            self.statusBar().showMessage(f"Exported: {path}", TOAST_MS_MED)
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
        # Tier 25: snap the undo baseline to the just-written preset values
        # so a later manual edit's Ctrl+Z stops at the preset state, not
        # the values that preceded the preset load. Safe at init (the
        # helper no-ops when `_undo_last` is not yet built).
        self._resync_undo_baseline()
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
            self.statusBar().showMessage("3D viewer ready.", TOAST_MS_BRIEF)
        QTimer.singleShot(500, _preinit)

    def _schedule_tpms_geometry_prewarm(self):
        """Warm the current TPMS geometry cache off the UI thread.

        Auto-fill calls compute_tpms(), whose first exact geometry evaluation
        builds a 256^3 voxel grid. Doing that in the background keeps the
        first Auto-fill click from paying the full cold-cache cost.

        Phase 5 follow-up (UI report #1, 2026-05-07): also pre-imports +
        warms the D-F surrogate (joblib/sklearn RBF). First call to
        ``df_fit.predict.predict_K_cF`` adds ~1-2 s on cold-cache because
        joblib has to demand-load the .joblib model and sklearn pulls in
        scipy. Doing that in the same background thread eliminates the
        "Not Responding" flash when the user clicks Fluid Auto-fill.
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

            tpms_type, Lcell, t_mm, _ = args

            def _worker():
                try:
                    tpms_geometry(*args)
                except Exception:
                    pass
                # Warm the D-F surrogate by triggering one prediction.
                # Loads joblib model + first sklearn import.
                try:
                    from df_fit.predict import predict_K_cF
                    predict_K_cF(tpms_type, float(Lcell), float(t_mm), 0.4)
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
            'layout':  True,
            'temp':    (not is_3d) and getattr(self, '_has_results_2d', False),
            'pres':    (not is_3d) and getattr(self, '_has_results_2d', False),
            'vel':     (not is_3d) and getattr(self, '_has_results_2d', False),
            '3d':      is_3d and getattr(self, '_has_results_3d', False),
            # D-plan: Optimize tab is the entry point for NSGA-II — must be
            # reachable before any compute so the user can click Launch.
            # The Pareto plot stays empty until a run completes; the
            # launch/status/progress header is always shown.
            'pareto':  True,
            # 2026-05-09 Phase 4 — 2D View aggregator: enable iff at least
            # one of the underlying field tabs is enabled (i.e., 2D mode +
            # results computed).
            '2d_view': (not is_3d) and getattr(self, '_has_results_2d', False),
        }
        btn_map = {
            'layout':  self.btn_tab_layout,
            'temp':    self.btn_tab_temp,
            'pres':    self.btn_tab_pres,
            'vel':     self.btn_tab_vel,
            '3d':      self.btn_tab_3d,
            'pareto':  self.btn_tab_pareto,
            '2d_view': getattr(self, 'btn_tab_2d_view', None),
        }
        for key, enabled in rules.items():
            btn = btn_map[key]
            if btn is None:
                continue   # 2d_view button may not yet exist (early init)
            btn.setEnabled(enabled)
            if not enabled and key != 'layout':
                btn.setStyleSheet(self._PTAB_DISABLED)
            card = self._canvas_cards.get(key)
            if card is not None and not enabled:
                card.hide()
        # 2026-05-09 fix #1 — keep combo_2d_field gated alongside the
        # btn_tab_2d_view button so a disabled tab doesn't have a vivid
        # field selector beside it (visual clash from screenshot review).
        _combo = getattr(self, 'combo_2d_field', None)
        if _combo is not None:
            _combo.setEnabled(rules.get('2d_view', False))
        # Fall back to Layout if active tab just became disabled
        if not rules.get(getattr(self, '_active_tab', 'layout'), True):
            self._switch_tab('layout')

    def _split_with_current(self, tab):
        """Enter split-view pairing the currently active tab with `tab`.
        No-op if the shifted tab is the one already active (user would
        end up pairing X with X, which is just a single view). The split
        view persists until any normal (non-shifted) tab click."""
        # 2026-05-20 UI sweep (Tier 19): the 2D View tab button binds
        # its Shift+click callback to `_split_with_current('2d_view')`,
        # but the `_en` map below has no '2d_view' key — it lists the
        # underlying field cards (temp/pres/vel) plus layout/pareto/3d.
        # Without this resolve step the lookup returned None, `_en`
        # returned False, and Shift+click on 2D View always surfaced
        # the misleading "Split view requires both tabs to have data"
        # status message. Resolve '2d_view' to whichever field card is
        # currently selected by the 2D field combo.
        if tab == '2d_view':
            tab = self._resolve_2d_view_card()
        cur = getattr(self, '_active_tab', None)
        if cur == '2d_view':
            cur = self._resolve_2d_view_card()
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

    def _resolve_2d_view_card(self) -> str:
        """Map the '2d_view' tab key onto the currently-selected underlying
        field card ('temp'/'vel'/'pres'). Added 2026-05-20 UI sweep so
        ``_split_with_current`` and other code paths share one resolver.
        """
        _combo = getattr(self, 'combo_2d_field', None)
        sel = _combo.currentText() if _combo is not None else "Temperature"
        return {
            "Temperature":   'temp',
            "Velocity |U|":  'vel',
            "Pressure":      'pres',
        }.get(sel, 'temp')

    def _switch_tab(self, tab: str):
        # 2026-05-09 Phase 4 — '2d_view' is the merged Temperature/Velocity/
        # Pressure tab. Resolve to the underlying card key based on the
        # combo_2d_field selection. The legacy 'temp'/'pres'/'vel' keys
        # still work directly (hotkeys, code-side routing) and reverse-sync
        # the combo so the dropdown reflects the active field.
        _combo = getattr(self, 'combo_2d_field', None)
        _combo_label_map = {
            'temp': "Temperature",
            'vel':  "Velocity |U|",
            'pres': "Pressure",
        }
        if tab == '2d_view':
            sel = _combo.currentText() if _combo is not None else "Temperature"
            tab = {
                "Temperature":   'temp',
                "Velocity |U|":  'vel',
                "Pressure":      'pres',
            }.get(sel, 'temp')
        elif tab in _combo_label_map and _combo is not None:
            target = _combo_label_map[tab]
            if _combo.currentText() != target:
                # Block the change-signal so we don't recurse via _switch_tab
                _combo.blockSignals(True)
                _combo.setCurrentText(target)
                _combo.blockSignals(False)
        # Exiting split view — a plain tab click means "back to single".
        if getattr(self, '_split_tabs', None):
            self._split_tabs = None
            from ui.ui_builders import _relayout_canvas_cards
            _relayout_canvas_cards(self, 1)
        # Reject clicks on hidden tabs (defensive — buttons are hidden anyway)
        btn_lookup = {
            'layout':  getattr(self, 'btn_tab_layout', None),
            'temp':    getattr(self, 'btn_tab_temp', None),
            'pres':    getattr(self, 'btn_tab_pres', None),
            'vel':     getattr(self, 'btn_tab_vel', None),
            '3d':      getattr(self, 'btn_tab_3d', None),
            'pareto':  getattr(self, 'btn_tab_pareto', None),
            '2d_view': getattr(self, 'btn_tab_2d_view', None),
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
        # Two-phase tab swap (UI report 2026-05-07 issue #4):
        #   Phase 1 — hide all non-target cards + restyle ALL tab buttons.
        #             These ops are cheap; finish them inside one repaint
        #             batch so the user sees the button highlight + the
        #             old card disappear immediately.
        #   Phase 2 — defer the heavy `card.show()` for the target tab
        #             (especially 3D, which spins up PyVista's OpenGL
        #             context for ~50-100 ms). Using QTimer.singleShot(0)
        #             yields one event-loop tick so the Phase-1 paint
        #             flushes before the heavy work blocks the thread.
        #
        # Prior to this split the user saw the 3D button highlight but
        # the Geometry card stayed visible until OpenGL came up.
        _scroll = getattr(self, '_canvas_scroll', None)
        _viewport = _scroll.viewport() if _scroll is not None else None
        if _viewport is not None:
            _viewport.setUpdatesEnabled(False)
        for key, btn in tabs:
            card = self._canvas_cards.get(key)
            if key == tab:
                btn.setStyleSheet(self._PTAB_ON)
            else:
                if card:
                    card.hide()
                if btn.isEnabled():
                    btn.setStyleSheet(self._PTAB_OFF)
                else:
                    btn.setStyleSheet(self._PTAB_DISABLED)
        # 2026-05-09 Phase 4 — keep the consolidated 2D View button styled
        # ON whenever the active card is one of the underlying 2D fields.
        _btn_2d = getattr(self, 'btn_tab_2d_view', None)
        if _btn_2d is not None:
            if tab in ('temp', 'pres', 'vel'):
                _btn_2d.setStyleSheet(self._PTAB_ON)
            elif _btn_2d.isEnabled():
                _btn_2d.setStyleSheet(self._PTAB_OFF)
            else:
                _btn_2d.setStyleSheet(self._PTAB_DISABLED)
        if _viewport is not None:
            _viewport.setUpdatesEnabled(True)
        # Phase 1 flush — paint button + hides before heavy work.
        try:
            from PySide6.QtWidgets import QApplication as _QApp
            _QApp.processEvents()
        except Exception:
            pass

        # Phase 2 — defer target card.show() (may activate OpenGL).
        target_card = self._canvas_cards.get(tab)
        showed_any = False
        if target_card and (tab == 'pareto'
                            or getattr(self, '_has_results', False)
                            or tab in drawn):
            target_card.show()
            showed_any = True
        elif tab == '3d' and target_card:
            target_card.hide()

        if hasattr(self, '_empty_state_label'):
            self._empty_state_label.setVisible(not showed_any)
        # UI report 2026-05-07 issue #5: re-evaluate summary bar
        # visibility against the new active tab (hides on Geometry).
        if hasattr(self, '_result_summary_bar') \
                and getattr(self, '_has_results', False):
            try:
                self._update_result_summary()
            except Exception:
                pass
        self._hover_label.setText("")

    def _on_hover(self, event):
        """Show data value at mouse position on contour plots."""
        # 2026-05-20 UI sweep (Tier 20): the unguarded `_on_hover`
        # was the *real* hot-path. The Tier-19 canvas_tools throttle
        # only governed the crosshair overlay; this label-updating
        # handler also fired on every motion_notify_event and ran
        # an axes scan + grid-index lookup + QLabel.setText + a
        # coord_inspector update. At 144 Hz mouse polling that
        # combined to >100 KB of churn per second of hover. Gate to
        # ~30 Hz; the eye cannot read faster than that anyway.
        from time import monotonic as _now_hover
        _t_hover = _now_hover()
        if _t_hover - getattr(self, '_last_hover_t', 0.0) < 0.033:
            return
        self._last_hover_t = _t_hover
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

        # Find which subplot the mouse is in. Cache the flattened axes
        # list on the canvas so we do not rebuild it on every motion —
        # the axes objects survive `fig.clear()` (clear destroys the
        # axes children but a *new* clear/replot would update
        # `canvas.axes` and invalidate the cache; we invalidate by
        # comparing the id of `canvas.axes`).
        _cache_key = id(canvas.axes)
        _cached = getattr(canvas, '_axes_flat_cache', None)
        if _cached is None or _cached[0] != _cache_key:
            axes = [ax for row in canvas.axes for ax in row]
            canvas._axes_flat_cache = (_cache_key, axes)
        else:
            axes = _cached[1]
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
            # Grid suggestion delegated to domain.validator (Phase 4 #4).
            # 2D path retains adaptive_grid (solver-side, BL-aware); 3D
            # path matches the legacy heuristic exactly via suggest_grid_3d.
            if is_3d:
                from domain.validator import suggest_grid_3d
                try:
                    Lz_dom = float(self.le_Lz.text())
                except ValueError:
                    Lz_dom = 0.02
                Nx_sug, Ny_sug, Nz_sug = suggest_grid_3d(
                    L_dom, H_dom, Lz_dom, r['D_h'])
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
        """Update outlet temperature display using actual flow directions.

        2026-05-20 UI sweep: was displaying raw Kelvin even when the
        user had toggled the header K/°C button to °C, producing a
        value/unit mismatch (label says °C, number was 415.4 K).
        Route through ``_set_temp_K`` so the displayed unit honours
        ``self._temp_unit``.
        """
        dir_A = self._dir_int(self.combo_dirA)
        dir_B = self._dir_int(self.combo_dirB)
        # Fluid A outlet
        if dir_A == 0:   ta = np.mean(self.T_fA[t_idx, -1, :])
        elif dir_A == 1: ta = np.mean(self.T_fA[t_idx, 0, :])
        elif dir_A == 2: ta = np.mean(self.T_fA[t_idx, :, -1])
        else:            ta = np.mean(self.T_fA[t_idx, :, 0])
        self._set_temp_K(self._r_ToutA, float(ta))
        # Fluid B outlet
        if dir_B == 0:   tb = np.mean(self.T_fB[t_idx, -1, :])
        elif dir_B == 1: tb = np.mean(self.T_fB[t_idx, 0, :])
        elif dir_B == 2: tb = np.mean(self.T_fB[t_idx, :, -1])
        else:            tb = np.mean(self.T_fB[t_idx, :, 0])
        self._set_temp_K(self._r_ToutB, float(tb))
        # Cache the raw K values so a later K/°C toggle can re-render
        # without re-running the solver.
        self._tout_K_cache = (float(ta), float(tb))

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
            # 2026-05-09 (option B) — route per-side fluid type through to
            # tpms_compute so water side picks up water properties + the
            # Pr-substitution Nu correlation. Falls back to 'air' if combo
            # not present (legacy compute path).
            from solvers.tpms_calc import parse_fluid_type
            _combo = getattr(self, f'combo_fluid{fluid}', None)
            _ftype = parse_fluid_type(_combo) if _combo is not None else 'air'
            r = tpms_compute(
                self.combo_tpms.currentText(),
                float(self.le_Lcell.text()), float(self.le_t.text()),
                float(le_u.text()), T_K,
                float(le_Pin.text()), float(self.le_ks.text()),
                fluid_type=_ftype)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return

        # Convert face HTC [W/(m2K)] to volumetric HTC [W/(m3K)] —
        # delegated to domain.compute_volumetric_htc (Phase 4 #4).
        from domain.validator import compute_volumetric_htc
        h_v_vol = compute_volumetric_htc(r['A_0'], r['H_sf'])
        u_val = float(le_u.text())
        U_sf = u_val * r['epsilon']

        # Re range check against Nu v4.1 calibration window.
        Re = r['Re']
        re_style = _VAL
        re_tag = ""
        if Re < RE_NU_LO:
            re_style = _VAL_WARN
            re_tag = f"  (< {RE_NU_LO}!)"
        elif Re > RE_NU_HI:
            re_style = _VAL_WARN
            re_tag = f"  (> {RE_NU_HI}!)"

        self.statusBar().showMessage(f"Fluid {fluid} filled.  Re={Re:.0f}{re_tag}  Nu={r['Nu']:.2f}  dP/L={r['dP_per_L']:.1f} Pa/m", TOAST_MS_MED)
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

    # Wall mapping moved to domain.validator.wall_for_dir (Phase 4 #4).
    # These shims keep call sites in main.py + ui/* working unchanged.
    def _inlet_wall(self, d):
        from domain.validator import wall_for_dir
        return wall_for_dir(d, 'inlet')

    def _outlet_wall(self, d):
        from domain.validator import wall_for_dir
        return wall_for_dir(d, 'outlet')

    def _on_dir_changed(self):
        """Relabel inlet/outlet fields to match selected flow-axis.

        dir 0/1 (±x) stream → cross1 = Y, cross2 = Z
        dir 2/3 (±y) stream → cross1 = X, cross2 = Z
        dir 4/5 (±z) stream → cross1 = X, cross2 = Y
        The UI fields `in_ctr/in_w/out_ctr/out_w` always control cross1;
        `in_z_ctr` etc. always control cross2 — labels show the real axis
        so user knows which coord they're editing.
        """
        # Cross-axis labels delegated to domain.validator (Phase 4 #4).
        from domain.validator import cross_axes_for_dir
        for combo, prefix in [(self.combo_dirA, 'pipeA'),
                              (self.combo_dirB, 'pipeB')]:
            try:
                c1, c2 = cross_axes_for_dir(combo.currentIndex())
            except ValueError:
                c1, c2 = 'Y', 'Z'
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
        # 2026-05-20 UI sweep: extended the label list with the result-row
        # outlet temperature labels (`_lbl_ToutA_unit`, `_lbl_ToutB_unit`)
        # captured by ui_builders. Previously these stayed `[K]` after a
        # K/°C toggle, mismatching the converted value.
        for attr in ('_lbl_TinA_unit', '_lbl_TinB_unit', '_lbl_TsInit_unit',
                     '_lbl_ToutA_unit', '_lbl_ToutB_unit'):
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
        # 2026-05-20 UI sweep: re-render the cached outlet temperature
        # results in the new unit so the result-row value follows the
        # label suffix instead of staying as raw Kelvin from the last
        # solve.
        _tout_cache = getattr(self, '_tout_K_cache', None)
        if _tout_cache is not None:
            try:
                ta_K, tb_K = _tout_cache
                self._set_temp_K(self._r_ToutA, ta_K)
                self._set_temp_K(self._r_ToutB, tb_K)
            except Exception:
                pass
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
                # Tier 25: keep the undo baseline in step with this
                # programmatic write (fluid-type combo change). These
                # fields are not the ones that re-fire fluid defaults
                # (that's the combo), so refreshing the baseline here is
                # safe and prevents a later manual edit's Ctrl+Z jumping
                # back across the auto-applied defaults to a stale value.
                ul = getattr(self, '_undo_last', None)
                if ul is not None:
                    ul[attr] = txt
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
        # 2026-05-20 UI sweep (Tier 21): guard the reattach against the
        # main-window-teardown path. The dialog is parented to `self`,
        # so when the main window closes Qt also destroys this dialog
        # and fires this override — at which point `self` is mid-destroy
        # and `self.statusBar()` inside `_reattach_3d_window` would
        # dereference a deleted C++ object. closeEvent (step 2) now
        # neutralises the override before app teardown, but keep a
        # try/except here as belt-and-braces.
        def _on_close(ev):
            try:
                self._reattach_3d_window()
            except (RuntimeError, AttributeError):
                pass
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
        self.statusBar().showMessage("3D view re-docked.", TOAST_MS_SHORT)

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
            # Tier 21: same dead-self guard as the 3D detach path.
            try:
                self._reattach_canvas(_k)
            except (RuntimeError, AttributeError):
                pass
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
        self.statusBar().showMessage(f"{key} canvas re-docked.", TOAST_MS_SHORT)

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
            last = getattr(self, '_last_elapsed_s', None)
            mode = self._active_compute_mode()
            if last is None:
                self._sb_clock.setText("⏱ —")
            else:
                self._sb_clock.setText(
                    f"⏱ {_fmt_dur(last)} · {mode.upper()}")
        except Exception:
            pass

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
            # 2026-05-20 UI sweep (Tier 20): mirror the theme-restart
            # save-guard so a session-write failure aborts execv
            # instead of losing the user's pending edits.
            _saved = False
            try:
                _saved = bool(self._save_session())
            except Exception:
                _saved = False
            if not _saved:
                QMessageBox.warning(
                    self, "Accent change — session not saved",
                    "The .accent file was written but persisting your "
                    "current inputs to the session failed. Restart was "
                    "cancelled to avoid losing pending edits. Save / "
                    "copy any values you need, then relaunch manually.")
                return
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
            # 2026-05-20 UI sweep (Tier 20): same save-guard as
            # _toggle_theme / _pick_accent_color. Density change is
            # cosmetic; losing the user's inputs to it is not.
            _saved = False
            try:
                _saved = bool(self._save_session())
            except Exception:
                _saved = False
            if not _saved:
                QMessageBox.warning(
                    self, "Density change — session not saved",
                    "The .density file was written but persisting your "
                    "current inputs to the session failed. Restart was "
                    "cancelled to avoid losing pending edits. Save / "
                    "copy any values you need, then relaunch manually.")
                return
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
            # 2026-05-20 UI sweep (Tier 18): the prior code called
            # `_save_session()` and then unconditionally invoked
            # `os.execv`, which replaces the current process image. If
            # the save IO failed (permission, disk full, locked file)
            # the user's pending edits were lost the instant execv
            # fired. Abort the restart on save failure and tell the
            # user explicitly so they can save manually first.
            _saved = False
            try:
                _saved = bool(self._save_session())
            except Exception:
                _saved = False
            if not _saved:
                QMessageBox.warning(
                    self, "Theme switch — session not saved",
                    "The theme change is queued (the .theme file is "
                    "written) but persisting your current inputs to "
                    "the session file failed. Restart was cancelled to "
                    "avoid losing pending edits. Please relaunch the "
                    "app manually once you have saved or copied any "
                    "values you need.")
                return
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

    def _resync_undo_baseline(self):
        """Reset the undo baseline (`_undo_last`) to the CURRENT text of
        every session line-edit.

        2026-05-20 UI sweep (Tier 25). The global undo stack records a
        field edit by comparing `editingFinished` text against
        `_undo_last`. A programmatic batch-write (preset / Reset /
        workspace switch / Shanghai defaults / session restore) rewrites
        many fields via `setText` WITHOUT emitting `editingFinished`, so
        `_undo_last` stayed at the pre-write values. The next manual edit
        then pushed an undo command whose "old" value was the
        pre-programmatic text — Ctrl+Z would jump back across the entire
        preset load to a stale value. Treat these batch writes as undo
        checkpoints: after the write, snap the baseline to the new text
        so undo reverts to the post-preset state, not before it.
        """
        ul = getattr(self, '_undo_last', None)
        if ul is None:
            return
        for _nm in self._SESSION_LINE_EDITS:
            _le = getattr(self, _nm, None)
            if _le is not None:
                try:
                    ul[_nm] = _le.text()
                except Exception:
                    pass

    def _invalidate_results_for_preset_load(self):
        """Drop every cached compute artefact so a freshly-loaded preset
        cannot show the previous run's plots next to its new inputs.

        Added 2026-05-20 UI sweep (Tier 18). Called from
        ``_apply_user_preset`` — covers both the explicit Load Preset
        path and the Recent-run click path (which routes through the
        same helper).
        """
        # 2D-mode result flags + cached fields.
        self._has_results_2d = False
        self.T_fA = self.T_fB = self.T_s = None
        # 3D-mode result flags + cached fields.
        self._has_results_3d = False
        self._result_3d = None
        self._tout_K_cache = None
        # Aggregate flag + draw tracker — keep in lock-step with the two
        # mode-specific flags above.
        self._has_results = False
        self._drawn_tabs = set()
        # Reset the outlet temperature display so a stale value can't be
        # mistaken for the post-preset result.
        for attr in ('_r_ToutA', '_r_ToutB', '_r_dP_A', '_r_dP_B', '_r_Q'):
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    w.setText("—")  # em dash
                except Exception:
                    pass
        # Refresh tab visibility so the result tabs (Temp/Pres/Vel/3D)
        # disable now that there are no results to show.
        try:
            self._update_tab_visibility()
        except Exception:
            pass
        # Disable the export buttons — there is nothing to export.
        for _bname in ('btn_export_results', 'btn_export_figure'):
            _b = getattr(self, _bname, None)
            if _b is not None:
                try:
                    _b.setEnabled(False)
                except Exception:
                    pass

    def _apply_user_preset(self, preset):
        """Apply a saved preset payload (shape matches _save_session output).

        Widget names are filtered through the SESSION allow-lists so a tampered
        or malicious share-link cannot address arbitrary window attributes.

        2026-05-20 UI sweep (Tier 18): also invalidate compute-result
        caches up front. Prior to this, loading a preset (or clicking a
        Recent run via ``_load_recent_run`` which delegates here) only
        rewrote the input fields. The result flags / drawn tabs / cached
        3D result dict / 2D T_fA/T_fB/T_s arrays all survived, so the
        Temperature/Velocity/Pressure/3D tabs remained ENABLED and the
        canvas still showed the PREVIOUS compute's plots next to the
        freshly-loaded parameters. Easy to read as "preset applied",
        miss that the visible result is stale, then quote a number from
        the old compute as if it were the new design's.
        """
        self._invalidate_results_for_preset_load()
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
                # Tier 25: builtin presets rewrite inputs via
                # _apply_shanghai_defaults, which does NOT route through
                # _apply_user_preset (where the Tier-18 invalidate lives).
                # Invalidate here so stale result tabs/plots/export from a
                # prior compute don't survive a builtin-preset switch.
                self._invalidate_results_for_preset_load()
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
        # Tier 25: a workspace switch reloads a completely different input
        # set, so the current compute result belongs to the OLD workspace.
        # Invalidate it before re-seeding so the new workspace doesn't open
        # showing the previous workspace's result tabs / plots / export.
        self._invalidate_results_for_preset_load()
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
        # 2026-05-20 UI sweep (Tier 18): SessionManager.set_active_workspace
        # returns False on IO failure. Previously this return was ignored,
        # so a marker-write failure silently reverted the next launch to
        # workspace 'A'. Surface the failure to the status bar so the
        # user knows to re-pick the workspace after restart.
        _wrote = False
        try:
            _wrote = bool(self.sm.set_active_workspace(new))
        except Exception:
            _wrote = False
        if _wrote:
            self.statusBar().showMessage(f"Workspace {new} loaded.", 4000)
        else:
            self.statusBar().showMessage(
                f"Workspace {new} loaded — but writing the active-workspace "
                f"marker failed; next launch may default to 'A'.", 8000)

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
        # 2026-05-20 UI sweep (Tier 18): return SessionManager's bool so
        # callers (notably _toggle_theme's restart path) can abort on a
        # silent IO failure instead of execv'ing into a process that has
        # lost the user's pending edits.
        return bool(self.sm.save_session(
            payload, getattr(self, '_active_workspace', 'A')))

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
        # Tier 25: the restore above rewrote every field via setText with
        # no editingFinished — snap the undo baseline to the restored
        # state so the user's first manual edit undoes to what they see,
        # not to the construction-time defaults.
        self._resync_undo_baseline()

    def closeEvent(self, event):
        """Single close-event handler — covers all three concerns:

        1. Persist session (legacy contract — was lost when a duplicate
           closeEvent at L4399 silently shadowed this one prior to the
           2026-05-20 UI sweep merge).
        2. Tear down PyVistaQt GL context before Qt destroys the widgets
           (moved here from the deleted L4399 dup).
        3. Bulk-disconnect router-tracked signal connections (Phase 3
           2026-05-06 #4 — belt-and-braces against bound-method slots
           that close over ``self`` and outlive C++ widget destruction).
        """
        # 1. Persist session first — `_save_session` failure used to be a
        #    silent pass; now surface to statusBar so users know.
        try:
            self._save_session()
        except Exception as _e_save:
            try:
                self.statusBar().showMessage(
                    f"Warning: session save failed — {_e_save}", 6000)
            except Exception:
                pass
        # 2. Cooperative compute cancel — flips the worker's cancel
        #    token so its next epoch-boundary check breaks out cleanly.
        #    Non-blocking: the solver may still complete (e.g. inner JIT
        #    loops can't be interrupted), but the signals it emits after
        #    we disconnect below land on dropped connections and never
        #    reach this (about-to-be-destroyed) window. Added 2026-05-20
        #    UI sweep to close the window-teardown-vs-worker race.
        try:
            if getattr(self, 'compute', None) is not None:
                self.compute.cancel()
        except Exception:
            pass
        # 2b. Neutralise any floating/detached canvas windows BEFORE Qt
        #     tears them down. Each was given a closeEvent override that
        #     calls _reattach_* → self.statusBar(); firing that during
        #     main-window destruction dereferences a half-dead C++
        #     object. Replace the override with a plain accept and close
        #     them now. Added 2026-05-20 UI sweep (Tier 21).
        _dw3d = getattr(self, '_3d_detached_window', None)
        if _dw3d is not None:
            try:
                _dw3d.closeEvent = lambda ev: ev.accept()
                _dw3d.close()
            except Exception:
                pass
            self._3d_detached_window = None
        for _k, _dw in list(getattr(self, '_detached_canvases', {}).items()):
            if _dw is not None:
                try:
                    _dw.closeEvent = lambda ev: ev.accept()
                    _dw.close()
                except Exception:
                    pass
        try:
            self._detached_canvases = {}
        except Exception:
            pass
        # 3. Detach canvas-tools mpl_connect handlers (crosshair / pin /
        #    line probe). Added 2026-05-20 UI sweep Tier 20 — pairs with
        #    the binding-retention list installed by install_canvas_tools.
        for _b in list(getattr(self, '_canvas_tool_bindings', []) or []):
            try:
                _b.disconnect()
            except Exception:
                pass
        # 4. PyVistaQt GL context teardown — must happen before Qt
        #    destroys child widgets, otherwise vtkRenderWindow leaks.
        panel = getattr(self, 'canvas_3d', None)
        if panel is not None:
            try:
                panel.cleanup()
            except Exception:
                pass
        # 5. Bulk-disconnect router-tracked signal connections.
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

            def _apply(self, value):
                # blockSignals(True) during setText prevents the editing-
                # Finished slot (_on_finished) from pushing a *new* undo
                # command for this programmatic change. We then update the
                # baseline cache to `value` and re-emit editingFinished
                # ourselves — because the cache now equals the field text,
                # _on_finished sees no diff and does NOT re-push, while the
                # OTHER editingFinished consumers (validator, edge-combo
                # refresh on L/H, quick-slider sync) still run. Tier 25:
                # fixes undo/redo silently bypassing that dependent logic.
                self._le.blockSignals(True)
                self._le.setText(value)
                self._le.blockSignals(False)
                self._cache[self._name] = value
                try:
                    self._le.editingFinished.emit()
                except Exception:
                    pass

            def undo(self):
                self._apply(self._old)

            def redo(self):
                self._apply(self._new)

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
            self.signals.adopt(le.editingFinished, _on_finished,
                                tag=f'undo-edit-{name}', sender=le)

        sc_u = QShortcut(QKeySequence.StandardKey.Undo, self)
        sc_u.activated.connect(self._undo_stack.undo)
        self.signals.adopt(sc_u.activated, self._undo_stack.undo,
                            tag='sc-undo', sender=sc_u)
        sc_r = QShortcut(QKeySequence.StandardKey.Redo, self)
        sc_r.activated.connect(self._undo_stack.redo)
        self.signals.adopt(sc_r.activated, self._undo_stack.redo,
                            tag='sc-redo', sender=sc_r)

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
        self.signals.adopt(self.statusBar().messageChanged, _on_msg,
                            tag='statusbar-msg', sender=self.statusBar())

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
        self.signals.adopt(btn.clicked, self._show_status_log,
                            tag='btn-status-log', sender=btn)
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

    # Audit C5 Phase 4 (L-b, 2026-05-28): unit-parsing config + the
    # canonical positive-numeric set live in ``domain/validator.py``
    # so future scripts / widgets can read the same canonical map.
    # The class still surfaces the two names as attributes for the
    # ``_attach_field_validation`` / ``_make_field_handler`` callers.
    from domain.validator import (
        FIELD_UNITS as _FIELD_UNITS,
        POSITIVE_FIELDS as _POSITIVE_FIELDS,
    )

    # ─── Audit C5 Phase 5 (L-b, 2026-05-28): ResultCache bridges ──
    # Storage moves wholesale to ``self.cache`` (ResultCache); these
    # properties keep the legacy attribute names working at every
    # existing call site (~50 sites in main.py + runs/ + ui/ +
    # finalize_plots), so the migration costs zero call-site churn.
    # Behaviour is single-source-of-truth: there is no longer a
    # parallel inline dict + the cache; the inline name reads/writes
    # through the cache.

    @property
    def _compute_results(self) -> dict:
        """2D mode result dict — bridges to ``self.cache``."""
        r = self.cache.get_result('2d')
        return r if r is not None else {}

    @_compute_results.setter
    def _compute_results(self, value) -> None:
        # An empty dict ``{}`` was used as a "clear" sentinel in some
        # call sites; treat that identically to ``None``.
        self.cache.set_result('2d', value if value else None)

    @property
    def _result_3d(self):
        """3D mode result dict — bridges to ``self.cache``."""
        return self.cache.get_result('3d')

    @_result_3d.setter
    def _result_3d(self, value) -> None:
        self.cache.set_result('3d', value)

    @property
    def _has_results_2d(self) -> bool:
        return self.cache.has_results('2d')

    @_has_results_2d.setter
    def _has_results_2d(self, value: bool) -> None:
        # Writing ``True`` is a no-op (presence of the result dict
        # already drives the flag).  Writing ``False`` clears the
        # cached 2D result so the next ``has_results('2d')`` returns
        # False, matching the legacy paired-write pattern.
        if not value:
            self.cache.set_result('2d', None)

    @property
    def _has_results_3d(self) -> bool:
        return self.cache.has_results('3d')

    @_has_results_3d.setter
    def _has_results_3d(self, value: bool) -> None:
        if not value:
            self.cache.set_result('3d', None)

    @property
    def _has_results(self) -> bool:
        return self.cache.has_any_results()

    @_has_results.setter
    def _has_results(self, value: bool) -> None:
        if not value:
            self.cache.clear()

    @property
    def _drawn_tabs(self) -> set:
        """Live view of ``self.cache._drawn_tabs``. Mutations on the
        returned set do NOT propagate back to the cache; call sites
        that previously did ``self._drawn_tabs.add(x)`` work because
        the cache exposes a real ``set`` reference (see
        ``ResultCache.get_drawn_tabs`` — currently returns a copy).
        Sites doing in-place ``.add`` after C5 Phase 5 should switch
        to ``self.cache.mark_drawn(x)``; meanwhile the setter below
        catches the common ``self._drawn_tabs = drawn`` pattern."""
        return self.cache.get_drawn_tabs()

    @_drawn_tabs.setter
    def _drawn_tabs(self, value: set) -> None:
        self.cache.replace_drawn_tabs(value)
    # ─── end Phase 5 bridges ──────────────────────────────────────

    def _attach_field_validation(self):
        """Unified blur-time unit parser + numeric validator.

        Audit C5 H4 fix (2026-05-28): replaces the pre-Phase-5 split where
        ``_attach_input_validators`` and ``_install_inline_unit_parser``
        each connected their own callback to ``editingFinished``. Qt
        fired them in connection order, so the validator saw the raw
        "5 mm" text *before* the unit parser converted it, leaving the
        ``inpError`` red border stuck on freshly-valid fields.

        The unified handler does parse → validate → apply in one slot.
        """
        all_fields = self._POSITIVE_FIELDS | self._FIELD_UNITS.keys()
        for attr in all_fields:
            le = getattr(self, attr, None)
            if le is None:
                continue
            fam_target = self._FIELD_UNITS.get(attr)
            is_positive = attr in self._POSITIVE_FIELDS
            cb = self._make_field_handler(le, attr, fam_target, is_positive)
            le.editingFinished.connect(cb)
            self.signals.adopt(le.editingFinished, cb,
                                tag=f'field-{attr}', sender=le)

    def _make_field_handler(self, le, attr, fam_target, is_positive):
        """Build the per-field blur callback: parse → validate → apply.

        ``fam_target`` is ``self._FIELD_UNITS.get(attr)`` (an
        ``(family, target_unit)`` tuple, or ``None`` if the field has
        no unit-parsing rule).  ``is_positive`` flips on the
        strictly-positive numeric validation.

        Unit parsing + formatting delegate to
        :func:`domain.validator.parse_field_value` /
        :func:`domain.validator.format_unit_value`.
        """
        import re as _re_up
        base_tip = le.toolTip() or ""
        num_unit = _re_up.compile(
            r"\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*"
            r"([A-Za-zμΜ°/··]+[A-Za-z0-9/··]*)\s*$")

        from domain.validator import (
            parse_field_value as _domain_parse_field,
            format_unit_value as _domain_format,
        )

        def _cb():
            txt = le.text().strip()
            if not txt:
                return

            # ── 1. PARSE — convert "5 mm" → "5e-3" etc. when the field
            #    has a unit family. Validator then sees the canonical
            #    value, never the raw "5 mm" string.
            if fam_target is not None:
                fam, target = fam_target
                m = num_unit.match(txt)
                if m:
                    try:
                        raw_val = float(m.group(1))
                    except ValueError:
                        raw_val = None
                    if raw_val is not None:
                        unit_txt = m.group(2)
                        new_val = _domain_parse_field(
                            attr, raw_val, unit_txt,
                            temp_unit=getattr(self, '_temp_unit', 'K'))
                        if new_val is not None:
                            fmt = _domain_format(new_val, fam)
                            # Suppress our own re-fire of editingFinished.
                            was = le.blockSignals(True)
                            le.setText(fmt)
                            le.blockSignals(was)
                            # Sync undo baseline (Tier 25).
                            ul = getattr(self, '_undo_last', None)
                            if ul is not None:
                                ul[attr] = fmt
                            self.statusBar().showMessage(
                                f"Converted {m.group(1)} {unit_txt} → {fmt} "
                                f"({target or fam})", 4000)
                            txt = fmt

            # ── 2. VALIDATE — strictly-positive numeric check for the
            #    positive-set fields. Non-positive fields skip this.
            bad = False
            reason = ""
            if is_positive:
                try:
                    v = float(txt)
                    if v <= 0:
                        bad = True
                        reason = "Must be > 0"
                except Exception:
                    bad = True
                    reason = "Must be a number"

            # ── 3. APPLY — flip inpError + tooltip + status-bar warn.
            current = le.property('inpError')
            new = 'true' if bad else 'false'
            if current != new:
                le.setProperty('inpError', new)
                le.style().unpolish(le)
                le.style().polish(le)
            if bad:
                le.setToolTip(f"⚠ {reason}"
                              + (f"\n{base_tip}" if base_tip else ""))
                self.statusBar().showMessage(
                    f"⚠  Invalid input: {le.objectName() or 'field'}"
                    f" — {reason}", 4000)
            else:
                le.setToolTip(base_tip)

        return _cb

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
        which conflated UI writes with result assembly.  Existing UI
        flow keeps calling ``run_calculation_inner`` (which still
        invokes ``_store_results`` for legacy shape); this method
        provides the parallel path for Pipeline-based callers.
        """
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
            'residuals_A': result.residuals.get('simple_A'),
            'residuals_B': result.residuals.get('simple_B'),
            'Q_A': result.residuals.get('Q_A', float('nan')),
            'Q_B': result.residuals.get('Q_B', float('nan')),
            'Q_net': result.residuals.get('Q_net', float('nan')),
            'energy_imbalance_rel': result.residuals.get(
                'energy_imbalance_rel', float('nan')),
        }
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
            from runs.run_calculation_3d import finalize_plots_3d
            # Audit C5 H5 fix (L-b, 2026-05-28): initialise the
            # ``_has_results_3d`` / ``_3d_vis_ok`` flags BEFORE entering
            # finalize_plots_3d.  If finalize crashes mid-way the
            # function previously returned early without resetting the
            # flag, leaving a stale ``True`` from a prior successful
            # 3D run — the next 2D compute would then see the 3D tab
            # marked ready and the user could be auto-switched to a
            # blank canvas.  Set False at the top, flip True only after
            # the embedded panel reports ok.
            self._has_results_3d = False
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
            except Exception:
                # If finalise crashes, walk the button text back to a
                # benign state — _end_compute_ui already restored it but
                # the flag must reflect failure for downstream gating.
                self._end_compute_ui(success=False)
            if not _finalize_ok:
                return
            self._has_results = True
            # Only mark the 3D View tab as ready if the PyVistaQt panel
            # actually populated. Otherwise leave the flag False so the
            # tab stays disabled and the user is not silently switched
            # to a blank canvas.
            self._has_results_3d = _3d_vis_ok
            for _bname in ('btn_export_results', 'btn_export_figure'):
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
            if res:
                try:
                    if _3d_vis_ok:
                        self.statusBar().showMessage(
                            f"3D done — Q={res.get('Q', 0):.1f} W  "
                            f"dP={res.get('dP', 0):.0f} Pa", 6000)
                    else:
                        # Solver succeeded but visualisation did not —
                        # surface explicitly so the user knows numbers
                        # are valid but the rendered canvas is not.
                        self.statusBar().showMessage(
                            f"3D solve done (Q={res.get('Q', 0):.1f} W  "
                            f"dP={res.get('dP', 0):.0f} Pa) — visualisation "
                            f"failed; check console.", 10000)
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
        for _bname in ('btn_export_results', 'btn_export_figure'):
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
        self.statusBar().showMessage("Cancelled.", TOAST_MS_SHORT)

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

    _MAX_RECENT_RUNS = 5

    # ─────────────────────────────────────────────────────────
    #  3D compute pipeline (uniform MVP)
    # ─────────────────────────────────────────────────────────
    # NB: the duplicate `closeEvent` that used to live here (silently
    # shadowing the canonical handler at L2755 above) was merged into the
    # single handler on 2026-05-20. The PyVistaQt GL-context teardown
    # logic now sits in step (2) of that handler.

    def _lazy_init_3d_panel(self):
        """Create PyVistaQt panel on first 3D tab click. ~1-2 s hit amortised.

        2026-05-20 UI sweep: added reentrance + already-init guards.
        Previously a rapid double-click on the 3D tab (or a tab switch
        while ``ThreeDVisPanel()`` was mid-construction) could spawn a
        second ``ThreeDVisPanel`` whose ``replaceWidget`` call no-op'd
        (placeholder already cleared by the first call), leaving the
        first real panel orphaned in the layout while ``self.canvas_3d``
        pointed at the second instance — a leaked VTK GL context plus a
        layout-stale widget.
        """
        if getattr(self, '_vis3d_import_error', None):
            return      # Offscreen / disabled — leave placeholder
        if getattr(self, 'canvas_3d', None) is not None:
            return      # Already initialised by a prior call.
        if getattr(self, '_lazy_init_3d_running', False):
            return      # In flight on another (nested) event loop call.
        self._lazy_init_3d_running = True
        try:
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
            self.statusBar().showMessage("3D view initialised.", TOAST_MS_BRIEF)
        finally:
            self._lazy_init_3d_running = False

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
        # 2026-05-20 UI sweep (Tier 22): pre-initialise Nx_u/Ny_u/Nz_u
        # BEFORE the try. Previously they were only assigned inside the
        # try; a parse failure (empty field, stray unit text) left the
        # `except` branch setting only `est_cells=0`, and the
        # `if Nz_u < 2:` check below then raised NameError on an
        # undefined local — turning a bad-input case into a hard crash.
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
        #
        # 2026-05-07 (UI report 2): hard budget bumped 600 s → 1800 s and
        # ETA is now u-aware. The previous estimator (35k cells / 150 s)
        # assumed Shanghai-typical low-Re cases; high-u runs (u > 10 m/s)
        # take 5-10× longer on the Forchheimer branch and were hitting
        # the 600 s cap mid-convergence.
        wd = QTimer(self)
        self._compute_3d_watchdog = wd
        _hard_timeout_s = 1800.0   # 30 min — generous for high-u + dense grids
        _ref_cells = 35000
        _ref_sec = 150.0
        # u-aware multiplier: V&V validates u ≤ 10 m/s; above that, scale
        # ETA by (u_max / 10)^2 (matches the run_calculation preflight
        # warning so user sees consistent expectations).
        try:
            _u_max = max(float(self.le_uA.text()),
                          float(self.le_uB.text()))
        except (ValueError, AttributeError):
            _u_max = 10.0
        _u_factor = max(1.0, (_u_max / 10.0) ** 2)

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
            eta_total = max(10.0,
                             est_cells_r / _ref_cells * _ref_sec * _u_factor)
            eta_remain = eta_total - elapsed
            from ui.fmt import duration as _fmt
            if eta_remain > 0:
                eta_txt = f"ETA ~{_fmt(eta_remain)} (u-factor {_u_factor:.1f})"
            else:
                over = elapsed - eta_total
                eta_txt = (f"past estimate by {_fmt(over)} — solver still "
                           f"running (u-factor {_u_factor:.1f})")
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
            self.statusBar().showMessage("No figures to export yet.", TOAST_MS_SHORT)
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
    """Pick Fira Sans > Inter > Segoe UI for labels, Fira Code for numbers.

    2026-05-09 Phase 3: app-wide font weight is set to Bold so the entire
    UI (labels, buttons, combos, dropdowns) shares one consistent weight.
    Individual stylesheet rules can still override (e.g. theme.py uses
    explicit ``font-weight:500`` for some labels), but the QApplication
    default is now bold.
    """
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
    qf = QFont(chosen, 10)
    qf.setWeight(QFont.Weight.Bold)
    app.setFont(qf)
    mono = next((n for n in ["Fira Code", "JetBrains Mono", "Consolas", "Courier New"]
                 if n in families), None)
    if mono:
        app._mono_font_family = mono
    print(f"[font] using {chosen!r} (Bold)")
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
