"""SIMPLER coupling (opt-in, openspec change simpler-coupling-2d) tests.

Covers the spec requirements:
1. `coupling` parameter validation (default / explicit / invalid).
2. Pseudo-velocity kernel coefficient parity with the sweep kernels:
   - d_u/d_v pointwise parity on a zero-flow frozen state (GS == Jacobi there,
     so the comparison is exact; exercises diffusion + Darcy + wall penalty).
   - single-cell hand-assembled û/v̂ spot check on a NONZERO frozen state
     (exercises the convective / SOU / variable-ρμ terms the zero-flow
     state cannot).
3. Incompressible-limit agreement: constant-density config converges to the
   same solution under both couplings (ΔP ≤ 1%, fields rel L2 ≤ 1e-2).
4. Compressible smoke: ideal-gas + mass-flux inlet still pins the inlet
   mass flux in SIMPLER mode.
"""
from __future__ import annotations
import numpy as np
import pytest

from sjtu_tpmshx.solvers.simple_solver import (
    SIMPLESolver,
    _sweep_u_jit_df, _sweep_v_jit_df,
    _pseudo_u_jit_df, _pseudo_v_jit_df,
    _porous_src_df, _umag_u, _sou_corr_u_x, _sou_corr_u_y, _WALL_PENALTY_BASE, _WALL_PENALTY_EFOLD,
)


def _make_solver(fluid_type='ideal_gas', v_inlet=8.0, Nx=12, Ny=24):
    return SIMPLESolver(
        W=0.042, H=0.06, Nx=Nx, Ny=Ny,
        tpms_type='Gyroid', L_cell_mm=7.0, t_mm=0.6, eps=0.6, r_h=1e-3,
        rho=1.2, mu=1.8e-5, T_in=322.0,
        inlet_lo=0.0, inlet_hi=0.042, v_inlet=v_inlet,
        fluid_type=fluid_type,
        wall_refine=False,
    )


# ────────────────────────────────────────────────────────────────────
# 1. coupling parameter validation
# ────────────────────────────────────────────────────────────────────

def test_coupling_invalid_raises():
    s = _make_solver()
    with pytest.raises(ValueError, match="coupling"):
        s.solve(max_iter=1, coupling='piso', verbose=False)


def test_coupling_default_and_explicit_simple_run():
    s = _make_solver()
    conv, _ = s.solve(max_iter=60, tol=1e-6, verbose=False)
    s2 = _make_solver()
    conv2, _ = s2.solve(max_iter=60, tol=1e-6, coupling='simple', verbose=False)
    assert conv and conv2
    assert np.array_equal(s.P, s2.P)   # explicit 'simple' is the default path


# ────────────────────────────────────────────────────────────────────
# 2. pseudo-velocity kernel coefficient parity
# ────────────────────────────────────────────────────────────────────

def _K2d_pair(s):
    """2026-07-10 lateral-K: kernels take 2D K/cF fields — tile the per-row
    arrays (laterally uniform -> bit-identical to the old 1D path)."""
    K2 = np.ascontiguousarray(np.repeat(s._K_arr[None, :], s.Nx, axis=0))
    c2 = np.ascontiguousarray(np.repeat(s._cF_arr[None, :], s.Nx, axis=0))
    return K2, c2


def test_d_coefficient_parity_zero_flow():
    """On a zero-flow frozen state the GS sweep does not move u/v (rhs = 0),
    so sweep and pseudo kernels see identical fields -> d must match exactly."""
    s = _make_solver(fluid_type='incompressible', v_inlet=0.0)
    Nx, Ny = s.Nx, s.Ny
    u = np.zeros_like(s.u); v = np.zeros_like(s.v)
    P = np.zeros_like(s.P)
    d_sweep_u = np.zeros_like(s.d_u); d_pseudo_u = np.zeros_like(s.d_u)
    d_sweep_v = np.zeros_like(s.d_v); d_pseudo_v = np.zeros_like(s.d_v)

    _sweep_u_jit_df(u.copy(), v.copy(), P, d_sweep_u,
                    s.inlet_frac, s.outlet_frac,
                    Nx, Ny, s.dx_arr, s.dy_arr, s.rho_field, s._mu_eff_field,
                    *_K2d_pair(s), s.mu_field, s.eps_field, 1.0, 1, 0.0)
    uhat = u.copy()
    _pseudo_u_jit_df(u, v, uhat, d_pseudo_u,
                     s.inlet_frac, s.outlet_frac,
                     Nx, Ny, s.dx_arr, s.dy_arr, s.rho_field, s._mu_eff_field,
                     *_K2d_pair(s), s.mu_field, s.eps_field, 0.0)
    np.testing.assert_allclose(d_pseudo_u, d_sweep_u, rtol=1e-12, atol=0.0)

    v_in = np.zeros(Nx)
    _sweep_v_jit_df(u.copy(), v.copy(), P, d_sweep_v,
                    s.inlet_frac, v_in, s.outlet_frac,
                    Nx, Ny, s.dx_arr, s.dy_arr, s.rho_field, s._mu_eff_field,
                    *_K2d_pair(s), s.mu_field, s.eps_field, 1.0, 1, 0.0)
    vhat = v.copy()
    _pseudo_v_jit_df(u, v, uhat, vhat, d_pseudo_v,
                     s.inlet_frac, v_in, s.outlet_frac,
                     Nx, Ny, s.dx_arr, s.dy_arr, s.rho_field, s._mu_eff_field,
                     *_K2d_pair(s), s.mu_field, s.eps_field, 0.0)
    np.testing.assert_allclose(d_pseudo_v, d_sweep_v, rtol=1e-12, atol=0.0)


