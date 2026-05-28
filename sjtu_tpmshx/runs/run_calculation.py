"""Main calculation pipeline for SJTU-TPMSHX (non-polygon case).

Extracted from main.py (Task B.9). Entry: run_calculation_inner.
Also contains finalize_plots which renders results on canvas widgets.

C3 refactor (2026-05-28, L-a-1): scalar UI inputs now route through
``controllers.compute_config.ComputeConfig.from_qt_window`` instead of
direct ````le_*`` widget.text()`` reads. The window is still required for
non-le state (zone config, _eps_A, extrap reasons, _temp_to_K hook,
_DIR_MAP, etc.) — C4 task to extract that into a SessionState object.
"""
import numpy as np
import matplotlib.pyplot as plt
from controllers.compute_config import ComputeConfig
from solvers.simple_solver import SIMPLESolver
from solvers.solve_full import solve_full_domain
from solvers.tpms_calc import compute as tpms_compute, geometry as tpms_geometry
from solvers.df_projection import override_simple_K_cF, extract_dP_from_simple


def _enthalpy_balance_2d(T_field, uc, vc, rho_cp_field, dir_code,
                          dx_arr, dy_arr, inlet_mask=None, outlet_mask=None):
    """Mass-conserving enthalpy balance Q = ṁ_in · (T_in_avg − T_out_avg).

    Uses the inlet plane ρ·|u|·A·mask as ṁ·cp reference so the returned Q
    is robust to partial SIMPLE mass-conservation convergence (B-1 refactor
    2026-04-24). The earlier H_in − H_out form gave spurious non-zero Q
    when ṁ_inlet ≠ ṁ_outlet, which in fast-mode NSGA-II inflated Q by 3×.

    Positive = fluid gives up heat (T_in > T_out).
    Optional 1D masks (length = cross-axis) gate the integral to partial
    inlet / outlet pipes; missing masks default to full face.
    """
    if dir_code in (0, 1):
        i_in, i_out = (0, -1) if dir_code == 0 else (-1, 0)
        A_cell = dy_arr
        n_cross = T_field.shape[1]
        m_in_arr  = (np.asarray(inlet_mask,  dtype=np.float64)
                     if inlet_mask  is not None else np.ones(n_cross))
        m_out_arr = (np.asarray(outlet_mask, dtype=np.float64)
                     if outlet_mask is not None else np.ones(n_cross))
        m_in_w  = rho_cp_field[i_in,  :] * np.abs(uc[i_in,  :]) * A_cell * m_in_arr
        m_out_w = rho_cp_field[i_out, :] * np.abs(uc[i_out, :]) * A_cell * m_out_arr
        T_in_face, T_out_face = T_field[i_in, :], T_field[i_out, :]
    else:
        j_in, j_out = (0, -1) if dir_code == 2 else (-1, 0)
        A_cell = dx_arr
        n_cross = T_field.shape[0]
        m_in_arr  = (np.asarray(inlet_mask,  dtype=np.float64)
                     if inlet_mask  is not None else np.ones(n_cross))
        m_out_arr = (np.asarray(outlet_mask, dtype=np.float64)
                     if outlet_mask is not None else np.ones(n_cross))
        m_in_w  = rho_cp_field[:, j_in]  * np.abs(vc[:, j_in])  * A_cell * m_in_arr
        m_out_w = rho_cp_field[:, j_out] * np.abs(vc[:, j_out]) * A_cell * m_out_arr
        T_in_face, T_out_face = T_field[:, j_in], T_field[:, j_out]
    m_dot_cp = float(np.sum(m_in_w))
    if m_dot_cp < 1e-30:
        return 0.0
    T_in_avg = float(np.sum(m_in_w * T_in_face)) / m_dot_cp
    m_out_total = float(np.sum(m_out_w))
    T_out_avg = (float(np.sum(m_out_w * T_out_face)) / m_out_total
                 if m_out_total > 1e-30 else float(np.mean(T_out_face)))
    return m_dot_cp * (T_in_avg - T_out_avg)


def run_calculation_inner(window):
    """Orchestrator: split into 4 phases for readability.

    Backward-compatible adapter — builds a strict-validated
    :class:`ComputeConfig` from the window and delegates to
    :func:`run_calculation_inner_cfg`. Callers that already hold a
    cfg (tests, future C4 Pipeline) can call ``_cfg`` directly.
    """
    compute_cfg = ComputeConfig.from_qt_window(window, strict=True)
    return run_calculation_inner_cfg(compute_cfg, window)


def run_calculation_inner_cfg(compute_cfg, window):
    """Orchestrator with explicit :class:`ComputeConfig` (C3, L-a-1).

    ``window`` is still required for non-le_* state (zone config,
    ``_eps_A``, ``_DIR_MAP``, extrap reasons, K/°C toggle, …); C4 will
    extract that into a ``SessionState`` object so the cfg is the only
    contract.
    """
    cfg = _parse_inputs(window, compute_cfg)
    fields = _build_fields(window, cfg)
    result = _run_solvers(window, cfg, fields)
    _store_results(window, cfg, result)


