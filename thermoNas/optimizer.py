"""
optimizer.py — Multi-objective optimization for TPMS heat exchanger zoning

Optimizes L and t parameters in inlet/outlet transition zones
using NSGA-II to find Pareto-optimal trade-offs between
heat transfer (Q) and pressure drop (dP).

Layout:
    y=100% ┌───┬───┬───┐
           │ 7 │ 8 │ 9 │  outlet transition (3×3)
    y=80%  ├───┴───┴───┤
           │  uniform   │  (fixed L₀, t₀)
    y=20%  ├───┬───┬───┤
           │ 1 │ 2 │ 3 │  inlet transition (3×3)
    y=0%   └───┴───┴───┘
           x=0  33  67 100%

Decision variables: 18 blocks × 2 params (L, t) = 36 variables
Objectives: minimize(-Q), minimize(dP)
"""

import os
import concurrent.futures
import numpy as np
import warnings
warnings.filterwarnings('ignore')

from zone_config import ZoneConfig
from solve_full import solve_full_domain
from simple_solver import SIMPLESolver
from tpms_calc import (compute as tpms_compute, geometry as tpms_geometry,
                       air_density, air_viscosity, adaptive_grid)

# NOTE: batch_runner.run_batch is NOT used here because its case-dict schema
# (L_cell_mm, t_wall_mm, u_air, T_Ain_C, …) is incompatible with the optimizer's
# 36-variable zoning vector.  Parallelism is implemented directly via
# concurrent.futures.ProcessPoolExecutor.
#
# Set THERMONAS_SERIAL=1 to force single-process execution (useful for debugging
# or when running inside a child process that already holds GIL-heavy resources).

def _parallel_workers():
    """Return number of parallel workers; 1 means serial (no subprocess overhead)."""
    if os.environ.get('THERMONAS_SERIAL') == '1':
        return 1
    return max(1, (os.cpu_count() or 2) - 1)


# ── Top-level worker functions (must be module-level for pickle on Windows) ──

def _eval_worker(args):
    """Worker: evaluate one design vector. Returns (Q_neg, dP, mass)."""
    x, cfg, use_richardson = args
    warnings.filterwarnings('ignore')
    if use_richardson:
        return evaluate_richardson(x, cfg)
    return evaluate(x, cfg)


def _solve_single_point_worker(args):
    """Worker: _solve_single_point for one design vector. Returns (Q, dP, mass)."""
    x, cfg, Nx, Ny = args
    warnings.filterwarnings('ignore')
    return _solve_single_point(x, cfg, Nx, Ny)


# ── Default configuration ────────────────────────────────────

DEFAULT_CONFIG = {
    'L_domain': 0.10,       # domain length [m]
    'H_domain': 0.05,       # domain height [m]
    # Nx, Ny: computed adaptively from D_h — see _resolve_grid()
    'tpms_type': 'Diamond',
    'k_s': 17.0,            # solid conductivity [W/(m K)]
    'u_A': 10.0,            # Fluid A velocity [m/s]
    'u_B': 10.0,            # Fluid B velocity [m/s]
    'T_inA': 350.0,         # Fluid A inlet temp [K]
    'T_inB': 300.0,         # Fluid B inlet temp [K]
    'cp_f': 1007.0,         # fluid specific heat [J/(kg K)]
    'rho_s': 2700.0,        # solid density [kg/m³]
    'L0': 6.0, 't0': 0.3,  # uniform zone params
    'y_trans': 0.2,         # transition zone fraction (each side)
    'dir_A': 0, 'dir_B': 3, # flow directions (+x, -y)
    'pipe_frac_A': 1.0,     # inlet width fraction for A
    'pipe_frac_B': 1.0,     # inlet width fraction for B
}


def _resolve_grid(cfg, alpha=0.8):
    """Return (Nx, Ny) from config, computing adaptively if not specified."""
    if 'Nx' in cfg and 'Ny' in cfg:
        return int(cfg['Nx']), int(cfg['Ny'])
    g = tpms_geometry(cfg['tpms_type'], cfg['L0'], cfg['t0'], cfg['k_s'])
    return adaptive_grid(cfg['L_domain'], cfg['H_domain'], g['D_h'], alpha)


# ── Grid cell builder ────────────────────────────────────────

def build_grid_cells(x, L0=6.0, t0=0.3, y_trans_inlet=0.2, y_trans_outlet=0.2,
                     opt_axis='y'):
    """Convert decision variable vector to grid_cells list.

    x: [L1,t1, L2,t2, ..., L18,t18]  (36 variables)
       x[0:18]  = inlet transition 3×3 (row-major)
       x[18:36] = outlet transition 3×3
    opt_axis: 'y' — zones along y-axis, 'x' — zones along x-axis
    """
    cells = []

    if opt_axis == 'y':
        # Along Y: inlet at bottom, outlet at top
        sy_in = y_trans_inlet / 3
        sy_out = y_trans_outlet / 3
        sx = 1.0 / 3

        # Inlet transition (y: 0 ~ y_trans_inlet)
        for iy in range(3):
            for ix in range(3):
                idx = (iy * 3 + ix) * 2
                cells.append({
                    'y0': iy * sy_in, 'y1': (iy + 1) * sy_in,
                    'x0': ix * sx, 'x1': (ix + 1) * sx,
                    'L': float(x[idx]), 't': float(x[idx + 1])
                })

        # Uniform zone
        cells.append({
            'y0': y_trans_inlet, 'y1': 1.0 - y_trans_outlet,
            'x0': 0.0, 'x1': 1.0,
            'L': L0, 't': t0
        })

        # Outlet transition (y: 1-y_trans_outlet ~ 1.0)
        for iy in range(3):
            for ix in range(3):
                idx = 18 + (iy * 3 + ix) * 2
                y_base = 1.0 - y_trans_outlet
                cells.append({
                    'y0': y_base + iy * sy_out, 'y1': y_base + (iy + 1) * sy_out,
                    'x0': ix * sx, 'x1': (ix + 1) * sx,
                    'L': float(x[idx]), 't': float(x[idx + 1])
                })
    else:
        # Along X: inlet at left, outlet at right
        sx_in = y_trans_inlet / 3
        sx_out = y_trans_outlet / 3
        sy = 1.0 / 3

        # Inlet transition (x: 0 ~ y_trans_inlet)
        for iy in range(3):
            for ix in range(3):
                idx = (iy * 3 + ix) * 2
                cells.append({
                    'y0': iy * sy, 'y1': (iy + 1) * sy,
                    'x0': ix * sx_in, 'x1': (ix + 1) * sx_in,
                    'L': float(x[idx]), 't': float(x[idx + 1])
                })

        # Uniform zone
        cells.append({
            'y0': 0.0, 'y1': 1.0,
            'x0': y_trans_inlet, 'x1': 1.0 - y_trans_outlet,
            'L': L0, 't': t0
        })

        # Outlet transition (x: 1-y_trans_outlet ~ 1.0)
        for iy in range(3):
            for ix in range(3):
                idx = 18 + (iy * 3 + ix) * 2
                x_base = 1.0 - y_trans_outlet
                cells.append({
                    'y0': iy * sy, 'y1': (iy + 1) * sy,
                    'x0': x_base + ix * sx_out, 'x1': x_base + (ix + 1) * sx_out,
                    'L': float(x[idx]), 't': float(x[idx + 1])
                })

    return cells


