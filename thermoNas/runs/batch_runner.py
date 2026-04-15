"""Batch runner for ThermoNAS single-case evaluations.

Provides a uniform interface for running a list of self-contained "case" dicts
through the full ThermoNAS solver stack. Task 9 implements the serial path;
Task 10 adds parallel execution via concurrent.futures.ProcessPoolExecutor.

Case dict schema (all keys required):
    tpms:            str    — e.g. 'Gyroid'
    L_cell_mm:       float  — TPMS cell length (mm)
    t_wall_mm:       float  — TPMS wall thickness (mm)
    K_S:             float  — solid thermal conductivity (W/m/K)
    L_dom:           float  — domain length in flow direction (m)
    H_dom:           float  — domain height (m)
    N_UNITS:         int    — number of parallel unit cells (prototype scale)
    A_flow_per_unit: float  — single-unit effective air cross section (m^2)
    u_air:           float  — air inlet velocity (m/s)
    T_Ain_C:         float  — air inlet temperature (°C)
    T_Bin_C:         float  — water inlet temperature (°C)
    T_Bout_C:        float  — water outlet temperature (°C)
    P_Ain_gauge_Pa:  float  — air inlet gauge pressure (Pa)

Result dict schema:
    Q_sim:      float       — predicted heat transfer (W)
    dP_sim:     float       — predicted air-side pressure drop (Pa); NaN if not computed
    converged:  bool
    err:        str or None — error message if solve failed

Entry points:
    run_single_case(case) -> result dict
    run_batch(cases, max_workers=1, progress_cb=None) -> list of result dicts
"""
from __future__ import annotations

import os
from typing import Callable, Optional
import numpy as np


def run_single_case(case: dict) -> dict:
    """Evaluate one case through the full ThermoNAS pipeline.

    Self-contained: imports solver modules on first call so worker processes
    in a multiprocessing pool each trigger their own JIT warmup on spawn.
    """
    try:
        from solvers.tpms_calc import (compute as tpms_compute,
                                geometry as tpms_geometry,
                                P_atm, air_density, air_viscosity,
                                air_conductivity, air_cp, adaptive_grid)
        from solvers.solve_full import solve_full_domain

        tpms = case['tpms']
        L_cell = case['L_cell_mm']
        t_wall = case['t_wall_mm']
        K_S = case['K_S']
        L_dom = case['L_dom']
        H_dom = case['H_dom']
        N_UNITS = case['N_UNITS']
        A_flow = N_UNITS * case['A_flow_per_unit']
        u_A = case['u_air']
        T_Ain_K = case['T_Ain_C'] + 273.15
        T_Bin_K = case['T_Bin_C'] + 273.15
        T_Bout_K = case['T_Bout_C'] + 273.15
        P_Ain = P_atm + case['P_Ain_gauge_Pa']

        # Geometry
        g = tpms_geometry(tpms, L_cell, t_wall, K_S)
        EPS = g['epsilon']; D_H = g['D_h']; A0 = g['A_0']
        N_X, N_Y = adaptive_grid(L_dom, H_dom, D_H, alpha=0.4)

        # Air properties
        rho_A = air_density(T_Ain_K, P_Ain)
        k_A = air_conductivity(T_Ain_K)
        cp_A = air_cp(T_Ain_K)
        m_air = rho_A * u_A * A_flow  # reconstruct mass flow from u_air

        # Air-side h_v from Nu correlation
        r_A = tpms_compute(tpms, L_cell, t_wall, u_A, T_Ain_K, P_Ain, K_S)
        h_vA = A0 * r_A['H_sf']

        # C-1 assumption: water side is a perfect heat sink (Ts tracks Tb)
        h_vB = 1.0e10

        # Thermal conductivity and heat capacity arrays
        K_ffA = (EPS / 2) * k_A
        K_ffB = (EPS / 2) * 0.6     # placeholder water k (unused since Tb frozen)
        K_ss = (1 - EPS) * K_S
        rho_cp_A = rho_A * cp_A
        rho_cp_B = 4.18e6           # placeholder water rho*cp

        # Uniform air velocity for the temperature solver (C-1 workaround)
        ucA = np.full((N_X, N_Y), u_A, dtype=np.float64)
        vcA = np.zeros((N_X, N_Y), dtype=np.float64)
        zero = np.zeros((N_X, N_Y), dtype=np.float64)

        # Linear Tb_prescribed field along y
        dy_cell = H_dom / N_Y
        y_centers = (np.arange(N_Y) + 0.5) * dy_cell
        Tb_1d = T_Bout_K + (T_Bin_K - T_Bout_K) * (y_centers / H_dom)
        Tb_pres = np.broadcast_to(Tb_1d[None, :], (N_X, N_Y)).copy()

        Ta, _, _, info = solve_full_domain(
            L_dom, H_dom, N_X, N_Y,
            T_Ain_K, T_Bin_K,
            K_ffA, K_ffB, K_ss,
            h_vA, h_vB,
            rho_cp_A, rho_cp_B,
            EPS,
            ucA, vcA, zero, zero,
            dir_A=0, dir_B=3,
            Tb_prescribed=Tb_pres,
            max_iter=50000, tol=1e-6,
            return_info=True,
        )
        T_A_out = float(np.mean(Ta[-1, :]))
        dT = T_Ain_K - T_A_out
        Q_sim = m_air * cp_A * dT

        return {
            'Q_sim': float(Q_sim),
            'dP_sim': float('nan'),
            'converged': bool(info.get('converged', False)),
            'err': None,
        }
    except Exception as e:
        import traceback
        return {
            'Q_sim': float('nan'),
            'dP_sim': float('nan'),
            'converged': False,
            'err': f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
        }


def run_batch(cases: list[dict],
              max_workers: int = 1,
              progress_cb: Optional[Callable[[int, int], None]] = None
              ) -> list[dict]:
    """Run a list of cases, optionally in parallel.

    max_workers:
        1    -> serial (default)
        > 1  -> ProcessPoolExecutor with given worker count
        None -> os.cpu_count() - 1

    progress_cb(done, total):
        Called after each case completes.
    """
    if max_workers is None:
        max_workers = max(1, (os.cpu_count() or 2) - 1)

    total = len(cases)
    if max_workers == 1:
        results = []
        for i, case in enumerate(cases):
            results.append(run_single_case(case))
            if progress_cb is not None:
                progress_cb(i + 1, total)
        return results

    # Parallel path
    from concurrent.futures import ProcessPoolExecutor, as_completed

    results: list[dict] = [{} for _ in range(total)]
    with ProcessPoolExecutor(max_workers=max_workers) as ex:
        # Submit all tasks, remember their indices
        future_to_idx = {ex.submit(run_single_case, case): i
                         for i, case in enumerate(cases)}
        done_count = 0
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                import traceback
                results[idx] = {
                    'Q_sim': float('nan'),
                    'dP_sim': float('nan'),
                    'converged': False,
                    'err': f"worker crashed: {type(e).__name__}: {e}\n{traceback.format_exc()}",
                }
            done_count += 1
            if progress_cb is not None:
                progress_cb(done_count, total)
    return results
