"""Fluids-page builder (Boundary Conditions accordion group).

Split out of ui_builders.py (Batch-2, 2026-06-10). Builds the Fluid A /
Fluid B input cards, the per-fluid inlet/outlet (partial-pipe BC)
sections and the polygon pipe-edge selectors.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QScrollArea, QFrame,
)

from .builders_base import section, row, res_row, add_row, _computed_divider

_DIR_ITEMS = ["+x  (left → right)", "-x  (right → left)",
              "+y  (bottom → top)", "-y  (top → bottom)",
              "+z  (front → back, 3D)", "-z  (back → front, 3D)"]

# Inlet/outlet card rows shared by the A/B mirror (B1 1.4). in_ctr/out_ctr
# defaults are per-side (crossflow geometry) and injected by the caller.
_PIPE_ROWS = (
    ('in_ctr',    "Inlet centre [m]",          None),
    ('in_w',      "Inlet width [m]",           "0.042"),
    ('out_ctr',   "Outlet centre [m]",         None),
    ('out_w',     "Outlet width [m]",          "0.042"),
    ('in_z_ctr',  "Inlet z-centre [m] (3D)",   "0.021"),
    ('in_z_w',    "Inlet z-width [m] (3D)",    "0.042"),
    ('out_z_ctr', "Outlet z-centre [m] (3D)",  "0.021"),
    ('out_z_w',   "Outlet z-width [m] (3D)",   "0.042"),
)


def _build_pipe_section(window, lay, side, *, title_style, frame_style,
                        combo_style, dir_index, in_ctr, out_ctr):
    """One ``Fluid X  Inlet / Outlet`` card — the A/B mirror collapsed
    (B1 1.4). Widget names follow the ``le_pipe{side}_*`` /
    ``_lbl_pipe{side}_*`` convention; the four z-rows register in
    ``window._3d_only_widgets`` in (le, lbl) pairs, preserving the
    original ordering.
    """
    gio, sec = section(window, lay, f"  Fluid {side}  Inlet / Outlet",
                       title_style, frame_style)
    window._rect_only_widgets.append(sec)
    combo = QComboBox(); combo.addItems(_DIR_ITEMS)
    combo.setCurrentIndex(dir_index)
    combo.setStyleSheet(combo_style)
    combo.currentIndexChanged.connect(window._on_dir_changed)
    setattr(window, f'combo_dir{side}', combo)
    add_row(window, gio, 0, "Flow direction", combo)
    per_side = {'in_ctr': in_ctr, 'out_ctr': out_ctr}
    for r, (suffix, label, default) in enumerate(_PIPE_ROWS, start=1):
        le = row(window, gio, r, label, per_side.get(suffix, default))
        lbl = gio.itemAtPosition(r, 0).widget()
        setattr(window, f'le_pipe{side}_{suffix}', le)
        setattr(window, f'_lbl_pipe{side}_{suffix}', lbl)
        if '_z_' in suffix:
            window._3d_only_widgets += [le, lbl]


def _build_fluid_io_rows(window, g, side, t, u_default, T_default, P_default,
                         btn_text):
    """Rows 1-10 shared by the Fluid A/B cards: u / T_in / P_in inputs, the
    COMPUTED divider, ρ/Re/Nu/dP·dL result rows and the Auto-fill button.

    Row 0 (fluid-type combo) stays per-side — the supported-fluid sets and
    their tooltips genuinely differ. ``btn_text`` is passed whole so each
    side keeps its original mnemonic (&) position.
    """
    s = side
    setattr(window, f'le_u{s}',
            row(window, g, 1, f"<i>u</i><sub>{s}</sub> [m/s]", u_default))
    setattr(window, f'le_Tin{s}',
            row(window, g, 2, "<i>T</i><sub>in</sub> [K]", T_default))
    setattr(window, f'_lbl_Tin{s}_unit', g.itemAtPosition(2, 0).widget())
    setattr(window, f'le_Pin{s}',
            row(window, g, 3, "<i>P</i><sub>in</sub> [Pa]", P_default))
    _computed_divider(g, 4)
    setattr(window, f'_v_rho{s}', res_row(window, g, 5, "<i>&rho;</i> [kg/m³]"))
    setattr(window, f'_v_Re{s}',  res_row(window, g, 6, "Re"))
    setattr(window, f'_v_Nu{s}',  res_row(window, g, 7, "Nu"))
    setattr(window, f'_v_dPL{s}', res_row(window, g, 8, "d<i>P</i>/d<i>L</i> [Pa/m]"))
    btn = QPushButton(btn_text)
    btn.setFixedHeight(28); btn.setStyleSheet(t.style('BTN_SECONDARY'))
    btn.setToolTip(f"Compute Fluid {s} density / Reynolds / Nusselt / dP·dL "
                   "from current state")
    btn.clicked.connect(getattr(window, f'auto_fill_fluid_{s.lower()}'))
    g.addWidget(btn, 10, 0, 1, 2)


def build_page_fluids(window):
    """Ex-Main_Menu._build_page_fluids(self) -> QScrollArea."""
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI.
    from .field_factory import default_factory
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
    _build_fluid_io_rows(window, g1, 'A', t,
                         u_default="20.0", T_default="422.0",
                         P_default="192362", btn_text="Auto-&fill A")

    # ── Fluid B (input + computed) — sits to the right of Fluid A ─────
    g2b, _ = section(window, _fluids_row_lay, "Fluid B", _T_B, _F_B)
    # Fluid B supports Air + Water (incompressible SIMPLE B path is wired,
    # see run_calculation_3d.py:910-917). sCO₂ remains unsupported until
    # a real-gas property table is added.
    window.combo_fluidB = QComboBox()
    window.combo_fluidB.addItems(_FLUID_TYPES)
    window.combo_fluidB.setCurrentIndex(1)  # default Water (Shanghai cold side)
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
    # Fluid B defaults: Shanghai Electric cold side = Water (case 8,
    # Re_water≈400). Raw values from data/raw_data/20260401-上海电气天然气
    # 加热器实验工况.xlsx Sheet1 row 9: water_in 26.89 °C → 300.0 K (col 24),
    # water_P 647.6 Pa gauge → 101973 Pa abs (col 26), water_flow 5193 ml/min
    # → u_B ≈ 0.133 m/s interstitial (col 11). Driving ΔT = T_inA − T_inB
    # ≈ 122 K (hot air 422 K cooled by cold water 300 K), matching the
    # gas-heater duty.
    _build_fluid_io_rows(window, g2b, 'B', t,
                         u_default="0.133", T_default="300.0",
                         P_default="101973", btn_text="Auto-fill &B")

    # ── Inlet / Outlet configuration (unified, A/B via _build_pipe_section) ──
    # A: +x default, inlet/outlet centred (0.021). B: -y crossflow default,
    # inlet at far edge (0.154), outlet near edge (0.028).
    _build_pipe_section(window, lay, 'A',
                        title_style=_T_A, frame_style=_F_A,
                        combo_style=_COMBO,
                        dir_index=0, in_ctr="0.021", out_ctr="0.021")
    _build_pipe_section(window, lay, 'B',
                        title_style=_T_B, frame_style=_F_B,
                        combo_style=_COMBO,
                        dir_index=3, in_ctr="0.154", out_ctr="0.028")

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
