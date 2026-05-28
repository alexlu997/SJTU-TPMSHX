"""validation/_metrics.py — shared error metrics for Shanghai + MMS scripts.

Per audit 2026-05-28 L5: previously inline-written in 3 production
validate_shanghai_* scripts with identical formulas. Extracted here so a
future change to the metric definition only needs to touch one place.

API
---
``rmsre_from_pct(err_pct)``    — single number from pre-computed % errors
``err_stats_pct(err_pct)``     — (rmsre, mean_bias, max_abs) triple

Both treat input as already in the desired unit (typically %); they don't
multiply by 100 themselves. Inputs should be ``(pred - exp) / exp * 100``
or equivalent.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np


def rmsre_from_pct(err_pct) -> float:
    """RMSRE from a pre-computed array of percent errors.

    Formula: ``sqrt(mean(err_pct**2))``. Output is in the same unit as input.
    """
    arr = np.asarray(err_pct, dtype=np.float64)
    return float(np.sqrt(np.mean(arr ** 2)))


def err_stats_pct(err_pct) -> Tuple[float, float, float]:
    """Return ``(rmsre, mean_bias, max_abs)`` from a percent-error array.

    All three are in the same unit as the input. Used by
    ``validate_shanghai_lumped_dual_nu.py`` for its summary table.
    """
    arr = np.asarray(err_pct, dtype=np.float64)
    return (
        float(np.sqrt(np.mean(arr ** 2))),
        float(np.mean(arr)),
        float(np.max(np.abs(arr))),
    )


__all__ = ["rmsre_from_pct", "err_stats_pct"]
