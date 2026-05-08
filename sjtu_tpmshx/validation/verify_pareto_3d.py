"""
validation/verify_pareto_3d.py — Independent 3D verification of a 2D Pareto pick.

The continuous-field optimizer runs a 2D SIMPLE × 2 + LTNE pipeline that
returns (Q_2D, dP_2D) per unit HX depth. This script takes one Pareto
solution, extrudes its L(x, y) and t(x, y) fields uniformly along z to fill
a 3D voxel grid, runs the full 3D solver stack
(SIMPLESolver3D + solve_full_domain_3d with outer ρ(T) coupling), and
reports::

    Q_3D vs Q_2D · Lz       — total heat transfer (W)
    dP_A_3D, dP_B_3D vs dP_2D
    Δ relative                — quantifies the 3D physics correction

Usage::

    python -m validation.verify_pareto_3d \\
        --pareto opt_runs/production_v1/pareto_final.csv \\
        --row    2 \\
        --Nx 40 --Ny 16 --Nz 16 \\
        --Lz 0.042

Defaults reuse the run's config.json so the 3D run sees the same
(tpms_type, L_domain, H_domain, fluid operating point) as the 2D
optimization. ``Lz`` defaults to 0.042 m (Shanghai depth), but is the only
parameter the 2D run cannot supply since the optimizer has no z dimension.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

warnings.filterwarnings('ignore')

from solvers.tpms_calc import (
    air_density, air_viscosity, air_cp,
    geometry as tpms_geometry,
)
from solvers.simple_solver_3d import SIMPLESolver3D
from solvers.solve_full_3d import solve_full_domain_3d
from solvers.df_projection import (
    project_fields_to_streamwise_K_cF_3d,
)
from solvers.field_param import from_decision_vector


R_AIR = 287.05


# ─── Loading ────────────────────────────────────────────────────────


def _load_pareto_row(pareto_csv: str, row_index: int,
                      decision_dim_expected: int = 16) -> tuple:
    data = np.loadtxt(pareto_csv, delimiter=',', skiprows=1)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if row_index < 0 or row_index >= data.shape[0]:
        raise IndexError(f"row {row_index} out of range [0, {data.shape[0]})")
    row = data[row_index]
    return (row[:decision_dim_expected],
            float(row[decision_dim_expected]),     # Q_2D [W/m]
            float(row[decision_dim_expected + 1])) # dP_2D [Pa]


def _load_run_cfg(pareto_csv: str) -> dict:
    cfg_path = Path(pareto_csv).parent / 'config.json'
    if cfg_path.exists():
        with open(cfg_path) as f:
            return json.load(f)
    return {}


# ─── 3D field construction (extrude 2D field along z) ───────────────


def _build_3d_arrays(fc, Nx: int, Ny: int, Nz: int,
                     u_A: float, u_B: float,
                     T_inA: float, T_inB: float,
                     P_inA: float, k_s: float,
                     tpms_type: str,
                     quant_L: float = 0.05,
                     quant_t: float = 0.01) -> dict:
    """Per-voxel arrays (eps, K_ffA/B, K_ss, h_vA/B, A_0, eps_A) of shape
    (Nx, Ny, Nz). 2D field extruded uniformly along z.
    """
    L_field_2D, t_field_2D = fc.evaluate_grid(Nx, Ny)

    # Quantize for cache reuse (same trick as the 2D build_grid_arrays)
    L_q = np.round(L_field_2D / quant_L) * quant_L
    t_q = np.round(t_field_2D / quant_t) * quant_t

    eps_arr   = np.empty((Nx, Ny, Nz), dtype=np.float64)
    eps_f_arr = np.empty((Nx, Ny, Nz), dtype=np.float64)
    K_ffA_arr = np.empty((Nx, Ny, Nz), dtype=np.float64)
    K_ffB_arr = np.empty((Nx, Ny, Nz), dtype=np.float64)
    K_ss_arr  = np.empty((Nx, Ny, Nz), dtype=np.float64)
    h_vA_arr  = np.empty((Nx, Ny, Nz), dtype=np.float64)
    h_vB_arr  = np.empty((Nx, Ny, Nz), dtype=np.float64)
    A_0_arr   = np.empty((Nx, Ny, Nz), dtype=np.float64)

    L_field_3D = np.broadcast_to(L_field_2D[:, :, None], (Nx, Ny, Nz)).copy()
    t_field_3D = np.broadcast_to(t_field_2D[:, :, None], (Nx, Ny, Nz)).copy()

    from solvers import tpms_calc
    cache: dict = {}
    for i in range(Nx):
        for j in range(Ny):
            key = (round(float(L_q[i, j]), 4),
                   round(float(t_q[i, j]), 4))
            if key not in cache:
                pA = tpms_calc.compute(tpms_type, key[0], key[1],
                                       u_A, T_inA, P_inA, k_s)
                pB = tpms_calc.compute(tpms_type, key[0], key[1],
                                       u_B, T_inB, P_inA, k_s)
                cache[key] = (pA, pB)
            pA, pB = cache[key]
            eps_arr[i, j, :]   = pA['epsilon']
            eps_f_arr[i, j, :] = pA['epsilon_A']
            K_ffA_arr[i, j, :] = pA['K_ff']
            K_ffB_arr[i, j, :] = pB['K_ff']
            K_ss_arr[i, j, :]  = pA['K_ss']
            h_vA_arr[i, j, :]  = pA['H_sf'] * pA['A_0']
            h_vB_arr[i, j, :]  = pB['H_sf'] * pB['A_0']
            A_0_arr[i, j, :]   = pA['A_0']

    return {
        'eps_arr':   eps_arr,
        'eps_f_arr': eps_f_arr,
        'K_ffA_arr': K_ffA_arr,
        'K_ffB_arr': K_ffB_arr,
        'K_ss_arr':  K_ss_arr,
        'h_vA_arr':  h_vA_arr,
        'h_vB_arr':  h_vB_arr,
        'A_0_arr':   A_0_arr,
        'L_field':   L_field_3D,
        't_field':   t_field_3D,
        'cache_size': len(cache),
    }


# ─── 3D evaluate ────────────────────────────────────────────────────


def evaluate_3d(x_decision: np.ndarray,
                cfg: dict,
                *,
                Nx: int = 40, Ny: int = 16, Nz: int = 16,
                Lz: float = 0.042,
                max_outer: int = 3,
                outer_tol_K: float = 0.5,
                alpha_outer: float = 0.6,
                max_iter_simple: int = 800,
                tol_simple: float = 1e-2,
                max_iter_energy: int = 2000,
                tol_energy: float = 0.5,
                verbose: bool = True) -> dict:
    """Run the 3D evaluator on a single decision vector. Returns (Q_3D_W,
    dP_A_3D, dP_B_3D, dP_total_3D, mass_kg, info_dict).
    """
    L_dom = float(cfg['L_domain']); H_dom = float(cfg['H_domain'])
    u_A   = float(cfg['u_A']);     u_B   = float(cfg['u_B'])
    T_inA = float(cfg['T_inA']);   T_inB = float(cfg['T_inB'])
    P_inA = float(cfg.get('P_inA', 101325.0))
    P_inB = float(cfg.get('P_inB', P_inA))
    tpms_type = cfg.get('tpms_type', 'Diamond')
    k_s   = float(cfg.get('k_s', 17.0))
    rho_s = float(cfg.get('rho_s', 2700.0))
    n_ctrl_x = int(cfg.get('n_ctrl_x', 4))
    n_ctrl_y = int(cfg.get('n_ctrl_y', 4))
    sym_y    = bool(cfg.get('symmetric_y', True))

    # 1. Build 2D field, extrude to 3D arrays
    fc = from_decision_vector(
        x_decision, tpms_type=tpms_type, k_s=k_s,
        L_domain=L_dom, H_domain=H_dom,
        n_ctrl_x=n_ctrl_x, n_ctrl_y=n_ctrl_y, symmetric_y=sym_y,
    )
    arrays = _build_3d_arrays(fc, Nx, Ny, Nz,
                               u_A, u_B, T_inA, T_inB, P_inA, k_s, tpms_type)

    dx_arr = np.full(Nx, L_dom / Nx, dtype=np.float64)
    dy_arr = np.full(Ny, H_dom / Ny, dtype=np.float64)
    dz_arr = np.full(Nz, Lz    / Nz, dtype=np.float64)

    # 2. Project to SIMPLE 3D K/cF arrays (per-row mean over cross-stream)
    K_A, cF_A = project_fields_to_streamwise_K_cF_3d(
        arrays['L_field'], arrays['t_field'], arrays['eps_f_arr'],
        tpms_type, Ny_sim=Nx, Nz_sim=Nz, fluid='A',
        streamwise_dx=dx_arr, z_dx=dz_arr)
    K_B, cF_B = project_fields_to_streamwise_K_cF_3d(
        arrays['L_field'], arrays['t_field'], arrays['eps_f_arr'],
        tpms_type, Ny_sim=Ny, Nz_sim=Nz, fluid='B',
        streamwise_dx=dy_arr, z_dx=dz_arr)

    # 3. Build SIMPLE 3D for both fluids. Fluid A: +x streamwise → axis swap
    # so SIMPLE-y = real-x; Fluid B: -y streamwise → SIMPLE-y = real-y reversed.
    rho_A0 = air_density(T_inA, P_inA); mu_A0 = air_viscosity(T_inA)
    rho_B0 = air_density(T_inB, P_inB); mu_B0 = air_viscosity(T_inB)
    eps_mean = float(arrays['eps_arr'].mean())

    # 1D D-F closed-form seed for P_ref_abs (matches retired evaluate_3d)
    K_mean_A = float(np.mean(K_A))
    cF_mean_A = float(np.mean(cF_A))
    G_A = rho_A0 * u_A
    C_A = mu_A0 * G_A / max(K_mean_A, 1e-16) + cF_mean_A * G_A * G_A
    P_out_sq_A = P_inA ** 2 - 2.0 * R_AIR * T_inA * C_A * L_dom
    P_ref_A = float(np.sqrt(max(P_out_sq_A, 1.0e4)))

    K_mean_B = float(np.mean(K_B))
    cF_mean_B = float(np.mean(cF_B))
    G_B = rho_B0 * u_B
    C_B = mu_B0 * G_B / max(K_mean_B, 1e-16) + cF_mean_B * G_B * G_B
    P_out_sq_B = P_inB ** 2 - 2.0 * R_AIR * T_inB * C_B * H_dom
    P_ref_B = float(np.sqrt(max(P_out_sq_B, 1.0e4)))

    sA = SIMPLESolver3D(
        Lx=H_dom, Ly=L_dom, Lz=Lz, Nx=Ny, Ny=Nx, Nz=Nz,
        rho=rho_A0, mu=mu_A0, T_in=T_inA, v_inlet=u_A,
        eps=eps_mean, K_arr=K_A, cF_arr=cF_A, P_ref_abs=P_ref_A,
    )
    sA.dx = np.ascontiguousarray(dy_arr, dtype=np.float64)
    sA.dy = np.ascontiguousarray(dx_arr, dtype=np.float64)
    sA.dz = np.ascontiguousarray(dz_arr, dtype=np.float64)

    sB = SIMPLESolver3D(
        Lx=L_dom, Ly=H_dom, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        rho=rho_B0, mu=mu_B0, T_in=T_inB, v_inlet=u_B,
        eps=eps_mean, K_arr=K_B, cF_arr=cF_B, P_ref_abs=P_ref_B,
    )
    sB.dx = np.ascontiguousarray(dx_arr, dtype=np.float64)
    sB.dy = np.ascontiguousarray(dy_arr, dtype=np.float64)
    sB.dz = np.ascontiguousarray(dz_arr, dtype=np.float64)

    # 4. Initial SIMPLE solves
    if verbose:
        print(f"[3D] Solving SIMPLE A (cold) … ", end='', flush=True)
    t0 = time.perf_counter()
    sA.solve(max_iter=max_iter_simple, tol=tol_simple, verbose=False)
    if verbose:
        print(f"{time.perf_counter()-t0:.0f}s")
        print(f"[3D] Solving SIMPLE B (cold) … ", end='', flush=True)
    t0 = time.perf_counter()
    sB.solve(max_iter=max_iter_simple, tol=tol_simple, verbose=False)
    if verbose:
        print(f"{time.perf_counter()-t0:.0f}s")

    # 5. Outer LTNE coupling with variable density on fluid A.
    rcp_A_field = np.full((Nx, Ny, Nz), rho_A0 * air_cp(T_inA), dtype=np.float64)
    rcp_B_field = np.full((Nx, Ny, Nz), rho_B0 * air_cp(T_inB), dtype=np.float64)
    Ta = Tb = Ts = None
    Ta_prev = None

    for outer_it in range(max_outer):
        # Cell-centred velocities
        vA_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])    # (Ny, Nx, Nz)
        ucA_real = vA_cc.transpose(1, 0, 2).copy()           # (Nx, Ny, Nz)
        vcA_real = np.zeros_like(ucA_real)
        wcA_real = np.zeros_like(ucA_real)
        vB_cc = 0.5 * (sB.v[:, :-1, :] + sB.v[:, 1:, :])    # (Nx, Ny, Nz)
        vcB_real = -vB_cc[:, ::-1, :].copy()
        ucB_real = np.zeros_like(vcB_real)
        wcB_real = np.zeros_like(vcB_real)

        if verbose:
            print(f"[3D] outer {outer_it+1}/{max_outer} … ", end='', flush=True)
        t0 = time.perf_counter()
        Ta, Tb, Ts = solve_full_domain_3d(
            L_dom, H_dom, Lz, Nx, Ny, Nz, T_inA, T_inB,
            arrays['K_ffA_arr'], arrays['K_ffB_arr'], arrays['K_ss_arr'],
            arrays['h_vA_arr'], arrays['h_vB_arr'],
            rcp_A_field, rcp_B_field, arrays['eps_arr'],
            ucA_real, vcA_real, wcA_real,
            ucB_real, vcB_real, wcB_real,
            cfg.get('dir_A', 0), cfg.get('dir_B', 3),
            dx_arr=dx_arr, dy_arr=dy_arr, dz_arr=dz_arr,
            max_iter=max_iter_energy, tol=outer_tol_K,
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
            alpha_T=0.7,
        )
        if verbose:
            print(f"{time.perf_counter()-t0:.0f}s")

        if Ta_prev is not None:
            dT_max = float(np.max(np.abs(Ta - Ta_prev)))
            if dT_max < outer_tol_K:
                if verbose:
                    print(f"[3D] outer converged at iter {outer_it+1} "
                          f"(dT_max={dT_max:.2f} < {outer_tol_K} K)")
                break
        Ta_prev = Ta.copy()

        if outer_it == max_outer - 1:
            break

        # Var-density update on fluid A (matches retired evaluate_3d)
        Ta_sA = Ta.transpose(1, 0, 2).copy()  # to SIMPLE A's internal layout
        P_abs_sA = sA.P_ref_abs + sA.P
        rho_A_new = P_abs_sA / (R_AIR * Ta_sA)
        mu_A_new = air_viscosity(Ta_sA)
        sA.rho_field = np.ascontiguousarray(
            alpha_outer * rho_A_new + (1 - alpha_outer) * sA.rho_field,
            dtype=np.float64)
        sA.mu_field = np.ascontiguousarray(
            alpha_outer * mu_A_new + (1 - alpha_outer) * sA.mu_field,
            dtype=np.float64)
        sA._mu_eff_field = np.ascontiguousarray(
            sA.mu_field / sA.eps, dtype=np.float64)
        T_avg = float(Ta_sA.mean())
        mu_avg = float(air_viscosity(T_avg))
        C_avg = mu_avg * G_A / max(K_mean_A, 1e-16) + cF_mean_A * G_A * G_A
        P_out_sq_new = P_inA ** 2 - 2.0 * R_AIR * T_avg * C_avg * L_dom
        sA.P_ref_abs = float(np.sqrt(max(P_out_sq_new, 1.0e4)))

        if verbose:
            print(f"[3D] re-solving SIMPLE A with var-ρ … ",
                  end='', flush=True)
        t0 = time.perf_counter()
        sA.solve(max_iter=max_iter_simple, tol=tol_simple, verbose=False)
        if verbose:
            print(f"{time.perf_counter()-t0:.0f}s")

        # Update rcp (real coords) using current Ta, Tb
        rcp_A_field = np.ascontiguousarray(
            alpha_outer * air_density(Ta, P_inA) * air_cp(Ta)
            + (1 - alpha_outer) * rcp_A_field, dtype=np.float64)
        rcp_B_field = np.ascontiguousarray(
            alpha_outer * air_density(Tb, P_inB) * air_cp(Tb)
            + (1 - alpha_outer) * rcp_B_field, dtype=np.float64)

    # 6. Integrate Q, dP, mass over the actual 3D grid
    cell_vol = (dx_arr[:, None, None]
                * dy_arr[None, :, None]
                * dz_arr[None, None, :])
    Q_3D = float(np.sum(arrays['h_vB_arr'] * (Ts - Tb) * cell_vol))   # W
    dP_A = float(SIMPLESolver3D.extract_dP_weighted(sA))
    dP_B = float(SIMPLESolver3D.extract_dP_weighted(sB))
    dP_total = dP_A + dP_B
    mass = float(np.sum((1.0 - arrays['eps_arr']) * rho_s * cell_vol))

    return {
        'Q_3D_W':       Q_3D,
        'dP_A_Pa':      dP_A,
        'dP_B_Pa':      dP_B,
        'dP_total_Pa':  dP_total,
        'mass_kg':      mass,
        'Lz_m':         Lz,
        'grid':         (Nx, Ny, Nz),
    }


# ─── CLI ────────────────────────────────────────────────────────────


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='verify_pareto_3d',
        description='3D verification of a 2D Pareto pick.')
    p.add_argument('--pareto', required=True, help='pareto_final.csv path')
    p.add_argument('--row', type=int, default=0, help='Pareto row index')
    p.add_argument('--Nx', type=int, default=40)
    p.add_argument('--Ny', type=int, default=16)
    p.add_argument('--Nz', type=int, default=16)
    p.add_argument('--Lz', type=float, default=0.042,
                   help='HX depth in m (default Shanghai 42 mm)')
    p.add_argument('--cfg-override', default=None,
                   help='optional JSON dict to merge over cfg.json (e.g. '
                        '\'{"u_A": 5.0}\')')
    return p


def main(argv=None) -> int:
    args = _build_argparser().parse_args(argv)

    x_decision, Q_2D_W_per_m, dP_2D_Pa = _load_pareto_row(args.pareto, args.row)
    cfg = _load_run_cfg(args.pareto)
    if args.cfg_override:
        cfg.update(json.loads(args.cfg_override))

    print(f"=== 3D verification of Pareto row {args.row} ===")
    print(f"  source: {args.pareto}")
    print(f"  cfg   : tpms={cfg.get('tpms_type')}  L_dom={cfg.get('L_domain')}  "
          f"H_dom={cfg.get('H_domain')}  Lz={args.Lz}  "
          f"u_A={cfg.get('u_A')}  u_B={cfg.get('u_B')}")
    print(f"  2D    : Q = {Q_2D_W_per_m:.0f} W/m   dP = {dP_2D_Pa:.0f} Pa")
    print(f"  3D run: grid {args.Nx}×{args.Ny}×{args.Nz}\n")

    t0 = time.perf_counter()
    out = evaluate_3d(x_decision, cfg,
                      Nx=args.Nx, Ny=args.Ny, Nz=args.Nz,
                      Lz=args.Lz)
    dt = time.perf_counter() - t0
    print(f"\n=== Results (3D wall {dt:.0f}s) ===")
    Q_2D_W_total = Q_2D_W_per_m * args.Lz
    Q_3D = out['Q_3D_W']; dP_3D = out['dP_total_Pa']
    print(f"  Q_2D × Lz   = {Q_2D_W_total:8.1f} W   ({Q_2D_W_per_m:.0f} W/m × {args.Lz} m)")
    print(f"  Q_3D        = {Q_3D:8.1f} W")
    print(f"  ΔQ rel      = {(Q_3D - Q_2D_W_total)/Q_2D_W_total*100:+6.2f} %")
    print()
    print(f"  dP_2D       = {dP_2D_Pa:8.0f} Pa  (sum of A + B in 2D evaluator)")
    print(f"  dP_A_3D     = {out['dP_A_Pa']:8.0f} Pa")
    print(f"  dP_B_3D     = {out['dP_B_Pa']:8.0f} Pa")
    print(f"  dP_total_3D = {dP_3D:8.0f} Pa")
    print(f"  ΔdP rel     = {(dP_3D - dP_2D_Pa)/max(dP_2D_Pa,1)*100:+6.2f} %")
    print()
    print(f"  mass        = {out['mass_kg']:8.4f} kg")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
