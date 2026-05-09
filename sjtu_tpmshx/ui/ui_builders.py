"""UI construction helpers for SJTU-TPMSHX Main_Menu.

Extracted from main.py (Task B.6). All functions take `window` (Main_Menu
instance) as first argument. Widget attributes are stored directly on
`window` (`window.combo_tpms = ...`), preserving the original access pattern.

Intra-module calls use top-level function names (e.g., `build_param_tabs(window)`
instead of `window._build_param_tabs()`) so the wiring within this module is
direct. Calls to methods that remain in main.py use `window.xxx()` so Python's
dynamic dispatch resolves them on the Main_Menu instance.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QToolButton, QMenu, QComboBox, QScrollArea, QSplitter,
    QFrame, QSizePolicy,
    QSlider, QProgressBar, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)
from PySide6.QtGui import QColor
from .matplotlib_canvas import MatplotlibCanvas
from .theme import _build_styles, get_theme, get_theme_name


_WORKFLOW_STEPS = (
    ('geom',     'GEOMETRY'),
    ('bc',       'BOUNDARY'),
    ('zones',    'ZONES'),
    ('compute',  'COMPUTE'),
    ('optimize', 'OPTIMIZE'),
)


def _build_workflow_breadcrumb(window, _t):
    """Narrow horizontal strip — 5 stage pills with connector dashes.
    Active + completed states refreshed by `refresh_workflow_breadcrumb`.
    """
    host = QWidget()
    host.setFixedHeight(28)
    host.setStyleSheet(f"background:{_t.get('surface_base', _t['bg'])};")
    lay = QHBoxLayout(host)
    lay.setContentsMargins(16, 2, 16, 2); lay.setSpacing(4)
    lay.addStretch(1)

    _sub = _t.get('sub_fg', _t['fg'])
    _border = _t.get('border_subtle', _t['card_border'])
    window._wf_pill_styles = {
        'idle':   (f"QLabel{{color:{_sub}; font-size:8pt; font-weight:700;"
                    f"letter-spacing:1.5px; background:transparent;"
                    f"border:1px solid {_border}; border-radius:10px;"
                    f"padding:2px 10px;}}"),
        'active': (f"QLabel{{color:#FFFFFF; font-size:8pt; font-weight:700;"
                    f"letter-spacing:1.5px;"
                    f"background:{_t.get('accent_primary', '#3B82F6')};"
                    f"border:1px solid {_t.get('accent_primary', '#3B82F6')};"
                    f"border-radius:10px; padding:2px 10px;}}"),
        'done':   (f"QLabel{{color:#FFFFFF; font-size:8pt; font-weight:700;"
                    f"letter-spacing:1.5px;"
                    f"background:{_t.get('accent_green', '#22C55E')};"
                    f"border:1px solid {_t.get('accent_green', '#22C55E')};"
                    f"border-radius:10px; padding:2px 10px;}}"),
    }
    window._wf_pills = {}
    for i, (key, label) in enumerate(_WORKFLOW_STEPS):
        pill = QLabel(label)
        pill.setStyleSheet(window._wf_pill_styles['idle'])
        window._wf_pills[key] = pill
        lay.addWidget(pill)
        if i < len(_WORKFLOW_STEPS) - 1:
            dash = QLabel("——")
            dash.setStyleSheet(
                f"color:{_border}; background:transparent;"
                "border:none; font-size:9pt; padding:0 2px;")
            lay.addWidget(dash)
    lay.addStretch(1)
    window._wf_host = host
    return host


def refresh_workflow_breadcrumb(window):
    """Set each step pill's visual state based on live window state."""
    if not hasattr(window, '_wf_pills'):
        return
    styles = window._wf_pill_styles
    states = {k: 'idle' for k, _ in _WORKFLOW_STEPS}
    # Geometry always considered done once dims combo has a selection.
    states['geom'] = 'done'
    # Boundary done when fluid A + B combos + inlet temps populated.
    try:
        if (window.combo_fluidA.currentText()
                and window.combo_fluidB.currentText()
                and window.le_TinA.text().strip()
                and window.le_TinB.text().strip()):
            states['bc'] = 'done'
    except Exception:
        pass
    # Zones done whenever chk_zones enabled AND rows present.
    try:
        if window.chk_zones.isChecked() and window.zone_table.rowCount() > 0:
            states['zones'] = 'done'
    except Exception:
        pass
    # Compute / Optimize from has-results flags.
    if getattr(window, '_has_results', False):
        states['compute'] = 'done'
    if getattr(window, '_has_pareto', False):
        states['optimize'] = 'done'
    # Active pill = first non-done step.
    for k, _ in _WORKFLOW_STEPS:
        if states[k] != 'done':
            states[k] = 'active'
            break
    for k, pill in window._wf_pills.items():
        pill.setStyleSheet(styles.get(states[k], styles['idle']))


def _on_dim_changed(window):
    """Toggle visibility of 3D-only inputs based on Dimensionality combo."""
    is_3d = window.combo_dim.currentIndex() == 1
    widgets = [window.le_Lz, window._lbl_Lz, window.le_Nz, window._lbl_Nz]
    if hasattr(window, 'chk_wall_refine_3d'):
        widgets.append(window.chk_wall_refine_3d)
    # z-partial BC 4 fields per fluid (+ labels) — hidden in 2D mode
    for name in ('le_pipeA_in_z_ctr', 'le_pipeA_in_z_w',
                 'le_pipeA_out_z_ctr', 'le_pipeA_out_z_w',
                 '_lbl_pipeA_in_z_ctr', '_lbl_pipeA_in_z_w',
                 '_lbl_pipeA_out_z_ctr', '_lbl_pipeA_out_z_w',
                 'le_pipeB_in_z_ctr', 'le_pipeB_in_z_w',
                 'le_pipeB_out_z_ctr', 'le_pipeB_out_z_w',
                 '_lbl_pipeB_in_z_ctr', '_lbl_pipeB_in_z_w',
                 '_lbl_pipeB_out_z_ctr', '_lbl_pipeB_out_z_w'):
        if hasattr(window, name):
            widgets.append(getattr(window, name))
    for w in widgets:
        w.setVisible(is_3d)
    # Mode change also reveals/hides the result tabs for the current mode
    if hasattr(window, '_update_tab_visibility'):
        window._update_tab_visibility()