# ── SIMPLE velocity cache (multi-grid) ───────────────────────
_simple_cache = {}  # {cache_key: {ucA, vcA, ucB, vcB, rho_A, mu_A, ...}}


def _clear_simple_cache():
    """Clear SIMPLE cache between optimization runs."""
    global _simple_cache
    _simple_cache = {}


def _simple_var_density(cfg, rho_A_field, rho_B_field):
    """Run SIMPLE for both fluids with given 2D rho fields (per-design, no cache).
    Returns ucA, vcA, ucB, vcB in real coordinates.
    rho_A_field, rho_B_field have shape (Nx, Ny) in real coords.
    """
    L = cfg['L_domain']; H = cfg['H_domain']
    Nx, Ny = _resolve_grid(cfg)
    g = tpms_geometry(cfg['tpms_type'], cfg['L0'], cfg['t0'], cfg['k_s'])
    eps0 = g['epsilon']; r_h0 = g['D_h'] / 2.0
    T_inA = cfg['T_inA']; T_inB = cfg['T_inB']
    u_A = cfg['u_A']; u_B = cfg['u_B']
    mu_A = air_viscosity(T_inA); mu_B = air_viscosity(T_inB)

    # Fluid A: SIMPLE in (Ny, Nx) coords → transpose rho field
    rho_A_simple = rho_A_field.T.copy()  # (Ny, Nx) for SIMPLE
    sA = SIMPLESolver(H, L, Ny, Nx, cfg['tpms_type'], cfg['L0'], cfg['t0'],
                      eps0, r_h0, rho_A_simple, mu_A, T_inA,
                      cfg.get('pipe_lo_A', 0), cfg.get('pipe_hi_A', H), u_A,
                      outlet_lo=cfg.get('outlet_lo_A', 0),
                      outlet_hi=cfg.get('outlet_hi_A', H))
    sA.solve(max_iter=5000, tol=1e-5, verbose=False)
    _, v_mA = sA.get_wall_masked_velocity()
    ucA = (0.5 * (v_mA[:, :-1] + v_mA[:, 1:])).T  # (Nx, Ny)
    vcA = np.zeros((Nx, Ny))

    # Fluid B: SIMPLE in (Nx, Ny) coords, dir=3 → flip j
    rho_B_simple = rho_B_field[:, ::-1].copy()  # flip y for -y flow
    sB = SIMPLESolver(L, H, Nx, Ny, cfg['tpms_type'], cfg['L0'], cfg['t0'],
                      eps0, r_h0, rho_B_simple, mu_B, T_inB,
                      cfg.get('pipe_lo_B', 0), cfg.get('pipe_hi_B', L), u_B,
                      outlet_lo=cfg.get('outlet_lo_B', 0),
                      outlet_hi=cfg.get('outlet_hi_B', L))
    sB.solve(max_iter=5000, tol=1e-5, verbose=False)
    _, v_mB = sB.get_wall_masked_velocity()
    vcB = -(0.5 * (v_mB[:, :-1] + v_mB[:, 1:]))[:, ::-1]  # un-flip
    ucB = np.zeros((Nx, Ny))

    return ucA, vcA, ucB, vcB


def _compute_simple(cfg):
    """Compute SIMPLE velocity fields. Results cached by config key (supports multiple grids)."""
    L = cfg['L_domain']; H = cfg['H_domain']
    Nx, Ny = _resolve_grid(cfg)
    u_A = cfg['u_A']; u_B = cfg['u_B']
    T_inA = cfg['T_inA']; T_inB = cfg['T_inB']

    cache_key = (cfg['tpms_type'], cfg['L0'], cfg['t0'],
                 cfg['L_domain'], cfg['H_domain'],
                 Nx, Ny, u_A, u_B, T_inA, T_inB,
                 cfg.get('pipe_lo_A', 0.0), cfg.get('pipe_hi_A', H),
                 cfg.get('pipe_lo_B', 0.0), cfg.get('pipe_hi_B', L),
                 cfg.get('outlet_lo_A'), cfg.get('outlet_hi_A'),
                 cfg.get('outlet_lo_B'), cfg.get('outlet_hi_B'))

    if cache_key in _simple_cache:
        return _simple_cache[cache_key]

    g = tpms_geometry(cfg['tpms_type'], cfg['L0'], cfg['t0'], cfg['k_s'])
    eps0 = g['epsilon']; r_h0 = g['D_h'] / 2.0
    rho_A = air_density(T_inA, 101325.0); mu_A = air_viscosity(T_inA)
    rho_B = air_density(T_inB, 101325.0); mu_B = air_viscosity(T_inB)

    # Fluid A: flows +x, SIMPLE axis is x (W=H, H=L, Ny_sim=Nx)
    pipe_lo_A = cfg.get('pipe_lo_A', 0.0)
    pipe_hi_A = cfg.get('pipe_hi_A', H)
    out_lo_A = cfg.get('outlet_lo_A', pipe_lo_A)
    out_hi_A = cfg.get('outlet_hi_A', pipe_hi_A)
    sA = SIMPLESolver(H, L, Ny, Nx, cfg['tpms_type'], cfg['L0'], cfg['t0'],
                      eps0, r_h0, rho_A, mu_A, T_inA, pipe_lo_A, pipe_hi_A, u_A,
                      outlet_lo=out_lo_A, outlet_hi=out_hi_A)
    sA.solve(max_iter=5000, tol=1e-5, verbose=False)
    _, v_mA = sA.get_wall_masked_velocity()
    ucA = (0.5 * (v_mA[:, :-1] + v_mA[:, 1:])).T
    vcA = np.zeros((Nx, Ny))

    # Fluid B: flows -y, SIMPLE axis is y (W=L, H=H)
    pipe_lo_B = cfg.get('pipe_lo_B', 0.0)
    pipe_hi_B = cfg.get('pipe_hi_B', L)
    out_lo_B = cfg.get('outlet_lo_B', pipe_lo_B)
    out_hi_B = cfg.get('outlet_hi_B', pipe_hi_B)
    sB = SIMPLESolver(L, H, Nx, Ny, cfg['tpms_type'], cfg['L0'], cfg['t0'],
                      eps0, r_h0, rho_B, mu_B, T_inB, pipe_lo_B, pipe_hi_B, u_B,
                      outlet_lo=out_lo_B, outlet_hi=out_hi_B)
    sB.solve(max_iter=5000, tol=1e-5, verbose=False)
    _, v_mB = sB.get_wall_masked_velocity()
    vcB = -(0.5 * (v_mB[:, :-1] + v_mB[:, 1:]))[:, ::-1]
    ucB = np.zeros((Nx, Ny))

    entry = {
        'ucA': ucA, 'vcA': vcA, 'ucB': ucB, 'vcB': vcB,
        'rho_A': rho_A, 'mu_A': mu_A, 'rho_B': rho_B, 'mu_B': mu_B,
    }
    _simple_cache[cache_key] = entry
    return entry


