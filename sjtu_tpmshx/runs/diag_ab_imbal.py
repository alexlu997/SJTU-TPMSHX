"""diag_ab_imbal.py — 4-metric AB-imbal diagnostic for Shanghai brick (T_inB=342K).

Runs the GUI-default 3D air-air case (Shanghai 4.3:1:1 brick, 0.182×0.042×0.042 m)
with T_inB modified to 342 K (matching user's screenshot scenario), then
extracts four energy metrics that should all agree at ε-level if the LTNE
energy balance is closed:

    Q_A_enth   = m_dot_A · cp_A · (T_inA - T_OUT_A)        # mass-side, fluid A
    Q_B_enth   = m_dot_B · cp_B · (T_OUT_B - T_inB)        # mass-side, fluid B
    Q_sA       = Σ h_vA(Ts - Ta) · V_cell                   # solid → A coupling sum
    Q_sB       = Σ h_vB(Ts - Tb) · V_cell                   # solid → B coupling sum
    Q_sA_int   = Σ over interior cells only (skip x=0, x=Nx-1 BC slabs)
    Q_sB_int   = Σ over interior cells only (skip y=0, y=Ny-1 BC slabs)

Imbalance = |Q_A_enth - Q_B_enth| / max(Q_A_enth, Q_B_enth).

If Q_A_enth << Q_B_enth (current symptom), checks whether Q_sA_int ≈ Q_sB_int
(then BC-cell over/under-counting is the root cause) or whether Q_sA_int
also lags Q_sB_int (then h_v / coupling itself is asymmetric).
"""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solvers.tpms_calc import geometry as tpms_geometry, compute as tpms_compute
from pipelines.stages_3d import _run_3d_stack