def build_ui(window):
    """Ex-Main_Menu._build_ui(self).
    Constructs the entire main window. Widgets are stored as attributes on
    `window` (e.g., `window.combo_tpms = QComboBox()`).
    """
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI.
    from .field_factory import default_factory
    f = default_factory()
    t = f.theme
    _BG = t.style('BG')

    cw = window.centralWidget()
    cw.setStyleSheet(f"background:{_BG};")

    root = QVBoxLayout(cw)
    root.setContentsMargins(8, 6, 8, 6)
    root.setSpacing(6)

    _t = get_theme()
    _hdr_btn_qss = (
        f"QPushButton{{background:{_t['hdr_btn_bg']}; border:1px solid {_t['hdr_btn_border']};"
        f"border-radius:6px; color:{_t['hdr_btn_fg']}; font-weight:bold; font-size:10pt;}}"
        f"QPushButton:hover{{background:{_t['hdr_btn_hover']}; color:{_t['hdr_fg']};}}"
        f"QPushButton:focus{{border:2px solid {_t['inp_focus']};}}"
        f"QPushButton:disabled{{color:rgba(255,255,255,0.35);}}")

    # Header bar: navy blue background strip
    header_widget = QWidget()
    header_widget.setStyleSheet(
        f"background:{_t['hdr_bg']}; border-radius:12px;")
    header_widget.setFixedHeight(44)
    header_row = QHBoxLayout(header_widget)
    header_row.setContentsMargins(8, 4, 8, 4)
    header_row.setSpacing(8)
    # SJTU banner (横版校徽+校名) — left side of header
    import os as _os_hdr
    from PySide6.QtGui import QPixmap
    _banner_path = _os_hdr.path.join(
        _os_hdr.path.dirname(_os_hdr.path.dirname(_os_hdr.path.abspath(__file__))),
        'sjtubannersilver.png' if get_theme_name() == 'dark' else 'sjtubannerred.png')
    banner_present = False
    if _os_hdr.path.exists(_banner_path):
        banner_lbl = QLabel()
        banner_lbl.setStyleSheet("background:transparent; border:none; padding:0;")
        banner_lbl.setToolTip("SJTU-TPMSHX · 上海交通大学")
        # HiDPI-aware scaling: request a pixmap at (logical height × dpr) and
        # tell the label the logical dpr so Qt draws crisply on 4K screens
        # instead of blurring a pre-scaled bitmap.
        _dpr = float(window.devicePixelRatioF() or 1.0)
        _logical_h = 30
        _px = QPixmap(_banner_path).scaledToHeight(
            int(_logical_h * _dpr),
            Qt.TransformationMode.SmoothTransformation)
        _px.setDevicePixelRatio(_dpr)
        banner_lbl.setPixmap(_px)
        banner_lbl.setFixedSize(
            int(_px.width() / _dpr), int(_px.height() / _dpr))
        header_row.addWidget(banner_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        header_row.addSpacing(12)
        banner_present = True
    # Show the project-code title only when the banner image is missing — the
    # banner already renders "SJTU-TPMSHX · 上海交通大学" itself, so repeating
    # the name here wastes header space.
    if not banner_present:
        hdr = QLabel("SJTU-TPMSHX")
        hdr.setStyleSheet(
            f"background:transparent; color:{_t['hdr_fg']}; font-size:11pt;"
            "font-weight:bold; border:none; padding:0;")
        hdr.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(hdr, 0)
    header_row.addStretch(1)
    # Preset picker — one-click load of canonical case configurations
    combo_preset = QComboBox()
    combo_preset.addItems([
        "Preset…",
        "Shanghai (3D Gyroid)",
        "Shanghai (2D Gyroid)",
        "Shanghai (3D Diamond)",
    ])
    combo_preset.setFixedHeight(32)
    combo_preset.setFixedWidth(190)
    combo_preset.setStyleSheet(t.style('COMBO'))
    combo_preset.setToolTip("Load a canonical case configuration")
    combo_preset.currentIndexChanged.connect(window._on_preset_selected)
    window.combo_preset = combo_preset
    header_row.addWidget(combo_preset, 0)
    header_row.addSpacing(6)

    # Theme toggle — icon reflects the theme you will switch TO, not the
    # current one (consistent with most desktop apps).
    btn_theme = QPushButton("☀" if get_theme_name() == 'dark' else "☾")
    btn_theme.setFixedSize(32, 32)
    btn_theme.setStyleSheet(_hdr_btn_qss)
    btn_theme.setToolTip(
        "Switch to light theme" if get_theme_name() == 'dark'
        else "Switch to dark theme")
    btn_theme.clicked.connect(window._toggle_theme)
    window.btn_theme = btn_theme
    header_row.addWidget(btn_theme, 0)
    header_row.addSpacing(6)

    # Help menu — About / Shortcuts / Quick tour. Pops a QMenu beneath the
    # button so users can discover shortcuts without hunting a menubar
    # (this app uses a custom header instead of QMainWindow.menuBar).
    btn_help = QPushButton("?")
    btn_help.setFixedSize(32, 32)
    btn_help.setStyleSheet(_hdr_btn_qss)
    btn_help.setToolTip(
        "Help — About, keyboard shortcuts, quick tour (Ctrl+?)")
    btn_help.clicked.connect(lambda: window._show_help_menu(btn_help))
    window.btn_help = btn_help
    header_row.addWidget(btn_help, 0)
    header_row.addSpacing(6)

    # Recent runs dropdown — populated after each successful compute so the
    # user can jump back to the last 5 parameter snapshots. QToolButton
    # because QPushButton can't render a persistent ▾ that opens on first
    # click; instantPopup keeps the menu one-click.
    btn_recent = QToolButton()
    btn_recent.setText("Recent ▾")
    btn_recent.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    btn_recent.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    btn_recent.setFixedHeight(32)
    btn_recent.setFixedWidth(92)
    btn_recent.setStyleSheet(
        _hdr_btn_qss.replace("QPushButton", "QToolButton"))
    btn_recent.setToolTip("Last 5 Compute runs — click to restore inputs")
    window.btn_recent = btn_recent
    header_row.addWidget(btn_recent, 0)
    header_row.addSpacing(6)
    # Seed an empty menu so the first click behaves as "no recent runs"
    # rather than silently doing nothing because menu is None.
    window._rebuild_recent_menu()

    # Workspace selector — three independent session slots (A/B/C). Lets
    # users keep a comparative parameter set parked (e.g., "Shanghai air"
    # vs "Water-loop sweep") and flip between them without losing either.
    btn_ws = QToolButton()
    btn_ws.setText("WS: A ▾")
    btn_ws.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    btn_ws.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    btn_ws.setFixedHeight(32)
    btn_ws.setFixedWidth(76)
    btn_ws.setStyleSheet(
        _hdr_btn_qss.replace("QPushButton", "QToolButton"))
    btn_ws.setToolTip("Switch between workspace A / B / C — each has its "
                      "own persisted parameter state")
    window.btn_workspace = btn_ws
    header_row.addWidget(btn_ws, 0)
    header_row.addSpacing(6)
    window._rebuild_workspace_menu()

    # Temperature unit toggle (K ↔ °C). Label shows the CURRENT unit so the
    # user knows what they're looking at; click flips display values.
    btn_temp_unit = QPushButton(
        "°C" if getattr(window, '_temp_unit', 'K') == 'C' else "K")
    btn_temp_unit.setFixedSize(36, 32)
    btn_temp_unit.setStyleSheet(_hdr_btn_qss)
    btn_temp_unit.setToolTip(
        "Temperatures currently in K. Click to switch K ↔ °C.")
    btn_temp_unit.clicked.connect(window._toggle_temp_unit)
    window.btn_temp_unit = btn_temp_unit
    header_row.addWidget(btn_temp_unit, 0)
    header_row.addSpacing(6)

    btn_reset = QPushButton("\u21ba  &Reset")
    btn_reset.setFixedHeight(32)
    btn_reset.setFixedWidth(100)
    btn_reset.setStyleSheet(
        _hdr_btn_qss)
    btn_reset.setToolTip("Reset all parameters to Shanghai Electric preset (Ctrl+Shift+R)")
    btn_reset.clicked.connect(window._reset_defaults)
    header_row.addWidget(btn_reset, 0)
    header_row.addSpacing(6)
    # Single-action Compute button. Optimize lives in the left
    # Optimization panel + Ctrl+K command palette, so no duplicate entry
    # here — keeps the header tidy and drops the split-arrow affordance.
    btn_run = QPushButton("\u25b6  &Compute")
    btn_run.setFixedHeight(32)
    btn_run.setMinimumWidth(160)
    btn_run.setStyleSheet(t.style('BTN_PRIMARY'))
    btn_run.setToolTip("Run single-point compute (Ctrl+R)")
    btn_run.clicked.connect(window.run_calculation)
    window.btn_compute = btn_run
    header_row.addWidget(btn_run, 0)
    header_row.addSpacing(6)
    btn_export = QPushButton("&Export Results")
    btn_export.setFixedHeight(32)
    btn_export.setFixedWidth(120)
    btn_export.setStyleSheet(t.style('BTN_SECONDARY'))
    btn_export.setToolTip("Export results (CSV + NPZ) to file")
    btn_export.setEnabled(False)
    btn_export.clicked.connect(window._export_results)
    window.btn_export_results = btn_export
    header_row.addWidget(btn_export, 0)
    root.addWidget(header_widget, 0)

    # E5 (removed per user request) — workflow breadcrumb strip used to
    # show GEOMETRY → BOUNDARY → ZONES → COMPUTE → OPTIMIZE pills here,
    # but the steps duplicated the left-panel collapsibles and the
    # progress bar already covers compute state, so the strip was just
    # noise. `refresh_workflow_breadcrumb` no-ops when `_wf_pills` isn't
    # populated, so leaving the call sites alone is safe.

    # Splitter: 1px separator — narrow band that reads as a divider,
    # widens on hover for a grab affordance.
    splitter = QSplitter(Qt.Orientation.Horizontal)
    _sep_col = _t.get('card_border', _t['splitter'])
    splitter.setHandleWidth(1)
    splitter.setStyleSheet(
        f"QSplitter::handle{{background:{_sep_col};}}"
        f"QSplitter::handle:hover{{background:{_t['splitter_hover']};}}")
    # Non-opaque resize: only recompute layout on mouse release. The rubber
    # band indicator drags at screen refresh rate, avoiding per-pixel child
    # re-layout which was causing noticeable drag lag on the 3D panel side.
    splitter.setOpaqueResize(False)
    splitter.setChildrenCollapsible(False)
    splitter.addWidget(build_param_tabs(window))
    splitter.addWidget(build_canvas_area(window))
    splitter.setStretchFactor(0, 35)
    splitter.setStretchFactor(1, 65)
    splitter.setSizes([400, 800])
    window._splitter = splitter
    root.addWidget(splitter, 1)


def build_param_tabs(window):
    """Left-panel parameter groups — collapsible accordion layout."""
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI.
    from .field_factory import default_factory
    from .theme import _THEMES as _THEMES_local
    f = default_factory()
    t = f.theme
    _BG = t.style('BG')

    # Canvas-tab styles: flat underline indicator instead of the older filled
    # pill. Active tab shows a 2px accent bar along the bottom edge; hover on
    # inactive tabs lightens the label without adding a second bar.
    _ts = get_theme()
    _accent = _ts['tab_on_bg']
    window._PTAB_ON  = (
        f"QPushButton{{color:{_accent};"
        "background:transparent; border:none;"
        f"border-bottom:2px solid {_accent};"
        "font-weight:bold; font-size:9pt; padding:6px 14px 4px 14px;}")
    window._PTAB_OFF = (
        f"QPushButton{{color:{_ts['tab_off_fg']};"
        "background:transparent; border:none;"
        "border-bottom:2px solid transparent;"
        "font-size:9pt; font-weight:500; padding:6px 14px 4px 14px;}"
        f"QPushButton:hover{{color:{_ts['fg']};"
        f"border-bottom:2px solid {_ts['tab_off_border']};}}"
        f"QPushButton:focus{{color:{_ts['fg']};"
        f"border-bottom:2px solid {_ts['inp_focus']};}}")
    # ★ fix #3 (2026-05-09) — disabled tabs explicitly drop bold + use a dimmer
    # foreground so the global QApplication Bold (Phase 3) doesn't make
    # disabled and enabled tabs visually identical.
    window._PTAB_DISABLED = (
        f"QPushButton{{color:rgba(255,255,255,40);"
        "background:transparent; border:none;"
        "border-bottom:2px solid transparent;"
        "font-size:9pt; font-weight:normal; padding:6px 14px 4px 14px;}")

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    # 8px track, semi-transparent handle — quieter than the old 10px slab but
    # still grabbable. Codex review 2026-04-22: "rgba(0.1)/0.2 on hover".
    scroll.setStyleSheet(
        f"QScrollArea{{background:{_BG}; border:none;}}"
        f"QScrollBar:vertical{{background:transparent; width:8px; border:none; margin:2px;}}"
        f"QScrollBar::handle:vertical{{background:{_ts['scroll_handle']};"
        f"border-radius:4px; min-height:30px;}}"
        f"QScrollBar::handle:vertical:hover{{background:{_ts['scroll_handle_hover']};}}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{{height:0;}}")
    scroll.setMinimumWidth(240)

    # Top-level accordion group: 12pt + 3px left accent bar, gray title strip
    _GRP_QSS = (
        "QGroupBox {"
        f"  font-size:12pt; font-weight:600; color:{_ts['fg']};"
        f"  background:transparent; border:none;"
        "  margin-top:12px; padding-top:38px;"
        "}"
        "QGroupBox::title {"
        f"  subcontrol-origin:margin; subcontrol-position:top left;"
        f"  left:0px; right:0px;"
        f"  background:{_ts['card_bg']}; color:{_ts['fg']};"
        f"  border-left:3px solid {_ts['group_accent']};"
        f"  border-bottom:1px solid {_ts['card_border']};"
        f"  border-top-left-radius:4px; border-top-right-radius:4px;"
        "  padding:10px 12px 10px 16px; min-height:20px; letter-spacing:0.3px;"
        "}"
        "QGroupBox::indicator {"
        "  width:0px; height:0px; margin:0px; padding:0px;"
        "  border:none; image:none;"
        "}"
        "QGroupBox::indicator:checked { image:none; }"
        "QGroupBox::indicator:unchecked { image:none; }"
    )

    page_geometry = build_page_domain(window)
    page_boundary = build_page_fluids(window)
    # Zone configuration now lives inside the Optimize tab (QSplitter on
    # the left side). The builder still runs here so the attached widgets
    # (zone_table, chk_zones, +Row/-Row, combo_zone_axis, etc.) exist on
    # the window before other builders reference them; `build_canvas_area`
    # then lifts the returned panel into the Optimize card.
    page_zone_layout = build_page_zones(window)
    window._zone_panel = page_zone_layout
    # Optimization UI now lives in its own top canvas tab (Plan D).

    from PySide6.QtWidgets import QGroupBox

    def _chevron_title(title, expanded):
        return f"▾  {title}" if expanded else f"▸  {title}"

    container = QWidget()
    container.setStyleSheet(f"background:{_BG};")
    vlay = QVBoxLayout(container)
    # Accordion: 8px outer padding + 12px gap between top-level groups.
    # Group's own margin-top:12px pushes total inter-group spacing to ~24px.
    vlay.setContentsMargins(6, 4, 6, 4)
    vlay.setSpacing(12)

    window._accordion_groups = {}
    for title, page, default_open in [
        ("Geometry",            page_geometry,      True),
        ("Boundary Conditions", page_boundary,      True),
    ]:
        grp = QGroupBox(_chevron_title(title, default_open))
        grp.setCheckable(True)
        grp.setChecked(default_open)
        grp.setStyleSheet(_GRP_QSS)
        grp_lay = QVBoxLayout(grp)
        grp_lay.setContentsMargins(4, 4, 4, 4)
        grp_lay.setSpacing(0)
        grp_lay.addWidget(page)
        page.setVisible(default_open)
        grp.toggled.connect(lambda checked, p=page, t=title, g=grp: (
            p.setVisible(checked),
            g.setTitle(_chevron_title(t, checked)),
        ))
        vlay.addWidget(grp)
        window._accordion_groups[title] = grp

    vlay.addStretch(1)
    scroll.setWidget(container)

    window._param_stack = None
    window._param_btns = []

    return scroll


def switch_param_tab(window, index):
    """Expand accordion group by index.

    Mapping (post 2026-04-22 restructure):
      0 = Geometry, 1 = Boundary Conditions, 2 = Zone Layout, 3 = Optimization
    """
    names = ["Geometry", "Boundary Conditions", "Zone Layout", "Optimization"]
    groups = getattr(window, '_accordion_groups', {})
    if 0 <= index < len(names):
        grp = groups.get(names[index])
        if grp is not None:
            grp.setChecked(True)
            from PySide6.QtWidgets import QScrollArea
            from PySide6.QtCore import QTimer
            w = grp.parent()
            while w and not isinstance(w, QScrollArea):
                w = w.parent()
            if w:
                QTimer.singleShot(50, lambda: w.ensureWidgetVisible(grp))


def build_page_domain(window):
    """Ex-Main_Menu._build_page_domain(self) -> QScrollArea."""
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI.
    from .field_factory import default_factory
    f = default_factory()
    t = f.theme
    _BG = t.style('BG')
    _T_NEUTRAL = t.style('T_NEUTRAL')
    _F_NEUTRAL = t.style('F_NEUTRAL')
    _COMBO = t.style('COMBO')
    _BTN_TPMS = t.style('BTN_TPMS')
    _LBL = t.style('LBL')
    _VAL = t.style('VAL')

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("border:none; background:transparent;")

    w = QWidget(); w.setStyleSheet(f"background:{_BG};")
    lay = QVBoxLayout(w)
    lay.setSpacing(12); lay.setContentsMargins(6, 4, 8, 6)

    # Domain Geometry
    g, _ = section(window, lay, "  Domain Geometry", _T_NEUTRAL, _F_NEUTRAL)
    window.le_L        = row(window, g, 0, "Length <i>L</i> [m]",                     "0.182")
    window.le_H        = row(window, g, 1, "Width <i>H</i> [m]",                      "0.042")
    window.le_Lz       = row(window, g, 2, "Depth <i>L<sub>z</sub></i> [m] (3D only)", "0.042")
    window._lbl_Lz     = g.itemAtPosition(2, 0).widget()

    # Update edge labels when L or H changes
    window.le_L.editingFinished.connect(window._update_edge_combos)
    window.le_H.editingFinished.connect(window._update_edge_combos)

    # Domain shape selector
    window.combo_shape = QComboBox()
    window.combo_shape.addItems(["Rectangle", "Hexagon", "Octagon"])
    window.combo_shape.setStyleSheet(_COMBO)
    window.combo_shape.currentIndexChanged.connect(window._on_shape_changed)
    add_row(window, g, 3, "Domain shape", window.combo_shape)

    # Dimensionality (2D / 3D MVP) — dispatch in run_calculation
    window.combo_dim = QComboBox()
    window.combo_dim.addItems(["2D", "3D"])
    window.combo_dim.setStyleSheet(_COMBO)
    window.combo_dim.currentIndexChanged.connect(
        lambda *_: _on_dim_changed(window))
    add_row(window, g, 4, "Dimensionality", window.combo_dim)

    # ── TPMS Structure ──
    g0, _ = section(window, lay, "  TPMS Structure", _T_NEUTRAL, _F_NEUTRAL)
    window.combo_tpms = QComboBox()
    window.combo_tpms.addItems(["Diamond", "Gyroid"])
    window.combo_tpms.setCurrentIndex(1)  # default Gyroid
    window.combo_tpms.setStyleSheet(_COMBO)
    add_row(window, g0, 0, "Type", window.combo_tpms)
    window.le_Lcell = row(window, g0, 1, "<i>L</i><sub>cell</sub> [mm]", "7.0")
    # t default: 0.5 mm sits at the upper bound of the ConstDF-v1 surrogate
    # training window [0.3, 0.5] so the default GUI run does NOT trigger
    # the extrapolation watermark every time. Users wanting t=0.6 mm (the
    # original Shanghai geometry) must edit explicitly and acknowledge the
    # extrap warning that follows. Re-train the surrogate to expand the
    # range when new CFD data arrives.
    window.le_t     = row(window, g0, 2, "<i>t</i> [mm]", "0.5")
    window.le_ks    = row(window, g0, 3, "<i>k</i><sub>s</sub> [W/(m\u00b7K)]", "16.0")
    btn_tpms = QPushButton("Compute TPMS &Geometry")
    btn_tpms.setFixedHeight(28); btn_tpms.setStyleSheet(t.style('BTN_SECONDARY'))
    btn_tpms.setToolTip("Compute porosity, specific area, hydraulic diameter, k_ss from current L_cell / t")
    btn_tpms.clicked.connect(window.compute_tpms)
    g0.addWidget(btn_tpms, 4, 0, 1, 2)
    # Computed outputs (green values)
    window._v_eps  = res_row(window, g0, 5, "<i>&epsilon;</i>")
    window._v_A0   = res_row(window, g0, 6, "<i>A</i><sub>0</sub> [m<sup>-1</sup>]")
    window._v_Dh   = res_row(window, g0, 7, "<i>D<sub>h</sub></i> [mm]")
    window._v_Kss  = res_row(window, g0, 8, "<i>K</i><sub>ss</sub> [W/(m\u00b7K)]")

    # Surrogate-domain guard. Default ON \u2014 near-boundary extrapolation
    # (e.g. Shanghai t=0.6 mm, 20% past the [0.3, 0.5] cap) is the common
    # validation workflow. Unchecking reverts to strict: out-of-window
    # inputs abort Compute. Either way, extrapolated results carry an
    # `extrapolated=True` flag and a watermark on every plot for
    # traceability.
    window.chk_allow_extrap = QCheckBox("Allow surrogate extrapolation")
    window.chk_allow_extrap.setChecked(True)
    window.chk_allow_extrap.setToolTip(
        "ConstDF-v1 \u8bad\u7ec3\u57df: L \u2208 [4, 8] mm, t \u2208 [0.3, 0.5] mm, Re \u2208 [400, 16000].\n"
        "\u9ed8\u8ba4\u4e25\u683c: \u8d85\u51fa\u4efb\u4e00\u8303\u56f4 Compute \u62d2\u7edd\u8fd0\u884c.\n"
        "\u52fe\u9009\u540e: \u8d85\u51fa\u4ec5 warn, \u7ed3\u679c\u6807\u8bb0\u4e3a extrapolated, \u56fe\u4e0a\u52a0\u6c34\u5370.\n"
        "\u7528\u4e8e Shanghai t=0.6 mm \u7b49\u8fd1\u8fb9\u754c\u9a8c\u8bc1\u5de5\u51b5."
    )
    _extrap_t = get_theme()
    window.chk_allow_extrap.setStyleSheet(
        f"QCheckBox{{color:{_extrap_t['fg']}; font-size:9pt; background:transparent;}}"
        f"QCheckBox::indicator{{width:14px; height:14px;"
        f"border:1px solid {_extrap_t['chk_indicator_border']};"
        f"border-radius:3px; background:{_extrap_t['chk_bg']};}}"
        f"QCheckBox::indicator:checked{{background:{_extrap_t['chk_checked_bg']};"
        f"border-color:{_extrap_t['chk_checked_border']};}}")
    g0.addWidget(window.chk_allow_extrap, 9, 0, 1, 2)

    # Material \u2014 only rho_s remains (k_s is in the solver/geometry panel).
    # cp_s and cp_f were removed: no solver path reads them. Solid cp is a
    # per-material constant hardcoded downstream; fluid cp is computed
    # per-cell via air_cp(T) inside tpms_calc.
    g2, _ = section(window, lay, "  Material Properties", _T_NEUTRAL, _F_NEUTRAL)
    window.le_rho_s = row(window, g2, 0, "<i>&rho;</i><sub>s</sub> [kg/m\u00b3]", "7900")
    # rho_s is NOT consumed by the steady-state LTNE energy equation
    # (\u2202T_s/\u2202t is dropped \u2192 \u03c1_s\u00b7cp_s prefactor disappears). It is saved with
    # the session config for forward compatibility with a future transient
    # extension (kernel would add \u03c1_s\u00b7cp_s\u00b7(T_s^{n+1}\u2212T_s^n)/\u0394t).
    window.le_rho_s.setToolTip(
        "Solid density. Saved with session config but NOT read by the "
        "current steady-state LTNE solver (no \u2202T_s/\u2202t term in the solid "
        "energy equation). Reserved for a future transient extension.")
    # T_s_init removed from UI (2026-04-29) -- was numerical iteration seed
    # only, not a physical parameter. Solver auto-seeds at 0.5*(T_inA+T_inB);
    # converged Ts is independent of seed within solver tolerance. Removed to
    # avoid user confusion. _parse_inputs falls back to None when le_TsInit
    # absent via getattr().

    # ── Grid Settings (rect mode) ──
    g4, sec_solver_rect = section(window, lay, "  Grid Settings", _T_NEUTRAL, _F_NEUTRAL)
    window._rect_only_widgets.append(sec_solver_rect)
    window.le_Nx = row(window, g4, 0, "Grid <i>N<sub>x</sub></i>", "30")
    window.le_Ny = row(window, g4, 1, "Grid <i>N<sub>y</sub></i>", "20")
    window.le_Nz = row(window, g4, 2, "Grid <i>N<sub>z</sub></i> (3D only)", "5")
    window._lbl_Nz = g4.itemAtPosition(2, 0).widget()

    # 3D wall-refine checkbox — adds 8 BL cells near each wall (all 6 faces).
    # OFF by default (5-15× faster, ~1pp accuracy cost). Turn ON for production
    # validation runs where dP near-wall BL matters more than UX speed.
    window.chk_wall_refine_3d = QCheckBox("6-wall BL refine (3D)")
    window.chk_wall_refine_3d.setChecked(False)
    window.chk_wall_refine_3d.setToolTip(
        "Enable six-wall boundary-layer refinement for 3D solves. "
        "Adds 8 cells per wall (first_cell=0.02 mm, growth 1.8). "
        "ON: 5-15× slower, ~+1pp dP accuracy. OFF: production-fast (default).")
    _tc = get_theme()
    window.chk_wall_refine_3d.setStyleSheet(f"""
        QCheckBox {{
            color: {_tc['fg']};
            font-size: 10pt;
            font-weight: bold;
            background: {_tc['chk_bg']};
            border: 1px solid {_tc['chk_border']};
            border-radius: 6px;
            padding: 6px 10px;
            spacing: 8px;
        }}
        QCheckBox:hover {{ border-color: {_tc['chk_hover_border']}; background: {_tc['chk_hover_bg']}; }}
        QCheckBox::indicator {{
            width: 16px; height: 16px;
            border: 1.5px solid {_tc['chk_indicator_border']};
            border-radius: 3px;
            background: {_tc['chk_bg']};
        }}
        QCheckBox::indicator:hover {{ border-color: {_tc['chk_hover_border']}; }}
        QCheckBox::indicator:checked {{
            background: {_tc['chk_checked_bg']};
            border-color: {_tc['chk_checked_border']};
            image: none;
        }}
        QCheckBox:focus {{
            outline: 0;
            border: 2px solid {_tc['inp_focus']};
        }}
    """)
    g4.addWidget(window.chk_wall_refine_3d, 3, 0, 1, 2)
    # NOTE: legacy `_chk_wall_refine_3d` alias removed 2026-05-05 audit;
    # no remaining readers (grep confirmed). Use `chk_wall_refine_3d`.

    # Hide 3D-only inputs by default (2D mode)
    _on_dim_changed(window)

    # ── Solver Settings (polygon mode) ──
    gp, sec_solver_poly = section(window, lay, "  Mesh Settings", _T_NEUTRAL, _F_NEUTRAL)
    window._poly_only_widgets.append(sec_solver_poly)
    sec_solver_poly.hide()  # hidden by default (rect mode)
    window.le_mesh_density = row(window, gp, 0, "Target cells", "auto")
    window._v_mesh_actual  = res_row(window, gp, 1, "Actual cells")

    # ── Results ──
    res_frame = QFrame()
    res_frame.setStyleSheet(_F_NEUTRAL)
    rg = QGridLayout(res_frame)
    rg.setContentsMargins(14, 8, 14, 8)
    rg.setHorizontalSpacing(20); rg.setVerticalSpacing(6)
    rg.setColumnStretch(0, 2); rg.setColumnStretch(1, 1)
    rg.setColumnStretch(2, 2); rg.setColumnStretch(3, 1)
    for c, txt in enumerate(["\u2500\u2500 Fluid A \u2500\u2500", "\u2500\u2500 Fluid B \u2500\u2500"]):
        h = QLabel(txt)
        h.setStyleSheet(_LBL)
        h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rg.addWidget(h, 0, c * 2, 1, 2)
    window._r_ToutA = res_row(window, rg, 1, "<i>T</i><sub>out</sub> [K]", 0)
    window._r_ToutB = res_row(window, rg, 1, "<i>T</i><sub>out</sub> [K]", 2)
    window._r_dP_A  = res_row(window, rg, 2, "\u0394<i>P</i><sub>total</sub> [Pa]", 0)
    window._r_dP_B  = res_row(window, rg, 2, "\u0394<i>P</i><sub>total</sub> [Pa]", 2)
    window._r_Q     = res_row(window, rg, 3, "<i>Q</i><sub>total</sub> [W/m]", 0)
    # Document which Q metric is shown so users don't conflate it with the
    # other diagnostics in the result dict (Q_solid_B, Q_sA, Q_sB,
    # Q_interior). Run_calculation_3d.py:1510 sets primary Q =
    # mean(Q_enthalpy_A, Q_enthalpy_B) when both fluids solve, else
    # Q_enthalpy_A alone.
    try:
        window._r_Q.setToolTip(
            "Primary heat transfer rate.\n"
            "Q = 0.5 · (Q_enthalpy_A + Q_enthalpy_B) when both fluids solve\n"
            "  = |m_dot · cp · (T_in − T_out)| per side\n"
            "  = Q_enthalpy_A alone when Fluid B is frozen.\n"
            "Diagnostic metrics (Q_solid_B, Q_sA/Q_sB, Q_interior) are "
            "exported in the result dict but NOT shown here.")
    except Exception:
        pass
    lay.addWidget(res_frame, 0)

    lay.addStretch()
    scroll.setWidget(w)
    return scroll


def build_page_fluids(window):
    """Ex-Main_Menu._build_page_fluids(self) -> QScrollArea."""
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI.
    # _THEMES is the raw palette registry from ui.theme — pulled
    # directly rather than through ThemeManager which only mirrors
    # style strings.
    from .field_factory import default_factory
    from .theme import _THEMES as _THEMES_local
    f = default_factory()
    t = f.theme
    _BG = t.style('BG')
    _T_A = t.style('T_A')
    _F_A = t.style('F_A')
    _T_B = t.style('T_B')
    _F_B = t.style('F_B')
    _T_NEUTRAL = t.style('T_NEUTRAL')
    _F_NEUTRAL = t.style('F_NEUTRAL')
    _COMBO = t.style('COMBO')
    _BTN_A = t.style('BTN_A')
    _BTN_B = t.style('BTN_B')
    _BTN_TPMS = t.style('BTN_TPMS')

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("border:none; background:transparent;")

    w = QWidget(); w.setStyleSheet(f"background:{_BG};")
    lay = QVBoxLayout(w)
    lay.setSpacing(12); lay.setContentsMargins(8, 4, 6, 6)

    # Pack Fluid A and Fluid B side-by-side in a horizontal row. When the
    # left panel is wide enough (≳ 520 px) the two cards sit next to each
    # other, halving the vertical scroll footprint. When narrower, Qt's own
    # layout engine will wrap/compress them gracefully; a follow-up
    # resize-to-stack responsive pass can swap to QVBoxLayout below a
    # threshold if it proves ugly in practice.
    _fluids_row = QWidget()
    _fluids_row.setStyleSheet("background:transparent;")
    _fluids_row_lay = QHBoxLayout(_fluids_row)
    _fluids_row_lay.setContentsMargins(0, 0, 0, 0)
    _fluids_row_lay.setSpacing(10)
    lay.addWidget(_fluids_row)

    # ── Fluid A (input + computed) ────────────────────────
    g1, _ = section(window, _fluids_row_lay, "Fluid A", _T_A, _F_A)
    _FLUID_TYPES = ["Air", "Water", "sCO₂"]
    # Fluid A only supports Air right now (Water needs an incompressible
    # SIMPLE A path; sCO₂ needs a real-gas property table). Disabling the
    # unsupported combo entries instead of hiding them keeps the option
    # visible as a "coming soon" hint without letting users hit
    # NotImplementedError at compute time. See run_calculation_3d.py:954-957.
    window.combo_fluidA = QComboBox()
    window.combo_fluidA.addItems(_FLUID_TYPES)
    window.combo_fluidA.setCurrentIndex(0)
    window.combo_fluidA.setStyleSheet(_COMBO)
    window.combo_fluidA.setToolTip(
        "Fluid A currently supports Air only.\n"
        "Water and sCO₂ are reserved (greyed) — solver blocks them.")
    # Disable Water (1) and sCO₂ (2) on Fluid A side
    try:
        _modelA = window.combo_fluidA.model()
        for _idx in (1, 2):
            _it = _modelA.item(_idx)
            if _it is not None:
                _it.setEnabled(False)
                _it.setToolTip(
                    "Not yet supported for Fluid A — see "
                    "run_calculation_3d.py:954 (Water needs incompressible "
                    "SIMPLE A path; sCO₂ needs real-gas property table).")
    except Exception:
        pass
    add_row(window, g1, 0, "Fluid type", window.combo_fluidA)
    window.le_uA   = row(window, g1, 1, "<i>u</i><sub>A</sub> [m/s]",  "20.0")
    window.le_TinA = row(window, g1, 2, "<i>T</i><sub>in</sub> [K]",   "422.0")
    window._lbl_TinA_unit = g1.itemAtPosition(2, 0).widget()
    window.le_PinA = row(window, g1, 3, "<i>P</i><sub>in</sub> [Pa]",  "192362")
    _computed_divider(g1, 4)
    window._v_rhoA = res_row(window, g1, 5, "<i>&rho;</i> [kg/m\u00b3]")
    window._v_ReA  = res_row(window, g1, 6, "Re")
    window._v_NuA  = res_row(window, g1, 7, "Nu")
    window._v_dPLA = res_row(window, g1, 8, "d<i>P</i>/d<i>L</i> [Pa/m]")
    btn_a = QPushButton("Auto-&fill A")
    btn_a.setFixedHeight(28); btn_a.setStyleSheet(t.style('BTN_SECONDARY'))
    btn_a.setToolTip("Compute Fluid A density / Reynolds / Nusselt / dP·dL from current state")
    btn_a.clicked.connect(window.auto_fill_fluid_a)
    g1.addWidget(btn_a, 10, 0, 1, 2)

    # ── Fluid B (input + computed) — sits to the right of Fluid A ─────
    g2b, _ = section(window, _fluids_row_lay, "Fluid B", _T_B, _F_B)
    # Fluid B supports Air + Water (incompressible SIMPLE B path is wired,
    # see run_calculation_3d.py:910-917). sCO₂ remains unsupported until
    # a real-gas property table is added.
    window.combo_fluidB = QComboBox()
    window.combo_fluidB.addItems(_FLUID_TYPES)
    window.combo_fluidB.setCurrentIndex(0)
    window.combo_fluidB.setStyleSheet(_COMBO)
    window.combo_fluidB.setToolTip(
        "Fluid B supports Air and Water.\n"
        "sCO₂ is reserved (greyed) — solver blocks it.")
    try:
        _modelB = window.combo_fluidB.model()
        _it = _modelB.item(2)   # sCO₂
        if _it is not None:
            _it.setEnabled(False)
            _it.setToolTip(
                "Not yet supported for Fluid B — needs real-gas property "
                "table. See run_calculation_3d.py:962.")
    except Exception:
        pass
    add_row(window, g2b, 0, "Fluid type", window.combo_fluidB)
    # Fluid B defaults: air-air startup scenario with B as the cold side.
    # u_B=10.0 m/s sits in the same magnitude as Fluid A (20.0 m/s) and
    # keeps Re inside the validated correlation range [600, 30000] for
    # typical TPMS D_h. T_inB=293.15 K (20 °C) and P_inB=101325 Pa
    # (standard atmosphere) give a clean reference cold-side ambient.
    # Driving ΔT = T_inA − T_inB ≈ 129 K provides enough thermal headroom
    # for an LTNE air-air run without further user tuning.
    window.le_uB   = row(window, g2b, 1, "<i>u</i><sub>B</sub> [m/s]",  "10.0")
    window.le_TinB = row(window, g2b, 2, "<i>T</i><sub>in</sub> [K]",   "293.15")
    window._lbl_TinB_unit = g2b.itemAtPosition(2, 0).widget()
    window.le_PinB = row(window, g2b, 3, "<i>P</i><sub>in</sub> [Pa]",  "101325")
    _computed_divider(g2b, 4)
    window._v_rhoB = res_row(window, g2b, 5, "<i>&rho;</i> [kg/m\u00b3]")
    window._v_ReB  = res_row(window, g2b, 6, "Re")
    window._v_NuB  = res_row(window, g2b, 7, "Nu")
    window._v_dPLB = res_row(window, g2b, 8, "d<i>P</i>/d<i>L</i> [Pa/m]")
    btn_b = QPushButton("Auto-fill &B")
    btn_b.setFixedHeight(28); btn_b.setStyleSheet(t.style('BTN_SECONDARY'))
    btn_b.setToolTip("Compute Fluid B density / Reynolds / Nusselt / dP·dL from current state")
    btn_b.clicked.connect(window.auto_fill_fluid_b)
    g2b.addWidget(btn_b, 10, 0, 1, 2)

    # ── Inlet / Outlet configuration (unified) ─────────────
    _DIR_ITEMS = ["+x  (left \u2192 right)", "-x  (right \u2192 left)",
                  "+y  (bottom \u2192 top)", "-y  (top \u2192 bottom)",
                  "+z  (front \u2192 back, 3D)", "-z  (back \u2192 front, 3D)"]

    gio, sec_pipeA = section(window, lay, "  Fluid A  Inlet / Outlet", _T_A, _F_A)
    window._rect_only_widgets.append(sec_pipeA)
    window.combo_dirA = QComboBox(); window.combo_dirA.addItems(_DIR_ITEMS)
    window.combo_dirA.setCurrentIndex(0)  # default +x
    window.combo_dirA.setStyleSheet(_COMBO)
    window.combo_dirA.currentIndexChanged.connect(window._on_dir_changed)
    add_row(window, gio, 0, "Flow direction", window.combo_dirA)
    window.le_pipeA_in_ctr  = row(window, gio, 1, "Inlet centre [m]",   "0.021")
    window._lbl_pipeA_in_ctr  = gio.itemAtPosition(1, 0).widget()
    window.le_pipeA_in_w    = row(window, gio, 2, "Inlet width [m]",    "0.042")
    window._lbl_pipeA_in_w    = gio.itemAtPosition(2, 0).widget()
    window.le_pipeA_out_ctr = row(window, gio, 3, "Outlet centre [m]",  "0.021")
    window._lbl_pipeA_out_ctr = gio.itemAtPosition(3, 0).widget()
    window.le_pipeA_out_w   = row(window, gio, 4, "Outlet width [m]",   "0.042")
    window._lbl_pipeA_out_w   = gio.itemAtPosition(4, 0).widget()
    # 3D-only z-partial BC (hidden in 2D — default full-depth)
    window.le_pipeA_in_z_ctr  = row(window, gio, 5,
                                     "Inlet z-centre [m] (3D)",  "0.021")
    window._lbl_pipeA_in_z_ctr  = gio.itemAtPosition(5, 0).widget()
    window.le_pipeA_in_z_w    = row(window, gio, 6,
                                     "Inlet z-width [m] (3D)",   "0.042")
    window._lbl_pipeA_in_z_w    = gio.itemAtPosition(6, 0).widget()
    window.le_pipeA_out_z_ctr = row(window, gio, 7,
                                     "Outlet z-centre [m] (3D)", "0.021")
    window._lbl_pipeA_out_z_ctr = gio.itemAtPosition(7, 0).widget()
    window.le_pipeA_out_z_w   = row(window, gio, 8,
                                     "Outlet z-width [m] (3D)",  "0.042")
    window._lbl_pipeA_out_z_w   = gio.itemAtPosition(8, 0).widget()

    gio2, sec_pipeB = section(window, lay, "  Fluid B  Inlet / Outlet", _T_B, _F_B)
    window._rect_only_widgets.append(sec_pipeB)
    window.combo_dirB = QComboBox(); window.combo_dirB.addItems(_DIR_ITEMS)
    window.combo_dirB.setCurrentIndex(3)  # default -y (crossflow)
    window.combo_dirB.setStyleSheet(_COMBO)
    window.combo_dirB.currentIndexChanged.connect(window._on_dir_changed)
    add_row(window, gio2, 0, "Flow direction", window.combo_dirB)
    window.le_pipeB_in_ctr  = row(window, gio2, 1, "Inlet centre [m]",   "0.154")
    window._lbl_pipeB_in_ctr  = gio2.itemAtPosition(1, 0).widget()
    window.le_pipeB_in_w    = row(window, gio2, 2, "Inlet width [m]",    "0.042")
    window._lbl_pipeB_in_w    = gio2.itemAtPosition(2, 0).widget()
    window.le_pipeB_out_ctr = row(window, gio2, 3, "Outlet centre [m]",  "0.028")
    window._lbl_pipeB_out_ctr = gio2.itemAtPosition(3, 0).widget()
    window.le_pipeB_out_w   = row(window, gio2, 4, "Outlet width [m]",   "0.042")
    window._lbl_pipeB_out_w   = gio2.itemAtPosition(4, 0).widget()
    # 3D-only z-partial BC for fluid B (mirror Fluid A)
    window.le_pipeB_in_z_ctr  = row(window, gio2, 5,
                                     "Inlet z-centre [m] (3D)",  "0.021")
    window._lbl_pipeB_in_z_ctr  = gio2.itemAtPosition(5, 0).widget()
    window.le_pipeB_in_z_w    = row(window, gio2, 6,
                                     "Inlet z-width [m] (3D)",   "0.042")
    window._lbl_pipeB_in_z_w    = gio2.itemAtPosition(6, 0).widget()
    window.le_pipeB_out_z_ctr = row(window, gio2, 7,
                                     "Outlet z-centre [m] (3D)", "0.021")
    window._lbl_pipeB_out_z_ctr = gio2.itemAtPosition(7, 0).widget()
    window.le_pipeB_out_z_w   = row(window, gio2, 8,
                                     "Outlet z-width [m] (3D)",  "0.042")
    window._lbl_pipeB_out_z_w   = gio2.itemAtPosition(8, 0).widget()

    # ── Polygon pipe edge config (hidden by default) ──────
    window._poly_pipe_frame = QFrame()
    window._poly_pipe_frame.setStyleSheet(_F_NEUTRAL)
    ppg = QGridLayout(window._poly_pipe_frame)
    ppg.setContentsMargins(10, 6, 10, 6); ppg.setVerticalSpacing(5)
    ppg.setColumnStretch(0, 3); ppg.setColumnStretch(1, 2)
    lbl_pp = QLabel("  Polygon Pipe Edges")
    lbl_pp.setStyleSheet(_T_NEUTRAL)
    lbl_pp.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(lbl_pp)
    window._poly_pipe_label = lbl_pp

    window.combo_edge_inA = QComboBox(); window.combo_edge_inA.setStyleSheet(_COMBO)
    window.combo_edge_outA = QComboBox(); window.combo_edge_outA.setStyleSheet(_COMBO)
    window.combo_edge_inB = QComboBox(); window.combo_edge_inB.setStyleSheet(_COMBO)
    window.combo_edge_outB = QComboBox(); window.combo_edge_outB.setStyleSheet(_COMBO)
    add_row(window, ppg, 0, "Inlet A edge", window.combo_edge_inA)
    add_row(window, ppg, 1, "Outlet A edge", window.combo_edge_outA)
    add_row(window, ppg, 2, "Inlet B edge", window.combo_edge_inB)
    add_row(window, ppg, 3, "Outlet B edge", window.combo_edge_outB)
    lay.addWidget(window._poly_pipe_frame)
    window._poly_pipe_frame.hide()
    window._poly_pipe_label.hide()

    # Preview button
    btn_preview = QPushButton("&Preview Layout")
    btn_preview.setFixedHeight(28); btn_preview.setStyleSheet(t.style('BTN_SECONDARY'))
    btn_preview.setToolTip("Draw domain + inlet/outlet geometry on the canvas")
    btn_preview.clicked.connect(window._draw_layout)
    lay.addWidget(btn_preview)

    lay.addStretch()
    # Initial dir-aware label sync (cross1 axis name per current combo_dirA/B)
    try:
        window._on_dir_changed()
    except Exception:
        pass
    scroll.setWidget(w)
    return scroll


def build_page_zones(window):
    """Ex-Main_Menu._build_page_zones(self) -> QScrollArea.

    Note: post 2026-04-22 restructure this page hosts "Zone Layout" only
    (config + table + Preview). NSGA-II trigger + status moved to
    build_page_optimization.
    """
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI.
    from .field_factory import default_factory
    f = default_factory()
    t = f.theme
    _t = get_theme()

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("border:none; background:transparent;")

    w = QWidget(); w.setStyleSheet(f"background:{t.style('BG')};")
    lay = QVBoxLayout(w)
    lay.setSpacing(12); lay.setContentsMargins(6, 4, 8, 6)

    # ── Zone Configuration ── (title-less frame: panel lives inside the
    # Optimize tab card which is already labelled "Optimize", so repeating
    # "Zone Configuration" above the grid would be noise).
    sec_zone = QWidget()
    sec_zone.setStyleSheet("background:transparent;")
    _cz_lay = QVBoxLayout(sec_zone)
    _cz_lay.setContentsMargins(0, 4, 0, 0); _cz_lay.setSpacing(0)
    _cz_frame = QFrame()
    _cz_frame.setStyleSheet(t.style('F_NEUTRAL'))
    g_zone = QGridLayout(_cz_frame)
    g_zone.setContentsMargins(12, 10, 12, 10)
    g_zone.setVerticalSpacing(8); g_zone.setHorizontalSpacing(10)
    g_zone.setColumnStretch(0, 3); g_zone.setColumnStretch(1, 2)
    _cz_lay.addWidget(_cz_frame)
    lay.addWidget(sec_zone)
    window._rect_only_widgets.append(sec_zone)

    window.chk_zones = QCheckBox("Enable zone partitioning")
    _tcz = get_theme()
    # Explicit checkbox-indicator styling — without this, Qt falls back to
    # the native square which on Windows light is a white box with a thin
    # gray border that's nearly invisible on a white card_bg.
    window.chk_zones.setStyleSheet(
        f"QCheckBox{{color:{_tcz['fg']}; font-size:10pt; font-weight:bold;"
        f"background:transparent; spacing:8px;}}"
        f"QCheckBox::indicator{{width:16px; height:16px;"
        f"border:1.5px solid {_tcz['chk_indicator_border']};"
        f"border-radius:3px; background:{_tcz['chk_bg']};}}"
        f"QCheckBox::indicator:hover{{border-color:{_tcz['chk_hover_border']};}}"
        f"QCheckBox::indicator:checked{{background:{_tcz['chk_checked_bg']};"
        f"border-color:{_tcz['chk_checked_border']};}}"
        f"QCheckBox:focus{{outline:0;}}")
    window.chk_zones.setChecked(False)
    # Hide zone table + controls when unchecked (saves vertical space on small screens)
    def _toggle_zone_table(checked):
        for w_z in (window.zone_table, nz_row, window.combo_zone_axis):
            try:
                w_z.setVisible(checked)
            except Exception:
                pass
    window.chk_zones.toggled.connect(_toggle_zone_table)
    window.combo_zone_axis = QComboBox()
    window.combo_zone_axis.addItems(["Along Y", "Along X", "Grid Y\u00d7X"])
    window.combo_zone_axis.setFixedHeight(32)
    window.combo_zone_axis.setStyleSheet(t.style('INP'))
    window.combo_zone_axis.currentIndexChanged.connect(window._zone_mode_changed)
    g_zone.addWidget(window.chk_zones, 0, 0)
    g_zone.addWidget(window.combo_zone_axis, 0, 1)

    # Zone +/- buttons row
    nz_row = QWidget()
    nz_lay = QHBoxLayout(nz_row)
    nz_lay.setContentsMargins(0, 0, 0, 0); nz_lay.setSpacing(4)
    btn_add = QPushButton("+Row"); btn_rm = QPushButton("-Row")
    _btn_tert = t.style('BTN_TERTIARY')
    for b in (btn_add, btn_rm):
        b.setFixedHeight(32); b.setMinimumWidth(48)
        b.setStyleSheet(_btn_tert)
    btn_add.setToolTip("Add a row (split the last zone in half)")
    btn_rm.setToolTip("Remove the last row")
    btn_add.clicked.connect(window._zone_add_row)
    btn_rm.clicked.connect(window._zone_remove_row)
    window.lbl_nx = QLabel("Col:"); window.lbl_nx.setStyleSheet(t.style('LBL'))
    window.btn_add_x = QPushButton("+Col"); window.btn_rm_x = QPushButton("-Col")
    for b in (window.btn_add_x, window.btn_rm_x):
        b.setFixedHeight(32); b.setMinimumWidth(48)
        b.setStyleSheet(_btn_tert)
    window.btn_add_x.setToolTip("Add a column (split the last column in half)")
    window.btn_rm_x.setToolTip("Remove the last column")
    window.btn_add_x.clicked.connect(window._zone_add_col)
    window.btn_rm_x.clicked.connect(window._zone_remove_col)
    window.lbl_nx.hide(); window.btn_add_x.hide(); window.btn_rm_x.hide()
    nz_lay.addWidget(btn_add)
    nz_lay.addWidget(btn_rm)
    nz_lay.addStretch()
    nz_lay.addWidget(window.lbl_nx)
    nz_lay.addWidget(window.btn_add_x)
    nz_lay.addWidget(window.btn_rm_x)
    g_zone.addWidget(nz_row, 1, 0, 1, 2)
    window._grid_nx = 2  # track x-column count for grid mode

    window.zone_table = QTableWidget(3, 4)
    window.zone_table.setHorizontalHeaderLabels(
        ["START %", "END %", "L [mm]", "t [mm]"])
    window.zone_table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.Stretch)
    window.zone_table.verticalHeader().setVisible(True)
    window.zone_table.verticalHeader().setDefaultSectionSize(34)
    window.zone_table.verticalHeader().setStyleSheet(
        f"QHeaderView::section{{background:{_t.get('surface_raised', _t['card_bg'])};"
        f"color:{_t.get('sub_fg', _t['fg'])};"
        f"font-family:'Fira Code','Consolas',monospace;"
        f"font-size:9pt; font-weight:700;"
        f"border:none; border-right:1px solid {_t.get('border_subtle', _t['card_border'])};"
        f"padding:0 6px;}}")
    window.zone_table.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Expanding)
    window.zone_table.setMinimumHeight(220)
    window.zone_table.setAlternatingRowColors(True)
    window.zone_table.setShowGrid(False)
    window.zone_table.horizontalHeader().setHighlightSections(False)
    window.zone_table.verticalHeader().setHighlightSections(False)
    # Per-zone colour palette for the row indicator swatch — rotated by
    # row index. Uses the shared `canvas_accents` list so the swatch
    # colour matches anything else keyed off zone index.
    _zone_swatches = _t.get('canvas_accents', [_t['accent_primary']] * 6)
    window._zone_swatches = list(_zone_swatches)
    window.zone_table.setStyleSheet(
        f"QTableWidget{{background:{_t['card_bg']}; color:{_t['fg']};"
        f"font-size:10pt; gridline-color:transparent;"
        f"alternate-background-color:{_t.get('surface_raised', _t['card_bg'])};"
        f"border:1px solid {_t.get('border_subtle', _t['card_border'])};"
        f"border-radius:6px;}}"
        f"QHeaderView::section{{background:transparent;"
        f"color:{_t.get('sub_fg', _t['fg'])}; font-size:9pt;"
        f"font-weight:700; letter-spacing:1.2px; padding:8px 6px;"
        f"border:none;"
        f"border-bottom:2px solid {_t.get('accent_primary', '#3B82F6')};}}"
        f"QTableWidget::item{{padding:6px 10px;"
        f"font-family:'Fira Code','Consolas',monospace;"
        f"border-right:1px solid {_t.get('border_subtle', _t['card_border'])};}}"
        f"QTableWidget::item:hover{{background:"
        f"{_t.get('btn_sec_hover_bg', 'rgba(59,130,246,0.12)')};}}"
        f"QTableWidget::item:selected{{background:"
        f"{_t.get('accent_primary', '#3B82F6')}; color:white;}}"
        f"QTableCornerButton::section{{background:{_t.get('surface_raised', _t['card_bg'])};"
        f"border:none;}}"
    )
    # Auto-select-on-edit delegate (Phase 5: moved out of main.py).
    from .delegates import SelectAllDelegate
    window.zone_table.setItemDelegate(SelectAllDelegate(window.zone_table))

    def _repaint_zone_swatches():
        """Prefix each row header with a coloured ● from the canvas_accents
        palette so zone rows have a stable visual identity that matches any
        per-zone markers in the layout preview."""
        from PySide6.QtGui import QBrush, QColor
        pal = window._zone_swatches
        n = window.zone_table.rowCount()
        for r in range(n):
            col = QColor(pal[r % len(pal)])
            item = QTableWidgetItem(f" ● #{r + 1} ")
            item.setForeground(QBrush(col))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            window.zone_table.setVerticalHeaderItem(r, item)
    window._repaint_zone_swatches = _repaint_zone_swatches

    # Keep swatches in sync whenever rows are added/removed. Qt emits
    # rowsInserted / rowsRemoved through the model; connect there.
    model = window.zone_table.model()
    model.rowsInserted.connect(lambda *a: _repaint_zone_swatches())
    model.rowsRemoved.connect(lambda *a: _repaint_zone_swatches())

    window._zone_init_1d(3)
    _repaint_zone_swatches()
    g_zone.addWidget(window.zone_table, 2, 0, 1, 2)

    # Initially hide zone table (checkbox unchecked)
    window.zone_table.setVisible(False)
    nz_row.setVisible(False)
    window.combo_zone_axis.setVisible(False)

    # Edit triggers: always allow editing (checkbox only controls whether zones are used in solver)
    window.zone_table.setEditTriggers(
        QAbstractItemView.EditTrigger.DoubleClicked |
        QAbstractItemView.EditTrigger.SelectedClicked |
        QAbstractItemView.EditTrigger.EditKeyPressed |
        QAbstractItemView.EditTrigger.AnyKeyPressed)

    # Cell-level validation: start/end percent in [0, 100]; L/t > 0. Writes
    # the `cellError` dynamic property which is styled red in the sheet
    # above. Lets the user spot a bad cell even when the solver hasn't run.
    def _zone_cell_validate(row, col):
        item = window.zone_table.item(row, col)
        if item is None:
            return
        txt = item.text().strip()
        # E16 — `=expr` cells evaluate via the safe expression parser
        # so users can type e.g. `=100/3` or `=0.4+0.1`.
        if txt.startswith('='):
            from .expr_eval import eval_expr as _ev
            val = _ev(txt[1:])
            if val is not None:
                window.zone_table.blockSignals(True)
                item.setText(f"{val:.6g}")
                window.zone_table.blockSignals(False)
                txt = item.text().strip()
        bad = False
        try:
            v = float(txt)
            if col in (0, 1):  # start%, end%
                if v < 0 or v > 100:
                    bad = True
            elif col in (2, 3):  # L [mm], t [mm]
                if v <= 0:
                    bad = True
        except Exception:
            bad = True
        new = 'true' if bad else 'false'
        if item.data(Qt.ItemDataRole.UserRole + 1) != new:
            item.setData(Qt.ItemDataRole.UserRole + 1, new)
        # setProperty isn't enough on QTableWidgetItem — use a visual marker
        # via background brush so the selector fires. Qt has no per-item
        # dynamic property driving QSS; approximate via background colour.
        if bad:
            from PySide6.QtGui import QBrush, QColor
            item.setBackground(QBrush(QColor(220, 38, 38, 70)))
            item.setToolTip(
                "Value out of range" if col in (0, 1)
                else "Value must be > 0")
        else:
            from PySide6.QtGui import QBrush
            item.setBackground(QBrush())
            item.setToolTip("")
    window.zone_table.cellChanged.connect(_zone_cell_validate)

    # Preview Layout trigger — auto-switches to the Layout tab after
    # drawing so the user actually sees the result (the canvas lives in
    # a different tab from this Zone panel, which is now embedded in
    # Optimize; clicking with no tab-switch felt like a broken button).
    btn_preview_z = QPushButton("&Preview Layout  ↗")
    btn_preview_z.setFixedHeight(28)
    btn_preview_z.setStyleSheet(t.style('BTN_SECONDARY'))
    btn_preview_z.setToolTip(
        "Render the zone configuration on the Layout tab and jump to it")
    def _preview_and_switch():
        window._draw_layout()
        try:
            window._switch_tab('layout')
        except Exception:
            pass
    btn_preview_z.clicked.connect(_preview_and_switch)
    lay.addWidget(btn_preview_z)

    lay.addStretch()
    scroll.setWidget(w)
    return scroll


