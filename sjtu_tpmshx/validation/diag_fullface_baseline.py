"""
P0: Full-face B baseline diagnostic (χ_B ≡ 1).

Locate Q_enth/Q_solid mismatch root cause before any χ_B sweep.
"""
import os, sys, time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runs.run_calculation_3d import _run_3d_stack

L, H, Lz = 0.182, 0.042, 0.042
Nx = Ny = Nz = 20

cfg = dict(
    L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
    u_A=10.0, u_B=20.0, T_inA=422.0, T_inB=322.0,
    P_inA=192362.0, P_inB=101325.0,
    tpms_type='Gyroid', Lcell=7.0, t_wall=0.6, k_s=16.0, eps=0.85,
    fluid_A_cfg=dict(dir=0, in_ctr=0.021, in_w=0.042,
                     out_ctr=0.021, out_w=0.042,
                     in_z_ctr=0.021, in_z_w=0.042,
                     out_z_ctr=0.021, out_z_w=0.042),
    fluid_B_cfg=dict(dir=3, in_ctr=0.091, in_w=0.182,   # FULL face
                     out_ctr=0.091, out_w=0.182,
                     in_z_ctr=0.021, in_z_w=0.042,
                     out_z_ctr=0.021, out_z_w=0.042),
    fluid_type_A='air', fluid_type_B='air',
    wall_refine_3d=False,
    # Bypass χ_B: α=0 → v_thr=0 → sigmoid(|u|/σ) ≈ 1 for all |u|>0
    chi_alpha=0.0,
)

print("=" * 70)
print("P0: Full-face B baseline (χ_B bypass)")
print("=" * 70)
t0 = time.time()
r = _run_3d_stack(cfg)
elapsed = time.time() - t0

# ── Extract all diagnostics ──
T_A_out = r['T_A_out']; T_B_out = r['T_B_out']
Q = r['Q']
Q_sA = r.get('Q_sA', float('nan'))
Q_sB = r.get('Q_sB', float('nan'))
Q_enth_A = r.get('Q_enthalpy_A', 0)
Q_enth_B = r.get('Q_enthalpy_B', 0)
Q_sA_int = r.get('Q_sA_interior', float('nan'))
Q_sB_int = r.get('Q_sB_interior', float('nan'))
dP_A = r.get('dP_A', 0)
dP_B = r.get('dP_B', 0)
e_imbal = r.get('energy_imbalance_rel', float('nan'))
m_imbal_A = r.get('mass_imbalance_rel_A', float('nan'))
m_imbal_B = r.get('mass_imbalance_rel_B', float('nan'))
chi = r.get('chi_B')

print(f"\nElapsed: {elapsed:.0f}s")
print(f"\n{'='*50}")
print(f"TEMPERATURE")
print(f"{'='*50}")
print(f"  T_A_out = {T_A_out:.2f} K")
print(f"  T_B_out = {T_B_out:.2f} K")
print(f"  dT = T_A-T_B = {T_A_out - T_B_out:.2f} K")
print(f"  T_B < T_A: {T_B_out < T_A_out}")

print(f"\n{'='*50}")
print(f"Q — SOLID-SOURCE (volume integral)")
print(f"{'='*50}")
print(f"  Q_solid_A  = {Q_sA:.1f} W  (∫ h_vA·(Ts-Ta)·dV)")
print(f"  Q_solid_B  = {Q_sB:.1f} W  (∫ h_vB·(Ts-Tb)·dV)")
print(f"  Q_sA + Q_sB = {Q_sA + Q_sB:.1f} W  (solid balance)")
print(f"  Q_sA_interior = {Q_sA_int:.1f} W  (BC layer excluded)")
print(f"  Q_sB_interior = {Q_sB_int:.1f} W  (BC layer excluded)")

