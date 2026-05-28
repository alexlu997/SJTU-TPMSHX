"""
optimization/evaluator.py — Single-design evaluator for the continuous-field
TPMS heat-exchanger optimizer.

Workflow per call::

    decision vector x  ─►  ContinuousFieldConfig  ─►  per-cell arrays
                                                       │
                                                       ▼
                       SIMPLE (fluid A)   SIMPLE (fluid B)
                                ▼                ▼
                       cell-centred velocity fields
                                ▼
                       solve_full_domain (LTNE energy)
                                ▼
                       Ta, Tb, Ts on (Nx, Ny)
                                ▼
                       Q  =  Σ h_vB·(Ts − Tb)·dA
                       dP =  dP_A + dP_B  (extract_dP_from_simple)
                       mass = Σ (1−ε)·ρ_s·dA

Compared to the retired patch-zoning evaluator this module:
  * accepts a 16-D continuous-field decision vector instead of 36-D patches;
  * skips the SIMPLE cache (each design is unique → cache hit-rate ≈ 0);
  * skips wall-refinement (`wall_refine=False`) — refinement was a Brinkman BL
    visualisation aid that the optimization path always disabled anyway;
  * skips the n_rho_loops > 1 outer compressibility iteration by default
    (set ``cfg['n_rho_loops'] > 1`` to enable, matching the prior evaluator's
    behavior; default 1 is the fast-mode preset).

Public API::

    DEFAULT_CONFIG : dict — sensible defaults; merge into user cfg
    evaluate_design(x, cfg) -> (Q_neg, dP, mass)

The returned objective is ``(-Q, dP)``: BO maximizes (so negate Q for
minimization-form output) while dP is minimized directly. The third value
``mass`` is informational (kg/m of HX depth) for downstream filtering.
"""

from __future__ import annotations

import warnings
import numpy as np

from solvers.tpms_calc import (
    air_density,
    air_viscosity,
    air_cp,
    geometry as tpms_geometry,
    adaptive_grid,
)
from solvers.simple_solver import SIMPLESolver
from solvers.solve_full import solve_full_domain
from solvers.df_projection import (
    extract_dP_from_simple,
    override_simple_K_cF,
)
from solvers.field_param import (
    ContinuousFieldConfig,
    from_decision_vector,
    DEFAULT_N_CTRL_X,
    DEFAULT_N_CTRL_Y,
    DEFAULT_SYMMETRIC_Y,
    DEFAULT_L_BOUNDS,
    DEFAULT_T_BOUNDS,
)


# ─── Default cfg (continuous-field flavour) ─────────────────────────


