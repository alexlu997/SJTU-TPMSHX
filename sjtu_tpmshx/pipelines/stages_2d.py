"""pipelines/stages_2d.py — 2D compute stage functions for SJTU-TPMSHX.

The cfg-only stage functions consumed by
controllers.compute_pipeline.Pipeline2D (_parse_inputs_cfg →
_build_fields_cfg → _run_solvers_cfg → _finalize_cfg).  Compute-only
(Qt/matplotlib-free); 2D result rendering lives in
``ui/plot_2d_results.py``.

Moved out of `runs/run_calculation.py` in batch-3 (2026-06-13) — completing
the controllers→runs layer-inversion fix.  This module imports nothing from
`runs/` or `controllers/` (contracts-layer split 2026-07-02: ComputeConfig /
ComputeResult now come from `domain`, so the old pipelines↔controllers cycle
— and the deferred imports that held it shut — is gone).

Originally extracted from main.py (Task B.9). C3 audit (2026-05-28, L-a-1):
scalar UI inputs route through ``ui.window_config.config_from_window`` rather
than direct ``le_*`` widget reads; the window is still required for non-le
state (zone config, _eps_A, extrap reasons, _temp_to_K hook, _DIR_MAP).
"""
import numpy as np
from domain.compute_config import ComputeConfig, bc_to_dict
from domain.compute_result import ComputeResult
from solvers.simple_solver import SIMPLESolver
from solvers.tpms_calc import compute as tpms_compute, geometry as tpms_geometry
from solvers.df_projection import override_simple_K_cF, extract_dP_from_simple
from pipelines._stage_common import (
    validate_domain_dims, surrogate_extrap_reasons, safe_float,
    geometry_props,
)
from logutil import get_logger

# Re-exports — external consumers (controllers/compute_pipeline, tests)
# import these from pipelines.stages_2d; keep every moved name reachable.
from pipelines.solve_2d import (
    _enthalpy_balance_2d, _PipelineWindowShim, _compute_pressure_2d,
    _apply_zone_stats_2d, _compute_Q_richardson, _run_solvers,
)

_log = get_logger(__name__)


# B2 2.1b (2026-06-13): the legacy window entrypoints
# run_calculation_inner / run_calculation_inner_cfg and the
# _parse_inputs window adapter were DELETED — the GUI 2D path now drives
# controllers.compute_pipeline.Pipeline2D (cfg-only stage functions
# below) and copies the ComputeResult back via Main_Menu.write_result.


def _check_zoned_fluid_support(compute_cfg):
    """Guard: the 2D zone property builders (ZoneConfig.compute_properties /
    build_grid_arrays and sigmoid_field.build_continuous_arrays) hardcode AIR
    (they call tpms_calc.compute / air_* with no fluid_type), so a water side
    would silently get air Nu/k — h_v ~280x and K_ff ~25x off (audit:
    zoned-water-side-uses-air-properties). Raise until per-fluid zoned props
    are implemented; the caller's broad except turns this into a clear warning
    and a safe fall-back to the uniform (correctly per-fluid) path. The 3D
    zoned path threads fluid_type_B and is unaffected.
    """
    if not getattr(compute_cfg.zones, 'enabled', False):
        return
    fA = compute_cfg.fluid_A.type
    fB = compute_cfg.fluid_B.type
    if fA != 'air' or fB != 'air':
        raise NotImplementedError(
            f"Zoned 2D compute supports air only (fluid_A={fA!r}, "
            f"fluid_B={fB!r}); the zone property builders would silently use "
            "air properties for a non-air side. Disable zones or run a uniform "
            "(non-zoned) case for water.")


