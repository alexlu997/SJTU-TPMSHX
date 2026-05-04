"""viz_nu_correlations.py — visualize Nu correlation curves vs training data.

Plots:
  Per TPMS, Nu vs Re curves for each (L, t) training geometry.
  Overlay: training Excel data points + correlation prediction.
  Highlight Shanghai geometry (L=7, t=0.6) as extrapolation.

Output: reports/figs/nu_correlations_viz.png
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import (
    geometry as tpms_geometry, nu_from_Re, Pr, Sa_mm,
)
from df_fit.fit_nu_single_stream import load_data

K_S = 16.0


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    fig, axes = plt.subplots(2, 2, figsize=(15, 11))
    plt.subplots_adjust(hspace=0.35, wspace=0.30)

    for tpms_idx, tpms in enumerate(['Diamond', 'Gyroid']):
        d = load_data(tpms)
        ax_top = axes[0, tpms_idx]
        ax_bot = axes[1, tpms_idx]
        geoms = sorted(set(zip(d['L'], d['t'])))
        cmap = plt.cm.viridis
        n_geoms = len(geoms)

        # Top: Nu vs Re per geometry (training + correlation)
        for gi, (L_, t_) in enumerate(geoms):
            color = cmap(gi / max(n_geoms - 1, 1))
            sub = d[(d['L'] == L_) & (d['t'] == t_)].sort_values('Re_fit')
            Re_arr = sub['Re_fit'].to_numpy()
            Nu_arr = sub['Nu'].to_numpy()
            eps_f = float(sub['eps_f'].iloc[0])
            D_h_mm = float(sub['D_h_mm'].iloc[0])
            L_mm = float(sub['L_mm'].iloc[0])
            # CFD points
            ax_top.scatter(Re_arr, Nu_arr, color=color, s=25, alpha=0.6,
                            edgecolors='black', linewidths=0.4)
            # Correlation curve
            Re_curve = np.logspace(np.log10(Re_arr.min()*0.9),
                                    np.log10(Re_arr.max()*1.1), 100)
            Nu_curve = np.array([nu_from_Re(tpms, r, eps_f, L_mm, D_h_mm)
                                  for r in Re_curve])
            ax_top.plot(Re_curve, Nu_curve, color=color, lw=1.5,
                         label=f'L={L_:.0f}, t={t_:.1f}')

        # Highlight Shanghai (L=7, t=0.6) extrapolation
        sg = tpms_geometry(tpms, 7.0, 0.6, K_S)
        eps_f_s = sg['epsilon'] / 2.0
        L_mm_s = 7.0
        D_h_mm_s = sg['D_h'] * 1000.0
        Re_sh = np.logspace(np.log10(500), np.log10(20000), 100)
        Nu_sh = np.array([nu_from_Re(tpms, r, eps_f_s, L_mm_s, D_h_mm_s)
                           for r in Re_sh])
        ax_top.plot(Re_sh, Nu_sh, 'r--', lw=2.5,
                     label=f'Shanghai L=7 t=0.6 (extrap)', zorder=10)

        ax_top.set_xscale('log'); ax_top.set_yscale('log')
        ax_top.set_xlabel('Re (D_h-based, single-stream)', fontsize=10)
        ax_top.set_ylabel('Nu = h·D_h/k_f', fontsize=10)
        formula = ('F4-D: variable n=n0+n1·ln(ε_f)' if tpms == 'Diamond'
                   else 'F7: log-quadratic Re')
        ax_top.set_title(f'{tpms} Nu correlation ({formula})',
                          fontsize=12, fontweight='bold')
        ax_top.legend(fontsize=7, loc='upper left', ncol=2)
        ax_top.grid(alpha=0.3, which='both')

        # Bottom: residuals
        Re_all = d['Re_fit'].to_numpy()
        Nu_data = d['Nu'].to_numpy()
        Nu_pred = np.array([
            nu_from_Re(tpms, r, ef, lm, dh)
            for r, ef, lm, dh in zip(d['Re_fit'], d['eps_f'],
                                       d['L_mm'], d['D_h_mm'])
        ])
        rel_err = (Nu_pred - Nu_data) / Nu_data * 100
        rmsre = float(np.sqrt(np.mean(rel_err**2)))

        for gi, (L_, t_) in enumerate(geoms):
            color = cmap(gi / max(n_geoms - 1, 1))
            sel = (d['L'] == L_) & (d['t'] == t_)
            sub = d[sel].sort_values('Re_fit')
            Re_g = sub['Re_fit'].to_numpy()
            err_g = ((np.array([nu_from_Re(tpms, r, sub['eps_f'].iloc[0],
                                             sub['L_mm'].iloc[0],
                                             sub['D_h_mm'].iloc[0])
                                  for r in Re_g])
                      - sub['Nu'].to_numpy())
                      / sub['Nu'].to_numpy() * 100)
            ax_bot.plot(Re_g, err_g, 'o-', color=color, lw=1, ms=4,
                         alpha=0.7, label=f'L={L_:.0f},t={t_:.1f}')

        ax_bot.axhline(0, color='black', lw=0.6)
        ax_bot.fill_between([Re_all.min()*0.9, Re_all.max()*1.1],
                              -10, 10, alpha=0.1, color='gray', label='±10%')
        ax_bot.set_xscale('log')
        ax_bot.set_xlabel('Re', fontsize=10)
        ax_bot.set_ylabel('(Nu_pred - Nu_data) / Nu_data × 100 [%]', fontsize=10)
        ax_bot.set_title(f'{tpms} in-sample residuals (RMSRE={rmsre:.2f}%)',
                          fontsize=12, fontweight='bold')
        ax_bot.legend(fontsize=6, loc='upper right', ncol=3)
        ax_bot.grid(alpha=0.3, which='both')

    fig.suptitle('Single-stream Nu correlations — Diamond + Gyroid (post-refit 2026-04-26)',
                 fontsize=14, fontweight='bold', y=0.995)

    fig_dir = _PROJECT / 'reports' / 'figs'
    fig_dir.mkdir(parents=True, exist_ok=True)
    fig_path = fig_dir / 'nu_correlations_viz.png'
    plt.savefig(fig_path, dpi=130, bbox_inches='tight')
    plt.close()
    print(f"Saved figure: {fig_path}")


if __name__ == '__main__':
    main()