DEFAULT_CONFIG: dict = {
    # Domain
    'L_domain':   0.10,    # m  (real x, fluid A streamwise)
    'H_domain':   0.05,    # m  (real y, fluid B streamwise)
    'Nx':         None,    # None → adaptive_grid from D_h(L_avg, t_avg)
    'Ny':         None,
    'grid_alpha': 0.8,     # adaptive_grid density factor (0.8 = baseline)

    # TPMS + solid
    'tpms_type':  'Diamond',
    'k_s':        17.0,    # solid conductivity [W/(m K)]
    'rho_s':      2700.0,  # solid density [kg/m^3]

    # Fluid operating point
    'u_A':        10.0,    # m/s
    'u_B':        10.0,
    'T_inA':      350.0,   # K
    'T_inB':      300.0,
    'P_inA':      101325.0,
    'P_inB':      101325.0,

    # Flow direction codes
    #   0 = +x, 1 = -x, 2 = +y, 3 = -y
    'dir_A':      0,       # fluid A flows +x  → streamwise = real x
    'dir_B':      3,       # fluid B flows -y  → streamwise = real y reversed

    # Solver knobs
    'max_iter_simple': 5000,
    'tol_simple':      1e-3,        # SIMPLE mass residual tolerance. The
                                    # cross-flow geometry (no manifold,
                                    # axis-swap on side B) leaves side B's
                                    # residual stagnating at O(1e-3) on
                                    # heterogeneous fields even though dP
                                    # has fully stabilized; tightening past
                                    # 1e-3 produces 100% rejection during
                                    # Sobol exploration without changing
                                    # Q / dP. V&V Standard-Tier paths can
                                    # override to 1e-5 explicitly.
    'max_iter_energy': 5000,
    'tol_energy':      0.5,        # K
    'n_rho_loops':     3,          # 1 = isothermal-ρ fast path; >1 enables
                                   # outer SIMPLE↔energy variable-density
                                   # iteration. 3 is the ConstDF-v1 baseline
                                   # used in validate_shanghai_3d_real and
                                   # the retired patch-zoning evaluator;
                                   # honors feedback_compressible_required.md.
    'drho_tol':        0.01,       # converge outer loop when |Δρ|/ρ̄ < 1 %
    'rho_relax':       0.7,        # under-relaxation on ρ updates (Picard)

    # Continuous-field parametrization
    'n_ctrl_x':    DEFAULT_N_CTRL_X,
    'n_ctrl_y':    DEFAULT_N_CTRL_Y,
    'symmetric_y': DEFAULT_SYMMETRIC_Y,
    'L_bounds':    DEFAULT_L_BOUNDS,
    't_bounds':    DEFAULT_T_BOUNDS,
    'spline_order': 3,

    # Manufacturability penalty added to dP objective
    'penalty_enabled':  True,
    'penalty_weight':   1.0,        # scales the raw penalty before adding to dP

    # Pathological-design rejection (production hardening; v2)
    'dp_cap_pa':            1.0e6,  # hard upper bound on dP. Designs that
                                    # blow past this — usually unconverged
                                    # SIMPLE residuals masquerading as dP —
                                    # are tagged bad and returned at the cap
                                    # so the BO surrogate sees a bounded
                                    # input distribution (no 17-MPa outliers
                                    # destroying GP lengthscale estimates).
    'reject_unconverged':   False,  # When True, a SIMPLE solve that exits at
                                    # max_iter without hitting tol returns at
                                    # the cap with Q ≈ 0. Default off because
                                    # the dp_cap_pa final guard already
                                    # catches the failure mode we care about
                                    # (residual-dominated dP > 1 MPa); strict
                                    # convergence-flag rejection just discards
                                    # designs where dP is already stable but
                                    # mass residual happens to plateau above
                                    # tol_simple. Set True for diagnostics
                                    # that demand machine-precision SIMPLE.
}


# ─── Helpers ────────────────────────────────────────────────────────


def _resolve_grid(cfg: dict, fc: ContinuousFieldConfig) -> tuple:
    """Return (Nx, Ny) from cfg or from adaptive_grid using the field's mean
    cell size as the characteristic length scale."""
    if cfg.get('Nx') is not None and cfg.get('Ny') is not None:
        return int(cfg['Nx']), int(cfg['Ny'])
    L_mean = float(fc.L_ctrl.mean())
    t_mean = float(fc.t_ctrl.mean())
    g = tpms_geometry(cfg['tpms_type'], L_mean, t_mean, cfg['k_s'])
    return adaptive_grid(cfg['L_domain'], cfg['H_domain'], g['D_h'],
                         cfg.get('grid_alpha', 0.8))


def _build_simple_A(cfg: dict, fc: ContinuousFieldConfig, arrays: dict,
                    Nx_real: int, Ny_real: int) -> SIMPLESolver:
    """Build SIMPLE for fluid A (+x streamwise; SIMPLE-internal y ↔ real x).

    Note the axis swap on the SIMPLESolver constructor: SIMPLE's W=H_real,
    H=L_real, Nx=Ny_real, Ny=Nx_real. This matches the fluid-A convention in
    runs/run_calculation.py.
    """
    L_dom = float(cfg['L_domain']); H_dom = float(cfg['H_domain'])
    T_inA = float(cfg['T_inA']);   P_inA = float(cfg['P_inA'])
    u_A   = float(cfg['u_A'])
    rho_A = air_density(T_inA, P_inA)
    mu_A  = air_viscosity(T_inA)
    eps_mean = float(arrays['eps_arr'].mean())
    r_h_mean = float(arrays['r_h_arr'].mean())

    s = SIMPLESolver(
        H_dom, L_dom, Ny_real, Nx_real,
        cfg['tpms_type'], float(fc.L_ctrl.mean()), float(fc.t_ctrl.mean()),
        eps_mean, r_h_mean,
        rho_A, mu_A, T_inA,
        inlet_lo=0.0, inlet_hi=H_dom, v_inlet=u_A,
        outlet_lo=0.0, outlet_hi=H_dom,
        wall_refine=False,
        P_ref_abs=P_inA,
    )

    # Push spatially-graded ε into SIMPLE's macroscopic continuity
    if 'eps_arr' in arrays:
        eps_real = arrays['eps_arr']                 # shape (Nx_real, Ny_real)
        eps_simple = eps_real.T.copy()               # → (Ny_real, Nx_real) for SIMPLE A
        if eps_simple.shape == s.eps_field.shape:
            s.eps_field = np.ascontiguousarray(eps_simple, dtype=np.float64)

    # Override per-row K / c_F from the design L_field, t_field
    Ny_sim = s._K_arr.shape[0]
    override_simple_K_cF(s, cfg['tpms_type'], cfg['k_s'], Ny_sim,
                         None, arrays['L_field'], arrays['t_field'], 'A')
    return s