def build_page_optimization(window):
    """NSGA-II trigger + live status. Separate accordion group from Zone Layout
    so users can collapse/expand optimization UI independently of zone config.
    """
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI rather
    # than back-importing main module globals.
    from .field_factory import default_factory
    f = default_factory()
    t = f.theme

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("border:none; background:transparent;")

    w = QWidget(); w.setStyleSheet(f"background:{t.style('BG')};")
    lay = QVBoxLayout(w)
    lay.setSpacing(8); lay.setContentsMargins(4, 4, 6, 4)

    # Trigger button - orange filled signals long-running (multi-minute) work.
    # Stored on the window so `optimize_panel._set_optimize_running` can flip
    # it into a Cancel button mid-run.
    btn_opt = QPushButton("&Optimize Zones (NSGA-II)")
    btn_opt.setFixedHeight(32)
    btn_opt.setStyleSheet(t.style('BTN_LONG'))
    btn_opt.setToolTip(
        "Launch NSGA-II Pareto search. Runs for minutes to hours.")
    btn_opt.clicked.connect(window._run_optimize)
    window._opt_btn = btn_opt
    lay.addWidget(btn_opt)

    # Live status
    g_opt, _ = section(window, lay, "  Optimization Status",
                        t.style('T_NEUTRAL'), t.style('F_NEUTRAL'))
    window._opt_status = QLabel("Idle")
    window._opt_status.setWordWrap(True)
    window._opt_status.setMinimumHeight(40)
    # Explicit fg color — _VAL's dynamic property-selector chain sometimes
    # failed to paint a default when the label had no valState attribute,
    # leaving "Idle" invisible (white-on-white) in light mode.
    _tos = get_theme()
    window._opt_status.setStyleSheet(
        f"color:{_tos['fg']}; font-family:'Fira Code','Consolas',monospace;"
        f"font-size:10pt; font-weight:bold; background:transparent; border:none;")
    window._opt_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
    g_opt.addWidget(window._opt_status, 0, 0, 1, 2)

    lay.addStretch()
    scroll.setWidget(w)
    return scroll


