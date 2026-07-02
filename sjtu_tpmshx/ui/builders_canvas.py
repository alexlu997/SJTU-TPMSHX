"""Canvas-area builder: tab toolbar, result summary strip, canvas cards.

Split out of ui_builders.py (Batch-2, 2026-06-10). Owns the right-hand
canvas stack (Temperature / Pressure / Velocity / Geometry / Optimize /
3D View cards), the tab-button row with split/detach affordances, and
the card zoom / re-layout helpers used by TabViewMixin.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QScrollArea, QSplitter, QFrame, QSizePolicy, QSlider,
    QProgressBar, QCheckBox,
)

from .matplotlib_canvas import MatplotlibCanvas
from .theme import get_theme


class _ShiftTabBtn(QPushButton):
    """Tab button that routes Shift+click to a split callback while
    preserving normal click semantics. `_shift_cb` injected after
    construction so the subclass needs no custom __init__."""
    def mousePressEvent(self, ev):
        if (ev.button() == Qt.MouseButton.LeftButton
                and (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            cb = getattr(self, '_shift_cb', None)
            if cb is not None:
                cb()
                return
        super().mousePressEvent(ev)


def build_canvas_area(window):
    """Ex-Main_Menu._build_canvas_area(self) -> QWidget."""
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI.
    from .field_factory import default_factory
    f = default_factory()
    t = f.theme
    _BG = t.style('BG')
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
    # 2026-06-03 — was hardcoded rgba(255,255,255,*) (white border + white
    # disabled text): invisible/jarring on the light theme's near-white tab
    # strip (read as an empty white box). Theme-token it + transparent fill so
    # it blends with the flat tab buttons in both palettes.
    _ct = get_theme()
    window.combo_2d_field.setStyleSheet(
        f"QComboBox{{padding:2px 6px; color:{_ct['inp_fg']}; background:transparent;"
        f" border:1px solid {_ct['tab_off_border']}; border-radius:4px;"
        f" font-weight:normal; font-size:9pt;}}"
        f"QComboBox:hover{{border-color:{_ct['combo_hover_border']};}}"
        f"QComboBox:disabled{{color:{_ct['tab_disabled_fg']};"
        f" background:transparent; border-color:{_ct['border_subtle']};}}"
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
    from PySide6.QtWidgets import QFrame as _QF, QHBoxLayout as _QHL
    _2d_cluster = _QF()
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

    # Fit View — restore the current canvas card to its default size after
    # Ctrl+Wheel zooming. (The +/- buttons were redundant with the wheel;
    # the 1↔2 column toggle was niche — both removed in the 2026-06 declutter.)
    btn_reset_view = QPushButton("Fit View")
    btn_reset_view.setFixedHeight(28)
    btn_reset_view.setStyleSheet(t.style('BTN_TERTIARY'))
    btn_reset_view.setToolTip("Fit current canvas card to its default size")
    btn_reset_view.clicked.connect(lambda: canvas_zoom_reset(window))
    toolbar.addWidget(btn_reset_view)

    # Single Export menu — Results (data) + Figure (image) in one entry, in
    # the canvas toolbar next to the data it exports (the old header "Export
    # Results" copy was easy to miss). Gated until a compute / layout fills it.
    from PySide6.QtWidgets import QToolButton as _QTB, QMenu as _QMenu
    btn_export = _QTB()
    btn_export.setText("Export ▾")
    btn_export.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    btn_export.setPopupMode(_QTB.ToolButtonPopupMode.InstantPopup)
    btn_export.setFixedHeight(28)
    btn_export.setStyleSheet(
        t.style('BTN_SECONDARY').replace("QPushButton", "QToolButton"))
    btn_export.setToolTip(
        "Export results (CSV + NPZ) or the current figure (PNG / SVG / PDF)")
    btn_export.setEnabled(False)
    _ex_menu = _QMenu(btn_export)
    # Theme-aware: without this the dropdown items inherited light-on-light text
    # in the white theme (unreadable). Explicit fg/bg keeps them legible in both.
    _ex_menu.setStyleSheet(
        f"QMenu {{ background:{_t['card_bg']}; color:{_t['fg']}; "
        f"border:1px solid {_t['card_border']}; border-radius:6px; padding:4px; }}"
        f"QMenu::item {{ padding:6px 20px; border-radius:4px; }}"
        f"QMenu::item:selected {{ background:{_t['accent_primary']}; color:#ffffff; }}")
    _ex_menu.addAction("Results — CSV + NPZ", window._export_results)
    _ex_menu.addAction("Figure — PNG / SVG / PDF", window._export_figure)
    btn_export.setMenu(_ex_menu)
    window.btn_export = btn_export
    toolbar.addWidget(btn_export)
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
    # HTML captions render real subscripts (no literal underscores): ΔP_A,
    # T_out,A → Δ<i>P</i><sub>A</sub>, <i>T</i><sub>out,A</sub>. unit kept
    # lowercase so "[Pa]"/"[K]" read right; Q carries no caption unit (W/m in
    # 2D vs W in 3D — mode-dependent, a fixed unit would mislabel one mode).
    for cap_html, unit, key in [
            ("<i>Q</i>", '', 'Q'),
            ("Δ<i>P</i><sub>A</sub>", 'Pa', 'dPA'),
            ("Δ<i>P</i><sub>B</sub>", 'Pa', 'dPB'),
            ("<i>T</i><sub>out,A</sub>", 'K', 'ToutA'),
            ("<i>T</i><sub>out,B</sub>", 'K', 'ToutB')]:
        _cap = QLabel(cap_html + (f" [{unit}]" if unit else ""))
        _cap.setTextFormat(Qt.TextFormat.RichText)
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
    # Structured three-step guidance (ui-layout-fixes) instead of a text
    # wall — verbs first, one job per line, theme-token colors.
    _acc = _t.get('accent_primary', '#3B82F6')
    _sub = _t.get('sub_fg', _t['fg'])
    _empty = QLabel(
        f"<div style='text-align:left;'>"
        f"<p style='color:{_t['fg']}; font-size:12pt; font-weight:600;"
        f" margin:0 0 14px 0;'>Run your first case</p>"
        f"<p style='margin:0 0 8px 0;'><span style='color:{_acc};"
        f" font-weight:700;'>1</span>&nbsp;&nbsp;Set the geometry and both"
        f" fluids in the left panel</p>"
        f"<p style='margin:0 0 8px 0;'><span style='color:{_acc};"
        f" font-weight:700;'>2</span>&nbsp;&nbsp;Click <b>Compute</b>"
        f" (Ctrl+R) — progress shows on the button</p>"
        f"<p style='margin:0;'><span style='color:{_acc};"
        f" font-weight:700;'>3</span>&nbsp;&nbsp;Read T / P / velocity"
        f" fields here; tabs appear above when ready</p>"
        f"</div>")
    _empty.setTextFormat(Qt.TextFormat.RichText)
    _empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
    _empty.setStyleSheet(
        f"color:{_sub}; background:transparent;"
        f"font-size:10pt; letter-spacing:0.2px;"
        f"padding:56px 48px; border:1px dashed {_t['card_border']};"
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

    # ── 3D card fits the scroll viewport (no forced vertical scrollbar) ──
    # The fixed card heights suit the stacked 2D canvases, but the lone 3D card
    # (1144 px) overflowed shorter screens → a scrollbar the user had to drag to
    # reach a usable size. Refit it to the visible viewport height on every
    # scroll-resize and whenever the card is shown (tab switch) so it lands
    # correctly sized with no scroll.
    def _fit_3d_card_to_viewport():
        c3d = window._canvas_cards.get('3d')
        sc = getattr(window, '_canvas_scroll', None)
        if c3d is None or sc is None or not c3d.isVisible():
            return
        vh = sc.viewport().height()
        if vh > 240:
            c3d.setFixedHeight(vh - 4)
    window._fit_3d_card_to_viewport = _fit_3d_card_to_viewport

    _sc = window._canvas_scroll
    _orig_sc_resize = _sc.resizeEvent
    def _sc_resize(ev, _o=_orig_sc_resize):
        if _o is not None:
            _o(ev)
        _fit_3d_card_to_viewport()
    _sc.resizeEvent = _sc_resize

    _c3d = window._canvas_cards.get('3d')
    if _c3d is not None:
        _orig_show = _c3d.showEvent
        def _c3d_show(ev, _o=_orig_show):
            if _o is not None:
                _o(ev)
            # 3D fills one card → no scroll needed. Hide the vertical bar so a
            # few px of layout slack can't trigger a stray scrollbar, and refit
            # the card to the viewport.
            window._canvas_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            _fit_3d_card_to_viewport()
        _c3d.showEvent = _c3d_show
        _orig_hide = _c3d.hideEvent
        def _c3d_hide(ev, _o=_orig_hide):
            if _o is not None:
                _o(ev)
            # Restore for the stacked, taller 2D-canvas tabs.
            window._canvas_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        _c3d.hideEvent = _c3d_hide

    # ── Hover data label ──
    window._hover_label = QLabel("")
    # RichText so field names render with real subscripts (P_A → P<sub>A</sub>)
    # instead of a literal underscore in the cursor readout.
    window._hover_label.setTextFormat(Qt.TextFormat.RichText)
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
