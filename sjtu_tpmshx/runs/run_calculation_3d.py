"""run_calculation_3d.py — 3D compute pipeline for SJTU-TPMSHX UI.

Mirrors `runs.run_calculation` (2D) but dispatches the 3D stack:
    SIMPLESolver3D (fluid A: air compressible, fluid B: air or water) +
    LTNE 3-temp coupling + solve_full_domain_3d (3D LTNE) + outer non-iso.

MVP (2026-04-20): uniform geometry only (no zoning from UI). Mirrors
`validation/validate_shanghai_3d_real.py::_run_one_case` but with UI-sourced
parameters instead of Shanghai Excel.

Entry:
    run_calculation_3d_inner(window)     — runs stack, stores fields on window
    (visualisation — finalize_plots_3d(window) — now lives in
     ui/plot_3d_results.py so this module stays Qt/matplotlib-free.)

Stored on window:
    window._result_3d = dict(
        Ta=..., vmag=..., P_kPa=..., L_mm=...,
        dx=..., dy=..., dz=...,
        Lx=..., Ly=..., Lz=...,
        Q=..., dP=..., u_A=..., T_in=...,
    )
"""

from __future__ import annotations
import os
import time as _time
import numpy as np

from controllers.compute_config import ComputeConfig, bc_to_dict
from solvers.simple_solver_3d import SIMPLESolver3D
from solvers.ltne_energy_3d import solve_full_domain_3d
from solvers.tpms_calc import (
    geometry as tpms_geometry, air_density, air_viscosity,
    air_conductivity, air_cp, P_atm,
    water_density, water_viscosity, water_conductivity, water_cp,
)
from solvers import fluid_props
from df_surrogate.predict import predict_K_cF
from solvers.roughness import (f_enhancement, nu_extra_factor,
                                 resolve_mode_from_env)


# ⚠ 2026-05-14 (revised): `norris_1a` is now a no-op for friction (f×1.0,
# alias of `baseline`). The ×1.28 Nu factor in tpms_calc air-Gyroid is the
# only roughness compensation; c_F was trained on real SLM dP so the friction
# side already encodes Sa. See `solvers/roughness.py` module docstring for
# the audit history (1.46 → 1.28 → 1.0).
#
# Naming retained for back-compat with existing config files / BO defaults
# (optimization/evaluator_3d.py also defaults to 'norris_1a'). 2D path in
# run_calculation.py defaults to 'baseline' — label asymmetry is cosmetic
# only (verified 2026-05-28 audit C2 follow-up). Stale earlier comment had
# claimed "norris_1a closes 44.74 %→24.15 %"; that data is from the pre-
# revert multiplier-bearing version and is obsolete post-2026-05-14.
_UI_ROUGH_MODE_DEFAULT = 'norris_1a'


def _resolve_ui_roughness():
    """Read mode + ε from env; default to norris_1a so UI matches BO."""
    return resolve_mode_from_env(default=_UI_ROUGH_MODE_DEFAULT)


# ---------------------------------------------------------------------------
# Face-flux helpers (module-level so they can be unit-tested independently)
# ---------------------------------------------------------------------------
def _face_flux_weights(solver, dir_code, face='real_outlet',
                       eps_mode='ltne', chi_face=None,
                       eps_f_per_side=None):
    """Unified face-flux weight array for T_out, m_dot, Q_enth.

    Parameters
    ----------
    solver : SIMPLESolver3D
    dir_code : int — 0=+x,1=-x,2=+y,3=-y,4=+z,5=-z
    face : 'real_inlet' or 'real_outlet'
    eps_mode : 'ltne' (× eps_f) or 'physical' (no eps_f)
    chi_face : optional 2D array — χ_B at this face for ghost suppression
    eps_f_per_side : optional scalar fallback when solver has no eps_field

    Returns
    -------
    w : 2D ndarray — face flux weights [kg/s] or eps_f·[kg/s].
        sum(w) = effective mass flow through this face.
    """
    # approach-(a): the solver is direction-agnostic — it always injects at
    # j=0 (inlet_frac) and exhausts at j=-1 (outlet_frac). The reverse-dir
    # spatial flip lives in the velocity transforms, NOT here, so the real
    # inlet maps to solver j=0 and the real outlet to j=-1 for ALL dirs.
    # (Was: an is_reverse branch swapping faces/masks — that was approach-(b)
    # and double-counted the flip, mirroring the reverse accounting.)
    if face == 'real_outlet':
        v_face = solver.v[:, -1, :]
        rho_face = solver.rho_field[:, -1, :]
        mask_face = getattr(solver, 'outlet_frac', None)
        face_idx = -1
    else:  # real_inlet
        v_face = solver.v[:, 0, :]
        rho_face = solver.rho_field[:, 0, :]
        mask_face = getattr(solver, 'inlet_frac', None)
        face_idx = 0
    dx_sol = solver.dx[:, None]; dz_sol = solver.dz[None, :]
    w = rho_face * np.abs(v_face) * dx_sol * dz_sol
    if eps_mode == 'ltne':
        eps_full = getattr(solver, 'eps_field', None)
        if eps_full is not None:
            w = w * (0.5 * np.asarray(eps_full[:, face_idx, :],
                                      dtype=np.float64))
        else:
            if eps_f_per_side is None:
                raise ValueError(
                    "_face_flux_weights: eps_mode='ltne' requires either "
                    "solver.eps_field or explicit eps_f_per_side")
            w = w * float(eps_f_per_side)
    if mask_face is not None:
        w = w * np.asarray(mask_face, dtype=np.float64)
    if chi_face is not None:
        w = w * np.asarray(chi_face, dtype=np.float64)
    return w


def _mass_weighted_T_out(T_face, solver, dir_code, eps_f_scalar,
                          chi_face=None):
    """Mass-flux-weighted T average at the REAL outlet face.
    Delegates to _face_flux_weights for consistent weighting.

    Falls back to naive face mean when the effective mass flow drops below
    1e-30 (e.g. no active outlet, fully blocked face). Mass-flux weights
    naturally suppress stagnant warm cells where ρ·|v| ≈ 0.
    """
    try:
        w = _face_flux_weights(solver, dir_code, face='real_outlet',
                               eps_mode='ltne', chi_face=chi_face,
                               eps_f_per_side=eps_f_scalar)
        tot = float(np.sum(w))
        if tot < 1e-30:
            return float(np.mean(T_face))
        return float(np.sum(T_face * w) / tot)
    except Exception:
        return float(np.mean(T_face))


# ── Direction → axis single source ──────────────────────────────────────────
# dir_code: 0=+x 1=-x 2=+y 3=-y 4=+z 5=-z (matches the 2D _dir_int convention).
# These helpers are the ONE place the dir→axis/index mapping is encoded; every
# face-slice / BC-mask / streamwise-component dispatch derives from them, so a
# direction cannot go inconsistent across call sites (the failure mode the
# reverse-dir saga kept reintroducing). Forward dirs (even) inject at stream
# index 0 and exhaust at -1; reverse dirs (odd) mirror that. 2026-06-09 A3.
def _stream_axis(dir_code):
    """Real-coord streamwise axis: 0/1→x(0), 2/3→y(1), 4/5→z(2)."""
    return int(dir_code) // 2


def _dir_is_reverse(dir_code):
    """True for negative-going dirs (-x/-y/-z = odd codes 1/3/5)."""
    return bool(int(dir_code) % 2)


def _inlet_index(dir_code):
    """Stream-axis index of the REAL inlet face (0 forward, -1 reverse)."""
    return -1 if _dir_is_reverse(dir_code) else 0


def _outlet_index(dir_code):
    """Stream-axis index of the REAL outlet face (-1 forward, 0 reverse)."""
    return 0 if _dir_is_reverse(dir_code) else -1


def _face_slice(field, dir_code, which):
    """View of ``field``'s real inlet/outlet face. which ∈ {'inlet','outlet'}.
    Returns the same axis-collapsed view the hand-rolled ladders did."""
    idx = _inlet_index(dir_code) if which == 'inlet' else _outlet_index(dir_code)
    sl = [slice(None), slice(None), slice(None)]
    sl[_stream_axis(dir_code)] = idx
    return field[tuple(sl)]


def _real_outlet_slice(T_field, dir_code):
    return _face_slice(T_field, dir_code, 'outlet')


def _simple_mass_flow(solver, dir_code, eps_f_per_side=None):
    """LTNE-effective m_dot at REAL inlet face via _face_flux_weights."""
    try:
        w = _face_flux_weights(solver, dir_code, face='real_inlet',
                               eps_mode='ltne',
                               eps_f_per_side=eps_f_per_side)
        return float(np.sum(w))
    except Exception:
        return 0.0


def _apply_roughness_KcF(K_arr, cF_arr, fluid_type, rho, mu, u, D_h_m):
    """Scale K/cF arrays by f_enhancement; skip fluids whose closure already
    embeds AM roughness (water: Yan [6]) — registry flag, B1 1.1."""
    if fluid_props.get(fluid_type).embeds_roughness:
        return K_arr, cF_arr
    mode, eps_um = _resolve_ui_roughness()
    if mode == 'baseline':
        return K_arr, cF_arr
    Re_loc = float(rho * abs(u) * D_h_m / max(mu, 1.0e-12))
    f_gain = float(f_enhancement(Re_loc, mode,
                                  eps_um=eps_um, D_h_mm=D_h_m * 1000.0))
    return (K_arr / f_gain).astype(np.float64, copy=False), \
           (cF_arr * f_gain).astype(np.float64, copy=False)


def _apply_roughness_h_v(h_v_field, fluid_type, rho, mu, u, D_h_m):
    """Multiply h_v by nu_extra_factor; skip roughness-embedding fluids
    (registry flag, B1 1.1). Norris 1a returns 1.0 (Nu unchanged ×1.28),
    so this is a no-op for the default mode; only bhatti_shah_1b actually
    rescales Nu."""
    if fluid_props.get(fluid_type).embeds_roughness:
        return h_v_field
    mode, eps_um = _resolve_ui_roughness()
    if mode == 'baseline':
        return h_v_field
    Re_loc = float(rho * abs(u) * D_h_m / max(mu, 1.0e-12))
    nu_extra = float(nu_extra_factor(Re_loc, mode,
                                      eps_um=eps_um, D_h_mm=D_h_m * 1000.0))
    if nu_extra == 1.0:
        return h_v_field
    return (h_v_field * nu_extra).astype(np.float64, copy=False)


# 2026-04-26: env var TPMSHX_SIMPLE_TOL overrides default SIMPLE pp tol for
# diagnostic sweeps (path 0 / 0' v3 plan). Read each call to allow sweeps.
def _simple_tol_default():
    return float(os.environ.get('TPMSHX_SIMPLE_TOL', '1e-5'))


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
            print(f"[PROF-RES] {tag}: (no residuals)", flush=True)
            return
        import numpy as _np
        arr = _np.asarray(r, dtype=float)
        i_min = int(_np.argmin(arr))
        head = " ".join(f"{x:.2e}" for x in arr[:5])
        tail = " ".join(f"{x:.2e}" for x in arr[-5:])
        print(f"[PROF-RES] {tag}: n={len(arr)} first=[{head}] "
              f"last=[{tail}] min={arr[i_min]:.2e}@{i_min} "
              f"final={arr[-1]:.2e}", flush=True)
    except Exception as _e:
        print(f"[PROF-RES] {tag}: trace failed: {_e}", flush=True)


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
        print(f"[PROF] initial SIMPLE (A||B parallel) {_dt:7.2f}s  "
              f"A={res[0]}  B={res[1]}  (cap={max_iter})", flush=True)
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