# ── Objective function ───────────────────────────────────────

def evaluate(x, config=None):
    """Evaluate a single design point.

    Parameters
    ----------
    x : array-like, shape (36,)
        [L1,t1, ..., L18,t18] for inlet + outlet transition zones
    config : dict, optional
        Override DEFAULT_CONFIG entries

    Returns
    -------
    Q_neg : float — negative total heat transfer (minimize = maximize Q)
    dP    : float — total pressure drop [Pa]
    mass  : float — total solid mass per unit depth [kg/m]
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}

    L = cfg['L_domain']; H = cfg['H_domain']
    Nx, Ny = _resolve_grid(cfg)
    cfg['Nx'] = Nx; cfg['Ny'] = Ny  # ensure downstream sees resolved values
    u_A = cfg['u_A']; u_B = cfg['u_B']
    T_inA = cfg['T_inA']; T_inB = cfg['T_inB']
    cp_f = cfg['cp_f']

    # 1-2. Build property arrays (continuous or discrete)
    if cfg.get('use_continuous', True):
        from sigmoid_field import build_continuous_arrays, get_geometry_lut
        lut = get_geometry_lut(cfg['tpms_type'])
        za = build_continuous_arrays(
            x, cfg['L0'], cfg['t0'],
            cfg.get('y_trans_inlet', cfg.get('y_trans', 0.2)),
            cfg.get('y_trans_outlet', cfg.get('y_trans', 0.2)),
            Nx, Ny, L, H,
            cfg['tpms_type'], cfg['k_s'],
            u_A, u_B, T_inA, T_inB,
            lut,
            sigmoid_width_y=cfg.get('sigmoid_width_y', 0.02),
            sigmoid_width_x=cfg.get('sigmoid_width_x', 0.05),
            fix_L=cfg.get('fix_L', False),
            fix_t=cfg.get('fix_t', False),
            opt_axis=cfg.get('opt_axis', 'y'))
    else:
        grid_cells = build_grid_cells(x, cfg['L0'], cfg['t0'],
                                      cfg.get('y_trans_inlet', cfg.get('y_trans', 0.2)),
                                      cfg.get('y_trans_outlet', cfg.get('y_trans', 0.2)),
                                      cfg.get('opt_axis', 'y'))
        za = ZoneConfig.build_grid_arrays(
            Nx, Ny, L, H, grid_cells,
            cfg['tpms_type'], cfg['k_s'],
            u_A, u_B, T_inA, T_inB)

    # 3. SIMPLE velocity fields (CACHED — computed once per optimization run)
    sc = _compute_simple(cfg)
    ucA = sc['ucA']; vcA = sc['vcA']
    ucB = sc['ucB']; vcB = sc['vcB']
    rho_A = sc['rho_A']; mu_A = sc['mu_A']
    rho_B = sc['rho_B']; mu_B = sc['mu_B']

    # 4. Energy solve with per-cell rho(T)*cp(T) coupling
    #    + variable density SIMPLE re-run after first energy iteration
    from tpms_calc import air_cp
    P_in = 101325.0
    rcp_A = air_density(T_inA, P_in) * air_cp(T_inA)
    rcp_B = air_density(T_inB, P_in) * air_cp(T_inB)
    Ta = Tb = Ts = None
    rho_A_field = np.full((Nx, Ny), air_density(T_inA, P_in))
    rho_B_field = np.full((Nx, Ny), air_density(T_inB, P_in))
    for _ci in range(3):
        Ta, Tb, Ts = solve_full_domain(
            L, H, Nx, Ny, T_inA, T_inB,
            za['K_ffA_arr'], za['K_ffB_arr'], za['K_ss_arr'],
            za['h_vA_arr'], za['h_vB_arr'],
            rcp_A, rcp_B,
            za['eps_arr'], ucA, vcA, ucB, vcB,
            cfg['dir_A'], cfg['dir_B'],
            tol=0.5, max_iter=5000,
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts)
        # Update rho fields from temperature
        rho_A_new = air_density(Ta, P_in)
        rho_B_new = air_density(Tb, P_in)
        drho = max(float(np.max(np.abs(rho_A_new - rho_A_field)) / rho_A_field.mean()),
                   float(np.max(np.abs(rho_B_new - rho_B_field)) / rho_B_field.mean()))
        if drho < 0.01:
            break
        rho_A_field = 0.7 * rho_A_new + 0.3 * rho_A_field
        rho_B_field = 0.7 * rho_B_new + 0.3 * rho_B_field
        rcp_A = 0.7 * rho_A_new * air_cp(Ta) + 0.3 * rcp_A
        rcp_B = 0.7 * rho_B_new * air_cp(Tb) + 0.3 * rcp_B
        # Re-run SIMPLE with variable rho field (per-design)
        ucA, vcA, ucB, vcB = _simple_var_density(cfg, rho_A_field, rho_B_field)

    # 5. Compute objectives (non-uniform cell areas)
    from simple_solver import _aligned_grid
    _dx_e = _aligned_grid(Nx, L, [])  # uniform for optimizer coarse grid
    _dy_e = _aligned_grid(Ny, H, [])
    _cell_area = _dx_e[:, None] * _dy_e[None, :]

    Q_total = np.sum(za['h_vB_arr'] * (Ts - Tb) * _cell_area)

    # Pressure drop
    if cfg.get('use_continuous', True) and 'L_field' in za:
        from sigmoid_field import compute_dP_continuous
        D_h_arr = 2.0 * za['eps_arr'] / (za['A_0_arr'] + 1e-30)
        dP_A_c, dP_B_c = compute_dP_continuous(
            za['L_field'], za['t_field'], za['eps_arr'], D_h_arr,
            u_A, u_B, rho_A, rho_B, mu_A, mu_B,
            cfg['tpms_type'], L, H, Nx, Ny, T_inA, T_inB)
        dP_total = dP_A_c + dP_B_c
    else:
        from tpms_calc import friction_factor, P_atm
        rho_ref_A = air_density(T_inA, P_atm)
        rho_ref_B = air_density(T_inB, P_atm)
        dP_A_total = 0.0; dP_B_total = 0.0
        _geom_cache = {}
        for gc in grid_cells:
            _gkey = (gc['L'], gc['t'])
            if _gkey not in _geom_cache:
                _geom_cache[_gkey] = tpms_geometry(cfg['tpms_type'], gc['L'], gc['t'], cfg['k_s'])
            g_loc = _geom_cache[_gkey]
            eps_loc = g_loc['epsilon']; r_h_loc = g_loc['D_h'] / 2.0
            zone_Lx = (gc['x1'] - gc['x0']) * L
            zone_Ly = (gc['y1'] - gc['y0']) * H
            Re_A = max(rho_ref_A * u_A * r_h_loc / mu_A, 10.0)
            f_A = friction_factor(cfg['tpms_type'], Re_A, eps_loc, gc['t'], gc['L'])
            dP_A_total += f_A * rho_A * u_A**2 / (2.0 * r_h_loc) * zone_Lx
            Re_B = max(rho_ref_B * u_B * r_h_loc / mu_B, 10.0)
            f_B = friction_factor(cfg['tpms_type'], Re_B, eps_loc, gc['t'], gc['L'])
            dP_B_total += f_B * rho_B * u_B**2 / (2.0 * r_h_loc) * zone_Ly
        dP_total = dP_A_total + dP_B_total

    # Mass: sum of (1-eps) * rho_s * cell_volume over all cells
    mass = np.sum((1.0 - za['eps_arr']) * cfg['rho_s'] * _cell_area)

    return -Q_total, dP_total, mass


def evaluate_richardson(x, config=None):
    """Evaluate using Richardson extrapolation on two grid levels.

    Coarse grid (Nx, Ny): full rho*cp coupling → Q_coarse + converged rA, rB.
    Fine grid (2Nx, 2Ny): single energy solve with coarse-grid rA, rB → Q_fine.
    Result: Q_extrap = 2*Q_fine - Q_coarse (first-order, ratio=2).
    dP and mass are grid-independent (from f-Re and volume integral).
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    L = cfg['L_domain']; H = cfg['H_domain']
    Nx_c, Ny_c = _resolve_grid(cfg)
    cfg['Nx'] = Nx_c; cfg['Ny'] = Ny_c
    Nx_f = Nx_c * 2;  Ny_f = Ny_c * 2
    u_A = cfg['u_A']; u_B = cfg['u_B']
    T_inA = cfg['T_inA']; T_inB = cfg['T_inB']
    cp_f = cfg['cp_f']
    P_in = 101325.0

    # Build arrays helper
    from tpms_calc import air_cp
    _y_trans_in = cfg.get('y_trans_inlet', cfg.get('y_trans', 0.2))
    _y_trans_out = cfg.get('y_trans_outlet', cfg.get('y_trans', 0.2))

    def _build_za(nx, ny):
        if cfg.get('use_continuous', True):
            from sigmoid_field import build_continuous_arrays, get_geometry_lut
            lut = get_geometry_lut(cfg['tpms_type'])
            return build_continuous_arrays(
                x, cfg['L0'], cfg['t0'], _y_trans_in, _y_trans_out,
                nx, ny, L, H, cfg['tpms_type'], cfg['k_s'],
                u_A, u_B, T_inA, T_inB, lut,
                sigmoid_width_y=cfg.get('sigmoid_width_y', 0.02),
                sigmoid_width_x=cfg.get('sigmoid_width_x', 0.05),
                fix_L=cfg.get('fix_L', False),
                fix_t=cfg.get('fix_t', False),
                opt_axis=cfg.get('opt_axis', 'y'))
        else:
            gc = build_grid_cells(x, cfg['L0'], cfg['t0'],
                                  _y_trans_in, _y_trans_out, cfg.get('opt_axis', 'y'))
            return ZoneConfig.build_grid_arrays(
                nx, ny, L, H, gc, cfg['tpms_type'], cfg['k_s'],
                u_A, u_B, T_inA, T_inB)

    # ── Coarse grid: full per-cell rho*cp coupling ──
    za_c = _build_za(Nx_c, Ny_c)
    sc_c = _compute_simple(cfg)
    rcp_A = air_density(T_inA, P_in) * air_cp(T_inA)
    rcp_B = air_density(T_inB, P_in) * air_cp(T_inB)
    rA_avg, rB_avg = sc_c['rho_A'], sc_c['rho_B']
    Ta_c = Tb_c = Ts_c = None
    for _ci in range(3):
        Ta_c, Tb_c, Ts_c = solve_full_domain(
            L, H, Nx_c, Ny_c, T_inA, T_inB,
            za_c['K_ffA_arr'], za_c['K_ffB_arr'], za_c['K_ss_arr'],
            za_c['h_vA_arr'], za_c['h_vB_arr'],
            rcp_A, rcp_B,
            za_c['eps_arr'], sc_c['ucA'], sc_c['vcA'], sc_c['ucB'], sc_c['vcB'],
            cfg['dir_A'], cfg['dir_B'],
            tol=0.5, max_iter=5000,
            Ta_init=Ta_c, Tb_init=Tb_c, Ts_init=Ts_c)
        rA_new = air_density(float(Ta_c.mean()), P_in)
        rB_new = air_density(float(Tb_c.mean()), P_in)
        if abs(rA_new - rA_avg) / rA_avg < 0.01 and abs(rB_new - rB_avg) / rB_avg < 0.01:
            break
        rcp_A = 0.7 * air_density(Ta_c, P_in) * air_cp(Ta_c) + 0.3 * rcp_A
        rcp_B = 0.7 * air_density(Tb_c, P_in) * air_cp(Tb_c) + 0.3 * rcp_B
        rA_avg = 0.7 * rA_new + 0.3 * rA_avg
        rB_avg = 0.7 * rB_new + 0.3 * rB_avg

    from simple_solver import _aligned_grid
    _dx_c = _aligned_grid(Nx_c, L, [])
    _dy_c = _aligned_grid(Ny_c, H, [])
    _area_c = _dx_c[:, None] * _dy_c[None, :]
    Q_coarse = np.sum(za_c['h_vB_arr'] * (Ts_c - Tb_c) * _area_c)

    # ── Fine grid: single energy solve with coarse-grid rho*cp ──
    from scipy.ndimage import zoom
    rcp_A_f = zoom(rcp_A if np.ndim(rcp_A) > 0 else np.full((Nx_c, Ny_c), float(rcp_A)), 2, order=1)
    rcp_B_f = zoom(rcp_B if np.ndim(rcp_B) > 0 else np.full((Nx_c, Ny_c), float(rcp_B)), 2, order=1)

    cfg_f = {**cfg, 'Nx': Nx_f, 'Ny': Ny_f}
    za_f = _build_za(Nx_f, Ny_f)
    sc_f = _compute_simple(cfg_f)
    Ta_f, Tb_f, Ts_f = solve_full_domain(
        L, H, Nx_f, Ny_f, T_inA, T_inB,
        za_f['K_ffA_arr'], za_f['K_ffB_arr'], za_f['K_ss_arr'],
        za_f['h_vA_arr'], za_f['h_vB_arr'],
        rcp_A_f, rcp_B_f,
        za_f['eps_arr'], sc_f['ucA'], sc_f['vcA'], sc_f['ucB'], sc_f['vcB'],
        cfg['dir_A'], cfg['dir_B'],
        tol=0.5, max_iter=5000)

    _dx_f = _aligned_grid(Nx_f, L, [])
    _dy_f = _aligned_grid(Ny_f, H, [])
    _area_f = _dx_f[:, None] * _dy_f[None, :]
    Q_fine = np.sum(za_f['h_vB_arr'] * (Ts_f - Tb_f) * _area_f)

    # ── Richardson extrapolation (first-order, ratio=2) ──
    Q_extrap = 2.0 * Q_fine - Q_coarse

    # ── dP and mass ──
    rho_A = sc_c['rho_A']; mu_A = sc_c['mu_A']
    rho_B = sc_c['rho_B']; mu_B = sc_c['mu_B']

    if cfg.get('use_continuous', True) and 'L_field' in za_c:
        from sigmoid_field import compute_dP_continuous
        D_h_c = 2.0 * za_c['eps_arr'] / (za_c['A_0_arr'] + 1e-30)
        dP_A_c, dP_B_c = compute_dP_continuous(
            za_c['L_field'], za_c['t_field'], za_c['eps_arr'], D_h_c,
            u_A, u_B, rho_A, rho_B, mu_A, mu_B,
            cfg['tpms_type'], L, H, Nx_c, Ny_c, T_inA, T_inB)
        dP_total = dP_A_c + dP_B_c
    else:
        from tpms_calc import friction_factor, P_atm
        rho_ref_A = air_density(T_inA, P_atm)
        rho_ref_B = air_density(T_inB, P_atm)
        grid_cells = build_grid_cells(x, cfg['L0'], cfg['t0'],
                                      _y_trans_in, _y_trans_out, cfg.get('opt_axis', 'y'))
        dP_A_total = 0.0; dP_B_total = 0.0
        _geom_cache = {}
        for gc in grid_cells:
            _gkey = (gc['L'], gc['t'])
            if _gkey not in _geom_cache:
                _geom_cache[_gkey] = tpms_geometry(cfg['tpms_type'], gc['L'], gc['t'], cfg['k_s'])
            g_loc = _geom_cache[_gkey]
            eps_loc = g_loc['epsilon']; r_h_loc = g_loc['D_h'] / 2.0
            zone_Lx = (gc['x1'] - gc['x0']) * L
            zone_Ly = (gc['y1'] - gc['y0']) * H
            Re_A = max(rho_ref_A * u_A * r_h_loc / mu_A, 10.0)
            f_A = friction_factor(cfg['tpms_type'], Re_A, eps_loc, gc['t'], gc['L'])
            dP_A_total += f_A * rho_A * u_A**2 / (2.0 * r_h_loc) * zone_Lx
            Re_B = max(rho_ref_B * u_B * r_h_loc / mu_B, 10.0)
            f_B = friction_factor(cfg['tpms_type'], Re_B, eps_loc, gc['t'], gc['L'])
            dP_B_total += f_B * rho_B * u_B**2 / (2.0 * r_h_loc) * zone_Ly
        dP_total = dP_A_total + dP_B_total

    mass = np.sum((1.0 - za_c['eps_arr']) * cfg['rho_s'] * _area_c)

    return -Q_extrap, dP_total, mass


