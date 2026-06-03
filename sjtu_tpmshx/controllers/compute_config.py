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
# the human-friendly names that the legacy ``runs.run_calculation._parse``
# helper surfaced in its ``ValueError`` payload.
_REQUIRED_2D = [
    ('le_L', "Domain Length (L)"),
    ('le_H', "Domain Height (H)"),
    ('le_Nx', "Grid Nx"),
    ('le_Ny', "Grid Ny"),
    ('le_uA', "Velocity A (u_A)"),
    ('le_uB', "Velocity B (u_B)"),
    ('le_TinA', "Inlet Temp A (T_inA)"),
    ('le_TinB', "Inlet Temp B (T_inB)"),
    ('le_Lcell', "TPMS L_cell"),
    ('le_t', "TPMS t"),
    ('le_ks', "TPMS k_s"),
]
_REQUIRED_3D_EXTRA = [
    ('le_Lz', "Width Lz"),
    ('le_Nz', "Grid Nz"),
]


def _validate_required_widgets(window, *, is_3d: bool) -> None:
    """Raise ``ValueError`` listing every blank / non-numeric required
    widget — preserves the legacy behaviour of
    ``runs.run_calculation._parse``.
    """
    required = list(_REQUIRED_2D)
    if is_3d:
        required = required + _REQUIRED_3D_EXTRA
    bad = []
    for attr, label in required:
        widget = getattr(window, attr, None)
        if widget is None:
            bad.append(label)
            continue
        txt = _qt_text(widget).strip()
        if not txt:
            bad.append(label)
            continue
        # int widgets get a tighter check
        if attr in ('le_Nx', 'le_Ny', 'le_Nz'):
            try:
                int(txt)
            except ValueError:
                bad.append(label)
        else:
            try:
                float(txt)
            except ValueError:
                bad.append(label)
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
    missing, matching the legacy ``runs.run_calculation._parse_inputs``
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
            try:
                bc.in_z_ctr = float(le_in_z_ctr.text())
                bc.in_z_w = float(getattr(window, f'{le_prefix}_in_z_w').text())
                bc.out_z_ctr = float(
                    getattr(window, f'{le_prefix}_out_z_ctr').text())
                bc.out_z_w = float(
                    getattr(window, f'{le_prefix}_out_z_w').text())
            except (AttributeError, ValueError):
                # Leave z-fields as None — solver treats as full face.
                pass
    return bc


def _read_zone_input(window) -> 'ZoneInputConfig':
    """Snapshot zone / sigmoid-field control state.

    Reads ``chk_zones``, ``combo_zone_axis``, ``_zone_grid``, and the
    ``_pareto_*`` attributes. When ``chk_zones`` is checked, also
    pre-resolves the ``ZoneConfig`` instance via
    ``solvers.zone_editor.build_zone_config(window)`` so the downstream
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
            from solvers.zone_editor import build_zone_config as _bzc
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
    unit = getattr(window, '_temp_unit', 'K')
    if unit not in ('K', 'C'):
        unit = 'K'
    return FeatureFlags(wall_refine_3d=wall, temp_unit=unit)


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
    boundary-layer refinement). ``temp_unit`` mirrors ``window._temp_unit``
    purely for round-tripping; ComputeConfig fields are always Kelvin so
    the solver itself never needs this flag.

    Audit C4 (L-a-2).
    """
    wall_refine_3d: bool = False
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
            inside ``runs.run_calculation._parse_inputs``. Defaults to
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
        # ── geometry ────────────────────────────────────────────
        tpms = _qt_text(getattr(window, 'combo_tpms', None)) or 'Gyroid'
        if tpms not in ('Diamond', 'Gyroid'):
            tpms = 'Gyroid'
        geom = GeometryConfig(
            tpms=tpms,
            L_cell_mm=_qt_float(getattr(window, 'le_Lcell', None), 7.0),
            t_wall_mm=_qt_float(getattr(window, 'le_t', None), 0.6),
            k_s_W_mK=_qt_float(getattr(window, 'le_ks', None), 16.0),
            L_dom_m=_qt_float(getattr(window, 'le_L', None), 0.182),
            H_dom_m=_qt_float(getattr(window, 'le_H', None), 0.042),
            Lz_m=(_qt_float(getattr(window, 'le_Lz', None), 0.042)
                  if getattr(window, 'le_Lz', None) is not None else None),
        )

        # ── solver ──────────────────────────────────────────────
        Nz = _qt_int(getattr(window, 'le_Nz', None), 1)
        # Optional Ts init: empty / None → solver default seed
        T_s_init: Optional[float] = None
        le_ts = getattr(window, 'le_TsInit', None)
        if le_ts is not None and _qt_text(le_ts).strip():
            T_s_init = _temp_in_K(window, le_ts, default_K=0.0) or None
        solver = SolverConfig(
            Nx=_qt_int(getattr(window, 'le_Nx', None), 30),
            Ny=_qt_int(getattr(window, 'le_Ny', None), 60),
            Nz=Nz,
            T_s_init_K=T_s_init,
            # remaining knobs keep dataclass defaults; UI does not surface
            # them yet (audit deferred to a later phase)
        )

        # ── fluids ──────────────────────────────────────────────
        fluid_A = FluidConfig(
            type=_parse_fluid_label(getattr(window, 'combo_fluidA', None)),
            u_mps=_qt_float(getattr(window, 'le_uA', None), 5.0),
            T_in_K=_temp_in_K(window, getattr(window, 'le_TinA', None),
                              default_K=300.0),
            P_in_Pa=_qt_float(getattr(window, 'le_PinA', None), 101325.0),
        )
        fluid_B = FluidConfig(
            type=_parse_fluid_label(getattr(window, 'combo_fluidB', None)),
            u_mps=_qt_float(getattr(window, 'le_uB', None), fluid_A.u_mps),
            T_in_K=_temp_in_K(window, getattr(window, 'le_TinB', None),
                              default_K=300.0),
            P_in_Pa=_qt_float(getattr(window, 'le_PinB', None), 101325.0),
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
