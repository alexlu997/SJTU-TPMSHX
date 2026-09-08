"""F2 convergence mode for the 3D SIMPLE solver (ledger C6 / C7).

`convergence_mode='f2'` replaces the legacy exit — `tol` on a mass residual that
ledger C6 showed to be an outlet-pin artifact, plus LowReExit's velocity
criterion — with three independent gates (momentum, solved-cell mass, global
boundary mass), each with its own tolerance, confirmed over consecutive checks.

The load-bearing test is `test_velocity_static_does_not_terminate`. It encodes
the single thing that was wrong with the first F2 design (caught in codex
review): LowReExit TERMINATES on a static velocity field, at a momentum residual
of 1.8e-3..1.5e-2 with the residual still falling. Simply flipping its verdict to
converged=False would have turned a premature SUCCESS into a premature FAILURE —
the solve would still stop at ~90 iterations and never reach the real gate. In
F2 a static field only TRIGGERS a check.
"""
import numpy as np
import pytest

from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D


def _make_solver(Nx=8, Ny=12, Nz=4, v_inlet=3.0, **kw):
    K = np.full((Ny, Nz), 3.0e-8)
    cF = np.full((Ny, Nz), 250.0)
    s = SIMPLESolver3D(
        Lx=0.02, Ly=0.03, Lz=0.01, Nx=Nx, Ny=Ny, Nz=Nz,
        rho=1.18, mu=1.85e-5, T_in=300.0, v_inlet=v_inlet,
        eps=0.72, K_arr=K, cF_arr=cF, fluid_type='ideal_gas')
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_legacy_is_the_default():
    """The SOLVER CLASS default stays 'legacy' — deliberately, even though F2
    is now priced (reports/f2_pricing_3d.csv), re-baselined, and the PIPELINE
    default (run_stack_3d / stages_2d resolve env > cfg > 'f2'). The class
    default is what kernel-direct callers (tests, diagnostics, the optimizer
    evaluator per ledger O2/R3) get without opting in; flipping it would
    silently change every one of them. If you flip it intentionally, this
    test is the loud part — re-derive the optimizer cost (measured 1.74x at
    mom_tol=1e-3) first."""
    s = _make_solver()
    s.solve(max_iter=30, tol=1e-12)
    assert not hasattr(s, 'mass_local_residuals'), \
        "F2 histories must not exist unless convergence_mode='f2'"
    assert s.exit_reason in ('tol', 'velocity', 'stall', 'max_iter')


def test_f2_exits_on_tol_with_all_three_gates_met():
    s = _make_solver(convergence_mode='f2', mom_tol=1e-4,
                     mass_local_tol=1e-6, mass_global_tol=1e-6)
    conv, n = s.solve(max_iter=3000, verbose=False)

    assert conv is True
    assert s.exit_reason == 'tol', \
        f"F2 must exit on the residual gate, got {s.exit_reason!r}"
    assert s.final_res_mom < 1e-4
    assert s.final_res_mass_local < 1e-6
    assert s.final_res_mass_global < 1e-6
    # Keep the separate legacy mass diagnostic; local outlet closure need not
    # leave its historical boundary-artifact floor.
    assert len(s.residuals) == n
    assert np.isfinite(s.final_res)


def test_velocity_static_does_not_terminate():
    """F2 must continue past a legacy mass-only or static-velocity exit and
    reach a materially lower momentum residual.
    """
    s_leg = _make_solver()
    s_leg.track_momentum_residual = True
    conv_leg, n_leg = s_leg.solve(max_iter=3000, tol=1e-12)
    assert s_leg.exit_reason in ('tol', 'velocity'), \
        "legacy can now reach its mass-only tol after local outlet closure"
    mom_leg = s_leg.mom_residuals[-1]['max']

    s_f2 = _make_solver(convergence_mode='f2', mom_tol=1e-4,
                        mass_local_tol=1e-6, mass_global_tol=1e-6)
    conv_f2, n_f2 = s_f2.solve(max_iter=3000)

    assert conv_f2 and s_f2.exit_reason == 'tol'
    assert n_f2 > n_leg, (
        f"F2 stopped no later than the velocity criterion ({n_f2} <= {n_leg}) — "
        "it is still terminating on a static field, not on the residual gate")
    assert s_f2.final_res_mom < mom_leg / 10.0, (
        f"F2 exited at momentum residual {s_f2.final_res_mom:.2e}, barely better "
        f"than the legacy exit's {mom_leg:.2e}")


