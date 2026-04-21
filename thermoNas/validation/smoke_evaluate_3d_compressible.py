"""smoke_evaluate_3d_compressible.py — one-shot evaluate_3d call with new default ideal_gas.

Verifies optimizer.evaluate_3d doesn't crash with fluid_type='ideal_gas' default
+ new P_ref_B seed, and prints Q/dP sanity.
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

from optimization.optimizer import evaluate_3d


def main():
    # Small Shanghai-like cfg
    cfg = {
        'tpms_type': 'Gyroid',
        'L0': 7.0, 't0': 0.6, 'k_s': 16.0,
        'L_domain': 0.10, 'H_domain': 0.04, 'Lz': 0.02,
        'Nx': 14, 'Ny': 10, 'Nz': 3,
        'u_A': 20.0, 'u_B': 1.0,
        'T_inA': 400.0, 'T_inB': 300.0,
        'y_trans_inlet': 0.2, 'y_trans_outlet': 0.2,
        'fix_L': True, 'fix_t': True,
        'max_iter_simple': 400, 'tol_simple': 1e-3,
        'max_outer_3d': 2, 'couple_3d': True,
        'wall_refine_3d': False,
        'dim': 3,
    }
    # 108-d uniform decision vector
    x = np.full(108, 0.5)

    print(f"Invoking evaluate_3d with grid {cfg['Nx']}×{cfg['Ny']}×{cfg['Nz']}...")
    neg_Q, dP_total, mass = evaluate_3d(x, cfg)
    Q_total = -neg_Q
    print("evaluate_3d returned:")
    print(f"  Q_total  = {Q_total:.6g} W")
    print(f"  dP_total = {dP_total:.6g} Pa")
    print(f"  mass     = {mass:.6g}")

    assert np.isfinite(Q_total), f"Q_total not finite: {Q_total}"
    assert np.isfinite(dP_total), f"dP_total not finite: {dP_total}"
    assert dP_total > 0, f"dP_total should be > 0, got {dP_total}"
    print("\nSMOKE PASS: evaluate_3d with compressible default OK.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
