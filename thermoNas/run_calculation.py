"""Main calculation pipeline for ThermoNAS (non-polygon case).

Extracted from main.py (Task B.9). Entry: run_calculation_inner.
Also contains finalize_plots which renders results on canvas widgets.
All functions take `window` (Main_Menu) as first argument.
"""
import numpy as np
import matplotlib.pyplot as plt
from simple_solver import SIMPLESolver
from solve_full import solve_full_domain
from tpms_calc import compute as tpms_compute, geometry as tpms_geometry


def run_calculation_inner(window):
    """Orchestrator: split into 4 phases for readability."""
    cfg = _parse_inputs(window)
    fields = _build_fields(window, cfg)
    result = _run_solvers(window, cfg, fields)
    _store_results(window, cfg, result)


def _parse_inputs(window):
    """Phase 1: UI input reading + validation + zone config building."""
    warnings_list = []

    def _parse(widget, name, typ=float):
        try:
            return typ(widget.text())
        except ValueError:
            return name  # return field name as sentinel

    _fields = {
        'L': _parse(window.le_L, "Domain Length (L)"),
        'H': _parse(window.le_H, "Domain Height (H)"),
        'cp_f': _parse(window.le_cp_f, "Specific Heat (cp)", float),
        'N_x': _parse(window.le_Nx, "Grid Nx", int),
        'N_y': _parse(window.le_Ny, "Grid Ny", int),
        'u_A': _parse(window.le_uA, "Velocity A (u_A)"),
        'u_B': _parse(window.le_uB, "Velocity B (u_B)"),
        'T_inA': _parse(window.le_TinA, "Inlet Temp A (T_inA)"),
        'T_inB': _parse(window.le_TinB, "Inlet Temp B (T_inB)"),
    }
    bad = [v for v in _fields.values() if isinstance(v, str)]
    if bad:
        raise ValueError(f"Invalid input in: {', '.join(bad)}")
    L, H, cp_f = _fields['L'], _fields['H'], _fields['cp_f']
    N_x, N_y = _fields['N_x'], _fields['N_y']
    u_A, u_B = _fields['u_A'], _fields['u_B']
    T_inA, T_inB = _fields['T_inA'], _fields['T_inB']

    dx = L / N_x;  dy = H / N_y
    try:
        cfgA = window._fluid_config('A')
        cfgB = window._fluid_config('B')
    except ValueError:
        cfgA = dict(dir=0, in_ctr=H/2, in_w=H, out_ctr=H/2, out_w=H)
        cfgB = dict(dir=3, in_ctr=L/2, in_w=L, out_ctr=L/2, out_w=L)
    dir_A = cfgA['dir'];  dir_B = cfgB['dir']

    tpms_type = window.combo_tpms.currentText()
    Lcell = float(window.le_Lcell.text())
    t_wall = float(window.le_t.text())
    k_s = float(window.le_ks.text())
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
            P_in_val = float(window.le_PinA.text())
            if z_axis == 'grid' and window._zone_grid is not None:
                # 2D grid mode — use Sigmoid continuous field if decision vector available
                _x_dec = getattr(window, '_pareto_x_decision', None)
                if _x_dec is not None:
                    from sigmoid_field import build_continuous_arrays, get_geometry_lut
                    _lut = get_geometry_lut(tpms_type)
                    za = build_continuous_arrays(
                        _x_dec, Lcell, t_wall,
                        getattr(window, '_pareto_y_trans_inlet', 0.2),
                        getattr(window, '_pareto_y_trans_outlet', 0.2),
                        N_x, N_y, L, H,
                        tpms_type, k_s,
                        u_A, u_B, T_inA, T_inB, _lut)
                    print(f"[ZONE] Continuous Sigmoid field ({N_x}x{N_y})")
                else:
                    from zone_config import ZoneConfig
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
        'L': L, 'H': H, 'cp_f': cp_f,
        'N_x': N_x, 'N_y': N_y,
        'dx': dx, 'dy': dy,
        'u_A': u_A, 'u_B': u_B,
        'T_inA': T_inA, 'T_inB': T_inB,
        'cfgA': cfgA, 'cfgB': cfgB,
        'dir_A': dir_A, 'dir_B': dir_B,
        'tpms_type': tpms_type,
        'Lcell': Lcell, 't_wall': t_wall, 'k_s': k_s,
        'eps': eps, 'r_h': r_h,
        'zone_config': zone_config, 'za': za, 'z_axis': z_axis,
        'warnings_list': warnings_list,
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
        import tpms_calc as _tc
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
    from simple_solver import _aligned_grid
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
    energy_dx = _aligned_grid(N_x, L, list(_x_breaks))
    energy_dy = _aligned_grid(N_y, H, list(_y_breaks))

    # Build the _run_simple closure here so it captures all needed locals.
    # It is returned in fields and called by Phase 3.
    simple_warnings = {}

    def _run_simple(cfg_fluid, rho_f, mu_f, T_in_f, u_f, label):
        d = cfg_fluid['dir']
        is_x = window._is_x_dir(d)
        pipe_lo = cfg_fluid['in_ctr'] - cfg_fluid['in_w'] / 2
        pipe_hi = cfg_fluid['in_ctr'] + cfg_fluid['in_w'] / 2
        out_lo = cfg_fluid.get('out_ctr', cfg_fluid['in_ctr']) - cfg_fluid.get('out_w', cfg_fluid['in_w']) / 2
        out_hi = cfg_fluid.get('out_ctr', cfg_fluid['in_ctr']) + cfg_fluid.get('out_w', cfg_fluid['in_w']) / 2

        # Build zone arrays for SIMPLE if zones are active
        z_arr = None
        from zone_config import ZoneConfig
        if za is not None:
            if is_x:
                z_arr = _build_zone_arrays_for_simple(za, N_x, N_y, True, mu_f)
            else:
                z_arr = _build_zone_arrays_for_simple(za, N_y, N_x, False, mu_f)

        zc_simple = zone_config if (not is_x and isinstance(zone_config, ZoneConfig)) else None

        # Transform rho_f to SIMPLE coords if it's a 2D field
        if np.ndim(rho_f) == 2:
            if is_x:
                # Real (Nx, Ny) → SIMPLE (Ny, Nx) by transpose
                rho_simple = rho_f.T.copy()
                if d == 1:  # -x: flip j (which is real x flipped)
                    rho_simple = rho_simple[:, ::-1].copy()
            else:
                rho_simple = rho_f.copy()
                if d == 3:  # -y: flip j (real y flipped)
                    rho_simple = rho_simple[:, ::-1].copy()
        else:
            rho_simple = rho_f  # scalar

        if is_x:
            s = SIMPLESolver(H, L, N_y, N_x, tpms_type, Lcell, t_wall,
                             eps, r_h, rho_simple, mu_f, T_in_f,
                             pipe_lo, pipe_hi, u_f,
                             outlet_lo=out_lo, outlet_hi=out_hi,
                             zone_arrays=z_arr)
            # Override grid to match energy solver (SIMPLE x = real y)
            s.dx_arr = energy_dy.copy()
            s.dy_arr = _aligned_grid(N_x, L, list(_x_breaks))
        else:
            s = SIMPLESolver(L, H, N_x, N_y, tpms_type, Lcell, t_wall,
                             eps, r_h, rho_simple, mu_f, T_in_f,
                             pipe_lo, pipe_hi, u_f,
                             outlet_lo=out_lo, outlet_hi=out_hi,
                             zone_config=zc_simple,
                             zone_arrays=z_arr if zc_simple is None else None)
            # Override grid to match energy solver (SIMPLE x = real x)
            s.dx_arr = energy_dx.copy()
            s.dy_arr = energy_dy.copy()
        _has_partial = np.any(s.outlet_frac < 0.99) and np.any(s.outlet_frac > 0.5)
        _tol = 5e-4 if _has_partial else 1e-5
        conv, n_it = s.solve(max_iter=5000, tol=_tol, verbose=False)
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

    energy_dx = fields['energy_dx']; energy_dy = fields['energy_dy']
    _x_breaks = fields['_x_breaks']; _y_breaks = fields['_y_breaks']
    _run_simple = fields['_run_simple']
    simple_warnings = fields['simple_warnings']

    # ── Outer velocity-temperature coupling loop ──
    import warnings as _warn
    import tpms_calc as _tc
    from simple_solver import _aligned_grid

    _MAX_COUPLING = 5
    _COUPLING_TOL = 0.01  # 1% relative change in rho
    _ALPHA_COUP = 0.7     # under-relaxation

    rho_A, rho_B = window._rho_A, window._rho_B
    mu_A, mu_B = window._mu_A, window._mu_B
    P_inA_val = float(window.le_PinA.text())
    P_inB_val = float(window.le_PinB.text())

    def _on_progress(step, total):
        pass  # progress handled by main thread timer

    coupling_converged = False
    drho_A = drho_B = float('inf')
    e_info = {'converged': False, 'iterations': 0, 'residual': float('inf')}
    Ta = Tb = Ts = None
    _has_partial_A = False
    _has_partial_B = False
    ucA = vcA = ucB = vcB = None
    simpA = simpB = None

    rho_cp_A = _tc.air_density(T_inA, P_inA_val) * _tc.air_cp(T_inA)
    rho_cp_B = _tc.air_density(T_inB, P_inB_val) * _tc.air_cp(T_inB)

    # Variable density: 2D rho fields for SIMPLE (initialized uniform)
    rho_A_field = np.full((N_x, N_y), _tc.air_density(T_inA, P_inA_val))
    rho_B_field = np.full((N_x, N_y), _tc.air_density(T_inB, P_inB_val))

    for _coup_it in range(_MAX_COUPLING):
        window._compute_progress = 10 + int(80 * _coup_it / _MAX_COUPLING)

        # Step 1: SIMPLE velocity with current rho field
        with _warn.catch_warnings(record=True) as _caught:
            _warn.simplefilter("always")
            ucA, vcA, simpA = _run_simple(cfgA, rho_A_field, mu_A, T_inA, u_A, 'Fluid A')
            ucB, vcB, simpB = _run_simple(cfgB, rho_B_field, mu_B, T_inB, u_B, 'Fluid B')
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

        # Step 2: Full-domain coupled energy solve (warm-start from previous iteration)
        if zone_config is not None:
            Ta, Tb, Ts, e_info = solve_full_domain(
                L, H, N_x, N_y, T_inA, T_inB,
                za['K_ffA_arr'], za['K_ffB_arr'], za['K_ss_arr'],
                za['h_vA_arr'], za['h_vB_arr'],
                rho_cp_A, rho_cp_B,
                za['eps_arr'], ucA, vcA, ucB, vcB,
                dir_A, dir_B,
                max_iter=5000, tol=0.5,
                progress_cb=_on_progress, return_info=True,
                Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
                dx_arr=energy_dx, dy_arr=energy_dy,
                inlet_mask_A=_imA, inlet_mask_B=_imB)
        else:
            Ta, Tb, Ts, e_info = solve_full_domain(
                L, H, N_x, N_y, T_inA, T_inB,
                window._K_ffA, window._K_ffB, window._K_ss,
                window._h_vA, window._h_vB,
                rho_cp_A, rho_cp_B,
                eps, ucA, vcA, ucB, vcB,
                dir_A, dir_B,
                max_iter=5000, tol=0.5,
                progress_cb=_on_progress, return_info=True,
                Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
                inlet_mask_A=_imA, inlet_mask_B=_imB,
                dx_arr=energy_dx, dy_arr=energy_dy)

        # Step 3: Update rho*cp and rho field from per-cell temperature
        rho_cp_A_new = _tc.air_density(Ta, P_inA_val) * _tc.air_cp(Ta)
        rho_cp_B_new = _tc.air_density(Tb, P_inB_val) * _tc.air_cp(Tb)
        rho_A_field_new = _tc.air_density(Ta, P_inA_val)  # 2D field
        rho_B_field_new = _tc.air_density(Tb, P_inB_val)

        T_avg_A = float(Ta.mean()); T_avg_B = float(Tb.mean())
        mu_A = _tc.air_viscosity(T_avg_A)  # mu still scalar (small effect)
        mu_B = _tc.air_viscosity(T_avg_B)

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
        print(f"  [Coupling {_coup_it+1}] drho_A={drho_A:.4f} drho_B={drho_B:.4f} "
              f"T_avg_A={T_avg_A:.1f}K T_avg_B={T_avg_B:.1f}K")

        if drho_A < _COUPLING_TOL and drho_B < _COUPLING_TOL:
            coupling_converged = True
            break

        # Under-relax (field-wise)
        rho_A_field = _ALPHA_COUP * rho_A_field_new + (1 - _ALPHA_COUP) * rho_A_field
        rho_B_field = _ALPHA_COUP * rho_B_field_new + (1 - _ALPHA_COUP) * rho_B_field
        rho_cp_A = _ALPHA_COUP * rho_cp_A_new + (1 - _ALPHA_COUP) * rho_cp_A
        rho_cp_B = _ALPHA_COUP * rho_cp_B_new + (1 - _ALPHA_COUP) * rho_cp_B

    if not coupling_converged:
        warnings_list.append(
            f"Velocity-temperature coupling: not converged after {_MAX_COUPLING} iters "
            f"(drho_A={drho_A:.4f}, drho_B={drho_B:.4f})")
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
            from zone_config import Zone
            dummy_zones = [Zone(f'g{r}', gc['y0'], gc['y1'], gc['L'], gc['t'])
                           for r, gc in enumerate(za.get('grid_cells', []))]
            from zone_config import compute_zone_statistics, format_zone_report
            _ca = energy_dx[:, None] * energy_dy[None, :]
            stats = compute_zone_statistics(Ta, Tb, Ts, za['zone_id'], dummy_zones,
                                            cell_area=_ca)
            print("\n[ZONE STATISTICS]")
            print(format_zone_report(stats))
            window._zone_stats = stats
        else:
            # 1D mode
            from zone_config import compute_zone_statistics, format_zone_report
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
    P_inA = float(window.le_PinA.text())
    P_inB = float(window.le_PinB.text())
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
        Q_100 = float(np.sum(za['h_vB_arr'] * (Ts - Tb) * _cell_area))
    else:
        h_vB = window._h_vB
        Q_100 = float(np.sum(h_vB * (Ts - Tb) * _cell_area))

    # Richardson: run energy at 200×100 for Q extrapolation
    Nx2, Ny2 = N_x * 2, N_y * 2
    energy_dx2 = _aligned_grid(Nx2, L, list(_x_breaks))
    energy_dy2 = _aligned_grid(Ny2, H, list(_y_breaks))

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
                       np.full((N_x, N_y), _tc.air_density(T_inA, P_inA_val) * _tc.air_cp(T_inA)))
    rcp_B2 = _interp2(rho_cp_B if np.ndim(rho_cp_B) > 0 else
                       np.full((N_x, N_y), _tc.air_density(T_inB, P_inB_val) * _tc.air_cp(T_inB)))
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
        Q_200 = float(np.sum(h_vB2 * (Ts2 - Tb2) * _area2))
    else:
        Q_200 = float(np.sum(h_vB2 * (Ts2 - Tb2) * _area2))
    Q_total = 2.0 * Q_200 - Q_100  # Richardson extrapolation

    # ΔP: f-Re for zones, SIMPLE for baseline
    if za is not None and 'L_field' in za and 'A_0_arr' in za:
        from sigmoid_field import compute_dP_continuous
        D_h_arr = 2.0 * za['eps_arr'] / (za['A_0_arr'] + 1e-30)
        tpms_type = window.combo_tpms.currentText()
        dP_A, dP_B = compute_dP_continuous(
            za['L_field'], za['t_field'], za['eps_arr'], D_h_arr,
            u_A, u_B, window._rho_A, window._rho_B,
            window._mu_A, window._mu_B,
            tpms_type, L, H, N_x, N_y,
            T_inA, T_inB)

    # Smooth pressure and velocity fields for display if partial-width
    if _has_partial_A or _has_partial_B:
        from scipy.ndimage import gaussian_filter
        _sp = 1.5
        if _has_partial_A:
            P_fA = gaussian_filter(P_fA, sigma=_sp)
        if _has_partial_B:
            P_fB = gaussian_filter(P_fB, sigma=_sp)

    result = {
        'Ta': Ta, 'Tb': Tb, 'Ts': Ts,
        'ucA': ucA, 'vcA': vcA, 'ucB': ucB, 'vcB': vcB,
        'P_fA': P_fA, 'P_fB': P_fB,
        'dP_A': dP_A, 'dP_B': dP_B,
        'Q_total': Q_total,
        'energy_dx': energy_dx, 'energy_dy': energy_dy,
        'warnings_list': warnings_list,
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
    }
    window._compute_warnings = result['warnings_list']
    return  # rendering happens in finalize_plots on main thread


