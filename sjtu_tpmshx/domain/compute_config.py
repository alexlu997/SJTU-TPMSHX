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

- ``ui.window_config.config_from_window(window)`` — read ``window.le_*`` /
  ``window.combo_*`` once at the UI boundary; downstream callers no
  longer touch ``window``. (Moved out of this module in the contracts-layer
  split, 2026-07-02 — this module is now import-clean of any UI concern.)
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
    # (A%/B%) convert to δ in run scripts via runs/diagnostics/asym_target_scan.
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
      returns ``None``, which ``_run_3d_stack`` reads as "no B fluid —
      single-fluid A-alone run" (it skips the B SIMPLE build). A
      partially-degenerate BC returns the raw partial dict (no full-face
      fallback). 3D side B only.

      NOTE: the ComputeConfig→3D boundary (``stages_3d._parse_inputs_3d_cfg``)
      rebuilds a full-face B from a None here, because via ComputeConfig
      fluid_B is always a configured 2nd fluid (a None there is just the
      ``PartialBCConfig`` default widths, meaning full-face cross-flow). The
      genuine single-fluid path reaches ``_run_3d_stack`` with an explicit
      ``fluid_B_cfg=None`` and bypasses that boundary.
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

    Constructed at the UI boundary via ``ui.window_config.config_from_window``
    or at a
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
    # Compressible validity-envelope behaviour (robustness, 2026-06-25):
    # 'raise' (default) -> ChokedFlowError on a choked/supersonic solve;
    # 'warn' -> run but flag envelope_valid=False (useful for batch sweeps that
    # must not abort on one choked operating point); 'off' -> legacy silent.
    envelope_mode: str = 'raise'

    # ── derived ──────────────────────────────────────────────────────

    @property
    def is_3d(self) -> bool:
        """True when the solver should run on the full 3D grid."""
        return int(self.solver.Nz) >= 2

    # ── adapters ─────────────────────────────────────────────────────


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
                envelope_mode=data.get('envelope_mode', 'raise'),
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
