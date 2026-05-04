"""eval_user_form.py — Evaluate user-proposed Nu forms against experimental data.

Diamond: Nu = 0.084645·Re^0.8273·(D_h/L)^0.2260
Gyroid:  Nu = 0.112938·Re^0.7898·(D_h/L)^0.2325

Pr absorbed implicitly into c (no Pr term in user form).
"""
from __future__ import annotations
import sys
import numpy as np
from sjtu_tpmshx.df_fit.fit_nu_exp_v3 import load_sheet


def eval_form(d, c, a, dd, name):
    Re = d['Re'].to_numpy()
    Dh = d['D_h_mm'].to_numpy()
    L = d['L'].to_numpy()
    Nu = d['Nu'].to_numpy()
    Nu_p = c * Re**a * (Dh / L)**dd
    err = (Nu_p - Nu) / Nu
    rmsre = float(np.sqrt(np.mean(err**2)) * 100)
    bias = float(np.mean(err) * 100)
    max_abs = float(np.max(np.abs(err)) * 100)
    print(f"=== {name} ===")
    print(f"  Form:  Nu = {c}·Re^{a}·(D_h/L)^{dd}")
    print(f"  rows:  {len(d)}")
    print(f"  RMSRE: {rmsre:.2f}%   bias: {bias:+.2f}%   max|err|: {max_abs:.2f}%")
    # per-geom breakdown
    print(f"  per-geometry RMSRE:")
    for (Lg, tg), grp in d.groupby(['L', 't']):
        g_idx = (d['L'] == Lg) & (d['t'] == tg)
        e = err[g_idx.to_numpy()]
        print(f"    L={Lg:.0f} t={tg:.1f}  n={len(e):2d}  "
              f"RMSRE={np.sqrt(np.mean(e**2))*100:5.2f}%  "
              f"bias={np.mean(e)*100:+6.2f}%")


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    dD = load_sheet('Diamond_汇总')
    dG = load_sheet('Gyroid_汇总')
    eval_form(dD, 0.084645, 0.8273, 0.2260, 'Diamond — user form')
    print()
    eval_form(dG, 0.112938, 0.7898, 0.2325, 'Gyroid — user form')


if __name__ == '__main__':
    main()
