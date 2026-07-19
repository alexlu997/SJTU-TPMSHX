"""core/evaluators.py — neutral-layer 3D design evaluator.

Physical definitions of the 3D evaluator live here (moved from
``validation/cases/verify_pareto_3d`` as part of audit M4 deep refactor,
2026-05-28). Both ``optimization/evaluator_3d`` (BO worker) and
``validation/cases/verify_pareto_3d`` (CLI verification) import from this
neutral layer, so the import direction is no longer
``optimization -> validation`` (which violated layering rules and
forced the BO worker to drag a CLI script into its dependency graph).

Public API
----------
``evaluate_3d(x, cfg, **kwargs) -> dict``
    Run the 3D LTNE evaluator on a single decision vector. Returns a
    dict with keys ``Q_3D_W``, ``dP_A_Pa``, ``dP_B_Pa``, ``dP_total_Pa``,
    ``mass_kg``, plus ``invalid`` / ``invalid_reason`` on infeasible
    (P_out**2 <= 0) inputs.

``_build_3d_arrays(fc, Nx, Ny, Nz, ...) -> dict``
    Per-voxel arrays (eps, K_ffA/B, K_ss, h_vA/B, A_0, eps_A) built by
    extruding a 2D continuous field along z. Used by ``evaluate_3d``
    and exposed for callers that need to drive the underlying solver
    stack with custom outer-loop logic.
"""
from __future__ import annotations

import time
import numpy as np

# xmod-eps-field-3d-evaluator (audit 2026-06-26): CLOSED by M2b (2026-07-09) —
# evaluate_3d now installs the per-cell eps_field on both SIMPLE-3D instances
# (see the solver-construction block), so graded designs are exact instead of
# mean-ε approximate. The one-shot warning guard that lived here is retired.

from solvers.tpms_calc import (
    air_density,
    air_viscosity,
    air_cp,
)
from solvers.simple_solver_3d import SIMPLESolver3D
from solvers.ltne_energy_3d import solve_full_domain_3d
from solvers.df_projection import (
    project_fields_to_streamwise_K_cF_3d,
)
from solvers.continuous_field import from_decision_vector
from solvers.envelope import R_AIR_DEFAULT, predict_outlet_p_sq
from logutil import get_logger

_log = get_logger(__name__)


# Re-exported for verify_pareto_3d et al.; the value lives in solvers/envelope
# (single authority for the 1D compressible D-F seed — P1.3, was a local copy).
R_AIR = R_AIR_DEFAULT


__all__ = ["evaluate_3d", "_build_3d_arrays", "R_AIR"]



# ─── 3D field construction (extrude 2D field along z) ───────────────


def _build_3d_arrays(fc, Nx: int, Ny: int, Nz: int,
                     u_A: float, u_B: float,
                     T_inA: float, T_inB: float,
                     P_inA: float, k_s: float,
                     tpms_type: str,
                     quant_L: float = 0.05,
                     quant_t: float = 0.01) -> dict:
    """Per-voxel arrays (eps, K_ffA/B, K_ss, h_vA/B, A_0, eps_A) of shape
    (Nx, Ny, Nz). 2D field extruded uniformly along z.
    """
    L_field_2D, t_field_2D = fc.evaluate_grid(Nx, Ny)

    # Quantized (L, t) → unique-pair scatter, shared with the 2D builder
    # (B3 C7: solvers.continuous_field.props_from_Lt_fields). Replaces the
    # former per-cell dict-cache loop; the quantization key moved from
    # Python round() to np.round (round-half-even, agrees on the
    # 0.05/0.01-quantized grid). Result is z-broadcast below.
    from solvers.continuous_field import props_from_Lt_fields
    p = props_from_Lt_fields(L_field_2D, t_field_2D, tpms_type, k_s,
                             u_A, u_B, T_inA, T_inB, P_inA,
                             quant_L=quant_L, quant_t=quant_t)

    L_field_3D = np.broadcast_to(L_field_2D[:, :, None], (Nx, Ny, Nz)).copy()
    t_field_3D = np.broadcast_to(t_field_2D[:, :, None], (Nx, Ny, Nz)).copy()

    def _z(a2d):
        """Extrude a (Nx, Ny) array uniformly to (Nx, Ny, Nz)."""
        return np.broadcast_to(a2d[:, :, None], (Nx, Ny, Nz)).copy()

    return {
        'eps_arr':   _z(p['eps_arr']),
        'eps_f_arr': _z(p['eps_f_arr']),
        'K_ffA_arr': _z(p['K_ffA_arr']),
        'K_ffB_arr': _z(p['K_ffB_arr']),
        'K_ss_arr':  _z(p['K_ss_arr']),
        'h_vA_arr':  _z(p['h_vA_arr']),
        'h_vB_arr':  _z(p['h_vB_arr']),
        'A_0_arr':   _z(p['A_0_arr']),
        'L_field':   L_field_3D,
        't_field':   t_field_3D,
        'cache_size': p['n_unique'],
    }


