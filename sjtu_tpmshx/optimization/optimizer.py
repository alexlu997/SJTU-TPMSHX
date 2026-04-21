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

from solvers.zone_config import ZoneConfig
from solvers.solve_full import solve_full_domain
from solvers.simple_solver import SIMPLESolver
from solvers.tpms_calc import (compute as tpms_compute, geometry as tpms_geometry,
                       air_density, air_viscosity, adaptive_grid)
from solvers.df_projection import (override_simple_K_cF as _override_simple_K_cF,
                                    extract_dP_from_simple as _extract_dP_from_simple,
                                    project_cells_to_streamwise_K_cF as _project_cells_to_streamwise_K_cF,
                                    project_fields_to_streamwise_K_cF as _project_fields_to_streamwise_K_cF,
                                    build_master_refined_grid as _build_master_refined_grid,
                                    project_fields_to_streamwise_K_cF_3d as _project_fields_to_streamwise_K_cF_3d,
                                    build_master_refined_grid_3d as _build_master_refined_grid_3d)


def _resolve_refined_grid(cfg):
    """Build master refined grid (both real x and real y walls) for the
    current optimizer cfg. Returns (dx_refined, dy_refined, Nx_r, Ny_r).

    Disabled via cfg['wall_refine']=False (returns uniform grid with original Nx, Ny).
    """
    L = cfg['L_domain']; H = cfg['H_domain']
    Nx_user, Ny_user = _resolve_grid(cfg)
    if not cfg.get('wall_refine', True):
        dx = np.full(Nx_user, L / Nx_user, dtype=np.float64)
        dy = np.full(Ny_user, H / Ny_user, dtype=np.float64)
        return dx, dy, Nx_user, Ny_user
    n_refine = cfg.get('n_wall_refine', 8)
    first_cell = cfg.get('wall_first_cell', 0.02e-3)
    try:
        return _build_master_refined_grid(L, H, Nx_user, Ny_user,
                                           n_refine=n_refine, first_cell=first_cell)
    except ValueError:
        # Domain too small; fall back to uniform
        dx = np.full(Nx_user, L / Nx_user, dtype=np.float64)
        dy = np.full(Ny_user, H / Ny_user, dtype=np.float64)
        return dx, dy, Nx_user, Ny_user

# NOTE: batch_runner.run_batch is NOT used here because its case-dict schema
# (L_cell_mm, t_wall_mm, u_air, T_Ain_C, …) is incompatible with the optimizer's
# 36-variable zoning vector.  Parallelism is implemented directly via
# concurrent.futures.ProcessPoolExecutor.
#
# Set TPMSHX_SERIAL=1 to force single-process execution (useful for debugging
# or when running inside a child process that already holds GIL-heavy resources).

def _parallel_workers():
    """Return number of parallel workers; 1 means serial (no subprocess overhead).

    Each 2D worker allocates ~300-500 MB (phi voxel grid + SIMPLE fields +
    numba caches). On a 16-thread machine the previous cap of 4 left most
    cores idle; default is now ``cpu_count - 1`` capped at 12 to stay under
    ~6-8 GB for typical sweeps while keeping Pareto scans an order of
    magnitude faster. Override via ``TPMSHX_WORKERS``.
    """
    if os.environ.get('TPMSHX_SERIAL') == '1':
        return 1
    override = os.environ.get('TPMSHX_WORKERS')
    if override:
        try:
            return max(1, int(override))
        except ValueError:
            pass
    return max(1, min(12, (os.cpu_count() or 2) - 1))


# ── Top-level worker functions (must be module-level for pickle on Windows) ──

def _eval_worker(args):
    """Worker: evaluate one design vector. Returns (Q_neg, dP, mass).

    Dispatches by cfg['dim']: 3 → evaluate_3d (no Richardson); 2 → Richardson
    or plain evaluate.
    """
    x, cfg, use_richardson = args
    warnings.filterwarnings('ignore')
    if int(cfg.get('dim', 2)) == 3:
        return evaluate_3d(x, cfg)
    if use_richardson:
        return evaluate_richardson(x, cfg)
    return evaluate(x, cfg)


def _solve_single_point_worker(args):
    """Worker: _solve_single_point for one design vector. Returns (Q, dP, mass).

    Dispatches by dim: 2-tuple grid (Nx, Ny) → 2D; 3-tuple → 3D.
    """
    warnings.filterwarnings('ignore')
    if len(args) == 4:
        x, cfg, Nx, Ny = args
        return _solve_single_point(x, cfg, Nx, Ny)
    elif len(args) == 5:
        x, cfg, Nx, Ny, Nz = args
        return _solve_single_point_3d(x, cfg, Nx, Ny, Nz)
    raise ValueError(f"unexpected worker args len {len(args)}")


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
    # Per-eval accuracy knobs (overridable for fast-mode NSGA-II search).
    # Default values match the full-accuracy baseline used prior to 2026-04-20.
    'fast_mode':        False,
    'max_iter_simple':  5000,
    'tol_simple':       1e-5,
    'max_iter_energy':  5000,
    'n_rho_loops':      3,
    'grid_alpha':       0.8,
    # ─── 3D Phase 1 knobs ───
    'dim':           2,      # 2 or 3; 3 routes to evaluate_3d / _resolve_grid_3d
    'Lz':            0.02,   # 3D depth [m] (ignored for dim=2)
    'Nz':            None,   # 3D depth cells; None → auto from D_h / Lz ratio
    'alpha_T':       0.7,    # LTNE three-temp under-relaxation (3D)
    'max_workers':   None,   # None → _auto_max_workers decides by dim+grid
    'mem_budget_gb': 12.0,   # Per-worker memory ceiling estimate
    'use_gpu':       False,  # Phase 4 trigger; raises NotImplementedError for now
}


def _apply_fast_preset(cfg):
    """When cfg['fast_mode'] is truthy, tighten per-eval knobs toward the
    published ``default`` fast-mode preset.

    Uses min/max so an explicit user override (e.g. ``tol_simple=5e-4``) takes
    precedence over the preset; preset is only a ceiling on cost, never a
    floor. Safe to call multiple times.
    """
    if not cfg.get('fast_mode', False):
        return cfg
    cfg['max_iter_simple'] = min(cfg.get('max_iter_simple', 5000), 800)
    cfg['tol_simple']      = max(cfg.get('tol_simple', 1e-5), 1e-3)
    cfg['max_iter_energy'] = min(cfg.get('max_iter_energy', 5000), 1500)
    cfg['n_rho_loops']     = min(cfg.get('n_rho_loops', 3), 1)
    cfg['grid_alpha']      = max(cfg.get('grid_alpha', 0.8), 1.5)
    return cfg


def _resolve_grid(cfg, alpha=None):
    """Return (Nx, Ny) from config, computing adaptively if not specified.

    ``alpha`` default reads ``cfg['grid_alpha']`` (0.8 = full-accuracy baseline).
    Callers can pass an explicit value to override (e.g.
    ``reevaluate_pareto`` uses ``alpha=0.4`` for fine-grid re-scoring).

    For cfg['dim']=3 this returns the first two axes only; use
    ``_resolve_grid_3d`` to get (Nx, Ny, Nz).
    """
    if cfg.get('Nx') is not None and cfg.get('Ny') is not None:
        return int(cfg['Nx']), int(cfg['Ny'])
    a = alpha if alpha is not None else cfg.get('grid_alpha', 0.8)
    g = tpms_geometry(cfg['tpms_type'], cfg['L0'], cfg['t0'], cfg['k_s'])
    return adaptive_grid(cfg['L_domain'], cfg['H_domain'], g['D_h'], a)


