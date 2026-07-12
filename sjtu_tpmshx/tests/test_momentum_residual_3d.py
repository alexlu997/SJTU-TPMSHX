"""Momentum residual (ledger C6) — correctness + non-interference.

The mass residual cannot measure convergence on this solver: the pressure
correction is solved EXACTLY each iteration against the very rho_eps the
residual is then evaluated with, so it is ~0 by construction on every solved
cell, and the reported number is entirely the pressure-pinned outlet row's
artifact. `_mom_res_jit_3d` is the honest alternative.

THE LOAD-BEARING TEST is `test_residual_vanishes_at_momentum_fixed_point`,
parametrised over every (use_sou, use_eps) branch.

`_{u,v,w}_coeffs_df_3d` is a DELIBERATE PARALLEL ASSEMBLY of the sweep cell
bodies `_{u,v,w}_cell_df_3d` — not a shared helper. (Factoring them out and
having both call one helper was tried; it moved golden-3D by fastmath ULP
re-association at the inline boundary, and a diagnostic must not cost a
re-baseline.) That duplication is a real drift hazard, so it is GUARDED here
rather than trusted: if you edit a sweep cell body and not its coeffs twin, the
residual stops vanishing at the sweep's OWN fixed point and this test fails
loudly. Keep them in lockstep.
"""
import numpy as np
import pytest

from solvers.simple_solver_3d import SIMPLESolver3D
from solvers._kernels_simple_3d import (
    _mom_res_jit_3d,
    _sweep_u_jit_df_3d,
    _sweep_v_jit_df_3d,
    _sweep_w_jit_df_3d,
)


def _make_solver(Nx=6, Ny=8, Nz=4, v_inlet=2.0, zoned_eps=False):
    K = np.full((Ny, Nz), 3.0e-8)
    cF = np.full((Ny, Nz), 250.0)
    s = SIMPLESolver3D(
        Lx=0.02, Ly=0.03, Lz=0.01, Nx=Nx, Ny=Ny, Nz=Nz,
        rho=1.18, mu=1.85e-5, T_in=300.0, v_inlet=v_inlet,
        eps=0.72, K_arr=K, cF_arr=cF,
        fluid_type='ideal_gas',
    )
    if zoned_eps:
        # Non-uniform ε in all three directions so every r_f = ε_f/ε_CV factor
        # in the use_eps=1 branch is exercised (a uniform field leaves them all
        # at 1.0 and the branch would be untested).
        i = np.arange(Nx)[:, None, None]
        j = np.arange(Ny)[None, :, None]
        k = np.arange(Nz)[None, None, :]
        s.eps_field = np.ascontiguousarray(
            0.60 + 0.02 * i + 0.008 * j + 0.015 * k, dtype=np.float64)
        s._mu_eff_field = np.ascontiguousarray(s.mu_field / s.eps_field)
    return s


def _mom_res(s, use_sou=0, use_eps=0):
    """(R_u, R_v, R_w) relative L1 momentum residuals on the solver's state."""
    nu, du, nv, dv, nw, dw = _mom_res_jit_3d(
        s.u, s.v, s.w, s.P,
        s.Nx, s.Ny, s.Nz, s.dx, s.dy, s.dz,
        s.rho_field, s._mu_eff_field, s.mu_field, s.eps_field,
        s.K_arr, s.cF_arr, s.outlet_frac, s.inlet_frac, use_sou, use_eps)
    f = lambda n, d: (n / d if d > 1e-300 else 0.0)  # noqa: E731
    return f(nu, du), f(nv, dv), f(nw, dw)


