"""core/evaluators.py — neutral-layer 3D design evaluator (M4 fix).

Re-exports ``evaluate_3d`` and ``_build_3d_arrays`` from
``validation/verify_pareto_3d``. Both ``optimization/evaluator_3d`` (BO
worker) and ``validation/verify_pareto_3d`` (CLI verification) import
from here so the import direction is no longer ``optimization → validation``.

⚠ DEEPER REFACTOR PENDING: the physical definitions still live in
``validation/verify_pareto_3d.py``. A future cleanup should physically
move them here, leaving ``verify_pareto_3d`` as the CLI wrapper only.
Tracked as follow-up to 2026-05-28 audit Item M4 (deeper move).

Public API
----------
``evaluate_3d(x, cfg, **kwargs) -> dict``
    Run the 3D LTNE evaluator on a single decision vector. Returns a
    dict with keys ``Q_3D_W``, ``dP_A_Pa``, ``dP_B_Pa``, ``dP_total_Pa``,
    ``mass_kg``, plus ``invalid`` / ``invalid_reason`` on infeasible
    (P_out² ≤ 0) inputs.
"""
from __future__ import annotations

# Thin re-export — physical definitions live in validation/verify_pareto_3d.py
# (legacy location). See module docstring for follow-up plan.
from validation.verify_pareto_3d import (
    evaluate_3d,
    _build_3d_arrays,
)

__all__ = ["evaluate_3d", "_build_3d_arrays"]
