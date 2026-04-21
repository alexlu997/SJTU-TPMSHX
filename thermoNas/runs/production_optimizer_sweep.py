"""
production_optimizer_sweep.py — Scale-up NSGA-II run + Diamond vs Gyroid
comparison on the same Shanghai-like configuration.

Runs two independent optimizations back-to-back (Gyroid then Diamond),
saves each in a separate subdir, then writes a combined comparison report.

Scale: 30 gen × 24 pop = 720 evals per TPMS, parallel.
Expected wall time: ~30–60 min each (parallel), ~1–2 h total.

Output:
    runs/production_output/
      Gyroid/
        config.json, pareto_final.csv, pareto_gen*.csv,
        pareto.png, best_q_field.png, best_dp_field.png, summary.json
      Diamond/
        (same files)
      comparison.png            — Gyroid + Diamond Pareto overlay
      comparison_summary.json   — side-by-side metrics

Command: python runs/production_optimizer_sweep.py
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
    plot_pareto, plot_design_field)


# ── Shared configuration template ─────────────────────────────
# Keep all physics/geometry the same across Diamond / Gyroid so the
# only independent variable is TPMS type.
#
# fast_mode=True caps per-eval work (max_iter=800, tol=1e-3, n_rho=1,
# alpha=1.5) during the NSGA-II search; reeval_pareto=True then re-scores
# the final Pareto front at full accuracy (alpha=0.4 + max_iter=5000).
BASE_CONFIG = dict(
    L_domain=0.1,
    H_domain=0.04,
    L0=6.0,
    t0=0.4,
    u_A=5.0,
    u_B=3.0,
    T_inA=500.0,
    T_inB=350.0,
    dir_A=0,
    dir_B=3,
    k_s=17.0,
    wall_refine=False,
    use_continuous=True,
    use_richardson=False,
    fast_mode=True,
    reeval_pareto=True,
)

N_GEN = 30
POP_SIZE = 24
SEED = 42


def run_for_tpms(tpms, out_root, skip_if_done=True):
    """Run one full optimization for a single TPMS type. Returns result dict.

    If ``skip_if_done`` is True and an existing summary.json is found in
    ``out_root/<tpms>/``, reloads the cached result and plots instead of
    re-running the NSGA-II loop.
    """
    cfg = {**DEFAULT_CONFIG, **BASE_CONFIG, 'tpms_type': tpms}
    out_dir = os.path.join(out_root, tpms)
    os.makedirs(out_dir, exist_ok=True)

    summary_path = os.path.join(out_dir, 'summary.json')
    pareto_path = os.path.join(out_dir, 'pareto_final.csv')
    if skip_if_done and os.path.exists(summary_path) and os.path.exists(pareto_path):
        print(f"\n========== {tpms} (cached) ==========", flush=True)
        print(f"Reusing existing {summary_path}", flush=True)
        with open(summary_path) as f:
            summary = json.load(f)
        # pareto_final.csv layout: [Q_pos, dP, X(36)]; convert back to F = [-Q, dP]
        data = np.loadtxt(pareto_path, delimiter=',', skiprows=1)
        F = np.column_stack([-data[:, 0], data[:, 1]])
        X = data[:, 2:]
        return dict(result=dict(X=X, F=F), summary=summary, cfg=cfg)

    print(f"\n========== {tpms} ==========")
    print(f"Config: {cfg['L_domain']*1000:.0f}×{cfg['H_domain']*1000:.0f} mm, "
          f"u_A={cfg['u_A']}, u_B={cfg['u_B']}, "
          f"T_inA={cfg['T_inA']}, T_inB={cfg['T_inB']}")
    print(f"Scale : {N_GEN} gen × {POP_SIZE} pop = {N_GEN * POP_SIZE} evals")
    print(f"Output: {out_dir}")

    # Uniform baseline
    x_unif = np.tile([cfg['L0'], cfg['t0']], 18)
    t0 = time.time()
    Q_neg, dP, mass = evaluate(x_unif, cfg)
    baseline = dict(x=x_unif.tolist(), Q=-Q_neg, dP=dP, mass=mass,
                    wall_s=time.time() - t0)
    print(f"[baseline] uniform  Q={-Q_neg:.1f} W/m  dP={dP:.1f} Pa  "
          f"mass={mass:.4f} kg/m")

    # NSGA-II
    t0 = time.time()
    result = run_optimization(
        cfg, n_gen=N_GEN, pop_size=POP_SIZE, seed=SEED,
        verbose=True, save_dir=out_dir)
    opt_wall = time.time() - t0
    print(f"[optimization] wall = {opt_wall:.1f}s")

    F = result['F']
    X = result['X']
    Q_arr = -F[:, 0]
    dP_arr = F[:, 1]
    idx_best_Q = int(np.argmax(Q_arr))
    idx_best_dP = int(np.argmin(dP_arr))

    summary = dict(
        tpms=tpms,
        config=cfg,
        baseline=baseline,
        pareto=dict(
            n=len(F),
            Q_range=[float(Q_arr.min()), float(Q_arr.max())],
            dP_range=[float(dP_arr.min()), float(dP_arr.max())],
            best_Q=dict(idx=idx_best_Q, Q=float(Q_arr[idx_best_Q]),
                        dP=float(dP_arr[idx_best_Q])),
            best_dP=dict(idx=idx_best_dP, Q=float(Q_arr[idx_best_dP]),
                         dP=float(dP_arr[idx_best_dP])),
        ),
        opt_wall_s=opt_wall,
    )
    with open(os.path.join(out_dir, 'summary.json'), 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    # Plots (matplotlib Agg backend for headless-safe)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig = plot_pareto(
        result,
        baselines={'Uniform baseline': {'Q': baseline['Q'], 'dP': baseline['dP']}},
        title=f"{tpms} Pareto — {len(F)} sols, {N_GEN}×{POP_SIZE} evals",
        save_path=os.path.join(out_dir, 'pareto.png'))
    plt.close(fig)

    fig = plot_design_field(
        X[idx_best_Q], cfg,
        title=f"{tpms} · best-Q (Q={Q_arr[idx_best_Q]:.0f})",
        save_path=os.path.join(out_dir, 'best_q_field.png'))
    plt.close(fig)

    fig = plot_design_field(
        X[idx_best_dP], cfg,
        title=f"{tpms} · best-dP (dP={dP_arr[idx_best_dP]:.0f})",
        save_path=os.path.join(out_dir, 'best_dp_field.png'))
    plt.close(fig)

    return dict(result=result, summary=summary, cfg=cfg)


def plot_comparison(gyroid, diamond, out_path):
    """Overlay Gyroid + Diamond Pareto + baselines on one figure."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 6))

    for bag, color, marker, label in (
        (gyroid, 'tab:blue', 'o', 'Gyroid'),
        (diamond, 'tab:red', 's', 'Diamond'),
    ):
        F = bag['result']['F']
        Q = -F[:, 0]; dP = F[:, 1]
        ax.scatter(dP, Q, c=color, marker=marker, s=50, alpha=0.75,
                   edgecolors='k', linewidths=0.5,
                   label=f"{label} Pareto ({len(F)} sols)")
        b = bag['summary']['baseline']
        ax.scatter(b['dP'], b['Q'], c=color, marker='*', s=260,
                   edgecolor='k', linewidths=1.0,
                   label=f"{label} uniform baseline", zorder=5)

    ax.set_xlabel('Total Pressure Drop ΔP [Pa]', fontsize=12)
    ax.set_ylabel('Total Heat Transfer Q [W/m]', fontsize=12)
    ax.set_title('Gyroid vs Diamond — Pareto comparison', fontsize=14,
                 fontweight='bold')
    ax.grid(alpha=0.3)
    ax.legend(loc='best', fontsize=10)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"[plot] {out_path}")


