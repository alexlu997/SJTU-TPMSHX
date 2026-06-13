"""coupling_skeleton.py — shared outer SIMPLE↔LTNE coupling-loop support.

The 2D (`pipelines.stages_2d._run_solvers`) and 3D
(`pipelines.stages_3d._run_3d_stack`) drivers each run an outer Picard
loop that couples the momentum solve (SIMPLE) to the energy solve (LTNE)
by feeding temperature-dependent properties (ρ, μ, cp, K) back into
SIMPLE until the temperature field stops moving. The two loop *bodies*
are deliberately NOT shared — they differ in solve order (2D SIMPLE→LTNE;
3D LTNE→SIMPLE), in the physics one side carries (χ_B closure,
conservative staggered-face LTNE, frozen-B, per-outer P_ref recompute),
and in Q extraction (2D Richardson vs 3D enthalpy). See the batch-4 design
note for why a full body-step driver was assessed and declined (the
shareable substance is exactly the convergence bookkeeping below; progress
plumbing and Q extraction are dim-specific, not deferrable shared code).

What IS genuinely shared — and all this module owns — is the convergence
bookkeeping both bodies duplicated:

  * the warm-start ``prev = field.copy()`` tracking,
  * the ``max|field − prev|`` convergence delta + the AND-gate break
    decision (2D: dual ΔT_A/ΔT_B + mass-flux-weighted Δρ; 3D: single ΔT).

:class:`OuterConvergence` is a stateful tracker each driver instantiates
once and calls at its own point in its own loop body, so behaviour stays
bit-identical to the prior inline code (same arithmetic, same copy
timing — verified by the 3D golden hash and the 2D golden gate). It is the
one clean shared seam; the per-iteration progress/label writes stay inline
in each driver because their fills differ per dimension (2D's _MAX_COUPLING
denominator + a 0.3 mid-iter sub-fill on a window attribute vs 3D's
_MAX_OUTER-const progress denominator but per-run _max_outer iter ticks via
callbacks) — sharing them would contort the helper for no real dedup.
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

import numpy as np


class OuterConvergence:
    """Warm-start delta tracker + break predicate for the outer coupling loop.

    Owns the per-iteration ``prev = field.copy()`` bookkeeping and the
    ``max|field − prev|`` temperature deltas that both the 2D and 3D loops
    computed inline. The break decision is an AND-gate over (a) every
    tracked temperature field's delta below ``tol_T`` and (b) any
    dim-specific extra criteria the caller passes in (e.g. the 2D
    mass-flux-weighted Δρ), each below its own tolerance.

    Parameters
    ----------
    tol_T : float
        Temperature-delta tolerance [K]. 2D uses 1.0, 3D uses 0.5.
    track : iterable of str
        Names of the temperature fields to track across iterations.
        2D tracks ('Ta', 'Tb'); 3D tracks ('Ta',).

    Notes
    -----
    First call (no ``prev`` yet) reports ``inf`` deltas and never
    converges, matching the legacy ``dT = inf`` first-iteration guard.
    ``check`` copies the current fields into ``prev`` on EVERY call; the
    legacy 2D path skipped the copy on the converged iteration (it broke
    first), but ``prev`` is unused after the loop exits, so the observable
    result is identical.
    """

    def __init__(self, *, tol_T: float, track: Iterable[str] = ('Ta',)) -> None:
        self.tol_T = float(tol_T)
        self.track: Tuple[str, ...] = tuple(track)
        self._prev: Dict[str, Optional[np.ndarray]] = {k: None for k in self.track}

    def check(self, fields: Dict[str, np.ndarray], *,
              extra: Optional[Iterable[float]] = None,
              extra_tol: Optional[float] = None) -> Tuple[bool, Dict[str, float]]:
        """Update warm-start state and decide whether the loop has converged.

        Parameters
        ----------
        fields : dict
            Maps each tracked name to its current array (this iteration's
            temperature field, real-coords, same shape as last call).
        extra : iterable of float, optional
            Dim-specific secondary convergence quantities (e.g. 2D's
            ``(drho_A, drho_B)``). Each must be below ``extra_tol``.
        extra_tol : float, optional
            Tolerance for every ``extra`` value. Required if ``extra`` given.

        Returns
        -------
        (converged, deltas) : (bool, dict)
            ``deltas`` maps each tracked name to ``max|field − prev|``
            (``inf`` on the first call), for the caller's status print.
        """
        first = any(self._prev[k] is None for k in self.track)
        deltas: Dict[str, float] = {}
        for k in self.track:
            prev = self._prev[k]
            if prev is None:
                deltas[k] = float('inf')
            else:
                deltas[k] = float(np.max(np.abs(fields[k] - prev)))

        T_ok = all(deltas[k] < self.tol_T for k in self.track)
        extra_ok = True
        if extra is not None:
            if extra_tol is None:
                raise ValueError("extra_tol required when extra is given")
            extra_ok = all(float(v) < extra_tol for v in extra)
        converged = (not first) and T_ok and extra_ok

        # Warm-start for the next iteration (copy so later in-place writes
        # to `fields` do not alias prev).
        for k in self.track:
            self._prev[k] = fields[k].copy()
        return converged, deltas
