"""
plot_shanghai_3d_errors.py — 3D Shanghai 16-case error analysis plots

Inputs:
  validation/shanghai_3d_baseline.csv          — uniform 20×10×3
  validation/shanghai_3d_baseline_refine.csv   — refined 36×26×19

Outputs (PNG, 300 dpi):
  vault/reports/2026-04-20-shanghai-3d-errors.png

Four-panel figure:
  (a) dP parity plot (sim vs exp) with 2D baseline overlay
  (b) Q  parity plot
  (c) err_dP% vs Re_air (trend)
  (d) err_Q% vs case index
"""

from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
VAULT_REPORTS = Path(r'D:\Postgraduate\vault\reports')

# Approximate air properties at Shanghai mean state for Re calc
RHO_AIR_REF = 1.0    # coarse — Re scale, not absolute
MU_AIR_REF = 2.5e-5  # coarse
D_H = 5.36e-3        # Gyroid L=7 t=0.6 D_h

def _load(csv_name):
    return pd.read_csv(ROOT / 'validation' / csv_name)


def _add_parity(ax, exp, sim, label, color, marker):
    ax.scatter(exp, sim, label=label, c=color, marker=marker, s=55,
                edgecolor='k', linewidth=0.5, zorder=3)


def main():
    uniform = _load('shanghai_3d_baseline.csv')
    refine = _load('shanghai_3d_baseline_refine.csv')

    # Re_air estimate (order-of-magnitude, via u_air * D_h / nu)
    for d in (uniform, refine):
        d['Re_air'] = d['u_air'] * D_H * RHO_AIR_REF / MU_AIR_REF

    fig, axes = plt.subplots(2, 2, figsize=(13, 10))

    # ─── (a) dP parity ───
    ax = axes[0, 0]
    xmin = min(uniform['dP_exp'].min(), refine['dP_exp'].min()) * 0.7
    xmax = uniform['dP_exp'].max() * 1.15
    diag = np.array([xmin, xmax])
    ax.plot(diag, diag, 'k--', lw=1, alpha=0.5, label='y=x (ideal)')
    ax.plot(diag, diag * 0.7, 'r:', lw=1, alpha=0.5, label='-30%')
    ax.plot(diag, diag * 0.5, 'r--', lw=1, alpha=0.5, label='-50%')
    _add_parity(ax, uniform['dP_exp'], uniform['dP_sim'],
                f"uniform 20x10x3 (RMSRE={_rmsre(uniform['err_dP%']):.1f}%)",
                'tab:orange', 'o')
    _add_parity(ax, refine['dP_exp'], refine['dP_sim'],
                f"refine 36x26x19 (RMSRE={_rmsre(refine['err_dP%']):.1f}%)",
                'tab:blue', 's')
    ax.set_xscale('log'); ax.set_yscale('log')
    ax.set_xlabel(r'$\Delta P_{\mathrm{exp}}$ [Pa]')
    ax.set_ylabel(r'$\Delta P_{\mathrm{sim}}$ [Pa]')
    ax.set_title('(a) Pressure drop parity — 3D Shanghai 16 cases')
    ax.legend(loc='upper left', fontsize=9)
    ax.grid(True, alpha=0.3, which='both')

    # ─── (b) Q parity ───
    ax = axes[0, 1]
    qmin = min(uniform['Q_exp'].min(), refine['Q_exp'].min()) * 0.7
    qmax = uniform['Q_exp'].max() * 1.15
    diag = np.array([qmin, qmax])
    ax.plot(diag, diag, 'k--', lw=1, alpha=0.5, label='y=x')
    ax.plot(diag, diag * 1.05, 'g:', lw=1, alpha=0.5, label='±5%')
    ax.plot(diag, diag * 0.95, 'g:', lw=1, alpha=0.5)
    _add_parity(ax, uniform['Q_exp'], uniform['Q_sim'],
                f"uniform (RMSRE={_rmsre(uniform['err_Q%']):.2f}%)",
                'tab:orange', 'o')
    _add_parity(ax, refine['Q_exp'], refine['Q_sim'],
                f"refine (RMSRE={_rmsre(refine['err_Q%']):.2f}%)",
                'tab:blue', 's')
    ax.set_xlabel(r'$Q_{\mathrm{exp}}$ [W]')
    ax.set_ylabel(r'$Q_{\mathrm{sim}}$ [W]')
    ax.set_title('(b) Heat transfer parity — 3D Shanghai')
    ax.legend(loc='upper left', fontsize=9)
    ax.grid(True, alpha=0.3)

    # ─── (c) err_dP% vs Re_air ───
    ax = axes[1, 0]
    ax.axhline(0, color='k', lw=0.8, alpha=0.5)
    ax.axhline(-32.34, color='gray', ls=':', lw=1, alpha=0.6,
               label='2D baseline RMSRE sign ref')
    ax.plot(uniform['Re_air'], uniform['err_dP%'],
            'o-', color='tab:orange', label=f"uniform (max|err|={refine['err_dP%'].abs().max():.1f}%)",
            ms=7, mec='k', mew=0.5, alpha=0.85)
    ax.plot(refine['Re_air'], refine['err_dP%'],
            's-', color='tab:blue', label=f"refine (max|err|={refine['err_dP%'].abs().max():.1f}%)",
            ms=7, mec='k', mew=0.5, alpha=0.85)
    ax.fill_between([uniform['Re_air'].min() * 0.9, uniform['Re_air'].max() * 1.1],
                     -50, -30, color='tab:red', alpha=0.08, label='underpredict zone')
    ax.set_xscale('log')
    ax.set_xlabel(r'$Re_{\mathrm{air}}$ (≈ $u_A \cdot D_h / \nu$)')
    ax.set_ylabel(r'$\mathrm{err}_{\Delta P}$ [%]')
    ax.set_title('(c) dP error vs Re — systematic under-prediction growing with Re')
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(True, alpha=0.3, which='both')

    # ─── (d) err_Q% vs case ───
    ax = axes[1, 1]
    ax.axhline(0, color='k', lw=0.8, alpha=0.5)
    ax.fill_between([0.5, 16.5], -5, 5, color='tab:green', alpha=0.08,
                     label=r'±5% target')
    ax.plot(uniform['case'], uniform['err_Q%'],
            'o-', color='tab:orange', label=f"uniform RMSRE={_rmsre(uniform['err_Q%']):.2f}%",
            ms=7, mec='k', mew=0.5, alpha=0.85)
    ax.plot(refine['case'], refine['err_Q%'],
            's-', color='tab:blue', label=f"refine RMSRE={_rmsre(refine['err_Q%']):.2f}%",
            ms=7, mec='k', mew=0.5, alpha=0.85)
    ax.axhline(5.70, color='gray', ls=':', lw=1, alpha=0.6, label='2D max|err|=5.70%')
    ax.axhline(-5.70, color='gray', ls=':', lw=1, alpha=0.6)
    ax.set_xlabel('Case index')
    ax.set_ylabel(r'$\mathrm{err}_Q$ [%]')
    ax.set_title('(d) Q error per case — 3D Q accuracy exceeds 2D baseline')
    ax.set_xticks(range(1, 17))
    ax.set_xlim(0.5, 16.5)
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(True, alpha=0.3)

    fig.suptitle(
        'Shanghai 3D Validation — Error Analysis (2026-04-20 P1b-b baseline)\n'
        f"Gyroid L=7.0 t=0.6, Domain 231×42×20mm, N_UNITS=36",
        fontsize=13, y=1.0)
    fig.tight_layout()

    out_png = VAULT_REPORTS / '2026-04-20-shanghai-3d-errors.png'
    fig.savefig(out_png, dpi=300, bbox_inches='tight')
    print(f"Saved: {out_png}")
    out_pdf = VAULT_REPORTS / '2026-04-20-shanghai-3d-errors.pdf'
    fig.savefig(out_pdf, bbox_inches='tight')
    print(f"Saved: {out_pdf}")


def _rmsre(series):
    return float(np.sqrt(np.mean(np.asarray(series, dtype=float) ** 2)))


if __name__ == '__main__':
    main()