def _build_simple_B(cfg: dict, fc: ContinuousFieldConfig, arrays: dict,
                    Nx_real: int, Ny_real: int) -> SIMPLESolver:
    """Build SIMPLE for fluid B (-y streamwise; SIMPLE coords match real)."""
    L_dom = float(cfg['L_domain']); H_dom = float(cfg['H_domain'])
    T_inB = float(cfg['T_inB']);   P_inB = float(cfg['P_inB'])
    u_B   = float(cfg['u_B'])
    rho_B = air_density(T_inB, P_inB)
    mu_B  = air_viscosity(T_inB)
    eps_mean = float(arrays['eps_arr'].mean())
    r_h_mean = float(arrays['r_h_arr'].mean())

    s = SIMPLESolver(
        L_dom, H_dom, Nx_real, Ny_real,
        cfg['tpms_type'], float(fc.L_ctrl.mean()), float(fc.t_ctrl.mean()),
        eps_mean, r_h_mean,
        rho_B, mu_B, T_inB,
        inlet_lo=0.0, inlet_hi=L_dom, v_inlet=u_B,
        outlet_lo=0.0, outlet_hi=L_dom,
        wall_refine=False,
        P_ref_abs=P_inB,
    )

    if 'eps_arr' in arrays:
        eps_simple = arrays['eps_arr']               # SIMPLE B uses real coords directly
        if eps_simple.shape == s.eps_field.shape:
            s.eps_field = np.ascontiguousarray(eps_simple, dtype=np.float64)

    Ny_sim = s._K_arr.shape[0]
    override_simple_K_cF(s, cfg['tpms_type'], cfg['k_s'], Ny_sim,
                         None, arrays['L_field'], arrays['t_field'], 'B')
    return s


def _cellcentered_velocity_A(s: SIMPLESolver, Nx_real: int, Ny_real: int) -> tuple:
    """Convert SIMPLE A internal v field → real-coord (ucA, vcA) on (Nx_real, Ny_real)."""
    # SIMPLE A: streamwise = SIMPLE-y = real-x. v field shape (Nx_simple, Ny_simple+1),
    # which is (Ny_real, Nx_real+1).
    vA = 0.5 * (s.v[:, :-1] + s.v[:, 1:])     # (Ny_real, Nx_real)
    ucA_real = vA.T.copy()                     # (Nx_real, Ny_real)
    vcA_real = np.zeros_like(ucA_real)
    return ucA_real, vcA_real


def _cellcentered_velocity_B(s: SIMPLESolver, Nx_real: int, Ny_real: int) -> tuple:
    """Convert SIMPLE B internal v field → real-coord (ucB, vcB).

    SIMPLE B has -y streamwise: SIMPLE's inlet (j=0) corresponds to real y=H,
    outlet (j=Ny−1) to real y=0. Mirror along axis 1 to put the result in
    real coords.
    """
    vB = 0.5 * (s.v[:, :-1] + s.v[:, 1:])     # (Nx_real, Ny_real)
    vcB_real = -vB[:, ::-1].copy()             # negate sign + mirror along y
    ucB_real = np.zeros_like(vcB_real)
    return ucB_real, vcB_real


def _enthalpy_q(arrays: dict, Tb: np.ndarray, Ts: np.ndarray,
                dx_arr: np.ndarray, dy_arr: np.ndarray) -> float:
    """Volumetric heat exchange Q = Σ h_vB · (Ts − Tb) · dA over the HX area.

    This is the same convention used by the retired 2-D evaluator
    (h_vB-based formulation; equivalent to ṁ·cp·ΔT to within enthalpy-flux
    boundary conditions).
    """
    cell_area = dx_arr[:, None] * dy_arr[None, :]
    return float(np.sum(arrays['h_vB_arr'] * (Ts - Tb) * cell_area))


