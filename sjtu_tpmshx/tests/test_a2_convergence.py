"""A2 convergence-criteria semantics (2026-07-06).

Covers the four A2 repairs:
  * 3D mass residual normalised by the inlet mass flux (``res_norm_ref``),
    so ``tol`` means "worst-cell imbalance as a fraction of throughput";
  * degenerate-inlet fallback to the absolute norm (``res_norm_ref == 1.0``);
  * ``'stall'`` early-exit reports ``converged=False`` while ``'velocity'``
    keeps reporting ``converged=True`` (2D + 3D), with ``exit_reason`` set
    on every exit path;
  * ``OuterConvergence`` AND-gates over all three tracked temperature
    fields (the wiring contract for the Ta/Tb/Ts outer gates).
"""
import warnings

warnings.filterwarnings('ignore')

import numpy as np

from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D
from sjtu_tpmshx.solvers.coupling_skeleton import OuterConvergence
from sjtu_tpmshx.solvers import _solve_common


# ── fixtures ─────────────────────────────────────────────────────────

def _solver_3d(Nx=12, Ny=10, Nz=4, v_inlet=3.0, eps=0.78,
               rho=1.0, mu=2e-5):
    K_arr = np.full((Ny, Nz), 1e-7, dtype=np.float64)
    cF_arr = np.full((Ny, Nz), 340.0, dtype=np.float64)
    return SIMPLESolver3D(
        Lx=0.1, Ly=0.04, Lz=0.02, Nx=Nx, Ny=Ny, Nz=Nz,
        rho=rho, mu=mu, T_in=350.0, v_inlet=v_inlet,
        eps=eps, K_arr=K_arr, cF_arr=cF_arr, P_ref_abs=101325.0)


def _solver_2d(v_inlet=3.0, Nx=12, Ny=20):
    return SIMPLESolver(
        W=0.042, H=0.06, Nx=Nx, Ny=Ny,
        tpms_type='Gyroid', L_cell_mm=7.0, t_mm=0.6, eps=0.6, r_h=1e-3,
        rho=1.2, mu=1.8e-5, T_in=322.0,
        inlet_lo=0.0, inlet_hi=0.042, v_inlet=v_inlet,
        fluid_type='incompressible', wall_refine=False)


# ── 3D residual normalisation ────────────────────────────────────────

def test_res_norm_ref_matches_inlet_flux():
    """res_norm_ref must equal Σ ε·ρ·|v_in|·dA over the j=0 inlet face."""
    s = _solver_3d()
    s.solve(max_iter=15, tol=0.0)   # tol=0 → never strict-exits
    rho_eps = s.rho_field * s.eps_field
    expected = float(np.sum(rho_eps[:, 0, :] * np.abs(s.v[:, 0, :])
                            * s.dx[:, None] * s.dz[None, :]))
    assert expected > 0.0
    # stored ref is the per-iteration snapshot; the post-solve recompute
    # differs by the density drift of the final iteration (~1e-4 relative)
    assert abs(s.res_norm_ref - expected) / expected < 1e-3, \
        f"res_norm_ref {s.res_norm_ref} != inlet flux {expected}"
    # residual history is dimensionless now — final entry matches final_res
    assert s.final_res == s.residuals[-1]
    print(f"test_res_norm_ref_matches_inlet_flux PASS "
          f"(ref={s.res_norm_ref:.4e} kg/s)")


def test_res_norm_fallback_absolute_on_no_flow():
    """Zero-inlet solve keeps the absolute norm (ref falls back to 1.0)."""
    s = _solver_3d(v_inlet=0.0)
    s.solve(max_iter=5, tol=0.0)
    assert s.res_norm_ref == 1.0, s.res_norm_ref
    print("test_res_norm_fallback_absolute_on_no_flow PASS")


def test_residual_scale_invariance():
    """Quadrupling ṁ must not change the normalised residual's meaning.

    Measured normalised ratio is ~0.35 (the two flows' physical residual
    trajectories genuinely differ ~3x). If the normalisation regressed to
    the old absolute norm, the ratio would gain the throughput factor 4:
    0.35 * 4 = ~1.4. The band's upper bound must therefore sit BELOW 1.4 —
    the original 0.1..10 band let the exact regression this test guards
    against pass through its middle (blind-spot audit T3, 2026-07-07)."""
    hist = {}
    for v in (1.0, 4.0):
        s = _solver_3d(v_inlet=v)
        s.lowre_early_exit = False   # full 30 iters for both trajectories
        s.solve(max_iter=30, tol=0.0)
        hist[v] = np.asarray(s.residuals[5:30])
    ratio = np.median(hist[4.0] / hist[1.0])
    assert 0.12 < ratio < 1.0, \
        f"normalised residuals not scale-invariant: median ratio {ratio:.3e}"
    print(f"test_residual_scale_invariance PASS (median ratio {ratio:.2f})")


