"""Re-fit user form (Nu = c·Re^a·(D_h/L)^d, no ε_f) to verify coefficients."""
from __future__ import annotations
import sys
import numpy as np
from scipy.optimize import curve_fit
from sjtu_tpmshx.df_fit.fit_nu_exp_v3 import load_sheet


def user_form(X, c, a, d):
    Re, Dh, L = X
    return c * Re**a * (Dh / L)**d


def fit_eval(d, name, user_c, user_a, user_d):
    Re = d['Re'].to_numpy()
    Dh = d['D_h_mm'].to_numpy()
    L = d['L'].to_numpy()
    Nu = d['Nu'].to_numpy()
    X = (Re, Dh, L)

    # Linear (curve_fit on Nu)
    popt_lin, _ = curve_fit(user_form, X, Nu, p0=[0.1, 0.8, 0.2],
                            bounds=([1e-6, 0, -5], [10, 2, 5]), maxfev=50000)

    # Log-space LSQ
    Y = np.log(Nu)
    A = np.column_stack([np.ones_like(Re), np.log(Re), np.log(Dh / L)])
    coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
    c_log = float(np.exp(coef[0]))
    a_log = float(coef[1])
    d_log = float(coef[2])

    def metrics(c, a, dd, label):
        Nu_p = c * Re**a * (Dh / L)**dd
        err = (Nu_p - Nu) / Nu
        rmsre = float(np.sqrt(np.mean(err**2)) * 100)
        bias = float(np.mean(err) * 100)
        # log-space residual
        log_err = np.log(Nu_p) - np.log(Nu)
        log_rmse = float(np.sqrt(np.mean(log_err**2)))
        print(f"    {label:<20} c={c:.6f} a={a:.6f} d={dd:.6f}")
        print(f"    {'':20s} RMSRE={rmsre:.2f}%  bias={bias:+.2f}%  log-RMSE={log_rmse:.4f}")

    print(f"=== {name} ===")
    metrics(user_c, user_a, user_d, "user-provided")
    metrics(*popt_lin, "linear-Nu fit")
    metrics(c_log, a_log, d_log, "log-space fit")


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    dD = load_sheet('Diamond_汇总')
    dG = load_sheet('Gyroid_汇总')
    fit_eval(dD, 'Diamond', 0.084645, 0.8273, 0.2260)
    print()
    fit_eval(dG, 'Gyroid', 0.112938, 0.7898, 0.2325)


if __name__ == '__main__':
    main()
