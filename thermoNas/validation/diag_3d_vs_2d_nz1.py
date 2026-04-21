"""
diag_3d_vs_2d_nz1.py — diagnose 2D-3D numerical divergence

Setup: run ONE Shanghai-like case on:
  * SIMPLESolver (2D)       with (Nx_2d, Ny_2d)
  * SIMPLESolver3D (3D)     with (Nx_3d, Ny_3d, Nz=1)

Identical geometry / fluid / K-cF / BC. Should produce bitwise-same P/v/dP
since Nz=1 degenerates 3D to 2D math.

Outputs per-field diff norms + picks first divergence.
"""

from __future__ import annotations
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solvers.simple_solver import SIMPLESolver
from solvers.simple_solver_3d import SIMPLESolver3D
from solvers.tpms_calc import (
    geometry as tpms_geometry, air_density, air_viscosity, P_atm,
)
from df_fit.predict import predict_K_cF


def main():
    # ─── Setup: Shanghai Gyroid fluid A (mid-Re case 8 like) ───
    TPMS = 'Gyroid'; L_CELL = 7.0; T_WALL = 0.6; K_S = 16.0
    g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
    EPS = g['epsilon']; D_H = g['D_h']; R_H = D_H / 2

    H_DOM = 0.042      # real y-height (2D's W, 3D's Lx)
    L_DOM = 0.231      # real x-length (2D's H, 3D's Ly)

    # Small grid for quick diag
    Nx_cross = 14      # cross-stream (real y) resolution
    Ny_stream = 10     # streamwise (real x) resolution
    Nz = 1             # depth

    # Mid-Re operating point
    u_inlet = 20.0     # interstitial [m/s]
    T_in = 400.0       # [K]
    P_Ain = P_atm + 1e5
    rho_air = air_density(T_in, P_Ain)
    mu_air = air_viscosity(T_in)

    # D-F surrogate at Gyroid L=7 t=0.6
    K_pred, cF_pred = predict_K_cF(TPMS, L_CELL, T_WALL, EPS / 2.0)

    # P_ref_abs 1D closed-form seed
    G_A = rho_air * u_inlet
    C_est = mu_air * G_A / K_pred + cF_pred * G_A * G_A
    P_out_sq = P_Ain**2 - 2.0 * 287.05 * T_in * C_est * L_DOM
    P_ref_abs = float(np.sqrt(max(P_out_sq, 1e4)))

    print(f"Setup: {TPMS} L={L_CELL} t={T_WALL} eps={EPS:.4f}")
    print(f"  grid: cross={Nx_cross}, stream={Ny_stream}, z={Nz}")
    print(f"  u_inlet={u_inlet:.2f} m/s  rho={rho_air:.3f}  mu={mu_air:.3e}  T={T_in}K")
    print(f"  K={K_pred:.3e}  cF={cF_pred:.1f}  P_ref_abs={P_ref_abs:.0f}\n")

    # ─── 2D SIMPLESolver ───
    s2 = SIMPLESolver(
        H_DOM, L_DOM, Nx_cross, Ny_stream,
        TPMS, L_CELL, T_WALL, EPS, R_H,
        rho_air, mu_air, T_in,
        inlet_lo=0.0, inlet_hi=H_DOM, v_inlet=u_inlet,
        outlet_lo=0.0, outlet_hi=H_DOM,
        P_ref_abs=P_ref_abs,
        wall_refine=False)
    s2._K_arr[:] = K_pred
    s2._cF_arr[:] = cF_pred
    conv2, it2 = s2.solve(max_iter=3000, tol=1e-5, verbose=False)
    print(f"2D: conv={conv2}  iters={it2}  residual_last={s2.residuals[-1]:.3e}")

    # ─── 3D SIMPLESolver3D Nz=1 ───
    s3 = SIMPLESolver3D(
        Lx=H_DOM, Ly=L_DOM, Lz=0.02,
        Nx=Nx_cross, Ny=Ny_stream, Nz=Nz,
        rho=rho_air, mu=mu_air, T_in=T_in, v_inlet=u_inlet,
        eps=EPS,
        K_arr=np.full((Ny_stream, Nz), K_pred),
        cF_arr=np.full((Ny_stream, Nz), cF_pred),
        P_ref_abs=P_ref_abs,
        fluid_type='ideal_gas')
    conv3, it3 = s3.solve(max_iter=3000, tol=1e-5, verbose=False)
    print(f"3D Nz=1: conv={conv3}  iters={it3}  residual_last={s3.residuals[-1]:.3e}")

    # ─── Compare P field ───
    # 2D: s2.P shape (Nx_cross, Ny_stream)
    # 3D: s3.P shape (Nx_cross, Ny_stream, 1) → squeeze to (Nx_cross, Ny_stream)
    P2 = s2.P
    P3 = s3.P[..., 0]
    print(f"\nP field:")
    print(f"  2D  shape {P2.shape}  range [{P2.min():.2f}, {P2.max():.2f}]  "
          f"mean {P2.mean():.3f}")
    print(f"  3D  shape {P3.shape}  range [{P3.min():.2f}, {P3.max():.2f}]  "
          f"mean {P3.mean():.3f}")
    d_P = P3 - P2
    rel_dP = np.abs(d_P).max() / (np.abs(P2).max() + 1e-30)
    print(f"  |ΔP|_max = {np.abs(d_P).max():.3e}  rel = {rel_dP:.3e}")
    print(f"  |ΔP|_mean = {np.abs(d_P).mean():.3e}")

    # ─── Compare v field (streamwise) ───
    # 2D: s2.v shape (Nx, Ny+1)   ← streamwise in 2D = y-axis
    # 3D: s3.v shape (Nx, Ny+1, 1) → squeeze
    v2 = s2.v
    v3 = s3.v[..., 0]
    print(f"\nv field (streamwise):")
    print(f"  2D  shape {v2.shape}  range [{v2.min():.3f}, {v2.max():.3f}]  "
          f"mean {v2.mean():.3f}")
    print(f"  3D  shape {v3.shape}  range [{v3.min():.3f}, {v3.max():.3f}]  "
          f"mean {v3.mean():.3f}")
    d_v = v3 - v2
    print(f"  |Δv|_max = {np.abs(d_v).max():.3e}")
    print(f"  |Δv|_mean = {np.abs(d_v).mean():.3e}")

    # ─── Compare u field (cross-stream) ───
    u2 = s2.u
    u3 = s3.u[..., 0]
    print(f"\nu field (cross-stream):")
    print(f"  2D  shape {u2.shape}  |u|_max = {np.abs(u2).max():.3e}")
    print(f"  3D  shape {u3.shape}  |u|_max = {np.abs(u3).max():.3e}")
    d_u = u3 - u2
    print(f"  |Δu|_max = {np.abs(d_u).max():.3e}")

    # ─── dP comparison ───
    from solvers.df_projection import extract_dP_from_simple
    dP_2d = extract_dP_from_simple(s2)
    dP_3d = SIMPLESolver3D.extract_dP_weighted(s3)
    dP_3d_simple_mean = float(s3.P[:, 0, :].mean() - s3.P[:, -1, :].mean())
    print(f"\ndP extraction:")
    print(f"  2D pipe-weighted: {dP_2d:.2f} Pa")
    print(f"  3D pipe-weighted: {dP_3d:.2f} Pa")
    print(f"  3D simple mean:   {dP_3d_simple_mean:.2f} Pa")
    print(f"  Δ(3D - 2D) weighted: {dP_3d - dP_2d:.2f} Pa  rel {(dP_3d - dP_2d)/abs(dP_2d)*100:+.2f}%")

    # ─── Mass flow comparison ───
    # 2D: sum rho * v_inlet * dx at j=0
    # 3D: sum rho * v_inlet * dx * dz at k=0
    dx_2d = s2.dx_arr; dy_2d = s2.dy_arr
    dx_3d = s3.dx; dy_3d = s3.dy; dz_3d = s3.dz
    print(f"\nGrid 1D:")
    print(f"  2D dx len={len(dx_2d)} sum={dx_2d.sum():.5f}  dy len={len(dy_2d)} sum={dy_2d.sum():.5f}")
    print(f"  3D dx len={len(dx_3d)} sum={dx_3d.sum():.5f}  dy len={len(dy_3d)} sum={dy_3d.sum():.5f}  dz len={len(dz_3d)} sum={dz_3d.sum():.5f}")

    m_2d_in = np.sum(s2.rho_field[:, 0] * s2.v[:, 0] * dx_2d)
    m_2d_out = np.sum(s2.rho_field[:, -1] * s2.v[:, -1] * dx_2d)
    m_3d_in = np.sum(s3.rho_field[:, 0, 0] * s3.v[:, 0, 0] * dx_3d * dz_3d[0])
    m_3d_out = np.sum(s3.rho_field[:, -1, 0] * s3.v[:, -1, 0] * dx_3d * dz_3d[0])
    print(f"\nMass flow (per unit depth in 2D, full Lz in 3D):")
    print(f"  2D m_in={m_2d_in:.4e}  m_out={m_2d_out:.4e}  rel={abs(m_2d_in-m_2d_out)/abs(m_2d_in):.2e}")
    print(f"  3D m_in={m_3d_in:.4e}  m_out={m_3d_out:.4e}  rel={abs(m_3d_in-m_3d_out)/abs(m_3d_in):.2e}")
    print(f"  ratio 3D/2D at inlet: {m_3d_in/(m_2d_in*dz_3d[0]):.4f}  (should=1.0 if bitwise match)")

    # ─── outlet_frac / wall_out inspection ───
    print(f"\nBC inspection:")
    print(f"  2D outlet_frac: min={s2.outlet_frac.min():.3f}  max={s2.outlet_frac.max():.3f}")
    print(f"  2D inlet_frac:  min={s2.inlet_frac.min():.3f}  max={s2.inlet_frac.max():.3f}")
    print(f"  3D outlet_frac: min={s3.outlet_frac.min():.3f}  max={s3.outlet_frac.max():.3f}")
    print(f"  3D inlet_frac:  min={s3.inlet_frac.min():.3f}  max={s3.inlet_frac.max():.3f}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
