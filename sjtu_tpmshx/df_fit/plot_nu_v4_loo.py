"""plot_nu_v4_loo.py — LOO error analysis figure for v4 3p PL Nu.

Generates 2×3 panel figure:
  Row 1: Diamond  | Row 2: Gyroid
  Col 1: Predicted vs Experimental Nu (log-log) + ±10/20% bands, color by Re
  Col 2: Per-geometry RMSRE bar chart
  Col 3: LOO relative residual vs Re scatter

Output:
  D:/Postgraduate/vault/reports/methodology/figs/2026-04-27-nu-v4-loo-error.png
  D:/Postgraduate/均质化/SJTU-TPMSHX/reports/figs/nu_v4_loo_error.png

Usage:
  python -u -m sjtu_tpmshx.df_fit.plot_nu_v4_loo
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl
from sjtu_tpmshx.df_fit.fit_nu_exp_v3 import load_sheet


# Production v4 3p PL coefficients (Pr=0.72 air const, Pr^(1/3) explicit)
PR_AIR = 0.72
PR13 = PR_AIR ** (1/3)
COEFS = {
    'Diamond': dict(c=0.094440, a=0.8273, d=0.2260),
    'Gyroid':  dict(c=0.126007, a=0.7898, d=0.2325),
}


def loo_predictions(d):
    """LOO-by-geometry: refit log-space LSQ excluding each geom, predict held-out."""
    Nu_pred_loo = np.zeros(len(d))
    geoms = sorted(set(zip(d['L'], d['t'])))
    for L_t, t_t in geoms:
        sel = ((d['L'] == L_t) & (d['t'] == t_t)).to_numpy()
        d_train = d[~sel]
        d_test = d[sel]
        if len(d_train) < 5 or len(d_test) == 0:
            continue
        # Fit on training
        Y = np.log(d_train['Nu'].to_numpy())
        Re_tr = d_train['Re'].to_numpy()
        DhL_tr = (d_train['D_h_mm'] / d_train['L']).to_numpy()
        A = np.column_stack([np.ones_like(Y), np.log(Re_tr), np.log(DhL_tr)])
        coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
        # Predict test
        Re_te = d_test['Re'].to_numpy()
        DhL_te = (d_test['D_h_mm'] / d_test['L']).to_numpy()
        Nu_pred_loo[sel] = np.exp(coef[0]) * Re_te**coef[1] * DhL_te**coef[2]
    return Nu_pred_loo


def in_sample_predictions(d, tpms):
    p = COEFS[tpms]
    Re = d['Re'].to_numpy()
    DhL = (d['D_h_mm'] / d['L']).to_numpy()
    return p['c'] * PR13 * Re**p['a'] * DhL**p['d']


def per_geom_rmsre(d, err_rel):
    """Compute per-geom RMSRE & sample count."""
    geoms = sorted(set(zip(d['L'], d['t'])))
    out = []
    for L, t in geoms:
        sel = ((d['L'] == L) & (d['t'] == t)).to_numpy()
        e = err_rel[sel]
        out.append(dict(L=L, t=t, n=int(sel.sum()),
                        rmsre=float(np.sqrt(np.mean(e**2)) * 100),
                        bias=float(np.mean(e) * 100)))
    return out


def plot_one_row(axes, d, tpms, color_cycle):
    Nu_exp = d['Nu'].to_numpy()
    Re = d['Re'].to_numpy()
    Nu_pred_loo = loo_predictions(d)
    err_rel = (Nu_pred_loo - Nu_exp) / Nu_exp
    rmsre_overall = float(np.sqrt(np.mean(err_rel**2)) * 100)
    bias_overall = float(np.mean(err_rel) * 100)

    # ---- Col 1: Pred vs Exp log-log ----
    ax = axes[0]
    sc = ax.scatter(Nu_exp, Nu_pred_loo, c=Re, s=20, alpha=0.75,
                    cmap='viridis', edgecolors='none', norm=mpl.colors.LogNorm())
    cbar = plt.colorbar(sc, ax=ax, pad=0.02)
    cbar.set_label('Re', fontsize=9)
    cbar.ax.tick_params(labelsize=8)
    lim = [Nu_exp.min() * 0.7, Nu_exp.max() * 1.3]
    ax.plot(lim, lim, 'k-', lw=1, alpha=0.6, label='y=x')
    for pct, ls in [(10, '--'), (20, ':')]:
        ax.plot(lim, [v*(1+pct/100) for v in lim], 'r', ls=ls, lw=0.8, alpha=0.5)
        ax.plot(lim, [v*(1-pct/100) for v in lim], 'r', ls=ls, lw=0.8, alpha=0.5,
                label=f'±{pct}%' if pct == 10 else None)
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel('Nu_exp', fontsize=10)
    ax.set_ylabel('Nu_pred (LOO)', fontsize=10)
    ax.set_title(f'{tpms}: LOO Nu Pred vs Exp\n'
                 f'RMSRE={rmsre_overall:.2f}%  bias={bias_overall:+.2f}%  N={len(d)}',
                 fontsize=10)
    ax.legend(loc='upper left', fontsize=8, framealpha=0.9)
    ax.grid(True, which='both', alpha=0.25)
    ax.tick_params(labelsize=8)

    # ---- Col 2: Per-geom RMSRE bars ----
    ax = axes[1]
    geom_stats = per_geom_rmsre(d, err_rel)
    labels = [f"L{g['L']:.0f}t{g['t']:.1f}" for g in geom_stats]
    rmsres = [g['rmsre'] for g in geom_stats]
    biases = [g['bias'] for g in geom_stats]
    ns = [g['n'] for g in geom_stats]
    x = np.arange(len(labels))
    bar_colors = ['tab:red' if abs(b) > 10 else 'tab:orange' if r > 15
                  else 'tab:green' for r, b in zip(rmsres, biases)]
    bars = ax.bar(x, rmsres, color=bar_colors, alpha=0.75, edgecolor='black', lw=0.5)
    for i, (bar, r, b, n) in enumerate(zip(bars, rmsres, biases, ns)):
        ax.text(bar.get_x() + bar.get_width()/2, r + 0.5,
                f'{b:+.0f}%\nn={n}', ha='center', va='bottom', fontsize=7)
    ax.axhline(rmsre_overall, color='blue', ls='--', lw=1,
               label=f'Overall {rmsre_overall:.2f}%')
    ax.axhline(10, color='gray', ls=':', lw=0.8, alpha=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=7)
    ax.set_ylabel('Per-geometry LOO RMSRE [%]', fontsize=10)
    ax.set_title(f'{tpms}: Per-Geometry LOO RMSRE\n(label: bias, n=sample count)',
                 fontsize=10)
    ax.legend(fontsize=8, loc='upper right')
    ax.grid(True, axis='y', alpha=0.25)
    ax.tick_params(labelsize=8)
    ax.set_ylim(0, max(rmsres) * 1.25)

    # ---- Col 3: Residual vs Re ----
    ax = axes[2]
    eps_f = d['eps_f'].to_numpy()
    sc = ax.scatter(Re, err_rel * 100, c=eps_f, s=20, alpha=0.75,
                    cmap='plasma', edgecolors='none')
    cbar = plt.colorbar(sc, ax=ax, pad=0.02)
    cbar.set_label('ε_f', fontsize=9)
    cbar.ax.tick_params(labelsize=8)
    ax.axhline(0, color='black', lw=0.8)
    ax.axhline(10, color='red', ls='--', lw=0.8, alpha=0.5)
    ax.axhline(-10, color='red', ls='--', lw=0.8, alpha=0.5)
    ax.set_xscale('log')
    ax.set_xlabel('Re', fontsize=10)
    ax.set_ylabel('LOO relative error [%]', fontsize=10)
    ax.set_title(f'{tpms}: LOO Residual vs Re\n(red dash = ±10%)', fontsize=10)
    ax.grid(True, which='both', alpha=0.25)
    ax.tick_params(labelsize=8)
    ax.set_ylim(-30, 30)


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    dD = load_sheet('Diamond_汇总')
    dG = load_sheet('Gyroid_汇总')

    fig, axes = plt.subplots(2, 3, figsize=(16, 9.5))
    plot_one_row(axes[0], dD, 'Diamond', 'tab:blue')
    plot_one_row(axes[1], dG, 'Gyroid', 'tab:orange')

    fig.suptitle('Nu v4 3-Parameter Power-Law: LOO-by-Geometry Error Analysis\n'
                 r'Form: $Nu = c \cdot Pr^{1/3} \cdot Re^{a} \cdot (D_h/L)^{d}$  '
                 '(Pr=0.72 air const, smooth-wall, 12 geom x 16-22 cases)',
                 fontsize=12, y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.96])

    out_vault = Path(r'D:\Postgraduate\vault\reports\methodology\figs\2026-04-27-nu-v4-loo-error.png')
    out_proj = Path(r'D:\Postgraduate\均质化\SJTU-TPMSHX\reports\figs\nu_v4_loo_error.png')
    out_vault.parent.mkdir(parents=True, exist_ok=True)
    out_proj.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_vault, dpi=160, bbox_inches='tight')
    fig.savefig(out_proj, dpi=160, bbox_inches='tight')
    print(f"Saved: {out_vault}")
    print(f"Saved: {out_proj}")


if __name__ == '__main__':
    main()