def _parse_inputs(window, compute_cfg):
    """Phase 1: UI input reading + validation + zone config building.

    ``compute_cfg`` (audit C3) carries every scalar that used to come
    from ````le_*`` widget`` reads. Non-scalar window state (zone config,
    eps_A snapshot, pareto state, extrap reasons) still flows through
    the Qt object.
    """
    warnings_list = []

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
    # If the "Allow surrogate extrapolation" checkbox is on (or env var
    # TPMSHX_ALLOW_EXTRAP=1), out-of-window values downgrade to warn and
    # we stash the reasons on window._extrap_reasons so run_calculation
    # can mark the result + watermark the plots.
    window._extrap_reasons = []
    _allow_extrap = bool(getattr(window, 'chk_allow_extrap', None)
                         and window.chk_allow_extrap.isChecked())
    try:
        from df_fit.surrogate_domain import check_surrogate_domain_at_point
        _tpms = compute_cfg.geometry.tpms
        _L = compute_cfg.geometry.L_cell_mm
        _t = compute_cfg.geometry.t_wall_mm
        _ks = compute_cfg.geometry.k_s_W_mK
        _T_A = compute_cfg.fluid_A.T_in_K
        _T_B = compute_cfg.fluid_B.T_in_K
        _P_A = compute_cfg.fluid_A.P_in_Pa
        _P_B = compute_cfg.fluid_B.P_in_Pa
        _uA = compute_cfg.fluid_A.u_mps
        _uB = compute_cfg.fluid_B.u_mps
        window._extrap_reasons += check_surrogate_domain_at_point(
            _tpms, _L, _t, _ks, _uA, _T_A, _P_A, side='A',
            allow_extrap=_allow_extrap) or []
        window._extrap_reasons += check_surrogate_domain_at_point(
            _tpms, _L, _t, _ks, _uB, _T_B, _P_B, side='B',
            allow_extrap=_allow_extrap) or []
    except (AttributeError, ValueError) as _e:
        if isinstance(_e, ValueError):
            raise

    # Scalar parameters (audit C3 — sourced from ComputeConfig instead of
    # ``float(``le_*`` widget.text())``). Strict validation happened upstream
    # in ``ComputeConfig.from_qt_window(window, strict=True)``.
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
    # Defensive unit firewall — see run_calculation_3d.py:_parse_inputs for
    # rationale (GUI labels L/H in METERS but L_cell/t in MM; mistyping the
    # mm value into the metre field silently spawns a multi-metre domain).
    _DOMAIN_MAX_M = 10.0
    for _name, _val in [('L', L), ('H', H)]:
        if _val > _DOMAIN_MAX_M:
            raise ValueError(
                f"Domain dimension {_name!r}={_val} m exceeds {_DOMAIN_MAX_M} m. "
                f"Likely unit slip — GUI expects meters here, while L_cell "
                f"and t use millimeters. Re-check input.")

    dx = L / N_x;  dy = H / N_y
    try:
        cfgA = window._fluid_config('A')
        cfgB = window._fluid_config('B')
    except ValueError:
        cfgA = dict(dir=0, in_ctr=H/2, in_w=H, out_ctr=H/2, out_w=H)
        cfgB = dict(dir=3, in_ctr=L/2, in_w=L, out_ctr=L/2, out_w=L)
    dir_A = cfgA['dir'];  dir_B = cfgB['dir']

    tpms_type = compute_cfg.geometry.tpms
    Lcell = compute_cfg.geometry.L_cell_mm
    t_wall = compute_cfg.geometry.t_wall_mm
    k_s = compute_cfg.geometry.k_s_W_mK
    eps = window._eps_A
    g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
    r_h = g['D_h'] / 2.0

    # ── Build zone config (if enabled) ──
    zone_config = None
    za = None
    z_axis = 'y'  # default; overwritten if zones active
    try:
        zone_config = window._build_zone_config()
        if zone_config is not None:
            z_axis = window._zone_axis()
            P_in_val = compute_cfg.fluid_A.P_in_Pa
            if z_axis == 'grid' and window._zone_grid is not None:
                # 2D grid mode — use Sigmoid continuous field if decision vector available
                _x_dec = getattr(window, '_pareto_x_decision', None)
                if _x_dec is not None:
                    from solvers.sigmoid_field import build_continuous_arrays, get_geometry_lut
                    _lut = get_geometry_lut(tpms_type)
                    _ax_ui = bool(getattr(window, 'chk_allow_extrap', None)
                                  and window.chk_allow_extrap.isChecked())
                    za = build_continuous_arrays(
                        _x_dec, Lcell, t_wall,
                        getattr(window, '_pareto_y_trans_inlet', 0.2),
                        getattr(window, '_pareto_y_trans_outlet', 0.2),
                        N_x, N_y, L, H,
                        tpms_type, k_s,
                        u_A, u_B, T_inA, T_inB, _lut,
                        allow_extrap=_ax_ui)
                    print(f"[ZONE] Continuous Sigmoid field ({N_x}x{N_y})")
                else:
                    from solvers.zone_config import ZoneConfig
                    za = ZoneConfig.build_grid_arrays(
                        N_x, N_y, L, H,
                        window._zone_grid['cells'],
                        window._zone_grid['tpms_type'], window._zone_grid['k_s'],
                        u_A, u_B, T_inA, T_inB, P_in_val)
                    print(f"[ZONE] Grid {len(window._zone_grid['cells'])} cells (discrete)")
                zone_config = 'grid'
            else:
                # 1D mode
                zone_config.compute_properties(
                    u_A=u_A, u_B=u_B, T_inA=T_inA, T_inB=T_inB,
                    P_in=P_in_val)
                z_dim = H if z_axis == 'y' else L
                za = zone_config.build_structured_arrays(
                    N_x, N_y, z_dim, axis=z_axis)
                print(f"[ZONE] {len(zone_config.zones)} zones along {z_axis}")
    except Exception as e:
        import traceback; traceback.print_exc()
        warnings_list.append(f"Zone config error: {e}\nFalling back to uniform zone.")
        zone_config = None

    # Smooth zone property arrays at boundaries (skip for continuous mode)
    if za is not None and zone_config is not None and za.get('axis') != 'continuous':
        from scipy.ndimage import gaussian_filter
        _sigma = 2.0  # smoothing width in cells
        for _key in ('K_ffA_arr', 'K_ffB_arr', 'K_ss_arr',
                     'h_vA_arr', 'h_vB_arr', 'eps_arr'):
            if _key in za:
                za[_key] = gaussian_filter(za[_key], sigma=_sigma)

    cfg = {
        'L': L, 'H': H,
        'N_x': N_x, 'N_y': N_y,
        'dx': dx, 'dy': dy,
        'u_A': u_A, 'u_B': u_B,
        'T_inA': T_inA, 'T_inB': T_inB,
        'T_s_init': T_s_init,
        'cfgA': cfgA, 'cfgB': cfgB,
        'dir_A': dir_A, 'dir_B': dir_B,
        'tpms_type': tpms_type,
        'Lcell': Lcell, 't_wall': t_wall, 'k_s': k_s,
        'eps': eps, 'r_h': r_h,
        'zone_config': zone_config, 'za': za, 'z_axis': z_axis,
        'fluid_A': fluid_A, 'fluid_B': fluid_B,
        'warnings_list': warnings_list,
        # Stash the strict ComputeConfig so downstream phases
        # (_build_fields / _run_solvers / _store_results) can reach
        # P_inA / P_inB etc. without re-reading ``le_*`` widget.
        'compute_cfg': compute_cfg,
    }
    return cfg