print(f"\n{'='*50}")
print(f"Q — ENTHALPY (m_dot·cp·ΔT) [LTNE m_dot = ε_f·ρ·u·A]")
print(f"{'='*50}")
print(f"  Q_enth_A_ltne = {Q_enth_A:.1f} W")
print(f"  Q_enth_B_ltne = {Q_enth_B:.1f} W")
print(f"  Q (primary)   = {Q:.1f} W  [mean(Q_enth_A, Q_enth_B)]")

print(f"\n{'='*50}")
print(f"CONSISTENCY CHECKS")
print(f"{'='*50}")
# Solid vs enthalpy
gap_A = abs(Q_sA) - Q_enth_A if Q_enth_A > 0 else 0
gap_B = abs(Q_sB) - Q_enth_B if Q_enth_B > 0 else 0
rel_gap_A = gap_A / max(abs(Q_sA), 1.0)
rel_gap_B = gap_B / max(abs(Q_sB), 1.0)
print(f"  |Q_sA| - Q_enth_A_ltne = {gap_A:.1f} W  ({rel_gap_A*100:.1f}%)")
print(f"  |Q_sB| - Q_enth_B_ltne = {gap_B:.1f} W  ({rel_gap_B*100:.1f}%)")
# BC-layer pinning check
if not np.isnan(Q_sA_int):
    bc_pin_A = abs(Q_sA) - abs(Q_sA_int)
    print(f"  BC-layer pinning A: |Q_sA| - |Q_sA_interior| = {bc_pin_A:.1f} W")
if not np.isnan(Q_sB_int):
    bc_pin_B = abs(Q_sB) - abs(Q_sB_int)
    print(f"  BC-layer pinning B: |Q_sB| - |Q_sB_interior| = {bc_pin_B:.1f} W")
print(f"  energy_imbalance_rel = {e_imbal:.6f}")
print(f"  mass_imbalance_rel_A = {m_imbal_A:.6f}")
print(f"  mass_imbalance_rel_B = {m_imbal_B:.6f}")

print(f"\n{'='*50}")
print(f"dP")
print(f"{'='*50}")
print(f"  dP_A = {dP_A:.0f} Pa")
print(f"  dP_B = {dP_B:.0f} Pa")

if chi is not None:
    cf = chi.ravel()
    print(f"\n{'='*50}")
    print(f"χ_B (should be ≈1 for baseline)")
    print(f"{'='*50}")
    print(f"  min={cf.min():.4f}  p10={np.percentile(cf,10):.4f}  "
          f"p50={np.percentile(cf,50):.4f}  p90={np.percentile(cf,90):.4f}  "
          f"max={cf.max():.4f}  mean={cf.mean():.4f}")

# ── Root cause assessment ──
print(f"\n{'='*50}")
print(f"ROOT CAUSE ASSESSMENT")
print(f"{'='*50}")
issues = []
if abs(gap_A) > 0.15 * max(abs(Q_sA), 1):
    issues.append(f"A-side enth-solid gap {rel_gap_A*100:.0f}% > 15%")
if abs(gap_B) > 0.15 * max(abs(Q_sB), 1):
    issues.append(f"B-side enth-solid gap {rel_gap_B*100:.0f}% > 15%")
if abs(Q_sA + Q_sB) > 0.05 * max(abs(Q_sA), abs(Q_sB)):
    issues.append("Solid energy imbalance > 5%")
if T_B_out > T_A_out:
    issues.append("Second-law violation: T_B > T_A")
if not np.isnan(Q_sA_int) and abs(Q_sA) - abs(Q_sA_int) > 0.2 * abs(Q_sA):
    issues.append(f"BC-layer pinning > 20% of Q_sA")
if not np.isnan(Q_sB_int) and abs(Q_sB) - abs(Q_sB_int) > 0.2 * abs(Q_sB):
    issues.append(f"BC-layer pinning > 20% of Q_sB")

if issues:
    print("Issues found:")
    for i in issues:
        print(f"  ✗ {i}")
else:
    print("  No critical issues — full-face baseline is consistent.")
