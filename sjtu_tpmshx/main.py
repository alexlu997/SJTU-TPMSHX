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
from ui.mixins import RunHistoryMixin, DialogsMixin, ZonePanelMixin, OptimizeUIMixin, TabViewMixin, UIBuilderMixin, FluidInputMixin, RunControllerMixin
from ui.ui_constants import (
    TOAST_MS_BRIEF, TOAST_MS_SHORT, TOAST_MS_MED,
    VV_VELOCITY_LIMIT_MS, RE_NU_LO, RE_NU_HI,
)
from ui.theme import (
    _THEMES, get_theme, get_theme_name, set_theme,
    apply_mpl_theme, get_density, set_density,
)

__version__ = "1.5.0"


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

def _rebuild_styles(theme_name=None):
    """Refresh styles after a theme switch.

    Batch-3 (2026-06-10): the module-level style globals (``_BG``,
    ``_LBL``, ``_COMBO``, …) are retired — every consumer reads styles
    through :class:`controllers.theme_manager.ThemeManager` (via
    ``ui.field_factory.default_factory().theme``). This hook persists
    the theme choice, refreshes the live window's manager when one
    exists, and re-applies the matplotlib theme.
    """
    if theme_name is not None:
        try:
            from ui.theme import set_theme as _st
            _st(theme_name)
        except Exception:
            pass
    # Refresh the live window's ThemeManager if one exists.
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            for w in app.topLevelWidgets():
                if (w.__class__.__name__ == 'Main_Menu'
                        and getattr(w, 'theme', None) is not None):
                    w.theme.rebuild()
                    break
    except Exception:
        pass
    apply_mpl_theme()


# ── Auto-select delegate for zone table editing ─────────────
# Moved to ui/delegates.py (Phase 5 follow-up). Re-exported here for
# any historical callers that imported `main._SelectAllDelegate`.
from ui.delegates import SelectAllDelegate as _SelectAllDelegate  # noqa: F401


