"""run_calculation_3d.py — 3D compute pipeline for SJTU-TPMSHX UI.

Mirrors `runs.run_calculation` (2D) but dispatches the 3D stack:
    SIMPLESolver3D (fluid A: air compressible, fluid B: air or water) +
    LTNE 3-temp coupling + solve_full_domain_3d (3D LTNE) + outer non-iso.

MVP (2026-04-20): uniform geometry only (no zoning from UI). Mirrors
`validation/validate_shanghai_3d_real.py::_run_one_case` but with UI-sourced
parameters instead of Shanghai Excel.

Entry:
    run_calculation_3d_inner(window)     — runs stack, stores fields on window
    finalize_plots_3d(window)            — pushes fields into ThreeDVisPanel

Stored on window:
    window._result_3d = dict(
        Ta=..., vmag=..., P_kPa=..., L_mm=...,
        dx=..., dy=..., dz=...,
        Lx=..., Ly=..., Lz=...,
        Q=..., dP=..., u_A=..., T_in=...,
    )
"""

from __future__ import annotations
import numpy as np

from solvers.simple_solver_3d import SIMPLESolver3D
from solvers.solve_full_3d import solve_full_domain_3d
from solvers.tpms_calc import (
    geometry as tpms_geometry, air_density, air_viscosity,
    air_conductivity, air_cp, P_atm,
    water_density, water_viscosity, water_conductivity, water_cp,
)
from df_fit.predict import predict_K_cF


def _run_two_simple_parallel(sA, sB, *, max_iter=400, tol=1e-3):
    """Run SIMPLE A and SIMPLE B concurrently on two OS threads.

    `SIMPLESolver3D.solve` spends its wall-clock inside Numba njit kernels
    and PyAMG/BiCGStab (both release the GIL), so pure Python threading
    delivers real parallelism. Fluid A and Fluid B use independent instances
    (own matrix, ml_cache, arrays) — no shared mutable state.

    Raises the first worker's exception (if any) after both threads finish.
    """
    import threading

    err = [None, None]

    def _solve_A():
        try:
            sA.solve(max_iter=max_iter, tol=tol, verbose=False)
        except Exception as e:
            err[0] = e

    def _solve_B():
        try:
            sB.solve(max_iter=max_iter, tol=tol, verbose=False)
        except Exception as e:
            err[1] = e

    tA = threading.Thread(target=_solve_A, daemon=True)
    tB = threading.Thread(target=_solve_B, daemon=True)
    tA.start(); tB.start()
    tA.join();  tB.join()

    if err[0] is not None:
        raise err[0]
    if err[1] is not None:
        raise err[1]


R_AIR = 287.05
_MAX_OUTER = 3        # outer SIMPLE ↔ LTNE iterations
_OUTER_TOL = 0.5      # K
_ALPHA_T = 0.6


def run_calculation_3d_inner(window):
    """Phase 1: parse inputs → build fields → solve → store."""
    cfg = _parse_inputs(window)
    def _prog(pct):
        window._compute_progress = pct
    cfg['_progress_cb'] = _prog
    result = _run_3d_stack(cfg)
    window._result_3d = result
    # Fill legacy result labels (best-effort; 2D UI still reads these)
    try:
        window._r_Q.setText(f"{result['Q']:.2f}")
        window._r_dP_A.setText(f"{result['dP']:.0f}")
    except Exception:
        pass


def finalize_plots_3d(window):
    """Push 3D fields into the embedded panel + mid-z slices to 2D canvases."""
    res = getattr(window, '_result_3d', None)
    if res is None:
        return
    # Skeleton placeholder retires once real 3D data lands.
    sk = getattr(window, '_3d_skeleton', None)
    if sk is not None:
        try: sk.stop()
        except Exception: pass

    # ── 1. PyVistaQt 3D panel ──
    panel = getattr(window, 'canvas_3d', None)
    if panel is not None:
        try:
            P_B_kPa = None
            if res.get('P_Pa_B') is not None:
                P_B_kPa = np.ascontiguousarray(res['P_Pa_B'] / 1000.0)
            panel.set_fields(
                Ta=res['Ta'],
                Tb=res.get('Tb'),
                Ts=res.get('Ts'),
                vmag=res['vmag'],
                vmag_B=res.get('vmag_B'),
                P_kPa=res['P_kPa'],
                P_B_kPa=P_B_kPa,
                L_mm=res['L_mm'],
                dx=res['dx'], dy=res['dy'], dz=res['dz'],
                real_dims=(res['Lx'], res['Ly'], res['Lz']),
            )
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"[3D vis] set_fields failed: {e}")

    # ── 2. 2D canvases: auto mid-z slice (keeps Temperature/Pressure/Velocity
    #       tabs relevant under 3D mode) ──
    _render_2d_slices_from_3d(window, res)


