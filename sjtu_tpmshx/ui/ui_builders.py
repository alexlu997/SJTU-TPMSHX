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
    QPushButton, QComboBox, QScrollArea, QSplitter, QFrame, QSizePolicy,
    QSlider, QProgressBar, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QStackedWidget, QInputDialog, QStyledItemDelegate,
    QAbstractItemView,
)
from PySide6.QtWidgets import QGraphicsDropShadowEffect
from PySide6.QtGui import QColor
from .matplotlib_canvas import MatplotlibCanvas
from .theme import _THEMES, _build_styles


def _m():
    """Return the main module (lazy to avoid circular import at module load)."""
    import main as _main
    return _main


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
    m = _m()
    _BG = m._BG

    cw = window.centralWidget()
    cw.setStyleSheet(f"background:{_BG};")

    root = QVBoxLayout(cw)
    root.setContentsMargins(8, 6, 8, 6)
    root.setSpacing(6)

    # Header bar: navy blue background strip
    header_widget = QWidget()
    header_widget.setStyleSheet(
        "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
        "stop:0 #1a2a44, stop:1 #2a4060); border-radius:8px;")
    header_widget.setFixedHeight(44)
    header_row = QHBoxLayout(header_widget)
    header_row.setContentsMargins(8, 4, 8, 4)
    header_row.setSpacing(8)
    # SJTU banner (横版校徽+校名) — left side of header
    import os as _os_hdr
    from PySide6.QtGui import QPixmap
    _banner_path = _os_hdr.path.join(
        _os_hdr.path.dirname(_os_hdr.path.dirname(_os_hdr.path.abspath(__file__))),
        'sjtubannerred.png')
    if _os_hdr.path.exists(_banner_path):
        banner_lbl = QLabel()
        banner_lbl.setStyleSheet("background:transparent; border:none; padding:0;")
        _px = QPixmap(_banner_path).scaledToHeight(
            32, Qt.TransformationMode.SmoothTransformation)
        banner_lbl.setPixmap(_px)
        banner_lbl.setFixedSize(_px.width(), _px.height())
        header_row.addWidget(banner_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        header_row.addSpacing(12)
    hdr = QLabel("SJTU-TPMSHX")
    hdr.setStyleSheet(
        "background:transparent; color:white; font-size:11pt;"
        "font-weight:bold; border:none; padding:0;")
    hdr.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    header_row.addWidget(hdr, 0)
    header_row.addStretch(1)
    btn_reset = QPushButton("\u21ba  Reset")
    btn_reset.setFixedHeight(32)
    btn_reset.setFixedWidth(100)
    btn_reset.setStyleSheet(
        "QPushButton{background:rgba(255,255,255,0.12); border:1px solid rgba(255,255,255,0.25);"
        "border-radius:6px; color:rgba(255,255,255,0.85); font-weight:bold; font-size:10pt;}"
        "QPushButton:hover{background:rgba(255,255,255,0.20); color:white;}")
    btn_reset.setToolTip("Reset all parameters to Shanghai Electric preset (Ctrl+Shift+R)")
    btn_reset.clicked.connect(window._reset_defaults)
    header_row.addWidget(btn_reset, 0)
    header_row.addSpacing(6)
    btn_run = QPushButton("\u25b6  Compute")
    btn_run.setFixedHeight(32)
    btn_run.setFixedWidth(160)
    btn_run.setStyleSheet(
        "QPushButton{background:rgba(84,130,53,220); border:1px solid rgba(120,170,80,200);"
        "border-radius:6px; color:white; font-weight:bold; font-size:12pt;}"
        "QPushButton:hover{background:rgba(104,150,73,240);}")
    btn_run.clicked.connect(window.run_calculation)
    header_row.addWidget(btn_run, 0)
    header_row.addSpacing(6)
    btn_export = QPushButton("Export")
    btn_export.setFixedHeight(32)
    btn_export.setFixedWidth(80)
    btn_export.setStyleSheet(
        "QPushButton{background:rgba(255,255,255,0.12); border:1px solid rgba(255,255,255,0.25);"
        "border-radius:6px; color:rgba(255,255,255,0.85); font-weight:bold; font-size:10pt;}"
        "QPushButton:hover{background:rgba(255,255,255,0.20); color:white;}")
    btn_export.setToolTip("Export results (CSV + NPZ) to file")
    btn_export.clicked.connect(window._export_results)
    header_row.addWidget(btn_export, 0)
    root.addWidget(header_widget, 0)

    # Splitter: param_tabs 35% / canvas_area 65%
    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setStyleSheet(
        "QSplitter::handle{background:#d1d5db; width:5px; border-radius:2px;}"
        "QSplitter::handle:hover{background:#2c5282;}")
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
    root.addWidget(splitter, 1)


def build_param_tabs(window):
    """Left-panel parameter groups — collapsible accordion layout."""
    m = _m()
    _BG = m._BG
    _THEMES_local = m._THEMES

    # Tab button styles still needed for canvas-area tab bar (not left panel)
    _ts = _THEMES_local['light']
    from ui.theme import RADIUS_TAB
    window._PTAB_ON  = (f"QPushButton{{color:{_ts['tab_on_fg']};"
                        f"background:{_ts['tab_on_bg']};"
                        f"border:1px solid {_ts['tab_on_border']};"
                        f"border-radius:{RADIUS_TAB}px;"
                        "font-weight:bold; font-size:9pt; padding:5px 16px;}")
    window._PTAB_OFF = (f"QPushButton{{background:{_ts['tab_off_bg']}; color:{_ts['tab_off_fg']};"
                        f"border:1px solid {_ts['tab_off_border']};"
                        f"border-radius:{RADIUS_TAB}px;"
                        f"font-size:9pt; font-weight:500; padding:5px 16px;}}"
                        f"QPushButton:hover{{background:{_ts['tab_off_hover']};"
                        f"color:#1a1f24;}}")

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet(
        f"QScrollArea{{background:{_BG}; border:none;}}"
        f"QScrollBar:vertical{{background:{_BG}; width:10px; border:none; margin:2px;}}"
        f"QScrollBar::handle:vertical{{background:#9ca3af; border-radius:4px; min-height:30px;}}"
        f"QScrollBar::handle:vertical:hover{{background:#6b7280;}}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{{height:0;}}")
    scroll.setMinimumWidth(240)

    container = QWidget()
    container.setStyleSheet(f"background:{_BG};")
    vlay = QVBoxLayout(container)
    vlay.setContentsMargins(4, 4, 4, 4); vlay.setSpacing(6)
    vlay.setAlignment(Qt.AlignmentFlag.AlignTop)

    _GRP_QSS = (
        "QGroupBox {"
        "  font-size:10pt; font-weight:bold; color:#374151;"
        "  background:transparent; border:1px solid #d1d5db;"
        "  border-radius:8px; margin-top:10px; padding:10px 4px 4px 4px;"
        "}"
        "QGroupBox::title {"
        "  subcontrol-origin:margin; left:10px; padding:0 8px;"
        "  background:#f5f6f8;"
        "}"
        "QGroupBox::indicator {"
        "  width:14px; height:14px; margin-right:4px;"
        "}"
        "QGroupBox::indicator:checked {"
        "  image: none;"
        "  border:2px solid #2c5282; border-radius:3px;"
        "  background:#2c5282;"
        "}"
        "QGroupBox::indicator:unchecked {"
        "  image: none;"
        "  border:2px solid #9ca3af; border-radius:3px;"
        "  background:transparent;"
        "}"
    )

    page_domain = build_page_domain(window)
    page_fluids = build_page_fluids(window)
    page_zones  = build_page_zones(window)

    from PySide6.QtWidgets import QGroupBox
    for title, page, default_open in [
        ("Domain", page_domain, True),
        ("Fluids", page_fluids, True),
        ("Zones",  page_zones,  False),
    ]:
        grp = QGroupBox(title)
        grp.setCheckable(True)
        grp.setChecked(default_open)
        grp.setStyleSheet(_GRP_QSS)
        grp_lay = QVBoxLayout(grp)
        grp_lay.setContentsMargins(0, 0, 0, 0)
        grp_lay.setSpacing(0)
        grp_lay.addWidget(page)
        page.setVisible(default_open)
        grp.toggled.connect(lambda checked, p=page: p.setVisible(checked))
        vlay.addWidget(grp)

    vlay.addStretch(1)
    scroll.setWidget(container)

    # Legacy compat: _param_stack / _param_btns not used but some code may ref
    window._param_stack = None
    window._param_btns = []

    return scroll


def switch_param_tab(window, index):
    """Legacy no-op — left panel is now collapsible, not tab-switched."""
    pass


def build_page_domain(window):
    """Ex-Main_Menu._build_page_domain(self) -> QScrollArea."""
    m = _m()
    _BG = m._BG
    _T_NEUTRAL = m._T_NEUTRAL
    _F_NEUTRAL = m._F_NEUTRAL
    _COMBO = m._COMBO
    _BTN_TPMS = m._BTN_TPMS
    _LBL = m._LBL
    _VAL = m._VAL

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("border:none; background:transparent;")

    w = QWidget(); w.setStyleSheet(f"background:{_BG};")
    lay = QVBoxLayout(w)
    lay.setSpacing(6); lay.setContentsMargins(4, 4, 6, 4)

    # Domain Geometry
    g, _ = section(window, lay, "  \u25c8  Domain Geometry", _T_NEUTRAL, _F_NEUTRAL)
    window.le_L        = row(window, g, 0, "Length <i>L</i> [m]",                     "0.182")
    window.le_H        = row(window, g, 1, "Width <i>H</i> [m]",                      "0.042")
    window.le_Lz       = row(window, g, 2, "Depth <i>L<sub>z</sub></i> [m] (3D only)", "0.020")
    window._lbl_Lz     = g.itemAtPosition(2, 0).widget()
    window.le_T_init_s = row(window, g, 3, "Solid init. temp <i>T</i><sub>0</sub> [K]", "325.0")

    # Update edge labels when L or H changes
    window.le_L.editingFinished.connect(window._update_edge_combos)
    window.le_H.editingFinished.connect(window._update_edge_combos)

    # Domain shape selector
    window.combo_shape = QComboBox()
    window.combo_shape.addItems(["Rectangle", "Hexagon", "Octagon"])
    window.combo_shape.setStyleSheet(_COMBO)
    window.combo_shape.currentIndexChanged.connect(window._on_shape_changed)
    add_row(window, g, 4, "Domain shape", window.combo_shape)

    # Dimensionality (2D / 3D MVP) — dispatch in run_calculation
    window.combo_dim = QComboBox()
    window.combo_dim.addItems(["2D", "3D (uniform)"])
    window.combo_dim.setStyleSheet(_COMBO)
    window.combo_dim.currentIndexChanged.connect(
        lambda *_: _on_dim_changed(window))
    add_row(window, g, 5, "Dimensionality", window.combo_dim)

    # ── TPMS Structure ──
    g0, _ = section(window, lay, "  \u25c8  TPMS Structure", _T_NEUTRAL, _F_NEUTRAL)
    window.combo_tpms = QComboBox()
    window.combo_tpms.addItems(["Diamond", "Gyroid"])
    window.combo_tpms.setCurrentIndex(1)  # default Gyroid
    window.combo_tpms.setStyleSheet(_COMBO)
    add_row(window, g0, 0, "Type", window.combo_tpms)
    window.le_Lcell = row(window, g0, 1, "<i>L</i><sub>cell</sub> [mm]", "7.0")
    window.le_t     = row(window, g0, 2, "<i>t</i> [mm]", "0.6")
    window.le_ks    = row(window, g0, 3, "<i>k</i><sub>s</sub> [W/(m\u00b7K)]", "17.0")
    btn_tpms = QPushButton("Compute TPMS Geometry")
    btn_tpms.setFixedHeight(26); btn_tpms.setStyleSheet(_BTN_TPMS)
    btn_tpms.clicked.connect(window.compute_tpms)
    g0.addWidget(btn_tpms, 4, 0, 1, 2)
    # Computed outputs (green values)
    window._v_eps  = res_row(window, g0, 5, "<i>&epsilon;</i>")
    window._v_A0   = res_row(window, g0, 6, "<i>A</i><sub>0</sub> [m<sup>-1</sup>]")
    window._v_Dh   = res_row(window, g0, 7, "<i>D<sub>h</sub></i> [mm]")
    window._v_Kss  = res_row(window, g0, 8, "<i>K</i><sub>ss</sub> [W/(m\u00b7K)]")

    # Material
    g2, _ = section(window, lay, "  \u25c8  Material Properties", _T_NEUTRAL, _F_NEUTRAL)
    window.le_rho_s = row(window, g2, 0, "<i>&rho;</i><sub>s</sub> [kg/m\u00b3]", "7900")
    window.le_cp_s  = row(window, g2, 1, "<i>c</i><sub>p,s</sub> [J/(kg\u00b7K)]", "500")
    window.le_cp_f  = row(window, g2, 2, "<i>c</i><sub>p,f</sub> [J/(kg\u00b7K)]", "1007")

    # ── Grid Settings (rect mode) ──
    g4, sec_solver_rect = section(window, lay, "  \u25c8  Grid Settings", _T_NEUTRAL, _F_NEUTRAL)
    window._rect_only_widgets.append(sec_solver_rect)
    window.le_Nx = row(window, g4, 0, "Grid <i>N<sub>x</sub></i>", "100")
    window.le_Ny = row(window, g4, 1, "Grid <i>N<sub>y</sub></i>", "50")
    window.le_Nz = row(window, g4, 2, "Grid <i>N<sub>z</sub></i> (3D only)", "5")
    window._lbl_Nz = g4.itemAtPosition(2, 0).widget()

    # 3D wall-refine checkbox — adds 8 BL cells near each wall (all 6 faces)
    window.chk_wall_refine_3d = QCheckBox("6-wall BL refine (3D)")
    window.chk_wall_refine_3d.setChecked(True)
    window.chk_wall_refine_3d.setToolTip(
        "Enable six-wall boundary-layer refinement for 3D solves. "
        "Adds 8 cells per wall (first_cell=0.02 mm, growth 1.8). "
        "Turn off for pure uniform grid.")
    window.chk_wall_refine_3d.setStyleSheet("""
        QCheckBox {
            color: #1a1f24;
            font-size: 10pt;
            font-weight: 600;
            background: #ffffff;
            border: 1px solid #aeb4ba;
            border-radius: 6px;
            padding: 6px 10px;
            spacing: 8px;
        }
        QCheckBox:hover { border-color: #2c5282; background: #eef2f6; }
        QCheckBox::indicator {
            width: 16px; height: 16px;
            border: 1.5px solid #606870;
            border-radius: 3px;
            background: #ffffff;
        }
        QCheckBox::indicator:hover { border-color: #2c5282; }
        QCheckBox::indicator:checked {
            background: #2c5282;
            border-color: #1e3a5f;
            image: none;
        }
    """)
    g4.addWidget(window.chk_wall_refine_3d, 3, 0, 1, 2)
    window._chk_wall_refine_3d = window.chk_wall_refine_3d  # alias

    # Hide 3D-only inputs by default (2D mode)
    _on_dim_changed(window)

    # ── Solver Settings (polygon mode) ──
    gp, sec_solver_poly = section(window, lay, "  \u25c8  Mesh Settings", _T_NEUTRAL, _F_NEUTRAL)
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
    lay.addWidget(res_frame, 0)

    lay.addStretch()
    scroll.setWidget(w)
    return scroll


def build_page_fluids(window):
    """Ex-Main_Menu._build_page_fluids(self) -> QScrollArea."""
    m = _m()
    _BG = m._BG
    _THEMES_local = m._THEMES
    _T_HOT = m._T_HOT
    _F_HOT = m._F_HOT
    _T_COLD = m._T_COLD
    _F_COLD = m._F_COLD
    _T_NEUTRAL = m._T_NEUTRAL
    _F_NEUTRAL = m._F_NEUTRAL
    _COMBO = m._COMBO
    _BTN_HOT = m._BTN_HOT
    _BTN_COLD = m._BTN_COLD
    _BTN_TPMS = m._BTN_TPMS

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("border:none; background:transparent;")

    w = QWidget(); w.setStyleSheet(f"background:{_BG};")
    lay = QVBoxLayout(w)
    lay.setSpacing(6); lay.setContentsMargins(6, 4, 4, 4)

    # ── Fluid A (input + computed) ────────────────────────
    g1, _ = section(window, lay, "  \u25b6  Fluid A  (hot)", _T_HOT, _F_HOT)
    window.le_uA   = row(window, g1, 0, "<i>u</i><sub>A</sub> [m/s]",  "10.0")
    window.le_TinA = row(window, g1, 1, "<i>T</i><sub>in</sub> [K]",   "350.0")
    window.le_PinA = row(window, g1, 2, "<i>P</i><sub>in</sub> [Pa]",  "101325")
    # ── separator ──
    _sep_a = QLabel("\u2500\u2500 computed \u2500\u2500")
    _sep_a.setStyleSheet(f"color:{_THEMES_local['light']['fg']}; font-size:9pt; border:none; background:transparent;")
    _sep_a.setAlignment(Qt.AlignmentFlag.AlignCenter)
    g1.addWidget(_sep_a, 3, 0, 1, 2)
    window._v_rhoA = res_row(window, g1, 4, "<i>&rho;</i> [kg/m\u00b3]")
    window._v_ReA  = res_row(window, g1, 5, "Re")
    window._v_NuA  = res_row(window, g1, 6, "Nu")
    window._v_dPLA = res_row(window, g1, 7, "d<i>P</i>/d<i>L</i> [Pa/m]")
    btn_a = QPushButton("Auto-fill")
    btn_a.setFixedHeight(26); btn_a.setStyleSheet(_BTN_HOT)
    btn_a.clicked.connect(window.auto_fill_fluid_a)
    g1.addWidget(btn_a, 9, 0, 1, 2)

    # ── Fluid B (input + computed) ────────────────────────
    g2b, _ = section(window, lay, "  \u25c0  Fluid B  (cold)", _T_COLD, _F_COLD)
    window.le_uB   = row(window, g2b, 0, "<i>u</i><sub>B</sub> [m/s]",  "10.0")
    window.le_TinB = row(window, g2b, 1, "<i>T</i><sub>in</sub> [K]",   "300.0")
    window.le_PinB = row(window, g2b, 2, "<i>P</i><sub>in</sub> [Pa]",  "101325")
    _sep_b = QLabel("\u2500\u2500 computed \u2500\u2500")
    _sep_b.setStyleSheet(f"color:{_THEMES_local['light']['fg']}; font-size:9pt; border:none; background:transparent;")
    _sep_b.setAlignment(Qt.AlignmentFlag.AlignCenter)
    g2b.addWidget(_sep_b, 3, 0, 1, 2)
    window._v_rhoB = res_row(window, g2b, 4, "<i>&rho;</i> [kg/m\u00b3]")
    window._v_ReB  = res_row(window, g2b, 5, "Re")
    window._v_NuB  = res_row(window, g2b, 6, "Nu")
    window._v_dPLB = res_row(window, g2b, 7, "d<i>P</i>/d<i>L</i> [Pa/m]")
    btn_b = QPushButton("Auto-fill")
    btn_b.setFixedHeight(26); btn_b.setStyleSheet(_BTN_COLD)
    btn_b.clicked.connect(window.auto_fill_fluid_b)
    g2b.addWidget(btn_b, 9, 0, 1, 2)

    # ── Inlet / Outlet configuration (unified) ─────────────
    _DIR_ITEMS = ["+x  (left \u2192 right)", "-x  (right \u2192 left)",
                  "+y  (bottom \u2192 top)", "-y  (top \u2192 bottom)",
                  "+z  (front \u2192 back, 3D)", "-z  (back \u2192 front, 3D)"]

    gio, sec_pipeA = section(window, lay, "  \u25c8  Fluid A  Inlet / Outlet", _T_HOT, _F_HOT)
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
                                     "Inlet z-centre [m] (3D)",  "0.010")
    window._lbl_pipeA_in_z_ctr  = gio.itemAtPosition(5, 0).widget()
    window.le_pipeA_in_z_w    = row(window, gio, 6,
                                     "Inlet z-width [m] (3D)",   "0.020")
    window._lbl_pipeA_in_z_w    = gio.itemAtPosition(6, 0).widget()
    window.le_pipeA_out_z_ctr = row(window, gio, 7,
                                     "Outlet z-centre [m] (3D)", "0.010")
    window._lbl_pipeA_out_z_ctr = gio.itemAtPosition(7, 0).widget()
    window.le_pipeA_out_z_w   = row(window, gio, 8,
                                     "Outlet z-width [m] (3D)",  "0.020")
    window._lbl_pipeA_out_z_w   = gio.itemAtPosition(8, 0).widget()

    gio2, sec_pipeB = section(window, lay, "  \u25c8  Fluid B  Inlet / Outlet", _T_COLD, _F_COLD)
    window._rect_only_widgets.append(sec_pipeB)
    window.combo_dirB = QComboBox(); window.combo_dirB.addItems(_DIR_ITEMS)
    window.combo_dirB.setCurrentIndex(3)  # default -y (crossflow)
    window.combo_dirB.setStyleSheet(_COMBO)
    window.combo_dirB.currentIndexChanged.connect(window._on_dir_changed)
    add_row(window, gio2, 0, "Flow direction", window.combo_dirB)
    window.le_pipeB_in_ctr  = row(window, gio2, 1, "Inlet centre [m]",   "0.203")
    window._lbl_pipeB_in_ctr  = gio2.itemAtPosition(1, 0).widget()
    window.le_pipeB_in_w    = row(window, gio2, 2, "Inlet width [m]",    "0.042")
    window._lbl_pipeB_in_w    = gio2.itemAtPosition(2, 0).widget()
    window.le_pipeB_out_ctr = row(window, gio2, 3, "Outlet centre [m]",  "0.028")
    window._lbl_pipeB_out_ctr = gio2.itemAtPosition(3, 0).widget()
    window.le_pipeB_out_w   = row(window, gio2, 4, "Outlet width [m]",   "0.042")
    window._lbl_pipeB_out_w   = gio2.itemAtPosition(4, 0).widget()
    # 3D-only z-partial BC for fluid B (mirror Fluid A)
    window.le_pipeB_in_z_ctr  = row(window, gio2, 5,
                                     "Inlet z-centre [m] (3D)",  "0.010")
    window._lbl_pipeB_in_z_ctr  = gio2.itemAtPosition(5, 0).widget()
    window.le_pipeB_in_z_w    = row(window, gio2, 6,
                                     "Inlet z-width [m] (3D)",   "0.020")
    window._lbl_pipeB_in_z_w    = gio2.itemAtPosition(6, 0).widget()
    window.le_pipeB_out_z_ctr = row(window, gio2, 7,
                                     "Outlet z-centre [m] (3D)", "0.010")
    window._lbl_pipeB_out_z_ctr = gio2.itemAtPosition(7, 0).widget()
    window.le_pipeB_out_z_w   = row(window, gio2, 8,
                                     "Outlet z-width [m] (3D)",  "0.020")
    window._lbl_pipeB_out_z_w   = gio2.itemAtPosition(8, 0).widget()

    # ── Polygon pipe edge config (hidden by default) ──────
    window._poly_pipe_frame = QFrame()
    window._poly_pipe_frame.setStyleSheet(_F_NEUTRAL)
    ppg = QGridLayout(window._poly_pipe_frame)
    ppg.setContentsMargins(10, 6, 10, 6); ppg.setVerticalSpacing(5)
    ppg.setColumnStretch(0, 3); ppg.setColumnStretch(1, 2)
    lbl_pp = QLabel("  \u25c8  Polygon Pipe Edges")
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
    btn_preview = QPushButton("Preview Layout")
    btn_preview.setFixedHeight(26); btn_preview.setStyleSheet(_BTN_TPMS)
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
    """Ex-Main_Menu._build_page_zones(self) -> QScrollArea."""
    m = _m()
    _BG = m._BG
    _THEMES_local = m._THEMES
    _T_NEUTRAL = m._T_NEUTRAL
    _F_NEUTRAL = m._F_NEUTRAL
    _INP = m._INP
    _BTN_TPMS = m._BTN_TPMS
    _BTN_RUN = m._BTN_RUN
    _VAL = m._VAL

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("border:none; background:transparent;")

    w = QWidget(); w.setStyleSheet(f"background:{_BG};")
    lay = QVBoxLayout(w)
    lay.setSpacing(6); lay.setContentsMargins(4, 4, 6, 4)

    # ── Zone Configuration ──
    g_zone, sec_zone = section(window, lay, "  \u25c8  Zone Configuration", _T_NEUTRAL, _F_NEUTRAL)
    window._rect_only_widgets.append(sec_zone)

    window.chk_zones = QCheckBox("Enable zone partitioning")
    window.chk_zones.setStyleSheet(f"color:{_THEMES_local['light']['fg']}; font-size:9pt; background:transparent;")
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
    window.combo_zone_axis.setFixedHeight(26)
    window.combo_zone_axis.setStyleSheet(_INP)
    window.combo_zone_axis.currentIndexChanged.connect(window._zone_mode_changed)
    g_zone.addWidget(window.chk_zones, 0, 0)
    g_zone.addWidget(window.combo_zone_axis, 0, 1)

    # Zone +/- buttons row
    nz_row = QWidget()
    nz_lay = QHBoxLayout(nz_row)
    nz_lay.setContentsMargins(0, 0, 0, 0); nz_lay.setSpacing(4)
    btn_add = QPushButton("+Row"); btn_rm = QPushButton("-Row")
    for b in (btn_add, btn_rm):
        b.setFixedHeight(26); b.setStyleSheet(_BTN_TPMS)
    btn_add.clicked.connect(window._zone_add_row)
    btn_rm.clicked.connect(window._zone_remove_row)
    window.lbl_nx = QLabel("Col:"); window.lbl_nx.setStyleSheet(m._LBL)
    window.btn_add_x = QPushButton("+Col"); window.btn_rm_x = QPushButton("-Col")
    for b in (window.btn_add_x, window.btn_rm_x):
        b.setFixedHeight(26); b.setStyleSheet(_BTN_TPMS)
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
    window.zone_table.setHorizontalHeaderLabels(["start%", "end%", "L [mm]", "t [mm]"])
    window.zone_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    window.zone_table.verticalHeader().setVisible(True)
    window.zone_table.verticalHeader().setDefaultSectionSize(30)
    window.zone_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    window.zone_table.setMinimumHeight(200)
    window.zone_table.setStyleSheet(
        "QTableWidget { background:rgba(255,255,255,220); color:#1a1a2e; font-size:10pt; }"
        "QHeaderView::section { background:#4472c4; color:white; font-size:9pt; padding:2px; }"
        "QTableWidget::item { padding: 2px 4px; }"
        "QTableWidget::item:selected { background:#4488cc; color:white; }")
    # Import _SelectAllDelegate from main to reuse the same class
    import main as _main_mod
    window.zone_table.setItemDelegate(_main_mod._SelectAllDelegate(window.zone_table))
    window._zone_init_1d(3)
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

    # ── Preview + Optimize buttons ──
    btn_preview_z = QPushButton("Preview Layout")
    btn_preview_z.setFixedHeight(26)
    btn_preview_z.setStyleSheet(_BTN_TPMS)
    btn_preview_z.clicked.connect(window._draw_layout)
    lay.addWidget(btn_preview_z)

    btn_opt = QPushButton("Optimize Zones (NSGA-II)")
    btn_opt.setFixedHeight(26)
    btn_opt.setStyleSheet(_BTN_RUN)
    btn_opt.clicked.connect(window._run_optimize)
    lay.addWidget(btn_opt)

    # ── Optimize status ──
    g_opt, _ = section(window, lay, "  \u25c8  Optimization Status", _T_NEUTRAL, _F_NEUTRAL)
    window._opt_status = QLabel("Idle")
    window._opt_status.setWordWrap(True)
    window._opt_status.setMinimumHeight(40)
    window._opt_status.setStyleSheet(_VAL)
    window._opt_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
    g_opt.addWidget(window._opt_status, 0, 0, 1, 2)

    lay.addStretch()
    scroll.setWidget(w)
    return scroll


