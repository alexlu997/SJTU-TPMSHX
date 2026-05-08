"""fit_gyroid_F7.py — final Gyroid Nu fit using F7 form.

F7: Nu = c · exp(a2·(logRe)^2) · Re^a · Pr^(1/3) · ε_f^b · (L/(1000·Sa))^d
    (log-quadratic Re modifier)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
from scipy.optimize import curve_fit

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import Pr, Sa_mm
from df_fit.fit_nu_single_stream import load_data


def gyroid_F7(X, c, a, a2, b, d):
    """F7 form: log-quadratic Re modifier."""
    Re, eps_f, L_mm = X
    logRe = np.log(np.maximum(Re, 1.0))
    return (c * np.exp(a2 * logRe**2) * Re**a * Pr**(1/3)
            * eps_f**b * (L_mm/(1000*Sa_mm))**d)


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    d = load_data('Gyroid')
    print(f"Gyroid F7 fit ({len(d)} rows, {len(set(zip(d['L'], d['t'])))} geometries)")
    Re = d['Re_fit'].to_numpy()
    eps_f = d['eps_f'].to_numpy()
    L_mm = d['L_mm'].to_numpy()
    Nu = d['Nu'].to_numpy()
    X = (Re, eps_f, L_mm)
    p0 = [0.5, 0.5, 0.0, 0.5, -1.0]
    bounds = ([1e-5, 0, -1, -10, -5], [50, 2, 1, 10, 5])
    popt, _ = curve_fit(gyroid_F7, X, Nu, p0=p0, bounds=bounds, maxfev=50000)
    Nu_pred = gyroid_F7(X, *popt)
    err = (Nu_pred - Nu) / Nu
    rmsre = float(np.sqrt(np.mean(err**2))*100)
    bias = float(np.mean(err)*100)

    # LOO
    geoms = sorted(set(zip(d['L'], d['t'])))
    err_loo = []
    for L_t, t_t in geoms:
        sel = (d['L'] == L_t) & (d['t'] == t_t)
        d_train = d[~sel]; d_test = d[sel]
        if len(d_train) < 10 or len(d_test) == 0:
            continue
        Xt = (d_train['Re_fit'].to_numpy(), d_train['eps_f'].to_numpy(),
               d_train['L_mm'].to_numpy())
        try:
            popt_t, _ = curve_fit(gyroid_F7, Xt, d_train['Nu'].to_numpy(),
                                    p0=p0, bounds=bounds, maxfev=50000)
        except Exception:
            continue
        Xs = (d_test['Re_fit'].to_numpy(), d_test['eps_f'].to_numpy(),
               d_test['L_mm'].to_numpy())
        Nu_p = gyroid_F7(Xs, *popt_t)
        err_loo.extend(((Nu_p - d_test['Nu'].to_numpy()) / d_test['Nu'].to_numpy()).tolist())
    err_loo = np.array(err_loo)
    loo_rmsre = float(np.sqrt(np.mean(err_loo**2))*100)
    loo_bias = float(np.mean(err_loo)*100)

    c, a, a2, b, dd = popt
    print(f"\nIn-sample: RMSRE={rmsre:.2f}%  bias={bias:+.2f}%")
    print(f"LOO:       RMSRE={loo_rmsre:.2f}%  bias={loo_bias:+.2f}%")
    print(f"\nCoefficients:")
    print(f"  c  = {c:.6f}")
    print(f"  a  = {a:.6f}    (Re exponent base)")
    print(f"  a2 = {a2:.6f}   (log-quadratic Re modifier)")
    print(f"  b  = {b:.6f}    (ε_f exponent)")
    print(f"  d  = {dd:.6f}   (L/Sa exponent)")
    print(f"\nFormula:")
    print(f"  Nu = {c:.4f} · exp({a2:.6f}·(ln Re)^2) · Re^{a:.4f} · Pr^(1/3) · ε_f^{b:.3f} · (L_mm/(1000·Sa))^{dd:.3f}")

    # Sanity: Shanghai L=7 t=0.6 prediction at multiple Re
    print(f"\nShanghai test (L=7mm, t=0.6mm, ε_f=0.3684):")
    eps_f_s = 0.3684
    L_s = 7.0
    for Re_s in [526, 1480, 4460, 9981]:
        X_s = (np.array([Re_s]), np.array([eps_f_s]), np.array([L_s]))
        Nu_s = float(gyroid_F7(X_s, *popt))
        print(f"  Re={Re_s:5d} → Nu_pred = {Nu_s:.2f}")


if __name__ == '__main__':
    main()
