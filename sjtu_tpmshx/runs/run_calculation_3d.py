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
import os
import numpy as np

from solvers.simple_solver_3d import SIMPLESolver3D
from solvers.solve_full_3d import solve_full_domain_3d
from solvers.tpms_calc import (
    geometry as tpms_geometry, air_density, air_viscosity,
    air_conductivity, air_cp, P_atm,
    water_density, water_viscosity, water_conductivity, water_cp,
)
from df_fit.predict import predict_K_cF


# 2026-04-26: env var TPMSHX_SIMPLE_TOL overrides default SIMPLE pp tol for
# diagnostic sweeps (path 0 / 0' v3 plan). Read each call to allow sweeps.
def _simple_tol_default():
    return float(os.environ.get('TPMSHX_SIMPLE_TOL', '1e-5'))


def _run_two_simple_parallel(sA, sB, *, max_iter=2000, tol=None):
    """Run SIMPLE A and SIMPLE B concurrently on two OS threads.

    `SIMPLESolver3D.solve` spends its wall-clock inside Numba njit kernels
    and PyAMG/BiCGStab (both release the GIL), so pure Python threading
    delivers real parallelism. Fluid A and Fluid B use independent instances
    (own matrix, ml_cache, arrays) — no shared mutable state.

    Raises the first worker's exception (if any) after both threads finish.
    """
    import threading
    if tol is None:
        tol = _simple_tol_default()

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
    """Phase 1: parse inputs → build fields → solve → store."""
    cfg = _parse_inputs(window)
    def _prog(pct):
        window._compute_progress = pct
    cfg['_progress_cb'] = _prog
    cfg['_cancel_check'] = lambda: bool(getattr(window, '_compute_cancel', False))
    # Phase A/B/C acceleration flags — env-var entrypoint (UI checkbox TBD).
    # Phase A defaults ON (zero-loss); Phase B/C opt-in until full-sweep
    # validated. Set TPMSHX_PHASE_A=0 to disable A; TPMSHX_PHASE_B=1 / _C=1
    # to enable B/C.
    import os as _os
    cfg.setdefault('use_adaptive_amg_tol',
                    _os.getenv('TPMSHX_PHASE_A', '1') != '0')
    cfg.setdefault('use_anderson',
                    _os.getenv('TPMSHX_PHASE_B', '0') == '1')
    cfg.setdefault('use_coarse_bootstrap',
                    _os.getenv('TPMSHX_PHASE_C', '0') == '1')
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


def _fmt_metric(value, fmt, dash='-'):
    try:
        if value is None or not np.isfinite(float(value)):
            return dash
        return fmt.format(float(value))
    except Exception:
        return dash


def _store_3d_result_labels(window, result):
    """Mirror 3D scalar metrics into the legacy left-panel labels.

    The canvas-top summary strip reads these same labels, so keeping this
    centralised prevents the 3D path from showing partial KPI state.
    """
    values = {
        '_r_Q': _fmt_metric(result.get('Q'), '{:.2f}'),
        '_r_dP_A': _fmt_metric(result.get('dP'), '{:.0f}'),
        '_r_dP_B': _fmt_metric(result.get('dP_B'), '{:.0f}'),
        '_r_ToutA': _fmt_metric(result.get('T_A_out'), '{:.1f}'),
        '_r_ToutB': _fmt_metric(result.get('T_B_out'), '{:.1f}'),
    }
    for attr, text in values.items():
        label = getattr(window, attr, None)
        if label is not None:
            try:
                label.setText(text)
            except Exception:
                pass


def finalize_plots_3d(window):
    """Push 3D fields into the embedded panel + mid-z slices to 2D canvases."""
    res = getattr(window, '_result_3d', None)
    if res is None:
        return
    _store_3d_result_labels(window, res)
    # Skeleton placeholder retires once real 3D data lands.
    sk = getattr(window, '_3d_skeleton', None)
    if sk is not None:
        try: sk.stop()
        except Exception: pass

    # ── 1. PyVistaQt 3D panel ──
    panel = getattr(window, 'canvas_3d', None)
    if panel is None and hasattr(window, '_lazy_init_3d_panel'):
        try:
            window._lazy_init_3d_panel()
            panel = getattr(window, 'canvas_3d', None)
        except Exception:
            panel = None
    if panel is not None:
        try:
            P_B_kPa = None
            if res.get('P_Pa_B') is not None:
                P_B_kPa = np.ascontiguousarray(res['P_Pa_B'] / 1000.0)
            # Map fluid-A dir index (0=+x,1=-x,2=+y,3=-y,4=+z,5=-z) to
            # '±axis' string so the panel can orient inlet/outlet glyphs.
            _dirs = ['+x', '-x', '+y', '-y', '+z', '-z']
            _dir_idx = res.get('dir_A', 0)
            _dir_str = _dirs[int(_dir_idx) % 6]
            _dir_b = res.get('dir_B')
            _dir_str_B = None if _dir_b is None else _dirs[int(_dir_b) % 6]
            # When sB was None, Tb is a uniform prescribed array (T_inB
            # everywhere) and would render as a flat single-color cube,
            # misleading the user into thinking they have a B field.
            # Filter it out at the panel boundary so the combo skips Tb.
            _has_B = _dir_b is not None
            _Tb_for_panel = res.get('Tb') if _has_B else None
            _vmag_B_for_panel = res.get('vmag_B') if _has_B else None
            _P_B_for_panel = P_B_kPa if _has_B else None
            panel.set_fields(
                Ta=res['Ta'],
                Tb=_Tb_for_panel,
                Ts=res.get('Ts'),
                vmag=res['vmag'],
                vmag_B=_vmag_B_for_panel,
                P_kPa=res['P_kPa'],
                P_B_kPa=_P_B_for_panel,
                L_mm=res['L_mm'],
                dx=res['dx'], dy=res['dy'], dz=res['dz'],
                real_dims=(res['Lx'], res['Ly'], res['Lz']),
                flow_dir=_dir_str,
                flow_dir_B=_dir_str_B if _has_B else None,
            )
            # Surrogate-extrapolation watermark — lower-left viewport.
            if res.get('extrapolated'):
                _reasons = res.get('extrap_reasons', [])
                _txt = "⚠ ConstDF-v1 extrapolated\n" + "\n".join(_reasons)
                try:
                    panel.set_watermark(_txt)
                except Exception:
                    pass
            else:
                try:
                    panel.set_watermark(None)
                except Exception:
                    pass
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"[3D vis] set_fields failed: {e}")

    # ── 2. 2D canvases: auto mid-z slice (keeps Temperature/Pressure/Velocity
    #       tabs relevant under 3D mode) ──
    import os as _os_3d_fin
    window._rendered_3d_slices = False
    if _os_3d_fin.environ.get('TPMSHX_EAGER_3D_SLICES', '0') == '1':
        _render_2d_slices_from_3d(window, res)
        window._rendered_3d_slices = True


