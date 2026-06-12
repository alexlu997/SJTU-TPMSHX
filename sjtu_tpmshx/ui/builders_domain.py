"""Domain-page builder (Geometry accordion group) + dimensionality toggle.

Split out of ui_builders.py (Batch-2, 2026-06-10). Builds the Domain
Geometry / TPMS Structure / Material / Grid Settings / Results sections
and owns ``_on_dim_changed`` — the 2D↔3D visibility toggle for the
3D-only widgets created here and in builders_fluids.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, QPushButton, QComboBox,
    QScrollArea, QFrame, QCheckBox,
)

from .theme import get_theme
from .builders_base import section, row, res_row, add_row


def _res_ab_row(window, rg, r, label, attr_a, attr_b, *, unit_lbl_attrs=None):
    """One A/B result-row pair in the results grid (B1 1.4): same label,
    column 0 for Fluid A and column 2 for Fluid B. ``unit_lbl_attrs``
    optionally captures the two label widgets (for the K/°C unit toggle).
    """
    setattr(window, attr_a, res_row(window, rg, r, label, 0))
    setattr(window, attr_b, res_row(window, rg, r, label, 2))
    if unit_lbl_attrs is not None:
        try:
            for col, lbl_attr in zip((0, 2), unit_lbl_attrs):
                item = rg.itemAtPosition(r, col)
                if item is not None:
                    setattr(window, lbl_attr, item.widget())
        except Exception:
            pass


def _on_dim_changed(window):
    """Toggle visibility of 3D-only inputs based on Dimensionality combo.

    Iterates the ``window._3d_only_widgets`` registry — populated by
    ``build_page_domain`` (Lz/Nz rows + 3D checkboxes) and
    ``builders_fluids.build_page_fluids`` (z-partial BC rows) as the
    widgets are created. New 3D-only widgets just register themselves;
    no hardcoded attribute list to keep in sync.
    """
    is_3d = window.combo_dim.currentIndex() == 1
    for w in getattr(window, '_3d_only_widgets', []):
        w.setVisible(is_3d)
    # Mode change also reveals/hides the result tabs for the current mode
    if hasattr(window, '_update_tab_visibility'):
        window._update_tab_visibility()


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

    # 3D-only widget registry — reset here because the domain page builds
    # first on every (re)build; builders_fluids appends its z-partial rows.
    window._3d_only_widgets = []

    # Domain Geometry
    g, _ = section(window, lay, "  Domain Geometry", _T_NEUTRAL, _F_NEUTRAL)
    window.le_L        = row(window, g, 0, "Length <i>L</i> [m]",                     "0.182")
    window.le_H        = row(window, g, 1, "Width <i>H</i> [m]",                      "0.042")
    window.le_Lz       = row(window, g, 2, "Depth <i>L<sub>z</sub></i> [m] (3D only)", "0.042")
    window._lbl_Lz     = g.itemAtPosition(2, 0).widget()
    window._3d_only_widgets += [window.le_Lz, window._lbl_Lz]

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
    # t default: 0.6 mm = the Shanghai Electric specimen wall thickness
    # (canonical geometry). This is 20% above the ConstDF-v1 surrogate
    # training window [0.3, 0.5], so the default GUI run WILL show the
    # extrapolation watermark — `chk_allow_extrap` defaults ON, so it warns
    # rather than aborts. Re-train the surrogate to expand the range when
    # new CFD data arrives.
    window.le_t     = row(window, g0, 2, "<i>t</i> [mm]", "0.6")
    window.le_ks    = row(window, g0, 3, "<i>k</i><sub>s</sub> [W/(m·K)]", "16.0")
    btn_tpms = QPushButton("Compute TPMS &Geometry")
    btn_tpms.setFixedHeight(28); btn_tpms.setStyleSheet(t.style('BTN_SECONDARY'))
    btn_tpms.setToolTip("Compute porosity, specific area, hydraulic diameter, k_ss from current L_cell / t")
    btn_tpms.clicked.connect(window.compute_tpms)
    g0.addWidget(btn_tpms, 4, 0, 1, 2)
    # Computed outputs (green values)
    window._v_eps  = res_row(window, g0, 5, "<i>&epsilon;</i>")
    window._v_A0   = res_row(window, g0, 6, "<i>A</i><sub>0</sub> [m<sup>-1</sup>]")
    window._v_Dh   = res_row(window, g0, 7, "<i>D<sub>h</sub></i> [mm]")
    window._v_Kss  = res_row(window, g0, 8, "<i>K</i><sub>ss</sub> [W/(m·K)]")

    # Surrogate-domain guard. Default ON — near-boundary extrapolation
    # (e.g. Shanghai t=0.6 mm, 20% past the [0.3, 0.5] cap) is the common
    # validation workflow. Unchecking reverts to strict: out-of-window
    # inputs abort Compute. Either way, extrapolated results carry an
    # `extrapolated=True` flag and a watermark on every plot for
    # traceability.
    window.chk_allow_extrap = QCheckBox("Allow surrogate extrapolation")
    window.chk_allow_extrap.setChecked(True)
    window.chk_allow_extrap.setToolTip(
        "ConstDF-v1 训练域: L ∈ [4, 8] mm, t ∈ [0.3, 0.5] mm, Re ∈ [400, 16000].\n"
        "默认严格: 超出任一范围 Compute 拒绝运行.\n"
        "勾选后: 超出仅 warn, 结果标记为 extrapolated, 图上加水印.\n"
        "用于 Shanghai t=0.6 mm 等近边界验证工况."
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

    # Material — only rho_s remains (k_s is in the solver/geometry panel).
    # cp_s and cp_f were removed: no solver path reads them. Solid cp is a
    # per-material constant hardcoded downstream; fluid cp is computed
    # per-cell via air_cp(T) inside tpms_calc.
    g2, _ = section(window, lay, "  Material Properties", _T_NEUTRAL, _F_NEUTRAL)
    window.le_rho_s = row(window, g2, 0, "<i>&rho;</i><sub>s</sub> [kg/m³]", "7900")
    # rho_s is NOT consumed by the steady-state LTNE energy equation
    # (∂T_s/∂t is dropped → ρ_s·cp_s prefactor disappears). It is saved with
    # the session config for forward compatibility with a future transient
    # extension (kernel would add ρ_s·cp_s·(T_s^{n+1}−T_s^n)/Δt).
    window.le_rho_s.setToolTip(
        "Solid density. Saved with session config but NOT read by the "
        "current steady-state LTNE solver (no ∂T_s/∂t term in the solid "
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
    window._3d_only_widgets += [window.le_Nz, window._lbl_Nz]

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
    window._3d_only_widgets.append(window.chk_wall_refine_3d)
    # NOTE: legacy `_chk_wall_refine_3d` alias removed 2026-05-05 audit;
    # no remaining readers (grep confirmed). Use `chk_wall_refine_3d`.

    # 3D variable-rho_cp checkbox — LTNE energy kernel builds gas density from
    # SIMPLE's LOCAL cell pressure ρ(P_local,T) instead of inlet ρ(T,P_in).
    # Conserves COMPRESSIBLE reverse-dir flow (Q_A≈Q_B); strict certificate
    # machine-zero; Shanghai bit-identical. ON by default (2026-06-09) — uncheck
    # for the legacy inlet-pressure density.
    window.chk_var_rhocp = QCheckBox("Local-P gas density (3D)")
    window.chk_var_rhocp.setChecked(True)
    window.chk_var_rhocp.setToolTip(
        "3D LTNE energy kernel: gas density ρ=P/RT from the LOCAL cell pressure "
        "(SIMPLE) instead of the inlet pressure. Conserves energy for "
        "compressible reverse-dir flow (Q_A≈Q_B). Strict conservation stays "
        "machine-zero; Shanghai bit-identical; low-ΔP cases unchanged. "
        "ON = default; uncheck for the legacy inlet-pressure density.")
    window.chk_var_rhocp.setStyleSheet(window.chk_wall_refine_3d.styleSheet())
    g4.addWidget(window.chk_var_rhocp, 4, 0, 1, 2)
    window._3d_only_widgets.append(window.chk_var_rhocp)

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
    for c, txt in enumerate(["── Fluid A ──", "── Fluid B ──"]):
        h = QLabel(txt)
        h.setStyleSheet(_LBL)
        h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rg.addWidget(h, 0, c * 2, 1, 2)
    # A/B result rows via the shared mirror helper (B1 1.4).
    # 2026-05-20 UI sweep: the T_out unit labels are captured so the K/°C
    # toggle (`_sync_temp_unit_labels` in main.py) can rewrite the `[K]`
    # suffix when the user flips the header unit button.
    _res_ab_row(window, rg, 1, "<i>T</i><sub>out</sub> [K]",
                '_r_ToutA', '_r_ToutB',
                unit_lbl_attrs=('_lbl_ToutA_unit', '_lbl_ToutB_unit'))
    _res_ab_row(window, rg, 2, "Δ<i>P</i><sub>total</sub> [Pa]",
                '_r_dP_A', '_r_dP_B')
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
