"""Strict-typed compute configuration dataclasses.

Audit followup C3 (L-a-1, 2026-05-28): replace the implicit "window
object holds all settings" contract with explicit dataclasses. The
solver / runs / optimization / validation layers all accept
``ComputeConfig`` instead of the Qt window. The UI layer is the *only*
place that reads ``QLineEdit`` / ``QComboBox`` values — everything
below this module is Qt-free.

The module is deliberately pure: no imports from ``sjtu_tpmshx``
internals (only stdlib + ``typing``). This avoids any circular import
risk and keeps the schema readable from a single file.

Schema (per
``vault/reports/engineering/2026-05-28-sjtu-tpmshx-4-perspective-audit-CN.html``
§视角2 §2.2 with minor extensions noted inline):

- ``FluidConfig``     — per-side fluid (type + u + T_in + P_in)
- ``GeometryConfig``  — domain + TPMS unit-cell + solid k_s
- ``SolverConfig``    — grid + LTNE outer + SIMPLE inner + roughness
- ``ComputeConfig``   — composite, has the entrypoint adapters

Adapters
~~~~~~~~

- ``ComputeConfig.from_qt_window(window)`` — read ``window.le_*`` /
  ``window.combo_*`` once at the UI boundary; downstream callers no
  longer touch ``window``.
- ``ComputeConfig.from_json(path)`` / ``to_json(path)`` — JSON
  serialisation for production validation scripts and tests.

Roadmap
~~~~~~~

C3 is the foundation for C4 (Pipeline ABC).  This module purposefully
does *not* describe partial-pipe BC, zone configs, or session state
(extrap reasons, cancel tokens) — those continue through their
existing window attributes for now; the grep gate (Task 4.3) limits
the scope to ``window.le_*`` reads, which this dataclass replaces.

Runtime env-flag registry (Batch-4, 2026-06-10)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Central inventory of every ``TPMSHX_*`` knob. Flags are read at call
time (never cached) so tests can monkeypatch them; each has one reading
site or one shared helper, listed here. Adding a flag = add a row.

- ``TPMSHX_ALLOW_EXTRAP`` (0) — surrogate out-of-window → warn, not abort.
  Read in ``df_surrogate/surrogate_domain.py``, ``solvers/sigmoid_field.py``,
  ``solvers/sigmoid_field_3d.py`` (3 identical 1-line parsers — kept local
  to avoid a solvers→df_surrogate dependency; keep in sync).
- ``TPMSHX_CHI_S`` (1.0) — solid-k anisotropy χ_s; ``solvers/tpms_calc.py``
  (module-level, fixed at import).
- ``TPMSHX_DEBUG`` (unset) — debug prints; ``solvers/simple_solver_3d.py``.
- ``TPMSHX_DF_RESIDUAL_CORR`` (0) — dP residual-learning correction;
  ``df_surrogate/predict.py``.
- ``TPMSHX_DISABLE_3D_PANEL`` (0) — skip PyVista panel;
  ``ui/builders_canvas.py``.
- ``TPMSHX_EAGER_3D_SLICES`` (0) — precompute 3D slices;
  ``ui/plot_3d_results.py``.
- ``TPMSHX_PARALLEL_THRESHOLD`` (200000) — red-black prange cell gate;
  ``solvers/simple_solver_3d.py`` (module-level, fixed at import).
- ``TPMSHX_PHASE_A/B/C`` (1/0/0) — SIMPLE acceleration phases; single
  helper ``pipelines.stages_3d._apply_phase_flags`` (cfg keys win).
- ``TPMSHX_PREINIT_3D`` (0) — prewarm 3D panel at startup; ``main.py``.
- ``TPMSHX_PROFILE_3D`` (0) — cProfile the 3D solve;
  ``pipelines/stages_3d.py``.
- ``TPMSHX_ROUGH_MODE`` (baseline; UI path defaults norris_1a) +
  ``TPMSHX_ROUGH_EPS_UM`` (100) — roughness model; single helper
  ``solvers.roughness.resolve_mode_from_env``.
- ``TPMSHX_RUN_SHANGHAI_REGRESSION`` (0) — opt-in long validation gate;
  ``tests/test_shanghai_regression.py``.
- ``TPMSHX_SIMPLE_TOL`` (1e-5) — SIMPLE pp tol for diagnostic sweeps;
  single helper ``pipelines.stages_3d._simple_tol_default``.
- ``TPMSHX_VAR_RHOCP`` (unset) — local-P gas density override (UI checkbox
  is primary); ``pipelines/stages_3d.py``.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Union


FluidType = Literal['air', 'water', 'sco2']
TPMSType = Literal['Diamond', 'Gyroid']
RoughMode = Literal['baseline', 'norris_1a', 'bhatti_shah_1b']
ZoneAxis = Literal['x', 'y', 'grid']


# ── helpers ──────────────────────────────────────────────────────────


def _qt_text(widget) -> str:
    """Return ``widget.text()`` (QLineEdit) or ``widget.currentText()``
    (QComboBox) or ``''`` for any AttributeError/None.

    Optional widgets (le_TsInit, le_PinB, combo_fluidB, …) are guarded
    by ``hasattr`` upstream; mirror that here so the adapter never
    raises on a stripped-down test stub.
    """
    if widget is None:
        return ''
    text_fn = getattr(widget, 'text', None) or getattr(
        widget, 'currentText', None)
    if text_fn is None:
        return ''
    try:
        return text_fn()
    except Exception:
        return ''


def _qt_float(widget, default: float) -> float:
    """Parse ``widget.text()`` as float, fall back to ``default``."""
    txt = _qt_text(widget).strip()
    if not txt:
        return default
    try:
        return float(txt)
    except (TypeError, ValueError):
        return default


def _qt_int(widget, default: int) -> int:
    """Parse ``widget.text()`` as int, fall back to ``default``."""
    txt = _qt_text(widget).strip()
    if not txt:
        return default
    try:
        return int(txt)
    except (TypeError, ValueError):
        return default


# Required widget attributes for strict-mode validation. The labels mirror
# the human-friendly names that the legacy ``pipelines.stages_2d._parse``
# helper surfaced in its ``ValueError`` payload.
@dataclass(frozen=True)
class FieldSpec:
    """One scalar ComputeConfig field's wiring: dataclass slot ↔ Qt widget
    ↔ parse kind ↔ required-validation membership (B2 2.4, 2026-06-12).

    Single source for the add-a-field procedure — previously adding one
    field meant touching the dataclass, ``from_qt_window``, and the
    ``_REQUIRED_*`` lists independently (silent-default drift when one
    was missed). ``kind``: 'float' | 'int' | 'temp' (unit-aware Kelvin).
    ``special=True`` rows participate in validation only; their read has
    bespoke semantics kept explicit in ``from_qt_window`` (cross-field
    defaults, None-when-missing, combo parsing).
    """
    section: str            # 'geometry' | 'solver' | 'fluid_A' | 'fluid_B'
    name: str               # dataclass field name
    widget: str             # window attribute, e.g. 'le_Lcell'
    kind: str               # 'float' | 'int' | 'temp'
    default: Any
    label: str = ''         # human label for the validation message
    required_2d: bool = False
    required_3d_extra: bool = False
    special: bool = False   # validated here, read bespokely


# Declaration order == legacy validation-message order (2D block first,
# then the 3D extras), preserved verbatim from the retired _REQUIRED_* lists.
CONFIG_FIELDS: tuple = (
    FieldSpec('geometry', 'L_dom_m',   'le_L',     'float', 0.182,
              label="Domain Length (L)", required_2d=True),
    FieldSpec('geometry', 'H_dom_m',   'le_H',     'float', 0.042,
              label="Domain Height (H)", required_2d=True),
    FieldSpec('solver',   'Nx',        'le_Nx',    'int',   30,
              label="Grid Nx", required_2d=True),
    FieldSpec('solver',   'Ny',        'le_Ny',    'int',   60,
              label="Grid Ny", required_2d=True),
    FieldSpec('fluid_A',  'u_mps',     'le_uA',    'float', 5.0,
              label="Velocity A (u_A)", required_2d=True),
    FieldSpec('fluid_B',  'u_mps',     'le_uB',    'float', None,
              label="Velocity B (u_B)", required_2d=True,
              special=True),   # default = fluid_A.u_mps (cross-field)
    FieldSpec('fluid_A',  'T_in_K',    'le_TinA',  'temp',  300.0,
              label="Inlet Temp A (T_inA)", required_2d=True),
    FieldSpec('fluid_B',  'T_in_K',    'le_TinB',  'temp',  300.0,
              label="Inlet Temp B (T_inB)", required_2d=True),
    FieldSpec('geometry', 'L_cell_mm', 'le_Lcell', 'float', 7.0,
              label="TPMS L_cell", required_2d=True),
    FieldSpec('geometry', 't_wall_mm', 'le_t',     'float', 0.6,
              label="TPMS t", required_2d=True),
    FieldSpec('geometry', 'k_s_W_mK',  'le_ks',    'float', 16.0,
              label="TPMS k_s", required_2d=True),
    FieldSpec('geometry', 'Lz_m',      'le_Lz',    'float', 0.042,
              label="Width Lz", required_3d_extra=True,
              special=True),   # None when the widget is absent (2D flag)
    FieldSpec('solver',   'Nz',        'le_Nz',    'int',   1,
              label="Grid Nz", required_3d_extra=True),
    # Non-required scalars (read table-driven, no validation membership):
    FieldSpec('fluid_A',  'P_in_Pa',   'le_PinA',  'float', 101325.0),
    FieldSpec('fluid_B',  'P_in_Pa',   'le_PinB',  'float', 101325.0),
)


def _read_section_fields(window, section: str) -> dict:
    """Table-driven scalar reads for one config section (non-special rows)."""
    out = {}
    for fs in CONFIG_FIELDS:
        if fs.section != section or fs.special:
            continue
        w = getattr(window, fs.widget, None)
        if fs.kind == 'float':
            out[fs.name] = _qt_float(w, fs.default)
        elif fs.kind == 'int':
            out[fs.name] = _qt_int(w, fs.default)
        elif fs.kind == 'temp':
            out[fs.name] = _temp_in_K(window, w, default_K=fs.default)
    return out


def _validate_required_widgets(window, *, is_3d: bool) -> None:
    """Raise ``ValueError`` listing every blank / non-numeric required
    widget — preserves the legacy behaviour of
    ``pipelines.stages_2d._parse``. Membership and message order come
    from CONFIG_FIELDS (B2 2.4).
    """
    required = [fs for fs in CONFIG_FIELDS if fs.required_2d]
    if is_3d:
        required += [fs for fs in CONFIG_FIELDS if fs.required_3d_extra]
    bad = []
    for fs in required:
        widget = getattr(window, fs.widget, None)
        if widget is None:
            bad.append(fs.label)
            continue
        txt = _qt_text(widget).strip()
        if not txt:
            bad.append(fs.label)
            continue
        caster = int if fs.kind == 'int' else float
        try:
            caster(txt)
        except ValueError:
            bad.append(fs.label)
    if bad:
        raise ValueError(f"Invalid input in: {', '.join(bad)}")


def _parse_fluid_label(combo) -> FluidType:
    """Inline copy of ``solvers.tpms_calc.parse_fluid_type``.

    Keeping the small mapping inline avoids importing the solver
    package from this controller module (purity rule, see header).
    """
    if combo is None:
        return 'air'
    try:
        text = combo.currentText().lower().replace('₂', '2')
    except Exception:
        return 'air'
    if 'co2' in text or 'sco' in text:
        return 'sco2'
    if 'water' in text:
        return 'water'
    return 'air'


def _temp_in_K(window, widget, default_K: float) -> float:
    """Honour the window's ``_temp_to_K`` toggle if present.

    Both ``run_calculation._parse_inputs`` and
    ``run_calculation_3d._parse_inputs`` route inlet-temperature reads
    through ``window._temp_to_K`` so the K/°C UI toggle is honoured.
    We do the same here so ``from_qt_window`` always returns Kelvin.
    """
    if widget is None:
        return default_K
    converter = getattr(window, '_temp_to_K', None)
    if converter is not None:
        try:
            return float(converter(widget))
        except Exception:
            pass  # fall back to direct float read
    return _qt_float(widget, default_K)


def _read_partial_bc(window, side: Literal['A', 'B']) -> 'PartialBCConfig':
    """Snapshot the per-side partial-pipe BC widgets into a dataclass.

    Mirrors ``Main_Menu._fluid_config(side)`` but does not call back into
    the window once the cfg is built. Optional z-partial widgets are
    only honoured when the matching ``le_pipe<side>_in_z_*`` widgets
    exist and are visible (3D mode); otherwise the z-fields stay
    ``None`` and the solver treats the z-axis as full-face.

    ``side='B'`` defaults to ``dir=3`` (-y) when ``combo_dirB`` is
    missing, matching the legacy ``pipelines.stages_2d._parse_inputs``
    fall-through (``cfgB = dict(dir=3, …)``).
    """
    le_prefix = f'le_pipe{side}'
    combo_dir = getattr(window, f'combo_dir{side}', None)
    default_dir = 3 if side == 'B' else 0
    dir_int = default_dir
    if combo_dir is not None:
        try:
            dir_int = int(combo_dir.currentIndex())
        except Exception:
            dir_int = default_dir
    bc = PartialBCConfig(
        dir=dir_int,
        in_ctr=_qt_float(getattr(window, f'{le_prefix}_in_ctr', None), 0.0),
        in_w=_qt_float(getattr(window, f'{le_prefix}_in_w', None), 0.0),
        out_ctr=_qt_float(getattr(window, f'{le_prefix}_out_ctr', None), 0.0),
        out_w=_qt_float(getattr(window, f'{le_prefix}_out_w', None), 0.0),
    )
    # 3D z-partial widgets are only present (and visible) in 3D mode.
    le_in_z_ctr = getattr(window, f'{le_prefix}_in_z_ctr', None)
    if le_in_z_ctr is not None:
        try:
            visible = not le_in_z_ctr.isHidden()
        except Exception:
            visible = True
        if visible:
            # FIX (2026-06-24 audit): parse all four z-values into locals first,
            # then commit to bc only if EVERY parse succeeds. The old code mutated
            # bc field-by-field, so a mid-sequence ValueError/AttributeError (e.g.
            # one z-widget blank/non-numeric) left a HALF-populated config (some
            # float, some None). bc_to_dict gates only on in_z_ctr is not None and
            # then emits all four keys, so a half state writes out_z_w=None, and
            # _build_partial_masks (stages_3d) crashes on `None / 2`. Atomic
            # all-or-nothing matches the documented all-None fallback.
            try:
                _in_z_ctr  = float(le_in_z_ctr.text())
                _in_z_w    = float(getattr(window, f'{le_prefix}_in_z_w').text())
                _out_z_ctr = float(getattr(window, f'{le_prefix}_out_z_ctr').text())
                _out_z_w   = float(getattr(window, f'{le_prefix}_out_z_w').text())
            except (AttributeError, ValueError):
                # Leave z-fields as None — solver treats as full face.
                pass
            else:
                bc.in_z_ctr, bc.in_z_w = _in_z_ctr, _in_z_w
                bc.out_z_ctr, bc.out_z_w = _out_z_ctr, _out_z_w
    return bc


def _read_zone_input(window) -> 'ZoneInputConfig':
    """Snapshot zone / sigmoid-field control state.

    Reads ``chk_zones``, ``combo_zone_axis``, ``_zone_grid``, and the
    ``_pareto_*`` attributes. When ``chk_zones`` is checked, also
    pre-resolves the ``ZoneConfig`` instance via
    ``ui.zone_table.build_zone_config(window)`` so the downstream
    Pipeline2D / Pipeline3D layer never touches the Qt zone-table
    widget.

    The pre-resolution is wrapped in ``try/except`` so test stubs that
    set ``chk_zones=True`` but skip the full ``zone_table`` widget
    still produce a usable ``ZoneInputConfig`` (with ``config=None``).
    """
    chk = getattr(window, 'chk_zones', None)
    enabled = bool(chk is not None and getattr(chk, 'isChecked', lambda: False)())
    axis: ZoneAxis = 'y'
    combo = getattr(window, 'combo_zone_axis', None)
    if combo is not None:
        try:
            idx = int(combo.currentIndex())
            axis = ('y', 'x', 'grid')[max(0, min(idx, 2))]
        except Exception:
            axis = 'y'

    # Pre-resolve ZoneConfig (1D zone mode needs the zone-table rows).
    # Grid mode populates ``window._zone_grid`` as a side effect of the
    # same call.  Skip silently when the call cannot fire — tests pass
    # plain ``object()`` stubs without a real zone_table widget.
    resolved_config = None
    if enabled:
        try:
            from ui.zone_table import build_zone_config as _bzc
            resolved_config = _bzc(window)
        except Exception:
            resolved_config = None
    grid = getattr(window, '_zone_grid', None)
    return ZoneInputConfig(
        enabled=enabled,
        axis=axis,
        grid=grid if isinstance(grid, dict) else None,
        config=resolved_config,
        pareto_x_decision=getattr(window, '_pareto_x_decision', None),
        pareto_y_trans_inlet=float(
            getattr(window, '_pareto_y_trans_inlet', 0.2)),
        pareto_y_trans_outlet=float(
            getattr(window, '_pareto_y_trans_outlet', 0.2)),
    )


def _read_feature_flags(window) -> 'FeatureFlags':
    """Snapshot UI feature-flag toggles that survive into the solver."""
    chk_wall = getattr(window, 'chk_wall_refine_3d', None)
    wall = bool(chk_wall is not None and
                getattr(chk_wall, 'isChecked', lambda: False)())
    # variable_rho_cp defaults ON (2026-06-09); an absent toggle (old/partial
    # window) keeps the default, a present one mirrors its checked state.
    chk_vrc = getattr(window, 'chk_var_rhocp', None)
    var_rhocp = (bool(getattr(chk_vrc, 'isChecked', lambda: True)())
                 if chk_vrc is not None else True)
    unit = getattr(window, '_temp_unit', 'K')
    if unit not in ('K', 'C'):
        unit = 'K'
    return FeatureFlags(wall_refine_3d=wall, variable_rho_cp=var_rhocp,
                        temp_unit=unit)


def _read_extrap_policy(window) -> 'ExtrapPolicy':
    """Snapshot the surrogate-domain extrapolation allow flag."""
    chk = getattr(window, 'chk_allow_extrap', None)
    allow = bool(chk is not None and
                 getattr(chk, 'isChecked', lambda: False)())
    return ExtrapPolicy(allow=allow)


# ── dataclasses ──────────────────────────────────────────────────────


@dataclass
class FluidConfig:
    """Single-side fluid inlet state."""
    type: FluidType = 'air'
    u_mps: float = 5.0
    T_in_K: float = 300.0
    P_in_Pa: float = 101325.0


@dataclass
class GeometryConfig:
    """TPMS unit cell + macroscopic domain + solid conductivity.

    ``Lz_m=None`` flags a 2D run; the legacy 2D path keeps using the
    XY plane and ignores Lz, while the 3D path *requires* ``Lz_m``
    (and ``solver.Nz >= 2``).
    """
    tpms: TPMSType = 'Gyroid'
    L_cell_mm: float = 7.0
    t_wall_mm: float = 0.6
    k_s_W_mK: float = 16.0
    L_dom_m: float = 0.182
    H_dom_m: float = 0.042
    Lz_m: Optional[float] = None
    # Asymmetric porosity: offset-isosurface centre δ (φ-units). 0.0 →
    # symmetric 50/50 (bit-identical). |δ|>0 → ε_A (φ<δ−C) ≠ ε_B (φ>δ+C);
    # consumed by pipelines.stages_3d._eps_sides_for_run. Human targets
    # (A%/B%) convert to δ in run scripts via runs/asym_target_scan.
    delta_levelset: float = 0.0


@dataclass
class SolverConfig:
    """LTNE outer + SIMPLE inner + grid + roughness model.

    ``T_s_init_K=None`` falls back to the legacy seed
    ``0.5 * (T_inA + T_inB)`` inside ``solve_full_domain[_3d]``.
    ``rough_mode='norris_1a'`` matches the runtime default established
    by the 2026-05 audit (see ``feedback_dp_gap_attribution`` memory).
    """
    max_outer_ltne: int = 4
    outer_tol_K: float = 0.5
    max_iter_simple: int = 800
    tol_simple: float = 1e-2
    alpha_T: float = 0.7
    rough_mode: RoughMode = 'norris_1a'
    Nx: int = 30
    Ny: int = 60
    Nz: int = 1
    T_s_init_K: Optional[float] = None


@dataclass
class PartialBCConfig:
    """Per-side partial-pipe inlet/outlet placement (cross-stream).

    ``dir`` is the flow direction encoded by ``window._DIR_MAP``:
    ``0=+x``, ``1=-x``, ``2=+y``, ``3=-y``. ``in_ctr``/``in_w`` and
    ``out_ctr``/``out_w`` are inlet / outlet centre + width in the
    cross-stream coordinate (m). ``in_z_*``/``out_z_*`` extend to the
    3D z-axis partial mask; ``None`` means "full face along z".

    Audit C4 (L-a-2): added so the pipeline does not have to call back
    into ``window._fluid_config(which)``.
    """
    dir: int = 0
    in_ctr: float = 0.0
    in_w: float = 0.0
    out_ctr: float = 0.0
    out_w: float = 0.0
    in_z_ctr: Optional[float] = None
    in_z_w: Optional[float] = None
    out_z_ctr: Optional[float] = None
    out_z_w: Optional[float] = None


def bc_to_dict(bc: 'PartialBCConfig', L_dom: float, H_dom: float,
               *, side: str = 'A', with_z: bool = False):
    """Convert a :class:`PartialBCConfig` into the legacy solver BC dict.

    Single source for the 2D + 3D conversions (was three near-duplicate
    ``_bc_cfg_to_dict_*`` functions). The side-B asymmetry is INTENTIONAL —
    it reproduces the legacy ValueError fallback in ``_parse_inputs``:

    * ``side='A'`` — a degenerate BC (``in_w<=0`` or ``out_w<=0``) falls back
      to a full-face inlet/outlet spanning the cross-stream axis. Used by the
      2D path (both sides) and 3D side A.
    * ``side='B'`` — a *fully* degenerate BC (``in_w<=0`` AND ``out_w<=0``)
      returns ``None``, which the 3D solver reads as "full-face cross-flow";
      a partially-degenerate BC returns the raw partial dict (no full-face
      fallback). 3D side B only.
    * ``with_z=True`` — append the ``in_z_*``/``out_z_*`` overlay when the cfg
      captured 3D z-partial fields (``None`` = full face along z).
    """
    is_x_flow = bc.dir in (0, 1)
    cross_dim = H_dom if is_x_flow else L_dom
    if side == 'B' and bc.in_w <= 0 and bc.out_w <= 0:
        return None
    if (bc.in_w > 0 and bc.out_w > 0) or side == 'B':
        d = dict(dir=bc.dir, in_ctr=bc.in_ctr, in_w=bc.in_w,
                 out_ctr=bc.out_ctr, out_w=bc.out_w)
    else:
        d = dict(dir=bc.dir, in_ctr=cross_dim / 2, in_w=cross_dim,
                 out_ctr=cross_dim / 2, out_w=cross_dim)
    if with_z and bc.in_z_ctr is not None:
        d['in_z_ctr'] = bc.in_z_ctr
        d['in_z_w'] = bc.in_z_w
        d['out_z_ctr'] = bc.out_z_ctr
        d['out_z_w'] = bc.out_z_w
    return d


@dataclass
class ZoneInputConfig:
    """Zone / sigmoid-field control state.

    Captures the inputs that the legacy ``window._build_zone_config()``
    + ``window._zone_axis()`` pair plus the ``_pareto_*`` attributes
    fed into the 2D/3D solver.

    ``config`` is the pre-resolved ``solvers.zone_config.ZoneConfig``
    instance (1D zone mode) or ``None`` when zones are disabled or
    running in grid mode (``grid`` carries the cell list instead).
    The UI adapter snapshots ``config`` via
    ``window._build_zone_config()`` at the boundary so the Pipeline
    layer never has to touch the Qt zone-table widget.

    Audit C4 (L-a-2).
    """
    enabled: bool = False
    axis: ZoneAxis = 'y'
    grid: Optional[Dict[str, Any]] = None  # cells / tpms_type / k_s
    config: Optional[Any] = None  # resolved ZoneConfig instance (1D)
    pareto_x_decision: Optional[Any] = None
    pareto_y_trans_inlet: float = 0.2
    pareto_y_trans_outlet: float = 0.2


@dataclass
class ExtrapPolicy:
    """Surrogate-domain extrapolation policy.

    ``allow`` mirrors the ``chk_allow_extrap`` checkbox (or the
    ``TPMSHX_ALLOW_EXTRAP=1`` env var read by the optimizer entrypoints).
    The pipeline appends string reasons to a separate ``warnings`` list
    on :class:`ComputeResult`; this dataclass is *input only*.

    Audit C4 (L-a-2).
    """
    allow: bool = False


@dataclass
class FeatureFlags:
    """UI toggles that survive into the solver layer.

    ``wall_refine_3d`` mirrors ``window.chk_wall_refine_3d`` (3D wall
    boundary-layer refinement). ``variable_rho_cp`` mirrors
    ``window.chk_var_rhocp`` (3D LTNE energy-kernel gas density from SIMPLE's
    local pressure ρ(P_local,T) instead of inlet pressure — conserves
    compressible reverse flow; default off). ``temp_unit`` mirrors
    ``window._temp_unit`` purely for round-tripping; ComputeConfig fields are
    always Kelvin so the solver itself never needs this flag.

    Audit C4 (L-a-2).
    """
    wall_refine_3d: bool = False
    variable_rho_cp: bool = True   # default ON (local-P gas density; 2026-06-09)
    temp_unit: Literal['K', 'C'] = 'K'


@dataclass
class ComputeConfig:
    """Composite settings handed to solver-side entrypoints.

    Constructed at the UI boundary via :meth:`from_qt_window` or at a
    script/test boundary via :meth:`from_json`. Downstream consumers
    *only* see this object.
    """
    fluid_A: FluidConfig = field(default_factory=FluidConfig)
    fluid_B: FluidConfig = field(default_factory=FluidConfig)
    geometry: GeometryConfig = field(default_factory=GeometryConfig)
    solver: SolverConfig = field(default_factory=SolverConfig)
    # ── audit C4 additions: cover the non-le_* window state that the
    # ── pipeline needs but C3 deliberately punted on.
    bc_A: PartialBCConfig = field(default_factory=PartialBCConfig)
    bc_B: PartialBCConfig = field(default_factory=PartialBCConfig)
    zones: ZoneInputConfig = field(default_factory=ZoneInputConfig)
    extrap: ExtrapPolicy = field(default_factory=ExtrapPolicy)
    flags: FeatureFlags = field(default_factory=FeatureFlags)

    # ── derived ──────────────────────────────────────────────────────

    @property
    def is_3d(self) -> bool:
        """True when the solver should run on the full 3D grid."""
        return int(self.solver.Nz) >= 2

    # ── adapters ─────────────────────────────────────────────────────

    @classmethod
    def from_qt_window(cls, window, *, strict: bool = False,
                       force_3d: Optional[bool] = None) -> 'ComputeConfig':
        """Build a ``ComputeConfig`` from the main UI window.

        Reads ``window.le_*`` and ``window.combo_*`` exactly once.
        Missing optional widgets fall back to the dataclass defaults.

        This is the *only* place in the codebase allowed to read
        ``QLineEdit.text()`` / ``QComboBox.currentText()`` and feed it
        into the solver layer.

        Parameters
        ----------
        window : Main_Menu
            The Qt window holding the QLineEdit / QComboBox widgets.
        strict : bool, optional
            When ``True``, raise ``ValueError`` listing every blank /
            non-numeric required widget — mirrors the legacy validation
            inside ``pipelines.stages_2d._parse_inputs``. Defaults to
            ``False`` so tests / scripts can build partial configs.
        force_3d : bool, optional
            Override the 3D-validation set. ``True`` requires Lz/Nz,
            ``False`` only requires the 2D set, ``None`` (default)
            decides from ``int(window.le_Nz.text()) >= 2`` after the
            cheap parse.
        """
        if strict:
            is_3d_for_check = force_3d
            if is_3d_for_check is None:
                try:
                    _nz_widget = getattr(window, 'le_Nz', None)
                    is_3d_for_check = (
                        _nz_widget is not None and
                        int(_qt_text(_nz_widget).strip() or '1') >= 2
                    )
                except ValueError:
                    is_3d_for_check = False
            _validate_required_widgets(window, is_3d=bool(is_3d_for_check))
        # ── table-driven scalar reads (B2 2.4: CONFIG_FIELDS single source;
        # ── special rows keep their bespoke semantics explicit below) ──
        # geometry — tpms combo parse + Lz None-when-absent are special:
        tpms = _qt_text(getattr(window, 'combo_tpms', None)) or 'Gyroid'
        if tpms not in ('Diamond', 'Gyroid'):
            tpms = 'Gyroid'
        geom = GeometryConfig(
            tpms=tpms,
            Lz_m=(_qt_float(getattr(window, 'le_Lz', None), 0.042)
                  if getattr(window, 'le_Lz', None) is not None else None),
            **_read_section_fields(window, 'geometry'),
        )

        # solver — optional Ts init (empty / None → solver default seed):
        T_s_init: Optional[float] = None
        le_ts = getattr(window, 'le_TsInit', None)
        if le_ts is not None and _qt_text(le_ts).strip():
            T_s_init = _temp_in_K(window, le_ts, default_K=0.0) or None
        solver = SolverConfig(
            T_s_init_K=T_s_init,
            # remaining knobs keep dataclass defaults; UI does not surface
            # them yet (audit deferred to a later phase)
            **_read_section_fields(window, 'solver'),
        )

        # fluids — type combos special; fluid_B.u_mps defaults to A's value:
        fluid_A = FluidConfig(
            type=_parse_fluid_label(getattr(window, 'combo_fluidA', None)),
            **_read_section_fields(window, 'fluid_A'),
        )
        fluid_B = FluidConfig(
            type=_parse_fluid_label(getattr(window, 'combo_fluidB', None)),
            u_mps=_qt_float(getattr(window, 'le_uB', None), fluid_A.u_mps),
            **_read_section_fields(window, 'fluid_B'),
        )

        # ── audit C4 additions ──────────────────────────────────
        # Partial-pipe BC + zone state + feature flags + extrap policy.
        # Defaults preserve legacy behaviour when widgets are missing
        # (test stubs, headless scripts).
        bc_A = _read_partial_bc(window, 'A')
        bc_B = _read_partial_bc(window, 'B')
        zones = _read_zone_input(window)
        flags = _read_feature_flags(window)
        extrap = _read_extrap_policy(window)

        return cls(fluid_A=fluid_A, fluid_B=fluid_B,
                   geometry=geom, solver=solver,
                   bc_A=bc_A, bc_B=bc_B,
                   zones=zones, flags=flags, extrap=extrap)

    # ── JSON ─────────────────────────────────────────────────────────

    @classmethod
    def from_json(cls, path: Union[str, Path]) -> 'ComputeConfig':
        """Load a ComputeConfig from a JSON file.

        Accepts both the canonical schema (mirroring the dataclass
        tree) and the legacy ``configs/shanghai_baseline.json`` shape
        (geometry + domain, fluids missing → defaults). The legacy
        path is the same one that ``configs.load_shanghai_baseline``
        already consumes, so production validate scripts can switch
        with a one-line change.
        """
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return cls.from_dict(data)

    def to_json(self, path: Union[str, Path]) -> None:
        """Write the config as JSON. Unknown / Path-typed fields
        round-trip through ``asdict`` (all-stdlib types)."""
        Path(path).write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding='utf-8',
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ComputeConfig':
        """Build a ComputeConfig from a JSON-shaped dict.

        Supports two layouts:

        1. **Canonical** — keys ``fluid_A``, ``fluid_B``,
           ``geometry``, ``solver``, each mapping to the corresponding
           dataclass shape (``asdict`` round-trip).
        2. **Legacy Shanghai baseline** — ``geometry`` + ``domain``
           dicts; ``domain.L_dom_m`` / ``H_dom_m`` / ``Lz_m`` fold
           into :class:`GeometryConfig`. Fluids fall back to defaults
           because the Shanghai loop overwrites them per case.
        """
        # ── canonical layout ────────────────────────────────────
        if any(k in data for k in ('fluid_A', 'fluid_B', 'solver')):
            fA_d = data.get('fluid_A', {}) or {}
            fB_d = data.get('fluid_B', {}) or {}
            ge_d = data.get('geometry', {}) or {}
            so_d = data.get('solver', {}) or {}
            # audit C4 additions — all optional, default-constructed
            # when absent so old JSON files keep round-tripping.
            bcA_d = data.get('bc_A', {}) or {}
            bcB_d = data.get('bc_B', {}) or {}
            zn_d = data.get('zones', {}) or {}
            fl_d = data.get('flags', {}) or {}
            ex_d = data.get('extrap', {}) or {}
            return cls(
                fluid_A=FluidConfig(**fA_d) if fA_d else FluidConfig(),
                fluid_B=FluidConfig(**fB_d) if fB_d else FluidConfig(),
                geometry=GeometryConfig(**ge_d) if ge_d else GeometryConfig(),
                solver=SolverConfig(**so_d) if so_d else SolverConfig(),
                bc_A=PartialBCConfig(**bcA_d) if bcA_d else PartialBCConfig(),
                bc_B=PartialBCConfig(**bcB_d) if bcB_d else PartialBCConfig(),
                zones=ZoneInputConfig(**zn_d) if zn_d else ZoneInputConfig(),
                flags=FeatureFlags(**fl_d) if fl_d else FeatureFlags(),
                extrap=ExtrapPolicy(**ex_d) if ex_d else ExtrapPolicy(),
            )

        # ── legacy shanghai_baseline.json layout ────────────────
        # Keys: _meta / geometry / domain / _excluded
        geom_raw = data.get('geometry', {}) or {}
        domain_raw = data.get('domain', {}) or {}
        geom = GeometryConfig(
            tpms=geom_raw.get('tpms', 'Gyroid'),
            L_cell_mm=float(geom_raw.get('L_cell_mm', 7.0)),
            t_wall_mm=float(geom_raw.get('t_wall_mm', 0.6)),
            k_s_W_mK=float(geom_raw.get('k_s_W_mK', 16.0)),
            L_dom_m=float(domain_raw.get('L_dom_m', 0.182)),
            H_dom_m=float(domain_raw.get('H_dom_m', 0.042)),
            Lz_m=(float(domain_raw['Lz_m'])
                  if 'Lz_m' in domain_raw else None),
        )
        return cls(geometry=geom)


__all__ = [
    'FluidType', 'TPMSType', 'RoughMode', 'ZoneAxis',
    'FluidConfig', 'GeometryConfig', 'SolverConfig',
    'PartialBCConfig', 'ZoneInputConfig',
    'ExtrapPolicy', 'FeatureFlags',
    'ComputeConfig',
]
