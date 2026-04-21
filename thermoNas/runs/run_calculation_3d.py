"""run_calculation_3d.py — 3D compute pipeline for ThermoNAS UI.

Mirrors `runs.run_calculation` (2D) but dispatches the 3D stack:
    SIMPLESolver3D (fluid A, compressible) + Tb-prescribed (water frozen)
    + solve_full_domain_3d (3D LTNE) + outer non-iso coupling.

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
)
from df_fit.predict import predict_K_cF

R_AIR = 287.05
_MAX_OUTER = 3        # outer SIMPLE ↔ LTNE iterations
_OUTER_TOL = 0.5      # K
_ALPHA_T = 0.6


def run_calculation_3d_inner(window):
    """Phase 1: parse inputs → build fields → solve → store."""
    cfg = _parse_inputs(window)
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

    # ── 1. PyVistaQt 3D panel ──
    panel = getattr(window, 'canvas_3d', None)
    if panel is not None:
        try:
            panel.set_fields(
                Ta=res['Ta'], vmag=res['vmag'],
                P_kPa=res['P_kPa'], L_mm=res['L_mm'],
                dx=res['dx'], dy=res['dy'], dz=res['dz'],
                real_dims=(res['Lx'], res['Ly'], res['Lz']),
            )
        except Exception as e:
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

    plot_jobs = [
        ('canvas_temp', _plot_3d_temperature,
            (Ta[:, :, k_mid], Tb[:, :, k_mid], Ts[:, :, k_mid], xc, yc, z_info)),
        ('canvas_pres', _plot_3d_pressure,
            (P_Pa[:, :, k_mid], xc, yc, res['dP'], z_info)),
        ('canvas_vel', _plot_3d_velocity_slice,
            (uc[:, :, k_mid], vc[:, :, k_mid], xc, yc, z_info)),
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


# Cached theme (loaded once)
from ui.theme import _THEMES as _THEMES_CACHE
_T = _THEMES_CACHE['light']


def _begin_canvas_plot(canvas, nrows=1, ncols=1):
    """Clear canvas + create axes + style spines. Returns (axes_iterable, (X, Y))
    placeholder None — caller provides xc/yc via a follow-up meshgrid."""
    canvas.fig.clear()
    canvas.fig.patch.set_facecolor(_T['fig_bg'])
    axes = canvas.fig.subplots(nrows, ncols)
    canvas.axes = [axes if hasattr(axes, '__iter__') else [axes]]
    return axes


def _style_axis(ax, xlabel='x [mm]', ylabel='y [mm]', title='',
                title_size=12, label_size=10, tick_size=9):
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


def _plot_3d_pressure(canvas, P_slice, xc, yc, dP, z_info):
    """Single-panel pressure (Fluid A only — B frozen)."""
    ax = _begin_canvas_plot(canvas)
    Y, X = np.meshgrid(yc, xc)
    cf = ax.contourf(X, Y, P_slice / 1000.0, levels=512, cmap='turbo')
    cb = canvas.fig.colorbar(cf, ax=ax, shrink=0.9, aspect=25, format='%.1f')
    cb.ax.tick_params(labelsize=9, colors=_T['ax_text'])
    _style_axis(ax, title=(f'$P_A$ (kPa) — Fluid A — 3D {z_info}   '
                            rf'$|\Delta P|$ = {dP:.0f} Pa'))
    canvas.fig.subplots_adjust(left=0.08, right=0.95, top=0.90, bottom=0.10)
    canvas.draw()


def _plot_3d_velocity_slice(canvas, u_slice, v_slice, xc, yc, z_info):
    """Velocity magnitude contourf."""
    ax = _begin_canvas_plot(canvas)
    Y, X = np.meshgrid(yc, xc)
    vmag = np.sqrt(u_slice ** 2 + v_slice ** 2)
    cf = ax.contourf(X, Y, vmag, levels=512, cmap='turbo')
    cb = canvas.fig.colorbar(cf, ax=ax, shrink=0.9, aspect=25, format='%.2f')
    cb.ax.tick_params(labelsize=9, colors=_T['ax_text'])
    _style_axis(ax, title=f'|v| (m/s) — Fluid A — 3D {z_info}')
    canvas.fig.subplots_adjust(left=0.08, right=0.95, top=0.92, bottom=0.08)
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
    T_inA = _f(window.le_TinA, "Inlet T_A")
    T_inB = _f(window.le_TinB, "Inlet T_B")
    P_inA = _f(window.le_PinA, "Inlet P_A") if hasattr(window, 'le_PinA') else P_atm + 1e5
    Lcell = _f(window.le_Lcell, "TPMS L_cell")
    t_wall = _f(window.le_t, "TPMS t")
    k_s = _f(window.le_ks, "TPMS k_s")
    tpms_type = window.combo_tpms.currentText()

    g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
    eps = g['epsilon']
    D_h = g['D_h']

    # Fluid A inlet/outlet config (for partial BC). Fallback = full face.
    try:
        fluid_A_cfg = window._fluid_config('A')
    except Exception:
        fluid_A_cfg = dict(dir=0, in_ctr=H / 2, in_w=H,
                           out_ctr=H / 2, out_w=H)

    # 3D wall refinement toggle (default ON — adds 8 BL cells near each of
    # the 6 walls with first_cell=0.02 mm + growth ratio 1.8).
    wall_refine = True
    if hasattr(window, 'chk_wall_refine_3d'):
        wall_refine = bool(window.chk_wall_refine_3d.isChecked())

    return dict(
        L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        u_A=u_A, T_inA=T_inA, T_inB=T_inB, P_inA=P_inA,
        Lcell=Lcell, t_wall=t_wall, k_s=k_s, tpms_type=tpms_type,
        eps=eps, D_h=D_h,
        fluid_A_cfg=fluid_A_cfg,
        wall_refine_3d=wall_refine,
    )


def _resolve_axis_map(fA, Nx, Ny, Nz, L, H, Lz, dx, dy, dz):
    """Map fluid-A direction code to SIMPLE3D solver axes + mask geometry.

    `dir_A`: 0=+x 1=-x 2=+y 3=-y  (matches 2D `_dir_int` convention).

    Returns dict with is_x_stream, is_reverse, solver_init, N_cross/N_stream,
    L_cross/L_stream, dcross/dstream, stream_real_axis. Callers apply
    `arr.transpose(1, 0, 2)` themselves if `is_x_stream` is True (solver/real
    axis swap is self-inverse; inlining keeps call sites explicit).
    """
    d = fA['dir']
    is_x_stream = d <= 1
    is_reverse = d in (1, 3)
    if is_x_stream:
        return dict(
            is_x_stream=True, is_reverse=is_reverse,
            solver_init=dict(Lx=H, Ly=L, Lz=Lz, Nx=Ny, Ny=Nx, Nz=Nz),
            N_cross=Ny, N_stream=Nx, L_cross=H, L_stream=L,
            dcross=dy, dstream=dx, stream_real_axis=0,
        )
    return dict(
        is_x_stream=False, is_reverse=is_reverse,
        solver_init=dict(Lx=L, Ly=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz),
        N_cross=Nx, N_stream=Ny, L_cross=L, L_stream=H,
        dcross=dx, dstream=dy, stream_real_axis=1,
    )


def _build_partial_masks(fA, dcross, Nz, N_cross, is_reverse):
    """Build inlet/outlet boolean masks on cross-stream axis + optional z-partial.

    Supports `in_z_ctr`/`in_z_w`/`out_z_ctr`/`out_z_w` (optional — default full depth).
    """
    cross_centres = np.cumsum(dcross) - dcross / 2
    in_lo = fA['in_ctr'] - fA['in_w'] / 2
    in_hi = fA['in_ctr'] + fA['in_w'] / 2
    out_lo = fA['out_ctr'] - fA['out_w'] / 2
    out_hi = fA['out_ctr'] + fA['out_w'] / 2
    in_c = (cross_centres >= in_lo - 1e-12) & (cross_centres <= in_hi + 1e-12)
    out_c = (cross_centres >= out_lo - 1e-12) & (cross_centres <= out_hi + 1e-12)
    if not in_c.any() or not out_c.any():
        raise ValueError("Inlet / outlet range resolves to zero cells — check "
                         "in_ctr / in_w / out_ctr / out_w vs cross-stream length.")

    # Optional z-partial (future UI hook). Default = full depth.
    in_z = np.ones(Nz, dtype=bool)
    out_z = np.ones(Nz, dtype=bool)
    # Reverse dir swaps which face the solver calls "inlet"
    if is_reverse:
        in_c, out_c = out_c, in_c
        in_z, out_z = out_z, in_z
    in_mask = np.outer(in_c, in_z).astype(np.float64)     # (N_cross, Nz)
    out_mask = np.outer(out_c, out_z).astype(np.float64)
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
    is_reverse = axis_map['is_reverse']
    N_cross, L_cross = axis_map['N_cross'], axis_map['L_cross']
    L_stream = axis_map['L_stream']
    dcross = axis_map['dcross']
    stream_real_axis = axis_map['stream_real_axis']
    solver_init = axis_map['solver_init']
    N_stream = axis_map['N_stream']

    # Fluid A properties at inlet
    rho_A = air_density(T_inA, P_inA)
    mu_A = air_viscosity(T_inA)
    cp_A = air_cp(T_inA)
    k_A = air_conductivity(T_inA)

    # D-F surrogate. SIMPLE3D K_arr/cF_arr shape = (Ny_sA, Nz) where Ny_sA
    # is the solver streamwise axis = N_stream in real coords.
    K_pred, cF_pred = predict_K_cF(tpms_type, Lcell, t_wall, eps / 2.0)
    K_A_arr = np.full((N_stream, Nz), K_pred)
    cF_A_arr = np.full((N_stream, Nz), cF_pred)

    # P_ref_abs 1D closed-form seed (uses streamwise length L_stream)
    G_A = rho_A * u_A
    C_est = mu_A * G_A / max(K_pred, 1e-16) + cF_pred * G_A * G_A
    P_out_sq = P_inA ** 2 - 2.0 * R_AIR * T_inA * C_est * L_stream
    P_ref_A = float(np.sqrt(max(P_out_sq, 1.0e4)))

    # Partial inlet / outlet (cross-stream + optional z-partial)
    in_mask_2d, out_mask_2d = _build_partial_masks(
        fA, dcross, Nz, N_cross, is_reverse)
    v_inlet_field = np.where(in_mask_2d > 0.5, u_A, 0.0).astype(np.float64)

    # ── SIMPLE A (3D, compressible) ──
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
    sA.solve(max_iter=400, tol=1e-3, verbose=False)

    # ── Fluid B frozen: Tb linear along real y ──
    ucB = np.zeros((Nx, Ny, Nz))
    vcB = np.zeros((Nx, Ny, Nz))
    wcB = np.zeros((Nx, Ny, Nz))

    # Fluid B uniform at T_inB (frozen — no mass flow, acts as constant sink)
    Tb_presc = np.full((Nx, Ny, Nz), T_inB, dtype=np.float64)

    # LTNE inputs
    eps_arr = np.full((Nx, Ny, Nz), eps)
    eps_f = eps / 2.0
    K_ffA = np.full((Nx, Ny, Nz), eps_f * k_A)
    K_ffB = np.full((Nx, Ny, Nz), eps_f * 0.6)    # water-equivalent k
    K_ss = np.full((Nx, Ny, Nz), (1.0 - eps) * k_s)

    h_vA0 = 1.0e5   # Shanghai-ish nominal h_v (overridden after first outer step)
    h_vA_field = np.full((Nx, Ny, Nz), h_vA0)
    h_vB_field = np.full((Nx, Ny, Nz), 1.0e10)    # perfect water sink
    rho_cp_A = rho_A * cp_A
    rho_cp_B = 998.0 * 4182.0

    # Helper: solver streamwise velocity → real component (uc or vc)
    def _assemble_real_velocity():
        v_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])   # (Nx_sA, Ny_sA, Nz)
        stream = v_cc.transpose(1, 0, 2) if is_x_stream else v_cc
        if is_reverse:
            stream = -stream
        zeros = np.zeros((Nx, Ny, Nz))
        if is_x_stream:
            return stream, zeros, zeros.copy()
        return zeros, stream, zeros.copy()

    # ── Outer SIMPLE ↔ LTNE coupling ──
    Ta = Tb = Ts = None
    Ta_prev = None
    for outer in range(_MAX_OUTER):
        ucA, vcA, wcA = _assemble_real_velocity()

        Ta, Tb, Ts = solve_full_domain_3d(
            L, H, Lz, Nx, Ny, Nz, T_inA, T_inB,
            K_ffA, K_ffB, K_ss, h_vA_field, h_vB_field,
            rho_cp_A, rho_cp_B, eps_arr,
            ucA, vcA, wcA, ucB, vcB, wcB,
            dir_A=fA['dir'], dir_B=3,
            dx_arr=dx, dy_arr=dy, dz_arr=dz,
            Tb_prescribed=Tb_presc, max_iter=20000, tol=1e-5,
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts, alpha_T=0.7)

        if Ta_prev is not None:
            dT = float(np.max(np.abs(Ta - Ta_prev)))
            if dT < _OUTER_TOL:
                break
        Ta_prev = Ta.copy()

        # Non-iso coupling: update ρ/μ in solver coords (transpose if x-stream)
        Ta_sA = Ta.transpose(1, 0, 2).copy() if is_x_stream else Ta.copy()
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

    # ── Extract metrics + fields ──
    # Q: mass flow uses void cross-section (eps * L_cross * Lz)
    m_dot = rho_A * u_A * (eps * L_cross * Lz)
    # Outlet real index depends on streamwise axis + reverse
    out_idx = 0 if is_reverse else -1
    T_A_out = float(np.mean(np.take(Ta, out_idx, axis=stream_real_axis)))
    Q = abs(m_dot * cp_A * (T_inA - T_A_out))

    dP = float(SIMPLESolver3D.extract_dP_weighted(sA))

    uc_real, vc_real, wc_real = _assemble_real_velocity()
    vmag = np.sqrt(uc_real ** 2 + vc_real ** 2 + wc_real ** 2)

    # P field → real coords (transpose if x-streamwise, else identity copy)
    P_real = sA.P.transpose(1, 0, 2).copy() if is_x_stream else sA.P.copy()
    P_kPa = P_real / 1000.0
    L_mm = np.full((Nx, Ny, Nz), Lcell, dtype=np.float64)

    return dict(
        Ta=Ta, Tb=Tb, Ts=Ts,
        vmag=vmag, P_kPa=P_kPa, L_mm=L_mm,
        P_Pa=P_real,
        uc_real=uc_real, vc_real=vc_real,
        dx=dx, dy=dy, dz=dz,
        Lx=L, Ly=H, Lz=Lz,
        Q=Q, dP=dP, u_A=u_A, T_in=T_inA,
        dir_A=fA['dir'],
    )
