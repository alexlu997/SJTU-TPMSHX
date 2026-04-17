"""
df_projection.py — 投影 2D 几何设计到 SIMPLE 1D K/c_F 数组 + master 加密网格

用于 optimizer 和 runs 共享。SIMPLE 内核的 K/c_F 数组是 1D (Ny_sim,) 行向，
这里把 2D grid_cells 或 sigmoid 连续场投影到 SIMPLE 的流向轴。

核心原则（2026-04-17）：生产 dP 路径严格走 SIMPLE，不允许任何解析公式
（1D D-F、f-Re、compute_dP_continuous 等）绕过 SIMPLE。

对应报告：vault/reports/2026-04-17-shanghai-dP-error-analysis-CN.md §11-§12
"""
import numpy as np
from .tpms_calc import geometry as tpms_geometry
from .simple_solver import build_wall_refined_1d


def build_master_refined_grid(L_dom, H_dom, Nx_user, Ny_user,
                               n_refine=8, first_cell=0.02e-3, growth=1.8):
    """构造"主加密网格"：真实坐标 x/y 两端都加密，四面墙 BL 都解析。

    返回 (dx_arr, dy_arr, Nx_refined, Ny_refined)
      dx_arr (m): 沿实际 x 方向，共 Nx_user + 2*n_refine 个单元，∑=L_dom
      dy_arr (m): 沿实际 y 方向，共 Ny_user + 2*n_refine 个单元，∑=H_dom

    映射到 SIMPLE 坐标：
      Fluid A (+x 流向): SIMPLE internal dx_arr = dy_refined, dy_arr = dx_refined
      Fluid B (-y 流向): SIMPLE internal dx_arr = dx_refined, dy_arr = dy_refined

    za 数组和 solve_full_domain 都直接用 (Nx_refined, Ny_refined) 这个网格。
    """
    dx_refined = build_wall_refined_1d(L_dom, Nx_user, n_refine=n_refine,
                                        first_cell=first_cell, growth=growth)
    dy_refined = build_wall_refined_1d(H_dom, Ny_user, n_refine=n_refine,
                                        first_cell=first_cell, growth=growth)
    return dx_refined, dy_refined, len(dx_refined), len(dy_refined)


def project_cells_to_streamwise_K_cF(grid_cells, tpms_type, k_s, Ny_sim, fluid,
                                       streamwise_dx=None):
    """Project 2D grid_cells onto streamwise axis for SIMPLE's 1D K/c_F arrays.

    For fluid A (+x streamwise): SIMPLE's y-axis maps to real x. For each SIMPLE
    row j, find grid_cells at real x_frac (streamwise cell-centre position) and
    average (L, t) weighted by cross-stream (y) overlap.

    For fluid B (-y streamwise): SIMPLE's y-axis is flipped relative to real y
    (SIMPLE y=0 is fluid B's inlet = real y_frac=1). Real y_frac = 1 - s_frac.

    streamwise_dx : 1D array of shape (Ny_sim,), cell widths along SIMPLE's y
        (streamwise). If None, assume uniform spacing. Pass for non-uniform
        (wall-refined) streamwise grid so s_frac reflects actual cell centre
        positions, not uniform (j+0.5)/Ny_sim.

    Returns (K_arr, cF_arr) both shape (Ny_sim,) float64.

    This loses cross-stream variation but is the best 1D projection available
    under SIMPLE's current K/c_F array shape limitation.
    """
    try:
        from df_fit.predict import predict_K_cF_vec
    except ImportError:
        from thermoNas.df_fit.predict import predict_K_cF_vec

    # Cell-centre s_frac: uniform or from streamwise_dx
    if streamwise_dx is None:
        s_fracs = (np.arange(Ny_sim) + 0.5) / Ny_sim
    else:
        sw = np.asarray(streamwise_dx, dtype=np.float64)
        total = sw.sum()
        cum = np.concatenate([[0.0], np.cumsum(sw)])
        s_fracs = 0.5 * (cum[:-1] + cum[1:]) / total

    L_row = np.empty(Ny_sim, dtype=np.float64)
    t_row = np.empty(Ny_sim, dtype=np.float64)
    eps_f_row = np.empty(Ny_sim, dtype=np.float64)

    for j in range(Ny_sim):
        s_frac = float(s_fracs[j])
        if fluid == 'A':
            real_x = s_frac
            cells_at = [gc for gc in grid_cells if gc['x0'] <= real_x < gc['x1']]
            cs_key_lo = 'y0'; cs_key_hi = 'y1'
        elif fluid == 'B':
            real_y = 1.0 - s_frac   # flip
            cells_at = [gc for gc in grid_cells if gc['y0'] <= real_y < gc['y1']]
            cs_key_lo = 'x0'; cs_key_hi = 'x1'
        else:
            raise ValueError(f"fluid must be 'A' or 'B', got {fluid!r}")

        if not cells_at:
            cells_at = [grid_cells[0]]

        total_w = 0.0; L_sum = 0.0; t_sum = 0.0
        for gc in cells_at:
            w = gc[cs_key_hi] - gc[cs_key_lo]
            L_sum += gc['L'] * w; t_sum += gc['t'] * w
            total_w += w
        L_avg = L_sum / total_w if total_w > 0 else cells_at[0]['L']
        t_avg = t_sum / total_w if total_w > 0 else cells_at[0]['t']

        g = tpms_geometry(tpms_type, L_avg, t_avg, k_s)
        L_row[j] = L_avg; t_row[j] = t_avg; eps_f_row[j] = g['epsilon'] / 2.0

    K_arr, cF_arr = predict_K_cF_vec(tpms_type, L_row, t_row, eps_f_row)
    return K_arr.astype(np.float64), cF_arr.astype(np.float64)


