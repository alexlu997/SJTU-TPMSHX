"""fit_nu_v4_brainstorm.py — Phase 2-3 of Gyroid Nu improvement plan.

Tests 4 new forms vs current 4p log-quad baseline:
  B1  Churchill-Usagi asymptotic match (Nu_lam, Nu_turb, p)
  B2  Additive two-term (c1·Re^a1 + c2·Re^a2)
  B5  Colburn j-factor (fit j(Re) instead of Nu(Re))
  C2  Tortuosity τ explicit (TPMS-specific feature)

τ is computed inline (not via tpms_geometry extension). Formula:
  τ_Gyroid = 1 + 1.5 · (1 - ε_full) (Iyer 2022)
  τ_Diamond = 1 + 1.2 · (1 - ε_full)

Each form: full LOO sweep + IS RMSRE + Shanghai forward Q validation.
Output: comparison table + Top form coefficients.
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

from solvers.tpms_calc import (
    Pr, Sa_mm, geometry as tpms_geometry,
    air_density, air_viscosity, air_conductivity, air_cp, P_atm,
)
from df_fit.fit_nu_single_stream import load_data


# ── Tortuosity inline ──
def tortuosity(tpms: str, eps_full: float) -> float:
    """τ ~ 1 + k·(1-ε_full). k from literature (Iyer 2022, Tang 2024)."""
    k = 1.5 if tpms == 'Gyroid' else 1.2
    return 1.0 + k * (1.0 - eps_full)


def add_tau(d, tpms):
    eps_full = d['eps_f'].to_numpy() * 2.0
    d = d.copy()
    d['tau'] = np.array([tortuosity(tpms, e) for e in eps_full])
    return d


# ── Forms ──
def f_baseline_logquad(X, c, a2, b, d):
    """4p current production: log-quad Re + ε_f + (D_h/L)."""
    Re, e, L, D, t, tau = X
    logRe = np.log(np.maximum(Re, 1.0))
    return c * Pr**(1/3) * np.exp(a2 * logRe**2) * e**b * (D/L)**d


def f_baseline_pwlaw(X, c, a, b, d):
    """4p pure power-law (no log-quad, comparison)."""
    Re, e, L, D, t, tau = X
    return c * Pr**(1/3) * Re**a * e**b * (D/L)**d


def f_B1_churchill(X, c1, a1, c2, a2, b, d, p):
    """B1: Churchill-Usagi asymptotic match. 7p."""
    Re, e, L, D, t, tau = X
    Pr_term = Pr**(1/3) * e**b * (D/L)**d
    Nu_lam = c1 * Re**a1 * Pr_term
    Nu_turb = c2 * Re**a2 * Pr_term
    return (Nu_lam**p + Nu_turb**p) ** (1/p)


def f_B1_churchill_p4(X, c1, a1, c2, a2, b, d):
    """B1 with p=4 fixed. 6p."""
    Re, e, L, D, t, tau = X
    Pr_term = Pr**(1/3) * e**b * (D/L)**d
    Nu_lam = c1 * Re**a1 * Pr_term
    Nu_turb = c2 * Re**a2 * Pr_term
    return (Nu_lam**4 + Nu_turb**4) ** (1/4)


def f_B2_additive(X, c1, a1, c2, a2, b, d):
    """B2: Additive two-term. 6p."""
    Re, e, L, D, t, tau = X
    Pr_term = Pr**(1/3) * e**b * (D/L)**d
    return (c1 * Re**a1 + c2 * Re**a2) * Pr_term


def f_B5_colburn(X, c, a, b, d):
    """B5: Colburn j-factor. Fit j(Re), return Nu = j·Re·Pr^(1/3). 4p."""
    Re, e, L, D, t, tau = X
    j = c * Re**a * e**b * (D/L)**d
    return j * Re * Pr**(1/3)


def f_C2_tortuosity(X, c, a, b, d, e_tau):
    """C2: tortuosity feature. 5p."""
    Re, e, L, D, t, tau = X
    return c * Pr**(1/3) * Re**a * e**b * (D/L)**d * tau**e_tau


def f_C2_tau_logquad(X, c, a2, b, d, e_tau):
    """C2 + log-quad combo (5p)."""
    Re, e, L, D, t, tau = X
    logRe = np.log(np.maximum(Re, 1.0))
    return c * Pr**(1/3) * np.exp(a2*logRe**2) * e**b * (D/L)**d * tau**e_tau


# ── LOO ──
def loo_form(d, fn, p0, bounds):
    geoms = sorted(set(zip(d['L'], d['t'])))
    err_all = []
    for L_t, t_t in geoms:
        sel = (d['L'] == L_t) & (d['t'] == t_t)
        d_tr = d[~sel]
        d_te = d[sel]
        if len(d_tr) < 10 or len(d_te) == 0:
            continue
        X_tr = (d_tr['Re_fit'].values, d_tr['eps_f'].values,
                d_tr['L_mm'].values, d_tr['D_h_mm'].values,
                d_tr['t'].values, d_tr['tau'].values)
        try:
            popt, _ = curve_fit(fn, X_tr, d_tr['Nu'].values,
                                p0=p0, bounds=bounds, maxfev=300000)
        except Exception:
            continue
        X_te = (d_te['Re_fit'].values, d_te['eps_f'].values,
                d_te['L_mm'].values, d_te['D_h_mm'].values,
                d_te['t'].values, d_te['tau'].values)
        Nu_p = fn(X_te, *popt)
        Nu_t = d_te['Nu'].values
        err = (Nu_p - Nu_t) / Nu_t
        err_all.extend(err.tolist())
    if not err_all:
        return float('nan'), float('nan')
    e = np.array(err_all)
    return float(np.sqrt(np.mean(e**2))*100), float(np.mean(e)*100)


def fit_full(d, fn, p0, bounds):
    X = (d['Re_fit'].values, d['eps_f'].values,
         d['L_mm'].values, d['D_h_mm'].values,
         d['t'].values, d['tau'].values)
    Nu = d['Nu'].values
    try:
        popt, _ = curve_fit(fn, X, Nu, p0=p0, bounds=bounds, maxfev=300000)
    except Exception as ex:
        return None, float('nan'), float('nan')
    Nu_p = fn(X, *popt)
    err = (Nu_p - Nu) / Nu
    rmsre = float(np.sqrt(np.mean(err**2))*100)
    bias = float(np.mean(err)*100)
    return popt, rmsre, bias


# ── Forms registry ──
FORMS = [
    # baseline
    ('B0a 4p log-quad (current prod)', f_baseline_logquad, 4,
     [1, 0.04, -0.5, 0.5],
     ([1e-5, -0.5, -10, -10], [100, 0.5, 10, 10])),
    ('B0b 4p pure power-law', f_baseline_pwlaw, 4,
     [1, 0.6, -0.5, 0.5],
     ([1e-5, 0, -10, -10], [100, 2, 10, 10])),
    # new forms
    ('B1a Churchill-Usagi 7p (free p)', f_B1_churchill, 7,
     [0.1, 0.5, 0.05, 0.8, -0.5, 0.5, 4.0],
     ([1e-5, 0, 1e-5, 0, -10, -10, 1.0],
      [100, 1.5, 100, 2, 10, 10, 20])),
    ('B1b Churchill-Usagi 6p (p=4 fixed)', f_B1_churchill_p4, 6,
     [0.1, 0.5, 0.05, 0.8, -0.5, 0.5],
     ([1e-5, 0, 1e-5, 0, -10, -10],
      [100, 1.5, 100, 2, 10, 10])),
    ('B2 Additive (c1·Re^a1 + c2·Re^a2)', f_B2_additive, 6,
     [0.5, 0.5, 0.05, 0.9, -0.5, 0.5],
     ([1e-5, 0, 1e-5, 0, -10, -10],
      [100, 1.5, 100, 2, 10, 10])),
    ('B5 Colburn j-factor 4p', f_B5_colburn, 4,
     [0.1, -0.3, -0.5, 0.5],
     ([1e-5, -2, -10, -10], [100, 1, 10, 10])),
    ('C2 τ-explicit 5p (no log-quad)', f_C2_tortuosity, 5,
     [1, 0.6, -0.5, 0.5, 1.0],
     ([1e-5, 0, -10, -10, -10], [100, 2, 10, 10, 10])),
    ('C2b τ + log-quad 5p combo', f_C2_tau_logquad, 5,
     [1, 0.04, -0.5, 0.5, 1.0],
     ([1e-5, -0.5, -10, -10, -10], [100, 0.5, 10, 10, 10])),
]


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    print("Phase 2 — Form sweep (B1/B2/B5/C2)")
    print("=" * 100)

    results = {}
    for tpms in ('Diamond', 'Gyroid'):
        d = load_data(tpms)
        d = add_tau(d, tpms)
        print(f"\n--- {tpms} (n={len(d)}, tau range [{d['tau'].min():.3f}, {d['tau'].max():.3f}]) ---")
        print(f"  {'Form':<40}  {'#par':>4}  {'IS%':>6}  {'IS_b':>6}  {'LOO%':>6}  {'LOO_b':>6}")
        print(f"  {'-'*40}  {'-'*4}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*6}")
        for name, fn, npar, p0, bounds in FORMS:
            popt, is_r, is_b = fit_full(d, fn, p0, bounds)
            loo_r, loo_b = loo_form(d, fn, p0, bounds)
            print(f"  {name:<40}  {npar:>4}  {is_r:>5.2f}  {is_b:>+5.2f}  "
                  f"{loo_r:>5.2f}  {loo_b:>+5.2f}")
            results[(tpms, name)] = (popt, loo_r, loo_b, is_r, is_b)

    # ── Phase 3: Shanghai validation for top forms ──
    print()
    print("=" * 100)
    print("Phase 3 — Shanghai 16-case Q validation (per form, Gyroid coeffs)")
    print("=" * 100)

    L_CELL = 7.0
    T_WALL = 0.6
    g = tpms_geometry('Gyroid', L_CELL, T_WALL, 16.0)
    EPS_F = float(g['epsilon']) / 2.0
    EPS_FULL = float(g['epsilon'])
    D_H = float(g['D_h'])
    L_MM_SH = L_CELL
    D_H_MM_SH = D_H * 1000.0
    T_MM_SH = T_WALL
    TAU_SH = tortuosity('Gyroid', EPS_FULL)
    A_FLOW = 36 * 18.0565e-6
    A_tot = float(g['A_0']) * 0.182 * 0.042 * 0.042

    XLSX = (_PROJECT_ROOT.parent / 'data' / 'raw_data'
            / '20260401-上海电气天然气加热器实验工况.xlsx')
    df_in = pd.read_excel(XLSX, sheet_name='Sheet1', engine='openpyxl',
                          header=None, skiprows=2)

    def shanghai_Q(coeffs, fn):
        errs = []
        for ci in range(16):
            m = float(df_in.iloc[ci, 5])
            T_in = float(df_in.iloc[ci, 28]) + 273.15
            T_out = float(df_in.iloc[ci, 29]) + 273.15
            P_in = P_atm + float(df_in.iloc[ci, 30])
            T_Bin = float(df_in.iloc[ci, 24]) + 273.15
            Q_exp = float(df_in.iloc[ci, 33])
            rho = air_density(T_in, P_in)
            mu = air_viscosity(T_in)
            u = m / (rho * A_FLOW)
            Re = rho * u * D_H / mu
            cp = air_cp(0.5*(T_in+T_out))
            k = air_conductivity(0.5*(T_in+T_out))
            X = (np.array([Re]), np.array([EPS_F]),
                 np.array([L_MM_SH]), np.array([D_H_MM_SH]),
                 np.array([T_MM_SH]), np.array([TAU_SH]))
            Nu = float(fn(X, *coeffs)[0])
            h = Nu * k / D_H
            NTU = h * A_tot / (m * cp)
            eps = 1 - np.exp(-NTU)
            Q_pred = eps * m * cp * (T_in - T_Bin)
            err = (Q_pred - Q_exp)/Q_exp*100
            errs.append(err)
        e = np.array(errs)
        return float(np.sqrt(np.mean(e**2))), float(np.mean(e)), float(np.max(np.abs(e)))

    print(f"  {'Form':<40}  {'G LOO%':>7}  {'Q RMSRE%':>9}  {'Q bias%':>8}  {'Q max%':>7}")
    print(f"  {'-'*40}  {'-'*7}  {'-'*9}  {'-'*8}  {'-'*7}")
    for name, fn, npar, p0, bounds in FORMS:
        popt_G, loo_G, _, _, _ = results[('Gyroid', name)]
        if popt_G is None:
            print(f"  {name:<40}  FAIL")
            continue
        try:
            qrm, qbias, qmax = shanghai_Q(popt_G, fn)
            print(f"  {name:<40}  {loo_G:>6.2f}%  {qrm:>8.2f}%  {qbias:>+7.2f}%  {qmax:>6.2f}%")
        except Exception as ex:
            print(f"  {name:<40}  Shanghai FAIL: {type(ex).__name__}")


if __name__ == '__main__':
    main()
