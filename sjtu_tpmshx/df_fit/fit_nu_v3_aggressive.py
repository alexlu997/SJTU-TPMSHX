"""fit_nu_v3_aggressive.py — push Nu accuracy beyond power-law.

Methods tested (LOO leave-one-geometry-out, all on v3/CFD4 data):
  M1: Polynomial in log-space (deg 2 / 3 / 4)
       log Nu = Σ c_ijk · (log Re)^i · (log ε_f)^j · (log L)^k · ...
  M2: Gaussian Process regression on log-space features
  M3: Radial Basis Function (multiquadric / thin-plate) interp
  M4: Neural network (small MLP, sklearn)
  M5: Power-law base (S8) + RBF residual correction
  M6: Random Forest / Gradient Boosting (XGBoost not required)
  M7: kNN baseline (smoothed)

All compared on same LOO protocol.
"""
from __future__ import annotations
import sys
import warnings
from pathlib import Path
import numpy as np
from scipy.optimize import curve_fit

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import Pr, Sa_mm
from df_fit.fit_nu_single_stream import load_data

warnings.filterwarnings('ignore')


def _features(d):
    """Return (X, log_Nu) for log-space methods."""
    Re = d['Re_fit'].to_numpy()
    eps_f = d['eps_f'].to_numpy()
    L = d['L_mm'].to_numpy()
    D = d['D_h_mm'].to_numpy()
    t = d['t'].to_numpy()
    X = np.column_stack([np.log(Re), np.log(eps_f),
                         np.log(L/(1000*Sa_mm)),
                         np.log(D/(1000*Sa_mm)),
                         np.log(t/(1000*Sa_mm))])
    Nu = d['Nu'].to_numpy()
    return X, np.log(Nu), Nu


def loo_run(d, fit_fn, predict_fn, name):
    """Generic LOO loop. fit_fn takes (X_tr, y_tr); predict_fn takes (model, X_te)."""
    geoms = sorted(set(zip(d['L'], d['t'])))
    err_all, in_err_all = [], []
    for L_t, t_t in geoms:
        sel = (d['L'] == L_t) & (d['t'] == t_t)
        d_tr = d[~sel]
        d_te = d[sel]
        if len(d_tr) < 10 or len(d_te) == 0:
            continue
        X_tr, y_tr_log, _ = _features(d_tr)
        X_te, y_te_log, Nu_te = _features(d_te)
        try:
            model = fit_fn(X_tr, y_tr_log)
            log_pred = predict_fn(model, X_te)
            Nu_p = np.exp(log_pred)
            err = (Nu_p - Nu_te) / Nu_te
            err_all.extend(err.tolist())
        except Exception as e:
            print(f"  {name}: LOO fold {L_t}_{t_t} FAIL: {e}")
            continue
    if not err_all:
        return float('nan'), float('nan')
    e = np.array(err_all)
    return float(np.sqrt(np.mean(e**2))*100), float(np.mean(e)*100)


def in_sample(d, fit_fn, predict_fn):
    X, y_log, Nu = _features(d)
    m = fit_fn(X, y_log)
    p = np.exp(predict_fn(m, X))
    err = (p - Nu) / Nu
    return float(np.sqrt(np.mean(err**2))*100), float(np.mean(err)*100)


# ── M1: Polynomial in log space ──
def make_poly(deg):
    from sklearn.preprocessing import PolynomialFeatures
    from sklearn.linear_model import LinearRegression
    from sklearn.pipeline import Pipeline
    def fit(X, y):
        pipe = Pipeline([
            ('poly', PolynomialFeatures(degree=deg, include_bias=False)),
            ('lin', LinearRegression()),
        ])
        pipe.fit(X, y)
        return pipe
    def predict(m, X):
        return m.predict(X)
    return fit, predict


# ── M2: Gaussian Process ──
def make_gp():
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel
    def fit(X, y):
        kernel = ConstantKernel(1.0) * RBF(length_scale=[1.0]*X.shape[1]) + WhiteKernel(0.01)
        gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True,
                                       n_restarts_optimizer=3,
                                       alpha=1e-6)
        gp.fit(X, y)
        return gp
    def predict(m, X):
        return m.predict(X)
    return fit, predict


# ── M3: RBF interpolation ──
def make_rbf(kind='thin_plate_spline'):
    from scipy.interpolate import RBFInterpolator
    def fit(X, y):
        return RBFInterpolator(X, y, kernel=kind, smoothing=0.01)
    def predict(m, X):
        return m(X)
    return fit, predict


# ── M4: Neural net (small MLP) ──
def make_mlp(hidden=(32, 16)):
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    def fit(X, y):
        pipe = Pipeline([
            ('sc', StandardScaler()),
            ('mlp', MLPRegressor(hidden_layer_sizes=hidden,
                                  activation='tanh',
                                  solver='lbfgs',
                                  max_iter=5000,
                                  random_state=42)),
        ])
        pipe.fit(X, y)
        return pipe
    def predict(m, X):
        return m.predict(X)
    return fit, predict


