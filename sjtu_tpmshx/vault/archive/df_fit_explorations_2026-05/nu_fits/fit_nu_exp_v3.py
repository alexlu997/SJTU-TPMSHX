"""fit_nu_exp_v3.py — Nu fit on EXPERIMENTAL Excel 试验记录表_整理版_v3.xlsx.

Conventions (per user, 2026-04-27):
  Re   = col 'Re' (col index 3) — only Re column post-update
  Nu   = col 'Nu' (smooth-wall, NO boundary effect correction)
  Pr   = 0.72 (constant), exponent fixed 1/3 → Pr^(1/3) absorbed into c
  ε_f  = ε from sheet group header / 2 (single-stream interstitial)
  D_h  = col 'D/mm' (mm)
  L, t = col 'L/mm', 't/mm'

Forms tested:
  A. Pure power-law 4p:    Nu = c · Re^a · ε_f^b · (D_h/L)^d
  B. Log-quad 5p:          Nu = c · exp(a2·(ln Re)^2) · Re^a · ε_f^b · (D_h/L)^d

Output: in-sample RMSRE/bias + LOO-by-geometry RMSRE/bias for each TPMS x form.

Usage:
  python -u -m sjtu_tpmshx.df_fit.fit_nu_exp_v3
"""
from __future__ import annotations
import sys, re
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