def build_canvas_area(window):
    """Ex-Main_Menu._build_canvas_area(self) -> QWidget."""
    m = _m()
    _BG = m._BG
    _THEMES_local = m._THEMES
    _BTN_TPMS = m._BTN_TPMS

    w = QWidget(); w.setStyleSheet(f"background:{_BG};")
    vlay = QVBoxLayout(w)
    vlay.setContentsMargins(0, 0, 0, 0); vlay.setSpacing(4)

    # ── Tab buttons + Export + Progress ──
    toolbar = QHBoxLayout()
    toolbar.setSpacing(4)
    toolbar.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    toolbar.setContentsMargins(12, 4, 4, 4)

    window.btn_tab_temp = QPushButton("Temperature")
    window.btn_tab_pres = QPushButton("Pressure")
    window.btn_tab_vel  = QPushButton("Velocity")
    window.btn_tab_layout = QPushButton("Geometry")
    window.btn_tab_pareto = QPushButton("Pareto")
    window.btn_tab_3d     = QPushButton("3D View")
    for b in (window.btn_tab_temp, window.btn_tab_pres, window.btn_tab_vel,
              window.btn_tab_layout, window.btn_tab_pareto, window.btn_tab_3d):
        b.setFixedHeight(28)
    window.btn_tab_layout.setStyleSheet(window._PTAB_ON)
    for b in (window.btn_tab_temp, window.btn_tab_pres, window.btn_tab_vel,
              window.btn_tab_pareto, window.btn_tab_3d):
        b.setStyleSheet(window._PTAB_OFF)
    # Initial visibility: only Geometry (Layout) tab shown until data arrives.
    # Other tabs revealed lazily by `Main_Menu._update_tab_visibility`:
    #   - temp/pres/vel ← 2D Run success + dim=2D
    #   - 3d            ← 3D Run success + dim=3D
    #   - pareto        ← optimizer finish
    for b in (window.btn_tab_temp, window.btn_tab_pres, window.btn_tab_vel,
              window.btn_tab_pareto, window.btn_tab_3d):
        b.hide()
    window.btn_tab_layout.clicked.connect(lambda: window._switch_tab('layout'))
    window.btn_tab_temp.clicked.connect(lambda: window._switch_tab('temp'))
    window.btn_tab_pres.clicked.connect(lambda: window._switch_tab('pres'))
    window.btn_tab_vel.clicked.connect(lambda: window._switch_tab('vel'))
    window.btn_tab_pareto.clicked.connect(lambda: window._switch_tab('pareto'))
    window.btn_tab_3d.clicked.connect(lambda: window._switch_tab('3d'))
    toolbar.addWidget(window.btn_tab_layout)
    toolbar.addWidget(window.btn_tab_temp)
    toolbar.addWidget(window.btn_tab_pres)
    toolbar.addWidget(window.btn_tab_vel)
    toolbar.addWidget(window.btn_tab_pareto)
    toolbar.addWidget(window.btn_tab_3d)
    toolbar.addStretch()

    btn_zoom_in = QPushButton("+")
    btn_zoom_out = QPushButton("-")
    btn_reset = QPushButton("Reset")
    for b in (btn_zoom_in, btn_zoom_out, btn_reset):
        b.setFixedHeight(28); b.setStyleSheet(_BTN_TPMS)
    btn_zoom_in.setFixedWidth(32); btn_zoom_out.setFixedWidth(32)
    btn_zoom_in.setToolTip("Zoom in (enlarge plot)")
    btn_zoom_out.setToolTip("Zoom out (shrink plot)")
    btn_reset.setToolTip("Reset to default size")
    btn_zoom_in.clicked.connect(lambda: canvas_zoom(window, 1.2))
    btn_zoom_out.clicked.connect(lambda: canvas_zoom(window, 0.8))
    btn_reset.clicked.connect(lambda: canvas_zoom_reset(window))
    toolbar.addWidget(btn_zoom_in)
    toolbar.addWidget(btn_zoom_out)
    toolbar.addWidget(btn_reset)

    btn_export = QPushButton("Export")
    btn_export.setFixedHeight(28)
    btn_export.setStyleSheet(_BTN_TPMS)
    btn_export.clicked.connect(window._export_figure)
    toolbar.addWidget(btn_export)
    vlay.addLayout(toolbar)

    # ── Thin progress line (2px, auto-hides) ──
    window.progress = QProgressBar()
    window.progress.setFixedHeight(3)
    window.progress.setTextVisible(False)
    window.progress.setStyleSheet(
        "QProgressBar{background:transparent; border:none;}"
        "QProgressBar::chunk{background:#4472c4; border-radius:1px;}")
    window.progress.setValue(0)
    window.progress.hide()
    vlay.addWidget(window.progress)

    # ── Scrollable canvas area with card containers ──
    _t = _THEMES_local['light']

    window._canvas_scroll = QScrollArea()
    window._canvas_scroll.setWidgetResizable(True)
    window._canvas_scroll.setStyleSheet(
        f"border:none; background:{_t['scroll_bg']};")
    window._canvas_scroll.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    canvas_container = QWidget()
    canvas_container.setStyleSheet(f"background:{_t['scroll_bg']};")
    canvas_lay = QVBoxLayout(canvas_container)
    canvas_lay.setContentsMargins(12, 12, 12, 12)
    canvas_lay.setSpacing(16)

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
        window.canvas_layout = MatplotlibCanvas(1, 1, figsize=(14, 11))
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

    # Accent colors per canvas tab
    _accents = {
        'temp':   '#4472c4',  # blue
        'pres':   '#548235',  # green
        'vel':    '#c55a11',  # orange
        'layout': '#888888',  # gray
        'pareto': '#7b4daa',  # purple
        '3d':     '#2c5282',  # industrial navy
    }

    window._canvas_default_h = {}
    window._canvas_cards = {}
    _card_specs = [
        (window.canvas_temp,   'temp',   1500),
        (window.canvas_pres,   'pres',   1200),
        (window.canvas_vel,    'vel',    1100),
        (window.canvas_layout, 'layout', 900),
        (window.canvas_pareto, 'pareto', 600),
    ]
    # 3D card inserted lazily (card reserved here as placeholder QWidget).
    # Taller card (1100 vs earlier 820) gives PyVistaQt ~950 px for the
    # plotter — the slice fills more of the available real-estate.
    from PySide6.QtWidgets import QWidget as _QW
    window._canvas_3d_placeholder = _QW()
    _card_specs.append((window._canvas_3d_placeholder, '3d', 1100))
    for c, key, h in _card_specs:
        # Card frame. 3D card skips top-accent stripe (its curved arc was
        # visually colliding with embedded toolbar labels — user report
        # 2026-04-21). Other cards keep the coloured accent.
        card = QFrame()
        from ui.theme import RADIUS_CARD
        accent = _accents.get(key, '#4472c4')
        if key == '3d':
            card.setStyleSheet(
                f"QFrame{{background:{_t['card_bg']};"
                f"border:1px solid {_t['card_border']};"
                f"border-radius:{RADIUS_CARD}px;}}")
        else:
            card.setStyleSheet(
                f"QFrame{{background:{_t['card_bg']};"
                f"border:2px solid {_t['card_border']};"
                f"border-top:5px solid {accent};"
                f"border-radius:{RADIUS_CARD+4}px;}}")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(16, 16, 16, 16)
        card_lay.setSpacing(0)
        # Micro drop shadow
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(8)
        shadow.setOffset(0, 1)
        from PySide6.QtGui import QColor
        shadow.setColor(QColor(0, 0, 0, 15))
        card.setGraphicsEffect(shadow)

        # Canvas inside card
        c.setSizePolicy(QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Expanding)
        c.setStyleSheet("border-radius:6px;")
        card_lay.addWidget(c)

        card.setFixedHeight(h + 44)  # h + padding (2x16 margin + 2x2 border + 5 accent + buffer)
        canvas_lay.addWidget(card)
        window._canvas_default_h[key] = h + 44
        window._canvas_cards[key] = card
        # Matplotlib canvases get custom wheel-zoom; 3D PyVistaQt keeps its own
        if key != '3d':
            c.wheelEvent = lambda evt, cv=c, k=key: canvas_wheel_zoom(window, evt, cv, k)

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


