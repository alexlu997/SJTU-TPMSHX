"""fit_nu_cfd4.py — refit Nu correlations on CFD4 data (authoritative).

CFD4 conventions (verified by audit_cfd4.py):
  col 0 Re   = ρ · u_CFD4 · D / μ          (D_h-based, NOT r_h-based)
  col 10 u   = ṁ/(ρ · ε_full · A_face)      (combined-stream "full porosity"
                                              ≡ u_single_interstitial / 2)
  col 37 Nu  = h · D_h / k_f                (standard, smooth wall)

Single-stream solver convention requires u_single. So:
  u_single = 2 · u_CFD4
  Re_fit   = ρ · u_single · D_h_geom / μ = 2 · col_0_Re_CFD4

Forms preserved from current production (CFD3-fit):
  Diamond F4-D: Nu = c · Pr^(1/3) · Re^n · ε_f^a · (D_h/Sa)^b,
                n = n0 + n1·ln(ε_f)
  Gyroid  F7:   Nu = c · exp(a2·(ln Re)²) · Re^a · ε_f^b · Pr^(1/3) · (L/Sa)^d

Outputs:
  - In-sample fit + LOO RMSRE / bias for both TPMS
  - New coefficients (drop-in replacement for tpms_calc.py if accepted)
  - Comparison vs current production (CFD3-fit)

Usage:
  python -u -m sjtu_tpmshx.df_fit.fit_nu_cfd4
"""
from __future__ import annotations
import sys
import re
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import geometry as tpms_geometry, Pr, Sa_mm