def _render_2d_slices_from_3d(window, res):
    """Mid-z slice of 3D fields → Temperature/Pressure/Velocity canvases.

    Custom renderers (not `plot_temperature`/`plot_pressure`) because refined
    3D grid is non-uniform; legacy 2D plotters assume `np.linspace` spacing.
    """
    Ta = res['Ta']; Tb = res['Tb']; Ts = res['Ts']
    P_Pa = res['P_Pa']; uc = res['uc_real']; vc = res['vc_real']
    wc = res.get('wc_real')
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
    wc_B = res.get('wc_real_B')
    dP_B = res.get('dP_B', 0.0)
    has_B = P_Pa_B is not None
    if wc is None:
        wc = np.zeros_like(uc)
    if has_B and wc_B is None:
        wc_B = np.zeros_like(uc_B)

    plot_jobs = [
        ('canvas_temp', _plot_3d_temperature,
            (Ta[:, :, k_mid], Tb[:, :, k_mid], Ts[:, :, k_mid], xc, yc, z_info)),
        ('canvas_pres', _plot_3d_pressure,
            (P_Pa[:, :, k_mid],
             P_Pa_B[:, :, k_mid] if has_B else None,
             xc, yc, res['dP'], dP_B, z_info)),
        ('canvas_vel', _plot_3d_velocity_slice,
            (uc[:, :, k_mid], vc[:, :, k_mid], wc[:, :, k_mid],
             uc_B[:, :, k_mid] if has_B else None,
             vc_B[:, :, k_mid] if has_B else None,
             wc_B[:, :, k_mid] if has_B else None,
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

    # Surrogate-extrapolation watermark on the 2D mid-z slice canvases so the
    # Temperature / Pressure / Velocity tabs under 3D mode carry the same
    # `⚠ ConstDF-v1 extrapolated` notice the 3D viewport + 2D-native path
    # already show. Without this, a 3D run with t=0.6 mm would hide the
    # extrapolation flag on every canvas except the PyVistaQt viewport.
    if res.get('extrapolated'):
        _reasons = list(res.get('extrap_reasons', []) or [])
        from ui.theme import get_theme as _gt
        _tw = _gt().get('warn', '#B45309')
        _wm_text = "⚠ ConstDF-v1 extrapolated: " + " | ".join(_reasons)
        for attr in ('canvas_temp', 'canvas_pres', 'canvas_vel'):
            _cv = getattr(window, attr, None)
            if _cv is None:
                continue
            try:
                _cv.fig.text(0.5, 0.005, _wm_text,
                             color=_tw, fontsize=8, ha='center', va='bottom',
                             fontweight='bold', alpha=0.85)
                _cv.draw_idle()
            except Exception:
                pass


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
    """3-panel temperature (Ta / Tb / Ts) on mid-z slice.

    All three panels share a single (vmin, vmax) so the slice colorscale
    matches the 3D viewport's `_share(('Ta','Tb','Ts'))` clim. Without the
    shared range, Ts (which can sit between bulk T_inA/T_inB and act
    nearly uniform) would autoscale to its own narrow range and look
    blown-up next to the fluid panels.
    """
    _T = _get_theme()
    axes = _begin_canvas_plot(canvas, 1, 3)
    Y, X = np.meshgrid(yc, xc)
    vmin_unified = float(min(Ta_slice.min(), Tb_slice.min(), Ts_slice.min()))
    vmax_unified = float(max(Ta_slice.max(), Tb_slice.max(), Ts_slice.max()))
    if vmax_unified - vmin_unified < 1e-12:
        vmax_unified = vmin_unified + 1.0
    datasets = [
        (Ta_slice, r'$T_{f,A}$ [K] — Fluid A'),
        (Tb_slice, r'$T_{f,B}$ [K] — Fluid B (frozen)'),
        (Ts_slice, r'$T_s$ [K] — Solid'),
    ]
    for ax, (field, title) in zip(axes, datasets):
        cf = ax.contourf(X, Y, field, levels=100, cmap='turbo',
                          vmin=vmin_unified, vmax=vmax_unified)
        cb = canvas.fig.colorbar(cf, ax=ax, shrink=0.85, aspect=18, format='%.1f')
        cb.ax.tick_params(labelsize=8, colors=_T['ax_text'])
        _style_axis(ax, title=title, title_size=11, label_size=9, tick_size=8)
        # Equal aspect preserves geometric proportion (e.g. Shanghai 182×42 mm
        # is not square; default 'auto' stretches it to fill the axis box and
        # makes the contour shapes disagree with the 3D volume rendering).
        try:
            ax.set_aspect('equal')
        except Exception:
            pass
    canvas.fig.suptitle(f'Temperature — 3D {z_info}', fontsize=12,
                         fontweight='bold', color=_T['ax_text'], y=0.995)
    canvas.fig.subplots_adjust(left=0.05, right=0.97, top=0.88, bottom=0.10,
                                wspace=0.32)
    canvas.draw()


def _plot_3d_pressure(canvas, P_slice_A, P_slice_B, xc, yc, dP_A, dP_B, z_info):
    """Pressure panels. If P_slice_B is None → single panel (A only, B frozen).

    A/B panels share one (vmin, vmax) so the same color reads as the same
    pressure across panels. Independent autoscale (matplotlib default) makes
    a 1 kPa B field look as red as a 100 kPa A field, which is misleading
    when both panels share the 'turbo' cmap.
    """
    _T = _get_theme()
    if P_slice_B is None:
        axes = [_begin_canvas_plot(canvas)]
        P_data = [(P_slice_A, 'A', dP_A)]
    else:
        axes = _begin_canvas_plot(canvas, 1, 2)
        P_data = [(P_slice_A, 'A', dP_A), (P_slice_B, 'B', dP_B)]
    Y, X = np.meshgrid(yc, xc)
    # Shared clim across all panels (kPa).
    p_min_kpa = float(P_slice_A.min()) / 1000.0
    p_max_kpa = float(P_slice_A.max()) / 1000.0
    if P_slice_B is not None:
        p_min_kpa = min(p_min_kpa, float(P_slice_B.min()) / 1000.0)
        p_max_kpa = max(p_max_kpa, float(P_slice_B.max()) / 1000.0)
    if p_max_kpa - p_min_kpa < 1e-12:
        p_max_kpa = p_min_kpa + 1.0
    for ax, (p, tag, dp) in zip(axes, P_data):
        cf = ax.contourf(X, Y, p / 1000.0, levels=512, cmap='turbo',
                          vmin=p_min_kpa, vmax=p_max_kpa)
        cb = canvas.fig.colorbar(cf, ax=ax, shrink=0.9, aspect=25, format='%.1f')
        cb.ax.tick_params(labelsize=9, colors=_T['ax_text'])
        _style_axis(ax, title=(f'$P_{tag}$ (kPa) — Fluid {tag} — 3D {z_info}   '
                                rf'$|\Delta P|$ = {dp:.0f} Pa'))
        try:
            ax.set_aspect('equal')
        except Exception:
            pass
    canvas.fig.subplots_adjust(left=0.06, right=0.96, top=0.90, bottom=0.10,
                                wspace=0.25)
    canvas.draw()


def _plot_3d_velocity_slice(canvas, uA, vA, wA, uB, vB, wB, xc, yc, z_info):
    """Velocity magnitude panels. If uB is None → single panel (A only).

    A/B panels share one vmax (vmin pinned at 0) so cross-flow B running
    at 0.5 m/s does not look as bright as A running at 5 m/s under the
    same 'turbo' cmap. Mirrors the panel's `_share(('vmag','vmag_B'))`
    clim convention.
    """
    _T = _get_theme()
    if uB is None:
        axes = [_begin_canvas_plot(canvas)]
        V_data = [(uA, vA, wA, 'A')]
    else:
        axes = _begin_canvas_plot(canvas, 1, 2)
        V_data = [(uA, vA, wA, 'A'), (uB, vB, wB, 'B')]
    Y, X = np.meshgrid(yc, xc)
    # Pre-compute |v| so we can pick a shared vmax across panels.
    vmags = []
    for u, v, w, _tag in V_data:
        ww = w if w is not None else np.zeros_like(u)
        vmags.append(np.sqrt(u ** 2 + v ** 2 + ww ** 2))
    vmax_v = max(float(vm.max()) for vm in vmags)
    if vmax_v <= 0.0:
        vmax_v = 1.0
    for ax, vmag, (u, v, w, tag) in zip(axes, vmags, V_data):
        cf = ax.contourf(X, Y, vmag, levels=512, cmap='turbo',
                          vmin=0.0, vmax=vmax_v)
        cb = canvas.fig.colorbar(cf, ax=ax, shrink=0.9, aspect=25, format='%.2f')
        cb.ax.tick_params(labelsize=9, colors=_T['ax_text'])
        _style_axis(ax, title=f'|v| (m/s) — Fluid {tag} — 3D {z_info}')
        try:
            ax.set_aspect('equal')
        except Exception:
            pass
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
    # Defensive unit check: GUI labels L/H/Lz as METERS but L_cell / t are in
    # MM. A user typing the TPMS-cell value (mm) into the domain field (m)
    # would silently spawn a 7 m × 0.6 m domain. Cap at 10 m as a sanity
    # firewall — physical TPMS HX rigs are sub-meter. Adjust if you ever
    # actually want to model a >10 m duct.
    _DOMAIN_MAX_M = 10.0
    for name, val in [('L', L), ('H', H), ('Lz', Lz)]:
        if val > _DOMAIN_MAX_M:
            raise ValueError(
                f"Domain dimension {name!r}={val} m exceeds {_DOMAIN_MAX_M} m. "
                f"Likely unit slip — GUI expects meters here, while L_cell "
                f"and t use millimeters. Re-check input.")
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

    # Optional solid warm-start seed — empty field falls back to the legacy
    # 0.5*(T_inA+T_inB) seed inside solve_full_domain_3d.
    _le_ts = getattr(window, 'le_TsInit', None)
    T_s_init = None
    if _le_ts is not None and _le_ts.text().strip():
        if hasattr(window, '_temp_to_K'):
            T_s_init = window._temp_to_K(_le_ts)
        else:
            T_s_init = float(_le_ts.text())
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

    # Surrogate training-domain guard for the UI 3D Compute path (#10).
    # Opt-in extrapolation via `chk_allow_extrap` or env TPMSHX_ALLOW_EXTRAP.
    window._extrap_reasons = []
    _allow_extrap = bool(getattr(window, 'chk_allow_extrap', None)
                         and window.chk_allow_extrap.isChecked())
    try:
        from optimization.optimizer import check_surrogate_domain_at_point
        window._extrap_reasons += check_surrogate_domain_at_point(
            tpms_type, Lcell, t_wall, k_s,
            u_A, T_inA, P_inA, side='A',
            allow_extrap=_allow_extrap) or []
        window._extrap_reasons += check_surrogate_domain_at_point(
            tpms_type, Lcell, t_wall, k_s,
            u_B, T_inB, P_inB, side='B',
            allow_extrap=_allow_extrap) or []
    except (ImportError, ValueError) as _e:
        if isinstance(_e, ValueError):
            raise

    from solvers.tpms_calc import parse_fluid_type, validate_fluid_type

    fluid_type_A = 'air'
    if hasattr(window, 'combo_fluidA'):
        fluid_type_A = parse_fluid_type(window.combo_fluidA)

    fluid_type_B = 'air'
    if hasattr(window, 'combo_fluidB'):
        fluid_type_B = parse_fluid_type(window.combo_fluidB)

    validate_fluid_type(fluid_type_A, 'A')
    validate_fluid_type(fluid_type_B, 'B')

    # 3D wall refinement toggle. Default OFF (matches UI checkbox default,
    # see ui_builders.py:628). Refine adds 8 BL cells per wall × 6 walls
    # → ~6× cell count, 3-5 min runs; only enable if BL accuracy needed.
    wall_refine = False
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
        T_s_init=T_s_init,
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
    # Reverse dir swaps which face the solver calls "inlet"
    if is_reverse:
        in_c1, out_c1 = out_c1, in_c1
        in_c2, out_c2 = out_c2, in_c2
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

    uf_real = np.ascontiguousarray(out[0], dtype=np.float64)
    vf_real = np.ascontiguousarray(out[1], dtype=np.float64)
    wf_real = np.ascontiguousarray(out[2], dtype=np.float64)

    # Shape sanity check
    assert uf_real.shape == (Nx+1, Ny, Nz), f"uf {uf_real.shape} != ({Nx+1},{Ny},{Nz})"
    assert vf_real.shape == (Nx, Ny+1, Nz), f"vf {vf_real.shape} != ({Nx},{Ny+1},{Nz})"
    assert wf_real.shape == (Nx, Ny, Nz+1), f"wf {wf_real.shape} != ({Nx},{Ny},{Nz+1})"
    return uf_real, vf_real, wf_real


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

    # Grid: either uniform user spacing or 6-wall boundary-layer refinement.
    # Refined grid expands user N by ~+2×n_refine cells per axis (n_refine=8
    # each wall; first cell 0.02 mm, growth 1.8). Typical: user 20×10×5 →
    # actual 36×26×21. Improves BL capture in every direction (including z).
    #
    # ⚠ Known limitation: SIMPLESolver3D.__init__ currently rebuilds its
    # internal `self.dx/dy/dz` as Lx/Nx_refined uniform arrays — i.e. the
    # SIMPLE momentum/pressure solve is run on a UNIFORM grid even when
    # wall_refine=True. Only the LTNE energy stage sees the refined dx/dy/dz
    # (`solve_full_domain_3d` accepts dx_arr/dy_arr/dz_arr). This means
    # wall_refine improves BL accuracy on the THERMAL side only; SIMPLE
    # velocity/pressure remain on the user grid. The mismatch is small for
    # typical Shanghai-class runs (BL contributes ~1pp dP) but the user
    # should be aware. Full wiring is deferred — adding dx_arr/dy_arr/dz_arr
    # to SIMPLESolver3D.__init__ requires re-validating the sweep_u/v/w
    # kernels under non-uniform spacing and re-running the Shanghai
    # validation suite.
    if wall_refine:
        import warnings as _w
        _w.warn(
            "wall_refine_3d=True: refined dx/dy/dz reach the LTNE solver "
            "but SIMPLE3D currently runs on the uniform user grid (solver "
            "ignores non-uniform spacing). Velocity/pressure fields are "
            "computed at uniform Nx_refined×Ny_refined×Nz_refined cell "
            "spacing. See run_calculation_3d.py:_run_3d_stack comment.",
            stacklevel=2,
        )
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
    t_field_3d = None      # per-cell wall thickness
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
        K_pred, cF_pred = predict_K_cF(tpms_type, Lcell, t_wall, 0.5 * eps)
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
    # Phase A/B/C acceleration flags. Phase A on by default (zero-loss inner-
    # tol scheduling); Phase B/C opt-in until full-sweep validated.
    sA.use_adaptive_amg_tol = bool(cfg.get('use_adaptive_amg_tol', True))
    sA.use_anderson = bool(cfg.get('use_anderson', False))
    sA.anderson_m = int(cfg.get('anderson_m', 5))
    sA.anderson_K = int(cfg.get('anderson_K', 3))
    sA.use_coarse_bootstrap = bool(cfg.get('use_coarse_bootstrap', False))
    sA.coarse_bootstrap_max_iter = int(cfg.get('coarse_bootstrap_max_iter', 200))
    sA.coarse_bootstrap_tol = float(cfg.get('coarse_bootstrap_tol', 1e-3))
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
    sA.outlet_mask_ij = sA.outlet_frac > 0.5
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
        # Zoned ε for sB: same eps_field but transposed via B's perm (built
        # below after sB construction).
        sB = SIMPLESolver3D(
            **axis_map_B['solver_init'],
            rho=rho_B, mu=mu_B, T_in=T_inB, v_inlet=v_inlet_B,
            eps=eps, K_arr=K_B_arr, cF_arr=cF_B_arr,
            P_ref_abs=P_ref_B, fluid_type=solver_fluid_type_B,
        )
        # Mirror Phase A/B/C flags onto sB (sweep config consistent with sA).
        sB.use_adaptive_amg_tol = bool(cfg.get('use_adaptive_amg_tol', True))
        sB.use_anderson = bool(cfg.get('use_anderson', False))
        sB.anderson_m = int(cfg.get('anderson_m', 5))
        sB.anderson_K = int(cfg.get('anderson_K', 3))
        sB.use_coarse_bootstrap = bool(cfg.get('use_coarse_bootstrap', False))
        sB.coarse_bootstrap_max_iter = int(cfg.get('coarse_bootstrap_max_iter', 200))
        sB.coarse_bootstrap_tol = float(cfg.get('coarse_bootstrap_tol', 1e-3))
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
        sB.outlet_mask_ij = sB.outlet_frac > 0.5
        # sB.solve deferred — dispatched with sA below in parallel threads.
        sB_info = dict(
            axis_map=axis_map_B,
            u_B=u_B, rho_B=rho_B, mu_B=mu_B,
            G_B=G_B, T_inB=T_inB,
        )
        # ── Parallel SIMPLE A + B solve (threads, njit releases GIL) ──
        _run_two_simple_parallel(sA, sB)
        # LTNE fluid B velocity: full vector remapped to real coordinates.
        ucB, vcB, wcB = _solver_velocity_to_real(
            sB, axis_map_B, (Nx, Ny, Nz))
        Tb_presc = None  # let LTNE solve Tb from convection
    else:
        # No B: run A alone (serial)
        sA.solve(max_iter=2000, tol=_simple_tol_default(), verbose=False)
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
    _NU_LAM_FLOOR = 4.36   # Hagen-Poiseuille single-tube limit
    u_B_val = cfg.get('u_B', u_A)

    def _fluid_transport_props(fluid_type, T_side, P_side):
        if fluid_type == 'water':
            rho = float(water_density(T_side))
            mu = float(water_viscosity(T_side))
            k_f = float(water_conductivity(T_side))
            Pr_f = float(water_cp(T_side)) * mu / max(k_f, 1e-30)
            return rho, mu, k_f, Pr_f
        rho = float(air_density(T_side, P_side))
        mu = float(air_viscosity(T_side))
        k_f = float(air_conductivity(T_side))
        return rho, mu, k_f, None

    def _nu_for_fluid(fluid_type, Re_val, eps_f_val, L_mm_val, D_h_mm_val, Pr_val=None):
        Re_eff = max(float(Re_val), 1.0)
        if fluid_type == 'water':
            Nu_val = _nu_water_from_Re(
                tpms_type, Re_eff, float(eps_f_val), float(L_mm_val),
                float(D_h_mm_val), float(Pr_val if Pr_val is not None else 7.0),
            )
        else:
            Nu_val = _nu_from_Re(
                tpms_type, Re_eff, float(eps_f_val), float(L_mm_val),
                float(D_h_mm_val),
            )
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
            Nu_loc = np.empty_like(Re_loc)
            for i in range(Nx):
                for j in range(Ny):
                    for k in range(Nz):
                        # single-stream convention: pass ε_f = ε/2 (post-refit 2026-04-26)
                        nu_corr = _nu_for_fluid(
                            fluid_type, float(Re_loc[i,j,k]),
                            g['epsilon'] / 2.0, Lcell, D_h_mm, Pr_f,
                        )
                        Nu_loc[i,j,k] = nu_corr
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
    if sB is not None:
        h_vB_field = _build_hv_field_3d(
            L_mm_field, t_field_3d, u_B_val, T_inB, P_inB, fluid_type_B)
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
    # per-fluid inlet T (the 2026-04-24 FV fix in solve_full_3d.py:1442-44
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
        """Pick streamwise cell-center velocity component."""
        if dir_code in (0, 1): return uc
        if dir_code in (2, 3): return vc
        return wc

    _progress_cb = cfg.get('_progress_cb')
    _cancel_check = cfg.get('_cancel_check')
    for outer in range(_max_outer):
        # Cooperative cancel: only safe boundary is between outer iterations
        # — a JIT'd SIMPLE inner sweep cannot be interrupted. The UI sets the
        # flag via the Cancel button or the wall-clock timeout.
        if _cancel_check is not None and _cancel_check():
            raise InterruptedError("compute cancelled by user")
        if _progress_cb is not None:
            _progress_cb(10 + int(80 * outer / _MAX_OUTER))
        ucA, vcA, wcA = _assemble_real_velocity()

        # #B fix: rebuild h_v per cell using LOCAL Re (cell-center stream u).
        # Wall cells with |u_local|→0 → Nu_lam floor (4.36) → h_local much
        # smaller than bulk h. Removes wall-BL stagnation over-count.
        u_stream_A = _stream_component(ucA, vcA, wcA, fA['dir'])
        h_vA_field = _build_hv_local_3d(
            L_mm_field, t_field_3d, u_stream_A, T_inA, P_inA, fluid_type_A)
        # Pre-compute LTNE inlet masks (needed by χ_B block and LTNE solve)
        _ltne_mask_A = (out_mask_2d if fA['dir'] in (1, 3, 5) else in_mask_2d)
        _ltne_mask_B = None
        if fB is not None:
            _ltne_mask_B = (out_mask_B if fB['dir'] in (1, 3, 5) else in_mask_B)

        if sB is not None:
            u_stream_B = _stream_component(ucB, vcB, wcB, fB['dir'])
            h_vB_field = _build_hv_local_3d(
                L_mm_field, t_field_3d, u_stream_B, T_inB, P_inB, fluid_type_B)
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

        # 2026-04-26: face_centered Moukalled kernel opt-in via env var.
        # When set, uses _gs_full_chunk_3d_moukalled (Patankar BC source +
        # NET_OUT) instead of stag kernel. Goal: AB imbal < 5%.
        _face_centered = os.environ.get('TPMSHX_FACE_CENTERED', '0') == '1'

        # H6 ghost-pin: pass chi_B_field + threshold to LTNE kernel. At cells
        # where chi_B_field < chi_B_kernel_threshold, kernel skips Tb update
        # (leaves Tb at init = T_inB). Prevents stagnant cells from relaxing
        # to local Ts via h_v and leaking that hot value into mass flow via
        # 1st-order upwind. Default threshold 0.0 = no kernel-level masking.
        _chi_B_kernel_thr = float(cfg.get('chi_B_kernel_threshold', 0.0))

        # MMS source fields (Air-Air V&V Phase A.1). Default None → no-op.
        # Solver accepts (Nx, Ny, Nz) arrays; volume-integrated source per
        # cell injected into FVM equation RHS. Used by validation/mms_3d_*.py.
        _mms_S_A = cfg.get('mms_S_A_field', None)
        _mms_S_B = cfg.get('mms_S_B_field', None)
        _mms_S_s = cfg.get('mms_S_s_field', None)
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
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts, alpha_T=0.7,
            ufA=ufA, vfA=vfA, wfA=wfA,
            ufB=ufB, vfB=vfB, wfB=wfB,
            face_centered=_face_centered,
            chi_B_field=chi_B,
            chi_B_kernel_threshold=_chi_B_kernel_thr,
            mms_S_A_field=_mms_S_A,
            mms_S_B_field=_mms_S_B,
            mms_S_s_field=_mms_S_s,
            return_info=True)
        Ta, Tb, Ts, _ltne_info_d = _ltne_result
        _ltne_info.append(dict(outer=outer, iters=_ltne_info_d.get('iterations',0),
                               converged=_ltne_info_d.get('converged',False),
                               residual=_ltne_info_d.get('residual',0.0)))

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
        sA.solve(max_iter=600, tol=_simple_tol_default(), verbose=False)

        # Refresh fluid-property fields using the *local* T field, keeping
        # the spatial structure built by the zoned-geometry pass up-front
        # (#1). The previous implementation used `eps_f` (undefined in
        # this scope) and a scalar mean T, which both crashed for zoned
        # runs and flattened any non-uniform K_ff / h_v / rho_cp back to
        # a uniform field.
        T_avgA = float(Ta.mean())
        K_ffA[:] = eps_f_arr * air_conductivity(Ta)
        rho_cp_fA[:] = air_density(Ta, P_inA) * air_cp(Ta)
        # h_v rebuilt at top of next outer iter using LOCAL Re (#B fix).

        if Tb is not None:
            T_avgB = float(Tb.mean())
            if is_water_B:
                K_ffB[:] = eps_f_arr * water_conductivity(Tb)
                rho_cp_fB[:] = water_density(Tb) * water_cp(Tb)
            else:
                K_ffB[:] = eps_f_arr * air_conductivity(Tb)
                rho_cp_fB[:] = air_density(Tb, P_inB) * air_cp(Tb)
            # h_vB rebuilt at top of next outer iter using LOCAL Re (#B fix).

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
            eps_eff_B = sB.eps_field if hasattr(sB, 'eps_field') else sB.eps
            sB._mu_eff_field = np.ascontiguousarray(
                sB.mu_field / eps_eff_B, dtype=np.float64)

            if not is_water_B:
                Tb_avg = float(Tb_sB.mean())
                mu_avg_B = float(air_viscosity(Tb_avg))
                C_avg_B = (mu_avg_B * G_B / max(K_pred, 1e-16)
                           + cF_pred * G_B * G_B)
                P_out_sq_B_new = (P_inB ** 2
                                  - 2.0 * R_AIR * Tb_avg * C_avg_B * L_stream_B)
                sB.P_ref_abs = float(np.sqrt(max(P_out_sq_B_new, 1.0e4)))

            sB.update_T_field(Tb_sB)
            sB.solve(max_iter=600, tol=_simple_tol_default(), verbose=False)

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
    # Mask convention: `_build_partial_masks` swaps in↔out for reverse
    # dirs (1/3/5) so sX.inlet_frac sits at SIMPLE's j=0 face.
    # In REAL coords: reverse dir's real inlet is at the other face, so
    # when we want a mask for the real outlet we must un-swap.
    def _real_outlet_mask(solver, dir_code):
        m_in = getattr(solver, 'inlet_frac', None)
        m_out = getattr(solver, 'outlet_frac', None)
        # real outlet mask
        return (m_in if dir_code in (1, 3, 5) else m_out)

    def _pipe_masked_mean(T_face, mask):
        if mask is None:
            return float(np.mean(T_face))
        w = np.asarray(mask, dtype=np.float64)
        tot = float(np.sum(w))
        if tot < 1e-30:
            return float(np.mean(T_face))
        return float(np.sum(T_face * w) / tot)

    def _face_flux_weights(solver, dir_code, face='real_outlet',
                           eps_mode='ltne', chi_face=None):
        """Unified face-flux weight array for T_out, m_dot, Q_enth.

        Parameters
        ----------
        solver : SIMPLESolver3D
        dir_code : int — 0=+x,1=-x,2=+y,3=-y,4=+z,5=-z
        face : 'real_inlet' or 'real_outlet'
        eps_mode : 'ltne' (× eps_f) or 'physical' (no eps_f)
        chi_face : optional 2D array — χ_B at this face for ghost suppression

        Returns
        -------
        w : 2D ndarray — face flux weights [kg/s] or eps_f·[kg/s].
            sum(w) = effective mass flow through this face.
        """
        is_reverse = dir_code in (1, 3, 5)
        if face == 'real_outlet':
            # real outlet ≡ solver j=0 for reverse, j=-1 for forward
            if is_reverse:
                v_face = solver.v[:, 0, :]
                rho_face = solver.rho_field[:, 0, :]
                mask_face = getattr(solver, 'inlet_frac', None)
                face_idx = 0
            else:
                v_face = solver.v[:, -1, :]
                rho_face = solver.rho_field[:, -1, :]
                mask_face = getattr(solver, 'outlet_frac', None)
                face_idx = -1
        else:  # real_inlet
            if is_reverse:
                v_face = solver.v[:, -1, :]
                rho_face = solver.rho_field[:, -1, :]
                mask_face = getattr(solver, 'outlet_frac', None)
                face_idx = -1
            else:
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
                w = w * eps_f_per_side  # closure: ε/2 scalar from outer scope
        if mask_face is not None:
            w = w * np.asarray(mask_face, dtype=np.float64)
        if chi_face is not None:
            w = w * np.asarray(chi_face, dtype=np.float64)
        return w

    def _mass_weighted_T_out(T_face, solver, dir_code, eps_f_scalar,
                              chi_face=None):
        """Mass-flux-weighted T average at the REAL outlet face.
        Delegates to _face_flux_weights for consistent weighting.
        """
        try:
            w = _face_flux_weights(solver, dir_code, face='real_outlet',
                                   eps_mode='ltne', chi_face=chi_face)
            tot = float(np.sum(w))
            if tot < 1e-30:
                return float(np.mean(T_face))
            return float(np.sum(T_face * w) / tot)
        except Exception:
            return float(np.mean(T_face))

    def _real_outlet_slice(T_field, dir_code):
        if dir_code == 0:   return T_field[-1, :, :]
        if dir_code == 1:   return T_field[0, :, :]
        if dir_code == 2:   return T_field[:, -1, :]
        if dir_code == 3:   return T_field[:, 0, :]
        if dir_code == 4:   return T_field[:, :, -1]
        return T_field[:, :, 0]

    def _simple_mass_flow(solver, dir_code):
        """LTNE-effective m_dot at REAL inlet face via _face_flux_weights."""
        try:
            w = _face_flux_weights(solver, dir_code, face='real_inlet',
                                   eps_mode='ltne')
            return float(np.sum(w))
        except Exception:
            return 0.0

    # LTNE uses ε_A = ε_B = ε/2 per side (symmetric 2-fluid split). Metric
    # must mirror that so m_dot ≡ ∫ ε_A·ρ·u·dA matches the solver's
    # internal advective mass flow.
    eps_f_per_side = 0.5 * float(eps)   # ε_A

    # Fluid A — unified face-flux weights for T_out and m_dot consistency
    m_dot_A_simple = _simple_mass_flow(sA, fA['dir'])
    T_A_out_face = _real_outlet_slice(Ta, fA['dir'])
    T_A_out = _mass_weighted_T_out(T_A_out_face, sA, fA['dir'], eps_f_per_side)
    # T_A_out no-chi (diagnostic only)
    T_A_out_no_chi = _mass_weighted_T_out(T_A_out_face, sA, fA['dir'], eps_f_per_side)
    Q_enthalpy_A = abs(m_dot_A_simple * cp_A * (T_inA - T_A_out))

    # Fluid B
    Q_enthalpy_B = 0.0
    chi_B_out_face = None
    if sB is not None:
        m_dot_B_simple = _simple_mass_flow(sB, fB['dir'])
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
    Q = 0.5 * (Q_enthalpy_A + Q_enthalpy_B) if Q_enthalpy_B > 0 else Q_enthalpy_A

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

    # Conservation diagnostics — always computed now (previously only in tests).
    # Lets the user spot non-physical regressions (e.g. refined-grid imbalance)
    # without re-running validation scripts.
    try:
        from solvers.solve_full_3d import energy_balance_3d, mass_balance_3d
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
    except Exception:
        Q_sA = Q_sB = Q_net = energy_rel = mass_rel_A = mass_rel_B = float('nan')

    # 2026-04-26 Path 0' (v3) — energy flux consistency fix.
    # Empirical finding (diag_bc_layer_test.py NORM-NO_REFINE):
    #   |Q_sA_interior| = 369.62W ≈ Q_enth_B = 369.31W (match within 0.08%)
    #   |Q_sB_interior| = 370.87W ≈ Q_enth_B (match within 0.4%)
    #   |Q_sA|_total = 414W (over by 28% due to BC inlet/outlet layer pinning)
    # Root cause: BC inlet cells with Ta pinned at T_in_A create artificial
    # h_v·(Ts-T_in_A) source contributions because the cell-center value is
    # held constant at the parameter, while solid responds. Excluding the
    # BC layer recovers the physical Q.
    # Diagnostic: also compute mean(|Q_sA_interior|, |Q_sB_interior|).
    # The returned primary Q remains the enthalpy metric above because the
    # validation/optimizer stack is calibrated to boundary heat balance.
    try:
        Nx_g, Ny_g, Nz_g = Ta.shape
        cell_vol = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]
        integ_A = h_vA_field * (Ts - Ta) * cell_vol
        integ_B = h_vB_field * (Ts - Tb) * cell_vol

        def _bc_face_mask(dir_code, NxG, NyG, NzG):
            m = np.zeros((NxG, NyG, NzG), dtype=bool)
            if   dir_code == 0: m[0, :, :] = True
            elif dir_code == 1: m[NxG-1, :, :] = True
            elif dir_code == 2: m[:, 0, :] = True
            elif dir_code == 3: m[:, NyG-1, :] = True
            elif dir_code == 4: m[:, :, 0] = True
            else:               m[:, :, NzG-1] = True
            return m

        def _outlet_mask(dir_code, NxG, NyG, NzG):
            m = np.zeros((NxG, NyG, NzG), dtype=bool)
            if   dir_code == 0: m[NxG-1, :, :] = True
            elif dir_code == 1: m[0, :, :] = True
            elif dir_code == 2: m[:, NyG-1, :] = True
            elif dir_code == 3: m[:, 0, :] = True
            elif dir_code == 4: m[:, :, NzG-1] = True
            else:               m[:, :, 0] = True
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
        # AB imbal on interior-corrected metric
        AB_interior = (abs(abs(Q_sA_interior) - abs(Q_sB_interior))
                       / max(abs(Q_sA_interior), abs(Q_sB_interior), 1e-30))
    except Exception:
        Q_sA_interior = Q_sB_interior = Q_interior_primary = float('nan')
        AB_interior = float('nan')

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
    _dbg = np  # always available (compact mode skips prints only)
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
        # B inlet face slice in real coords
        if fB['dir'] == 0:    chi_B_in_face = chi_B[0, :, :]
        elif fB['dir'] == 1:  chi_B_in_face = chi_B[-1, :, :]
        elif fB['dir'] == 2:  chi_B_in_face = chi_B[:, 0, :]
        elif fB['dir'] == 3:  chi_B_in_face = chi_B[:, -1, :]
        elif fB['dir'] == 4:  chi_B_in_face = chi_B[:, :, 0]
        else:                 chi_B_in_face = chi_B[:, :, -1]
        # Inlet patch mask: _ltne_mask_B is the pre-swap inlet mask in 2D
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

    return dict(
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
        # Plan C v2: B flow-path indicator field (χ_B) for visualization
        chi_B=chi_B,
        # Sweep profile diagnostics
        _ltne_info=_ltne_info,
        _max_outer=_max_outer,
        _ltne_max_iter=_ltne_max_iter,
        _needs_full_validate=(_compact_diag and not all(
            d['converged'] for d in _ltne_info)),
        # ── Audit-only additive exports (read-only, deep-copied) ──
        # 2026-05-04: passthrough of SIMPLE face arrays + masks for the
        # standalone partial-B LTNE conservation audit
        # (validation/audit_partial_b_ltne.py). No physics or closure
        # changes; consumers must not mutate. All entries are guarded
        # with None fallbacks and have no effect on existing callers.
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
