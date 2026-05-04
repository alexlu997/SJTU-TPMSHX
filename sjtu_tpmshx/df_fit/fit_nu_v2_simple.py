"""fit_nu_v2_simple.py — refit Nu on v2 data with simpler unified form.

Goal: high accuracy + simple form. Sa included explicitly via (D_h/Sa)
or (L/Sa) ratio. Single-stream convention (ε_f = ε/2, Re D_h-based).

Forms tried (per TPMS, length scale = D_h for Diamond, L for Gyroid):

  A1: Nu = c · Pr^(1/3) · Re^a                            [3p]
  A2: Nu = c · Pr^(1/3) · Re^a · ε_f^b                    [4p]
  A3: Nu = c · Pr^(1/3) · Re^a · ε_f^b · (X/Sa)^d         [5p]  ← Sa explicit
  A4: var-n form  n = n0 + n1·ln(ε_f)
        Nu = c · Pr^(1/3) · Re^n · ε_f^b · (X/Sa)^d        [6p]
  A5: combined: Nu = c · Pr^(1/3) · Re^a · ε_f^b · (X/Sa)^d · (t/L)^e  [6p]

Roughness 1.28 enhancement (smooth-CFD vs printed-rough wall) is applied
post-fit as a global multiplier in production, NOT inside the fit.
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


# ─────────────────────────────────────────────────────────────
# Forms (X = length scale: D_h for Diamond, L for Gyroid)
# ─────────────────────────────────────────────────────────────

def m_A1(X, c, a):
    Re, eps_f, X_mm = X
    return c * Pr**(1/3) * Re**a


def m_A2(X, c, a, b):
    Re, eps_f, X_mm = X
    return c * Pr**(1/3) * Re**a * eps_f**b


def m_A3(X, c, a, b, d):
    Re, eps_f, X_mm = X
    return c * Pr**(1/3) * Re**a * eps_f**b * (X_mm / (1000*Sa_mm))**d


def m_A4(X, c, n0, n1, b, d):
    Re, eps_f, X_mm = X
    n = n0 + n1 * np.log(eps_f)
    return c * Pr**(1/3) * Re**n * eps_f**b * (X_mm / (1000*Sa_mm))**d


def m_A5(X, c, a, b, d, e):
    Re, eps_f, X_mm, tL = X
    return (c * Pr**(1/3) * Re**a * eps_f**b
            * (X_mm / (1000*Sa_mm))**d * tL**e)


# ─────────────────────────────────────────────────────────────
# Fit + LOO
# ─────────────────────────────────────────────────────────────

def _build_X(d, length='D_h'):
    Re = d['Re_fit'].to_numpy()
    eps_f = d['eps_f'].to_numpy()
    X_mm = (d['D_h_mm'].to_numpy() if length == 'D_h'
            else d['L_mm'].to_numpy())
    return Re, eps_f, X_mm


def _fit_one(model, p0, bounds, d, length='D_h', extra_t=False):
    X = _build_X(d, length)
    Nu = d['Nu'].to_numpy()
    if extra_t:
        tL = (d['t'] / d['L']).to_numpy()
        X = X + (tL,)
    try:
        popt, _ = curve_fit(model, X, Nu, p0=p0, bounds=bounds, maxfev=30000)
        Nu_pred = model(X, *popt)
        err = (Nu_pred - Nu) / Nu
        rmsre = float(np.sqrt(np.mean(err**2)) * 100)
        bias = float(np.mean(err) * 100)
        return popt, rmsre, bias
    except Exception as e:
        return None, np.nan, np.nan


def _loo(model, p0, bounds, d, length='D_h', extra_t=False):
    geoms = sorted(set(zip(d['L'], d['t'])))
    err_all = []
    for L_t, t_t in geoms:
        sel = (d['L'] == L_t) & (d['t'] == t_t)
        d_tr = d[~sel]
        d_te = d[sel]
        if len(d_tr) < 10 or len(d_te) == 0:
            continue
        out = _fit_one(model, p0, bounds, d_tr, length, extra_t)
        if out[0] is None:
            continue
        popt = out[0]
        X_te = _build_X(d_te, length)
        if extra_t:
            X_te = X_te + ((d_te['t'] / d_te['L']).to_numpy(),)
        Nu_pred = model(X_te, *popt)
        err = (Nu_pred - d_te['Nu'].to_numpy()) / d_te['Nu'].to_numpy()
        err_all.extend(err.tolist())
    err_all = np.array(err_all)
    return (float(np.sqrt(np.mean(err_all**2))*100),
            float(np.mean(err_all)*100))


# ─────────────────────────────────────────────────────────────
# Sweep
# ─────────────────────────────────────────────────────────────

CONFIGS = [
    dict(name='A1', model=m_A1, p0=[0.1, 0.6],
         bounds=([1e-6, 0], [100, 2]), n_par=3, length=None),
    dict(name='A2', model=m_A2, p0=[0.1, 0.6, 1.0],
         bounds=([1e-6, 0, -10], [100, 2, 10]), n_par=4, length=None),
    dict(name='A3', model=m_A3, p0=[0.5, 0.6, 1.0, 0.5],
         bounds=([1e-6, 0, -10, -5], [100, 2, 10, 5]), n_par=5, length=None),
    dict(name='A4', model=m_A4, p0=[1.0, 0.5, -0.5, 3.0, 0.0],
         bounds=([1e-6, 0, -5, -10, -5], [100, 5, 5, 20, 5]),
         n_par=6, length=None),
    dict(name='A5', model=m_A5,
         p0=[0.5, 0.6, 1.0, 0.5, 0.0],
         bounds=([1e-6, 0, -10, -5, -5], [100, 2, 10, 5, 5]),
         n_par=6, length=None, extra_t=True),
]


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("Nu refit v2 — simpler unified form sweep")
    print("=" * 78)

    for tpms in ('Diamond', 'Gyroid'):
        d = load_data(tpms)
        length = 'D_h' if tpms == 'Diamond' else 'L'
        print(f"\n--- {tpms} ({len(d)} rows, "
              f"{len(set(zip(d['L'], d['t'])))} geoms, length={length}) ---")
        print(f"  Form  #par   IS%   bias%    LOO%   bias%   coeffs")
        print(f"  ----  ----  -----  -----   -----  -----   ------")
        for cfg in CONFIGS:
            extra_t = cfg.get('extra_t', False)
            popt, rmsre_is, bias_is = _fit_one(
                cfg['model'], cfg['p0'], cfg['bounds'], d, length, extra_t)
            if popt is None:
                print(f"  {cfg['name']:<4}  {cfg['n_par']:<4}   FAIL")
                continue
            rmsre_loo, bias_loo = _loo(
                cfg['model'], cfg['p0'], cfg['bounds'], d, length, extra_t)
            coeffs_s = ', '.join(f'{p:.3f}' for p in popt)
            print(f"  {cfg['name']:<4}  {cfg['n_par']:<4}  {rmsre_is:5.2f}  "
                  f"{bias_is:+5.2f}   {rmsre_loo:5.2f}  {bias_loo:+5.2f}   "
                  f"[{coeffs_s}]")


if __name__ == '__main__':
    main()
