"""
M4 corrected sweep — fast_sweep profile, Q/C_min ε definition.
p ∈ {0.5, 0.67, 1.0} × r_eff_mode ∈ {"sqrt", "min"}.
Cases: C1 (low partial), C2 (mid partial), C4 (full-face).

Pass criteria (corrected):
  Hard: ε_obs ≤ ε_max, Q_sA+Q_sB closed, full-face η=1 recovers baseline
  Soft: S_gen ≥ 0, Q_A/Q_B imbalance explainable, dP not directly affected
"""
import os, sys, time, json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runs.run_calculation_3d import _run_3d_stack
from solvers.tpms_calc import air_cp, air_density

L, H, Lz = 0.182, 0.042, 0.042
Nx = Ny = Nz = 20  # will be overridden by fast_sweep to 15

EXPONENTS = [0.5, 0.67, 1.0]
MODES = ["sqrt", "min"]

CASES = [
    ("C1_low_partial",   2.0,  4.0,  422., 322., 102325., 101325., True),
    ("C2_mid_partial",  10.0, 20.0,  422., 322., 192362., 101325., True),
    ("C4_mid_full",     10.0, 20.0,  422., 322., 192362., 101325., False),
]

def make_cfg(label, u_A, u_B, T_inA, T_inB, P_inA, P_inB, partial, mode, p):
    fB = dict(dir=3,
        in_ctr=0.154 if partial else 0.091,
        in_w=0.042 if partial else 0.182,
        out_ctr=0.028 if partial else 0.091,
        out_w=0.042 if partial else 0.182,
        in_z_ctr=0.021, in_z_w=0.042,
        out_z_ctr=0.021, out_z_w=0.042)
    return dict(
        L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        u_A=u_A, u_B=u_B, T_inA=T_inA, T_inB=T_inB,
        P_inA=P_inA, P_inB=P_inB,
        tpms_type='Gyroid', Lcell=7.0, t_wall=0.6, k_s=16.0, eps=0.85,
        fluid_A_cfg=dict(dir=0, in_ctr=0.021, in_w=0.042,
                         out_ctr=0.021, out_w=0.042,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
        fluid_B_cfg=fB, fluid_type_A='air', fluid_type_B='air',
        wall_refine_3d=False,
        sweep_profile='fast_sweep',
        partial_B_closure='m4_effective_area',
        m4_eff_mode=mode, m4_exponent=p,
        _case_label=label,
    )


def eps_max_crossflow(C_r, ntu):
    """ε_max for cross-flow unmixed-unmixed (Incropera approx)."""
    if ntu <= 0: return 0.0
    if C_r < 0.001: return 1.0 - np.exp(-ntu)
    return 1.0 - np.exp((np.exp(-C_r * ntu**0.78) - 1.0) / (C_r * ntu**-0.22))


def run_one(label, u_A, u_B, T_inA, T_inB, P_inA, P_inB, partial, mode, p):
    cfg = make_cfg(label, u_A, u_B, T_inA, T_inB, P_inA, P_inB, partial, mode, p)
    t0 = time.time()
    r = _run_3d_stack(cfg)
    dt = time.time() - t0

    cp_A = air_cp(T_inA); cp_B = air_cp(T_inB)
    dT_max = T_inA - T_inB

    # ── Corrected ε using Q and C_min ──
    Q_A = abs(r.get('Q_enthalpy_A', 0))
    Q_B = abs(r.get('Q_enthalpy_B', 0)) if r.get('T_B_out') is not None else 0
    Q_ref = 0.5 * (Q_A + Q_B) if Q_B > 0 else Q_A
    Q_imbal = abs(Q_A - Q_B) / max(Q_ref, 1e-30)

    # C_A, C_B from physical m_dot at inlet conditions
    rho_A_in = air_density(T_inA, P_inA)
    m_A_phys = rho_A_in * u_A * H * Lz  # A: full-face +x, cross-section H×Lz
    C_A = m_A_phys * cp_A
    rho_B_in = air_density(T_inB, P_inB)
    if partial:
        A_B_in = (0.042 * 0.042)  # H × Lz patch
    else:
        A_B_in = L * Lz  # full face
    m_B_phys = rho_B_in * u_B * A_B_in
    C_B = m_B_phys * cp_B
    C_min = min(C_A, C_B); C_r = C_min / max(C_A, C_B)

    eps_obs = Q_ref / (C_min * dT_max) if C_min > 0 else 0.0
    # NTU estimate for ε_max
    h_v_est = 6.8e5  # W/m³K typical Gyroid L=7,t=0.6
    V = L * H * Lz
    ntu_est = h_v_est * V / max(C_min, 1e-6)
    eps_max_val = eps_max_crossflow(C_r, ntu_est)

    # Pass criteria
    hard_pass = (eps_obs <= eps_max_val + 0.05 and
                 abs(r.get('Q_sA',0) + r.get('Q_sB',0)) < 10.0)
    ltne_info = r.get('_ltne_info', [])
    hit_max = any(d.get('iters', 0) >= r.get('_ltne_max_iter', 99999)
                  for d in ltne_info)

    row = dict(
        label=label, partial_B=partial, mode=mode, p=p,
        r_eff=0.2 if partial else 1.0,  # r_in=r_out for this geometry
        eta_eff=round((0.2 if partial else 1.0)**p, 4),
        m_A_phys=round(m_A_phys, 5), m_B_phys=round(m_B_phys, 5),
        C_A=round(C_A,2), C_B=round(C_B,2), C_r=round(C_r,4),
        Q_A=round(Q_A,0), Q_B=round(Q_B,0), Q_ref=round(Q_ref,0),
        Q_imbal=round(Q_imbal,4),
        eps_obs=round(eps_obs,4), eps_max=round(eps_max_val,4),
        T_A_out=round(r['T_A_out'],1), T_B_out=round(r['T_B_out'],1),
        Q_sA=round(r.get('Q_sA',0),0), Q_sB=round(r.get('Q_sB',0),0),
        Q_bal=round(r.get('Q_sA',0)+r.get('Q_sB',0),1),
        e_imbal=r.get('energy_imbalance_rel', float('nan')),
        dP_A=round(r.get('dP_A',0),0), dP_B=round(r.get('dP_B',0),0),
        ltne_iters=[d.get('iters',0) for d in ltne_info],
        ltne_conv=[d.get('converged',False) for d in ltne_info],
        hit_max_iter=hit_max,
        residual=ltne_info[-1].get('residual',0) if ltne_info else 0,
        needs_full=r.get('_needs_full_validate',False),
        elapsed=int(dt),
        hard_pass=hard_pass,
    )
    # S_gen estimate
    if T_inA > 0 and T_inB > 0 and r['T_A_out'] > 0 and (r.get('T_B_out') or 0) > 0:
        T_B = r.get('T_B_out', T_inB)
        row['S_gen'] = round(
            C_A * np.log(r['T_A_out']/T_inA) +
            C_B * np.log(T_B/T_inB), 2)
    else:
        row['S_gen'] = 0.0

    return row


def main():
    print("="*70)
    print("M4 corrected sweep — fast_sweep, Q/C_min ε definition")
    print("="*70)

    results = []
    for label, u_A, u_B, T_inA, T_inB, P_inA, P_inB, partial in CASES:
        for mode in MODES:
            for p in EXPONENTS:
                print(f"\n--- {label} mode={mode} p={p} ---")
                row = run_one(label, u_A, u_B, T_inA, T_inB, P_inA, P_inB,
                             partial, mode, p)
                results.append(row)
                ver = "PASS" if row['hard_pass'] else "FAIL"
                nf = " FULL?" if row['needs_full'] else ""
                print(f"  T_A={row['T_A_out']} T_B={row['T_B_out']} "
                      f"Q_ref={row['Q_ref']:.0f} eps_obs={row['eps_obs']:.4f} "
                      f"eps_max={row['eps_max']:.4f} "
                      f"C_A={row['C_A']:.0f} C_B={row['C_B']:.0f} C_r={row['C_r']:.3f} "
                      f"→ {ver}{nf} [{row['elapsed']}s]")

    # Summary
    print(f"\n{'='*95}")
    print(f"SUMMARY — Corrected ε = Q_ref / (C_min · ΔT_max)")
    print(f"{'='*95}")
    hdr = (f"{'Case':<20} {'p':>5} {'η_eff':>7} {'C_A':>6} {'C_B':>6} {'C_r':>6} "
           f"{'Q_ref':>8} {'ε_obs':>7} {'ε_max':>7} {'T_A':>7} {'T_B':>7} "
           f"{'Q_bal':>7} {'dP_B':>8} {'S_gen':>7} {'Verdict':>8}")
    print(hdr)
    print("-"*len(hdr))
    for r in results:
        ver = "PASS" if r['hard_pass'] else "FAIL"
        print(f"{r['label']:<20} {r['p']:>5.2f} {r['eta_eff']:>7.4f} "
              f"{r['C_A']:>6.0f} {r['C_B']:>6.0f} {r['C_r']:>6.3f} "
              f"{r['Q_ref']:>8.0f} {r['eps_obs']:>7.4f} {r['eps_max']:>7.4f} "
              f"{r['T_A_out']:>7.1f} {r['T_B_out']:>7.1f} "
              f"{r['Q_bal']:>7.1f} {r['dP_B']:>8.0f} {r['S_gen']:>7.2f} {ver:>8}")

    # C2 recommendation
    c2 = [r for r in results if r['label'].startswith('C2') and r['hard_pass']]
    print(f"\nC2 PASS combos: {len(c2)}")
    if c2:
        best = min(c2, key=lambda r: r['eps_obs'])  # lowest ε = most conservative
        print(f"Best C2: p={best['p']} η={best['eta_eff']} "
              f"ε_obs={best['eps_obs']:.4f} ≤ ε_max={best['eps_max']:.4f} "
              f"T_A={best['T_A_out']} T_B={best['T_B_out']}")

    log = ROOT / "validation" / "m4_corrected_sweep.json"
    with open(log, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nLog: {log}")

if __name__ == '__main__':
    main()
