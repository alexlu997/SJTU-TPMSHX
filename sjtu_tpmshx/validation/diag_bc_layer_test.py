"""diag_bc_layer_test.py — Test if Q_sA over-counts BC layer.

Hypothesis: Q_sA = ∫h_v·(Ts-Ta)·dV over ALL cells over-counts because BC
inlet cells have Ta pinned at T_in (artificial). Solid responds to this
artificial pinning, creating spurious h_v·(Ts-T_in) contribution at BC layer.

Test: compute Q_sA_interior = same integral but EXCLUDING BC inlet/outlet
layer cells. If Q_sA_interior ≈ Q_enth_A, BC layer over-count is the cause.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import warnings
warnings.filterwarnings('ignore')

from runs.run_calculation_3d import _run_3d_stack


def build_cfg(wall_refine: bool, swap: bool = False,
              Nx_u: int = 30, Ny_u: int = 20, Nz_u: int = 5):
    L_DOM, H_DOM, Lz = 0.182, 0.042, 0.042
    T_hot, T_cold = 422.0, 300.0
    T_inA, T_inB = (T_cold, T_hot) if swap else (T_hot, T_cold)
    fA = dict(dir=0, in_ctr=H_DOM/2, in_w=H_DOM, out_ctr=H_DOM/2, out_w=H_DOM)
    fB = dict(dir=3, in_ctr=L_DOM/2, in_w=L_DOM, out_ctr=L_DOM/2, out_w=L_DOM)
    cfg = dict(
        L=L_DOM, H=H_DOM, Lz=Lz, Nx=Nx_u, Ny=Ny_u, Nz=Nz_u,
        u_A=5.0, u_B=5.0, T_inA=T_inA, T_inB=T_inB,
        P_inA=1.01325e5, P_inB=1.01325e5, T_s_init=None,
        Lcell=7.0, t_wall=0.6, k_s=16.0, tpms_type='Gyroid',
        eps=None, D_h=None, fluid_A_cfg=fA, fluid_B_cfg=fB,
        wall_refine_3d=wall_refine, zone_grid_cells=None,
        fluid_type_A='air', fluid_type_B='air',
    )
    from solvers.tpms_calc import geometry
    g = geometry('Gyroid', 7.0, 0.6, 16.0)
    cfg['eps'] = g['epsilon']
    cfg['D_h'] = g['D_h']
    return cfg


def compute_q_split(cfg):
    """Run 3D, then compute Q_sA separated into BC-layer vs interior."""
    res = _run_3d_stack(cfg)
    Ta = res['Ta']; Tb = res['Tb']; Ts = res['Ts']
    dx = res['dx']; dy = res['dy']; dz = res['dz']
    h_vA = res.get('h_vA_field')
    h_vB = res.get('h_vB_field')
    if h_vA is None:
        # Fallback: try res['h_vA'] or compute from data
        print("    [warn] h_vA_field missing, skipping BC-layer split")
        return res, None

    vol = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]
    integrand_A = h_vA * (Ts - Ta) * vol
    integrand_B = h_vB * (Ts - Tb) * vol

    fA = cfg['fluid_A_cfg']
    fB = cfg['fluid_B_cfg']
    Nx, Ny, Nz = Ta.shape

    # BC layer mask for A: inlet face cells (i=0 if dir=0, i=Nx-1 if dir=1, etc.)
    def bc_layer_mask(dir_code):
        m = np.zeros((Nx, Ny, Nz), dtype=bool)
        if dir_code == 0:   m[0, :, :] = True
        elif dir_code == 1: m[Nx-1, :, :] = True
        elif dir_code == 2: m[:, 0, :] = True
        elif dir_code == 3: m[:, Ny-1, :] = True
        elif dir_code == 4: m[:, :, 0] = True
        else:               m[:, :, Nz-1] = True
        return m

    # Outlet layer
    def outlet_layer_mask(dir_code):
        m = np.zeros((Nx, Ny, Nz), dtype=bool)
        if dir_code == 0:   m[Nx-1, :, :] = True
        elif dir_code == 1: m[0, :, :] = True
        elif dir_code == 2: m[:, Ny-1, :] = True
        elif dir_code == 3: m[:, 0, :] = True
        elif dir_code == 4: m[:, :, Nz-1] = True
        else:               m[:, :, 0] = True
        return m

    inlet_A = bc_layer_mask(fA['dir'])
    outlet_A = outlet_layer_mask(fA['dir'])
    inlet_B = bc_layer_mask(fB['dir'])
    outlet_B = outlet_layer_mask(fB['dir'])

    # Q_sA split
    Q_sA_inlet = float(np.sum(integrand_A[inlet_A]))
    Q_sA_outlet = float(np.sum(integrand_A[outlet_A]))
    Q_sA_interior = float(np.sum(integrand_A[~(inlet_A | outlet_A)]))
    Q_sA_total = float(np.sum(integrand_A))

    Q_sB_inlet = float(np.sum(integrand_B[inlet_B]))
    Q_sB_outlet = float(np.sum(integrand_B[outlet_B]))
    Q_sB_interior = float(np.sum(integrand_B[~(inlet_B | outlet_B)]))
    Q_sB_total = float(np.sum(integrand_B))

    return res, dict(
        Q_sA_total=Q_sA_total,
        Q_sA_inlet=Q_sA_inlet,
        Q_sA_outlet=Q_sA_outlet,
        Q_sA_interior=Q_sA_interior,
        Q_sB_total=Q_sB_total,
        Q_sB_inlet=Q_sB_inlet,
        Q_sB_outlet=Q_sB_outlet,
        Q_sB_interior=Q_sB_interior,
    )


def main():
    print("="*74)
    print("BC layer over-count test")
    print("="*74)
    print("Hypothesis: |Q_sA| over-counts due to BC inlet pinning artifact.")
    print("If |Q_sA_interior| ≈ Q_enth_A: confirmed.\n")

    for label, wall, swap in [
        ('NORM-NO_REFINE', False, False),
        ('NORM-REFINE', True, False),
    ]:
        cfg = build_cfg(wall, swap)
        print(f"\n--- {label} (wall_refine={wall}, swap={swap}) ---")
        res, split = compute_q_split(cfg)
        Q_A = abs(res.get('Q_enthalpy_A', float('nan')))
        Q_B = abs(res.get('Q_enthalpy_B', float('nan')))
        print(f"  Q_enth_A = {Q_A:.2f}W   Q_enth_B = {Q_B:.2f}W   AB={(abs(Q_A-Q_B)/max(Q_A,Q_B)*100):.2f}%")
        if split is None:
            continue
        print(f"  Q_sA_total    = {split['Q_sA_total']:.2f}W")
        print(f"    inlet layer  = {split['Q_sA_inlet']:.2f}W")
        print(f"    outlet layer = {split['Q_sA_outlet']:.2f}W")
        print(f"    interior     = {split['Q_sA_interior']:.2f}W")
        print(f"  Q_sB_total    = {split['Q_sB_total']:.2f}W")
        print(f"    inlet layer  = {split['Q_sB_inlet']:.2f}W")
        print(f"    outlet layer = {split['Q_sB_outlet']:.2f}W")
        print(f"    interior     = {split['Q_sB_interior']:.2f}W")
        print(f"  R_E_A_total    = {abs(Q_A - abs(split['Q_sA_total']))/max(Q_A,1e-30)*100:.2f}%")
        print(f"  R_E_A_interior = {abs(Q_A - abs(split['Q_sA_interior']))/max(Q_A,1e-30)*100:.2f}%")
        print(f"  R_E_B_total    = {abs(Q_B - abs(split['Q_sB_total']))/max(Q_B,1e-30)*100:.2f}%")
        print(f"  R_E_B_interior = {abs(Q_B - abs(split['Q_sB_interior']))/max(Q_B,1e-30)*100:.2f}%")


if __name__ == '__main__':
    main()
