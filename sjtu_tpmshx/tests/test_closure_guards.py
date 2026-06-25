"""Closure-model robustness guards (Stage 2, 2026-06-25).

Audit (Agent 4) found several closures that silently return physically
meaningless values outside their calibration window. These guards make the
out-of-window behaviour explicit (clear error for impossible inputs, a loud
one-shot warning for extrapolation) without erroring on valid inputs.
"""
import sys
import warnings as W
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import solvers.tpms_calc as tpms_calc
from solvers.tpms_calc import geometry, compute, water_density
import solvers.nu_correlations as nu_correlations
from solvers.nu_correlations import nu_water_topo
from df_surrogate.predict import predict_dP_compressible


# ── geometry degeneracy floor ──────────────────────────────────────────────
def test_geometry_near_degenerate_raises_instead_of_zero_eps():
    # 2t just below L passes the 2t>=L guard but yields eps=0 / D_h=0 silently.
    with pytest.raises(ValueError):
        geometry('Gyroid', 4.0, 1.99, 16.0)


def test_geometry_valid_still_works():
    g = geometry('Gyroid', 7.0, 0.5, 16.0)
    assert g['epsilon'] > 0.0 and g['D_h'] > 0.0


# ── water two-phase warning above 1-atm boiling ────────────────────────────
def test_water_density_warns_two_phase_above_boiling():
    tpms_calc._WATER_TWO_PHASE_WARNED.clear()
    with W.catch_warnings(record=True) as rec:
        W.simplefilter('always')
        water_density(400.0)               # 127 C, two-phase at 1 atm
    msgs = [str(w.message).lower() for w in rec]
    assert any('two-phase' in m or 'boil' in m or 'saturation' in m
               for m in msgs), msgs


def test_water_density_no_two_phase_warn_in_range():
    tpms_calc._WATER_TWO_PHASE_WARNED.clear()
    with W.catch_warnings(record=True) as rec:
        W.simplefilter('always')
        water_density(330.0)               # 57 C, liquid
    msgs = [str(w.message).lower() for w in rec]
    assert not any('two-phase' in m or 'boil' in m for m in msgs), msgs


# ── nu_water_topo extrapolation warning ────────────────────────────────────
def test_nu_water_topo_warns_outside_range():
    nu_correlations._WATER_NU_WARNED.clear()
    with W.catch_warnings(record=True) as rec:
        W.simplefilter('always')
        nu_water_topo('Gyroid', 80000.0, 4.0)   # Re > 50000
    assert any('water' in str(w.message).lower() for w in rec)


# ── Nu air window unified to [400, 16000] (was [600, 30000] in compute) ─────
def test_compute_nu_window_unified_no_warn_at_re_581():
    compute.cache_clear()
    nu_correlations._EXTRAP_WARNED.clear()
    with W.catch_warnings(record=True) as rec:
        W.simplefilter('always')
        compute('Diamond', 6.0, 0.4, 5.0, 350.0, 101325.0, 16.0)  # Re ~ 581
    msgs = [str(w.message) for w in rec]
    # 581 is inside the single-source window [400, 16000]; the old duplicate
    # [600, 30000] check would have warned.
    assert not any('validated range' in m for m in msgs), msgs


# ── compressible dP infeasibility honesty ──────────────────────────────────
def test_predict_dP_choked_warns_when_rescuing_to_pin():
    import df_surrogate.predict as predmod
    predmod._CHOKE_WARNED.clear()
    with W.catch_warnings(record=True) as rec:
        W.simplefilter('always')
        # Huge G over a long channel -> P_out^2 < 0 -> non-strict P_in rescue.
        dP = predict_dP_compressible(
            'Gyroid', 7.0, 0.5, 0.78, G=200.0, T=800.0, P_in=101325.0,
            mu=3.6e-5, L=0.7, strict=False)
    assert dP == pytest.approx(101325.0)
    assert any('chok' in str(w.message).lower()
               or 'infeasible' in str(w.message).lower() for w in rec)
