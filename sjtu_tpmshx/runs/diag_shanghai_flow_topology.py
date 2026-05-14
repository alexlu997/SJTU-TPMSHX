"""Flow-field topology audit — Shanghai case 1, real geometry (6×6×26 cells).

Question: does SIMPLE B's water flow match the expected diagonal cross-flow
topology (top-right inlet → bottom-left outlet), or does Brinkman over-
homogenise into a near-uniform field across the whole domain?

Outputs (D:/Postgraduate/vault/reports/3d-solver/2026-05-14-flow-topology/):
  flow_air_mid_z.png      — Air u_A magnitude at mid-z slice
  flow_water_mid_z.png    — Water |v| at mid-z slice
  flow_mass_flux_water.png — ρ·|v| water at mid-z (mass flux density)
  flow_quantile_report.md  — Per-quantile speed + spatial structure stats

Reads case 1 inlet conditions from validation/shanghai_3d_baselineNz10.csv.
"""
from __future__ import annotations

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
    water_density, water_viscosity, water_cp, water_conductivity,
)
from solvers.simple_solver_3d import SIMPLESolver3D
from df_fit.predict import predict_K_cF

R_AIR = 287.05

# Shanghai prototype geometry (verified 2026-05-14, 6×6×26 unit cells)
NX, NY, NZ = 26, 6, 6   # match real unit-cell counts
L_DOM = 0.182; H_DOM = 0.042; LZ = 0.042
TPMS = 'Gyroid'; L_CELL = 7.0; T_WALL = 0.6; K_S = 16.0

# Shanghai case 1 inputs
T_AIN = 126.0327 + 273.15
T_BIN = 18.1274 + 273.15
U_A = 3.91617
U_B = 0.01658
P_INA = 101325.0; P_INB = 101325.0

# Partial-B inlet geometry (top-right 42mm), outlet (bottom-left 42mm)
B_IN_CTR = 0.154; B_IN_W = 0.042
B_OUT_CTR = 0.028; B_OUT_W = 0.042

OUT_DIR = Path(r"D:/Postgraduate/vault/reports/3d-solver/2026-05-14-flow-topology")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _build_partial_B_masks(Nx, Nz):
    x_centres = (np.arange(Nx) + 0.5) * (L_DOM / Nx)
    in_x  = ((x_centres >= B_IN_CTR  - B_IN_W/2)  & (x_centres <= B_IN_CTR  + B_IN_W/2)).astype(np.float64)
    out_x = ((x_centres >= B_OUT_CTR - B_OUT_W/2) & (x_centres <= B_OUT_CTR + B_OUT_W/2)).astype(np.float64)
    in_mask  = np.broadcast_to(in_x[:, None],  (Nx, Nz)).copy()
    out_mask = np.broadcast_to(out_x[:, None], (Nx, Nz)).copy()
    return in_mask, out_mask