def run_calculation_3d_inner(window):
    """Adapter (audit C3): builds a strict :class:`ComputeConfig` from
    the window then delegates to :func:`run_calculation_3d_inner_cfg`.

    Callers that already hold a :class:`ComputeConfig` (tests, future
    C4 Pipeline) should call ``_cfg`` directly to skip the Qt read.
    """
    compute_cfg = ComputeConfig.from_qt_window(window, strict=True,
                                                force_3d=True)
    return run_calculation_3d_inner_cfg(compute_cfg, window)


def run_calculation_3d_inner_cfg(compute_cfg, window):
    """Phase 1: parse inputs → build fields → solve → store.

    ``window`` still required for non-le_* state (zone_grid, cancel
    token, _compute_progress, extrap reasons, K/°C hook). C4 task to
    extract that into a SessionState object.
    """
    cfg = _parse_inputs(window, compute_cfg)
    def _prog(pct):
        window._compute_progress = pct
    cfg['_progress_cb'] = _prog
    cfg['_cancel_check'] = lambda: bool(getattr(window, '_compute_cancel', False))
    # Outer-iteration label hook — the UI ticker (_tick_btn / _tick_3d) reads
    # window._iter_label_now to show "outer k/N" so the user sees progress
    # through the SIMPLE↔LTNE coupling loop (3D previously published none, so
    # the button/status showed only elapsed time).
    def _iter_cb(outer, n_outer):
        window._iter_label_now = f"outer {outer}/{n_outer}"
    cfg['_iter_cb'] = _iter_cb
    # Phase A/B/C acceleration flags — see _apply_phase_flags.
    _apply_phase_flags(cfg)
    result = _run_3d_stack(cfg)
    # Tag extrap provenance — set by `_parse_inputs` when surrogate domain
    # guard downgraded to warn. Lets downstream (UI panel, export) flag the
    # result without re-running the range check.
    _reasons = list(getattr(window, '_extrap_reasons', []) or [])
    result['extrapolated'] = bool(_reasons)
    result['extrap_reasons'] = _reasons
    window._result_3d = result
    window._has_extrap = bool(_reasons)
    # Qt widgets are updated by finalize_plots_3d on the GUI thread.


# ── 3D result visualisation (PyVistaQt panel + 2D mid-z slice canvases) was
#    extracted to ui/plot_3d_results.py (2026-06-09 Group-4 slice A1/A2):
#    finalize_plots_3d / _render_2d_slices_from_3d / _plot_3d_{temperature,
#    pressure,velocity} / _begin_canvas_plot / _style_axis /
#    _store_3d_result_labels / _fmt_metric. Moved out so this compute module
#    no longer imports ui.theme / matplotlib (C4 'Qt-free' contract).


# ─────────────────────────── internals ────────────────────────────

def _parse_inputs_3d_cfg(compute_cfg):
    """Phase 1 (Qt-free) 3D mirror of ``_parse_inputs(window, compute_cfg)``.

    Audit C4 (L-a-2): reads only :class:`ComputeConfig`. Returns the
    same parsed dict ``_run_3d_stack`` expects plus an
    ``extrap_reasons`` key (the legacy version mutated this onto
    ``window._extrap_reasons``).
    """
    # ── scalar geometry + grid + fluids ─────────────────────────────
    L = compute_cfg.geometry.L_dom_m
    H = compute_cfg.geometry.H_dom_m
    Lz = (compute_cfg.geometry.Lz_m
          if compute_cfg.geometry.Lz_m is not None else 0.042)
    Nx = compute_cfg.solver.Nx
    Ny = compute_cfg.solver.Ny
    Nz = compute_cfg.solver.Nz

    for name, val in [('L', L), ('H', H), ('Lz', Lz)]:
        if val <= 0:
            raise ValueError(
                f"Domain dimension {name!r} must be > 0 (got {val})")
    _DOMAIN_MAX_M = 10.0
    for name, val in [('L', L), ('H', H), ('Lz', Lz)]:
        if val > _DOMAIN_MAX_M:
            raise ValueError(
                f"Domain dimension {name!r}={val} m exceeds "
                f"{_DOMAIN_MAX_M} m. Likely unit slip — GUI expects "
                f"meters here, while L_cell and t use millimeters. "
                f"Re-check input.")
    for name, val in [('Nx', Nx), ('Ny', Ny), ('Nz', Nz)]:
        if val < 1:
            raise ValueError(
                f"Grid count {name!r} must be >= 1 (got {val})")

    u_A = compute_cfg.fluid_A.u_mps
    u_B = compute_cfg.fluid_B.u_mps
    T_inA = compute_cfg.fluid_A.T_in_K
    T_inB = compute_cfg.fluid_B.T_in_K
    T_s_init = compute_cfg.solver.T_s_init_K
    P_inA = compute_cfg.fluid_A.P_in_Pa
    P_inB = compute_cfg.fluid_B.P_in_Pa
    Lcell = compute_cfg.geometry.L_cell_mm
    t_wall = compute_cfg.geometry.t_wall_mm
    k_s = compute_cfg.geometry.k_s_W_mK
    tpms_type = compute_cfg.geometry.tpms

    g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
    eps = g['epsilon']
    D_h = g['D_h']

    # Partial-pipe BC dicts — side A full-face fallback, side B None.
    fluid_A_cfg = bc_to_dict(compute_cfg.bc_A, L, H, side='A', with_z=True)
    fluid_B_cfg = bc_to_dict(compute_cfg.bc_B, L, H, side='B', with_z=True)

    # Surrogate-domain extrap guard — cfg.extrap.allow drives it.
    extrap_reasons = []
    _allow_extrap = bool(compute_cfg.extrap.allow)
    try:
        from df_surrogate.surrogate_domain import check_surrogate_domain_at_point
        extrap_reasons += check_surrogate_domain_at_point(
            tpms_type, Lcell, t_wall, k_s,
            u_A, T_inA, P_inA, side='A',
            allow_extrap=_allow_extrap) or []
        extrap_reasons += check_surrogate_domain_at_point(
            tpms_type, Lcell, t_wall, k_s,
            u_B, T_inB, P_inB, side='B',
            allow_extrap=_allow_extrap) or []
    except ImportError:
        # surrogate_domain module unavailable → skip the extrap-domain check.
        # A ValueError from the check is a real domain violation and must
        # propagate, so it is intentionally not caught here.
        pass

    from solvers.tpms_calc import validate_fluid_type
    fluid_type_A = compute_cfg.fluid_A.type
    fluid_type_B = compute_cfg.fluid_B.type
    validate_fluid_type(fluid_type_A, 'A')
    validate_fluid_type(fluid_type_B, 'B')

    # Feature flags — sourced from cfg.flags + cfg.zones.
    wall_refine = bool(compute_cfg.flags.wall_refine_3d)
    zone_grid_cells = None
    if (compute_cfg.zones.enabled and compute_cfg.zones.grid is not None):
        zg = compute_cfg.zones.grid
        if isinstance(zg, dict) and zg.get('cells'):
            zone_grid_cells = zg['cells']

    return dict(
        L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        u_A=u_A, u_B=u_B, T_inA=T_inA, T_inB=T_inB,
        P_inA=P_inA, P_inB=P_inB,
        T_s_init=T_s_init,
        Lcell=Lcell, t_wall=t_wall, k_s=k_s, tpms_type=tpms_type,
        eps=eps, D_h=D_h,
        fluid_A_cfg=fluid_A_cfg,
        fluid_B_cfg=fluid_B_cfg,
        wall_refine_3d=wall_refine,
        variable_rho_cp=bool(compute_cfg.flags.variable_rho_cp),
        zone_grid_cells=zone_grid_cells,
        fluid_type_A=fluid_type_A,
        fluid_type_B=fluid_type_B,
        extrap_reasons=extrap_reasons,
        compute_cfg=compute_cfg,
    )


def _build_fields_3d_cfg(parsed):
    """Phase 2 (Qt-free) 3D: passthrough.

    Audit C4 (L-a-2). The 3D stack has no separate build phase — the
    cfg dict from :func:`_parse_inputs_3d_cfg` is consumed directly by
    :func:`_run_3d_stack`. This stub keeps the Pipeline ABC contract
    symmetric with 2D: ``build_fields → run_solvers → finalize``.
    """
    return parsed


def _run_solvers_3d_cfg(parsed, fields, *, progress_cb=None,
                         cancel_token=None):
    """Phase 3 (Qt-free) 3D: drive :func:`_run_3d_stack` with the
    progress + cancel hooks read off the cfg dict.

    Audit C4 (L-a-2). Wraps the existing ``_run_3d_stack(cfg)`` body
    without modifying it.  ``parsed`` and ``fields`` are the same dict
    (the build phase is a passthrough); the Pipeline ABC contract
    surfaces both so the signature matches :class:`Pipeline2D`.
    """
    cfg = dict(parsed)  # shallow copy — _run_3d_stack mutates a few keys

    # Progress + cancel hooks (mirrors legacy run_calculation_3d_inner_cfg).
    if progress_cb is not None:
        cfg['_progress_cb'] = (lambda pct, _cb=progress_cb: _cb(int(pct)))
    if cancel_token is not None:
        cfg['_cancel_check'] = (lambda _tok=cancel_token:
                                bool(getattr(_tok, 'cancelled', False)))

    # Phase A/B/C acceleration flags — see _apply_phase_flags.
    _apply_phase_flags(cfg)

    return _run_3d_stack(cfg)


