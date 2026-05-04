"""diag_3d_energy_imbal.py — Shanghai 3D Air-Air energy imbalance diagnostic.

Goal (2026-04-25): fix 3D energy conservation with Air vs Air. Uses full-face
(B dir=3, in/out across whole Lz/Lx) to isolate FV discretisation from
partial-mask effects. Reports per-side mass imbalance, NET_OUT magnitude,
and all Q metrics.
"""
from __future__ import annotations
import os, sys, warnings
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
warnings.filterwarnings('ignore')

from runs.run_calculation_3d import _run_3d_stack
from solvers.solve_full_3d import mass_balance_3d, energy_balance_3d


def build_cfg(wall_refine: bool, swap: bool = False,
              Nx_u: int = 30, Ny_u: int = 20, Nz_u: int = 5):
    """Shanghai Air-Air 3D config. Both full-face (no partial BC) for clean
    test. A=+x, B=-y. Air properties both sides."""
    L_DOM, H_DOM, Lz = 0.182, 0.042, 0.042
    T_hot, T_cold = 422.0, 300.0
    if swap:
        T_inA, T_inB = T_cold, T_hot
    else:
        T_inA, T_inB = T_hot, T_cold

    fA = dict(dir=0, in_ctr=H_DOM / 2, in_w=H_DOM, out_ctr=H_DOM / 2, out_w=H_DOM)
    # B full-face across x (cross1) × z (cross2)
    fB = dict(dir=3, in_ctr=L_DOM / 2, in_w=L_DOM, out_ctr=L_DOM / 2, out_w=L_DOM)

    cfg = dict(
        L=L_DOM, H=H_DOM, Lz=Lz,
        Nx=Nx_u, Ny=Ny_u, Nz=Nz_u,
        u_A=5.0, u_B=5.0,
        T_inA=T_inA, T_inB=T_inB,
        P_inA=1.01325e5, P_inB=1.01325e5,
        T_s_init=None,
        Lcell=7.0, t_wall=0.6, k_s=16.0,
        tpms_type='Gyroid',
        eps=None, D_h=None,
        fluid_A_cfg=fA, fluid_B_cfg=fB,
        wall_refine_3d=wall_refine,
        zone_grid_cells=None,
        fluid_type_A='air', fluid_type_B='air',
    )
    # compute eps, D_h
    from solvers.tpms_calc import geometry as tpms_geometry
    g = tpms_geometry('Gyroid', 7.0, 0.6, 16.0)
    cfg['eps'] = g['epsilon']; cfg['D_h'] = g['D_h']
    return cfg


