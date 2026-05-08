"""fit_nu_form_sweep.py — try multiple Nu correlation forms.

All conventions single-stream (ε_f = ε/2, D_h-Re).

Forms tested (per TPMS):
  F1  Dittus-Boelter:           Nu = c · Pr^(1/3) · Re^a
  F2  D-B + porosity:           Nu = c · Pr^(1/3) · Re^a · ε_f^b
  F3  D-B + porosity + length:  Nu = c · Pr^(1/3) · Re^a · ε_f^b · (L_char/Sa)^d
  F4  Variable n (current):     Nu = c · Pr^(1/3) · Re^n · ε_f^b · (L_char/Sa)^d
                                   n = n0 + n1·ln(ε_f)            (Diamond style)
                                   n = c1·Re^c2·ε_f^c3            (Gyroid style)
  F5  Add t/L term:             Nu = c · Pr^(1/3) · Re^a · ε_f^b · (L_char/Sa)^d · (t/L)^e
  F6  Re·Pr Reynolds-Prandtl:    Nu = c · (Re·Pr)^a · ε_f^b · (L_char/Sa)^d
  F7  GP / RBF interpolation:   non-parametric

Per-form: in-sample fit + LOO across geometries.
Output: comparison table.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import geometry as tpms_geometry, Pr, Sa_mm
from df_fit.fit_nu_single_stream import load_data

# ============================================================
# Form definitions (each takes (Re, eps_f, L_mm, D_h_mm, t_mm) → Nu)
# Length scale per TPMS: Diamond uses D_h_mm, Gyroid uses L_mm
# ============================================================

def make_form(form_id, length_scale='D_h'):
    """Returns (model_fn, n_params, p0, bounds) for given form_id.
    length_scale: 'D_h' for Diamond, 'L' for Gyroid.
    """
    if form_id == 'F1':
        # Nu = c · Pr^(1/3) · Re^a
        def model(X, c, a):
            Re, _, _, _, _ = X
            return c * Pr**(1/3) * Re**a
        p0 = [0.05, 0.5]
        bounds = ([1e-5, 0], [10, 2])
        return model, 2, p0, bounds, 'F1: c·Pr^(1/3)·Re^a'

    if form_id == 'F2':
        # Nu = c · Pr^(1/3) · Re^a · ε_f^b
        def model(X, c, a, b):
            Re, eps_f, _, _, _ = X
            return c * Pr**(1/3) * Re**a * eps_f**b
        p0 = [0.05, 0.5, 0.5]
        bounds = ([1e-5, 0, -10], [50, 2, 10])
        return model, 3, p0, bounds, 'F2: c·Pr^(1/3)·Re^a·ε_f^b'

    if form_id == 'F3':
        # Nu = c · Pr^(1/3) · Re^a · ε_f^b · (L_char/Sa)^d
        if length_scale == 'D_h':
            def model(X, c, a, b, d):
                Re, eps_f, _, D_h_mm, _ = X
                return c * Pr**(1/3) * Re**a * eps_f**b * (D_h_mm/(1000*Sa_mm))**d
        else:
            def model(X, c, a, b, d):
                Re, eps_f, L_mm, _, _ = X
                return c * Pr**(1/3) * Re**a * eps_f**b * (L_mm/(1000*Sa_mm))**d
        p0 = [0.5, 0.5, 0.5, -1.0]
        bounds = ([1e-5, 0, -10, -5], [50, 2, 10, 5])
        return model, 4, p0, bounds, 'F3: F2 + (L_char/Sa)^d'

    if form_id == 'F4_diamond':
        # Diamond style variable n
        def model(X, c, n0, n1, b, d):
            Re, eps_f, _, D_h_mm, _ = X
            n = n0 + n1*np.log(eps_f)
            return c * Pr**(1/3) * Re**n * eps_f**b * (D_h_mm/(1000*Sa_mm))**d
        p0 = [0.99, 0.19, -0.53, 6.34, -1.77]
        bounds = ([1e-4, 0, -5, 0, -5], [10, 5, 5, 20, 5])
        return model, 5, p0, bounds, 'F4-D: variable n=n0+n1·ln(ε_f)'

    if form_id == 'F4_gyroid':
        # Gyroid style variable n
        def model(X, c, c1, c2, c3, b, d):
            Re, eps_f, L_mm, _, _ = X
            n = c1 * Re**c2 * eps_f**c3
            return c * Pr**(1/3) * Re**n * eps_f**b * (L_mm/(1000*Sa_mm))**d
        p0 = [2.38, 0.0277, 0.177, -0.71, 1.74, -1.88]
        bounds = ([1e-4, 1e-4, 0, -5, 0, -5], [10, 5, 1, 5, 10, 5])
        return model, 6, p0, bounds, 'F4-G: variable n=c1·Re^c2·ε_f^c3'

    if form_id == 'F5':
        # Add t/L term
        if length_scale == 'D_h':
            def model(X, c, a, b, d, e):
                Re, eps_f, L_mm, D_h_mm, t_mm = X
                return (c * Pr**(1/3) * Re**a * eps_f**b
                        * (D_h_mm/(1000*Sa_mm))**d * (t_mm/L_mm)**e)
        else:
            def model(X, c, a, b, d, e):
                Re, eps_f, L_mm, _, t_mm = X
                return (c * Pr**(1/3) * Re**a * eps_f**b
                        * (L_mm/(1000*Sa_mm))**d * (t_mm/L_mm)**e)
        p0 = [0.5, 0.5, 0.5, -1.0, 0.0]
        bounds = ([1e-5, 0, -10, -5, -5], [50, 2, 10, 5, 5])
        return model, 5, p0, bounds, 'F5: F3 + (t/L)^e'

    if form_id == 'F6':
        # Reynolds-Prandtl product
        if length_scale == 'D_h':
            def model(X, c, a, b, d):
                Re, eps_f, _, D_h_mm, _ = X
                return c * (Re*Pr)**a * eps_f**b * (D_h_mm/(1000*Sa_mm))**d
        else:
            def model(X, c, a, b, d):
                Re, eps_f, L_mm, _, _ = X
                return c * (Re*Pr)**a * eps_f**b * (L_mm/(1000*Sa_mm))**d
        p0 = [0.5, 0.5, 0.5, -1.0]
        bounds = ([1e-5, 0, -10, -5], [50, 2, 10, 5])
        return model, 4, p0, bounds, 'F6: c·(Re·Pr)^a·ε_f^b·(L_char/Sa)^d'

    if form_id == 'F7':
        # F3 + Re^2 cross term (quadratic Re effect)
        if length_scale == 'D_h':
            def model(X, c, a, a2, b, d):
                Re, eps_f, _, D_h_mm, _ = X
                logRe = np.log(np.maximum(Re, 1.0))
                # log Nu = log c + a·logRe + a2·(logRe)^2 + b·log(eps_f) + d·log(L/Sa)
                return (c * np.exp(a2 * logRe**2) * Re**a * eps_f**b
                        * Pr**(1/3) * (D_h_mm/(1000*Sa_mm))**d)
        else:
            def model(X, c, a, a2, b, d):
                Re, eps_f, L_mm, _, _ = X
                logRe = np.log(np.maximum(Re, 1.0))
                return (c * np.exp(a2 * logRe**2) * Re**a * eps_f**b
                        * Pr**(1/3) * (L_mm/(1000*Sa_mm))**d)
        p0 = [0.5, 0.5, 0.0, 0.5, -1.0]
        bounds = ([1e-5, 0, -1, -10, -5], [50, 2, 1, 10, 5])
        return model, 5, p0, bounds, 'F7: log-quadratic Re'

    raise ValueError(form_id)


def fit_one(d, form_id, length_scale):
    Re = d['Re_fit'].to_numpy()
    eps_f = d['eps_f'].to_numpy()
    L_mm = d['L_mm'].to_numpy()
    D_h_mm = d['D_h_mm'].to_numpy()
    t_mm = d['t'].to_numpy()
    Nu = d['Nu'].to_numpy()
    X = (Re, eps_f, L_mm, D_h_mm, t_mm)
    model, n_params, p0, bounds, label = make_form(form_id, length_scale)
    try:
        popt, _ = curve_fit(model, X, Nu, p0=p0, bounds=bounds, maxfev=50000)
        Nu_pred = model(X, *popt)
        err = (Nu_pred - Nu) / Nu
        rmsre = float(np.sqrt(np.mean(err**2)) * 100)
        bias = float(np.mean(err) * 100)
        return label, n_params, popt, rmsre, bias
    except Exception as e:
        return label, n_params, None, float('nan'), float('nan')


def loo_one(d, form_id, length_scale):
    """Leave-one-geometry-out cross-validation."""
    geoms = sorted(set(zip(d['L'], d['t'])))
    err_all = []
    for L_test, t_test in geoms:
        sel = (d['L'] == L_test) & (d['t'] == t_test)
        d_train = d[~sel]
        d_test = d[sel]
        if len(d_train) < 10 or len(d_test) == 0:
            continue
        Re = d_train['Re_fit'].to_numpy()
        eps_f = d_train['eps_f'].to_numpy()
        L_mm = d_train['L_mm'].to_numpy()
        D_h_mm = d_train['D_h_mm'].to_numpy()
        t_mm = d_train['t'].to_numpy()
        Nu = d_train['Nu'].to_numpy()
        X_tr = (Re, eps_f, L_mm, D_h_mm, t_mm)
        model, _, p0, bounds, _ = make_form(form_id, length_scale)
        try:
            popt, _ = curve_fit(model, X_tr, Nu, p0=p0, bounds=bounds, maxfev=50000)
        except Exception:
            continue
        X_te = (d_test['Re_fit'].to_numpy(), d_test['eps_f'].to_numpy(),
                d_test['L_mm'].to_numpy(), d_test['D_h_mm'].to_numpy(),
                d_test['t'].to_numpy())
        Nu_pred = model(X_te, *popt)
        Nu_true = d_test['Nu'].to_numpy()
        err = (Nu_pred - Nu_true) / Nu_true
        err_all.extend(err.tolist())
    if not err_all:
        return float('nan'), float('nan')
    err_all = np.array(err_all)
    return (float(np.sqrt(np.mean(err_all**2))*100),
            float(np.mean(err_all)*100))


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("Form sweep — single-stream Nu correlation\n" + "=" * 72)

    for tpms in ('Diamond', 'Gyroid'):
        d = load_data(tpms)
        n_geoms = len(set(zip(d['L'], d['t'])))
        length_scale = 'D_h' if tpms == 'Diamond' else 'L'
        print(f"\n--- {tpms} ({len(d)} rows, {n_geoms} geometries, length scale = {length_scale}) ---")
        print(f"  {'Form':<40}  {'#par':>4}  {'IS%':>6}  {'IS bias%':>8}  {'LOO%':>6}  {'LOO bias%':>9}")
        print(f"  {'-'*40}  {'-'*4}  {'-'*6}  {'-'*8}  {'-'*6}  {'-'*9}")

        forms = ['F1', 'F2', 'F3', f'F4_{tpms.lower()}', 'F5', 'F6', 'F7']
        for form_id in forms:
            label, np_, popt, is_rmsre, is_bias = fit_one(d, form_id, length_scale)
            loo_rmsre, loo_bias = loo_one(d, form_id, length_scale)
            label_short = label[:40]
            print(f"  {label_short:<40}  {np_:>4d}  "
                  f"{is_rmsre:>5.2f}  {is_bias:>+7.2f}  "
                  f"{loo_rmsre:>5.2f}  {loo_bias:>+8.2f}")
            if popt is not None and form_id == f'F4_{tpms.lower()}':
                pass  # current production form, already known


if __name__ == '__main__':
    main()