def _expected_uhat_cell(s, u, v, i, j):
    """Hand-assembled û for one interior u-cell — mirrors the documented
    coefficient formula (convection/diffusion/DF/SOU, no pressure, no relax)."""
    Nx, Ny = s.Nx, s.Ny
    dx_arr, dy_arr = s.dx_arr, s.dy_arr
    dxi = 0.5 * (dx_arr[i - 1] + dx_arr[min(i, Nx - 1)])
    dyj = dy_arr[j]
    vol = dxi * dyj
    il_r, ir_r = max(i - 1, 0), min(i, Nx - 1)
    mu_e = 0.5 * (s._mu_eff_field[il_r, j] + s._mu_eff_field[ir_r, j])
    De0 = mu_e * dyj / dxi
    Dn0 = mu_e * dxi / dyj
    uE = u[i + 1, j] if i + 1 < Nx else 0.0
    uW = u[i - 1, j] if i > 1 else 0.0
    uN = u[i, j + 1] if j < Ny - 1 else u[i, j]
    uS = u[i, j - 1] if j > 0 else 0.0
    De = Dw = De0
    Dn = Dn0 if j < Ny - 1 else 0.0
    Ds = Dn0 if j > 0 else 0.0
    ue = 0.5 * (u[i, j] + u[min(i + 1, Nx), j])
    uw = 0.5 * (u[max(i - 1, 0), j] + u[i, j])
    il, ir = max(i - 1, 0), min(i, Nx - 1)
    vn = 0.5 * (v[il, j + 1] + v[ir, j + 1]) if j < Ny - 1 else 0.0
    vs = 0.5 * (v[il, j] + v[ir, j])
    rho_loc = 0.5 * (s.rho_field[il_r, j] + s.rho_field[ir_r, j])
    mu_loc = 0.5 * (s.mu_field[il_r, j] + s.mu_field[ir_r, j])
    Fe = rho_loc * ue * dyj; Fw = rho_loc * uw * dyj
    Fn = rho_loc * vn * dxi; Fs = rho_loc * vs * dxi
    aE = De + max(-Fe, 0.0); aW = Dw + max(Fw, 0.0)
    aN = Dn + max(-Fn, 0.0); aS = Ds + max(Fs, 0.0)
    umag = _umag_u(u, v, i, j, Nx, Ny)
    Sp = _porous_src_df(umag, s._K_arr[j], s._cF_arr[j], mu_loc, rho_loc) * vol
    aP_nat = aE + aW + aN + aS
    wall_out = 1.0 - 0.5 * (s.outlet_frac[il_r] + s.outlet_frac[ir_r])
    if wall_out > 0.01 and j >= Ny - 8:
        Sp += _WALL_PENALTY_BASE * wall_out**4 * np.exp(
            -_WALL_PENALTY_EFOLD * (Ny - j - 1)) * aP_nat
    wall_in = 1.0 - 0.5 * (s.inlet_frac[il_r] + s.inlet_frac[ir_r])
    if wall_in > 0.01 and j < 8:
        Sp += _WALL_PENALTY_BASE * wall_in**4 * np.exp(
            -_WALL_PENALTY_EFOLD * j) * aP_nat
    sou = (_sou_corr_u_x(u, i, j, Nx, Fe, Fw)
           + _sou_corr_u_y(u, i, j, Ny, Fn, Fs))
    aP0 = aE + aW + aN + aS + Sp
    return (aE * uE + aW * uW + aN * uN + aS * uS + sou) / aP0


def test_pseudo_u_spot_check_nonzero_flow():
    """Convective-term parity: û at interior cells matches the hand-assembled
    formula on a frozen NONZERO velocity/density state."""
    s = _make_solver()
    Nx, Ny = s.Nx, s.Ny
    rng = np.random.default_rng(7)
    u = 0.5 * rng.standard_normal((Nx + 1, Ny))
    v = 4.0 + 0.5 * rng.standard_normal((Nx, Ny + 1))
    s.rho_field = 1.2 + 0.1 * rng.random((Nx, Ny))
    uhat = u.copy()
    d_u = np.zeros_like(s.d_u)
    _pseudo_u_jit_df(u, v, uhat, d_u,
                     s.inlet_frac, s.outlet_frac,
                     Nx, Ny, s.dx_arr, s.dy_arr, s.rho_field, s._mu_eff_field,
                     *_K2d_pair(s), s.mu_field, s.eps_field, 0.0)
    for (i, j) in [(3, 5), (6, 12), (Nx - 2, Ny - 10)]:
        expected = _expected_uhat_cell(s, u, v, i, j)
        assert uhat[i, j] == pytest.approx(expected, rel=1e-12), (i, j)


