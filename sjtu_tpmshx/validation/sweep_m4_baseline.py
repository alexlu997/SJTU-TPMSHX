"""
M4 0D effective interfacial-area baseline closure sweep.
p ∈ {0.5, 0.67, 1.0} × r_eff_mode ∈ {"sqrt", "min"}
Cases: full-face B, ghost-B partial, Shanghai-style air-air 5-subset.
"""
import os, sys, time, json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runs.run_calculation_3d import _run_3d_stack

L, H, Lz = 0.182, 0.042, 0.042
Nx = Ny = Nz = 20

EXPONENTS = [0.5, 0.67, 1.0]
MODES = ["sqrt", "min"]

CASES = [
    # (label, u_A, u_B, T_Ain, T_Bin, P_Ain, P_Bin, partial_B)
    ("C1_low_partial",   2.0,  4.0,  422., 322., 102325., 101325., True),
    ("C2_mid_partial",  10.0, 20.0,  422., 322., 192362., 101325., True),
    ("C3_high_partial", 30.0, 50.0,  422., 322., 300000., 101325., True),
    ("C4_mid_full",     10.0, 20.0,  422., 322., 192362., 101325., False),
    ("C5_high_full",    30.0, 50.0,  422., 322., 300000., 101325., False),
]

def make_cfg(u_A, u_B, T_inA, T_inB, P_inA, P_inB, partial_B, mode, p):
    fB = dict(dir=3,
        in_ctr=0.154 if partial_B else 0.091,
        in_w=0.042 if partial_B else 0.182,
        out_ctr=0.028 if partial_B else 0.091,
        out_w=0.042 if partial_B else 0.182,
        in_z_ctr=0.021, in_z_w=0.042,
        out_z_ctr=0.021, out_z_w=0.042)
    return dict(L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        u_A=u_A, u_B=u_B, T_inA=T_inA, T_inB=T_inB,
        P_inA=P_inA, P_inB=P_inB,
        tpms_type='Gyroid', Lcell=7.0, t_wall=0.6, k_s=16.0, eps=0.85,
        fluid_A_cfg=dict(dir=0, in_ctr=0.021, in_w=0.042,
                         out_ctr=0.021, out_w=0.042,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
        fluid_B_cfg=fB, fluid_type_A='air', fluid_type_B='air',
        wall_refine_3d=False,
        partial_B_closure='m4_effective_area',
        m4_eff_mode=mode, m4_exponent=p)

def run_one(label, u_A, u_B, T_inA, T_inB, P_inA, P_inB, partial, mode, p):
    cfg = make_cfg(u_A, u_B, T_inA, T_inB, P_inA, P_inB, partial, mode, p)
    t0 = time.time()
    r = _run_3d_stack(cfg)
    dt = time.time() - t0

    row = dict(
        label=label, partial_B=partial, mode=mode, p=p,
        T_A_out=round(r['T_A_out'],1), T_B_out=round(r['T_B_out'],1),
        Q=round(r['Q'],0),
        Q_enth_A=round(r.get('Q_enthalpy_A',0),0),
        Q_enth_B=round(r.get('Q_enthalpy_B',0),0),
        Q_sA=round(r.get('Q_sA',0),0), Q_sB=round(r.get('Q_sB',0),0),
        Q_bal=round(r.get('Q_sA',0)+r.get('Q_sB',0),1),
        dP_A=round(r.get('dP_A',0),0), dP_B=round(r.get('dP_B',0),0),
        e_imbal=r.get('energy_imbalance_rel', float('nan')),
        m_imbal_A=r.get('mass_imbalance_rel_A', float('nan')),
        m_imbal_B=r.get('mass_imbalance_rel_B', float('nan')),
        elapsed=int(dt),
    )
    # ε-NTU
    dTmax = T_inA - T_inB
    row['eps_obs'] = round((r['T_B_out']-T_inB)/dTmax, 4) if dTmax>0 else float('nan')
    return row

def main():
    print("="*70)
    print("M4 0D effective-area baseline closure sweep")
    print("="*70)

    results = []
    for label, u_A, u_B, T_inA, T_inB, P_inA, P_inB, partial in CASES:
        for mode in MODES:
            for p in EXPONENTS:
                print(f"\n--- {label} mode={mode} p={p} ---")
                row = run_one(label, u_A, u_B, T_inA, T_inB, P_inA, P_inB,
                             partial, mode, p)
                results.append(row)
                ok = "PASS" if (not partial or row['T_B_out'] < row['T_A_out']) else "FAIL"
                print(f"  T_A={row['T_A_out']} T_B={row['T_B_out']} "
                      f"Q={row['Q']} Q_bal={row['Q_bal']} "
                      f"eps_obs={row['eps_obs']} → {ok} [{row['elapsed']}s]")

    # Summary
    print(f"\n{'='*100}")
    print("SUMMARY")
    print(f"{'='*100}")
    hdr = (f"{'Case':<20} {'mode':>5} {'p':>5} {'T_A':>7} {'T_B':>7} "
           f"{'Q':>8} {'Q_bal':>8} {'dP_B':>8} {'eps_obs':>7} {'Verdict':>8}")
    print(hdr)
    print("-"*len(hdr))
    for r in results:
        v = "PASS" if (not r['partial_B'] or r['T_B_out'] < r['T_A_out']) else "FAIL"
        print(f"{r['label']:<20} {r['mode']:>5} {r['p']:>5.2f} "
              f"{r['T_A_out']:>7.1f} {r['T_B_out']:>7.1f} {r['Q']:>8.0f} "
              f"{r['Q_bal']:>8.1f} {r['dP_B']:>8.0f} {r['eps_obs']:>7.3f} {v:>8}")

    # Pass criteria
    print(f"\n--- Pass criteria ---")
    partials = [r for r in results if r['partial_B']]
    fulls = [r for r in results if not r['partial_B']]
    fail_partial = [r for r in partials if r['T_B_out'] >= r['T_A_out']]
    print(f"  Full-face: {len(fulls)} combos — verify Q & dP consistency")
    print(f"  Partial T_B<T_A: {len(partials)-len(fail_partial)}/{len(partials)} combos pass")
    if fail_partial:
        print(f"  FAILURES: {[(r['label'],r['mode'],r['p']) for r in fail_partial]}")

    log_path = ROOT / "validation" / "m4_sweep_results.json"
    with open(log_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nLog: {log_path}")

if __name__ == '__main__':
    main()
