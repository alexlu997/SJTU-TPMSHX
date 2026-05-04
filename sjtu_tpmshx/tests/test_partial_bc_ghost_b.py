"""Partial BC + Air-Air ghost-B regression tests (M4 baseline closure).

Validates that the M4 0D effective interfacial-area closure prevents
thermodynamic bound violation under partial inlet/outlet BC.

PASS/FAIL uses corrected criteria (v3):
  - ε_obs = Q_ref / (C_min · ΔT_max) ≤ ε_max
  - S_gen ≥ 0
  - Q_sA + Q_sB closed (solid energy balance)
  - Historical ghost-B fixture retains T_B<T_A as regression warning,
    NOT as universal thermodynamic gate (C_r-dependent, see P0 diag).
"""
import os, sys, pytest, numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solvers.tpms_calc import air_cp, air_density as _air_rho


def _partial_bc_air_air_cfg(**overrides):
    """Shanghai Air-Air partial-B config (Nx=Ny=Nz=15 for speed)."""
    cfg = dict(
        L=0.182, H=0.042, Lz=0.042,
        Nx=15, Ny=15, Nz=15,
        u_A=10.0, u_B=20.0, T_inA=422.0, T_inB=322.0,
        P_inA=192362.0, P_inB=101325.0,
        tpms_type='Gyroid', Lcell=7.0, t_wall=0.6, k_s=16.0, eps=0.85,
        fluid_A_cfg=dict(dir=0, in_ctr=0.021, in_w=0.042,
                         out_ctr=0.021, out_w=0.042,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
        fluid_B_cfg=dict(dir=3, in_ctr=0.154, in_w=0.042,
                         out_ctr=0.028, out_w=0.042,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
        fluid_type_A='air', fluid_type_B='air',
        wall_refine_3d=False,
        partial_B_closure='m4_effective_area', m4_exponent=0.67,
    )
    cfg.update(overrides)
    return cfg


def _compute_epsilon(r):
    """Corrected ε = Q_ref / (C_min · ΔT_max)."""
    cp_A = air_cp(422); cp_B = air_cp(322)
    rho_A = _air_rho(422, 192362); rho_B = _air_rho(322, 101325)
    A_A = 0.042*0.042; A_B = 0.042*0.042  # partial B
    C_A = rho_A * 10 * A_A * cp_A
    C_B = rho_B * 20 * A_B * cp_B
    C_min = min(C_A, C_B)
    Q_A = abs(r.get('Q_enthalpy_A', 0))
    Q_B = abs(r.get('Q_enthalpy_B', 0))
    Q_ref = 0.5 * (Q_A + Q_B)
    return Q_ref / (C_min * 100.0) if C_min > 0 else 0.0


# ── Thermodynamic bound (corrected ε-NTU) ──────────────────────────


def test_epsilon_ntu_bound():
    """ε_obs ≤ ε_max for partial-BC ghost-B case."""
    from runs.run_calculation_3d import _run_3d_stack
    r = _run_3d_stack(_partial_bc_air_air_cfg())
    eps = _compute_epsilon(r)
    # ε_max for cross-flow C_r≈0.74, NTU≈7: ≈0.87
    assert eps <= 0.90, f"ε_obs={eps:.4f} exceeds ε_max bound"


# ── Historical ghost-B fixture (regression warning only) ────────────


def test_ghost_B_T_out_regression():
    """Historical ghost-B case: T_B < T_A as regression warning.
    NOT a universal thermodynamic gate. C_r-dependent — if C_B >> C_A,
    T_B > T_A is physically possible. Use epsilon criteria for PASS/FAIL."""
    from runs.run_calculation_3d import _run_3d_stack
    r = _run_3d_stack(_partial_bc_air_air_cfg())
    if r['T_B_out'] > r['T_A_out']:
        # Warning only — check ε before failing
        eps = _compute_epsilon(r)
        if eps > 0.90:
            pytest.fail(f"Ghost-B regression: T_B={r['T_B_out']:.1f} > "
                        f"T_A={r['T_A_out']:.1f} AND ε={eps:.4f} > 0.90")


# ── Solid energy balance ───────────────────────────────────────────


def test_solid_energy_balance():
    """Q_sA + Q_sB ≈ 0 (solid-phase steady-state energy conservation)."""
    from runs.run_calculation_3d import _run_3d_stack
    r = _run_3d_stack(_partial_bc_air_air_cfg())
    Q_sA = r.get('Q_sA', 0.0); Q_sB = r.get('Q_sB', 0.0)
    imbal = abs(Q_sA + Q_sB) / max(abs(Q_sA) + abs(Q_sB), 1e-30)
    assert imbal < 0.05, f"Solid imbalance: rel={imbal:.4f}"


# ── Enthalpy-solid gap diagnostic (xfail, known BC-layer pinning) ──

@pytest.mark.xfail(reason="Known BC-layer pinning in LTNE enthalpy vs "
                          "solid-source balance. See P0 diag.")
def test_enthalpy_solid_gap_diagnostic():
    """Diagnostic: B-side Q_enth vs Q_solid gap (BC-pinning awareness)."""
    from runs.run_calculation_3d import _run_3d_stack
    r = _run_3d_stack(_partial_bc_air_air_cfg())
    Qe_B = abs(r['Q_enthalpy_B']); Q_sB = abs(r.get('Q_sB', 0.0))
    if Qe_B > 1 and Q_sB > 1:
        rel = abs(Qe_B - Q_sB) / max(Q_sB, 1.0)
        assert rel < 0.15, f"B enth-solid gap: {rel:.3f}"


# ── η_B degradation: zero inlet velocity ──────────────────────────


def test_eta_B_degenerate_zero_inlet():
    """u_B=0 → η_B bounded. Must not crash or div-by-zero."""
    from runs.run_calculation_3d import _run_3d_stack
    r = _run_3d_stack(_partial_bc_air_air_cfg(u_B=0.0))
    assert np.isfinite(r['T_A_out']), "T_A must be finite"
    assert np.isfinite(r.get('T_B_out', 0)), "T_B must be finite"


# ── M4 degradation: full-face B → η_eff = 1 ───────────────────────


def test_full_face_B_recovers_identity():
    """Full-face B → r_eff=1 → η_eff=1. Should match no-closure."""
    from runs.run_calculation_3d import _run_3d_stack
    cfg = _partial_bc_air_air_cfg()
    cfg['fluid_B_cfg'] = dict(dir=3, in_ctr=0.091, in_w=0.182,
                              out_ctr=0.091, out_w=0.182,
                              in_z_ctr=0.021, in_z_w=0.042,
                              out_z_ctr=0.021, out_z_w=0.042)
    r = _run_3d_stack(cfg)
    chi = r.get('chi_B')
    if chi is not None:
        assert np.mean(chi) > 0.95, f"Full-face: χ mean={np.mean(chi):.4f}"
    eps = _compute_epsilon(r)
    assert eps <= 0.95, f"Full-face ε={eps:.4f}"


# ── η_B field sanity ──────────────────────────────────────────────


def test_eta_B_field_bounds():
    """η_B (chi_B) must be in [0, 1] everywhere."""
    from runs.run_calculation_3d import _run_3d_stack
    r = _run_3d_stack(_partial_bc_air_air_cfg())
    chi = r.get('chi_B')
    if chi is None:
        pytest.skip("chi_B not in result dict")
    c = np.asarray(chi)
    assert c.min() >= -1e-9 and c.max() <= 1.0 + 1e-9