# ── pymoo Problem ────────────────────────────────────────────

# Shared progress counter (thread-safe via GIL for simple int)
_progress = {'count': 0, 'total': 0, 'best_Q': 0.0,
             'phase': 'optimize', 'reeval_count': 0, 'reeval_total': 0}


def _make_problem(config=None):
    from pymoo.core.problem import Problem

    cfg = {**DEFAULT_CONFIG, **(config or {})}
    n_var = 36
    n_obj = 2  # -Q, dP

    # Bounds: L ∈ [4,8], t ∈ [0.3,0.5], alternating
    xl = np.array([4.0, 0.3] * 18)
    xu = np.array([8.0, 0.5] * 18)

    use_richardson = cfg.get('use_richardson', True)

    class TPMSProblem(Problem):
        def __init__(self):
            super().__init__(n_var=n_var, n_obj=n_obj, xl=xl, xu=xu)

        def _evaluate(self, X, out, *args, **kwargs):
            F = np.empty((len(X), n_obj))
            n_workers = _parallel_workers()

            if n_workers > 1 and len(X) > 1:
                # Parallel path: each design vector is evaluated in a separate
                # worker process.  _eval_worker is a module-level function so
                # it can be pickled by multiprocessing on Windows (spawn).
                task_args = [(x, cfg, use_richardson) for x in X]
                with concurrent.futures.ProcessPoolExecutor(
                        max_workers=min(n_workers, len(X))) as pool:
                    for i, (Q_neg, dP, mass) in enumerate(
                            pool.map(_eval_worker, task_args)):
                        F[i] = [Q_neg, dP]
                        _progress['count'] += 1
                        if -Q_neg > _progress['best_Q']:
                            _progress['best_Q'] = -Q_neg
            else:
                # Serial path (THERMONAS_SERIAL=1 or single candidate)
                eval_fn = evaluate_richardson if use_richardson else evaluate
                for i, x in enumerate(X):
                    Q_neg, dP, mass = eval_fn(x, cfg)
                    F[i] = [Q_neg, dP]
                    _progress['count'] += 1
                    if -Q_neg > _progress['best_Q']:
                        _progress['best_Q'] = -Q_neg

            out["F"] = F

    return TPMSProblem()