def _render_2d_slices_from_3d(window, res):
    """Mid-z slice of 3D fields → Temperature/Pressure/Velocity canvases.

    Custom renderers (not `plot_temperature`/`plot_pressure`) because refined
    3D grid is non-uniform; legacy 2D plotters assume `np.linspace` spacing.
    """
    Ta = res['Ta']; Tb = res['Tb']; Ts = res['Ts']
    P_Pa = res['P_Pa']; uc = res['uc_real']; vc = res['vc_real']
    dx = res['dx']; dy = res['dy']
    Nx, Ny, Nz = Ta.shape
    k_mid = Nz // 2
    z_info = f'mid-z (k={k_mid}/{Nz})'

    # Legacy attrs for hover/export (single-step (1, Nx, Ny))
    window.T_fA = Ta[None, :, :, k_mid]
    window.T_fB = Tb[None, :, :, k_mid]
    window.T_s  = Ts[None, :, :, k_mid]
    window.P_fA = P_Pa[:, :, k_mid]
    window.P_fB = np.zeros_like(window.P_fA)

    # Shared cumsum coord grid (mm) — handles non-uniform dx/dy
    xc = (np.cumsum(dx) - dx / 2) * 1000.0
    yc = (np.cumsum(dy) - dy / 2) * 1000.0

    # Fluid B optional (cross-flow). Detect by presence of P_Pa_B
    P_Pa_B = res.get('P_Pa_B')
    vmag_B = res.get('vmag_B')
    uc_B = res.get('uc_real_B')
    vc_B = res.get('vc_real_B')
    dP_B = res.get('dP_B', 0.0)
    has_B = P_Pa_B is not None

    plot_jobs = [
        ('canvas_temp', _plot_3d_temperature,
            (Ta[:, :, k_mid], Tb[:, :, k_mid], Ts[:, :, k_mid], xc, yc, z_info)),
        ('canvas_pres', _plot_3d_pressure,
            (P_Pa[:, :, k_mid],
             P_Pa_B[:, :, k_mid] if has_B else None,
             xc, yc, res['dP'], dP_B, z_info)),
        ('canvas_vel', _plot_3d_velocity_slice,
            (uc[:, :, k_mid], vc[:, :, k_mid],
             uc_B[:, :, k_mid] if has_B else None,
             vc_B[:, :, k_mid] if has_B else None,
             xc, yc, z_info)),
    ]
    for attr, fn, args in plot_jobs:
        canvas = getattr(window, attr, None)
        if canvas is None:
            continue
        try:
            fn(canvas, *args)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"[3D->2D {attr}] {e}")


# Theme — resolved at call time via get_theme()
from ui.theme import get_theme as _get_theme


def _begin_canvas_plot(canvas, nrows=1, ncols=1):
    """Clear canvas + create axes + style spines. Returns (axes_iterable, (X, Y))
    placeholder None — caller provides xc/yc via a follow-up meshgrid."""
    _T = _get_theme()
    canvas.fig.clear()
    canvas.fig.patch.set_facecolor(_T['fig_bg'])
    axes = canvas.fig.subplots(nrows, ncols)
    canvas.axes = [axes if hasattr(axes, '__iter__') else [axes]]
    return axes


def _style_axis(ax, xlabel='x [mm]', ylabel='y [mm]', title='',
                title_size=12, label_size=10, tick_size=9):
    _T = _get_theme()
    ax.set_facecolor(_T['ax_bg'])
    if title:
        ax.set_title(title, fontsize=title_size, fontweight='bold',
                     color=_T['ax_text'])
    ax.set_xlabel(xlabel, fontsize=label_size, color=_T['ax_text'])
    ax.set_ylabel(ylabel, fontsize=label_size, color=_T['ax_text'])
    ax.tick_params(labelsize=tick_size, colors=_T['ax_text'])
    for sp in ax.spines.values():
        sp.set_edgecolor(_T['ax_spine'])