def test_f2_rejects_anderson():
    """Anderson mutates u/v/w/P/rho after the Picard step, gates its candidate on
    the C6-falsified mass artifact, and its rollback does not restore rho_field
    exactly. None of that is compatible with a residual-gated exit — fail loud
    rather than silently produce a residual that describes a discarded state."""
    s = _make_solver(convergence_mode='f2', use_anderson=True)
    with pytest.raises(ValueError, match="use_anderson"):
        s.solve(max_iter=10)


def test_f2_rejects_unknown_mode():
    s = _make_solver(convergence_mode='momentum')
    with pytest.raises(ValueError, match="convergence_mode"):
        s.solve(max_iter=10)


def test_each_gate_can_hold_the_exit_open():
    """All three gates are required. Driving any ONE of them to an unreachable
    tolerance must prevent the 'tol' exit — otherwise that gate is decorative.

    The unreachable value is 0.0, not a tiny number. All three residuals are
    non-negative, so `R < 0.0` is strictly impossible — whereas `R < 1e-30` is
    NOT: the global mass residual reaches EXACTLY zero at convergence (the
    outlet BC extrapolates a conserved eps*rho*v and the pp solve makes the
    interior telescope, so mdot_out == mdot_in bit-for-bit). A first draft of
    this test used 1e-30 and the global gate passed it legitimately — the
    residual really was zero, and the test was wrong, not the gate.
    """
    base = dict(convergence_mode='f2', mom_tol=1e-4,
                mass_local_tol=1e-6, mass_global_tol=1e-6)
    s = _make_solver(**base)
    s.solve(max_iter=1500)
    assert s.exit_reason == 'tol', "precondition: the base config converges"
    n_base = len(s.residuals)

    for gate in ('mom_tol', 'mass_local_tol', 'mass_global_tol'):
        cfg = dict(base)
        cfg[gate] = 0.0                        # strictly unreachable (R >= 0)
        s = _make_solver(**cfg)
        conv, n = s.solve(max_iter=400)
        assert conv is False, f"{gate} did not hold the exit open"
        assert s.exit_reason in ('max_iter', 'stall'), \
            f"{gate}: unexpected exit {s.exit_reason!r}"

    # Fourth gate (2026-07-13): outlet backflow. backflow_frac >= 0 always,
    # so a threshold of -1.0 is strictly unreachable — same pattern as the
    # 0.0 tolerances above. (The default 0.01 is inert on every measured
    # baseline: backflow is exactly 0 there.)
    cfg = dict(base)
    cfg['f2_backflow_max'] = -1.0
    s = _make_solver(**cfg)
    conv, n = s.solve(max_iter=400)
    assert conv is False, "f2_backflow_max did not hold the exit open"
    assert s.exit_reason in ('max_iter', 'stall'), \
        f"f2_backflow_max: unexpected exit {s.exit_reason!r}"

    # And each gate is load-bearing in the ordinary regime too: tightening it
    # (without making it impossible) must delay the exit, not be ignored.
    for gate, tight in (('mom_tol', 1e-9),
                        ('mass_local_tol', 1e-12),
                        ('mass_global_tol', 1e-30)):
        cfg = dict(base)
        cfg[gate] = tight
        s = _make_solver(**cfg)
        s.solve(max_iter=1500)
        assert len(s.residuals) > n_base, (
            f"tightening {gate} from {base[gate]:g} to {tight:g} did not delay "
            f"the exit ({len(s.residuals)} vs {n_base}) — the gate is being "
            "ignored")


def test_n_confirm_requires_consecutive_passes():
    """A single lucky iterate is not convergence. With n_confirm=1 the solve may
    stop on the first passing check; with n_confirm=3 it must take at least two
    more checks."""
    kw = dict(convergence_mode='f2', mom_tol=1e-4,
              mass_local_tol=1e-6, mass_global_tol=1e-6)
    s1 = _make_solver(f2_n_confirm=1, **kw)
    s1.solve(max_iter=3000)
    s3 = _make_solver(f2_n_confirm=3, **kw)
    s3.solve(max_iter=3000)

    assert s1.exit_reason == s3.exit_reason == 'tol'
    assert len(s3.residuals) >= len(s1.residuals) + 2, (
        f"n_confirm=3 exited after {len(s3.residuals)} iters vs "
        f"{len(s1.residuals)} for n_confirm=1 — the confirm streak is not "
        "actually being required")