# ── Run optimization ─────────────────────────────────────────

def _solve_single_point(x, cfg, Nx, Ny):
    """Full physical solve for a single design point at given grid resolution.

    Returns (Q, dP_A, dP_B) with SIMPLE-based ΔP.
    """
    from sigmoid_field import build_continuous_arrays, get_geometry_lut
    from tpms_calc import air_cp

    L = cfg['L_domain']; H = cfg['H_domain']
    tpms_type = cfg['tpms_type']; k_s = cfg['k_s']
    u_A = cfg['u_A']; u_B = cfg['u_B']
    T_inA = cfg['T_inA']; T_inB = cfg['T_inB']
    L0 = cfg['L0']; t0 = cfg['t0']
    P_in = 101325.0

    lut = get_geometry_lut(tpms_type)
    g0 = tpms_geometry(tpms_type, L0, t0, k_s)
    eps0 = g0['epsilon']; r_h0 = g0['D_h'] / 2.0

    # 1. Sigmoid continuous property arrays
    za = build_continuous_arrays(
        x, L0, t0,
        cfg.get('y_trans_inlet', 0.2), cfg.get('y_trans_outlet', 0.2),
        Nx, Ny, L, H, tpms_type, k_s,
        u_A, u_B, T_inA, T_inB, lut,
        fix_L=cfg.get('fix_L', False), fix_t=cfg.get('fix_t', False))

    # 2. SIMPLE
    rho_A = air_density(T_inA, P_in); mu_A = air_viscosity(T_inA)
    rho_B = air_density(T_inB, P_in); mu_B = air_viscosity(T_inB)

    sA = SIMPLESolver(H, L, Ny, Nx, tpms_type, L0, t0,
                      eps0, r_h0, rho_A, mu_A, T_inA,
                      cfg.get('pipe_lo_A', 0.0), cfg.get('pipe_hi_A', H), u_A,
                      outlet_lo=cfg.get('outlet_lo_A'), outlet_hi=cfg.get('outlet_hi_A'))
    sA.solve(max_iter=5000, tol=1e-5, verbose=False)
    _, v_mA = sA.get_wall_masked_velocity()
    ucA = (0.5 * (v_mA[:, :-1] + v_mA[:, 1:])).T
    vcA = np.zeros((Nx, Ny))

    sB = SIMPLESolver(L, H, Nx, Ny, tpms_type, L0, t0,
                      eps0, r_h0, rho_B, mu_B, T_inB,
                      cfg.get('pipe_lo_B', 0.0), cfg.get('pipe_hi_B', L), u_B,
                      outlet_lo=cfg.get('outlet_lo_B'), outlet_hi=cfg.get('outlet_hi_B'))
    sB.solve(max_iter=5000, tol=1e-5, verbose=False)
    _, v_mB = sB.get_wall_masked_velocity()
    vcB = -(0.5 * (v_mB[:, :-1] + v_mB[:, 1:]))[:, ::-1]
    ucB = np.zeros((Nx, Ny))

    # 3. Energy solve with ρ*cp coupling
    rcp_A = air_density(T_inA, P_in) * air_cp(T_inA)
    rcp_B = air_density(T_inB, P_in) * air_cp(T_inB)
    Ta = Tb = Ts = None
    for _ci in range(3):
        Ta, Tb, Ts = solve_full_domain(
            L, H, Nx, Ny, T_inA, T_inB,
            za['K_ffA_arr'], za['K_ffB_arr'], za['K_ss_arr'],
            za['h_vA_arr'], za['h_vB_arr'],
            rcp_A, rcp_B,
            za['eps_arr'], ucA, vcA, ucB, vcB,
            cfg.get('dir_A', 0), cfg.get('dir_B', 3),
            tol=0.5, max_iter=5000,
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts)
        rA_new = air_density(float(Ta.mean()), P_in)
        rB_new = air_density(float(Tb.mean()), P_in)
        if abs(rA_new - float(np.mean(rcp_A / air_cp(Ta) if np.ndim(rcp_A) > 0 else rcp_A / air_cp(T_inA)))) / rA_new < 0.01:
            break
        rcp_A = 0.7 * air_density(Ta, P_in) * air_cp(Ta) + 0.3 * rcp_A
        rcp_B = 0.7 * air_density(Tb, P_in) * air_cp(Tb) + 0.3 * rcp_B

    # 4. Q and ΔP
    from simple_solver import _aligned_grid
    _dx_sp = _aligned_grid(Nx, L, [])
    _dy_sp = _aligned_grid(Ny, H, [])
    _area_sp = _dx_sp[:, None] * _dy_sp[None, :]
    Q = float(np.sum(za['h_vB_arr'] * (Ts - Tb) * _area_sp))

    # ΔP: per-cell f-Re integration from continuous field
    from sigmoid_field import compute_dP_continuous
    D_h_arr = 2.0 * za['eps_arr'] / (za['A_0_arr'] + 1e-30)
    dP_A, dP_B = compute_dP_continuous(
        za['L_field'], za['t_field'], za['eps_arr'], D_h_arr,
        u_A, u_B, rho_A, rho_B, mu_A, mu_B,
        tpms_type, L, H, Nx, Ny, T_inA, T_inB)

    return Q, dP_A + dP_B, 0.0