def _finalize_3d_cfg(raw, fields):
    """Phase 4 (Qt-free) 3D: assemble a :class:`ComputeResult` from the
    ``_run_3d_stack`` output.

    Audit C4 (L-a-2). The 3D result dict is much richer than the 2D
    one — most fields land in ``ComputeResult.fields`` /
    ``ComputeResult.diagnostics``. The headline scalars (``Q_total``,
    ``dP_A`` / ``dP_B``, ``T_out_A`` / ``T_out_B``) lift directly.

    ⚠ Dual-representation contract: the raw dict (this function's ``raw`` arg)
    is the LIVE result carrier (window._result_3d → ui.plot_3d_results); the
    ComputeResult below is the C4 Pipeline view. They must not drift — the
    mapping here is locked by ``tests/test_finalize_3d_result_sync.py`` (G1).
    Full unification (live UI → ComputeResult) is the deliberate C4 migration,
    not done here.
    """
    from controllers.compute_pipeline import ComputeResult
    compute_cfg = fields.get('compute_cfg')

    # 3D solver already computed mass-weighted outlet T per side.
    # ``raw.get(key, default)`` only returns ``default`` when ``key`` is
    # absent — explicit ``None`` values (e.g. when fluid B is frozen)
    # come back as ``None``, which would crash ``float(None)``. Guard
    # via ``or`` so any None / missing value falls back to ``nan``.
    def _safe_float(v):
        try:
            return float(v) if v is not None else float('nan')
        except (TypeError, ValueError):
            return float('nan')

    T_out_A = _safe_float(raw.get('T_out_A', raw.get('T_A_out')))
    T_out_B = _safe_float(raw.get('T_out_B', raw.get('T_B_out')))

    # TPMS geometry (eps + D_h + A_0) for props slot.
    eps_geom = D_h_m = A_0_m2 = float('nan')
    if compute_cfg is not None:
        from solvers.tpms_calc import geometry as _tpms_geom
        g = _tpms_geom(compute_cfg.geometry.tpms,
                       compute_cfg.geometry.L_cell_mm,
                       compute_cfg.geometry.t_wall_mm,
                       compute_cfg.geometry.k_s_W_mK)
        eps_geom = g['epsilon']
        D_h_m = g['D_h']
        A_0_m2 = g['A_0']

    return ComputeResult(
        Q_W=_safe_float(raw.get('Q_total', raw.get('Q'))),
        dP_A_Pa=_safe_float(raw.get('dP_A', raw.get('dP'))),
        dP_B_Pa=_safe_float(raw.get('dP_B')),
        T_out_A_K=T_out_A,
        T_out_B_K=T_out_B,
        fields={
            'Ta': raw.get('Ta'),
            'Tb': raw.get('Tb'),
            'Ts': raw.get('Ts'),
            'P_fA': raw.get('P_Pa'),
            'P_fB': raw.get('P_Pa_B'),
            'ucA': raw.get('uc_real'),
            'vcA': raw.get('vc_real'),
            'wcA': raw.get('wc_real'),
            'ucB': raw.get('uc_real_B'),
            'vcB': raw.get('vc_real_B'),
            'wcB': raw.get('wc_real_B'),
            'dx': raw.get('dx'),
            'dy': raw.get('dy'),
            'dz': raw.get('dz'),
            'Lx': raw.get('Lx'),
            'Ly': raw.get('Ly'),
            'Lz': raw.get('Lz'),
            'dir_A': raw.get('dir_A'),
            'dir_B': raw.get('dir_B'),
            'vmag_A': raw.get('vmag'),
            'vmag_B': raw.get('vmag_B'),
            'chi_B': raw.get('chi_B'),
            'h_vA_field': raw.get('h_vA_field'),
            'h_vB_field': raw.get('h_vB_field'),
        },
        coeffs={
            'K_ffA': raw.get('_audit_K_ffA'),
            'K_ffB': raw.get('_audit_K_ffB'),
            'K_ss': raw.get('_audit_K_ss'),
        },
        props={
            'eps_A': eps_geom,
            'D_h_m': D_h_m,
            'A_0_m2': A_0_m2,
            'rho_cp_A': raw.get('_audit_rho_cp_fA'),
            'rho_cp_B': raw.get('_audit_rho_cp_fB'),
        },
        residuals={
            'Q_enthalpy_A': _safe_float(raw.get('Q_enthalpy_A')),
            'Q_enthalpy_B': _safe_float(raw.get('Q_enthalpy_B')),
            'Q_solid_B': _safe_float(raw.get('Q_solid_B')),
            'Q_sA': _safe_float(raw.get('Q_sA')),
            'Q_sB': _safe_float(raw.get('Q_sB')),
            'Q_net': _safe_float(raw.get('Q_net')),
            'Q_interior': _safe_float(raw.get('Q_interior')),
            'energy_imbalance_rel': _safe_float(
                raw.get('energy_imbalance_rel')),
            'mass_imbalance_rel_A': _safe_float(
                raw.get('mass_imbalance_rel_A')),
            'mass_imbalance_rel_B': _safe_float(
                raw.get('mass_imbalance_rel_B')),
        },
        zones=None,  # 3D zones land in fields['chi_B'] / fields['*'] directly
        warnings=[],
        extrap_reasons=list(fields.get('extrap_reasons', [])),
        diagnostics={
            '_ltne_info': raw.get('_ltne_info'),
            'AB_interior': raw.get('AB_interior'),
            'Q_sA_interior': raw.get('Q_sA_interior'),
            'Q_sB_interior': raw.get('Q_sB_interior'),
        },
    )


def _parse_inputs(window, compute_cfg=None):
    """Phase 1 adapter: thin wrapper around :func:`_parse_inputs_3d_cfg`
    that propagates the extrap-reasons list back onto ``window`` so the
    UI watermark + status-bar handler keep working.

    Audit C4 (L-a-2): the cfg-pure body lives in ``_parse_inputs_3d_cfg``;
    Pipeline3D drives that directly without a window.
    """
    if compute_cfg is None:
        compute_cfg = ComputeConfig.from_qt_window(window, strict=True,
                                                    force_3d=True)
    parsed = _parse_inputs_3d_cfg(compute_cfg)
    if window is not None:
        window._extrap_reasons = list(parsed.get('extrap_reasons', []))
    return parsed


def _resolve_axis_map(fA, Nx, Ny, Nz, L, H, Lz, dx, dy, dz):
    """Map fluid-A direction code to SIMPLE3D solver axes + mask geometry.

    `dir_A`: 0=+x 1=-x 2=+y 3=-y  (matches 2D `_dir_int` convention).

    Maps fluid direction (0/1=±x, 2/3=±y, 4/5=±z) to SIMPLESolver3D axes.
    SIMPLE3D enforces streamwise = solver Y axis, inlet at solver y=0.
    We permute real (x, y, z) → solver (X_sol, Y_sol=stream, Z_sol) so the
    streamwise face is at solver y=0, then transpose fields back for visualisation.

    Returns dict with:
      is_x_stream (dir ∈ {0,1}), is_y_stream (2,3), is_z_stream (4,5)
      is_reverse (dir ∈ {1,3,5}: negative direction)
      solver_init, N_stream, N_cross1, N_cross2, L_stream, L_cross1, L_cross2
      dstream, dcross1, dcross2
      stream_real_axis (0, 1, or 2)
      cross1_real_axis, cross2_real_axis
      solver_to_real_perm : tuple for arr.transpose() mapping solver → real
    """
    d = fA['dir']
    is_reverse = d in (1, 3, 5)
    if d in (0, 1):
        # Streamwise real x.  Solver Ly=L(x), Lx=H(y), Lz=Lz(z).
        return dict(
            is_x_stream=True, is_y_stream=False, is_z_stream=False,
            is_reverse=is_reverse,
            solver_init=dict(Lx=H, Ly=L, Lz=Lz, Nx=Ny, Ny=Nx, Nz=Nz),
            N_stream=Nx, N_cross1=Ny, N_cross2=Nz,
            L_stream=L, L_cross1=H, L_cross2=Lz,
            dstream=dx, dcross1=dy, dcross2=dz,
            stream_real_axis=0, cross1_real_axis=1, cross2_real_axis=2,
            solver_to_real_perm=(1, 0, 2),   # solver (Ny,Nx,Nz) → real (Nx,Ny,Nz)
            N_cross=Ny, L_cross=H, dcross=dy,  # back-compat aliases
        )
    if d in (2, 3):
        # Streamwise real y.  Solver Ly=H(y), Lx=L(x), Lz=Lz(z).
        return dict(
            is_x_stream=False, is_y_stream=True, is_z_stream=False,
            is_reverse=is_reverse,
            solver_init=dict(Lx=L, Ly=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz),
            N_stream=Ny, N_cross1=Nx, N_cross2=Nz,
            L_stream=H, L_cross1=L, L_cross2=Lz,
            dstream=dy, dcross1=dx, dcross2=dz,
            stream_real_axis=1, cross1_real_axis=0, cross2_real_axis=2,
            solver_to_real_perm=(0, 1, 2),   # solver (Nx,Ny,Nz) = real (Nx,Ny,Nz)
            N_cross=Nx, L_cross=L, dcross=dx,
        )
    # d in (4, 5): streamwise real z.  Solver Ly=Lz(z), Lx=L(x), Lz=H(y).
    return dict(
        is_x_stream=False, is_y_stream=False, is_z_stream=True,
        is_reverse=is_reverse,
        solver_init=dict(Lx=L, Ly=Lz, Lz=H, Nx=Nx, Ny=Nz, Nz=Ny),
        N_stream=Nz, N_cross1=Nx, N_cross2=Ny,
        L_stream=Lz, L_cross1=L, L_cross2=H,
        dstream=dz, dcross1=dx, dcross2=dy,
        stream_real_axis=2, cross1_real_axis=0, cross2_real_axis=1,
        solver_to_real_perm=(0, 2, 1),   # solver (Nx,Nz,Ny) → real (Nx,Ny,Nz)
        N_cross=Nx, L_cross=L, dcross=dx,
    )


def _build_zone_fields_3d(cells, Nx, Ny, Nz, L, H, tpms_type, k_s,
                           default_L, default_t):
    """Map 2D grid zones to 3D (Nx, Ny, Nz) L/t/eps fields (z-uniform).

    **3D geometry is currently a z-uniform extrusion of the 2D design** —
    a design change in (x, y) propagates identically through all Nz
    layers. This matches the "extrude the 2D TPMS pattern along z" MVP
    assumption. True 3D zoning (design varies along z as well) would
    require an Nz-dimensional decision vector in the optimiser and a
    different cell list shape — not wired in yet.

    cells: list of dicts {y0, y1, x0, x1, L, t} with 0-1 normalised x/y.
    Returns L_field / t_field / eps_field (mm, mm, 0-1).
    """
    from scipy.ndimage import gaussian_filter
    from solvers.tpms_calc import geometry as tpms_geometry
    L_2d = np.full((Nx, Ny), float(default_L), dtype=np.float64)
    t_2d = np.full((Nx, Ny), float(default_t), dtype=np.float64)
    for cell in cells:
        x_lo = int(round(cell['x0'] * Nx)); x_hi = int(round(cell['x1'] * Nx))
        y_lo = int(round(cell['y0'] * Ny)); y_hi = int(round(cell['y1'] * Ny))
        x_lo = max(0, min(x_lo, Nx)); x_hi = max(0, min(x_hi, Nx))
        y_lo = max(0, min(y_lo, Ny)); y_hi = max(0, min(y_hi, Ny))
        L_2d[x_lo:x_hi, y_lo:y_hi] = float(cell['L'])
        t_2d[x_lo:x_hi, y_lo:y_hi] = float(cell['t'])
    L_2d = gaussian_filter(L_2d, sigma=2.0)
    t_2d = gaussian_filter(t_2d, sigma=2.0)
    eps_2d = np.empty_like(L_2d)
    for i in range(Nx):
        for j in range(Ny):
            g = tpms_geometry(tpms_type, float(L_2d[i, j]),
                              float(t_2d[i, j]), float(k_s))
            eps_2d[i, j] = g['epsilon']
    L_field = np.broadcast_to(L_2d[:, :, None], (Nx, Ny, Nz)).copy()
    t_field = np.broadcast_to(t_2d[:, :, None], (Nx, Ny, Nz)).copy()
    eps_field = np.broadcast_to(eps_2d[:, :, None], (Nx, Ny, Nz)).copy()
    return L_field, t_field, eps_field


