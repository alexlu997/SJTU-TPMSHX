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

    SKIP HISTORY — 2026-07-15: production switched to SMOOTH-WALL closures,
    gate suspended "until the experimental γ anchor lands". 2026-07-22
    (D-2sc-3): γ_Nu HAS landed (nu_correlations.gamma_nu_sco2, Diamond
    1.756 — the historical ~1.7× gap this gate measured), so the PHYSICS
    trigger is satisfied; what still blocks the re-arm is MECHANICAL:
    (a) validate_sco2_d76.py carries pre-P1.8b dead imports (`from solvers
    import …` — projects/ was never migrated), so exec_module fails and
    this test would skip VACUOUSLY; (b) its XLSX path points at
    data/raw_data/D-7-6-sCO2/…V1.xlsx which no longer exists (flat
    D-7-6实验数据-sCO2.xlsx — same-content verification pending).
    Re-arm slice = candidate D · D-2sc-4."""
    pytest.skip("γ_Nu landed 2026-07-22 (D-2sc-3) — re-arm now blocked on "
                "projects/703 script import migration + XLSX path fix "
                "(D-2sc-4), not on physics")
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
