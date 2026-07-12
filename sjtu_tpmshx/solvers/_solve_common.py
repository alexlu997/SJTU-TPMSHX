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


class F2Monitor:
    """Convergence monitor for the 3D SIMPLE **F2** path (ledger C6/C7).

    Replaces `LowReExit` as the DECIDER when ``convergence_mode == 'f2'``.
    `LowReExit` is left untouched — it is shared with 2D and is under a
    bit-identity contract; F2 needs different semantics, not a patched default.

    THE DIFFERENCE THAT MATTERS. `LowReExit` TERMINATES the solve the moment the
    velocity field goes static (`simple_solver_3d.py`: ``return (_reason ==
    'velocity'), it``). Measured (ledger C7): that happens at a momentum residual
    of 1.8e-3 .. 1.5e-2, while the momentum residual is still falling fast. So
    velocity-static is NOT convergence — and simply flipping its verdict to
    ``converged=False`` would only turn a premature SUCCESS into a premature
    FAILURE: the solve would still stop at ~90 iterations and never reach the
    real gate at ~200-300. Here, therefore:

        velocity going static TRIGGERS AN IMMEDIATE RESIDUAL CHECK.
        It does NOT terminate. If the gates fail, the loop keeps iterating.

    THREE INDEPENDENT GATES, all required, for ``n_confirm`` consecutive checks
    (a single lucky iterate is not convergence):

        R_mom          — momentum residual (the binding one; see _mom_res_jit_3d)
        R_mass_local   — continuity over the cells the pp equation SOLVES,
                         against the CURRENT rho (not the stale one it already
                         zeroed itself against)
        R_mass_global  — |mdot_out - mdot_in| / mdot_in on the boundary faces

    Local and global are both needed: the local metric says nothing about the
    Dirichlet outlet row (excluded by construction), and the global metric is a
    single scalar that per-cell errors can cancel inside. Neither alone is a
    mass certificate.

    COST. The momentum residual costs a full coefficient re-assembly, so it is
    evaluated every ``mom_every`` iterations — plus immediately whenever the
    velocity field goes static, and every iteration once a confirm-streak has
    started. It is read-only, so this schedule cannot change the numeric
    trajectory; the worst case is exiting up to ``mom_every - 1`` iterations late.
    """

    def __init__(self, solver, vels, min_iter: int):
        g = lambda k, d: getattr(solver, k, d)  # noqa: E731
        self.mom_tol = float(g('mom_tol', 1e-4))
        self.mass_local_tol = float(g('mass_local_tol', 1e-6))
        self.mass_global_tol = float(g('mass_global_tol', 1e-6))
        self.n_confirm = int(g('f2_n_confirm', 2))
        self.mom_every = max(1, int(g('f2_mom_every', 5)))
        self.vtol = float(g('lowre_vel_tol', 1e-4))
        self.stall_window = int(g('f2_stall_window', 60))
        self.stall_ratio = float(g('f2_stall_ratio', 1e-3))
        self.min_iter = int(min_iter)
        self._prev = [v.copy() for v in vels]
        self._streak = 0
        self._mom_at_window_start = None
        self._window_start_it = 0
        self.last_vd = float('inf')

    def velocity_delta(self, vels) -> float:
        """max|Δφ| / scale since the last call. ALWAYS refreshes the snapshot —
        unlike LowReExit, which only refreshes when it is NOT exiting (fine when
        the reason terminates; a stale-snapshot bug the moment it does not)."""
        deltas = [np.max(np.abs(v - p)) for v, p in zip(vels, self._prev)]
        scale = max(max(np.max(np.abs(v)) for v in vels), 1e-30)
        vd = max(deltas) / scale
        for p, v in zip(self._prev, vels):
            p[:] = v
        self.last_vd = vd
        return vd

    def should_eval_momentum(self, it: int, vd: float) -> bool:
        if it < self.min_iter:
            return False
        if self._streak > 0:
            return True                 # confirming — check every iteration
        if vd < self.vtol:
            return True                 # velocity static — check NOW
        return (it % self.mom_every) == 0

    def submit(self, it: int, R_mom: float, R_mass_local: float,
               R_mass_global: float, vd: float):
        """Call ONLY on iterations where R_mom was actually evaluated.

        Returns None (keep iterating) | 'tol' (converged) | 'stall' (give up,
        converged=False).
        """
        if it < self.min_iter:
            return None
        ok = (R_mom < self.mom_tol
              and R_mass_local < self.mass_local_tol
              and R_mass_global < self.mass_global_tol)
        if ok:
            self._streak += 1
            return 'tol' if self._streak >= self.n_confirm else None
        self._streak = 0

        # Plateau stall: the momentum residual stopped improving over a window
        # AND the field is near-static. Unlike the legacy 'stall' (which fired on
        # the outlet-pin plateau of a residual that never moved at all), this one
        # can only fire on a quantity that genuinely converges — so it means what
        # it says: the iteration is stuck short of the gate.
        if (self._mom_at_window_start is None
                or (it - self._window_start_it) >= self.stall_window):
            if (self._mom_at_window_start is not None
                    and vd < 10.0 * self.vtol
                    and R_mom > self._mom_at_window_start
                        * (1.0 - self.stall_ratio)):
                return 'stall'
            self._mom_at_window_start = R_mom
            self._window_start_it = it
        return None
