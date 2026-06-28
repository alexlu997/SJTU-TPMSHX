"""Phase 2.2 — njit enthalpy-form 3D LTNE kernel conservation gate.

solve_ltne_enthalpy_3d keeps h as the primary fluid unknown and telescopes the
mass flux ṁ on h (true enthalpy flux), so for a strongly variable-cp sCO2 stream
the two fluids' duties balance — unlike the legacy ρcp·u·T conservative kernel,
which on the same case leaves a large A/B imbalance (the 703 ~41% defect).

This is the 3D (njit) counterpart of the validated 1D PoC
(poc/poc_1d_ltne_enthalpy_optionB.py). Counterflow along x, variable-cp CO2
straddling the pseudocritical line.
"""
import numpy as np
import pytest

from solvers import sco2_props

pytestmark = pytest.mark.skipif(
    not sco2_props._HAVE_COOLPROP, reason="CoolProp required for sCO2 tests")


def _case():
    return dict(
        Nx=16, Ny=3, Nz=3, Lx=0.20, Ly=0.02, Lz=0.02,
        eps=0.68, k_s=14.0,
        m_dot_A=+1.6e-4, m_dot_B=-1.0e-4,
        h_vA=2.5e5, h_vB=2.5e5,
        T_inA=360.0, T_inB=298.0, P=8.0e6,
        dir_A=0, dir_B=1,
        n_sweep=20, omega=0.7, tol=1e-3, n_outer=2000,
    )


def test_enthalpy_3d_conserves_on_variable_cp_counterflow():
    from solvers.ltne_enthalpy_3d import solve_ltne_enthalpy_3d, enthalpy_metrics_3d
    res = solve_ltne_enthalpy_3d(**_case())
    m = enthalpy_metrics_3d(res, _case())

    # toy 16x3x3 grid → discretisation-sensitive; the meaningful gate is the
    # recuperator case (<5%) and the real 703 pipeline (2.2%). vs ~41-67% legacy.
    assert m["AB_imbal"] < 0.05, (
        f"3D enthalpy kernel A/B imbalance {m['AB_imbal']*100:.2f}% — not "
        f"conserving true enthalpy")
    assert m["e_imb_LTNE"] < 0.02, (
        f"solid balance Q_sA+Q_sB {m['e_imb_LTNE']*100:.3f}% not closing")


def test_enthalpy_3d_temperatures_physical():
    """Counterflow: hot A cools, cold B warms; both stay in a sane range."""
    from solvers.ltne_enthalpy_3d import solve_ltne_enthalpy_3d
    c = _case()
    res = solve_ltne_enthalpy_3d(**c)
    Ta, Tb = res["Ta"], res["Tb"]
    # hot inlet at x=0 (dir_A=0): A outlet (x=-1) cooler than inlet
    assert Ta[-1, :, :].mean() < c["T_inA"]
    # cold inlet at x=-1 (dir_B=1): B outlet (x=0) warmer than inlet
    assert Tb[0, :, :].mean() > c["T_inB"]
    assert Ta.min() > 240.0 and Ta.max() < 420.0


def _recuperator_case():
    """703 recuperator: hot 737 K @ 8.017 MPa, cold 361 K @ 18.48 MPa,
    counterflow, per-side pressure, high-NTU (h_v ~ 4e6 from the sCO2 Nu).
    The legacy ρcp·u·T 3D kernel leaves ~41% A/B imbalance here and under-reads
    the cold outlet to ~515 K; the enthalpy form must recover the energy-balance
    outlet (~655 K) and close the imbalance."""
    return dict(
        Nx=16, Ny=3, Nz=3, Lx=0.344, Ly=0.860, Lz=0.860,
        eps=0.675, k_s=16.0,
        m_dot_A=+37.6, m_dot_B=-37.6,
        h_vA=4.19e6, h_vB=4.32e6,
        T_inA=737.0, T_inB=361.0, P=8.017e6, P_B=18.48e6,
        dir_A=0, dir_B=1,
        n_sweep=25, omega=0.6, tol=1e-3, n_outer=1500,
    )


def test_enthalpy_3d_703_recuperator_conserves():
    """End-to-end value gate: Option B on the real 703 recuperator envelope
    closes the A/B imbalance (was ~41% with ρcp·u·T) and recovers the cold
    outlet (was wrongly ~515 K, energy balance wants ~655 K)."""
    from solvers.ltne_enthalpy_3d import solve_ltne_enthalpy_3d, enthalpy_metrics_3d
    c = _recuperator_case()
    res = solve_ltne_enthalpy_3d(**c)
    m = enthalpy_metrics_3d(res, c)

    assert m["AB_imbal"] < 0.05, (
        f"703 recuperator A/B imbalance {m['AB_imbal']*100:.2f}% — Option B "
        f"should be far below the legacy ~41%")
    assert m["e_imb_LTNE"] < 0.02
    # cold outlet (dir_B=1 → x=0) must land near the energy-balance value,
    # decisively above the legacy ρcp·u·T under-read of ~515 K.
    cold_out = float(res["Tb"][0, :, :].mean())
    assert cold_out > 600.0, (
        f"cold outlet {cold_out:.0f} K still under-read (legacy gave ~515 K; "
        f"energy balance wants ~655 K)")


def test_enthalpy_3d_near_critical_cp_spike_robust():
    """Precooler regime: a stream traversing the pseudocritical cp×56 spike
    (Tpc≈306 K @ 7.7 MPa) must stay robust and conservative. Option B has cp
    only in the denominator of the inter-phase linearisation and none in the
    convection, so the ×56 jump cannot destabilise it — the reason it was
    chosen over the in-T deferred-correction form (Option A)."""
    from solvers.ltne_enthalpy_3d import solve_ltne_enthalpy_3d, enthalpy_metrics_3d
    # hot A = large reservoir at ~322 K, cold B small → dragged up across Tpc.
    c = dict(Nx=40, Ny=3, Nz=3, Lx=0.20, Ly=0.5, Lz=0.5, eps=0.675, k_s=16.0,
             m_dot_A=+250.0, m_dot_B=-7.0, h_vA=2.5e6, h_vB=2.5e6,
             T_inA=322.0, T_inB=290.0, P=7.7e6, P_B=7.7e6, dir_A=0, dir_B=1,
             n_sweep=30, omega=0.5, tol=5e-4, n_outer=4000)
    res = solve_ltne_enthalpy_3d(**c)
    m = enthalpy_metrics_3d(res, c)

    assert np.all(np.isfinite(res["Ta"])) and np.all(np.isfinite(res["Tb"])), \
        "NaN through the cp×56 spike"
    Tb = res["Tb"][:, 1, 1]
    # the cold stream must actually traverse the spike, with cells in the peak
    assert Tb.min() < 306.0 < Tb.max(), "cold stream did not cross Tpc"
    assert int(np.sum((Tb > 303.0) & (Tb < 309.0))) >= 5, \
        "no cells resolved inside the sharp spike band"
    # and conservation must hold THROUGH the spike
    assert m["AB_imbal"] < 0.03, (
        f"A/B imbalance {m['AB_imbal']*100:.2f}% through the cp×56 spike")
    assert m["e_imb_LTNE"] < 0.02