def test_mom_every_does_not_change_the_answer():
    """The momentum residual is READ-ONLY, so evaluating it every iteration or
    every 5 must land on the same solution — the schedule can only shift WHEN we
    notice convergence, never what we converge to. Worst case: exiting up to
    (mom_every - 1) iterations late."""
    kw = dict(convergence_mode='f2', mom_tol=1e-4,
              mass_local_tol=1e-6, mass_global_tol=1e-6)
    s1 = _make_solver(f2_mom_every=1, **kw)
    s1.solve(max_iter=3000)
    s5 = _make_solver(f2_mom_every=5, **kw)
    s5.solve(max_iter=3000)

    assert s1.exit_reason == s5.exit_reason == 'tol'
    assert abs(len(s5.residuals) - len(s1.residuals)) <= 5
    # Same fixed point, to well inside the gate tolerance.
    for a, b in ((s1.u, s5.u), (s1.v, s5.v), (s1.w, s5.w)):
        scale = max(float(np.abs(a).max()), 1e-30)
        assert float(np.abs(a - b).max()) / scale < 1e-3


def test_backflow_fraction_is_reported():
    """The global mass gate is a single signed scalar: positive and negative
    outlet fluxes can cancel inside it and hide a recirculating outlet. The
    backflow fraction must be exposed alongside so that cancellation is visible.
    """
    s = _make_solver(convergence_mode='f2')
    s.solve(max_iter=1500)
    assert hasattr(s, 'outlet_backflow_frac')
    assert 0.0 <= s.outlet_backflow_frac <= 1.0
    assert s.outlet_backflow_frac == pytest.approx(0.0, abs=1e-12), \
        "a healthy forward outflow must show no backflow"


