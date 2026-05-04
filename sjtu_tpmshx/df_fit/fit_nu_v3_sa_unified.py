"""fit_nu_v3_sa_unified.py — dimensionally-consistent Sa-explicit forms on v3.

Each form contains length scales only as ratios to Sa (= 31 μm). All terms
dimensionless. Tested forms (10 candidates), unified form across both TPMS.

Forms:
  S1: Nu = c·Pr^(1/3)·Re^a·ε_f^b·(D_h/Sa)^d                              (4p)
  S2: Nu = c·Pr^(1/3)·Re^a·ε_f^b·(L/Sa)^d                                (4p)
  S3: Nu = c·Pr^(1/3)·Re^a·ε_f^b·(D_h/Sa)^d1·(L/Sa)^d2                   (5p)
  S4: Nu = c·Pr^(1/3)·Re^a·ε_f^b·(D_h/Sa)^d1·(t/Sa)^d2                   (5p)
  S5: Nu = c·Pr^(1/3)·Re^a·ε_f^b·(L/Sa)^d1·(t/Sa)^d2                     (5p)
  S6: Nu = c·Pr^(1/3)·Re^a·ε_f^b·(D_h/Sa)^d1·(L/Sa)^d2·(t/Sa)^d3         (6p)
  S7: var-n + 3 Sa ratios:
      Nu = c·Pr^(1/3)·Re^[n0+n1·ln(ε_f)]·ε_f^b·(D_h/Sa)^d1·(L/Sa)^d2·(t/Sa)^d3  (8p)
  S8: log-quad Re + 3 Sa ratios:
      Nu = c·Pr^(1/3)·Re^a·exp(a2·(ln Re)^2)·ε_f^b·(D_h/Sa)^d1·(L/Sa)^d2·(t/Sa)^d3  (8p)
  S9: Re·Pr coupling + 3 Sa ratios (4p):
      Nu = c·(Re·Pr)^a·ε_f^b·(D_h·L·t/Sa^3)^d                             (4p)
  S10: like S6 but Re·Pr coupled:
      Nu = c·(Re·Pr)^a·ε_f^b·(D_h/Sa)^d1·(L/Sa)^d2·(t/Sa)^d3              (6p)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
from scipy.optimize import curve_fit

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import Pr, Sa_mm
from df_fit.fit_nu_single_stream import load_data


# ── Forms (X = Re, eps_f, L_mm, D_h_mm, t_mm) ──
def S1(X, c, a, b, d):
    Re, e, L, D, t = X
    return c * Pr**(1/3) * Re**a * e**b * (D/(1000*Sa_mm))**d

def S2(X, c, a, b, d):
    Re, e, L, D, t = X
    return c * Pr**(1/3) * Re**a * e**b * (L/(1000*Sa_mm))**d

def S3(X, c, a, b, d1, d2):
    Re, e, L, D, t = X
    return c * Pr**(1/3) * Re**a * e**b * (D/(1000*Sa_mm))**d1 * (L/(1000*Sa_mm))**d2

def S4(X, c, a, b, d1, d2):
    Re, e, L, D, t = X
    return c * Pr**(1/3) * Re**a * e**b * (D/(1000*Sa_mm))**d1 * (t/(1000*Sa_mm))**d2

def S5(X, c, a, b, d1, d2):
    Re, e, L, D, t = X
    return c * Pr**(1/3) * Re**a * e**b * (L/(1000*Sa_mm))**d1 * (t/(1000*Sa_mm))**d2

def S6(X, c, a, b, d1, d2, d3):
    Re, e, L, D, t = X
    return (c * Pr**(1/3) * Re**a * e**b
            * (D/(1000*Sa_mm))**d1 * (L/(1000*Sa_mm))**d2 * (t/(1000*Sa_mm))**d3)

def S7(X, c, n0, n1, b, d1, d2, d3):
    Re, e, L, D, t = X
    n = n0 + n1*np.log(e)
    return (c * Pr**(1/3) * Re**n * e**b
            * (D/(1000*Sa_mm))**d1 * (L/(1000*Sa_mm))**d2 * (t/(1000*Sa_mm))**d3)

def S8(X, c, a, a2, b, d1, d2, d3):
    Re, e, L, D, t = X
    logRe = np.log(np.maximum(Re, 1.0))
    return (c * Pr**(1/3) * Re**a * np.exp(a2*logRe**2) * e**b
            * (D/(1000*Sa_mm))**d1 * (L/(1000*Sa_mm))**d2 * (t/(1000*Sa_mm))**d3)

def S9(X, c, a, b, d):
    Re, e, L, D, t = X
    prod = (D * L * t) / ((1000*Sa_mm)**3)
    return c * (Re*Pr)**a * e**b * prod**d

def S10(X, c, a, b, d1, d2, d3):
    Re, e, L, D, t = X
    return (c * (Re*Pr)**a * e**b
            * (D/(1000*Sa_mm))**d1 * (L/(1000*Sa_mm))**d2 * (t/(1000*Sa_mm))**d3)


def S11(X, c, n0, n1, a2, b, d1, d2, d3):
    """var-n + log-quad Re + 3 Sa ratios (8p)."""
    Re, e, L, D, t = X
    n = n0 + n1*np.log(e)
    logRe = np.log(np.maximum(Re, 1.0))
    return (c * Pr**(1/3) * Re**n * np.exp(a2*logRe**2) * e**b
            * (D/(1000*Sa_mm))**d1 * (L/(1000*Sa_mm))**d2 * (t/(1000*Sa_mm))**d3)


def S12(X, c, a, a2, b1, b2, d1, d2, d3):
    """log-quad Re + ε_f var-power (b1+b2·ln Re) + 3 Sa ratios (8p)."""
    Re, e, L, D, t = X
    logRe = np.log(np.maximum(Re, 1.0))
    b_eff = b1 + b2 * logRe
    return (c * Pr**(1/3) * Re**a * np.exp(a2*logRe**2) * e**b_eff
            * (D/(1000*Sa_mm))**d1 * (L/(1000*Sa_mm))**d2 * (t/(1000*Sa_mm))**d3)


def S13(X, c, a, a2, b, d1, d2, d3, e_tL):
    """S8 + (t/L) ratio (8p)."""
    Re, e, L, D, t = X
    logRe = np.log(np.maximum(Re, 1.0))
    return (c * Pr**(1/3) * Re**a * np.exp(a2*logRe**2) * e**b
            * (D/(1000*Sa_mm))**d1 * (L/(1000*Sa_mm))**d2
            * (t/(1000*Sa_mm))**d3 * (t/L)**e_tL)


FORMS = [
    ('S1',  S1,  4, [0.5, 0.5, 0.5, -0.5],
            ([1e-5, 0, -10, -5], [50, 2, 10, 5])),
    ('S2',  S2,  4, [0.5, 0.5, 0.5, -0.5],
            ([1e-5, 0, -10, -5], [50, 2, 10, 5])),
    ('S3',  S3,  5, [0.5, 0.5, 0.5, -0.5, -0.5],
            ([1e-5, 0, -10, -5, -5], [50, 2, 10, 5, 5])),
    ('S4',  S4,  5, [0.5, 0.5, 0.5, -0.5, 0.0],
            ([1e-5, 0, -10, -5, -5], [50, 2, 10, 5, 5])),
    ('S5',  S5,  5, [0.5, 0.5, 0.5, -0.5, 0.0],
            ([1e-5, 0, -10, -5, -5], [50, 2, 10, 5, 5])),
    ('S6',  S6,  6, [0.5, 0.5, 0.5, -0.5, -0.5, 0.0],
            ([1e-5, 0, -10, -5, -5, -5], [50, 2, 10, 5, 5, 5])),
    ('S7',  S7,  7, [0.5, 0.5, -0.5, 0.5, -0.5, -0.5, 0.0],
            ([1e-8, 0, -10, -20, -10, -10, -10], [1e4, 5, 10, 20, 10, 10, 10])),
    ('S8',  S8,  7, [0.5, 0.3, 0.0, 0.5, -0.5, -0.5, 0.0],
            ([1e-8, 0, -1, -20, -10, -10, -10], [1e4, 2, 1, 20, 10, 10, 10])),
    ('S9',  S9,  4, [0.5, 0.5, 0.5, -0.5],
            ([1e-5, 0, -10, -5], [50, 2, 10, 5])),
    ('S10', S10, 6, [0.5, 0.5, 0.5, -0.5, -0.5, 0.0],
            ([1e-5, 0, -10, -5, -5, -5], [50, 2, 10, 5, 5, 5])),
    ('S11', S11, 8, [1.0, 0.5, -0.3, 0.02, 0.5, -0.5, 0.0, 0.0],
            ([1e-8, 0, -10, -1, -20, -10, -10, -10], [1e4, 5, 10, 1, 20, 10, 10, 10])),
    ('S12', S12, 8, [1.0, 0.3, 0.02, 0.5, 0.0, -0.5, 0.0, 0.0],
            ([1e-8, 0, -1, -20, -10, -10, -10, -10], [1e4, 2, 1, 20, 10, 10, 10, 10])),
    ('S13', S13, 8, [1.0, 0.3, 0.02, 0.5, -0.5, 0.0, 0.0, 0.0],
            ([1e-8, 0, -1, -20, -10, -10, -10, -10], [1e4, 2, 1, 20, 10, 10, 10, 10])),
]


def fit_form(d, fn, p0, bounds):
    X = (d['Re_fit'].to_numpy(), d['eps_f'].to_numpy(),
         d['L_mm'].to_numpy(), d['D_h_mm'].to_numpy(), d['t'].to_numpy())
    Nu = d['Nu'].to_numpy()
    try:
        popt, _ = curve_fit(fn, X, Nu, p0=p0, bounds=bounds, maxfev=200000)
    except Exception as e:
        return None
    Nu_p = fn(X, *popt)
    err = (Nu_p - Nu) / Nu
    return popt, float(np.sqrt(np.mean(err**2))*100), float(np.mean(err)*100)


def loo_form(d, fn, p0, bounds):
    geoms = sorted(set(zip(d['L'], d['t'])))
    err_all = []
    for L_t, t_t in geoms:
        sel = (d['L'] == L_t) & (d['t'] == t_t)
        d_tr = d[~sel]
        d_te = d[sel]
        if len(d_tr) < 10 or len(d_te) == 0:
            continue
        X_tr = (d_tr['Re_fit'].to_numpy(), d_tr['eps_f'].to_numpy(),
                d_tr['L_mm'].to_numpy(), d_tr['D_h_mm'].to_numpy(),
                d_tr['t'].to_numpy())
        try:
            popt, _ = curve_fit(fn, X_tr, d_tr['Nu'].to_numpy(),
                                p0=p0, bounds=bounds, maxfev=200000)
        except Exception:
            continue
        X_te = (d_te['Re_fit'].to_numpy(), d_te['eps_f'].to_numpy(),
                d_te['L_mm'].to_numpy(), d_te['D_h_mm'].to_numpy(),
                d_te['t'].to_numpy())
        Nu_p = fn(X_te, *popt)
        Nu_t = d_te['Nu'].to_numpy()
        err = (Nu_p - Nu_t) / Nu_t
        err_all.extend(err.tolist())
    if not err_all:
        return float('nan'), float('nan')
    e = np.array(err_all)
    return float(np.sqrt(np.mean(e**2))*100), float(np.mean(e)*100)


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("Sa-explicit dimensionally-consistent form sweep on v3 (CFD4)")
    print("=" * 90)
    for tpms in ('Diamond', 'Gyroid'):
        d = load_data(tpms)
        print(f"\n--- {tpms} ({len(d)} rows, {len(set(zip(d['L'], d['t'])))} geoms) ---")
        print(f"  {'Form':<5}  {'#par':>4}  {'IS%':>6}  {'IS_b':>6}  {'LOO%':>6}  {'LOO_b':>6}")
        results = []
        for name, fn, npar, p0, bounds in FORMS:
            res = fit_form(d, fn, p0, bounds)
            if res is None:
                print(f"  {name:<5}  {npar:>4}  FAIL")
                continue
            popt, is_r, is_b = res
            loo_r, loo_b = loo_form(d, fn, p0, bounds)
            print(f"  {name:<5}  {npar:>4}  {is_r:>5.2f}  {is_b:>+5.2f}  "
                  f"{loo_r:>5.2f}  {loo_b:>+5.2f}")
            results.append((name, npar, popt, is_r, loo_r))
        # Best by LOO
        best = min((r for r in results if not np.isnan(r[4])), key=lambda r: r[4])
        print(f"  ★ best by LOO: {best[0]} (LOO {best[4]:.2f}%)")
        print(f"    coeffs: {best[2].tolist()}")


if __name__ == '__main__':
    main()