def _build_fields(window, cfg):
    """Phase 2: construct aligned grid arrays and SIMPLE helper closures."""
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
                    T_field_real=None, fluid_type='ideal_gas'):
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
        is_x = window._is_x_dir(d)
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

        if is_x:
            s = SIMPLESolver(H, L, N_y, N_x, tpms_type, Lcell, t_wall,
                             eps, r_h, rho_simple, mu_simple, T_in_f,
                             pipe_lo, pipe_hi, u_f,
                             outlet_lo=out_lo, outlet_hi=out_hi,
                             zone_arrays=z_arr,
                             wall_refine=False,
                             P_ref_abs=P_in_abs,
                             fluid_type=fluid_type)
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
                             fluid_type=fluid_type)
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
        # window buffer so the UI sparkline can render during the solve
        # instead of only after it returns.
        _buf = getattr(window, '_live_residuals', None)
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
    from solvers.simple_solver import _aligned_grid

    # 2026-05-09 (option B) — per-side fluid property accessors. Air uses
    # ideal-gas density (T, P); water is incompressible so P is ignored.
    # Returns (rho_fn, cp_fn, mu_fn, k_fn) — each accepts a scalar or
    # ndarray T (K) and P (Pa, optional) with broadcast semantics.
    def _props_for(fluid: str):
        if fluid == 'water':
            return dict(
                rho=(lambda T, P=None: _tc.water_density(T)),
                cp=_tc.water_cp,
                mu=_tc.water_viscosity,
                k=_tc.water_conductivity,
                name='water',
            )
        return dict(
            rho=(lambda T, P=101325.0: _tc.air_density(T, P)),
            cp=_tc.air_cp,
            mu=_tc.air_viscosity,
            k=_tc.air_conductivity,
            name='air',
        )
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
    # |u_cc|·D_h·ρ/μ Reynolds. Wall cells with u→0 fall to Nu_lam=4.36 floor
    # (laminar Hagen-Poiseuille limit, prevents Nu→0 non-physical extrapolation).
    _NU_LAM_FLOOR_2D = 4.36

    def _nu_dispatch(side_props, side_T_for_Pr, Re, eps_f, L_mm, D_h_mm):
        """Per-side Nu: water uses Pr-substitution onto air-fit correlation
        (option B, 2026-05-09). Air uses native Nu correlation."""
        if side_props['name'] == 'water':
            mu_w = float(side_props['mu'](side_T_for_Pr))
            k_w  = float(side_props['k'](side_T_for_Pr))
            cp_w = float(side_props['cp'](side_T_for_Pr))
            Pr_w = mu_w * cp_w / k_w
            return _tc.nu_water_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm,
                                        Pr_w)
        return _tc.nu_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm)

    def _build_hv_local_2d(rho_scalar, mu_scalar, k_f_scalar,
                            u_mag_field, L_mm_field, t_mm_field,
                            side_props=None, side_T_for_Pr=None):
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
                                                D_h * 1000.0)
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
                                            L_ij, D_h_l * 1000.0)
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

    def _on_progress(step, total):
        pass  # progress handled by main thread timer

    coupling_converged = False
    drho_A = drho_B = float('inf')
    dT_A = dT_B = float('inf')
    Ta_prev = Tb_prev = None
    e_info = {'converged': False, 'iterations': 0, 'residual': float('inf')}
    Ta = Tb = Ts = None
    # User-provided solid warm-start seed. Empty → solver fallback
    # (per-fluid inlet T for Ta/Tb, 0.5*(T_inA+T_inB) for Ts).
    # Filled → only Ts is overridden with the user value; Ta/Tb stay at
    # the per-fluid inlet T to avoid the 0.5-mean energy-balance leak
    # documented in solve_full_3d.py:1442-44 (mid-T value at non-pipe
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

    rho_cp_A = _pA['rho'](T_inA, P_inA_val) * _pA['cp'](T_inA)
    rho_cp_B = _pB['rho'](T_inB, P_inB_val) * _pB['cp'](T_inB)

    # Variable density: 2D rho fields for SIMPLE (initialized uniform)
    rho_A_field = np.full((N_x, N_y), _pA['rho'](T_inA, P_inA_val))
    rho_B_field = np.full((N_x, N_y), _pB['rho'](T_inB, P_inB_val))

    for _coup_it in range(_MAX_COUPLING):
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
            # 2026-05-09 (option B) — water side runs incompressible SIMPLE
            # so _update_density (ideal-gas P/RT update) is a no-op; ρ stays
            # at the inlet value over the whole field.
            _ftA = 'incompressible' if _pA['name'] == 'water' else 'ideal_gas'
            _ftB = 'incompressible' if _pB['name'] == 'water' else 'ideal_gas'
            ucA, vcA, simpA = _run_simple(cfgA, rho_A_field, mu_A, T_inA, u_A,
                                            'Fluid A', P_inA_val,
                                            T_field_real=_Ta_for_simpA,
                                            fluid_type=_ftA)
            ucB, vcB, simpB = _run_simple(cfgB, rho_B_field, mu_B, T_inB, u_B,
                                            'Fluid B', P_inB_val,
                                            T_field_real=_Tb_for_simpB,
                                            fluid_type=_ftB)
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
        k_fA = float(_pA['k'](T_inA))
        k_fB = float(_pB['k'](T_inB))
        # Zoned L/t fields (only if zone_config and grid mode); otherwise None
        L_field_2d = None; t_field_2d = None
        if zone_config is not None and za is not None:
            L_field_2d = za.get('L_mm_arr')
            t_field_2d = za.get('t_arr')
        h_vA_local = _build_hv_local_2d(rho_A_scalar, mu_A_scalar, k_fA,
                                         u_mag_A, L_field_2d, t_field_2d,
                                         side_props=_pA, side_T_for_Pr=T_inA)
        h_vB_local = _build_hv_local_2d(rho_B_scalar, mu_B_scalar, k_fB,
                                         u_mag_B, L_field_2d, t_field_2d,
                                         side_props=_pB, side_T_for_Pr=T_inB)

        # 2026-05-09 (option B) — water-side stiffness: ρ·cp_water ~ 4100×
        # ρ·cp_air, h_v_water ~ 2-3× h_v_air (Pr-substitution). solve_full_domain
        # GS-smoother is air-fit and can NaN-blow up on raw water settings.
        # Loosen tol + raise max_iter when ANY side is water; air-air case
        # keeps the original tight settings.
        _has_water = (_pA['name'] == 'water') or (_pB['name'] == 'water')
        _e_max_iter = 12000 if _has_water else 5000
        _e_tol      = 1.0   if _has_water else 0.5

        # Step 2: Full-domain coupled energy solve (warm-start from previous iteration)
        if zone_config is not None:
            Ta, Tb, Ts, e_info = solve_full_domain(
                L, H, N_x, N_y, T_inA, T_inB,
                za['K_ffA_arr'], za['K_ffB_arr'], za['K_ss_arr'],
                h_vA_local, h_vB_local,
                rho_cp_A, rho_cp_B,
                za['eps_arr'], ucA, vcA, ucB, vcB,
                dir_A, dir_B,
                max_iter=_e_max_iter, tol=_e_tol,
                progress_cb=_on_progress, return_info=True,
                Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
                dx_arr=energy_dx, dy_arr=energy_dy,
                inlet_mask_A=_imA, inlet_mask_B=_imB)
        else:
            Ta, Tb, Ts, e_info = solve_full_domain(
                L, H, N_x, N_y, T_inA, T_inB,
                window._K_ffA, window._K_ffB, window._K_ss,
                h_vA_local, h_vB_local,
                rho_cp_A, rho_cp_B,
                eps, ucA, vcA, ucB, vcB,
                dir_A, dir_B,
                max_iter=_e_max_iter, tol=_e_tol,
                progress_cb=_on_progress, return_info=True,
                Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
                inlet_mask_A=_imA, inlet_mask_B=_imB,
                dx_arr=energy_dx, dy_arr=energy_dy)

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
        rho_cp_A_new = _pA['rho'](Ta, P_abs_A) * _pA['cp'](Ta)
        rho_cp_B_new = _pB['rho'](Tb, P_abs_B) * _pB['cp'](Tb)
        rho_A_field_new = _pA['rho'](Ta, P_abs_A)
        rho_B_field_new = _pB['rho'](Tb, P_abs_B)

        # Variable mu: build 2D viscosity field from per-cell Ta/Tb via
        # Sutherland (air) or Vogel (water). With local-P density now using
        # the full field, local mu keeps the momentum balance consistent
        # cell-by-cell.
        mu_A = _pA['mu'](Ta)
        mu_B = _pB['mu'](Tb)
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
        if Ta_prev is not None:
            dT_A = float(np.max(np.abs(Ta - Ta_prev)))
            dT_B = float(np.max(np.abs(Tb - Tb_prev)))
        else:
            dT_A = dT_B = float('inf')  # first iter — always not converged
        print(f"  [Coupling {_coup_it+1}] drho_A={drho_A:.4f} drho_B={drho_B:.4f} "
              f"dT_A={dT_A:.2f}K dT_B={dT_B:.2f}K "
              f"T_avg_A={T_avg_A:.1f}K T_avg_B={T_avg_B:.1f}K")

        if (drho_A < _COUPLING_TOL and drho_B < _COUPLING_TOL
                and dT_A < _DT_TOL_K and dT_B < _DT_TOL_K):
            coupling_converged = True
            break

        Ta_prev = Ta.copy(); Tb_prev = Tb.copy()

        # Under-relax (field-wise)
        rho_A_field = _ALPHA_COUP * rho_A_field_new + (1 - _ALPHA_COUP) * rho_A_field
        rho_B_field = _ALPHA_COUP * rho_B_field_new + (1 - _ALPHA_COUP) * rho_B_field
        rho_cp_A = _ALPHA_COUP * rho_cp_A_new + (1 - _ALPHA_COUP) * rho_cp_A
        rho_cp_B = _ALPHA_COUP * rho_cp_B_new + (1 - _ALPHA_COUP) * rho_cp_B

    if not coupling_converged:
        warnings_list.append(
            f"Velocity-temperature coupling: not converged after {_MAX_COUPLING} iters "
            f"(drho_A={drho_A:.4f}, drho_B={drho_B:.4f}, "
            f"dT_A={dT_A:.2f}K, dT_B={dT_B:.2f}K)")
    warnings_list.extend(simple_warnings.values())

    # Zone statistics and boundary lines
    z_axis = cfg['z_axis']
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

    # Smooth temperature fields for display if partial-width inlets exist
    # (removes Brinkman-induced stripes; Q/dP already computed from raw fields)
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
    dir_flow_A = window._DIR_MAP[dir_A]
    dir_flow_B = window._DIR_MAP[dir_B]

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
                               _pA['rho'](T_inA, P_inA_val) * _pA['cp'](T_inA)))
    rcp_B2 = _interp2(rho_cp_B if np.ndim(rho_cp_B) > 0 else
                       np.full((N_x, N_y),
                               _pB['rho'](T_inB, P_inB_val) * _pB['cp'](T_inB)))
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
    Ta2, Tb2, Ts2 = solve_full_domain(
        L, H, Nx2, Ny2, T_inA, T_inB,
        K_ffA2, K_ffB2, K_ss2, h_vA2, h_vB2,
        rcp_A2, rcp_B2, eps2,
        ucA2, vcA2, ucB2, vcB2,
        dir_A, dir_B, tol=0.5, max_iter=5000,
        dx_arr=energy_dx2, dy_arr=energy_dy2)
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

    try:
        Q_A_fine = _enthalpy_balance_2d(
            Ta, ucA, vcA, rho_cp_A_fld, dir_A, energy_dx, energy_dy,
            inlet_mask=mA_in, outlet_mask=mA_out)
        Q_B_fine = _enthalpy_balance_2d(
            Tb, ucB, vcB, rho_cp_B_fld, dir_B, energy_dx, energy_dy,
            inlet_mask=mB_in, outlet_mask=mB_out)
        Q_A_coarse = _enthalpy_balance_2d(
            Ta2, ucA2, vcA2, rcp_A2, dir_A, energy_dx2, energy_dy2,
            inlet_mask=mA_in2, outlet_mask=mA_out2)
        Q_B_coarse = _enthalpy_balance_2d(
            Tb2, ucB2, vcB2, rcp_B2, dir_B, energy_dx2, energy_dy2,
            inlet_mask=mB_in2, outlet_mask=mB_out2)
        # A-1 refactor (2026-04-24): apply Richardson to |Q_A| and |Q_B|
        # separately, THEN take max. Each Richardson acts on a smooth
        # (single-sign) function across refinement, so the formal
        # 2nd-order extrapolation stays valid. Prior pipeline applied
        # Richardson after max(), which fails if max-argument flips
        # between the coarse and fine grids.
        Q_A_ext = (4.0 * abs(Q_A_fine)   - abs(Q_A_coarse)  ) / 3.0
        Q_B_ext = (4.0 * abs(Q_B_fine)   - abs(Q_B_coarse)  ) / 3.0
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
            cp_A_in  = float(_pA['cp'](T_inA))
            cp_B_in  = float(_pB['cp'](T_inB))
            A_in_A = float(cfgA.get('in_w', H))
            A_in_B = float(cfgB.get('in_w', L))
            m_dot_A = rho_A_in * abs(u_A) * A_in_A
            m_dot_B = rho_B_in * abs(u_B) * A_in_B
            Q_A_simple = m_dot_A * cp_A_in * abs(T_inA - T_out_A_mean)
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
    }
    return result


