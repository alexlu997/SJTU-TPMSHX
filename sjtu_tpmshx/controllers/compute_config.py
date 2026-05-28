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

    # ── derived ──────────────────────────────────────────────────────

    @property
    def is_3d(self) -> bool:
        """True when the solver should run on the full 3D grid."""
        return int(self.solver.Nz) >= 2

    # ── adapters ─────────────────────────────────────────────────────

    @classmethod
    def from_qt_window(cls, window) -> 'ComputeConfig':
        """Build a ``ComputeConfig`` from the main UI window.

        Reads ``window.le_*`` and ``window.combo_*`` exactly once.
        Missing optional widgets fall back to the dataclass defaults.

        This is the *only* place in the codebase allowed to read
        ``QLineEdit.text()`` / ``QComboBox.currentText()`` and feed it
        into the solver layer.
        """
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

        return cls(fluid_A=fluid_A, fluid_B=fluid_B,
                   geometry=geom, solver=solver)

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
            return cls(
                fluid_A=FluidConfig(**fA_d) if fA_d else FluidConfig(),
                fluid_B=FluidConfig(**fB_d) if fB_d else FluidConfig(),
                geometry=GeometryConfig(**ge_d) if ge_d else GeometryConfig(),
                solver=SolverConfig(**so_d) if so_d else SolverConfig(),
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
    'FluidType', 'TPMSType', 'RoughMode',
    'FluidConfig', 'GeometryConfig', 'SolverConfig',
    'ComputeConfig',
]
