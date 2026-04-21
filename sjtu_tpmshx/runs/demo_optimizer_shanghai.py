"""
demo_optimizer_shanghai.py — End-to-end optimizer demonstration.

Small-scale design search on a Shanghai-like configuration:
- Gyroid TPMS, 100×40 mm rectangular domain
- Fluid A (hot, T_inA = 500 K) + Fluid B (cold, T_inB = 350 K)
- Sigmoid continuous L, t field (18×2 = 36 decision vars)
- NSGA-II for Pareto (Q vs dP)

Runs:
  1. Baseline uniform geometry — reference point
  2. Graded handcrafted design — sanity check on directionality
  3. NSGA-II optimization (8 gen × 12 pop = 96 evals)
  4. Save results + plot Pareto + L/t fields for best-Q and best-dP designs

Wall time: ~15 min on 1 CPU, or ~3 min parallel.

Outputs (written to sjtu_tpmshx/runs/demo_output/):
    summary.json           — config + baseline values
    pareto.csv             — final Pareto front (X, F)
    pareto.png             — Q vs dP scatter
    best_q_field.png       — L, t field of best-Q design
    best_dp_field.png      — L, t field of best-dP design
    convergence.png        — Q/dP hypervolume vs generation
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

warnings.filterwarnings('ignore')

from optimization.optimizer import (
    DEFAULT_CONFIG, evaluate, run_optimization,
    plot_pareto as _plot_pareto_opt,
    plot_design_field as _plot_design_field_opt)


def make_config():
    """Shanghai-like small test case, tuned for demo speed."""
    cfg = dict(DEFAULT_CONFIG)
    cfg.update({
        'tpms_type': 'Gyroid',
        'L_domain':  0.1,      # m — downscaled from Shanghai's 0.231
        'H_domain':  0.04,     # m — downscaled from Shanghai's 0.042
        'L0':        6.0,      # mm — uniform baseline cell size
        't0':        0.4,      # mm — uniform baseline wall thickness
        'u_A':       5.0,
        'u_B':       3.0,
        'T_inA':     500.0,
        'T_inB':     350.0,
        'dir_A':     0,
        'dir_B':     3,
        # Speed knobs for e2e demo (trade accuracy for wall time)
        'wall_refine':    False,
        'use_continuous': True,
        'use_richardson': False,
        'reeval_pareto':  False,
    })
    return cfg


def run_baselines(cfg):
    """Evaluate uniform + graded hand-designs. Returns dict of (Q, dP, mass)."""
    results = {}

    x_uniform = np.tile([cfg['L0'], cfg['t0']], 18)
    t0 = time.time()
    Q_neg, dP, mass = evaluate(x_uniform, cfg)
    results['uniform'] = dict(
        x=x_uniform.tolist(), Q=-Q_neg, dP=dP, mass=mass,
        wall_s=time.time() - t0,
    )
    print(f"[baseline] uniform  Q={-Q_neg:.1f} W/m  dP={dP:.1f} Pa  "
          f"mass={mass:.4f} kg/m  ({time.time()-t0:.1f}s)")

    # Graded: dense inlet (small L, thick t), open outlet (large L, thin t)
    x_graded = np.zeros(36)
    for k in range(9):                 # inlet 3x3
        x_graded[2*k]   = 4.0
        x_graded[2*k+1] = 0.5
    for k in range(9, 18):             # outlet 3x3
        x_graded[2*k]   = 8.0
        x_graded[2*k+1] = 0.3
    t0 = time.time()
    Q_neg, dP, mass = evaluate(x_graded, cfg)
    results['graded'] = dict(
        x=x_graded.tolist(), Q=-Q_neg, dP=dP, mass=mass,
        wall_s=time.time() - t0,
    )
    print(f"[baseline] graded   Q={-Q_neg:.1f} W/m  dP={dP:.1f} Pa  "
          f"mass={mass:.4f} kg/m  ({time.time()-t0:.1f}s)")

    return results


def plot_pareto(result, baselines, out_dir):
    """Thin wrapper: delegate to optimizer.plot_pareto with demo baselines."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    bl = {k: {'Q': v['Q'], 'dP': v['dP']} for k, v in baselines.items()}
    fig = _plot_pareto_opt(
        result, baselines=bl,
        title=f"Optimizer e2e demo — Gyroid 100×40mm, {len(result['F'])} solutions",
        save_path=os.path.join(out_dir, 'pareto.png'))
    plt.close(fig)