def _plot_3d_temperature(canvas, Ta_slice, Tb_slice, Ts_slice, xc, yc, z_info):
    """3-panel temperature (Ta / Tb / Ts) on mid-z slice."""
    _T = _get_theme()
    axes = _begin_canvas_plot(canvas, 1, 3)
    Y, X = np.meshgrid(yc, xc)
    vmin_f = min(Ta_slice.min(), Tb_slice.min())
    vmax_f = max(Ta_slice.max(), Tb_slice.max())
    datasets = [
        (Ta_slice, r'$T_{f,A}$ [K] — Fluid A', 'turbo', vmin_f, vmax_f),
        (Tb_slice, r'$T_{f,B}$ [K] — Fluid B (frozen)', 'turbo', vmin_f, vmax_f),
        (Ts_slice, r'$T_s$ [K] — Solid', 'coolwarm', Ts_slice.min(), Ts_slice.max()),
    ]
    for ax, (field, title, cmap, lo, hi) in zip(axes, datasets):
        cf = ax.contourf(X, Y, field, levels=100, cmap=cmap, vmin=lo, vmax=hi)
        cb = canvas.fig.colorbar(cf, ax=ax, shrink=0.85, aspect=18, format='%.1f')
        cb.ax.tick_params(labelsize=8, colors=_T['ax_text'])
        _style_axis(ax, title=title, title_size=11, label_size=9, tick_size=8)
    canvas.fig.suptitle(f'Temperature — 3D {z_info}', fontsize=12,
                         fontweight='bold', color=_T['ax_text'], y=0.995)
    canvas.fig.subplots_adjust(left=0.05, right=0.97, top=0.88, bottom=0.10,
                                wspace=0.32)
    canvas.draw()


def _plot_3d_pressure(canvas, P_slice_A, P_slice_B, xc, yc, dP_A, dP_B, z_info):
    """Pressure panels. If P_slice_B is None → single panel (A only, B frozen)."""
    _T = _get_theme()
    if P_slice_B is None:
        axes = [_begin_canvas_plot(canvas)]
        P_data = [(P_slice_A, 'A', dP_A)]
    else:
        axes = _begin_canvas_plot(canvas, 1, 2)
        P_data = [(P_slice_A, 'A', dP_A), (P_slice_B, 'B', dP_B)]
    Y, X = np.meshgrid(yc, xc)
    for ax, (p, tag, dp) in zip(axes, P_data):
        cf = ax.contourf(X, Y, p / 1000.0, levels=512, cmap='turbo')
        cb = canvas.fig.colorbar(cf, ax=ax, shrink=0.9, aspect=25, format='%.1f')
        cb.ax.tick_params(labelsize=9, colors=_T['ax_text'])
        _style_axis(ax, title=(f'$P_{tag}$ (kPa) — Fluid {tag} — 3D {z_info}   '
                                rf'$|\Delta P|$ = {dp:.0f} Pa'))
    canvas.fig.subplots_adjust(left=0.06, right=0.96, top=0.90, bottom=0.10,
                                wspace=0.25)
    canvas.draw()


def _plot_3d_velocity_slice(canvas, uA, vA, uB, vB, xc, yc, z_info):
    """Velocity magnitude panels. If uB is None → single panel (A only)."""
    _T = _get_theme()
    if uB is None:
        axes = [_begin_canvas_plot(canvas)]
        V_data = [(uA, vA, 'A')]
    else:
        axes = _begin_canvas_plot(canvas, 1, 2)
        V_data = [(uA, vA, 'A'), (uB, vB, 'B')]
    Y, X = np.meshgrid(yc, xc)
    for ax, (u, v, tag) in zip(axes, V_data):
        vmag = np.sqrt(u ** 2 + v ** 2)
        cf = ax.contourf(X, Y, vmag, levels=512, cmap='turbo')
        cb = canvas.fig.colorbar(cf, ax=ax, shrink=0.9, aspect=25, format='%.2f')
        cb.ax.tick_params(labelsize=9, colors=_T['ax_text'])
        _style_axis(ax, title=f'|v| (m/s) — Fluid {tag} — 3D {z_info}')
    canvas.fig.subplots_adjust(left=0.06, right=0.96, top=0.92, bottom=0.08,
                                wspace=0.25)
    canvas.draw()


