"""Shanghai case 1 partial-B inlet — compare ghost-heating bug fix.

⚠ ARCHIVAL: 2026-05-14 historical diagnostic snapshot. The issues this
   investigated (ε double-halving / partial-B ghost / mass-flow) have
   since been fixed (commits 02f091c / 2026-05-14 closure default 'none'
   / d80fbb1). Kept for reference; not for routine CI runs.

Two runs at identical config:
  A. partial_B_closure='none'           (current UI default, ghost-heated)
  B. partial_B_closure='per_cell_chi_b' (fix, ghost cells zero out h_vB+K_ffB)

Dumps T_B at z=10mm slice (matches UI 3D View screenshot) for both, plus
quantitative report.

Outputs:
  D:/Postgraduate/vault/reports/3d-solver/2026-05-14-shanghai-3d-n20-case1-fields/
    partial_b_TB_none.png
    partial_b_TB_perCellChiB.png
    partial_b_compare.png
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
    air_density, air_viscosity, air_cp, air_conductivity,
    water_density, water_viscosity, water_cp, water_conductivity,
)
from solvers.simple_solver_3d import SIMPLESolver3D
from solvers.ltne_energy_3d import solve_full_domain_3d
from df_surrogate.predict import predict_K_cF

R_AIR = 287.05

# Shanghai case 1
NX, NY, NZ = 30, 20, 10
L_DOM = 0.182; H_DOM = 0.042; LZ = 0.042
T_AIN = 126.0327 + 273.15
T_BIN = 18.1274 + 273.15
U_A = 3.91617
U_B = 0.01658
P_INA = 101325.0; P_INB = 101325.0
TPMS = 'Gyroid'; L_CELL = 7.0; T_WALL = 0.6; K_S = 16.0

# Partial-B inlet geometry (Shanghai)
B_IN_CTR = 0.154   # m
B_IN_W   = 0.042   # m  (so x ∈ [0.133, 0.175])
B_OUT_CTR = 0.028  # m
B_OUT_W   = 0.042  # m  (so x ∈ [0.007, 0.049])

OUT_DIR = Path(r"D:/Postgraduate/vault/reports/3d-solver/2026-05-14-shanghai-3d-n20-case1-fields")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _build_partial_B_masks(Nx, Nz, dx, dz):
    """Return (in_mask, out_mask) 2D (Nx, Nz) arrays in [0, 1].

    Inlet at y=H spans x ∈ [B_IN_CTR - B_IN_W/2, B_IN_CTR + B_IN_W/2].
    Outlet at y=0 spans x ∈ [B_OUT_CTR - B_OUT_W/2, B_OUT_CTR + B_OUT_W/2].
    Full Z width (partial only in x).
    """
    x_centres = (np.arange(Nx) + 0.5) * (L_DOM / Nx)
    in_lo  = B_IN_CTR - B_IN_W / 2
    in_hi  = B_IN_CTR + B_IN_W / 2
    out_lo = B_OUT_CTR - B_OUT_W / 2
    out_hi = B_OUT_CTR + B_OUT_W / 2
    in_x  = ((x_centres >= in_lo)  & (x_centres <= in_hi)).astype(np.float64)
    out_x = ((x_centres >= out_lo) & (x_centres <= out_hi)).astype(np.float64)
    in_mask  = np.broadcast_to(in_x[:, None],  (Nx, Nz)).copy()
    out_mask = np.broadcast_to(out_x[:, None], (Nx, Nz)).copy()
    return in_mask, out_mask


def _build_chi_B_simple(u_field, v_field, w_field, rho_field,
                          dx_arr, dy_arr, dz_arr,
                          threshold_frac=0.05):
    """Compute per-cell chi_B from mass flux throughput.

    Threshold = threshold_frac × p75(throughput in non-zero cells).
    """
    Nx, Ny, Nz = rho_field.shape
    Ax = dy_arr[None, :, None] * dz_arr[None, None, :]
    Ay = dx_arr[:, None, None] * dz_arr[None, None, :]
    Az = dx_arr[:, None, None] * dy_arr[None, :, None]
    Ax = np.broadcast_to(Ax, rho_field.shape)
    Ay = np.broadcast_to(Ay, rho_field.shape)
    Az = np.broadcast_to(Az, rho_field.shape)

    # Face mass fluxes (per cell)
    flux_w = np.abs(rho_field * u_field[:-1, :, :]) * Ax
    flux_e = np.abs(rho_field * u_field[1:, :, :])  * Ax
    flux_s = np.abs(rho_field * v_field[:, :-1, :]) * Ay
    flux_n = np.abs(rho_field * v_field[:, 1:, :])  * Ay
    flux_b = np.abs(rho_field * w_field[:, :, :-1]) * Az
    flux_t = np.abs(rho_field * w_field[:, :, 1:])  * Az
    throughput = np.maximum.reduce([flux_w, flux_e, flux_s, flux_n, flux_b, flux_t])

    nonzero = throughput[throughput > 0]
    ref = np.percentile(nonzero, 75) if len(nonzero) > 0 else 1.0
    threshold = threshold_frac * ref
    chi = (throughput > threshold).astype(np.float64)
    return chi, throughput


def main():
    print(f"# Shanghai case 1 partial-B closure comparison")
    print(f"Grid {NX}×{NY}×{NZ}, domain {L_DOM*1e3:.0f}×{H_DOM*1e3:.0f}×{LZ*1e3:.0f} mm")
    print(f"Water inlet x∈[{(B_IN_CTR-B_IN_W/2)*1e3:.0f}, {(B_IN_CTR+B_IN_W/2)*1e3:.0f}] mm at y=H")
    print(f"Water outlet x∈[{(B_OUT_CTR-B_OUT_W/2)*1e3:.0f}, {(B_OUT_CTR+B_OUT_W/2)*1e3:.0f}] mm at y=0")

    g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
    eps = g['epsilon']; eps_A = g['epsilon_A']; D_h = g['D_h']; A_0 = g['A_0']
    K_val, cF_val = predict_K_cF(TPMS, L_CELL, T_WALL, eps_A)

    rho_A0 = float(air_density(T_AIN, P_INA)); mu_A0 = float(air_viscosity(T_AIN)); cp_A0 = float(air_cp(T_AIN))
    rho_B0 = float(water_density(T_BIN)); mu_B0 = float(water_viscosity(T_BIN)); cp_B0 = float(water_cp(T_BIN))
    k_fA = float(air_conductivity(T_AIN))
    k_fB = float(water_conductivity(T_BIN))

    dx_arr = np.full(NX, L_DOM/NX); dy_arr = np.full(NY, H_DOM/NY); dz_arr = np.full(NZ, LZ/NZ)

    # ── SIMPLE A: full-width air, +x ──
    K_A_solver = np.full((NX, NZ), K_val); cF_A_solver = np.full((NX, NZ), cF_val)
    G_A = rho_A0 * U_A
    C_A = mu_A0 * G_A / K_val + cF_val * G_A * G_A
    P_ref_A = float(np.sqrt(max(P_INA**2 - 2.0*R_AIR*T_AIN*C_A*L_DOM, 1e4)))
    sA = SIMPLESolver3D(Lx=H_DOM, Ly=L_DOM, Lz=LZ, Nx=NY, Ny=NX, Nz=NZ,
                        rho=rho_A0, mu=mu_A0, T_in=T_AIN, v_inlet=U_A,
                        eps=eps_A, K_arr=K_A_solver, cF_arr=cF_A_solver,
                        P_ref_abs=P_ref_A, fluid_type='ideal_gas')
    sA.dx = dy_arr.copy(); sA.dy = dx_arr.copy(); sA.dz = dz_arr.copy()
    print("\nSolving SIMPLE A …", flush=True)
    sA.solve(max_iter=800, tol=1e-2, verbose=False)

    # ── SIMPLE B: partial-B inlet, -y direction ──
    # sB axes: Nx_solver=NX (real x), Ny_solver=NY (real y streamwise), Nz_solver=NZ
    K_B_solver = np.full((NY, NZ), K_val); cF_B_solver = np.full((NY, NZ), cF_val)
    in_mask_B, out_mask_B = _build_partial_B_masks(NX, NZ, dx_arr, dz_arr)
    # v_inlet only on inlet mask
    v_inlet_B = np.where(in_mask_B > 0.5, U_B, 0.0).astype(np.float64)

    sB = SIMPLESolver3D(Lx=L_DOM, Ly=H_DOM, Lz=LZ, Nx=NX, Ny=NY, Nz=NZ,
                        rho=rho_B0, mu=mu_B0, T_in=T_BIN, v_inlet=v_inlet_B,
                        eps=eps_A, K_arr=K_B_solver, cF_arr=cF_B_solver,
                        P_ref_abs=P_INB - 1.0, fluid_type='incompressible')
    sB.dx = dx_arr.copy(); sB.dy = dy_arr.copy(); sB.dz = dz_arr.copy()
    sB.inlet_frac = in_mask_B
    sB.outlet_frac = out_mask_B
    print("Solving SIMPLE B (partial inlet/outlet) …", flush=True)
    sB.solve(max_iter=800, tol=1e-2, verbose=False)

    # Cell-centre velocities
    vA_cc = 0.5*(sA.v[:,:-1,:] + sA.v[:,1:,:])
    ucA = vA_cc.transpose(1,0,2).copy(); vcA = np.zeros_like(ucA); wcA = np.zeros_like(ucA)
    vB_cc = 0.5*(sB.v[:,:-1,:] + sB.v[:,1:,:])
    vcB_real = -vB_cc[:,::-1,:].copy(); ucB = np.zeros_like(vcB_real); wcB = np.zeros_like(vcB_real)

    # LTNE arrays
    h_vA = 1.56e4; h_vB = 2.77e5
    h_vA_arr = np.full((NX,NY,NZ), h_vA); h_vB_arr = np.full((NX,NY,NZ), h_vB)
    eps_kernel = np.full((NX,NY,NZ), eps)  # 2026-05-19: FULL ε; kernel halves once (Option A)
    rcp_A = np.full((NX,NY,NZ), rho_A0*cp_A0); rcp_B = np.full((NX,NY,NZ), rho_B0*cp_B0)
    K_ffA = np.full((NX,NY,NZ), eps_A*k_fA); K_ffB = np.full((NX,NY,NZ), eps_A*k_fB)
    K_ss = np.full((NX,NY,NZ), (1-eps)*K_S)

    # Inlet masks for LTNE (3D coords)
    # in_mask_B (Nx, Nz) → expand to 2D cross-section in LTNE convention
    # For dir_B=3 (-y), inlet at j=Ny-1 (top); LTNE uses this mask as cross-section
    inlet_mask_B = in_mask_B  # (Nx, Nz)

    # Build chi_B from SIMPLE B mass flux (real coords)
    chi_B_real, throughput = _build_chi_B_simple(
        sB.u, sB.v, sB.w, sB.rho_field,
        sB.dx, sB.dy, sB.dz,
        threshold_frac=0.05,
    )
    # Dilate chi_B by 1 cell (matches production)
    chi_B_dilated = chi_B_real.copy()
    for ax in (0, 1, 2):
        chi_B_dilated = np.maximum(chi_B_dilated,
                                     np.roll(chi_B_real, 1, axis=ax))
        chi_B_dilated = np.maximum(chi_B_dilated,
                                     np.roll(chi_B_real, -1, axis=ax))
    chi_B = chi_B_dilated

    print(f"\nχ_B coverage: {100*chi_B.mean():.1f}% cells active ({int(chi_B.sum())} of {chi_B.size})")

    # ── Run two LTNE cases ──
    results = {}
    for tag, chi_input in [("none", None), ("per_cell_chi_b", chi_B)]:
        print(f"\n--- LTNE with partial_B_closure={tag!r} ---", flush=True)
        Ta = Tb = Ts = None
        t0 = time.perf_counter()
        for outer in range(2):
            Ta, Tb, Ts = solve_full_domain_3d(
                L_DOM, H_DOM, LZ, NX, NY, NZ, T_AIN, T_BIN,
                K_ffA, K_ffB, K_ss, h_vA_arr, h_vB_arr,
                rcp_A, rcp_B, eps_kernel,
                ucA, vcA, wcA, ucB, vcB_real, wcB,
                0, 3,
                inlet_mask_B=inlet_mask_B,
                chi_B_field=chi_input,
                chi_B_kernel_threshold=0.3 if chi_input is not None else 0.0,
                dx_arr=dx_arr, dy_arr=dy_arr, dz_arr=dz_arr,
                max_iter=1500, tol=0.5, alpha_T=0.7,
                Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
            )
            # Compressibility outer for sA
            Ta_sA = Ta.transpose(1,0,2).copy()
            sA.update_T_field(Ta_sA)
            sA.solve(max_iter=300, tol=1e-2, verbose=False)
            rcp_A = 0.6 * air_density(Ta, P_INA) * air_cp(Ta) + 0.4 * rcp_A
        print(f"  wall = {time.perf_counter()-t0:.1f}s")
        print(f"  Tb range: [{Tb.min()-273.15:.1f}, {Tb.max()-273.15:.1f}] °C  span={Tb.max()-Tb.min():.1f} K")
        print(f"  Ts range: [{Ts.min()-273.15:.1f}, {Ts.max()-273.15:.1f}] °C")
        print(f"  Tb mean: {Tb.mean()-273.15:.1f}°C")
        print(f"  Q_sA = {float(np.sum(h_vA_arr * (Ts-Ta) * dx_arr[:,None,None]*dy_arr[None,:,None]*dz_arr[None,None,:])):.1f} W")
        results[tag] = (Ta.copy(), Tb.copy(), Ts.copy())

    # ── Plot T_B at z=10mm slice (matches UI screenshot) ──
    z_target = 10e-3  # 10 mm
    z_centres = (np.arange(NZ) + 0.5) * (LZ / NZ)
    k_slice = int(np.argmin(np.abs(z_centres - z_target)))
    print(f"\nSlicing z={z_centres[k_slice]*1e3:.1f}mm (k={k_slice})")

    fig, axes = plt.subplots(1, 3, figsize=(18, 5), constrained_layout=True)
    Tb_none = results['none'][1][:, :, k_slice] - 273.15  # (Nx, Ny)
    Tb_chi  = results['per_cell_chi_b'][1][:, :, k_slice] - 273.15
    vmin = min(Tb_none.min(), Tb_chi.min())
    vmax = max(Tb_none.max(), Tb_chi.max())

    extent = [0, L_DOM*1e3, 0, H_DOM*1e3]
    im0 = axes[0].imshow(Tb_none.T, origin='lower', aspect='auto',
                          cmap='jet', extent=extent, vmin=vmin, vmax=vmax)
    axes[0].set_title("partial_B_closure='none' (current UI default, BUG)")
    axes[0].set_xlabel('X [mm]'); axes[0].set_ylabel('Y [mm]')
    plt.colorbar(im0, ax=axes[0], label='T_B [°C]')

    im1 = axes[1].imshow(Tb_chi.T, origin='lower', aspect='auto',
                          cmap='jet', extent=extent, vmin=vmin, vmax=vmax)
    axes[1].set_title("partial_B_closure='per_cell_chi_b' (FIX)")
    axes[1].set_xlabel('X [mm]'); axes[1].set_ylabel('Y [mm]')
    plt.colorbar(im1, ax=axes[1], label='T_B [°C]')

    # χ_B slice for reference
    im2 = axes[2].imshow(chi_B[:, :, k_slice].T, origin='lower', aspect='auto',
                          cmap='gray', extent=extent, vmin=0, vmax=1)
    axes[2].set_title('χ_B mask (1=active, 0=ghost)')
    axes[2].set_xlabel('X [mm]'); axes[2].set_ylabel('Y [mm]')
    plt.colorbar(im2, ax=axes[2], label='χ_B')

    fig.suptitle(f"Shanghai case 1 — T_B at z={z_centres[k_slice]*1e3:.0f}mm — partial-B ghost-heating audit",
                  fontsize=13)
    out = OUT_DIR / "partial_b_compare.png"
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"\nWrote {out}")

    # Quantitative report
    print(f"\n=== Summary ===")
    print(f"{'tag':<22} {'Tb_min':>8} {'Tb_max':>8} {'Tb_mean':>9} {'Tb_span':>9}")
    for tag, (_, Tb_r, _) in results.items():
        print(f"{tag:<22} {Tb_r.min()-273.15:>8.2f} {Tb_r.max()-273.15:>8.2f} {Tb_r.mean()-273.15:>9.2f} {Tb_r.max()-Tb_r.min():>9.2f}")


if __name__ == '__main__':
    main()
