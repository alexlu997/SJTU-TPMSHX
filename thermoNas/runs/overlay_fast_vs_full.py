"""
overlay_fast_vs_full.py — Overlay Pareto fronts: full-mode vs fast-reeval.

Reads:
  production_output/{Gyroid,Diamond}/pareto_final_fine.csv  (fast + reeval)
  production_output/{Gyroid_full,Diamond_full}/pareto_final.csv  (full mode)

Writes:
  production_output/overlay_fast_vs_full.png
  production_output/overlay_summary.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve()
OUT_ROOT = _HERE.parent / 'production_output'


def _load_pareto(csv_path):
    data = np.loadtxt(csv_path, delimiter=',', skiprows=1)
    # CSV layout: Q_total_W_m, dP_total_Pa, ...X...
    return data[:, 0], data[:, 1]  # Q, dP


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    summary = {}

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=False)

    for ax, tpms in zip(axes, ('Gyroid', 'Diamond')):
        fast_csv = OUT_ROOT / tpms / 'pareto_final_fine.csv'
        full_csv = OUT_ROOT / f'{tpms}_full' / 'pareto_final.csv'

        if not fast_csv.exists():
            print(f"MISSING: {fast_csv}")
            continue
        if not full_csv.exists():
            print(f"MISSING: {full_csv}")
            continue

        Q_fast, dP_fast = _load_pareto(fast_csv)
        Q_full, dP_full = _load_pareto(full_csv)

        # Load baseline from each
        def _baseline(dirname, key='baseline'):
            with open(OUT_ROOT / dirname / 'summary.json') as f:
                s = json.load(f)
            return s[key]['Q'], s[key]['dP']

        try:
            Q_bl_full, dP_bl_full = _baseline(f'{tpms}_full')
        except Exception as e:
            Q_bl_full = dP_bl_full = None

        ax.scatter(dP_full, Q_full, c='tab:blue', marker='o', s=55,
                   edgecolor='k', linewidths=0.5,
                   label=f'Full-mode sweep ({len(Q_full)} sols)',
                   zorder=3)
        ax.scatter(dP_fast, Q_fast, c='tab:red', marker='^', s=55,
                   edgecolor='k', linewidths=0.5,
                   label=f'Fast-mode → reeval ({len(Q_fast)} sols)',
                   zorder=4)
        if Q_bl_full is not None:
            ax.scatter(dP_bl_full, Q_bl_full, c='tab:green', marker='*',
                       s=320, edgecolor='k', linewidths=1.0,
                       label=f'Uniform baseline', zorder=5)

        ax.set_xlabel('Total Pressure Drop ΔP [Pa]', fontsize=11)
        ax.set_ylabel('Total Heat Transfer Q [W/m]', fontsize=11)
        ax.set_title(f'{tpms}', fontsize=13, fontweight='bold')
        ax.grid(alpha=0.3)
        ax.legend(loc='best', fontsize=9)

        # Metrics
        summary[tpms] = dict(
            baseline=dict(Q=Q_bl_full, dP=dP_bl_full) if Q_bl_full else None,
            full=dict(n=len(Q_full),
                      Q_max=float(Q_full.max()), Q_min=float(Q_full.min()),
                      dP_max=float(dP_full.max()), dP_min=float(dP_full.min())),
            fast_reeval=dict(n=len(Q_fast),
                             Q_max=float(Q_fast.max()), Q_min=float(Q_fast.min()),
                             dP_max=float(dP_fast.max()), dP_min=float(dP_fast.min())),
        )
        # Relative loss from using fast search:
        summary[tpms]['fast_Q_loss_pct'] = \
            (float(Q_full.max()) - float(Q_fast.max())) / float(Q_full.max()) * 100
        summary[tpms]['fast_dP_advantage_pct'] = \
            (float(dP_full.min()) - float(dP_fast.min())) / float(dP_full.min()) * 100

    fig.suptitle('Pareto overlay — full-mode search vs fast-mode search → reeval',
                 fontsize=14, fontweight='bold')
    fig.tight_layout()
    out_png = OUT_ROOT / 'overlay_fast_vs_full.png'
    fig.savefig(out_png, dpi=180, bbox_inches='tight')
    plt.close(fig)
    print(f"Saved: {out_png}")

    out_json = OUT_ROOT / 'overlay_summary.json'
    with open(out_json, 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Saved: {out_json}")

    # Console table
    print("\n" + "=" * 70)
    print("Fast-mode search quality loss (vs full-mode)")
    print("=" * 70)
    print(f"{'TPMS':<10} {'Q_max loss':>12} {'dP_min gain':>14}")
    for t, s in summary.items():
        ql = s.get('fast_Q_loss_pct', float('nan'))
        dpa = s.get('fast_dP_advantage_pct', float('nan'))
        print(f"{t:<10} {ql:>+10.2f}%  {dpa:>+12.2f}%")


if __name__ == '__main__':
    main()
