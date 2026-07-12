"""F2 convergence mode for the 2D SIMPLE solver (ledger C6 / C7 / C9).

2D's legacy `tol` is even more degenerate than 3D's. `_mass_res_jit` is a
PLANE-INTEGRATED flux defect; the pp solve drives the per-cell divergence to
zero, so every plane's flux telescopes to the inlet's and on a FULL-FACE outlet
the residual is a TAUTOLOGY. `tol` therefore fires at the MIN-ITER FLOOR
(iteration 20) and the solve stops there — with dP under-converged by 3.3 % on
the production pipeline.

The load-bearing tests here:

  * `test_legacy_tol_is_a_tautology_and_fires_at_the_min_iter_floor` — pins the
    DEFECT itself, so nobody "fixes" F2 by reverting to a criterion that never
    tested anything.
  * `test_momentum_residual_vanishes_at_the_sweep_fixed_point` — the sync guard
    for the deliberate parallel assembly in `_{u,v}_coeffs_df_2d`.
  * `test_balanced_denominator_has_no_false_zero` — the P0 the balanced
    denominator exists to kill.
"""
import numpy as np
import pytest

from solvers.simple_solver import SIMPLESolver
from solvers._kernels_simple_2d import (
    _mom_res_jit_2d,
    _sweep_u_jit_df,
    _sweep_v_jit_df,
)


def _make(Nx=20, Ny=20, v_inlet=8.0, **kw):
    s = SIMPLESolver(0.05, 0.10, Nx, Ny, 'Gyroid', 6.0, 0.4, 0.7, 1.7e-3,
                     1.18, 1.85e-5, 400.0, 0.0, 0.05, v_inlet,
                     outlet_lo=0.0, outlet_hi=0.05,
                     P_ref_abs=101325.0, wall_refine=False)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _K2d(s):
    return (s._K_field2d if s._K_field2d is not None
            else np.ascontiguousarray(np.repeat(s._K_arr[None, :], s.Nx, axis=0)))


def _cF2d(s):
    return (s._cF_field2d if s._cF_field2d is not None
            else np.ascontiguousarray(np.repeat(s._cF_arr[None, :], s.Nx, axis=0)))


def _mom(s):
    """(num_u, den_u, num_v, den_v) on the solver's current state."""
    return _mom_res_jit_2d(
        s.u, s.v, s.P, s.Nx, s.Ny, s.dx_arr, s.dy_arr,
        s.rho_field, s._mu_eff_field, _K2d(s), _cF2d(s), s.mu_field,
        s.eps_field, s.inlet_frac, s.outlet_frac, s.cf_aniso)


# ─────────────────────────────────────────────────────────────────────────
#  The defect (pin it, so nobody "restores" it)
# ─────────────────────────────────────────────────────────────────────────

def test_legacy_tol_is_a_tautology_and_fires_at_the_min_iter_floor():
    """THE 2D defect, pinned (ledger C9).

    On a full-face outlet the legacy residual is not small — it is ZERO, by
    construction. The pp solve makes every cell divergence-free, so each plane's
    mass flux telescopes to the inlet's, and `max_j |Q_j − Q_in| / Q_in` has
    nothing left to measure. `tol` then fires at the `it >= 20` minimum-iteration
    floor and the solve stops after 20 iterations.

    If this test ever starts FAILING because the residual became meaningful,
    that is good news — but re-derive the exit criterion before celebrating.
    """
    s = _make()
    conv, n = s.solve(max_iter=3000, tol=1e-5, verbose=False)

    assert conv is True and s.exit_reason == 'tol'
    assert n == 20, (
        f"legacy exited at iteration {n}, not the min-iter floor of 20 — the "
        "tautology may no longer hold; re-read ledger C9")
    assert s.residuals[-1] < 1e-12, (
        f"legacy residual is {s.residuals[-1]:.2e} — it is supposed to be "
        "machine zero (a tautology), not merely small")


