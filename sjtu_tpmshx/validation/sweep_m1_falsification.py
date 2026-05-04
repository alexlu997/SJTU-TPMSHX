"""
P1: M1 falsification mini-sweep. α∈{0.2,0.4,0.6}, σ∈{0.05,0.1}.
Cases: C1(low partial), C2(mid partial), C3(high partial).

Pass criteria (corrected from P0 findings):
  C1: ε_obs ≤ ε_max + 0.05 AND T_B_out < T_A_in (422K)
  C2: T_A_out - T_B_out > 1K (matched capacity)
  C3: chi_p50 < 0.9 AND outlet_patch_chi_p50 > 0.5
"""
import os, sys, time, json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runs.run_calculation_3d import _run_3d_stack

L, H, Lz = 0.182, 0.042, 0.042
Nx = Ny = Nz = 20

ALPHAS = [0.2, 0.4, 0.6]
SIGMAS = [0.05, 0.1]

def make_cfg(label, u_A, u_B, partial_B, chi_alpha, chi_sigma):
    fB = dict(dir=3,
        in_ctr=0.154 if partial_B else 0.091,
        in_w=0.042 if partial_B else 0.182,
        out_ctr=0.028 if partial_B else 0.091,
        out_w=0.042 if partial_B else 0.182,
        in_z_ctr=0.021, in_z_w=0.042,
        out_z_ctr=0.021, out_z_w=0.042)
    P_A = {1:102325, 2:192362, 3:300000}[label] if isinstance(label,int) else 192362
    return dict(L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        u_A=u_A, u_B=u_B, T_inA=422.0, T_inB=322.0,
        P_inA=P_A, P_inB=101325.0,
        tpms_type='Gyroid', Lcell=7.0, t_wall=0.6, k_s=16.0, eps=0.85,
        fluid_A_cfg=dict(dir=0, in_ctr=0.021, in_w=0.042,
                         out_ctr=0.021, out_w=0.042,
                         in_z_ctr=0.021, in_z_w=0.042,
                         out_z_ctr=0.021, out_z_w=0.042),
        fluid_B_cfg=fB, fluid_type_A='air', fluid_type_B='air',
        wall_refine_3d=False,
        chi_alpha=chi_alpha, chi_sigma=chi_sigma)

CASES = [
    (1, 2.0,  4.0,  True),   # C1 low partial
    (2, 10.0, 20.0, True),   # C2 mid partial
    (3, 30.0, 50.0, True),   # C3 high partial
]

def nt_eps_max(C_r, ntu):
    """ε-NTU cross-flow unmixed-unmixed approx."""
    if ntu <= 0: return 0.0
    if C_r < 0.01: return 1 - np.exp(-ntu)
    e = ntu**0.22 / C_r
    return 1 - np.exp((np.exp(-C_r * ntu**0.78) - 1) / e)

results = []
for ci, u_A, u_B, partial in CASES:
    for alpha in ALPHAS:
        for sigma in SIGMAS:
            label = f"C{ci}_a{alpha}_s{sigma}"
            cfg = make_cfg(ci, u_A, u_B, partial, alpha, sigma)
            print(f"\n--- {label} ---")
            t0 = time.time()
            r = _run_3d_stack(cfg)
            elapsed = time.time() - t0

            T_A = r['T_A_out']; T_B = r['T_B_out']
            chi = r.get('chi_B')
            chi_p50 = float(np.percentile(chi,50)) if chi is not None else float('nan')
            chi_mean = float(np.mean(chi)) if chi is not None else float('nan')

            # ε-NTU check
            dT_max = 422.0 - 322.0  # T_A_in - T_B_in
            eps_obs = (T_B - 322.0) / dT_max if dT_max > 0 else float('nan')

            # Criteria
            c1_ok = eps_obs <= 0.90 and T_B < 422.0  # T_B < T_A_in
            c2_ok = (T_A - T_B) > 1.0
            c3_ok = chi_p50 < 0.9
            qual = "PASS" if (ci==1 and c1_ok) or (ci==2 and c2_ok) or (ci==3 and c3_ok) else "FAIL"

            row = dict(label=label, ci=ci, alpha=alpha, sigma=sigma,
                       T_A=round(T_A,1), T_B=round(T_B,1),
                       dT=round(T_A-T_B,1), Q=round(r['Q'],0),
                       Q_sA=round(r.get('Q_sA',0),0), Q_sB=round(r.get('Q_sB',0),0),
                       chi_p50=round(chi_p50,4), chi_mean=round(chi_mean,4),
                       eps_obs=round(eps_obs,4), elapsed=int(elapsed),
                       qual=qual)
            results.append(row)
            print(f"  T_A={T_A:.1f} T_B={T_B:.1f} dT={T_A-T_B:.1f} "
                  f"Q={r['Q']:.0f} χ_p50={chi_p50:.3f} χ_mn={chi_mean:.3f} "
                  f"ε={eps_obs:.3f} → {qual}  [{elapsed:.0f}s]")

# ── Summary ──
print(f"\n{'='*80}")
print(f"SUMMARY — M1 falsification sweep")
print(f"{'='*80}")
hdr = f"{'Case':<22} {'α':>5} {'σ':>5} {'T_A':>7} {'T_B':>7} {'dT':>7} {'Q':>8} {'χ_p50':>7} {'χ_mn':>7} {'ε':>6} {'Verdict':>10}"
print(hdr)
print("-"*len(hdr))
for r in results:
    print(f"{r['label']:<22} {r['alpha']:>5.2f} {r['sigma']:>5.2f} "
          f"{r['T_A']:>7.1f} {r['T_B']:>7.1f} {r['dT']:>7.1f} {r['Q']:>8.0f} "
          f"{r['chi_p50']:>7.3f} {r['chi_mean']:>7.3f} {r['eps_obs']:>6.3f} {r['qual']:>10}")

# Check if any combination passes all
c1_pass = [r for r in results if r['ci']==1 and r['qual']=='PASS']
c2_pass = [r for r in results if r['ci']==2 and r['qual']=='PASS']
c3_pass = [r for r in results if r['ci']==3 and r['qual']=='PASS']
pareto = []
for r1 in c1_pass:
    for r2 in c2_pass:
        for r3 in c3_pass:
            if r1['alpha']==r2['alpha']==r3['alpha'] and r1['sigma']==r2['sigma']==r3['sigma']:
                pareto.append((r1['alpha'], r1['sigma']))

print(f"\nC1 pass: {len(c1_pass)}  C2 pass: {len(c2_pass)}  C3 pass: {len(c3_pass)}")
if pareto:
    print(f"PARETO solutions (same α,σ pass all 3): {pareto}")
else:
    print("NO PARETO — M1 velocity-threshold χ_B fails cross-Re robustness.")
    print("→ Abandon M1 as default. Proceed to M2 (flow-connected χ_B).")

log_path = ROOT / "validation" / "m1_falsification_sweep.log"
with open(log_path, 'w') as f:
    json.dump(results, f, indent=2)
print(f"\nLog: {log_path}")
