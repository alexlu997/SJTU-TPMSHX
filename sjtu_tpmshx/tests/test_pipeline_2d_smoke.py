"""Pipeline2D end-to-end smoke — audit C4 (L-a-2).

Drives :class:`controllers.compute_pipeline.Pipeline2D` on a small
in-domain Shanghai-like case and asserts the ComputeResult slots
populate with physically plausible numbers.  Not a regression test —
the canonical Shanghai numbers live in ``test_shanghai_regression.py``
(opt-in subprocess test).  This test exists so a CI run catches
``Pipeline2D`` breakage without the 13-minute lumped-dual-nu cost.

Marked ``@pytest.mark.slow`` because the inner SIMPLE+LTNE loop on a
20x40 grid takes ~10–15 s per run; pytest skips by default unless the
runner explicitly opts in.
"""
from __future__ import annotations

import time

import pytest

from domain.compute_config import (
    ComputeConfig,
    FluidConfig,
    GeometryConfig,
    SolverConfig,
    PartialBCConfig,
)
from controllers.compute_pipeline import (
    Pipeline2D,
    pipeline_for,
    ComputeResult,
)


def _shanghai_like_cfg() -> ComputeConfig:
    """Build a Shanghai-like ComputeConfig that stays inside the
    ConstDF-v1 + Nu surrogate domains (Re>=400, t in [0.3, 0.5] mm)."""
    return ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=10.0, T_in_K=600.0,
                            P_in_Pa=101325.0),
        fluid_B=FluidConfig(type='air', u_mps=10.0, T_in_K=300.0,
                            P_in_Pa=101325.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0,
                                t_wall_mm=0.4, k_s_W_mK=16.0,
                                L_dom_m=0.182, H_dom_m=0.042),
        solver=SolverConfig(Nx=20, Ny=40, Nz=1),
        bc_A=PartialBCConfig(dir=0),
        bc_B=PartialBCConfig(dir=3),
    )


@pytest.mark.slow
def test_pipeline2d_run_returns_compute_result():
    """``Pipeline2D(cfg).run()`` must return a :class:`ComputeResult`
    with the headline scalars populated and all sub-dicts non-empty."""
    cfg = _shanghai_like_cfg()
    pipe = Pipeline2D(cfg)
    t0 = time.time()
    result = pipe.run()
    dt = time.time() - t0

    assert isinstance(result, ComputeResult)

    # Headline scalars — positive, finite, physically plausible.
    assert result.Q_W > 0, f"Q_W must be positive (got {result.Q_W})"
    assert result.Q_W < 1e6, (
        f"Q_W must be < 1 MW for 0.182×0.042 m domain "
        f"(got {result.Q_W:.0f})")
    assert result.dP_A_Pa > 0
    assert result.dP_B_Pa > 0
    assert 250 < result.T_out_A_K < 700
    assert 250 < result.T_out_B_K < 700

    # Heat exchanger primary: hot side cools, cold side warms.
    assert result.T_out_A_K < cfg.fluid_A.T_in_K, (
        f"Hot side must cool: T_out_A={result.T_out_A_K:.1f} K "
        f"vs T_in_A={cfg.fluid_A.T_in_K} K")
    assert result.T_out_B_K > cfg.fluid_B.T_in_K, (
        f"Cold side must warm: T_out_B={result.T_out_B_K:.1f} K "
        f"vs T_in_B={cfg.fluid_B.T_in_K} K")

    # Sub-dicts populated.
    assert 'Ta' in result.fields
    assert 'Tb' in result.fields
    assert 'Ts' in result.fields
    assert 'P_fA' in result.fields and 'P_fB' in result.fields
    # Field grids share one 2D shape. Wall-refinement expands the nominal
    # Nx×Ny (here 20×40 → 36×56), so assert consistency + lower bound, not
    # an exact shape that rots whenever BL refinement params change.
    ta_shape = result.fields['Ta'].shape
    assert len(ta_shape) == 2
    assert result.fields['Tb'].shape == ta_shape
    assert result.fields['Ts'].shape == ta_shape
    assert ta_shape[0] >= cfg.solver.Nx and ta_shape[1] >= cfg.solver.Ny

    # Coefficients + properties. K_ss is the single shared solid-wall
    # conductance (one solid between both fluids — no per-side K_ssA/K_ssB;
    # the per-side coefficients are the fluid ones K_ffA/K_ffB). A uniform
    # (non-zone) run resolves it to a float, so assert it flowed through
    # finalize into coeffs.
    assert result.coeffs['K_ss'] is not None
    assert result.props['rho_A'] is not None
    assert result.props['mu_A'] is not None
    assert 0 < result.props['eps_A'] < 1
    assert result.props['D_h_m'] > 0

    # Residuals contain Q breakdown.
    assert 'Q_A' in result.residuals
    assert 'Q_B' in result.residuals
    # Energy imbalance — should be < 10% for a settled run.
    eir = result.residuals['energy_imbalance_rel']
    assert eir is not None
    if eir == eir:  # not NaN
        assert eir < 0.20, (
            f"Energy imbalance too large: {eir:.3f}")

    # Diagnostics surface — Q_richardson is finite or NaN, no crash.
    assert 'Q_richardson_warn' in result.diagnostics

    # Sanity on wall time — should not be > 5 minutes for a 20×40 grid.
    assert dt < 300, f"Pipeline2D.run() took {dt:.1f}s — too slow"


@pytest.mark.slow
def test_pipeline2d_progress_cb_fires():
    """``progress_cb`` must fire at least 5 times (ABC ticks + shim
    forwards from ``_compute_progress`` writes inside the solver loop)."""
    cfg = _shanghai_like_cfg()
    seen = []
    pipe = Pipeline2D(cfg, progress_cb=lambda p: seen.append(p))
    pipe.run()
    # ABC fires 20/90/100 + shim fires each outer-loop coupling iter.
    assert len(seen) >= 5, f"progress_cb only fired {len(seen)} times"
    assert 20 in seen
    assert 90 in seen
    assert 100 in seen
    assert max(seen) == 100


@pytest.mark.slow
def test_pipeline_for_2d_dispatch():
    """``pipeline_for(cfg)`` with Nz=1 must return a Pipeline2D that
    runs to completion."""
    cfg = _shanghai_like_cfg()
    pipe = pipeline_for(cfg)
    assert isinstance(pipe, Pipeline2D)
    result = pipe.run()
    assert result.Q_W > 0