# ─── Public API ─────────────────────────────────────────────────────


def _compute_cfg_to_evaluator_dict(compute_cfg) -> dict:
    """Map ``controllers.ComputeConfig`` → evaluator-style flat dict.

    Audit C3 (2026-05-28, L-a-1): callers can pass a strict-typed
    ComputeConfig instead of hand-rolling a dict. Keys are the subset
    that overlaps with :data:`DEFAULT_CONFIG`; everything else stays
    on the dataclass defaults.
    """
    return {
        'L_domain': compute_cfg.geometry.L_dom_m,
        'H_domain': compute_cfg.geometry.H_dom_m,
        'Nx': compute_cfg.solver.Nx,
        'Ny': compute_cfg.solver.Ny,
        'tpms_type': compute_cfg.geometry.tpms,
        'k_s': compute_cfg.geometry.k_s_W_mK,
        'u_A': compute_cfg.fluid_A.u_mps,
        'u_B': compute_cfg.fluid_B.u_mps,
        'T_inA': compute_cfg.fluid_A.T_in_K,
        'T_inB': compute_cfg.fluid_B.T_in_K,
        'P_inA': compute_cfg.fluid_A.P_in_Pa,
        'P_inB': compute_cfg.fluid_B.P_in_Pa,
        'max_iter_simple': compute_cfg.solver.max_iter_simple,
        'tol_simple': compute_cfg.solver.tol_simple,
        'tol_energy': compute_cfg.solver.outer_tol_K,
    }


