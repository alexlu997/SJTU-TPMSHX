"""validate_shanghai_3d_full_ltne.py — Shanghai 16-case Air-Water full LTNE.

Phase 7-2: replaces frozen-B Tb_prescribed (in `validate_shanghai_3d_real.py`)
with full SIMPLE-B + LTNE 3-temperature coupling. Water (Fluid B) solved by
SIMPLESolver3D incompressible + LTNE Tb update.

Geometry:
- Air (Fluid A): dir=0, full-face cross-section H_DOM × LZ at x=0
- Water (Fluid B): dir=3, full-face cross-section L_DOM × LZ at y=H_DOM
- Cross-flow unmixed-unmixed.

H8 ghost-pin disabled by default (full-face → no ghost cells). Can be
enabled via --h8 for partial-B experiments (future work if Shanghai actual
geometry has partial-B).

Compares Q_sim vs Q_exp (water heat capacity rate · ΔT) for 16 cases.
"""
from __future__ import annotations
import os, sys, warnings, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
warnings.filterwarnings('ignore')

from runs.run_calculation_3d import _run_3d_stack
from solvers.tpms_calc import (
    geometry as tpms_geometry, air_density, air_cp, P_atm,
)


# ── Shanghai geometry constants (mirror validate_shanghai_3d_real.py) ──
TPMS = 'Gyroid'
L_CELL = 7.0
T_WALL = 0.6
K_S = 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']

L_DOM = 0.182
H_DOM = 0.042
LZ = 0.042

N_UNITS = 36
A_FLOW_PER_UNIT = 18.0565e-6
A_FLOW = N_UNITS * A_FLOW_PER_UNIT