def finalize_plots(window):
    """Ex-Main_Menu._finalize_plots(self). Render plots from stored results.
    MUST run on main thread."""
    from theme import _THEMES
    import main as _main_mod
    _t = _THEMES['light']

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

    # Temperature: vertical 3×1 plot (Fluid A, Fluid B, Solid)
    window.canvas_temp.fig.clear()
    axes = window.canvas_temp.fig.subplots(3, 1)
    window.canvas_temp.axes = [list(axes)]
    window.canvas_temp.fig.patch.set_facecolor(_t['fig_bg'])

    _dx = r.get('dx_arr', np.full(N_x, L / N_x))
    _dy = r.get('dy_arr', np.full(N_y, H / N_y))
    x = (np.cumsum(_dx) - _dx / 2) * 1000
    y = (np.cumsum(_dy) - _dy / 2) * 1000
    Y, X = np.meshgrid(y, x)
    vmin_f = min(Ta.min(), Tb.min()); vmax_f = max(Ta.max(), Tb.max())
    _sub = '#888888'
    plot_items = [
        (Ta, r"$T_{f,A}$  [K]", "Fluid A"),
        (Tb, r"$T_{f,B}$  [K]", "Fluid B"),
        (Ts, r"$T_s$  [K]", "Solid"),
    ]
    for ax, (field, main_title, subtitle) in zip(axes, plot_items):
        ax.set_facecolor(_t['ax_bg'])
        if 'T_s' in main_title:
            kw = dict(levels=512, cmap='coolwarm')
        else:
            kw = dict(levels=512, cmap='turbo', vmin=vmin_f, vmax=vmax_f)
        cf = ax.contourf(X, Y, field, **kw)
        cb = window.canvas_temp.fig.colorbar(cf, ax=ax, shrink=0.9,
                                              aspect=25, format="%.0f")
        cb.ax.tick_params(labelsize=8, colors=_t['ax_text'], length=3)
        cb.ax.yaxis.set_major_locator(plt.MaxNLocator(nbins=7))
        cb.outline.set_edgecolor(_t['ax_spine'])
        # Inline title: main left, subtitle right
        ax.set_title(main_title, fontsize=13, fontweight="bold",
                     color=_t['ax_text'], loc='left', pad=6)
        ax.text(0.99, 1.02, subtitle, transform=ax.transAxes,
                fontsize=9, color='#888888', ha='right', va='bottom',
                fontstyle='italic')
        ax.set_xlabel("x [mm]", fontsize=10, color=_t['ax_text'])
        ax.set_ylabel("y [mm]", fontsize=10, color=_t['ax_text'])
        ax.tick_params(labelsize=9, colors=_t['ax_text'], length=4, width=0.8)
        ax.set_aspect('auto')
        ax.grid(True, alpha=0.12, linewidth=0.4, color=_t['ax_text'])
        for sp in ax.spines.values():
            sp.set_edgecolor(_t['ax_spine']); sp.set_linewidth(0.8)
        # Zone boundaries
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

    # Spacing: tight within group, loose between groups
    window.canvas_temp.fig.subplots_adjust(left=0.08, right=0.93,
                                            top=0.96, bottom=0.06, hspace=0.34)
    window.canvas_temp.draw()
    # Store data for hover
    window.canvas_temp._hover_data = {
        'fields': [Ta, Tb, Ts],
        'names': ['T_fA', 'T_fB', 'T_s'],
        'unit': 'K',
        'L': L, 'H': H, 'Nx': N_x, 'Ny': N_y,
    }

    # Pressure plot (pass correct dP values)
    window.canvas_pres.plot_pressure(P_fA, P_fB, N_x, N_y, L, H, mode_label,
                                     dP_A=dP_A, dP_B=dP_B,
                                     dx_arr=r.get('dx_arr'), dy_arr=r.get('dy_arr'))
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
        cf = ax.contourf(X, Y, field, levels=512, cmap='turbo', norm=_vnorm)
        cb = window.canvas_vel.fig.colorbar(cf, ax=ax, shrink=0.9,
                                             aspect=25, format="%.1f")
        cb.ax.tick_params(labelsize=8, colors=_t['ax_text'], length=3)
        cb.ax.yaxis.set_major_locator(plt.MaxNLocator(nbins=7))
        cb.outline.set_edgecolor(_t['ax_spine'])
        ax.set_title(main_title, fontsize=13, fontweight="bold",
                     color=_t['ax_text'], loc='left', pad=6)
        ax.text(0.99, 1.02, subtitle, transform=ax.transAxes,
                fontsize=9, color='#888888', ha='right', va='bottom',
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
