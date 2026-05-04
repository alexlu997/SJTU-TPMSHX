"""diag_3d_field_physics.py — 3D field physical sanity check.

Inline minimal Shanghai 3D Case 7 (mid-Re typical), captures Ta/Tb/Ts/u/v/w/P
arrays + prints distributions along each axis.

Verifies:
  * Ta cools along +y (A axial flow direction in SIMPLE3D internal axes):
    j=0 inlet T_in_A vs j=Ny outlet
  * Tb (prescribed): linear along real x (water -y in real device)
  * Ts between Ta and Tb
  * P decreases along +y
  * v ≈ uniform along y, slight ↑ via compressibility
  * u, w small (no transverse forcing)
  * z direction symmetric / uniform
"""
from __future__ import annotations

import sys, os, warnings
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
warnings.filterwarnings('ignore')

from solvers.tpms_calc import (
    air_density, air_viscosity, air_conductivity, air_cp,
    compute as tpms_compute, geometry as tpms_geometry, P_atm,
)
from solvers.simple_solver_3d import SIMPLESolver3D
from solvers.solve_full_3d import solve_full_domain_3d
from df_fit.predict import predict_K_cF
from validation.validate_shanghai_3d_real import (
    L_DOM, H_DOM, LZ, TPMS, L_CELL, T_WALL, K_S, EPS,
    _build_grid, _build_inlet_profile, _compute_h_vA_field_3d,
    A_FLOW, A0, MAX_OUTER, ALPHA_T, OUTER_TOL, water_rho, water_cp,
)
R_AIR = 287.05


