"""
optimization/evaluator_3d.py — 3D BO-compatible single-design evaluator.

Wraps ``validation.verify_pareto_3d.evaluate_3d`` (which already extrudes a
2D L(x,y), t(x,y) field along z, runs SIMPLE 3D × 2 + LTNE solve_full_domain_3d
with outer ρ(T) coupling) into the same (Q_neg, dP, mass) return contract as
``optimization.evaluator.evaluate_design`` so ``optimizer_qnehvi.run_qnehvi``
can drive it via ``evaluator_fn=evaluate_design_3d``.

Design choices:
  * Q is normalized to W per metre of HX depth (Q_3D / Lz) so the 3D Pareto
    sits in the same axis as the 2D Pareto — direct comparison.
  * ``DEFAULT_CONFIG_3D`` inherits ``optimization.evaluator.DEFAULT_CONFIG``
    plus four 3D-only knobs: ``Nx_3d``, ``Ny_3d``, ``Nz_3d``, ``Lz``,
    ``max_outer_3d``, ``outer_tol_K``, ``alpha_outer``. Solver-tol overrides
    (``max_iter_simple``, ``tol_simple``, ``max_iter_energy``, ``tol_energy``)
    flow through unchanged.
  * Errors caught in BO worker (_eval_worker) — this function raises on
    pathology so the worker tags it with the dp_cap fallback.

Public API::

    DEFAULT_CONFIG_3D : dict
    evaluate_design_3d(x, cfg) -> (Q_neg_per_m, dP_total, mass_per_m)
"""

from __future__ import annotations

import numpy as np

from optimization.evaluator import DEFAULT_CONFIG as _EVAL_DEFAULT_CONFIG
from validation.verify_pareto_3d import evaluate_3d as _evaluate_3d_dict


# ─── Default cfg ────────────────────────────────────────────────────


DEFAULT_CONFIG_3D: dict = {
    **_EVAL_DEFAULT_CONFIG,

    # 3D-only knobs (fast-mode preset — calibrated for ~3-5 min/eval at
    # workstation 12-core; full-mode would be Nx=40 Ny=16 Nz=16 max_outer=3).
    'Nx_3d':         30,
    'Ny_3d':         12,
    'Nz_3d':         6,
    'Lz':            0.042,    # m  (Shanghai HX depth default)
    'max_outer_3d':  2,        # outer ρ(T) iterations; 2 is fast-mode minimum
    'outer_tol_K':   0.5,
    'alpha_outer':   0.6,

    # Override 2D defaults to match 3D fast-mode budget
    'max_iter_simple': 300,
    'tol_simple':      1e-2,
    'max_iter_energy': 1000,
    'tol_energy':      0.5,

    # ⚠ PROVISIONAL air-side roughness correction (2026-05-13/14).
    # Default 'norris_1a' is a literature-anchored ANSATZ derived from the
    # empirical ×1.28 Nu multiplier (which silently encodes 试验记录表
    # Sa=31μm) via the Norris (1971) Reynolds analogy:
    #     1.46 = 1.28 ** (1/0.68)
    # The chain inherits two unverified assumptions (see solvers/roughness.py
    # module docstring for the full derivation). Expected to be replaced
    # once the Sa-exploration track (kept SEPARATE per user 2026-05-14)
    # produces a defensible alternative or a TPMS-fit rough-wall correlation
    # becomes available. Closes Shanghai dP 44.74% → 24.15% (bias −43% →
    # −15%) with Q virtually unchanged (2.91% → 3.61%); Pareto-best over
    # baseline + bhatti_shah_1b. Water side (Yan [6]) embeds AM roughness
    # already and is untouched here.
    'roughness_mode':   'norris_1a',
    'roughness_eps_um': 100.0,        # only used by bhatti_shah_1b
}


# ─── Public API ─────────────────────────────────────────────────────


def evaluate_design_3d(x: np.ndarray,
                       cfg: dict | None = None) -> tuple:
    """Evaluate one 3D design.

    Parameters
    ----------
    x : (D,) array — decision vector (D = decision_dim from cfg control grid).
    cfg : dict — overrides over DEFAULT_CONFIG_3D.

    Returns
    -------
    Q_neg_per_m : float — −Q in W/m of HX depth (BO maximizes ⇒ negate for
        min-form). Normalized by cfg['Lz'] so 3D Pareto comparable to 2D.
    dP_total : float — dP_A + dP_B in Pa.
    mass_per_m : float — solid mass kg per metre of HX depth.
    """
    cfg_full = {**DEFAULT_CONFIG_3D, **(cfg or {})}

    Nx = int(cfg_full['Nx_3d'])
    Ny = int(cfg_full['Ny_3d'])
    Nz = int(cfg_full['Nz_3d'])
    Lz = float(cfg_full['Lz'])

    res = _evaluate_3d_dict(
        np.asarray(x, dtype=np.float64), cfg_full,
        Nx=Nx, Ny=Ny, Nz=Nz, Lz=Lz,
        max_outer=int(cfg_full['max_outer_3d']),
        outer_tol_K=float(cfg_full['outer_tol_K']),
        alpha_outer=float(cfg_full['alpha_outer']),
        max_iter_simple=int(cfg_full['max_iter_simple']),
        tol_simple=float(cfg_full['tol_simple']),
        max_iter_energy=int(cfg_full['max_iter_energy']),
        tol_energy=float(cfg_full['tol_energy']),
        roughness_mode=str(cfg_full.get('roughness_mode', 'norris_1a')),
        roughness_eps_um=float(cfg_full.get('roughness_eps_um', 100.0)),
        verbose=False,
    )

    Q_per_m = float(res['Q_3D_W']) / max(Lz, 1.0e-9)       # W → W/m
    dP_total = float(res['dP_total_Pa'])
    mass_per_m = float(res['mass_kg']) / max(Lz, 1.0e-9)   # kg → kg/m

    return -Q_per_m, dP_total, mass_per_m