def main():
    t0_total = time.perf_counter()
    print(f"# Shanghai flow-topology audit  (grid {NX}×{NY}×{NZ}, real cell counts)")

    g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
    eps_A = g['epsilon_A']; D_h = g['D_h']
    K_val, cF_val = predict_K_cF(TPMS, L_CELL, T_WALL, eps_A)
    rho_A0 = float(air_density(T_AIN, P_INA)); mu_A0 = float(air_viscosity(T_AIN))
    rho_B0 = float(water_density(T_BIN));      mu_B0 = float(water_viscosity(T_BIN))

    dx = np.full(NX, L_DOM/NX); dy = np.full(NY, H_DOM/NY); dz = np.full(NZ, LZ/NZ)

    # ── SIMPLE A: air, +x, full-width ──
    K_A = np.full((NX, NZ), K_val); cF_A = np.full((NX, NZ), cF_val)
    G_A = rho_A0 * U_A
    C_A = mu_A0 * G_A / K_val + cF_val * G_A * G_A
    P_ref_A = float(np.sqrt(max(P_INA**2 - 2.0*R_AIR*T_AIN*C_A*L_DOM, 1e4)))

    sA = SIMPLESolver3D(Lx=H_DOM, Ly=L_DOM, Lz=LZ, Nx=NY, Ny=NX, Nz=NZ,
                        rho=rho_A0, mu=mu_A0, T_in=T_AIN, v_inlet=U_A,
                        eps=eps_A, K_arr=K_A, cF_arr=cF_A, P_ref_abs=P_ref_A,
                        fluid_type='ideal_gas')
    sA.dx = dy.copy(); sA.dy = dx.copy(); sA.dz = dz.copy()
    print("\nSolving SIMPLE A …")
    t0 = time.perf_counter()
    sA.solve(max_iter=2000, tol=1e-3, verbose=False)
    print(f"  {time.perf_counter()-t0:.1f}s")

    # ── SIMPLE B: water, -y, partial inlet/outlet ──
    K_B = np.full((NY, NZ), K_val); cF_B = np.full((NY, NZ), cF_val)
    in_mask_B, out_mask_B = _build_partial_B_masks(NX, NZ)
    v_inlet_B = np.where(in_mask_B > 0.5, U_B, 0.0).astype(np.float64)

    sB = SIMPLESolver3D(Lx=L_DOM, Ly=H_DOM, Lz=LZ, Nx=NX, Ny=NY, Nz=NZ,
                       rho=rho_B0, mu=mu_B0, T_in=T_BIN, v_inlet=v_inlet_B,
                       eps=eps_A, K_arr=K_B, cF_arr=cF_B,
                       P_ref_abs=P_INB - 1.0, fluid_type='incompressible')
    sB.dx = dx.copy(); sB.dy = dy.copy(); sB.dz = dz.copy()
    sB.inlet_frac = in_mask_B
    sB.outlet_frac = out_mask_B
    print("Solving SIMPLE B …")
    t0 = time.perf_counter()
    sB.solve(max_iter=2000, tol=1e-3, verbose=False)
    print(f"  {time.perf_counter()-t0:.1f}s")

    # ── Cell-centre velocities (real coords) ──
    # Air
    vA_cc = 0.5*(sA.v[:,:-1,:] + sA.v[:,1:,:])
    u_A_field = vA_cc.transpose(1, 0, 2).copy()    # (NX, NY, NZ) — streamwise
    u_mag_A = np.abs(u_A_field)

    # Water
    vB_cc = 0.5*(sB.v[:,:-1,:] + sB.v[:,1:,:])     # (NX, NY, NZ)
    uB_cc = 0.5*(sB.u[:-1,:,:] + sB.u[1:,:,:])
    wB_cc = 0.5*(sB.w[:,:,:-1] + sB.w[:,:,1:])
    v_B_real = -vB_cc[:, ::-1, :].copy()            # flip for -y
    u_B_real = uB_cc[:, ::-1, :].copy()
    w_B_real = wB_cc[:, ::-1, :].copy()
    u_mag_B = np.sqrt(u_B_real**2 + v_B_real**2 + w_B_real**2)
    mass_flux_B = sB.rho_field.mean() * u_mag_B    # incompressible ρ const

    # ── Quantile/stats report ──
    log = []
    p = lambda s: (print(s, flush=True), log.append(s))
    p("\n## Air velocity (u_A magnitude)")
    p(f"  min/max: {u_mag_A.min():.4f} / {u_mag_A.max():.4f} m/s")
    p(f"  mean: {u_mag_A.mean():.4f} m/s   span = {u_mag_A.max()-u_mag_A.min():.4f}")
    p(f"  std / mean: {u_mag_A.std()/u_mag_A.mean()*100:.2f}%  (low = plug)")
    p(f"  quantiles: p10={np.percentile(u_mag_A, 10):.4f}  p50={np.percentile(u_mag_A, 50):.4f}  p90={np.percentile(u_mag_A, 90):.4f}")

    p("\n## Water |u| total (magnitude)")
    p(f"  min/max: {u_mag_B.min():.6f} / {u_mag_B.max():.6f} m/s")
    p(f"  mean: {u_mag_B.mean():.6f} m/s")
    p(f"  std / mean: {u_mag_B.std()/(u_mag_B.mean()+1e-30)*100:.2f}%")
    p(f"  quantiles: p10={np.percentile(u_mag_B, 10):.6f}  p50={np.percentile(u_mag_B, 50):.6f}  p90={np.percentile(u_mag_B, 90):.6f}")

    # "Active flow region" = cells with |u_B| > 10% of max
    threshold = 0.10 * u_mag_B.max()
    active = u_mag_B > threshold
    p(f"\n## Active flow fraction (|u_B| > 10% max)")
    p(f"  active cells: {int(active.sum())} / {active.size}  ({100*active.mean():.1f}%)")
    p(f"  → expected ~ 20-40% for diagonal cross-flow topology")
    p(f"  → if much higher: Brinkman over-homogenising water across whole domain")

    # Threshold sweep — distinguish Brinkman over-smoothing vs genuine spread.
    # Healthy diagonal cross-flow expected:
    #   >5% max → 70-90% active, >30% max → 30-50%, >50% max → 20-30%.
    p("\n## Active fraction vs threshold sweep")
    sweep_rows = []
    for thr_pct in [5, 10, 20, 30, 50]:
        thr = thr_pct * 0.01 * u_mag_B.max()
        frac = float((u_mag_B > thr).mean()) * 100
        p(f"  |u_B| > {thr_pct:2d}% max: {frac:5.1f}% cells")
        sweep_rows.append((thr_pct, frac))
    # Quick verdict
    f30 = next(f for t, f in sweep_rows if t == 30)
    if f30 > 60:
        p(f"  ⚠ {f30:.1f}% > 60% at 30%-thr — Brinkman over-homogenising")
    elif f30 < 25:
        p(f"  ⚠ {f30:.1f}% < 25% at 30%-thr — under-resolved or wrong topology")
    else:
        p(f"  ✓ {f30:.1f}% in [25, 60]% at 30%-thr — healthy diagonal cross-flow")

    # Mass conservation check
    A_face_inlet  = H_DOM * LZ                       # B inlet area (full top face, masked)
    A_open_inlet  = float(in_mask_B.sum() / in_mask_B.size) * A_face_inlet
    m_dot_target  = rho_B0 * U_B * A_open_inlet
    m_dot_actual_top = float(np.sum(sB.v[:, -1, :] * sB.rho_field[:, -1, :]
                                    * (sB.dx[:, None] * sB.dz[None, :])
                                    * in_mask_B))
    p(f"\n## Water mass flow consistency")
    p(f"  target m_dot (geometric inlet)  = {m_dot_target:.5f} kg/s")
    p(f"  actual top-face inlet (masked)  = {m_dot_actual_top:.5f} kg/s")

    # ── Plots ──
    k_mid = NZ // 2
    print(f"\nPlot slices at k=mid-z ({k_mid})")

    fig, axes = plt.subplots(1, 2, figsize=(14, 4), constrained_layout=True)
    im0 = axes[0].imshow(u_mag_A[:, :, k_mid].T, origin='lower', aspect='auto',
                          cmap='viridis', extent=[0, L_DOM*1e3, 0, H_DOM*1e3])
    axes[0].set_title(f'Air |u_A| at mid-z (k={k_mid})')
    axes[0].set_xlabel('X [mm]  (air →)'); axes[0].set_ylabel('Y [mm]')
    plt.colorbar(im0, ax=axes[0], label='|u_A| [m/s]')

    im1 = axes[1].imshow(u_mag_B[:, :, k_mid].T, origin='lower', aspect='auto',
                          cmap='plasma', extent=[0, L_DOM*1e3, 0, H_DOM*1e3])
    axes[1].set_title(f'Water |u_B| at mid-z (k={k_mid})')
    axes[1].set_xlabel('X [mm]'); axes[1].set_ylabel('Y [mm]  (water ↓)')
    # Annotate inlet / outlet
    axes[1].axhline(y=H_DOM*1e3, xmin=(B_IN_CTR-B_IN_W/2)/L_DOM,
                     xmax=(B_IN_CTR+B_IN_W/2)/L_DOM, color='cyan', lw=4, label='IN')
    axes[1].axhline(y=0,         xmin=(B_OUT_CTR-B_OUT_W/2)/L_DOM,
                     xmax=(B_OUT_CTR+B_OUT_W/2)/L_DOM, color='red',  lw=4, label='OUT')
    axes[1].legend(loc='upper left', fontsize=8)
    plt.colorbar(im1, ax=axes[1], label='|u_B| [m/s]')

    out = OUT_DIR / "flow_air_water_mid_z.png"
    fig.savefig(out, dpi=140); plt.close(fig)
    print(f"  wrote {out}")

    # Water at multiple z slices to see depth uniformity
    fig, axes = plt.subplots(1, NZ, figsize=(3*NZ, 4), constrained_layout=True)
    vmin, vmax = u_mag_B.min(), u_mag_B.max()
    for k in range(NZ):
        im = axes[k].imshow(u_mag_B[:, :, k].T, origin='lower', aspect='auto',
                             cmap='plasma', extent=[0, L_DOM*1e3, 0, H_DOM*1e3],
                             vmin=vmin, vmax=vmax)
        axes[k].set_title(f'k={k}')
        if k == 0:
            axes[k].set_ylabel('Y [mm]')
        axes[k].set_xlabel('X [mm]')
    fig.suptitle('Water |u_B| at each z-layer (depth variation)', fontsize=12)
    plt.colorbar(im, ax=axes[-1], label='|u_B| [m/s]', shrink=0.7)
    out = OUT_DIR / "flow_water_all_z.png"
    fig.savefig(out, dpi=120); plt.close(fig)
    print(f"  wrote {out}")

    with open(OUT_DIR / "flow_quantile_report.md", 'w', encoding='utf-8') as f:
        f.write("\n".join(log))
    print(f"\nDone. wall = {time.perf_counter()-t0_total:.1f}s")


if __name__ == '__main__':
    main()