def report_axis(name, arr, axis, idx_label):
    """Print min/mean/max of arr along given axis (averaged over other axes)."""
    other_axes = tuple(a for a in range(arr.ndim) if a != axis)
    profile = arr.mean(axis=other_axes) if len(other_axes) > 0 else arr
    print(f"  {name} along {idx_label}:")
    n = profile.size
    for i in (0, n // 4, n // 2, 3 * n // 4, n - 1):
        print(f"    [{i}] = {profile[i]:.3f}")
    print(f"    span: [{profile.min():.3f}, {profile.max():.3f}], "
          f"d({name}) end-end = {profile[-1] - profile[0]:+.3f}")


def main():
    data_path = r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
    df = pd.read_excel(data_path, engine='openpyxl', sheet_name='Sheet1',
                       header=None, skiprows=2)

    ci = 6  # Case 7
    Nx_u, Ny_u, Nz_u = 20, 10, 3
    dx, dy, dz, Nx, Ny, Nz = _build_grid(Nx_u, Ny_u, Nz_u, wall_refine=False)

    # Extract case data (column indices match validate_shanghai_3d_real)
    m_air = float(df.iloc[ci, 5])
    T_Ain_C = float(df.iloc[ci, 28]); T_Ain_K = T_Ain_C + 273.15
    P_Ain_g = float(df.iloc[ci, 30]); P_Ain = P_atm + P_Ain_g
    m_water = float(df.iloc[ci, 7])
    T_Bin_C = float(df.iloc[ci, 24]); T_Bin_K = T_Bin_C + 273.15
    T_Bout_C = float(df.iloc[ci, 25]); T_Bout_K = T_Bout_C + 273.15
    P_Aout_g = float(df.iloc[ci, 31])
    dP_A_exp = P_Ain_g - P_Aout_g
    Q_exp = float(df.iloc[ci, 33])

    rho_A = air_density(T_Ain_K, P_Ain)
    mu_A = air_viscosity(T_Ain_K)
    cp_A = air_cp(T_Ain_K)
    rho_B = water_rho(T_Bin_K)
    u_A = m_air / (rho_A * A_FLOW)

    print(f"=== Shanghai 3D Case {ci+1} field physics check ===")
    print(f"  u_A={u_A:.2f} m/s, T_Ain={T_Ain_K:.1f}K, T_Bin={T_Bin_K:.1f}K")
    print(f"  dP_exp={dP_A_exp:.0f} Pa, Q_exp={Q_exp:.0f} W")
    print(f"  Grid: {Nx} × {Ny} × {Nz} = {Nx*Ny*Nz} cells")
    print()

    # K, cF
    K_pred, cF_pred = predict_K_cF(TPMS, L_CELL, T_WALL, 0.5 * EPS)
    K_A_arr = np.full((Nx, Nz), K_pred)
    cF_A_arr = np.full((Nx, Nz), cF_pred)

    # h_v
    K_S_arr = K_S
    r_A = tpms_compute(TPMS, L_CELL, T_WALL, u_A, T_Ain_K, P_Ain, K_S_arr)
    h_vA0 = A0 * r_A['H_sf']
    h_vA_field = np.full((Nx, Ny, Nz), h_vA0)
    h_vB_field = np.full((Nx, Ny, Nz), 1.0e10)

    rho_cp_A = rho_A * cp_A
    rho_cp_B = rho_B * water_cp(T_Bin_K)

    # P_ref
    G_A = m_air / A_FLOW
    C_est = mu_A * G_A / K_pred + cF_pred * G_A * G_A
    P_out_sq = P_Ain ** 2 - 2.0 * R_AIR * T_Ain_K * C_est * L_DOM
    P_ref_A = float(np.sqrt(max(P_out_sq, 1.0e4)))

    # SIMPLE A: SIMPLE internal axes Nx_simA=Ny, Ny_simA=Nx
    v_inlet_A = _build_inlet_profile(Ny, Nz, u_A, kind='uniform', eta=0.0)
    sA = SIMPLESolver3D(Lx=H_DOM, Ly=L_DOM, Lz=LZ,
                        Nx=Ny, Ny=Nx, Nz=Nz,
                        rho=rho_A, mu=mu_A, T_in=T_Ain_K,
                        v_inlet=v_inlet_A,
                        eps=EPS, K_arr=K_A_arr, cF_arr=cF_A_arr,
                        P_ref_abs=P_ref_A,
                        fluid_type='ideal_gas')
    sA.apply_outlet_taper(n_taper=8, min_frac=0.2)
    print("Solving SIMPLE 3D + LTNE outer (4 iters)...")
    sA.solve(max_iter=400, tol=1e-3, verbose=False)

    # B side prescribed
    ucB_real = np.zeros((Nx, Ny, Nz))
    vcB_real = np.zeros((Nx, Ny, Nz))
    wcB_real = np.zeros((Nx, Ny, Nz))
    y_centres = (np.arange(Ny) + 0.5) * (H_DOM / Ny)
    Tb_1d = T_Bout_K + (T_Bin_K - T_Bout_K) * (y_centres / H_DOM)
    Tb_prescribed = np.broadcast_to(Tb_1d[None, :, None], (Nx, Ny, Nz)).copy()

    # K_ff for LTNE
    k_air = float(air_conductivity(T_Ain_K))
    K_ffA = (1.0 - EPS / 2.0) * k_air
    K_ffB = (1.0 - EPS / 2.0) * 0.6
    K_ss = (1.0 - EPS) * 16.0
    eps_arr = np.full((Nx, Ny, Nz), EPS)

    Ta = Tb = Ts = None
    for outer in range(4):
        vA_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])  # (Ny, Nx, Nz)
        ucA_real = vA_cc.transpose(1, 0, 2).copy()         # (Nx, Ny, Nz)
        vcA_real = np.zeros((Nx, Ny, Nz))
        wcA_real = np.zeros((Nx, Ny, Nz))
        if Ta is not None:
            h_vA_field = _compute_h_vA_field_3d(Ta, ucA_real, sA)

        Ta, Tb, Ts = solve_full_domain_3d(
            L_DOM, H_DOM, LZ, Nx, Ny, Nz, T_Ain_K, T_Bin_K,
            K_ffA, K_ffB, K_ss,
            h_vA_field, h_vB_field,
            rho_cp_A, rho_cp_B, eps_arr,
            ucA_real, vcA_real, wcA_real,
            ucB_real, vcB_real, wcB_real,
            dir_A=0, dir_B=3,
            dx_arr=dx, dy_arr=dy, dz_arr=dz,
            Tb_prescribed=Tb_prescribed,
            max_iter=20000, tol=1e-6,
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
            alpha_T=0.7)

        # Update SIMPLE A T_field (so _update_density uses local Ta, not stale T_in)
        Ta_sA = Ta.transpose(1, 0, 2).copy()
        sA.update_T_field(Ta_sA)
        P_abs_sA = sA.P_ref_abs + sA.P
        rho_A_new = P_abs_sA / (R_AIR * Ta_sA)
        mu_A_new = air_viscosity(Ta_sA)
        if outer > 0:
            sA.rho_field = ALPHA_T * rho_A_new + (1.0 - ALPHA_T) * sA.rho_field
            sA.mu_field = ALPHA_T * mu_A_new + (1.0 - ALPHA_T) * sA.mu_field
        else:
            sA.rho_field = rho_A_new.copy()
            sA.mu_field = mu_A_new.copy()
        sA._mu_eff_field = sA.mu_field / sA.eps
        sA.solve(max_iter=400, tol=1e-3, verbose=False)

    # ─────────────────────────────────────────────────────
    # Field physics inspection
    # SIMPLE3D internal axes: x_internal = real y (transverse), y_internal = real x (axial)
    # So in SIMPLE3D: dir=2 (+y_internal) = +x_real (axial flow A)
    # ─────────────────────────────────────────────────────
    P_abs = sA.P_ref_abs + sA.P  # Ny_simA × Nx_simA × Nz_simA = (Ny, Nx, Nz)
    # Ta, Tb, Ts: real coords (Nx, Ny, Nz) where +x is air flow direction

    print()
    print("=" * 78)
    print("FIELD PHYSICS DIAGNOSTICS")
    print("=" * 78)

    print("\n──── A 流体温度 Ta (real coords, +x = A flow direction) ────")
    report_axis("Ta", Ta, axis=0, idx_label="x (axial, A flow)")
    print(f"    EXPECT: T_in_A={T_Ain_K:.1f}K → T_out (cooled by B)")
    print(f"    SIM: T_axial[0]={Ta[0].mean():.1f} → T_axial[-1]={Ta[-1].mean():.1f}")

    print("\n──── B 流体温度 Tb (prescribed, -y direction) ────")
    report_axis("Tb", Tb, axis=1, idx_label="y (transverse, B flow)")
    print(f"    EXPECT: T_in_B={T_Bin_K:.1f} (j=Ny-1) ← T_out_B={T_Bout_K:.1f} (j=0)")
    print(f"    SIM:    Tb[j=Ny-1]={Tb[:, -1, :].mean():.1f}, Tb[j=0]={Tb[:, 0, :].mean():.1f}")

    print("\n──── 固体温度 Ts ────")
    report_axis("Ts", Ts, axis=0, idx_label="x (axial)")
    print(f"    EXPECT: Ta_min ≤ Ts ≤ Tb_max approximately")
    print(f"    SIM Ts span: [{Ts.min():.1f}, {Ts.max():.1f}]")
    print(f"    Ta span: [{Ta.min():.1f}, {Ta.max():.1f}]")
    print(f"    Tb span: [{Tb.min():.1f}, {Tb.max():.1f}]")

    print("\n──── 压力 P (gauge + ref_abs, SIMPLE3D internal coords) ────")
    # P shape (Nx_sA, Ny_sA, Nz_sA) = (Ny, Nx, Nz). Internal y = real x = axial.
    print(f"    P_ref_abs = {sA.P_ref_abs:.0f} Pa")
    P_axial_real_x = P_abs.mean(axis=(0, 2))  # avg over (real y, z) → profile along real x = SIMPLE internal y
    print(f"  P along axial x (real, A flow):")
    for i in (0, len(P_axial_real_x)//4, len(P_axial_real_x)//2, 3*len(P_axial_real_x)//4, -1):
        print(f"    [{i}] = {P_axial_real_x[i]:.0f} Pa")
    print(f"    EXPECT: P[inlet]>P[outlet] (Darcy-Forch loss)")
    print(f"    SIM: dP = P[0]-P[-1] = {P_axial_real_x[0]-P_axial_real_x[-1]:.0f} Pa (vs exp {dP_A_exp:.0f})")

    print("\n──── 速度 v (SIMPLE3D 内部 +y = real +x axial) ────")
    # v shape (Nx_sA, Ny_sA+1, Nz_sA) = (Ny, Nx+1, Nz)
    v_axial_profile = sA.v.mean(axis=(0, 2))  # avg over (real y, z)
    print(f"  v along SIMPLE-internal y (=axial real x):")
    n = len(v_axial_profile)
    for i in (0, n//4, n//2, 3*n//4, -1):
        print(f"    [{i}] = {v_axial_profile[i]:.4f} m/s")
    print(f"    EXPECT: ≈ uniform u_A={u_A:.3f}, slight ↑ from compressible expansion")
    print(f"    SIM: v in/out = {v_axial_profile[0]:.4f} / {v_axial_profile[-1]:.4f}")

    print("\n──── u (transverse y in SIMPLE = real y) ────")
    u_profile_simx = sA.u.mean(axis=(1, 2))  # SIMPLE internal x = real y
    print(f"  u (SIMPLE internal x):")
    n = len(u_profile_simx)
    for i in (0, n//2, -1):
        print(f"    [{i}] = {u_profile_simx[i]:.6f} m/s")
    print(f"    EXPECT: ≈ 0 (no transverse forcing in y for A flow)")

    print("\n──── w (z direction) ────")
    w_profile_z = sA.w.mean(axis=(0, 1))
    print(f"  w along z:")
    for i in range(min(5, len(w_profile_z))):
        print(f"    [{i}] = {w_profile_z[i]:.6f} m/s")
    print(f"    EXPECT: ≈ 0 (no source in z)")

    print("\n──── z 方向对称性 (Ta z-slice variation) ────")
    Ta_z_slices = [Ta[:, :, k].mean() for k in range(Nz)]
    print(f"  Ta avg per z-slice:")
    for k, t in enumerate(Ta_z_slices):
        print(f"    [k={k}] = {t:.3f} K")
    print(f"    EXPECT: 几乎一致 (no z-source)")
    z_var = np.std(Ta_z_slices)
    print(f"    SIM z-std = {z_var:.4f} K")

    print("\n──── 密度 ρ_A (compressibility) ────")
    rho_axial = sA.rho_field.mean(axis=(0, 2))  # avg over (real y, z); profile along real x
    print(f"  rho along axial x:")
    n = len(rho_axial)
    for i in (0, n//2, -1):
        print(f"    [{i}] = {rho_axial[i]:.4f} kg/m^3")
    print(f"    EXPECT: ρ[inlet] > ρ[outlet] (P drops, gas expands)")
    print(f"    SIM: ρ in/out = {rho_axial[0]:.4f} / {rho_axial[-1]:.4f}, "
          f"Δρ = {rho_axial[0]-rho_axial[-1]:+.4f}")


if __name__ == '__main__':
    main()