def canvas_zoom(window, factor):
    """Ex-Main_Menu._canvas_zoom(self, factor). Zoom current canvas card by factor."""
    tab = window._active_tab
    card = window._canvas_cards.get(tab)
    if card:
        h = max(200, int(card.height() * factor))
        card.setFixedHeight(h)


def canvas_zoom_reset(window):
    """Ex-Main_Menu._canvas_zoom_reset(self). Reset current canvas card to default height."""
    tab = window._active_tab
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
    """Ex-Main_Menu._section(self, parent_lay, title, title_style, frame_style).
    Create a titled section. Returns (grid_layout, container_widget).
    """
    container = QWidget()
    container.setStyleSheet("background:transparent;")
    clay = QVBoxLayout(container)
    clay.setContentsMargins(0, 6, 0, 0); clay.setSpacing(0)

    t = QLabel(title); t.setStyleSheet(title_style)
    t.setAlignment(Qt.AlignmentFlag.AlignCenter)
    clay.addWidget(t)

    frame = QFrame(); frame.setStyleSheet(frame_style)
    g = QGridLayout(frame)
    g.setContentsMargins(10, 6, 10, 6); g.setVerticalSpacing(5)
    g.setColumnStretch(0, 3); g.setColumnStretch(1, 2)
    clay.addWidget(frame)

    parent_lay.addWidget(container)
    return g, container