def _build_partial_masks(fA, dcross1, dcross2, N_cross1, N_cross2, is_reverse):
    """Build inlet/outlet boolean masks on the 2-axis inlet face.

    Solver's inlet_frac shape is (Nx_sol, Nz_sol) = (N_cross1, N_cross2).
    UI inputs `in_ctr/in_w` → cross1 axis; `in_z_ctr/in_z_w` → cross2 axis.
    For ±x/±y streamwise cross2 is real-z; for ±z streamwise cross2 is real-y.
    (Semantic mismatch noted in UI docs — future UI pass may relabel.)
    """
    c1_centres = np.cumsum(dcross1) - dcross1 / 2
    in_lo = fA['in_ctr'] - fA['in_w'] / 2
    in_hi = fA['in_ctr'] + fA['in_w'] / 2
    out_lo = fA['out_ctr'] - fA['out_w'] / 2
    out_hi = fA['out_ctr'] + fA['out_w'] / 2
    in_c1 = (c1_centres >= in_lo - 1e-12) & (c1_centres <= in_hi + 1e-12)
    out_c1 = (c1_centres >= out_lo - 1e-12) & (c1_centres <= out_hi + 1e-12)
    if not in_c1.any() or not out_c1.any():
        raise ValueError("Inlet / outlet range (cross1) resolves to zero cells.")

    # cross2 (z-partial keys — treated as second cross-axis regardless of label)
    has_c2_partial = all(k in fA for k in
                          ('in_z_ctr', 'in_z_w', 'out_z_ctr', 'out_z_w'))
    if has_c2_partial and dcross2 is not None:
        c2_centres = np.cumsum(dcross2) - dcross2 / 2
        in_z_lo = fA['in_z_ctr'] - fA['in_z_w'] / 2
        in_z_hi = fA['in_z_ctr'] + fA['in_z_w'] / 2
        out_z_lo = fA['out_z_ctr'] - fA['out_z_w'] / 2
        out_z_hi = fA['out_z_ctr'] + fA['out_z_w'] / 2
        in_c2 = (c2_centres >= in_z_lo - 1e-12) & (c2_centres <= in_z_hi + 1e-12)
        out_c2 = (c2_centres >= out_z_lo - 1e-12) & (c2_centres <= out_z_hi + 1e-12)
        if not in_c2.any() or not out_c2.any():
            raise ValueError("Inlet / outlet range (cross2) resolves to zero cells.")
    else:
        in_c2 = np.ones(N_cross2, dtype=bool)
        out_c2 = np.ones(N_cross2, dtype=bool)
    # approach-(a) reverse convention: NO in/out swap. The solver always
    # injects at j=0 with inlet_frac and exhausts at j=-1 with outlet_frac;
    # the reverse-dir spatial flip (in the velocity transforms) maps solver
    # j=0 onto the real inlet end, so in_mask must carry the PHYSICAL inlet
    # patch (in_ctr) regardless of direction. (Was: swap in_c<->out_c for
    # is_reverse — that was approach-(b) and contradicted the LTNE kernel.)
    in_mask = np.outer(in_c1, in_c2).astype(np.float64)   # (N_cross1, N_cross2)
    out_mask = np.outer(out_c1, out_c2).astype(np.float64)
    return in_mask, out_mask


def _solver_velocity_to_real(solver, axis_map, real_shape):
    """Map SIMPLE3D staggered velocity components back to real coordinates."""
    perm = axis_map['solver_to_real_perm']
    u_cc = 0.5 * (solver.u[:-1, :, :] + solver.u[1:, :, :])
    v_cc = 0.5 * (solver.v[:, :-1, :] + solver.v[:, 1:, :])
    w_cc = 0.5 * (solver.w[:, :, :-1] + solver.w[:, :, 1:])

    comps = [np.zeros(real_shape, dtype=np.float64) for _ in range(3)]
    comps[axis_map['cross1_real_axis']] = np.ascontiguousarray(
        u_cc.transpose(perm))
    stream = np.ascontiguousarray(v_cc.transpose(perm))
    if axis_map['is_reverse']:
        stream = -stream
    comps[axis_map['stream_real_axis']] = stream
    comps[axis_map['cross2_real_axis']] = np.ascontiguousarray(
        w_cc.transpose(perm))
    # approach-(a) reverse convention: y-reflection of the velocity field.
    # The solver injects at j=0 (its +stream); for a reverse-dir fluid the
    # real inlet is at the OPPOSITE stream end, so the field is spatially
    # flipped along the real stream axis (stream component already negated
    # above). Matches evaluate_3d's -vB_cc[:, ::-1, :] and the LTNE kernel's
    # approach-(a) inlet/outlet placement.
    if axis_map['is_reverse']:
        sax = axis_map['stream_real_axis']
        comps = [np.flip(c, axis=sax) for c in comps]
    return tuple(np.ascontiguousarray(c) for c in comps)


def _solver_staggered_to_real(solver, axis_map, real_shape):
    """Map SIMPLE3D staggered face velocities to REAL-coord face arrays.

    Returns (uf_real, vf_real, wf_real) of shapes:
      uf_real : (Nx+1, Ny, Nz)  — face velocities at real x-faces (+x signed)
      vf_real : (Nx, Ny+1, Nz)  — face velocities at real y-faces (+y signed)
      wf_real : (Nx, Ny, Nz+1)  — face velocities at real z-faces (+z signed)

    The stream component (solver's y-axis v) gets sign-flipped if is_reverse,
    because for reverse-dir fluids SIMPLE's local +y is the real -stream_axis.

    This is what `_gs_full_chunk_3d_stag` consumes — identical face fluxes
    to SIMPLE's momentum solver so ∇·(ρv) = 0 cell-wise (to SIMPLE's
    continuity residual) and the LTNE metric's NET_OUT is zero.
    """
    perm = axis_map['solver_to_real_perm']
    Nx, Ny, Nz = real_shape

    # SIMPLE's u is staggered in solver's X axis (cross1 in real).
    # Shape (Nx_sol+1, Ny_sol, Nz_sol). After transpose(perm): must end
    # up staggered in cross1_real_axis.
    # SIMPLE's v is staggered in solver Y (the stream).
    # SIMPLE's w is staggered in solver Z (cross2 in real).
    u_sol = solver.u  # (Nx_sol+1, Ny_sol, Nz_sol)
    v_sol = solver.v  # (Nx_sol, Ny_sol+1, Nz_sol)
    w_sol = solver.w  # (Nx_sol, Ny_sol, Nz_sol+1)

    # Transpose mirrors cell-centred components' perm. The extra +1
    # dimension survives the transpose automatically.
    u_real = np.ascontiguousarray(u_sol.transpose(perm))
    v_real = np.ascontiguousarray(v_sol.transpose(perm))
    w_real = np.ascontiguousarray(w_sol.transpose(perm))

    # Classify each transposed array into (x-staggered, y-staggered, z-staggered).
    # The original array is staggered along ONE solver axis; perm maps that axis
    # to the corresponding real axis. After transpose, the staggered axis lives
    # at real axis = perm.index(original_axis).
    # SIMPLE conventions:
    #   u staggered on solver axis 0 (cross1 in real → cross1_real_axis)
    #   v staggered on solver axis 1 (stream)
    #   w staggered on solver axis 2 (cross2)
    stream_ax = axis_map['stream_real_axis']
    cross1_ax = axis_map['cross1_real_axis']
    cross2_ax = axis_map['cross2_real_axis']

    # sign-flip the stream array for reverse dirs.
    is_reverse = axis_map['is_reverse']

    # Build outputs — assign each transposed staggered array to the slot
    # indexed by its real axis.
    out = [None, None, None]  # slot[k] = face array staggered in real axis k
    # u_real: staggered in axis perm.index(0) → cross1_real_axis
    # v_real: staggered in axis perm.index(1) → stream_real_axis
    # w_real: staggered in axis perm.index(2) → cross2_real_axis
    out[cross1_ax] = u_real
    stream_arr = v_real if not is_reverse else -v_real
    out[stream_ax] = stream_arr
    out[cross2_ax] = w_real

    # approach-(a) reverse convention: spatially flip the staggered face
    # arrays along the real stream axis (the stream component is already
    # negated above). A staggered array of size N+1 along the flip axis
    # reverses so the +1 face lands on the mirrored boundary — matches
    # evaluate_3d's sB.u/-sB.v/sB.w [:, ::-1, :] and keeps the face fluxes
    # discretely solenoidal for the conservative LTNE kernel.
    if is_reverse:
        out = [np.flip(o, axis=stream_ax) for o in out]

    uf_real = np.ascontiguousarray(out[0], dtype=np.float64)
    vf_real = np.ascontiguousarray(out[1], dtype=np.float64)
    wf_real = np.ascontiguousarray(out[2], dtype=np.float64)

    # Shape sanity check
    assert uf_real.shape == (Nx+1, Ny, Nz), f"uf {uf_real.shape} != ({Nx+1},{Ny},{Nz})"
    assert vf_real.shape == (Nx, Ny+1, Nz), f"vf {vf_real.shape} != ({Nx},{Ny+1},{Nz})"
    assert wf_real.shape == (Nx, Ny, Nz+1), f"wf {wf_real.shape} != ({Nx},{Ny},{Nz+1})"
    return uf_real, vf_real, wf_real


