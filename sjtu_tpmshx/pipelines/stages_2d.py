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
from solvers.coupling_skeleton import OuterConvergence, run_outer_coupling
from solvers.simple_solver import SIMPLESolver
from solvers.ltne_energy import solve_full_domain
from solvers.tpms_calc import compute as tpms_compute, geometry as tpms_geometry
from solvers.df_projection import override_simple_K_cF, extract_dP_from_simple
from solvers.envelope import gate_solution, mach_field_max
from pipelines._stage_common import (
    validate_domain_dims, surrogate_extrap_reasons, safe_float,
    geometry_props,
)


def _enthalpy_balance_2d(T_field, uc, vc, rho_cp_field, dir_code,
                          dx_arr, dy_arr, inlet_mask=None, outlet_mask=None,
                          enthalpy_fn=None, rho_fn=None, P_ref=None):
    """Mass-conserving enthalpy balance Q = ṁ_in · (T_in_avg − T_out_avg).

    Uses the inlet plane ρ·|u|·A·mask as ṁ·cp reference so the returned Q
    is robust to partial SIMPLE mass-conservation convergence (B-1 refactor
    2026-04-24). The earlier H_in − H_out form gave spurious non-zero Q
    when ṁ_inlet ≠ ṁ_outlet, which in fast-mode NSGA-II inflated Q by 3×.

    Positive = fluid gives up heat (T_in > T_out).
    Optional 1D masks (length = cross-axis) gate the integral to partial
    inlet / outlet pipes; missing masks default to full face.

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

    if enthalpy_fn is not None and rho_fn is not None and P_ref is not None:
        # True-enthalpy duty for strongly variable-cp fluids (sCO2).
        rho_in  = np.asarray(rho_fn(T_in_face,  P_ref), dtype=np.float64)
        rho_out = np.asarray(rho_fn(T_out_face, P_ref), dtype=np.float64)
        w_in  = rho_in  * u_in_face  * A_cell * m_in_arr
        w_out = rho_out * u_out_face * A_cell * m_out_arr
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

    m_in_w  = rho_cp_in  * u_in_face  * A_cell * m_in_arr
    m_out_w = rho_cp_out * u_out_face * A_cell * m_out_arr
    m_dot_cp = float(np.sum(m_in_w))
    if m_dot_cp < 1e-30:
        return 0.0
    T_in_avg = float(np.sum(m_in_w * T_in_face)) / m_dot_cp
    m_out_total = float(np.sum(m_out_w))
    T_out_avg = (float(np.sum(m_out_w * T_out_face)) / m_out_total
                 if m_out_total > 1e-30 else float(np.mean(T_out_face)))
    return m_dot_cp * (T_in_avg - T_out_avg)


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
                    print(f"[ZONE] Continuous Sigmoid field ({N_x}x{N_y})")
                else:
                    from solvers.zone_config import ZoneConfig
                    za = ZoneConfig.build_grid_arrays(
                        N_x, N_y, L, H,
                        grid['cells'],
                        grid['tpms_type'], grid['k_s'],
                        u_A, u_B, T_inA, T_inB, P_in_val)
                    print(f"[ZONE] Grid {len(grid['cells'])} cells (discrete)")
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
                    print(f"[ZONE] {len(zone_config.zones)} zones along "
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
            print(f"[run_calculation] Wall-refined grid: {N_x}×{N_y} cells (4-wall BL resolved)")
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
        from solvers import tpms_calc as _tc
        from solvers.tpms_calc import geometry as _tpms_geom
        from domain.validator import compute_volumetric_htc

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
    def _pipe_weighted(P_row, w):
        s = float(w.sum())
        return float((P_row * w).sum() / s) if s > 1e-12 else float(P_row.mean())

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
            from solvers.zone_config import Zone
            dummy_zones = [Zone(f'g{r}', gc['y0'], gc['y1'], gc['L'], gc['t'])
                           for r, gc in enumerate(za.get('grid_cells', []))]
            from solvers.zone_config import compute_zone_statistics, format_zone_report
            _ca = energy_dx[:, None] * energy_dy[None, :]
            stats = compute_zone_statistics(Ta, Tb, Ts, za['zone_id'], dummy_zones,
                                            cell_area=_ca)
            print("\n[ZONE STATISTICS]")
            print(format_zone_report(stats))
            window._zone_stats = stats
        else:
            # 1D mode
            from solvers.zone_config import compute_zone_statistics, format_zone_report
            _ca = energy_dx[:, None] * energy_dy[None, :]
            stats = compute_zone_statistics(Ta, Tb, Ts, za['zone_id'],
                                            zone_config.zones, cell_area=_ca)
            print("\n[ZONE STATISTICS]")
            print(format_zone_report(stats))
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
    from solvers.simple_solver import _aligned_grid
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

    try:
        Q_A_fine = _enthalpy_balance_2d(
            Ta, ucA, vcA, rho_cp_A_fld, dir_A, energy_dx, energy_dy,
            inlet_mask=mA_in, outlet_mask=mA_out,
            enthalpy_fn=_enth_A, rho_fn=_pA['rho'], P_ref=P_inA_val)
        Q_B_fine = _enthalpy_balance_2d(
            Tb, ucB, vcB, rho_cp_B_fld, dir_B, energy_dx, energy_dy,
            inlet_mask=mB_in, outlet_mask=mB_out,
            enthalpy_fn=_enth_B, rho_fn=_pB['rho'], P_ref=P_inB_val)
        Q_A_coarse = _enthalpy_balance_2d(
            Ta2, ucA2, vcA2, rcp_A2, dir_A, energy_dx2, energy_dy2,
            inlet_mask=mA_in2, outlet_mask=mA_out2,
            enthalpy_fn=_enth_A, rho_fn=_pA['rho'], P_ref=P_inA_val)
        Q_B_coarse = _enthalpy_balance_2d(
            Tb2, ucB2, vcB2, rcp_B2, dir_B, energy_dx2, energy_dy2,
            inlet_mask=mB_in2, outlet_mask=mB_out2,
            enthalpy_fn=_enth_B, rho_fn=_pB['rho'], P_ref=P_inB_val)
        # Per-side duty weighting (offset-isosurface δ): weight each side's mass
        # flux by its void fraction relative to the symmetric ε/2 (factor 1.0 at
        # δ=0 → bit-identical). A signed scale preserves the gives-up/absorbs
        # sign; the |·| below takes magnitude. Keeps ṁ_A/ṁ_B physical and the
        # AB balance closed on the split geometry (kernel already uses ε_A/ε_B).
        if _asymQ:
            Q_A_fine *= _fAQ; Q_A_coarse *= _fAQ
            Q_B_fine *= _fBQ; Q_B_coarse *= _fBQ
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
        print(f"[Q-calc] Richardson try-block raised {_q_exc!r} — "
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
            # Per-side void weighting (offset-isosurface δ; 1.0 at δ=0).
            if _asymQ:
                m_dot_A *= _fAQ
                m_dot_B *= _fBQ
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
            print(f"[Q-calc] 1D fallback: Q_A={Q_A_simple:.1f}, "
                  f"Q_B={Q_B_simple:.1f}, Q_total={Q_total:.1f} W/m  "
                  f"(T_out_A_mean={T_out_A_mean:.2f}K, "
                  f"T_out_B_mean={T_out_B_mean:.2f}K)")
        except Exception as _fb_exc:
            import traceback as _tb2
            _tb2.print_exc()
            print(f"[Q-calc] 1D fallback also raised {_fb_exc!r} — "
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
    from solvers import tpms_calc as _tc
    from solvers import fluid_props
    from solvers.simple_solver import _aligned_grid

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

    # Local-Re Nu rescale (2D #1 fix 2026-04-25): per-cell h_v using local
    # |u_cc|·D_h·ρ/μ Reynolds. Wall cells with u→0 fall to the laminar
    # Hagen-Poiseuille floor (prevents Nu→0 non-physical extrapolation).
    from solvers.nu_correlations import NU_LAM_FLOOR as _NU_LAM_FLOOR_2D

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
            out = np.empty((Nx_l, Ny_l), dtype=np.float64)
            for i in range(Nx_l):
                for j in range(Ny_l):
                    Re_ij = max(float(Re_loc[i, j]), 1.0)
                    if side_props is not None:
                        nu_corr = _nu_dispatch(side_props, side_T_for_Pr,
                                                Re_ij, eps_g / 2.0, Lcell,
                                                D_h * 1000.0, side_P)
                    else:
                        nu_corr = _tc.nu_from_Re(tpms_type, Re_ij,
                                                  eps_g / 2.0, Lcell,
                                                  D_h * 1000.0)
                    Nu_l = max(nu_corr, _NU_LAM_FLOOR_2D)
                    out[i, j] = A0 * Nu_l * k_f_scalar / D_h
            return out
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

    rho_A, rho_B = window._rho_A, window._rho_B
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
    from solvers.asym_split import _asym_split_A as _asym_split_A_2d
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
        from solvers.tpms_geometry import _phi_grid, _C_from_tL
        from solvers import asym_geometry as _ag
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
    # Warm-start delta tracker (shared with the 3D driver) — dual ΔTa/ΔTb < tol
    # AND mass-flux-weighted Δρ < tol; owns the prev-copy bookkeeping.
    _outer_conv = OuterConvergence(tol_T=_DT_TOL_K, track=('Ta', 'Tb'))
    e_info = {'converged': False, 'iterations': 0, 'residual': float('inf')}
    Ta = Tb = Ts = None
    # User-provided solid warm-start seed. Empty → solver fallback
    # (per-fluid inlet T for Ta/Tb, 0.5*(T_inA+T_inB) for Ts).
    # Filled → only Ts is overridden with the user value; Ta/Tb stay at
    # the per-fluid inlet T to avoid the 0.5-mean energy-balance leak
    # documented in ltne_energy_3d.py:1442-44 (mid-T value at non-pipe
    # inlet cells diffuses back as a virtual heat source, ~20–25% on
    # partial-inlet geometries). Ts is *not* prescribed; the solid
    # energy equation still updates it every sweep.
    _Ts_init_user = cfg.get('T_s_init')
    if _Ts_init_user is not None:
        Ta = np.full((N_x, N_y), float(T_inA), dtype=np.float64)
        Tb = np.full((N_x, N_y), float(T_inB), dtype=np.float64)
        Ts = np.full((N_x, N_y), float(_Ts_init_user), dtype=np.float64)
    _has_partial_A = False
    _has_partial_B = False
    ucA = vcA = ucB = vcB = None
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
            # sCO2 Forchheimer cF needs the D-7-6 effective scale (air/water=1.0,
            # bit-identical). Diamond-only, like nu_sco2_topo.
            from df_surrogate.predict import SCO2_CF_SCALE
            _cfsA = SCO2_CF_SCALE if _pA['name'] == 'sco2' else 1.0
            _cfsB = SCO2_CF_SCALE if _pB['name'] == 'sco2' else 1.0
            ucA, vcA, simpA = _run_simple(cfgA, rho_A_field, mu_A, T_inA, u_A,
                                            'Fluid A', P_inA_val,
                                            T_field_real=_Ta_for_simpA,
                                            fluid_type=_ftA, cf_scale=_cfsA)
            ucB, vcB, simpB = _run_simple(cfgB, rho_B_field, mu_B, T_inB, u_B,
                                            'Fluid B', P_inB_val,
                                            T_field_real=_Tb_for_simpB,
                                            fluid_type=_ftB, cf_scale=_cfsB)
        if _coup_it == 0:
            for w in _caught:
                warnings_list.append(str(w.message))

        window._compute_progress = 10 + int(80 * (_coup_it + 0.3) / _MAX_COUPLING)

        # Smooth velocity near partial-width wall boundaries
        _has_partial_A = np.any(simpA.outlet_frac < 0.99) or np.any(simpA.inlet_frac < 0.99)
        _has_partial_B = np.any(simpB.outlet_frac < 0.99) or np.any(simpB.inlet_frac < 0.99)
        if _has_partial_A or _has_partial_B:
            from scipy.ndimage import gaussian_filter
            _sv = 2.0
            if _has_partial_A:
                ucA = gaussian_filter(ucA, sigma=_sv)
                vcA = gaussian_filter(vcA, sigma=_sv)
            if _has_partial_B:
                ucB = gaussian_filter(ucB, sigma=_sv)
                vcB = gaussian_filter(vcB, sigma=_sv)

        # Inlet fractions for energy solver (continuous blending at wall/open edge)
        _imA = simpA.inlet_frac.astype(np.float64)  # 1D float, length = SIMPLE Nx for A
        _imB = simpB.inlet_frac.astype(np.float64)  # 1D float, length = SIMPLE Nx for B

        # Build local-Re per-cell h_v fields (#1 fix). Use cell-center magnitude.
        u_mag_A = np.sqrt(ucA**2 + vcA**2)
        u_mag_B = np.sqrt(ucB**2 + vcB**2)
        rho_A_scalar = float(rho_A_field.mean())
        rho_B_scalar = float(rho_B_field.mean())
        mu_A_scalar = float(np.asarray(mu_A).mean()) if np.ndim(mu_A) else float(mu_A)
        mu_B_scalar = float(np.asarray(mu_B).mean()) if np.ndim(mu_B) else float(mu_B)
        k_fA = float(_pA['k'](T_inA, P_inA_val))
        k_fB = float(_pB['k'](T_inB, P_inB_val))
        # Zoned L/t fields (only if zone_config and grid mode); otherwise None
        L_field_2d = None; t_field_2d = None
        if zone_config is not None and za is not None:
            L_field_2d = za.get('L_mm_arr')
            t_field_2d = za.get('t_arr')
        h_vA_local = _build_hv_local_2d(rho_A_scalar, mu_A_scalar, k_fA,
                                         u_mag_A, L_field_2d, t_field_2d,
                                         side_props=_pA, side_T_for_Pr=T_inA,
                                         side_P=P_inA_val)
        h_vB_local = _build_hv_local_2d(rho_B_scalar, mu_B_scalar, k_fB,
                                         u_mag_B, L_field_2d, t_field_2d,
                                         side_props=_pB, side_T_for_Pr=T_inB,
                                         side_P=P_inB_val)
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
                f"2D View can render velocity/pressure. "
                f"Q value is unreliable. Cause: {_cause}.")
            Ta = np.where(np.isnan(Ta), T_inA, Ta)
            Tb = np.where(np.isnan(Tb), T_inB, Tb)
            Ts = np.where(np.isnan(Ts), 0.5 * (T_inA + T_inB), Ts)

        # Step 3: Update rho*cp and rho field from per-cell temperature AND
        # per-cell absolute pressure. Using the scalar inlet P here under-
        # predicts density drop across the domain at high dP and diverges
        # from the 3D path (which already uses P_ref_abs + P). Transpose /
        # flip SIMPLE coords → real (Nx, Ny) to match Ta shape.
        def _simp_P_abs_real(simp, dir_code):
            P_loc = simp.P_ref_abs + simp.P  # (simp.Nx, simp.Ny) solver coords
            if window._is_x_dir(dir_code):
                P_real = P_loc.T
                if dir_code == 1:
                    P_real = P_real[::-1, :]
            else:
                P_real = P_loc
                if dir_code == 3:
                    P_real = P_real[:, ::-1]
            return np.ascontiguousarray(P_real)
        P_abs_A = _simp_P_abs_real(simpA, dir_A)
        P_abs_B = _simp_P_abs_real(simpB, dir_B)
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
        # Dual ΔTa/ΔTb (tol _DT_TOL_K) AND mass-flux-weighted Δρ (tol
        # _COUPLING_TOL) — the shared tracker owns the ΔT deltas + warm-start
        # prev-copy; Δρ is the 2D-specific extra criterion.
        _converged, _deltas = _outer_conv.check(
            {'Ta': Ta, 'Tb': Tb},
            extra=(drho_A, drho_B), extra_tol=_COUPLING_TOL)
        dT_A = _deltas['Ta']; dT_B = _deltas['Tb']
        print(f"  [Coupling {_coup_it+1}] drho_A={drho_A:.4f} drho_B={drho_B:.4f} "
              f"dT_A={dT_A:.2f}K dT_B={dT_B:.2f}K "
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
            ma_max=mach_field_max(_vmagA, Ta))
        _env_valid = _env_valid and _vA
        _env_reasons += [f"[A] {r}" for r in _rA]
    if simpB is not None and getattr(simpB, 'fluid_type', None) == 'ideal_gas':
        _clip_hits_2d += int(getattr(simpB, '_p_clip_hits', 0))
        _vmagB = np.sqrt(np.asarray(ucB) ** 2 + np.asarray(vcB) ** 2)
        _vB, _rB = gate_solution(
            float((simpB.P_ref_abs + simpB.P).min()), float(_vmagB.max()),
            float(T_inB), mode=_env_mode, dims='2D-B',
            ma_max=mach_field_max(_vmagB, Tb))
        _env_valid = _env_valid and _vB
        _env_reasons += [f"[B] {r}" for r in _rB]

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
    try:
        resid_A = list(simpA.residuals) if simpA is not None else None
    except Exception:
        resid_A = None
    try:
        resid_B = list(simpB.residuals) if simpB is not None else None
    except Exception:
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
    try:
        Q_net = Q_A + Q_B
        energy_rel = abs(Q_net) / (abs(Q_A) + abs(Q_B) + 1e-30)
    except Exception:
        Q_net = energy_rel = float('nan')

    result = {
        'Ta': Ta, 'Tb': Tb, 'Ts': Ts,
        'ucA': ucA, 'vcA': vcA, 'ucB': ucB, 'vcB': vcB,
        'P_fA': P_fA, 'P_fB': P_fB,
        'dP_A': dP_A, 'dP_B': dP_B,
        'Q_total': Q_total,
        'energy_dx': energy_dx, 'energy_dy': energy_dy,
        'warnings_list': warnings_list,
        'residuals_A': resid_A, 'residuals_B': resid_B,
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