def test_solved_cell_mass_excludes_the_dirichlet_outlet_row():
    """The solved-cell mass residual must select on `cell_kind`, not on a row
    index: a partial / tapered outlet pins only SOME cells of the last row, and
    the unpinned ones DO have a continuity equation that must be counted."""
    from sjtu_tpmshx.solvers._kernels_simple_3d import _mass_res_solved_jit_3d
    s = _make_solver(convergence_mode='f2')
    # Block half the outlet face -> those cells are walls, not Dirichlet pins.
    frac = np.ones((s.Nx, s.Nz))
    frac[: s.Nx // 2, :] = 0.0
    s.outlet_frac = frac                     # property setter rebuilds the mask
    s.solve(max_iter=800)

    kind = s._pp_sparsity['cell_kind']
    n_pinned = int((kind == 1).sum())
    assert n_pinned == int(s.outlet_mask_ij.sum()), \
        "only the OPEN outlet cells may be pinned"
    assert n_pinned < s.Nx * s.Nz, "precondition: this is a partial outlet"

    rho_eps = np.ascontiguousarray(s.rho_field * s.eps_field)
    _, n_counted = _mass_res_solved_jit_3d(
        s.u, s.v, s.w, s.Nx, s.Ny, s.Nz, s.dx, s.dy, s.dz, rho_eps, kind)
    assert n_counted <= s.Nx * s.Ny * s.Nz - n_pinned
    # The blocked half of the last row is a WALL cell: still solved, still counted.
    assert n_counted > (s.Nx * s.Ny * s.Nz) - n_pinned - s.Nx * s.Nz


def _small_f2(dim):
    if dim == 2:
        from sjtu_tpmshx.tests.test_f2_convergence_2d import _make
        return _make(Nx=4, Ny=4, convergence_mode='f2')
    return _make_solver(Nx=4, Ny=4, Nz=3, convergence_mode='f2',
                        use_coarse_bootstrap=False)


def _solver_module(dim):
    from sjtu_tpmshx.solvers import simple_solver, simple_solver_3d
    return simple_solver if dim == 2 else simple_solver_3d


@pytest.mark.parametrize('dim,field', [
    (dim, field) for dim in (2, 3)
    for field in ('u', 'v', 'P', 'rho_field', 'T_field') + (('w',) if dim == 3 else ())])
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
@pytest.mark.parametrize('stage', ['entry', 'iteration'])
def test_nonfinite_actual_state_cannot_be_certified(monkeypatch, dim, field, bad, stage):
    s = _small_f2(dim)
    closed = []
    if dim == 2:
        monkeypatch.setattr(s, '_enforce_mass_conservation', lambda **kw: closed.append(True))

    def corrupt():
        getattr(s, field).flat[0] = bad

    if stage == 'entry':
        corrupt()
        # Entry rejection must precede kernels, including the optional 3D bootstrap.
        def forbidden(*args, **kwargs):
            pytest.fail('invalid F2 input reached a solver kernel/bootstrap')
        module = _solver_module(dim)
        monkeypatch.setattr(module, '_sweep_u_jit_df' if dim == 2 else '_sweep_u_jit_df_3d', forbidden)
        if dim == 3:
            from sjtu_tpmshx.solvers import coarse_bootstrap_3d
            s.use_coarse_bootstrap = True
            monkeypatch.setattr(coarse_bootstrap_3d, 'bootstrap_simple_3d', forbidden)
    else:
        original = s._update_density

        def update():
            original()
            corrupt()

        monkeypatch.setattr(s, '_update_density', update)
    assert s.solve(max_iter=1, verbose=False) == (False, 0 if stage == 'entry' else 1)
    assert s.exit_reason == 'nonfinite'
    if dim == 2:
        assert s.f2_cert_post_rescale_ok is False
        assert not closed


@pytest.mark.parametrize('dim', [2, 3])
@pytest.mark.parametrize('index', range(5))
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_nonfinite_scalar_breaks_confirmation(dim, index, bad):
    from types import SimpleNamespace
    from sjtu_tpmshx.solvers._solve_common import F2Monitor
    monitor = F2Monitor(SimpleNamespace(), (np.zeros(2),)*dim, min_iter=0)
    assert monitor.submit(1, 0., 0., 0., 0., 0.) is None
    values = [0.]*5
    values[index] = bad
    assert monitor.submit(2, *values) == 'nonfinite'
    assert monitor.submit(3, 0., 0., 0., 0., 0.) is None
    assert monitor.submit(4, 0., 0., 0., 0., 0.) == 'tol'


@pytest.mark.parametrize('dim,index', [(dim, i) for dim in (2, 3) for i in range(2*dim)])
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_nonfinite_momentum_raw_is_not_a_zero(monkeypatch, dim, index, bad):
    s = _small_f2(dim)
    raw = [0., 1.]*dim
    raw[index] = bad
    monkeypatch.setattr(_solver_module(dim), f'_mom_res_jit_{dim}d', lambda *a: tuple(raw))
    if dim == 2:
        value, record = s._momentum_residual(s.Nx, s.Ny, s.dx_arr, s.dy_arr, None, None)
    else:
        value, record = s._momentum_residual(s.Nx, s.Ny, s.Nz, s.dx, s.dy, s.dz, 0, 0)
    assert not np.isfinite(value)
    np.testing.assert_equal(record['num'], raw[::2])
    np.testing.assert_equal(record['den'], raw[1::2])


@pytest.mark.parametrize('dim', [2, 3])
@pytest.mark.parametrize('index', range(3))
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_nonfinite_global_flux_stops_before_momentum_schedule(monkeypatch, dim, index, bad):
    s = _small_f2(dim)
    raw = [1., 1., 0.]
    raw[index] = bad
    monkeypatch.setattr(_solver_module(dim), f'_mass_global_jit_{dim}d', lambda *a: tuple(raw))
    assert s.solve(max_iter=1, verbose=False) == (False, 1)
    assert s.exit_reason == 'nonfinite'
    assert s.mom_residuals == []  # Do not force an unscheduled momentum assembly.


@pytest.mark.parametrize('field', ['u', 'v', 'P', 'rho_field', 'T_field'])
@pytest.mark.parametrize('reason', ['tol', 'stall', None])
def test_nonfinite_after_2d_closeout_cannot_be_certified(monkeypatch, field, reason):
    s = _small_f2(2)
    module = _solver_module(2)
    monkeypatch.setattr(module.F2Monitor, 'should_eval_momentum', lambda *a: True)
    monkeypatch.setattr(module.F2Monitor, 'submit', lambda *a: reason)
    monkeypatch.setattr(s, '_momentum_residual', lambda *a: (0., {}))
    monkeypatch.setattr(module, '_mass_res_solved_jit_2d', lambda *a: (0., 1))
    monkeypatch.setattr(module, '_mass_global_jit_2d', lambda *a: (1., 1., 0.))

    def close(**kwargs):
        getattr(s, field).flat[-1] = np.nan

    monkeypatch.setattr(s, '_enforce_mass_conservation', close)
    assert s.solve(max_iter=1, verbose=False) == (False, 1)
    assert s.exit_reason == 'nonfinite'
    assert s.f2_cert_post_rescale_ok is False


@pytest.mark.parametrize('dim', [2, 3])
@pytest.mark.parametrize('mode', ['unknown', 'unsupported'])
def test_nonfinite_does_not_hide_configuration_error(dim, mode):
    s = _small_f2(dim)
    s.P.flat[0] = np.nan
    options = {}
    if mode == 'unknown':
        s.convergence_mode = 'invalid'
    elif dim == 2:
        options['coupling'] = 'simpler'
    else:
        s.use_anderson = True
    with pytest.raises(ValueError, match='convergence_mode|coupling|use_anderson'):
        s.solve(max_iter=1, verbose=False, **options)


@pytest.mark.parametrize('dim', [2, 3])
def test_nonfinite_input_preserves_cancellation(dim):
    from sjtu_tpmshx.domain.cancellation import CancelledError
    s = _small_f2(dim)
    s.P.flat[0] = np.nan
    with pytest.raises(CancelledError):
        s.solve(max_iter=1, verbose=False, cancel_check=lambda: True)


@pytest.mark.parametrize('dim', [2, 3])
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_nonfinite_momentum_observation_exits_solver(monkeypatch, dim, bad):
    s = _small_f2(dim)
    s.track_momentum_residual = True
    module = _solver_module(dim)
    monkeypatch.setattr(module.F2Monitor, 'should_eval_momentum', lambda *a: True)
    raw = (bad, 1.) * dim
    monkeypatch.setattr(module, f'_mom_res_jit_{dim}d', lambda *a: raw)
    assert s.solve(max_iter=1, verbose=False) == (False, 1)
    assert s.exit_reason == 'nonfinite'
    np.testing.assert_equal(s.mom_residuals[-1]['num'], raw[::2])


@pytest.mark.parametrize('metric', ['mom', 'local', 'global', 'backflow'])
def test_nonfinite_post_closeout_observation_rejects_2d(monkeypatch, metric):
    s = _small_f2(2)
    module = _solver_module(2)
    monkeypatch.setattr(module.F2Monitor, 'should_eval_momentum', lambda *a: True)
    monkeypatch.setattr(module.F2Monitor, 'submit', lambda *a: 'tol')
    mom = iter([0., np.nan if metric == 'mom' else 0.])
    local = iter([0., np.nan if metric == 'local' else 0.])
    fluxes = iter([(1., 1., 0.),
                   (1., np.nan if metric == 'global' else 1.,
                    np.nan if metric == 'backflow' else 0.)])
    monkeypatch.setattr(s, '_momentum_residual', lambda *a: (next(mom), {}))
    monkeypatch.setattr(module, '_mass_res_solved_jit_2d', lambda *a: (next(local), 1))
    monkeypatch.setattr(module, '_mass_global_jit_2d', lambda *a: next(fluxes))
    assert s.solve(max_iter=1, verbose=False) == (False, 1)
    assert s.exit_reason == 'nonfinite'
    assert s.f2_cert_post_rescale_ok is False


def test_nonfinite_exit_is_rejected_by_3d_result_consumer(monkeypatch):
    from sjtu_tpmshx.tests.test_convergence_truth_table import _cheap_3d, _run_3d_stack
    original = SIMPLESolver3D.solve

    def failed(self, *args, **kwargs):
        # Keep the existing finite flow; isolate the returned status only.
        _, iterations = original(self, *args, **kwargs)
        self.exit_reason = 'nonfinite'
        return False, iterations

    monkeypatch.setattr(SIMPLESolver3D, 'solve', failed)
    result = _run_3d_stack(_cheap_3d())
    detail = result['convergence_detail']
    assert detail['simple_exit_A'] == 'nonfinite'
    assert detail['simple_ok'] is False
    assert result['solver_converged'] is False


def test_nonfinite_bootstrap_return_is_rejected_before_main_iteration(monkeypatch):
    from sjtu_tpmshx.solvers import coarse_bootstrap_3d
    s = _small_f2(3)
    s.use_coarse_bootstrap = True

    def bootstrap(solver, **kwargs):
        solver.P.flat[0] = np.nan
        return {'applied': False}

    def forbidden(*args, **kwargs):
        pytest.fail('invalid bootstrap return reached the main sweep')

    monkeypatch.setattr(coarse_bootstrap_3d, 'bootstrap_simple_3d', bootstrap)
    monkeypatch.setattr(_solver_module(3), '_sweep_u_jit_df_3d', forbidden)
    assert s.solve(max_iter=1, verbose=False) == (False, 0)
    assert s.exit_reason == 'nonfinite'
