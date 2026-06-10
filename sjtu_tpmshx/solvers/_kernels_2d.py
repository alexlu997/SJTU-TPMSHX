"""Shared Numba kernel helpers for the 2D solvers.

minmod() is the MINMOD-limited slope used by every SOU deferred-correction
kernel (_sou_corr_* in simple_solver.py and ltne_energy.py). It was previously
inlined ~24 times verbatim; extracting it with ``inline='always'`` keeps the
compiled output byte-identical while collapsing the duplication.
"""
from numba import njit


@njit(inline='always', cache=True)
def minmod(gu, gd):
    """MINMOD limiter: signed min(|gu|,|gd|) when gu,gd share a sign, else 0.

    Byte-identical to the block it replaces::

        phi = 0.0
        if gu * gd > 0:
            phi = min(abs(gu), abs(gd))
            if gu < 0: phi = -phi
    """
    if gu * gd > 0:
        phi = min(abs(gu), abs(gd))
        if gu < 0:
            phi = -phi
        return phi
    return 0.0
