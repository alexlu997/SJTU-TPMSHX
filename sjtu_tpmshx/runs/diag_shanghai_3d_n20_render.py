"""Re-run Shanghai case 1 3D and produce pyvista volume + isosurface
renderings of Ta (air), Tb (water), and Ts (solid).

Outputs PNGs to vault/reports/3d-solver/2026-05-14-shanghai-3d-n20-case1-fields/
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pyvista as pv

_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT))

# Re-import the same setup machinery
from runs.diag_shanghai_3d_n20_case1 import (
    NX, NY, NZ, L_DOM, H_DOM, LZ, T_AIN, T_BIN,
    DIR_A, DIR_B, U_A, U_B, P_INA, P_INB,
    TPMS, L_CELL, T_WALL, K_S, OUT_DIR, R_AIR,
)
from solvers.tpms_calc import (
    geometry as tpms_geometry,
    air_density, air_viscosity, air_cp,
    water_density, water_viscosity, water_cp, water_conductivity,
)
from solvers.simple_solver_3d import SIMPLESolver3D
from solvers.solve_full_3d import solve_full_domain_3d
from df_fit.predict import predict_K_cF


def _rerun_solve():
    """Re-run the SIMPLE + LTNE pipeline. Returns (Ta, Tb, Ts) in (Nx,Ny,Nz).

    Duplicates diag_shanghai_3d_n20_case1.main field-building so we don't have
    to refactor it into a return. Cheap (~15 s) and avoids touching the
    diag module.
    """
    g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
    eps = g['epsilon']; eps_A = g['epsilon_A']; D_h = g['D_h']; A_0 = g['A_0']
    K_val, cF_val = predict_K_cF(TPMS, L_CELL, T_WALL, eps_A)

    rho_A0 = float(air_density(T_AIN, P_INA))
    mu_A0  = float(air_viscosity(T_AIN))
    cp_A0  = float(air_cp(T_AIN))
    rho_B0 = float(water_density(T_BIN))
    mu_B0  = float(water_viscosity(T_BIN))
    cp_B0  = float(water_cp(T_BIN))
    k_fB   = float(water_conductivity(T_BIN))

    K_A_solver = np.full((NX, NZ), K_val); cF_A_solver = np.full((NX, NZ), cF_val)
    K_B_solver = K_A_solver.copy(); cF_B_solver = cF_A_solver.copy()

    G_A = rho_A0 * U_A
    C_A = mu_A0 * G_A / K_val + cF_val * G_A * G_A
    P_out_sq_A = P_INA**2 - 2.0 * R_AIR * T_AIN * C_A * L_DOM
    P_ref_A = float(np.sqrt(max(P_out_sq_A, 1.0e4)))

    sA = SIMPLESolver3D(
        Lx=H_DOM, Ly=L_DOM, Lz=LZ, Nx=NY, Ny=NX, Nz=NZ,
        rho=rho_A0, mu=mu_A0, T_in=T_AIN, v_inlet=U_A,
        eps=eps, K_arr=K_A_solver, cF_arr=cF_A_solver, P_ref_abs=P_ref_A,
    )
    dx_arr = np.full(NX, L_DOM / NX); dy_arr = np.full(NY, H_DOM / NY)
    dz_arr = np.full(NZ, LZ / NZ)
    sA.dx = dy_arr.copy(); sA.dy = dx_arr.copy(); sA.dz = dz_arr.copy()

    sB = SIMPLESolver3D(
        Lx=L_DOM, Ly=H_DOM, Lz=LZ, Nx=NX, Ny=NY, Nz=NZ,
        rho=rho_B0, mu=mu_B0, T_in=T_BIN, v_inlet=U_B,
        eps=eps, K_arr=K_B_solver, cF_arr=cF_B_solver,
        P_ref_abs=P_INB - 1.0, fluid_type='incompressible',
    )
    sB.dx = dx_arr.copy(); sB.dy = dy_arr.copy(); sB.dz = dz_arr.copy()

    print("Solving SIMPLE A …", flush=True); t0 = time.perf_counter()
    sA.solve(max_iter=800, tol=1e-2, verbose=False)
    print(f"  {time.perf_counter()-t0:.1f}s")
    print("Solving SIMPLE B …", flush=True); t0 = time.perf_counter()
    sB.solve(max_iter=800, tol=1e-2, verbose=False)
    print(f"  {time.perf_counter()-t0:.1f}s")

    # Real-coord velocity maps
    vA_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])
    ucA_real = vA_cc.transpose(1, 0, 2).copy()
    vcA_real = np.zeros_like(ucA_real); wcA_real = np.zeros_like(ucA_real)
    vB_cc = 0.5 * (sB.v[:, :-1, :] + sB.v[:, 1:, :])
    vcB_real = -vB_cc[:, ::-1, :].copy()
    ucB_real = np.zeros_like(vcB_real); wcB_real = np.zeros_like(vcB_real)

    h_vA = 1.56e4; h_vB = 2.77e5  # match diag_*case1 simple Nu values
    h_vA_arr = np.full((NX, NY, NZ), h_vA); h_vB_arr = np.full((NX, NY, NZ), h_vB)
    eps_arr = np.full((NX, NY, NZ), eps)  # 2026-05-19: FULL ε; kernel halves once (Option A)
    rcp_A = np.full((NX, NY, NZ), rho_A0 * cp_A0)
    rcp_B = np.full((NX, NY, NZ), rho_B0 * cp_B0)
    K_ffA = np.full((NX, NY, NZ), eps_A * 0.034)
    K_ffB = np.full((NX, NY, NZ), eps_A * k_fB)
    K_ss  = np.full((NX, NY, NZ), (1 - eps) * K_S)

    print("Solving LTNE + compressible outer loop …", flush=True); t0 = time.perf_counter()
    Ta = Tb = Ts = None
    for it in range(4):
        # Re-derive cell-center velocities from current SIMPLE state
        vA_cc_loop = 0.5*(sA.v[:,:-1,:] + sA.v[:,1:,:])
        ucA_real_loop = vA_cc_loop.transpose(1,0,2).copy()
        vcA_real_loop = np.zeros_like(ucA_real_loop)
        wcA_real_loop = np.zeros_like(ucA_real_loop)
        Ta, Tb, Ts = solve_full_domain_3d(
            L_DOM, H_DOM, LZ, NX, NY, NZ, T_AIN, T_BIN,
            K_ffA, K_ffB, K_ss, h_vA_arr, h_vB_arr, rcp_A, rcp_B, eps_arr,
            ucA_real_loop, vcA_real_loop, wcA_real_loop,
            ucB_real, vcB_real, wcB_real,
            DIR_A, DIR_B,
            dx_arr=dx_arr, dy_arr=dy_arr, dz_arr=dz_arr,
            max_iter=1500, tol=0.5, alpha_T=0.7,
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
        )
        # 2026-05-14: propagate Ta into SIMPLE T_field so compressibility
        # couples T → ρ → u along x. Without this, u stays plug.
        Ta_sA = Ta.transpose(1,0,2).copy()
        sA.update_T_field(Ta_sA)
        sA.solve(max_iter=300, tol=1e-2, verbose=False)
        # Update rcp from current T
        rcp_A = 0.6 * air_density(Ta, P_INA) * air_cp(Ta) + 0.4 * rcp_A
    print(f"  {time.perf_counter()-t0:.1f}s")
    return Ta, Tb, Ts, sA, sB


def _make_grid():
    """Build pyvista StructuredGrid for Nx*Ny*Nz cell centres."""
    xc = np.linspace(L_DOM / (2 * NX), L_DOM - L_DOM / (2 * NX), NX) * 1e3
    yc = np.linspace(H_DOM / (2 * NY), H_DOM - H_DOM / (2 * NY), NY) * 1e3
    zc = np.linspace(LZ    / (2 * NZ), LZ    - LZ    / (2 * NZ), NZ) * 1e3
    X, Y, Z = np.meshgrid(xc, yc, zc, indexing='ij')
    grid = pv.StructuredGrid(X, Y, Z)
    return grid, xc, yc, zc


def _render(grid, scalar_3d_C, title, cmap, fname,
             contour_n=8, clip_axes=('x',)):
    """Render volume slices + isosurfaces and save PNG."""
    grid_local = grid.copy()
    grid_local["T"] = scalar_3d_C.flatten(order='F')  # pv flat F-order for StructuredGrid

    p = pv.Plotter(off_screen=True, window_size=(1200, 900))
    p.set_background("white")

    # Three orthogonal slices through domain centre
    centre = grid_local.center
    slices = grid_local.slice_orthogonal(x=centre[0], y=centre[1], z=centre[2])
    p.add_mesh(slices, cmap=cmap, scalars="T",
               scalar_bar_args={"title": f"{title} [°C]",
                                "label_font_size": 14,
                                "title_font_size": 16})

    # Isosurfaces (transparent)
    Tmin = float(np.min(scalar_3d_C)); Tmax = float(np.max(scalar_3d_C))
    levels = np.linspace(Tmin + 0.05*(Tmax-Tmin), Tmax - 0.05*(Tmax-Tmin), contour_n)
    iso = grid_local.contour(isosurfaces=levels.tolist(), scalars="T")
    if iso.n_points > 0:
        p.add_mesh(iso, cmap=cmap, opacity=0.30, scalars="T",
                    show_scalar_bar=False)

    # Domain bounding box
    p.add_mesh(grid_local.outline(), color="black", line_width=1)
    p.add_axes(interactive=False)
    p.camera_position = [(L_DOM*1e3*1.6, -H_DOM*1e3*2.0, LZ*1e3*2.2),
                          (L_DOM*1e3*0.5, H_DOM*1e3*0.5, LZ*1e3*0.5),
                          (0, 0, 1)]
    p.show_bounds(xlabel='x [mm]', ylabel='y [mm]', zlabel='z [mm]',
                  font_size=12, location="outer", grid=False)
    p.add_text(title, position='upper_left', font_size=14, color='black')

    out = OUT_DIR / fname
    p.screenshot(str(out))
    p.close()
    print(f"  wrote {out}")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    Ta, Tb, Ts, sA, sB = _rerun_solve()
    grid, xc, yc, zc = _make_grid()

    Ta_C = Ta - 273.15
    Tb_C = Tb - 273.15
    Ts_C = Ts - 273.15

    # Cell-center velocity for air (real coords)
    vA_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])
    u_A_field = vA_cc.transpose(1, 0, 2).copy()  # (Nx, Ny, Nz)

    print("\nRendering …")
    _render(grid, Ta_C, "Air temperature  T_A",     "hot",    "render_T_A_air_3D.png")
    _render(grid, Tb_C, "Water temperature  T_B",   "cool",   "render_T_B_water_3D.png")
    _render(grid, Ts_C, "Solid temperature  T_s",   "copper", "render_T_solid_3D.png")
    _render(grid, u_A_field, "Air velocity  u_A",    "viridis", "render_u_A_air_3D.png")

    # T_A vs u_A side-by-side — for visual similarity check
    p = pv.Plotter(off_screen=True, window_size=(1400, 600), shape=(1, 2))
    for i, (field, title, cmap) in enumerate([
        (Ta_C,       "Air T_A (°C) — flows +x",   "hot"),
        (u_A_field,  "Air u_A (m/s) — flows +x",  "viridis"),
    ]):
        p.subplot(0, i)
        p.set_background("white")
        g = grid.copy(); g["v"] = field.flatten(order='F')
        slc = g.slice_orthogonal(x=g.center[0], y=g.center[1], z=g.center[2])
        p.add_mesh(slc, cmap=cmap, scalars="v",
                    scalar_bar_args={"title": title, "label_font_size": 10,
                                     "title_font_size": 12, "n_labels": 4})
        p.add_mesh(g.outline(), color="black", line_width=1)
        p.camera_position = [(L_DOM*1e3*1.6, -H_DOM*1e3*2.0, LZ*1e3*2.2),
                              (L_DOM*1e3*0.5, H_DOM*1e3*0.5, LZ*1e3*0.5),
                              (0, 0, 1)]
        p.add_axes(interactive=False)
    out = OUT_DIR / "render_T_vs_u_compare.png"
    p.screenshot(str(out))
    p.close()
    print(f"  wrote {out}")

    # Original 3-panel
    p = pv.Plotter(off_screen=True, window_size=(1400, 600), shape=(1, 3))
    for i, (T_C, title, cmap) in enumerate([
        (Ta_C, "Air T_A (°C) — flows +x",   "hot"),
        (Tb_C, "Water T_B (°C) — flows -y", "cool"),
        (Ts_C, "Solid T_s (°C)",            "copper"),
    ]):
        p.subplot(0, i)
        p.set_background("white")
        g = grid.copy(); g["T"] = T_C.flatten(order='F')
        slc = g.slice_orthogonal(x=g.center[0], y=g.center[1], z=g.center[2])
        p.add_mesh(slc, cmap=cmap, scalars="T",
                    scalar_bar_args={"title": title, "label_font_size": 10,
                                     "title_font_size": 12, "n_labels": 4})
        p.add_mesh(g.outline(), color="black", line_width=1)
        p.camera_position = [(L_DOM*1e3*1.6, -H_DOM*1e3*2.0, LZ*1e3*2.2),
                              (L_DOM*1e3*0.5, H_DOM*1e3*0.5, LZ*1e3*0.5),
                              (0, 0, 1)]
        p.add_axes(interactive=False)
    out = OUT_DIR / "render_combined_3panel.png"
    p.screenshot(str(out))
    p.close()
    print(f"  wrote {out}")

    # Quantitative report
    T_x = Ta.mean(axis=(1, 2))
    u_x = u_A_field.mean(axis=(1, 2))
    r = float(np.corrcoef(Ta.flatten(), u_A_field.flatten())[0, 1])
    print(f"\nQuantitative T vs u:")
    print(f"  T_A range: [{Ta.min()-273.15:.1f}, {Ta.max()-273.15:.1f}] °C  span = {Ta.max()-Ta.min():.1f} K")
    print(f"  u_A range: [{u_A_field.min():.3f}, {u_A_field.max():.3f}] m/s  span = {u_A_field.max()-u_A_field.min():.3f}")
    print(f"  Pearson r(T_A, u_A) full 3D: {r:.4f}")
    print(f"  Along x (avg yz): r = {np.corrcoef(T_x, u_x)[0,1]:.4f}")


if __name__ == '__main__':
    main()