def main():
    out_root = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'production_output')
    os.makedirs(out_root, exist_ok=True)

    print("=" * 62)
    print(f"Production sweep — Gyroid + Diamond  ({N_GEN}×{POP_SIZE} each)")
    print(f"Output root: {out_root}")
    print("=" * 62)

    t_all = time.time()
    gyroid = run_for_tpms('Gyroid', out_root)
    diamond = run_for_tpms('Diamond', out_root)

    # Combined comparison
    plot_comparison(gyroid, diamond, os.path.join(out_root, 'comparison.png'))

    combined = dict(
        n_gen=N_GEN, pop_size=POP_SIZE, seed=SEED,
        Gyroid=gyroid['summary'],
        Diamond=diamond['summary'],
        total_wall_s=time.time() - t_all,
    )
    with open(os.path.join(out_root, 'comparison_summary.json'), 'w') as f:
        json.dump(combined, f, indent=2, default=str)

    # Console side-by-side
    print("\n" + "=" * 62)
    print("COMPARISON SUMMARY")
    print("=" * 62)
    for tpms, bag in (('Gyroid', gyroid), ('Diamond', diamond)):
        b = bag['summary']['baseline']
        p = bag['summary']['pareto']
        lift_Q = (p['best_Q']['Q'] - b['Q']) / b['Q'] * 100
        lift_dP = (p['best_dP']['dP'] - b['dP']) / b['dP'] * 100
        print(f"\n{tpms}:")
        print(f"  Baseline uniform   Q={b['Q']:.1f}  dP={b['dP']:.1f}")
        print(f"  Pareto best-Q     Q={p['best_Q']['Q']:.1f} (+{lift_Q:.2f}%)  "
              f"dP={p['best_Q']['dP']:.1f}")
        print(f"  Pareto best-dP    Q={p['best_dP']['Q']:.1f}  "
              f"dP={p['best_dP']['dP']:.1f} ({lift_dP:+.2f}%)")
        print(f"  Pareto spread     Q [{p['Q_range'][0]:.0f}, {p['Q_range'][1]:.0f}]  "
              f"dP [{p['dP_range'][0]:.0f}, {p['dP_range'][1]:.0f}]")
        print(f"  Opt wall          {bag['summary']['opt_wall_s']:.1f}s")

    print(f"\nTotal wall:  {time.time() - t_all:.1f}s")
    print(f"Artifacts:   {out_root}")


if __name__ == '__main__':
    main()
