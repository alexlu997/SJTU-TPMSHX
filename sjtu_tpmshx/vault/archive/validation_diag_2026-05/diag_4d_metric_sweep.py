"""diag_4d_metric_sweep.py — Step 1 of v3 future-work plan.

Runs Shanghai air-air with 4-D conservation metric (R_m_inf, R_m_1, NET_OUT,
R_E=AB imbal) at multiple SIMPLE pressure-correction tolerances. Goal: locate
where AB imbal originates — mass-side (SIMPLE residual) vs energy-side (flux
consistency).

Usage:
    python -u sjtu_tpmshx/validation/diag_4d_metric_sweep.py

Outputs CSV + console summary.
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
from solvers.solve_full_3d import energy_balance_3d


def build_cfg(wall_refine: bool, swap: bool = False,
              Nx_u: int = 30, Ny_u: int = 20, Nz_u: int = 5):
    """Shanghai Air-Air 3D config (full-face for clean test). A=+x, B=-y."""
    L_DOM, H_DOM, Lz = 0.182, 0.042, 0.042
    T_hot, T_cold = 422.0, 300.0
    if swap:
        T_inA, T_inB = T_cold, T_hot
    else:
        T_inA, T_inB = T_hot, T_cold

    fA = dict(dir=0, in_ctr=H_DOM / 2, in_w=H_DOM, out_ctr=H_DOM / 2, out_w=H_DOM)
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
    from solvers.tpms_calc import geometry as tpms_geometry
    g = tpms_geometry('Gyroid', 7.0, 0.6, 16.0)
    cfg['eps'] = g['epsilon']
    cfg['D_h'] = g['D_h']
    return cfg


def compute_4d_metrics(res, cfg):
    """Extract R_m_inf, R_m_1, NET_OUT, R_E from result dict + helper data."""
    Q_A = abs(res.get('Q_enthalpy_A', float('nan')))
    Q_B = abs(res.get('Q_enthalpy_B', float('nan')))
    Q_sA = res.get('Q_sA', float('nan'))
    Q_sB = res.get('Q_sB', float('nan'))
    Q_net = res.get('Q_net', Q_sA + Q_sB if not np.isnan(Q_sA) else float('nan'))

    # AB imbalance (energy)
    denom = max(Q_A, Q_B, 1e-30)
    AB_imbal = abs(Q_A - Q_B) / denom

    # LTNE source net (should ≈ 0)
    e_imb_LTNE = abs(Q_net) / max(abs(Q_sA), abs(Q_sB), 1e-30)

    # Mass: NET_OUT = mass_rel (bulk)
    m_rel_A = res.get('mass_imbalance_rel_A', float('nan'))
    m_rel_B = res.get('mass_imbalance_rel_B', float('nan'))

    # R_m_inf, R_m_1 not currently stored, would need solver instrumentation.
    # Use mass_imbalance_rel as proxy for NET_OUT.
    NET_OUT_A = m_rel_A
    NET_OUT_B = m_rel_B

    # R_E: |Q_enth - |Q_s|| (boundary metric vs volume integral)
    R_E_A = abs(Q_A - abs(Q_sA)) / max(Q_A, 1e-30) if not np.isnan(Q_sA) else float('nan')
    R_E_B = abs(Q_B - abs(Q_sB)) / max(Q_B, 1e-30) if not np.isnan(Q_sB) else float('nan')

    return dict(
        Q_A=Q_A, Q_B=Q_B, Q_sA=Q_sA, Q_sB=Q_sB,
        AB_imbal=AB_imbal, e_imb_LTNE=e_imb_LTNE,
        NET_OUT_A=NET_OUT_A, NET_OUT_B=NET_OUT_B,
        R_E_A=R_E_A, R_E_B=R_E_B,
    )


def run_one(label, wall_refine, swap, simple_tol):
    """Run one Shanghai case at given SIMPLE tol and return 4-D metrics."""
    os.environ['TPMSHX_SIMPLE_TOL'] = str(simple_tol)
    cfg = build_cfg(wall_refine, swap)
    print(f"\n--- {label} (wall_refine={wall_refine}, swap={swap}, simple_tol={simple_tol:.0e}) ---")
    res = _run_3d_stack(cfg)
    m = compute_4d_metrics(res, cfg)
    print(f"  AB_imbal={m['AB_imbal']*100:.3f}%  e_imb_LTNE={m['e_imb_LTNE']*100:.4f}%")
    print(f"  NET_OUT_A={m['NET_OUT_A']*100:.4f}%  NET_OUT_B={m['NET_OUT_B']*100:.4f}%")
    print(f"  R_E_A={m['R_E_A']*100:.3f}%  R_E_B={m['R_E_B']*100:.3f}%")
    print(f"  Q_A={m['Q_A']:.2f}W  Q_B={m['Q_B']:.2f}W  Q_sA={m['Q_sA']:.2f}W  Q_sB={m['Q_sB']:.2f}W")
    return dict(label=label, simple_tol=simple_tol, **m)


def main():
    print("=" * 74)
    print("4-D Metric SIMPLE Tol Sweep — v3 Step 1 Diagnostic")
    print("=" * 74)
    print("Goal: locate AB imbal source (mass-side vs energy-side)")
    print("If R_m ↓ + AB ↓ sync: mass main cause → path 0 fix")
    print("If R_m ↓ but AB stable: energy main cause → path 0' fix (likely)")
    print("If R_m unchanged: deeper face flux issue\n")

    tols = [1e-5, 1e-6, 1e-8]   # 1e-10 too costly for full sweep, add only if needed
    cases = [
        ('NORM-NO_REFINE', False, False),
        ('NORM-REFINE',    True,  False),
        ('SWAP-NO_REFINE', False, True),
        ('SWAP-REFINE',    True,  True),
    ]

    rows = []
    for label, wall, swap in cases:
        for tol in tols:
            full_label = f"{label}-tol{tol:.0e}"
            r = run_one(full_label, wall, swap, tol)
            rows.append(r)

    print("\n" + "=" * 74)
    print("Summary table")
    print("=" * 74)
    print(f"{'Case':<32s} {'tol':>8s} {'R_m_A%':>8s} {'R_m_B%':>8s} "
          f"{'AB%':>7s} {'e_LTNE%':>8s} {'R_E_A%':>8s} {'R_E_B%':>8s}")
    for r in rows:
        print(f"{r['label']:<32s} {r['simple_tol']:>8.0e} "
              f"{r['NET_OUT_A']*100:>7.4f} {r['NET_OUT_B']*100:>7.4f} "
              f"{r['AB_imbal']*100:>6.2f} {r['e_imb_LTNE']*100:>7.4f} "
              f"{r['R_E_A']*100:>7.2f} {r['R_E_B']*100:>7.2f}")

    print("\n" + "=" * 74)
    print("Interpretation")
    print("=" * 74)
    # For each base case, check if AB drops with tighter tol
    base_cases = ['NORM-NO_REFINE', 'NORM-REFINE', 'SWAP-NO_REFINE', 'SWAP-REFINE']
    for bc in base_cases:
        case_rows = [r for r in rows if r['label'].startswith(bc + '-tol')]
        if len(case_rows) < 2:
            continue
        ab_first = case_rows[0]['AB_imbal']
        ab_last = case_rows[-1]['AB_imbal']
        m_first = case_rows[0]['NET_OUT_A']
        m_last = case_rows[-1]['NET_OUT_A']
        ab_change = (ab_first - ab_last) / max(ab_first, 1e-30) * 100
        m_change = (m_first - m_last) / max(m_first, 1e-30) * 100
        print(f"  {bc}: tol {case_rows[0]['simple_tol']:.0e}->{case_rows[-1]['simple_tol']:.0e}  "
              f"R_m_A change {m_change:+.1f}%  AB change {ab_change:+.1f}%")
        if abs(m_change) > 30 and abs(ab_change) > 30:
            print(f"    -> mass-side dominant (path 0 / path 2 useful)")
        elif abs(m_change) > 30 and abs(ab_change) < 10:
            print(f"    -> ENERGY-side dominant (path 0' energy flux consistency required)")
        elif abs(m_change) < 10:
            print(f"    -> deeper face-flux / discretization issue")


if __name__ == '__main__':
    main()
