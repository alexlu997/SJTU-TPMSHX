"""runs/run_m2_rerank_m1.py — M2 gate 3: re-evaluate the M1 graded Pareto
under the VANS-corrected solver and quantify the ranking shift.

Plan §六 M2 完成判据之三（偏移量化）+ §七 双门之门 1: the M1 graded winners
are the steepest-ε-gradient designs and were originally evaluated WITHOUT
the ∇ε momentum terms. This script re-runs exactly those decision vectors
through the corrected evaluator and reports per-design (Q, dP) drift plus
Pareto-order changes.

Run (repo root):
  PYTHONHASHSEED=0 OMP_NUM_THREADS=1 PYTHONPATH=sjtu_tpmshx python -u \
      sjtu_tpmshx/runs/run_m2_rerank_m1.py

Output: reports/m1_uniform_vs_graded/m2_rerank.json / .csv
"""
from __future__ import annotations

import json
import os
import warnings

import numpy as np

from optimization.evaluator import evaluate_design
from optimization.optimizer_qnehvi import _pareto_mask_max
from runs.run_m1_uniform_vs_graded import CFG_M1

RUNS = {
    'seed42': 'reports/m1_uniform_vs_graded/qnehvi_m1/pareto_final.csv',
    'seed7': 'reports/m1_uniform_vs_graded/seed7_full/qnehvi_m1/pareto_final.csv',
    'seed123': 'reports/m1_uniform_vs_graded/seed123_full/qnehvi_m1/pareto_final.csv',
}
OUT = 'reports/m1_uniform_vs_graded'


def main() -> None:
    rows_out = []
    summary = {}
    for tag, path in RUNS.items():
        data = np.loadtxt(path, delimiter=',', skiprows=1)
        if data.ndim == 1:
            data = data[None, :]
        X = data[:, :-2]
        Q_old, dP_old = data[:, -2], data[:, -1]
        Q_new = np.empty_like(Q_old); dP_new = np.empty_like(dP_old)
        for k, x in enumerate(X):
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                Qn, dPn, _m = evaluate_design(np.asarray(x), dict(CFG_M1))
            Q_new[k] = -float(Qn); dP_new[k] = float(dPn)
            print(f"[M2-rerank] {tag}[{k}] Q {Q_old[k]:8.0f}→{Q_new[k]:8.0f} "
                  f"({(Q_new[k]/Q_old[k]-1)*100:+.2f}%)  "
                  f"dP {dP_old[k]:8.0f}→{dP_new[k]:8.0f} "
                  f"({(dP_new[k]/dP_old[k]-1)*100:+.2f}%)", flush=True)
            rows_out.append((tag, k, Q_old[k], dP_old[k], Q_new[k], dP_new[k]))

        # ranking metrics within this run's front
        dq = Q_new / Q_old - 1.0
        dp = dP_new / dP_old - 1.0
        # dP-order (the axis the Pareto is drawn in): does sorting change?
        order_old = np.argsort(dP_old).tolist()
        order_new = np.argsort(dP_new).tolist()
        # Pareto membership under the new numbers
        mask_new = _pareto_mask_max(np.column_stack([Q_new, -dP_new]))
        summary[tag] = {
            'n': int(len(X)),
            'dQ_pct_max_abs': float(np.max(np.abs(dq)) * 100),
            'dP_pct_max_abs': float(np.max(np.abs(dp)) * 100),
            'dQ_pct_mean': float(np.mean(dq) * 100),
            'dP_pct_mean': float(np.mean(dp) * 100),
            'dP_order_changed': order_old != order_new,
            'n_dropped_from_pareto': int(len(X) - mask_new.sum()),
        }
        print(f"[M2-rerank] {tag}: |dQ|max {summary[tag]['dQ_pct_max_abs']:.2f}% "
              f"|dP|max {summary[tag]['dP_pct_max_abs']:.2f}% "
              f"order_changed={summary[tag]['dP_order_changed']} "
              f"dropped={summary[tag]['n_dropped_from_pareto']}", flush=True)

    np.savetxt(os.path.join(OUT, 'm2_rerank.csv'),
               np.array([r[2:] for r in rows_out], dtype=np.float64),
               delimiter=',',
               header='Q_old,dP_old,Q_new,dP_new', comments='')
    with open(os.path.join(OUT, 'm2_rerank.json'), 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"[M2-rerank] DONE → {OUT}/m2_rerank.json", flush=True)


if __name__ == '__main__':
    main()