@pytest.mark.parametrize('use_sou', [0, 1])
@pytest.mark.parametrize('use_eps', [0, 1])
def test_residual_vanishes_at_momentum_fixed_point(use_sou, use_eps):
    """THE sync guard, on every branch. Sweep momentum alone (P, rho frozen) to
    its own fixed point; the residual kernel must then read ~0. It can only do
    so if `_{u,v,w}_coeffs_df_3d` assembles exactly the aP0/rhs that
    `_{u,v,w}_cell_df_3d` does — including the guarded SOU and VANS ε-ratio
    blocks. Any coefficient drift between the twins leaves an O(1e-2..1)
    residual here.
    """
    s = _make_solver(zoned_eps=bool(use_eps))
    # A non-trivial frozen pressure field so p_src is not identically zero.
    ii = np.arange(s.Nx)[:, None, None]
    jj = np.arange(s.Ny)[None, :, None]
    s.P[:, :, :] = 50.0 * (s.Ny - 1 - jj) + 3.0 * ii

    kw = dict(Nx=s.Nx, Ny=s.Ny, Nz=s.Nz, dx=s.dx, dy=s.dy, dz=s.dz,
              rho_field=s.rho_field, mu_eff_field=s._mu_eff_field,
              mu_field=s.mu_field, eps_field=s.eps_field,
              K_arr=s.K_arr, cF_arr=s.cF_arr,
              outlet_frac=s.outlet_frac, inlet_frac=s.inlet_frac,
              alpha_u=1.0, use_sou=use_sou, use_eps=use_eps)

    # Momentum-only Picard: sweep u/v/w with P frozen until the field stops
    # moving. alpha_u = 1.0 -> the sweep's fixed point IS the unrelaxed
    # equation aP0*phi = rhs, which is exactly what the residual measures.
    for _ in range(600):
        prev = (s.u.copy(), s.v.copy(), s.w.copy())
        _sweep_u_jit_df_3d(s.u, s.v, s.w, s.P, s.d_u, n_sweeps=1, **kw)
        _sweep_v_jit_df_3d(s.u, s.v, s.w, s.P, s.d_v,
                           v_inlet_field=s.v_inlet_field, n_sweeps=1, **kw)
        _sweep_w_jit_df_3d(s.u, s.v, s.w, s.P, s.d_w, n_sweeps=1, **kw)
        d = max(np.abs(s.u - prev[0]).max(),
                np.abs(s.v - prev[1]).max(),
                np.abs(s.w - prev[2]).max())
        if d < 1e-14:
            break
    else:
        pytest.fail(f"momentum sweeps did not reach a fixed point (last d={d:.2e})")

    Ru, Rv, Rw = _mom_res(s, use_sou=use_sou, use_eps=use_eps)
    assert Ru < 1e-12, f"u-momentum residual did not vanish: {Ru:.3e}"
    assert Rv < 1e-12, f"v-momentum residual did not vanish: {Rv:.3e}"
    assert Rw < 1e-12, f"w-momentum residual did not vanish: {Rw:.3e}"


def test_residual_is_nonzero_off_the_fixed_point():
    """Sanity: the metric is not trivially zero. Perturb a converged field and
    the residual must jump — otherwise the vanishing above proves nothing."""
    s = _make_solver()
    s.P[:, :, :] = 100.0
    before = _mom_res(s)
    s.u += 0.5          # kick the field off any equilibrium
    s.v += 0.3
    after = _mom_res(s)
    assert max(after) > max(before), (before, after)
    assert max(after) > 1e-3, f"residual implausibly small after a 0.5 m/s kick: {after}"


def test_tracking_is_opt_in_and_off_by_default():
    s = _make_solver()
    s.solve(max_iter=5, tol=1e-12)
    assert not hasattr(s, 'mom_residuals'), \
        "momentum-residual tracking must be OFF by default (it costs an extra " \
        "coefficient assembly per iteration)"


def test_tracking_records_a_history_and_does_not_change_the_result():
    """Enabling the diagnostic must not perturb ANY solver output — it is
    recorded after the fields are final and never gates the exit."""
    s0 = _make_solver()
    c0, n0 = s0.solve(max_iter=60, tol=1e-12)

    s1 = _make_solver()
    s1.track_momentum_residual = True
    c1, n1 = s1.solve(max_iter=60, tol=1e-12)

    assert (c0, n0) == (c1, n1)
    assert s0.exit_reason == s1.exit_reason
    np.testing.assert_array_equal(s0.u, s1.u)
    np.testing.assert_array_equal(s0.v, s1.v)
    np.testing.assert_array_equal(s0.w, s1.w)
    np.testing.assert_array_equal(s0.P, s1.P)
    np.testing.assert_array_equal(s0.rho_field, s1.rho_field)

    assert len(s1.mom_residuals) == n1
    for r in s1.mom_residuals:
        assert set(r) == {'u', 'v', 'w', 'max'}
        assert r['max'] == max(r['u'], r['v'], r['w'])
        assert np.isfinite(r['max'])


def test_momentum_residual_decays_over_a_solve():
    """The metric must actually converge: it rises as the momentum sweeps
    develop the flow, then falls by orders of magnitude. (LowReExit is disabled
    so the solve is not cut short by the velocity criterion at iteration 10.)

    Deliberately NOT asserted here: that the mass residual floors. The floor's
    MAGNITUDE is case-dependent (it is the pinned outlet row's transverse
    divergence, which is small on a slow uniform toy and 8e-4 on the compressible
    Shanghai case). Pinning it on a toy config would be a fragile test of a real
    phenomenon; the evidence lives in ledger C6 with the production numbers.
    """
    s = _make_solver(Nx=8, Ny=12, Nz=4, v_inlet=3.0)
    s.track_momentum_residual = True
    s.lowre_early_exit = False
    s.solve(max_iter=400, tol=1e-14)

    mom = [r['max'] for r in s.mom_residuals]
    assert len(mom) == len(s.residuals) >= 100

    peak = max(mom)
    tail = min(mom[-10:])
    assert tail < peak / 10.0, \
        f"momentum residual did not decay: peak={peak:.2e} tail={tail:.2e}"
    assert all(np.isfinite(m) for m in mom)