# ─── 3D evaluate ────────────────────────────────────────────────────


def evaluate_3d(x_decision: np.ndarray,
                cfg: dict,
                *,
                Nx: int = 40, Ny: int = 16, Nz: int = 16,
                Lz: float = 0.042,
                max_outer: int = 3,
                outer_tol_K: float = 0.5,
                alpha_outer: float = 0.6,
                max_iter_simple: int = 800,
                tol_simple: float = 1e-2,
                max_iter_energy: int = 2000,
                tol_energy: float = 0.5,
                roughness_mode: str | None = None,
                roughness_eps_um: float | None = None,
                convergence_mode: str = 'legacy',
                verbose: bool = True) -> dict:
    """Run the 3D evaluator on a single decision vector. Returns (Q_3D_W,
    dP_A_3D, dP_B_3D, dP_total_3D, mass_kg, info_dict).

    convergence_mode : 'legacy' (default) or 'f2'.
        'legacy' is the cheap screening criterion for BO throughput (rankings
        only — see the block comment at the solver setup below). 'f2' is the
        honest three-gate criterion (ledger C7); pass it when this evaluator
        is used to REPORT numbers rather than rank designs (e.g.
        `validation/cases/verify_pareto_3d.py`).
    """
    L_dom = float(cfg['L_domain']); H_dom = float(cfg['H_domain'])
    u_A   = float(cfg['u_A']);     u_B   = float(cfg['u_B'])
    T_inA = float(cfg['T_inA']);   T_inB = float(cfg['T_inB'])
    P_inA = float(cfg.get('P_inA', 101325.0))
    P_inB = float(cfg.get('P_inB', P_inA))
    tpms_type = cfg.get('tpms_type', 'Diamond')
    k_s   = float(cfg.get('k_s', 17.0))
    rho_s = float(cfg.get('rho_s', 2700.0))
    n_ctrl_x = int(cfg.get('n_ctrl_x', 4))
    n_ctrl_y = int(cfg.get('n_ctrl_y', 4))
    sym_y    = bool(cfg.get('symmetric_y', True))

    # 1. Build 2D field, extrude to 3D arrays
    fc = from_decision_vector(
        x_decision, tpms_type=tpms_type, k_s=k_s,
        L_domain=L_dom, H_domain=H_dom,
        n_ctrl_x=n_ctrl_x, n_ctrl_y=n_ctrl_y, symmetric_y=sym_y,
    )
    arrays = _build_3d_arrays(fc, Nx, Ny, Nz,
                               u_A, u_B, T_inA, T_inB, P_inA, k_s, tpms_type)

    dx_arr = np.full(Nx, L_dom / Nx, dtype=np.float64)
    dy_arr = np.full(Ny, H_dom / Ny, dtype=np.float64)
    dz_arr = np.full(Nz, Lz    / Nz, dtype=np.float64)

    # 2. Project to SIMPLE 3D K/cF arrays (per-row mean over cross-stream)
    K_A, cF_A = project_fields_to_streamwise_K_cF_3d(
        arrays['L_field'], arrays['t_field'], arrays['eps_f_arr'],
        tpms_type, Ny_sim=Nx, Nz_sim=Nz, fluid='A',
        streamwise_dx=dx_arr, z_dx=dz_arr)
    K_B, cF_B = project_fields_to_streamwise_K_cF_3d(
        arrays['L_field'], arrays['t_field'], arrays['eps_f_arr'],
        tpms_type, Ny_sim=Ny, Nz_sim=Nz, fluid='B',
        streamwise_dx=dy_arr, z_dx=dz_arr)

    # 2026-05-13 — air-side wall-roughness correction (Norris 1971 or
    # Bhatti-Shah-Haaland). Resolve mode + ε from env if not passed in.
    # Water side untouched (the per-topology water fit (`nu_water_topo`)
    # embeds AM roughness already).
    if roughness_mode is None or roughness_eps_um is None:
        from solvers.roughness import resolve_mode_from_env as _resolve
        _env_mode, _env_eps = _resolve(default='baseline')
        roughness_mode = roughness_mode or _env_mode
        roughness_eps_um = roughness_eps_um if roughness_eps_um is not None else _env_eps
    if roughness_mode != 'baseline':
        from solvers.roughness import f_enhancement, nu_extra_factor
        from solvers.tpms_calc import geometry as _tpms_geom
        _g_case = _tpms_geom(tpms_type, float(fc.L_ctrl.mean()),
                              float(fc.t_ctrl.mean()), k_s)
        _D_h_m = _g_case['D_h']
        _D_h_mm = _D_h_m * 1000.0
        # Standalone case-Re using freestream A inlet props (mirror validate
        # script). Independent of later SIMPLE init.
        _rho_A_in = air_density(T_inA, P_inA)
        _mu_A_in  = air_viscosity(T_inA)
        Re_A_case = float(_rho_A_in * abs(u_A) * _D_h_m / _mu_A_in)
        f_gain_A = float(f_enhancement(Re_A_case, roughness_mode,
                                        eps_um=roughness_eps_um,
                                        D_h_mm=_D_h_mm))
        K_A = (K_A / f_gain_A).astype(np.float64, copy=False)
        cF_A = (cF_A * f_gain_A).astype(np.float64, copy=False)
        # bhatti_shah_1b overrides Nu × 1.28 baked into compute(); norris_1a
        # leaves Nu unchanged (nu_extra_factor returns 1.0).
        nu_extra_A = float(nu_extra_factor(Re_A_case, roughness_mode,
                                            eps_um=roughness_eps_um,
                                            D_h_mm=_D_h_mm))
        if nu_extra_A != 1.0:
            arrays['h_vA_arr'] = (arrays['h_vA_arr'] * nu_extra_A).astype(
                np.float64, copy=False)
        if verbose:
            _log.info(f"[3D rough] mode={roughness_mode} eps={roughness_eps_um} μm  "
                      f"Re_A={Re_A_case:.0f}  f_gain_A={f_gain_A:.3f}  "
                      f"nu_extra_A={nu_extra_A:.3f}")

    # 3. Build SIMPLE 3D for both fluids. Fluid A: +x streamwise → axis swap
    # so SIMPLE-y = real-x; Fluid B: -y streamwise → SIMPLE-y = real-y reversed.
    rho_A0 = air_density(T_inA, P_inA); mu_A0 = air_viscosity(T_inA)
    rho_B0 = air_density(T_inB, P_inB); mu_B0 = air_viscosity(T_inB)
    eps_mean = float(arrays['eps_arr'].mean())
    # M2b (2026-07-09): the deferred xmod-eps-field-3d-evaluator finding is
    # CLOSED — the per-cell eps_field is installed on both solvers below
    # (fluid A with the SIMPLE-A axis swap), so graded designs run the exact
    # ε in continuity, μ_eff and the M2b VANS momentum ratios. eps_mean
    # remains only as the constructor scalar (the field overrides it).

    # 1D D-F closed-form seed for P_ref_abs (matches retired evaluate_3d)
    K_mean_A = float(np.mean(K_A))
    cF_mean_A = float(np.mean(cF_A))
    G_A = rho_A0 * u_A
    C_A = mu_A0 * G_A / max(K_mean_A, 1e-16) + cF_mean_A * G_A * G_A
    P_out_sq_A = predict_outlet_p_sq(P_inA, T_inA, C_A, L_dom)

    K_mean_B = float(np.mean(K_B))
    cF_mean_B = float(np.mean(cF_B))
    G_B = rho_B0 * u_B
    C_B = mu_B0 * G_B / max(K_mean_B, 1e-16) + cF_mean_B * G_B * G_B
    P_out_sq_B = predict_outlet_p_sq(P_inB, T_inB, C_B, H_dom)

    # 2026-05-20 UI sweep (Tier 17, user re-audit): strict-mode contract
    # from `tests/test_pressure_invalid_flag.py`. The compressible D-F
    # seed `P_out² = P_in² − 2RT·C·L` can go non-positive when C·L is
    # large (choked / over-driven duty). Solver paths legitimately
    # apply a `max(..., 1e4)` rescue floor so the optimizer value-path
    # is undisturbed (`test_predict_dP_default_returns_P_in_unchanged`),
    # but a *validation* tool must surface infeasibility — silently
    # papering over it with a finite plausible P_ref hides physically
    # impossible Pareto picks. Return NaN + an explicit `invalid` flag
    # so the caller can detect, exclude, and count them per
    # `test_predict_dP_strict_returns_nan_on_infeasible`.
    if P_out_sq_A <= 0.0 or P_out_sq_B <= 0.0:
        if verbose:
            _log.warning(f"[3D verify] INFEASIBLE — P_out²_A={P_out_sq_A:.3e} Pa², "
                         f"P_out²_B={P_out_sq_B:.3e} Pa². Returning NaN per strict "
                         "validation contract.")
        # mass is pure geometry — computable regardless of the choke, and a
        # bounded-bad BO fallback needs it (mass=NaN/0 would make an invalid
        # dense design look light on the mass objective).
        _cv = (dx_arr[:, None, None] * dy_arr[None, :, None]
               * dz_arr[None, None, :])
        _mass_geom = float(np.sum((1.0 - arrays['eps_arr']) * rho_s * _cv))
        return {
            'Q_3D_W':         float('nan'),
            'dP_A_Pa':        float('nan'),
            'dP_B_Pa':        float('nan'),
            'dP_total_Pa':    float('nan'),
            'mass_kg':        _mass_geom,
            'Lz_m':           Lz,
            'grid':           (Nx, Ny, Nz),
            'invalid':        True,
            'converged':      False,
            'invalid_reason': ('P_out² ≤ 0 on the 1D D-F seed — operating '
                               f'point is choked (A={P_out_sq_A:.3e}, '
                               f'B={P_out_sq_B:.3e}).'),
        }
    P_ref_A = float(np.sqrt(P_out_sq_A))
    P_ref_B = float(np.sqrt(P_out_sq_B))

    # BC note (2026-07-10): no inlet/outlet extents are passed, so both
    # solvers run the constructor default = FULL-FACE inlet/outlet. Port-type
    # partial BCs are NOT wired into this 3D optimizer stack (the 2D
    # optimization/evaluator.py has them via ports_A/ports_B); wiring them
    # here needs the run_stack_3d mask conventions (in_mask_2d et al.).
    sA = SIMPLESolver3D(
        Lx=H_dom, Ly=L_dom, Lz=Lz, Nx=Ny, Ny=Nx, Nz=Nz,
        rho=rho_A0, mu=mu_A0, T_in=T_inA, v_inlet=u_A,
        eps=eps_mean, K_arr=K_A, cF_arr=cF_A, P_ref_abs=P_ref_A,
    )
    sA.dx = np.ascontiguousarray(dy_arr, dtype=np.float64)
    sA.dy = np.ascontiguousarray(dx_arr, dtype=np.float64)
    sA.dz = np.ascontiguousarray(dz_arr, dtype=np.float64)
    # M2b: per-cell ε (SIMPLE-A indices (i,j,k) = (real-y, real-x, z)).
    # Uniform designs produce a constant array → use_eps stays 0 in the
    # solver and the pre-M2b float sequence is reproduced bit-identically.
    sA.eps_field = np.ascontiguousarray(
        arrays['eps_arr'].transpose(1, 0, 2), dtype=np.float64)
    # C10: refresh μ/ε to the installed per-cell ε (production pattern,
    # run_stack_3d does this right after its eps_field install). Without it
    # the FIRST cold solve ran the Brinkman term on the uniform mean-ε
    # (update_T_field self-heals sA from outer iter 1 — but not the cold one).
    sA._mu_eff_field = np.ascontiguousarray(sA.mu_field / sA.eps_field,
                                            dtype=np.float64)

    sB = SIMPLESolver3D(
        Lx=L_dom, Ly=H_dom, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        rho=rho_B0, mu=mu_B0, T_in=T_inB, v_inlet=u_B,
        eps=eps_mean, K_arr=K_B, cF_arr=cF_B, P_ref_abs=P_ref_B,
    )
    sB.dx = np.ascontiguousarray(dx_arr, dtype=np.float64)
    sB.dy = np.ascontiguousarray(dy_arr, dtype=np.float64)
    sB.dz = np.ascontiguousarray(dz_arr, dtype=np.float64)
    # M2b per-cell ε — C10 mapping fix: sB is REVERSE-y (real −y streamwise),
    # solver j=0 = the B inlet at real y=H, so per-cell fields map real→solver
    # by MIRRORING axis 1 — the same transform as the staggered faces above
    # and as K_B/cF_B (df_projection docstring: "flip along 0" for fluid B).
    # The pre-C10 install was unmirrored: an identity for symmetric_y=True
    # designs (every current track), WRONG for y-asymmetric ones.
    sB.eps_field = np.ascontiguousarray(arrays['eps_arr'][:, ::-1, :],
                                        dtype=np.float64)
    # C10: same μ/ε refresh as sA. sB never gets update_T_field (frozen-B),
    # so without this its Brinkman term uses the mean-ε μ/ε for the WHOLE run.
    sB._mu_eff_field = np.ascontiguousarray(sB.mu_field / sB.eps_field,
                                            dtype=np.float64)

    # ── Convergence mode: LEGACY by default, deliberately (ledger C6/C7) ──
    # The production pipeline (`run_stack_3d._apply_accel_flags`) now defaults to
    # 'f2' — the honest three-gate criterion. This optimizer evaluator does NOT,
    # and the choice is explicit rather than inherited so it cannot rot into an
    # accident:
    #   * F2 costs a measured ~2x SIMPLE wall time (reports/f2_pricing_3d.csv).
    #     This evaluator is called thousands of times per BO run; the pipeline is
    #     called once per reported result.
    #   * The standing convention (ledger O2 / audit R3) is that the optimizer
    #     produces RANKINGS ONLY, and every Pareto pick is re-solved through the
    #     production pipeline before any physical number is reported. Under that
    #     rule a cheaper, less-converged screening criterion is legitimate.
    # Under 'legacy': DO NOT quote this evaluator's dP/Q as physical results.
    # Callers that must REPORT numbers pass convergence_mode='f2' (ledger C10):
    # graded continuous-field designs cannot run through `run_stack_3d` (its
    # zoned path is piecewise-constant `zone_grid_cells`, a different geometry
    # parametrization), so `verify_pareto_3d.py` uses THIS evaluator at f2.
    # Remaining gaps vs the production pipeline even at f2 (ledger O2): fluid B
    # is solved once cold (frozen velocities, no var-ρ re-solve) and there is no
    # post-solve Mach/positive-pressure gate.
    for _s in (sA, sB):
        _s.convergence_mode = str(convergence_mode)

    # 4. Initial SIMPLE solves.
    # Convergence TRUTH TABLE (2026-07-13, codex review P0): these verdicts
    # used to be DISCARDED — three solve() calls dropped (converged, iters),
    # the LTNE call never asked for return_info, and hitting max_outer set no
    # failure state, so an unconverged run returned Q/dP indistinguishable
    # from a converged one and `verify_pareto_3d` exited 0 on it. Every
    # verdict is now collected and returned; reporting callers must gate on
    # them (screening callers may ignore them — rankings-only, ledger O2).
    if verbose:
        _log.info(f"[3D] Solving SIMPLE A (cold) … ")
    t0 = time.perf_counter()
    simple_A_ok, _itA = sA.solve(max_iter=max_iter_simple, tol=tol_simple,
                                 verbose=False)
    if verbose:
        _log.info(f"{time.perf_counter()-t0:.0f}s")
        _log.info(f"[3D] Solving SIMPLE B (cold) … ")
    t0 = time.perf_counter()
    simple_B_ok, _itB = sB.solve(max_iter=max_iter_simple, tol=tol_simple,
                                 verbose=False)
    if verbose:
        _log.info(f"{time.perf_counter()-t0:.0f}s")
    # Last LTNE inner pass's verdict (the returned fields ARE that pass's) and
    # the outer dT loop's own verdict. `outer_converged` stays False when the
    # loop exits via the max_outer cap — including max_outer == 1/2 where the
    # dT check never fires: "unverified" counts as NOT converged, by design.
    ltne_inner_ok = False
    outer_ok = False

    # 5. Outer LTNE coupling with variable density on fluid A.
    rcp_A_field = np.full((Nx, Ny, Nz), rho_A0 * air_cp(T_inA), dtype=np.float64)
    rcp_B_field = np.full((Nx, Ny, Nz), rho_B0 * air_cp(T_inB), dtype=np.float64)
    # Robustness (2026-06-25): a non-positive max_outer skips the loop below,
    # leaving Ta/Tb/Ts = None and crashing the post-loop reductions with an
    # opaque `None - None` TypeError. Fail loud on the invalid input instead.
    if max_outer < 1:
        raise ValueError(
            f"max_outer must be >= 1 (got {max_outer}); the LTNE outer loop "
            "would not run and the temperature fields would stay None.")
    Ta = Tb = Ts = None
    Ta_prev = None

    for outer_it in range(max_outer):
        # Cell-centred velocities
        vA_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])    # (Ny, Nx, Nz)
        ucA_real = vA_cc.transpose(1, 0, 2).copy()           # (Nx, Ny, Nz)
        vcA_real = np.zeros_like(ucA_real)
        wcA_real = np.zeros_like(ucA_real)
        vB_cc = 0.5 * (sB.v[:, :-1, :] + sB.v[:, 1:, :])    # (Nx, Ny, Nz)
        vcB_real = -vB_cc[:, ::-1, :].copy()
        ucB_real = np.zeros_like(vcB_real)
        wcB_real = np.zeros_like(vcB_real)

        # Full SIMPLE staggered faces → real coords, to drive the conservative
        # kernel (B-plan; matches the production run_stack_3d path so the
        # optimizer/Pareto evaluator uses the SAME strict-conservation solver
        # as the UI). sA maps solver→real via transpose(1,0,2) (A streamwise
        # +x); sB is reverse-y, so its faces mirror along y (axis 1) with the
        # streamwise (v) component negated — the divergence-preserving
        # transform, leaving the faces discretely solenoidal.
        ufA = np.ascontiguousarray(sA.v.transpose(1, 0, 2))   # (Nx+1,Ny,Nz)
        vfA = np.ascontiguousarray(sA.u.transpose(1, 0, 2))   # (Nx,Ny+1,Nz)
        wfA = np.ascontiguousarray(sA.w.transpose(1, 0, 2))   # (Nx,Ny,Nz+1)
        ufB = np.ascontiguousarray(sB.u[:, ::-1, :])          # (Nx+1,Ny,Nz)
        vfB = np.ascontiguousarray(-sB.v[:, ::-1, :])         # (Nx,Ny+1,Nz)
        wfB = np.ascontiguousarray(sB.w[:, ::-1, :])          # (Nx,Ny,Nz+1)

        if verbose:
            _log.info(f"[3D] outer {outer_it+1}/{max_outer} … ")
        t0 = time.perf_counter()
        # 2026-05-19 ε contract (Option A): pass FULL porosity. Kernel does
        # the single halving (eps_f = 0.5*epsilon → ε_A). Pre-halving here
        # double-halved to ε_full/4. K_ff arrays already use ε_A — untouched.
        Ta, Tb, Ts, _ltne_info = solve_full_domain_3d(
            L_dom, H_dom, Lz, Nx, Ny, Nz, T_inA, T_inB,
            arrays['K_ffA_arr'], arrays['K_ffB_arr'], arrays['K_ss_arr'],
            arrays['h_vA_arr'], arrays['h_vB_arr'],
            rcp_A_field, rcp_B_field, arrays['eps_arr'],
            ucA_real, vcA_real, wcA_real,
            ucB_real, vcB_real, wcB_real,
            cfg.get('dir_A', 0), cfg.get('dir_B', 3),
            dx_arr=dx_arr, dy_arr=dy_arr, dz_arr=dz_arr,
            max_iter=max_iter_energy, tol=tol_energy,  # FIX (2026-06-24 audit): use the advertised inner tol_energy, not outer_tol_K (the outer dT break below still uses outer_tol_K). Both default 0.5 → production unchanged.
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
            alpha_T=0.7,
            ufA=ufA, vfA=vfA, wfA=wfA, ufB=ufB, vfB=vfB, wfB=wfB,
            conservative_ltne=True,
            return_info=True,
        )
        ltne_inner_ok = bool(_ltne_info.get('converged', False))
        if verbose:
            _log.info(f"{time.perf_counter()-t0:.0f}s")

        if Ta_prev is not None:
            dT_max = float(np.max(np.abs(Ta - Ta_prev)))
            if dT_max < outer_tol_K:
                if verbose:
                    _log.info(f"[3D] outer converged at iter {outer_it+1} "
                              f"(dT_max={dT_max:.2f} < {outer_tol_K} K)")
                outer_ok = True
                break
        Ta_prev = Ta.copy()

        if outer_it == max_outer - 1:
            break

        # Var-density update on fluid A (matches retired evaluate_3d).
        # 2026-05-14 fix: also propagate Ta into SIMPLE.T_field so that
        # `_update_density` inside the next sA.solve() uses real local T
        # instead of stale T_in scalar. Without this, the manual
        # rho_field/mu_field assignment below is silently overwritten on
        # the first inner iter, breaking compressible T-ρ coupling.
        # validate_shanghai_3d_real.py and pipelines/run_stack_3d.py have
        # this propagation already; the BO evaluator was missing it.
        Ta_sA = Ta.transpose(1, 0, 2).copy()  # to SIMPLE A's internal layout
        sA.update_T_field(Ta_sA)
        P_abs_sA = sA.P_ref_abs + sA.P
        rho_A_new = P_abs_sA / (R_AIR * Ta_sA)
        mu_A_new = air_viscosity(Ta_sA)
        sA.rho_field = np.ascontiguousarray(
            alpha_outer * rho_A_new + (1 - alpha_outer) * sA.rho_field,
            dtype=np.float64)
        sA.mu_field = np.ascontiguousarray(
            alpha_outer * mu_A_new + (1 - alpha_outer) * sA.mu_field,
            dtype=np.float64)
        # C10: divide by the PER-CELL eps_field, not the scalar (this line used
        # to re-break the per-cell μ/ε install on every outer iteration;
        # uniform designs are value-identical either way).
        sA._mu_eff_field = np.ascontiguousarray(
            sA.mu_field / sA.eps_field, dtype=np.float64)
        T_avg = float(Ta_sA.mean())
        mu_avg = float(air_viscosity(T_avg))
        C_avg = mu_avg * G_A / max(K_mean_A, 1e-16) + cF_mean_A * G_A * G_A
        P_out_sq_new = predict_outlet_p_sq(P_inA, T_avg, C_avg, L_dom)
        if P_out_sq_new <= 0.0:
            # Hot-state choke (2026-07-13 audit): the COLD seed above passed,
            # but the heated T_avg raised 2RT·C·L past P_in². This used to be
            # `sqrt(max(..., 1e4))` — a silent 100 Pa outlet anchor that let
            # the run continue in a region with NO steady solution and return
            # numbers (the exact failure mode the envelope invariant exists to
            # stop, and `verify_pareto_3d` REPORTS these numbers). Same strict
            # contract as the cold seed: NaN + invalid, never a floored anchor.
            if verbose:
                _log.warning(f"[3D verify] INFEASIBLE at outer {outer_it+1} -- "
                             f"P_out^2={P_out_sq_new:.3e} Pa^2 after var-rho "
                             "reseed (hot-state choke). Returning NaN per "
                             "strict validation contract.")
            _cv = (dx_arr[:, None, None] * dy_arr[None, :, None]
                   * dz_arr[None, None, :])
            _mass_geom = float(np.sum((1.0 - arrays['eps_arr'])
                                      * rho_s * _cv))
            return {
                'Q_3D_W':         float('nan'),
                'dP_A_Pa':        float('nan'),
                'dP_B_Pa':        float('nan'),
                'dP_total_Pa':    float('nan'),
                'mass_kg':        _mass_geom,
                'Lz_m':           Lz,
                'grid':           (Nx, Ny, Nz),
                'invalid':        True,
                'converged':      False,
                'invalid_reason': ('P_out² ≤ 0 on the var-ρ outer reseed — '
                                   'operating point chokes once heated '
                                   f'(outer {outer_it+1}, T_avg={T_avg:.1f} K, '
                                   f'P_out²={P_out_sq_new:.3e}).'),
            }
        sA.P_ref_abs = float(np.sqrt(P_out_sq_new))

        if verbose:
            _log.info(f"[3D] re-solving SIMPLE A with var-ρ … ")
        t0 = time.perf_counter()
        # Last re-solve's verdict overwrites the cold one (the fields returned
        # are the last solve's).
        simple_A_ok, _itA = sA.solve(max_iter=max_iter_simple, tol=tol_simple,
                                     verbose=False)
        if verbose:
            _log.info(f"{time.perf_counter()-t0:.0f}s")

        # ── LTNE convective ρcp from SIMPLE's LOCAL ρ (ledger C10 fix) ────
        # This used to be `air_density(Ta/Tb, P_in)` — density at the INLET
        # pressure over the WHOLE domain, the pre-2026-06-09 behaviour the
        # production pipeline already fixed (`run_stack_3d` variable_rho_cp:
        # "rho_cp = ρ_local·cp matches SIMPLE's conserved mass flux").
        # SIMPLE's u accelerates as ρ falls downstream (G = ρ·u conserved);
        # multiplying that u by an inlet-pressure ρ inflates the convective
        # flux by P_in/P_local — a spurious enthalpy source growing with
        # Δp/P_in, i.e. a ranking distortion for high-Δp designs (C8-family).
        #   A: sA was just re-solved with the updated T_field, so rho_field is
        #      ρ(P_local, Ta) — use it directly (production pattern). SIMPLE-A
        #      layout (real-y, real-x, z) → real via transpose(1, 0, 2).
        #   B: sB is solved ONCE (cold, isothermal T_inB) with frozen
        #      velocities — use its ρ AS-IS (local P, T_inB) rather than
        #      re-warming with Tb: ρ·u then remains the flux SIMPLE-B actually
        #      conserved, so the convective operator sees no spurious
        #      divergence. The stale-T bias in B's ρ is part of the frozen-B
        #      approximation, same tier as the frozen velocities themselves.
        #      sB is reverse-y (see face transform above): mirror axis 1.
        rho_A_ltne = sA.rho_field.transpose(1, 0, 2)
        rho_B_ltne = sB.rho_field[:, ::-1, :]
        rcp_A_field = np.ascontiguousarray(
            alpha_outer * rho_A_ltne * air_cp(Ta)
            + (1 - alpha_outer) * rcp_A_field, dtype=np.float64)
        rcp_B_field = np.ascontiguousarray(
            alpha_outer * rho_B_ltne * air_cp(Tb)
            + (1 - alpha_outer) * rcp_B_field, dtype=np.float64)

    # 6. Integrate Q, dP, mass over the actual 3D grid
    cell_vol = (dx_arr[:, None, None]
                * dy_arr[None, :, None]
                * dz_arr[None, None, :])
    Q_3D = float(np.sum(arrays['h_vB_arr'] * (Ts - Tb) * cell_vol))   # W
    dP_A = float(SIMPLESolver3D.extract_dP_weighted(sA))
    dP_B = float(SIMPLESolver3D.extract_dP_weighted(sB))
    dP_total = dP_A + dP_B
    mass = float(np.sum((1.0 - arrays['eps_arr']) * rho_s * cell_vol))

    # Convergence truth table (codex review P0, 2026-07-13). `converged` is
    # the conjunction; reporting callers (verify_pareto_3d) MUST gate on it,
    # screening callers (BO wrapper) may ignore it — rankings-only, ledger O2.
    finite_ok = bool(np.isfinite(Q_3D) and np.isfinite(dP_A)
                     and np.isfinite(dP_B) and np.isfinite(mass))
    truth = {
        'simple_A_converged':   bool(simple_A_ok),
        'simple_B_converged':   bool(simple_B_ok),
        'ltne_inner_converged': bool(ltne_inner_ok),
        'outer_converged':      bool(outer_ok),
        'finite':               finite_ok,
    }
    return {
        'Q_3D_W':       Q_3D,
        'dP_A_Pa':      dP_A,
        'dP_B_Pa':      dP_B,
        'dP_total_Pa':  dP_total,
        'mass_kg':      mass,
        'Lz_m':         Lz,
        'grid':         (Nx, Ny, Nz),
        'invalid':      False,
        'converged':    all(truth.values()),
        **truth,
    }