def _balance_stream_outflow(faces, axis_map, coef, dx, dy, dz):
    """Rescale the OUTFLOW stream-boundary face so the coef-weighted net flux
    through the two stream boundary faces is zero — discrete global mass
    conservation, ∮F·n dA = 0.

    Why: the strict conservative-LTNE kernel telescopes the SIMPLE staggered
    face fluxes (`F_e[i] ≡ F_w[i+1]`), so summing the per-cell energy balance
    over the domain collapses to the boundary integral ∮F·n. SIMPLE's converged
    velocity carries a small continuity residual; partial-BC inlet/outlet masks
    + the outlet taper amplify it for offset/reverse cases, leaving a nonzero
    net ΣD ≡ ∮F·n. The homogeneous-Neumann MAC projection
    (`_project_faces_div_free`) removes only the zero-mean part of that
    divergence — the constant null-space component (= the net ΣD) is
    irreducible, so it survives as a uniform spurious energy divergence and the
    reverse-dir heat load drifts (y-mirror breaks ~17 %, spurious over-heating).
    Enforcing Σ_inlet = Σ_outlet here drives ΣD → 0 BEFORE the projection, so
    the projection then cleans the interior to machine precision and the kernel
    is genuinely conservative for reverse-dir/offset fluids too.

    `coef` = eps_f · ρcp = the projection's per-cell flux coefficient (eps_f =
    0.5·ε). Near-balanced cases (full-face, Shanghai) get scale ≈ 1 → no-op.

    Mutates and returns `faces` = [uf, vf, wf] (already contiguous copies).
    """
    sax = int(axis_map['stream_real_axis'])
    is_rev = bool(axis_map['is_reverse'])
    F = faces[sax]
    # Perpendicular face area + boundary-cell coef (matching the projection's
    # boundary-face coefficient `cf[0]=coef[0]`, `cf[-1]=coef[-1]`).
    if sax == 0:
        A = dy[:, None] * dz[None, :]
        cf_lo, cf_hi = coef[0, :, :], coef[-1, :, :]
        sl_lo = (0, slice(None), slice(None)); sl_hi = (-1, slice(None), slice(None))
    elif sax == 1:
        A = dx[:, None] * dz[None, :]
        cf_lo, cf_hi = coef[:, 0, :], coef[:, -1, :]
        sl_lo = (slice(None), 0, slice(None)); sl_hi = (slice(None), -1, slice(None))
    else:
        A = dx[:, None] * dy[None, :]
        cf_lo, cf_hi = coef[:, :, 0], coef[:, :, -1]
        sl_lo = (slice(None), slice(None), 0); sl_hi = (slice(None), slice(None), -1)
    flux_lo = float(np.sum(cf_lo * F[sl_lo] * A))
    flux_hi = float(np.sum(cf_hi * F[sl_hi] * A))
    # Reverse-dir: inlet at the high-index face, outlet at low; forward: vice-versa.
    inlet_flux, outlet_flux = (flux_hi, flux_lo) if is_rev else (flux_lo, flux_hi)
    sl_out = sl_lo if is_rev else sl_hi
    # Degenerate / inconsistent outflow → leave to the projection's mean-zero
    # fallback rather than rescale by a wild factor.
    if abs(outlet_flux) < 1e-12 * (abs(inlet_flux) + 1e-30):
        return faces
    scale = inlet_flux / outlet_flux
    if not np.isfinite(scale) or scale <= 0.0:
        return faces
    F[sl_out] = F[sl_out] * scale
    return faces


# ──────────────────────────────────────────────────────────────────────────
# Per-cell χ_B participation field (Phase 1, 2026-05-04)
#
# Replaces the M4 0D scalar effective-area closure with a per-cell field
# in real (Nx, Ny, Nz) coords. χ_B(x) ∈ [0, 1] modulates BOTH:
#     h_vB_field *= χ_B          (zero source in pure ghost)
#     K_ffB      *= χ_B + floor  (zero diffusion path in pure ghost)
# Together they cut the ghost-B → active-B heat-leak path identified in the
# 2026-05-04 partial-B audit (vault/reports/3d-solver/2026-05-04-partial-b-
# ltne-audit-CN.md). Energy carried by the SIMPLE momentum solution is
# unaffected (eps_f, ρ_cp, advection face fluxes untouched).
#
# Two construction methods. Selectable via cfg['chi_B_method'].
#   - 'union_extrude'      Method A: streamwise extrusion of inlet ∪ outlet
#                          patches with cross-stream tanh ramp. Simple,
#                          works only for aligned partial-B.
#   - 'velocity_threshold' Method B (default): use the converged SIMPLE B
#                          velocity magnitude as the participation indicator,
#                          then dilate + smooth. Works for cross-flow with
#                          offset inlet/outlet patches (Shanghai case 1).
# ──────────────────────────────────────────────────────────────────────────

def _dilate_one_step_3d(arr):
    """Single-step 6-connected 3D max-dilation (no scipy dep)."""
    out = arr.copy()
    out[:-1] = np.maximum(out[:-1], arr[1:])
    out[1:]  = np.maximum(out[1:],  arr[:-1])
    out[:, :-1] = np.maximum(out[:, :-1], arr[:, 1:])
    out[:, 1:]  = np.maximum(out[:, 1:],  arr[:, :-1])
    out[:, :, :-1] = np.maximum(out[:, :, :-1], arr[:, :, 1:])
    out[:, :, 1:]  = np.maximum(out[:, :, 1:],  arr[:, :, :-1])
    return out


def _box_smooth_3d(arr, n_passes=2):
    """3-point box filter applied n_passes times along each of 3 axes.

    Edge cells use 2-point average. After n_passes, the discrete kernel
    approximates a Gaussian with σ ≈ sqrt(n_passes) cells; combined with
    binary input this gives a smooth tanh-like ramp at boundaries.
    """
    out = arr.copy()
    for _ in range(n_passes):
        # axis 0
        s = out.copy()
        if s.shape[0] >= 3:
            s[1:-1] = (out[:-2] + out[1:-1] + out[2:]) / 3.0
            s[0]    = (out[0]   + out[1])             / 2.0
            s[-1]   = (out[-1]  + out[-2])            / 2.0
        out = s
        # axis 1
        s = out.copy()
        if s.shape[1] >= 3:
            s[:, 1:-1] = (out[:, :-2] + out[:, 1:-1] + out[:, 2:]) / 3.0
            s[:, 0]    = (out[:, 0]   + out[:, 1])                 / 2.0
            s[:, -1]   = (out[:, -1]  + out[:, -2])                / 2.0
        out = s
        # axis 2
        s = out.copy()
        if s.shape[2] >= 3:
            s[:, :, 1:-1] = (out[:, :, :-2] + out[:, :, 1:-1] + out[:, :, 2:]) / 3.0
            s[:, :, 0]    = (out[:, :, 0]   + out[:, :, 1])                    / 2.0
            s[:, :, -1]   = (out[:, :, -1]  + out[:, :, -2])                   / 2.0
        out = s
    return out


def _build_chi_B_union_extrude(fB, dx_arr, dy_arr, dz_arr, shape, n_taper=3):
    """Method A: streamwise extrusion of (inlet ∪ outlet) patches in real coords.

    Patch boxes from fB cfg (in_ctr/in_w + in_z_ctr/in_z_w, same for out_*).
    Streamwise axis from fB['dir']:
        dir 0/1 → streamwise=x, cross=(y, z)
        dir 2/3 → streamwise=y, cross=(x, z)
        dir 4/5 → streamwise=z, cross=(x, y)
    Cross-stream tanh ramp via n_taper-pass box smoothing.

    Limitation: cross-flow with offset inlet/outlet patches creates two
    disconnected streamwise channels — the diagonal connecting corridor
    is NOT included. Use Method B (velocity_threshold) for such cases.
    """
    Nx, Ny, Nz = shape
    x_c = np.cumsum(dx_arr) - dx_arr / 2
    y_c = np.cumsum(dy_arr) - dy_arr / 2
    z_c = np.cumsum(dz_arr) - dz_arr / 2
    dir_B = int(fB['dir'])

    if dir_B in (0, 1):
        sw_axis = 0
        c1, c2 = y_c, z_c
    elif dir_B in (2, 3):
        sw_axis = 1
        c1, c2 = x_c, z_c
    else:
        sw_axis = 2
        c1, c2 = x_c, y_c

    eps_g = 1e-12
    in_lo_c1 = float(fB['in_ctr']) - float(fB['in_w']) / 2
    in_hi_c1 = float(fB['in_ctr']) + float(fB['in_w']) / 2
    out_lo_c1 = float(fB['out_ctr']) - float(fB['out_w']) / 2
    out_hi_c1 = float(fB['out_ctr']) + float(fB['out_w']) / 2
    in_lo_c2 = float(fB.get('in_z_ctr', c2.mean())) - float(fB.get('in_z_w', c2.max() - c2.min())) / 2
    in_hi_c2 = float(fB.get('in_z_ctr', c2.mean())) + float(fB.get('in_z_w', c2.max() - c2.min())) / 2
    out_lo_c2 = float(fB.get('out_z_ctr', c2.mean())) - float(fB.get('out_z_w', c2.max() - c2.min())) / 2
    out_hi_c2 = float(fB.get('out_z_ctr', c2.mean())) + float(fB.get('out_z_w', c2.max() - c2.min())) / 2

    in_c1 = (c1 >= in_lo_c1 - eps_g) & (c1 <= in_hi_c1 + eps_g)
    in_c2 = (c2 >= in_lo_c2 - eps_g) & (c2 <= in_hi_c2 + eps_g)
    out_c1 = (c1 >= out_lo_c1 - eps_g) & (c1 <= out_hi_c1 + eps_g)
    out_c2 = (c2 >= out_lo_c2 - eps_g) & (c2 <= out_hi_c2 + eps_g)

    in_2d = np.outer(in_c1, in_c2).astype(np.float64)
    out_2d = np.outer(out_c1, out_c2).astype(np.float64)
    union_2d = np.maximum(in_2d, out_2d)

    if sw_axis == 0:
        chi_3d = np.broadcast_to(union_2d[None, :, :], shape).copy()
    elif sw_axis == 1:
        chi_3d = np.broadcast_to(union_2d[:, None, :], shape).copy()
    else:
        chi_3d = np.broadcast_to(union_2d[:, :, None], shape).copy()

    if n_taper > 0:
        chi_3d = _box_smooth_3d(chi_3d, n_passes=n_taper)
    return np.clip(chi_3d, 0.0, 1.0)