def project_fields_to_streamwise_K_cF(L_field, t_field, tpms_type, k_s,
                                       Nx_field, Ny_field, Ny_sim, fluid,
                                       streamwise_dx=None):
    """Project 2D sigmoid fields onto streamwise axis for SIMPLE's K/c_F arrays.

    L_field, t_field shape: (Nx_field, Ny_field) in real coords.
    For fluid A: average along real y at each real x, then resample to Ny_sim.
    For fluid B: average along real x at each real y, flip, then resample.

    Returns (K_arr, cF_arr) both shape (Ny_sim,) float64.
    """
    try:
        from df_fit.predict import predict_K_cF_vec
    except ImportError:
        from thermoNas.df_fit.predict import predict_K_cF_vec

    if fluid == 'A':
        L_1d = L_field.mean(axis=1)
        t_1d = t_field.mean(axis=1)
        src_n = Nx_field
    elif fluid == 'B':
        L_1d = L_field.mean(axis=0)
        t_1d = t_field.mean(axis=0)
        L_1d = L_1d[::-1].copy()   # flip for -y flow
        t_1d = t_1d[::-1].copy()
        src_n = Ny_field
    else:
        raise ValueError(f"fluid must be 'A' or 'B', got {fluid!r}")

    # Cell-centre s_frac supports non-uniform streamwise grid
    if streamwise_dx is None:
        s_fracs = (np.arange(Ny_sim) + 0.5) / Ny_sim
    else:
        sw = np.asarray(streamwise_dx, dtype=np.float64)
        total = sw.sum()
        cum = np.concatenate([[0.0], np.cumsum(sw)])
        s_fracs = 0.5 * (cum[:-1] + cum[1:]) / total

    L_row = np.empty(Ny_sim, dtype=np.float64)
    t_row = np.empty(Ny_sim, dtype=np.float64)
    eps_f_row = np.empty(Ny_sim, dtype=np.float64)
    for j in range(Ny_sim):
        s_frac = float(s_fracs[j])
        src_idx = int(min(s_frac * src_n, src_n - 1))
        L_avg = float(L_1d[src_idx]); t_avg = float(t_1d[src_idx])
        g = tpms_geometry(tpms_type, L_avg, t_avg, k_s)
        L_row[j] = L_avg; t_row[j] = t_avg; eps_f_row[j] = g['epsilon'] / 2.0

    K_arr, cF_arr = predict_K_cF_vec(tpms_type, L_row, t_row, eps_f_row)
    return K_arr.astype(np.float64), cF_arr.astype(np.float64)


def override_simple_K_cF(sim, tpms_type, k_s, Ny_sim, grid_cells, L_field, t_field, fluid):
    """Project design geometry to streamwise axis, override sim._K_arr/_cF_arr.

    Reads sim.dy_arr (SIMPLE internal streamwise widths) to handle non-uniform
    grids correctly. No-op if neither grid_cells nor fields provided.
    """
    if grid_cells is None and L_field is None:
        return
    streamwise_dx = sim.dy_arr if sim.dy_arr is not None else None
    if grid_cells is not None:
        K_arr, cF_arr = project_cells_to_streamwise_K_cF(
            grid_cells, tpms_type, k_s, Ny_sim, fluid,
            streamwise_dx=streamwise_dx)
    else:
        Nx_field, Ny_field = L_field.shape
        K_arr, cF_arr = project_fields_to_streamwise_K_cF(
            L_field, t_field, tpms_type, k_s,
            Nx_field, Ny_field, Ny_sim, fluid,
            streamwise_dx=streamwise_dx)
    sim._K_arr[:] = K_arr
    sim._cF_arr[:] = cF_arr


def extract_dP_from_simple(s):
    """Extract inlet/outlet-averaged dP from a converged SIMPLE instance.

    Uses the inlet_frac/outlet_frac weighting (same as validate_shanghai.py:273-276)
    to handle partial inlet/outlet openings correctly.
    """
    wA_in = s.inlet_frac; wA_out = s.outlet_frac
    mI = wA_in > 0.01; mO = wA_out > 0.5
    if not (mI.any() and mO.any()):
        return 0.0
    return float(np.average(s.P[mI, 0], weights=wA_in[mI])
               - np.average(s.P[mO, -1], weights=wA_out[mO]))
