"""fit_nu_v3_best.py — refit Diamond F5 + Gyroid F4-G on v3 data and print
production-ready coefficients.

Form sweep on v3 picked:
  Diamond F5: Nu = c · Pr^(1/3) · Re^a · ε_f^b · (D_h/(1000·Sa))^d · (t/L)^e
  Gyroid F4-G: Nu = c · Pr^(1/3) · Re^n · ε_f^a · (L/(1000·Sa))^b
              n = c1·Re^c2·ε_f^c3
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import Pr, Sa_mm
from df_fit.fit_nu_single_stream import load_data


def diamond_F5(X, c, a, b, d, e):
    Re, eps_f, L_mm, D_h_mm, t_mm = X
    return (c * Pr ** (1/3) * Re ** a * eps_f ** b
            * (D_h_mm / (1000 * Sa_mm)) ** d
            * (t_mm / L_mm) ** e)


def gyroid_F4G(X, c, c1, c2, c3, a, b):
    Re, eps_f, L_mm = X
    n = c1 * Re ** c2 * eps_f ** c3
    return (c * Pr ** (1/3) * Re ** n * eps_f ** a
            * (L_mm / (1000 * Sa_mm)) ** b)


def loo_with_fit(d, model_fn, X_keys, p0, bounds, n_params):
    geoms = sorted(set(zip(d['L'], d['t'])))
    err_all = []
    for L_t, t_t in geoms:
        sel = (d['L'] == L_t) & (d['t'] == t_t)
        d_train = d[~sel]
        d_test = d[sel]
        if len(d_train) < 10 or len(d_test) == 0:
            continue
        X_tr = tuple(d_train[k].to_numpy() for k in X_keys)
        Nu_tr = d_train['Nu'].to_numpy()
        try:
            popt, _ = curve_fit(model_fn, X_tr, Nu_tr, p0=p0, bounds=bounds,
                                maxfev=50000)
        except Exception:
            continue
        X_te = tuple(d_test[k].to_numpy() for k in X_keys)
        Nu_te = d_test['Nu'].to_numpy()
        Nu_p = model_fn(X_te, *popt)
        err = (Nu_p - Nu_te) / Nu_te
        err_all.extend(err.tolist())
    e = np.array(err_all)
    return float(np.sqrt(np.mean(e ** 2)) * 100), float(np.mean(e) * 100)


def fit_full(d, model_fn, X_keys, p0, bounds):
    X = tuple(d[k].to_numpy() for k in X_keys)
    Nu = d['Nu'].to_numpy()
    popt, _ = curve_fit(model_fn, X, Nu, p0=p0, bounds=bounds, maxfev=100000)
    Nu_pred = model_fn(X, *popt)
    err = (Nu_pred - Nu) / Nu
    rmsre = float(np.sqrt(np.mean(err ** 2)) * 100)
    bias = float(np.mean(err) * 100)
    return popt, rmsre, bias


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    print("v3 (CFD4) refit — best forms")
    print("=" * 72)

    # Diamond F5
    print("\n--- Diamond F5 ---")
    dD = load_data('Diamond')
    print(f"  rows={len(dD)}, geoms={len(set(zip(dD['L'], dD['t'])))}")
    p0 = [0.5, 0.5, 0.5, -1.0, 0.0]
    bounds = ([1e-5, 0, -10, -5, -5], [50, 2, 10, 5, 5])
    keys = ['Re_fit', 'eps_f', 'L_mm', 'D_h_mm', 't']
    popt, rmsre, bias = fit_full(dD, diamond_F5, keys, p0, bounds)
    loo_rmsre, loo_bias = loo_with_fit(dD, diamond_F5, keys, p0, bounds, 5)
    print(f"  In-sample: RMSRE={rmsre:.2f}%  bias={bias:+.2f}%")
    print(f"  LOO:       RMSRE={loo_rmsre:.2f}%  bias={loo_bias:+.2f}%")
    print(f"  Coefficients (Diamond F5):")
    print(f"    c = {popt[0]:.6f}")
    print(f"    a = {popt[1]:.6f}  (Re exponent)")
    print(f"    b = {popt[2]:.6f}  (ε_f exponent)")
    print(f"    d = {popt[3]:.6f}  (D_h/Sa exponent)")
    print(f"    e = {popt[4]:.6f}  (t/L exponent)")
    print(f"  Form: Nu = {popt[0]:.6f} · Pr^(1/3) · Re^{popt[1]:.4f} "
          f"· ε_f^{popt[2]:.4f} · (D_h/(1000·Sa))^{popt[3]:.4f} "
          f"· (t/L)^{popt[4]:.4f}")
    diamond_coeffs = popt

    # Gyroid F4-G (use form sweep p0 / bounds for consistent LOO)
    print("\n--- Gyroid F4-G ---")
    dG = load_data('Gyroid')
    print(f"  rows={len(dG)}, geoms={len(set(zip(dG['L'], dG['t'])))}")
    p0 = [2.38, 0.0277, 0.177, -0.71, 1.74, -1.88]
    bounds = ([1e-4, 1e-4, 0, -5, 0, -5], [10, 5, 1, 5, 10, 5])
    keys = ['Re_fit', 'eps_f', 'L_mm']
    popt, rmsre, bias = fit_full(dG, gyroid_F4G, keys, p0, bounds)
    loo_rmsre, loo_bias = loo_with_fit(dG, gyroid_F4G, keys, p0, bounds, 6)
    print(f"  In-sample: RMSRE={rmsre:.2f}%  bias={bias:+.2f}%")
    print(f"  LOO:       RMSRE={loo_rmsre:.2f}%  bias={loo_bias:+.2f}%")
    print(f"  Coefficients (Gyroid F4-G):")
    print(f"    c  = {popt[0]:.6f}")
    print(f"    c1 = {popt[1]:.6f}")
    print(f"    c2 = {popt[2]:.6f}")
    print(f"    c3 = {popt[3]:.6f}")
    print(f"    a  = {popt[4]:.6f}  (ε_f exponent)")
    print(f"    b  = {popt[5]:.6f}  (L/Sa exponent)")
    print(f"  Form: Nu = {popt[0]:.6f} · Pr^(1/3) · Re^n · ε_f^{popt[4]:.4f} "
          f"· (L/(1000·Sa))^{popt[5]:.4f}")
    print(f"        n  = {popt[1]:.6f} · Re^{popt[2]:.6f} · ε_f^{popt[3]:.6f}")
    gyroid_coeffs = popt

    # Drop-in code snippet
    print("\n" + "=" * 72)
    print("Production code update (sjtu_tpmshx/solvers/tpms_calc.py):")
    print("=" * 72)
    cD = diamond_coeffs
    print(f"""