XLSX = Path(r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data\试验记录表_整理版_v3.xlsx')
PR = 0.72
PR13 = PR ** (1.0 / 3.0)

HEADER_RE = re.compile(r'====\s*([DG])_(\d+)_(\d+)\s*\(L=(\d+)mm,\s*t=([0-9.]+)mm,\s*ε=([0-9.]+)\)')


def load_sheet(sheet: str) -> pd.DataFrame:
    df = pd.read_excel(XLSX, sheet_name=sheet, engine='openpyxl')
    rows = []
    cur_eps = None
    for _, r in df.iterrows():
        bid = str(r['编号'])
        m = HEADER_RE.search(bid)
        if m:
            cur_eps = float(m.group(6))
            continue
        if cur_eps is None:
            continue
        try:
            Re = float(r['Re'])
            Nu = float(r['Nu'])
            L = float(r['L/mm'])
            t = float(r['t/mm'])
            D_h = float(r['D/mm'])
            if any(np.isnan(x) for x in (Re, Nu, L, t, D_h)):
                continue
            rows.append(dict(sample=bid, L=L, t=t, eps_full=cur_eps,
                             eps_f=cur_eps / 2.0, D_h_mm=D_h, Re=Re, Nu=Nu))
        except (ValueError, KeyError, TypeError):
            continue
    return pd.DataFrame(rows)


# ============= Forms =============

def form_A(X, c, a, b, d):
    """Pure power-law 4p: Nu = c · Pr^(1/3) · Re^a · ε_f^b · (D_h/L)^d"""
    Re, eps_f, D_h, L = X
    return c * PR13 * Re**a * eps_f**b * (D_h / L)**d


def form_B(X, c, a, a2, b, d):
    """Log-quad 5p: Nu = c · Pr^(1/3) · exp(a2·(ln Re)^2) · Re^a · ε_f^b · (D_h/L)^d"""
    Re, eps_f, D_h, L = X
    lnRe = np.log(np.maximum(Re, 1.0))
    return c * PR13 * np.exp(a2 * lnRe**2) * Re**a * eps_f**b * (D_h / L)**d


def form_C(X, c, a, b, d, e):
    """Power-law 5p split: Nu = c · Pr^(1/3) · Re^a · ε_f^b · D_h^d · L^e"""
    Re, eps_f, D_h, L = X
    return c * PR13 * Re**a * eps_f**b * D_h**d * L**e


def form_D(X, c, a, a2, b, d, e):
    """Log-quad 6p split: Nu = c · Pr^(1/3) · exp(a2·(lnRe)^2) · Re^a · ε_f^b · D_h^d · L^e"""
    Re, eps_f, D_h, L = X
    lnRe = np.log(np.maximum(Re, 1.0))
    return c * PR13 * np.exp(a2 * lnRe**2) * Re**a * eps_f**b * D_h**d * L**e


def form_E(X, c, a, b):
    """Minimal power-law 3p: Nu = c · Pr^(1/3) · Re^a · ε_f^b (no geometry length)"""
    Re, eps_f, _, _ = X
    return c * PR13 * Re**a * eps_f**b


def form_F(X, c, a, a2, b):
    """Log-quad 4p: Nu = c · Pr^(1/3) · exp(a2·(lnRe)^2) · Re^a · ε_f^b (no geom length)"""
    Re, eps_f, _, _ = X
    lnRe = np.log(np.maximum(Re, 1.0))
    return c * PR13 * np.exp(a2 * lnRe**2) * Re**a * eps_f**b


def form_G(X, c, a, b, d):
    """Power-law 4p with L only: Nu = c · Pr^(1/3) · Re^a · ε_f^b · L^d"""
    Re, eps_f, _, L = X
    return c * PR13 * Re**a * eps_f**b * L**d


def form_H(X, c, a, a2, b, d):
    """Log-quad 5p with L only: Nu = c · Pr^(1/3) · exp(a2·(lnRe)^2) · Re^a · ε_f^b · L^d"""
    Re, eps_f, _, L = X
    lnRe = np.log(np.maximum(Re, 1.0))
    return c * PR13 * np.exp(a2 * lnRe**2) * Re**a * eps_f**b * L**d


def fit_form(d, form, p0, bounds):
    Re = d['Re'].to_numpy()
    eps_f = d['eps_f'].to_numpy()
    D_h = d['D_h_mm'].to_numpy()
    L = d['L'].to_numpy()
    Nu = d['Nu'].to_numpy()
    X = (Re, eps_f, D_h, L)
    popt, _ = curve_fit(form, X, Nu, p0=p0, bounds=bounds, maxfev=80000)
    Nu_pred = form(X, *popt)
    err = (Nu_pred - Nu) / Nu
    return popt, float(np.sqrt(np.mean(err**2)) * 100), float(np.mean(err) * 100)


def loo(d, form, p0, bounds):
    geoms = sorted(set(zip(d['L'], d['t'])))
    err_all = []
    for L_t, t_t in geoms:
        sel = (d['L'] == L_t) & (d['t'] == t_t)
        d_train = d[~sel]
        d_test = d[sel]
        if len(d_train) < 5 or len(d_test) == 0:
            continue
        try:
            popt, _, _ = fit_form(d_train, form, p0, bounds)
        except Exception:
            continue
        X = (d_test['Re'].to_numpy(), d_test['eps_f'].to_numpy(),
             d_test['D_h_mm'].to_numpy(), d_test['L'].to_numpy())
        Nu_p = form(X, *popt)
        err = (Nu_p - d_test['Nu'].to_numpy()) / d_test['Nu'].to_numpy()
        err_all.extend(err.tolist())
    e = np.array(err_all)
    return float(np.sqrt(np.mean(e**2)) * 100), float(np.mean(e) * 100), len(geoms)


def report(name, d):
    print(f"\n=== {name} ===")
    print(f"  rows: {len(d)}, geometries: {len(set(zip(d['L'], d['t'])))}")
    print(f"  Re range:    [{d['Re'].min():.0f}, {d['Re'].max():.0f}]")
    print(f"  ε_f range:   [{d['eps_f'].min():.3f}, {d['eps_f'].max():.3f}]")
    print(f"  D_h/L range: [{(d['D_h_mm']/d['L']).min():.3f}, {(d['D_h_mm']/d['L']).max():.3f}]")

    # Form A — pure power-law 4p (D_h/L combined)
    p0_A = [0.5, 0.6, 0.5, -0.5]
    b_A = ([1e-10, -3, -20, -20], [1000, 3, 20, 20])
    pA, rA, biasA = fit_form(d, form_A, p0_A, b_A)
    looA_r, looA_b, _ = loo(d, form_A, p0_A, b_A)
    c, a, b, dd = pA
    print(f"\n  Form A (power-law 4p): Nu = c·Pr^(1/3)·Re^a·ε_f^b·(D_h/L)^d")
    print(f"    c={c:.6f}  a={a:.6f}  b={b:.6f}  d={dd:.6f}")
    print(f"    in-sample: RMSRE={rA:.2f}% bias={biasA:+.2f}%")
    print(f"    LOO:       RMSRE={looA_r:.2f}% bias={looA_b:+.2f}%")

    # Form B — log-quad 5p (D_h/L combined)
    p0_B = [0.5, 0.5, 0.0, 0.5, -0.5]
    b_B = ([1e-10, -3, -1, -20, -20], [1000, 3, 1, 20, 20])
    pB, rB, biasB = fit_form(d, form_B, p0_B, b_B)
    looB_r, looB_b, _ = loo(d, form_B, p0_B, b_B)
    c, a, a2, b, dd = pB
    print(f"\n  Form B (log-quad 5p): Nu = c·Pr^(1/3)·exp(a2·(lnRe)^2)·Re^a·ε_f^b·(D_h/L)^d")
    print(f"    c={c:.6f}  a={a:.6f}  a2={a2:.6f}  b={b:.6f}  d={dd:.6f}")
    print(f"    in-sample: RMSRE={rB:.2f}% bias={biasB:+.2f}%")
    print(f"    LOO:       RMSRE={looB_r:.2f}% bias={looB_b:+.2f}%")

    # Form C — power-law 5p (D_h, L split)
    p0_C = [0.5, 0.6, 0.5, 0.5, -0.5]
    b_C = ([1e-10, -3, -20, -20, -20], [1000, 3, 20, 20, 20])
    pC, rC, biasC = fit_form(d, form_C, p0_C, b_C)
    looC_r, looC_b, _ = loo(d, form_C, p0_C, b_C)
    c, a, b, dd, ee = pC
    print(f"\n  Form C (power-law 5p): Nu = c·Pr^(1/3)·Re^a·ε_f^b·D_h^d·L^e")
    print(f"    c={c:.6f}  a={a:.6f}  b={b:.6f}  d={dd:.6f}  e={ee:.6f}")
    print(f"    in-sample: RMSRE={rC:.2f}% bias={biasC:+.2f}%")
    print(f"    LOO:       RMSRE={looC_r:.2f}% bias={looC_b:+.2f}%")

    # Form D — log-quad 6p split
    p0_D = [0.5, 0.5, 0.0, 0.5, 0.5, -0.5]
    b_D = ([1e-10, -3, -1, -20, -20, -20], [1000, 3, 1, 20, 20, 20])
    pD, rD_, biasD = fit_form(d, form_D, p0_D, b_D)
    looD_r, looD_b, _ = loo(d, form_D, p0_D, b_D)
    c, a, a2, b, dd, ee = pD
    print(f"\n  Form D (log-quad 6p): Nu = c·Pr^(1/3)·exp(a2·(lnRe)^2)·Re^a·ε_f^b·D_h^d·L^e")
    print(f"    c={c:.6f}  a={a:.6f}  a2={a2:.6f}  b={b:.6f}  d={dd:.6f}  e={ee:.6f}")
    print(f"    in-sample: RMSRE={rD_:.2f}% bias={biasD:+.2f}%")
    print(f"    LOO:       RMSRE={looD_r:.2f}% bias={looD_b:+.2f}%")

    # Form E — minimal 3p (Re, ε_f only)
    p0_E = [0.5, 0.6, 0.5]
    b_E = ([1e-10, -3, -20], [1000, 3, 20])
    pE, rE, biasE = fit_form(d, form_E, p0_E, b_E)
    looE_r, looE_b, _ = loo(d, form_E, p0_E, b_E)
    c, a, b = pE
    print(f"\n  Form E (power-law 3p, no L): Nu = c·Pr^(1/3)·Re^a·ε_f^b")
    print(f"    c={c:.6f}  a={a:.6f}  b={b:.6f}")
    print(f"    in-sample: RMSRE={rE:.2f}% bias={biasE:+.2f}%")
    print(f"    LOO:       RMSRE={looE_r:.2f}% bias={looE_b:+.2f}%")

    # Form F — log-quad 4p (no L)
    p0_F = [0.5, 0.5, 0.0, 0.5]
    b_F = ([1e-10, -3, -1, -20], [1000, 3, 1, 20])
    pF, rF, biasF = fit_form(d, form_F, p0_F, b_F)
    looF_r, looF_b, _ = loo(d, form_F, p0_F, b_F)
    c, a, a2, b = pF
    print(f"\n  Form F (log-quad 4p, no L): Nu = c·Pr^(1/3)·exp(a2·(lnRe)^2)·Re^a·ε_f^b")
    print(f"    c={c:.6f}  a={a:.6f}  a2={a2:.6f}  b={b:.6f}")
    print(f"    in-sample: RMSRE={rF:.2f}% bias={biasF:+.2f}%")
    print(f"    LOO:       RMSRE={looF_r:.2f}% bias={looF_b:+.2f}%")

    # Form G — PL 4p with L only
    p0_G = [0.5, 0.6, 0.5, -0.5]
    b_G = ([1e-10, -3, -20, -10], [1000, 3, 20, 10])
    pG, rG_, biasG = fit_form(d, form_G, p0_G, b_G)
    looG_r, looG_b, _ = loo(d, form_G, p0_G, b_G)
    c, a, b, dd = pG
    print(f"\n  Form G (PL 4p, L only): Nu = c·Pr^(1/3)·Re^a·ε_f^b·L^d")
    print(f"    c={c:.6f}  a={a:.6f}  b={b:.6f}  d={dd:.6f}")
    print(f"    in-sample: RMSRE={rG_:.2f}% bias={biasG:+.2f}%")
    print(f"    LOO:       RMSRE={looG_r:.2f}% bias={looG_b:+.2f}%")

    # Form H — LQ 5p with L only
    p0_H = [0.5, 0.5, 0.0, 0.5, -0.5]
    b_H = ([1e-10, -3, -1, -20, -10], [1000, 3, 1, 20, 10])
    pH, rH, biasH = fit_form(d, form_H, p0_H, b_H)
    looH_r, looH_b, _ = loo(d, form_H, p0_H, b_H)
    c, a, a2, b, dd = pH
    print(f"\n  Form H (LQ 5p, L only): Nu = c·Pr^(1/3)·exp(a2·(lnRe)^2)·Re^a·ε_f^b·L^d")
    print(f"    c={c:.6f}  a={a:.6f}  a2={a2:.6f}  b={b:.6f}  d={dd:.6f}")
    print(f"    in-sample: RMSRE={rH:.2f}% bias={biasH:+.2f}%")
    print(f"    LOO:       RMSRE={looH_r:.2f}% bias={looH_b:+.2f}%")

    return dict(A=(pA, rA, looA_r), B=(pB, rB, looB_r),
                C=(pC, rC, looC_r), D=(pD, rD_, looD_r),
                E=(pE, rE, looE_r), F=(pF, rF, looF_r),
                G=(pG, rG_, looG_r), H=(pH, rH, looH_r))


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("=" * 78)
    print(f"Nu fit — experimental Excel: {XLSX.name}")
    print(f"Pr={PR}, Pr^(1/3)={PR13:.4f} (absorbed into c); boundary effect IGNORED")
    print("=" * 78)
    dD = load_sheet('Diamond_汇总')
    dG = load_sheet('Gyroid_汇总')
    rD = report('Diamond', dD)
    rG = report('Gyroid', dG)

    print("\n" + "=" * 78)
    print("Summary (LOO-by-geometry RMSRE):")
    forms = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
    labels = ['A(PL4p Dh/L)', 'B(LQ5p Dh/L)', 'C(PL5p)', 'D(LQ6p)',
              'E(PL3p)', 'F(LQ4p)', 'G(PL4p L)', 'H(LQ5p L)']
    head = '  TPMS       ' + ' '.join(f'{l:<10}' for l in labels)
    print(head)
    print('  ' + '-'*10 + ' ' + ' '.join(['-'*10]*6))
    print('  Diamond    ' + ' '.join(f'{rD[f][2]:>6.2f}%   ' for f in forms))
    print('  Gyroid     ' + ' '.join(f'{rG[f][2]:>6.2f}%   ' for f in forms))


if __name__ == '__main__':
    main()
