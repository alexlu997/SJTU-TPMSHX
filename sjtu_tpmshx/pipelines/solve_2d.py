"""2D solver engine loop + Q/pressure postprocessing, moved verbatim from
stages_2d.py (openspec split-pipelines, 2026-07-03); behavior bit-identical.
"""
import numpy as np
from sjtu_tpmshx.solvers.coupling_skeleton import OuterConvergence, run_outer_coupling
from sjtu_tpmshx.solvers.ltne_energy import solve_full_domain
from sjtu_tpmshx.solvers.tpms_calc import geometry as tpms_geometry
from sjtu_tpmshx.solvers.envelope import gate_solution, mach_field_max
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)


def _enthalpy_balance_2d(T_field, uc, vc, rho_cp_field, dir_code,
                          dx_arr, dy_arr, inlet_mask=None, outlet_mask=None,
                          enthalpy_fn=None, rho_fn=None, P_ref=None,
                          eps_side=None):
    """Mass-conserving enthalpy balance Q = ṁ_in · (T_in_avg − T_out_avg).

    Uses the inlet plane ρ·|u|·A·mask as ṁ·cp reference so the returned Q
    is robust to partial SIMPLE mass-conservation convergence (B-1 refactor
    2026-04-24). The earlier H_in − H_out form gave spurious non-zero Q
    when ṁ_inlet ≠ ṁ_outlet, which in fast-mode NSGA-II inflated Q by 3×.

    Positive = fluid gives up heat (T_in > T_out).
    Optional 1D masks (length = cross-axis) gate the integral to partial
    inlet / outlet pipes; missing masks default to full face.

    ``eps_side`` (N1 fix, 2026-07-07): the PER-SIDE void fraction (scalar or
    2D field). Velocities are interstitial, so the physical face mass flux is
    ε_side·ρ·|u|·A — without it the duty over-reads by 1/ε_side (verified
    2.7086 vs 1/ε_A = 2.7147 against the independent Σh_vB·(Ts−Tb)·dA
    integral on the golden air-air case). None keeps the legacy ε-less
    arithmetic for callers that pre-scale externally.

    True-enthalpy mode (sCO2, audit 2026-06-28 D1): when ``enthalpy_fn`` /
    ``rho_fn`` / ``P_ref`` are supplied the duty is the physically correct
    Q = ṁ·(⟨h_in⟩ − ⟨h_out⟩) with mass-flux-weighted mean enthalpy ⟨h(T)⟩ on
    each face (not ρcp(T_in)·ΔT, and not h(⟨T⟩) — both bias Q by tens-to-
    hundreds of percent for sCO2 across the pseudocritical cp spike). The mass
    flux weight is ρ·|u|·A (true mass flow), NOT ρcp. Air/water pass these as
    None and keep the legacy ρcp·ΔT arithmetic exactly (constant cp ⇒ value-
    identical, golden-safe).
    """
    if dir_code in (0, 1):
        i_in, i_out = (0, -1) if dir_code == 0 else (-1, 0)
        A_cell = dy_arr
        n_cross = T_field.shape[1]
        m_in_arr  = (np.asarray(inlet_mask,  dtype=np.float64)
                     if inlet_mask  is not None else np.ones(n_cross))
        m_out_arr = (np.asarray(outlet_mask, dtype=np.float64)
                     if outlet_mask is not None else np.ones(n_cross))
        u_in_face, u_out_face = np.abs(uc[i_in, :]), np.abs(uc[i_out, :])
        rho_cp_in, rho_cp_out = rho_cp_field[i_in, :], rho_cp_field[i_out, :]
        T_in_face, T_out_face = T_field[i_in, :], T_field[i_out, :]
        if eps_side is None:
            eps_in = eps_out = 1.0
        elif np.ndim(eps_side) == 0:
            eps_in = eps_out = float(eps_side)
        else:
            eps_in, eps_out = eps_side[i_in, :], eps_side[i_out, :]
    else:
        j_in, j_out = (0, -1) if dir_code == 2 else (-1, 0)
        A_cell = dx_arr
        n_cross = T_field.shape[0]
        m_in_arr  = (np.asarray(inlet_mask,  dtype=np.float64)
                     if inlet_mask  is not None else np.ones(n_cross))
        m_out_arr = (np.asarray(outlet_mask, dtype=np.float64)
                     if outlet_mask is not None else np.ones(n_cross))
        u_in_face, u_out_face = np.abs(vc[:, j_in]), np.abs(vc[:, j_out])
        rho_cp_in, rho_cp_out = rho_cp_field[:, j_in], rho_cp_field[:, j_out]
        T_in_face, T_out_face = T_field[:, j_in], T_field[:, j_out]
        if eps_side is None:
            eps_in = eps_out = 1.0
        elif np.ndim(eps_side) == 0:
            eps_in = eps_out = float(eps_side)
        else:
            eps_in, eps_out = eps_side[:, j_in], eps_side[:, j_out]

    if enthalpy_fn is not None and rho_fn is not None and P_ref is not None:
        # True-enthalpy duty for strongly variable-cp fluids (sCO2).
        rho_in  = np.asarray(rho_fn(T_in_face,  P_ref), dtype=np.float64)
        rho_out = np.asarray(rho_fn(T_out_face, P_ref), dtype=np.float64)
        w_in  = eps_in  * rho_in  * u_in_face  * A_cell * m_in_arr
        w_out = eps_out * rho_out * u_out_face * A_cell * m_out_arr
        m_dot = float(np.sum(w_in))
        if m_dot < 1e-30:
            return 0.0
        h_in  = np.asarray(enthalpy_fn(T_in_face,  P_ref), dtype=np.float64)
        h_out = np.asarray(enthalpy_fn(T_out_face, P_ref), dtype=np.float64)
        h_in_avg = float(np.sum(w_in * h_in)) / m_dot
        m_out_tot = float(np.sum(w_out))
        h_out_avg = (float(np.sum(w_out * h_out)) / m_out_tot
                     if m_out_tot > 1e-30 else float(np.mean(h_out)))
        return m_dot * (h_in_avg - h_out_avg)

    m_in_w  = eps_in  * rho_cp_in  * u_in_face  * A_cell * m_in_arr
    m_out_w = eps_out * rho_cp_out * u_out_face * A_cell * m_out_arr
    m_dot_cp = float(np.sum(m_in_w))
    if m_dot_cp < 1e-30:
        return 0.0
    T_in_avg = float(np.sum(m_in_w * T_in_face)) / m_dot_cp
    m_out_total = float(np.sum(m_out_w))
    T_out_avg = (float(np.sum(m_out_w * T_out_face)) / m_out_total
                 if m_out_total > 1e-30 else float(np.mean(T_out_face)))
    return m_dot_cp * (T_in_avg - T_out_avg)


class _PipelineWindowShim:
    """Minimal window-like adapter feeding cfg-derived state into
    ``_run_solvers`` and capturing back-mutations for the Pipeline.

    Audit C4 (L-a-2). Pre-populates the read-only window attributes
    (``_rho_A``, ``_rho_B``, ``_mu_A``, ``_mu_B``, ``_K_ffA``,
    ``_K_ffB``, ``_K_ss``) by re-running ``tpms_calc.compute`` per
    side; the legacy UI flow stashed these after the user clicked
    Auto-Fill, but Pipeline2D drives a cfg-only entrypoint without
    that hand-off.  Mutation writes (``_compute_progress``,
    ``_iter_label_now``, ``_zone_*``) are captured for the Pipeline's
    ``ComputeResult.diagnostics`` and ``ComputeResult.zones`` slots.

    Bridging via this shim avoids a 770-line rewrite of the
    ``_run_solvers`` body in this PR; C5 / future phases can hoist
    the loop into a window-free function.
    """

    # Prevent the __setattr__ progress hook from firing during the
    # constructor's many attribute assignments.
    _init_done = False

    def __init__(self, compute_cfg, progress_cb=None, iter_label_cb=None):
        from sjtu_tpmshx.solvers import tpms_calc as _tc
        from sjtu_tpmshx.solvers.tpms_calc import geometry as _tpms_geom
        from sjtu_tpmshx.domain.validator import compute_volumetric_htc

        # Bypass our own __setattr__ during init so the progress
        # callback only fires on the real loop updates below.
        object.__setattr__(self, '_progress_cb',
                           progress_cb or (lambda _pct: None))
        # B2 2.1a: forward `_iter_label_now` writes ("iter k/N") to the UI
        # ticker — the legacy window path read this attribute directly.
        object.__setattr__(self, '_iter_label_cb',
                           iter_label_cb or (lambda _s: None))

        # Re-run tpms_calc.compute per side — the same call
        # ``Main_Menu._auto_fill_fluid`` would have made in the UI
        # path before _run_solvers, but driven purely by cfg here.
        rA = _tc.compute(compute_cfg.geometry.tpms,
                         compute_cfg.geometry.L_cell_mm,
                         compute_cfg.geometry.t_wall_mm,
                         compute_cfg.fluid_A.u_mps,
                         compute_cfg.fluid_A.T_in_K,
                         compute_cfg.fluid_A.P_in_Pa,
                         compute_cfg.geometry.k_s_W_mK,
                         compute_cfg.fluid_A.type)
        rB = _tc.compute(compute_cfg.geometry.tpms,
                         compute_cfg.geometry.L_cell_mm,
                         compute_cfg.geometry.t_wall_mm,
                         compute_cfg.fluid_B.u_mps,
                         compute_cfg.fluid_B.T_in_K,
                         compute_cfg.fluid_B.P_in_Pa,
                         compute_cfg.geometry.k_s_W_mK,
                         compute_cfg.fluid_B.type)

        self._rho_A = rA['rho']
        self._rho_B = rB['rho']
        self._mu_A = rA['mu']
        self._mu_B = rB['mu']
        self._K_ffA = rA['K_ff']
        self._K_ffB = rB['K_ff']
        g = _tpms_geom(compute_cfg.geometry.tpms,
                       compute_cfg.geometry.L_cell_mm,
                       compute_cfg.geometry.t_wall_mm,
                       compute_cfg.geometry.k_s_W_mK)
        self._K_ss = g['K_ss']
        # h_v stashed for completeness — _run_solvers builds local
        # h_v fields per cell, but downstream UI panels read these.
        self._h_vA = compute_volumetric_htc(rA['A_0'], rA['H_sf'])
        self._h_vB = compute_volumetric_htc(rB['A_0'], rB['H_sf'])

        # Mutation collectors — _run_solvers writes these directly.
        self._compute_progress = 0
        self._iter_label_now = ''
        self._zone_axis_dir = None
        self._zone_stats = None
        self._zone_boundaries = None
        self._zone_boundaries_x = None
        self._zone_boundaries_y = None
        self._extrap_reasons = []

        # Now enable the progress forwarding hook.
        object.__setattr__(self, '_init_done', True)

    # Direction encoding shared with ``Main_Menu._DIR_MAP``.
    _DIR_MAP = {0: '+x', 1: '-x', 2: '+y', 3: '-y', 4: '+z', 5: '-z'}

    # _run_solvers calls ``window._is_x_dir(d)`` in three places.
    @staticmethod
    def _is_x_dir(d):
        return d in (0, 1)

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if not getattr(self, '_init_done', False):
            return
        if name == '_compute_progress':
            try:
                self._progress_cb(int(value))
            except Exception:
                pass
        elif name == '_iter_label_now':
            try:
                self._iter_label_cb(str(value))
            except Exception:
                pass


