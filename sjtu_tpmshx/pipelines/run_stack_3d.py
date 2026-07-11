"""pipelines/run_stack_3d.py — the unified 3D SIMPLE↔LTNE run stack.

Moved verbatim from stages_3d.py (openspec split-pipelines, 2026-07-03);
behavior bit-identical. Depends only on the leaf modules pipelines.flux_3d /
pipelines.grid_3d / pipelines.stages_3d_helpers — it must NOT import
pipelines.stages_3d (no cycles; stages_3d re-exports these names instead).
"""

from __future__ import annotations
import os
import time as _time
import numpy as np

from solvers.coupling_skeleton import OuterConvergence, run_outer_coupling
from solvers.simple_solver_3d import SIMPLESolver3D
from solvers.ltne_energy_3d import solve_full_domain_3d
from solvers.tpms_calc import (
    geometry as tpms_geometry, air_density, air_viscosity,
    air_conductivity, air_cp,
)
from solvers import fluid_props
from solvers import sco2_props
from solvers.asym_split import (
    _asym_split_A, _per_side_eps_override, _eps_sides_for_run,
)
from df_surrogate.predict import predict_K_cF, SCO2_CF_SCALE
from df_surrogate.kappa_asym import kappa_KcF
from solvers.envelope import (check_compressible_envelope, gate_solution,
                               mach_field_max, ChokedFlowError,
                               PRESSURE_FLOOR_PA)

from pipelines.flux_3d import (
    _face_flux_weights, _mass_weighted_T_out, _mass_weighted_h_out,
    _sco2_hv_local_field, _simple_mass_flow,
    _apply_roughness_KcF, _apply_roughness_h_v,
)
from pipelines.grid_3d import (
    _resolve_axis_map, _build_zone_fields_3d, _build_grid_3d,
    _solver_spacings,
)
from pipelines.stages_3d_helpers import (  # Phase 3: extracted pure helpers
    _stream_axis, _inlet_index, _outlet_index,
    _face_slice, _real_outlet_slice,
    _build_partial_masks, _solver_velocity_to_real, _solver_staggered_to_real,
    _balance_stream_outflow, _build_chi_B_union_extrude,
    _build_chi_B_mass_flux_threshold, _build_chi_B_velocity_threshold,
)
from logutil import get_logger

_log = get_logger(__name__)


def _seed_p_ref(P_out_sq, P_in, *, mode, warn_list, context):
    """Pre-solve choke gate + the legacy 1D P_ref_abs seed.

    ``check_compressible_envelope`` raises (mode='raise') or returns a warning
    string (mode='warn') when ``P_out_sq <= 0`` (predicted dP >= inlet abs
    pressure). The returned ``sqrt(max(P_out_sq, 1e4))`` is the unchanged seed
    used by 'warn'/'off' so a non-raising run still produces a P_ref_abs.
    """
    w = check_compressible_envelope(P_out_sq, P_in, mode=mode, context=context)
    if w:
        warn_list.append(w)
    return float(np.sqrt(max(P_out_sq, 1.0e4)))


# 2026-04-26: env var TPMSHX_SIMPLE_TOL overrides default SIMPLE pp tol for
# diagnostic sweeps (path 0 / 0' v3 plan). Read each call to allow sweeps.
# R3 (2026-07-07): SolverConfig.tol_simple slots between env and the auto —
# precedence env > config > 1e-5. cfg-less callers keep the old behaviour.
def _simple_tol_default(cfg=None):
    env = os.environ.get('TPMSHX_SIMPLE_TOL')
    if env is not None:
        return float(env)
    if cfg is not None and cfg.get('tol_simple') is not None:
        return float(cfg['tol_simple'])
    return 1e-5


def _simple_max_iter(cfg, default):
    """R3: SolverConfig.max_iter_simple overrides the per-stage auto."""
    v = cfg.get('max_iter_simple') if cfg is not None else None
    return int(v) if v is not None else int(default)


def _apply_phase_flags(cfg):
    """Phase A/B/C acceleration flags — env-var entrypoint (UI checkbox TBD).

    Phase A defaults ON (zero-loss); Phase B/C opt-in until full-sweep
    validated. Set ``TPMSHX_PHASE_A=0`` to disable A; ``TPMSHX_PHASE_B=1`` /
    ``_C=1`` to enable B/C. ``setdefault`` so explicit cfg keys win over env.
    Single env-read source for both the window path and the cfg (Pipeline3D)
    path; ``_apply_accel_flags`` below then mirrors cfg onto each solver.
    """
    cfg.setdefault('use_adaptive_amg_tol',
                    os.getenv('TPMSHX_PHASE_A', '1') != '0')
    cfg.setdefault('use_anderson',
                    os.getenv('TPMSHX_PHASE_B', '0') == '1')
    cfg.setdefault('use_coarse_bootstrap',
                    os.getenv('TPMSHX_PHASE_C', '0') == '1')


def _apply_accel_flags(solver, cfg):
    """Mirror the Phase A/B/C acceleration knobs from ``cfg`` onto a SIMPLE3D
    solver. Single source so fluid A and fluid B stay in lockstep (these seven
    assignments were previously duplicated verbatim per fluid). Phase A defaults
    on (zero-loss inner-tol scheduling); B/C opt-in until full-sweep validated."""
    solver.use_adaptive_amg_tol = bool(cfg.get('use_adaptive_amg_tol', True))
    solver.use_anderson = bool(cfg.get('use_anderson', False))
    solver.anderson_m = int(cfg.get('anderson_m', 5))
    solver.anderson_K = int(cfg.get('anderson_K', 3))
    solver.use_coarse_bootstrap = bool(cfg.get('use_coarse_bootstrap', False))
    solver.coarse_bootstrap_max_iter = int(cfg.get('coarse_bootstrap_max_iter', 200))
    solver.coarse_bootstrap_tol = float(cfg.get('coarse_bootstrap_tol', 1e-3))


# ─────────────────────────────────────────────────────────────────────────
#  3D solver profiler (opt-in, zero-cost when off)
# ─────────────────────────────────────────────────────────────────────────
#  WHY: 3D runtime is dominated by the SIMPLE↔LTNE coupling. When a run is
#  slow, you need per-solve attribution to know whether SIMPLE-A, SIMPLE-B,
#  or the LTNE solve is the bottleneck — and whether a solve is genuinely
#  converging or burning iterations on a residual plateau. This profiler
#  emits exactly that.
#
#  This is the instrument that diagnosed the low-Re water bottleneck
#  (2026-06-02): it showed SIMPLE_B hitting its iteration cap (2000/600,
#  conv=False) while its velocity field was already settled — i.e. the
#  absolute mass residual plateaus above the air-tuned tol for slow water.
#  That finding drove the A+B early-exit in solvers/simple_solver_3d.py.
#
#  OUTPUT (stdout, grep-friendly):
#    [PROF]     <stage>: <wall>s  iters=<n>  conv=<bool>  (cap=<n>)
#    [PROF-RES] <stage>: n=<N> first=[..] last=[..] min=<r>@<it> final=<r>
#               — the per-iter mass-residual trajectory (head/tail/min), to
#               distinguish a slow-but-monotone descent from a plateau.
#
#  COST: gated behind _prof_3d_enabled(); when off, no perf_counter call, no
#  array copy, no print — pure `if False:`. Safe to leave in production.
#
#  ENABLE: TPMSHX_PROFILE_3D=1  (or drop an empty `.profile_3d` file at the
#  package root for GUI / IDE launches that carry no shell env).
def _prof_3d_enabled():
    """B1 profiler gate. Prints per-outer wall-clock + iteration counts for
    each SIMPLE / LTNE solve so the 3D runtime can be attributed to a specific
    solver. Zero cost when off. Enable by EITHER:
      - env var:  TPMSHX_PROFILE_3D=1   (PowerShell: $env:TPMSHX_PROFILE_3D=1)
      - flag file: drop an empty file named ``.profile_3d`` in the package root
        (same dir as main.py) — handy when the GUI is launched without a shell
        env (double-click, IDE run config, etc.)."""
    if os.environ.get('TPMSHX_PROFILE_3D', '0') == '1':
        return True
    try:
        _flag = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            '.profile_3d')
        return os.path.exists(_flag)
    except Exception:
        return False


def _prof_res_trace(tag, solver):
    """B2a: print the SIMPLE mass-residual trajectory (per-iter ``residuals``
    list) so we can tell a slow-but-monotone descent (raise cap / accelerate)
    from a plateau / limit-cycle (needs a scheme change). Samples first 5,
    last 5, and the min residual + the iter it occurred."""
    try:
        r = list(getattr(solver, 'residuals', []) or [])
        if not r:
            _log.info(f"[PROF-RES] {tag}: (no residuals)")
            return
        import numpy as _np
        arr = _np.asarray(r, dtype=float)
        i_min = int(_np.argmin(arr))
        head = " ".join(f"{x:.2e}" for x in arr[:5])
        tail = " ".join(f"{x:.2e}" for x in arr[-5:])
        _log.info(f"[PROF-RES] {tag}: n={len(arr)} first=[{head}] "
                  f"last=[{tail}] min={arr[i_min]:.2e}@{i_min} "
                  f"final={arr[-1]:.2e}")
    except Exception as _e:
        _log.warning(f"[PROF-RES] {tag}: trace failed: {_e}")


def _run_two_simple_parallel(sA, sB, *, max_iter=2000, tol=None,
                             cancel_check=None):
    """Run SIMPLE A and SIMPLE B concurrently on two OS threads.

    `SIMPLESolver3D.solve` spends its wall-clock inside Numba njit kernels
    and PyAMG/BiCGStab (both release the GIL), so pure Python threading
    delivers real parallelism. Fluid A and Fluid B use independent instances
    (own matrix, ml_cache, arrays) — no shared mutable state.

    `cancel_check` (optional callable -> bool) is forwarded to both solves so
    each thread breaks its SIMPLE loop early on cancel; after the join the
    caller raises if cancellation was requested (point 4).

    Raises the first worker's exception (if any) after both threads finish.
    """
    import threading
    if tol is None:
        tol = _simple_tol_default()

    err = [None, None]
    res = [None, None]   # (converged, iters) per fluid for the B1 profiler
    _prof = _prof_3d_enabled()
    _t0 = _time.perf_counter() if _prof else None

    def _solve_A():
        try:
            res[0] = sA.solve(max_iter=max_iter, tol=tol, verbose=False,
                              cancel_check=cancel_check)
        except Exception as e:
            err[0] = e

    def _solve_B():
        try:
            res[1] = sB.solve(max_iter=max_iter, tol=tol, verbose=False,
                              cancel_check=cancel_check)
        except Exception as e:
            err[1] = e

    tA = threading.Thread(target=_solve_A, daemon=True)
    tB = threading.Thread(target=_solve_B, daemon=True)
    tA.start(); tB.start()
    tA.join();  tB.join()

    if _prof:
        _dt = _time.perf_counter() - _t0
        _log.info(f"[PROF] initial SIMPLE (A||B parallel) {_dt:7.2f}s  "
                  f"A={res[0]}  B={res[1]}  (cap={max_iter})")
        _prof_res_trace("initial SIMPLE_A", sA)
        _prof_res_trace("initial SIMPLE_B", sB)

    if err[0] is not None:
        raise err[0]
    if err[1] is not None:
        raise err[1]
    # Both threads may have broken early on cancel; surface it as the same
    # InterruptedError the outer loop uses so the worker treats it as a cancel.
    if cancel_check is not None and cancel_check():
        raise InterruptedError("compute cancelled by user")
    return res    # [(converged_A, iters_A), (converged_B, iters_B)|None]


R_AIR = 287.05
_MAX_OUTER = 5        # outer SIMPLE ↔ LTNE iterations
_OUTER_TOL = 0.5      # K
_ALPHA_T = 0.6

# ── M4 partial-BC closure (experimental, opt-in) ──
# Candidate: partial_B_closure='m4_effective_area', m4_exponent=0.67,
#            m4_eff_mode='sqrt'.
# Default: 'none' (no closure — η_eff ≡ 1, full LTNE).
# DO NOT set as default until Shanghai real-data RMSRE validation passes.
_M4_DEFAULT_EXPONENT = 0.67
_M4_DEFAULT_MODE = 'sqrt'


def _conservation_diagnostics_3d(Ta, Tb, Ts, h_vA_field, h_vB_field,
                                 sA, sB, fA, fB, dx, dy, dz):
    """Energy + mass conservation diagnostics for a converged 3D solve
    (extracted from _run_3d_stack, 2026-06-09 F1). Returns a dict:
    domain-total balances (Q_sA/Q_sB/Q_net/energy_rel/mass_rel_A/mass_rel_B)
    + BC-layer-excluded interior-corrected metrics (Q_sA_interior /
    Q_sB_interior / Q_interior_primary / AB_interior). Always computed so the
    user spots non-physical regressions without re-running validation; any
    failure warns + reports NaN (never silently swallowed)."""
    try:
        from solvers.ltne_energy_3d import energy_balance_3d, mass_balance_3d
        e_bal = energy_balance_3d(Ta, Tb, Ts, h_vA_field, h_vB_field, dx, dy, dz)
        Q_sA = e_bal['Q_sA']
        Q_sB = e_bal['Q_sB']
        Q_net = e_bal['Q_net']
        energy_rel = abs(Q_net) / (abs(Q_sA) + abs(Q_sB) + 1e-30)
        m_bal_A = mass_balance_3d(
            sA.u, sA.v, sA.w, sA.rho_field, sA.dy, sA.dx, sA.dz, 2)
        mass_rel_A = m_bal_A.get('rel', 0.0)
        mass_rel_B = 0.0
        if sB is not None:
            m_bal_B = mass_balance_3d(
                sB.u, sB.v, sB.w, sB.rho_field, sB.dy, sB.dx, sB.dz, 2)
            mass_rel_B = m_bal_B.get('rel', 0.0)
    except Exception as _e:
        # Surface the failure instead of nan-ing it away silently: these
        # diagnostics exist precisely to flag non-physical regressions, so a
        # swallowed exception here would hide the very thing they watch for.
        import warnings as _w
        _w.warn(f"3D conservation diagnostics failed ({_e!r}); reporting NaN.",
                stacklevel=2)
        Q_sA = Q_sB = Q_net = energy_rel = mass_rel_A = mass_rel_B = float('nan')

    # Path 0' (v3): exclude the BC inlet/outlet layer, where Ta pinned at T_in
    # creates artificial h_v·(Ts-T_in) source terms (|Q_sA|_total over-reads
    # ~28%). Interior-corrected metric recovers the physical Q.
    try:
        Nx_g, Ny_g, Nz_g = Ta.shape
        cell_vol = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]
        integ_A = h_vA_field * (Ts - Ta) * cell_vol
        integ_B = h_vB_field * (Ts - Tb) * cell_vol

        def _bc_face_mask(dir_code, NxG, NyG, NzG):
            m = np.zeros((NxG, NyG, NzG), dtype=bool)
            sl = [slice(None)] * 3
            sl[_stream_axis(dir_code)] = _inlet_index(dir_code)
            m[tuple(sl)] = True
            return m

        def _outlet_mask(dir_code, NxG, NyG, NzG):
            m = np.zeros((NxG, NyG, NzG), dtype=bool)
            sl = [slice(None)] * 3
            sl[_stream_axis(dir_code)] = _outlet_index(dir_code)
            m[tuple(sl)] = True
            return m

        bc_A_in  = _bc_face_mask(fA['dir'], Nx_g, Ny_g, Nz_g)
        bc_A_out = _outlet_mask(fA['dir'], Nx_g, Ny_g, Nz_g)
        bc_A = bc_A_in | bc_A_out
        Q_sA_interior = float(np.sum(integ_A[~bc_A]))

        if fB is not None:
            bc_B_in  = _bc_face_mask(fB['dir'], Nx_g, Ny_g, Nz_g)
            bc_B_out = _outlet_mask(fB['dir'], Nx_g, Ny_g, Nz_g)
            bc_B = bc_B_in | bc_B_out
            Q_sB_interior = float(np.sum(integ_B[~bc_B]))
        else:
            Q_sB_interior = 0.0

        Q_interior_primary = 0.5 * (abs(Q_sA_interior) + abs(Q_sB_interior)) \
            if Q_sB_interior != 0.0 else abs(Q_sA_interior)
        AB_interior = (abs(abs(Q_sA_interior) - abs(Q_sB_interior))
                       / max(abs(Q_sA_interior), abs(Q_sB_interior), 1e-30))
    except Exception as _e:
        import warnings as _w
        _w.warn(f"3D interior-corrected Q diagnostics failed ({_e!r}); "
                f"reporting NaN.", stacklevel=2)
        Q_sA_interior = Q_sB_interior = Q_interior_primary = float('nan')
        AB_interior = float('nan')

    return dict(
        Q_sA=Q_sA, Q_sB=Q_sB, Q_net=Q_net, energy_rel=energy_rel,
        mass_rel_A=mass_rel_A, mass_rel_B=mass_rel_B,
        Q_sA_interior=Q_sA_interior, Q_sB_interior=Q_sB_interior,
        Q_interior_primary=Q_interior_primary, AB_interior=AB_interior)