# ─────────────────────────── internals ────────────────────────────

def _parse_inputs(window):
    def _f(widget, name):
        try:
            return float(widget.text())
        except ValueError:
            raise ValueError(f"Invalid number in {name!r}: {widget.text()!r}")

    def _i(widget, name):
        try:
            return int(widget.text())
        except ValueError:
            raise ValueError(f"Invalid integer in {name!r}: {widget.text()!r}")

    L = _f(window.le_L, "Length L")
    H = _f(window.le_H, "Width H")
    Lz = _f(window.le_Lz, "Depth Lz")
    Nx = _i(window.le_Nx, "Grid Nx")
    Ny = _i(window.le_Ny, "Grid Ny")
    Nz = _i(window.le_Nz, "Grid Nz")

    # Basic positive-domain sanity checks
    for name, val in [('L', L), ('H', H), ('Lz', Lz)]:
        if val <= 0:
            raise ValueError(f"Domain dimension {name!r} must be > 0 (got {val})")
    for name, val in [('Nx', Nx), ('Ny', Ny), ('Nz', Nz)]:
        if val < 1:
            raise ValueError(f"Grid count {name!r} must be >= 1 (got {val})")
    u_A = _f(window.le_uA, "Velocity u_A")
    # Honour UI K/°C toggle — _temp_to_K returns Kelvin regardless of display
    if hasattr(window, '_temp_to_K'):
        T_inA = window._temp_to_K(window.le_TinA)
        T_inB = window._temp_to_K(window.le_TinB)
    else:
        T_inA = _f(window.le_TinA, "Inlet T_A")
        T_inB = _f(window.le_TinB, "Inlet T_B")
    P_inA = _f(window.le_PinA, "Inlet P_A") if hasattr(window, 'le_PinA') else P_atm + 1e5
    P_inB = _f(window.le_PinB, "Inlet P_B") if hasattr(window, 'le_PinB') else P_atm
    Lcell = _f(window.le_Lcell, "TPMS L_cell")
    t_wall = _f(window.le_t, "TPMS t")
    k_s = _f(window.le_ks, "TPMS k_s")
    tpms_type = window.combo_tpms.currentText()

    g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
    eps = g['epsilon']
    D_h = g['D_h']

    # Fluid A + B inlet/outlet config (for partial BC). Fallback = full face.
    try:
        fluid_A_cfg = window._fluid_config('A')
    except Exception:
        fluid_A_cfg = dict(dir=0, in_ctr=H / 2, in_w=H,
                           out_ctr=H / 2, out_w=H)
    try:
        fluid_B_cfg = window._fluid_config('B')
    except Exception:
        fluid_B_cfg = None
    try:
        u_B = float(window.le_uB.text())
    except Exception:
        u_B = u_A

    from solvers.tpms_calc import parse_fluid_type, validate_fluid_type

    fluid_type_A = 'air'
    if hasattr(window, 'combo_fluidA'):
        fluid_type_A = parse_fluid_type(window.combo_fluidA)

    fluid_type_B = 'air'
    if hasattr(window, 'combo_fluidB'):
        fluid_type_B = parse_fluid_type(window.combo_fluidB)

    validate_fluid_type(fluid_type_A, 'A')
    validate_fluid_type(fluid_type_B, 'B')

    # 3D wall refinement toggle (default ON — adds 8 BL cells near each of
    # the 6 walls with first_cell=0.02 mm + growth ratio 1.8).
    wall_refine = True
    if hasattr(window, 'chk_wall_refine_3d'):
        wall_refine = bool(window.chk_wall_refine_3d.isChecked())

    # Optional zone grid (2D design broadcast over z for 3D z-uniform zoning)
    zone_grid_cells = None
    if (getattr(window, 'chk_zones', None) is not None
            and window.chk_zones.isChecked()
            and getattr(window, '_zone_grid', None) is not None):
        zg = window._zone_grid
        if isinstance(zg, dict) and zg.get('cells'):
            zone_grid_cells = zg['cells']

    return dict(
        L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        u_A=u_A, u_B=u_B, T_inA=T_inA, T_inB=T_inB, P_inA=P_inA, P_inB=P_inB,
        Lcell=Lcell, t_wall=t_wall, k_s=k_s, tpms_type=tpms_type,
        eps=eps, D_h=D_h,
        fluid_A_cfg=fluid_A_cfg,
        fluid_B_cfg=fluid_B_cfg,
        wall_refine_3d=wall_refine,
        zone_grid_cells=zone_grid_cells,
        fluid_type_A=fluid_type_A,
        fluid_type_B=fluid_type_B,
    )


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
    # Reverse dir swaps which face the solver calls "inlet"
    if is_reverse:
        in_c1, out_c1 = out_c1, in_c1
        in_c2, out_c2 = out_c2, in_c2
    in_mask = np.outer(in_c1, in_c2).astype(np.float64)   # (N_cross1, N_cross2)
    out_mask = np.outer(out_c1, out_c2).astype(np.float64)
    return in_mask, out_mask


