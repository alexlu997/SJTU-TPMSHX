"""
compare_fast_vs_full.py — V1 verification for optimizer fast mode.

Runs the same decision vector through evaluate() twice:
  1. full-mode (DEFAULT_CONFIG, max_iter=5000, tol=1e-5, n_rho_loops=3, alpha=0.8)
  2. fast-mode (fast_mode=True → max_iter=800, tol=1e-3, n_rho_loops=1, alpha=1.5)

Reports:
  - Wall-time speedup
  - Relative Q, dP, mass deviations
  - Acceptance: Q err < 5%, dP err < 10%

Runs for both Gyroid and Diamond on the Shanghai-like small test config,
and for both uniform and hand-designed graded x vectors.

Usage:
    cd thermoNas && PYTHONPATH=. python validation/compare_fast_vs_full.py
"""
from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

_HERE = Path(__file__).resolve()
_THERMONAS = _HERE.parent.parent
if str(_THERMONAS) not in sys.path:
    sys.path.insert(0, str(_THERMONAS))

warnings.filterwarnings('ignore')

import numpy as np

from optimization.optimizer import evaluate, DEFAULT_CONFIG


BASE_CFG = dict(DEFAULT_CONFIG)
BASE_CFG.update({
    'L_domain': 0.1,
    'H_domain': 0.04,
    'L0': 6.0,
    't0': 0.4,
    'u_A': 5.0,
    'u_B': 3.0,
    'T_inA': 500.0,
    'T_inB': 350.0,
    'wall_refine': False,
})

Q_ERR_TOL = 5.0    # percent
DP_ERR_TOL = 10.0  # percent


def _design_uniform(cfg):
    return np.tile([cfg['L0'], cfg['t0']], 18)


def _design_graded():
    x = np.zeros(36)
    for k in range(9):         # inlet: small L, thick t
        x[2*k] = 4.0; x[2*k+1] = 0.5
    for k in range(9, 18):     # outlet: large L, thin t
        x[2*k] = 8.0; x[2*k+1] = 0.3
    return x


def _time_eval(x, cfg):
    t0 = time.time()
    Q_neg, dP, mass = evaluate(x, cfg)
    dt = time.time() - t0
    return dict(Q=-Q_neg, dP=dP, mass=mass, wall_s=dt)


def compare_one(tpms, x_name, x):
    cfg_full = {**BASE_CFG, 'tpms_type': tpms, 'fast_mode': False}
    cfg_fast = {**BASE_CFG, 'tpms_type': tpms, 'fast_mode': True}
    print(f"\n--- {tpms} · {x_name} ---")
    full = _time_eval(x, cfg_full)
    print(f"  full: Q={full['Q']:.2f}  dP={full['dP']:.2f}  mass={full['mass']:.4f}  "
          f"wall={full['wall_s']:.1f}s")
    fast = _time_eval(x, cfg_fast)
    print(f"  fast: Q={fast['Q']:.2f}  dP={fast['dP']:.2f}  mass={fast['mass']:.4f}  "
          f"wall={fast['wall_s']:.1f}s")

    q_err = (fast['Q'] - full['Q']) / full['Q'] * 100
    dp_err = (fast['dP'] - full['dP']) / full['dP'] * 100
    speedup = full['wall_s'] / max(fast['wall_s'], 1e-9)
    q_pass = abs(q_err) <= Q_ERR_TOL
    dp_pass = abs(dp_err) <= DP_ERR_TOL
    overall = '[PASS]' if (q_pass and dp_pass) else '[FAIL]'
    print(f"  delta: Q {q_err:+.2f}% ({'OK' if q_pass else 'FAIL'})  "
          f"dP {dp_err:+.2f}% ({'OK' if dp_pass else 'FAIL'})  "
          f"speedup {speedup:.1f}x   {overall}")
    return dict(tpms=tpms, x_name=x_name,
                full=full, fast=fast,
                q_err_pct=q_err, dp_err_pct=dp_err,
                speedup=speedup, q_pass=q_pass, dp_pass=dp_pass)


def main():
    print("=" * 66)
    print("V1 · fast-mode vs full-mode single-point comparison")
    print("Acceptance: Q err < 5%, dP err < 10%")
    print("=" * 66)

    results = []
    for tpms in ('Gyroid', 'Diamond'):
        cfg_tmp = {**BASE_CFG, 'tpms_type': tpms}
        for x_name, x in (('uniform', _design_uniform(cfg_tmp)),
                          ('graded',  _design_graded())):
            results.append(compare_one(tpms, x_name, x))

    print("\n" + "=" * 66)
    print("SUMMARY")
    print("=" * 66)
    print(f"{'TPMS':<8} {'Design':<10} {'Q Δ%':>8} {'dP Δ%':>8} {'speedup':>10} {'verdict':>10}")
    for r in results:
        verdict = 'PASS' if (r['q_pass'] and r['dp_pass']) else 'FAIL'
        print(f"{r['tpms']:<8} {r['x_name']:<10} "
              f"{r['q_err_pct']:>+8.2f} {r['dp_err_pct']:>+8.2f} "
              f"{r['speedup']:>9.1f}× {verdict:>10}")

    all_pass = all(r['q_pass'] and r['dp_pass'] for r in results)
    mean_speedup = np.mean([r['speedup'] for r in results])
    print(f"\nAll cases: {'PASS' if all_pass else 'FAIL'}")
    print(f"Mean speedup: {mean_speedup:.1f}×")
    return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(main())