def build_cfg():
    # B2 2.6: canonical template + this diag's GUI-screenshot deltas
    # (20x25x25 grid, t=0.6 mm, Ts seed 300 K, diagonal partial-B BC).
    from runs._case_template import build_cfg as _template_cfg
    return _template_cfg(
        Nx=20, Ny=25, Nz=25, t_wall=0.6, T_s_init=300.0,
        fluid_A_cfg=dict(dir=0, in_ctr=0.021, in_w=0.042,
                         out_ctr=0.021, out_w=0.042,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
        # User's screenshot: partial BC for B (diagonal pattern)
        # Inlet X 0.154 ± 0.021 (top right), Outlet X 0.028 ± 0.021 (bottom left)
        fluid_B_cfg=dict(dir=3,
                         in_ctr=0.154, in_w=0.042,
                         out_ctr=0.028, out_w=0.042,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
    )


def diag(res, cfg):
    Ta = res['Ta']; Tb = res['Tb']; Ts = res['Ts']
    Nx, Ny, Nz = Ta.shape
    dx = res['dx']; dy = res['dy']; dz = res['dz']

    Vol = (dx[:, None, None] * dy[None, :, None] * dz[None, None, :])  # (Nx,Ny,Nz)

    # h_v fields — recompute from Re using current rho, mu, u (interstitial)
    # Use per-cell h_v if solver exposes it; otherwise fall back to global Nu.
    h_vA = res.get('h_vA_field')
    h_vB = res.get('h_vB_field')
    if h_vA is None or h_vB is None:
        # Fallback: bulk h_v from tpms_calc.compute
        rA = tpms_compute(cfg['tpms_type'], cfg['Lcell'], cfg['t_wall'],
                          cfg['u_A'], cfg['T_inA'], cfg['P_inA'], cfg['k_s'])
        rB = tpms_compute(cfg['tpms_type'], cfg['Lcell'], cfg['t_wall'],
                          cfg['u_B'], cfg['T_inB'], cfg['P_inB'], cfg['k_s'])
        h_vA_scalar = rA['h_v']
        h_vB_scalar = rB['h_v']
        print(f"  [fallback] h_vA bulk = {h_vA_scalar:.2e} W/m³K  "
              f"h_vB bulk = {h_vB_scalar:.2e} W/m³K")
        h_vA = np.full_like(Ta, h_vA_scalar)
        h_vB = np.full_like(Ta, h_vB_scalar)
    else:
        print(f"  [field] h_vA range = [{h_vA.min():.2e}, {h_vA.max():.2e}]  "
              f"h_vB range = [{h_vB.min():.2e}, {h_vB.max():.2e}]")

    # Q solid → A (positive when Ts > Ta, heat transfers from solid to fluid A)
    Q_sA_per_cell = h_vA * (Ts - Ta) * Vol
    Q_sB_per_cell = h_vB * (Ts - Tb) * Vol

    Q_sA_total = float(Q_sA_per_cell.sum())
    Q_sB_total = float(Q_sB_per_cell.sum())

    # Interior excludes inlet/outlet BC slabs along each fluid's flow direction
    # A flows in +x (dir 0): BC at x=0 (inlet), x=Nx-1 (outlet)
    # B flows in -y (dir 3): BC at y=Ny-1 (inlet, top), y=0 (outlet, bottom)
    Q_sA_interior = float(Q_sA_per_cell[1:-1, :, :].sum())  # strip x=0, x=Nx-1
    Q_sB_interior = float(Q_sB_per_cell[:, 1:-1, :].sum())  # strip y=0, y=Ny-1
    Q_sA_BC = Q_sA_total - Q_sA_interior
    Q_sB_BC = Q_sB_total - Q_sB_interior

    Q_A_enth = float(res.get('Q_enthalpy_A', np.nan))
    Q_B_enth = float(res.get('Q_enthalpy_B', np.nan))
    Q_primary = float(res.get('Q', np.nan))

    print()
    print("=" * 72)
    print(" 4-METRIC AB-IMBAL DIAGNOSTIC — Shanghai brick, T_inB=342K")
    print("=" * 72)
    print(f"  T_inA            : {cfg['T_inA']:.2f} K")
    print(f"  T_inB            : {cfg['T_inB']:.2f} K")
    print(f"  T_OUT_A          : {res['T_A_out']:.2f} K  ΔT_A = "
          f"{cfg['T_inA']-res['T_A_out']:+.2f} K")
    print(f"  T_OUT_B          : {res['T_B_out']:.2f} K  ΔT_B = "
          f"{res['T_B_out']-cfg['T_inB']:+.2f} K")
    print()
    print("  ENTHALPY-SIDE (mass × cp × ΔT)")
    print(f"    Q_A_enth        : {Q_A_enth:>12.2f} W")
    print(f"    Q_B_enth        : {Q_B_enth:>12.2f} W")
    print(f"    |ΔQ| / max      : "
          f"{abs(Q_A_enth-Q_B_enth)/max(abs(Q_A_enth),abs(Q_B_enth),1e-12)*100:>11.2f} %")
    print()
    print("  SOLID-COUPLING-SIDE (Σ h_v · (Ts-T) · V)")
    print(f"    Q_sA total      : {Q_sA_total:>12.2f} W   "
          f"(BC slabs: {Q_sA_BC:>9.2f}  interior: {Q_sA_interior:>9.2f})")
    print(f"    Q_sB total      : {Q_sB_total:>12.2f} W   "
          f"(BC slabs: {Q_sB_BC:>9.2f}  interior: {Q_sB_interior:>9.2f})")
    print(f"    |Q_sA-Q_sB|/max : "
          f"{abs(Q_sA_total-Q_sB_total)/max(abs(Q_sA_total),abs(Q_sB_total),1e-12)*100:>11.2f} %  (total)")
    print(f"    interior diff   : "
          f"{abs(Q_sA_interior-Q_sB_interior)/max(abs(Q_sA_interior),abs(Q_sB_interior),1e-12)*100:>11.2f} %")
    print()
    print("  PRIMARY DISPLAYED Q : {:>9.2f} W   (UI shows this)".format(Q_primary))
    print()
    print("=" * 72)
    print(" THEORY CHECK — what ε-NTU expects")
    print("=" * 72)
    cp_air = 1005.0
    R = 287.0
    # Inlet ρ
    rhoA = cfg['P_inA'] / (R * cfg['T_inA'])
    rhoB = cfg['P_inB'] / (R * cfg['T_inB'])
    A_yz = cfg['H'] * cfg['Lz']
    A_xz = cfg['L'] * cfg['Lz']
    eps_p = cfg['eps']
    m_A = rhoA * cfg['u_A'] * A_yz * eps_p
    m_B = rhoB * cfg['u_B'] * A_xz * eps_p
    C_A = m_A * cp_air
    C_B = m_B * cp_air
    C_min = min(C_A, C_B)
    C_max = max(C_A, C_B)
    Cr = C_min / C_max
    dT_max = cfg['T_inA'] - cfg['T_inB']
    Q_max = C_min * dT_max
    print(f"  m_dot_A          : {m_A:.4f} kg/s   m_dot_B : {m_B:.4f} kg/s")
    print(f"  C_A              : {C_A:.2f} W/K     C_B     : {C_B:.2f} W/K")
    print(f"  C_min            : {C_min:.2f} W/K   C_r     : {Cr:.3f}")
    print(f"  ΔT_max           : {dT_max:.2f} K")
    print(f"  Q_max (theoretic): {Q_max:.2f} W")
    print(f"  ε_actual = Q/Q_max:")
    print(f"     using Q_A_enth: {Q_A_enth/Q_max:.4f}")
    print(f"     using Q_B_enth: {Q_B_enth/Q_max:.4f}")
    print(f"     using Q_sA_int: {Q_sA_interior/Q_max:.4f}")


if __name__ == '__main__':
    cfg = build_cfg()
    print(f"Running 3D Shanghai brick, T_inB={cfg['T_inB']:.1f}K (user scenario)...")
    import time
    t0 = time.time()
    res = _run_3d_stack(cfg)
    print(f"Solver: {time.time()-t0:.1f}s")
    diag(res, cfg)
