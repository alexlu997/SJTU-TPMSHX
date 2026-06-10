"""Codex #6 — explicit invalid-pressure-state flag (minimal slice, no optimizer).

1D compressible D-F: P_out² = P_in² − 2RT·C·L. When C·L is large enough
that P_out² ≤ 0 the operating point is physically infeasible (choked /
over-driven). The code historically *silently rescued* it (`return P_in`),
hiding infeasibility behind a finite plausible number — dangerous for BO
and high-Re extrapolation.

Contract (Option i):
- `predict_dP(..., strict=False)`  → DEFAULT unchanged (returns P_in on
  infeasible) so the optimizer value-path is untouched.
- `predict_dP(..., strict=True)`   → returns NaN on infeasible so
  validation/eval can detect, exclude and COUNT invalid points.
"""
import math
import numpy as np
import pytest

from df_surrogate.surrogate_v3 import SurrogateV3
from df_surrogate.predict import predict_dP_compressible
from df_surrogate.residual_correction import predict_dP_compressible_corrected


# --- predict_dP_compressible (geometry-routed) infeasible / feasible -----
# Surrogate-routed: K/c_F come from the Gyroid model for L=7,t=0.6. The
# infeasible point pushes G·L huge with low P_in so 2RT·C·L ≫ P_in² for
# ANY physical c_F (margin ~5 orders); feasible point is a normal duty.
_C_GEOM = dict(tpms_type='Gyroid', L_mm=7.0, t_mm=0.6, eps_f=0.368)
_C_INFEASIBLE = dict(**_C_GEOM, G=400.0, T=400.0, P_in=5.0e4,
                     mu=2.0e-5, L=5.0)
_C_FEASIBLE = dict(**_C_GEOM, G=20.0, T=370.0, P_in=3.0e5,
                   mu=2.0e-5, L=0.18)


# Infeasible point: tiny K + big cF/G/L drives 2RT·C·L ≫ P_in².
_INFEASIBLE = dict(K=1e-9, c_F=300.0, G=100.0, T=400.0,
                   P_in=1.0e5, mu=2.0e-5, L=1.0)
# Feasible sanity point (small resistance).
_FEASIBLE = dict(K=1e-7, c_F=50.0, G=5.0, T=400.0,
                 P_in=3.0e5, mu=2.0e-5, L=0.18)


def test_predict_dP_strict_returns_nan_on_infeasible():
    dp = SurrogateV3.predict_dP(strict=True, **_INFEASIBLE)
    assert math.isnan(dp), (
        f"strict=True must return NaN on infeasible (P_out²≤0); got {dp}"
    )


def test_predict_dP_default_returns_P_in_unchanged():
    """Default path MUST stay P_in so the optimizer is not disturbed."""
    dp = SurrogateV3.predict_dP(**_INFEASIBLE)
    assert dp == pytest.approx(_INFEASIBLE["P_in"], rel=1e-9), (
        f"default (strict=False) must keep legacy P_in rescue; got {dp}"
    )


def test_predict_dP_feasible_same_both_modes():
    """Feasible point: strict flag must not change a valid answer."""
    a = SurrogateV3.predict_dP(**_FEASIBLE)
    b = SurrogateV3.predict_dP(strict=True, **_FEASIBLE)
    assert a == pytest.approx(b, rel=1e-12) and np.isfinite(a) and a > 0


# --- predict_dP_compressible: same contract as predict_dP -----------------

def test_compressible_strict_returns_nan_on_infeasible():
    dp = predict_dP_compressible(strict=True, **_C_INFEASIBLE)
    assert math.isnan(dp), (
        f"strict=True must return NaN on infeasible (P_out²≤0); got {dp}"
    )


def test_compressible_default_returns_P_in_unchanged():
    """Default path MUST keep legacy P_in rescue (optimizer untouched)."""
    dp = predict_dP_compressible(**_C_INFEASIBLE)
    assert dp == pytest.approx(_C_INFEASIBLE["P_in"], rel=1e-9), (
        f"default (strict=False) must return legacy P_in; got {dp}"
    )


def test_compressible_feasible_same_both_modes():
    """Feasible point: strict flag must not perturb a valid dP."""
    a = predict_dP_compressible(**_C_FEASIBLE)
    b = predict_dP_compressible(strict=True, **_C_FEASIBLE)
    assert a == pytest.approx(b, rel=1e-12) and np.isfinite(a) and a > 0


# --- residual_correction.predict_dP_compressible_corrected ----------------
# Codex 3rd-pass P2a: the residual-corrected direct API silently rescued
# infeasible (return P_in). Same strict-flag contract as predict_dP_*.

def test_corrected_strict_returns_nan_on_infeasible():
    dp = predict_dP_compressible_corrected(strict=True, **_C_INFEASIBLE)
    assert math.isnan(dp), (
        f"strict=True must return NaN on infeasible (P_out²≤0); got {dp}"
    )


def test_corrected_default_returns_P_in_unchanged():
    """Default path MUST keep legacy P_in rescue (no caller disturbed)."""
    dp = predict_dP_compressible_corrected(**_C_INFEASIBLE)
    assert dp == pytest.approx(_C_INFEASIBLE["P_in"], rel=1e-9), (
        f"default (strict=False) must return legacy P_in; got {dp}"
    )