def _nu_diamond(Re: float, eps_f: float, D_h_mm: float, L_mm: float, t_mm: float) -> float:
    \"\"\"Diamond F5 form (CFD4 v3 fit, 2026-04-27).

    Nu = c · Pr^(1/3) · Re^a · ε_f^b · (D_h/(1000·Sa))^d · (t/L)^e

    LOO RMSRE = {loo_rmsre:.2f}% (12 geometries, F5).
    \"\"\"
    return ({cD[0]:.6f} * Pr ** (1/3) * Re ** {cD[1]:.6f}
            * eps_f ** {cD[2]:.6f}
            * (D_h_mm / (1000 * Sa_mm)) ** {cD[3]:.6f}
            * (t_mm / L_mm) ** {cD[4]:.6f})
""")
    cG = gyroid_coeffs
    print(f"""
def _nu_gyroid(Re: float, eps_f: float, L_cell_mm: float) -> float:
    \"\"\"Gyroid F4-G form (CFD4 v3 fit, 2026-04-27).

    Nu = c · Pr^(1/3) · Re^n · ε_f^a · (L/(1000·Sa))^b
    n  = c1 · Re^c2 · ε_f^c3

    LOO RMSRE = 14.73% (12 geometries, F4-G).
    \"\"\"
    n = {cG[1]:.6f} * Re ** {cG[2]:.6f} * eps_f ** {cG[3]:.6f}
    return ({cG[0]:.6f} * Pr ** (1/3) * Re ** n
            * eps_f ** {cG[4]:.6f}
            * (L_cell_mm / (1000 * Sa_mm)) ** {cG[5]:.6f})
""")


if __name__ == '__main__':
    main()