def _parse_inputs_cfg(compute_cfg):
    """Phase 1 (Qt-free): assemble the parsed-config dict from a
    :class:`ComputeConfig`.

    Audit C4 (L-a-2): cfg-only mirror of ``_parse_inputs``. The legacy
    function now wraps this and propagates ``extrap_reasons`` back onto
    ``window._extrap_reasons`` so the UI watermark keeps working.

    Returns the same parsed dict as ``_parse_inputs`` plus an
    ``extrap_reasons`` key (the legacy version mutated this onto the
    window directly; the cfg-pure version returns it instead).
    """
    warnings_list = []
    extrap_reasons = []

    # Block unsupported fluids up-front (2D path currently hardcodes air_*
    # 2026-05-09 (option B) — water + air supported in 2D Compute. sCO2
    # still blocks. Per-side fluid type captured into cfg so _run_solvers
    # picks the right property accessors.
    from solvers.tpms_calc import validate_fluid_type
    fluid_A = compute_cfg.fluid_A.type
    fluid_B = compute_cfg.fluid_B.type
    validate_fluid_type(fluid_A, 'A')
    validate_fluid_type(fluid_B, 'B')

    # Surrogate training-domain guard for the UI Compute path (#10) —
    # previously only the optimizer did this; the Compute tab now also
    # guards a single out-of-window (u, T, L, t) from silent RBF extrap.
    # If ``cfg.extrap.allow`` is set (the checkbox is on, or the env
    # var TPMSHX_ALLOW_EXTRAP=1 fed the dataclass), out-of-window
    # values downgrade to warn and we stash the reasons in the parsed
    # dict so the UI can mark the result + watermark the plots.
    _allow_extrap = bool(compute_cfg.extrap.allow)
    extrap_reasons += surrogate_extrap_reasons(compute_cfg, _allow_extrap)

    # Scalar parameters (already cfg-sourced).
    L = compute_cfg.geometry.L_dom_m
    H = compute_cfg.geometry.H_dom_m
    N_x = compute_cfg.solver.Nx
    N_y = compute_cfg.solver.Ny
    u_A = compute_cfg.fluid_A.u_mps
    u_B = compute_cfg.fluid_B.u_mps
    T_inA = compute_cfg.fluid_A.T_in_K
    T_inB = compute_cfg.fluid_B.T_in_K

    # Optional solid initial temperature — None means legacy seed
    # 0.5*(T_inA+T_inB) inside solve_full_domain. Not a prescribed Ts.
    T_s_init = compute_cfg.solver.T_s_init_K

    # Defensive unit firewall — shared with the 3D parse (_stage_common).
    validate_domain_dims([('L', L), ('H', H)])

    dx = L / N_x
    dy = H / N_y
    cfgA = bc_to_dict(compute_cfg.bc_A, L, H, side='A')
    cfgB = bc_to_dict(compute_cfg.bc_B, L, H, side='A')
    dir_A = cfgA['dir']
    dir_B = cfgB['dir']

    # TPMS geometry derives porosity + hydraulic radius purely from cfg.
    # The legacy version cached this in ``window._eps_A``; we re-derive
    # because tpms_geometry is cheap (closed-form per Cheng 2021).
    tpms_type = compute_cfg.geometry.tpms
    Lcell = compute_cfg.geometry.L_cell_mm
    t_wall = compute_cfg.geometry.t_wall_mm
    k_s = compute_cfg.geometry.k_s_W_mK
    g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
    eps = g['epsilon']
    r_h = g['D_h'] / 2.0

    # ── zone config from cfg.zones (pre-resolved at UI boundary) ──
    zone_config = None
    za = None
    z_axis = 'y'
    try:
        if compute_cfg.zones.enabled:
            _check_zoned_fluid_support(compute_cfg)
            z_axis = compute_cfg.zones.axis
            P_in_val = compute_cfg.fluid_A.P_in_Pa
            if z_axis == 'grid' and compute_cfg.zones.grid is not None:
                grid = compute_cfg.zones.grid
                _x_dec = compute_cfg.zones.pareto_x_decision
                if _x_dec is not None:
                    from solvers.sigmoid_field import (
                        build_continuous_arrays, get_geometry_lut,
                    )
                    _lut = get_geometry_lut(tpms_type)
                    za = build_continuous_arrays(
                        _x_dec, Lcell, t_wall,
                        compute_cfg.zones.pareto_y_trans_inlet,
                        compute_cfg.zones.pareto_y_trans_outlet,
                        N_x, N_y, L, H,
                        tpms_type, k_s,
                        u_A, u_B, T_inA, T_inB, _lut,
                        P_in=P_in_val,  # FIX (2026-06-24 audit): was defaulting to P_atm
                        allow_extrap=_allow_extrap,
                        fluid_type=fluid_A)  # air-only builder; non-air raises
                    _log.info(f"[ZONE] Continuous Sigmoid field ({N_x}x{N_y})")
                else:
                    from solvers.zone_config import ZoneConfig
                    za = ZoneConfig.build_grid_arrays(
                        N_x, N_y, L, H,
                        grid['cells'],
                        grid['tpms_type'], grid['k_s'],
                        u_A, u_B, T_inA, T_inB, P_in_val)
                    _log.info(f"[ZONE] Grid {len(grid['cells'])} cells (discrete)")
                zone_config = 'grid'
            else:
                # 1D zone mode — cfg.zones.config carries the resolved
                # ZoneConfig (pre-built at the UI boundary by
                # _read_zone_input in domain.compute_config).
                if compute_cfg.zones.config is None:
                    warnings_list.append(
                        "Zone enabled in 1D mode but no ZoneConfig "
                        "resolved; falling back to uniform zone.")
                else:
                    zone_config = compute_cfg.zones.config
                    zone_config.compute_properties(
                        u_A=u_A, u_B=u_B, T_inA=T_inA, T_inB=T_inB,
                        P_in=P_in_val)
                    z_dim = H if z_axis == 'y' else L
                    za = zone_config.build_structured_arrays(
                        N_x, N_y, z_dim, axis=z_axis)
                    _log.info(f"[ZONE] {len(zone_config.zones)} zones along "
                              f"{z_axis}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        warnings_list.append(
            f"Zone config error: {e}\nFalling back to uniform zone.")
        zone_config = None
        za = None

    # Smooth zone property arrays at boundaries (skip continuous mode).
    if za is not None and zone_config is not None and za.get('axis') != 'continuous':
        from scipy.ndimage import gaussian_filter
        _sigma = 2.0
        for _key in ('K_ffA_arr', 'K_ffB_arr', 'K_ss_arr',
                     'h_vA_arr', 'h_vB_arr', 'eps_arr'):
            if _key in za:
                za[_key] = gaussian_filter(za[_key], sigma=_sigma)

    return {
        'L': L, 'H': H,
        'N_x': N_x, 'N_y': N_y,
        'dx': dx, 'dy': dy,
        'u_A': u_A, 'u_B': u_B,
        'T_inA': T_inA, 'T_inB': T_inB,
        'T_s_init': T_s_init,
        'cfgA': cfgA, 'cfgB': cfgB,
        'dir_A': dir_A, 'dir_B': dir_B,
        'envelope_mode': getattr(compute_cfg, 'envelope_mode', 'raise'),
        'tpms_type': tpms_type,
        'Lcell': Lcell, 't_wall': t_wall, 'k_s': k_s,
        'eps': eps, 'r_h': r_h,
        'zone_config': zone_config, 'za': za, 'z_axis': z_axis,
        'fluid_A': fluid_A, 'fluid_B': fluid_B,
        'warnings_list': warnings_list,
        'extrap_reasons': extrap_reasons,
        # Stash the strict ComputeConfig so downstream phases
        # (_build_fields / _run_solvers / _store_results) can reach
        # P_inA / P_inB etc. without re-reading ``le_*`` widget.
        'compute_cfg': compute_cfg,
    }