def _store_results(window, cfg, result):
    """Phase 4: store results on window for finalize_plots."""
    N_x = cfg['N_x']; N_y = cfg['N_y']
    L = cfg['L']; H = cfg['H']
    dir_A = cfg['dir_A']; dir_B = cfg['dir_B']
    zone_config = cfg['zone_config']; za = cfg['za']

    window._compute_results = {
        'Ta': result['Ta'], 'Tb': result['Tb'], 'Ts': result['Ts'],
        'ucA': result['ucA'], 'vcA': result['vcA'],
        'ucB': result['ucB'], 'vcB': result['vcB'],
        'P_fA': result['P_fA'], 'P_fB': result['P_fB'],
        'dP_A': result['dP_A'], 'dP_B': result['dP_B'],
        'Q_total': result['Q_total'],
        'N_x': N_x, 'N_y': N_y, 'L': L, 'H': H,
        'dir_A': dir_A, 'dir_B': dir_B,
        'zone_config': zone_config, 'za': za,
        'dx_arr': result['energy_dx'], 'dy_arr': result['energy_dy'],
        'residuals_A': result.get('residuals_A'),
        'residuals_B': result.get('residuals_B'),
        # Conservation diagnostics (per-fluid enthalpy change, net, relative)
        'Q_A': result.get('Q_A', float('nan')),
        'Q_B': result.get('Q_B', float('nan')),
        'Q_net': result.get('Q_net', float('nan')),
        'energy_imbalance_rel': result.get('energy_imbalance_rel', float('nan')),
    }
    window._compute_warnings = result['warnings_list']
    return  # rendering happens in finalize_plots on main thread


