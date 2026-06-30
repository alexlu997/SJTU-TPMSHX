"""Shared MMS grid-sweep loop (B2 2.5, 2026-06-13 — slim scope).

The three sweep harnesses (mms_phase_a3_h_refine, mms_phase_a4_boundary,
mms_phase_b4_order) each hand-rolled the same timed
``for N in grids: run_mms → extract row`` loop. This module owns that
loop; metric extraction, per-grid printing, order-fit grouping, CSV
formats and hard gates stay per-script — after B1 unified the fit math
in validation/_order_fit, those remaining parts are genuinely divergent
presentation/gating and table-driving them was rejected as
over-parameterisation.
"""
from __future__ import annotations

import time
from typing import Callable, Optional, Sequence


def run_grid_sequence(grids: Sequence[int],
                      run_case: Callable[[int], dict],
                      row_builder: Callable[[int, dict, float], dict],
                      *, on_grid: Optional[Callable] = None) -> list[dict]:
    """Timed h-refinement sweep.

    run_case(N)              → solver result dict (one grid level)
    row_builder(N, r, dt)    → record dict appended to the returned rows
    on_grid(N, r, row, dt)   → optional per-grid progress print
    """
    rows = []
    for g in grids:
        t0 = time.time()
        r = run_case(g)
        dt = time.time() - t0
        row = row_builder(g, r, dt)
        rows.append(row)
        if on_grid is not None:
            on_grid(g, r, row, dt)
    return rows
