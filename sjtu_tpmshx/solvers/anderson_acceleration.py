"""Anderson acceleration for SIMPLE outer Picard iteration.

Treats the SIMPLE step as a fixed-point map G: x → x' where
``x = stack(u, v, w, P)``. Anderson Type-II uses a window of m past residuals
to extrapolate a better next state via a least-squares mixing of recent steps.

Mass conservation note
----------------------
Anderson on raw (u,v,w,P) does NOT inherently preserve ∇·(ρu)=0. The caller
MUST run one extra pressure correction (`_solve_pp_amg` + `_correct_jit_3d`)
after every Anderson step so the projected velocity is divergence-free again.
The Anderson step is therefore a candidate; the projection makes it admissible.

Safety gates
------------
- Apply only every K outer iterations (default 3) — pure Picard between to
  let SIMPLE re-establish self-consistency.
- Skip if ΔR is rank-deficient (cond > 1e10).
- Roll back to Picard if the Anderson candidate increases the residual norm.
"""
from __future__ import annotations
import numpy as np
from collections import deque
from typing import Tuple


class AndersonSIMPLE:
    """Type-II Anderson acceleration for SIMPLE outer loop.

    Parameters
    ----------
    m : int
        History depth. m=5 is a robust default for SIMPLE.
    K : int
        Apply Anderson every K outer iterations; pure Picard between.
    beta : float
        Damping factor. 1.0 = full Anderson; <1.0 mixes with Picard. Default
        1.0 — SIMPLE under-relaxation already provides damping.
    cond_max : float
        Skip Anderson if cond(ΔR) exceeds this. Default 1e10.
    """

    def __init__(self, m: int = 5, K: int = 3, beta: float = 1.0,
                 cond_max: float = 1e10):
        self.m = int(m)
        self.K = int(K)
        self.beta = float(beta)
        self.cond_max = float(cond_max)
        # ring buffers of past states x_k and residuals r_k = G(x_k) - x_k
        self._X: deque = deque(maxlen=self.m + 1)
        self._R: deque = deque(maxlen=self.m + 1)
        self.applied_count: int = 0
        self.skipped_count: int = 0
        self.rolled_back_count: int = 0

    def reset(self) -> None:
        self._X.clear()
        self._R.clear()
        self.applied_count = 0
        self.skipped_count = 0
        self.rolled_back_count = 0

    def push(self, x: np.ndarray, gx: np.ndarray) -> None:
        """Record an iterate ``x`` and its image ``gx = G(x)``."""
        self._X.append(np.ascontiguousarray(x, dtype=np.float64))
        self._R.append(np.ascontiguousarray(gx - x, dtype=np.float64))

    def candidate(self, gx_picard: np.ndarray) -> Tuple[np.ndarray, bool]:
        """Return Anderson-accelerated candidate or pass-through Picard.

        Parameters
        ----------
        gx_picard : np.ndarray
            The pure Picard step output G(x_k) at the current iteration.

        Returns
        -------
        x_new : np.ndarray
            Either the Anderson-mixed candidate or ``gx_picard`` unchanged.
        applied : bool
            True if Anderson mixing was applied.
        """
        if len(self._X) < 2:
            return gx_picard, False

        X = np.stack(list(self._X), axis=1)        # (n, k+1)
        R = np.stack(list(self._R), axis=1)        # (n, k+1)
        dX = np.diff(X, axis=1)                    # (n, k)
        dR = np.diff(R, axis=1)                    # (n, k)

        # cond check via ratio of singular values; cheap for m≤5
        try:
            s = np.linalg.svd(dR, compute_uv=False)
            if s.size == 0 or s[0] == 0.0 or (s[0] / max(s[-1], 1e-30)) > self.cond_max:
                self.skipped_count += 1
                return gx_picard, False
        except np.linalg.LinAlgError:
            self.skipped_count += 1
            return gx_picard, False

        r_curr = R[:, -1]
        try:
            gamma, *_ = np.linalg.lstsq(dR, r_curr, rcond=None)
        except np.linalg.LinAlgError:
            self.skipped_count += 1
            return gx_picard, False

        # x_anderson = G(x_k) - (dX + dR) @ gamma  (Type-II)
        x_anderson = gx_picard - (dX + dR) @ gamma
        if self.beta < 1.0:
            x_anderson = self.beta * x_anderson + (1.0 - self.beta) * gx_picard

        if not np.all(np.isfinite(x_anderson)):
            self.skipped_count += 1
            return gx_picard, False

        self.applied_count += 1
        return x_anderson, True

    def maybe_rollback(self, x_anderson: np.ndarray, gx_picard: np.ndarray,
                        res_anderson: float, res_picard: float) -> np.ndarray:
        """Roll back to Picard if Anderson candidate increased residual."""
        if not np.isfinite(res_anderson) or res_anderson > res_picard:
            self.rolled_back_count += 1
            return gx_picard
        return x_anderson


def stack_state(u: np.ndarray, v: np.ndarray, w: np.ndarray,
                 P: np.ndarray) -> np.ndarray:
    """Flatten (u,v,w,P) into a single 1-D float64 vector.

    Staggered grid friendly: each component may have its own shape
    (e.g. u is (Nx+1, Ny, Nz), v is (Nx, Ny+1, Nz), w is (Nx, Ny, Nz+1),
    P is (Nx, Ny, Nz)). Shapes are recovered by :func:`unstack_state`
    using the original arrays as templates.
    """
    return np.concatenate([u.ravel(), v.ravel(), w.ravel(), P.ravel()])


def unstack_state(x: np.ndarray, u_ref: np.ndarray, v_ref: np.ndarray,
                   w_ref: np.ndarray, P_ref: np.ndarray
                   ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Inverse of :func:`stack_state` using reference arrays for shapes."""
    nu = u_ref.size
    nv = v_ref.size
    nw = w_ref.size
    nP = P_ref.size
    u = x[0:nu].reshape(u_ref.shape).copy()
    v = x[nu:nu + nv].reshape(v_ref.shape).copy()
    w = x[nu + nv:nu + nv + nw].reshape(w_ref.shape).copy()
    P = x[nu + nv + nw:nu + nv + nw + nP].reshape(P_ref.shape).copy()
    return u, v, w, P