def _build_fields_cfg(cfg, *, live_residuals=None):
    """Phase 2 (Qt-free): construct aligned grid arrays and SIMPLE
    helper closures.

    Audit C4 (L-a-2): renamed from ``_build_fields(window, cfg)``. The
    two window touches were:

    1. ``window._is_x_dir(d)`` — inlined as ``d in (0, 1)`` per the
       original ``Main_Menu._is_x_dir`` body.
    2. ``window._live_residuals`` (UI sparkline buffer) — now passed
       explicitly via the ``live_residuals`` keyword.  Pipeline2D
       leaves it at ``None`` (no UI); the legacy UI adapter
       :func:`_build_fields` extracts it from the window.
    """
    L = cfg['L']; H = cfg['H']
    N_x = cfg['N_x']; N_y = cfg['N_y']
    u_A = cfg['u_A']; u_B = cfg['u_B']
    T_inA = cfg['T_inA']; T_inB = cfg['T_inB']
    cfgA = cfg['cfgA']; cfgB = cfg['cfgB']
    tpms_type = cfg['tpms_type']
    Lcell = cfg['Lcell']; t_wall = cfg['t_wall']; k_s = cfg['k_s']
    eps = cfg['eps']; r_h = cfg['r_h']
    zone_config = cfg['zone_config']; za = cfg['za']

    # ── Step 1: SIMPLE velocity fields on full L × H ──
    def _build_zone_arrays_for_simple(za_dict, N_flow, N_perp, is_x_flow, mu_fluid):
        """Build 1D per-row arrays for SIMPLE from 2D zone arrays.
        SIMPLE's y-axis = flow direction. Need per-row porous params."""
        from solvers import tpms_calc as _tc
        mu_eff = np.empty(N_flow, dtype=np.float64)
        r_h_a  = np.empty(N_flow, dtype=np.float64)
        ln_eps = np.empty(N_flow, dtype=np.float64)
        ln_tL  = np.empty(N_flow, dtype=np.float64)
        ln_XSa = np.empty(N_flow, dtype=np.float64)
        eps_2d = za_dict['eps_arr']
        for j in range(N_flow):
            if is_x_flow:
                # SIMPLE y-axis = real x-axis; average over real y
                e = eps_2d[j, :].mean()
            else:
                # SIMPLE y-axis = real y-axis; average over real x
                e = eps_2d[:, j].mean()
            # Find matching grid cell for representative L/t
            gc = za_dict.get('grid_cells', za_dict.get('zone_params', []))
            if gc:
                # Use the cell that covers this row's midpoint
                frac = (j + 0.5) / N_flow
                matched = None
                for c in gc:
                    if isinstance(c, dict):
                        if is_x_flow:
                            if c.get('x0', c.get('y_frac_start', 0)) <= frac < c.get('x1', c.get('y_frac_end', 1)):
                                matched = c; break
                        else:
                            if c.get('y0', c.get('y_frac_start', 0)) <= frac < c.get('y1', c.get('y_frac_end', 1)):
                                matched = c; break
                if matched:
                    L_mm = matched.get('L', matched.get('L_mm', Lcell))
                    t_mm = matched.get('t', matched.get('t_mm', t_wall))
                else:
                    L_mm, t_mm = Lcell, t_wall
            else:
                L_mm, t_mm = Lcell, t_wall
            g_loc = tpms_geometry(tpms_type, L_mm, t_mm, k_s)
            e_loc = g_loc['epsilon']
            rh_loc = g_loc['D_h'] / 2.0
            mu_eff[j] = mu_fluid / e_loc
            r_h_a[j] = rh_loc
            ln_eps[j] = np.log(e_loc / 2.0)  # single-channel porosity for f-Re
            ln_tL[j] = np.log(t_mm / L_mm)
            X_mm = 2.0 * rh_loc * 1000.0 if tpms_type == 'Diamond' else L_mm
            ln_XSa[j] = np.log(X_mm / (1000.0 * _tc.Sa_mm))
        return {'mu_eff_arr': mu_eff, 'r_h_arr': r_h_a,
                'ln_eps_arr': ln_eps, 'ln_tL_arr': ln_tL, 'ln_XSa_arr': ln_XSa}

    # Build aligned grid arrays for energy solver
    from solvers.simple_solver import _aligned_grid
    _x_breaks = set()
    _y_breaks = set()
    # Fluid B (y-flow): inlet/outlet on x-axis
    _blo = cfgB['in_ctr'] - cfgB['in_w'] / 2
    _bhi = cfgB['in_ctr'] + cfgB['in_w'] / 2
    if _blo > L * 0.001: _x_breaks.add(_blo)
    if _bhi < L * 0.999: _x_breaks.add(_bhi)
    _bolo = cfgB.get('out_ctr', cfgB['in_ctr']) - cfgB.get('out_w', cfgB['in_w']) / 2
    _bohi = cfgB.get('out_ctr', cfgB['in_ctr']) + cfgB.get('out_w', cfgB['in_w']) / 2
    if _bolo > L * 0.001: _x_breaks.add(_bolo)
    if _bohi < L * 0.999: _x_breaks.add(_bohi)
    # Fluid A (x-flow): inlet/outlet on y-axis
    _alo = cfgA['in_ctr'] - cfgA['in_w'] / 2
    _ahi = cfgA['in_ctr'] + cfgA['in_w'] / 2
    if _alo > H * 0.001: _y_breaks.add(_alo)
    if _ahi < H * 0.999: _y_breaks.add(_ahi)
    _aolo = cfgA.get('out_ctr', cfgA['in_ctr']) - cfgA.get('out_w', cfgA['in_w']) / 2
    _aohi = cfgA.get('out_ctr', cfgA['in_ctr']) + cfgA.get('out_w', cfgA['in_w']) / 2
    if _aolo > H * 0.001: _y_breaks.add(_aolo)
    if _aohi < H * 0.999: _y_breaks.add(_aohi)

    # Use 4-wall Brinkman-BL refined grid when inlet/outlet are full-width (no
    # break points). Otherwise, fall back to aligned uniform grid since
    # refinement would conflict with inlet/outlet boundary alignment.
    _wall_refine_gui = (
        len(_x_breaks) == 0 and len(_y_breaks) == 0
        and zone_config is None and za is None
    )
    if _wall_refine_gui:
        from solvers.df_projection import build_master_refined_grid
        try:
            energy_dx, energy_dy, N_x, N_y = build_master_refined_grid(
                L, H, N_x, N_y, n_refine=8, first_cell=0.02e-3, growth=1.8)
            _log.info(f"[run_calculation] Wall-refined grid: {N_x}×{N_y} cells (4-wall BL resolved)")
        except ValueError:
            energy_dx = _aligned_grid(N_x, L, list(_x_breaks))
            energy_dy = _aligned_grid(N_y, H, list(_y_breaks))
    else:
        energy_dx = _aligned_grid(N_x, L, list(_x_breaks))
        energy_dy = _aligned_grid(N_y, H, list(_y_breaks))

    # From this point onward the 2D compute path must use the effective grid
    # dimensions implied by energy_dx/energy_dy, not the raw UI values.  The
    # refined-grid path can expand e.g. user Nx=20 to actual Nx=23; keeping the
    # old cfg dimensions made Ta/rho/P fields broadcast as (20, 4) vs (23, 4).
    N_x = int(len(energy_dx))
    N_y = int(len(energy_dy))
    cfg['N_x'] = N_x
    cfg['N_y'] = N_y

    def _resize_zone_arrays_to_effective_grid(za_dict, shape):
        if za_dict is None:
            return

        def _nearest(arr):
            sx, sy = arr.shape
            ix = np.clip(((np.arange(shape[0]) + 0.5) * sx / shape[0]).astype(int),
                         0, sx - 1)
            iy = np.clip(((np.arange(shape[1]) + 0.5) * sy / shape[1]).astype(int),
                         0, sy - 1)
            return arr[np.ix_(ix, iy)]

        def _linear(arr):
            sx, sy = arr.shape
            x_old = (np.arange(sx) + 0.5) / sx
            y_old = (np.arange(sy) + 0.5) / sy
            x_new = (np.arange(shape[0]) + 0.5) / shape[0]
            y_new = (np.arange(shape[1]) + 0.5) / shape[1]
            tmp = np.empty((shape[0], sy), dtype=np.float64)
            for j in range(sy):
                tmp[:, j] = np.interp(x_new, x_old, arr[:, j])
            out = np.empty(shape, dtype=np.float64)
            for i in range(shape[0]):
                out[i, :] = np.interp(y_new, y_old, tmp[i, :])
            return out

        for key, value in list(za_dict.items()):
            arr = np.asarray(value)
            if arr.ndim != 2 or arr.shape == shape:
                continue
            if arr.shape[0] == 0 or arr.shape[1] == 0:
                continue
            if key == 'zone_id' or not np.issubdtype(arr.dtype, np.floating):
                za_dict[key] = _nearest(arr)
            else:
                za_dict[key] = _linear(arr.astype(np.float64, copy=False))

        if 'eps_arr' in za_dict:
            za_dict['eps_f_arr'] = np.asarray(za_dict['eps_arr'],
                                              dtype=np.float64) / 2.0

    _resize_zone_arrays_to_effective_grid(za, (N_x, N_y))

    # Build the _run_simple closure here so it captures all needed locals.
    # It is returned in fields and called by Phase 3.
    simple_warnings = {}

    def _run_simple(cfg_fluid, rho_f, mu_f, T_in_f, u_f, label, P_in_abs=101325.0,
                    T_field_real=None, fluid_type='ideal_gas', cf_scale=1.0):
        """Build + solve SIMPLE for one fluid.

        T_field_real : optional 2D array (Nx, Ny) of cell-centered T. When
        supplied (after first outer iter, from LTNE Ta/Tb), propagated to
        SIMPLE.T_field via update_T_field so inner _update_density() uses
        local T (not stale scalar T_in_f). Required for compressible coupling
        consistency across outer iters.

        fluid_type : 'ideal_gas' (default, air) or 'incompressible' (water).
        Controls whether SIMPLE's _update_density runs ρ = P / (R·T) per
        iter or treats ρ as fixed (water). Option B 2026-05-09.
        """
        d = cfg_fluid['dir']
        is_x = d in (0, 1)  # x-flow = dirs {+x, -x}
        pipe_lo = cfg_fluid['in_ctr'] - cfg_fluid['in_w'] / 2
        pipe_hi = cfg_fluid['in_ctr'] + cfg_fluid['in_w'] / 2
        out_lo = cfg_fluid.get('out_ctr', cfg_fluid['in_ctr']) - cfg_fluid.get('out_w', cfg_fluid['in_w']) / 2
        out_hi = cfg_fluid.get('out_ctr', cfg_fluid['in_ctr']) + cfg_fluid.get('out_w', cfg_fluid['in_w']) / 2

        # Build zone arrays for SIMPLE if zones are active
        z_arr = None
        from solvers.zone_config import ZoneConfig
        if za is not None:
            if is_x:
                z_arr = _build_zone_arrays_for_simple(za, N_x, N_y, True, mu_f)
            else:
                z_arr = _build_zone_arrays_for_simple(za, N_y, N_x, False, mu_f)

        zc_simple = zone_config if (not is_x and isinstance(zone_config, ZoneConfig)) else None

        # Transform rho_f / mu_f (either or both may be 2D) to SIMPLE coords.
        def _to_simple_coords(fld):
            if np.ndim(fld) != 2:
                return fld
            if is_x:
                out = fld.T.copy()
                if d == 1:
                    out = out[:, ::-1].copy()
            else:
                out = fld.copy()
                if d == 3:
                    out = out[:, ::-1].copy()
            return out
        rho_simple = _to_simple_coords(rho_f)
        mu_simple = _to_simple_coords(mu_f)

        # Mass-flux inlet reference density ρ(T_in, P_in): the physical inlet
        # density the pipeline used to convert ṁ → u_f. Passed explicitly so the
        # pin holds the PHYSICAL throughput even though this pipeline recreates
        # the solver every outer iter with an already-compressed rho_f (a
        # field-based capture would ratchet here). Ideal gas only — water is
        # incompressible (SIMPLE._update_density is a no-op → massflux inert).
        rho_inlet_ref = (float(P_in_abs) / (287.05 * float(T_in_f))
                         if fluid_type == 'ideal_gas' else None)

        if is_x:
            s = SIMPLESolver(H, L, N_y, N_x, tpms_type, Lcell, t_wall,
                             eps, r_h, rho_simple, mu_simple, T_in_f,
                             pipe_lo, pipe_hi, u_f,
                             outlet_lo=out_lo, outlet_hi=out_hi,
                             zone_arrays=z_arr,
                             wall_refine=False,
                             P_ref_abs=P_in_abs,
                             rho_inlet_ref=rho_inlet_ref,
                             fluid_type=fluid_type,
                             cf_scale=cf_scale)
            # Override grid to match energy solver (SIMPLE x = real y)
            s.dx_arr = energy_dy.copy()
            s.dy_arr = energy_dx.copy()
        else:
            s = SIMPLESolver(L, H, N_x, N_y, tpms_type, Lcell, t_wall,
                             eps, r_h, rho_simple, mu_simple, T_in_f,
                             pipe_lo, pipe_hi, u_f,
                             outlet_lo=out_lo, outlet_hi=out_hi,
                             zone_config=zc_simple,
                             zone_arrays=z_arr if zc_simple is None else None,
                             wall_refine=False,
                             P_ref_abs=P_in_abs,
                             rho_inlet_ref=rho_inlet_ref,
                             fluid_type=fluid_type,
                             cf_scale=cf_scale)
            # Override grid to match energy solver (SIMPLE x = real x)
            s.dx_arr = energy_dx.copy()
            s.dy_arr = energy_dy.copy()
        # 2026-05-07: SIMPLESolver.__init__ silently expands the grid via
        # `_aligned_grid` when `min(2, ...)` per-segment forces total > Nx
        # (case: B partial inlet/outlet on x-axis with 4 break points).
        # The override above swaps in the energy-solver's dx_arr (which
        # is already length Nx), but `inlet_frac` / `outlet_frac` were
        # computed from the longer aligned grid and now disagree with
        # `s.Nx`. Rebuild them from the canonical dx_arr.
        if len(s.dx_arr) != len(s.inlet_frac):
            x_lo_e = np.concatenate(([0.0], np.cumsum(s.dx_arr[:-1])))
            x_hi_e = np.cumsum(s.dx_arr)
            s.inlet_frac = np.clip(
                (np.minimum(x_hi_e, pipe_hi) - np.maximum(x_lo_e, pipe_lo))
                / s.dx_arr, 0.0, 1.0)
            s.inlet_mask = s.inlet_frac > 0.01
            s.outlet_frac = np.clip(
                (np.minimum(x_hi_e, out_hi) - np.maximum(x_lo_e, out_lo))
                / s.dx_arr, 0.0, 1.0)
            s.outlet_mask = s.outlet_frac > 0.01
        # Zoned ε push (#2 fix): if zone config gives spatial eps_arr, push to
        # SIMPLE so its continuity uses ∇·(ε·ρ·u)=0 instead of ∇·(ρ·u)=0.
        # Uniform ε leaves default (eps_field=eps everywhere) unchanged.
        if za is not None and za.get('eps_arr') is not None:
            eps_real = np.asarray(za['eps_arr'], dtype=np.float64)
            eps_sol = _to_simple_coords(eps_real)
            if eps_sol.shape == s.eps_field.shape:
                s.eps_field = np.ascontiguousarray(eps_sol, dtype=np.float64)
        # ── Design-specific K/c_F override (2026-04-17) ──
        # zone_config path above already populates per-row K/c_F via
        # predict_K_cF_vec inside SIMPLE.__init__. But zone_arrays path and
        # sigmoid-continuous za don't — SIMPLE falls back to uniform (L0, t0).
        # Here we project the actual design geometry onto SIMPLE's streamwise
        # axis and overwrite _K_arr/_cF_arr so dP reflects the heterogeneous
        # design. See vault/reports/2026-04-17-shanghai-dP-error-analysis-CN.md §11.
        if za is not None and zc_simple is None:
            Ny_sim = s._K_arr.shape[0]
            fluid = 'A' if is_x else 'B'
            if 'L_field' in za and 't_field' in za:
                override_simple_K_cF(s, tpms_type, k_s, Ny_sim,
                                     None, za['L_field'], za['t_field'], fluid)
            elif za.get('grid_cells'):
                override_simple_K_cF(s, tpms_type, k_s, Ny_sim,
                                     za['grid_cells'], None, None, fluid)
        _has_partial = np.any(s.outlet_frac < 0.99) and np.any(s.outlet_frac > 0.5)
        _tol = 5e-4 if _has_partial else 1e-5
        # Propagate Ta/Tb to SIMPLE.T_field if available (compressible coupling
        # fix; without this _update_density uses stale scalar T_in inside SIMPLE)
        if T_field_real is not None:
            T_simple = _to_simple_coords(T_field_real)
            if T_simple.shape == s.T_field.shape:
                s.update_T_field(np.ascontiguousarray(T_simple))
        # Live residual hook — push (iter, residual) onto the shared
        # buffer (captured from the enclosing _build_fields_cfg
        # ``live_residuals`` parameter) so the UI sparkline can render
        # during the solve instead of only after it returns. ``None``
        # disables the hook for headless pipeline runs.
        _buf = live_residuals
        _side = 'A' if 'A' in label else 'B'
        def _progress_cb(it, res, _s=_side):
            if _buf is None:
                return
            _buf.setdefault(_s, []).append((int(it), float(res)))
        # 2026-05-07: 2D SIMPLE max_iter 5000 → 10000. Crossflow with
        # partial-B inlet (e.g. user's pipeB w=0.068m of L=0.182) +
        # high-u Forchheimer-branch needs more iters to drive residual
        # below tol. 5000 left B at res~3e-3 with target 1e-3.
        conv, n_it = s.solve(max_iter=10000, tol=_tol, verbose=False,
                               progress_cb=_progress_cb)
        if not conv:
            simple_warnings[label] = (
                f"SIMPLE ({label}): not converged after {n_it} iters "
                f"(res={s.residuals[-1]:.2e})")

        # Extract cell-centre velocities (wall-masked for energy solver)
        u_m, v_m = s.get_wall_masked_velocity()
        main_cc = 0.5 * (v_m[:, :-1] + v_m[:, 1:])    # main flow (v in SIMPLE)
        cross_cc = 0.5 * (u_m[:-1, :] + u_m[1:, :])   # cross flow (u in SIMPLE)
        if is_x:
            # SIMPLE (perp=Ny, flow=Nx) → real (Nx, Ny)
            uc_real = main_cc.T     # main flow → x
            vc_real = cross_cc.T    # cross flow → y
            if d == 1:  # -x: flip
                uc_real = -uc_real[::-1, :]
                vc_real = vc_real[::-1, :]
        else:
            vc_real = main_cc       # main flow → y
            uc_real = cross_cc      # cross flow → x
            if d == 3:  # -y: flip
                vc_real = -vc_real[:, ::-1]
                uc_real = uc_real[:, ::-1]

        return uc_real, vc_real, s

    fields = {
        'energy_dx': energy_dx, 'energy_dy': energy_dy,
        '_x_breaks': _x_breaks, '_y_breaks': _y_breaks,
        '_run_simple': _run_simple,
        'simple_warnings': simple_warnings,
    }
    return fields