def _pipe_weighted(P_row, w):
    """Open-fraction-weighted boundary-row mean (module-level so the C8
    shooting reseed can measure dP with EXACTLY the reporting convention —
    see `_pipe_dp_2d`). Was nested in `_compute_pressure_2d`; moved verbatim."""
    s = float(w.sum())
    return float((P_row * w).sum() / s) if s > 1e-12 else float(P_row.mean())


def _pipe_dp_2d(simp):
    """Solved dP of one SIMPLE instance, in the 2D REPORTING convention:
    pipe-weighted inlet-row gauge minus pipe-weighted outlet-row gauge
    (identical arithmetic to `_compute_pressure_2d`'s dP_A/dP_B). Used by
    the C8 shooting reseed so 'realized inlet = P_ref_abs + dP' is self-
    consistent with the dP the pipeline reports."""
    return (_pipe_weighted(simp.P[:, 0],
                           simp.inlet_frac.astype(np.float64))
            - _pipe_weighted(simp.P[:, -1],
                             simp.outlet_frac.astype(np.float64)))


def _compute_pressure_2d(simpA, simpB, dir_A, dir_B, P_inA, P_inB, window):
    """Real-coordinate pressure fields + pipe-weighted dP from converged SIMPLE.

    Extracted verbatim from ``_run_solvers`` (#9-2D god-function split).
    Returns ``(P_fA, P_fB, dP_A, dP_B)``.
    """
    # Pipe-weighted pressure references (exclude wall cells under partial BC).
    # SIMPLE convention: inlet row = P[:, 0], outlet row = P[:, -1]; inlet_frac
    # / outlet_frac are 1-D (length = SIMPLE's perpendicular dim) indicating the
    # open fraction of each cell at the boundary. A plain row mean mixes wall
    # and pipe cells, severely diluting dP for partial-BC flows (validation
    # showed B's dP under-estimated by >10x in default cross-flow cases).
    _wA_in  = simpA.inlet_frac.astype(np.float64)
    _wA_out = simpA.outlet_frac.astype(np.float64)
    _wB_in  = simpB.inlet_frac.astype(np.float64)
    _wB_out = simpB.outlet_frac.astype(np.float64)

    P_ref_A       = _pipe_weighted(simpA.P[:,  0], _wA_in)   # pipe-inlet gauge
    P_ref_B       = _pipe_weighted(simpB.P[:,  0], _wB_in)
    P_out_gauge_A = _pipe_weighted(simpA.P[:, -1], _wA_out)  # pipe-outlet gauge
    P_out_gauge_B = _pipe_weighted(simpB.P[:, -1], _wB_out)

    is_xA = window._is_x_dir(dir_A)
    if is_xA:
        P_gA = simpA.P.T.copy()          # transpose to real coords
        if dir_A == 1:                     # -x: inlet at right
            P_gA = P_gA[::-1, :]
    else:
        P_gA = simpA.P.copy()
        if dir_A == 3:                     # -y: inlet at top
            P_gA = P_gA[:, ::-1]
    P_fA = P_inA + (P_gA - P_ref_A)

    is_xB = window._is_x_dir(dir_B)
    if is_xB:
        P_gB = simpB.P.T.copy()
        if dir_B == 1:
            P_gB = P_gB[::-1, :]
    else:
        P_gB = simpB.P.copy()
        if dir_B == 3:
            P_gB = P_gB[:, ::-1]
    P_fB = P_inB + (P_gB - P_ref_B)

    # Pressure drop = pipe-inlet minus pipe-outlet gauge pressure. The
    # P_inA/P_inB shift cancels in this difference, so using gauge directly
    # is equivalent and avoids double-counting the reference.
    dP_A = P_ref_A - P_out_gauge_A
    dP_B = P_ref_B - P_out_gauge_B
    return P_fA, P_fB, dP_A, dP_B


def _apply_zone_stats_2d(window, z_axis, zone_config, za, L, H,
                         energy_dx, energy_dy, Ta, Tb, Ts):
    """Compute per-zone statistics + boundary lines and stash them on
    ``window`` (read back by the Pipeline shim after ``_run_solvers``).

    Extracted verbatim from ``_run_solvers`` (#9-2D god-function split).
    Writes ``window._zone_{axis_dir,stats,boundaries,boundaries_x,
    boundaries_y}``; returns nothing.
    """
    if zone_config is not None and za is not None:
        window._zone_axis_dir = z_axis
        if z_axis == 'grid':
            # Grid mode: boundaries from zone_config
            window._zone_boundaries = []
            window._zone_boundaries_x = [b * L for b in za.get('x_bounds', [])]
            window._zone_boundaries_y = [b * H for b in za.get('y_bounds', [])]
            # Build dummy Zone objects for statistics
            from sjtu_tpmshx.solvers.zone_config import Zone
            dummy_zones = [Zone(f'g{r}', gc['y0'], gc['y1'], gc['L'], gc['t'])
                           for r, gc in enumerate(za.get('grid_cells', []))]
            from sjtu_tpmshx.solvers.zone_config import compute_zone_statistics, format_zone_report
            _ca = energy_dx[:, None] * energy_dy[None, :]
            stats = compute_zone_statistics(Ta, Tb, Ts, za['zone_id'], dummy_zones,
                                            cell_area=_ca)
            _log.info("\n[ZONE STATISTICS]")
            _log.info(format_zone_report(stats))
            window._zone_stats = stats
        else:
            # 1D mode
            from sjtu_tpmshx.solvers.zone_config import compute_zone_statistics, format_zone_report
            _ca = energy_dx[:, None] * energy_dy[None, :]
            stats = compute_zone_statistics(Ta, Tb, Ts, za['zone_id'],
                                            zone_config.zones, cell_area=_ca)
            _log.info("\n[ZONE STATISTICS]")
            _log.info(format_zone_report(stats))
            window._zone_stats = stats
            window._zone_boundaries_x = None
            window._zone_boundaries_y = None
            if z_axis == 'y':
                window._zone_boundaries = [z.y_frac_end * H for z in zone_config.zones[:-1]]
            else:
                window._zone_boundaries = [z.y_frac_end * L for z in zone_config.zones[:-1]]
    else:
        window._zone_stats = None
        window._zone_axis_dir = None
        window._zone_boundaries = None
        window._zone_boundaries_x = None
        window._zone_boundaries_y = None


