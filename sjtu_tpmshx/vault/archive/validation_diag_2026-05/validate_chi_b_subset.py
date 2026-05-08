"""
Phase 3a: χ_B subset validation — Air-Air cases through _run_3d_stack.

Validates χ_B indicator-field reformulation on 5 Air-Air cases spanning
low/mid/high Re + partial/full BC. Shanghai frozen-B script does NOT
exercise _run_3d_stack, so this script covers the active-B path.

Cases:
  1. Low-Re partial  (u_A=2,  u_B=4,  partial -y B)  — ghost-B risk high
  2. Mid-Re partial  (u_A=10, u_B=20, partial -y B)  — ghost-B baseline
  3. High-Re partial (u_A=30, u_B=50, partial -y B)  — high-NTU edge
  4. Mid-Re full     (u_A=10, u_B=20, full -y B)     — χ_B should ≈ 1
  5. High-Re full    (u_A=30, u_B=50, full -y B)     — sanity, ε-NTU check
"""
import os, sys, time, json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs.run_calculation_3d import _run_3d_stack
from solvers.tpms_calc import air_density, air_viscosity, air_cp, air_conductivity

R_AIR = 287.05
L, H, Lz = 0.182, 0.042, 0.042
Nx = Ny = Nz = 20

# ── Case definitions ──
CASES = [
    # (label, u_A, u_B, T_inA, T_inB, P_inA, P_inB, partial_B)
    ("C1_low_partial",   2.0,  4.0,  422., 322., 102325., 101325., True),
    ("C2_mid_partial",  10.0, 20.0,  422., 322., 192362., 101325., True),
    ("C3_high_partial", 30.0, 50.0,  422., 322., 300000., 101325., True),
    ("C4_mid_full",     10.0, 20.0,  422., 322., 192362., 101325., False),
    ("C5_high_full",    30.0, 50.0,  422., 322., 300000., 101325., False),
]