def row(window, g, row_idx, text, default):
    """Ex-Main_Menu._row(self, g, row, text, default) -> QLineEdit.
    Note: parameter `row` renamed to `row_idx` to avoid shadowing the function name.
    """
    m = _m()
    _LBL = m._LBL
    _INP = m._INP

    lbl = QLabel(text); lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setStyleSheet(_LBL); lbl.setWordWrap(False)
    le = QLineEdit(default); le.setStyleSheet(_INP)
    g.addWidget(lbl, row_idx, 0); g.addWidget(le, row_idx, 1)
    return le


def res_row(window, g, row_idx, text, col=0):
    """Ex-Main_Menu._res_row(self, g, row, text, col=0) -> QLabel.
    Note: parameter `row` renamed to `row_idx` to avoid shadowing the function name.
    """
    m = _m()
    _LBL = m._LBL
    _VAL = m._VAL

    lbl = QLabel(text); lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setStyleSheet(_LBL)
    val = QLabel("\u2014"); val.setStyleSheet(_VAL)
    g.addWidget(lbl, row_idx, col); g.addWidget(val, row_idx, col + 1)
    return val


def add_row(window, g, row_idx, text, widget):
    """Ex-Main_Menu._add_row(self, g, row, text, widget).
    Note: parameter `row` renamed to `row_idx` to avoid shadowing the function name.
    """
    m = _m()
    _LBL = m._LBL

    lbl = QLabel(text); lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setStyleSheet(_LBL)
    g.addWidget(lbl, row_idx, 0); g.addWidget(widget, row_idx, 1)
