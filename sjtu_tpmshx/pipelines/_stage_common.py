"""Shared non-kernel scaffolding for the 2D/3D pipeline stages.

Extracted (openspec pipeline-stage-dedup, 2026-07-03) from copy-pasted blocks
in ``stages_2d._parse_inputs`` / ``stages_3d._parse_inputs_3d_cfg`` and the
two ``ComputeResult`` assembly sites. Pure input validation / result plumbing
— nothing here touches solver numerics, so the golden 2D/3D gates must stay
bit-identical across this extraction.

The numba kernels themselves stay per-dimension by design (unification
rejected — the stencils genuinely differ); only Qt-free, kernel-free glue
belongs in this module.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from domain.compute_config import ComputeConfig

# Defensive unit firewall (GUI labels L/H in METERS but L_cell/t in MM;
# mistyping the mm value into the metre field silently spawns a multi-metre
# domain and an hour-long hang instead of an error).
_DOMAIN_MAX_M = 10.0


def validate_domain_dims(pairs: Iterable[tuple[str, float]]) -> None:
    """Raise ValueError for any (name, value-in-m) pair above _DOMAIN_MAX_M.

    ``pairs`` is an iterable of ``(name, val)`` — 2D passes L/H, 3D adds Lz.
    """
    for name, val in pairs:
        if val > _DOMAIN_MAX_M:
            raise ValueError(
                f"Domain dimension {name!r}={val} m exceeds "
                f"{_DOMAIN_MAX_M} m. Likely unit slip — GUI expects "
                f"meters here, while L_cell and t use millimeters. "
                f"Re-check input.")


def surrogate_extrap_reasons(compute_cfg: ComputeConfig,
                             allow_extrap: bool) -> list[str]:
    """Both-side surrogate training-domain check → list of extrap reasons.

    ImportError (surrogate_domain unavailable) → skip, return []. A
    ValueError from the check is a real domain violation and must propagate,
    so it is intentionally not caught. (The pre-dedup 2D copy swallowed
    AttributeError instead — a broken guard silently disabled extrapolation
    warnings; that hush is gone.)
    """
    try:
        from df_surrogate.surrogate_domain import check_surrogate_domain_at_point
    except ImportError:
        return []
    geo = compute_cfg.geometry
    reasons = []
    for side, fl in (('A', compute_cfg.fluid_A), ('B', compute_cfg.fluid_B)):
        reasons += check_surrogate_domain_at_point(
            geo.tpms, geo.L_cell_mm, geo.t_wall_mm, geo.k_s_W_mK,
            fl.u_mps, fl.T_in_K, fl.P_in_Pa, side=side,
            allow_extrap=allow_extrap, fluid=fl.type) or []
    return reasons


def safe_float(v: Any) -> float:
    """float(v) with None / non-numeric → nan (headline-scalar guard).

    ``raw.get(key, default)`` only returns ``default`` when ``key`` is
    absent — explicit ``None`` values (e.g. when fluid B is frozen) would
    crash ``float(None)``.
    """
    try:
        return float(v) if v is not None else float('nan')
    except (TypeError, ValueError):
        return float('nan')


def geometry_props(compute_cfg: ComputeConfig) -> tuple[float, float, float]:
    """(epsilon, D_h_m, A_0_m2) triple for the ComputeResult ``props`` slot,
    derived from cfg geometry via the closed-form tpms_calc.geometry."""
    from solvers.tpms_calc import geometry as _tpms_geom
    g = _tpms_geom(compute_cfg.geometry.tpms,
                   compute_cfg.geometry.L_cell_mm,
                   compute_cfg.geometry.t_wall_mm,
                   compute_cfg.geometry.k_s_W_mK)
    return g['epsilon'], g['D_h'], g['A_0']
