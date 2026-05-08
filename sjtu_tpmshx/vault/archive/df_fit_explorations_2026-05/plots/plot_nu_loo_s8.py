"""plot_nu_loo_s8.py — Re vs Nu LOO error plot for S8 unified form on v3.

Both TPMS use S8 (7p log-quadratic Re, Sa-explicit). Re_fit = Excel col 0
(no recompute).
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from scipy.optimize import curve_fit

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import Pr, Sa_mm
from df_fit.fit_nu_single_stream import load_data


def S8(X, c, a, a2, b, d1, d2, d3):
    Re, e, L, D, t = X
    logRe = np.log(np.maximum(Re, 1.0))
    return (c * Pr**(1/3) * Re**a * np.exp(a2*logRe**2) * e**b
            * (D/(1000*Sa_mm))**d1 * (L/(1000*Sa_mm))**d2 * (t/(1000*Sa_mm))**d3)


def loo_predictions(tpms):
    d = load_data(tpms)
    geoms = sorted(set(zip(d['L'], d['t'])))
    Nu_pred = np.full(len(d), np.nan)
    p0 = [0.5, 0.3, 0.0, 0.5, -0.5, -0.5, 0.0]
    bounds = ([1e-8, 0, -1, -20, -10, -10, -10],
              [1e4, 2, 1, 20, 10, 10, 10])
    for L_t, t_t in geoms:
        sel_test = (d['L'] == L_t) & (d['t'] == t_t)
        d_tr = d[~sel_test]
        d_te = d[sel_test]
        if len(d_tr) < 10 or len(d_te) == 0:
            continue
        X_tr = (d_tr['Re_fit'].values, d_tr['eps_f'].values,
                d_tr['L_mm'].values, d_tr['D_h_mm'].values, d_tr['t'].values)
        try:
            popt, _ = curve_fit(S8, X_tr, d_tr['Nu'].values,
                                p0=p0, bounds=bounds, maxfev=200000)
        except Exception:
            continue
        X_te = (d_te['Re_fit'].values, d_te['eps_f'].values,
                d_te['L_mm'].values, d_te['D_h_mm'].values, d_te['t'].values)
        Nu_pred[d.index[sel_test].to_numpy()] = S8(X_te, *popt)
    return d, Nu_pred


def plot_panel(ax_curve, ax_resid, d, Nu_pred, title):
    geoms = sorted(set(zip(d['L'], d['t'])))
    eps_f_all = np.array([float(d.iloc[d.index[(d['L'] == L) & (d['t'] == t)][0]]['eps_f'])
                          for (L, t) in geoms])
    norm = Normalize(vmin=eps_f_all.min(), vmax=eps_f_all.max())
    cmap = plt.get_cmap('viridis')

    for (L, t) in geoms:
        sel = (d['L'] == L) & (d['t'] == t)
        sub = d[sel].sort_values('Re_fit')
        idx = sub.index.to_numpy()
        Re_g = sub['Re_fit'].to_numpy()
        Nu_truth = sub['Nu'].to_numpy()
        Nu_loo = Nu_pred[idx]
        eps_f_g = float(sub['eps_f'].iloc[0])
        c = cmap(norm(eps_f_g))
        ax_curve.scatter(Re_g, Nu_truth, s=18, marker='o',
                         facecolors='none', edgecolors=c, linewidths=1.0, alpha=0.85)
        ax_curve.plot(Re_g, Nu_loo, '-', color=c, linewidth=1.3, alpha=0.85)
        err = (Nu_loo - Nu_truth) / Nu_truth * 100.0
        ax_resid.scatter(Re_g, err, s=20, color=c, alpha=0.85,
                         edgecolors='black', linewidths=0.3)

    ax_curve.set_xscale('log')
    ax_curve.set_yscale('log')
    ax_curve.set_xlabel(r'$Re$ (Excel design, $\rho_{atm} u D_h/\mu$)')
    ax_curve.set_ylabel(r'$Nu = h\, D_h / k_f$')
    ax_curve.set_title(f'{title} — CFD truth (○) vs LOO prediction (—)')
    ax_curve.grid(True, which='both', alpha=0.3)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax_curve, pad=0.02)
    cbar.set_label(r'$\varepsilon_f$ (single-stream porosity)')

    err_all = (Nu_pred - d['Nu'].to_numpy()) / d['Nu'].to_numpy() * 100.0
    err_all = err_all[np.isfinite(err_all)]
    rmsre = float(np.sqrt(np.mean(err_all**2)))
    bias = float(np.mean(err_all))
    ax_resid.axhline(0, color='black', linewidth=0.7)
    ax_resid.axhline(rmsre, color='red', linewidth=0.6, linestyle='--',
                     label=f'+RMSRE = {rmsre:.2f}%')
    ax_resid.axhline(-rmsre, color='red', linewidth=0.6, linestyle='--')
    ax_resid.set_xscale('log')
    ax_resid.set_xlabel(r'$Re$')
    ax_resid.set_ylabel(r'LOO residual [%]')
    ax_resid.set_title(f'{title} — LOO residual (bias = {bias:+.2f}%)')
    ax_resid.grid(True, which='both', alpha=0.3)
    ax_resid.legend(loc='upper right', fontsize=8)
    return rmsre, bias


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("Generating Nu S8 LOO error figure (v3 CFD4, Excel Re)")
    print("=" * 60)
    print("Diamond LOO...")
    dD, predD = loo_predictions('Diamond')
    print("Gyroid LOO...")
    dG, predG = loo_predictions('Gyroid')

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    rd, bd = plot_panel(axes[0, 0], axes[1, 0], dD, predD, 'Diamond (S8)')
    rg, bg = plot_panel(axes[0, 1], axes[1, 1], dG, predG, 'Gyroid (S8)')

    fig.suptitle('Nu S8 LOO interpolation — v3 (CFD4 + Excel Re, smooth-wall, no ×1.28)',
                 fontsize=13, y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.985])

    out_dir = _PROJECT_ROOT.parent / 'reports' / 'figs'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / 'nu_loo_error_s8_v3.png'
    fig.savefig(out_png, dpi=150, bbox_inches='tight')

    vault = Path(r'D:\Postgraduate\vault\reports\methodology\figs')
    vault.mkdir(parents=True, exist_ok=True)
    fig.savefig(vault / 'nu_loo_error_s8_v3.png', dpi=150, bbox_inches='tight')

    print(f"\nSaved: {out_png}")
    print(f"Saved: {vault / 'nu_loo_error_s8_v3.png'}")
    print(f"\nDiamond S8 LOO RMSRE = {rd:.2f}% bias = {bd:+.2f}%")
    print(f"Gyroid  S8 LOO RMSRE = {rg:.2f}% bias = {bg:+.2f}%")


if __name__ == '__main__':
    main()
