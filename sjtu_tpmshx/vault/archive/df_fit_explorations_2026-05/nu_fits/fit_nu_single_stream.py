"""fit_nu_single_stream.py — refit Nu correlations with single-stream convention.

Convention (post-refit, audit-verified 2026-04-26):
  ε:    single-stream porosity ε_f = ε_full / 2
  Re:   D_h-based, Re = ρ·u·D_h/μ  (u single-stream from Excel col 13)
        Note: Excel col 3 Re uses r_h convention; refit uses Re_fit = 2·Re_excel
  Nu:   standard h·D_h/k_f (unchanged)
  Sa:   31 μm (constant)

Form preserved (power-law):
  Diamond: Nu = c_D · Pr^(1/3) · Re^n · ε_f^a · (D_h_mm/(1000·Sa_mm))^b
           n = n0 + n1·ln(ε_f)
  Gyroid:  Nu = c_G · Pr^(1/3) · Re^n · ε_f^a · (L_mm/(1000·Sa_mm))^b
           n = c1·Re^c2·ε_f^c3

Output: new coefficients per TPMS type.

Usage:
  python -m sjtu_tpmshx.df_fit.fit_nu_single_stream
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit, least_squares

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import geometry as tpms_geometry, Pr, Sa_mm

XLSX = _PROJECT / 'data' / 'raw_data' / '试验记录表_整理版_v3.xlsx'
# v3 structure (2026-04-27): same legacy `Diamond_汇总` / `Gyroid_汇总`
# single-sheet layout, sourced from `副本试验记录表_CFD4.xlsx` (authoritative
# CFD4 dataset), merged via `merge_cfd4_to_legacy.py`.
#   - col 13 u  = 2 · u_CFD4 (single-stream interstitial)
#   - col 3  Re = 2 · CFD4_col_0 (D_h-based single-stream Re)
#   - col 40 Nu = CFD4 Nu (h·D_h/k_f, smooth wall)
# Fit script reads col 13 u + col 12 ρ + col 9 μ and recomputes
# Re_fit = ρ·u·D_h_geom/μ (D_h-based single-stream), matching solver convention.
K_S = 16.0


def load_data(tpms: str) -> pd.DataFrame:
    """Load + compute single-stream features.

    Reads single-sheet `{tpms}_汇总` (49-col legacy layout):
      col 1 = L/mm, col 2 = t/mm, col 3 = Re (Excel design Re, used directly),
      col 9 = mu, col 12 = rho, col 13 = u, col 40 = Nu.

    Re_fit = col 3 verbatim (Excel design Re, single-stream D_h-based for v3).
    NOT recomputed via ρ·u·D_h/μ (avoids 5-15% drift from operating-state ρ).
    """
    df = pd.read_excel(XLSX, sheet_name=f'{tpms}_汇总',
                       engine='openpyxl', header=None, skiprows=2)
    L_col = pd.to_numeric(df.iloc[:, 1], errors='coerce')
    mask = L_col.notna()
    df = df[mask].reset_index(drop=True)
    rows = []
    for idx in range(len(df)):
        try:
            L = float(df.iloc[idx, 1])
            t = float(df.iloc[idx, 2])
            Re_excel = float(df.iloc[idx, 3])
            mu = float(df.iloc[idx, 9])
            rho = float(df.iloc[idx, 12])
            u = float(df.iloc[idx, 13])
            Nu = float(df.iloc[idx, 40])
            if np.isnan(Re_excel) or np.isnan(Nu) or np.isnan(u):
                continue
            geom = tpms_geometry(tpms, L, t, K_S)
            eps_full = float(geom['epsilon'])
            eps_f = eps_full / 2.0
            D_h_m = float(geom['D_h'])
            D_h_mm = D_h_m * 1000.0
            Re_fit = Re_excel   # use Excel col 3 verbatim (design Re)
            rows.append(dict(L=L, t=t, eps_full=eps_full, eps_f=eps_f,
                             D_h_m=D_h_m, D_h_mm=D_h_mm, L_mm=L,
                             u=u, Re_fit=Re_fit, Re_excel=Re_excel,
                             Nu=Nu))
        except Exception:
            pass
    return pd.DataFrame(rows)


# ============================================================
# Diamond form: Nu = c · Pr^(1/3) · Re^n · ε_f^a · (D_h_mm/(1000·Sa_mm))^b
#               n = n0 + n1·ln(ε_f)
# ============================================================
def diamond_model(X, c, n0, n1, a, b):
    """X: (Re, eps_f, D_h_mm) tuple of arrays."""
    Re, eps_f, D_h_mm = X
    n = n0 + n1 * np.log(eps_f)
    ratio = D_h_mm / (1000.0 * Sa_mm)
    return c * Pr ** (1/3) * Re ** n * eps_f ** a * ratio ** b


def gyroid_model(X, c, c1, c2, c3, a, b):
    """X: (Re, eps_f, L_mm)."""
    Re, eps_f, L_mm = X
    n = c1 * Re ** c2 * eps_f ** c3
    ratio = L_mm / (1000.0 * Sa_mm)
    return c * Pr ** (1/3) * Re ** n * eps_f ** a * ratio ** b


def fit_diamond(d: pd.DataFrame):
    Re = d['Re_fit'].to_numpy()
    eps_f = d['eps_f'].to_numpy()
    D_h_mm = d['D_h_mm'].to_numpy()
    Nu = d['Nu'].to_numpy()
    X = (Re, eps_f, D_h_mm)
    # Initial guesses: rescale old (full ε) to half ε
    # Old: Nu = 0.008 · Pr^(1/3) · Re^n · ε^7.41 · (D_h/Sa)^(-1.92)
    #      n = 0.618 - 0.800 · ln(ε)
    # If ε_old = 2·ε_f: ε_old^7.41 = 2^7.41 · ε_f^7.41 = 169.7 · ε_f^7.41
    # → c_new ≈ 0.008 × 169.7 = 1.36, a = 7.41
    # ln(ε_old) = ln(2) + ln(ε_f) → n0_new = 0.618 - 0.8·ln(2) = 0.0635, n1_new = -0.8
    # But Re convention also doubled (r_h → D_h): Re_new = 2·Re_old
    # → Re_new^n = (2·Re_old)^n = 2^n · Re_old^n. n ~0.5 so factor 2^0.5 = 1.41
    # → c_new further scaled by 1/1.41 ≈ 0.71x
    # Net c0 init ≈ 1.36 · 0.71 ≈ 0.96
    p0 = [0.96, 0.0635, -0.800, 7.41, -1.92]
    bounds = ([1e-4, 0, -5, 0, -5], [10, 5, 5, 20, 5])
    try:
        popt, pcov = curve_fit(diamond_model, X, Nu, p0=p0, bounds=bounds,
                                maxfev=20000)
        Nu_pred = diamond_model(X, *popt)
        err = (Nu_pred - Nu) / Nu
        rmsre = float(np.sqrt(np.mean(err ** 2)) * 100)
        bias = float(np.mean(err) * 100)
        return dict(c=popt[0], n0=popt[1], n1=popt[2], a=popt[3], b=popt[4],
                    rmsre=rmsre, bias=bias, n_data=len(d))
    except Exception as e:
        print(f"  Diamond fit FAILED: {type(e).__name__}: {e}")
        return None


def fit_gyroid(d: pd.DataFrame):
    Re = d['Re_fit'].to_numpy()
    eps_f = d['eps_f'].to_numpy()
    L_mm = d['L_mm'].to_numpy()
    Nu = d['Nu'].to_numpy()
    X = (Re, eps_f, L_mm)
    # Old: Nu = 0.17 · Pr^(1/3) · Re^n · ε^2.25 · (L/Sa)^(-2.01)
    #      n = 0.177 · Re^0.1 · ε^(-2/3)
    # ε_old^2.25 = 2^2.25 · ε_f^2.25 = 4.76 · ε_f^2.25 → c × 4.76
    # ε_old^(-2/3) = 2^(-2/3) · ε_f^(-2/3) = 0.63 · ε_f^(-2/3) → c1 × 0.63
    # Re_new = 2·Re_old → Re_new^c2 = 2^c2 · Re_old^c2 (c2=0.1, factor 2^0.1≈1.07)
    # Re-shift via c1; Re_new^n = 2^n · Re_old^n (n~0.5, factor 1.41)
    # Net c init ≈ 0.17 · 4.76 / 1.41 ≈ 0.57
    # n init: c1·0.63·... — keep initial close to 0.17·0.63 = 0.111
    p0 = [0.57, 0.111, 0.1, -0.667, 2.25, -2.01]
    bounds = ([1e-4, 1e-4, 0, -5, 0, -5], [10, 5, 1, 5, 10, 5])
    try:
        popt, pcov = curve_fit(gyroid_model, X, Nu, p0=p0, bounds=bounds,
                                maxfev=30000)
        Nu_pred = gyroid_model(X, *popt)
        err = (Nu_pred - Nu) / Nu
        rmsre = float(np.sqrt(np.mean(err ** 2)) * 100)
        bias = float(np.mean(err) * 100)
        return dict(c=popt[0], c1=popt[1], c2=popt[2], c3=popt[3],
                    a=popt[4], b=popt[5],
                    rmsre=rmsre, bias=bias, n_data=len(d))
    except Exception as e:
        print(f"  Gyroid fit FAILED: {type(e).__name__}: {e}")
        return None


def loo_diamond(d: pd.DataFrame):
    """Leave-one-geometry-out cross-validation."""
    geoms = sorted(set(zip(d['L'], d['t'])))
    err_all = []
    for L_test, t_test in geoms:
        sel_test = (d['L'] == L_test) & (d['t'] == t_test)
        d_train = d[~sel_test]
        d_test = d[sel_test]
        if len(d_train) < 10 or len(d_test) == 0:
            continue
        fit = fit_diamond(d_train)
        if fit is None:
            continue
        X_test = (d_test['Re_fit'].to_numpy(), d_test['eps_f'].to_numpy(),
                   d_test['D_h_mm'].to_numpy())
        Nu_pred = diamond_model(X_test, fit['c'], fit['n0'], fit['n1'],
                                  fit['a'], fit['b'])
        Nu_true = d_test['Nu'].to_numpy()
        err = (Nu_pred - Nu_true) / Nu_true
        err_all.extend(err.tolist())
    err_all = np.array(err_all)
    return dict(rmsre=float(np.sqrt(np.mean(err_all ** 2)) * 100),
                bias=float(np.mean(err_all) * 100),
                n_geoms=len(geoms))


def loo_gyroid(d: pd.DataFrame):
    geoms = sorted(set(zip(d['L'], d['t'])))
    err_all = []
    for L_test, t_test in geoms:
        sel_test = (d['L'] == L_test) & (d['t'] == t_test)
        d_train = d[~sel_test]
        d_test = d[sel_test]
        if len(d_train) < 10 or len(d_test) == 0:
            continue
        fit = fit_gyroid(d_train)
        if fit is None:
            continue
        X_test = (d_test['Re_fit'].to_numpy(), d_test['eps_f'].to_numpy(),
                   d_test['L_mm'].to_numpy())
        Nu_pred = gyroid_model(X_test, fit['c'], fit['c1'], fit['c2'],
                                fit['c3'], fit['a'], fit['b'])
        Nu_true = d_test['Nu'].to_numpy()
        err = (Nu_pred - Nu_true) / Nu_true
        err_all.extend(err.tolist())
    err_all = np.array(err_all)
    return dict(rmsre=float(np.sqrt(np.mean(err_all ** 2)) * 100),
                bias=float(np.mean(err_all) * 100),
                n_geoms=len(geoms))


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("Single-stream Nu refit\n" + "=" * 60)
    print(f"  Convention: ε_f = ε_full/2,  Re = ρ·u·D_h/μ (= 2·Re_excel)")
    print(f"  Pr={Pr}, Sa={Sa_mm}mm")
    print()

    print("--- Diamond ---")
    d_diamond = load_data('Diamond')
    print(f"  data: {len(d_diamond)} rows, {len(set(zip(d_diamond['L'], d_diamond['t'])))} geometries")
    fit_d = fit_diamond(d_diamond)
    if fit_d:
        print(f"  In-sample fit:  RMSRE={fit_d['rmsre']:.2f}%  bias={fit_d['bias']:+.2f}%")
        print(f"  Coefficients:")
        print(f"    c  = {fit_d['c']:.6f}")
        print(f"    n0 = {fit_d['n0']:.6f}")
        print(f"    n1 = {fit_d['n1']:.6f}")
        print(f"    a  = {fit_d['a']:.6f}  (ε_f exponent)")
        print(f"    b  = {fit_d['b']:.6f}  (D_h/Sa exponent)")
        print(f"  Form: Nu = {fit_d['c']:.4f} · Pr^(1/3) · Re^n · ε_f^{fit_d['a']:.3f} "
              f"· (D_h_mm/(1000·Sa))^{fit_d['b']:.3f}")
        print(f"        n = {fit_d['n0']:.4f} + {fit_d['n1']:.4f}·ln(ε_f)")
    loo_d = loo_diamond(d_diamond)
    print(f"  LOO: RMSRE={loo_d['rmsre']:.2f}%  bias={loo_d['bias']:+.2f}%  n_geoms={loo_d['n_geoms']}")

    print("\n--- Gyroid ---")
    d_gyroid = load_data('Gyroid')
    print(f"  data: {len(d_gyroid)} rows, {len(set(zip(d_gyroid['L'], d_gyroid['t'])))} geometries")
    fit_g = fit_gyroid(d_gyroid)
    if fit_g:
        print(f"  In-sample fit:  RMSRE={fit_g['rmsre']:.2f}%  bias={fit_g['bias']:+.2f}%")
        print(f"  Coefficients:")
        print(f"    c  = {fit_g['c']:.6f}")
        print(f"    c1 = {fit_g['c1']:.6f}")
        print(f"    c2 = {fit_g['c2']:.6f}")
        print(f"    c3 = {fit_g['c3']:.6f}")
        print(f"    a  = {fit_g['a']:.6f}  (ε_f exponent)")
        print(f"    b  = {fit_g['b']:.6f}  (L/Sa exponent)")
        print(f"  Form: Nu = {fit_g['c']:.4f} · Pr^(1/3) · Re^n · ε_f^{fit_g['a']:.3f} "
              f"· (L_mm/(1000·Sa))^{fit_g['b']:.3f}")
        print(f"        n = {fit_g['c1']:.4f} · Re^{fit_g['c2']:.4f} · ε_f^{fit_g['c3']:.4f}")
    loo_g = loo_gyroid(d_gyroid)
    print(f"  LOO: RMSRE={loo_g['rmsre']:.2f}%  bias={loo_g['bias']:+.2f}%  n_geoms={loo_g['n_geoms']}")

    print("\n" + "=" * 60)
    print("Old correlations (for comparison, full ε):")
    print("  Diamond: Nu = 0.008 · Pr^(1/3) · Re^n · ε^7.41 · (D_h/Sa)^(-1.92)")
    print("           n = 0.618 - 0.800 · ln(ε)")
    print("  Gyroid:  Nu = 0.17 · Pr^(1/3) · Re^n · ε^2.25 · (L/Sa)^(-2.01)")
    print("           n = 0.177 · Re^0.1 · ε^(-2/3)")
    print("  Both expected full ε; new fits use ε_f = ε/2.")


if __name__ == '__main__':
    main()