def run_and_diag(label: str, wall_refine: bool, swap: bool = False):
    print(f"\n╔═══ {label} (wall_refine={wall_refine}, swap={swap}) ═══╗")
    cfg = build_cfg(wall_refine, swap)
    res = _run_3d_stack(cfg)

    Q_primary = res.get('Q', float('nan'))
    Q_A = res.get('Q_enthalpy_A', float('nan'))
    Q_B = res.get('Q_enthalpy_B', float('nan'))
    Q_solid = res.get('Q_solid_B', float('nan'))
    Q_sA = res.get('Q_sA', float('nan'))
    Q_sB = res.get('Q_sB', float('nan'))
    Q_net = res.get('Q_net', float('nan'))
    e_rel = res.get('energy_imbalance_rel', float('nan'))
    m_rel_A = res.get('mass_imbalance_rel_A', float('nan'))
    m_rel_B = res.get('mass_imbalance_rel_B', float('nan'))

    denom = max(abs(Q_A), abs(Q_B), 1e-30)
    ab_imbal = abs(Q_A - Q_B) / denom

    # NTU thermodynamic upper bound (cross-flow unmixed/unmixed)
    from solvers.tpms_calc import geometry as tpms_geom
    g = tpms_geom('Gyroid', 7.0, 0.6, 16.0)
    eps = g['epsilon']; A0 = g['A_0']
    V_dom = 0.182 * 0.042 * 0.042
    rho_A = 101325 / (287 * cfg['T_inA']) if cfg['T_inA'] > 350 else 101325 / (287 * cfg['T_inA'])
    rho_B = 101325 / (287 * cfg['T_inB']) if cfg['T_inB'] > 350 else 101325 / (287 * cfg['T_inB'])
    C_A = (eps/2) * rho_A * 5 * 0.042 * 0.042 * 1006
    C_B = (eps/2) * rho_B * 5 * 0.182 * 0.042 * 1006
    C_min = min(C_A, C_B); C_max = max(C_A, C_B); C_r = C_min/C_max
    dT_max = abs(cfg['T_inA'] - cfg['T_inB'])
    Q_NTU_upper = C_min * dT_max

    pct = e_rel * 100
    pass_fail = "PASS" if pct < 5.0 else "FAIL"
    Q_ntu_pct = Q_primary / Q_NTU_upper * 100
    ntu_flag = "OK" if Q_primary <= Q_NTU_upper * 1.1 else "OVER"
    print(f"  ★ Q (primary, mean Q_enth)             = {Q_primary:10.3f} W")
    print(f"  ★ NTU upper bound (ε=1·C_min·ΔT)       = {Q_NTU_upper:10.3f} W   "
          f"[Q/Q_NTU={Q_ntu_pct:.1f}%  {ntu_flag}]")
    print(f"  ★ Energy conservation |Q_sA+Q_sB|/sum  = {pct:7.4f}%   [{pass_fail} <5%]")
    Q_int = res.get('Q_interior', float('nan'))
    AB_int = res.get('AB_interior', float('nan'))
    Q_sA_int = res.get('Q_sA_interior', float('nan'))
    Q_sB_int = res.get('Q_sB_interior', float('nan'))
    print(f"  ★ Q_interior (BC-excl primary) = {Q_int:.2f} W   AB_interior = {AB_int*100:.4f}%")
    print(f"     |Q_sA_interior| = {abs(Q_sA_int):.2f}W  |Q_sB_interior| = {abs(Q_sB_int):.2f}W")
    print(f"  Q_sA (solid→A) = {Q_sA:10.3f} W")
    print(f"  Q_sB (solid→B) = {Q_sB:10.3f} W")
    print(f"  Q_net          = {Q_net:10.3f} W")
    print(f"  ---- secondary diagnostic metrics ----")
    print(f"  Q_enthalpy_A   = {Q_A:10.3f} W    (m·cp·ΔT, AB imbal = {ab_imbal*100:.2f}%)")
    print(f"  Q_enthalpy_B   = {Q_B:10.3f} W")
    print(f"  mass_rel_A     = {m_rel_A*100:.4f}%")
    print(f"  mass_rel_B     = {m_rel_B*100:.4f}%")
    print(f"  T_A_out        = {res.get('T_A_out', float('nan')):.3f} K  "
          f"(T_inA = {cfg['T_inA']:.1f})")
    print(f"  T_B_out        = {res.get('T_B_out', float('nan')):.3f} K  "
          f"(T_inB = {cfg['T_inB']:.1f})")
    # Extra diag: SIMPLE raw face velocities & rho at inlet/outlet of A
    uc_real = res.get('uc_real')
    if uc_real is not None:
        print(f"  ucA_real[0,:,:]_mean   = {float(np.mean(uc_real[0, :, :])):.3f}")
        print(f"  ucA_real[-1,:,:]_mean  = {float(np.mean(uc_real[-1, :, :])):.3f}")
    return dict(label=label, Q_A=Q_A, Q_B=Q_B, ab_imbal=ab_imbal,
                Q_solid=Q_solid, Q_sA=Q_sA, Q_sB=Q_sB, Q_net=Q_net,
                e_rel=e_rel, m_rel_A=m_rel_A, m_rel_B=m_rel_B,
                Q_interior=res.get('Q_interior', float('nan')),
                AB_interior=res.get('AB_interior', float('nan')))


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--grid-sweep', action='store_true', help='grid-convergence sweep')
    args = ap.parse_args()

    if args.grid_sweep:
        # Uniform grid convergence: measure AB imbal as Nx, Ny, Nz all scale.
        print("Grid convergence sweep (no wall refine, NORM):")
        for mult in (1, 2, 3):
            Nx, Ny, Nz = 30 * mult, 20 * mult, 5 * mult
            label = f"NORM-G{mult}x ({Nx}x{Ny}x{Nz})"
            print(f"\n-- {label} --")
            cfg = build_cfg(wall_refine=False, swap=False, Nx_u=Nx, Ny_u=Ny, Nz_u=Nz)
            res = _run_3d_stack(cfg)
            Q_A = res['Q_enthalpy_A']; Q_B = res['Q_enthalpy_B']
            Q_sA = res.get('Q_sA', float('nan')); Q_sB = res.get('Q_sB', float('nan'))
            e_rel = res.get('energy_imbalance_rel', float('nan'))
            denom = max(abs(Q_A), abs(Q_B), 1e-30)
            ab_imbal = abs(Q_A - Q_B) / denom
            print(f"  Q_A={Q_A:.1f}  Q_B={Q_B:.1f}  |Q_sA|={abs(Q_sA):.1f}  |Q_sB|={abs(Q_sB):.1f}")
            print(f"  AB imbal = {ab_imbal*100:.2f}%   LTNE net-imbal = {e_rel*100:.3f}%")
    else:
        r1 = run_and_diag('NORM-NO_REFINE', wall_refine=False, swap=False)
        r2 = run_and_diag('NORM-REFINE',     wall_refine=True,  swap=False)
        r3 = run_and_diag('SWAP-NO_REFINE', wall_refine=False, swap=True)
        r4 = run_and_diag('SWAP-REFINE',     wall_refine=True,  swap=True)

        print("\n╔═══ Summary ═══╗")
        for r in (r1, r2, r3, r4):
            print(f"  {r['label']:16s}: AB {r['ab_imbal']*100:6.2f}%  "
                  f"mA {r['m_rel_A']*100:.3f}%  mB {r['m_rel_B']*100:.3f}%  "
                  f"e_imb {r['e_rel']*100:.3f}%  "
                  f"AB_interior {r.get('AB_interior', float('nan'))*100:6.4f}%")