def reevaluate_pareto(X, config=None, Nx_fine=None, Ny_fine=None,
                      progress_cb=None):
    """Re-evaluate Pareto front with Richardson extrapolation.

    Two grid levels (Nx_fine × Ny_fine and 2× that) for grid-independent Q.
    ΔP uses f-Re integration (grid-independent).
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    if Nx_fine is None or Ny_fine is None:
        Nx_fine, Ny_fine = _resolve_grid(cfg, alpha=0.4)
    Nx_c, Ny_c = Nx_fine, Ny_fine
    Nx_f, Ny_f = Nx_fine * 2, Ny_fine * 2

    N = len(X)
    F_fine = np.empty((N, 2))
    n_workers = _parallel_workers()

    if n_workers > 1 and N > 1:
        # Parallel path: evaluate all Pareto points at both grid levels using
        # _solve_single_point_worker (module-level, picklable on Windows spawn).
        # Coarse and fine passes run as two separate pool.map calls so that each
        # task dict is a plain tuple with no closure state.
        coarse_args = [(x, cfg, Nx_c, Ny_c) for x in X]
        fine_args   = [(x, cfg, Nx_f, Ny_f) for x in X]
        with concurrent.futures.ProcessPoolExecutor(
                max_workers=min(n_workers, N)) as pool:
            coarse_results = list(pool.map(_solve_single_point_worker, coarse_args))
            fine_results   = list(pool.map(_solve_single_point_worker, fine_args))
        for idx in range(N):
            Q_c, dP_c, _ = coarse_results[idx]
            Q_f, dP_f, _ = fine_results[idx]
            F_fine[idx] = [-(2.0 * Q_f - Q_c), dP_f]
            if progress_cb:
                progress_cb(idx + 1, N)
    else:
        # Serial path
        for idx, x in enumerate(X):
            Q_c, dP_c, _ = _solve_single_point(x, cfg, Nx_c, Ny_c)
            Q_f, dP_f, _ = _solve_single_point(x, cfg, Nx_f, Ny_f)
            F_fine[idx] = [-(2.0 * Q_f - Q_c), dP_f]
            if progress_cb:
                progress_cb(idx + 1, N)

    return F_fine


def _save_pareto_csv(path, X, F):
    """Save current Pareto front to CSV."""
    with open(path, 'w') as f:
        cols = ['Q_total_W_m', 'dP_total_Pa']
        for i in range(18):
            zone = 'inlet' if i < 9 else 'outlet'
            idx = i if i < 9 else i - 9
            cols += [f'{zone}_{idx}_L_mm', f'{zone}_{idx}_t_mm']
        f.write(','.join(cols) + '\n')
        for i in range(len(X)):
            row = [f"{-F[i,0]:.2f}", f"{F[i,1]:.2f}"]
            for v in X[i]:
                row.append(f"{v:.3f}")
            f.write(','.join(row) + '\n')


def run_optimization(config=None, n_gen=100, pop_size=40, seed=42,
                     verbose=True, save_dir=None, algorithm='nsga2'):
    """Run multi-objective optimization.

    Parameters
    ----------
    config    : dict, optional — override DEFAULT_CONFIG
    n_gen     : int — number of generations
    pop_size  : int — population size per generation
    seed      : int — random seed
    verbose   : bool — print progress
    algorithm : str — 'nsga2' (default), 'moead', or 'qnehvi'
    callback  : callable(gen, n_gen, pop) — called each generation

    Returns
    -------
    dict with keys:
        X : (N, 36) — Pareto-optimal decision variables
        F : (N, 2)  — objective values [-Q, dP]
        n_evals : int — total evaluations
    """
    import os, json, time
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.termination import get_termination
    from pymoo.optimize import minimize
    from pymoo.core.callback import Callback

    _progress['count'] = 0
    _progress['total'] = n_gen * pop_size
    _progress['best_Q'] = 0.0
    _progress['phase'] = 'optimize'
    _progress['reeval_count'] = 0
    _progress['reeval_total'] = 0

    # Create save directory with descriptive name
    if save_dir is None:
        cfg_save = {**DEFAULT_CONFIG, **(config or {})}
        code_dir = os.path.dirname(os.path.abspath(__file__))
        folder_name = (
            f"{cfg_save['tpms_type']}"
            f"_L{cfg_save['L_domain']*1000:.0f}xH{cfg_save['H_domain']*1000:.0f}mm"
            f"_uA{cfg_save['u_A']:.0f}_uB{cfg_save['u_B']:.0f}"
            f"_TinA{cfg_save['T_inA']:.0f}_TinB{cfg_save['T_inB']:.0f}"
            f"_L0{cfg_save['L0']}_t0{cfg_save['t0']}"
            f"_gen{n_gen}_pop{pop_size}"
            f"_{time.strftime('%m%d_%H%M')}"
        )
        save_dir = os.path.join(code_dir, "CSVdata", folder_name)
    os.makedirs(save_dir, exist_ok=True)

    # Save config
    if 'cfg_save' not in dir():
        cfg_save = {**DEFAULT_CONFIG, **(config or {})}
    with open(os.path.join(save_dir, "config.json"), 'w') as f:
        json.dump(cfg_save, f, indent=2)

    # Callback: save Pareto front after each generation
    class SaveCallback(Callback):
        def __init__(self):
            super().__init__()
            self._save_dir = save_dir

        def notify(self, algorithm):
            gen = algorithm.n_gen
            opt = algorithm.opt
            if opt is not None and len(opt) > 0:
                X = opt.get("X")
                F = opt.get("F")
                path = os.path.join(self._save_dir, f"pareto_gen{gen:04d}.csv")
                _save_pareto_csv(path, X, F)
                # Also save as "latest"
                _save_pareto_csv(os.path.join(self._save_dir, "pareto_latest.csv"), X, F)

    cfg_final = {**DEFAULT_CONFIG, **(config or {})}
    # Resolve adaptive grid and store in config for downstream use
    Nx_c, Ny_c = _resolve_grid(cfg_final)
    cfg_final['Nx'] = Nx_c; cfg_final['Ny'] = Ny_c
    _clear_simple_cache()

    # Pre-warm SIMPLE caches for both grid levels
    if cfg_final.get('use_richardson', True):
        _compute_simple(cfg_final)
        _compute_simple({**cfg_final, 'Nx': Nx_c * 2, 'Ny': Ny_c * 2})
        if verbose:
            print(f"[Optimizer] SIMPLE cached at {Nx_c}×{Ny_c} and {Nx_c*2}×{Ny_c*2}")
    else:
        _compute_simple(cfg_final)

    problem = _make_problem(config)

    # Dispatch to algorithm
    if algorithm == 'qnehvi':
        # Bayesian optimization via BoTorch — separate code path, returns early
        from optimizer_botorch import run_botorch_optimization
        return run_botorch_optimization(config, n_init=50, n_iter=60, q_batch=4,
                                         seed=seed, verbose=verbose, save_dir=save_dir)
    elif algorithm == 'moead':
        from pymoo.algorithms.moo.moead import MOEAD
        from pymoo.util.ref_dirs import get_reference_directions
        ref_dirs = get_reference_directions("uniform", 2, n_partitions=pop_size - 1)
        algo = MOEAD(ref_dirs=ref_dirs)
        algo_name = "MOEA/D"
    else:  # 'nsga2'
        algo = NSGA2(pop_size=pop_size)
        algo_name = "NSGA-II"
    termination = get_termination("n_gen", n_gen)

    if verbose:
        total = n_gen * pop_size
        mode = "Richardson (coarse + fine)" if cfg_final.get('use_richardson', True) else "Standard"
        print(f"[Optimizer] Starting {algo_name}: {n_gen} gen × {pop_size} pop = {total} evals [{mode}]")
        print(f"[Optimizer] Saving to: {save_dir}")

    res = minimize(problem, algo, termination, seed=seed,
                   verbose=verbose, callback=SaveCallback())

    # Final save (optimizer-grid values)
    _save_pareto_csv(os.path.join(save_dir, "pareto_final.csv"), res.X, res.F)

    result = {
        'X': res.X,
        'F': res.F,
        'n_evals': res.algorithm.evaluator.n_eval,
        'save_dir': save_dir,
    }

    if verbose:
        print(f"[Optimizer] Done. {len(res.X)} Pareto solutions found.")
        print(f"  Q range:  [{-res.F[:,0].max():.0f}, {-res.F[:,0].min():.0f}] W/m")
        print(f"  dP range: [{res.F[:,1].min():.0f}, {res.F[:,1].max():.0f}] Pa")

    # Post-optimization Pareto re-evaluation at fine grid
    if cfg_final.get('reeval_pareto', True):
        if 'reeval_Nx' in cfg_final and 'reeval_Ny' in cfg_final:
            Nx_re, Ny_re = cfg_final['reeval_Nx'], cfg_final['reeval_Ny']
        else:
            Nx_re, Ny_re = _resolve_grid(cfg_final, alpha=0.4)
        n_pareto = len(res.X)
        if verbose:
            print(f"[Optimizer] Re-evaluating {n_pareto} Pareto solutions at {Nx_re}×{Ny_re}...")

        _progress['phase'] = 'reeval'
        _progress['reeval_total'] = n_pareto

        def _reeval_cb(i, n):
            _progress['reeval_count'] = i

        F_fine = reevaluate_pareto(res.X, config, Nx_re, Ny_re, _reeval_cb)
        _save_pareto_csv(os.path.join(save_dir, "pareto_final_fine.csv"), res.X, F_fine)

        result['F_coarse'] = res.F.copy()
        result['F'] = F_fine

        if verbose:
            print(f"  Fine Q range:  [{-F_fine[:,0].max():.0f}, {-F_fine[:,0].min():.0f}] W/m")
            print(f"  Fine dP range: [{F_fine[:,1].min():.0f}, {F_fine[:,1].max():.0f}] Pa")

    if verbose:
        print(f"  Results in: {save_dir}")

    return result


# ── Visualization ────────────────────────────────────────────

def plot_pareto(result, save_path=None):
    """Plot Pareto front from optimization result."""
    import matplotlib.pyplot as plt

    F = result['F']
    Q = -F[:, 0]   # restore positive Q
    dP = F[:, 1]

    fig, ax = plt.subplots(figsize=(8, 6))
    sc = ax.scatter(dP, Q, c=Q/dP, cmap='viridis', s=40, edgecolors='#333', linewidths=0.5)
    ax.set_xlabel('Total Pressure Drop ΔP [Pa]', fontsize=12)
    ax.set_ylabel('Total Heat Transfer Q [W/m]', fontsize=12)
    ax.set_title('Pareto Front: Q vs ΔP', fontsize=14, fontweight='bold')
    cb = fig.colorbar(sc, ax=ax, shrink=0.8)
    cb.set_label('Q/ΔP efficiency [W/m/Pa]', fontsize=10)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=200, bbox_inches='tight')
        print(f"Saved: {save_path}")

    return fig


def print_best(result, config=None):
    """Print the best solutions from Pareto front."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    F = result['F']
    X = result['X']

    # Best Q (most heat transfer)
    idx_Q = np.argmin(F[:, 0])  # most negative = best Q
    # Best dP (lowest pressure drop)
    idx_dP = np.argmin(F[:, 1])
    # Best compromise (highest Q/dP ratio)
    Q = -F[:, 0]; dP = F[:, 1]
    idx_eff = np.argmax(Q / dP)

    for label, idx in [("Max Q", idx_Q), ("Min dP", idx_dP), ("Best Q/dP", idx_eff)]:
        x = X[idx]
        print(f"\n=== {label}: Q={-F[idx,0]:.0f} W/m, dP={F[idx,1]:.0f} Pa ===")
        print("  Inlet transition (3×3):")
        for iy in range(3):
            row = []
            for ix in range(3):
                i = (iy * 3 + ix) * 2
                row.append(f"L={x[i]:.1f},t={x[i+1]:.2f}")
            print(f"    y{iy}: {' | '.join(row)}")
        print(f"  Uniform: L={cfg['L0']}, t={cfg['t0']}")
        print("  Outlet transition (3×3):")
        for iy in range(3):
            row = []
            for ix in range(3):
                i = 18 + (iy * 3 + ix) * 2
                row.append(f"L={x[i]:.1f},t={x[i+1]:.2f}")
            print(f"    y{iy}: {' | '.join(row)}")


# ── Standalone test ──────────────────────────────────────────

if __name__ == '__main__':
    import time

    print("=== Single evaluation test ===")
    # All uniform L=6, t=0.3 (baseline)
    x0 = np.array([6.0, 0.3] * 18)
    t0 = time.time()
    Q_neg, dP, mass = evaluate(x0)
    t1 = time.time()
    print(f"  Q = {-Q_neg:.1f} W/m,  dP = {dP:.1f} Pa,  mass = {mass:.4f} kg/m")
    print(f"  Time: {t1-t0:.1f}s")

    # Non-uniform test
    x1 = np.array([4.0, 0.4] * 9 + [8.0, 0.3] * 9)
    Q1, dP1, m1 = evaluate(x1)
    print(f"\n  Non-uniform: Q={-Q1:.1f}, dP={dP1:.1f}, mass={m1:.4f}")
    print(f"  Differs from baseline: {abs(Q_neg - Q1) > 1}")

    print("\n=== Mini optimization (5 gen × 10 pop) ===")
    res = run_optimization(n_gen=5, pop_size=10, verbose=True)
    print(f"  Pareto solutions: {len(res['X'])}")

    print_best(res)
    fig = plot_pareto(res, save_path='pareto_test.png')
    print("\nDone.")