# ── Main window ───────────────────────────────────────────────
class Main_Menu(RunHistoryMixin, DialogsMixin, ZonePanelMixin, OptimizeUIMixin, TabViewMixin, UIBuilderMixin, FluidInputMixin, RunControllerMixin, QMainWindow):
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

        # Phase 3: ThemeManager owns the style dict. Batch-3 (2026-06-10):
        # the legacy `import main as _m; m._BG` back-import path is retired
        # — the last consumers (ui/overview.py, ui/sensitivity.py) now read
        # styles via default_factory().theme, so no bind_to_module call.
        # SignalRouter records connections for bulk disconnect on closeEvent.
        self.theme = ThemeManager(self)
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
        self._rebuild_recent_menu()
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
        self._install_dialog_theme()
        from ui.command_palette import install_command_palette
        install_command_palette(self)
        from ui.coord_inspector import install_coord_inspector
        install_coord_inspector(self)
        from ui.zone_editor import ZoneHandleManager
        self._zone_handle_mgr = ZoneHandleManager(self)
        self._zone_handle_mgr.wire()
        from ui.field_menu import install_field_menus
        install_field_menus(self)
        from ui.expr_eval import install_expression_eval
        install_expression_eval(self)
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
        # qNEHVI launch
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
                # B3 C5: res_3d is the ComputeResult (raw_3d dict retired).
                # Scalars come off the dataclass / props; arrays off fields.
                _rf = res_3d.fields
                rows.append(["Q [W]", f"{res_3d.Q_W:.4f}"])
                rows.append(["dP_A [Pa]", f"{res_3d.dP_A_Pa:.2f}"])
                rows.append(["dP_B [Pa]", f"{res_3d.dP_B_Pa:.2f}"])
                rows.append(["T_inA [K]",
                             f"{res_3d.props.get('T_in_A_K', 0) or 0:.2f}"])
                rows.append(["u_A [m/s]",
                             f"{res_3d.props.get('u_A_in_mps', 0) or 0:.4f}"])
                Ta = _rf.get('Ta')
                if Ta is not None:
                    rows.append(["Ta_min [K]", f"{float(Ta.min()):.2f}"])
                    rows.append(["Ta_max [K]", f"{float(Ta.max()):.2f}"])
                    rows.append(["Grid Nx", str(Ta.shape[0])])
                    rows.append(["Grid Ny", str(Ta.shape[1])])
                    rows.append(["Grid Nz", str(Ta.shape[2])])
                rows.append(["Lx [m]", f"{_rf.get('Lx', 0) or 0:.6f}"])
                rows.append(["Ly [m]", f"{_rf.get('Ly', 0) or 0:.6f}"])
                rows.append(["Lz [m]", f"{_rf.get('Lz', 0) or 0:.6f}"])
            with open(path, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(["Parameter", "Value"])
                w.writerows(rows)
            # Optional: save 3D fields as NPZ alongside. Keep the legacy
            # NPZ schema (vmag, P_kPa) stable: map from ComputeResult.fields
            # (vmag_A → vmag; P_fA/1000 → P_kPa).
            npz_path = os.path.splitext(path)[0] + '_fields.npz'
            if res_3d is not None:
                _rf = res_3d.fields
                save_dict = {}
                for npz_key, src in (('Ta', 'Ta'), ('Tb', 'Tb'),
                                     ('Ts', 'Ts'), ('vmag', 'vmag_A'),
                                     ('L_mm', 'L_mm'), ('dx', 'dx'),
                                     ('dy', 'dy'), ('dz', 'dz')):
                    v = _rf.get(src)
                    if v is not None:
                        save_dict[npz_key] = v
                _p_fa = _rf.get('P_fA')
                if _p_fa is not None:
                    save_dict['P_kPa'] = _p_fa / 1000.0
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
        # Flow topology → canonical Shanghai crossflow. This method used to
        # leave the direction/fluid-B combos at whatever the session had set,
        # so a stale session could open in a ROTATED topology (e.g. A:+y B:-x)
        # even after Reset. Pin them here:
        #   A air  → +x (index 0), streams along the 182 mm length
        #   B water→ -y (index 3), crossflow across the 42 mm width
        #   Fluid B→ Water (index 1), the gas-heater cold side
        for combo_attr, idx in (('combo_dirA', 0),
                                ('combo_dirB', 3),
                                ('combo_fluidB', 1)):
            try:
                c = getattr(self, combo_attr, None)
                if c is not None and 0 <= idx < c.count():
                    c.setCurrentIndex(idx)
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
        ``df_surrogate.predict.predict_K_cF`` adds ~1-2 s on cold-cache because
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
                    from df_surrogate.predict import predict_K_cF
                    predict_K_cF(tpms_type, float(Lcell), float(t_mm), 0.4)
                except Exception:
                    pass

            import threading
            threading.Thread(
                target=_worker, name="tpms-geometry-prewarm",
                daemon=True).start()

        QTimer.singleShot(900, _start)


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
        #       gives "paper-run" ~90k-cell refined grid matching the
        #       current Shanghai 3D dP baseline ≈ 9.82% (gamma_df) /
        #       7.19% (rbf) RMSRE without runaway timing (17.83% is
        #       historical).
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


    # Wall mapping moved to domain.validator.wall_for_dir (Phase 4 #4).
    # These shims keep call sites in main.py + ui/* working unchanged.


    # Auto-defaults applied when the user swaps the fluid type for a given
    # side. Values are conservative "typical operating point" numbers; the
    # user can still edit afterwards. Temperature stored in K; the parser
    # converts to °C if the header toggle is currently °C.
    _FLUID_DEFAULTS = {
        'Air':   {'u': 20.0,  'T': 422.0, 'P': 101325.0},
        'Water': {'u': 0.15,  'T': 300.0, 'P': 101325.0},
        'sCO₂':  {'u': 2.0,   'T': 350.0, 'P': 8000000.0},
    }


    # Detached 3D panel — right-click the "3D View" tab offers "Open in
    # new window". The panel widget is reparented to a borderless QDialog
    # so users on multi-monitor setups can drag it to a second screen.
    # Closing the detached window reattaches to the card.
    _3d_detached_window = None


    # ─── D17 — generic any-canvas detach ─────────────────────────────
    _detached_canvases = {}


    # ─────────────────────────────────────────────────────────
    #  Status bar — persistent context strip (IDE-style)
    # ─────────────────────────────────────────────────────────

    def _refresh_status_bar(self):
        """Re-read Re / clock values and repaint the persistent status-bar
        widgets. Safe to call before the widgets exist (early startup) —
        silently no-ops."""
        if not hasattr(self, '_sb_re'):
            return
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
            from ui.plot_2d_results import redraw_temperature_panel
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

    def _load_user_presets(self):
        """Return the list of user-defined preset dicts (possibly empty).

        Delegates to SessionManager (Plan #4 P2.3).
        """
        return self.sm.load_user_presets()

    def _save_user_presets(self, presets):
        """Persist user preset list. Delegates to SessionManager (P2.3)."""
        self.sm.save_user_presets(presets)

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
        # Disable the export button — there is nothing to export.
        for _bname in ('btn_export',):
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

    def _load_named_preset(self, name):
        """Load a built-in canonical preset by name. Wired from the header
        载入 ▾ menu and the command palette (replaces the old index-based
        combo handler)."""
        if name not in self._BUILTIN_PRESETS:
            return
        self._active_preset_name = name
        if hasattr(self, '_refresh_status_bar'):
            self._refresh_status_bar()
        # Builtin presets rewrite inputs via _apply_shanghai_defaults, which
        # does NOT route through _apply_user_preset (where the result-cache
        # invalidate lives). Invalidate here so stale result tabs/plots/export
        # from a prior compute don't survive a builtin-preset switch.
        self._invalidate_results_for_preset_load()
        self._apply_shanghai_defaults()
        if name == "Shanghai (2D Gyroid)":
            self.combo_dim.setCurrentIndex(0)
        elif name == "Shanghai (3D Diamond)":
            self.combo_tpms.setCurrentIndex(0)
        self.statusBar().showMessage(f"Preset: {name}.", 5000)

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
        self._rebuild_recent_menu()
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
    _SESSION_CHECKS = ('chk_zones', 'chk_wall_refine_3d', 'chk_var_rhocp')

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
            # The app must open in the canonical Shanghai topology regardless
            # of what the previous session stored: fluids A=Air / B=Water and
            # crossflow directions A:+x / B:-y. Skip restoring these four so
            # the construction + _apply_shanghai_defaults values stand — a
            # stale session must not rotate the case (A:+y B:-x) or swap the
            # cold fluid back to Air.
            if name in ('combo_fluidA', 'combo_fluidB',
                        'combo_dirA', 'combo_dirB'):
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
        # 3. PyVistaQt GL context teardown — must happen before Qt
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
            "(menu → Optimize for qNEHVI optimization).\n"
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
             "Start qNEHVI Bayesian multi-objective search — runs for minutes to hours"),
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
            "2D/3D compressible D-F + SIMPLE with qNEHVI Bayesian zoning search.")
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


    # -------------------------------------------------------------------
    # ComputeOrchestrator signal handlers (Plan #4 Phase 1.2 — A.2 wiring).
    # Replace the raw threading.Thread + QTimer poll pattern in
    # run_calculation. orchestrator's signals auto-marshal to the GUI thread,
    # so these handlers run on the main thread (Qt-safe).
    # -------------------------------------------------------------------


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
            # Fit the 3D card to the scroll viewport now that the real panel is
            # in (avoids the fixed 1144 px card overflowing → scrollbar).
            _fit = getattr(self, '_fit_3d_card_to_viewport', None)
            if _fit is not None:
                try:
                    _fit()
                except Exception:
                    pass
            self.statusBar().showMessage("3D view initialised.", TOAST_MS_BRIEF)
        finally:
            self._lazy_init_3d_running = False


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