def _build_chi_B_mass_flux_threshold(sB, axis_map_B, shape,
                                      threshold_frac=0.05,
                                      n_dilate=2, n_smooth=1,
                                      ref_mode='p75'):
    """Method H8: per-cell χ_B from actual mass-flux throughput.

    For each cell, compute the mass throughput as the **maximum** of the
    six face mass-fluxes |ρ·u_face·A|. A cell is 'participating' if its
    throughput > `threshold_frac` · ref_throughput.

    `ref_mode` selects the reference throughput value:
        'p75'  — 75th percentile (default, stable across grids)
        'p90'  — 90th percentile (closer to max, less robust)
        'p50'  — median (most robust, may be too low for narrow corridors)
        'max'  — max throughput (legacy; sensitive to extreme cells)
        'mean' — arithmetic mean (no robustness to skewed distributions)

    Percentile-based ref (p75 default) gives grid-independent sweet spot:
    median throughput in the active corridor scales with mass conservation,
    not with grid resolution. The factor 'threshold_frac' then represents
    the fraction of typical-flow throughput that defines the cutoff.

    Returns chi_B in REAL (Nx, Ny, Nz) coordinates.
    """
    Nx, Ny, Nz = shape
    u_sol = sB.u; v_sol = sB.v; w_sol = sB.w
    rho_sol = sB.rho_field
    dx_sol = sB.dx; dy_sol = sB.dy; dz_sol = sB.dz
    Nx_s, Ny_s, Nz_s = rho_sol.shape

    # Per-cell face-area arrays (broadcast)
    Ax_3d = np.broadcast_to(
        (dy_sol[None, :, None] * dz_sol[None, None, :]), rho_sol.shape)
    Ay_3d = np.broadcast_to(
        (dx_sol[:, None, None] * dz_sol[None, None, :]), rho_sol.shape)
    Az_3d = np.broadcast_to(
        (dx_sol[:, None, None] * dy_sol[None, :, None]), rho_sol.shape)

    # Face-cell ρ (linear interpolation between adjacent cells)
    if Nx_s > 1:
        rho_xface = 0.5 * (rho_sol[:-1, :, :] + rho_sol[1:, :, :])
    if Ny_s > 1:
        rho_yface = 0.5 * (rho_sol[:, :-1, :] + rho_sol[:, 1:, :])
    if Nz_s > 1:
        rho_zface = 0.5 * (rho_sol[:, :, :-1] + rho_sol[:, :, 1:])

    # |Mass flux| at each face of each cell, kg/s
    # u_sol shape (Nx_s+1, Ny_s, Nz_s). u_sol[i, :, :] is the face between
    # cell i-1 and cell i.
    flux_w = np.abs(rho_sol * u_sol[:-1, :, :]) * Ax_3d  # west face per cell
    flux_e = np.abs(rho_sol * u_sol[1:, :, :])  * Ax_3d  # east face per cell
    if Nx_s > 1:
        flux_w[1:, :, :] = np.abs(rho_xface * u_sol[1:-1, :, :]) * Ax_3d[1:, :, :]
        flux_e[:-1, :, :] = np.abs(rho_xface * u_sol[1:-1, :, :]) * Ax_3d[:-1, :, :]

    flux_s = np.abs(rho_sol * v_sol[:, :-1, :]) * Ay_3d
    flux_n = np.abs(rho_sol * v_sol[:, 1:, :])  * Ay_3d
    if Ny_s > 1:
        flux_s[:, 1:, :] = np.abs(rho_yface * v_sol[:, 1:-1, :]) * Ay_3d[:, 1:, :]
        flux_n[:, :-1, :] = np.abs(rho_yface * v_sol[:, 1:-1, :]) * Ay_3d[:, :-1, :]

    flux_b = np.abs(rho_sol * w_sol[:, :, :-1]) * Az_3d
    flux_t = np.abs(rho_sol * w_sol[:, :, 1:])  * Az_3d
    if Nz_s > 1:
        flux_b[:, :, 1:] = np.abs(rho_zface * w_sol[:, :, 1:-1]) * Az_3d[:, :, 1:]
        flux_t[:, :, :-1] = np.abs(rho_zface * w_sol[:, :, 1:-1]) * Az_3d[:, :, :-1]

    # Per-cell mass throughput = max of 6 face fluxes
    throughput_solver = np.maximum.reduce([
        flux_w, flux_e, flux_s, flux_n, flux_b, flux_t])

    m_max = float(np.max(throughput_solver))
    if m_max < 1e-30:
        return np.ones(shape, dtype=np.float64)

    # Reference throughput — percentile-based for grid-independence.
    if ref_mode == 'p50':
        m_ref = float(np.percentile(throughput_solver, 50))
    elif ref_mode == 'p75':
        m_ref = float(np.percentile(throughput_solver, 75))
    elif ref_mode == 'p90':
        m_ref = float(np.percentile(throughput_solver, 90))
    elif ref_mode == 'mean':
        m_ref = float(np.mean(throughput_solver))
    else:  # 'max' (legacy)
        m_ref = m_max
    if m_ref < 1e-30:
        m_ref = m_max   # fallback

    chi_binary_solver = (throughput_solver > threshold_frac * m_ref).astype(np.float64)

    # Transpose solver-coord chi to real-coord chi using axis_map_B perm
    perm = axis_map_B['solver_to_real_perm']
    chi_3d = np.ascontiguousarray(chi_binary_solver.transpose(perm))
    # approach-(a) reverse convention: the solver is direction-agnostic, so the
    # solver-coord χ is identical for ±stream; the real-coord χ for a reverse
    # dir must be spatially flipped along the real stream axis to track the
    # mirrored flow corridor (same flip the velocity transforms apply).
    if axis_map_B.get('is_reverse'):
        chi_3d = np.ascontiguousarray(
            np.flip(chi_3d, axis=axis_map_B['stream_real_axis']))
    if chi_3d.shape != shape:
        # Fallback: identity if shape mismatch (shouldn't happen)
        chi_3d = np.ones(shape, dtype=np.float64)

    for _ in range(int(n_dilate)):
        chi_3d = _dilate_one_step_3d(chi_3d)
    if n_smooth > 0:
        chi_3d = _box_smooth_3d(chi_3d, n_passes=int(n_smooth))
    return np.clip(chi_3d, 0.0, 1.0)


def _build_chi_B_velocity_threshold(ucB, vcB, wcB,
                                     threshold_frac=0.5,
                                     u_ref_mode='inlet',
                                     u_inlet=None,
                                     n_dilate=3, n_smooth=2):
    """Method B: per-cell χ_B from the converged SIMPLE B velocity field.

    A cell is 'participating' if |v_cell| > threshold_frac · u_ref.

    `u_ref_mode` selects the reference velocity:
        'inlet'    — u_ref = u_inlet (passed param). Stable, recommended.
        'p50'      — u_ref = median(|v|) (50th percentile). Robust.
        'p90'      — u_ref = 90th percentile. Closer to max but resistant
                     to pathological hot cells.
        'max'      — u_ref = max(|v|). Original behavior; sensitive to
                     porous-medium pressure-driven hotspots.

    Then: dilate by n_dilate cells (6-connected, Chebyshev radius 1 per step)
    to capture the diffusion-affected boundary layer beyond pure advection,
    then box-smooth n_smooth times for a tanh-like ramp at the boundary.

    Inputs are cell-center velocity components in REAL (Nx, Ny, Nz) coords —
    same arrays already produced by `_solver_velocity_to_real`.
    """
    vmag = np.sqrt(ucB ** 2 + vcB ** 2 + wcB ** 2)
    v_max = float(np.max(vmag))
    if v_max < 1e-30:
        return np.ones_like(vmag, dtype=np.float64)
    if u_ref_mode == 'inlet':
        u_ref = float(u_inlet) if (u_inlet is not None and u_inlet > 0) else v_max
    elif u_ref_mode == 'p50':
        u_ref = float(np.median(vmag))
    elif u_ref_mode == 'p90':
        u_ref = float(np.percentile(vmag, 90))
    else:  # 'max'
        u_ref = v_max
    chi_binary = (vmag > threshold_frac * u_ref).astype(np.float64)
    chi_3d = chi_binary
    for _ in range(int(n_dilate)):
        chi_3d = _dilate_one_step_3d(chi_3d)
    if n_smooth > 0:
        chi_3d = _box_smooth_3d(chi_3d, n_passes=int(n_smooth))
    return np.clip(chi_3d, 0.0, 1.0)


def _build_grid_3d(wall_refine, L, H, Lz, Nx_u, Ny_u, Nz_u):
    """Build 3D cell-spacing arrays + grid counts (extracted from _run_3d_stack,
    2026-06-09 F1). Uniform user spacing, or 6-wall boundary-layer refinement
    when ``wall_refine`` (expands user N by ~+2·n_refine per axis; first cell
    0.02 mm, growth 1.8). Returns ``(dx, dy, dz, Nx, Ny, Nz)``.

    2026-06-09 E1: the refined non-uniform spacing now reaches BOTH stages —
    the LTNE energy solve AND the SIMPLE momentum/pressure solve (the latter via
    SIMPLESolver3D's dx_arr/dy_arr/dz_arr; its kernels were already non-uniform-
    aware). Previously SIMPLE silently ran on a uniform grid under wall_refine.
    Velocity/pressure now resolve the boundary layer too (verified: Shanghai
    wall_refine converges, dP within ~0.6% of the uniform-grid value, mass
    residual ~1e-5).
    """
    if wall_refine:
        from solvers.df_projection import build_master_refined_grid_3d
        try:
            dx, dy, dz, Nx, Ny, Nz = build_master_refined_grid_3d(
                L, H, Lz, Nx_u, Ny_u, Nz_u,
                n_refine=8, first_cell=0.02e-3, growth=1.8)
            print(f"[3D grid] wall-refine: user {Nx_u}x{Ny_u}x{Nz_u} -> "
                  f"actual {Nx}x{Ny}x{Nz}")
        except ValueError as e:
            print(f"[3D grid] wall-refine skipped ({e}); using uniform")
            dx = np.full(Nx_u, L / Nx_u, dtype=np.float64)
            dy = np.full(Ny_u, H / Ny_u, dtype=np.float64)
            dz = np.full(Nz_u, Lz / Nz_u, dtype=np.float64)
            Nx, Ny, Nz = Nx_u, Ny_u, Nz_u
    else:
        dx = np.full(Nx_u, L / Nx_u, dtype=np.float64)
        dy = np.full(Ny_u, H / Ny_u, dtype=np.float64)
        dz = np.full(Nz_u, Lz / Nz_u, dtype=np.float64)
        Nx, Ny, Nz = Nx_u, Ny_u, Nz_u
    return dx, dy, dz, Nx, Ny, Nz