def plot_temperature_3panel(window, r, _t):
    """Render the 3-row T_fA / T_fB / T_s contour panel on canvas_temp.

    Honours `window.chk_sync_colorbar_T` — when checked, all three panels
    share the global vmin/vmax so a colour has the same temperature meaning
    across fluids and solid. When off, fluids share vmin/vmax and solid
    auto-scales independently (the pre-toggle behaviour).
    """
    Ta, Tb, Ts = r['Ta'], r['Tb'], r['Ts']
    N_x, N_y, L, H = r['N_x'], r['N_y'], r['L'], r['H']

    window.canvas_temp.fig.clear()
    axes = window.canvas_temp.fig.subplots(3, 1)
    window.canvas_temp.axes = [list(axes)]
    window.canvas_temp.fig.patch.set_facecolor(_t['fig_bg'])

    _dx = r.get('dx_arr', np.full(N_x, L / N_x))
    _dy = r.get('dy_arr', np.full(N_y, H / N_y))
    x = (np.cumsum(_dx) - _dx / 2) * 1000
    y = (np.cumsum(_dy) - _dy / 2) * 1000
    Y, X = np.meshgrid(y, x)

    _sync = True
    try:
        _sync = bool(window.chk_sync_colorbar_T.isChecked())
    except Exception:
        pass
    if _sync:
        v_all_min = float(min(Ta.min(), Tb.min(), Ts.min()))
        v_all_max = float(max(Ta.max(), Tb.max(), Ts.max()))
        vmin_f, vmax_f = v_all_min, v_all_max
        vmin_s, vmax_s = v_all_min, v_all_max
    else:
        vmin_f = min(Ta.min(), Tb.min()); vmax_f = max(Ta.max(), Tb.max())
        vmin_s, vmax_s = None, None

    plot_items = [
        (Ta, r"$T_{f,A}$  [K]", "Fluid A"),
        (Tb, r"$T_{f,B}$  [K]", "Fluid B"),
        (Ts, r"$T_s$  [K]", "Solid"),
    ]
    for ax, (field, main_title, subtitle) in zip(axes, plot_items):
        ax.set_facecolor(_t['ax_bg'])
        if 'T_s' in main_title:
            # T_s uses turbo to match fluid T_a/T_b + 3D volume — all physics
            # fields share the same modern-rainbow LUT for cross-plot parity.
            # levels=128 (was 512): see 2026-05-20 UI sweep note in
            # run_calculation_3d.py — 512 over-samples turbo's 256-colour
            # LUT and quadruples contour triangulation cost.
            kw = dict(levels=128, cmap='turbo')
            if vmin_s is not None:
                kw.update(vmin=vmin_s, vmax=vmax_s)
        else:
            kw = dict(levels=128, cmap='turbo', vmin=vmin_f, vmax=vmax_f)
        from ui.matplotlib_canvas import pad_field_to_edges
        _Xp, _Yp, _Fp = pad_field_to_edges(x, y, field, L * 1000.0, H * 1000.0)
        cf = ax.contourf(_Xp, _Yp, _Fp, **kw)
        ax.set_xlim(0, L * 1000.0); ax.set_ylim(0, H * 1000.0)
        cb = window.canvas_temp.fig.colorbar(cf, ax=ax, shrink=0.9,
                                              aspect=25, format="%.0f")
        cb.ax.tick_params(labelsize=8, colors=_t['ax_text'], length=3)
        cb.ax.yaxis.set_major_locator(plt.MaxNLocator(nbins=7))
        cb.outline.set_edgecolor(_t['ax_spine'])
        ax.set_title(main_title, fontsize=13, fontweight="bold",
                     color=_t['ax_text'], loc='left', pad=6)
        ax.text(0.99, 1.02, subtitle, transform=ax.transAxes,
                fontsize=9, color=_t['mpl_subtitle'], ha='right', va='bottom',
                fontstyle='italic')
        ax.set_xlabel("x [mm]", fontsize=10, color=_t['ax_text'])
        ax.set_ylabel("y [mm]", fontsize=10, color=_t['ax_text'])
        ax.tick_params(labelsize=9, colors=_t['ax_text'], length=4, width=0.8)
        ax.set_aspect('auto')
        ax.grid(True, alpha=0.12, linewidth=0.4, color=_t['ax_text'])
        for sp in ax.spines.values():
            sp.set_edgecolor(_t['ax_spine']); sp.set_linewidth(0.8)
        if hasattr(window, '_zone_boundaries') and window._zone_boundaries:
            z_dir = getattr(window, '_zone_axis_dir', 'y')
            for b in window._zone_boundaries:
                if z_dir == 'y':
                    ax.axhline(y=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)
                else:
                    ax.axvline(x=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)
        for b in (getattr(window, '_zone_boundaries_x', None) or []):
            ax.axvline(x=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)
        for b in (getattr(window, '_zone_boundaries_y', None) or []):
            ax.axhline(y=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)

    window.canvas_temp.fig.subplots_adjust(left=0.08, right=0.93,
                                            top=0.96, bottom=0.06, hspace=0.34)
    window.canvas_temp.draw()
    window.canvas_temp._hover_data = {
        'fields': [Ta, Tb, Ts],
        'names': ['T_fA', 'T_fB', 'T_s'],
        'unit': 'K',
        'L': L, 'H': H, 'Nx': N_x, 'Ny': N_y,
    }