def test_f2_reaches_a_materially_better_solution_than_legacy():
    """The whole point: legacy's premature exit costs real accuracy."""
    s_leg = _make()
    s_leg.solve(max_iter=3000, tol=1e-5, verbose=False)
    dP_leg = float(np.mean(s_leg.P[:, 0]) - np.mean(s_leg.P[:, -1]))

    s_f2 = _make(convergence_mode='f2', mom_tol=1e-4,
                 mass_local_tol=1e-6, mass_global_tol=1e-6)
    conv, n = s_f2.solve(max_iter=3000, verbose=False)
    dP_f2 = float(np.mean(s_f2.P[:, 0]) - np.mean(s_f2.P[:, -1]))

    assert conv is True and s_f2.exit_reason == 'tol'
    assert n > 20, "F2 must not stop at the legacy min-iter floor"
    assert abs(dP_leg - dP_f2) / dP_f2 > 0.01, (
        f"expected legacy to be materially under-converged, but dP moved only "
        f"{abs(dP_leg - dP_f2) / dP_f2 * 100:.2f} % ({dP_leg:.1f} -> {dP_f2:.1f})")


# ─────────────────────────────────────────────────────────────────────────
#  The sync guard for the deliberate parallel assembly
# ─────────────────────────────────────────────────────────────────────────

def test_momentum_residual_vanishes_at_the_sweep_fixed_point():
    """THE sync guard. `_{u,v}_coeffs_df_2d` is a deliberate PARALLEL ASSEMBLY of
    `_sweep_{u,v}_jit_df`'s coefficient block, not a shared helper. Sweep the
    momentum equations alone (P, rho frozen, alpha_u = 1) to their own fixed
    point; the residual kernel must then read ~0. It can only do so if it
    assembles exactly the aP0/rhs the sweeps do — including the ALWAYS-ON SOU
    correction and the ALWAYS-ON VANS eps ratios (2D has no use_sou / use_eps
    flags, unlike 3D). Edit a sweep and not its twin, and this fails loudly.
    """
    s = _make()
    ii = np.arange(s.Nx)[:, None]
    jj = np.arange(s.Ny)[None, :]
    s.P[:, :] = 40.0 * (s.Ny - 1 - jj) + 2.0 * ii     # non-trivial p_src

    K2, cF2 = _K2d(s), _cF2d(s)
    kw = dict(Nx=s.Nx, Ny=s.Ny, dx_arr=s.dx_arr, dy_arr=s.dy_arr,
              rho_field=s.rho_field, mu_eff_field=s._mu_eff_field,
              K_arr=K2, cF_arr=cF2, mu_field=s.mu_field,
              eps_field=s.eps_field, alpha_u=1.0, n_sweeps=1,
              cf_aniso=s.cf_aniso)

    for _ in range(3000):
        pu, pv = s.u.copy(), s.v.copy()
        _sweep_u_jit_df(s.u, s.v, s.P, s.d_u, s.inlet_frac, s.outlet_frac, **kw)
        _sweep_v_jit_df(s.u, s.v, s.P, s.d_v, s.inlet_frac, s.v_inlet_field,
                        s.outlet_frac, **kw)
        d = max(np.abs(s.u - pu).max(), np.abs(s.v - pv).max())
        if d < 1e-14:
            break
    else:
        pytest.fail(f"momentum sweeps did not reach a fixed point (d={d:.2e})")

    nu, du, nv, dv = _mom(s)
    Ru = nu / du if du > 0 else 0.0
    Rv = nv / dv if dv > 0 else 0.0
    assert Ru < 1e-12, f"u-momentum residual did not vanish: {Ru:.3e}"
    assert Rv < 1e-12, f"v-momentum residual did not vanish: {Rv:.3e}"


