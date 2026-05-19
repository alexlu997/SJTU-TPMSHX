"""Diagnostic dump of 3D fields for Shanghai case 1, uniform Gyroid L=7 t=0.6.

User reports velocity/pressure/temperature fields look wrong in 3D. This
script reproduces a single 3D run at Nx=Ny=Nz=20, wall_refine OFF, and
dumps every relevant field slice + numeric sanity checks so we can spot
the actual anomaly without going through the UI.

Output:
    vault/reports/3d-solver/2026-05-14-shanghai-3d-n20-case1-fields/
        report.md
        field_*.png

Usage:
    python -u -m runs.diag_shanghai_3d_n20_case1

The script intentionally avoids touching solvers/roughness.py,
validation/validate_shanghai_3d_real.py and the linked memory file
(other conversation's lock).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT))

from solvers.tpms_calc import (
    geometry as tpms_geometry,
    air_density, air_viscosity, air_cp,
)
from solvers.tpms_calc import (
    water_density, water_viscosity, water_cp, water_conductivity,
)
from solvers.simple_solver_3d import SIMPLESolver3D
from solvers.solve_full_3d import (
    solve_full_domain_3d, mass_balance_3d, energy_balance_3d,
)
from df_fit.predict import predict_K_cF


# ── Case 1 inputs (from validation/shanghai_3d_baselineNz10.csv) ──
U_A    = 3.916173093520119   # m/s (interstitial, air)
U_B    = 0.01658351884693773 # m/s (interstitial, water)
T_AIN  = 126.0326842877776 + 273.15  # K  (air hot inlet)
T_BIN  = 18.12736824938262 + 273.15  # K  (water cold inlet)
P_INA  = 101325.0  # Pa
P_INB  = 101325.0  # Pa
DP_EXP = 1149.13   # Pa (sum)
Q_EXP  = 248.40    # W

# Geometry
L_DOM = 0.182  # m   (streamwise A)
H_DOM = 0.042  # m   (streamwise B, +z = depth)
LZ    = 0.042  # m
TPMS  = 'Gyroid'
L_CELL = 7.0   # mm
T_WALL = 0.6   # mm
K_S    = 16.0  # W/m·K (solid k, AlSi10Mg-class)

# Grid
NX, NY, NZ = 20, 20, 20

# Direction codes (cross-flow)
DIR_A = 0  # +x: air along long axis
DIR_B = 3  # -y: water along short axis, opposite sense

# Output — write directly to the Obsidian-linked Postgraduate vault, not
# the per-repo SJTU-TPMSHX/vault (merged into Postgraduate/vault on
# 2026-05-14 per user request: all generated vault content lives in the
# project-root Obsidian vault).
OUT_DIR = Path(r"D:/Postgraduate/vault/reports/3d-solver/2026-05-14-shanghai-3d-n20-case1-fields")
OUT_DIR.mkdir(parents=True, exist_ok=True)

R_AIR = 287.05


def main():
    t_total = time.perf_counter()
    log: list[str] = []
    p = lambda s: (print(s, flush=True), log.append(s))

    p("# Shanghai case 1, 3D field diagnostic")
    p(f"Grid: Nx={NX} Ny={NY} Nz={NZ}  ({NX*NY*NZ} cells)")
    p(f"Domain: L={L_DOM*1e3:.0f} × H={H_DOM*1e3:.0f} × Lz={LZ*1e3:.0f} mm")
    p(f"u_A={U_A:.3f} m/s  T_A={T_AIN-273.15:.1f}°C  P_A={P_INA:.0f} Pa")
    p(f"u_B={U_B:.5f} m/s  T_B={T_BIN-273.15:.1f}°C  P_B={P_INB:.0f} Pa")
    p(f"Exp: Q={Q_EXP:.1f} W   dP_sum={DP_EXP:.0f} Pa")
    p("")

    # ── Geometry derived ──
    g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
    eps = g['epsilon']
    eps_A = g['epsilon_A']
    D_h = g['D_h']
    A_0 = g['A_0']
    p(f"Geom: ε={eps:.4f}  ε_A={eps_A:.4f}  D_h={D_h*1e3:.3f} mm  A_0={A_0:.0f} 1/m")

    # K, cF from surrogate (smooth-wall ConstDF-v1)
    K_val, cF_val = predict_K_cF(TPMS, L_CELL, T_WALL, eps_A)
    p(f"D-F: K={K_val:.4e} m²  cF={cF_val:.2f} 1/m")

    # ── Fluid props at inlet ──
    rho_A0 = float(air_density(T_AIN, P_INA))
    mu_A0  = float(air_viscosity(T_AIN))
    cp_A0  = float(air_cp(T_AIN))
    rho_B0 = float(water_density(T_BIN))
    mu_B0  = float(water_viscosity(T_BIN))
    cp_B0  = float(water_cp(T_BIN))
    k_fB   = float(water_conductivity(T_BIN))
    Re_A = rho_A0 * abs(U_A) * D_h / mu_A0
    Re_B = rho_B0 * abs(U_B) * D_h / mu_B0
    p(f"Air  ρ={rho_A0:.4f}  μ={mu_A0:.4e}  cp={cp_A0:.1f}  Re_A={Re_A:.0f}")
    p(f"H2O  ρ={rho_B0:.1f}  μ={mu_B0:.4e}  cp={cp_B0:.0f}  Re_B={Re_B:.1f}")

    # ── Build uniform 3D arrays (Nx, Ny, Nz) ──
    K_A_arr = np.full((NX, NY, NZ), K_val, dtype=np.float64)
    cF_A_arr = np.full((NX, NY, NZ), cF_val, dtype=np.float64)
    K_B_arr = K_A_arr.copy()
    cF_B_arr = cF_A_arr.copy()

    # h_v (volumetric htc), eps fields
    # h_v = A_0 * h_sf; h_sf from Nu·k/D_h. Use simple correlations.
    # For air: Nu_air ≈ Nu_Gyroid_v4.1 — use ×1.28 already baked into compute(). Use baseline here.
    # Simple choice: forced convection Nu = 0.023·Re^0.8·Pr^(1/3) (Dittus-Boelter) for sanity
    Pr_A = mu_A0 * cp_A0 / 0.04  # k_f air at 400K ~ 0.034
    k_fA = 0.034
    Nu_A = max(3.66, 0.023 * Re_A**0.8 * Pr_A**(1/3))
    Pr_B = mu_B0 * cp_B0 / k_fB
    Nu_B = max(3.66, 0.023 * max(Re_B, 1.0)**0.8 * Pr_B**(1/3))
    h_sfA = Nu_A * k_fA / D_h
    h_sfB = Nu_B * k_fB / D_h
    h_vA = A_0 * h_sfA  # W/m³K
    h_vB = A_0 * h_sfB
    p(f"Nu_A={Nu_A:.2f} h_vA={h_vA:.2e}   Nu_B={Nu_B:.2f} h_vB={h_vB:.2e}")
    h_vA_arr = np.full((NX, NY, NZ), h_vA, dtype=np.float64)
    h_vB_arr = np.full((NX, NY, NZ), h_vB, dtype=np.float64)
    # 2026-05-14: kernel expects single-channel ε_A (= ε/2 for Gyroid).
    eps_arr = np.full((NX, NY, NZ), eps, dtype=np.float64)  # 2026-05-19: FULL ε; kernel halves once (Option A)
    eps_A_arr = np.full((NX, NY, NZ), eps_A, dtype=np.float64)
    eps_B_arr = np.full((NX, NY, NZ), eps_A, dtype=np.float64)  # symmetric A/B for Gyroid

    rcp_A = np.full((NX, NY, NZ), rho_A0 * cp_A0, dtype=np.float64)
    rcp_B = np.full((NX, NY, NZ), rho_B0 * cp_B0, dtype=np.float64)

    K_ffA = np.full((NX, NY, NZ), eps_A * k_fA, dtype=np.float64)
    K_ffB = np.full((NX, NY, NZ), eps_A * k_fB, dtype=np.float64)
    K_ss  = np.full((NX, NY, NZ), (1 - eps) * K_S, dtype=np.float64)

    dx_arr = np.full(NX, L_DOM / NX, dtype=np.float64)
    dy_arr = np.full(NY, H_DOM / NY, dtype=np.float64)
    dz_arr = np.full(NZ, LZ    / NZ, dtype=np.float64)

    # ── SIMPLE A (air, +x → solver-y = real-x) ──
    # SIMPLESolver3D streamwise axis is solver-y; map K_A to (Ny_sim, Nz)
    # For Fluid A streamwise = real-x → solver Nx_sim = NY (real-y cross), Ny_sim = NX (real-x streamwise)
    K_A_solver = np.full((NX, NZ), K_val, dtype=np.float64)  # (Ny_sim=NX, Nz)
    cF_A_solver = np.full((NX, NZ), cF_val, dtype=np.float64)
    # Mean P seed
    G_A = rho_A0 * U_A
    C_A = mu_A0 * G_A / K_val + cF_val * G_A * G_A
    P_out_sq_A = P_INA**2 - 2.0 * R_AIR * T_AIN * C_A * L_DOM
    P_ref_A = float(np.sqrt(max(P_out_sq_A, 1.0e4)))

    sA = SIMPLESolver3D(
        Lx=H_DOM, Ly=L_DOM, Lz=LZ,
        Nx=NY, Ny=NX, Nz=NZ,
        rho=rho_A0, mu=mu_A0, T_in=T_AIN, v_inlet=U_A,
        eps=eps, K_arr=K_A_solver, cF_arr=cF_A_solver,
        P_ref_abs=P_ref_A,
    )
    sA.dx = np.ascontiguousarray(dy_arr, dtype=np.float64)
    sA.dy = np.ascontiguousarray(dx_arr, dtype=np.float64)
    sA.dz = np.ascontiguousarray(dz_arr, dtype=np.float64)

    # ── SIMPLE B (water, -y → solver-y = real-y reversed) ──
    K_B_solver = np.full((NX, NZ), K_val, dtype=np.float64)
    cF_B_solver = np.full((NX, NZ), cF_val, dtype=np.float64)
    G_B = rho_B0 * U_B
    C_B = mu_B0 * G_B / K_val + cF_val * G_B * G_B
    P_out_sq_B = P_INB**2 - 2.0 * R_AIR * T_BIN * C_B * H_DOM
    # water incompressible: avoid P²-based seed
    P_ref_B = P_INB - 1.0  # tiny offset; water solver will not use ideal gas

    sB = SIMPLESolver3D(
        Lx=L_DOM, Ly=H_DOM, Lz=LZ,
        Nx=NX, Ny=NY, Nz=NZ,
        rho=rho_B0, mu=mu_B0, T_in=T_BIN, v_inlet=U_B,
        eps=eps, K_arr=K_B_solver, cF_arr=cF_B_solver,
        P_ref_abs=P_ref_B,
        fluid_type='incompressible',
    )
    sB.dx = np.ascontiguousarray(dx_arr, dtype=np.float64)
    sB.dy = np.ascontiguousarray(dy_arr, dtype=np.float64)
    sB.dz = np.ascontiguousarray(dz_arr, dtype=np.float64)

    p("\n## SIMPLE A solve")
    t0 = time.perf_counter()
    sA.solve(max_iter=800, tol=1e-2, verbose=False)
    p(f"  wall = {time.perf_counter()-t0:.1f}s")
    p(f"  v range = [{sA.v.min():.3f}, {sA.v.max():.3f}]  mean = {sA.v.mean():.3f}")
    p(f"  P range = [{sA.P.min():.1f}, {sA.P.max():.1f}]  span = {sA.P.max()-sA.P.min():.1f}")

    p("\n## SIMPLE B solve")
    t0 = time.perf_counter()
    sB.solve(max_iter=800, tol=1e-2, verbose=False)
    p(f"  wall = {time.perf_counter()-t0:.1f}s")
    p(f"  v range = [{sB.v.min():.5f}, {sB.v.max():.5f}]  mean = {sB.v.mean():.5f}")
    p(f"  P range = [{sB.P.min():.3f}, {sB.P.max():.3f}]  span = {sB.P.max()-sB.P.min():.3f}")

    # ── Map cell-centered velocities to real coords ──
    # Fluid A: solver internal axes (Nx_sim=NY, Ny_sim=NX, Nz). Streamwise = solver-y.
    vA_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])    # (NY, NX, NZ)
    ucA_real = vA_cc.transpose(1, 0, 2).copy()           # (NX, NY, NZ)
    vcA_real = np.zeros_like(ucA_real)
    wcA_real = np.zeros_like(ucA_real)

    # Fluid B: solver (NX, NY, NZ). Streamwise = solver-y. Dir code -y.
    vB_cc = 0.5 * (sB.v[:, :-1, :] + sB.v[:, 1:, :])    # (NX, NY, NZ)
    vcB_real = -vB_cc[:, ::-1, :].copy()                  # flip y axis for -y dir
    ucB_real = np.zeros_like(vcB_real)
    wcB_real = np.zeros_like(vcB_real)

    p(f"\n## Velocity map (real coords)")
    p(f"  A: u range [{ucA_real.min():.3f}, {ucA_real.max():.3f}]  mean {ucA_real.mean():.3f}")
    p(f"  B: v range [{vcB_real.min():.5f}, {vcB_real.max():.5f}]  mean {vcB_real.mean():.5f}")

    # ── LTNE solve ──
    # NOTE: frozen-velocity thermal snapshot — sA/sB solved ONCE above; this
    # loop iterates ONLY the LTNE 3-temperature solve. NOT a SIMPLE<->LTNE
    # compressible coupling (no sA.solve()/update_T_field re-call by design).
    # For coupled T-rho behaviour see ui/demo_vis_3d.py:140-147.
    p("\n## Outer LTNE solve (2 outer iters, frozen velocity)")
    Ta = Tb = Ts = None
    for it in range(2):
        t0 = time.perf_counter()
        Ta, Tb, Ts = solve_full_domain_3d(
            L_DOM, H_DOM, LZ, NX, NY, NZ, T_AIN, T_BIN,
            K_ffA, K_ffB, K_ss, h_vA_arr, h_vB_arr,
            rcp_A, rcp_B, eps_arr,
            ucA_real, vcA_real, wcA_real,
            ucB_real, vcB_real, wcB_real,
            DIR_A, DIR_B,
            dx_arr=dx_arr, dy_arr=dy_arr, dz_arr=dz_arr,
            max_iter=1500, tol=0.5, alpha_T=0.7,
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
        )
        p(f"  outer {it+1}: wall = {time.perf_counter()-t0:.1f}s")
        p(f"    Ta range [{Ta.min()-273.15:.1f}, {Ta.max()-273.15:.1f}] °C  mean {Ta.mean()-273.15:.1f}")
        p(f"    Tb range [{Tb.min()-273.15:.1f}, {Tb.max()-273.15:.1f}] °C  mean {Tb.mean()-273.15:.1f}")
        p(f"    Ts range [{Ts.min()-273.15:.1f}, {Ts.max()-273.15:.1f}] °C  mean {Ts.mean()-273.15:.1f}")

    # ── Sanity checks ──
    p("\n## Conservation diagnostics")
    e_bal = energy_balance_3d(Ta, Tb, Ts, h_vA_arr, h_vB_arr,
                                dx_arr, dy_arr, dz_arr)
    Q_sA = e_bal['Q_sA']
    Q_sB = e_bal['Q_sB']
    Q_net = e_bal['Q_net']
    p(f"  Q_sA  ∫h_vA·(Ts−Ta)·V = {Q_sA:+.3f} W  (solid→A; neg = A heating solid)")
    p(f"  Q_sB  ∫h_vB·(Ts−Tb)·V = {Q_sB:+.3f} W  (solid→B; pos = solid heats B)")
    p(f"  Q_net = Q_sA + Q_sB   = {Q_net:+.3f} W  (steady → 0)")
    p(f"  Q_net / max(|Q_sA|,|Q_sB|) = {Q_net/max(abs(Q_sA),abs(Q_sB),1e-9):.3e}")

    # Enthalpy balance (A inlet/outlet faces)
    # Air: dir=+x → inlet at x=0 (i=0), outlet at x=L (i=Nx-1)
    A_face_x = H_DOM * LZ
    mdot_A_face = rho_A0 * U_A * A_face_x  # superficial-velocity flow rate (kg/s)
    # interstitial inlet on (Ny, Nz): u·ε_A·A_face = u_int·A_open
    A_open = eps_A * A_face_x
    mdot_A_int = rho_A0 * U_A * A_open
    T_A_in_mean  = float(Ta[0, :, :].mean())
    T_A_out_mean = float(Ta[-1, :, :].mean())
    Q_enth_A_face_super = mdot_A_face * cp_A0 * (T_A_in_mean - T_A_out_mean)
    Q_enth_A_face_int   = mdot_A_int  * cp_A0 * (T_A_in_mean - T_A_out_mean)
    p(f"\n  Air mass flow (superficial face):  {mdot_A_face:.4e} kg/s")
    p(f"  Air mass flow (interstitial open): {mdot_A_int:.4e} kg/s")
    p(f"  T_A in = {T_A_in_mean-273.15:.1f}°C  out = {T_A_out_mean-273.15:.1f}°C  ΔT = {T_A_in_mean-T_A_out_mean:.1f}K")
    p(f"  Q_enth_A (superficial m_dot) = {Q_enth_A_face_super:.1f} W")
    p(f"  Q_enth_A (interstitial m_dot) = {Q_enth_A_face_int:.1f} W")
    p(f"  Q_exp                         = {Q_EXP:.1f} W")

    # Q via enthalpy
    cell_vol = (dx_arr[:, None, None] * dy_arr[None, :, None] * dz_arr[None, None, :])
    Q_enth_A = float(np.sum(h_vA_arr * (Ts - Ta) * cell_vol))
    Q_enth_B = float(np.sum(h_vB_arr * (Ts - Tb) * cell_vol))
    p(f"  Σh_vA·(Ts−Ta)·V = {Q_enth_A:+.3f} W")
    p(f"  Σh_vB·(Ts−Tb)·V = {Q_enth_B:+.3f} W")

    # dP
    dP_A = float(SIMPLESolver3D.extract_dP_weighted(sA))
    dP_B = float(SIMPLESolver3D.extract_dP_weighted(sB))
    p(f"\n  dP_A = {dP_A:.1f} Pa")
    p(f"  dP_B = {dP_B:.3f} Pa")
    p(f"  dP_sum = {dP_A + dP_B:.1f} Pa  (exp = {DP_EXP:.0f})")

    # ── Field slices ──
    p("\n## Field slices saved to:")
    p(f"  {OUT_DIR}")

    # Helper
    def save_slice(field_3d, name, cmap='viridis', cbar_label=''):
        i_mid = NX // 2
        j_mid = NY // 2
        k_mid = NZ // 2
        fig, axes = plt.subplots(1, 3, figsize=(14, 4))
        # Mid-x (y-z plane)
        im0 = axes[0].imshow(field_3d[i_mid, :, :].T, origin='lower',
                              aspect='auto', cmap=cmap,
                              extent=[0, H_DOM*1e3, 0, LZ*1e3])
        axes[0].set_title(f'{name}  mid-x (i={i_mid})')
        axes[0].set_xlabel('y [mm]'); axes[0].set_ylabel('z [mm]')
        plt.colorbar(im0, ax=axes[0], label=cbar_label)
        # Mid-y (x-z plane)
        im1 = axes[1].imshow(field_3d[:, j_mid, :].T, origin='lower',
                              aspect='auto', cmap=cmap,
                              extent=[0, L_DOM*1e3, 0, LZ*1e3])
        axes[1].set_title(f'{name}  mid-y (j={j_mid})')
        axes[1].set_xlabel('x [mm]'); axes[1].set_ylabel('z [mm]')
        plt.colorbar(im1, ax=axes[1], label=cbar_label)
        # Mid-z (x-y plane)
        im2 = axes[2].imshow(field_3d[:, :, k_mid].T, origin='lower',
                              aspect='auto', cmap=cmap,
                              extent=[0, L_DOM*1e3, 0, H_DOM*1e3])
        axes[2].set_title(f'{name}  mid-z (k={k_mid})')
        axes[2].set_xlabel('x [mm]'); axes[2].set_ylabel('y [mm]')
        plt.colorbar(im2, ax=axes[2], label=cbar_label)
        plt.tight_layout()
        out = OUT_DIR / f'field_{name.replace(" ", "_").replace("/", "")}.png'
        fig.savefig(out, dpi=120)
        plt.close(fig)

    save_slice(ucA_real, 'u_A_streamwise',  cmap='viridis', cbar_label='m/s')
    save_slice(vcB_real, 'v_B_streamwise',  cmap='viridis', cbar_label='m/s')
    # Pressure (transpose A back to real coords)
    P_real_A = sA.P.transpose(1, 0, 2).copy()  # (NY, NX, NZ) -> (NX, NY, NZ)
    P_real_B = sB.P.copy()
    save_slice(P_real_A,  'P_A_gauge', cmap='plasma',  cbar_label='Pa')
    save_slice(P_real_B,  'P_B_gauge', cmap='plasma',  cbar_label='Pa')
    save_slice(Ta - 273.15, 'T_A_air',     cmap='hot',     cbar_label='°C')
    save_slice(Tb - 273.15, 'T_B_water',   cmap='cool',    cbar_label='°C')
    save_slice(Ts - 273.15, 'T_solid',     cmap='copper',  cbar_label='°C')

    p("\nDone. Total wall: {:.1f}s".format(time.perf_counter() - t_total))

    with open(OUT_DIR / 'report.md', 'w', encoding='utf-8') as f:
        f.write("\n".join(log))


if __name__ == '__main__':
    main()
