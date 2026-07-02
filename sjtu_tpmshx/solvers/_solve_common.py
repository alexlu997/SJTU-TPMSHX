"""_solve_common.py — shared SIMPLE outer-loop scaffolding (2D + 3D).

openspec arch-b-c-e batch C. Single source for the low-Re / plateau
early-exit criteria that used to live as two hand-synchronised copies in
``simple_solver.py`` and ``simple_solver_3d.py`` — exactly the dual-
maintenance surface that let the 3D fix miss 2D for months (R1,
solver-efficiency-r1-r4: 2D cross-flow solves burned 10000 iters).

BIT-IDENTITY CONTRACT: this is plain Python (no numba/fastmath), and every
float operation reproduces the retired inline blocks in their original
order — max over the per-field deltas, scale = max(per-field maxima, 1e-30),
vd = max(deltas)/scale. Golden 2D + 3D bit-identical is the merge gate;
re-baselining to absorb a drift here is NOT allowed.
"""
from __future__ import annotations

import numpy as np


class LowReExit:
    """Velocity-stability-gated early exit for the SIMPLE outer loop.

    Two tests, both gated on the field being (near-)static so a moving
    field can never exit early:

    (B) velocity-delta — ``max|Δv|/scale < vtol`` → the field has stopped
        moving → converged (the absolute mass residual is NOT scale-
        invariant; cross-flow / low-speed sides plateau above an air-tuned
        tol with a settled field).
    (A) plateau-stall — the residual improved by less than ``stall_ratio``
        over a ``stall_window`` AND the field is near-static (10× the
        velocity tol, the fallback for fields that creep but never meet B).

    Parameters are read from the solver via ``getattr`` with the shared
    defaults (identical in 2D and 3D): ``lowre_early_exit=True``,
    ``lowre_vel_tol=1e-4``, ``lowre_stall_window=30``,
    ``lowre_stall_ratio=1e-3``. ``min_iter`` keeps each solver's historical
    floor (2D: 20, 3D: 10).

    Usage per outer iteration (velocity fields as a tuple, (u, v) in 2D,
    (u, v, w) in 3D)::

        exit_ = LowReExit(self, (self.u, self.v), min_iter=20)
        ...
        reason = exit_.check((self.u, self.v), res, it)   # None | 'velocity' | 'stall'

    ``check`` also refreshes the previous-iterate snapshots (call it exactly
    once per iteration, after the residual is known). The caller owns the
    closeout on exit (2D: ``_enforce_mass_conservation``).
    """

    def __init__(self, solver, vels, min_iter: int):
        self.enabled = bool(getattr(solver, 'lowre_early_exit', True))
        self.vtol = float(getattr(solver, 'lowre_vel_tol', 1e-4))
        self.stall_window = int(getattr(solver, 'lowre_stall_window', 30))
        self.stall_ratio = float(getattr(solver, 'lowre_stall_ratio', 1e-3))
        self.min_iter = int(min_iter)
        self._prev = [v.copy() for v in vels] if self.enabled else None
        self._res_at_window_start = None
        self._window_start_it = 0

    def check(self, vels, res: float, it: int):
        """Return ``None`` (keep iterating), ``'velocity'`` or ``'stall'``."""
        if not self.enabled:
            return None
        reason = None
        if it >= self.min_iter:
            deltas = [np.max(np.abs(v - p)) for v, p in zip(vels, self._prev)]
            scale = max(max(np.max(np.abs(v)) for v in vels), 1e-30)
            vd = max(deltas) / scale
            if vd < self.vtol:
                reason = 'velocity'
            elif self._res_at_window_start is None or \
                    (it - self._window_start_it) >= self.stall_window:
                if (self._res_at_window_start is not None
                        and vd < 10.0 * self.vtol
                        and res > self._res_at_window_start
                            * (1.0 - self.stall_ratio)):
                    reason = 'stall'
                else:
                    self._res_at_window_start = res
                    self._window_start_it = it
        if reason is None:
            for p, v in zip(self._prev, vels):
                p[:] = v
        return reason