def redraw_temperature_panel(window):
    """Re-render the temperature tab using the last stored compute result.
    No-op if nothing has been computed yet."""
    r = getattr(window, '_compute_results', None)
    if r is None:
        return
    from ui.theme import get_theme
    plot_temperature_3panel(window, r, get_theme())


def finalize_plots(window):
    """Ex-Main_Menu._finalize_plots(self). Render plots from stored results.
    MUST run on main thread."""
    from ui.theme import get_theme
    import main as _main_mod
    _t = get_theme()

    if getattr(window, '_compute_warnings', None):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(
            window, "Solver Warnings",
            "\n\n".join(window._compute_warnings))
        window._compute_warnings = None
    r = window._compute_results
    Ta, Tb, Ts = r['Ta'], r['Tb'], r['Ts']
    ucA, vcA, ucB, vcB = r['ucA'], r['vcA'], r['ucB'], r['vcB']
    P_fA, P_fB = r['P_fA'], r['P_fB']
    dP_A, dP_B = r['dP_A'], r['dP_B']
    N_x, N_y, L, H = r['N_x'], r['N_y'], r['L'], r['H']
    dir_A, dir_B = r['dir_A'], r['dir_B']
    zone_config, za = r['zone_config'], r['za']

    dir_flow_A = window._DIR_MAP[dir_A]
    dir_flow_B = window._DIR_MAP[dir_B]

    window._r_dP_A.setText(f"{dP_A:.1f}")
    window._r_dP_B.setText(f"{dP_B:.1f}")
    window._r_Q.setText(f"{r.get('Q_total', 0):.1f}")

    mode_label = f"A:{dir_flow_A} B:{dir_flow_B}"

    # Temperature: vertical 3×1 plot (Fluid A, Fluid B, Solid) — delegated
    # to a module-level helper so the K/°C sync toggle can redraw without
    # re-running the full finalize pipeline.
    plot_temperature_3panel(window, r, _t)
    # Hover data cached by helper; the rest of this function handles
    # pressure, velocity, and layout panels. Preserve original variable
    # bindings for code below.
    _dx = r.get('dx_arr', np.full(N_x, L / N_x))
    _dy = r.get('dy_arr', np.full(N_y, H / N_y))
    x = (np.cumsum(_dx) - _dx / 2) * 1000
    y = (np.cumsum(_dy) - _dy / 2) * 1000
    Y, X = np.meshgrid(y, x)
    _sub = _t['mpl_subtitle']

    # Pressure plot (pass correct dP values + residual history for the
    # convergence mini-plot at the bottom of the tab)
    window.canvas_pres.plot_pressure(P_fA, P_fB, N_x, N_y, L, H, mode_label,
                                     dP_A=dP_A, dP_B=dP_B,
                                     dx_arr=r.get('dx_arr'), dy_arr=r.get('dy_arr'),
                                     residuals_A=r.get('residuals_A'),
                                     residuals_B=r.get('residuals_B'))
    window.canvas_pres._hover_data = {
        'fields': [P_fA, P_fB],
        'names': ['P_A', 'P_B'],
        'unit': 'Pa',
        'L': L, 'H': H, 'Nx': N_x, 'Ny': N_y,
    }

    # Velocity plot: vertical 2×1 (Fluid A, Fluid B)
    window.canvas_vel.fig.clear()
    window.canvas_vel.fig.patch.set_facecolor(_t['fig_bg'])
    ax_vA, ax_vB = window.canvas_vel.fig.subplots(2, 1)
    # Register axes for _on_hover (list-of-rows format expected by the
    # generic hover handler at _on_hover:907)
    window.canvas_vel.axes = [[ax_vA, ax_vB]]
    UmagA = np.sqrt(ucA**2 + vcA**2)
    UmagB = np.sqrt(ucB**2 + vcB**2)
    for ax, (field, main_title, subtitle) in zip([ax_vA, ax_vB], [
        (UmagA, r"$|\mathbf{U}_A|$  [m/s]", "Fluid A"),
        (UmagB, r"$|\mathbf{U}_B|$  [m/s]", "Fluid B"),
    ]):
        ax.set_facecolor(_t['ax_bg'])
        # PowerNorm(gamma=0.4): v^0.4 mapping from v to colour, slightly
        # more aggressive than sqrt (gamma=0.5). Physical motivation: at
        # Re ~500 the porous-media regime is Forchheimer, dP/dx ~ rho*beta*v^2,
        # so v ~ sqrt(dP) and a sqrt-ish colour scale maps linearly to the
        # pressure gradient (the true driver). gamma=0.4 pushes low-end
        # values (1-2 m/s stagnation zones) further up the colormap so they
        # are clearly visible — at gamma=0.5 v=1 sits at only 29% of the
        # colormap (still turbo's dark blue), gamma=0.4 lifts it to 37%
        # (cyan) so the stagnation gradient reads clearly from wall to pipe.
        # For the narrow-range A case (9.4-10.0) the normalisation is
        # auto-scaled so the gamma only biases colour distribution slightly.
        from matplotlib.colors import PowerNorm as _PowerNorm
        _vnorm = _PowerNorm(gamma=0.4, vmin=float(field.min()),
                            vmax=float(field.max()))
        from ui.matplotlib_canvas import pad_field_to_edges
        _Xp, _Yp, _Fp = pad_field_to_edges(x, y, field, L * 1000.0, H * 1000.0)
        cf = ax.contourf(_Xp, _Yp, _Fp, levels=128, cmap='turbo', norm=_vnorm)
        ax.set_xlim(0, L * 1000.0); ax.set_ylim(0, H * 1000.0)
        cb = window.canvas_vel.fig.colorbar(cf, ax=ax, shrink=0.9,
                                             aspect=25, format="%.1f")
        cb.ax.tick_params(labelsize=8, colors=_t['ax_text'], length=3)
        cb.ax.yaxis.set_major_locator(plt.MaxNLocator(nbins=7))
        cb.outline.set_edgecolor(_t['ax_spine'])
        ax.set_title(main_title, fontsize=13, fontweight="bold",
                     color=_t['ax_text'], loc='left', pad=6)
        ax.text(0.99, 1.02, subtitle, transform=ax.transAxes,
                fontsize=9, color=_t['mpl_subtitle'], ha='right', va='bottom',
                fontstyle='italic')
        ax.set_xlabel("x [mm]", fontsize=10, color=_t['ax_text'])
        ax.set_ylabel("y [mm]", fontsize=10, color=_t['ax_text'])
        ax.tick_params(labelsize=9, colors=_t['ax_text'], length=4, width=0.8)
        ax.set_aspect('auto')
        ax.grid(True, alpha=0.15, linewidth=0.5, color=_t['ax_text'])
        for sp in ax.spines.values():
            sp.set_edgecolor(_t['ax_spine']); sp.set_linewidth(0.8)
        if hasattr(window, '_zone_boundaries') and window._zone_boundaries:
            z_dir = getattr(window, '_zone_axis_dir', 'y')
            for b in window._zone_boundaries:
                if z_dir == 'y':
                    ax.axhline(y=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)
                else:
                    ax.axvline(x=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)
        for b in (getattr(window, '_zone_boundaries_x', None) or []):
            ax.axvline(x=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)
        for b in (getattr(window, '_zone_boundaries_y', None) or []):
            ax.axhline(y=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)
    window.canvas_vel.fig.subplots_adjust(left=0.08, right=0.93,
                                           top=0.96, bottom=0.07, hspace=0.32)
    window.canvas_vel.draw()
    window.canvas_vel._hover_data = {
        'fields': [UmagA, UmagB],
        'names': ['|U_A|', '|U_B|'],
        'unit': 'm/s',
        'L': L, 'H': H, 'Nx': N_x, 'Ny': N_y,
    }

    window.slider.hide()
    window._update_tout(-1)

    # Surrogate extrapolation watermark — one compact label across all
    # result canvases so the reader always sees this run left the
    # validated (L, t, Re) window. Also stored on window._has_extrap so
    # the Pareto / export paths can refuse or flag it downstream.
    _reasons = list(getattr(window, '_extrap_reasons', []) or [])
    window._has_extrap = bool(_reasons)
    if _reasons:
        from ui.theme import get_theme as _gt
        _tw = _gt().get('warn', '#B45309')
        _wm_text = "⚠ ConstDF-v1 extrapolated: " + " | ".join(_reasons)
        for _cv in (window.canvas_temp, window.canvas_pres, window.canvas_vel):
            try:
                _cv.fig.text(0.5, 0.005, _wm_text,
                             color=_tw, fontsize=8, ha='center', va='bottom',
                             fontweight='bold', alpha=0.85)
                _cv.draw_idle()
            except Exception:
                pass