def make_cfg(u_A, u_B, T_inA, T_inB, P_inA, P_inB, partial_B):
    fB = dict(
        dir=3,
        in_ctr=0.154 if partial_B else 0.091,
        in_w=0.042 if partial_B else 0.182,
        out_ctr=0.028 if partial_B else 0.091,
        out_w=0.042 if partial_B else 0.182,
        in_z_ctr=0.021, in_z_w=0.042,
        out_z_ctr=0.021, out_z_w=0.042,
    )
    return dict(
        L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        u_A=u_A, u_B=u_B, T_inA=T_inA, T_inB=T_inB,
        P_inA=P_inA, P_inB=P_inB,
        tpms_type='Gyroid', Lcell=7.0, t_wall=0.6, k_s=16.0,
        eps=0.85,
        fluid_A_cfg=dict(dir=0, in_ctr=0.021, in_w=0.042,
                         out_ctr=0.021, out_w=0.042,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
        fluid_B_cfg=fB,
        fluid_type_A='air', fluid_type_B='air',
        wall_refine_3d=False,
    )


def run_case(label, cfg):
    t0 = time.time()
    r = _run_3d_stack(cfg)
    elapsed = time.time() - t0

    T_A = r['T_A_out']; T_B = r['T_B_out']
    dT = T_A - T_B
    chi = r.get('chi_B')

    # χ stats
    chi_stats = {}
    if chi is not None:
        cf = chi.ravel()
        chi_stats = dict(
            mean=float(np.mean(cf)), p10=float(np.percentile(cf,10)),
            p50=float(np.percentile(cf,50)), p90=float(np.percentile(cf,90)),
        )

    # Physical m_dot estimate for NTU
    rho_A_in = air_density(cfg['T_inA'], cfg['P_inA'])
    cp_A = air_cp(cfg['T_inA']); cp_B = air_cp(cfg['T_inB'])

    # NTU bound check
    m_A_phys_est = rho_A_in * cfg['u_A'] * H * Lz  # full face A
    C_A = m_A_phys_est * cp_A
    m_B_phys_est = air_density(cfg['T_inB'], cfg['P_inB']) * cfg['u_B'] * L * Lz
    if not cfg['fluid_B_cfg']['in_w'] > 0.1:  # partial
        m_B_phys_est *= (0.042 / 0.182)  # inlet width ratio
    C_B = m_B_phys_est * cp_B
    C_min = min(C_A, C_B)
    C_max = max(C_A, C_B)
    C_r = C_min / C_max

    row = dict(
        label=label,
        u_A=cfg['u_A'], u_B=cfg['u_B'],
        partial_B=cfg['fluid_B_cfg']['in_w'] < 0.1,
        T_A_out=round(T_A, 1), T_B_out=round(T_B, 1),
        dT_margin=round(dT, 1),
        Q=r['Q'],
        Q_sA=r.get('Q_sA', float('nan')),
        Q_sB=r.get('Q_sB', float('nan')),
        Q_enth_A=r.get('Q_enthalpy_A', 0),
        Q_enth_B=r.get('Q_enthalpy_B', 0),
        dP_A=r.get('dP_A', 0), dP_B=r.get('dP_B', 0),
        energy_imbal=r.get('energy_imbalance_rel', float('nan')),
        elapsed_s=int(elapsed),
        **chi_stats,
    )
    # ε-NTU check
    dT_max = cfg['T_inA'] - cfg['T_inB']
    if dT_max > 0:
        row['eps_obs'] = round((T_B - cfg['T_inB']) / dT_max, 4)
        row['eps_max'] = round(1 - np.exp(-5 * C_r) if C_r < 0.99 else 0.5, 4)
    else:
        row['eps_obs'] = float('nan'); row['eps_max'] = float('nan')

    return row


def main():
    print("=" * 80)
    print("Phase 3a: χ_B Air-Air 5-case subset validation")
    print("=" * 80)

    results = []
    for label, u_A, u_B, T_inA, T_inB, P_inA, P_inB, partial_B in CASES:
        cfg = make_cfg(u_A, u_B, T_inA, T_inB, P_inA, P_inB, partial_B)
        print(f"\n--- {label} (u_A={u_A}, u_B={u_B}, partial_B={partial_B}) ---")
        row = run_case(label, cfg)
        results.append(row)
        # Quick per-case verdict
        verdict = "PASS" if row['dT_margin'] > 1.0 else ("FRAGILE" if row['dT_margin'] > 0 else "FAIL")
        print(f"  T_A={row['T_A_out']} T_B={row['T_B_out']} dT={row['dT_margin']} "
              f"Q={row['Q']:.0f} chi_p50={row.get('p50','N/A')} → {verdict}")

    # ── Summary table ──
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    header = (f"{'Case':<18} {'T_A':>6} {'T_B':>6} {'dT':>6} {'Q':>8} "
              f"{'Q_sA':>8} {'Q_sB':>8} {'dP_A':>8} {'dP_B':>8} "
              f"{'χ_p50':>7} {'χ_mn':>7} {'ε_obs':>7} {'Verdict':>10}")
    print(header)
    print("-" * len(header))
    all_pass = True
    for r in results:
        v = "PASS" if r['dT_margin'] > 1.0 else ("FRAGILE" if r['dT_margin'] > 0 else "FAIL")
        if v != "PASS":
            all_pass = False
        print(f"{r['label']:<18} {r['T_A_out']:>6.1f} {r['T_B_out']:>6.1f} "
              f"{r['dT_margin']:>6.1f} {r['Q']:>8.1f} "
              f"{r['Q_sA'] or 0:>8.1f} {r['Q_sB'] or 0:>8.1f} "
              f"{r['dP_A']:>8.0f} {r['dP_B']:>8.0f} "
              f"{r.get('p50','?'):>7} {r.get('mean','?'):>7} "
              f"{r.get('eps_obs','?'):>7} {v:>10}")

    # ── Pass/fail criteria ──
    print(f"\nPass criteria check:")
    all_dT_ok = all(r['dT_margin'] > 0 for r in results)
    print(f"  All T_B < T_A: {'PASS' if all_dT_ok else 'FAIL'}")
    min_dT = min(r['dT_margin'] for r in results)
    print(f"  min(dT_margin) = {min_dT:.1f} K {'> 1K: PASS' if min_dT > 1 else 'FRAGILE' if min_dT > 0 else 'FAIL'}")
    # ε check
    for r in results:
        if r.get('eps_obs') and r.get('eps_max'):
            ok = r['eps_obs'] <= r['eps_max'] + 0.05
            print(f"  {r['label']}: ε_obs={r['eps_obs']:.3f} ≤ ε_max={r['eps_max']:.3f} {'✓' if ok else '✗'}")

    # Write log
    log_path = ROOT / "validation" / "shanghai_chi_b_subset_v3.log"
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write("Phase 3a χ_B subset validation log\n")
        f.write("=" * 60 + "\n")
        for r in results:
            f.write(json.dumps(r, default=str) + "\n")
    print(f"\nLog: {log_path}")

    return 0 if all_pass and all_dT_ok and min_dT > 0 else 1


if __name__ == '__main__':
    sys.exit(main())
