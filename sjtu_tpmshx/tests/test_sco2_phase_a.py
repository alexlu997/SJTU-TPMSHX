"""Phase A sCO2 enablement (2026-06-26).

Covers: SCO2_NU_COEFFS / nu_sco2_topo correlation form, FluidModel('sco2')
CoolProp primitives + (T,P) signature, compute(fluid_type='sco2') routing the
sCO2 Nu, single-geometry guard (Diamond only). Far-from-critical regime.

See vault reports/engineering/sco2/2026-06-26-sco2-nu-correlation-construction-CN.md
"""
import warnings

import numpy as np
import pytest

from solvers import fluid_props, tpms_calc
from solvers.nu_correlations import (
    nu_sco2_topo, SCO2_NU_COEFFS, SCO2_NU_RE_RANGE,
)


# ── correlation form ────────────────────────────────────────────────
def test_sco2_nu_form_diamond():
    """Nu = c·Re^a·Pr^(1/3), c=0.28, a=0.75 (no ×1.28 roughness)."""
    Re, Pr = 20000.0, 0.85
    expect = 0.28 * Re ** 0.75 * Pr ** (1 / 3)
    assert nu_sco2_topo('Diamond', Re, Pr) == pytest.approx(expect, rel=1e-12)


def test_sco2_nu_coeffs_locked():
    assert SCO2_NU_COEFFS['Diamond'] == {'c': 0.28, 'a': 0.75}
    assert SCO2_NU_RE_RANGE == (9000.0, 41000.0)


def test_sco2_nu_array_safe():
    Re = np.array([9000.0, 20000.0, 41000.0])
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        out = nu_sco2_topo('Diamond', Re, 0.85)
    assert out.shape == Re.shape and np.all(out > 0)


def test_sco2_nu_gyroid_raises():
    """Single-geometry fit — no silent borrowing of another topology."""
    with pytest.raises(NotImplementedError):
        nu_sco2_topo('Gyroid', 20000.0, 0.85)


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
    expect = 0.28 * r['Re'] ** 0.75 * Pr ** (1 / 3)
    assert r['Nu'] == pytest.approx(expect, rel=1e-9)
    assert r['H_sf'] > 0


# ── Gate A: lumped ε-NTU duty vs D-7-6 GOLD experiment ──────────────
def test_gate_a_d76_gold_duty():
    """sCO2 Nu closure reproduces measured duty on the 6 GOLD cases within
    15 %. Skips if the (large, un-versioned) experiment xlsx is absent."""
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