def _run_3d_stack(cfg):
    """Unified 3D stack: SIMPLE3D (A) + frozen Tb + LTNE3D.

    Supports fluid-A streamwise direction ∈ {+x, -x, +y, -y} and partial
    inlet/outlet in the cross-stream dimension (z-partial optional via
    `in_z_ctr`/`in_z_w` etc. in `fluid_A_cfg`).

    Sweep profiles (cfg['sweep_profile']):
      'fast_sweep'    — 15³ grid, _MAX_OUTER=3, max_iter=20000, compact diag
      'full_validate' — cfg grid,  _MAX_OUTER=5, max_iter=50000, full diag
      None (default)  — cfg values, _MAX_OUTER=5, full diagnostic
    """
    # ── Sweep profile resolution ──
    _profile = cfg.get('sweep_profile', None)
    _max_outer = _MAX_OUTER
    _ltne_max_iter = 20000
    _compact_diag = False
    if _profile == 'fast_sweep':
        _max_outer = 3
        _ltne_max_iter = 20000
        _compact_diag = True
        # Override grid to 15³ if user requested larger
        cfg = dict(cfg)  # shallow copy so we don't mutate caller
        cfg['Nx'] = min(cfg.get('Nx', 20), 15)
        cfg['Ny'] = min(cfg.get('Ny', 20), 15)
        cfg['Nz'] = min(cfg.get('Nz', 20), 15)
    elif _profile == 'full_validate':
        _max_outer = 5
        _ltne_max_iter = 50000
        _compact_diag = False
    # else: use module-level defaults, full diagnostic
    # R3 (2026-07-07): an explicit SolverConfig knob outranks the sweep-
    # profile preset (a user-set value is more specific than a profile);
    # None keeps the resolution above bit-identically.
    if cfg.get('max_outer_ltne') is not None:
        _max_outer = int(cfg['max_outer_ltne'])
        # 0 used to fall through and blow up far downstream with an opaque
        # `TypeError: unsupported operand type(s) for -: 'NoneType' and
        # 'NoneType'` (nothing was ever solved, so the field vars stayed None).
        # Fail loud, here, with the reason. `1` stays legal as an explicit
        # single-pass SCREENING mode — it cannot converge by construction and
        # now honestly reports solver_converged=False. The typed production
        # boundary (ComputeConfig.validate) rejects anything < 2 outright.
        if _max_outer < 1:
            raise ValueError(
                f"max_outer_ltne={_max_outer} — must be >= 1. Zero outer "
                "iterations solves nothing; the run has no result to report.")
    _outer_tol = (float(cfg['outer_tol_K'])
                  if cfg.get('outer_tol_K') is not None else _OUTER_TOL)

    # Compressible validity-envelope mode (robustness, 2026-06-25):
    #   'raise' (default) -> ChokedFlowError on a choked/supersonic case
    #   'warn'            -> run anyway, flag the result invalid + collect msgs
    #   'off'             -> legacy silent behaviour
    _env_mode = cfg.get('envelope_mode', 'raise')
    _env_warnings = []
    # Track SIMPLE non-convergence across the outer loop so it can be surfaced
    # as a user warning (the 2D pipeline already does; 3D used to only print it
    # under the profiler). Each entry: "A@outer3" etc.
    _simple_nonconv = []

    _ltne_info = []  # per-outer {outer, iters, converged, residual}

    L, H, Lz = cfg['L'], cfg['H'], cfg['Lz']
    Nx_u, Ny_u, Nz_u = cfg['Nx'], cfg['Ny'], cfg['Nz']
    u_A = cfg['u_A']
    T_inA, T_inB = cfg['T_inA'], cfg['T_inB']
    P_inA = cfg['P_inA']
    P_inB = cfg.get('P_inB', P_inA)
    tpms_type = cfg['tpms_type']
    Lcell, t_wall, k_s = cfg['Lcell'], cfg['t_wall'], cfg['k_s']
    eps = cfg['eps']
    fA = cfg['fluid_A_cfg']
    wall_refine = cfg.get('wall_refine_3d', False)

    # 2026-05-13 — derive D_h locally so roughness helpers can compute Re.
    _g_3d = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
    D_h = _g_3d['D_h']

    # Grid: uniform user spacing, or 6-wall BL refinement (see _build_grid_3d).
    dx, dy, dz, Nx, Ny, Nz = _build_grid_3d(
        wall_refine, L, H, Lz, Nx_u, Ny_u, Nz_u)

    # robustness-hardening (2026-07-03): hard cell cap. The UI has a
    # Yes/No dialog at >100k cells, but the script/optimizer path reached
    # here unguarded — 200³ = 8M cells × ~50 float64 arrays + AMG
    # hierarchies is an OOM, not a slow run. Override deliberately via
    # TPMSHX_MAX_CELLS_3D (or cfg['max_cells_3d']) when you actually have
    # the RAM.
    _cell_cap = int(cfg.get('max_cells_3d',
                            os.environ.get('TPMSHX_MAX_CELLS_3D',
                                           '2000000')))
    _n_cells = Nx * Ny * Nz
    if _n_cells > _cell_cap:
        raise ValueError(
            f"3D grid {Nx}x{Ny}x{Nz} = {_n_cells:,} cells exceeds the "
            f"{_cell_cap:,}-cell cap (~{_n_cells * 50 * 8 / 1e9:.1f} GB "
            f"working memory). Reduce the grid, or raise the cap "
            f"deliberately via TPMSHX_MAX_CELLS_3D / cfg['max_cells_3d'].")

    # Resolve streamwise geometry from dir_A
    axis_map = _resolve_axis_map(fA, Nx, Ny, Nz, L, H, Lz, dx, dy, dz)
    is_x_stream = axis_map['is_x_stream']
    is_y_stream = axis_map['is_y_stream']
    is_z_stream = axis_map['is_z_stream']
    is_reverse = axis_map['is_reverse']
    N_cross1, N_cross2 = axis_map['N_cross1'], axis_map['N_cross2']
    L_cross1, L_cross2 = axis_map['L_cross1'], axis_map['L_cross2']
    L_stream = axis_map['L_stream']
    dcross1, dcross2 = axis_map['dcross1'], axis_map['dcross2']
    stream_real_axis = axis_map['stream_real_axis']
    solver_init = axis_map['solver_init']
    N_stream = axis_map['N_stream']
    solver_to_real_perm = axis_map['solver_to_real_perm']
    # Back-compat: L_cross alias for mass-flow area calc (uses both cross axes)
    L_cross = axis_map['L_cross']

    # Fluid A properties at inlet — via the registry (parity with side B, B1 1.1).
    # air: rho=air_density(T,P), cp/mu/k ignore P (value-identical to the old
    # air_* calls → golden-safe). sco2: real-gas (T,P). water-A stays blocked
    # (needs validation; 703 never uses water as Fluid A).
    fluid_type_A = cfg.get('fluid_type_A', 'air')
    if fluid_type_A == 'water':
        raise NotImplementedError(
            "Water Fluid A not yet implemented (needs incompressible SIMPLE A path)")
    _mA = fluid_props.get(fluid_type_A)
    rho_A = float(_mA.rho(T_inA, P_inA))
    mu_A = float(_mA.mu(T_inA, P_inA))
    cp_A = float(_mA.cp(T_inA, P_inA))
    k_A = float(_mA.k(T_inA, P_inA))

    # D-F surrogate. SIMPLE3D K_arr/cF_arr shape = (Ny_sA, Nz) where Ny_sA
    # is the solver streamwise axis = N_stream in real coords.
    # If zones enabled: per-cell K/cF via 2D grid zones broadcast over z.
    zone_cells = cfg.get('zone_grid_cells')
    L_mm_field = None      # (Nx, Ny, Nz) for vis; None → uniform Lcell later
    t_field_3d = None      # per-cell wall thickness
    eps_field_3d = None    # per-cell porosity if zoned
    if zone_cells:
        L_mm_field, t_field_3d, eps_field_3d = _build_zone_fields_3d(
            zone_cells, Nx, Ny, Nz, L, H, tpms_type, k_s, Lcell, t_wall)
        from df_surrogate.predict import predict_K_cF_vec
        K_field_3d, cF_field_3d = predict_K_cF_vec(
            tpms_type, L_mm_field, t_field_3d, eps_field_3d / 2.0)
        # Real → solver coord permutation (inverse equals same tuple for 2-swaps),
        # then mean over solver Nx axis (cross1) → (N_stream, N_cross2) for K_arr.
        K_sol = K_field_3d.transpose(solver_to_real_perm)
        cF_sol = cF_field_3d.transpose(solver_to_real_perm)
        K_A_arr = np.ascontiguousarray(K_sol.mean(axis=0))
        cF_A_arr = np.ascontiguousarray(cF_sol.mean(axis=0))
        K_pred = float(K_A_arr.mean())
        cF_pred = float(cF_A_arr.mean())
        _log.info(f"[3D zones] using {len(zone_cells)} zone cells; "
                  f"K range [{K_field_3d.min():.2e}, {K_field_3d.max():.2e}]")
        # Zoned path is a uniform-only-δ exception: no asymmetric split here.
        K_pred_B, cF_pred_B = K_pred, cF_pred
    else:
        K0, cF0 = predict_K_cF(tpms_type, Lcell, t_wall, 0.5 * eps)
        # Per-side asymmetric D-F κ correction (offset-isosurface δ). κ=1 when
        # δ=0 / disabled / no-CFD-table → K_pred_B==K_pred==K0 (bit-identical).
        # κ multiplies the symmetric baseline output; backend (gamma_df/rbf)
        # and predict_K_cF signature are untouched.
        _split_A = _asym_split_A(cfg, tpms_type, Lcell, t_wall)
        _eps_sym = 0.5 * eps
        _kKA, _kcFA = kappa_KcF(tpms_type, eps * _split_A, _eps_sym)
        _kKB, _kcFB = kappa_KcF(tpms_type, eps * (1.0 - _split_A), _eps_sym)
        K_pred, cF_pred = K0 * _kKA, cF0 * _kcFA
        K_pred_B, cF_pred_B = K0 * _kKB, cF0 * _kcFB
        K_A_arr = np.full((N_stream, N_cross2), K_pred)
        cF_A_arr = np.full((N_stream, N_cross2), cF_pred)

    # 2026-05-13 — apply UI roughness correction (norris_1a default) to K_A,
    # cF_A. Air side only; water skipped (the per-topology water fit
    # (`nu_water_topo`) embeds AM roughness).
    K_A_arr, cF_A_arr = _apply_roughness_KcF(
        K_A_arr, cF_A_arr, fluid_type_A, rho_A, mu_A, u_A, D_h)
    # sCO2: Forchheimer cF needs the D-7-6 effective scale (×3.39). Roughness is
    # already skipped for sco2 (embeds_roughness), so this is the sole cF lift.
    # Diamond-only, like nu_sco2_topo. Scale both the field and the seed scalar.
    if fluid_type_A == 'sco2':
        cF_A_arr = cF_A_arr * SCO2_CF_SCALE
        cF_pred = cF_pred * SCO2_CF_SCALE

    # P_ref_abs 1D closed-form seed (uses streamwise length L_stream).
    solver_fluid_type_A = fluid_props.flow_model(fluid_type_A)
    G_A = rho_A * u_A
    # C = μG/K + cF·G² where G = ρu (mass flux, constant along pipe by continuity).
    C_est = mu_A * G_A / max(K_pred, 1e-16) + cF_pred * G_A * G_A
    if _mA.compressible:
        # P² compressible (ideal-gas) seed; only air-A can choke.
        P_out_sq = P_inA ** 2 - 2.0 * R_AIR * T_inA * C_est * L_stream
        P_ref_A = _seed_p_ref(P_out_sq, P_inA, mode=_env_mode,
                              warn_list=_env_warnings, context='fluid A inlet seed')
    else:
        # sco2 Phase-A is incompressible (ρ frozen) → simple 1D Darcy-Forchheimer
        # pressure-drop seed sets the gauge level; no choke path.
        P_ref_A = max(float(P_inA - C_est * L_stream / rho_A), 1.0e4)

    # Partial inlet / outlet on the 2-axis inlet face.
    in_mask_2d, out_mask_2d = _build_partial_masks(
        fA, dcross1, dcross2, N_cross1, N_cross2, is_reverse)
    v_inlet_field = np.where(in_mask_2d > 0.5, u_A, 0.0).astype(np.float64)

    # ── SIMPLE A (3D, compressible) — BUILD ONLY ──
    # E1: under wall_refine, feed the refined non-uniform spacing (permuted to
    # solver axes) so SIMPLE solves on the same grid the LTNE stage uses. For
    # the uniform default these stay None → solver builds uniform (unchanged).
    _sdxA = _sdyA = _sdzA = None
    if wall_refine:
        _sdxA, _sdyA, _sdzA = _solver_spacings(dx, dy, dz, solver_to_real_perm)
    sA = SIMPLESolver3D(
        **solver_init,
        rho=rho_A, mu=mu_A, T_in=T_inA, v_inlet=v_inlet_field,
        eps=eps, K_arr=K_A_arr, cF_arr=cF_A_arr,
        P_ref_abs=P_ref_A, fluid_type=solver_fluid_type_A,
        dx_arr=_sdxA, dy_arr=_sdyA, dz_arr=_sdzA,
    )
    # Phase A/B/C acceleration flags (Phase A on by default; B/C opt-in).
    _apply_accel_flags(sA, cfg)
    sA.inlet_frac = in_mask_2d
    sA.outlet_frac = out_mask_2d
    # Zoned ε → push to SIMPLE so its continuity ∇·(ε·ρ·u)=0 picks up the
    # ∇ε contribution. Uniform ε leaves the default unchanged.
    if eps_field_3d is not None:
        eps_sol = np.ascontiguousarray(
            eps_field_3d.transpose(axis_map['solver_to_real_perm'])
            if axis_map['solver_to_real_perm'] != (0, 1, 2)
            else eps_field_3d, dtype=np.float64)
        if eps_sol.shape == sA.eps_field.shape:
            sA.eps_field = eps_sol
            sA._mu_eff_field = np.ascontiguousarray(
                sA.mu_field / sA.eps_field, dtype=np.float64)
    sA.apply_outlet_taper(n_taper=8, min_frac=0.2)
    sA.outlet_frac = (sA.outlet_frac * out_mask_2d).astype(np.float64)
    # outlet_mask_ij auto-synced by @outlet_frac.setter (commit 44800ba).
    # A.solve() deferred — build B first then run both in parallel threads.

    # (Fluid A type already resolved + validated near the A-property block;
    # sCO2-A is now supported, water-A still blocked there.)

    # ── Fluid B: cross-flow SIMPLE — BUILD ONLY (solve in parallel with A) ──
    fB = cfg.get('fluid_B_cfg')
    fluid_type_B = cfg.get('fluid_type_B', 'air')
    is_water_B = fluid_type_B == 'water'
    # B1 1.1: property primitives + flow model for side B via the registry
    # (frozen-B / stiffness semantics keep using is_water_B).
    _mB = fluid_props.get(fluid_type_B)
    sB = None
    sB_info = None
    if fB is not None:
        u_B = cfg.get('u_B', u_A)
        rho_B = float(_mB.rho(T_inB, P_inB))   # water rho ignores P; sco2 (T,P)
        mu_B = float(_mB.mu(T_inB, P_inB))     # air/water ignore P; sco2 needs P
        axis_map_B = _resolve_axis_map(fB, Nx, Ny, Nz, L, H, Lz, dx, dy, dz)
        is_x_stream_B = axis_map_B['is_x_stream']
        is_y_stream_B = axis_map_B['is_y_stream']
        is_z_stream_B = axis_map_B['is_z_stream']
        is_reverse_B = axis_map_B['is_reverse']
        N_stream_B = axis_map_B['N_stream']
        N_cross2_B = axis_map_B['N_cross2']
        L_stream_B = axis_map_B['L_stream']
        dcross1_B = axis_map_B['dcross1']; dcross2_B = axis_map_B['dcross2']
        perm_B = axis_map_B['solver_to_real_perm']
        K_B_arr = np.full((N_stream_B, N_cross2_B), K_pred_B)
        cF_B_arr = np.full((N_stream_B, N_cross2_B), cF_pred_B)
        # 2026-05-13 — apply UI roughness correction to K_B / cF_B. Skip for
        # water (the per-topology water fit (`nu_water_topo`) embeds AM
        # roughness; double-counting would over-predict friction).
        K_B_arr, cF_B_arr = _apply_roughness_KcF(
            K_B_arr, cF_B_arr, fluid_type_B,
            rho_B, mu_B, u_B, D_h)
        # sCO2 B side: same D-7-6 effective-cF scale as A (×3.39); roughness
        # already skipped (embeds_roughness). Scale field + seed scalar.
        if fluid_type_B == 'sco2':
            cF_B_arr = cF_B_arr * SCO2_CF_SCALE
            cF_pred_B = cF_pred_B * SCO2_CF_SCALE
        G_B = rho_B * u_B
        C_B = mu_B * G_B / max(K_pred_B, 1e-16) + cF_pred_B * G_B * G_B
        solver_fluid_type_B = fluid_props.flow_model(fluid_type_B)
        if _mB.compressible:
            P_out_sq_B = P_inB ** 2 - 2.0 * R_AIR * T_inB * C_B * L_stream_B
            # Only an ideal-gas (air) B side can choke; water B is incompressible.
            _b_mode = _env_mode if solver_fluid_type_B == 'ideal_gas' else 'off'
            P_ref_B = _seed_p_ref(P_out_sq_B, P_inB, mode=_b_mode,
                                  warn_list=_env_warnings,
                                  context='fluid B inlet seed')
        else:
            P_ref_B = float(P_inB - C_B * L_stream_B / rho_B)
            P_ref_B = max(P_ref_B, 1.0e4)
        in_mask_B, out_mask_B = _build_partial_masks(
            fB, dcross1_B, dcross2_B,
            axis_map_B['N_cross1'], axis_map_B['N_cross2'], is_reverse_B)
        v_inlet_B = np.where(in_mask_B > 0.5, u_B, 0.0).astype(np.float64)
        # Zoned ε for sB: same eps_field but transposed via B's perm (built
        # below after sB construction).
        _sdxB = _sdyB = _sdzB = None
        if wall_refine:
            _sdxB, _sdyB, _sdzB = _solver_spacings(dx, dy, dz, perm_B)
        sB = SIMPLESolver3D(
            **axis_map_B['solver_init'],
            rho=rho_B, mu=mu_B, T_in=T_inB, v_inlet=v_inlet_B,
            eps=eps, K_arr=K_B_arr, cF_arr=cF_B_arr,
            P_ref_abs=P_ref_B, fluid_type=solver_fluid_type_B,
            dx_arr=_sdxB, dy_arr=_sdyB, dz_arr=_sdzB,
        )
        # Mirror Phase A/B/C flags onto sB (sweep config consistent with sA).
        _apply_accel_flags(sB, cfg)
        sB.inlet_frac = in_mask_B
        sB.outlet_frac = out_mask_B
        # Zoned ε for sB.
        if eps_field_3d is not None:
            eps_sol_B = np.ascontiguousarray(
                eps_field_3d.transpose(axis_map_B['solver_to_real_perm'])
                if axis_map_B['solver_to_real_perm'] != (0, 1, 2)
                else eps_field_3d, dtype=np.float64)
            if eps_sol_B.shape == sB.eps_field.shape:
                sB.eps_field = eps_sol_B
                sB._mu_eff_field = np.ascontiguousarray(
                    sB.mu_field / sB.eps_field, dtype=np.float64)
        sB.apply_outlet_taper(n_taper=8, min_frac=0.2)
        sB.outlet_frac = (sB.outlet_frac * out_mask_B).astype(np.float64)
        # outlet_mask_ij auto-synced by @outlet_frac.setter (commit 44800ba).
        # sB.solve deferred — dispatched with sA below in parallel threads.
        sB_info = dict(
            axis_map=axis_map_B,
            u_B=u_B, rho_B=rho_B, mu_B=mu_B,
            G_B=G_B, T_inB=T_inB,
        )
        # ── Parallel SIMPLE A + B solve (threads, njit releases GIL) ──
        # SolverConfig propagation (2026-07-12): this call used to pass NEITHER
        # max_iter NOR tol, so the dual-fluid INITIAL solve silently fell back
        # to the helper's signature defaults (max_iter=2000, tol=None →
        # _simple_tol_default() with cfg=None, which skips the cfg['tol_simple']
        # branch). Only the A-alone branch below and the `post` re-solves obeyed
        # SolverConfig — i.e. a user-set max_iter_simple / tol_simple governed
        # every SIMPLE solve EXCEPT the first one. Same resolution helpers as
        # the A-alone branch, so a config leaving both knobs at None (and no
        # TPMSHX_SIMPLE_TOL) is bit-identical to before.
        _init_res = _run_two_simple_parallel(
            sA, sB,
            max_iter=_simple_max_iter(cfg, 2000),
            tol=_simple_tol_default(cfg),
            cancel_check=cfg.get('_cancel_check'))
        if _init_res and _init_res[0] is not None and not _init_res[0][0]:
            _simple_nonconv.append(
                f"A@init[{getattr(sA, 'exit_reason', '?')}]")
        if _init_res and _init_res[1] is not None and not _init_res[1][0]:
            _simple_nonconv.append(
                f"B@init[{getattr(sB, 'exit_reason', '?')}]")
        # LTNE fluid B velocity: full vector remapped to real coordinates.
        ucB, vcB, wcB = _solver_velocity_to_real(
            sB, axis_map_B, (Nx, Ny, Nz))
        Tb_presc = None  # let LTNE solve Tb from convection
    else:
        # No B: run A alone (serial)
        _prof_t_a0 = _time.perf_counter() if _prof_3d_enabled() else None
        _a0_conv, _a0_it = sA.solve(max_iter=_simple_max_iter(cfg, 2000),
                                    tol=_simple_tol_default(cfg),
                                    verbose=False,
                                    cancel_check=cfg.get('_cancel_check'))
        if not _a0_conv:
            _simple_nonconv.append(
                f"A@init[{getattr(sA, 'exit_reason', '?')}]")
        if _prof_t_a0 is not None:
            _log.info(f"[PROF] initial SIMPLE_A (serial, no-B) "
                      f"{_time.perf_counter()-_prof_t_a0:7.2f}s  "
                      f"iters={_a0_it}  conv={_a0_conv}  (cap=2000)")
        ucB = np.zeros((Nx, Ny, Nz))
        vcB = np.zeros((Nx, Ny, Nz))
        wcB = np.zeros((Nx, Ny, Nz))
        Tb_presc = np.full((Nx, Ny, Nz), T_inB, dtype=np.float64)

    # LTNE inputs — Fluid A and B via the registry. air/water ignore P
    # (value-identical); sco2 needs P (real-gas).
    cp_B = _mB.cp(T_inB, P_inB)
    k_B = float(_mB.k(T_inB, P_inB))
    rho_B_ltne = float(_mB.rho(T_inB, P_inB))   # water rho ignores P; sco2 (T,P)
    eps_arr = (eps_field_3d.copy() if eps_field_3d is not None
               else np.full((Nx, Ny, Nz), eps))
    # Per-cell single-channel void fraction (#2/#3). When zoned, eps varies
    # with (L, t) over space, so K_ffA/B and K_ss must track local eps too.
    eps_f_arr = eps_arr / 2.0
    # Per-side (asymmetric offset-isosurface δ) single-channel void fractions.
    # δ=0 → both are the symmetric eps_f_arr object (bit-identical legacy path);
    # δ≠0 → geometry-derived A:B split preserving total eps_arr. Threaded into
    # the LTNE kernel (eps_A/eps_B), Q/dP extraction and balance projection.
    eps_fA_arr, eps_fB_arr = _eps_sides_for_run(
        cfg, tpms_type, Lcell, t_wall, eps_arr, eps_f_arr)
    K_ffA = eps_fA_arr * k_A
    K_ffB = eps_fB_arr * k_B
    # Optional thermal dispersion: K_disp = C * ρ·cp·|u|·D_h added to K_ff.
    # Off by default (disp_C_* = 0). Standard homogenisation has K_ff = ε·k_f
    # (molecular only); at high Pe the effective fluid conductivity is larger
    # due to tortuous-channel mixing. Turn on by setting disp_C_A / disp_C_B
    # in the config (typical values 0.05-0.3 depending on TPMS type). D_h
    # here uses the uniform cell geometry; once zoned K-field support lands,
    # promote this to per-cell using local D_h and |u|.
    disp_C_A = float(cfg.get('disp_C_A', 0.0))
    disp_C_B = float(cfg.get('disp_C_B', 0.0))
    if disp_C_A > 0.0:
        D_h_A = tpms_geometry(tpms_type, Lcell, t_wall, k_s)['D_h']
        K_disp_A = disp_C_A * rho_A * cp_A * abs(u_A) * D_h_A
        K_ffA = K_ffA + K_disp_A
    if disp_C_B > 0.0:
        D_h_B = tpms_geometry(tpms_type, Lcell, t_wall, k_s)['D_h']
        K_disp_B = disp_C_B * rho_B_ltne * cp_B * abs(cfg.get('u_B', u_A)) * D_h_B
        K_ffB = K_ffB + K_disp_B
    # K_ss = χ_s(type, ε) · (1 − eps_local) · k_s, tracks zoned porosity (#3).
    # B2 (2026-07-06): χ_s from unit-cell homogenization fit (chi_s_eff).
    from solvers.tpms_calc import chi_s_eff as _chi_s_eff
    K_ss = _chi_s_eff(tpms_type, eps_arr) * (1.0 - eps_arr) * k_s

    # h_v from Nu correlation. Per-cell when zoned (#4): tpms_compute uses
    # local (Lcell_ij, t_wall_ij) so A_0, H_sf track the design field.
    # Uniform case reduces to the old scalar path.
    from solvers.tpms_calc import compute as tpms_compute
    from solvers.nu_correlations import NU_LAM_FLOOR as _NU_LAM_FLOOR  # Hagen-Poiseuille single-tube limit
    u_B_val = cfg.get('u_B', u_A)

    def _fluid_transport_props(fluid_type, T_side, P_side):
        m = fluid_props.get(fluid_type)
        # air/water ignore P (value-identical to the old T-only calls → golden-
        # safe); sco2 is real-gas and REQUIRES P.
        rho = float(m.rho(T_side, P_side))
        mu = float(m.mu(T_side, P_side))
        k_f = float(m.k(T_side, P_side))
        if not m.compressible:               # water/sco2: Pr-substitution (3D: k guard)
            Pr_f = float(m.cp(T_side, P_side)) * mu / max(k_f, 1e-30)
            return rho, mu, k_f, Pr_f
        return rho, mu, k_f, None

    def _nu_for_fluid(fluid_type, Re_val, eps_f_val, L_mm_val, D_h_mm_val, Pr_val=None):
        Re_eff = max(float(Re_val), 1.0)
        m = fluid_props.get(fluid_type)
        # water: Pr-substitution with 7.0 fallback; air ignores Pr (built-in default).
        Pr = float(Pr_val if Pr_val is not None else 7.0) if not m.compressible else None
        Nu_val = m.nu(tpms_type, Re_eff, float(eps_f_val), float(L_mm_val),
                      float(D_h_mm_val), Pr)
        return max(float(Nu_val), _NU_LAM_FLOOR)

    def _build_hv_field_3d(L_fld, t_fld, u_side, T_side, P_side, fluid_type='air'):
        """Bulk h_v = A_0(L,t) × H_sf(Re_bulk) on 3D mesh."""
        if L_fld is None:
            if fluid_type == 'air':
                g = tpms_compute(tpms_type, Lcell, t_wall, u_side, T_side, P_side, k_s)
                return np.full((Nx, Ny, Nz), g['A_0'] * g['H_sf'], dtype=np.float64)
            g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
            rho, mu, k_f, Pr_f = _fluid_transport_props(fluid_type, T_side, P_side)
            D_h_m = max(float(g['D_h']), 1e-12)
            Re_val = rho * max(abs(float(u_side)), 0.0) * D_h_m / max(mu, 1e-30)
            Nu_val = _nu_for_fluid(
                fluid_type, Re_val, float(g['epsilon']) / 2.0,
                Lcell, D_h_m * 1000.0, Pr_f,
            )
            return np.full((Nx, Ny, Nz), g['A_0'] * Nu_val * k_f / D_h_m, dtype=np.float64)
        out = np.empty((Nx, Ny, Nz), dtype=np.float64)
        rho, mu, k_f, Pr_f = _fluid_transport_props(fluid_type, T_side, P_side)
        for i in range(Nx):
            for j in range(Ny):
                for k in range(Nz):
                    Li = float(L_fld[i, j, k])
                    ti = float(t_fld[i, j, k])
                    if fluid_type == 'air':
                        g = tpms_compute(tpms_type, Li, ti, u_side, T_side, P_side, k_s)
                        out[i, j, k] = g['A_0'] * g['H_sf']
                    else:
                        g = tpms_geometry(tpms_type, Li, ti, k_s)
                        D_h_m = max(float(g['D_h']), 1e-12)
                        Re_val = rho * max(abs(float(u_side)), 0.0) * D_h_m / max(mu, 1e-30)
                        Nu_val = _nu_for_fluid(
                            fluid_type, Re_val, float(g['epsilon']) / 2.0,
                            Li, D_h_m * 1000.0, Pr_f,
                        )
                        out[i, j, k] = g['A_0'] * Nu_val * k_f / D_h_m
        return out

    # Local-Re per-cell h_v (2026-04-25 #B fix).
    # Each cell uses its own |u_local|·D_h·ρ/μ Reynolds → local Nu via
    # tpms_calc.nu_from_Re → local h_v = A_0·Nu·k/D_h. Wall-BL cells with
    # u_local→0 fall back to laminar Nu floor (4.36) so h_v doesn't blow up
    # to zero (correlation Nu→0 at Re→0 is non-physical extrapolation).
    # This kills the wall-BL stagnation over-count that pushed |Q_sB| above
    # the NTU thermodynamic bound.
    def _build_hv_local_3d(
        L_fld, t_fld, u_field_3d, T_side, P_side, fluid_type='air',
        A_0_scalar=None,
    ):
        """Per-cell h_v using LOCAL |u_cc|·D_h·ρ/μ Reynolds + Nu floor."""
        u_abs = np.abs(u_field_3d) + 1e-12
        # D3 fix (audit 2026-06-28): uniform-geometry sCO2 with a LOCAL T FIELD
        # evaluates ρ,μ,k,Pr per cell instead of freezing them at the scalar
        # inlet T. air/water and the zoned (L_fld not None) path fall through to
        # the scalar-inlet branch below → golden + Shanghai-3D bit-identical.
        # (Iter-0 Ta is None → caller passes scalar T_inA → scalar path, so the
        # first sweep is value-identical; local props kick in from iter 1.)
        if fluid_type == 'sco2' and L_fld is None and np.ndim(T_side) > 0:
            g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
            return _sco2_hv_local_field(T_side, P_side, u_abs,
                                        g['A_0'], g['D_h'], tpms_type)
        rho, mu, k_f, Pr_f = _fluid_transport_props(fluid_type, T_side, P_side)
        if L_fld is None:
            g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
            A_0 = g['A_0']; D_h_m = g['D_h']
            D_h_mm = D_h_m * 1000.0
            Re_loc = rho * u_abs * D_h_m / mu
            # Vectorized Nu over the whole grid. fluid_props .nu forwards to
            # nu_from_Re, which accepts an array Re. This mirrors the scalar
            # _nu_for_fluid path element-for-element (Re pre-floor at 1.0, Nu
            # post-floor at _NU_LAM_FLOOR, single-stream ε_f = ε/2), so it is
            # bit-identical to the prior per-cell triple loop — just Nx·Ny·Nz×
            # fewer Python calls. 2026-06-09 perf B1.
            _m = fluid_props.get(fluid_type)
            _Pr = (None if _m.compressible
                   else float(Pr_f if Pr_f is not None else 7.0))
            Nu_loc = _m.nu(tpms_type, np.maximum(Re_loc, 1.0),
                           g['epsilon'] / 2.0, Lcell, D_h_mm, _Pr)
            Nu_loc = np.maximum(np.asarray(Nu_loc, dtype=np.float64),
                                _NU_LAM_FLOOR)
            H_sf_loc = Nu_loc * k_f / D_h_m
            return A_0 * H_sf_loc
        # Zoned (L,t) varying — recompute geom per cell
        out = np.empty((Nx, Ny, Nz), dtype=np.float64)
        for i in range(Nx):
            for j in range(Ny):
                for k in range(Nz):
                    L_ij = float(L_fld[i, j, k]); t_ij = float(t_fld[i, j, k])
                    g = tpms_geometry(tpms_type, L_ij, t_ij, k_s)
                    D_h_m_l = g['D_h']
                    Re_l = rho * float(u_abs[i,j,k]) * D_h_m_l / mu
                    # single-stream: ε_f = ε/2
                    Nu_l = _nu_for_fluid(
                        fluid_type, Re_l, g['epsilon'] / 2.0,
                        L_ij, D_h_m_l * 1000.0, Pr_f,
                    )
                    out[i,j,k] = g['A_0'] * Nu_l * k_f / D_h_m_l
        return out

    # Per-side h_v geometric multiplier for asymmetric offset-isosurface δ.
    # h_v = A_0·Nu·k/D_h; for δ≠0 each side's (A_0, D_h) shifts. The ratio is
    # taken vs asym_geometry's OWN δ=0 reference (same method) so it is EXACTLY
    # 1.0 at δ=0 → multiplying the existing symmetric h_v is bit-identical
    # (×1.0). k_f cancels; Nu's ε arg is inert (air/water Nu ignore ε); the
    # ratio is u-independent (Re_side/Re_ref = D_h_side/D_h_ref) so it applies
    # equally to the bulk and the later local-Re h_v. Captures the geometric
    # Nu/area effect; the residual (κ_Nu) is a CFD calibration left to
    # ingest_cfd_kappa (Nu is secondary per the Phase-1 plan; dP is primary).
    def _hv_side_geom_ratio(fluid_type, u_side, T_side, P_side, side):
        if float(cfg.get('delta_levelset', 0.0)) == 0.0:
            return 1.0
        from solvers.tpms_geometry import _phi_grid, _C_from_tL
        from solvers import asym_geometry as _ag
        _N = 128
        _phi = _phi_grid(tpms_type, _N)
        _C = _C_from_tL(tpms_type, float(t_wall) / float(Lcell))
        _delta = float(cfg['delta_levelset'])
        _Lm = float(Lcell) / 1000.0
        A0A, A0B = _ag.a0_sides(_phi, _C, _delta, _Lm, _N)
        DhA, DhB = _ag.dh_sides(_phi, _C, _delta, _Lm, _N, mc=True)
        A0A0, A0B0 = _ag.a0_sides(_phi, _C, 0.0, _Lm, _N)
        DhA0, DhB0 = _ag.dh_sides(_phi, _C, 0.0, _Lm, _N, mc=True)
        A0_s, Dh_s, A0_r, Dh_r = ((A0A, DhA, A0A0, DhA0) if side == 'A'
                                  else (A0B, DhB, A0B0, DhB0))
        _rho, _mu, _kf, _Pr = _fluid_transport_props(fluid_type, T_side, P_side)

        def _hv(A0, Dh):
            Dh_m = max(float(Dh), 1e-12)
            Re = _rho * max(abs(float(u_side)), 0.0) * Dh_m / max(_mu, 1e-30)
            Nu = _nu_for_fluid(fluid_type, Re, 0.5 * float(eps),
                               Lcell, Dh_m * 1000.0, _Pr)
            return A0 * Nu / Dh_m
        _ref = _hv(A0_r, Dh_r)
        return (_hv(A0_s, Dh_s) / _ref) if _ref > 0 else 1.0

    _hv_ratio_A = _hv_side_geom_ratio(fluid_type_A, u_A, T_inA, P_inA, 'A')
    _hv_ratio_B = _hv_side_geom_ratio(fluid_type_B, u_B_val, T_inB, P_inB, 'B')

    # Initial bulk h_v (used at outer=0 before SIMPLE solves; becomes local
    # after first outer iter when ucA/B are available).
    h_vA_field = _build_hv_field_3d(
        L_mm_field, t_field_3d, u_A, T_inA, P_inA, fluid_type_A)
    h_vA_field = _apply_roughness_h_v(
        h_vA_field, fluid_type_A, rho_A, mu_A, u_A, D_h)
    h_vA_field = h_vA_field * _hv_ratio_A
    if sB is not None:
        h_vB_field = _build_hv_field_3d(
            L_mm_field, t_field_3d, u_B_val, T_inB, P_inB, fluid_type_B)
        h_vB_field = _apply_roughness_h_v(
            h_vB_field, fluid_type_B, rho_B, mu_B, u_B_val, D_h)
        h_vB_field = h_vB_field * _hv_ratio_B
    else:
        # No B fluid solver → "no B fluid" should mean ZERO B-side coupling,
        # not "infinite reservoir at T_inB". The previous behaviour kept
        # h_vB at the bulk Nu·k/D_h value while Tb_prescribed pinned Tb to
        # T_inB everywhere, so the LTNE source term h_vB·(Ts−Tb) acted as
        # a phantom infinite heat sink/source on the solid. Setting
        # h_vB_field=0 makes the solid energy equation degenerate cleanly
        # to the single-fluid LTNE limit driven only by Q_sA.
        h_vB_field = np.zeros((Nx, Ny, Nz), dtype=np.float64)

    # NOTE on wall-BL homogenization (2026-04-25 NTU audit):
    # Kim/Gyroid Nu correlations fit BULK TPMS-cell flow at Re ≥ 600. Cells
    # adjacent to domain walls have reduced |u| (Brinkman BL), but uniform
    # h_v overstates their contribution to ∫h_v·(Ts-T)·dV → Q_sA exceeds the
    # thermodynamic NTU upper bound by ~5-25% on REFINE grids.
    # Tried local-Re rescaling h ∝ Re^0.6 — h_reduction only 1-3% mean
    # (cell-center u doesn't drop steeply enough on uniform grids; refined
    # grids do but contribution is small). True fix requires BL-specific
    # Nu correlation or conjugate heat transfer at outer walls — research
    # work beyond this audit. Q_enthalpy_A/_B (m·cp·ΔT) remain physically
    # consistent with NTU; mean(Q_A,Q_B) is the user-facing Q.
    # P2: rho_cp as 3D field (not scalar) for per-cell accuracy
    rho_cp_fA = np.full((Nx, Ny, Nz), rho_A * cp_A, dtype=np.float64)
    rho_cp_fB = np.full((Nx, Ny, Nz), rho_B_ltne * cp_B, dtype=np.float64)
    # Default ON (2026-06-09): build the LTNE convective rho_cp from SIMPLE's
    # LOCAL density field ρ(P_local,T) instead of ρ(T,P_inlet). For compressible
    # fluids the kernel then telescopes cp·(ε·ρ_local·u) = cp·(SIMPLE mass flux),
    # so ∮(ε·ρcp·u) ≈ cp·∮(mass flux) ≈ 0 (SIMPLE continuity) and the strict
    # conservative kernel is mass-conserving for COMPRESSIBLE reverse flow too
    # (fixes the air-air reverse ε-NTU/full-face cases). Strict certificate
    # machine-zero on all 6 audit cases; Shanghai bit-identical to the old
    # inlet-P path. Env `TPMSHX_VAR_RHOCP=0/1` is an explicit override; otherwise
    # cfg/flags default True. Set cfg['variable_rho_cp']=False (or uncheck the
    # UI box) to restore the legacy inlet-pressure density.
    _env_vrc = os.environ.get('TPMSHX_VAR_RHOCP')
    if _env_vrc in ('0', '1'):
        _var_rhocp = _env_vrc == '1'
    else:
        _var_rhocp = bool(cfg.get('variable_rho_cp', True))

    # Helper: solver streamwise velocity → correct real component (uc/vc/wc).
    # Transposes solver (Nx_sol, Ny_sol, Nz_sol) → real (Nx, Ny, Nz) via
    # `solver_to_real_perm` (self-inverse for all 3 supported perms), then
    # assigns the streamwise vector to the matching real axis.
    def _assemble_real_velocity():
        return _solver_velocity_to_real(sA, axis_map, (Nx, Ny, Nz))

    # ── Outer SIMPLE ↔ LTNE coupling ──
    Ta = Tb = Ts = None
    # Warm-start delta tracker (shared with the 2D driver). A2 (2026-07-06):
    # gate on ALL THREE temperature fields — the old ('Ta',)-only criterion
    # let Tb/Ts drift unmonitored (a cross-flow B side or slow solid could
    # still be moving when Ta settled).
    _outer_conv = OuterConvergence(tol_T=_outer_tol, track=('Ta', 'Tb', 'Ts'))
    _outer_dT_hist = []   # per-outer-iter {field: max|Δ|} — convergence_detail
    chi_B = None         # B flow-path indicator field (χ_B), built each outer iter
    # Optional solid warm-start seed from the UI. Empty → solver default
    # (Ta=T_inA, Tb=T_inB, Ts=0.5*(T_inA+T_inB) inside solve_full_domain_3d).
    # Filled → only Ts is overridden with the user value; Ta/Tb stay at the
    # per-fluid inlet T (the 2026-04-24 FV fix in solvers/ltne_energy_3d.py
    # showed that 0.5*mean for Ta/Tb leaks into non-pipe inlet cells and
    # breaks energy balance by 20–25% on partial-inlet runs). The solid
    # energy equation still updates Ts each sweep; this is *not* prescribed.
    _Ts_init_user = cfg.get('T_s_init')
    if _Ts_init_user is not None:
        _shape3d = (Nx, Ny, Nz)
        Ta = np.full(_shape3d, float(T_inA), dtype=np.float64)
        Tb = np.full(_shape3d, float(T_inB), dtype=np.float64)
        Ts = np.full(_shape3d, float(_Ts_init_user), dtype=np.float64)
    def _stream_component(uc, vc, wc, dir_code):
        """Streamwise cell-center velocity component (single dir source)."""
        return (uc, vc, wc)[_stream_axis(dir_code)]

    _progress_cb = cfg.get('_progress_cb')
    _cancel_check = cfg.get('_cancel_check')
    _iter_cb = cfg.get('_iter_cb')
    # B2 strict-conservation certificates — assigned each outer iter, read
    # after the loop for the result dict; pre-init so the step closure's
    # `nonlocal` has an enclosing binding (loop always runs ≥1 iter so the
    # None default is dead, but it keeps the scope valid).
    _eps_A_strict = _eps_B_strict = None
    _eps_A_strict_cellmax = _eps_B_strict_cellmax = None
    # LTNE inlet-patch masks — assigned each iter inside the step, read after
    # the loop (χ_B inlet-patch slice + audit dict); pre-init so the step
    # closure's `nonlocal` has an enclosing binding (legacy relied on the
    # loop variable leaking to function scope).
    _ltne_mask_A = _ltne_mask_B = None

    # Outer SIMPLE↔LTNE loop, driven by the shared run_outer_coupling skeleton
    # (3D = LTNE-first: `step` builds props + solves LTNE + checks ΔTa; `post`
    # re-solves SIMPLE A/B with the updated fields for the next iter). The body
    # below is the verbatim former loop body, wrapped so the only `nonlocal`s
    # are the fields that persist across iters or are read after the loop.
    def _outer_step_3d(outer):
        nonlocal Ta, Tb, Ts, chi_B, h_vA_field, h_vB_field, K_ffB
        nonlocal _ltne_mask_A, _ltne_mask_B
        nonlocal _eps_A_strict, _eps_B_strict
        nonlocal _eps_A_strict_cellmax, _eps_B_strict_cellmax
        # Cooperative cancel: only safe boundary is between outer iterations
        # — a JIT'd SIMPLE inner sweep cannot be interrupted. The UI sets the
        # flag via the Cancel button or the wall-clock timeout.
        if _cancel_check is not None and _cancel_check():
            raise InterruptedError("compute cancelled by user")
        if _iter_cb is not None:
            _iter_cb(outer + 1, _max_outer)
        if _progress_cb is not None:
            _progress_cb(10 + int(80 * outer / _MAX_OUTER))
        ucA, vcA, wcA = _assemble_real_velocity()

        # #B fix: rebuild h_v per cell using LOCAL Re (cell-center stream u).
        # Wall cells with |u_local|→0 → Nu_lam floor (4.36) → h_local much
        # smaller than bulk h. Removes wall-BL stagnation over-count.
        u_stream_A = _stream_component(ucA, vcA, wcA, fA['dir'])
        # D3: sCO2 uses the LOCAL temperature field (lagged Ta) for h_v props;
        # iter-0 Ta is None → scalar T_inA (frozen, = old behaviour).
        _T_hvA = Ta if (fluid_type_A == 'sco2' and Ta is not None) else T_inA
        h_vA_field = _build_hv_local_3d(
            L_mm_field, t_field_3d, u_stream_A, _T_hvA, P_inA, fluid_type_A)
        h_vA_field = _apply_roughness_h_v(
            h_vA_field, fluid_type_A, rho_A, mu_A, u_A, D_h)
        h_vA_field = h_vA_field * _hv_ratio_A   # per-side asym geom (1.0 at δ=0)
        # Pre-compute LTNE inlet masks (needed by χ_B block and LTNE solve).
        # approach-(a): the kernel applies the inlet BC at its inlet face using
        # this mask; with the reverse spatial flip + no mask swap, the physical
        # inlet patch is in_mask for BOTH forward and reverse dirs.
        _ltne_mask_A = in_mask_2d
        _ltne_mask_B = None
        if fB is not None:
            _ltne_mask_B = in_mask_B

        if sB is not None:
            u_stream_B = _stream_component(ucB, vcB, wcB, fB['dir'])
            _T_hvB = Tb if (fluid_type_B == 'sco2' and Tb is not None) else T_inB
            h_vB_field = _build_hv_local_3d(
                L_mm_field, t_field_3d, u_stream_B, _T_hvB, P_inB, fluid_type_B)
            h_vB_field = _apply_roughness_h_v(
                h_vB_field, fluid_type_B, rho_B, mu_B, u_B_val, D_h)
            h_vB_field = h_vB_field * _hv_ratio_B   # per-side asym geom (1.0 at δ=0)
            # ── partial-B closure dispatch ──
            # Three options selectable via cfg['partial_B_closure']:
            #   'none'                 — no correction (χ_B ≡ 1; legacy)
            #   'm4_effective_area'    — 0D scalar η_eff (legacy, regression)
            #   'per_cell_chi_b'       — Phase 1 fix (3D field, NEW default-
            #                            recommended for any partial-B run).
            # 2026-05-04 audit (vault/reports/3d-solver/2026-05-04-partial-b-
            # ltne-audit-CN.md) showed the 0D scalar leaks ghost-B diffusion
            # into the active flow channel via ε_f·k_f·∇²Tb, inflating
            # T_B_out 4×. Per-cell approach cuts BOTH source and diffusion
            # path in pure ghost cells (h_vB → 0 AND K_ffB → 0).
            # 2026-05-14: tried 'per_cell_chi_b' default but reverted —
            # at Shanghai partial-B inlet u_B=0.15, χ_B mask was 90.5% active
            # (Brinkman spread water to all cells, mass-flux threshold caught
            # almost none as ghost) AND tightening `chi_B_kernel_threshold`
            # to 0.30 broke discrete mass conservation (m_in 0.208 ≠ m_out
            # 0.222 kg/s, 7% imbalance). Visual ghost-heating in T_B plots
            # is a known-acceptable artefact: production Q reporting uses
            # m_dot·cp·ΔT_face with χ_B-weighted T_out (not domain mean),
            # so the LTNE-internal Q_solid_B figure remains physically
            # correct. UI users should read inlet/outlet face values, not
            # domain colour maps, until partial-B physics is re-examined.
            _closure = cfg.get('partial_B_closure', 'none')
            if _closure == 'm4_effective_area':
                # Legacy 0D scalar — kept for regression comparison.
                _dx_s = sB.dx; _dz_s = sB.dz  # solver cross1, cross2
                _area_2d = _dx_s[:, None] * _dz_s[None, :]
                _A_full = float(np.sum(_area_2d))
                if in_mask_B is not None:
                    _A_in = float(np.sum(_area_2d * (in_mask_B > 0.5)))
                    _r_in = _A_in / max(_A_full, 1e-30)
                    _A_out = float(np.sum(_area_2d * (out_mask_B > 0.5)))
                    _r_out = _A_out / max(_A_full, 1e-30)
                else:
                    _r_in = _r_out = 1.0
                _mode = cfg.get('m4_eff_mode', 'sqrt')
                if _mode == 'min':
                    r_eff = min(_r_in, _r_out)
                else:
                    r_eff = float(np.sqrt(_r_in * _r_out))
                p = float(cfg.get('m4_exponent', 0.67))
                eta_eff = r_eff ** p
                chi_B = np.full((Nx, Ny, Nz), eta_eff, dtype=np.float64)
                h_vB_field = h_vB_field * eta_eff
                # NOTE: legacy path does NOT modify K_ffB — that's exactly
                # the diffusion-leak channel the per-cell path closes.
                if outer == 0:
                    _log.info(f"[M4-legacy] r_in={_r_in:.4f} r_out={_r_out:.4f} "
                              f"mode={_mode} r_eff={r_eff:.4f} "
                              f"p={p} η_eff={eta_eff:.4f}")
            elif _closure == 'per_cell_chi_b':
                # ── Phase 1 fix: per-cell 3D participation field ──
                _method = cfg.get('chi_B_method', 'mass_flux_threshold')
                if _method == 'union_extrude':
                    chi_B = _build_chi_B_union_extrude(
                        fB, dx, dy, dz, (Nx, Ny, Nz),
                        n_taper=int(cfg.get('chi_B_n_taper', 3)))
                elif _method == 'mass_flux_threshold':
                    # Method H8: auto-adaptive based on per-cell mass flux
                    # throughput. Geometry-independent (no u_ref tuning).
                    # 2026-05-14: H8-tightened defaults (thr=0.20, n_dil=1)
                    # were tried but reverted with the parent closure flip;
                    # production default is now 'none' so this branch only
                    # runs when explicitly requested via cfg. Original
                    # permissive defaults (0.05, 2) restored for symmetry
                    # with prior calibration scripts.
                    chi_B = _build_chi_B_mass_flux_threshold(
                        sB, axis_map_B, (Nx, Ny, Nz),
                        threshold_frac=float(cfg.get('chi_B_threshold_frac', 0.05)),
                        n_dilate=int(cfg.get('chi_B_n_dilate', 2)),
                        n_smooth=int(cfg.get('chi_B_n_smooth', 1)),
                        ref_mode=cfg.get('chi_B_mass_ref_mode', 'p75'))
                else:  # 'velocity_threshold' (legacy method, geometry-tuned)
                    chi_B = _build_chi_B_velocity_threshold(
                        ucB, vcB, wcB,
                        threshold_frac=float(cfg.get('chi_B_threshold_frac', 0.5)),
                        u_ref_mode=cfg.get('chi_B_u_ref_mode', 'inlet'),
                        u_inlet=float(u_B),
                        n_dilate=int(cfg.get('chi_B_n_dilate', 3)),
                        n_smooth=int(cfg.get('chi_B_n_smooth', 2)))
                # Floor for stiffness: K_ffB·χ_floor keeps Tb-matrix diagonal
                # non-zero even in pure ghost cells. Heat leak negligible at
                # 1e-3 (1000× attenuation vs bulk K).
                chi_floor = float(cfg.get('chi_B_floor', 1e-3))
                chi_B_eff_K = np.maximum(chi_B, chi_floor)
                # Apply: zero source AND zero diffusion path in pure ghost
                h_vB_field = h_vB_field * chi_B
                K_ffB      = K_ffB      * chi_B_eff_K
                if outer == 0:
                    _part_frac = float(np.sum(chi_B > 0.5)) / chi_B.size
                    _log.info(f"[χ_B] closure=per_cell_chi_b method={_method} "
                              f"min={chi_B.min():.3f} max={chi_B.max():.3f} "
                              f"mean={chi_B.mean():.3f} part_frac={_part_frac:.3f} "
                              f"floor={chi_floor:.1e}")
            else:
                chi_B = np.ones((Nx, Ny, Nz), dtype=np.float64)

        # ── H2 audit hook: zero K_ffB at the real-outlet 1-cell layer ──
        # Diagnostic-only (NOT physics). Tests whether T_B_out hot-spot is
        # driven by lateral diffusion from hot solid into the outlet patch.
        # Activated via cfg['audit_zero_K_ffB_at_outlet']=True. No effect
        # otherwise. See vault/reports/3d-solver/2026-05-04-3d-conservation-
        # spec-CN.md §H2.
        if (cfg.get('audit_zero_K_ffB_at_outlet', False)
                and sB is not None and fB is not None):
            _dir_B = int(fB['dir'])
            _layers = int(cfg.get('audit_h2_n_layers', 1))
            _idx_dict = {0: (0, slice(Nx-_layers, Nx)),
                         1: (0, slice(0, _layers)),
                         2: (1, slice(Ny-_layers, Ny)),
                         3: (1, slice(0, _layers)),
                         4: (2, slice(Nz-_layers, Nz)),
                         5: (2, slice(0, _layers))}
            _ax, _idx = _idx_dict[_dir_B]
            _sl = [slice(None), slice(None), slice(None)]
            _sl[_ax] = _idx
            _sl = tuple(_sl)
            _h2_floor = float(cfg.get('audit_h2_K_floor', 1e-6))
            K_ffB[_sl] = K_ffB[_sl] * 0.0 + _h2_floor * float(np.mean(K_ffB))
            if outer == 0:
                _log.info(f"[H2-audit] K_ffB := {_h2_floor:.0e}·K̄ at outlet "
                          f"axis={_ax} idx={_idx} ({_layers} cell-layer)")

        # Extract SIMPLE's staggered face velocities in REAL coords for the
        # mass-conserving LTNE kernel (2026-04-25 FV#6).
        ufA, vfA, wfA = _solver_staggered_to_real(sA, axis_map, (Nx, Ny, Nz))
        if sB is not None:
            ufB, vfB, wfB = _solver_staggered_to_real(sB, axis_map_B, (Nx, Ny, Nz))
        else:
            ufB = np.zeros((Nx+1, Ny, Nz), dtype=np.float64)
            vfB = np.zeros((Nx, Ny+1, Nz), dtype=np.float64)
            wfB = np.zeros((Nx, Ny, Nz+1), dtype=np.float64)

        # Strict-conservation prerequisite (2026-06-09): enforce discrete global
        # mass balance ∮F·n=0 on the extracted stream-boundary faces so the
        # conservative-LTNE kernel's telescoping sum closes to machine
        # precision. SIMPLE's small continuity residual (amplified by partial-BC
        # + outlet taper on offset/reverse fluids) otherwise leaves a net ΣD the
        # homogeneous-Neumann MAC projection cannot remove → reverse heat-load
        # drift. coef = eps_f·ρcp = 0.5·ε·ρcp matches the projection.
        #
        # INCOMPRESSIBLE ONLY. The kernel telescopes ε·ρcp·u with a CONSTANT
        # ρcp, so enforcing ∮(ε·ρcp·u)=0 means enforcing volume-flux balance
        # ∮(εu)=0. For incompressible flow that IS mass conservation (ρ const).
        # For compressible (ideal-gas) flow mass conservation is ∮(ερu)=0 with
        # ρ=ρ(P,T) varying, so ∮(εu)≠0 is PHYSICAL — forcing it would corrupt
        # the velocity field (measured: air scale 0.58–0.94, +300 % Q error).
        # Compressible reverse-dir conservation is a separate kernel-level
        # (constant-ρcp) limitation, out of scope here.
        if bool(cfg.get('conservative_ltne', True)) and cfg.get('strict_mass_balance', True):
            # Incompressible always; compressible only with variable_rho_cp (then
            # rho_cp = ρ_local·cp matches SIMPLE's conserved mass flux, so the
            # balance scale ≈ 1 and it removes only the residual — see _var_rhocp).
            if (not fluid_props.get(fluid_type_A).compressible) or _var_rhocp:
                # Per-side ε must match the LTNE kernel's eps_fA/eps_fB exactly,
                # else the MAC projection corrupts and reverse-dir Q drift
                # silently returns. δ=0 → eps_fA_arr == eps_arr/2 (identical).
                _coefA = eps_fA_arr * rho_cp_fA
                _balance_stream_outflow([ufA, vfA, wfA], axis_map, _coefA, dx, dy, dz)
            if sB is not None and (
                    (not fluid_props.get(fluid_type_B).compressible) or _var_rhocp):
                _coefB = eps_fB_arr * rho_cp_fB
                _balance_stream_outflow([ufB, vfB, wfB], axis_map_B, _coefB, dx, dy, dz)

        # H6 ghost-pin: pass chi_B_field + threshold to LTNE kernel. At cells
        # where chi_B_field < chi_B_kernel_threshold, kernel skips Tb update
        # (leaves Tb at init = T_inB). Prevents stagnant cells from relaxing
        # to local Ts via h_v and leaking that hot value into mass flow via
        # 1st-order upwind. Default 0.0 = no kernel-level masking.
        # 2026-05-14: 0.30 tightening was tested with the now-reverted
        # 'per_cell_chi_b' default and broke discrete mass conservation
        # (7% imbalance between m_in and m_out). Default restored to 0.0;
        # tuning requires re-validation before re-enabling.
        _chi_B_kernel_thr = float(cfg.get('chi_B_kernel_threshold', 0.0))
        # B-plan B5: strict face-centered energy conservation is now the 3D
        # production default (telescoping aP + face-shared HO + MAC projection).
        # The legacy cell-local-|u_c| kernel remains an explicit fallback via
        # cfg['conservative_ltne']=False.
        _conservative_ltne = bool(cfg.get('conservative_ltne', True))

        # MMS source fields (Air-Air V&V Phase A.1). Default None → no-op.
        # Solver accepts (Nx, Ny, Nz) arrays; volume-integrated source per
        # cell injected into FVM equation RHS. Used by validation/cases/mms_3d_*.py.
        _mms_S_A = cfg.get('mms_S_A_field', None)
        _mms_S_B = cfg.get('mms_S_B_field', None)
        _mms_S_s = cfg.get('mms_S_s_field', None)
        # 2026-05-19 ε contract (Option A — supersedes the wrong 2026-05-14
        # "fix"): pass FULL porosity `eps_arr`. The kernel itself does
        # eps_f = 0.5*epsilon (single halving → ε_A = ε_full/2). The
        # 2026-05-14 change to `eps_f_arr` here double-halved ε to ε_full/4
        # (the "ΔT_A 90→105°C" it celebrated was the BUG, not a fix —
        # half the LTNE fluid heat capacity). K_ffA/K_ffB stay built from
        # eps_f_arr (= ε_A, correct for diffusion); only the convective
        # epsilon arg must be FULL ε.
        _prof_t_ltne = _time.perf_counter() if _prof_3d_enabled() else None
        # Option B gate: sCO2-both-sides counterflow-x with ltne_enthalpy_mode on.
        # sCO2-both (recuperator) OR sCO2 + water (precooler); ≥1 variable-cp
        # sCO2 side. air/water-only stays on the legacy ρcp·u·T path.
        _enth_gate = (bool(cfg.get('ltne_enthalpy_mode', False))
                      and fluid_type_A in ('sco2', 'water')
                      and fluid_type_B in ('sco2', 'water')
                      and (fluid_type_A == 'sco2' or fluid_type_B == 'sco2')
                      and sB is not None
                      and fA['dir'] in (0, 1) and fB['dir'] in (0, 1))
        # When the enthalpy solve will overwrite the result below, run the legacy
        # ρcp·u·T solve for only a couple of sweeps (a cheap warm-start) rather
        # than to full convergence — its Ta/Tb/Ts are discarded.
        _eff_ltne_max_iter = 2 if _enth_gate else _ltne_max_iter
        _ltne_result = solve_full_domain_3d(
            L, H, Lz, Nx, Ny, Nz, T_inA, T_inB,
            K_ffA, K_ffB, K_ss, h_vA_field, h_vB_field,
            rho_cp_fA, rho_cp_fB, eps_arr,
            ucA, vcA, wcA, ucB, vcB, wcB,
            dir_A=fA['dir'],
            dir_B=(fB['dir'] if fB is not None else 3),
            dx_arr=dx, dy_arr=dy, dz_arr=dz,
            inlet_mask_A=_ltne_mask_A,
            inlet_mask_B=_ltne_mask_B,
            Tb_prescribed=Tb_presc, max_iter=_eff_ltne_max_iter, tol=1e-5,
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
            alpha_T=float(cfg.get('ltne_alpha_T', 0.7)),
            # force_cc_ltne: drop face velocities so the LTNE uses the cc
            # (non-stag) advection chunk — same scheme as the V&V'd 2D solver.
            # The face (stag) chunk's SOU uses a cc-reconstructed flux magnitude
            # inconsistent with its face base fluxes, which limit-cycles the
            # deferred correction for stiff low-Re water (point-0 root cause).
            # conservative_ltne (B-plan B2) overrides force_cc_ltne: the strict
            # face-centered conservation form lives in the stag kernel, so the
            # SIMPLE face velocities MUST flow through regardless.
            ufA=(ufA if _conservative_ltne or not cfg.get('force_cc_ltne', True) else None),
            vfA=(vfA if _conservative_ltne or not cfg.get('force_cc_ltne', True) else None),
            wfA=(wfA if _conservative_ltne or not cfg.get('force_cc_ltne', True) else None),
            ufB=ufB, vfB=vfB, wfB=wfB,
            chi_B_field=chi_B,
            chi_B_kernel_threshold=_chi_B_kernel_thr,
            mms_S_A_field=_mms_S_A,
            mms_S_B_field=_mms_S_B,
            mms_S_s_field=_mms_S_s,
            conservative_ltne=_conservative_ltne,
            # Asymmetric per-side ε (offset-isosurface δ). Passed ONLY when δ≠0
            # → δ=0 omits the kwargs → kernel's symmetric 0.5·ε default path →
            # bit-identical. eps_fA/eps_fB are single-channel (already-split)
            # fractions in the same real axes as eps_arr; kernel consumes them
            # without further halving.
            eps_A=(eps_fA_arr if float(cfg.get('delta_levelset', 0.0)) != 0.0
                   else None),
            eps_B=(eps_fB_arr if float(cfg.get('delta_levelset', 0.0)) != 0.0
                   else None),
            cancel_check=_cancel_check,
            return_info=True)
        Ta, Tb, Ts, _ltne_info_d = _ltne_result

        # ── Option B: enthalpy-conservative LTNE for variable-cp sCO2 ──
        # The ρcp·u·T conservative kernel above conserves ρcp·T-energy, which
        # for sCO2 (cp spikes near the pseudocritical line) is NOT the true
        # enthalpy ṁ·h → the 703 recuperator ~41% A/B imbalance / wrong cold
        # outlet. When opted in (`ltne_enthalpy_mode`, default OFF) for an
        # sCO2-both-sides counterflow-x case, replace the result with the
        # enthalpy-form solve (true ṁ·h transport). Default-off + the strict
        # gate keep air/water and every other config bit-identical.
        # (Plan: vault reports/method/3d/2026-06-28-3d-ltne-enthalpy-*.)
        if _enth_gate:
            from solvers.ltne_enthalpy_3d import solve_ltne_enthalpy_3d_pipeline
            _epsps = 0.5 * float(eps)
            # N4 (2026-06-28): under δ≠0 the per-side ṁ must weight by the actual
            # channel void (ε·split), matching the duty-extraction path and the
            # asymmetric eps_A/eps_B fields handed to the kernel. None at δ=0 →
            # symmetric 0.5·ε (every 703/production config; bit-identical).
            _ov_A_e, _ov_B_e = _per_side_eps_override(
                cfg, tpms_type, Lcell, t_wall, eps)
            _mdA = (1.0 if fA['dir'] == 0 else -1.0) * abs(
                _simple_mass_flow(sA, fA['dir'], eps_f_per_side=_epsps,
                                  eps_side_override=_ov_A_e))
            _mdB = (1.0 if fB['dir'] == 0 else -1.0) * abs(
                _simple_mass_flow(sB, fB['dir'], eps_f_per_side=_epsps,
                                  eps_side_override=_ov_B_e))
            Ta, Tb, Ts, _ltne_info_d = solve_ltne_enthalpy_3d_pipeline(
                Nx, Ny, Nz, dx, dy, dz, eps_arr, k_s,
                h_vA_field, h_vB_field, _mdA, _mdB,
                T_inA, T_inB, P_inA, P_inB, fA['dir'], fB['dir'],
                fluid_A=fluid_type_A, fluid_B=fluid_type_B,
                eps_A_field=(eps_fA_arr if float(cfg.get('delta_levelset', 0.0)) != 0.0 else None),
                eps_B_field=(eps_fB_arr if float(cfg.get('delta_levelset', 0.0)) != 0.0 else None),
                Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
                n_sweep=int(cfg.get('ltne_enthalpy_nsweep', 25)),
                omega=float(cfg.get('ltne_enthalpy_omega', 0.6)),
                n_outer=int(cfg.get('ltne_enthalpy_outer', 1500)),
                tol=float(cfg.get('ltne_enthalpy_tol', 1e-3)))

        # B2 strict-conservation certificate (last outer iter holds final).
        _eps_A_strict = _ltne_info_d.get('eps_A_strict')
        _eps_B_strict = _ltne_info_d.get('eps_B_strict')
        _eps_A_strict_cellmax = _ltne_info_d.get('eps_A_strict_cellmax')
        _eps_B_strict_cellmax = _ltne_info_d.get('eps_B_strict_cellmax')
        if _cancel_check is not None and _cancel_check():
            raise InterruptedError("compute cancelled by user")
        _ltne_info.append(dict(outer=outer, iters=_ltne_info_d.get('iterations',0),
                               converged=_ltne_info_d.get('converged',False),
                               residual=_ltne_info_d.get('residual',0.0)))
        if _prof_t_ltne is not None:
            _dt = _time.perf_counter() - _prof_t_ltne
            _log.info(f"[PROF] outer {outer}: LTNE {_dt:7.2f}s  "
                      f"iters={_ltne_info_d.get('iterations',0)}  "
                      f"conv={_ltne_info_d.get('converged',False)}  "
                      f"res={_ltne_info_d.get('residual',0.0):.2e}  "
                      f"(cap={_ltne_max_iter})")

        _converged, _outer_deltas = _outer_conv.check(
            {'Ta': Ta, 'Tb': Tb, 'Ts': Ts})
        _outer_dT_hist.append(_outer_deltas)
        return _converged, None

    def _outer_post_3d(outer, _carry):
        # Non-iso coupling: Ta real → solver coords via self-inverse perm
        Ta_sA = np.ascontiguousarray(Ta.transpose(solver_to_real_perm))
        # #5 reverse-dir density-frame fix, fluid-A side (audit 2026-06-28). Same
        # bug class as the Tb_sB flip below: the velocity transforms flip for a
        # reverse-dir fluid but this T→SIMPLE transform did not, mirroring the
        # SIMPLE density frame for a reverse-dir A. Gated to sCO2 reverse-dir A
        # (ρ(T)-sensitive); forward A (all 703/Shanghai configs, dir 0) → no-op,
        # bit-identical. air/water keep the legacy frame (validation-safe).
        if fluid_type_A == 'sco2' and axis_map['is_reverse']:
            _ssax_A = solver_to_real_perm[int(axis_map['stream_real_axis'])]
            Ta_sA = np.ascontiguousarray(np.flip(Ta_sA, axis=_ssax_A))
        # Critical: propagate Ta to T_field so SIMPLE inner _update_density()
        # uses local cell T, not stale T_in. (Mirror sB.update_T_field below.)
        sA.update_T_field(Ta_sA)
        P_abs = sA.P_ref_abs + sA.P
        if _mA.compressible:
            rho_new = P_abs / (R_AIR * Ta_sA)            # ideal gas
            mu_new_A = air_viscosity(Ta_sA)
        elif os.environ.get('TPMSHX_SCO2_COMPRESSIBLE', '').lower() in ('1', 'true', 'yes'):
            # #4 Phase-B (opt-in, EXPERIMENTAL): sco2 ρ/μ at the LOCAL absolute-P
            # field (ρ tracks local P, not frozen inlet P). ⚠ PROPERTY SIDE ONLY —
            # the full compressible continuity (∂ρ/∂P in the pressure correction,
            # Karki-Patankar ψ) is NOT implemented, so high-dP convergence is
            # unverified. 703 dP<2% ⇒ default Phase A (below) is sufficient.
            rho_new = sco2_props.sco2_prop("D", Ta_sA, P_abs)
            mu_new_A = sco2_props.sco2_prop("V", Ta_sA, P_abs)
        else:
            # sco2 Phase A (default): ρ=ρ(T,P_in), μ=μ(T,P_in) per cell (frozen P;
            # ρ still tracks T — captures the near-critical ρ swing). CoolProp.
            rho_new = sco2_props.sco2_density_field(Ta_sA, P_inA)
            mu_new_A = sco2_props.sco2_viscosity_field(Ta_sA, P_inA)
        if outer > 0:
            sA.rho_field = np.ascontiguousarray(
                _ALPHA_T * rho_new + (1.0 - _ALPHA_T) * sA.rho_field,
                dtype=np.float64)
            sA.mu_field = np.ascontiguousarray(
                _ALPHA_T * mu_new_A
                + (1.0 - _ALPHA_T) * sA.mu_field, dtype=np.float64)
        else:
            sA.rho_field = np.ascontiguousarray(rho_new, dtype=np.float64)
            sA.mu_field = np.ascontiguousarray(mu_new_A, dtype=np.float64)
        eps_eff_A = sA.eps_field if hasattr(sA, 'eps_field') else sA.eps
        sA._mu_eff_field = np.ascontiguousarray(
            sA.mu_field / eps_eff_A, dtype=np.float64)

        T_avg = float(Ta_sA.mean())
        if _mA.compressible:
            mu_avg = float(air_viscosity(T_avg))
            C_avg = mu_avg * G_A / max(K_pred, 1e-16) + cF_pred * G_A * G_A
            P_out_sq_new = P_inA ** 2 - 2.0 * R_AIR * T_avg * C_avg * L_stream
            sA.P_ref_abs = _seed_p_ref(P_out_sq_new, P_inA, mode=_env_mode,
                                       warn_list=_env_warnings,
                                       context='fluid A reseed (outer iter)')
        else:
            # sco2-A reseed: 1D Darcy-Forchheimer dP (cF_pred already ×SCO2_CF_SCALE).
            mu_avg = float(sco2_props.sco2_viscosity(T_avg, P_inA))
            C_avg = mu_avg * G_A / max(K_pred, 1e-16) + cF_pred * G_A * G_A
            _sco2_compress = (os.environ.get('TPMSHX_SCO2_COMPRESSIBLE', '')
                              .lower() in ('1', 'true', 'yes'))
            if _sco2_compress:
                # #4 (2026-06-28): the opt-in compressible sCO2 path is now
                # ENVELOPE-GUARDED (repo hard invariant: a compressible path must
                # not silently floor into a vacuum/garbage state). sCO2 is
                # real-gas, so the ideal-gas P² choke relation does not apply —
                # use the linear DF outlet pressure with the mean LOCAL density
                # (ρ tracks P on this path, unlike Phase A's frozen ρ). If the
                # drop would push the outlet to/below the floor, route through
                # envelope_mode (raise/warn) instead of the silent clip.
                _rho_mean = max(float(np.mean(sA.rho_field)), 1.0e-9)
                _dP_1d = C_avg * L_stream / _rho_mean
                _P_out_1d = float(P_inA - _dP_1d)
                if _P_out_1d <= PRESSURE_FLOOR_PA:
                    _ck = (f"Off-envelope sCO2 (compressible path): 1D "
                           f"Darcy-Forchheimer drop {_dP_1d:.3e} Pa >= inlet "
                           f"absolute P {float(P_inA):.0f} Pa → outlet <= floor. "
                           f"No steady solution; lower the velocity, shorten the "
                           f"streamwise domain, or raise the inlet pressure. "
                           f"[fluid A sCO2 compressible reseed]")
                    if _env_mode == 'raise':
                        raise ChokedFlowError(_ck)
                    if _env_mode == 'warn':
                        _env_warnings.append(_ck)
                sA.P_ref_abs = max(_P_out_1d, PRESSURE_FLOOR_PA)
            else:
                # Phase A (default): frozen-ρ 1D DF seed. ρ at the inlet
                # reference ⇒ no compressible positive feedback ⇒ no choke path.
                sA.P_ref_abs = max(float(P_inA - C_avg * L_stream / rho_A), 1.0e4)

        # Warm restart: SIMPLE fields nearly converged after outer 0.
        # ρ/μ change is small (α_T=0.6 under-relaxation), so 150 iter is plenty
        # for the residual to re-sink to 1e-3. Saves ~50% of SIMPLE work in
        # outer iters 1-2.
        _prof_t_sa = _time.perf_counter() if _prof_3d_enabled() else None
        _sa_conv, _sa_it = sA.solve(max_iter=_simple_max_iter(cfg, 600),
                                    tol=_simple_tol_default(cfg),
                                    verbose=False, cancel_check=_cancel_check)
        if not _sa_conv:
            _simple_nonconv.append(
                f"A@outer{outer}[{getattr(sA, 'exit_reason', '?')}]")
        if _prof_t_sa is not None:
            _log.info(f"[PROF] outer {outer}: SIMPLE_A {_time.perf_counter()-_prof_t_sa:7.2f}s  "
                      f"iters={_sa_it}  conv={_sa_conv}  (cap=600)")

        # Refresh fluid-property fields using the *local* T field, keeping
        # the spatial structure built by the zoned-geometry pass up-front
        # (#1). The previous implementation used `eps_f` (undefined in
        # this scope) and a scalar mean T, which both crashed for zoned
        # runs and flattened any non-uniform K_ff / h_v / rho_cp back to
        # a uniform field.
        T_avgA = float(Ta.mean())
        # FIX (2026-06-24 audit): rebuild K_ffA from the per-side asymmetric void
        # fraction (eps_fA_arr), NOT the symmetric eps_f_arr — otherwise the δ≠0
        # offset-isosurface path reverts to the eps/2 split after outer iter 0.
        # Also re-add the optional thermal-dispersion term that the old in-place
        # refresh silently dropped. δ=0 ⇒ eps_fA_arr IS eps_f_arr (bit-identical);
        # disp_C_A=0 ⇒ no-op.
        if _mA.compressible:
            K_ffA[:] = eps_fA_arr * air_conductivity(Ta)
            _cpA_fld = air_cp(Ta)
        else:
            K_ffA[:] = eps_fA_arr * sco2_props.sco2_conductivity_field(Ta, P_inA)
            _cpA_fld = sco2_props.sco2_cp_field(Ta, P_inA)
        if disp_C_A > 0.0:
            K_ffA[:] += K_disp_A
        if _var_rhocp and sA is not None:
            # SIMPLE's local ρ(P_local,T) → real coords (transpose + reverse flip)
            _rhoA_real = sA.rho_field.transpose(axis_map['solver_to_real_perm'])
            if axis_map['is_reverse']:
                _rhoA_real = np.flip(_rhoA_real, axis=axis_map['stream_real_axis'])
            rho_cp_fA[:] = np.ascontiguousarray(_rhoA_real) * _cpA_fld
        else:
            _rhoA_fld = (air_density(Ta, P_inA) if _mA.compressible
                         else sco2_props.sco2_density_field(Ta, P_inA))
            rho_cp_fA[:] = _rhoA_fld * _cpA_fld
        # h_v rebuilt at top of next outer iter using LOCAL Re (#B fix).

        if Tb is not None:
            T_avgB = float(Tb.mean())
            # B1 1.1: per-fluid primitives via registry; the local-P
            # rho·cp path is compressible-only physics (water keeps ρ(T)).
            K_ffB[:] = eps_fB_arr * _mB.k(Tb, P_inB)  # FIX (2026-06-24 audit): asym per-side eps + re-add dispersion (see fluid-A note above); P for sco2
            if disp_C_B > 0.0:
                K_ffB[:] += K_disp_B
            if _mB.compressible and _var_rhocp and sB is not None:
                _rhoB_real = sB.rho_field.transpose(perm_B)
                if axis_map_B['is_reverse']:
                    _rhoB_real = np.flip(
                        _rhoB_real, axis=axis_map_B['stream_real_axis'])
                rho_cp_fB[:] = np.ascontiguousarray(_rhoB_real) * _mB.cp(Tb, P_inB)
            else:
                rho_cp_fB[:] = _mB.rho(Tb, P_inB) * _mB.cp(Tb, P_inB)
            # h_vB rebuilt at top of next outer iter using LOCAL Re (#B fix).

        # Non-iso coupling for fluid B. Water: ρ(T) only, no ideal gas.
        # Air: ρ(P,T) via ideal gas law (mirror of A).
        if sB is not None and Tb is not None:
            Tb_sB = np.ascontiguousarray(Tb.transpose(perm_B))
            # #5 reverse-dir density-frame fix (2026-06-28). The velocity
            # transforms (_solver_*_to_real) and rho_cp_fB apply the reverse-dir
            # np.flip, but this real→solver T transpose does NOT — so for a
            # reverse-dir B the SIMPLE density frame is MIRRORED relative to the
            # velocity frame: the hot real-OUTLET T lands on the solver
            # injection face (j=0), so ρ_in = ρ(T_out) not ρ(T_in). For
            # ρ(T)-sensitive sCO2 this under-reads ṁ_B ~2.4× (e.g. 703
            # recuperator: 15.5 vs 37.6 kg/s) and corrupts dP_B + the cold-side
            # duty. The fix flips T to match the velocity frame. GATED to sCO2:
            # air/water (weak ρ(T); error within the accepted air-air B-side
            # imbalance) keep the legacy frame so the Shanghai/golden 3D
            # baselines stay bit-identical — the general reverse-dir fix needs a
            # full re-validation (documented follow-up).
            if fluid_type_B == 'sco2' and axis_map_B['is_reverse']:
                _ssax_B = perm_B[int(axis_map_B['stream_real_axis'])]
                Tb_sB = np.ascontiguousarray(np.flip(Tb_sB, axis=_ssax_B))
            if _mB.compressible:
                P_abs_B = sB.P_ref_abs + sB.P
                rho_new_B = P_abs_B / (R_AIR * Tb_sB)
            else:
                rho_new_B = _mB.rho(Tb_sB, P_inB)   # water ignores P; sco2 (T,P_in)
            mu_new_B = _mB.mu(Tb_sB, P_inB)          # air/water ignore P; sco2 needs P
            if outer > 0:
                sB.rho_field = np.ascontiguousarray(
                    _ALPHA_T * rho_new_B + (1.0 - _ALPHA_T) * sB.rho_field,
                    dtype=np.float64)
                sB.mu_field = np.ascontiguousarray(
                    _ALPHA_T * mu_new_B + (1.0 - _ALPHA_T) * sB.mu_field,
                    dtype=np.float64)
            else:
                sB.rho_field = np.ascontiguousarray(rho_new_B, dtype=np.float64)
                sB.mu_field = np.ascontiguousarray(mu_new_B, dtype=np.float64)
            eps_eff_B = sB.eps_field if hasattr(sB, 'eps_field') else sB.eps
            sB._mu_eff_field = np.ascontiguousarray(
                sB.mu_field / eps_eff_B, dtype=np.float64)

            if _mB.compressible:   # P_ref recompute is compressible-only
                Tb_avg = float(Tb_sB.mean())
                mu_avg_B = float(_mB.mu(Tb_avg))
                # Use the B-side permeability / Forchheimer coeff (audit
                # 2026-06-28): the outer-loop reseed previously used fluid A's
                # K_pred / cF_pred, inconsistent with the initial B seed (L1829,
                # K_pred_B / cF_pred_B). Identical for same-geometry same-fluid
                # A/B; differs for asymmetric ε (δ≠0) or differing per-side cF.
                C_avg_B = (mu_avg_B * G_B / max(K_pred_B, 1e-16)
                           + cF_pred_B * G_B * G_B)
                P_out_sq_B_new = (P_inB ** 2
                                  - 2.0 * R_AIR * Tb_avg * C_avg_B * L_stream_B)
                sB.P_ref_abs = _seed_p_ref(P_out_sq_B_new, P_inB,
                                           mode=_env_mode,
                                           warn_list=_env_warnings,
                                           context='fluid B reseed (outer iter)')

            sB.update_T_field(Tb_sB)
            _prof_t_sb = _time.perf_counter() if _prof_3d_enabled() else None
            _sb_conv, _sb_it = sB.solve(max_iter=_simple_max_iter(cfg, 600),
                                        tol=_simple_tol_default(cfg),
                                        verbose=False, cancel_check=_cancel_check)
            if not _sb_conv:
                _simple_nonconv.append(
                    f"B@outer{outer}[{getattr(sB, 'exit_reason', '?')}]")
            if _prof_t_sb is not None:
                _log.info(f"[PROF] outer {outer}: SIMPLE_B {_time.perf_counter()-_prof_t_sb:7.2f}s  "
                          f"iters={_sb_it}  conv={_sb_conv}  (cap=600)")
                _prof_res_trace(f"outer {outer} SIMPLE_B", sB)

            # rho_cp_fB already refreshed above (P0/P1/P2 block)

            # Re-extract the full B vector for the next LTNE pass.
            ucB2, vcB2, wcB2 = _solver_velocity_to_real(
                sB, axis_map_B, (Nx, Ny, Nz))
            ucB[:] = ucB2
            vcB[:] = vcB2
            wcB[:] = wcB2

    # The skeleton returns (last_iter, converged). 3D used to DISCARD both, so
    # the outer-coupling verdict never reached `solver_converged` (2D captures
    # it — solve_2d.py:1173). A run that burned every outer iteration with ΔT
    # still bouncing could therefore report success as long as the final LTNE
    # inner pass and the SIMPLE solves converged. (Audit 2026-07-12.)
    _outer_last_iter, _outer_converged = run_outer_coupling(
        max_iter=_max_outer, step=_outer_step_3d, post=_outer_post_3d)

    # ── Extract metrics + fields ──
    # Primary Q is the volume integral of h_vB·(Ts−Tb), matching the
    # 2D UI path (run_calculation.py:_store_results.Q_total) and the
    # optimizer (both 2D and 3D). This makes Q comparable across the
    # three paths without a unit-mismatch penalty. (#5 / v1.0.10 #6)
    #
    # Q_enthalpy_A (m_dot × cp × ΔT) is kept as a secondary reading;
    # it uses inlet-plane ρ from the solver's rho_field (not a stale
    # cold-seed scalar) and respects the solver's inlet mask via
    # v_inlet_field. (v1.0.10 #2)
    # NOTE: despite the legacy comment above, the returned Q is assigned from
    # the enthalpy balance below; Q_solid_B remains diagnostic only.
    cell_vol = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]
    Q_solid_B = float(np.sum(h_vB_field * (Ts - Tb) * cell_vol))

    out_idx = 0 if is_reverse else -1
    T_A_out = float(np.mean(np.take(Ta, out_idx, axis=stream_real_axis)))
    T_B_out = None
    if sB is not None:
        axis_B = sB_info['axis_map']['stream_real_axis']
        out_idx_B = 0 if sB_info['axis_map']['is_reverse'] else -1
        T_B_out = float(np.mean(np.take(Tb, out_idx_B, axis=axis_B)))
    # Mass flow from the solver's actual inlet face: ρ·v_in × open-area.
    # sA.v has shape (solver Nx, solver Ny+1, solver Nz); inlet face is
    # j=0. Use rho_field[:, 0, :] × v[:, 0, :] × (dx × dz) with open-area
    # fraction `inlet_frac` so partial-inlet geometries are honoured.
    # Q_enthalpy via **SIMPLE-native** mass flow (2026-04-25 FV hardening).
    # Earlier used cell-centered ucA/vcA/wcA reconstructed via
    # _solver_velocity_to_real, but that cell-averaged interpolation lost
    # ~40% mass flow on wall-refined grids (the averaging leaked no-slip
    # wall cells into the mean). Now m_dot comes directly from the SIMPLE
    # staggered v-face + ρ-face which the pressure-correction enforces to
    # be divergence-free. T_out is a pipe-masked mean on the real outlet
    # face using Ta/Tb cell-centered values.
    #
    # _face_flux_weights / _mass_weighted_T_out / _real_outlet_slice /
    # _simple_mass_flow are now module-level (hoisted 2026-05-15) so they can
    # be unit-tested for stagnant-cell suppression. `eps_f_per_side` is
    # passed explicitly instead of captured by closure.

    # LTNE uses ε_A = ε_B = ε/2 per side (symmetric 2-fluid split). Metric
    # must mirror that so m_dot ≡ ∫ ε_A·ρ·u·dA matches the solver's
    # internal advective mass flow.
    eps_f_per_side = 0.5 * float(eps)   # ε_A (symmetric)
    # Asymmetric per-side single-channel void fractions (offset-isosurface δ).
    # None at δ=0 → symmetric 0.5·ε path (bit-identical). δ≠0 → per-side ε_side
    # so m_dot/Q weight by the actual channel void fraction, not 0.5·ε
    # (else ṁ_A/ṁ_B mis-scale by split/0.5 on the asymmetric geometry).
    _eps_ov_A, _eps_ov_B = _per_side_eps_override(
        cfg, tpms_type, Lcell, t_wall, eps)

    # Fluid A — unified face-flux weights for T_out and m_dot consistency
    m_dot_A_simple = _simple_mass_flow(sA, fA['dir'], eps_f_per_side=eps_f_per_side,
                                       eps_side_override=_eps_ov_A)
    T_A_out_face = _real_outlet_slice(Ta, fA['dir'])
    T_A_out = _mass_weighted_T_out(T_A_out_face, sA, fA['dir'], eps_f_per_side,
                                   eps_side_override=_eps_ov_A)
    # (A side has no χ_B weighting, so there is no chi/no-chi distinction here —
    #  the former duplicate `T_A_out_no_chi` local was dead and was removed.)
    # sCO2: true enthalpy duty ṁ·Δh (cp varies strongly with T,P → cp·ΔT is
    # wrong); air/water keep cp·ΔT (constant cp ⇒ value-identical, golden-safe).
    if fluid_type_A == 'sco2':
        # D2 (audit 2026-06-28): mass-weighted mean OUTLET enthalpy ⟨h(T)⟩,
        # NOT h(⟨T⟩_out) — h(T) is strongly nonlinear across the pseudocritical
        # spike (Jensen). Inlet is a uniform Dirichlet T so h(T_inA) is exact.
        h_A_out = _mass_weighted_h_out(
            T_A_out_face, P_inA, sco2_props.sco2_enthalpy_field, sA, fA['dir'],
            eps_f_per_side, eps_side_override=_eps_ov_A)
        Q_enthalpy_A = abs(m_dot_A_simple * (
            sco2_props.sco2_enthalpy(float(T_inA), P_inA) - h_A_out))
    else:
        Q_enthalpy_A = abs(m_dot_A_simple * cp_A * (T_inA - T_A_out))

    # Fluid B
    Q_enthalpy_B = 0.0
    chi_B_out_face = None
    if sB is not None:
        m_dot_B_simple = _simple_mass_flow(sB, fB['dir'], eps_f_per_side=eps_f_per_side,
                                           eps_side_override=_eps_ov_B)
        T_B_out_face = _real_outlet_slice(Tb, fB['dir'])
        # χ_B at outlet face for ghost-B suppression
        if chi_B is not None:
            chi_B_out_face = _real_outlet_slice(chi_B, fB['dir'])
        # T_out with and without χ_B for diagnostic comparison
        T_B_out_no_chi = _mass_weighted_T_out(T_B_out_face, sB, fB['dir'],
                                               eps_f_per_side,
                                               eps_side_override=_eps_ov_B)
        T_B_out = _mass_weighted_T_out(T_B_out_face, sB, fB['dir'], eps_f_per_side,
                                        chi_face=chi_B_out_face,
                                        eps_side_override=_eps_ov_B)
        # m_dot variants for diagnostic
        m_dot_B_phys_in = float(np.sum(_face_flux_weights(
            sB, fB['dir'], face='real_inlet', eps_mode='physical')))
        m_dot_B_phys_out = float(np.sum(_face_flux_weights(
            sB, fB['dir'], face='real_outlet', eps_mode='physical',
            chi_face=chi_B_out_face)))
        if fluid_type_B == 'sco2':
            # D2: mass-weighted mean outlet enthalpy ⟨h(T)⟩ (with χ_B ghost
            # suppression), not h(⟨T⟩_out). Inlet uniform Dirichlet → exact.
            h_B_out = _mass_weighted_h_out(
                T_B_out_face, P_inB, sco2_props.sco2_enthalpy_field, sB, fB['dir'],
                eps_f_per_side, chi_face=chi_B_out_face,
                eps_side_override=_eps_ov_B)
            Q_enthalpy_B = abs(m_dot_B_simple * (
                sco2_props.sco2_enthalpy(float(T_inB), P_inB) - h_B_out))
        else:
            Q_enthalpy_B = abs(m_dot_B_simple * cp_B * (T_inB - T_B_out))

    # #5 guard (2026-06-28 audit): the 3D conservative LTNE kernel conserves the
    # ε·ρcp·u·A energy mass-flux, which is inconsistent with true enthalpy ṁ·Δh
    # for a STRONGLY VARYING-cp fluid (sCO2). The reverse-dir density-frame fix
    # above removed the dominant ~2× ṁ_B under-read (75 %→41 % on the 703
    # recuperator), but a residual enthalpy-vs-(cp·T) gap remains (the kernel
    # transports cp·T, not ∫cp dT) → the cold-side duty still under-reads. Flag
    # it so the 3D coupled-Q / cold-outlet are not trusted for sCO2 (full fix =
    # enthalpy-form LTNE kernel; use the 2D double-live solve for the coupled
    # duty). Air/water (near-constant cp) are unaffected. The imbalance is also
    # surfaced as the `Q_AB_imbalance_rel` result field for downstream callers.
    Q_AB_imbalance_rel = float('nan')
    if (sB is not None and (fluid_type_A == 'sco2' or fluid_type_B == 'sco2')
            and Q_enthalpy_A > 1.0 and Q_enthalpy_B > 1.0):
        Q_AB_imbalance_rel = (abs(Q_enthalpy_A - Q_enthalpy_B)
                              / max(Q_enthalpy_A, Q_enthalpy_B))
        if Q_AB_imbalance_rel > 0.10:
            import warnings as _w5
            _w5.warn(
                f"[sCO2 3D energy] A/B enthalpy duties differ by "
                f"{Q_AB_imbalance_rel*100:.0f}% (Q_A={Q_enthalpy_A/1e6:.2f} MW, "
                f"Q_B={Q_enthalpy_B/1e6:.2f} MW): the conservative LTNE kernel "
                "transports ρcp·u·A·T, not true enthalpy, for varying-cp sCO2. "
                "The 3D coupled Q / cold-outlet are NOT trustworthy — use the 2D "
                "double-live solve for the coupled duty. dP + hot-side duty are "
                "still reliable.", stacklevel=2)

    # Primary Q — mean of A and B enthalpy metrics (m·cp·ΔT per side).
    # NTU check (2026-04-25): Q_enthalpy_A/_B match the cross-flow ε·C_min·ΔT
    # bound to within engineering tolerance (e.g. Shanghai Air-Air NORM:
    # Q_A=323W, Q_B=374W, NTU_max=333W — both sides physical).
    #
    # **|Q_solid_B| = ∫h_vB(Ts−Tb)dV** is KEPT as a diagnostic but NO LONGER
    # primary: the homogenised h_v applied uniformly over all cells spuriously
    # counts stagnant wall-BL zones where no real flow carries heat, pushing
    # |Q_sB| ~25% above the NTU upper bound. The LTNE Q_sA+Q_sB ≈ 0 internal
    # check still holds (<1%) — it's the magnitude that over-estimates, not
    # the conservation.
    # Headline heat duty = AIR/A-side advective enthalpy ONLY. The B/water-side
    # advective enthalpy (Q_enthalpy_B = m_B·cp·ΔT_B) drops the boundary-
    # conduction flux, so it over/under-reads by ~8 % even when the scheme
    # conserves. The old 0.5·(Q_A+Q_B) average therefore drifted non-physically
    # (e.g. the displayed Q ROSE when coolant flow FELL — the B term polluting
    # it). Q_enthalpy_A matches the experiment-validated duty: validation/
    # validate_shanghai_3d_real computes the same m_air·cp·ΔT_A (RMSRE ~3 %).
    # Q_enthalpy_B is retained in the result dict as a transparent diagnostic.
    Q = Q_enthalpy_A

    dP = float(SIMPLESolver3D.extract_dP_face_extrap(sA))

    uc_real, vc_real, wc_real = _assemble_real_velocity()
    vmag = np.sqrt(uc_real ** 2 + vc_real ** 2 + wc_real ** 2)

    # P field → real coords via solver perm. DISPLAY ABSOLUTE pressure anchored
    # so the INLET reads exactly the user-input P_in — identical convention to
    # the 2D-native path (run_calculation.py:821, P_fA = P_inA + (P_g - P_ref
    # _inlet)). SIMPLE's self.P is the gauge field (outlet pinned ~0, inlet ≈
    # dP); abs = (P_in - dP) + gauge ⇒ inlet=P_in, outlet=P_in-dP. Pure baseline
    # shift, physics-free — dP itself is reported via extract_dP_face_extrap
    # (line above), and this anchor does NOT depend on the P_ref_abs
    # reconstruction (which for
    # water is a fixed 1D seed, not loop-converged → would over-shoot the inlet).
    P_disp_A = (P_inA - dP) + sA.P
    P_real = np.ascontiguousarray(P_disp_A.transpose(solver_to_real_perm))
    P_kPa = P_real / 1000.0
    L_mm = (L_mm_field.copy() if L_mm_field is not None
            else np.full((Nx, Ny, Nz), Lcell, dtype=np.float64))

    # Fluid B fields (if sB solved): real-coord P + velocity magnitude
    if sB is not None:
        axis_map_B = sB_info['axis_map']
        perm_B = axis_map_B['solver_to_real_perm']
        dP_B = float(SIMPLESolver3D.extract_dP_face_extrap(sB))
        # ABSOLUTE pressure anchored so inlet == input P_inB (same convention as
        # fluid A and the 2D path). Works for both water (incompressible) and
        # air B without depending on the P_ref_abs reconstruction.
        P_disp_B = (P_inB - dP_B) + sB.P
        P_real_B = np.ascontiguousarray(P_disp_B.transpose(perm_B))
        # approach-(a) reverse convention: sB.P is in SOLVER coords (inlet at
        # solver y=0, high P). For a reverse-dir fluid the real inlet is at the
        # OPPOSITE stream end, so the pressure must be spatially flipped along
        # the real stream axis — exactly like _solver_velocity_to_real and the
        # LTNE temperature solve. Pressure is a scalar, so NO sign change
        # (unlike the stream velocity component). Without this flip the
        # displayed P_B put the inlet's high pressure at the real OUTLET end.
        # The constant baseline shift commutes with transpose+flip.
        # Display-only field (feeds the vis panels; no physics consumes it).
        if axis_map_B.get('is_reverse'):
            P_real_B = np.ascontiguousarray(
                np.flip(P_real_B, axis=axis_map_B['stream_real_axis']))
        vmag_B = np.sqrt(ucB ** 2 + vcB ** 2 + wcB ** 2)
    else:
        P_real_B = None
        vmag_B = None
        dP_B = 0.0

    # Conservation diagnostics (energy + mass balance + interior-corrected Q) —
    # extracted to _conservation_diagnostics_3d (F1). Always computed so the
    # user spots non-physical regressions without re-running validation.
    _cdiag = _conservation_diagnostics_3d(
        Ta, Tb, Ts, h_vA_field, h_vB_field, sA, sB, fA, fB, dx, dy, dz)
    Q_sA = _cdiag['Q_sA']; Q_sB = _cdiag['Q_sB']; Q_net = _cdiag['Q_net']
    energy_rel = _cdiag['energy_rel']
    mass_rel_A = _cdiag['mass_rel_A']; mass_rel_B = _cdiag['mass_rel_B']
    Q_sA_interior = _cdiag['Q_sA_interior']
    Q_sB_interior = _cdiag['Q_sB_interior']
    Q_interior_primary = _cdiag['Q_interior_primary']
    AB_interior = _cdiag['AB_interior']

    # ═══════════════════════════════════════════════════════════════════
    # Phase 2 diagnostics (Plan A v3): REQ_1–4 data dump
    # ═══════════════════════════════════════════════════════════════════
    if _compact_diag:
        # Fast sweep: single CSV-style row, skip full diagnostic dump
        _ltne_iters = [d['iters'] for d in _ltne_info]
        _ltne_conv = [d['converged'] for d in _ltne_info]
        _ltne_hit_max = [d['iters'] >= _ltne_max_iter for d in _ltne_info]
        eps_obs = ((T_B_out - T_inB) / (T_inA - T_inB)
                   if sB is not None and T_inA != T_inB else 0.0)
        chi_p50 = float(np.percentile(chi_B, 50)) if chi_B is not None else 1.0
        _log.info(f"[SWEEP-CSV] {cfg.get('_case_label','?')},"
                  f"{len(_ltne_info)},{_ltne_iters},{_ltne_conv},"
                  f"{any(_ltne_hit_max)},{_ltne_info[-1]['residual']:.2e},"
                  f"{T_A_out:.1f},{T_B_out:.1f},{Q:.1f},"
                  f"{Q_sA:.1f},{Q_sB:.1f},{Q_sA+Q_sB:.1f},"
                  f"{energy_rel:.6f},{eps_obs:.4f},{chi_p50:.4f}")
    # Run diagnostics (Q-DIAG / CHI / CHI-BC) — OPT-IN, skipped in production.
    # None of these locals feed the return dict; gating avoids the extra
    # _face_flux_weights / percentile / histogram recompute + ~30 lines of
    # console spam on every run. Enable via the 3D profiler (.profile_3d /
    # TPMSHX_PROFILE_3D=1) or cfg['_verbose_diag']=True. 2026-06-09 perf B2.
    if _prof_3d_enabled() or bool(cfg.get('_verbose_diag', False)):
        _dbg = np
        Q_solid_A_val = float(_dbg.sum(h_vA_field * (Ts - Ta) * cell_vol))
        Q_solid_B_val = float(_dbg.sum(h_vB_field * (Ts - Tb) * cell_vol))

        # Group 1: LTNE-effective Q (uses eps_f, chi_face, LTNE volume source)
        Q_enth_A_ltne = abs(m_dot_A_simple * cp_A * (T_inA - T_A_out))
        Q_enth_B_ltne = abs(m_dot_B_simple * cp_B * (T_inB - T_B_out)) if sB is not None else 0.0

        # Group 2: Physical-boundary Q (no eps_f, physical m_dot at inlet)
        m_A_phys_in = float(_dbg.sum(_face_flux_weights(
            sA, fA['dir'], face='real_inlet', eps_mode='physical')))
        Q_enth_A_phys = abs(m_A_phys_in * cp_A * (T_inA - T_A_out))
        if sB is not None:
            Q_enth_B_phys = abs(m_dot_B_phys_in * cp_B * (T_inB - T_B_out))
        else:
            Q_enth_B_phys = 0.0

        _log.info(f"[Q-DIAG] === LTNE-effective group ===")
        _log.info(f"[Q-DIAG] m_dot_A_ltne={m_dot_A_simple:.5f} kg/s  "
                  f"T_A_out={T_A_out:.1f} K  Q_enth_A_ltne={Q_enth_A_ltne:.1f} W")
        if sB is not None:
            _log.info(f"[Q-DIAG] m_dot_B_ltne={m_dot_B_simple:.5f} kg/s  "
                      f"T_B_out={T_B_out:.1f} K (chi)  "
                      f"T_B_out_no_chi={T_B_out_no_chi:.1f} K  "
                      f"Q_enth_B_ltne={Q_enth_B_ltne:.1f} W")
        _log.info(f"[Q-DIAG] Q_solid_A={Q_solid_A_val:.1f}  Q_solid_B={Q_solid_B_val:.1f}  "
                  f"balance={Q_solid_A_val+Q_solid_B_val:.1f} W")
        _log.info(f"[Q-DIAG] Q_ltne_consistency: |Q_sA|-Q_enth_A_ltne="
                  f"{abs(Q_solid_A_val)-Q_enth_A_ltne:.1f}  "
                  f"|Q_sB|-Q_enth_B_ltne={abs(Q_solid_B_val)-Q_enth_B_ltne:.1f}")

        _log.info(f"[Q-DIAG] === Physical-boundary group ===")
        _log.info(f"[Q-DIAG] m_A_phys_in={m_A_phys_in:.5f} kg/s  "
                  f"Q_enth_A_phys={Q_enth_A_phys:.1f} W")
        if sB is not None:
            _log.info(f"[Q-DIAG] m_B_phys_in={m_dot_B_phys_in:.5f}  "
                      f"m_B_phys_out_chi={m_dot_B_phys_out:.5f} kg/s  "
                      f"T_B_out={T_B_out:.1f} K")
            _log.info(f"[Q-DIAG] Q_enth_B_phys={Q_enth_B_phys:.1f} W")

        # ── REQ_2: χ_B distribution histogram ──
        if chi_B is not None:
            chi_flat = chi_B.ravel()
            _log.info(f"[CHI] min={chi_flat.min():.3f} max={chi_flat.max():.3f} "
                      f"mean={chi_flat.mean():.3f}")
            _log.info(f"[CHI] p10={_dbg.percentile(chi_flat,10):.3f} "
                      f"p25={_dbg.percentile(chi_flat,25):.3f} "
                      f"p50={_dbg.percentile(chi_flat,50):.3f} "
                      f"p75={_dbg.percentile(chi_flat,75):.3f} "
                      f"p90={_dbg.percentile(chi_flat,90):.3f}")
            hist, bin_edges = _dbg.histogram(chi_flat, bins=10, range=(0, 1))
            _log.info("[CHI] histogram bins:")
            for i, c in enumerate(hist):
                _log.info(f"  [{bin_edges[i]:.1f}, {bin_edges[i+1]:.1f}): "
                          f"{c} ({100*c/chi_flat.size:.1f}%)")

        # ── REQ_4: χ_B on B inlet/outlet patches (masked, not full face) ──
        if chi_B is not None and sB is not None:
            # B inlet face slice in real coords (single dir source).
            chi_B_in_face = _face_slice(chi_B, fB['dir'], 'inlet')
            # Inlet patch mask: _ltne_mask_B is the physical inlet patch in 2D
            # (in_mask_B; approach-(a), no in/out swap).
            _ltne_mask_B_val = _ltne_mask_B  # from outer loop scope
            if _ltne_mask_B_val is not None:
                chi_in_patch = chi_B_in_face[_ltne_mask_B_val > 0.5]
                if len(chi_in_patch) > 0:
                    _log.info(f"[CHI-BC] χ_B on inlet PATCH (n={len(chi_in_patch)}): "
                              f"p10={_dbg.percentile(chi_in_patch,10):.3f} "
                              f"p50={_dbg.percentile(chi_in_patch,50):.3f} "
                              f"p90={_dbg.percentile(chi_in_patch,90):.3f}")
            # Outlet patch
            if chi_B_out_face is not None:
                chi_out_patch = chi_B_out_face[_ltne_mask_B_val > 0.5] if _ltne_mask_B_val is not None else chi_B_out_face.ravel()
                if len(chi_out_patch) > 0:
                    _log.info(f"[CHI-BC] χ_B on outlet PATCH (n={len(chi_out_patch)}): "
                              f"p10={_dbg.percentile(chi_out_patch,10):.3f} "
                              f"p50={_dbg.percentile(chi_out_patch,50):.3f} "
                              f"p90={_dbg.percentile(chi_out_patch,90):.3f}")
    # ═══════════════════════════════════════════════════════════════════

    _result = dict(
        Ta=Ta, Tb=Tb, Ts=Ts,
        vmag=vmag, P_kPa=P_kPa, L_mm=L_mm,
        P_Pa=P_real,
        uc_real=uc_real, vc_real=vc_real, wc_real=wc_real,
        # Fluid B (None if frozen)
        P_Pa_B=P_real_B,
        uc_real_B=ucB, vc_real_B=vcB, wc_real_B=wcB,
        vmag_B=vmag_B, dP_B=dP_B,
        dx=dx, dy=dy, dz=dz,
        Lx=L, Ly=H, Lz=Lz,
        Q=Q, Q_total=Q, Q_enthalpy_A=Q_enthalpy_A, Q_enthalpy_B=Q_enthalpy_B,
        Q_solid_B=Q_solid_B,
        dP=dP, dP_A=dP, u_A=u_A, T_in=T_inA,
        T_A_out=T_A_out, T_B_out=T_B_out,
        T_out_A=T_A_out, T_out_B=T_B_out,
        dir_A=fA['dir'], dir_B=(fB['dir'] if fB is not None else None),
        # Conservation diagnostics
        Q_sA=Q_sA, Q_sB=Q_sB, Q_net=Q_net,
        energy_imbalance_rel=energy_rel,
        mass_imbalance_rel_A=mass_rel_A,
        mass_imbalance_rel_B=mass_rel_B,
        # #5: sCO2 A/B enthalpy-duty imbalance (nan for air/water) — the residual
        # after the reverse-dir mass-flow fix; >10% ⇒ trust 2D coupled duty.
        Q_AB_imbalance_rel=Q_AB_imbalance_rel,
        # h_v fields for BC-layer split diagnostic (path 0' v3)
        h_vA_field=h_vA_field, h_vB_field=h_vB_field,
        # Path 0' interior-corrected metrics (BC layer excluded)
        Q_sA_interior=Q_sA_interior,
        Q_sB_interior=Q_sB_interior,
        Q_interior=Q_interior_primary,
        AB_interior=AB_interior,
        # B2 strict-conservation certificate (None unless conservative_ltne)
        eps_A_strict=_eps_A_strict,
        eps_B_strict=_eps_B_strict,
        eps_A_strict_cellmax=_eps_A_strict_cellmax,
        eps_B_strict_cellmax=_eps_B_strict_cellmax,
        # Plan C v2: B flow-path indicator field (χ_B) for visualization
        chi_B=chi_B,
        # Sweep profile diagnostics
        _ltne_info=_ltne_info,
        _max_outer=_max_outer,
        _ltne_max_iter=_ltne_max_iter,
        _needs_full_validate=(_compact_diag and not all(
            d['converged'] for d in _ltne_info)),
    )

    # ── Post-solve compressible validity gate (robustness, 2026-06-25) ──
    # Catches dynamic choking the 1D pre-seed missed: a supersonic |v| or a
    # pressure clipped to the floor in the converged field. Mach is the load-
    # bearing signal (the _update_density floor bounds the stored gauge, but a
    # choked solve still drives v=G/rho supersonic); it is computed per-cell
    # against the LOCAL temperature so a cold low-density region isn't missed.
    # BOTH ideal-gas sides are checked — fluid B (air-air) can choke too.
    _clip_hits = int(getattr(sA, '_p_clip_hits', 0))
    if sB is not None:
        _clip_hits += int(getattr(sB, '_p_clip_hits', 0))
    _env_valid, _env_reasons = True, []
    if cfg.get('fluid_type_A', 'air') == 'air':
        _vA, _rA = gate_solution(
            float((sA.P_ref_abs + sA.P).min()), float(vmag.max()),
            float(T_inA), mode=_env_mode, dims='3D-A',
            ma_max=mach_field_max(vmag, Ta))
        _env_valid = _env_valid and _vA
        _env_reasons += [f"[A] {r}" for r in _rA]
    if (sB is not None and vmag_B is not None
            and cfg.get('fluid_type_B', 'air') == 'air'):
        _vB, _rB = gate_solution(
            float((sB.P_ref_abs + sB.P).min()), float(vmag_B.max()),
            float(T_inB), mode=_env_mode, dims='3D-B',
            ma_max=mach_field_max(vmag_B, Tb))
        _env_valid = _env_valid and _vB
        _env_reasons += [f"[B] {r}" for r in _rB]
    if _simple_nonconv:
        _env_warnings.append(
            "SIMPLE momentum solve did not converge to tol at: "
            + ", ".join(_simple_nonconv)
            + " — the velocity/pressure field may be under-resolved (raise "
              "max_iter or relax tol).")
    _env_warnings = list(dict.fromkeys(_env_warnings))   # dedup, keep order
    _result['envelope_valid'] = _env_valid
    _result['envelope_reasons'] = _env_reasons
    _result['envelope_warnings'] = _env_warnings
    _result['p_clip_hits'] = _clip_hits
    # ── Convergence verdict — explicit AND over every gate (2026-07-12) ──
    # robustness-hardening (2026-07-03) introduced this key but only ANDed
    # SIMPLE with the FINAL outer LTNE pass. Three ways a bad solve could still
    # report success, all closed here:
    #   (a) outer coupling never converged  — the skeleton's verdict was
    #       discarded at the call site (see run_outer_coupling above);
    #   (b) `max_outer_ltne=0` → zero iterations → `_ltne_info` empty → the
    #       `not _ltne_info` short-circuit returned True on a run that solved
    #       nothing;
    #   (c) a non-finite (NaN/inf) temperature or velocity field — the envelope
    #       gate flags non-finite P/Mach, but a NaN inside Ta/Tb/Ts alone did
    #       not touch the verdict.
    # Only the verdict changes; no numeric field is touched (golden gates hash
    # fields + headline scalars, not this key).
    _fields_finite = bool(
        np.all(np.isfinite(Ta)) and np.all(np.isfinite(Tb))
        and np.all(np.isfinite(Ts)) and np.all(np.isfinite(vmag))
        and (vmag_B is None or np.all(np.isfinite(vmag_B))))
    if not _fields_finite:
        _env_warnings.append(
            "Non-finite (NaN/inf) cells in the converged temperature or "
            "velocity field — the result is not physical; solver_converged "
            "is forced False.")
        _env_warnings = list(dict.fromkeys(_env_warnings))
        _result['envelope_warnings'] = _env_warnings
    _ltne_ok = bool(_ltne_info) and bool(
        _ltne_info[-1].get('converged', False))
    _result['solver_converged'] = bool(
        (not _simple_nonconv)          # every SIMPLE solve reached tol
        and _ltne_ok                   # FINAL outer LTNE inner pass converged
        and bool(_outer_converged)     # outer coupling converged (not capped)
        and _fields_finite             # no NaN/inf in the reported fields
        and bool(_env_valid))          # post-solve compressible envelope gate
    # A2 (2026-07-06): structured convergence detail. Additive result keys
    # only (the golden gate hashes fields + headline scalars, not these).
    #   simple_*   : final SIMPLE exit per solver — reason ('tol'|'velocity'|
    #                'stall'|'max_iter'|'cancelled'), final normalised
    #                residual, and the kg/s normalisation reference.
    #   outer_dT   : per-outer-iteration {Ta,Tb,Ts: max|Δ| [K]} history.
    #   outer_converged : the tracked-field AND-gate verdict of the LAST
    #                outer iteration (False when the loop hit _MAX_OUTER).
    def _simple_detail(s):
        if s is None:
            return None
        return dict(exit_reason=getattr(s, 'exit_reason', None),
                    final_res=getattr(s, 'final_res', None),
                    res_norm_ref=getattr(s, 'res_norm_ref', None))
    _result['convergence_detail'] = dict(
        simple_A=_simple_detail(sA),
        simple_B=_simple_detail(sB),
        simple_nonconv=list(_simple_nonconv),
        outer_dT=[{k: float(v) for k, v in d.items()}
                  for d in _outer_dT_hist],
        # The skeleton's OWN verdict, not a reconstruction from the ΔT history
        # (the reconstruction could disagree with the loop that actually ran —
        # e.g. it returned True for a converged-on-the-first-pass run whose
        # history the skeleton never marks). Also records WHY it stopped.
        outer_converged=bool(_outer_converged),
        outer_iters=int(_outer_last_iter) + 1,
        outer_hit_cap=bool(not _outer_converged),
        # Per-gate breakdown so a caller can see WHICH gate failed rather than
        # just that the AND is False (convergence truth-table, 2026-07-12).
        simple_ok=bool(not _simple_nonconv),
        ltne_ok=_ltne_ok,
        fields_finite=_fields_finite,
        envelope_ok=bool(_env_valid),
    )

    # ── Audit-only additive exports (read-only, deep-copied) ── OPT-IN.
    # Passthrough of SIMPLE face arrays + masks for the standalone partial-B
    # LTNE conservation audit (validation/cases/audit_partial_b_ltne.py).
    # 2026-06-09 perf C1: gated behind cfg['_emit_audit'] (default False) —
    # these deep-copy both solvers' full u/v/w/ρ fields + K/eps/rho_cp/χ arrays,
    # a large memory + wall-time cost paid on EVERY run. Only the audit scripts
    # and test_partial_bc_ghost_b consume them, so those callers set
    # _emit_audit=True. Consumers must not mutate. No physics change.
    if cfg.get('_emit_audit', False):
        _result.update(
        _audit_sA_face=dict(
            u=sA.u.copy(), v=sA.v.copy(), w=sA.w.copy(),
            rho=sA.rho_field.copy(),
            inlet_frac=(np.asarray(sA.inlet_frac).copy()
                        if getattr(sA, 'inlet_frac', None) is not None else None),
            outlet_frac=(np.asarray(sA.outlet_frac).copy()
                         if getattr(sA, 'outlet_frac', None) is not None else None),
            eps=(np.asarray(sA.eps_field).copy()
                 if getattr(sA, 'eps_field', None) is not None else None),
            dx=sA.dx.copy(), dy=sA.dy.copy(), dz=sA.dz.copy(),
            dir_real=fA['dir'],
            solver_to_real_perm=solver_to_real_perm,
        ),
        _audit_sB_face=(dict(
            u=sB.u.copy(), v=sB.v.copy(), w=sB.w.copy(),
            rho=sB.rho_field.copy(),
            inlet_frac=(np.asarray(sB.inlet_frac).copy()
                        if getattr(sB, 'inlet_frac', None) is not None else None),
            outlet_frac=(np.asarray(sB.outlet_frac).copy()
                         if getattr(sB, 'outlet_frac', None) is not None else None),
            eps=(np.asarray(sB.eps_field).copy()
                 if getattr(sB, 'eps_field', None) is not None else None),
            dx=sB.dx.copy(), dy=sB.dy.copy(), dz=sB.dz.copy(),
            dir_real=fB['dir'],
            solver_to_real_perm=sB_info['axis_map']['solver_to_real_perm'],
        ) if sB is not None else None),
        _audit_ltne_mask_B=(np.asarray(_ltne_mask_B).copy()
                             if _ltne_mask_B is not None else None),
        _audit_ltne_mask_A=(np.asarray(_ltne_mask_A).copy()
                             if _ltne_mask_A is not None else None),
        _audit_in_mask_B=(np.asarray(in_mask_B).copy()
                          if (sB is not None and in_mask_B is not None) else None),
        _audit_out_mask_B=(np.asarray(out_mask_B).copy()
                           if (sB is not None and out_mask_B is not None) else None),
        _audit_in_mask_2d=(np.asarray(in_mask_2d).copy()
                           if in_mask_2d is not None else None),
        _audit_out_mask_2d=(np.asarray(out_mask_2d).copy()
                            if out_mask_2d is not None else None),
        _audit_m_dot_A_simple=float(m_dot_A_simple),
        _audit_m_dot_B_simple=(float(m_dot_B_simple) if sB is not None else None),
        _audit_m_dot_B_phys_in=(float(m_dot_B_phys_in) if sB is not None else None),
        _audit_m_dot_B_phys_out=(float(m_dot_B_phys_out) if sB is not None else None),
        _audit_cp_A=float(cp_A),
        _audit_cp_B=(float(cp_B) if sB is not None else None),
        _audit_T_inA=float(T_inA),
        _audit_T_inB=(float(T_inB) if sB is not None else None),
        _audit_u_A=float(u_A),
        _audit_u_B=(float(u_B) if sB is not None else None),
        _audit_eps=float(eps),
        _audit_fA=dict(fA),
        _audit_fB=(dict(fB) if fB is not None else None),
        # Phase 2 conservation-residual exports (post-χ_B for K_ffB)
        _audit_K_ffA=K_ffA.copy(),
        _audit_K_ffB=K_ffB.copy(),
        _audit_K_ss=K_ss.copy(),
        _audit_eps_arr=eps_arr.copy(),
        _audit_rho_cp_fA=rho_cp_fA.copy(),
        _audit_rho_cp_fB=rho_cp_fB.copy(),
        _audit_chi_B=(chi_B.copy() if chi_B is not None else None),
        _audit_P_inA=float(P_inA),
        _audit_P_inB=float(P_inB),
        )
    return _result
