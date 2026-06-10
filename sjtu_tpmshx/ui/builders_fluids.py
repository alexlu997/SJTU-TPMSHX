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
    window.le_uA   = row(window, g1, 1, "<i>u</i><sub>A</sub> [m/s]",  "20.0")
    window.le_TinA = row(window, g1, 2, "<i>T</i><sub>in</sub> [K]",   "422.0")
    window._lbl_TinA_unit = g1.itemAtPosition(2, 0).widget()
    window.le_PinA = row(window, g1, 3, "<i>P</i><sub>in</sub> [Pa]",  "192362")
    _computed_divider(g1, 4)
    window._v_rhoA = res_row(window, g1, 5, "<i>&rho;</i> [kg/m³]")
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
    window.le_uB   = row(window, g2b, 1, "<i>u</i><sub>B</sub> [m/s]",  "0.133")
    window.le_TinB = row(window, g2b, 2, "<i>T</i><sub>in</sub> [K]",   "300.0")
    window._lbl_TinB_unit = g2b.itemAtPosition(2, 0).widget()
    window.le_PinB = row(window, g2b, 3, "<i>P</i><sub>in</sub> [Pa]",  "101973")
    _computed_divider(g2b, 4)
    window._v_rhoB = res_row(window, g2b, 5, "<i>&rho;</i> [kg/m³]")
    window._v_ReB  = res_row(window, g2b, 6, "Re")
    window._v_NuB  = res_row(window, g2b, 7, "Nu")
    window._v_dPLB = res_row(window, g2b, 8, "d<i>P</i>/d<i>L</i> [Pa/m]")
    btn_b = QPushButton("Auto-fill &B")
    btn_b.setFixedHeight(28); btn_b.setStyleSheet(t.style('BTN_SECONDARY'))
    btn_b.setToolTip("Compute Fluid B density / Reynolds / Nusselt / dP·dL from current state")
    btn_b.clicked.connect(window.auto_fill_fluid_b)
    g2b.addWidget(btn_b, 10, 0, 1, 2)

    # ── Inlet / Outlet configuration (unified) ─────────────
    _DIR_ITEMS = ["+x  (left → right)", "-x  (right → left)",
                  "+y  (bottom → top)", "-y  (top → bottom)",
                  "+z  (front → back, 3D)", "-z  (back → front, 3D)"]

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