def _solver_spacings(dx, dy, dz, perm):
    """Map real-coords cell-spacing arrays onto a SIMPLE solver's axis order.

    The solver↔real mapping is ``real = solver.transpose(perm)`` (perm =
    solver_to_real_perm), so solver axis ``s`` spans real axis ``perm.index(s)``.
    Returns ``(sdx, sdy, sdz)`` in solver-axis order. Used to feed the refined
    non-uniform grid into SIMPLESolver3D under wall_refine (E1, 2026-06-09)."""
    real = (dx, dy, dz)
    return (real[perm.index(0)], real[perm.index(1)], real[perm.index(2)])


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

    # Fluid A properties at inlet
    rho_A = air_density(T_inA, P_inA)
    mu_A = air_viscosity(T_inA)
    cp_A = air_cp(T_inA)
    k_A = air_conductivity(T_inA)

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
        print(f"[3D zones] using {len(zone_cells)} zone cells; "
              f"K range [{K_field_3d.min():.2e}, {K_field_3d.max():.2e}]")
    else:
        K_pred, cF_pred = predict_K_cF(tpms_type, Lcell, t_wall, 0.5 * eps)
        K_A_arr = np.full((N_stream, N_cross2), K_pred)
        cF_A_arr = np.full((N_stream, N_cross2), cF_pred)

    # 2026-05-13 — apply UI roughness correction (norris_1a default) to K_A,
    # cF_A. Air side only; water skipped (Yan [6] embeds AM roughness).
    K_A_arr, cF_A_arr = _apply_roughness_KcF(
        K_A_arr, cF_A_arr, cfg.get('fluid_type_A', 'air'),
        rho_A, mu_A, u_A, D_h)

    # P_ref_abs 1D closed-form seed (uses streamwise length L_stream)
    G_A = rho_A * u_A
    # P² compressible seed: C = μG/K + cF·G² where G = ρu (mass flux, constant
    # along pipe by continuity). NOT the local dp/dx = μu/K + ρcFu².
    C_est = mu_A * G_A / max(K_pred, 1e-16) + cF_pred * G_A * G_A
    P_out_sq = P_inA ** 2 - 2.0 * R_AIR * T_inA * C_est * L_stream
    P_ref_A = float(np.sqrt(max(P_out_sq, 1.0e4)))

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
        P_ref_abs=P_ref_A, fluid_type='ideal_gas',
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

    # ── Fluid type validation ──
    fluid_type_A = cfg.get('fluid_type_A', 'air')
    if fluid_type_A == 'sco2':
        raise NotImplementedError("sCO₂ properties not yet implemented for Fluid A")
    if fluid_type_A == 'water':
        raise NotImplementedError("Water Fluid A not yet implemented (needs incompressible SIMPLE A path)")

    # ── Fluid B: cross-flow SIMPLE — BUILD ONLY (solve in parallel with A) ──
    fB = cfg.get('fluid_B_cfg')
    fluid_type_B = cfg.get('fluid_type_B', 'air')
    if fluid_type_B == 'sco2':
        raise NotImplementedError("sCO₂ properties not yet implemented for Fluid B")
    is_water_B = fluid_type_B == 'water'
    # B1 1.1: property primitives + flow model for side B via the registry
    # (frozen-B / stiffness semantics keep using is_water_B).
    _mB = fluid_props.get(fluid_type_B)
    sB = None
    sB_info = None
    if fB is not None:
        u_B = cfg.get('u_B', u_A)
        rho_B = float(_mB.rho(T_inB, P_inB))   # water rho ignores P
        mu_B = float(_mB.mu(T_inB))
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
        K_B_arr = np.full((N_stream_B, N_cross2_B), K_pred)
        cF_B_arr = np.full((N_stream_B, N_cross2_B), cF_pred)
        # 2026-05-13 — apply UI roughness correction to K_B / cF_B. Skip for
        # water (Yan [6] correlation embeds AM roughness; double-counting
        # would over-predict friction).
        K_B_arr, cF_B_arr = _apply_roughness_KcF(
            K_B_arr, cF_B_arr, fluid_type_B,
            rho_B, mu_B, u_B, D_h)
        G_B = rho_B * u_B
        C_B = mu_B * G_B / max(K_pred, 1e-16) + cF_pred * G_B * G_B
        solver_fluid_type_B = fluid_props.flow_model(fluid_type_B)
        if _mB.compressible:
            P_out_sq_B = P_inB ** 2 - 2.0 * R_AIR * T_inB * C_B * L_stream_B
            P_ref_B = float(np.sqrt(max(P_out_sq_B, 1.0e4)))
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
        _run_two_simple_parallel(sA, sB, cancel_check=cfg.get('_cancel_check'))
        # LTNE fluid B velocity: full vector remapped to real coordinates.
        ucB, vcB, wcB = _solver_velocity_to_real(
            sB, axis_map_B, (Nx, Ny, Nz))
        Tb_presc = None  # let LTNE solve Tb from convection
    else:
        # No B: run A alone (serial)
        _prof_t_a0 = _time.perf_counter() if _prof_3d_enabled() else None
        _a0_conv, _a0_it = sA.solve(max_iter=2000, tol=_simple_tol_default(),
                                    verbose=False,
                                    cancel_check=cfg.get('_cancel_check'))
        if _prof_t_a0 is not None:
            print(f"[PROF] initial SIMPLE_A (serial, no-B) "
                  f"{_time.perf_counter()-_prof_t_a0:7.2f}s  "
                  f"iters={_a0_it}  conv={_a0_conv}  (cap=2000)", flush=True)
        ucB = np.zeros((Nx, Ny, Nz))
        vcB = np.zeros((Nx, Ny, Nz))
        wcB = np.zeros((Nx, Ny, Nz))
        Tb_presc = np.full((Nx, Ny, Nz), T_inB, dtype=np.float64)

    # LTNE inputs — Fluid A always air, Fluid B via the registry (B1 1.1).
    cp_B = _mB.cp(T_inB)
    k_B = float(_mB.k(T_inB))
    rho_B_ltne = float(_mB.rho(T_inB, P_inB))   # water rho ignores P
    eps_arr = (eps_field_3d.copy() if eps_field_3d is not None
               else np.full((Nx, Ny, Nz), eps))
    # Per-cell single-channel void fraction (#2/#3). When zoned, eps varies
    # with (L, t) over space, so K_ffA/B and K_ss must track local eps too.
    eps_f_arr = eps_arr / 2.0
    K_ffA = eps_f_arr * k_A
    K_ffB = eps_f_arr * k_B
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
    # K_ss = χ_s · (1 − eps_local) · k_s, tracks zoned porosity (#3).
    from solvers.tpms_calc import CHI_S as _CHI_S
    K_ss = _CHI_S * (1.0 - eps_arr) * k_s

    # h_v from Nu correlation. Per-cell when zoned (#4): tpms_compute uses
    # local (Lcell_ij, t_wall_ij) so A_0, H_sf track the design field.
    # Uniform case reduces to the old scalar path.
    from solvers.tpms_calc import compute as tpms_compute
    from solvers.tpms_calc import nu_from_Re as _nu_from_Re
    from solvers.tpms_calc import nu_water_from_Re as _nu_water_from_Re
    from solvers.nu_correlations import NU_LAM_FLOOR as _NU_LAM_FLOOR  # Hagen-Poiseuille single-tube limit
    u_B_val = cfg.get('u_B', u_A)

    def _fluid_transport_props(fluid_type, T_side, P_side):
        m = fluid_props.get(fluid_type)
        rho = float(m.rho(T_side, P_side))   # water.rho ignores P (incompressible)
        mu = float(m.mu(T_side))
        k_f = float(m.k(T_side))
        if not m.compressible:               # water: Pr-substitution (3D: k guard)
            Pr_f = float(m.cp(T_side)) * mu / max(k_f, 1e-30)
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

    # Initial bulk h_v (used at outer=0 before SIMPLE solves; becomes local
    # after first outer iter when ucA/B are available).
    h_vA_field = _build_hv_field_3d(
        L_mm_field, t_field_3d, u_A, T_inA, P_inA, fluid_type_A)
    h_vA_field = _apply_roughness_h_v(
        h_vA_field, fluid_type_A, rho_A, mu_A, u_A, D_h)
    if sB is not None:
        h_vB_field = _build_hv_field_3d(
            L_mm_field, t_field_3d, u_B_val, T_inB, P_inB, fluid_type_B)
        h_vB_field = _apply_roughness_h_v(
            h_vB_field, fluid_type_B, rho_B, mu_B, u_B_val, D_h)
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
    Ta_prev = None
    chi_B = None         # B flow-path indicator field (χ_B), built each outer iter
    # Optional solid warm-start seed from the UI. Empty → solver default
    # (Ta=T_inA, Tb=T_inB, Ts=0.5*(T_inA+T_inB) inside solve_full_domain_3d).
    # Filled → only Ts is overridden with the user value; Ta/Tb stay at the
    # per-fluid inlet T (the 2026-04-24 FV fix in ltne_energy_3d.py:1442-44
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
    for outer in range(_max_outer):
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
        h_vA_field = _build_hv_local_3d(
            L_mm_field, t_field_3d, u_stream_A, T_inA, P_inA, fluid_type_A)
        h_vA_field = _apply_roughness_h_v(
            h_vA_field, fluid_type_A, rho_A, mu_A, u_A, D_h)
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
            h_vB_field = _build_hv_local_3d(
                L_mm_field, t_field_3d, u_stream_B, T_inB, P_inB, fluid_type_B)
            h_vB_field = _apply_roughness_h_v(
                h_vB_field, fluid_type_B, rho_B, mu_B, u_B_val, D_h)
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
                    print(f"[M4-legacy] r_in={_r_in:.4f} r_out={_r_out:.4f} "
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
                    print(f"[χ_B] closure=per_cell_chi_b method={_method} "
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
                print(f"[H2-audit] K_ffB := {_h2_floor:.0e}·K̄ at outlet "
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
                _coefA = 0.5 * eps_arr * rho_cp_fA
                _balance_stream_outflow([ufA, vfA, wfA], axis_map, _coefA, dx, dy, dz)
            if sB is not None and (
                    (not fluid_props.get(fluid_type_B).compressible) or _var_rhocp):
                _coefB = 0.5 * eps_arr * rho_cp_fB
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
        # cell injected into FVM equation RHS. Used by validation/mms_3d_*.py.
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
            Tb_prescribed=Tb_presc, max_iter=_ltne_max_iter, tol=1e-5,
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
            cancel_check=_cancel_check,
            return_info=True)
        Ta, Tb, Ts, _ltne_info_d = _ltne_result
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
            print(f"[PROF] outer {outer}: LTNE {_dt:7.2f}s  "
                  f"iters={_ltne_info_d.get('iterations',0)}  "
                  f"conv={_ltne_info_d.get('converged',False)}  "
                  f"res={_ltne_info_d.get('residual',0.0):.2e}  "
                  f"(cap={_ltne_max_iter})", flush=True)

        if Ta_prev is not None:
            dT = float(np.max(np.abs(Ta - Ta_prev)))
            if dT < _OUTER_TOL:
                break
        Ta_prev = Ta.copy()

        # Non-iso coupling: Ta real → solver coords via self-inverse perm
        Ta_sA = np.ascontiguousarray(Ta.transpose(solver_to_real_perm))
        # Critical: propagate Ta to T_field so SIMPLE inner _update_density()
        # uses local cell T, not stale T_in. (Mirror sB.update_T_field below.)
        sA.update_T_field(Ta_sA)
        P_abs = sA.P_ref_abs + sA.P
        rho_new = P_abs / (R_AIR * Ta_sA)
        if outer > 0:
            sA.rho_field = np.ascontiguousarray(
                _ALPHA_T * rho_new + (1.0 - _ALPHA_T) * sA.rho_field,
                dtype=np.float64)
            sA.mu_field = np.ascontiguousarray(
                _ALPHA_T * air_viscosity(Ta_sA)
                + (1.0 - _ALPHA_T) * sA.mu_field, dtype=np.float64)
        else:
            sA.rho_field = np.ascontiguousarray(rho_new, dtype=np.float64)
            sA.mu_field = np.ascontiguousarray(air_viscosity(Ta_sA), dtype=np.float64)
        eps_eff_A = sA.eps_field if hasattr(sA, 'eps_field') else sA.eps
        sA._mu_eff_field = np.ascontiguousarray(
            sA.mu_field / eps_eff_A, dtype=np.float64)

        T_avg = float(Ta_sA.mean())
        mu_avg = float(air_viscosity(T_avg))
        C_avg = mu_avg * G_A / max(K_pred, 1e-16) + cF_pred * G_A * G_A
        P_out_sq_new = P_inA ** 2 - 2.0 * R_AIR * T_avg * C_avg * L_stream
        sA.P_ref_abs = float(np.sqrt(max(P_out_sq_new, 1.0e4)))

        # Warm restart: SIMPLE fields nearly converged after outer 0.
        # ρ/μ change is small (α_T=0.6 under-relaxation), so 150 iter is plenty
        # for the residual to re-sink to 1e-3. Saves ~50% of SIMPLE work in
        # outer iters 1-2.
        _prof_t_sa = _time.perf_counter() if _prof_3d_enabled() else None
        _sa_conv, _sa_it = sA.solve(max_iter=600, tol=_simple_tol_default(),
                                    verbose=False, cancel_check=_cancel_check)
        if _prof_t_sa is not None:
            print(f"[PROF] outer {outer}: SIMPLE_A {_time.perf_counter()-_prof_t_sa:7.2f}s  "
                  f"iters={_sa_it}  conv={_sa_conv}  (cap=600)", flush=True)

        # Refresh fluid-property fields using the *local* T field, keeping
        # the spatial structure built by the zoned-geometry pass up-front
        # (#1). The previous implementation used `eps_f` (undefined in
        # this scope) and a scalar mean T, which both crashed for zoned
        # runs and flattened any non-uniform K_ff / h_v / rho_cp back to
        # a uniform field.
        T_avgA = float(Ta.mean())
        K_ffA[:] = eps_f_arr * air_conductivity(Ta)
        if _var_rhocp and sA is not None:
            # SIMPLE's local ρ(P_local,T) → real coords (transpose + reverse flip)
            _rhoA_real = sA.rho_field.transpose(axis_map['solver_to_real_perm'])
            if axis_map['is_reverse']:
                _rhoA_real = np.flip(_rhoA_real, axis=axis_map['stream_real_axis'])
            rho_cp_fA[:] = np.ascontiguousarray(_rhoA_real) * air_cp(Ta)
        else:
            rho_cp_fA[:] = air_density(Ta, P_inA) * air_cp(Ta)
        # h_v rebuilt at top of next outer iter using LOCAL Re (#B fix).

        if Tb is not None:
            T_avgB = float(Tb.mean())
            # B1 1.1: per-fluid primitives via registry; the local-P
            # rho·cp path is compressible-only physics (water keeps ρ(T)).
            K_ffB[:] = eps_f_arr * _mB.k(Tb)
            if _mB.compressible and _var_rhocp and sB is not None:
                _rhoB_real = sB.rho_field.transpose(perm_B)
                if axis_map_B['is_reverse']:
                    _rhoB_real = np.flip(
                        _rhoB_real, axis=axis_map_B['stream_real_axis'])
                rho_cp_fB[:] = np.ascontiguousarray(_rhoB_real) * _mB.cp(Tb)
            else:
                rho_cp_fB[:] = _mB.rho(Tb, P_inB) * _mB.cp(Tb)
            # h_vB rebuilt at top of next outer iter using LOCAL Re (#B fix).

        # Non-iso coupling for fluid B. Water: ρ(T) only, no ideal gas.
        # Air: ρ(P,T) via ideal gas law (mirror of A).
        if sB is not None and Tb is not None:
            Tb_sB = np.ascontiguousarray(Tb.transpose(perm_B))
            if _mB.compressible:
                P_abs_B = sB.P_ref_abs + sB.P
                rho_new_B = P_abs_B / (R_AIR * Tb_sB)
            else:
                rho_new_B = _mB.rho(Tb_sB)
            mu_new_B = _mB.mu(Tb_sB)
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
                C_avg_B = (mu_avg_B * G_B / max(K_pred, 1e-16)
                           + cF_pred * G_B * G_B)
                P_out_sq_B_new = (P_inB ** 2
                                  - 2.0 * R_AIR * Tb_avg * C_avg_B * L_stream_B)
                sB.P_ref_abs = float(np.sqrt(max(P_out_sq_B_new, 1.0e4)))

            sB.update_T_field(Tb_sB)
            _prof_t_sb = _time.perf_counter() if _prof_3d_enabled() else None
            _sb_conv, _sb_it = sB.solve(max_iter=600, tol=_simple_tol_default(),
                                        verbose=False, cancel_check=_cancel_check)
            if _prof_t_sb is not None:
                print(f"[PROF] outer {outer}: SIMPLE_B {_time.perf_counter()-_prof_t_sb:7.2f}s  "
                      f"iters={_sb_it}  conv={_sb_conv}  (cap=600)", flush=True)
                _prof_res_trace(f"outer {outer} SIMPLE_B", sB)

            # rho_cp_fB already refreshed above (P0/P1/P2 block)

            # Re-extract the full B vector for the next LTNE pass.
            ucB2, vcB2, wcB2 = _solver_velocity_to_real(
                sB, axis_map_B, (Nx, Ny, Nz))
            ucB[:] = ucB2
            vcB[:] = vcB2
            wcB[:] = wcB2

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
    eps_f_per_side = 0.5 * float(eps)   # ε_A

    # Fluid A — unified face-flux weights for T_out and m_dot consistency
    m_dot_A_simple = _simple_mass_flow(sA, fA['dir'], eps_f_per_side=eps_f_per_side)
    T_A_out_face = _real_outlet_slice(Ta, fA['dir'])
    T_A_out = _mass_weighted_T_out(T_A_out_face, sA, fA['dir'], eps_f_per_side)
    # (A side has no χ_B weighting, so there is no chi/no-chi distinction here —
    #  the former duplicate `T_A_out_no_chi` local was dead and was removed.)
    Q_enthalpy_A = abs(m_dot_A_simple * cp_A * (T_inA - T_A_out))

    # Fluid B
    Q_enthalpy_B = 0.0
    chi_B_out_face = None
    if sB is not None:
        m_dot_B_simple = _simple_mass_flow(sB, fB['dir'], eps_f_per_side=eps_f_per_side)
        T_B_out_face = _real_outlet_slice(Tb, fB['dir'])
        # χ_B at outlet face for ghost-B suppression
        if chi_B is not None:
            chi_B_out_face = _real_outlet_slice(chi_B, fB['dir'])
        # T_out with and without χ_B for diagnostic comparison
        T_B_out_no_chi = _mass_weighted_T_out(T_B_out_face, sB, fB['dir'],
                                               eps_f_per_side)
        T_B_out = _mass_weighted_T_out(T_B_out_face, sB, fB['dir'], eps_f_per_side,
                                        chi_face=chi_B_out_face)
        # m_dot variants for diagnostic
        m_dot_B_phys_in = float(np.sum(_face_flux_weights(
            sB, fB['dir'], face='real_inlet', eps_mode='physical')))
        m_dot_B_phys_out = float(np.sum(_face_flux_weights(
            sB, fB['dir'], face='real_outlet', eps_mode='physical',
            chi_face=chi_B_out_face)))
        Q_enthalpy_B = abs(m_dot_B_simple * cp_B * (T_inB - T_B_out))

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

    dP = float(SIMPLESolver3D.extract_dP_weighted(sA))

    uc_real, vc_real, wc_real = _assemble_real_velocity()
    vmag = np.sqrt(uc_real ** 2 + vc_real ** 2 + wc_real ** 2)

    # P field → real coords via solver perm. DISPLAY ABSOLUTE pressure anchored
    # so the INLET reads exactly the user-input P_in — identical convention to
    # the 2D-native path (run_calculation.py:821, P_fA = P_inA + (P_g - P_ref
    # _inlet)). SIMPLE's self.P is the gauge field (outlet pinned ~0, inlet ≈
    # dP); abs = (P_in - dP) + gauge ⇒ inlet=P_in, outlet=P_in-dP. Pure baseline
    # shift, physics-free — dP itself is reported via extract_dP_weighted, and
    # this anchor does NOT depend on the P_ref_abs reconstruction (which for
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
        dP_B = float(SIMPLESolver3D.extract_dP_weighted(sB))
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
        print(f"[SWEEP-CSV] {cfg.get('_case_label','?')},"
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

        print(f"[Q-DIAG] === LTNE-effective group ===")
        print(f"[Q-DIAG] m_dot_A_ltne={m_dot_A_simple:.5f} kg/s  "
              f"T_A_out={T_A_out:.1f} K  Q_enth_A_ltne={Q_enth_A_ltne:.1f} W")
        if sB is not None:
            print(f"[Q-DIAG] m_dot_B_ltne={m_dot_B_simple:.5f} kg/s  "
                  f"T_B_out={T_B_out:.1f} K (chi)  "
                  f"T_B_out_no_chi={T_B_out_no_chi:.1f} K  "
                  f"Q_enth_B_ltne={Q_enth_B_ltne:.1f} W")
        print(f"[Q-DIAG] Q_solid_A={Q_solid_A_val:.1f}  Q_solid_B={Q_solid_B_val:.1f}  "
              f"balance={Q_solid_A_val+Q_solid_B_val:.1f} W")
        print(f"[Q-DIAG] Q_ltne_consistency: |Q_sA|-Q_enth_A_ltne="
              f"{abs(Q_solid_A_val)-Q_enth_A_ltne:.1f}  "
              f"|Q_sB|-Q_enth_B_ltne={abs(Q_solid_B_val)-Q_enth_B_ltne:.1f}")

        print(f"[Q-DIAG] === Physical-boundary group ===")
        print(f"[Q-DIAG] m_A_phys_in={m_A_phys_in:.5f} kg/s  "
              f"Q_enth_A_phys={Q_enth_A_phys:.1f} W")
        if sB is not None:
            print(f"[Q-DIAG] m_B_phys_in={m_dot_B_phys_in:.5f}  "
                  f"m_B_phys_out_chi={m_dot_B_phys_out:.5f} kg/s  "
                  f"T_B_out={T_B_out:.1f} K")
            print(f"[Q-DIAG] Q_enth_B_phys={Q_enth_B_phys:.1f} W")

        # ── REQ_2: χ_B distribution histogram ──
        if chi_B is not None:
            chi_flat = chi_B.ravel()
            print(f"[CHI] min={chi_flat.min():.3f} max={chi_flat.max():.3f} "
                  f"mean={chi_flat.mean():.3f}")
            print(f"[CHI] p10={_dbg.percentile(chi_flat,10):.3f} "
                  f"p25={_dbg.percentile(chi_flat,25):.3f} "
                  f"p50={_dbg.percentile(chi_flat,50):.3f} "
                  f"p75={_dbg.percentile(chi_flat,75):.3f} "
                  f"p90={_dbg.percentile(chi_flat,90):.3f}")
            hist, bin_edges = _dbg.histogram(chi_flat, bins=10, range=(0, 1))
            print("[CHI] histogram bins:")
            for i, c in enumerate(hist):
                print(f"  [{bin_edges[i]:.1f}, {bin_edges[i+1]:.1f}): "
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
                    print(f"[CHI-BC] χ_B on inlet PATCH (n={len(chi_in_patch)}): "
                          f"p10={_dbg.percentile(chi_in_patch,10):.3f} "
                          f"p50={_dbg.percentile(chi_in_patch,50):.3f} "
                          f"p90={_dbg.percentile(chi_in_patch,90):.3f}")
            # Outlet patch
            if chi_B_out_face is not None:
                chi_out_patch = chi_B_out_face[_ltne_mask_B_val > 0.5] if _ltne_mask_B_val is not None else chi_B_out_face.ravel()
                if len(chi_out_patch) > 0:
                    print(f"[CHI-BC] χ_B on outlet PATCH (n={len(chi_out_patch)}): "
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
    # ── Audit-only additive exports (read-only, deep-copied) ── OPT-IN.
    # Passthrough of SIMPLE face arrays + masks for the standalone partial-B
    # LTNE conservation audit (validation/audit_partial_b_ltne.py).
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