def make_cfg_case(ci, df, Nx=20, Ny=10, Nz=10, use_h8=False):
    """Build cfg dict for Shanghai case ci (0-15)."""
    # Air (Fluid A) inlet conditions
    m_air = float(df.iloc[ci, 5])
    T_Ain_C = float(df.iloc[ci, 28]); T_Ain_K = T_Ain_C + 273.15
    P_Ain_g = float(df.iloc[ci, 30])
    P_Ain = P_atm + P_Ain_g
    rho_A = air_density(T_Ain_K, P_Ain)
    u_A = m_air / (rho_A * A_FLOW)

    # Water (Fluid B) inlet conditions
    m_water = float(df.iloc[ci, 7])
    T_Bin_C = float(df.iloc[ci, 24]); T_Bin_K = T_Bin_C + 273.15
    rho_B = 999.84 - 0.05 * T_Bin_C - 0.004 * T_Bin_C ** 2
    # Water inlet: 42×42 mm manifold patch at one corner (NOT full L_DOM×LZ).
    # Shanghai actual geometry — water enters narrow port, diffuses inside HX,
    # contracts back at outlet manifold at opposite x-corner. This is partial-B
    # offset cross-flow (matches T4 audit case). Yan [6] Re convention uses
    # manifold u (lumped harness same convention).
    A_water_manifold = H_DOM * LZ   # 42×42 mm² = 0.001764 m²
    u_B = m_water / (rho_B * A_water_manifold)

    # Experimental refs
    P_Aout_g = float(df.iloc[ci, 31])
    dP_A_exp = P_Ain_g - P_Aout_g
    Q_exp = float(df.iloc[ci, 33])

    cfg = dict(
        L=L_DOM, H=H_DOM, Lz=LZ,
        Nx=Nx, Ny=Ny, Nz=Nz,
        u_A=u_A, u_B=u_B,
        T_inA=T_Ain_K, T_inB=T_Bin_K,
        P_inA=P_Ain, P_inB=P_atm,    # water reference pressure
        tpms_type=TPMS, Lcell=L_CELL, t_wall=T_WALL,
        k_s=K_S, eps=EPS,
        # Air full-face inlet
        fluid_A_cfg=dict(dir=0, in_ctr=H_DOM/2, in_w=H_DOM,
                          out_ctr=H_DOM/2, out_w=H_DOM,
                          in_z_ctr=LZ/2, in_z_w=LZ,
                          out_z_ctr=LZ/2, out_z_w=LZ),
        # Water 42×42 manifold partial-B offset cross-flow:
        # inlet manifold at x≈0.021 (left corner, 0-42mm), full z;
        # outlet manifold at x≈0.161 (right corner, 140-182mm), full z.
        # Diagonal flow corridor diffuses through HX bulk.
        fluid_B_cfg=dict(dir=3,
                          in_ctr=0.021, in_w=0.042,
                          out_ctr=0.161, out_w=0.042,
                          in_z_ctr=LZ/2, in_z_w=LZ,
                          out_z_ctr=LZ/2, out_z_w=LZ),
        fluid_type_A='air', fluid_type_B='water',
        wall_refine_3d=False,
    )
    if use_h8:
        cfg.update(dict(
            partial_B_closure='per_cell_chi_b',
            chi_B_method='mass_flux_threshold',
            chi_B_mass_ref_mode='max',
            chi_B_threshold_frac=0.20,
            chi_B_n_dilate=1,
            chi_B_n_smooth=0,
            chi_B_floor=1e-3,
            chi_B_kernel_threshold=0.30,
        ))
    cfg['_case_label'] = f'shanghai_case_{ci+1}'
    cfg['_dP_exp'] = dP_A_exp
    cfg['_Q_exp'] = Q_exp
    cfg['_T_Bin_K'] = T_Bin_K
    cfg['_T_Ain_K'] = T_Ain_K
    cfg['_m_water'] = m_water
    cfg['_m_air'] = m_air
    return cfg


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--nx', type=int, default=20)
    ap.add_argument('--ny', type=int, default=10)
    ap.add_argument('--nz', type=int, default=10)
    ap.add_argument('--cases', type=int, default=16)
    ap.add_argument('--h8', action='store_true', help='Enable H8 ghost-pin')
    ap.add_argument('--suffix', type=str, default='')
    args = ap.parse_args()

    data_path = (
        r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data'
        r'\20260401-上海电气天然气加热器实验工况.xlsx'
    )
    df = pd.read_excel(data_path, engine='openpyxl', sheet_name='Sheet1',
                       header=None, skiprows=2)

    print(f"Shanghai 3D full-LTNE validation (Air-Water cross-flow)")
    print(f"Geometry: {L_DOM*1000:.0f}×{H_DOM*1000:.0f}×{LZ*1000:.0f} mm")
    print(f"Grid: {args.nx}×{args.ny}×{args.nz}")
    print(f"H8 ghost-pin: {'ON' if args.h8 else 'OFF'}\n")

    results = []
    for ci in range(args.cases):
        cfg = make_cfg_case(ci, df, Nx=args.nx, Ny=args.ny, Nz=args.nz,
                              use_h8=args.h8)
        Q_exp = cfg['_Q_exp']
        dP_exp = cfg['_dP_exp']
        t0 = time.time()
        try:
            res = _run_3d_stack(cfg)
            dt = time.time() - t0
            Q_sim = float(res.get('Q_enthalpy_A', 0.0))
            dP_sim = float(res.get('dP', 0.0))
            T_A_out = float(res.get('T_A_out', 0.0))
            T_B_out = float(res.get('T_B_out', 0.0))
            err_Q = (Q_sim - Q_exp) / max(abs(Q_exp), 1e-30) * 100
            err_dP = (dP_sim - dP_exp) / max(abs(dP_exp), 1e-30) * 100
            results.append(dict(
                case=ci+1, Q_exp=Q_exp, Q_sim=Q_sim, err_Q=err_Q,
                dP_exp=dP_exp, dP_sim=dP_sim, err_dP=err_dP,
                T_A_out=T_A_out, T_B_out=T_B_out,
                Q_solid_B=float(res.get('Q_sB_interior', 0.0)),
                elapsed=int(dt),
            ))
            print(f"Case {ci+1:2d}: dP {dP_exp:.0f}/{dP_sim:.0f} "
                  f"({err_dP:+.1f}%)  Q {Q_exp:.0f}/{Q_sim:.0f} "
                  f"({err_Q:+.1f}%)  T_A_out={T_A_out:.1f} "
                  f"T_B_out={T_B_out:.1f}  [{dt:.0f}s]")
        except Exception as e:
            print(f"Case {ci+1:2d}: FAILED ({type(e).__name__}: {e})")
            results.append(dict(case=ci+1, error=str(e), elapsed=0))

    valid = [r for r in results if 'err_Q' in r]
    if valid:
        rmsre_Q = float(np.sqrt(np.mean([r['err_Q']**2 for r in valid])))
        rmsre_dP = float(np.sqrt(np.mean([r['err_dP']**2 for r in valid])))
        max_Q = max(abs(r['err_Q']) for r in valid)
        max_dP = max(abs(r['err_dP']) for r in valid)
        print(f"\n{'='*70}")
        print(f"  RMSRE_dP   : {rmsre_dP:.2f}%   max|err_dP|: {max_dP:.2f}%")
        print(f"  RMSRE_Q    : {rmsre_Q:.2f}%   max|err_Q| : {max_Q:.2f}%")
        print(f"{'='*70}")

    out = pd.DataFrame(valid)
    csv_path = (ROOT / 'validation' /
                f'shanghai_3d_full_ltne{args.suffix}.csv')
    out.to_csv(csv_path, index=False)
    print(f"\nSaved: {csv_path}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
