"""plot_nu_v4_parity_error.py — Two separate publication figures:

Figure 1: Parity plot (Nu_pred LOO vs Nu_exp), 1×2 panels (Diamond + Gyroid)
Figure 2: LOO error analysis, 2×3 panels:
   row 1 Diamond / row 2 Gyroid
   col 1 Per-geom RMSRE bars
   col 2 Residual vs Re scatter (color = ε_f)
   col 3 Residual histogram

Output:
   vault/reports/methodology/figs/2026-04-27-nu-v4-parity.png
   vault/reports/methodology/figs/2026-04-27-nu-v4-error-analysis.png
   均质化/SJTU-TPMSHX/reports/figs/{same names}

Usage:
   python -u -m sjtu_tpmshx.df_fit.plot_nu_v4_parity_error
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl
from sjtu_tpmshx.df_fit.fit_nu_exp_v3 import load_sheet


PR_AIR = 0.72
PR13 = PR_AIR ** (1/3)
COEFS = {
    'Diamond': dict(c=0.094440, a=0.8273, d=0.2260),
    'Gyroid':  dict(c=0.126007, a=0.7898, d=0.2325),
}


def loo_predictions(d):
    """LOO-by-geometry: refit log-space LSQ excluding each geom, predict held-out.

    Note fit is in absorbed-Pr space (no explicit Pr column); the resulting c is
    numerically equivalent to c_explicit · Pr^(1/3) at Pr_air=0.72.
    """
    Nu_pred_loo = np.zeros(len(d))
    geoms = sorted(set(zip(d['L'], d['t'])))
    for L_t, t_t in geoms:
        sel = ((d['L'] == L_t) & (d['t'] == t_t)).to_numpy()
        d_train = d[~sel]
        d_test = d[sel]
        if len(d_train) < 5 or len(d_test) == 0:
            continue
        Y = np.log(d_train['Nu'].to_numpy())
        Re_tr = d_train['Re'].to_numpy()
        DhL_tr = (d_train['D_h_mm'] / d_train['L']).to_numpy()
        A = np.column_stack([np.ones_like(Y), np.log(Re_tr), np.log(DhL_tr)])
        coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
        Re_te = d_test['Re'].to_numpy()
        DhL_te = (d_test['D_h_mm'] / d_test['L']).to_numpy()
        Nu_pred_loo[sel] = np.exp(coef[0]) * Re_te**coef[1] * DhL_te**coef[2]
    return Nu_pred_loo


def per_geom_stats(d, err_rel):
    geoms = sorted(set(zip(d['L'], d['t'])))
    out = []
    for L, t in geoms:
        sel = ((d['L'] == L) & (d['t'] == t)).to_numpy()
        e = err_rel[sel]
        out.append(dict(L=L, t=t, n=int(sel.sum()),
                        rmsre=float(np.sqrt(np.mean(e**2)) * 100),
                        bias=float(np.mean(e) * 100)))
    return out


# ============= Figure 1: Parity plot =============

def parity_panel(ax, d, tpms):
    Nu_exp = d['Nu'].to_numpy()
    Re = d['Re'].to_numpy()
    Nu_pred = loo_predictions(d)
    err = (Nu_pred - Nu_exp) / Nu_exp
    rmsre = float(np.sqrt(np.mean(err**2)) * 100)
    bias = float(np.mean(err) * 100)

    sc = ax.scatter(Nu_exp, Nu_pred, c=Re, s=28, alpha=0.85,
                    cmap='viridis', edgecolors='black', linewidths=0.3,
                    norm=mpl.colors.LogNorm())
    cbar = plt.colorbar(sc, ax=ax, pad=0.02)
    cbar.set_label('Re', fontsize=10)
    cbar.ax.tick_params(labelsize=9)

    lim_lo = min(Nu_exp.min(), Nu_pred.min()) * 0.7
    lim_hi = max(Nu_exp.max(), Nu_pred.max()) * 1.3
    lim = [lim_lo, lim_hi]
    ax.plot(lim, lim, 'k-', lw=1.4, alpha=0.7, label='y = x', zorder=1)
    ax.plot(lim, [v * 1.10 for v in lim], 'r--', lw=1.0, alpha=0.6, label='+10%', zorder=1)
    ax.plot(lim, [v * 0.90 for v in lim], 'r--', lw=1.0, alpha=0.6, label='-10%', zorder=1)
    ax.plot(lim, [v * 1.20 for v in lim], 'r:', lw=0.9, alpha=0.5, label='+20%', zorder=1)
    ax.plot(lim, [v * 0.80 for v in lim], 'r:', lw=0.9, alpha=0.5, label='-20%', zorder=1)
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_aspect('equal', adjustable='box')
    ax.set_xlabel(r'$Nu_{\mathrm{exp}}$', fontsize=12)
    ax.set_ylabel(r'$Nu_{\mathrm{pred}}$ (LOO)', fontsize=12)
    ax.set_title(f'{tpms}: Parity Plot (LOO)\n'
                 f'RMSRE = {rmsre:.2f}%   bias = {bias:+.2f}%   N = {len(d)}',
                 fontsize=11)
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles[:3], labels[:3], loc='upper left', fontsize=9, framealpha=0.9)
    ax.grid(True, which='both', alpha=0.25)
    ax.tick_params(labelsize=9)


def make_figure_parity(dD, dG, out_paths):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.5))
    parity_panel(axes[0], dD, 'Diamond')
    parity_panel(axes[1], dG, 'Gyroid')
    fig.suptitle('Nu v4 Parity Plot (Leave-One-Geometry-Out Cross-Validation)\n'
                 r'$Nu = c \cdot Pr^{1/3} \cdot Re^{a} \cdot (D_h/L)^{d}$, '
                 'Pr=0.72 (air), 试验记录表 v3, 12 geom × 16-22 cases',
                 fontsize=13, y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    for p in out_paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(p, dpi=180, bbox_inches='tight')
        print(f"Saved: {p}")
    plt.close(fig)


# ============= Figure 2: Error analysis =============

def err_row(axes, d, tpms):
    Nu_exp = d['Nu'].to_numpy()
    Re = d['Re'].to_numpy()
    eps_f = d['eps_f'].to_numpy()
    Nu_pred = loo_predictions(d)
    err = (Nu_pred - Nu_exp) / Nu_exp
    err_pct = err * 100
    rmsre = float(np.sqrt(np.mean(err**2)) * 100)
    bias = float(np.mean(err) * 100)

    # Col 1: per-geom RMSRE bars
    ax = axes[0]
    stats = per_geom_stats(d, err)
    labels = [f"L{g['L']:.0f}t{g['t']:.1f}" for g in stats]
    rmsres = [g['rmsre'] for g in stats]
    biases = [g['bias'] for g in stats]
    ns = [g['n'] for g in stats]
    x = np.arange(len(labels))
    bar_colors = ['#d62728' if abs(b) > 10 else '#ff7f0e' if r > 15
                  else '#2ca02c' for r, b in zip(rmsres, biases)]
    bars = ax.bar(x, rmsres, color=bar_colors, alpha=0.85,
                  edgecolor='black', lw=0.5)
    for bar, r, b, n in zip(bars, rmsres, biases, ns):
        ax.text(bar.get_x() + bar.get_width()/2, r + 0.4,
                f'{b:+.0f}%\nn={n}', ha='center', va='bottom', fontsize=7.5)
    ax.axhline(rmsre, color='blue', ls='--', lw=1.2,
               label=f'Overall {rmsre:.2f}%')
    ax.axhline(10, color='gray', ls=':', lw=0.8, alpha=0.6, label='10% line')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=8)
    ax.set_ylabel('Per-geometry LOO RMSRE [%]', fontsize=10)
    ax.set_title(f'{tpms}: Per-Geometry RMSRE', fontsize=11)
    ax.legend(fontsize=8, loc='upper right')
    ax.grid(True, axis='y', alpha=0.25)
    ax.tick_params(labelsize=9)
    ax.set_ylim(0, max(rmsres) * 1.30)

    # Col 2: residual vs Re
    ax = axes[1]
    sc = ax.scatter(Re, err_pct, c=eps_f, s=24, alpha=0.85,
                    cmap='plasma', edgecolors='black', linewidths=0.2)
    cbar = plt.colorbar(sc, ax=ax, pad=0.02)
    cbar.set_label(r'$\varepsilon_f$', fontsize=10)
    cbar.ax.tick_params(labelsize=9)
    ax.axhline(0, color='black', lw=1.0)
    ax.axhline(10, color='red', ls='--', lw=0.9, alpha=0.55)
    ax.axhline(-10, color='red', ls='--', lw=0.9, alpha=0.55)
    ax.axhline(20, color='red', ls=':', lw=0.7, alpha=0.4)
    ax.axhline(-20, color='red', ls=':', lw=0.7, alpha=0.4)
    ax.set_xscale('log')
    ax.set_xlabel('Re', fontsize=11)
    ax.set_ylabel('LOO relative error [%]', fontsize=10)
    ax.set_title(f'{tpms}: Residual vs Re\n(red dashed ±10%, dotted ±20%)',
                 fontsize=11)
    ax.grid(True, which='both', alpha=0.25)
    ax.tick_params(labelsize=9)
    ax.set_ylim(-30, 30)

    # Col 3: histogram
    ax = axes[2]
    bins = np.linspace(-30, 30, 31)
    ax.hist(err_pct, bins=bins, color='#1f77b4', alpha=0.75,
            edgecolor='black', lw=0.5)
    ax.axvline(0, color='black', lw=1.0)
    ax.axvline(bias, color='blue', ls='--', lw=1.2,
               label=f'bias {bias:+.2f}%')
    ax.axvline(rmsre, color='red', ls=':', lw=1.0, alpha=0.7,
               label=f'+RMSRE {rmsre:.2f}%')
    ax.axvline(-rmsre, color='red', ls=':', lw=1.0, alpha=0.7)
    ax.set_xlabel('LOO relative error [%]', fontsize=11)
    ax.set_ylabel('Count', fontsize=10)
    ax.set_title(f'{tpms}: Residual Distribution', fontsize=11)
    ax.legend(fontsize=8, loc='upper right')
    ax.grid(True, axis='y', alpha=0.25)
    ax.tick_params(labelsize=9)
    ax.set_xlim(-30, 30)


def make_figure_error(dD, dG, out_paths):
    fig, axes = plt.subplots(2, 3, figsize=(17, 10))
    err_row(axes[0], dD, 'Diamond')
    err_row(axes[1], dG, 'Gyroid')
    fig.suptitle('Nu v4 LOO Error Analysis  (Per-Geometry RMSRE / Residual vs Re / '
                 'Error Histogram)\n'
                 r'$Nu = c \cdot Pr^{1/3} \cdot Re^{a} \cdot (D_h/L)^{d}$, '
                 'Pr=0.72 (air), 试验记录表 v3, 12 geom × 16-22 cases',
                 fontsize=13, y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    for p in out_paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(p, dpi=180, bbox_inches='tight')
        print(f"Saved: {p}")
    plt.close(fig)


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    # Avoid CJK glyph warnings — use ASCII only in titles (suptitle has CJK,
    # so set CJK-capable font if available).
    for f in ('Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC', 'DejaVu Sans'):
        try:
            mpl.rcParams['font.sans-serif'] = [f]
            break
        except Exception:
            continue
    mpl.rcParams['axes.unicode_minus'] = False

    dD = load_sheet('Diamond_汇总')
    dG = load_sheet('Gyroid_汇总')

    vault_dir = Path(r'D:\Postgraduate\vault\reports\methodology\figs')
    proj_dir = Path(r'D:\Postgraduate\均质化\SJTU-TPMSHX\reports\figs')

    make_figure_parity(dD, dG, [
        vault_dir / '2026-04-27-nu-v4-parity.png',
        proj_dir / 'nu_v4_parity.png',
    ])

    make_figure_error(dD, dG, [
        vault_dir / '2026-04-27-nu-v4-error-analysis.png',
        proj_dir / 'nu_v4_error_analysis.png',
    ])


if __name__ == '__main__':
    main()
