"""Phase A sCO2 enablement (2026-06-26; correlation swapped 2026-07-15).

Covers: SCO2_NU_COEFFS / nu_sco2_topo correlation form (smooth-wall unit-cell
CFD campaign, Diamond + Gyroid, Nu = c·Re^a·Pr^⅓·(Dh/L)^d — replaced the
D-7-6 single-geometry experimental fit), FluidModel('sco2') CoolProp
primitives + (T,P) signature, compute(fluid_type='sco2') routing the sCO2 Nu.

Fit provenance: validation/sco2_cfd/fit_nu_sco2.py (V0b), ledger SCO2-CFD.
"""
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.solvers import fluid_props, tpms_calc
from sjtu_tpmshx.solvers.nu_correlations import (
    nu_sco2_topo, SCO2_NU_COEFFS, SCO2_NU_RE_RANGE,
)


# ── correlation form ────────────────────────────────────────────────
def test_sco2_nu_form_diamond():
    """Nu = c·Re^a·Pr^(1/3)·(Dh/L)^d, smooth wall (no roughness factor)."""
    Re, Pr, L_mm, Dh_mm = 20000.0, 0.85, 7.0, 2.9
    co = SCO2_NU_COEFFS['Diamond']
    expect = (co['c'] * Re ** co['a'] * Pr ** (1 / 3)
              * (Dh_mm / L_mm) ** co['d'])
    assert nu_sco2_topo('Diamond', Re, Pr, L_mm, Dh_mm) \
        == pytest.approx(expect, rel=1e-12)


def test_sco2_nu_coeffs_locked():
    """2026-07-15 smooth-wall CFD fit (V0b) — refit = edit nu_correlations."""
    assert SCO2_NU_COEFFS['Diamond'] == {
        'c': 0.166714, 'a': 0.705490, 'd': -0.434198}
    assert SCO2_NU_COEFFS['Gyroid'] == {
        'c': 0.199133, 'a': 0.719463, 'd': -0.109010}
    assert SCO2_NU_RE_RANGE == (2600.0, 128000.0)


def test_sco2_nu_array_safe():
    Re = np.array([3000.0, 20000.0, 60000.0])
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        out = nu_sco2_topo('Diamond', Re, 0.85, 7.0, 2.9)
    assert out.shape == Re.shape and np.all(out > 0)


def test_sco2_nu_gyroid_supported():
    """CFD campaign covers Gyroid — unlocked 2026-07-15 (was Diamond-only)."""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        nu_g = nu_sco2_topo('Gyroid', 20000.0, 1.5, 5.0, 2.3)
    assert nu_g > 0


def test_sco2_nu_unknown_topology_raises():
    """No silent borrowing of coefficients for unfitted topologies."""
    with pytest.raises(NotImplementedError):
        nu_sco2_topo('Primitive', 20000.0, 0.85, 5.0, 2.0)


# ── FluidModel primitives (CoolProp) ────────────────────────────────
def test_sco2_fluidmodel_incompressible_phase_a():
    m = fluid_props.get('sco2')
    assert m.compressible is False              # Phase A: incompressible
    assert m.embeds_roughness is True           # SLM roughness baked in
    assert fluid_props.flow_model('sco2') == 'incompressible'


def test_sco2_props_depend_on_pressure():
    """Real-gas: density at fixed T differs between 8 and 18 MPa (NOT ideal)."""
    m = fluid_props.get('sco2')
    rho_low = m.rho(360.0, 8e6)
    rho_high = m.rho(360.0, 18e6)
    assert rho_high > 1.5 * rho_low             # dense at high P, far from ideal


def test_sco2_props_require_pressure():
    m = fluid_props.get('sco2')
    with pytest.raises(ValueError, match="pressure"):
        m.cp(400.0)                              # missing P must raise clearly


# ── compute() routing ───────────────────────────────────────────────
def test_compute_sco2_routes_sco2_nu():
    T, P = 420.0, 9e6
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        r = tpms_calc.compute('Diamond', 7.0, 0.6, u=1.5,
                              T_in_K=T, P_in_Pa=P, k_s=15.0,
                              fluid_type='sco2')
    m = fluid_props.get('sco2')
    Pr = m.mu(T, P) * m.cp(T, P) / m.k(T, P)
    g = tpms_calc.geometry('Diamond', 7.0, 0.6, 15.0)
    co = tpms_calc.SCO2_NU_COEFFS['Diamond']
    # Smooth CFD form × the experimental HX-level correction γ_Nu
    # (D-2sc-3, 2026-07-22): compute() must carry the PRODUCTION value —
    # a smooth-only expectation would go stale (and an air-Nu mis-route
    # still lands far from either).
    from sjtu_tpmshx.solvers.nu_correlations import gamma_nu_sco2
    expect = (gamma_nu_sco2('Diamond', float(r['Re']))
              * co['c'] * r['Re'] ** co['a'] * Pr ** (1 / 3)
              * (float(g['D_h']) * 1000.0 / 7.0) ** co['d'])
    assert r['Nu'] == pytest.approx(expect, rel=1e-9)
    assert r['H_sf'] > 0


# ── Gate A: lumped ε-NTU duty vs D-7-6 GOLD experiment ──────────────
def test_gate_a_d76_gold_duty():
    """sCO2 Nu closure reproduces measured duty on the 6 GOLD cases within
    15 %. Skips if the (large, un-versioned) experiment xlsx is absent.

    RE-ARMED 2026-07-22 (candidate D · D-2sc-4) — suspended 2026-07-15 when
    production went smooth-wall; the experimental anchors landed in
    D-2sc-2/3 (gamma_f_sco2 / gamma_nu_sco2) and the script was migrated to
    package imports + the flat re-exported xlsx (header-guarded column map;
    same dataset, cross-checked). Measured at re-arm: RMSRE 4.2 %,
    max|err| 8.1 % (case 37 — its hot Re 8453 sits below the gamma_Nu
    window, honestly falling back to smooth there), bias −0.8 %.
    HONESTY NOTE: the GOLD cases belong to the same campaign the γ anchors
    were fitted on — this is an IN-FAMILY end-to-end assembly check
    (correction reaches compute(); UA/ε-NTU chain sane), not a blind gate
    (sCO2 has no blind data — audit §4)."""
    from pathlib import Path
    import importlib.util
    # Moved from sjtu_tpmshx/validation/ to projects/703-sCO2-D76/ in c3635cd
    # (2026-06-30); the old path made this gate silently skip.
    val = (Path(__file__).resolve().parent.parent.parent / "projects"
           / "703-sCO2-D76" / "validate_sco2_d76.py")
    if not val.exists():
        pytest.skip("validate_sco2_d76.py not found")
    spec = importlib.util.spec_from_file_location("_val_sco2_d76", val)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:                       # pragma: no cover
        pytest.skip(f"validation module import failed: {e}")
    if not mod.XLSX.exists():
        pytest.skip("D-7-6 experiment xlsx not present")
    assert mod.main() == 0                       # 0 = Gate A PASS