def evaluate_design(x: np.ndarray,
                    cfg: dict | None = None,
                    fc: ContinuousFieldConfig | None = None,
                    *, verbose: bool = False,
                    compute_cfg=None) -> tuple:
    """Evaluate one continuous-field design.

    Parameters
    ----------
    x : (16,) array   — decision vector. Ignored when ``fc`` is provided.
    cfg : dict        — overrides over DEFAULT_CONFIG.
    fc  : ContinuousFieldConfig — pre-built field (e.g. for sanity tests
                        bypassing the encode/decode step).
    verbose : bool    — propagate to SIMPLE for residual printout.
    compute_cfg : controllers.ComputeConfig, optional
                        Strict-typed config (audit C3, L-a-1). When
                        provided, its overlapping fields are merged
                        underneath ``cfg`` so the dict path keeps
                        absolute precedence.

    Returns
    -------
    Q_neg : float — −Q (W per metre of HX depth). Smaller = more heat moved.
    dP    : float — total pressure drop on both fluid sides + manufacturability
                    penalty [Pa].
    mass  : float — solid mass per unit depth [kg/m].
    """
    if compute_cfg is not None:
        cc_dict = _compute_cfg_to_evaluator_dict(compute_cfg)
        cfg_full = {**DEFAULT_CONFIG, **cc_dict, **(cfg or {})}
    else:
        cfg_full = {**DEFAULT_CONFIG, **(cfg or {})}

    # 1. Build / accept the field config
    if fc is None:
        fc = from_decision_vector(
            x,
            tpms_type=cfg_full['tpms_type'],
            k_s=cfg_full['k_s'],
            L_domain=cfg_full['L_domain'],
            H_domain=cfg_full['H_domain'],
            n_ctrl_x=cfg_full['n_ctrl_x'],
            n_ctrl_y=cfg_full['n_ctrl_y'],
            symmetric_y=cfg_full['symmetric_y'],
            spline_order=cfg_full['spline_order'],
            L_bounds=cfg_full['L_bounds'],
            t_bounds=cfg_full['t_bounds'],
        )

    Nx, Ny = _resolve_grid(cfg_full, fc)

    # 2. Per-cell property arrays (uniform grid spacing for now; wall-refine off)
    L_dom = float(cfg_full['L_domain']); H_dom = float(cfg_full['H_domain'])
    dx_arr = np.full(Nx, L_dom / Nx, dtype=np.float64)
    dy_arr = np.full(Ny, H_dom / Ny, dtype=np.float64)

    arrays = fc.build_grid_arrays(
        Nx, Ny,
        u_A=cfg_full['u_A'], u_B=cfg_full['u_B'],
        T_inA=cfg_full['T_inA'], T_inB=cfg_full['T_inB'],
        P_in=cfg_full['P_inA'],
    )

    # 3. SIMPLE for both fluids (cold-start; design-specific so cache is moot)
    sA = _build_simple_A(cfg_full, fc, arrays, Nx, Ny)
    sB = _build_simple_B(cfg_full, fc, arrays, Nx, Ny)

    sA_converged, _sA_iters = sA.solve(max_iter=cfg_full['max_iter_simple'],
                                        tol=cfg_full['tol_simple'],
                                        verbose=verbose)
    sB_converged, _sB_iters = sB.solve(max_iter=cfg_full['max_iter_simple'],
                                        tol=cfg_full['tol_simple'],
                                        verbose=verbose)

    # ── Reject pathological designs early ──
    # Rationale: an unconverged SIMPLE leaves a non-zero mass-residual P field
    # whose inlet–outlet spread reads as a multi-MPa "dP". Letting that into
    # the GP destroys lengthscale estimation. Returning at the dp_cap (rather
    # than 1e9) keeps the input distribution bounded — the GP learns "this
    # part of design space is uniformly bad" instead of overshooting.
    dp_cap = float(cfg_full.get('dp_cap_pa', 1.0e6))
    # 2026-05-20 code-bug sweep (Tier 23): the `.get` fallback was `True`,
    # contradicting DEFAULT_CONFIG['reject_unconverged'] = False. With a
    # fully-merged cfg the key is always present (so the fallback is
    # dead), but a caller passing a partial cfg dict would silently flip
    # to reject-on-unconverged — the OPPOSITE of the documented default.
    # Align the fallback with DEFAULT_CONFIG so both sources of truth
    # agree.
    if cfg_full.get('reject_unconverged', False) and not (sA_converged and sB_converged):
        cell_area = dx_arr[:, None] * dy_arr[None, :]
        mass_rejected = float(np.sum((1.0 - arrays['eps_arr'])
                                     * cfg_full['rho_s'] * cell_area))
        return -1e-6, dp_cap, mass_rejected

    # 4. Energy LTNE + variable-density outer coupling.
    #
    # n_rho_loops == 1   → isothermal-ρ fast path (single energy solve)
    # n_rho_loops >  1   → after each energy solve, update ρ_A/B(T) via
    #                       ideal-gas state law, push back into SIMPLE (with
    #                       axis-swap for fluid A), re-solve SIMPLE warm-start,
    #                       repeat until max relative ρ change < 1 % or the
    #                       loop cap is hit. This honors the project's
    #                       compressibility hard constraint (see
    #                       feedback_compressible_required.md): the ideal-gas
    #                       coupling is what holds the dP RMSRE at 17.83 % on
    #                       Shanghai 3D; dropping it regressed dP to 38.88 %.
    n_rho_loops = max(1, int(cfg_full.get('n_rho_loops', 1)))
    drho_tol    = float(cfg_full.get('drho_tol', 0.01))
    rho_relax   = float(cfg_full.get('rho_relax', 0.7))

    P_inA = float(cfg_full['P_inA']); P_inB = float(cfg_full['P_inB'])
    T_inA = float(cfg_full['T_inA']); T_inB = float(cfg_full['T_inB'])

    # Real-coord (Nx, Ny) ρ and ρ·cp fields seeded at inlet conditions.
    rho_A_field = np.full((Nx, Ny), air_density(T_inA, P_inA), dtype=np.float64)
    rho_B_field = np.full((Nx, Ny), air_density(T_inB, P_inB), dtype=np.float64)
    rcp_A = rho_A_field * air_cp(T_inA)
    rcp_B = rho_B_field * air_cp(T_inB)

    Ta = Tb = Ts = None
    for outer_it in range(n_rho_loops):
        ucA, vcA = _cellcentered_velocity_A(sA, Nx, Ny)
        ucB, vcB = _cellcentered_velocity_B(sB, Nx, Ny)
        Ta, Tb, Ts = solve_full_domain(
            L_dom, H_dom, Nx, Ny,
            T_inA, T_inB,
            arrays['K_ffA_arr'], arrays['K_ffB_arr'], arrays['K_ss_arr'],
            arrays['h_vA_arr'], arrays['h_vB_arr'],
            rcp_A, rcp_B,
            arrays['eps_arr'], ucA, vcA, ucB, vcB,
            cfg_full['dir_A'], cfg_full['dir_B'],
            tol=cfg_full['tol_energy'], max_iter=cfg_full['max_iter_energy'],
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
            dx_arr=dx_arr, dy_arr=dy_arr,
        )

        if n_rho_loops == 1:
            break

        # Update ρ from new Ta/Tb (real coords). air_density takes (T, P)
        # broadcastable arrays; here T is 2D and P is scalar.
        rho_A_new = air_density(Ta, P_inA)
        rho_B_new = air_density(Tb, P_inB)
        drho_max = max(
            float(np.max(np.abs(rho_A_new - rho_A_field)) /
                  max(rho_A_field.mean(), 1e-12)),
            float(np.max(np.abs(rho_B_new - rho_B_field)) /
                  max(rho_B_field.mean(), 1e-12)),
        )
        if drho_max < drho_tol:
            break  # converged
        if outer_it == n_rho_loops - 1:
            break  # last sweep — no point re-solving SIMPLE only to discard

        # Under-relaxed update of ρ + ρ·cp fields.
        rho_A_field = rho_relax * rho_A_new + (1.0 - rho_relax) * rho_A_field
        rho_B_field = rho_relax * rho_B_new + (1.0 - rho_relax) * rho_B_field
        rcp_A = (rho_relax * rho_A_new * air_cp(Ta)
                 + (1.0 - rho_relax) * rcp_A)
        rcp_B = (rho_relax * rho_B_new * air_cp(Tb)
                 + (1.0 - rho_relax) * rcp_B)

        # Push updated ρ + T into SIMPLE. SIMPLE A's internal grid is
        # axis-swapped (SIMPLE-y = real-x), so transpose before assignment.
        # update_T_field also refreshes mu_field / mu_eff_field via
        # Sutherland so the D-F sweep stays consistent under non-iso flow.
        sA.rho_field = np.ascontiguousarray(rho_A_field.T, dtype=np.float64)
        sB.rho_field = np.ascontiguousarray(rho_B_field,   dtype=np.float64)
        sA.update_T_field(np.ascontiguousarray(Ta.T,       dtype=np.float64))
        sB.update_T_field(np.ascontiguousarray(Tb,         dtype=np.float64))

        # Re-solve SIMPLE with warm-started u/v/P.
        sA.solve(max_iter=cfg_full['max_iter_simple'],
                 tol=cfg_full['tol_simple'], verbose=verbose)
        sB.solve(max_iter=cfg_full['max_iter_simple'],
                 tol=cfg_full['tol_simple'], verbose=verbose)

    # 5. Objectives
    Q_total = _enthalpy_q(arrays, Tb, Ts, dx_arr, dy_arr)
    dP_A = extract_dP_from_simple(sA)
    dP_B = extract_dP_from_simple(sB)
    dP_total = float(dP_A + dP_B)

    pen = 0.0
    if cfg_full['penalty_enabled']:
        pen = float(cfg_full['penalty_weight']) * fc.manufacturability_penalty()

    cell_area = dx_arr[:, None] * dy_arr[None, :]
    mass = float(np.sum((1.0 - arrays['eps_arr']) * cfg_full['rho_s'] * cell_area))

    dP_objective = float(dP_total + pen)
    # Final blowup guard: NaN, inf, or above the cap → tag bad. Even when
    # SIMPLE converged, the pen term or a degenerate field can lift the
    # objective above the cap; clamp so the GP input stays bounded.
    if not np.isfinite(dP_objective) or dP_objective > dp_cap:
        return -1e-6, dp_cap, mass

    return -Q_total, dP_objective, mass


# ─── Standalone smoke test ──────────────────────────────────────────


if __name__ == '__main__':
    import time
    warnings.filterwarnings('ignore')

    # Build a uniform field at L=6, t=0.4 → equivalent to single-zone baseline
    from solvers.field_param import uniform_field, encode_decision_vector

    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0, 0.10, 0.05)
    print("Building uniform-field design …")
    t0 = time.perf_counter()
    Q_neg, dP, mass = evaluate_design(
        x=None, cfg={'fast_mode': False, 'max_iter_simple': 800,
                     'tol_simple': 1e-3, 'max_iter_energy': 1500,
                     'tol_energy': 0.5},
        fc=fc, verbose=False)
    dt = time.perf_counter() - t0
    print(f"Q  = {-Q_neg:8.1f} W/m   (Q_neg = {Q_neg:.1f})")
    print(f"dP = {dP:8.1f} Pa")
    print(f"mass = {mass:.3f} kg/m   solid")
    print(f"wall time {dt:.1f} s")