# ── M5: S8 power-law base + RBF residual correction ──
def make_residual_rbf():
    """S8 base + RBF correction in log space."""
    from scipy.interpolate import RBFInterpolator

    def s8_log(Re, eps_f, L, D, t, params):
        c, a, a2, b, d1, d2, d3 = params
        logRe = np.log(np.maximum(Re, 1.0))
        log_Nu = (np.log(c) + (1/3)*np.log(Pr) + a*logRe + a2*logRe**2
                  + b*np.log(eps_f)
                  + d1*np.log(D/(1000*Sa_mm))
                  + d2*np.log(L/(1000*Sa_mm))
                  + d3*np.log(t/(1000*Sa_mm)))
        return log_Nu

    def s8_model(X, c, a, a2, b, d1, d2, d3):
        Re, eps_f, L, D, t = X
        logRe = np.log(np.maximum(Re, 1.0))
        return (c * Pr**(1/3) * Re**a * np.exp(a2*logRe**2) * eps_f**b
                * (D/(1000*Sa_mm))**d1 * (L/(1000*Sa_mm))**d2
                * (t/(1000*Sa_mm))**d3)

    def fit(X, y_log):
        # X cols: log Re, log eps_f, log L/Sa, log D/Sa, log t/Sa
        Re = np.exp(X[:, 0])
        eps_f = np.exp(X[:, 1])
        L = np.exp(X[:, 2]) * 1000 * Sa_mm
        D = np.exp(X[:, 3]) * 1000 * Sa_mm
        t = np.exp(X[:, 4]) * 1000 * Sa_mm
        Nu = np.exp(y_log)
        Xs = (Re, eps_f, L, D, t)
        p0 = [10.0, 1e-5, 0.04, 0.5, -0.5, 0.0, 0.0]
        bounds = ([1e-8, 0, -1, -20, -10, -10, -10],
                  [1e4, 2, 1, 20, 10, 10, 10])
        try:
            popt, _ = curve_fit(s8_model, Xs, Nu, p0=p0, bounds=bounds,
                                maxfev=200000)
        except Exception:
            popt = np.array(p0)
        Nu_base = s8_model(Xs, *popt)
        log_resid = y_log - np.log(Nu_base)
        rbf = RBFInterpolator(X, log_resid, kernel='thin_plate_spline',
                              smoothing=0.05)
        return (popt, rbf)

    def predict(m, X):
        popt, rbf = m
        Re = np.exp(X[:, 0])
        eps_f = np.exp(X[:, 1])
        L = np.exp(X[:, 2]) * 1000 * Sa_mm
        D = np.exp(X[:, 3]) * 1000 * Sa_mm
        t = np.exp(X[:, 4]) * 1000 * Sa_mm
        Xs = (Re, eps_f, L, D, t)
        Nu_base = s8_model(Xs, *popt)
        log_corr = rbf(X)
        return np.log(Nu_base) + log_corr

    return fit, predict


# ── M6: Random Forest / Gradient Boosting ──
def make_rf():
    from sklearn.ensemble import RandomForestRegressor
    def fit(X, y):
        return RandomForestRegressor(n_estimators=200, max_depth=8,
                                      min_samples_leaf=2, random_state=42).fit(X, y)
    def predict(m, X):
        return m.predict(X)
    return fit, predict


def make_gb():
    from sklearn.ensemble import GradientBoostingRegressor
    def fit(X, y):
        return GradientBoostingRegressor(n_estimators=300, max_depth=4,
                                          learning_rate=0.05, random_state=42).fit(X, y)
    def predict(m, X):
        return m.predict(X)
    return fit, predict


# ── M7: kNN ──
def make_knn(k=5):
    from sklearn.neighbors import KNeighborsRegressor
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    def fit(X, y):
        return Pipeline([
            ('sc', StandardScaler()),
            ('knn', KNeighborsRegressor(n_neighbors=k, weights='distance')),
        ]).fit(X, y)
    def predict(m, X):
        return m.predict(X)
    return fit, predict


METHODS = [
    ('M1 Poly2',          make_poly(2)),
    ('M1 Poly3',          make_poly(3)),
    ('M1 Poly4',          make_poly(4)),
    ('M2 GP RBF',         make_gp()),
    ('M3 RBF tps',        make_rbf('thin_plate_spline')),
    ('M3 RBF mq',         make_rbf('multiquadric')),
    ('M4 MLP 32-16',      make_mlp((32, 16))),
    ('M4 MLP 64-32-16',   make_mlp((64, 32, 16))),
    ('M5 S8+RBF resid',   make_residual_rbf()),
    ('M6 RF',             make_rf()),
    ('M6 GB',             make_gb()),
    ('M7 kNN k=5',        make_knn(5)),
]


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("Aggressive Nu fit on v3 (CFD4) — push beyond power-law")
    print("=" * 80)
    for tpms in ('Diamond', 'Gyroid'):
        d = load_data(tpms)
        print(f"\n--- {tpms} ({len(d)} rows, {len(set(zip(d['L'], d['t'])))} geoms) ---")
        print(f"  {'Method':<22}  {'IS%':>6}  {'IS_b':>6}  {'LOO%':>6}  {'LOO_b':>6}")
        print(f"  {'-'*22}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*6}")
        for name, (fit_fn, pred_fn) in METHODS:
            try:
                is_r, is_b = in_sample(d, fit_fn, pred_fn)
                loo_r, loo_b = loo_run(d, fit_fn, pred_fn, name)
                print(f"  {name:<22}  {is_r:>5.2f}  {is_b:>+5.2f}  "
                      f"{loo_r:>5.2f}  {loo_b:>+5.2f}")
            except Exception as e:
                print(f"  {name:<22}  ERROR: {type(e).__name__}: {str(e)[:50]}")


if __name__ == '__main__':
    main()