# ── exit_reason semantics ────────────────────────────────────────────

def test_stall_reports_not_converged_3d(monkeypatch):
    monkeypatch.setattr(_solve_common.LowReExit, 'check',
                        lambda self, vels, res, it: 'stall')
    s = _solver_3d()
    conv, it = s.solve(max_iter=50, tol=0.0)
    assert conv is False and s.exit_reason == 'stall', \
        (conv, s.exit_reason)
    print("test_stall_reports_not_converged_3d PASS")


def test_velocity_reports_converged_3d(monkeypatch):
    monkeypatch.setattr(_solve_common.LowReExit, 'check',
                        lambda self, vels, res, it: 'velocity')
    s = _solver_3d()
    conv, it = s.solve(max_iter=50, tol=0.0)
    assert conv is True and s.exit_reason == 'velocity', \
        (conv, s.exit_reason)
    print("test_velocity_reports_converged_3d PASS")


def test_stall_reports_not_converged_2d(monkeypatch):
    monkeypatch.setattr(_solve_common.LowReExit, 'check',
                        lambda self, vels, res, it: 'stall')
    s = _solver_2d()
    conv, it = s.solve(max_iter=60, tol=0.0)
    assert conv is False and s.exit_reason == 'stall', \
        (conv, s.exit_reason)
    print("test_stall_reports_not_converged_2d PASS")


def test_velocity_reports_converged_2d(monkeypatch):
    monkeypatch.setattr(_solve_common.LowReExit, 'check',
                        lambda self, vels, res, it: 'velocity')
    s = _solver_2d()
    conv, it = s.solve(max_iter=60, tol=0.0)
    assert conv is True and s.exit_reason == 'velocity', \
        (conv, s.exit_reason)
    print("test_velocity_reports_converged_2d PASS")


def test_exit_reason_on_strict_and_max_iter_3d():
    # generous tol → strict or velocity exit, both converged
    s = _solver_3d()
    conv, _ = s.solve(max_iter=500, tol=1e-3)
    assert conv is True and s.exit_reason in ('tol', 'velocity'), \
        (conv, s.exit_reason)
    # impossible tol + early-exit disabled → max_iter, not converged
    s2 = _solver_3d()
    s2.lowre_early_exit = False
    conv2, it2 = s2.solve(max_iter=12, tol=0.0)
    assert conv2 is False and s2.exit_reason == 'max_iter' and it2 == 12, \
        (conv2, s2.exit_reason, it2)
    print("test_exit_reason_on_strict_and_max_iter_3d PASS")


# ── outer-gate wiring contract ───────────────────────────────────────

def test_outer_convergence_gates_all_three_fields():
    oc = OuterConvergence(tol_T=0.5, track=('Ta', 'Tb', 'Ts'))
    Ta = np.full((4, 4), 300.0)
    Tb = np.full((4, 4), 320.0)
    Ts = np.full((4, 4), 310.0)
    conv, d = oc.check({'Ta': Ta, 'Tb': Tb, 'Ts': Ts})
    assert not conv and all(np.isinf(v) for v in d.values())   # first iter
    conv, d = oc.check({'Ta': Ta, 'Tb': Tb, 'Ts': Ts})
    assert conv and max(d.values()) == 0.0                     # all static
    # only the SOLID moves → gate must hold the loop open
    conv, d = oc.check({'Ta': Ta, 'Tb': Tb, 'Ts': Ts + 1.0})
    assert not conv and d['Ts'] == 1.0 and d['Ta'] == 0.0, d
    print("test_outer_convergence_gates_all_three_fields PASS")


if __name__ == '__main__':
    test_res_norm_ref_matches_inlet_flux()
    test_res_norm_fallback_absolute_on_no_flow()
    test_residual_scale_invariance()
    test_exit_reason_on_strict_and_max_iter_3d()
    test_outer_convergence_gates_all_three_fields()
    print("ALL DIRECT-RUN TESTS PASS (monkeypatch tests need pytest)")
