"""plot_nu_loo_error.py — Re vs Nu LOO interpolation error figure.

Generates 4-panel figure:
  top-left:   Diamond Re vs Nu — CFD truth scatter + LOO predicted curves per geometry
  top-right:  Gyroid same
  bot-left:   Diamond LOO residual (%) vs Re, colored by ε_f
  bot-right:  Gyroid same

Smooth-wall fit only — NO ×1.28 roughness factor applied (LOO assesses
intrinsic interpolation accuracy on smooth-CFD training data).

Usage:
  python -u -m sjtu_tpmshx.df_fit.plot_nu_loo_error
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import cm
from matplotlib.colors import Normalize

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from df_fit.fit_nu_single_stream import (
    load_data, fit_diamond, diamond_model,
)
from scipy.optimize import curve_fit
from solvers.tpms_calc import Pr, Sa_mm


# Gyroid F7 form (production) — log-quadratic Re, length scale = L
def gyroid_F7_model(X, c, a, a2, b, d):
    """X: (Re, eps_f, L_mm). Form: c·exp(a2·(ln Re)²)·Re^a·ε_f^b·Pr^(1/3)·(L/Sa)^d."""
    Re, eps_f, L_mm = X
    logRe = np.log(np.maximum(Re, 1.0))
    return (c * np.exp(a2 * logRe ** 2) * Re ** a * eps_f ** b
            * Pr ** (1 / 3) * (L_mm / (1000 * Sa_mm)) ** d)


def fit_gyroid_F7(d):
    Re = d['Re_fit'].to_numpy()
    eps_f = d['eps_f'].to_numpy()
    L_mm = d['L_mm'].to_numpy()
    Nu = d['Nu'].to_numpy()
    X = (Re, eps_f, L_mm)
    p0 = [0.5, 0.5, 0.0, 0.5, -1.0]
    bounds = ([1e-5, 0, -1, -10, -5], [50, 2, 1, 10, 5])
    try:
        popt, _ = curve_fit(gyroid_F7_model, X, Nu, p0=p0, bounds=bounds,
                            maxfev=50000)
        Nu_pred = gyroid_F7_model(X, *popt)
        err = (Nu_pred - Nu) / Nu
        return dict(c=popt[0], a=popt[1], a2=popt[2], b=popt[3], d=popt[4],
                    rmsre=float(np.sqrt(np.mean(err ** 2)) * 100),
                    bias=float(np.mean(err) * 100))
    except Exception:
        return None


def loo_predictions(tpms: str):
    """Run LOO; return (df, Nu_pred_loo, fit_info_per_geom).

    Diamond uses F4-D form (fit_diamond), Gyroid uses F7 (production).
    """
    d = load_data(tpms)
    geoms = sorted(set(zip(d['L'], d['t'])))
    Nu_pred = np.full(len(d), np.nan)
    fits = {}
    for L_test, t_test in geoms:
        sel_test = (d['L'] == L_test) & (d['t'] == t_test)
        d_train = d[~sel_test]
        d_test = d[sel_test]
        if len(d_train) < 10 or len(d_test) == 0:
            continue
        if tpms == 'Diamond':
            fit = fit_diamond(d_train)
            if fit is None:
                continue
            X_test = (d_test['Re_fit'].to_numpy(),
                      d_test['eps_f'].to_numpy(),
                      d_test['D_h_mm'].to_numpy())
            pred = diamond_model(X_test, fit['c'], fit['n0'], fit['n1'],
                                 fit['a'], fit['b'])
        else:
            fit = fit_gyroid_F7(d_train)
            if fit is None:
                continue
            X_test = (d_test['Re_fit'].to_numpy(),
                      d_test['eps_f'].to_numpy(),
                      d_test['L_mm'].to_numpy())
            pred = gyroid_F7_model(X_test, fit['c'], fit['a'], fit['a2'],
                                   fit['b'], fit['d'])
        idx = d.index[sel_test].to_numpy()
        Nu_pred[idx] = pred
        fits[(L_test, t_test)] = fit
    return d, Nu_pred, fits


def plot_panel(ax_curve, ax_resid, d, Nu_pred, tpms_name):
    """Plot Re vs Nu (top) + residual vs Re (bot) for one TPMS."""
    geoms = sorted(set(zip(d['L'], d['t'])))
    eps_f_all = np.array([d.iloc[d.index[(d['L'] == L) & (d['t'] == t)][0]]['eps_f']
                          for (L, t) in geoms])
    norm = Normalize(vmin=eps_f_all.min(), vmax=eps_f_all.max())
    cmap = plt.get_cmap('viridis')

    # Top: Re vs Nu — CFD scatter + LOO line per geom
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
                         alpha=0.85, label=None)
        ax_curve.plot(Re_g, Nu_loo, '-', color=c, linewidth=1.3,
                      alpha=0.85, label=f'L={L:.0f} t={t:.1f}')

        # Bot: residual % vs Re
        err = (Nu_loo - Nu_truth) / Nu_truth * 100.0
        ax_resid.scatter(Re_g, err, s=20, color=c, alpha=0.85,
                         edgecolors='black', linewidths=0.3)

    # Top fmt
    ax_curve.set_xscale('log')
    ax_curve.set_yscale('log')
    ax_curve.set_xlabel(r'$Re$ (single-stream, $\rho u D_h/\mu$)')
    ax_curve.set_ylabel(r'$Nu = h\, D_h / k_f$')
    ax_curve.set_title(f'{tpms_name} — CFD truth (○) vs LOO prediction (—)')
    ax_curve.grid(True, which='both', alpha=0.3)
    sm = cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax_curve, pad=0.02)
    cbar.set_label(r'$\varepsilon_f$ (single-stream porosity)')

    # Bot fmt
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
    ax_resid.set_ylabel(r'LOO residual $(Nu_{pred} - Nu_{CFD}) / Nu_{CFD}$  [%]')
    ax_resid.set_title(f'{tpms_name} — LOO residual  (bias = {bias:+.2f}%)')
    ax_resid.grid(True, which='both', alpha=0.3)
    ax_resid.legend(loc='upper right', fontsize=8)
    return rmsre, bias


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("Generating Nu LOO error figure (smooth-wall, no ×1.28)")
    print("=" * 60)

    print("Loading + LOO Diamond...")
    d_d, pred_d, _ = loo_predictions('Diamond')
    print(f"  {len(d_d)} rows, {len(set(zip(d_d['L'], d_d['t'])))} geometries")
    print("Loading + LOO Gyroid...")
    d_g, pred_g, _ = loo_predictions('Gyroid')
    print(f"  {len(d_g)} rows, {len(set(zip(d_g['L'], d_g['t'])))} geometries")

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    rmsre_d, bias_d = plot_panel(axes[0, 0], axes[1, 0], d_d, pred_d, 'Diamond (F4-D)')
    rmsre_g, bias_g = plot_panel(axes[0, 1], axes[1, 1], d_g, pred_g, 'Gyroid (F7)')

    fig.suptitle('Nu LOO interpolation error — smooth-wall fit (no ×1.28 roughness factor)',
                 fontsize=13, y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.985])

    out_dir = _PROJECT_ROOT.parent / 'reports' / 'figs'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / 'nu_loo_error_re_vs_nu.png'
    fig.savefig(out_png, dpi=150, bbox_inches='tight')
    print(f"\nSaved: {out_png}")

    # Also save to vault for narrative
    vault_dir = Path(r'D:\Postgraduate\vault\reports\methodology\figs')
    vault_dir.mkdir(parents=True, exist_ok=True)
    vault_png = vault_dir / 'nu_loo_error_re_vs_nu.png'
    fig.savefig(vault_png, dpi=150, bbox_inches='tight')
    print(f"Saved: {vault_png}")

    print(f"\nDiamond LOO RMSRE = {rmsre_d:.2f}%  bias = {bias_d:+.2f}%")
    print(f"Gyroid  LOO RMSRE = {rmsre_g:.2f}%  bias = {bias_g:+.2f}%")


if __name__ == '__main__':
    main()