def _run_solvers_cfg(cfg, fields, *, progress_cb=None, cancel_token=None,
                     ui_hooks=None):
    """Phase 3 (Qt-free): drive ``_run_solvers`` via the
    :class:`_PipelineWindowShim` adapter.

    Audit C4 (L-a-2). ``progress_cb`` is fired indirectly: the shim's
    ``__setattr__`` forwards any ``_compute_progress`` write inside
    the solver loop to ``progress_cb`` as an integer 0–100. The
    enclosing :class:`ComputePipeline.run` adds its own 20 / 90 / 100
    ticks around the three phases.

    ``cancel_token`` is currently passive — ``_run_solvers`` does not
    poll for cancellation inside its inner loops. The Pipeline ABC
    checks the token between phases, so worst case the user waits one
    full solver pass.  C5+ may push cancel polling inward.

    ``ui_hooks`` (B2 2.1a): optional dict; ``'iter_label_cb'`` receives
    the shim-captured ``_iter_label_now`` strings ("iter k/N").
    """
    compute_cfg = cfg['compute_cfg']
    _hooks = ui_hooks or {}
    shim = _PipelineWindowShim(compute_cfg, progress_cb=progress_cb,
                               iter_label_cb=_hooks.get('iter_label_cb'))
    result = _run_solvers(shim, cfg, fields)
    # Forward shim-captured state into the result dict so Pipeline2D's
    # finalize step can promote it into ComputeResult slots.
    result['_shim_zone_axis_dir'] = shim._zone_axis_dir
    result['_shim_zone_stats'] = shim._zone_stats
    result['_shim_zone_boundaries'] = shim._zone_boundaries
    result['_shim_zone_boundaries_x'] = shim._zone_boundaries_x
    result['_shim_zone_boundaries_y'] = shim._zone_boundaries_y
    # Fluid + solid properties — needed by ComputeResult.props.
    result['_shim_rho_A'] = shim._rho_A
    result['_shim_rho_B'] = shim._rho_B
    result['_shim_mu_A'] = shim._mu_A
    result['_shim_mu_B'] = shim._mu_B
    result['_shim_K_ffA'] = shim._K_ffA
    result['_shim_K_ffB'] = shim._K_ffB
    result['_shim_K_ss'] = shim._K_ss
    result['_shim_h_vA'] = shim._h_vA
    result['_shim_h_vB'] = shim._h_vB
    return result