def test_pseudo_boundary_faces_carry_bcs():
    """û side walls are 0; v̂ inlet face = v_inlet_field·inlet_frac; v̂ outlet
    face closes local mass including transverse pseudo-flux."""
    s = _make_solver()
    Nx, Ny = s.Nx, s.Ny
    rng = np.random.default_rng(11)
    u = 0.1 * rng.standard_normal((Nx + 1, Ny))
    v = 4.0 + 0.1 * rng.standard_normal((Nx, Ny + 1))
    uhat = u.copy(); vhat = v.copy()
    d_u = np.zeros_like(s.d_u); d_v = np.zeros_like(s.d_v)
    _pseudo_u_jit_df(u, v, uhat, d_u, s.inlet_frac, s.outlet_frac,
                     Nx, Ny, s.dx_arr, s.dy_arr, s.rho_field, s._mu_eff_field,
                     *_K2d_pair(s), s.mu_field, s.eps_field, 0.0)
    _pseudo_v_jit_df(u, v, uhat, vhat, d_v, s.inlet_frac, s.v_inlet_field,
                     s.outlet_frac,
                     Nx, Ny, s.dx_arr, s.dy_arr, s.rho_field, s._mu_eff_field,
                     *_K2d_pair(s), s.mu_field, s.eps_field, 0.0)
    assert np.all(uhat[0, :] == 0.0) and np.all(uhat[Nx, :] == 0.0)
    np.testing.assert_allclose(vhat[:, 0], s.v_inlet_field * s.inlet_frac)
    rho_inner = 0.5 * (s.rho_field[:, Ny - 2] + s.rho_field[:, Ny - 1])
    lateral = np.diff(uhat[:, -1]) * s.dy_arr[-1] / s.dx_arr
    np.testing.assert_allclose(
        vhat[:, Ny], vhat[:, Ny - 1] * rho_inner / s.rho_field[:, Ny - 1] - lateral)


# ────────────────────────────────────────────────────────────────────
# 3. incompressible-limit agreement (SIMPLE vs SIMPLER same solution)
# ────────────────────────────────────────────────────────────────────

def _rel_l2(a, b):
    return float(np.linalg.norm(a - b) / max(np.linalg.norm(b), 1e-30))


def test_simpler_incompressible_limit_agreement():
    sA = _make_solver(fluid_type='incompressible', v_inlet=5.0, Nx=16, Ny=32)
    convA, _ = sA.solve(max_iter=2000, tol=1e-8, verbose=False)
    sB = _make_solver(fluid_type='incompressible', v_inlet=5.0, Nx=16, Ny=32)
    convB, _ = sB.solve(max_iter=2000, tol=1e-8, coupling='simpler',
                        verbose=False)
    assert convA and convB
    dP_A = float(sA.P[:, 0].mean() - sA.P[:, -1].mean())
    dP_B = float(sB.P[:, 0].mean() - sB.P[:, -1].mean())
    assert abs(dP_B - dP_A) / abs(dP_A) <= 0.01
    # u is the SECONDARY (cross-stream) velocity, near zero in this duct
    # config — self-normalised rel-L2 would amplify iteration-path noise, so
    # normalise by the primary-flow scale ||v|| (Ghia-style U_ref convention).
    assert float(np.linalg.norm(sB.u - sA.u) / np.linalg.norm(sA.v)) <= 1e-2
    assert _rel_l2(sB.v, sA.v) <= 1e-2
    assert _rel_l2(sB.P, sA.P) <= 1e-2


# ────────────────────────────────────────────────────────────────────
# 4. compressible smoke: mass-flux inlet preserved in SIMPLER mode
# ────────────────────────────────────────────────────────────────────

def test_simpler_massflux_inlet_pins_throughput():
    s = _make_solver()   # ideal_gas, massflux default ON
    conv, _ = s.solve(max_iter=600, tol=1e-6, coupling='simpler',
                      verbose=False)
    assert conv
    assert s.envelope_ok if hasattr(s, 'envelope_ok') else True
    G = s._massflux_target
    flux = s.v_inlet_field * np.maximum(s.rho_field[:, 0], 1e-9)
    np.testing.assert_allclose(flux, G, rtol=1e-12)
    # SIMPLER didn't corrupt the P gauge: outlet row stays at 0
    assert np.allclose(s.P[:, -1], 0.0)