def _resolve_grid_3d(cfg, alpha=None):
    """Return (Nx, Ny, Nz) from config for dim=3 runs.

    Nz default scales from D_h and cfg['Lz'] via adaptive_grid; caps at Nx/2 for
    memory sanity on the first 3D pass (Phase 1 coarse). Override via cfg['Nz'].
    """
    Nx, Ny = _resolve_grid(cfg, alpha=alpha)
    if cfg.get('Nz') is not None:
        return Nx, Ny, int(cfg['Nz'])
    g = tpms_geometry(cfg['tpms_type'], cfg['L0'], cfg['t0'], cfg['k_s'])
    Lz = float(cfg.get('Lz', 0.02))
    a = alpha if alpha is not None else cfg.get('grid_alpha', 0.8)
    # Reuse 1D dimension from adaptive_grid in z via a square surrogate
    Nz_a, _ = adaptive_grid(Lz, Lz, g['D_h'], a)
    Nz = max(3, min(Nz_a, max(3, Nx // 2)))
    return Nx, Ny, Nz


def _auto_max_workers(cfg):
    """Decide worker count from cfg['dim'], grid size, mem budget.

    Workers are OS processes — each has its own Python interpreter, numba
    cache and SIMPLE fields, so contention between them is minimal. Cap is
    set by available cores and per-worker memory footprint, not by cell
    count alone.

    Rules:
      explicit cfg['max_workers']       → use it
      TPMSHX_WORKERS env             → override
      estimated mem > budget            → drop to fit, warn if forced to 1
      otherwise                         → min(cpu-1, 12, budget/mem_per_worker)
    """
    dim = int(cfg.get('dim', 2))
    if cfg.get('max_workers') is not None:
        return max(1, int(cfg['max_workers']))
    env = os.environ.get('TPMSHX_WORKERS')
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass

    budget = float(cfg.get('mem_budget_gb', 12.0))
    cores_cap = max(1, min(12, (os.cpu_count() or 2) - 1))
    if dim == 2:
        # 2D worker ~500 MB; 12 GB budget easily holds 12 workers
        return cores_cap

    # 3D memory estimate: ~1 GB per 500k cells (SIMPLE fields + pyamg + caches)
    Nx, Ny, Nz = _resolve_grid_3d(cfg)
    cells = Nx * Ny * Nz
    mem_per_worker_gb = max(0.5, cells * 2000.0 / (1024 ** 3))
    mem_cap = max(1, int(budget / mem_per_worker_gb))
    n = min(cores_cap, mem_cap)
    if n == 1 and cells * 2000.0 / (1024 ** 3) > budget:
        warnings.warn(
            f"3D grid {Nx}×{Ny}×{Nz} ≈ {mem_per_worker_gb:.1f} GB/worker > "
            f"budget {budget} GB — forcing max_workers=1")
    return n


def extract_dP_from_simple_3d(s):
    """SIMPLE 3D inlet-outlet pressure drop (pipe-weighted if outlet_frac set).

    P2-a' (2026-04-20): Uses SIMPLESolver3D.extract_dP_weighted when available,
    which down-weights corner cells via outlet_frac taper (mirror 2D pattern).
    Fallback to plain mean for backward compatibility.
    """
    if hasattr(s, 'extract_dP_weighted') and hasattr(s, 'outlet_frac'):
        return s.extract_dP_weighted(s)
    return float(s.P[:, 0, :].mean() - s.P[:, -1, :].mean())


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


# ── SIMPLE cache (multi-grid) ───────────────────────
# Stores SIMPLE solver instances (sA, sB) so we can extract both velocity AND
# pressure from the same object. Cache key includes grid geometry hash to
# ensure design-specific runs (non-uniform zones) don't reuse stale results.
_simple_cache = {}  # {cache_key: {sA, sB, ucA, vcA, ucB, vcB, rho_A, mu_A, ...}}


def _clear_simple_cache():
    """Clear SIMPLE cache between optimization runs."""
    global _simple_cache
    _simple_cache = {}


# ── Streamwise projection: moved to solvers/df_projection.py ──
# Helpers imported at top of file: _project_cells_to_streamwise_K_cF,
# _project_fields_to_streamwise_K_cF, _extract_dP_from_simple, _override_simple_K_cF


def _simple_var_density(cfg, rho_A_field, rho_B_field,
                         grid_cells=None, L_field=None, t_field=None,
                         refined_grid=None):
    """Run SIMPLE for both fluids with given 2D rho fields (per-design, no cache).

    refined_grid : (dx_refined, dy_refined, Nx_r, Ny_r). When supplied, SIMPLE
    runs on the 4-wall refined grid. rho_A_field and rho_B_field must also
    be on this grid.
    """
    L = cfg['L_domain']; H = cfg['H_domain']
    if refined_grid is None:
        refined_grid = _resolve_refined_grid(cfg)
    dx_refined, dy_refined, Nx, Ny = refined_grid
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
                      outlet_hi=cfg.get('outlet_hi_A', H),
                      wall_refine=False)
    sA.dx_arr = dy_refined.copy()
    sA.dy_arr = dx_refined.copy()
    _override_simple_K_cF(sA, cfg['tpms_type'], cfg['k_s'], Nx, grid_cells, L_field, t_field, 'A')
    sA.solve(max_iter=cfg.get('max_iter_simple', 5000),
             tol=cfg.get('tol_simple', 1e-5), verbose=False)
    _, v_mA = sA.get_wall_masked_velocity()
    ucA = (0.5 * (v_mA[:, :-1] + v_mA[:, 1:])).T  # (Nx, Ny)
    vcA = np.zeros((Nx, Ny))

    # Fluid B: SIMPLE in (Nx, Ny) coords, dir=3 → flip j
    rho_B_simple = rho_B_field[:, ::-1].copy()  # flip y for -y flow
    sB = SIMPLESolver(L, H, Nx, Ny, cfg['tpms_type'], cfg['L0'], cfg['t0'],
                      eps0, r_h0, rho_B_simple, mu_B, T_inB,
                      cfg.get('pipe_lo_B', 0), cfg.get('pipe_hi_B', L), u_B,
                      outlet_lo=cfg.get('outlet_lo_B', 0),
                      outlet_hi=cfg.get('outlet_hi_B', L),
                      wall_refine=False)
    sB.dx_arr = dx_refined.copy()
    sB.dy_arr = dy_refined.copy()
    _override_simple_K_cF(sB, cfg['tpms_type'], cfg['k_s'], Ny, grid_cells, L_field, t_field, 'B')
    sB.solve(max_iter=cfg.get('max_iter_simple', 5000),
             tol=cfg.get('tol_simple', 1e-5), verbose=False)
    _, v_mB = sB.get_wall_masked_velocity()
    vcB = -(0.5 * (v_mB[:, :-1] + v_mB[:, 1:]))[:, ::-1]  # un-flip
    ucB = np.zeros((Nx, Ny))

    return sA, sB, ucA, vcA, ucB, vcB


def _compute_simple(cfg, grid_cells=None, L_field=None, t_field=None,
                    refined_grid=None):
    """Compute SIMPLE fields (velocity + pressure) for A and B fluids.

    refined_grid : tuple (dx_refined, dy_refined, Nx_r, Ny_r) or None.
        When given, SIMPLE runs at refined Nx_r × Ny_r with non-uniform dx/dy
        so that the Brinkman BL at all four domain walls is resolved. Fluid A
        and B each get the correct mapping (cross-stream vs streamwise).
        When None, falls back to uniform grid from _resolve_grid(cfg).

    Returns dict with keys: sA, sB, ucA, vcA, ucB, vcB, rho_A, mu_A, rho_B, mu_B,
    plus Nx_r, Ny_r, dx_refined, dy_refined for downstream consumers.
    """
    L = cfg['L_domain']; H = cfg['H_domain']
    if refined_grid is None:
        refined_grid = _resolve_refined_grid(cfg)
    dx_refined, dy_refined, Nx, Ny = refined_grid
    u_A = cfg['u_A']; u_B = cfg['u_B']
    T_inA = cfg['T_inA']; T_inB = cfg['T_inB']

    # Design hash for cache key (grid_cells or field stats)
    if grid_cells is not None:
        design_key = tuple((gc['x0'], gc['x1'], gc['y0'], gc['y1'],
                            gc['L'], gc['t']) for gc in grid_cells)
    elif L_field is not None:
        design_key = ('field', L_field.shape, float(L_field.mean()),
                      float(t_field.mean()),
                      float(L_field.std()), float(t_field.std()))
    else:
        design_key = ('uniform',)

    cache_key = (cfg['tpms_type'], cfg['L0'], cfg['t0'],
                 cfg['L_domain'], cfg['H_domain'],
                 Nx, Ny, u_A, u_B, T_inA, T_inB,
                 cfg.get('pipe_lo_A', 0.0), cfg.get('pipe_hi_A', H),
                 cfg.get('pipe_lo_B', 0.0), cfg.get('pipe_hi_B', L),
                 cfg.get('outlet_lo_A'), cfg.get('outlet_hi_A'),
                 cfg.get('outlet_lo_B'), cfg.get('outlet_hi_B'),
                 design_key)

    if cache_key in _simple_cache:
        return _simple_cache[cache_key]

    g = tpms_geometry(cfg['tpms_type'], cfg['L0'], cfg['t0'], cfg['k_s'])
    eps0 = g['epsilon']; r_h0 = g['D_h'] / 2.0
    rho_A = air_density(T_inA, 101325.0); mu_A = air_viscosity(T_inA)
    rho_B = air_density(T_inB, 101325.0); mu_B = air_viscosity(T_inB)

    # Fluid A: flows +x, SIMPLE internal x-axis = real y, y-axis = real x
    # SIMPLE's dx_arr (cross, Nx_sim=Ny) = dy_refined; dy_arr (stream, Ny_sim=Nx) = dx_refined
    pipe_lo_A = cfg.get('pipe_lo_A', 0.0)
    pipe_hi_A = cfg.get('pipe_hi_A', H)
    out_lo_A = cfg.get('outlet_lo_A', pipe_lo_A)
    out_hi_A = cfg.get('outlet_hi_A', pipe_hi_A)
    sA = SIMPLESolver(H, L, Ny, Nx, cfg['tpms_type'], cfg['L0'], cfg['t0'],
                      eps0, r_h0, rho_A, mu_A, T_inA, pipe_lo_A, pipe_hi_A, u_A,
                      outlet_lo=out_lo_A, outlet_hi=out_hi_A,
                      wall_refine=False)
    sA.dx_arr = dy_refined.copy()
    sA.dy_arr = dx_refined.copy()
    _override_simple_K_cF(sA, cfg['tpms_type'], cfg['k_s'], Nx, grid_cells, L_field, t_field, 'A')
    sA.solve(max_iter=cfg.get('max_iter_simple', 5000),
             tol=cfg.get('tol_simple', 1e-5), verbose=False)
    _, v_mA = sA.get_wall_masked_velocity()
    ucA = (0.5 * (v_mA[:, :-1] + v_mA[:, 1:])).T  # (Nx, Ny)
    vcA = np.zeros((Nx, Ny))

    # Fluid B: flows -y, SIMPLE internal x-axis = real x, y-axis = real y
    # SIMPLE's dx_arr = dx_refined (cross for B); dy_arr = dy_refined (stream for B)
    pipe_lo_B = cfg.get('pipe_lo_B', 0.0)
    pipe_hi_B = cfg.get('pipe_hi_B', L)
    out_lo_B = cfg.get('outlet_lo_B', pipe_lo_B)
    out_hi_B = cfg.get('outlet_hi_B', pipe_hi_B)
    sB = SIMPLESolver(L, H, Nx, Ny, cfg['tpms_type'], cfg['L0'], cfg['t0'],
                      eps0, r_h0, rho_B, mu_B, T_inB, pipe_lo_B, pipe_hi_B, u_B,
                      outlet_lo=out_lo_B, outlet_hi=out_hi_B,
                      wall_refine=False)
    sB.dx_arr = dx_refined.copy()
    sB.dy_arr = dy_refined.copy()
    _override_simple_K_cF(sB, cfg['tpms_type'], cfg['k_s'], Ny, grid_cells, L_field, t_field, 'B')
    sB.solve(max_iter=cfg.get('max_iter_simple', 5000),
             tol=cfg.get('tol_simple', 1e-5), verbose=False)
    _, v_mB = sB.get_wall_masked_velocity()
    vcB = -(0.5 * (v_mB[:, :-1] + v_mB[:, 1:]))[:, ::-1]  # (Nx, Ny)
    ucB = np.zeros((Nx, Ny))

    entry = {
        'sA': sA, 'sB': sB,
        'ucA': ucA, 'vcA': vcA, 'ucB': ucB, 'vcB': vcB,
        'rho_A': rho_A, 'mu_A': mu_A, 'rho_B': rho_B, 'mu_B': mu_B,
        'Nx_r': Nx, 'Ny_r': Ny,
        'dx_refined': dx_refined, 'dy_refined': dy_refined,
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
    _apply_fast_preset(cfg)

    L = cfg['L_domain']; H = cfg['H_domain']
    # Master refined grid (4-wall BL resolution). Nx, Ny below are the refined
    # dimensions used consistently by za arrays, SIMPLE, and solve_full_domain.
    refined_grid = _resolve_refined_grid(cfg)
    dx_refined, dy_refined, Nx, Ny = refined_grid
    cfg['Nx'] = Nx; cfg['Ny'] = Ny  # downstream sees refined values
    u_A = cfg['u_A']; u_B = cfg['u_B']
    T_inA = cfg['T_inA']; T_inB = cfg['T_inB']
    cp_f = cfg['cp_f']

    # 1-2. Build property arrays at refined grid (continuous or discrete)
    grid_cells = None
    L_field_design = None; t_field_design = None
    if cfg.get('use_continuous', True):
        from solvers.sigmoid_field import build_continuous_arrays, get_geometry_lut
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
            opt_axis=cfg.get('opt_axis', 'y'),
            dx_arr=dx_refined, dy_arr=dy_refined)
        L_field_design = za['L_field']; t_field_design = za['t_field']
    else:
        grid_cells = build_grid_cells(x, cfg['L0'], cfg['t0'],
                                      cfg.get('y_trans_inlet', cfg.get('y_trans', 0.2)),
                                      cfg.get('y_trans_outlet', cfg.get('y_trans', 0.2)),
                                      cfg.get('opt_axis', 'y'))
        za = ZoneConfig.build_grid_arrays(
            Nx, Ny, L, H, grid_cells,
            cfg['tpms_type'], cfg['k_s'],
            u_A, u_B, T_inA, T_inB,
            dx_arr=dx_refined, dy_arr=dy_refined)

    # 3. SIMPLE velocity + pressure fields (design-specific via zone projection)
    sc = _compute_simple(cfg, grid_cells=grid_cells,
                         L_field=L_field_design, t_field=t_field_design,
                         refined_grid=refined_grid)
    ucA = sc['ucA']; vcA = sc['vcA']
    ucB = sc['ucB']; vcB = sc['vcB']
    rho_A = sc['rho_A']; mu_A = sc['mu_A']
    rho_B = sc['rho_B']; mu_B = sc['mu_B']
    sA_final = sc['sA']; sB_final = sc['sB']  # for dP extraction

    # 4. Energy solve with per-cell rho(T)*cp(T) coupling
    #    + variable density SIMPLE re-run after first energy iteration
    from solvers.tpms_calc import air_cp
    P_in = 101325.0
    rcp_A = air_density(T_inA, P_in) * air_cp(T_inA)
    rcp_B = air_density(T_inB, P_in) * air_cp(T_inB)
    Ta = Tb = Ts = None
    rho_A_field = np.full((Nx, Ny), air_density(T_inA, P_in))
    rho_B_field = np.full((Nx, Ny), air_density(T_inB, P_in))
    n_rho = max(1, int(cfg.get('n_rho_loops', 3)))
    max_iter_e = int(cfg.get('max_iter_energy', 5000))
    for _ci in range(n_rho):
        Ta, Tb, Ts = solve_full_domain(
            L, H, Nx, Ny, T_inA, T_inB,
            za['K_ffA_arr'], za['K_ffB_arr'], za['K_ss_arr'],
            za['h_vA_arr'], za['h_vB_arr'],
            rcp_A, rcp_B,
            za['eps_arr'], ucA, vcA, ucB, vcB,
            cfg['dir_A'], cfg['dir_B'],
            tol=0.5, max_iter=max_iter_e,
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
            dx_arr=dx_refined, dy_arr=dy_refined)
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
        sA_final, sB_final, ucA, vcA, ucB, vcB = _simple_var_density(
            cfg, rho_A_field, rho_B_field,
            grid_cells=grid_cells, L_field=L_field_design, t_field=t_field_design,
            refined_grid=refined_grid)

    # 5. Compute objectives (non-uniform cell areas)
    # Cell area for integrals uses the same refined grid as za / SIMPLE
    _cell_area = dx_refined[:, None] * dy_refined[None, :]

    Q_total = np.sum(za['h_vB_arr'] * (Ts - Tb) * _cell_area)

    # Pressure drop: extract from SIMPLE P fields (D-F physics via SurrogateV3)
    # Legacy f-Re / compute_dP_continuous paths are DEPRECATED — they bypassed
    # SIMPLE's D-F source term and the grid path had a 7x double-count bug.
    # See vault/reports/2026-04-17-shanghai-dP-error-analysis-CN.md for principle:
    # production dP path is strictly SIMPLE, never analytical.
    dP_A = _extract_dP_from_simple(sA_final)
    dP_B = _extract_dP_from_simple(sB_final)
    dP_total = dP_A + dP_B

    # Mass: sum of (1-eps) * rho_s * cell_volume over all cells
    mass = np.sum((1.0 - za['eps_arr']) * cfg['rho_s'] * _cell_area)

    return -Q_total, dP_total, mass


def evaluate_3d(x, config=None):
    """Evaluate one 108-dim 3D design point.

    Pipeline: sigmoid_field_3d → project K/cF → SIMPLE 3D × 2 → LTNE solve_full_3d
    → (non-iso outer loop + var-rho iteration) → integrate Q, dP, mass.

    P1b additions (2026-04-20):
      * P_ref_abs seeded from 1D compressible D-F closed form (fluid A)
      * Outer SIMPLE ↔ LTNE coupling: cfg['max_outer_3d'] iterations
        (default 4), with ALPHA_T under-relax on SIMPLE's T_field feedback
      * Variable-density: between outer iters, rebuild sA.rho_field /
        mu_field / _mu_eff_field from updated Ta; sB stays incompressible

    cfg flags (all optional, defaults preserve P1 MVP behaviour):
      * 'couple_3d'      : bool, default True — enable outer coupling
      * 'max_outer_3d'   : int,  default 4    — outer iterations cap
      * 'outer_tol_K_3d' : float, default 0.5 K
      * 'alpha_outer_3d' : float, default 0.6 — T_field under-relax

    Returns (Q_neg, dP, mass).
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    _apply_fast_preset(cfg)

    if cfg.get('use_gpu', False):
        raise NotImplementedError("GPU path is a Phase 4 trigger stub")

    x = np.asarray(x, dtype=np.float64)
    if x.shape != (108,):
        raise ValueError(f"dim=3 decision vector must be shape (108,), got {x.shape}")

    L = float(cfg['L_domain']); H = float(cfg['H_domain']); D = float(cfg['Lz'])
    Nx_u, Ny_u, Nz_u = _resolve_grid_3d(cfg)

    u_A = cfg['u_A']; u_B = cfg['u_B']
    T_inA = cfg['T_inA']; T_inB = cfg['T_inB']
    R_AIR = 287.05
    P_atm_local = 101325.0

    # 0. Optional six-wall refinement (3D Brinkman BL resolution)
    refine_3d = bool(cfg.get('wall_refine_3d', False))
    if refine_3d:
        n_refine = int(cfg.get('n_wall_refine', 8))
        first_cell = float(cfg.get('wall_first_cell', 0.02e-3))
        try:
            dx_arr, dy_arr, dz_arr, Nx, Ny, Nz = _build_master_refined_grid_3d(
                L, H, D, Nx_u, Ny_u, Nz_u,
                n_refine=n_refine, first_cell=first_cell)
        except ValueError:
            refine_3d = False
            dx_arr = np.full(Nx_u, L / Nx_u); dy_arr = np.full(Ny_u, H / Ny_u)
            dz_arr = np.full(Nz_u, D / Nz_u); Nx, Ny, Nz = Nx_u, Ny_u, Nz_u
    else:
        dx_arr = np.full(Nx_u, L / Nx_u); dy_arr = np.full(Ny_u, H / Ny_u)
        dz_arr = np.full(Nz_u, D / Nz_u); Nx, Ny, Nz = Nx_u, Ny_u, Nz_u

    cfg['Nx'] = Nx; cfg['Ny'] = Ny; cfg['Nz'] = Nz

    # 1. Sigmoid 3D continuous fields (all shape (Nx, Ny, Nz))
    from solvers.sigmoid_field import get_geometry_lut
    from solvers.sigmoid_field_3d import build_continuous_arrays_3d
    from solvers.simple_solver_3d import SIMPLESolver3D
    from solvers.solve_full_3d import solve_full_domain_3d
    from solvers.tpms_calc import air_cp

    lut = get_geometry_lut(cfg['tpms_type'])
    za = build_continuous_arrays_3d(
        x, cfg['L0'], cfg['t0'],
        cfg.get('y_trans_inlet', cfg.get('y_trans', 0.2)),
        cfg.get('y_trans_outlet', cfg.get('y_trans', 0.2)),
        Nx, Ny, Nz, L, H, D,
        cfg['tpms_type'], cfg['k_s'],
        u_A, u_B, T_inA, T_inB, lut,
        fix_L=cfg.get('fix_L', False), fix_t=cfg.get('fix_t', False),
        dx_arr=dx_arr, dy_arr=dy_arr, dz_arr=dz_arr)

    # 2. Project to SIMPLE 3D K / cF arrays
    # Fluid A: SIMPLE Ny = real Nx (streamwise dx_arr); SIMPLE Nz = Nz (dz_arr)
    # Fluid B: SIMPLE Ny = real Ny (streamwise dy_arr); SIMPLE Nz = Nz (dz_arr)
    K_A, cF_A = _project_fields_to_streamwise_K_cF_3d(
        za['L_field'], za['t_field'], za['eps_f_arr'],
        cfg['tpms_type'], Ny_sim=Nx, Nz_sim=Nz, fluid='A',
        streamwise_dx=dx_arr, z_dx=dz_arr)
    K_B, cF_B = _project_fields_to_streamwise_K_cF_3d(
        za['L_field'], za['t_field'], za['eps_f_arr'],
        cfg['tpms_type'], Ny_sim=Ny, Nz_sim=Nz, fluid='B',
        streamwise_dx=dy_arr, z_dx=dz_arr)

    # 3. SIMPLE instances with P_ref_abs seeding (fluid A compressible)
    rho_A0 = air_density(T_inA, P_atm_local); mu_A0 = air_viscosity(T_inA)
    rho_B0 = air_density(T_inB, P_atm_local); mu_B0 = air_viscosity(T_inB)
    eps_mean = float(np.mean(za['eps_arr']))

    # 1D compressible D-F closed form seed for both fluids:
    #   P_out² = P_in² − 2·R·T·(μG/K + c_F·G²)·L_flow
    K_mean_A = float(np.mean(K_A))
    cF_mean_A = float(np.mean(cF_A))
    G_A = rho_A0 * u_A
    C_A = mu_A0 * G_A / max(K_mean_A, 1e-16) + cF_mean_A * G_A * G_A
    P_out_sq_A = P_atm_local ** 2 - 2.0 * R_AIR * T_inA * C_A * L
    P_ref_A = float(np.sqrt(max(P_out_sq_A, 1.0e4)))

    K_mean_B = float(np.mean(K_B))
    cF_mean_B = float(np.mean(cF_B))
    G_B = rho_B0 * u_B
    C_B = mu_B0 * G_B / max(K_mean_B, 1e-16) + cF_mean_B * G_B * G_B
    P_out_sq_B = P_atm_local ** 2 - 2.0 * R_AIR * T_inB * C_B * H
    P_ref_B = float(np.sqrt(max(P_out_sq_B, 1.0e4)))

    sA = SIMPLESolver3D(Lx=H, Ly=L, Lz=D, Nx=Ny, Ny=Nx, Nz=Nz,
                         rho=rho_A0, mu=mu_A0, T_in=T_inA, v_inlet=u_A,
                         eps=eps_mean, K_arr=K_A, cF_arr=cF_A,
                         P_ref_abs=P_ref_A)
    # Axis swap for fluid A: SIMPLE dx → real dy (cross-stream); dy → real dx (stream)
    sA.dx = np.ascontiguousarray(dy_arr, dtype=np.float64)
    sA.dy = np.ascontiguousarray(dx_arr, dtype=np.float64)
    sA.dz = np.ascontiguousarray(dz_arr, dtype=np.float64)

    sB = SIMPLESolver3D(Lx=L, Ly=H, Lz=D, Nx=Nx, Ny=Ny, Nz=Nz,
                         rho=rho_B0, mu=mu_B0, T_in=T_inB, v_inlet=u_B,
                         eps=eps_mean, K_arr=K_B, cF_arr=cF_B,
                         P_ref_abs=P_ref_B)
    # Fluid B: SIMPLE dx = real dx; dy = real dy; dz = real dz
    sB.dx = np.ascontiguousarray(dx_arr, dtype=np.float64)
    sB.dy = np.ascontiguousarray(dy_arr, dtype=np.float64)
    sB.dz = np.ascontiguousarray(dz_arr, dtype=np.float64)

    max_iter_simple = int(cfg.get('max_iter_simple', 800))
    tol_simple = float(cfg.get('tol_simple', 1e-3))

    sA.solve(max_iter=max_iter_simple, tol=tol_simple, verbose=False)
    sB.solve(max_iter=max_iter_simple, tol=tol_simple, verbose=False)

    # 4. Outer SIMPLE ↔ LTNE coupling loop (non-iso + var-ρ)
    couple = bool(cfg.get('couple_3d', True))
    max_outer = int(cfg.get('max_outer_3d', 4))
    outer_tol = float(cfg.get('outer_tol_K_3d', 0.5))
    alpha_outer = float(cfg.get('alpha_outer_3d', 0.6))
    max_iter_energy = int(cfg.get('max_iter_energy', 5000))

    rcp_A_field = np.full((Nx, Ny, Nz), rho_A0 * air_cp(T_inA))
    rcp_B_field = np.full((Nx, Ny, Nz), rho_B0 * air_cp(T_inB))

    Ta = Tb = Ts = None
    Ta_prev = None
    outer_iters = 1 if not couple else max_outer

    for outer_it in range(outer_iters):
        # Cell-centred velocities in real coords (Nx, Ny, Nz)
        vA_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])     # (Ny, Nx, Nz)
        ucA_real = vA_cc.transpose(1, 0, 2).copy()            # (Nx, Ny, Nz)
        vcA_real = np.zeros((Nx, Ny, Nz))
        wcA_real = np.zeros((Nx, Ny, Nz))
        vB_cc = 0.5 * (sB.v[:, :-1, :] + sB.v[:, 1:, :])     # (Nx, Ny, Nz)
        vcB_real = -vB_cc[:, ::-1, :].copy()
        ucB_real = np.zeros((Nx, Ny, Nz))
        wcB_real = np.zeros((Nx, Ny, Nz))

        Ta, Tb, Ts = solve_full_domain_3d(
            L, H, D, Nx, Ny, Nz, T_inA, T_inB,
            za['K_ffA_arr'], za['K_ffB_arr'], za['K_ss_arr'],
            za['h_vA_arr'], za['h_vB_arr'],
            rcp_A_field, rcp_B_field, za['eps_arr'],
            ucA_real, vcA_real, wcA_real,
            ucB_real, vcB_real, wcB_real,
            cfg.get('dir_A', 0), cfg.get('dir_B', 3),
            dx_arr=dx_arr, dy_arr=dy_arr, dz_arr=dz_arr,
            max_iter=max_iter_energy, tol=0.5,
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
            alpha_T=float(cfg.get('alpha_T', 0.7)),
            alpha_T_s=cfg.get('alpha_T_s'),
            alpha_T_fA=cfg.get('alpha_T_fA'),
            alpha_T_fB=cfg.get('alpha_T_fB'))

        if not couple:
            break

        # Convergence on fluid A T-field (biggest driver of ρ, μ)
        if Ta_prev is not None:
            dT_max = float(np.max(np.abs(Ta - Ta_prev)))
            if dT_max < outer_tol:
                break
        Ta_prev = Ta.copy()

        # Rebuild SIMPLE A's rho/mu/mu_eff fields from updated Ta
        #   Ta real (Nx, Ny, Nz) -> SIMPLE A internal (Ny, Nx, Nz)
        Ta_sA = Ta.transpose(1, 0, 2).copy()
        P_abs_sA = sA.P_ref_abs + sA.P
        rho_A_new = P_abs_sA / (R_AIR * Ta_sA)
        mu_A_new = air_viscosity(Ta_sA)

        if outer_it > 0:
            rho_A_mix = alpha_outer * rho_A_new + (1.0 - alpha_outer) * sA.rho_field
            mu_A_mix = alpha_outer * mu_A_new + (1.0 - alpha_outer) * sA.mu_field
        else:
            rho_A_mix = rho_A_new; mu_A_mix = mu_A_new

        sA.rho_field = np.ascontiguousarray(rho_A_mix, dtype=np.float64)
        sA.mu_field = np.ascontiguousarray(mu_A_mix, dtype=np.float64)
        sA._mu_eff_field = np.ascontiguousarray(mu_A_mix / sA.eps, dtype=np.float64)

        # Refresh P_ref_abs from the updated mean T
        T_avg = float(Ta_sA.mean())
        mu_avg = float(air_viscosity(T_avg))
        C_avg = mu_avg * G_A / max(K_mean_A, 1e-16) + cF_mean_A * G_A * G_A
        P_out_sq_new = P_atm_local ** 2 - 2.0 * R_AIR * T_avg * C_avg * L
        sA.P_ref_abs = float(np.sqrt(max(P_out_sq_new, 1.0e4)))

        # Re-solve SIMPLE A under new ρ, μ, P_ref_abs
        sA.solve(max_iter=max_iter_simple, tol=tol_simple, verbose=False)

        # Update LTNE heat capacity fields for next outer iter
        rcp_A_field = np.ascontiguousarray(
            alpha_outer * air_density(Ta, P_atm_local) * air_cp(Ta)
            + (1.0 - alpha_outer) * rcp_A_field, dtype=np.float64)
        rcp_B_field = np.ascontiguousarray(
            alpha_outer * air_density(Tb, P_atm_local) * air_cp(Tb)
            + (1.0 - alpha_outer) * rcp_B_field, dtype=np.float64)

    # 5. Integrals on the actual grid (refined or uniform)
    cell_vol = dx_arr[:, None, None] * dy_arr[None, :, None] * dz_arr[None, None, :]
    Q_total = float(np.sum(za['h_vB_arr'] * (Ts - Tb) * cell_vol))
    dP_A = extract_dP_from_simple_3d(sA)
    dP_B = extract_dP_from_simple_3d(sB)
    dP_total = dP_A + dP_B
    mass = float(np.sum((1.0 - za['eps_arr']) * cfg['rho_s'] * cell_vol))

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
    Nx_c_user, Ny_c_user = _resolve_grid(cfg)
    cfg['Nx'] = Nx_c_user; cfg['Ny'] = Ny_c_user
    Nx_f_user = Nx_c_user * 2;  Ny_f_user = Ny_c_user * 2
    u_A = cfg['u_A']; u_B = cfg['u_B']
    T_inA = cfg['T_inA']; T_inB = cfg['T_inB']
    cp_f = cfg['cp_f']
    P_in = 101325.0

    # Master refined grids for coarse and fine levels
    refined_c = _resolve_refined_grid(cfg)
    dx_c, dy_c, Nx_c, Ny_c = refined_c
    cfg_f_grid = {**cfg, 'Nx': Nx_f_user, 'Ny': Ny_f_user}
    refined_f = _resolve_refined_grid(cfg_f_grid)
    dx_f, dy_f, Nx_f, Ny_f = refined_f

    # Build arrays helper
    from solvers.tpms_calc import air_cp
    _y_trans_in = cfg.get('y_trans_inlet', cfg.get('y_trans', 0.2))
    _y_trans_out = cfg.get('y_trans_outlet', cfg.get('y_trans', 0.2))

    def _build_za(nx, ny, dx, dy):
        if cfg.get('use_continuous', True):
            from solvers.sigmoid_field import build_continuous_arrays, get_geometry_lut
            lut = get_geometry_lut(cfg['tpms_type'])
            return build_continuous_arrays(
                x, cfg['L0'], cfg['t0'], _y_trans_in, _y_trans_out,
                nx, ny, L, H, cfg['tpms_type'], cfg['k_s'],
                u_A, u_B, T_inA, T_inB, lut,
                sigmoid_width_y=cfg.get('sigmoid_width_y', 0.02),
                sigmoid_width_x=cfg.get('sigmoid_width_x', 0.05),
                fix_L=cfg.get('fix_L', False),
                fix_t=cfg.get('fix_t', False),
                opt_axis=cfg.get('opt_axis', 'y'),
                dx_arr=dx, dy_arr=dy)
        else:
            gc = build_grid_cells(x, cfg['L0'], cfg['t0'],
                                  _y_trans_in, _y_trans_out, cfg.get('opt_axis', 'y'))
            return ZoneConfig.build_grid_arrays(
                nx, ny, L, H, gc, cfg['tpms_type'], cfg['k_s'],
                u_A, u_B, T_inA, T_inB,
                dx_arr=dx, dy_arr=dy)

    # ── Determine design-specific inputs for SIMPLE ──
    grid_cells_r = None; L_field_r = None; t_field_r = None
    if not cfg.get('use_continuous', True):
        grid_cells_r = build_grid_cells(x, cfg['L0'], cfg['t0'],
                                        _y_trans_in, _y_trans_out, cfg.get('opt_axis', 'y'))

    # ── Coarse grid: full per-cell rho*cp coupling ──
    za_c = _build_za(Nx_c, Ny_c, dx_c, dy_c)
    if cfg.get('use_continuous', True) and 'L_field' in za_c:
        L_field_r = za_c['L_field']; t_field_r = za_c['t_field']
    sc_c = _compute_simple(cfg, grid_cells=grid_cells_r,
                           L_field=L_field_r, t_field=t_field_r,
                           refined_grid=refined_c)
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
            Ta_init=Ta_c, Tb_init=Tb_c, Ts_init=Ts_c,
            dx_arr=dx_c, dy_arr=dy_c)
        rA_new = air_density(float(Ta_c.mean()), P_in)
        rB_new = air_density(float(Tb_c.mean()), P_in)
        if abs(rA_new - rA_avg) / rA_avg < 0.01 and abs(rB_new - rB_avg) / rB_avg < 0.01:
            break
        rcp_A = 0.7 * air_density(Ta_c, P_in) * air_cp(Ta_c) + 0.3 * rcp_A
        rcp_B = 0.7 * air_density(Tb_c, P_in) * air_cp(Tb_c) + 0.3 * rcp_B
        rA_avg = 0.7 * rA_new + 0.3 * rA_avg
        rB_avg = 0.7 * rB_new + 0.3 * rB_avg

    _area_c = dx_c[:, None] * dy_c[None, :]
    Q_coarse = np.sum(za_c['h_vB_arr'] * (Ts_c - Tb_c) * _area_c)

    # ── Fine grid: single energy solve with coarse-grid rho*cp (upsample) ──
    from scipy.ndimage import zoom
    # Upsample from coarse refined grid to fine refined grid (both are irregular)
    zoom_factor_x = Nx_f / Nx_c
    zoom_factor_y = Ny_f / Ny_c
    rcp_A_f = zoom(rcp_A if np.ndim(rcp_A) > 0 else np.full((Nx_c, Ny_c), float(rcp_A)),
                   (zoom_factor_x, zoom_factor_y), order=1)
    rcp_B_f = zoom(rcp_B if np.ndim(rcp_B) > 0 else np.full((Nx_c, Ny_c), float(rcp_B)),
                   (zoom_factor_x, zoom_factor_y), order=1)

    za_f = _build_za(Nx_f, Ny_f, dx_f, dy_f)
    L_field_rf = za_f['L_field'] if (cfg.get('use_continuous', True) and 'L_field' in za_f) else None
    t_field_rf = za_f['t_field'] if (cfg.get('use_continuous', True) and 't_field' in za_f) else None
    sc_f = _compute_simple(cfg_f_grid, grid_cells=grid_cells_r,
                            L_field=L_field_rf, t_field=t_field_rf,
                            refined_grid=refined_f)
    Ta_f, Tb_f, Ts_f = solve_full_domain(
        L, H, Nx_f, Ny_f, T_inA, T_inB,
        za_f['K_ffA_arr'], za_f['K_ffB_arr'], za_f['K_ss_arr'],
        za_f['h_vA_arr'], za_f['h_vB_arr'],
        rcp_A_f, rcp_B_f,
        za_f['eps_arr'], sc_f['ucA'], sc_f['vcA'], sc_f['ucB'], sc_f['vcB'],
        cfg['dir_A'], cfg['dir_B'],
        tol=0.5, max_iter=5000,
        dx_arr=dx_f, dy_arr=dy_f)

    _area_f = dx_f[:, None] * dy_f[None, :]
    Q_fine = np.sum(za_f['h_vB_arr'] * (Ts_f - Tb_f) * _area_f)

    # ── Richardson extrapolation (first-order, ratio=2) ──
    Q_extrap = 2.0 * Q_fine - Q_coarse

    # ── dP (from coarse-grid SIMPLE P field) and mass ──
    # dP comes from SIMPLE's converged pressure field (D-F physics).
    # Coarse grid used for speed; fine-grid dP would be marginally different.
    # See vault/reports/2026-04-17-shanghai-dP-error-analysis-CN.md.
    dP_A_r = _extract_dP_from_simple(sc_c['sA'])
    dP_B_r = _extract_dP_from_simple(sc_c['sB'])
    dP_total = dP_A_r + dP_B_r

    mass = np.sum((1.0 - za_c['eps_arr']) * cfg['rho_s'] * _area_c)

    return -Q_extrap, dP_total, mass


# ── pymoo Problem ────────────────────────────────────────────

# Shared progress counter (thread-safe via GIL for simple int)
_progress = {'count': 0, 'total': 0, 'best_Q': 0.0,
             'phase': 'optimize', 'reeval_count': 0, 'reeval_total': 0}


def _make_problem(config=None):
    from pymoo.core.problem import Problem

    cfg = {**DEFAULT_CONFIG, **(config or {})}
    dim = int(cfg.get('dim', 2))
    n_obj = 2  # -Q, dP

    # Bounds: L ∈ [4, 8] mm, t ∈ [0.3, 0.5] mm alternating per zone
    if dim == 3:
        n_var = 108   # 3×3×3 inlet + 3×3×3 outlet, × (L, t)
        xl = np.array([4.0, 0.3] * 54)
        xu = np.array([8.0, 0.5] * 54)
    else:
        n_var = 36
        xl = np.array([4.0, 0.3] * 18)
        xu = np.array([8.0, 0.5] * 18)

    use_richardson = cfg.get('use_richardson', True) and dim == 2

    class TPMSProblem(Problem):
        def __init__(self):
            super().__init__(n_var=n_var, n_obj=n_obj, xl=xl, xu=xu)

        def _evaluate(self, X, out, *args, **kwargs):
            F = np.empty((len(X), n_obj))
            n_workers = _auto_max_workers(cfg) if dim == 3 else _parallel_workers()

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
                # Serial path (TPMSHX_SERIAL=1 or single candidate)
                if dim == 3:
                    eval_fn = evaluate_3d
                elif use_richardson:
                    eval_fn = evaluate_richardson
                else:
                    eval_fn = evaluate
                for i, x in enumerate(X):
                    Q_neg, dP, mass = eval_fn(x, cfg)
                    F[i] = [Q_neg, dP]
                    _progress['count'] += 1
                    if -Q_neg > _progress['best_Q']:
                        _progress['best_Q'] = -Q_neg

            out["F"] = F

    return TPMSProblem()


# ── Run optimization ─────────────────────────────────────────

def _solve_single_point(x, cfg, Nx_user, Ny_user):
    """Full physical solve for a single design point at given USER grid resolution.

    Internally builds refined 4-wall BL grid and consistently uses it for za,
    SIMPLE, and solve_full_domain. Returns (Q, dP_total, 0.0).
    """
    from solvers.sigmoid_field import build_continuous_arrays, get_geometry_lut
    from solvers.tpms_calc import air_cp

    L = cfg['L_domain']; H = cfg['H_domain']
    tpms_type = cfg['tpms_type']; k_s = cfg['k_s']
    u_A = cfg['u_A']; u_B = cfg['u_B']
    T_inA = cfg['T_inA']; T_inB = cfg['T_inB']
    L0 = cfg['L0']; t0 = cfg['t0']
    P_in = 101325.0

    # Build master refined grid from user resolution
    cfg_local = {**cfg, 'Nx': Nx_user, 'Ny': Ny_user}
    refined_grid = _resolve_refined_grid(cfg_local)
    dx_r, dy_r, Nx, Ny = refined_grid

    lut = get_geometry_lut(tpms_type)
    g0 = tpms_geometry(tpms_type, L0, t0, k_s)
    eps0 = g0['epsilon']; r_h0 = g0['D_h'] / 2.0

    # 1. Sigmoid continuous property arrays at refined grid
    za = build_continuous_arrays(
        x, L0, t0,
        cfg.get('y_trans_inlet', 0.2), cfg.get('y_trans_outlet', 0.2),
        Nx, Ny, L, H, tpms_type, k_s,
        u_A, u_B, T_inA, T_inB, lut,
        fix_L=cfg.get('fix_L', False), fix_t=cfg.get('fix_t', False),
        dx_arr=dx_r, dy_arr=dy_r)

    # 2. SIMPLE at refined grid (design-specific K/c_F override + refined dx/dy)
    rho_A = air_density(T_inA, P_in); mu_A = air_viscosity(T_inA)
    rho_B = air_density(T_inB, P_in); mu_B = air_viscosity(T_inB)
    L_field_sp = za['L_field']; t_field_sp = za['t_field']

    sA = SIMPLESolver(H, L, Ny, Nx, tpms_type, L0, t0,
                      eps0, r_h0, rho_A, mu_A, T_inA,
                      cfg.get('pipe_lo_A', 0.0), cfg.get('pipe_hi_A', H), u_A,
                      outlet_lo=cfg.get('outlet_lo_A'), outlet_hi=cfg.get('outlet_hi_A'),
                      wall_refine=False)
    sA.dx_arr = dy_r.copy(); sA.dy_arr = dx_r.copy()
    _override_simple_K_cF(sA, cfg['tpms_type'], cfg['k_s'], Nx, None, L_field_sp, t_field_sp, 'A')
    sA.solve(max_iter=5000, tol=1e-5, verbose=False)
    _, v_mA = sA.get_wall_masked_velocity()
    ucA = (0.5 * (v_mA[:, :-1] + v_mA[:, 1:])).T
    vcA = np.zeros((Nx, Ny))

    sB = SIMPLESolver(L, H, Nx, Ny, tpms_type, L0, t0,
                      eps0, r_h0, rho_B, mu_B, T_inB,
                      cfg.get('pipe_lo_B', 0.0), cfg.get('pipe_hi_B', L), u_B,
                      outlet_lo=cfg.get('outlet_lo_B'), outlet_hi=cfg.get('outlet_hi_B'),
                      wall_refine=False)
    sB.dx_arr = dx_r.copy(); sB.dy_arr = dy_r.copy()
    _override_simple_K_cF(sB, cfg['tpms_type'], cfg['k_s'], Ny, None, L_field_sp, t_field_sp, 'B')
    sB.solve(max_iter=5000, tol=1e-5, verbose=False)
    _, v_mB = sB.get_wall_masked_velocity()
    vcB = -(0.5 * (v_mB[:, :-1] + v_mB[:, 1:]))[:, ::-1]
    ucB = np.zeros((Nx, Ny))

    # 3. Energy solve with ρ*cp coupling at refined grid
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
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
            dx_arr=dx_r, dy_arr=dy_r)
        rA_new = air_density(float(Ta.mean()), P_in)
        rB_new = air_density(float(Tb.mean()), P_in)
        if abs(rA_new - float(np.mean(rcp_A / air_cp(Ta) if np.ndim(rcp_A) > 0 else rcp_A / air_cp(T_inA)))) / rA_new < 0.01:
            break
        rcp_A = 0.7 * air_density(Ta, P_in) * air_cp(Ta) + 0.3 * rcp_A
        rcp_B = 0.7 * air_density(Tb, P_in) * air_cp(Tb) + 0.3 * rcp_B

    # 4. Q and ΔP using refined cell_area
    _area_sp = dx_r[:, None] * dy_r[None, :]
    Q = float(np.sum(za['h_vB_arr'] * (Ts - Tb) * _area_sp))

    dP_A = _extract_dP_from_simple(sA)
    dP_B = _extract_dP_from_simple(sB)

    return Q, dP_A + dP_B, 0.0


def _solve_single_point_3d(x, cfg, Nx_user, Ny_user, Nz_user):
    """3D single-point physical solve at forced grid. Wraps evaluate_3d.

    Returns (Q_positive, dP_total, mass) — matches 2D `_solve_single_point`.
    """
    cfg_local = {**cfg, 'Nx': int(Nx_user), 'Ny': int(Ny_user), 'Nz': int(Nz_user)}
    Qneg, dP, mass = evaluate_3d(x, cfg_local)
    return float(-Qneg), float(dP), float(mass)


def reevaluate_pareto(X, config=None, Nx_fine=None, Ny_fine=None,
                      progress_cb=None):
    """Re-evaluate Pareto front with Richardson extrapolation.

    Two grid levels (coarse and ×2 fine) for grid-independent Q.
    ΔP uses D-F SIMPLE (grid-independent).

    cfg['dim']=3 → route to `_solve_single_point_3d` with (Nx, Ny, Nz).
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    dim = int(cfg.get('dim', 2))

    N = len(X)
    F_fine = np.empty((N, 2))
    n_workers = _auto_max_workers(cfg) if dim == 3 else _parallel_workers()

    if dim == 3:
        Nx_c, Ny_c, Nz_c = _resolve_grid_3d(cfg, alpha=0.4)
        Nx_f, Ny_f, Nz_f = Nx_c * 2, Ny_c * 2, Nz_c * 2
        coarse_args = [(x, cfg, Nx_c, Ny_c, Nz_c) for x in X]
        fine_args   = [(x, cfg, Nx_f, Ny_f, Nz_f) for x in X]
    else:
        if Nx_fine is None or Ny_fine is None:
            Nx_fine, Ny_fine = _resolve_grid(cfg, alpha=0.4)
        Nx_c, Ny_c = Nx_fine, Ny_fine
        Nx_f, Ny_f = Nx_fine * 2, Ny_fine * 2
        coarse_args = [(x, cfg, Nx_c, Ny_c) for x in X]
        fine_args   = [(x, cfg, Nx_f, Ny_f) for x in X]

    if n_workers > 1 and N > 1:
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
        for idx, x in enumerate(X):
            Q_c, dP_c, _ = _solve_single_point_worker(coarse_args[idx])
            Q_f, dP_f, _ = _solve_single_point_worker(fine_args[idx])
            F_fine[idx] = [-(2.0 * Q_f - Q_c), dP_f]
            if progress_cb:
                progress_cb(idx + 1, N)

    return F_fine


def _save_pareto_csv(path, X, F):
    """Save Pareto front to CSV. Auto-detects 2D (36-dim) vs 3D (108-dim) schema."""
    n_var = X.shape[1] if hasattr(X, 'shape') else len(X[0])
    with open(path, 'w') as f:
        cols = ['Q_total', 'dP_total_Pa']
        if n_var == 108:
            # 3D: inlet 3×3×3 + outlet 3×3×3, × (L, t)
            for side in ('inlet', 'outlet'):
                for iy in range(3):
                    for ix in range(3):
                        for iz in range(3):
                            zi = f"{side}_iy{iy}_ix{ix}_iz{iz}"
                            cols += [f'{zi}_L_mm', f'{zi}_t_mm']
        else:
            # 2D default 36-dim
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
        from .optimizer_botorch import run_botorch_optimization
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
        dim_final = int(cfg_final.get('dim', 2))
        if 'reeval_Nx' in cfg_final and 'reeval_Ny' in cfg_final:
            Nx_re, Ny_re = cfg_final['reeval_Nx'], cfg_final['reeval_Ny']
            Nz_re = cfg_final.get('reeval_Nz')
        elif dim_final == 3:
            Nx_re, Ny_re, Nz_re = _resolve_grid_3d(cfg_final, alpha=0.4)
        else:
            Nx_re, Ny_re = _resolve_grid(cfg_final, alpha=0.4)
            Nz_re = None
        n_pareto = len(res.X)
        if verbose:
            if dim_final == 3:
                print(f"[Optimizer] Re-evaluating {n_pareto} Pareto at 3D {Nx_re}×{Ny_re}×{Nz_re}...")
            else:
                print(f"[Optimizer] Re-evaluating {n_pareto} Pareto at {Nx_re}×{Ny_re}...")

        _progress['phase'] = 'reeval'
        _progress['reeval_total'] = n_pareto

        def _reeval_cb(i, n):
            _progress['reeval_count'] = i

        F_fine = reevaluate_pareto(res.X, config, Nx_re, Ny_re, _reeval_cb)
        _save_pareto_csv(os.path.join(save_dir, "pareto_final_fine.csv"), res.X, F_fine)

        result['F_coarse'] = res.F.copy()
        result['F'] = F_fine

        if verbose:
            q_unit = 'W' if dim_final == 3 else 'W/m'
            print(f"  Fine Q range:  [{-F_fine[:,0].max():.2f}, {-F_fine[:,0].min():.2f}] {q_unit}")
            print(f"  Fine dP range: [{F_fine[:,1].min():.2f}, {F_fine[:,1].max():.2f}] Pa")

    if verbose:
        print(f"  Results in: {save_dir}")

    return result


# ── Visualization ────────────────────────────────────────────

def plot_pareto(result, save_path=None, baselines=None, title=None):
    """Plot Pareto front from optimization result.

    Parameters
    ----------
    result : dict — output of run_optimization, must contain 'F' (N, 2)
    save_path : str, optional — if given, saves PNG at this path
    baselines : dict, optional — {label: {'Q': float, 'dP': float}, ...}
        Plots each baseline as a labeled marker for reference.
    title : str, optional — plot title; defaults to "Pareto Front: Q vs ΔP"
    """
    import matplotlib.pyplot as plt

    F = result['F']
    Q = -F[:, 0]   # restore positive Q
    dP = F[:, 1]

    fig, ax = plt.subplots(figsize=(8, 6))
    sc = ax.scatter(dP, Q, c=Q/dP, cmap='viridis', s=40,
                    edgecolors='#333', linewidths=0.5, label='Pareto front')
    ax.set_xlabel('Total Pressure Drop ΔP [Pa]', fontsize=12)
    ax.set_ylabel('Total Heat Transfer Q [W/m]', fontsize=12)
    ax.set_title(title or 'Pareto Front: Q vs ΔP',
                 fontsize=14, fontweight='bold')
    cb = fig.colorbar(sc, ax=ax, shrink=0.8)
    cb.set_label('Q/ΔP efficiency [W/m/Pa]', fontsize=10)

    if baselines:
        markers = ['s', '^', 'D', 'v', 'P', 'X']
        colors = ['tab:orange', 'tab:green', 'tab:red',
                  'tab:purple', 'tab:brown', 'tab:pink']
        for i, (label, b) in enumerate(baselines.items()):
            ax.scatter(b['dP'], b['Q'],
                       marker=markers[i % len(markers)],
                       c=colors[i % len(colors)],
                       s=140, edgecolor='k', linewidths=1.0,
                       label=label, zorder=5)
        ax.legend(loc='best', fontsize=10)

    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=200, bbox_inches='tight')
        print(f"Saved: {save_path}")

    return fig


def plot_design_field(x, config=None, title=None, save_path=None):
    """Plot L(x,y) and t(x,y) sigmoid-continuous fields for a decision vector.

    Parameters
    ----------
    x : array-like (36,) — decision variable from evaluate() / Pareto front
    config : dict — same as passed to evaluate() / run_optimization
    title : str, optional — figure suptitle
    save_path : str, optional — if given, saves PNG at this path
    """
    import matplotlib.pyplot as plt
    from solvers.sigmoid_field import build_continuous_arrays, get_geometry_lut

    cfg = {**DEFAULT_CONFIG, **(config or {})}
    Nx, Ny = _resolve_grid(cfg)
    lut = get_geometry_lut(cfg['tpms_type'])
    dx = np.full(Nx, cfg['L_domain'] / Nx, dtype=np.float64)
    dy = np.full(Ny, cfg['H_domain'] / Ny, dtype=np.float64)
    za = build_continuous_arrays(
        x, cfg['L0'], cfg['t0'],
        cfg.get('y_trans_inlet', cfg.get('y_trans', 0.2)),
        cfg.get('y_trans_outlet', cfg.get('y_trans', 0.2)),
        Nx, Ny, cfg['L_domain'], cfg['H_domain'],
        cfg['tpms_type'], cfg['k_s'],
        cfg['u_A'], cfg['u_B'], cfg['T_inA'], cfg['T_inB'],
        lut,
        sigmoid_width_y=cfg.get('sigmoid_width_y', 0.02),
        sigmoid_width_x=cfg.get('sigmoid_width_x', 0.05),
        fix_L=cfg.get('fix_L', False),
        fix_t=cfg.get('fix_t', False),
        opt_axis=cfg.get('opt_axis', 'y'),
        dx_arr=dx, dy_arr=dy)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
    extent = [0, cfg['L_domain'] * 1000, 0, cfg['H_domain'] * 1000]

    im1 = ax1.imshow(za['L_field'].T, origin='lower', aspect='auto',
                     cmap='viridis', extent=extent)
    ax1.set_title(f"L [mm]  (range {za['L_field'].min():.2f}–{za['L_field'].max():.2f})")
    ax1.set_xlabel('x [mm]'); ax1.set_ylabel('y [mm]')
    plt.colorbar(im1, ax=ax1)

    im2 = ax2.imshow(za['t_field'].T, origin='lower', aspect='auto',
                     cmap='plasma', extent=extent)
    ax2.set_title(f"t [mm]  (range {za['t_field'].min():.3f}–{za['t_field'].max():.3f})")
    ax2.set_xlabel('x [mm]'); ax2.set_ylabel('y [mm]')
    plt.colorbar(im2, ax=ax2)

    if title:
        fig.suptitle(title)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
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