def _finalize_cfg(raw, fields):
    """Phase 4 (Qt-free): assemble a :class:`ComputeResult` from the
    raw ``_run_solvers_cfg`` output and the original ``fields`` dict.

    Audit C4 (L-a-2): no window writes; everything moves through the
    returned :class:`domain.compute_result.ComputeResult`.
    Legacy ``_store_results(window, cfg, result)`` becomes a thin
    adapter that copies the result's slots into the UI attributes
    that ``finalize_plots`` already reads from ``window``.

    The ``fields`` dict still holds the parsed-input cfg dict under
    key ``compute_cfg`` (the original :class:`ComputeConfig`) plus
    ``N_x`` / ``N_y`` / ``L`` / ``H`` / ``dir_A`` / ``dir_B`` /
    ``zone_config`` / ``za`` — the same keys ``_store_results`` read
    from the parsed-cfg dict.
    """
    Ta, Tb, Ts = raw['Ta'], raw['Tb'], raw['Ts']
    ucA, vcA = raw['ucA'], raw['vcA']
    ucB, vcB = raw['ucB'], raw['vcB']

    # Mass-weighted outlet T per side using the same enthalpy balance
    # _run_solvers used for Q_A_fine / Q_B_fine; that gives the same
    # T_out a downstream finalize_plots would compute by hand.
    compute_cfg = fields['compute_cfg']

    def _outlet_T(T_field, uc_field, vc_field, dir_code, fluid_type,
                  T_in_K, P_in_Pa):
        # B1 1.1: param renamed from `fluid_props` — it shadowed the
        # solvers.fluid_props module this function now dispatches through.
        from solvers import fluid_props as _fluids
        # Same convention as ``_enthalpy_balance_2d`` outlet plane.
        if dir_code in (0, 1):
            j_out = -1 if dir_code == 0 else 0
            u_face = uc_field[j_out, :]
            T_face = T_field[j_out, :]
            dA = raw['energy_dy']
        else:
            i_out = -1 if dir_code == 2 else 0
            u_face = vc_field[:, i_out]
            T_face = T_field[:, i_out]
            dA = raw['energy_dx']
        # ρ·cp weighting — registry primitives (water rho ignores P).
        _m = _fluids.get(fluid_type)
        rho = _m.rho(T_face, P_in_Pa)
        cp = _m.cp(T_face, P_in_Pa)
        import numpy as _np
        w = _np.asarray(rho) * _np.asarray(cp) * _np.abs(u_face) * dA
        wsum = float(_np.sum(w))
        if wsum < 1e-30:
            return float(_np.mean(T_face))
        return float(_np.sum(w * T_face) / wsum)

    T_out_A = _outlet_T(Ta, ucA, vcA, fields['dir_A'],
                        compute_cfg.fluid_A.type,
                        compute_cfg.fluid_A.T_in_K,
                        compute_cfg.fluid_A.P_in_Pa)
    T_out_B = _outlet_T(Tb, ucB, vcB, fields['dir_B'],
                        compute_cfg.fluid_B.type,
                        compute_cfg.fluid_B.T_in_K,
                        compute_cfg.fluid_B.P_in_Pa)

    # Zone slot — None when zones disabled.
    zones_slot = None
    if (raw.get('_shim_zone_axis_dir') is not None
            or raw.get('_shim_zone_stats') is not None):
        zones_slot = {
            'axis_dir': raw.get('_shim_zone_axis_dir'),
            'stats': raw.get('_shim_zone_stats'),
            'boundaries': raw.get('_shim_zone_boundaries'),
            'boundaries_x': raw.get('_shim_zone_boundaries_x'),
            'boundaries_y': raw.get('_shim_zone_boundaries_y'),
        }

    # TPMS geometry derived from cfg (eps + D_h + A_0) for props slot.
    eps_geom, D_h_m, A_0_m2 = geometry_props(compute_cfg)

    return ComputeResult(
        Q_W=safe_float(raw['Q_total']),
        dP_A_Pa=safe_float(raw['dP_A']),
        dP_B_Pa=safe_float(raw['dP_B']),
        T_out_A_K=T_out_A,
        T_out_B_K=T_out_B,
        fields={
            'Ta': Ta, 'Tb': Tb, 'Ts': Ts,
            'ucA': ucA, 'vcA': vcA, 'ucB': ucB, 'vcB': vcB,
            'P_fA': raw['P_fA'], 'P_fB': raw['P_fB'],
            'dx_arr': raw['energy_dx'], 'dy_arr': raw['energy_dy'],
            'N_x': fields['N_x'], 'N_y': fields['N_y'],
            'L': fields['L'], 'H': fields['H'],
            'dir_A': fields['dir_A'], 'dir_B': fields['dir_B'],
            'zone_config': fields['zone_config'],
            'za': fields['za'],
        },
        coeffs={
            'K_ffA': raw.get('_shim_K_ffA'),
            'K_ffB': raw.get('_shim_K_ffB'),
            'K_ss': raw.get('_shim_K_ss'),
            'h_vA': raw.get('_shim_h_vA'),
            'h_vB': raw.get('_shim_h_vB'),
        },
        props={
            'rho_A': raw.get('_shim_rho_A'),
            'rho_B': raw.get('_shim_rho_B'),
            'mu_A': raw.get('_shim_mu_A'),
            'mu_B': raw.get('_shim_mu_B'),
            'eps_A': eps_geom,
            'D_h_m': D_h_m,
            'A_0_m2': A_0_m2,
        },
        residuals={
            'r_dP_A': float('nan'),  # _run_solvers does not surface
            'r_dP_B': float('nan'),
            'r_Q': 1.0 if raw.get('Q_richardson_warn') else 0.0,
            'simple_A': raw.get('residuals_A'),
            'simple_B': raw.get('residuals_B'),
            'Q_A': float(raw.get('Q_A', float('nan'))),
            'Q_B': float(raw.get('Q_B', float('nan'))),
            'Q_net': float(raw.get('Q_net', float('nan'))),
            'energy_imbalance_rel': float(
                raw.get('energy_imbalance_rel', float('nan'))),
        },
        zones=zones_slot,
        warnings=list(raw.get('warnings_list', [])),
        extrap_reasons=list(fields.get('extrap_reasons', [])),
        diagnostics={
            # Dimension marker for write_result dispatch (C4).
            'mode': '2d',
            'Q_enthalpy_A': raw.get('Q_enthalpy_A'),
            'Q_enthalpy_B': raw.get('Q_enthalpy_B'),
            'Q_solid_richardson': raw.get('Q_solid_richardson'),
            'Q_richardson_warn': bool(raw.get('Q_richardson_warn', False)),
        },
    )


# B2 2.1b: the _store_results(window, cfg, result) adapter was DELETED —
# Main_Menu.write_result (ui/mixins/run_controller.py) is the single
# ComputeResult→window copy now. Note: the old dict's residuals_A/B
# snapshots are not forwarded (they only fed the removed 2D convergence
# plot; verified no UI consumer).
