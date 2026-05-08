"""Log-space LSQ comparison: user 3p form vs adding ε_f."""
from __future__ import annotations
import sys
import numpy as np
from sjtu_tpmshx.df_fit.fit_nu_exp_v3 import load_sheet


def log_fit(d, regressors, names):
    Y = np.log(d['Nu'].to_numpy())
    A = np.column_stack([np.ones_like(Y)] + regressors)
    coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
    pred = A @ coef
    err_log = pred - Y
    Nu_p = np.exp(pred)
    err_rel = (Nu_p - d['Nu'].to_numpy()) / d['Nu'].to_numpy()
    rmsre = float(np.sqrt(np.mean(err_rel**2)) * 100)
    bias = float(np.mean(err_rel) * 100)
    log_rmse = float(np.sqrt(np.mean(err_log**2)))
    coef_str = f"c={np.exp(coef[0]):.6f}  " + "  ".join(
        f"{n}={c:+.4f}" for n, c in zip(names, coef[1:]))
    print(f"    {coef_str}")
    print(f"    RMSRE={rmsre:.2f}%  bias={bias:+.2f}%  log-RMSE={log_rmse:.4f}")
    return coef, rmsre


def loo_log(d, build_regressors_fn, names):
    """LOO-by-geometry on log-space fit."""
    geoms = sorted(set(zip(d['L'], d['t'])))
    err_all = []
    for L_t, t_t in geoms:
        sel = (d['L'] == L_t) & (d['t'] == t_t)
        d_train = d[~sel]
        d_test = d[sel]
        regs_train = build_regressors_fn(d_train)
        regs_test = build_regressors_fn(d_test)
        Y = np.log(d_train['Nu'].to_numpy())
        A_train = np.column_stack([np.ones_like(Y)] + regs_train)
        coef, *_ = np.linalg.lstsq(A_train, Y, rcond=None)
        A_test = np.column_stack([np.ones(len(d_test))] + regs_test)
        Nu_p = np.exp(A_test @ coef)
        err = (Nu_p - d_test['Nu'].to_numpy()) / d_test['Nu'].to_numpy()
        err_all.extend(err.tolist())
    e = np.array(err_all)
    return float(np.sqrt(np.mean(e**2)) * 100), float(np.mean(e) * 100)


def report(d, name):
    print(f"=== {name} (log-space LSQ) ===")

    # Form U: user form — Re, D_h/L
    print(f"  Form U:  Nu = c·Re^a·(D_h/L)^d   (3p, user)")
    log_fit(d, [np.log(d['Re']), np.log(d['D_h_mm']/d['L'])], ['a', 'd'])
    rmsre_loo, bias_loo = loo_log(d,
        lambda x: [np.log(x['Re'].to_numpy()), np.log(x['D_h_mm'].to_numpy()/x['L'].to_numpy())],
        ['a', 'd'])
    print(f"    LOO: RMSRE={rmsre_loo:.2f}%  bias={bias_loo:+.2f}%")

    # Form U+ε: add ε_f
    print(f"\n  Form U+ε: Nu = c·Re^a·ε_f^b·(D_h/L)^d   (4p)")
    log_fit(d, [np.log(d['Re']), np.log(d['eps_f']), np.log(d['D_h_mm']/d['L'])],
            ['a', 'b', 'd'])
    rmsre_loo, bias_loo = loo_log(d,
        lambda x: [np.log(x['Re'].to_numpy()), np.log(x['eps_f'].to_numpy()),
                   np.log(x['D_h_mm'].to_numpy()/x['L'].to_numpy())],
        ['a', 'b', 'd'])
    print(f"    LOO: RMSRE={rmsre_loo:.2f}%  bias={bias_loo:+.2f}%")

    # Log-quad: add (lnRe)^2
    print(f"\n  Form LQ: Nu = c·exp(a2·(lnRe)^2)·Re^a·ε_f^b·(D_h/L)^d   (5p)")
    lnRe = np.log(d['Re'].to_numpy())
    log_fit(d, [lnRe, lnRe**2, np.log(d['eps_f']), np.log(d['D_h_mm']/d['L'])],
            ['a', 'a2', 'b', 'd'])
    def reg_lq(x):
        ln = np.log(x['Re'].to_numpy())
        return [ln, ln**2, np.log(x['eps_f'].to_numpy()),
                np.log(x['D_h_mm'].to_numpy()/x['L'].to_numpy())]
    rmsre_loo, bias_loo = loo_log(d, reg_lq, ['a', 'a2', 'b', 'd'])
    print(f"    LOO: RMSRE={rmsre_loo:.2f}%  bias={bias_loo:+.2f}%")


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    dD = load_sheet('Diamond_汇总')
    dG = load_sheet('Gyroid_汇总')
    report(dD, 'Diamond')
    print()
    report(dG, 'Gyroid')


if __name__ == '__main__':
    main()