def _run_3d_stack(cfg):
    """Unified 3D stack: SIMPLE3D (A) + frozen Tb + LTNE3D.

    Supports fluid-A streamwise direction ∈ {+x, -x, +y, -y} and partial
    inlet/outlet in the cross-stream dimension (z-partial optional via
    `in_z_ctr`/`in_z_w` etc. in `fluid_A_cfg`).
    """
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
    wall_refine = cfg.get('wall_refine_3d', True)

    # Grid: either uniform user spacing or 6-wall boundary-layer refinement.
    # Refined grid expands user N by ~+2×n_refine cells per axis (n_refine=8
    # each wall; first cell 0.02 mm, growth 1.8). Typical: user 20×10×5 →
    # actual 36×26×21. Improves BL capture in every direction (including z).
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
    eps_field_3d = None    # per-cell porosity if zoned
    if zone_cells:
        L_mm_field, t_field_3d, eps_field_3d = _build_zone_fields_3d(
            zone_cells, Nx, Ny, Nz, L, H, tpms_type, k_s, Lcell, t_wall)
        from df_fit.predict import predict_K_cF_vec
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
        K_pred, cF_pred = predict_K_cF(tpms_type, Lcell, t_wall, eps / 2.0)
        K_A_arr = np.full((N_stream, N_cross2), K_pred)
        cF_A_arr = np.full((N_stream, N_cross2), cF_pred)

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
    sA = SIMPLESolver3D(
        **solver_init,
        rho=rho_A, mu=mu_A, T_in=T_inA, v_inlet=v_inlet_field,
        eps=eps, K_arr=K_A_arr, cF_arr=cF_A_arr,
        P_ref_abs=P_ref_A, fluid_type='ideal_gas',
    )
    sA.inlet_frac = in_mask_2d
    sA.outlet_frac = out_mask_2d
    sA.apply_outlet_taper(n_taper=8, min_frac=0.2)
    sA.outlet_frac = (sA.outlet_frac * out_mask_2d).astype(np.float64)
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
    sB = None
    sB_info = None
    if fB is not None:
        u_B = cfg.get('u_B', u_A)
        if is_water_B:
            rho_B = float(water_density(T_inB))
            mu_B = float(water_viscosity(T_inB))
        else:
            rho_B = air_density(T_inB, P_inB)
            mu_B = air_viscosity(T_inB)
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
        G_B = rho_B * u_B
        if is_water_B:
            C_B = mu_B * G_B / max(K_pred, 1e-16) + cF_pred * G_B * G_B
            P_ref_B = float(P_inB - C_B * L_stream_B / rho_B)
            P_ref_B = max(P_ref_B, 1.0e4)
            solver_fluid_type_B = 'incompressible'
        else:
            C_B = mu_B * G_B / max(K_pred, 1e-16) + cF_pred * G_B * G_B
            P_out_sq_B = P_inB ** 2 - 2.0 * R_AIR * T_inB * C_B * L_stream_B
            P_ref_B = float(np.sqrt(max(P_out_sq_B, 1.0e4)))
            solver_fluid_type_B = 'ideal_gas'
        in_mask_B, out_mask_B = _build_partial_masks(
            fB, dcross1_B, dcross2_B,
            axis_map_B['N_cross1'], axis_map_B['N_cross2'], is_reverse_B)
        v_inlet_B = np.where(in_mask_B > 0.5, u_B, 0.0).astype(np.float64)
        sB = SIMPLESolver3D(
            **axis_map_B['solver_init'],
            rho=rho_B, mu=mu_B, T_in=T_inB, v_inlet=v_inlet_B,
            eps=eps, K_arr=K_B_arr, cF_arr=cF_B_arr,
            P_ref_abs=P_ref_B, fluid_type=solver_fluid_type_B,
        )
        sB.inlet_frac = in_mask_B
        sB.outlet_frac = out_mask_B
        sB.apply_outlet_taper(n_taper=8, min_frac=0.2)
        sB.outlet_frac = (sB.outlet_frac * out_mask_B).astype(np.float64)
        # sB.solve deferred — dispatched with sA below in parallel threads.
        sB_info = dict(
            axis_map=axis_map_B,
            u_B=u_B, rho_B=rho_B, mu_B=mu_B,
            G_B=G_B, T_inB=T_inB,
        )
        # ── Parallel SIMPLE A + B solve (threads, njit releases GIL) ──
        _run_two_simple_parallel(sA, sB)
        # LTNE fluid B velocity: extract real-coord stream component via perm
        v_cc_B = 0.5 * (sB.v[:, :-1, :] + sB.v[:, 1:, :])
        streamB = v_cc_B.transpose(perm_B)
        if is_reverse_B:
            streamB = -streamB
        ucB = np.zeros((Nx, Ny, Nz))
        vcB = np.zeros((Nx, Ny, Nz))
        wcB = np.zeros((Nx, Ny, Nz))
        if is_x_stream_B:
            ucB = streamB
        elif is_y_stream_B:
            vcB = streamB
        else:
            wcB = streamB
        Tb_presc = None  # let LTNE solve Tb from convection
    else:
        # No B: run A alone (serial)
        sA.solve(max_iter=400, tol=1e-3, verbose=False)
        ucB = np.zeros((Nx, Ny, Nz))
        vcB = np.zeros((Nx, Ny, Nz))
        wcB = np.zeros((Nx, Ny, Nz))
        Tb_presc = np.full((Nx, Ny, Nz), T_inB, dtype=np.float64)

    # LTNE inputs — Fluid A always air, Fluid B dispatches on fluid_type_B.
    if is_water_B:
        cp_B = water_cp(T_inB)
        k_B = float(water_conductivity(T_inB))
        rho_B_ltne = float(water_density(T_inB))
    else:
        cp_B = air_cp(T_inB)
        k_B = air_conductivity(T_inB)
        rho_B_ltne = air_density(T_inB, P_inB)
    eps_arr = (eps_field_3d.copy() if eps_field_3d is not None
               else np.full((Nx, Ny, Nz), eps))
    eps_f = eps / 2.0
    K_ffA = np.full((Nx, Ny, Nz), eps_f * k_A)
    K_ffB = np.full((Nx, Ny, Nz), eps_f * k_B)
    K_ss = np.full((Nx, Ny, Nz), (1.0 - eps) * k_s)

    # h_v from Nu correlation (P0 fix: was hardcoded 1e5, now physics-based).
    # h_v = A_0 × H_sf_face, where H_sf = Nu × k_f / D_h.
    # A (hot air) and B (cold air) have different Re → different Nu → different h_v.
    from solvers.tpms_calc import compute as tpms_compute
    _geom_A = tpms_compute(tpms_type, Lcell, t_wall, u_A, T_inA, P_inA, k_s)
    h_vA0 = _geom_A['A_0'] * _geom_A['H_sf']
    u_B_val = cfg.get('u_B', u_A)
    _geom_B = tpms_compute(tpms_type, Lcell, t_wall, u_B_val, T_inB, P_inB, k_s)
    h_vB0 = _geom_B['A_0'] * _geom_B['H_sf']
    h_vA_field = np.full((Nx, Ny, Nz), h_vA0, dtype=np.float64)
    h_vB_field = np.full((Nx, Ny, Nz), h_vB0, dtype=np.float64)
    # P2: rho_cp as 3D field (not scalar) for per-cell accuracy
    rho_cp_fA = np.full((Nx, Ny, Nz), rho_A * cp_A, dtype=np.float64)
    rho_cp_fB = np.full((Nx, Ny, Nz), rho_B_ltne * cp_B, dtype=np.float64)

    # Helper: solver streamwise velocity → correct real component (uc/vc/wc).
    # Transposes solver (Nx_sol, Ny_sol, Nz_sol) → real (Nx, Ny, Nz) via
    # `solver_to_real_perm` (self-inverse for all 3 supported perms), then
    # assigns the streamwise vector to the matching real axis.
    def _assemble_real_velocity():
        v_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])
        stream = v_cc.transpose(solver_to_real_perm)
        if is_reverse:
            stream = -stream
        zeros = np.zeros((Nx, Ny, Nz))
        if is_x_stream:
            return stream, zeros, zeros.copy()
        if is_y_stream:
            return zeros, stream, zeros.copy()
        return zeros, zeros.copy(), stream          # z-stream

    # ── Outer SIMPLE ↔ LTNE coupling ──
    Ta = Tb = Ts = None
    Ta_prev = None
    _progress_cb = cfg.get('_progress_cb')
    for outer in range(_MAX_OUTER):
        if _progress_cb is not None:
            _progress_cb(10 + int(80 * outer / _MAX_OUTER))
        ucA, vcA, wcA = _assemble_real_velocity()

        Ta, Tb, Ts = solve_full_domain_3d(
            L, H, Lz, Nx, Ny, Nz, T_inA, T_inB,
            K_ffA, K_ffB, K_ss, h_vA_field, h_vB_field,
            rho_cp_fA, rho_cp_fB, eps_arr,
            ucA, vcA, wcA, ucB, vcB, wcB,
            dir_A=fA['dir'],
            dir_B=(fB['dir'] if fB is not None else 3),
            dx_arr=dx, dy_arr=dy, dz_arr=dz,
            Tb_prescribed=Tb_presc, max_iter=20000, tol=1e-5,
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts, alpha_T=0.7)

        if Ta_prev is not None:
            dT = float(np.max(np.abs(Ta - Ta_prev)))
            if dT < _OUTER_TOL:
                break
        Ta_prev = Ta.copy()

        # Non-iso coupling: Ta real → solver coords via self-inverse perm
        Ta_sA = np.ascontiguousarray(Ta.transpose(solver_to_real_perm))
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
        sA._mu_eff_field = np.ascontiguousarray(
            sA.mu_field / sA.eps, dtype=np.float64)

        T_avg = float(Ta_sA.mean())
        mu_avg = float(air_viscosity(T_avg))
        C_avg = mu_avg * G_A / max(K_pred, 1e-16) + cF_pred * G_A * G_A
        P_out_sq_new = P_inA ** 2 - 2.0 * R_AIR * T_avg * C_avg * L_stream
        sA.P_ref_abs = float(np.sqrt(max(P_out_sq_new, 1.0e4)))

        # Warm restart: SIMPLE fields nearly converged after outer 0.
        # ρ/μ change is small (α_T=0.6 under-relaxation), so 150 iter is plenty
        # for the residual to re-sink to 1e-3. Saves ~50% of SIMPLE work in
        # outer iters 1-2.
        sA.solve(max_iter=150, tol=1e-3, verbose=False)

        # P0/P1: Refresh h_v from Nu(Re_local, T_local) for both fluids.
        # P10: Refresh K_ff from k_air(T) for both fluids.
        # P2: Refresh rho_cp as 3D fields.
        T_avgA = float(Ta.mean())
        _gA = tpms_compute(tpms_type, Lcell, t_wall, u_A, T_avgA, P_inA, k_s)
        h_vA_field[:] = _gA['A_0'] * _gA['H_sf']
        K_ffA[:] = eps_f * air_conductivity(T_avgA)
        rho_cp_fA[:] = air_density(T_avgA, P_inA) * air_cp(T_avgA)

        if Tb is not None:
            T_avgB = float(Tb.mean())
            _gB = tpms_compute(tpms_type, Lcell, t_wall, u_B_val, T_avgB, P_inB, k_s)
            h_vB_field[:] = _gB['A_0'] * _gB['H_sf']
            if is_water_B:
                K_ffB[:] = eps_f * water_conductivity(T_avgB)
                rho_cp_fB[:] = water_density(T_avgB) * water_cp(T_avgB)
            else:
                K_ffB[:] = eps_f * air_conductivity(T_avgB)
                rho_cp_fB[:] = air_density(T_avgB, P_inB) * air_cp(T_avgB)

        # Non-iso coupling for fluid B. Water: ρ(T) only, no ideal gas.
        # Air: ρ(P,T) via ideal gas law (mirror of A).
        if sB is not None and Tb is not None:
            Tb_sB = np.ascontiguousarray(Tb.transpose(perm_B))
            if is_water_B:
                rho_new_B = water_density(Tb_sB)
                mu_new_B = water_viscosity(Tb_sB)
            else:
                P_abs_B = sB.P_ref_abs + sB.P
                rho_new_B = P_abs_B / (R_AIR * Tb_sB)
                mu_new_B = air_viscosity(Tb_sB)
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
            sB._mu_eff_field = np.ascontiguousarray(
                sB.mu_field / sB.eps, dtype=np.float64)

            if not is_water_B:
                Tb_avg = float(Tb_sB.mean())
                mu_avg_B = float(air_viscosity(Tb_avg))
                C_avg_B = (mu_avg_B * G_B / max(K_pred, 1e-16)
                           + cF_pred * G_B * G_B)
                P_out_sq_B_new = (P_inB ** 2
                                  - 2.0 * R_AIR * Tb_avg * C_avg_B * L_stream_B)
                sB.P_ref_abs = float(np.sqrt(max(P_out_sq_B_new, 1.0e4)))

            sB.update_T_field(Tb_sB)
            sB.solve(max_iter=150, tol=1e-3, verbose=False)

            # rho_cp_fB already refreshed above (P0/P1/P2 block)

            # Re-extract B velocity for next LTNE pass
            v_cc_B2 = 0.5 * (sB.v[:, :-1, :] + sB.v[:, 1:, :])
            streamB2 = v_cc_B2.transpose(perm_B)
            if is_reverse_B:
                streamB2 = -streamB2
            ucB[:] = 0; vcB[:] = 0; wcB[:] = 0
            if is_x_stream_B:
                ucB[:] = streamB2
            elif is_y_stream_B:
                vcB[:] = streamB2
            else:
                wcB[:] = streamB2

    # ── Extract metrics + fields ──
    # Q: single-channel void area = (eps/2) × cross1 × cross2.
    # Use bulk-mean ρ (inlet+outlet average) for mass flow accuracy.
    out_idx = 0 if is_reverse else -1
    T_A_out = float(np.mean(np.take(Ta, out_idx, axis=stream_real_axis)))
    # Fixed velocity inlet BC → m_dot = ρ_in × u_in × A_void (inlet face).
    # NOT average ρ: solver enforces u_in at inlet with inlet density.
    m_dot = rho_A * u_A * (eps / 2.0 * L_cross1 * L_cross2)
    Q = abs(m_dot * cp_A * (T_inA - T_A_out))

    dP = float(SIMPLESolver3D.extract_dP_weighted(sA))

    uc_real, vc_real, wc_real = _assemble_real_velocity()
    vmag = np.sqrt(uc_real ** 2 + vc_real ** 2 + wc_real ** 2)

    # P field → real coords via solver perm
    P_real = np.ascontiguousarray(sA.P.transpose(solver_to_real_perm))
    P_kPa = P_real / 1000.0
    L_mm = (L_mm_field.copy() if L_mm_field is not None
            else np.full((Nx, Ny, Nz), Lcell, dtype=np.float64))

    # Fluid B fields (if sB solved): real-coord P + velocity magnitude
    if sB is not None:
        perm_B = sB_info['axis_map']['solver_to_real_perm']
        P_real_B = np.ascontiguousarray(sB.P.transpose(perm_B))
        vmag_B = np.sqrt(ucB ** 2 + vcB ** 2 + wcB ** 2)
        dP_B = float(SIMPLESolver3D.extract_dP_weighted(sB))
    else:
        P_real_B = None
        vmag_B = None
        dP_B = 0.0

    return dict(
        Ta=Ta, Tb=Tb, Ts=Ts,
        vmag=vmag, P_kPa=P_kPa, L_mm=L_mm,
        P_Pa=P_real,
        uc_real=uc_real, vc_real=vc_real,
        # Fluid B (None if frozen)
        P_Pa_B=P_real_B,
        uc_real_B=ucB, vc_real_B=vcB,
        vmag_B=vmag_B, dP_B=dP_B,
        dx=dx, dy=dy, dz=dz,
        Lx=L, Ly=H, Lz=Lz,
        Q=Q, dP=dP, u_A=u_A, T_in=T_inA,
        dir_A=fA['dir'],
    )