def build_canvas_area(window):
    """Ex-Main_Menu._build_canvas_area(self) -> QWidget."""
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI.
    from .field_factory import default_factory
    from .theme import _THEMES as _THEMES_local
    f = default_factory()
    t = f.theme
    _BG = t.style('BG')
    _BTN_TPMS = t.style('BTN_TPMS')
    _t = get_theme()

    w = QWidget(); w.setStyleSheet(f"background:{_BG};")
    vlay = QVBoxLayout(w)
    vlay.setContentsMargins(0, 0, 0, 0); vlay.setSpacing(4)

    # ── Tab buttons + Export + Progress ──
    toolbar = QHBoxLayout()
    toolbar.setSpacing(4)
    toolbar.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    toolbar.setContentsMargins(12, 4, 4, 4)

    # Left-panel collapse toggle — chevron flips direction to reflect state.
    btn_toggle_left = QPushButton("‹")
    btn_toggle_left.setFixedSize(24, 28)
    btn_toggle_left.setStyleSheet(t.style('BTN_TERTIARY'))
    btn_toggle_left.setToolTip("Collapse parameter panel")
    btn_toggle_left.clicked.connect(window._toggle_left_panel)
    window.btn_toggle_left = btn_toggle_left
    toolbar.addWidget(btn_toggle_left)

    class _ShiftTabBtn(QPushButton):
        """Tab button that routes Shift+click to a split callback while
        preserving normal click semantics. `_tab_key` + `_win` injected
        after construction so the subclass needs no custom __init__."""
        def mousePressEvent(self, ev):
            if (ev.button() == Qt.MouseButton.LeftButton
                    and (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
                cb = getattr(self, '_shift_cb', None)
                if cb is not None:
                    cb()
                    return
            super().mousePressEvent(ev)
    window.btn_tab_temp = _ShiftTabBtn("Temperature")
    window.btn_tab_pres = _ShiftTabBtn("Pressure")
    window.btn_tab_vel  = _ShiftTabBtn("Velocity")
    window.btn_tab_layout = _ShiftTabBtn("Geometry")
    window.btn_tab_pareto = _ShiftTabBtn("Optimize")
    window.btn_tab_3d     = _ShiftTabBtn("3D View")
    for b, key in ((window.btn_tab_temp, 'temp'),
                    (window.btn_tab_pres, 'pres'),
                    (window.btn_tab_vel, 'vel'),
                    (window.btn_tab_layout, 'layout'),
                    (window.btn_tab_pareto, 'pareto'),
                    (window.btn_tab_3d, '3d')):
        b._shift_cb = (lambda k=key: window._split_with_current(k))
        b.setToolTip(b.toolTip() or f"{b.text()} tab "
                      "(Shift+click to compare side-by-side)")
    for b in (window.btn_tab_temp, window.btn_tab_pres, window.btn_tab_vel,
              window.btn_tab_layout, window.btn_tab_pareto, window.btn_tab_3d):
        b.setFixedHeight(28)
    window.btn_tab_layout.setStyleSheet(window._PTAB_ON)
    for b in (window.btn_tab_temp, window.btn_tab_pres, window.btn_tab_vel,
              window.btn_tab_3d):
        b.setStyleSheet(window._PTAB_DISABLED)
        b.setEnabled(False)
    # Optimize tab is the entry point for NSGA-II — always enabled so the
    # user can click through to the Launch button without first running a
    # single-point compute. The Pareto plot stays empty until a search
    # completes.
    window.btn_tab_pareto.setStyleSheet(window._PTAB_OFF)
    window.btn_tab_pareto.setEnabled(True)
    window.btn_tab_layout.clicked.connect(lambda: window._switch_tab('layout'))
    window.btn_tab_temp.clicked.connect(lambda: window._switch_tab('temp'))
    window.btn_tab_pres.clicked.connect(lambda: window._switch_tab('pres'))
    window.btn_tab_vel.clicked.connect(lambda: window._switch_tab('vel'))
    window.btn_tab_pareto.clicked.connect(lambda: window._switch_tab('pareto'))
    window.btn_tab_3d.clicked.connect(lambda: window._switch_tab('3d'))
    # Right-click the 3D tab button → "Open in new window" so users on
    # multi-monitor setups can detach the volume view without giving up
    # their parameter panel.
    window.btn_tab_3d.setContextMenuPolicy(
        Qt.ContextMenuPolicy.CustomContextMenu)
    def _open_3d_ctx(pos):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(window.btn_tab_3d)
        if getattr(window, '_3d_detached_window', None) is None:
            act = menu.addAction("Open in &new window")
            act.triggered.connect(window._detach_3d_window)
        else:
            act = menu.addAction("&Re-dock 3D panel")
            act.triggered.connect(window._reattach_3d_window)
        menu.exec(window.btn_tab_3d.mapToGlobal(pos))
    window.btn_tab_3d.customContextMenuRequested.connect(_open_3d_ctx)
    # D17 — generic detach context menu on every other tab button.
    for _bkey, _btn in (('temp',   window.btn_tab_temp),
                         ('pres',   window.btn_tab_pres),
                         ('vel',    window.btn_tab_vel),
                         ('layout', window.btn_tab_layout),
                         ('pareto', window.btn_tab_pareto)):
        _btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        def _open_ctx(pos, _key=_bkey, _b=_btn):
            from PySide6.QtWidgets import QMenu as _QM
            menu = _QM(_b)
            detached = window._detached_canvases.get(_key) is not None
            if detached:
                act = menu.addAction("&Re-dock canvas")
                act.triggered.connect(
                    lambda _c=False, k=_key: window._reattach_canvas(k))
            else:
                act = menu.addAction("Open in &new window")
                act.triggered.connect(
                    lambda _c=False, k=_key: window._detach_canvas(k))
            menu.exec(_b.mapToGlobal(pos))
        _btn.customContextMenuRequested.connect(_open_ctx)
    # 2026-05-09 Phase 4 — merge Temperature / Pressure / Velocity into a
    # single "2D VIEW" toolbar entry with a field-selector combo, parallel
    # to the existing "3D View" tab. The legacy buttons remain in `window.*`
    # for backward compat (hotkeys, split view, _switch_tab routing) but are
    # not added to the toolbar; the combo drives the same _switch_tab calls.
    window.btn_tab_2d_view = _ShiftTabBtn("2D View")
    window.btn_tab_2d_view.setFixedHeight(28)
    window.btn_tab_2d_view.setStyleSheet(window._PTAB_DISABLED)
    window.btn_tab_2d_view.setEnabled(False)
    window.btn_tab_2d_view._shift_cb = (
        lambda: window._split_with_current('2d_view'))
    window.btn_tab_2d_view.setToolTip(
        "2D field view (Temperature / Velocity / Pressure). "
        "Pick the field with the dropdown next to it. "
        "Shift+click to compare side-by-side.")
    window.btn_tab_2d_view.clicked.connect(
        lambda: window._switch_tab('2d_view'))

    window.combo_2d_field = QComboBox()
    window.combo_2d_field.addItems(["Temperature", "Velocity |U|", "Pressure"])
    window.combo_2d_field.setFixedHeight(28)
    window.combo_2d_field.setFixedWidth(120)            # ★ fix #4 (cap width)
    window.combo_2d_field.setEnabled(False)             # ★ fix #1 (gate w/ btn)
    # ★ fix #4 (thin 1px border, lighter weight, 9pt to match tab buttons)
    window.combo_2d_field.setStyleSheet(
        "QComboBox{padding:2px 6px; border:1px solid rgba(255,255,255,40);"
        " border-radius:4px; font-weight:normal; font-size:9pt;}"
        "QComboBox:hover{border-color:rgba(255,255,255,90);}"
        "QComboBox:disabled{color:rgba(255,255,255,40);"
        " border-color:rgba(255,255,255,15);}"
    )
    window.combo_2d_field.setToolTip(
        "Select which 2D field to display when '2D View' tab is active.")

    def _on_2d_field_changed(_idx):
        # Re-trigger the active tab so the canvas swap honors the new combo
        # selection. The _switch_tab fast-path returns immediately when the
        # active tab is unchanged, so we explicitly call with the resolved
        # underlying tab key.
        if getattr(window, '_active_tab', None) in ('temp', 'pres', 'vel',
                                                     '2d_view'):
            window._switch_tab('2d_view')
    window.combo_2d_field.currentIndexChanged.connect(_on_2d_field_changed)

    # ★ fix #2 — visually group [2D View | combo] as one cluster so the combo
    # reads as the field selector for that tab (not for Optimize on its right).
    # We use a thin 8-px QFrame wrapper with no background; the cluster has a
    # tighter inner gap (2 px) than the toolbar default and lives in a single
    # addWidget call so spacers don't separate them.
    from PySide6.QtWidgets import QFrame, QHBoxLayout as _QHL
    _2d_cluster = QFrame()
    _2d_cluster.setStyleSheet(
        "QFrame{background:transparent; border:none; padding:0px;}")
    _cl_lay = _QHL(_2d_cluster)
    _cl_lay.setContentsMargins(0, 0, 0, 0)
    _cl_lay.setSpacing(2)
    _cl_lay.addWidget(window.btn_tab_2d_view)
    _cl_lay.addWidget(window.combo_2d_field)
    window._2d_view_cluster = _2d_cluster

    toolbar.addWidget(window.btn_tab_layout)
    toolbar.addWidget(_2d_cluster)
    toolbar.addWidget(window.btn_tab_pareto)
    toolbar.addWidget(window.btn_tab_3d)
    # Legacy buttons retained in window.* but hidden from the toolbar so
    # _split_with_current / hotkeys / _switch_tab routing still resolves them.
    window.btn_tab_temp.hide()
    window.btn_tab_pres.hide()
    window.btn_tab_vel.hide()
    toolbar.addStretch()

    btn_zoom_in = QPushButton("+")
    btn_zoom_out = QPushButton("-")
    btn_reset_view = QPushButton("Reset View")
    for b in (btn_zoom_in, btn_zoom_out, btn_reset_view):
        b.setFixedHeight(28); b.setStyleSheet(t.style('BTN_TERTIARY'))
    btn_zoom_in.setFixedWidth(32); btn_zoom_out.setFixedWidth(32)
    btn_zoom_in.setToolTip("Zoom current canvas card in (Ctrl+Wheel)")
    btn_zoom_out.setToolTip("Zoom current canvas card out (Ctrl+Wheel)")
    btn_reset_view.setToolTip("Reset current canvas card to default size")
    btn_zoom_in.clicked.connect(lambda: canvas_zoom(window, 1.2))
    btn_zoom_out.clicked.connect(lambda: canvas_zoom(window, 0.8))
    btn_reset_view.clicked.connect(lambda: canvas_zoom_reset(window))
    toolbar.addWidget(btn_zoom_in)
    toolbar.addWidget(btn_zoom_out)
    toolbar.addWidget(btn_reset_view)

    # Canvas column toggle (1 ↔ 2 cols). Lives next to the zoom buttons
    # since both affect canvas presentation rather than data.
    btn_canvas_cols = QPushButton("⊞")
    btn_canvas_cols.setFixedSize(32, 28)
    btn_canvas_cols.setStyleSheet(t.style('BTN_TERTIARY'))
    btn_canvas_cols.setToolTip("Switch to two-column canvas layout")
    btn_canvas_cols.clicked.connect(lambda: toggle_canvas_cols(window))
    window.btn_canvas_cols = btn_canvas_cols
    toolbar.addWidget(btn_canvas_cols)

    btn_export_fig = QPushButton("Export &Figure")
    btn_export_fig.setFixedHeight(28)
    btn_export_fig.setStyleSheet(t.style('BTN_SECONDARY'))
    btn_export_fig.setToolTip("Save current canvas as PNG / SVG / PDF")
    btn_export_fig.setEnabled(False)
    btn_export_fig.clicked.connect(window._export_figure)
    window.btn_export_figure = btn_export_fig
    toolbar.addWidget(btn_export_fig)
    vlay.addLayout(toolbar)

    # Result summary strip — a thin bar showing the headline numbers from the
    # most recent compute. Hidden until data lands; populated by
    # `_update_result_summary` on Main_Menu. Lives above the progress line
    # so a running compute shows its progress directly below the last
    # solved summary, making the sequence visually obvious.
    _res_bar = QWidget()
    _res_bar.setStyleSheet(
        f"background:{_t['card_bg']};"
        f"border:1px solid {_t['card_border']}; border-radius:6px;")
    _res_lay = QHBoxLayout(_res_bar)
    _res_lay.setContentsMargins(12, 4, 12, 4); _res_lay.setSpacing(18)
    _chip_qss = (
        f"color:{_t['fg']}; background:transparent; border:none;"
        f"font-size:9pt; font-weight:500;")
    _cap_qss = (
        f"color:{_t.get('sub_fg', _t['fg'])}; background:transparent;"
        "border:none; font-size:8pt; font-weight:600; letter-spacing:0.8px;")
    # Monospace stack so chip numerics line up decimal-to-decimal across
    # runs — key for quick visual scanning of delta chips next to values.
    _chip_num_qss = (
        f"color:{_t['fg']}; background:transparent; border:none;"
        f"font-family:'Fira Code','Consolas',monospace;"
        f"font-size:9pt; font-weight:600;")
    window._res_chips = {}
    for label_text, key in [("Q", 'Q'), ("ΔP A", 'dPA'),
                             ("ΔP B", 'dPB'),
                             ("T_out A", 'ToutA'),
                             ("T_out B", 'ToutB')]:
        _cap = QLabel(label_text.upper())
        _cap.setStyleSheet(_cap_qss)
        _val = QLabel("—")
        _val.setStyleSheet(_chip_num_qss)
        # Delta badge beside the numeric chip — populated by
        # `_update_result_summary` with "↑5.1%" style annotations relative
        # to the previous run. Starts empty so the first compute just
        # shows the plain number without a misleading delta.
        _delta = QLabel("")
        _delta.setStyleSheet(
            f"color:{_t.get('sub_fg', _t['fg'])}; font-size:8pt;"
            "font-weight:bold; background:transparent; border:none;"
            "padding-left:4px;")
        _val._delta_label = _delta
        _res_lay.addWidget(_cap)
        _res_lay.addWidget(_val)
        _res_lay.addWidget(_delta)
        window._res_chips[key] = _val
    _res_lay.addStretch(1)
    _res_bar.setFixedHeight(26)
    _res_bar.hide()
    window._result_summary_bar = _res_bar
    vlay.addWidget(_res_bar)

    # ── Thin progress line (2px, auto-hides) ──
    window.progress = QProgressBar()
    window.progress.setFixedHeight(3)
    window.progress.setTextVisible(False)
    window.progress.setStyleSheet(
        "QProgressBar{background:transparent; border:none;}"
        f"QProgressBar::chunk{{background:{_t['prog_chunk']}; border-radius:1px;}}")
    window.progress.setValue(0)
    window.progress.hide()
    vlay.addWidget(window.progress)

    # ── Scrollable canvas area with card containers ──
    _t = get_theme()

    window._canvas_scroll = QScrollArea()
    window._canvas_scroll.setWidgetResizable(True)
    window._canvas_scroll.setStyleSheet(
        f"border:none; background:{_t['scroll_bg']};")
    window._canvas_scroll.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    canvas_container = QWidget()
    canvas_container.setStyleSheet(f"background:{_t['scroll_bg']};")
    # QGridLayout backs the card area so _relayout_cards() can re-pack
    # single-column ↔ two-column on demand (see window._set_canvas_cols).
    canvas_lay = QGridLayout(canvas_container)
    canvas_lay.setContentsMargins(12, 12, 12, 12)
    canvas_lay.setHorizontalSpacing(12)
    canvas_lay.setVerticalSpacing(16)
    window._canvas_lay = canvas_lay
    window._canvas_cols = 1

    # Empty state: visible until a Compute or Preview populates any card.
    _empty = QLabel(
        "⚙  Configure parameters on the left and click ▶ Compute"
        "\nto visualize temperature, pressure, and velocity fields.")
    _empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
    _empty.setStyleSheet(
        f"color:{_t.get('sub_fg', _t['fg'])}; background:transparent;"
        f"font-size:11pt; font-weight:500; letter-spacing:0.3px;"
        f"padding:80px 40px; border:1px dashed {_t['card_border']};"
        f"border-radius:8px;")
    canvas_lay.addWidget(_empty, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
    window._empty_state_label = _empty

    # Canvas widgets (reuse if available from theme switch)
    _reuse = getattr(window, '_reuse_canvases', None)
    if _reuse:
        window.canvas_temp   = _reuse['temp']
        window.canvas_pres   = _reuse['pres']
        window.canvas_vel    = _reuse['vel']
        window.canvas_layout = _reuse['layout']
        window.canvas_pareto = _reuse['pareto']
        window.canvas_3d     = _reuse.get('3d')
    else:
        window.canvas_temp   = MatplotlibCanvas(3, 1, figsize=(14, 24))
        window.canvas_pres   = MatplotlibCanvas(1, 1, figsize=(14, 18))
        window.canvas_vel    = MatplotlibCanvas(2, 1, figsize=(14, 16))
        window.canvas_layout = MatplotlibCanvas(1, 1, figsize=(10.5, 6.8))
        window.canvas_pareto = MatplotlibCanvas(1, 1, figsize=(14, 8))

    # PyVistaQt init is heavy (~1-2s VTK/OpenGL context setup).
    # Defer until user actually switches to the 3D tab → faster cold start
    # and no impact on 2D Compute Geometry / Auto-fill / Run responsiveness.
    window.canvas_3d = None
    window._vis3d_import_error = None
    import os as _os
    if (_os.environ.get('QT_QPA_PLATFORM', '').lower() == 'offscreen'
            or _os.environ.get(
                'TPMSHX_DISABLE_3D_PANEL', '').lower() in ('1', 'true', 'yes')):
        window._vis3d_import_error = 'headless/offscreen — 3D panel skipped'

    _ca = _t['canvas_accents']
    _accents = {
        'temp':   _ca[0],
        'pres':   _ca[1],
        'vel':    _ca[2],
        'layout': _ca[3],
        'pareto': _ca[4],
        '3d':     _ca[5],
    }

    window._canvas_default_h = {}
    window._canvas_cards = {}
    _card_specs = [
        (window.canvas_temp,   'temp',   1500),
        (window.canvas_pres,   'pres',   1200),
        (window.canvas_vel,    'vel',    1100),
        (window.canvas_layout, 'layout', 680),
        (window.canvas_pareto, 'pareto', 880),
    ]
    # 3D card inserted lazily (card reserved here as placeholder QWidget).
    # Taller card (1100 vs earlier 820) gives PyVistaQt ~950 px for the
    # plotter — the slice fills more of the available real-estate.
    from PySide6.QtWidgets import QWidget as _QW
    window._canvas_3d_placeholder = _QW()
    _card_specs.append((window._canvas_3d_placeholder, '3d', 1100))
    _card_row_order = []
    for c, key, h in _card_specs:
        # Card frame. 3D card skips top-accent stripe (its curved arc was
        # visually colliding with embedded toolbar labels — user report
        # 2026-04-21). Other cards keep the coloured accent.
        card = QFrame()
        accent = _accents.get(key, _t['accent_primary'])
        if key in ('layout', '3d'):
            card.setStyleSheet(
                f"QFrame{{background:{_t['card_bg']};"
                f"border:none; border-radius:4px;}}")
        else:
            card.setStyleSheet(
                f"QFrame{{background:{_t['card_bg']};"
                f"border:none; border-left:3px solid {accent};"
                f"border-radius:4px;}}")
        card_lay = QVBoxLayout(card)
        if key == 'layout':
            card_lay.setContentsMargins(8, 8, 8, 8)
        else:
            card_lay.setContentsMargins(16, 16, 16, 16)
        card_lay.setSpacing(0)
        # Drop shadows removed (2026-04-23): QGraphicsDropShadowEffect on a
        # large Matplotlib/PyVista surface repaints on every scroll, costing
        # noticeable FPS. Card depth is conveyed by the 3px left accent and
        # card_bg contrast against scroll_bg instead, which renders flat and
        # cheap. Re-enable only if a future design absolutely requires depth.

        # Card-local mini toolbar (temperature only) — hosts the
        # "Sync colorbar across Ta/Tb/Ts" toggle so users can flip between
        # shared and independent vmin/vmax at any time without re-running
        # Compute. Signal connects to `_redraw_temp_if_ready` in main.
        if key == 'temp':
            from PySide6.QtWidgets import QWidget as _QWtb, QHBoxLayout as _HB
            tb = _QWtb()
            tbl = _HB(tb)
            tbl.setContentsMargins(0, 0, 0, 6); tbl.setSpacing(8)
            tbl.addStretch(1)
            chk = QCheckBox("Sync colorbar (Ta/Tb/Ts)")
            chk.setChecked(True)
            chk.setToolTip(
                "When on, all three panels share a common vmin/vmax so "
                "cross-panel comparison is direct. Turn off for per-panel "
                "auto-scale.")
            chk.setStyleSheet(
                f"QCheckBox{{color:{_t['fg']}; font-size:9pt; "
                f"background:transparent;}}"
                f"QCheckBox::indicator{{width:14px; height:14px;"
                f"border:1px solid {_t['chk_indicator_border']};"
                f"border-radius:3px; background:{_t['chk_bg']};}}"
                f"QCheckBox::indicator:checked{{background:{_t['chk_checked_bg']};"
                f"border-color:{_t['chk_checked_border']};}}")
            tbl.addWidget(chk, 0)
            window.chk_sync_colorbar_T = chk
            chk.toggled.connect(
                lambda _on: window._redraw_temp_if_ready())
            card_lay.addWidget(tb)

        # Optimize tab header — Pro-Max layout:
        #   [Stage strip]      Config → Running → Result
        #   [KPI row]          Gen · Best Q · ETA + convergence sparkline
        #   [Control row]      Launch + Cancel + status
        #   [Progress bar]     fat 8 px pill bar
        #   [Summary banner]   green pill, post-run
        if key == 'pareto':
            from PySide6.QtWidgets import (
                QWidget as _QWop, QHBoxLayout as _HBop,
                QVBoxLayout as _VBop, QProgressBar as _PBop,
                QFrame as _QFop)
            from .sparkline import Sparkline as _SLop
            _surface_el = _t.get('surface_elevated', _t['card_bg'])
            _surface_ra = _t.get('surface_raised', _t['card_bg'])
            _border_sub = _t.get('border_subtle', _t['card_border'])
            _sub_fg = _t.get('sub_fg', _t['fg'])
            _mono = "'Fira Code','JetBrains Mono','Consolas',monospace"

            op_host = _QWop()
            op_v = _VBop(op_host)
            op_v.setContentsMargins(0, 0, 0, 10); op_v.setSpacing(12)

            # ── Stage strip ────────────────────────────────────────
            _pill_base = (
                "QLabel{{padding:5px 14px; border-radius:12px;"
                "font-size:9pt; font-weight:700; letter-spacing:0.8px;"
                "font-family:'Fira Sans','Inter','Segoe UI',sans-serif;"
                "background:{bg}; color:{fg}; border:1px solid {bd};}}")
            _pill_idle = _pill_base.format(
                bg=_surface_ra, fg=_sub_fg, bd=_border_sub)
            _pill_active = _pill_base.format(
                bg=_t.get('accent_primary', '#3B82F6'),
                fg='#FFFFFF',
                bd=_t.get('accent_primary', '#3B82F6'))
            _pill_done = _pill_base.format(
                bg=_t.get('accent_green', '#22C55E'),
                fg='#FFFFFF',
                bd=_t.get('accent_green', '#22C55E'))
            window._opt_pill_styles = (_pill_idle, _pill_active, _pill_done)

            stage_row = _HBop()
            stage_row.setSpacing(6); stage_row.setContentsMargins(0, 0, 0, 0)
            window._opt_stage_pills = {}
            stage_items = [('config', '01  CONFIG'),
                           ('running', '02  RUNNING'),
                           ('result', '03  RESULT')]
            for i, (skey, slabel) in enumerate(stage_items):
                pill = QLabel(slabel)
                pill.setStyleSheet(_pill_idle)
                stage_row.addWidget(pill)
                window._opt_stage_pills[skey] = pill
                if i < len(stage_items) - 1:
                    arr = QLabel("─")
                    arr.setStyleSheet(
                        f"color:{_border_sub}; font-size:12pt;"
                        "background:transparent; border:none; padding:0 2px;")
                    stage_row.addWidget(arr)
            stage_row.addStretch(1)
            op_v.addLayout(stage_row)
            # Initial stage: Config active, others idle
            window._opt_stage_pills['config'].setStyleSheet(_pill_active)

            # ── Hero KPI row ──────────────────────────────────────
            # Display-serif stack for hero numerics — research-tool gravitas.
            # Falls through to mono if no serif installed, so builds without
            # Instrument Serif still look sharp.
            _hero_font = ("'Instrument Serif','Fraunces','EB Garamond',"
                          "'Source Serif Pro','Georgia',"
                          "'Fira Code',serif")
            def _mk_kpi(caption, initial="—", min_w=150):
                card = _QFop()
                card.setStyleSheet(
                    f"QFrame{{background:{_surface_el};"
                    f"border:1px solid {_border_sub}; border-radius:10px;}}")
                card.setFixedHeight(78)
                card.setMinimumWidth(min_w)
                cl = _VBop(card)
                cl.setContentsMargins(14, 8, 14, 8); cl.setSpacing(2)
                cap = QLabel(caption)
                cap.setStyleSheet(
                    f"color:{_sub_fg}; font-size:8pt; font-weight:700;"
                    "letter-spacing:1.4px; background:transparent; border:none;"
                    "font-family:'Fira Sans','Inter',sans-serif;")
                val = QLabel(initial)
                val.setStyleSheet(
                    f"color:{_t['fg']}; font-family:{_hero_font};"
                    f"font-size:22pt; font-weight:600;"
                    "background:transparent; border:none;"
                    "font-feature-settings: 'tnum' on, 'lnum' on;")
                cl.addWidget(cap); cl.addWidget(val)
                return card, val

            kpi_row = _HBop()
            kpi_row.setSpacing(10)
            card_gen, val_gen = _mk_kpi("GENERATION", "—", 130)
            card_q,   val_q   = _mk_kpi("BEST Q [W/m]", "—", 180)
            card_dp,  val_dp  = _mk_kpi("BEST ΔP [Pa]", "—", 180)
            card_eta, val_eta = _mk_kpi("ETA", "—", 120)
            window._opt_kpi_gen = val_gen
            window._opt_kpi_q = val_q
            window._opt_kpi_dp = val_dp
            window._opt_kpi_eta = val_eta
            kpi_row.addWidget(card_gen)
            kpi_row.addWidget(card_q)
            kpi_row.addWidget(card_dp)
            kpi_row.addWidget(card_eta)

            # Sparkline card (flex 1)
            spark_card = _QFop()
            spark_card.setStyleSheet(
                f"QFrame{{background:{_surface_el};"
                f"border:1px solid {_border_sub}; border-radius:10px;}}")
            spark_card.setFixedHeight(72)
            spark_card.setMinimumWidth(220)
            scl = _VBop(spark_card)
            scl.setContentsMargins(14, 8, 14, 8); scl.setSpacing(2)
            spark_cap = QLabel("CONVERGENCE · BEST Q")
            spark_cap.setStyleSheet(
                f"color:{_sub_fg}; font-size:8pt; font-weight:700;"
                "letter-spacing:1.4px; background:transparent; border:none;"
                "font-family:'Fira Sans','Inter',sans-serif;")
            spark = _SLop(height=40)
            window._opt_sparkline = spark
            scl.addWidget(spark_cap)
            scl.addWidget(spark, 1)
            kpi_row.addWidget(spark_card, 1)
            op_v.addLayout(kpi_row)

            # ── Control row: Launch + Cancel + status ────────────
            ctrl_row = _HBop()
            ctrl_row.setSpacing(10)
            btn_opt = QPushButton("▶  &Optimize Zones (NSGA-II)")
            btn_opt.setFixedHeight(36)
            btn_opt.setMinimumWidth(250)
            btn_opt.setStyleSheet(t.style('BTN_LONG'))
            btn_opt.setToolTip(
                "Launch NSGA-II Pareto search (minutes to hours). "
                "Progress + live Pareto render in this tab.")
            btn_opt.clicked.connect(window._run_optimize)
            window._opt_btn = btn_opt
            ctrl_row.addWidget(btn_opt)

            btn_opt_cancel = QPushButton("Cancel")
            btn_opt_cancel.setFixedHeight(36)
            btn_opt_cancel.setMinimumWidth(90)
            btn_opt_cancel.setStyleSheet(t.style('BTN_TERTIARY'))
            btn_opt_cancel.setToolTip(
                "Request graceful cancel of the running NSGA-II search")
            btn_opt_cancel.setEnabled(False)
            btn_opt_cancel.clicked.connect(window._cancel_optimize)
            window._opt_cancel_btn = btn_opt_cancel
            ctrl_row.addWidget(btn_opt_cancel)
            ctrl_row.addStretch(1)

            status = QLabel("Idle — click Launch to start a search")
            status.setMinimumHeight(32)
            status.setStyleSheet(
                f"color:{_sub_fg}; font-family:{_mono};"
                f"font-size:10pt; font-weight:bold;"
                f"background:transparent; border:none; padding:4px 8px;")
            status.setAlignment(Qt.AlignmentFlag.AlignRight
                                | Qt.AlignmentFlag.AlignVCenter)
            window._opt_status = status
            ctrl_row.addWidget(status, 0)
            op_v.addLayout(ctrl_row)

            # ── Fat progress bar (8 px rounded pill) ─────────────
            op_pb = _PBop()
            op_pb.setFixedHeight(8)
            op_pb.setTextVisible(False)
            op_pb.setRange(0, 100); op_pb.setValue(0)
            op_pb.setStyleSheet(
                f"QProgressBar{{background:{_surface_ra};"
                f"border:1px solid {_border_sub}; border-radius:4px;}}"
                f"QProgressBar::chunk{{background:qlineargradient("
                f"x1:0,y1:0,x2:1,y2:0,"
                f"stop:0 {_t.get('accent_primary', '#3B82F6')},"
                f"stop:1 {_t.get('accent_green', '#22C55E')});"
                f"border-radius:4px;}}")
            op_pb.hide()
            window._opt_progress = op_pb
            op_v.addWidget(op_pb)

            # ── Summary banner (hidden initially) ────────────────
            banner = QLabel("")
            banner.setStyleSheet(
                f"QLabel{{color:#FFFFFF;"
                f"background:{_t.get('accent_green', '#22C55E')};"
                f"border:none; border-radius:8px;"
                f"padding:10px 16px;"
                f"font-family:{_mono}; font-size:10pt; font-weight:700;"
                "letter-spacing:0.3px;}")
            banner.setWordWrap(True)
            banner.hide()
            window._opt_summary_banner = banner
            op_v.addWidget(banner)

            card_lay.addWidget(op_host)

        # Canvas inside card. For the Optimize (pareto) tab the canvas
        # shares a horizontal QSplitter with the zone-configuration
        # panel that used to live in the left accordion — zones now read
        # as the "input" half and Pareto as the "output" half of the
        # optimisation workflow.
        c.setSizePolicy(QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Expanding)
        c.setStyleSheet("border-radius:6px;")
        if key == 'pareto' and getattr(window, '_zone_panel', None) is not None:
            _zp = window._zone_panel
            _zp.setMinimumWidth(280)
            _zp.setMaximumWidth(460)
            _split = QSplitter(Qt.Orientation.Horizontal)
            _split.setChildrenCollapsible(False)
            _split.setHandleWidth(6)
            _split.setStyleSheet(
                f"QSplitter::handle{{background:{_t.get('border_subtle', _t['card_border'])};"
                f"margin:0 2px; border-radius:2px;}}"
                f"QSplitter::handle:hover{{background:{_t.get('accent_primary', '#3B82F6')};}}")
            _split.addWidget(_zp)
            _split.addWidget(c)
            _split.setStretchFactor(0, 0)
            _split.setStretchFactor(1, 1)
            _split.setSizes([300, 1100])
            card_lay.addWidget(_split, 1)
            window._optimize_split = _split
        else:
            card_lay.addWidget(c)

        # Skeleton shimmer placeholder for tabs that start with no data.
        # Overlays the canvas widget until the first relevant compute
        # finishes; stop() + hide() from the show_* callback restores the
        # real chart. Uses an event filter to keep geometry in sync.
        if key in ('pareto', '3d'):
            try:
                from .skeleton import Skeleton as _Sk
                skel_kind = 'pareto' if key == 'pareto' else '3d'
                skel = _Sk(skel_kind, parent=c)
                skel.setGeometry(0, 0, max(1, c.width()), max(1, c.height()))
                _prev_resize = c.resizeEvent
                def _on_resize(ev, s=skel, cv=c, prev=_prev_resize):
                    s.setGeometry(0, 0, max(1, cv.width()),
                                   max(1, cv.height()))
                    if prev is not None:
                        prev(ev)
                c.resizeEvent = _on_resize
                skel.start()
                if key == 'pareto':
                    window._pareto_skeleton = skel
                else:
                    window._3d_skeleton = skel
            except Exception:
                pass

        card.setFixedHeight(h + 44)  # h + padding (2x16 margin + 2x2 border + 5 accent + buffer)
        _card_row_order.append((key, card))
        window._canvas_default_h[key] = h + 44
        window._canvas_cards[key] = card
        # Matplotlib canvases get custom wheel-zoom; 3D PyVistaQt keeps its own
        if key != '3d':
            c.wheelEvent = lambda evt, cv=c, k=key: canvas_wheel_zoom(window, evt, cv, k)

    # Register card ordering + initial single-column placement.
    window._canvas_card_order = [k for k, _ in _card_row_order]
    _relayout_canvas_cards(window, 1)

    # Initial state: hide all cards (shown after Compute/Preview)
    if not _reuse:
        # First launch: clear empty axes (matplotlib only)
        for key in ('temp', 'pres', 'vel', 'layout', 'pareto'):
            c = getattr(window, f'canvas_{key}')
            c.fig.clear()
            c.fig.patch.set_facecolor(_t['fig_bg'])
            c.draw()
    _hide_keys = ['temp', 'pres', 'vel', 'layout', 'pareto']
    if '3d' in window._canvas_cards:
        _hide_keys.append('3d')
    for key in _hide_keys:
        window._canvas_cards[key].hide()
    window._active_tab = 'layout'
    if not _reuse:
        window._has_results = False
        window._drawn_tabs = set()

    window._canvas_scroll.setWidget(canvas_container)
    vlay.addWidget(window._canvas_scroll, 1)

    # ── Hover data label ──
    window._hover_label = QLabel("")
    window._hover_label.setStyleSheet(
        f"color:{_t['fg']}; font-size:9pt; background:transparent; padding:2px 8px;")
    window._hover_label.setFixedHeight(20)
    vlay.addWidget(window._hover_label)

    # Connect hover events
    for c in (window.canvas_temp, window.canvas_pres, window.canvas_vel):
        c.mpl_connect('motion_notify_event', window._on_hover)

    # ── Slider (hidden for steady-state) ──
    window.slider = QSlider(Qt.Orientation.Horizontal)
    window.slider.setStyleSheet(
        "QSlider::groove:horizontal{background:rgba(0,0,0,30);"
        "height:5px; border-radius:3px;}"
        "QSlider::handle:horizontal{background:rgba(68,114,196,200);"
        "width:13px; height:13px; margin:-4px 0; border-radius:7px;}"
        "QSlider::sub-page:horizontal{background:rgba(68,114,196,150);"
        "border-radius:3px;}")
    window.slider.valueChanged.connect(window.update_graph_from_slider)
    window.slider.hide()
    vlay.addWidget(window.slider)

    return w


def _layout_split_cards(window, keys):
    """Place exactly `keys` (two tab keys) side-by-side; hide the rest.

    Used by the Shift-click split-view flow — lets users compare e.g.
    Temperature and Pressure or Layout and Pareto without constantly
    switching tabs. Non-split cards are hidden but not destroyed so
    a subsequent single-click restores them in one op.
    """
    lay = getattr(window, '_canvas_lay', None)
    order = getattr(window, '_canvas_card_order', None)
    if lay is None or order is None or not keys:
        return
    keys = [k for k in keys if k in window._canvas_cards][:2]
    if not keys:
        return
    # Detach every card.
    for k in order:
        card = window._canvas_cards.get(k)
        if card is not None:
            lay.removeWidget(card)
            card.hide()
    # Place the two split keys on a single row.
    for i, k in enumerate(keys):
        card = window._canvas_cards.get(k)
        if card is None:
            continue
        lay.addWidget(card, 0, i)
        card.show()
    window._canvas_cols = 2
    window._split_tabs = list(keys)


def _relayout_canvas_cards(window, cols):
    """Re-pack the canvas cards at `cols` columns (1 or 2). Preserves the
    user-visible order stored in `window._canvas_card_order`."""
    lay = getattr(window, '_canvas_lay', None)
    order = getattr(window, '_canvas_card_order', None)
    if lay is None or order is None:
        return
    cols = max(1, min(2, int(cols)))
    # Detach every card from its current cell.
    for key in order:
        card = window._canvas_cards.get(key)
        if card is not None:
            lay.removeWidget(card)
    # Re-add in row-major order.
    for i, key in enumerate(order):
        card = window._canvas_cards.get(key)
        if card is None:
            continue
        r, c = divmod(i, cols)
        lay.addWidget(card, r, c)
    window._canvas_cols = cols


def toggle_canvas_cols(window):
    """Flip between single-column and two-column canvas layouts. Wired from
    the canvas-area toolbar button."""
    current = getattr(window, '_canvas_cols', 1)
    new = 2 if current == 1 else 1
    _relayout_canvas_cards(window, new)
    if hasattr(window, 'btn_canvas_cols'):
        window.btn_canvas_cols.setText("⊟" if new == 2 else "⊞")
        window.btn_canvas_cols.setToolTip(
            "Switch to single-column canvas layout" if new == 2
            else "Switch to two-column canvas layout")


def canvas_zoom(window, factor):
    """Ex-Main_Menu._canvas_zoom(self, factor). Zoom current canvas card by factor."""
    tab = window._active_tab
    if tab == '3d':
        panel = getattr(window, 'canvas_3d', None)
        plotter = getattr(panel, 'plotter', None)
        if plotter is not None:
            try:
                plotter.camera.zoom(float(factor))
                plotter.render()
                return
            except Exception:
                pass
    card = window._canvas_cards.get(tab)
    if card:
        h = max(200, int(card.height() * factor))
        card.setFixedHeight(h)


def canvas_zoom_reset(window):
    """Ex-Main_Menu._canvas_zoom_reset(self). Reset current canvas card to default height."""
    tab = window._active_tab
    if tab == '3d':
        panel = getattr(window, 'canvas_3d', None)
        if panel is not None:
            try:
                panel._set_view('iso')
                return
            except Exception:
                pass
    card = window._canvas_cards.get(tab)
    if card and tab in window._canvas_default_h:
        card.setFixedHeight(window._canvas_default_h[tab])


def canvas_wheel_zoom(window, event, canvas, key):
    """Ex-Main_Menu._canvas_wheel_zoom(self, event, canvas, key).
    Ctrl + mouse wheel zoom. Without Ctrl, pass to ScrollArea for scrolling.
    """
    if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
        window._canvas_scroll.wheelEvent(event)
        return
    delta = event.angleDelta().y()
    if delta > 0:
        factor = 1.1
    elif delta < 0:
        factor = 0.9
    else:
        return
    card = window._canvas_cards.get(key)
    if card:
        h = max(200, int(card.height() * factor))
        card.setFixedHeight(h)


def section(window, parent_lay, title, title_style, frame_style):
    """Ex-Main_Menu._section. Phase 5: delegates to FieldFactory.

    The ``window`` argument is unused — kept for backward compatibility
    with every existing call site in ``build_page_*``. Returns
    ``(grid_layout, container_widget)``.
    """
    from .field_factory import default_factory
    return default_factory().section(parent_lay, title,
                                       title_style, frame_style)


def row(window, g, row_idx, text, default):
    """Ex-Main_Menu._row -> QLineEdit. Phase 5: delegates to FieldFactory.

    Note: parameter `row` renamed to `row_idx` to avoid shadowing the
    function name. ``window`` retained for call-site compatibility.
    """
    from .field_factory import default_factory
    return default_factory().row(g, row_idx, text, default)


def _computed_divider(g, row_idx, cols=2):
    """Insert a left-aligned `COMPUTED` caption + thin horizontal rule into
    grid `g` at the given row, spanning `cols` columns.

    Replaces the older `── computed ──` text separator. Visual weight is
    deliberately low — this is a layout hint, not a header.
    """
    t = get_theme()
    sub_fg = t.get('sub_fg', t['fg'])
    card_border = t.get('card_border', '#334155')

    holder = QWidget()
    holder.setStyleSheet("background:transparent;")
    h = QHBoxLayout(holder)
    h.setContentsMargins(0, 6, 0, 2)
    h.setSpacing(8)

    cap = QLabel("COMPUTED")
    cap.setStyleSheet(
        f"color:{sub_fg}; font-size:8pt; font-weight:600; letter-spacing:1.2px;"
        "background:transparent; border:none; padding:0;")
    cap.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    h.addWidget(cap, 0)

    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(
        f"background:{card_border}; border:none; color:{card_border};")
    h.addWidget(line, 1)

    g.addWidget(holder, row_idx, 0, 1, cols)


class _ResultLabel(QLabel):
    """QLabel that flips its dynamic `valState` property between `empty`
    ("—", muted italic) and `filled` (bold accent) as its text changes.

    A single `_VAL` stylesheet hosts both `QLabel[valState="empty"]` and
    `QLabel[valState="filled"]` selectors; Qt repolishes after each property
    change so call-sites that do `label.setText(...)` see the right look
    without touching styles themselves.

    Right-click pops a small menu with "Copy value" / "Copy with units";
    the unit string is parsed once from the row label at creation time.
    """
    _EMPTY_TOKENS = ('—', '-', '', None)

    def __init__(self, *args, unit_hint="", quantity_name="", **kw):
        super().__init__(*args, **kw)
        self._unit_hint = unit_hint
        self._quantity_name = quantity_name
        from PySide6.QtCore import Qt as _Qt
        self.setContextMenuPolicy(_Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_ctx_menu)

    def setText(self, txt):  # type: ignore[override]
        super().setText(txt if txt is not None else '—')
        state = 'empty' if (txt in self._EMPTY_TOKENS) else 'filled'
        if self.property('valState') != state:
            self.setProperty('valState', state)
            self.style().unpolish(self)
            self.style().polish(self)

    def _show_ctx_menu(self, pos):
        from PySide6.QtWidgets import QMenu, QApplication
        txt = self.text()
        is_empty = txt in self._EMPTY_TOKENS
        menu = QMenu(self)
        act_val = menu.addAction("&Copy value")
        act_val.setEnabled(not is_empty)
        unit_suffix = f"  [{self._unit_hint}]" if self._unit_hint else ""
        act_unit = menu.addAction(f"Copy with &units{unit_suffix}")
        act_unit.setEnabled(not is_empty and bool(self._unit_hint))
        menu.addSeparator()
        act_qty = menu.addAction(
            f"Copy as &assignment ({self._quantity_name or 'value'} = …)")
        act_qty.setEnabled(not is_empty)
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        cb = QApplication.clipboard()
        if chosen is act_val:
            cb.setText(txt)
        elif chosen is act_unit and self._unit_hint:
            cb.setText(f"{txt} {self._unit_hint}")
        elif chosen is act_qty:
            q = self._quantity_name or "value"
            cb.setText(f"{q} = {txt}" + (
                f" [{self._unit_hint}]" if self._unit_hint else ""))


_ENTITY_MAP = {
    '&nbsp;': ' ',
    '&epsilon;': 'ε', '&mu;': 'μ', '&rho;': 'ρ', '&sigma;': 'σ',
    '&phi;': 'φ', '&psi;': 'ψ', '&theta;': 'θ', '&lambda;': 'λ',
    '&alpha;': 'α', '&beta;': 'β', '&gamma;': 'γ', '&delta;': 'δ',
    '&Delta;': 'Δ', '&eta;': 'η', '&kappa;': 'κ', '&pi;': 'π',
    '&tau;': 'τ', '&omega;': 'ω',
    '&middot;': '·', '&plusmn;': '±', '&deg;': '°',
}


def _parse_unit_from_label(text):
    """Extract the unit string inside the last bracket pair of a row label.
    Accepts HTML; strips tags and common entities first. Returns ("K", "T_out")
    for "<i>T</i><sub>out</sub> [K]" etc. Empty unit_hint → no unit token.
    """
    import re as _re_u
    plain = _re_u.sub(r"<[^>]+>", "", text or "")
    for ent, ch in _ENTITY_MAP.items():
        plain = plain.replace(ent, ch)
    plain = plain.strip()
    m = _re_u.search(r"\[([^\[\]]+)\]\s*$", plain)
    unit = m.group(1).strip() if m else ""
    name = (plain[:m.start()] if m else plain).strip().rstrip(",:")
    return unit, name


def res_row(window, g, row_idx, text, col=0):
    """Label + computed-value row. Phase 5: delegates to FieldFactory."""
    from .field_factory import default_factory
    return default_factory().res_row(g, row_idx, text, col=col)


def add_row(window, g, row_idx, text, widget):
    """Ex-Main_Menu._add_row. Phase 5: delegates to FieldFactory."""
    from .field_factory import default_factory
    return default_factory().add_row(g, row_idx, text, widget)