XLSX = Path(r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data\副本试验记录表_CFD4.xlsx')
SHEET_RE = re.compile(r'^(Diamond|Gyroid)(\d+)_(\d+)$')
K_S = 16.0


def load_data(tpms: str) -> pd.DataFrame:
    """Load CFD4 data, applying single-stream convention conversion.

    CFD4 col 10 u is combined-stream (u_single/2). We double it to recover
    single-stream interstitial velocity, matching solver convention.
    """
    sheets = pd.ExcelFile(XLSX).sheet_names
    target_sheets = []
    for s in sheets:
        m = SHEET_RE.match(s)
        if m and m.group(1) == tpms:
            target_sheets.append((s, float(m.group(2)), float(m.group(3))/10.0))

    rows = []
    for sheet, L, t in target_sheets:
        df = pd.read_excel(XLSX, sheet_name=sheet, engine='openpyxl',
                           header=None, skiprows=1)
        for idx in range(len(df)):
            try:
                Re_excel = float(df.iloc[idx, 0])
                D_xls = float(df.iloc[idx, 1])
                mu = float(df.iloc[idx, 6])
                rho = float(df.iloc[idx, 9])
                u_cfd4 = float(df.iloc[idx, 10])      # combined-stream
                Nu = float(df.iloc[idx, 37])
                if any(np.isnan(x) for x in (Re_excel, mu, rho, u_cfd4, Nu)):
                    continue
                geom = tpms_geometry(tpms, L, t, K_S)
                eps_full = float(geom['epsilon'])
                eps_f = eps_full / 2.0
                D_h_m = float(geom['D_h'])
                D_h_mm = D_h_m * 1000.0
                # CFD4 u → single-stream interstitial (× 2)
                u_single = 2.0 * u_cfd4
                Re_fit = rho * u_single * D_h_m / mu
                rows.append(dict(L=L, t=t, eps_full=eps_full, eps_f=eps_f,
                                 D_h_m=D_h_m, D_h_mm=D_h_mm, L_mm=L,
                                 u_single=u_single, u_cfd4=u_cfd4,
                                 Re_fit=Re_fit, Re_excel=Re_excel,
                                 Nu=Nu, sheet=sheet))
            except Exception:
                continue
    return pd.DataFrame(rows)


# Diamond F4-D
def diamond_F4D(X, c, n0, n1, a, b):
    Re, eps_f, D_h_mm = X
    n = n0 + n1 * np.log(eps_f)
    ratio = D_h_mm / (1000.0 * Sa_mm)
    return c * Pr ** (1/3) * Re ** n * eps_f ** a * ratio ** b


# Gyroid F7
def gyroid_F7(X, c, a, a2, b, d):
    Re, eps_f, L_mm = X
    logRe = np.log(np.maximum(Re, 1.0))
    return (c * np.exp(a2 * logRe**2) * Re**a * eps_f**b
            * Pr**(1/3) * (L_mm/(1000*Sa_mm))**d)


def fit_diamond(d):
    Re = d['Re_fit'].to_numpy()
    eps_f = d['eps_f'].to_numpy()
    D_h_mm = d['D_h_mm'].to_numpy()
    Nu = d['Nu'].to_numpy()
    X = (Re, eps_f, D_h_mm)
    p0 = [0.96, 0.0635, -0.800, 7.41, -1.92]
    bounds = ([1e-4, 0, -5, 0, -5], [10, 5, 5, 20, 5])
    try:
        popt, _ = curve_fit(diamond_F4D, X, Nu, p0=p0, bounds=bounds, maxfev=20000)
        Nu_pred = diamond_F4D(X, *popt)
        err = (Nu_pred - Nu) / Nu
        return dict(c=popt[0], n0=popt[1], n1=popt[2], a=popt[3], b=popt[4],
                    rmsre=float(np.sqrt(np.mean(err**2))*100),
                    bias=float(np.mean(err)*100), n=len(d))
    except Exception as e:
        print(f"  Diamond fit FAIL: {e}")
        return None


def fit_gyroid(d):
    Re = d['Re_fit'].to_numpy()
    eps_f = d['eps_f'].to_numpy()
    L_mm = d['L_mm'].to_numpy()
    Nu = d['Nu'].to_numpy()
    X = (Re, eps_f, L_mm)
    p0 = [0.5, 0.5, 0.0, 0.5, -1.0]
    bounds = ([1e-5, 0, -1, -10, -5], [50, 2, 1, 10, 5])
    try:
        popt, _ = curve_fit(gyroid_F7, X, Nu, p0=p0, bounds=bounds, maxfev=50000)
        Nu_pred = gyroid_F7(X, *popt)
        err = (Nu_pred - Nu) / Nu
        return dict(c=popt[0], a=popt[1], a2=popt[2], b=popt[3], d=popt[4],
                    rmsre=float(np.sqrt(np.mean(err**2))*100),
                    bias=float(np.mean(err)*100), n=len(d))
    except Exception as e:
        print(f"  Gyroid fit FAIL: {e}")
        return None


def loo_diamond(d):
    geoms = sorted(set(zip(d['L'], d['t'])))
    err_all = []
    for L_t, t_t in geoms:
        sel = (d['L'] == L_t) & (d['t'] == t_t)
        d_train = d[~sel]
        d_test = d[sel]
        if len(d_train) < 10 or len(d_test) == 0:
            continue
        f = fit_diamond(d_train)
        if f is None:
            continue
        X = (d_test['Re_fit'].to_numpy(), d_test['eps_f'].to_numpy(),
             d_test['D_h_mm'].to_numpy())
        Nu_p = diamond_F4D(X, f['c'], f['n0'], f['n1'], f['a'], f['b'])
        err = (Nu_p - d_test['Nu'].to_numpy()) / d_test['Nu'].to_numpy()
        err_all.extend(err.tolist())
    e = np.array(err_all)
    return dict(rmsre=float(np.sqrt(np.mean(e**2))*100),
                bias=float(np.mean(e)*100), n_geoms=len(geoms))


def loo_gyroid(d):
    geoms = sorted(set(zip(d['L'], d['t'])))
    err_all = []
    for L_t, t_t in geoms:
        sel = (d['L'] == L_t) & (d['t'] == t_t)
        d_train = d[~sel]
        d_test = d[sel]
        if len(d_train) < 10 or len(d_test) == 0:
            continue
        f = fit_gyroid(d_train)
        if f is None:
            continue
        X = (d_test['Re_fit'].to_numpy(), d_test['eps_f'].to_numpy(),
             d_test['L_mm'].to_numpy())
        Nu_p = gyroid_F7(X, f['c'], f['a'], f['a2'], f['b'], f['d'])
        err = (Nu_p - d_test['Nu'].to_numpy()) / d_test['Nu'].to_numpy()
        err_all.extend(err.tolist())
    e = np.array(err_all)
    return dict(rmsre=float(np.sqrt(np.mean(e**2))*100),
                bias=float(np.mean(e)*100), n_geoms=len(geoms))


def predict_with_current_production(d, tpms):
    """Apply CURRENT production coefficients (CFD3-fit) to CFD4 data."""
    from solvers.tpms_calc import _nu_diamond, _nu_gyroid
    Re = d['Re_fit'].to_numpy()
    eps_f = d['eps_f'].to_numpy()
    if tpms == 'Diamond':
        D_h_mm = d['D_h_mm'].to_numpy()
        Nu_pred = np.array([_nu_diamond(r, e, D) for r, e, D in zip(Re, eps_f, D_h_mm)])
    else:
        L_mm = d['L_mm'].to_numpy()
        Nu_pred = np.array([_nu_gyroid(r, e, L) for r, e, L in zip(Re, eps_f, L_mm)])
    err = (Nu_pred - d['Nu'].to_numpy()) / d['Nu'].to_numpy()
    return dict(rmsre=float(np.sqrt(np.mean(err**2))*100),
                bias=float(np.mean(err)*100))


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("CFD4 Nu refit (single-stream convention)")
    print("=" * 72)
    print(f"  Source: {XLSX.name}")
    print(f"  u_single = 2 · u_CFD4 (CFD4 reports combined-stream u)")
    print()

    # ---- Diamond ----
    print("--- Diamond ---")
    dD = load_data('Diamond')
    print(f"  data: {len(dD)} rows, {len(set(zip(dD['L'], dD['t'])))} geometries")
    print(f"  Re_fit range: [{dD['Re_fit'].min():.0f}, {dD['Re_fit'].max():.0f}]")
    print(f"  eps_f range:  [{dD['eps_f'].min():.3f}, {dD['eps_f'].max():.3f}]")

    cur_d = predict_with_current_production(dD, 'Diamond')
    print(f"\n  Current production (CFD3-fit) on CFD4 data:")
    print(f"    RMSRE = {cur_d['rmsre']:.2f}%   bias = {cur_d['bias']:+.2f}%")

    fit_d = fit_diamond(dD)
    loo_d = loo_diamond(dD)
    if fit_d:
        print(f"\n  CFD4 refit (F4-D):")
        print(f"    In-sample RMSRE = {fit_d['rmsre']:.2f}%  bias = {fit_d['bias']:+.2f}%")
        print(f"    LOO RMSRE       = {loo_d['rmsre']:.2f}%  bias = {loo_d['bias']:+.2f}%")
        print(f"  Coefficients (Diamond F4-D, CFD4):")
        print(f"    c  = {fit_d['c']:.6f}")
        print(f"    n  = {fit_d['n0']:.6f} + ({fit_d['n1']:.6f}) · ln(ε_f)")
        print(f"    a  = {fit_d['a']:.6f}  (ε_f exponent)")
        print(f"    b  = {fit_d['b']:.6f}  (D_h/Sa exponent)")

    # ---- Gyroid ----
    print("\n--- Gyroid ---")
    dG = load_data('Gyroid')
    print(f"  data: {len(dG)} rows, {len(set(zip(dG['L'], dG['t'])))} geometries")
    print(f"  Re_fit range: [{dG['Re_fit'].min():.0f}, {dG['Re_fit'].max():.0f}]")
    print(f"  eps_f range:  [{dG['eps_f'].min():.3f}, {dG['eps_f'].max():.3f}]")

    cur_g = predict_with_current_production(dG, 'Gyroid')
    print(f"\n  Current production (CFD3-fit) on CFD4 data:")
    print(f"    RMSRE = {cur_g['rmsre']:.2f}%   bias = {cur_g['bias']:+.2f}%")

    fit_g = fit_gyroid(dG)
    loo_g = loo_gyroid(dG)
    if fit_g:
        print(f"\n  CFD4 refit (F7):")
        print(f"    In-sample RMSRE = {fit_g['rmsre']:.2f}%  bias = {fit_g['bias']:+.2f}%")
        print(f"    LOO RMSRE       = {loo_g['rmsre']:.2f}%  bias = {loo_g['bias']:+.2f}%")
        print(f"  Coefficients (Gyroid F7, CFD4):")
        print(f"    c  = {fit_g['c']:.6f}")
        print(f"    a  = {fit_g['a']:.6f}")
        print(f"    a2 = {fit_g['a2']:.6f}")
        print(f"    b  = {fit_g['b']:.6f}  (ε_f exponent)")
        print(f"    d  = {fit_g['d']:.6f}  (L/Sa exponent)")

    # Comparison summary
    print("\n" + "=" * 72)
    print("Summary (LOO RMSRE, smooth-wall, NO ×1.28):")
    print(f"  {'TPMS':<8}  {'Production (CFD3 fit applied to CFD4)':<40}  {'CFD4 refit':<12}")
    print(f"  {'-'*8}  {'-'*40}  {'-'*12}")
    print(f"  Diamond   {cur_d['rmsre']:>5.2f}%  (bias {cur_d['bias']:+5.2f}%){' '*15}  "
          f"{loo_d['rmsre']:>5.2f}% (bias {loo_d['bias']:+5.2f}%)")
    print(f"  Gyroid    {cur_g['rmsre']:>5.2f}%  (bias {cur_g['bias']:+5.2f}%){' '*15}  "
          f"{loo_g['rmsre']:>5.2f}% (bias {loo_g['bias']:+5.2f}%)")


if __name__ == '__main__':
    main()