def plot_field(x, cfg, title, path):
    """Thin wrapper: delegate to optimizer.plot_design_field."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig = _plot_design_field_opt(x, cfg, title=title, save_path=path)
    plt.close(fig)


def main():
    cfg = make_config()
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'demo_output')
    os.makedirs(out_dir, exist_ok=True)

    print(f"=== Optimizer e2e demo ===")
    print(f"Config: {cfg['tpms_type']}  "
          f"{cfg['L_domain']*1000:.0f}x{cfg['H_domain']*1000:.0f} mm  "
          f"u_A={cfg['u_A']}  u_B={cfg['u_B']}  "
          f"T_inA={cfg['T_inA']}  T_inB={cfg['T_inB']}")
    print(f"Output: {out_dir}")
    print()

    # Baselines
    print("--- Baselines ---")
    baselines = run_baselines(cfg)

    # Optimization
    print()
    print("--- NSGA-II (8 gen × 12 pop = 96 evals) ---")
    t_opt = time.time()
    result = run_optimization(cfg, n_gen=8, pop_size=12, seed=42,
                               verbose=True, save_dir=out_dir)
    print(f"[optimization] wall = {time.time()-t_opt:.1f}s")

    F = result['F']
    X = result['X']
    Q_arr = -F[:, 0]
    dP_arr = F[:, 1]
    idx_best_Q = int(np.argmax(Q_arr))
    idx_best_dP = int(np.argmin(dP_arr))

    print(f"\n--- Summary ---")
    print(f"Baseline uniform:  Q={baselines['uniform']['Q']:.1f} "
          f"dP={baselines['uniform']['dP']:.1f}")
    print(f"Baseline graded :  Q={baselines['graded']['Q']:.1f} "
          f"dP={baselines['graded']['dP']:.1f}")
    print(f"Pareto best-Q  :  Q={Q_arr[idx_best_Q]:.1f} "
          f"dP={dP_arr[idx_best_Q]:.1f}")
    print(f"Pareto best-dP :  Q={Q_arr[idx_best_dP]:.1f} "
          f"dP={dP_arr[idx_best_dP]:.1f}")

    # Save summary
    summary = dict(
        config=cfg,
        baselines=baselines,
        pareto_summary=dict(
            n=len(F),
            Q_range=[float(Q_arr.min()), float(Q_arr.max())],
            dP_range=[float(dP_arr.min()), float(dP_arr.max())],
            best_Q=dict(idx=idx_best_Q, Q=float(Q_arr[idx_best_Q]),
                        dP=float(dP_arr[idx_best_Q])),
            best_dP=dict(idx=idx_best_dP, Q=float(Q_arr[idx_best_dP]),
                         dP=float(dP_arr[idx_best_dP])),
        ),
        opt_wall_s=time.time() - t_opt,
    )
    with open(os.path.join(out_dir, 'summary.json'), 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"[save] {os.path.join(out_dir, 'summary.json')}")

    # Plots
    plot_pareto(result, baselines, out_dir)
    plot_field(X[idx_best_Q], cfg, f'Best-Q design (Q={Q_arr[idx_best_Q]:.0f})',
               os.path.join(out_dir, 'best_q_field.png'))
    plot_field(X[idx_best_dP], cfg, f'Best-dP design (dP={dP_arr[idx_best_dP]:.0f})',
               os.path.join(out_dir, 'best_dp_field.png'))

    print("\n=== e2e demo done ===")


if __name__ == '__main__':
    main()
