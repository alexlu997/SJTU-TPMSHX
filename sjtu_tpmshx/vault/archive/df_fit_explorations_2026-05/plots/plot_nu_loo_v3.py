"""plot_nu_loo_v3.py — Re vs Nu LOO error plot for v3 (CFD4) data.

Forms used (per form-sweep best on v3):
  Diamond → F5 (5p, includes (t/L)^e)
  Gyroid  → F4-G (6p, variable n)
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
from df_fit.fit_nu_v3_best import diamond_F5, gyroid_F4G


def loo_predictions(tpms: str):
    d = load_data(tpms)
    geoms = sorted(set(zip(d['L'], d['t'])))
    Nu_pred = np.full(len(d), np.nan)
    for L_t, t_t in geoms:
        sel_test = (d['L'] == L_t) & (d['t'] == t_t)
        d_train = d[~sel_test]
        d_test = d[sel_test]
        if len(d_train) < 10 or len(d_test) == 0:
            continue
        if tpms == 'Diamond':
            X_tr = (d_train['Re_fit'].to_numpy(), d_train['eps_f'].to_numpy(),
                    d_train['L_mm'].to_numpy(), d_train['D_h_mm'].to_numpy(),
                    d_train['t'].to_numpy())
            p0 = [0.5, 0.5, 0.5, -1.0, 0.0]
            bounds = ([1e-5, 0, -10, -5, -5], [50, 2, 10, 5, 5])
            try:
                popt, _ = curve_fit(diamond_F5, X_tr, d_train['Nu'].to_numpy(),
                                    p0=p0, bounds=bounds, maxfev=50000)
            except Exception:
                continue
            X_te = (d_test['Re_fit'].to_numpy(), d_test['eps_f'].to_numpy(),
                    d_test['L_mm'].to_numpy(), d_test['D_h_mm'].to_numpy(),
                    d_test['t'].to_numpy())
            Nu_p = diamond_F5(X_te, *popt)
        else:
            X_tr = (d_train['Re_fit'].to_numpy(), d_train['eps_f'].to_numpy(),
                    d_train['L_mm'].to_numpy())
            p0 = [2.38, 0.0277, 0.177, -0.71, 1.74, -1.88]
            bounds = ([1e-4, 1e-4, 0, -5, 0, -5], [10, 5, 1, 5, 10, 5])
            try:
                popt, _ = curve_fit(gyroid_F4G, X_tr, d_train['Nu'].to_numpy(),
                                    p0=p0, bounds=bounds, maxfev=50000)
            except Exception:
                continue
            X_te = (d_test['Re_fit'].to_numpy(), d_test['eps_f'].to_numpy(),
                    d_test['L_mm'].to_numpy())
            Nu_p = gyroid_F4G(X_te, *popt)
        Nu_pred[d.index[sel_test].to_numpy()] = Nu_p
    return d, Nu_pred


def plot_panel(ax_curve, ax_resid, d, Nu_pred, title):
    geoms = sorted(set(zip(d['L'], d['t'])))
    eps_f_all = []
    for (L, t) in geoms:
        idx = d.index[(d['L'] == L) & (d['t'] == t)][0]
        eps_f_all.append(float(d.iloc[idx]['eps_f']))
    eps_f_all = np.array(eps_f_all)
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
                         facecolors='none', edgecolors=c, linewidths=1.0,
                         alpha=0.85)
        ax_curve.plot(Re_g, Nu_loo, '-', color=c, linewidth=1.3, alpha=0.85)
        err = (Nu_loo - Nu_truth) / Nu_truth * 100.0
        ax_resid.scatter(Re_g, err, s=20, color=c, alpha=0.85,
                         edgecolors='black', linewidths=0.3)

    ax_curve.set_xscale('log')
    ax_curve.set_yscale('log')
    ax_curve.set_xlabel(r'$Re$ (single-stream, $\rho u D_h/\mu$)')
    ax_curve.set_ylabel(r'$Nu = h\, D_h / k_f$')
    ax_curve.set_title(f'{title} — CFD truth (○) vs LOO prediction (—)')
    ax_curve.grid(True, which='both', alpha=0.3)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax_curve, pad=0.02)
    cbar.set_label(r'$\varepsilon_f$ (single-stream porosity)')

    err_all = (Nu_pred - d['Nu'].to_numpy()) / d['Nu'].to_numpy() * 100.0
    err_all = err_all[np.isfinite(err_all)]
    rmsre = float(np.sqrt(np.mean(err_all ** 2)))
    bias = float(np.mean(err_all))
    ax_resid.axhline(0, color='black', linewidth=0.7)
    ax_resid.axhline(rmsre, color='red', linewidth=0.6, linestyle='--',
                     label=f'+RMSRE = {rmsre:.2f}%')
    ax_resid.axhline(-rmsre, color='red', linewidth=0.6, linestyle='--')
    ax_resid.set_xscale('log')
    ax_resid.set_xlabel(r'$Re$')
    ax_resid.set_ylabel(r'LOO residual  [%]')
    ax_resid.set_title(f'{title} — LOO residual (bias = {bias:+.2f}%)')
    ax_resid.grid(True, which='both', alpha=0.3)
    ax_resid.legend(loc='upper right', fontsize=8)
    return rmsre, bias


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("Generating Nu LOO error figure for v3 (CFD4 data)")
    print("=" * 60)
    print("Loading + LOO Diamond F5...")
    dD, predD = loo_predictions('Diamond')
    print("Loading + LOO Gyroid F4-G...")
    dG, predG = loo_predictions('Gyroid')

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    rmsre_d, bias_d = plot_panel(axes[0, 0], axes[1, 0], dD, predD,
                                  'Diamond (F5)')
    rmsre_g, bias_g = plot_panel(axes[0, 1], axes[1, 1], dG, predG,
                                  'Gyroid (F4-G)')

    fig.suptitle('Nu LOO error — v3 (CFD4 data, 2026-04-27, smooth-wall, no ×1.28)',
                 fontsize=13, y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.985])

    out_dir = _PROJECT_ROOT.parent / 'reports' / 'figs'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / 'nu_loo_error_re_vs_nu_v3.png'
    fig.savefig(out_png, dpi=150, bbox_inches='tight')

    vault = Path(r'D:\Postgraduate\vault\reports\methodology\figs')
    vault.mkdir(parents=True, exist_ok=True)
    fig.savefig(vault / 'nu_loo_error_re_vs_nu_v3.png', dpi=150, bbox_inches='tight')

    print(f"\nSaved: {out_png}")
    print(f"Saved: {vault / 'nu_loo_error_re_vs_nu_v3.png'}")
    print(f"\nDiamond F5 LOO RMSRE = {rmsre_d:.2f}%  bias = {bias_d:+.2f}%")
    print(f"Gyroid F4-G LOO RMSRE = {rmsre_g:.2f}%  bias = {bias_g:+.2f}%")


if __name__ == '__main__':
    main()