def test_balanced_denominator_has_no_false_zero():
    """A component with zero velocity but a live pressure source is maximally
    unconverged. The naive Patankar denominator `sum|aP0*phi|` is 0 there, and a
    `num/den if den > 0 else 0.0` guard would report CONVERGED — a silent false
    convergence once the metric gates the exit.

    The balanced denominator `sum(0.5*(|lhs| + |rhs|))` removes the failure mode
    STRUCTURALLY: |lhs-rhs| <= |lhs|+|rhs| gives num <= 2*den, so num > 0 implies
    den > 0. The ratio is also bounded by 2.
    """
    s = _make()
    s.u[:] = 0.0
    s.v[:] = 0.0
    ii = np.arange(s.Nx)[:, None]
    s.P[:, :] = 1000.0 * ii            # gradient along x -> u-momentum p_src != 0

    nu, du, nv, dv = _mom(s)
    assert nu > 0.0, "u-momentum numerator must be nonzero (p_src != 0)"
    assert du > 0.0, (
        "BALANCED denominator must be nonzero whenever the numerator is — this "
        "is the false zero the old sum|aP0*phi| denominator produced")
    assert nu <= 2.0 * du + 1e-9, "triangle inequality num <= 2*den violated"
    Ru = nu / du
    assert Ru > 1.0, f"a quiescent component with a live source must read badly " \
                     f"unconverged, got {Ru:.3e}"
    assert Ru <= 2.0 + 1e-9, f"the balanced ratio must be bounded by 2, got {Ru}"

    rmax, rec = s._momentum_residual(s.Nx, s.Ny, s.dx_arr, s.dy_arr,
                                     _K2d(s), _cF2d(s))
    assert rmax > 0.0, "solver-level momentum residual reported a false zero"
    assert rec['num'][0] == nu and rec['den'][0] == du, \
        "raw num/den must be preserved for post-hoc re-normalisation"


# ─────────────────────────────────────────────────────────────────────────
#  Wiring
# ─────────────────────────────────────────────────────────────────────────

def test_legacy_is_the_default():
    s = _make()
    s.solve(max_iter=100, tol=1e-5, verbose=False)
    assert not hasattr(s, 'mass_local_residuals'), \
        "F2 histories must not exist unless convergence_mode='f2'"


def test_f2_exits_on_tol_with_all_three_gates_met():
    s = _make(convergence_mode='f2', mom_tol=1e-4,
              mass_local_tol=1e-6, mass_global_tol=1e-6)
    conv, n = s.solve(max_iter=3000, verbose=False)
    assert conv is True and s.exit_reason == 'tol'
    assert s.final_res_mom < 1e-4
    assert s.final_res_mass_local < 1e-6
    assert s.final_res_mass_global < 1e-6
    assert 0.0 <= s.outlet_backflow_frac <= 1.0
    assert len(s.mass_local_residuals) == n


def test_each_gate_can_hold_the_exit_open():
    """All three gates are required. 0.0 is strictly unreachable (all three
    residuals are non-negative), unlike a tiny positive number — the global mass
    residual reaches EXACTLY zero at convergence."""
    base = dict(convergence_mode='f2', mom_tol=1e-4,
                mass_local_tol=1e-6, mass_global_tol=1e-6)
    s = _make(**base)
    s.solve(max_iter=3000, verbose=False)
    assert s.exit_reason == 'tol', "precondition: the base config converges"

    for gate in ('mom_tol', 'mass_local_tol', 'mass_global_tol'):
        cfg = dict(base)
        cfg[gate] = 0.0
        s = _make(**cfg)
        conv, n = s.solve(max_iter=300, verbose=False)
        assert conv is False, f"{gate} did not hold the exit open"
        assert s.exit_reason in ('max_iter', 'stall')


def test_f2_rejects_simpler_coupling():
    """SIMPLER solves the pressure directly — a different fixed point. The
    momentum residual's "what SIMPLE drops is proportional to Pp" argument does
    not carry over unexamined, so fail loud rather than gate on it."""
    s = _make(convergence_mode='f2')
    with pytest.raises(ValueError, match="coupling"):
        s.solve(max_iter=10, coupling='simpler', verbose=False)


def test_f2_rejects_unknown_mode():
    s = _make(convergence_mode='momentum')
    with pytest.raises(ValueError, match="convergence_mode"):
        s.solve(max_iter=10, verbose=False)