def _compute_Q_richardson(
        Ta, Tb, Ts, ucA, vcA, ucB, vcB, rho_cp_A, rho_cp_B,
        simpA, simpB, N_x, N_y, L, H, dir_A, dir_B,
        energy_dx, energy_dy, _x_breaks, _y_breaks,
        T_inA, T_inB, P_inA_val, P_inB_val, eps, za, window,
        _pA, _pB, cfgA, cfgB, u_A, u_B, warnings_list, split_A=0.5,
        hv_ratio_A=1.0, hv_ratio_B=1.0):
    """Heat duty Q via Richardson extrapolation on the enthalpy balance.

    Re-solves the coupled energy field on a 2x-refined grid, applies
    per-side Richardson extrapolation to |Q_A|/|Q_B|, and falls back to
    a 1D plate-average when the refined solve is unavailable. Extracted
    verbatim from ``_run_solvers`` (#9-2D god-function split);
    ``warnings_list`` is appended in place on fallback paths.

    ``split_A`` (offset-isosurface δ): fraction of total ε on side A. 0.5 →
    symmetric (bit-identical). δ≠0 → the refined solve uses the per-side
    porosity (eps_A/eps_B + K_ff scaled by 2s / 2(1−s), mirroring the main
    solve) and each side's duty mass flux is weighted by the same per-side
    factor so ṁ_A / ṁ_B reflect ε_A / ε_B (not a shared ε/2).

    Returns ``(Q_total, Q_A_fine, Q_B_fine, Q_solid_richardson,
    richardson_warn)``.
    """
    # Per-side duty weighting relative to the symmetric ε/2 baseline (= 1.0 at
    # δ=0 ⇒ bit-identical). Matches the K_ff / convective scaling in the main
    # solve so the extracted A / B duties stay balanced on the split geometry.
    _asymQ = (float(split_A) != 0.5)
    _fAQ = 2.0 * float(split_A)
    _fBQ = 2.0 * (1.0 - float(split_A))
    from sjtu_tpmshx.solvers.simple_solver import _aligned_grid
    # Compute Q with Richardson extrapolation (N_x×N_y + 2N_x×2N_y)
    _cell_area = energy_dx[:, None] * energy_dy[None, :]  # (Nx, Ny)
    if za is not None and 'h_vB_arr' in za:
        Q_solid_100 = float(np.sum(za['h_vB_arr'] * (Ts - Tb) * _cell_area))
    else:
        h_vB = window._h_vB
        Q_solid_100 = float(np.sum(h_vB * (Ts - Tb) * _cell_area))

    # Richardson: run energy at 200×100 for Q extrapolation
    Nx2, Ny2 = N_x * 2, N_y * 2
    energy_dx2 = _aligned_grid(Nx2, L, list(_x_breaks))
    energy_dy2 = _aligned_grid(Ny2, H, list(_y_breaks))
    # 2026-05-07: `_aligned_grid` silently expands the cell count when
    # `min(2, ...)` per segment forces total > N (case: B partial pipe
    # with 4 break points on x). Read back the actual length so Nx2/Ny2
    # match the returned dx/dy arrays — otherwise solve_full_domain
    # receives mismatched (Nx2, Ny2) vs dx_arr/dy_arr shapes and
    # `h_vB_arr * (Ts - Tb)` broadcasts the wrong way.
    Nx2 = int(len(energy_dx2))
    Ny2 = int(len(energy_dy2))

    # Interpolate fields from coarse to fine grid using actual coordinates
    from scipy.interpolate import RegularGridInterpolator
    x_c1 = np.cumsum(energy_dx) - energy_dx / 2   # coarse centres
    y_c1 = np.cumsum(energy_dy) - energy_dy / 2
    x_c2 = np.cumsum(energy_dx2) - energy_dx2 / 2  # fine centres
    y_c2 = np.cumsum(energy_dy2) - energy_dy2 / 2
    def _interp2(arr):
        if np.ndim(arr) < 2:
            return arr
        f = RegularGridInterpolator((x_c1, y_c1), arr, method='linear',
                                    bounds_error=False, fill_value=None)
        pts = np.stack(np.meshgrid(x_c2, y_c2, indexing='ij'), axis=-1)
        return f(pts)

    ucA2 = _interp2(ucA); vcA2 = _interp2(vcA)
    ucB2 = _interp2(ucB); vcB2 = _interp2(vcB)
    rcp_A2 = _interp2(rho_cp_A if np.ndim(rho_cp_A) > 0 else
                       np.full((N_x, N_y),
                               _pA['rho'](T_inA, P_inA_val) * _pA['cp'](T_inA, P_inA_val)))
    rcp_B2 = _interp2(rho_cp_B if np.ndim(rho_cp_B) > 0 else
                       np.full((N_x, N_y),
                               _pB['rho'](T_inB, P_inB_val) * _pB['cp'](T_inB, P_inB_val)))
    if za is not None and 'h_vB_arr' in za:
        h_vA2 = _interp2(za['h_vA_arr'])
        h_vB2 = _interp2(za['h_vB_arr'])
        K_ffA2 = _interp2(za['K_ffA_arr'])
        K_ffB2 = _interp2(za['K_ffB_arr'])
        K_ss2 = _interp2(za['K_ss_arr'])
        eps2 = _interp2(za['eps_arr'])
    else:
        h_vA2 = window._h_vA; h_vB2 = window._h_vB
        K_ffA2 = window._K_ffA; K_ffB2 = window._K_ffB
        K_ss2 = window._K_ss; eps2 = eps
    # Per-side porosity on the refined grid (mirror the main solve) so the
    # Richardson pair is solved with the SAME physics. δ=0 → unchanged.
    if _asymQ:
        K_ffA2_use = K_ffA2 * _fAQ
        K_ffB2_use = K_ffB2 * _fBQ
        h_vA2 = h_vA2 * hv_ratio_A
        h_vB2 = h_vB2 * hv_ratio_B
        epsA2_use = (eps2 * float(split_A) if np.ndim(eps2) > 0
                     else float(eps2) * float(split_A))
        epsB2_use = (eps2 * (1.0 - float(split_A)) if np.ndim(eps2) > 0
                     else float(eps2) * (1.0 - float(split_A)))
    else:
        K_ffA2_use = K_ffA2; K_ffB2_use = K_ffB2
        epsA2_use = None; epsB2_use = None
    Ta2, Tb2, Ts2 = solve_full_domain(
        L, H, Nx2, Ny2, T_inA, T_inB,
        K_ffA2_use, K_ffB2_use, K_ss2, h_vA2, h_vB2,
        rcp_A2, rcp_B2, eps2,
        ucA2, vcA2, ucB2, vcB2,
        dir_A, dir_B, tol=0.5, max_iter=5000,
        dx_arr=energy_dx2, dy_arr=energy_dy2,
        eps_A=epsA2_use, eps_B=epsB2_use)
    _area2 = energy_dx2[:, None] * energy_dy2[None, :]
    if za is not None and 'h_vB_arr' in za:
        Q_solid_200 = float(np.sum(h_vB2 * (Ts2 - Tb2) * _area2))
    else:
        Q_solid_200 = float(np.sum(h_vB2 * (Ts2 - Tb2) * _area2))
    # Diagnostic only — solid-side Richardson retains the old signed
    # convention and lets us track grid convergence on ∑h_vB·(Ts−Tb).
    Q_solid_richardson = (4.0 * Q_solid_200 - Q_solid_100) / 3.0

    # Primary Q_total via Richardson on enthalpy max(|Q_A|,|Q_B|) — signed-to-
    # unsigned fix (Option C, 2026-04-24). Coarse grid has no SIMPLE, so mask
    # is upsampled from the fine-grid inlet_frac (nearest-neighbor 2× repeat;
    # exact since Nx2 = 2·N_x, Ny2 = 2·N_y).
    mA_in  = simpA.inlet_frac.astype(np.float64)  if simpA is not None else None
    mA_out = simpA.outlet_frac.astype(np.float64) if simpA is not None else None
    mB_in  = simpB.inlet_frac.astype(np.float64)  if simpB is not None else None
    mB_out = simpB.outlet_frac.astype(np.float64) if simpB is not None else None
    # 2026-05-09 — np.repeat(m, 2) breaks when Nx2 != 2*N_x (which happens
    # whenever the master refined grid uses wall-refinement: e.g.
    # 20 + 2 * n_refine = 40 + 14 = 54 cells, not 40). Resample masks via
    # linear interpolation onto the actual fine-grid axis length so the
    # _enthalpy_balance_2d face arithmetic gets matching shapes.
    def _resample_1d(arr_src, n_dst):
        if arr_src is None or len(arr_src) == n_dst:
            return arr_src
        x_src = np.linspace(0.0, 1.0, len(arr_src))
        x_dst = np.linspace(0.0, 1.0, n_dst)
        return np.interp(x_dst, x_src, arr_src).astype(np.float64)
    Nx2_real, Ny2_real = (energy_dx2.size, energy_dy2.size)
    # mA_in/out is along the cross-stream axis of A's enthalpy face; for
    # dir_A in {0,1} (x-flow) the cross axis is real y → length Ny2_real.
    # For dir_A in {2,3} (y-flow) the cross axis is real x → length Nx2_real.
    _A_cross_n = Ny2_real if dir_A in (0, 1) else Nx2_real
    _B_cross_n = Ny2_real if dir_B in (0, 1) else Nx2_real
    mA_in2  = _resample_1d(mA_in,  _A_cross_n)
    mA_out2 = _resample_1d(mA_out, _A_cross_n)
    mB_in2  = _resample_1d(mB_in,  _B_cross_n)
    mB_out2 = _resample_1d(mB_out, _B_cross_n)

    rho_cp_A_fld = (rho_cp_A if np.ndim(rho_cp_A) > 0
                    else np.full((N_x, N_y), rho_cp_A))
    rho_cp_B_fld = (rho_cp_B if np.ndim(rho_cp_B) > 0
                    else np.full((N_x, N_y), rho_cp_B))

    # sCO2 (audit 2026-06-28 D1): true mass-weighted enthalpy duty ṁ·(⟨h_in⟩−
    # ⟨h_out⟩); cp(T_in)·ΔT is −40 %…+224 % wrong across the pseudocritical cp
    # spike. air/water pass None → byte-identical legacy ρcp·ΔT (golden-safe).
    _enth_A = _pA.get('enthalpy') if _pA.get('name') == 'sco2' else None
    _enth_B = _pB.get('enthalpy') if _pB.get('name') == 'sco2' else None

    # Per-side void fraction ε_side = ε·s (N1 fix, 2026-07-07): velocities are
    # interstitial, so the physical face mass flux is ε_side·ρ·|u|·A. The old
    # code integrated with NO ε (duty over-read by 1/ε_side ≈ 2.7× on the
    # golden case, self-inconsistent with Q_solid_richardson by the same
    # factor) and applied only the asym reweight 2s/2(1−s) — i.e. the split
    # RATIO was right but the ε/2 base factor was missing. ε_side inside the
    # balance supersedes that reweight: ε·s = (ε/2)·2s. δ=0 → ε/2 per side;
    # matches the 3D flux extraction convention (flux_3d eps_mode='ltne').
    _sA_Q = float(split_A)
    _sB_Q = 1.0 - float(split_A)
    try:
        Q_A_fine = _enthalpy_balance_2d(
            Ta, ucA, vcA, rho_cp_A_fld, dir_A, energy_dx, energy_dy,
            inlet_mask=mA_in, outlet_mask=mA_out,
            enthalpy_fn=_enth_A, rho_fn=_pA['rho'], P_ref=P_inA_val,
            eps_side=eps * _sA_Q)
        Q_B_fine = _enthalpy_balance_2d(
            Tb, ucB, vcB, rho_cp_B_fld, dir_B, energy_dx, energy_dy,
            inlet_mask=mB_in, outlet_mask=mB_out,
            enthalpy_fn=_enth_B, rho_fn=_pB['rho'], P_ref=P_inB_val,
            eps_side=eps * _sB_Q)
        Q_A_coarse = _enthalpy_balance_2d(
            Ta2, ucA2, vcA2, rcp_A2, dir_A, energy_dx2, energy_dy2,
            inlet_mask=mA_in2, outlet_mask=mA_out2,
            enthalpy_fn=_enth_A, rho_fn=_pA['rho'], P_ref=P_inA_val,
            eps_side=eps2 * _sA_Q)
        Q_B_coarse = _enthalpy_balance_2d(
            Tb2, ucB2, vcB2, rcp_B2, dir_B, energy_dx2, energy_dy2,
            inlet_mask=mB_in2, outlet_mask=mB_out2,
            enthalpy_fn=_enth_B, rho_fn=_pB['rho'], P_ref=P_inB_val,
            eps_side=eps2 * _sB_Q)
        # A-1 refactor (2026-04-24): apply Richardson to |Q_A| and |Q_B|
        # separately, THEN take max. Each Richardson acts on a smooth
        # (single-sign) function across refinement, so the formal
        # 2nd-order extrapolation stays valid. Prior pipeline applied
        # Richardson after max(), which fails if max-argument flips
        # between the coarse and fine grids.
        # FIX (2026-06-24 audit): Richardson r=2 weights the FINER grid by r^2=4.
        # The historical names here are INVERTED relative to grid resolution:
        # Q_*_fine is built from `Ta`/`energy_dx` (the USER grid = COARSER), while
        # Q_*_coarse is built from `Ta2`/`energy_dx2` (the 2x-REFINED = FINER) solve.
        # So the 4x weight must sit on Q_*_coarse (the finer value). Disambiguate
        # with explicit aliases. Prior code put 4x on Q_*_fine (user/coarse grid),
        # which AMPLIFIES the O(h^2) error ~1.25x instead of cancelling it; the
        # solid-side Richardson in this same function (the _200/_100 site) is correct.
        Q_A_user, Q_A_ref2x = abs(Q_A_fine), abs(Q_A_coarse)
        Q_B_user, Q_B_ref2x = abs(Q_B_fine), abs(Q_B_coarse)
        Q_A_ext = (4.0 * Q_A_ref2x - Q_A_user) / 3.0
        Q_B_ext = (4.0 * Q_B_ref2x - Q_B_user) / 3.0
        # 2026-05-09 — NaN-fallback: if either side's 2× refined solve
        # NaN-blew up (e.g. ConstDF-v1 K extrapolation at t outside
        # [0.3, 0.5] mm produces unphysical Brinkman coefficients on the
        # finer grid), Richardson extrapolation propagates nan up to
        # Q_total. Fall back to the directly-measured Q_fine value, which
        # only depends on the user-grid Ta (already nan-guarded above).
        # User still sees a finite Q in the UI; we set richardson_warn
        # so the warning banner reflects degraded grid convergence.
        if not np.isfinite(Q_A_ext):
            Q_A_ext = abs(Q_A_fine) if np.isfinite(Q_A_fine) else float('nan')
        if not np.isfinite(Q_B_ext):
            Q_B_ext = abs(Q_B_fine) if np.isfinite(Q_B_fine) else float('nan')
        # Robust max across (possibly nan) candidates: prefer finite values.
        _q_candidates = [v for v in (Q_A_ext, Q_B_ext)
                         if np.isfinite(v)]
        Q_total = max(_q_candidates) if _q_candidates else float('nan')

        Q_fine_max = max(abs(Q_A_fine), abs(Q_B_fine))
        Q_coarse_max = max(abs(Q_A_coarse), abs(Q_B_coarse))
        # Flag when fine vs coarse grid differ a lot (Richardson 2nd-order
        # assumption in doubt). Per-side unified metric: compare the side
        # that dominates Q_total. Also flag when Richardson fell back to
        # the direct Q_fine (means the 2× refined solve was unreliable).
        _denom = max(Q_fine_max, 1e-12)
        richardson_warn = (
            (np.isfinite(Q_coarse_max)
             and abs(Q_fine_max - Q_coarse_max) / _denom > 0.10)
            or (not np.isfinite(Q_A_coarse) or not np.isfinite(Q_B_coarse)))
    except Exception as _q_exc:
        import traceback as _tb
        _tb.print_exc()
        _log.warning(f"[Q-calc] Richardson try-block raised {_q_exc!r} — "
                     f"falling through to 1D-mean fallback.")
        Q_A_fine = Q_B_fine = float('nan')
        Q_A_ext = Q_B_ext = float('nan')
        Q_fine_max = float('nan')
        Q_total = float('nan')
        richardson_warn = False

    # 2026-05-09 — UNCONDITIONAL last-resort 1D fallback. Runs OUTSIDE the
    # try/except above so an exception in the Richardson block doesn't
    # short-circuit it. Computes
    #     Q_A ≈ m_dot_A · cp_A · |T_inA − ⟨T_out_A⟩|
    # using the same outlet-face mean convention the UI's T_OUT widget uses
    # (np.mean over the outlet face with a finite-only filter). Q_total
    # stays whatever Richardson / Q_*_fine produced when those are finite;
    # if and only if Q_total is nan after the Richardson block, this
    # bumps in. Guarantees Q_total is finite whenever T_OUT_A / T_OUT_B
    # display finite (which is the same condition the UI advertises).
    if not np.isfinite(Q_total):
        try:
            # Outlet face per side. dir_code: 0=+x 1=-x 2=+y 3=-y.
            if dir_A == 0:    Tout_A_face = Ta[-1, :]
            elif dir_A == 1:  Tout_A_face = Ta[0, :]
            elif dir_A == 2:  Tout_A_face = Ta[:, -1]
            else:             Tout_A_face = Ta[:, 0]
            if dir_B == 0:    Tout_B_face = Tb[-1, :]
            elif dir_B == 1:  Tout_B_face = Tb[0, :]
            elif dir_B == 2:  Tout_B_face = Tb[:, -1]
            else:             Tout_B_face = Tb[:, 0]
            _Tout_A_finite = Tout_A_face[np.isfinite(Tout_A_face)]
            _Tout_B_finite = Tout_B_face[np.isfinite(Tout_B_face)]
            T_out_A_mean = (float(np.mean(_Tout_A_finite))
                            if _Tout_A_finite.size else float(T_inA))
            T_out_B_mean = (float(np.mean(_Tout_B_finite))
                            if _Tout_B_finite.size else float(T_inB))
            rho_A_in = float(_pA['rho'](T_inA, P_inA_val))
            rho_B_in = float(_pB['rho'](T_inB, P_inB_val))
            cp_A_in  = float(_pA['cp'](T_inA, P_inA_val))
            cp_B_in  = float(_pB['cp'](T_inB, P_inB_val))
            A_in_A = float(cfgA.get('in_w', H))
            A_in_B = float(cfgB.get('in_w', L))
            m_dot_A = rho_A_in * abs(u_A) * A_in_A
            m_dot_B = rho_B_in * abs(u_B) * A_in_B
            # Per-side void fraction ε·s (N1 fix, 2026-07-07): interstitial
            # velocity ⇒ ṁ_phys = ε_side·ρ·u·A. Replaces the ε-less 2s/2(1−s)
            # asym reweight (same ratio, adds the missing ε/2 base factor).
            _eps_mean_1d = float(np.mean(eps))
            m_dot_A *= _eps_mean_1d * float(split_A)
            m_dot_B *= _eps_mean_1d * (1.0 - float(split_A))
            # sCO2 (D1): ṁ·Δh even in the last-resort fallback (cp_in·ΔT is
            # badly wrong near the pseudocritical line). air/water keep cp·ΔT.
            if _pA.get('name') == 'sco2':
                Q_A_simple = m_dot_A * abs(float(_pA['enthalpy'](T_inA, P_inA_val))
                                           - float(_pA['enthalpy'](T_out_A_mean, P_inA_val)))
            else:
                Q_A_simple = m_dot_A * cp_A_in * abs(T_inA - T_out_A_mean)
            if _pB.get('name') == 'sco2':
                Q_B_simple = m_dot_B * abs(float(_pB['enthalpy'](T_inB, P_inB_val))
                                           - float(_pB['enthalpy'](T_out_B_mean, P_inB_val)))
            else:
                Q_B_simple = m_dot_B * cp_B_in * abs(T_inB - T_out_B_mean)
            Q_total = max(Q_A_simple, Q_B_simple)
            if np.isfinite(Q_total):
                warnings_list.append(
                    f"Q_total computed via 1D plate-average fallback "
                    f"(m_dot · cp · |T_in − ⟨T_out⟩|) because the "
                    f"cross-stream-resolved enthalpy integral was unavailable. "
                    f"Q_A={Q_A_simple:.0f} W/m, Q_B={Q_B_simple:.0f} W/m. "
                    f"Tighten tol or refine grid for production-grade Q.")
                richardson_warn = True
            _log.warning(f"[Q-calc] 1D fallback: Q_A={Q_A_simple:.1f}, "
                         f"Q_B={Q_B_simple:.1f}, Q_total={Q_total:.1f} W/m  "
                         f"(T_out_A_mean={T_out_A_mean:.2f}K, "
                         f"T_out_B_mean={T_out_B_mean:.2f}K)")
        except Exception as _fb_exc:
            import traceback as _tb2
            _tb2.print_exc()
            _log.warning(f"[Q-calc] 1D fallback also raised {_fb_exc!r} — "
                         f"Q_total stays nan.")
    return (Q_total, Q_A_fine, Q_B_fine, Q_solid_richardson,
            richardson_warn)


def _run_solvers(window, cfg, fields):
    """Phase 3: run SIMPLE + coupling loop + pressure + Richardson Q."""
    L = cfg['L']; H = cfg['H']
    N_x = cfg['N_x']; N_y = cfg['N_y']
    u_A = cfg['u_A']; u_B = cfg['u_B']
    T_inA = cfg['T_inA']; T_inB = cfg['T_inB']
    cfgA = cfg['cfgA']; cfgB = cfg['cfgB']
    dir_A = cfg['dir_A']; dir_B = cfg['dir_B']
    tpms_type = cfg['tpms_type']
    eps = cfg['eps']
    zone_config = cfg['zone_config']; za = cfg['za']
    warnings_list = cfg['warnings_list']
    fluid_A = cfg.get('fluid_A', 'air')
    fluid_B = cfg.get('fluid_B', 'air')

    energy_dx = fields['energy_dx']; energy_dy = fields['energy_dy']
    _x_breaks = fields['_x_breaks']; _y_breaks = fields['_y_breaks']
    _run_simple = fields['_run_simple']
    simple_warnings = fields['simple_warnings']

    # ── Outer velocity-temperature coupling loop ──
    import warnings as _warn
    from sjtu_tpmshx.solvers import tpms_calc as _tc
    from sjtu_tpmshx.solvers import fluid_props

    # 2026-05-09 (option B) — per-side fluid property accessors. Air uses
    # ideal-gas density (T, P); water is incompressible so P is ignored.
    # Returns (rho_fn, cp_fn, mu_fn, k_fn) — each accepts a scalar or
    # ndarray T (K) and P (Pa, optional) with broadcast semantics.
    def _props_for(fluid: str):
        # Primitives from the single fluid registry; dict shape kept for the
        # downstream ['name']/['rho']/... consumers (behavior-identical).
        m = fluid_props.get(fluid)
        return dict(rho=m.rho, cp=m.cp, mu=m.mu, k=m.k, name=m.name,
                    enthalpy=m.enthalpy)
    _pA = _props_for(fluid_A)
    _pB = _props_for(fluid_B)
    _sco2_v1 = (_pA['name'] == _pB['name'] == 'sco2'
                and dir_A == 0 and dir_B == 1
                and zone_config is None)
    mA_rows = mB_rows = None

    # 2026-05-09 — bump _MAX_COUPLING 5→10 default. The loop short-circuits
    # once both drho_X and dT_X drop below their respective tolerances, so
    # already-converged cases (most air-air on fitted-window geometries)
    # still exit at iter 3-5 with no extra work. Cases that previously hit
    # iter 5 with dT_B still bouncing (cross-flow + partial-BC inlet) now
    # have headroom to settle without firing the "not converged" warning.
    _MAX_COUPLING = 10
    _COUPLING_TOL = 0.01  # 1% relative change in rho
    _DT_TOL_K     = 1.0   # max |ΔT| between outer iterations, Kelvin
    _ALPHA_COUP = 0.7     # under-relaxation
    # R3 (2026-07-07): SolverConfig production knobs override the autos
    # above (None keeps them bit-identically). max_outer_ltne caps the
    # SIMPLE↔LTNE coupling rounds; outer_tol_K replaces the ΔT criterion.
    _sol_knobs = getattr(cfg.get('compute_cfg'), 'solver', None)
    if _sol_knobs is not None:
        if _sol_knobs.max_outer_ltne is not None:
            _MAX_COUPLING = int(_sol_knobs.max_outer_ltne)
        if _sol_knobs.outer_tol_K is not None:
            _DT_TOL_K = float(_sol_knobs.outer_tol_K)

    # Local-Re Nu rescale (2D #1 fix 2026-04-25): per-cell h_v using local
    # |u_cc|·D_h·ρ/μ Reynolds. Wall cells with u→0 fall to the laminar
    # Hagen-Poiseuille floor (prevents Nu→0 non-physical extrapolation).
    from sjtu_tpmshx.solvers.nu_correlations import NU_LAM_FLOOR as _NU_LAM_FLOOR_2D

    def _nu_dispatch(side_props, side_T_for_Pr, Re, eps_f, L_mm, D_h_mm,
                     side_P=None):
        """Per-side Nu: water / sCO2 use Pr-substitution onto a topo-fit
        correlation; air uses its native Nu. ``side_P`` (Pa) is forwarded to
        the property primitives — air/water ignore it (value-identical), sCO2
        requires it (real-gas)."""
        m = fluid_props.get(side_props['name'])
        Pr = None
        if side_props['name'] in ('water', 'sco2'):
            # Pr-substitution (2D convention: no k guard) computed here so the
            # registry stays free of the 2D-vs-3D Prandtl differences.
            mu_w = float(side_props['mu'](side_T_for_Pr, side_P))
            k_w  = float(side_props['k'](side_T_for_Pr, side_P))
            cp_w = float(side_props['cp'](side_T_for_Pr, side_P))
            Pr = mu_w * cp_w / k_w
        return m.nu(tpms_type, Re, eps_f, L_mm, D_h_mm, Pr)

    def _build_hv_local_2d(rho_scalar, mu_scalar, k_f_scalar,
                            u_mag_field, L_mm_field, t_mm_field,
                            side_props=None, side_T_for_Pr=None, side_P=None):
        """Per-cell h_v = A_0 · max(Nu(Re_local), Nu_lam) · k_f / D_h.
        L_mm_field, t_mm_field None → uniform Lcell, t_wall.
        side_props (dict) + side_T_for_Pr (K) drive water Nu dispatch
        when present; default None falls back to air Nu (legacy)."""
        Nx_l, Ny_l = u_mag_field.shape
        if L_mm_field is None:
            g_u = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
            A0 = g_u['A_0']; D_h = g_u['D_h']; eps_g = g_u['epsilon']
            Re_loc = rho_scalar * (np.abs(u_mag_field) + 1e-12) * D_h / mu_scalar
            # perf-wave1 (2026-07-03): vectorized Nu over the whole grid —
            # the 2D port of the 3D perf-B1 transform. Mirrors the old
            # per-cell loop element-for-element (Re pre-floor at 1.0, Pr
            # computed ONCE from the scalar side T exactly as _nu_dispatch
            # did per cell, Nu post-floor at _NU_LAM_FLOOR_2D, single-stream
            # ε_f = ε/2), so it is bit-identical — just Nx·Ny× fewer Python
            # calls per side per outer coupling iter.
            Re_arr = np.maximum(Re_loc, 1.0)
            if side_props is not None:
                m = fluid_props.get(side_props['name'])
                Pr = None
                if side_props['name'] in ('water', 'sco2'):
                    mu_w = float(side_props['mu'](side_T_for_Pr, side_P))
                    k_w = float(side_props['k'](side_T_for_Pr, side_P))
                    cp_w = float(side_props['cp'](side_T_for_Pr, side_P))
                    Pr = mu_w * cp_w / k_w
                Nu_arr = m.nu(tpms_type, Re_arr, eps_g / 2.0, Lcell,
                              D_h * 1000.0, Pr)
            else:
                Nu_arr = _tc.nu_from_Re(tpms_type, Re_arr, eps_g / 2.0,
                                        Lcell, D_h * 1000.0)
            Nu_arr = np.maximum(np.asarray(Nu_arr, dtype=np.float64),
                                _NU_LAM_FLOOR_2D)
            return A0 * Nu_arr * k_f_scalar / D_h
        out = np.empty((Nx_l, Ny_l), dtype=np.float64)
        for i in range(Nx_l):
            for j in range(Ny_l):
                L_ij = float(L_mm_field[i, j]); t_ij = float(t_mm_field[i, j])
                g = tpms_geometry(tpms_type, L_ij, t_ij, k_s)
                D_h_l = g['D_h']
                Re_l = rho_scalar * (abs(float(u_mag_field[i, j])) + 1e-12) * D_h_l / mu_scalar
                Re_ij = max(Re_l, 1.0)
                if side_props is not None:
                    nu_corr = _nu_dispatch(side_props, side_T_for_Pr,
                                            Re_ij, g['epsilon'] / 2.0,
                                            L_ij, D_h_l * 1000.0, side_P)
                else:
                    nu_corr = _tc.nu_from_Re(tpms_type, Re_ij,
                                              g['epsilon'] / 2.0,
                                              L_ij, D_h_l * 1000.0)
                Nu_l = max(nu_corr, _NU_LAM_FLOOR_2D)
                out[i, j] = g['A_0'] * Nu_l * k_f_scalar / D_h_l
        return out

    tpms_type = cfg['tpms_type']
    Lcell = cfg['Lcell']; t_wall = cfg['t_wall']; k_s = cfg['k_s']

    mu_A, mu_B = window._mu_A, window._mu_B
    P_inA_val = cfg['compute_cfg'].fluid_A.P_in_Pa
    P_inB_val = cfg['compute_cfg'].fluid_B.P_in_Pa

    # ── Asymmetric per-side porosity (offset-isosurface δ) — mirror 3D ──
    # δ=0 → symmetric (split=0.5, factors=1, no per-side override) → bit-
    # identical legacy path. δ≠0 → redistribute the total void between channels
    # A / B by the geometry split ratio s = split_A (shared with 3D via
    # solvers.asym_split). 2D's symmetric K_ff uses the FULL ε (tpms_calc:506)
    # while the convective term uses ε/2, so EVERY per-side void-weighted term
    # scales by the SAME factor relative to the symmetric ε/2 baseline —
    # 2s for A, 2(1−s) for B — which is bit-identical at δ=0 (factor=1 at s=0.5)
    # and keeps diffusion / convection / duty per-side consistent. The kernel
    # itself receives the absolute eps_A = ε·s / eps_B = ε·(1−s) (Phase 1 hook).
    # See design add-2d-asym-porosity D2(b).
    from sjtu_tpmshx.solvers.asym_split import _asym_split_A as _asym_split_A_2d
    _delta_2d = float(cfg['compute_cfg'].geometry.delta_levelset)
    _asym_2d = (_delta_2d != 0.0)
    _split_A_2d = _asym_split_A_2d({'delta_levelset': _delta_2d},
                                   tpms_type, Lcell, t_wall)
    _epsfac_A = 2.0 * _split_A_2d            # ε_A / (ε/2)
    _epsfac_B = 2.0 * (1.0 - _split_A_2d)    # ε_B / (ε/2)

    # Per-side interfacial coupling h_v geometry ratio under δ (mirror 3D
    # stages_3d._hv_side_geom_ratio). Each side's (A_0, D_h) shift with the
    # offset; the ratio vs the δ=0 reference is EXACTLY 1.0 at δ=0 (bit-
    # identical ×1.0) and u-independent (Re_side/Re_ref = D_h_side/D_h_ref), so
    # the scalar applies to both the bulk and local-Re h_v. k_f cancels. Captures
    # the geometric Nu/area effect; the residual κ_Nu is CFD calibration (P1-CFD,
    # out of scope). Per-side dP (Darcy-Forchheimer κ) is likewise the opt-in
    # CFD κ layer — 3D's default kappa_KcF returns (1,1) with no table, so the
    # symmetric K_df/cF here matches the 3D default. See design D2(b) / Risks.
    def _hv_side_geom_ratio_2d(side_props, u_side, T_side, P_side):
        if not _asym_2d:
            return 1.0
        from sjtu_tpmshx.solvers.tpms_geometry import _phi_grid, _C_from_tL
        from sjtu_tpmshx.solvers import asym_geometry as _ag
        _N = 128
        _phi = _phi_grid(tpms_type, _N)
        _C = _C_from_tL(tpms_type, float(t_wall) / float(Lcell))
        _Lm = float(Lcell) / 1000.0
        A0A, A0B = _ag.a0_sides(_phi, _C, _delta_2d, _Lm, _N)
        DhA, DhB = _ag.dh_sides(_phi, _C, _delta_2d, _Lm, _N, mc=True)
        A0A0, A0B0 = _ag.a0_sides(_phi, _C, 0.0, _Lm, _N)
        DhA0, DhB0 = _ag.dh_sides(_phi, _C, 0.0, _Lm, _N, mc=True)
        _is_A = (side_props is _pA)
        A0_s, Dh_s, A0_r, Dh_r = ((A0A, DhA, A0A0, DhA0) if _is_A
                                  else (A0B, DhB, A0B0, DhB0))
        _rho = float(side_props['rho'](T_side, P_side))
        _mu = float(side_props['mu'](T_side, P_side))

        def _hv(A0, Dh):
            Dh_m = max(float(Dh), 1e-12)
            Re = max(_rho * abs(float(u_side)) * Dh_m / max(_mu, 1e-30), 1.0)
            if side_props['name'] in ('water', 'sco2'):
                nu = _nu_dispatch(side_props, T_side, Re, 0.5 * float(eps),
                                  Lcell, Dh_m * 1000.0, P_side)
            else:
                nu = _tc.nu_from_Re(tpms_type, Re, 0.5 * float(eps),
                                    Lcell, Dh_m * 1000.0)
            nu = max(nu, _NU_LAM_FLOOR_2D)
            return A0 * nu / Dh_m
        _ref = _hv(A0_r, Dh_r)
        return (_hv(A0_s, Dh_s) / _ref) if _ref > 0 else 1.0

    _hv_ratio_A_2d = _hv_side_geom_ratio_2d(_pA, u_A, T_inA, P_inA_val)
    _hv_ratio_B_2d = _hv_side_geom_ratio_2d(_pB, u_B, T_inB, P_inB_val)

    def _on_progress(step, total):
        pass  # progress handled by main thread timer

    coupling_converged = False
    drho_A = drho_B = float('inf')
    dT_A = dT_B = float('inf')
    # Warm-start delta tracker (shared with the 3D driver) — ΔTa/ΔTb/ΔTs < tol
    # AND mass-flux-weighted Δρ < tol; owns the prev-copy bookkeeping.
    # A2 (2026-07-06): Ts added — the solid field settles slowest and the old
    # (Ta,Tb)-only gate could break while Ts was still moving.
    _outer_conv = OuterConvergence(tol_T=_DT_TOL_K, track=('Ta', 'Tb', 'Ts'))
    e_info = {'converged': False, 'iterations': 0, 'residual': float('inf')}
    # Sticky: set the moment the energy solve produces a NaN cell. The NaN is
    # patched over (below) so the UI can still render velocity/pressure, but a
    # patched-over blow-up must never be reported as a converged solve. Sticky
    # because a later outer iteration starting from the PATCHED field can
    # converge on the patch — the deltas between two identically-patched fields
    # are small. (Audit 2026-07-12.)
    _energy_nan_hit = False
    Ta = Tb = Ts = None
    # User-provided solid warm-start seed. Empty → solver fallback
    # (per-fluid inlet T for Ta/Tb, 0.5*(T_inA+T_inB) for Ts).
    # Filled → only Ts is overridden with the user value; Ta/Tb stay at
    # the per-fluid inlet T to avoid the 0.5-mean energy-balance leak
    # (2026-04-24 FV fix in solvers/ltne_energy_3d.py: mid-T value at
    # non-pipe inlet cells diffuses back as a virtual heat source,
    # ~20–25% on partial-inlet geometries). Ts is *not* prescribed; the
    # solid energy equation still updates it every sweep.
    _Ts_init_user = cfg.get('T_s_init')
    if _Ts_init_user is not None:
        Ta = np.full((N_x, N_y), float(T_inA), dtype=np.float64)
        Tb = np.full((N_x, N_y), float(T_inB), dtype=np.float64)
        Ts = np.full((N_x, N_y), float(_Ts_init_user), dtype=np.float64)
    _has_partial_A = False
    _has_partial_B = False
    ucA = vcA = ucB = vcB = None
    ucA_disp = vcA_disp = ucB_disp = vcB_disp = None   # N5 display copies
    simpA = simpB = None

    rho_cp_A = _pA['rho'](T_inA, P_inA_val) * _pA['cp'](T_inA, P_inA_val)
    rho_cp_B = _pB['rho'](T_inB, P_inB_val) * _pB['cp'](T_inB, P_inB_val)

    # Variable density: 2D rho fields for SIMPLE (initialized uniform)
    rho_A_field = np.full((N_x, N_y), _pA['rho'](T_inA, P_inA_val))
    rho_B_field = np.full((N_x, N_y), _pB['rho'](T_inB, P_inB_val))

    # Outer SIMPLE↔LTNE loop, driven by the shared run_outer_coupling skeleton
    # (2D = SIMPLE-first: `step` solves SIMPLE A/B + the coupled energy + the
    # dual ΔT/Δρ check; `post` under-relaxes the rho/rho·cp fields for the next
    # iter via the carry). Body below is the verbatim former loop body; the
    # `nonlocal`s are the vars that persist across iters or are read afterwards.
    def _step_2d(_coup_it):
        nonlocal ucA, vcA, ucB, vcB, simpA, simpB, Ta, Tb, Ts, e_info
        nonlocal mA_rows, mB_rows
        nonlocal _energy_nan_hit
        nonlocal ucA_disp, vcA_disp, ucB_disp, vcB_disp
        nonlocal mu_A, mu_B, _has_partial_A, _has_partial_B
        nonlocal drho_A, drho_B, dT_A, dT_B
        window._compute_progress = 10 + int(80 * _coup_it / _MAX_COUPLING)
        # Live iteration label for the UI button ticker (replaces the
        # dropped ETA text). 2026-05-14.
        window._iter_label_now = f"iter {_coup_it + 1}/{_MAX_COUPLING}"

        # Step 1: SIMPLE velocity with current rho field. Pass Ta/Tb after
        # first outer iter so SIMPLE _update_density uses local T (not stale T_in).
        _Ta_for_simpA = Ta if _coup_it > 0 else None
        _Tb_for_simpB = Tb if _coup_it > 0 else None
        with _warn.catch_warnings(record=True) as _caught:
            _warn.simplefilter("always")
            # 2026-05-09 (option B) — incompressible fluids run SIMPLE with
            # _update_density (ideal-gas P/RT update) as a no-op; ρ stays
            # at the inlet value over the whole field. B1 1.1: mapping via
            # the registry's flow_model() instead of a per-site string check.
            _ftA = fluid_props.flow_model(_pA['name'])
            _ftB = fluid_props.flow_model(_pB['name'])
            from sjtu_tpmshx.df_surrogate.predict import SCO2_DF_METHOD
            _dfA = SCO2_DF_METHOD if _pA['name'] == 'sco2' else None
            _dfB = SCO2_DF_METHOD if _pB['name'] == 'sco2' else None
            # perf-wave1 (2026-07-03): run the two independent SIMPLE solves
            # on two OS threads — the 2D port of run_stack_3d's
            # _run_two_simple_parallel. njit kernels + spsolve release the
            # GIL, the solvers share no mutable state (separate instances,
            # per-side live-residual lists, per-label simple_warnings keys),
            # and the outputs are the same objects the sequential calls
            # produced — golden 2D stays bit-identical, only wall-clock
            # changes. Errors are re-raised after BOTH threads join so a
            # cancel/exception on one side can't orphan the other.
            import threading as _threading
            _res: list = [None, None]
            _err: list = [None, None]

            def _solve_side(idx, args, kwargs):
                try:
                    _res[idx] = _run_simple(*args, **kwargs)
                except BaseException as e:   # incl. InterruptedError
                    _err[idx] = e

            # C8 shooting: hand the PREVIOUS iteration's (P_ref_abs, solved
            # dP — reporting convention) to _run_simple, which recreates the
            # solver each outer iter. First iteration has no previous solve
            # → None (the 1D closed-form seed stands). _run_simple itself
            # gates on the knob + ideal_gas, so passing unconditionally is
            # inert when shooting is off or the side is incompressible.
            _psA = ((float(simpA.P_ref_abs), _pipe_dp_2d(simpA))
                    if simpA is not None else None)
            _psB = ((float(simpB.P_ref_abs), _pipe_dp_2d(simpB))
                    if simpB is not None else None)
            _tA = _threading.Thread(
                target=_solve_side,
                args=(0, (cfgA, rho_A_field, mu_A, T_inA, u_A,
                          'Fluid A', P_inA_val),
                      dict(T_field_real=_Ta_for_simpA,
                           fluid_type=_ftA, df_method=_dfA,
                           rho_inlet_ref=(
                               float(_pA['rho'](T_inA, P_inA_val))
                               if _pA['name'] == 'sco2' else None),
                           p_shoot_prev=_psA)),
                daemon=True)
            _tB = _threading.Thread(
                target=_solve_side,
                args=(1, (cfgB, rho_B_field, mu_B, T_inB, u_B,
                          'Fluid B', P_inB_val),
                      dict(T_field_real=_Tb_for_simpB,
                           fluid_type=_ftB, df_method=_dfB,
                           rho_inlet_ref=(
                               float(_pB['rho'](T_inB, P_inB_val))
                               if _pB['name'] == 'sco2' else None),
                           p_shoot_prev=_psB)),
                daemon=True)
            _tA.start(); _tB.start()
            _tA.join(); _tB.join()
            for _e in _err:
                if _e is not None:
                    raise _e
            ucA, vcA, simpA = _res[0]
            ucB, vcB, simpB = _res[1]
        # Collect EVERY round's warnings (dedup by message). The old
        # `if _coup_it == 0` gate destroyed any warning first raised on a
        # later coupling round — e.g. Re drifting out of the Nu fit window
        # only after the properties iterated (blind-spot audit W1a,
        # 2026-07-07); record=True also suppresses the default stderr print,
        # so a dropped message was lost everywhere.
        for w in _caught:
            _msg = str(w.message)
            if _msg not in warnings_list:
                warnings_list.append(_msg)

        window._compute_progress = 10 + int(80 * (_coup_it + 0.3) / _MAX_COUPLING)

        # Smooth velocity near partial-width wall boundaries — DISPLAY ONLY.
        # N5 (2026-07-07): the smoothed fields used to OVERWRITE ucA/vcA and
        # feed the LTNE energy solve, the local-Re h_v build and the duty
        # extraction. Gaussian filtering breaks the discrete mass balance of
        # the advecting field (spurious grid-dependent ∇·(ερcp·u) sources on
        # the temperature-form kernel) — the same defect class as the
        # 2026-06-24 temperature-smoothing fix, which kept Ta_raw for
        # physics. Physics now consumes the raw mass-conserving fields;
        # only the rendered copies are smoothed.
        _has_partial_A = np.any(simpA.outlet_frac < 0.99) or np.any(simpA.inlet_frac < 0.99)
        _has_partial_B = np.any(simpB.outlet_frac < 0.99) or np.any(simpB.inlet_frac < 0.99)
        ucA_disp = vcA_disp = ucB_disp = vcB_disp = None
        if _has_partial_A or _has_partial_B:
            from scipy.ndimage import gaussian_filter
            _sv = 2.0
            if _has_partial_A:
                ucA_disp = gaussian_filter(ucA, sigma=_sv)
                vcA_disp = gaussian_filter(vcA, sigma=_sv)
            if _has_partial_B:
                ucB_disp = gaussian_filter(ucB, sigma=_sv)
                vcB_disp = gaussian_filter(vcB, sigma=_sv)

        # Inlet fractions for energy solver (continuous blending at wall/open edge)
        _imA = simpA.inlet_frac.astype(np.float64)  # 1D float, length = SIMPLE Nx for A
        _imB = simpB.inlet_frac.astype(np.float64)  # 1D float, length = SIMPLE Nx for B

        # Build local-Re per-cell h_v fields (#1 fix). Use cell-center magnitude.
        u_mag_A = np.sqrt(ucA**2 + vcA**2)
        u_mag_B = np.sqrt(ucB**2 + vcB**2)
        # Zoned L/t fields (only if zone_config and grid mode); otherwise None
        L_field_2d = None; t_field_2d = None
        if zone_config is not None and za is not None:
            L_field_2d = za.get('L_mm_arr')
            t_field_2d = za.get('t_arr')
        if _sco2_v1:
            # Reuse the array-rank-agnostic 3D closure so 2D and 3D evaluate
            # rho, mu, k, cp, Re and Pr from the same lagged local T field.
            from sjtu_tpmshx.pipelines.flux_3d import _sco2_hv_local_field
            _g_hv = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
            _Ta_hv = (Ta if Ta is not None
                      else np.full_like(u_mag_A, T_inA))
            _Tb_hv = (Tb if Tb is not None
                      else np.full_like(u_mag_B, T_inB))
            h_vA_local = _sco2_hv_local_field(
                _Ta_hv, P_inA_val, u_mag_A, _g_hv['A_0'], _g_hv['D_h'],
                tpms_type, Lcell)
            h_vB_local = _sco2_hv_local_field(
                _Tb_hv, P_inB_val, u_mag_B, _g_hv['A_0'], _g_hv['D_h'],
                tpms_type, Lcell)
        else:
            rho_A_scalar = float(rho_A_field.mean())
            rho_B_scalar = float(rho_B_field.mean())
            mu_A_scalar = (float(np.asarray(mu_A).mean())
                           if np.ndim(mu_A) else float(mu_A))
            mu_B_scalar = (float(np.asarray(mu_B).mean())
                           if np.ndim(mu_B) else float(mu_B))
            k_fA = float(_pA['k'](T_inA, P_inA_val))
            k_fB = float(_pB['k'](T_inB, P_inB_val))
            h_vA_local = _build_hv_local_2d(
                rho_A_scalar, mu_A_scalar, k_fA,
                u_mag_A, L_field_2d, t_field_2d,
                side_props=_pA, side_T_for_Pr=T_inA, side_P=P_inA_val)
            h_vB_local = _build_hv_local_2d(
                rho_B_scalar, mu_B_scalar, k_fB,
                u_mag_B, L_field_2d, t_field_2d,
                side_props=_pB, side_T_for_Pr=T_inB, side_P=P_inB_val)
        # Per-side interfacial geometry under δ (1.0 at δ=0 → bit-identical).
        if _asym_2d:
            h_vA_local = h_vA_local * _hv_ratio_A_2d
            h_vB_local = h_vB_local * _hv_ratio_B_2d

        # 2026-05-09 (option B) — water-side stiffness: ρ·cp_water ~ 4100×
        # ρ·cp_air, h_v_water ~ 2-3× h_v_air (Pr-substitution). solve_full_domain
        # GS-smoother is air-fit and can NaN-blow up on raw water settings.
        # Loosen tol + raise max_iter when ANY side is water; air-air case
        # keeps the original tight settings.
        _has_water = (_pA['name'] == 'water') or (_pB['name'] == 'water')
        _e_max_iter = 12000 if _has_water else 5000
        _e_tol      = 1.0   if _has_water else 0.5
        if _sco2_v1:
            _e_tol = 0.1

        # Step 2: Full-domain coupled energy solve (warm-start from previous iteration)
        # Per-side porosity for the offset-isosurface δ. δ=0 → eps_A/eps_B None
        # and the K_ff sources are passed through unscaled → bit-identical to the
        # legacy symmetric path (zoned and non-zoned branches only ever differed
        # in the K_ff / ε *source* and the kwarg order, both equivalent here).
        if zone_config is not None:
            _Kffa_src = za['K_ffA_arr']; _Kffb_src = za['K_ffB_arr']
            _Kss_src = za['K_ss_arr']; _eps_src = za['eps_arr']
        else:
            _Kffa_src = window._K_ffA; _Kffb_src = window._K_ffB
            _Kss_src = window._K_ss; _eps_src = eps
        if _asym_2d:
            _Kffa_use = _Kffa_src * _epsfac_A
            _Kffb_use = _Kffb_src * _epsfac_B
            _epsA_use = _eps_src * _split_A_2d
            _epsB_use = _eps_src * (1.0 - _split_A_2d)
        else:
            _Kffa_use = _Kffa_src; _Kffb_use = _Kffb_src
            _epsA_use = None; _epsB_use = None
        def _simp_P_abs_real(simp, direction, P_in, fluid_name):
            if window._is_x_dir(direction):
                gauge = simp.P.T.copy()
                if direction == 1:
                    gauge = gauge[::-1, :]
            else:
                gauge = simp.P.copy()
                if direction == 3:
                    gauge = gauge[:, ::-1]
            if fluid_name == 'sco2':
                inlet = gauge[0, :] if direction == 0 else gauge[-1, :]
                return np.ascontiguousarray(P_in + gauge - inlet[None, :])
            return np.ascontiguousarray(simp.P_ref_abs + gauge)

        P_abs_A = _simp_P_abs_real(simpA, dir_A, P_inA_val, _pA['name'])
        P_abs_B = _simp_P_abs_real(simpB, dir_B, P_inB_val, _pB['name'])
        if _sco2_v1:
            from sjtu_tpmshx.solvers.ltne_enthalpy_2d import (
                solve_sco2_enthalpy_2d,
            )
            eps_side = np.asarray(_eps_src, dtype=np.float64) * 0.5
            eps_A_in = (float(eps_side) if eps_side.ndim == 0
                        else eps_side[0, :])
            eps_B_in = (float(eps_side) if eps_side.ndim == 0
                        else eps_side[-1, :])
            rho_A_in = simpA.rho_field[:, 0]
            rho_B_in = simpB.rho_field[:, 0]
            # Use the SIMPLE-native inlet face, not the first cell-centre
            # velocity (which averages inlet and interior faces and therefore
            # does not exactly carry the prescribed mass flow).  Both +x and
            # -x solves inject at SIMPLE j=0; the real-coordinate flip happens
            # only in the reconstructed display/energy fields.
            mA_rows = (eps_A_in * rho_A_in * np.abs(simpA.v[:, 0])
                       * energy_dy)
            mB_rows = (eps_B_in * rho_B_in * np.abs(simpB.v[:, 0])
                       * energy_dy)
            Ta, Tb, Ts, e_info = solve_sco2_enthalpy_2d(
                T_inA, T_inB, P_abs_A, P_abs_B, mA_rows, mB_rows,
                h_vA_local, h_vB_local, _Kss_src, energy_dx, energy_dy,
                Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
                max_iter=_e_max_iter, tol=_e_tol,
            )
        else:
            Ta, Tb, Ts, e_info = solve_full_domain(
                L, H, N_x, N_y, T_inA, T_inB,
                _Kffa_use, _Kffb_use, _Kss_src,
                h_vA_local, h_vB_local,
                rho_cp_A, rho_cp_B,
                _eps_src, ucA, vcA, ucB, vcB,
                dir_A, dir_B,
                max_iter=_e_max_iter, tol=_e_tol,
                progress_cb=_on_progress, return_info=True,
                Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
                dx_arr=energy_dx, dy_arr=energy_dy,
                inlet_mask_A=_imA, inlet_mask_B=_imB,
                eps_A=_epsA_use, eps_B=_epsB_use)

        # 2026-05-09 NaN guard — energy solver may NaN-blow up on water-side
        # stiffness (rho·cp 4100× + h_v 2-3× vs air). Replace nan with the
        # per-side inlet T so finalize_plots can render velocity / pressure
        # canvases (the user still wants those visible) instead of crashing
        # on contourf(nan). Surface a warning so the user knows Q is unreliable.
        _has_nan = (np.any(np.isnan(Ta)) or np.any(np.isnan(Tb))
                    or np.any(np.isnan(Ts)))
        if _has_nan:
            # Validity, not just a warning string: the patched field is NOT a
            # solution. Sticky flag → forced into solver_converged below.
            _energy_nan_hit = True
            n_nan_a = int(np.sum(np.isnan(Ta)))
            n_nan_b = int(np.sum(np.isnan(Tb)))
            n_nan_s = int(np.sum(np.isnan(Ts)))
            n_total = Ta.size
            _cause = ("water-side LTNE stiffness (ρ·cp 4100× air)"
                      if _has_water
                      else "energy solver divergence (likely Nu/h_v "
                           "extrapolation, partial-BC layer, or non-monotonic "
                           "convection — check log)")
            warnings_list.append(
                f"Energy solver produced NaN cells "
                f"(Ta {n_nan_a}/{n_total}, Tb {n_nan_b}/{n_total}, "
                f"Ts {n_nan_s}/{n_total}) — replacing with inlet T so "
                f"the 2D result view can render velocity/pressure. "
                f"Q value is unreliable. Cause: {_cause}.")
            Ta = np.where(np.isnan(Ta), T_inA, Ta)
            Tb = np.where(np.isnan(Tb), T_inB, Tb)
            Ts = np.where(np.isnan(Ts), 0.5 * (T_inA + T_inB), Ts)

        # Step 3: Update rho*cp and rho field from per-cell temperature AND
        # per-cell absolute pressure. Using the scalar inlet P here under-
        # predicts density drop across the domain at high dP and diverges
        # from the 3D path (which already uses P_ref_abs + P). Transpose /
        # flip SIMPLE coords → real (Nx, Ny) to match Ta shape.
        rho_cp_A_new = _pA['rho'](Ta, P_abs_A) * _pA['cp'](Ta, P_abs_A)
        rho_cp_B_new = _pB['rho'](Tb, P_abs_B) * _pB['cp'](Tb, P_abs_B)
        rho_A_field_new = _pA['rho'](Ta, P_abs_A)
        rho_B_field_new = _pB['rho'](Tb, P_abs_B)

        # Variable mu: build 2D viscosity field from per-cell Ta/Tb via
        # Sutherland (air) or Vogel (water). With local-P density now using
        # the full field, local mu keeps the momentum balance consistent
        # cell-by-cell.
        mu_A = _pA['mu'](Ta, P_abs_A)
        mu_B = _pB['mu'](Tb, P_abs_B)
        T_avg_A = float(Ta.mean()); T_avg_B = float(Tb.mean())

        # Convergence: mass-flux-weighted relative rho change.
        # Physical reasoning — the coupling is driven by ∇·(ρu) = 0, so only
        # cells with nonzero mass flux are physically relevant. Wall cells
        # (v≈0 under partial BC) have T that drifts slowly from neighbor
        # diffusion but does not affect the coupled solution. Weighting by
        # |u| filters that tail-end noise cleanly so the metric reflects
        # convergence where it matters.
        dA = rho_A_field_new - rho_A_field
        dB = rho_B_field_new - rho_B_field
        wA = np.sqrt(ucA * ucA + vcA * vcA) + 1e-12
        wB = np.sqrt(ucB * ucB + vcB * vcB) + 1e-12
        drho_A = float(np.sum(np.abs(dA / rho_A_field) * wA) / np.sum(wA))
        drho_B = float(np.sum(np.abs(dB / rho_B_field) * wB) / np.sum(wB))

        # Temperature-field convergence: max|ΔT| across outer iterations.
        # rho-only criterion can flag converged while the T field is still
        # drifting (rho = P / (R·T) damps temperature swings); requiring
        # both is a tighter guarantee the coupled state is stationary.
        # ΔTa/ΔTb/ΔTs (tol _DT_TOL_K) AND mass-flux-weighted Δρ (tol
        # _COUPLING_TOL) — the shared tracker owns the ΔT deltas + warm-start
        # prev-copy; Δρ is the 2D-specific extra criterion.
        _converged, _deltas = _outer_conv.check(
            {'Ta': Ta, 'Tb': Tb, 'Ts': Ts},
            extra=(drho_A, drho_B), extra_tol=_COUPLING_TOL)
        dT_A = _deltas['Ta']; dT_B = _deltas['Tb']
        _log.info(f"  [Coupling {_coup_it+1}] drho_A={drho_A:.4f} drho_B={drho_B:.4f} "
                  f"dT_A={dT_A:.2f}K dT_B={dT_B:.2f}K dT_S={_deltas['Ts']:.2f}K "
                  f"T_avg_A={T_avg_A:.1f}K T_avg_B={T_avg_B:.1f}K")

        # Carry the under-relaxation inputs to `post` (avoids 4 more nonlocals).
        return _converged, (rho_A_field_new, rho_B_field_new,
                            rho_cp_A_new, rho_cp_B_new)

    def _post_2d(_coup_it, _carry):
        nonlocal rho_A_field, rho_B_field, rho_cp_A, rho_cp_B
        (rho_A_field_new, rho_B_field_new,
         rho_cp_A_new, rho_cp_B_new) = _carry
        # Under-relax (field-wise)
        rho_A_field = _ALPHA_COUP * rho_A_field_new + (1 - _ALPHA_COUP) * rho_A_field
        rho_B_field = _ALPHA_COUP * rho_B_field_new + (1 - _ALPHA_COUP) * rho_B_field
        rho_cp_A = _ALPHA_COUP * rho_cp_A_new + (1 - _ALPHA_COUP) * rho_cp_A
        rho_cp_B = _ALPHA_COUP * rho_cp_B_new + (1 - _ALPHA_COUP) * rho_cp_B

    _last_coup, coupling_converged = run_outer_coupling(
        max_iter=_MAX_COUPLING, step=_step_2d, post=_post_2d)

    if not coupling_converged:
        warnings_list.append(
            f"Velocity-temperature coupling: not converged after {_MAX_COUPLING} iters "
            f"(drho_A={drho_A:.4f}, drho_B={drho_B:.4f}, "
            f"dT_A={dT_A:.2f}K, dT_B={dT_B:.2f}K)")
    warnings_list.extend(simple_warnings.values())

    # Zone statistics and boundary lines
    z_axis = cfg['z_axis']
    _apply_zone_stats_2d(window, z_axis, zone_config, za, L, H,
                         energy_dx, energy_dy, Ta, Tb, Ts)

    # FIX (2026-06-24): keep RAW (unsmoothed) fields for Q extraction. The
    # display smoothing below blurs the sharp inlet/outlet thermal gradients;
    # because gaussian_filter `sigma` is in CELLS, that blur is GRID-DEPENDENT
    # and corrupts the enthalpy-balance Q — it drags the pinned 422 K air inlet
    # down to ~403 K on a 20-grid (and warms the outlet), halving the apparent
    # ΔT. This was the root cause of the 2D heat-duty grid non-convergence
    # (Q_A_fine used the smoothed field, while the Richardson 2× grid is solved
    # fresh = unsmoothed, so the two disagreed wildly). The old comment "Q/dP
    # already computed from raw fields" was STALE — Q is computed below, AFTER
    # this block, so it must be fed the raw fields explicitly.
    Ta_raw, Tb_raw, Ts_raw = Ta, Tb, Ts

    # Smooth temperature fields FOR DISPLAY ONLY if partial-width inlets exist
    # (removes Brinkman-induced stripes). Rebinds Ta/Tb/Ts to display copies;
    # the Q call below uses Ta_raw/Tb_raw/Ts_raw.
    if _has_partial_A or _has_partial_B:
        from scipy.ndimage import gaussian_filter
        _st = 1.5  # temperature smoothing width in cells
        Ta = gaussian_filter(Ta, sigma=_st)
        Tb = gaussian_filter(Tb, sigma=_st)
        Ts = gaussian_filter(Ts, sigma=_st)

    # Store for slider / export (wrap in 3D for compatibility)
    window.T_fA = Ta[np.newaxis]
    window.T_fB = Tb[np.newaxis]
    window.T_s  = Ts[np.newaxis]

    # ── Step 3: Pressure from SIMPLE ──
    P_inA = cfg['compute_cfg'].fluid_A.P_in_Pa
    P_inB = cfg['compute_cfg'].fluid_B.P_in_Pa
    P_fA, P_fB, dP_A, dP_B = _compute_pressure_2d(
        simpA, simpB, dir_A, dir_B, P_inA, P_inB, window)

    # ── Post-solve compressible validity gate (robustness, 2026-06-25) ──
    # Same fail-loud guard as the 3D pipeline: a choked air case (dP -> P_in,
    # outlet vacuum) drives v=G/rho supersonic; flag it instead of returning
    # garbage. Both ideal-gas sides checked (air-air B can choke too); water is
    # incompressible. Mach is per-cell against the local temperature.
    _env_mode = cfg.get('envelope_mode', 'raise')
    _env_valid = True
    _env_reasons = []
    _clip_hits_2d = 0
    if simpA is not None and getattr(simpA, 'fluid_type', None) == 'ideal_gas':
        _clip_hits_2d += int(getattr(simpA, '_p_clip_hits', 0))
        _vmagA = np.sqrt(np.asarray(ucA) ** 2 + np.asarray(vcA) ** 2)
        _vA, _rA = gate_solution(
            float((simpA.P_ref_abs + simpA.P).min()), float(_vmagA.max()),
            float(T_inA), mode=_env_mode, dims='2D-A',
            # RAW T (2026-07-13 audit): Ta/Tb are display-smoothed rebinds by
            # this point on partial-BC runs — a physics gate must not read a
            # cosmetic filter. Q below already uses the raw fields.
            ma_max=mach_field_max(_vmagA, Ta_raw))
        _env_valid = _env_valid and _vA
        _env_reasons += [f"[A] {r}" for r in _rA]
    if simpB is not None and getattr(simpB, 'fluid_type', None) == 'ideal_gas':
        _clip_hits_2d += int(getattr(simpB, '_p_clip_hits', 0))
        _vmagB = np.sqrt(np.asarray(ucB) ** 2 + np.asarray(vcB) ** 2)
        _vB, _rB = gate_solution(
            float((simpB.P_ref_abs + simpB.P).min()), float(_vmagB.max()),
            float(T_inB), mode=_env_mode, dims='2D-B',
            ma_max=mach_field_max(_vmagB, Tb_raw))
        _env_valid = _env_valid and _vB
        _env_reasons += [f"[B] {r}" for r in _rB]

    if _sco2_v1:
        Q_A_fine = float(e_info['Q_A'])
        Q_B_fine = float(e_info['Q_B'])
        # Match the established 3D/Shanghai headline convention: Fluid-A
        # advective enthalpy duty. Fluid B remains the conservation diagnostic.
        Q_total = abs(Q_A_fine)
        Q_solid_richardson = abs(Q_B_fine)
        richardson_warn = False
    else:
        # Compute Q with Richardson extrapolation (N_x×N_y + 2N_x×2N_y)
        (Q_total, Q_A_fine, Q_B_fine, Q_solid_richardson,
         richardson_warn) = _compute_Q_richardson(
            Ta_raw, Tb_raw, Ts_raw, ucA, vcA, ucB, vcB, rho_cp_A, rho_cp_B,
            simpA, simpB, N_x, N_y, L, H, dir_A, dir_B,
            energy_dx, energy_dy, _x_breaks, _y_breaks,
            T_inA, T_inB, P_inA_val, P_inB_val, eps, za, window,
            _pA, _pB, cfgA, cfgB, u_A, u_B, warnings_list,
            split_A=_split_A_2d,
            hv_ratio_A=_hv_ratio_A_2d, hv_ratio_B=_hv_ratio_B_2d)

    # ΔP: always from SIMPLE converged P fields (dP_A, dP_B set above at line 580-581
    # via inlet/outlet-weighted SIMPLE pressure averages). Previously this block
    # overrode dP with compute_dP_continuous (legacy f-Re) when sigmoid fields
    # were present — that bypassed SIMPLE's D-F closure and is now removed.
    # Production dP path is strictly SIMPLE (2026-04-17).

    # Smooth pressure and velocity fields for display if partial-width
    if _has_partial_A or _has_partial_B:
        from scipy.ndimage import gaussian_filter
        _sp = 1.5
        if _has_partial_A:
            P_fA = gaussian_filter(P_fA, sigma=_sp)
        if _has_partial_B:
            P_fB = gaussian_filter(P_fB, sigma=_sp)

    # Capture SIMPLE residual histories so the Pressure tab can render a
    # convergence mini-plot alongside the pressure fields. A copy avoids
    # holding a reference to the live solver past this function.
    # except-audit 2026-07-03: narrowed from bare Exception — only a missing
    # / non-iterable `residuals` attr is expected here (cosmetic mini-plot
    # data); anything else should surface.
    try:
        resid_A = list(simpA.residuals) if simpA is not None else None
    except (AttributeError, TypeError):
        resid_A = None
    try:
        resid_B = list(simpB.residuals) if simpB is not None else None
    except (AttributeError, TypeError):
        resid_B = None

    # Conservation diagnostics — STRICT enthalpy flux at inlet / outlet.
    # The previous implementation averaged T with a normalised mass-flux
    # weight that divided by a plane-mean ρ·cp (#5 reviewer concern —
    # not equal to ∑ρ·cp·u·A·T when ρ·cp varied along the face). Now we
    # compute the integral directly:
    #   H_in  = ∑_face ρ·cp·|u·n̂|·A · T
    #   H_out = same on the outlet face
    #   Q_fluid = H_in − H_out   (positive = heat given up by the fluid)
    # Enthalpy balance uses module-level _enthalpy_balance_2d; see top of file.

    # Reuse fine-grid enthalpy already computed above in the Richardson block.
    Q_A = Q_A_fine
    Q_B = Q_B_fine
    # except-audit 2026-07-03: narrowed — only a None operand (side not
    # solved) is expected; arithmetic on floats cannot otherwise raise.
    try:
        Q_net = Q_A + Q_B
        energy_rel = abs(Q_net) / (abs(Q_A) + abs(Q_B) + 1e-30)
    except TypeError:
        Q_net = energy_rel = float('nan')

    result = {
        'Ta': Ta, 'Tb': Tb, 'Ts': Ts,
        'ucA': ucA, 'vcA': vcA, 'ucB': ucB, 'vcB': vcB,
        # N5: display-smoothed copies (partial-BC runs only; None ⇒ use raw).
        # Physics consumers ('ucA' etc.) stay raw / mass-conserving.
        'ucA_disp': ucA_disp, 'vcA_disp': vcA_disp,
        'ucB_disp': ucB_disp, 'vcB_disp': vcB_disp,
        'P_fA': P_fA, 'P_fB': P_fB,
        'dP_A': dP_A, 'dP_B': dP_B,
        # ── C8 shooting diagnostics (openspec c8-p-in-shooting) ──────────
        # Realized inlet absolute pressure = P_ref_abs (outlet anchor,
        # ledger C8) + reported dP, vs the specified P_in. Ideal-gas sides
        # only (incompressible P_ref_abs is a frozen inlet value — level
        # inert, metric meaningless → NaN). With shooting OFF this exposes
        # the legacy 1D-seed bias; ON, it certifies the shot landed.
        'P_in_realized_A': (
            float(simpA.P_ref_abs) + float(dP_A)
            if getattr(simpA, 'fluid_type', None) == 'ideal_gas'
            else float('nan')),
        'P_in_shoot_resid_A': (
            (float(simpA.P_ref_abs) + float(dP_A) - float(P_inA_val))
            / float(P_inA_val)
            if getattr(simpA, 'fluid_type', None) == 'ideal_gas'
            else float('nan')),
        'P_in_realized_B': (
            float(simpB.P_ref_abs) + float(dP_B)
            if getattr(simpB, 'fluid_type', None) == 'ideal_gas'
            else float('nan')),
        'P_in_shoot_resid_B': (
            (float(simpB.P_ref_abs) + float(dP_B) - float(P_inB_val))
            / float(P_inB_val)
            if getattr(simpB, 'fluid_type', None) == 'ideal_gas'
            else float('nan')),
        'Q_total': Q_total,
        'mass_flow_A_kg_s_per_m': (
            float(np.sum(mA_rows)) if mA_rows is not None else float('nan')),
        'mass_flow_B_kg_s_per_m': (
            float(np.sum(mB_rows)) if mB_rows is not None else float('nan')),
        'energy_dx': energy_dx, 'energy_dy': energy_dy,
        'warnings_list': warnings_list,
        # ── Convergence verdict — explicit AND over every gate (2026-07-12) ──
        # robustness-hardening (2026-07-03) ANDed SIMPLE with the outer
        # coupling only. Three gaps closed here (mirrors the 3D fix):
        #   (a) the LTNE inner verdict `e_info['converged']` was captured at
        #       the solve_full_domain call and then NEVER READ — a write-only
        #       variable;
        #   (b) a NaN blow-up patched over with inlet T (see _energy_nan_hit)
        #       left `converged` untouched, so a patched non-solution could
        #       report success;
        #   (c) the post-solve compressible envelope verdict was reported on a
        #       separate key but not ANDed into the headline flag.
        # Verdict only — no numeric field is touched.
        'solver_converged': bool(
            coupling_converged                       # outer ΔT+Δρ criterion
            and not simple_warnings                  # every SIMPLE side ok
            and bool(e_info.get('converged', False))  # LTNE inner pass
            and (not _sco2_v1 or energy_rel < 0.05)   # true-h pair balance
            and not _energy_nan_hit                  # no patched-over NaN
            and bool(_env_valid)),                   # envelope gate
        'convergence_detail': {
            'outer_converged': bool(coupling_converged),
            # The ACTUAL outer-iteration count (3D parity). `_last_coup` is the
            # 0-based index the skeleton stopped at, so +1 is the count of passes
            # actually run — NOT the cap. Absent before 2026-07-12, so callers
            # reading `outer_iters` (e.g. the Shanghai 2D gate) silently got -1.
            'outer_iters': int(_last_coup) + 1,
            'outer_hit_cap': bool(not coupling_converged),
            'simple_ok': bool(not simple_warnings),
            'ltne_ok': bool(e_info.get('converged', False)),
            'ltne_iterations': int(e_info.get('iterations', 0)),
            'ltne_residual': float(e_info.get('residual', float('inf'))),
            'enthalpy_balance_ok': bool(not _sco2_v1 or energy_rel < 0.05),
            'energy_nan_hit': bool(_energy_nan_hit),
            'envelope_ok': bool(_env_valid),
        },
        'residuals_A': resid_A, 'residuals_B': resid_B,
        'mass_imbalance_rel_A': float(getattr(
            simpA, 'final_res_mass_global', float('nan'))),
        'mass_imbalance_rel_B': float(getattr(
            simpB, 'final_res_mass_global', float('nan'))),
        # Conservation diagnostics
        'Q_A': Q_A, 'Q_B': Q_B, 'Q_net': Q_net,
        'energy_imbalance_rel': energy_rel,
        # Q-reconciliation diagnostics (Option C, 2026-04-24)
        'Q_enthalpy_A': abs(Q_A_fine) if Q_A_fine == Q_A_fine else float('nan'),
        'Q_enthalpy_B': abs(Q_B_fine) if Q_B_fine == Q_B_fine else float('nan'),
        'Q_solid_richardson': Q_solid_richardson,
        'Q_richardson_warn': bool(richardson_warn),
        # Compressible validity gate (robustness, 2026-06-25)
        'envelope_valid': _env_valid,
        'envelope_reasons': _env_reasons,
        'p_clip_hits': _clip_hits_2d,
    }
    return result
