# -*- coding: utf-8 -*-
"""D-F coefficient surrogate model zoo.

Goal: probe whether any training method beats production RBF on BOTH
interpolation (LOO) and extrapolation (leave-one-L-out, Shanghai t=0.6).

Data: the 12 calibrated per-geometry (K, c_F) fit points from SurrogateV3
(same WLS calibration; only the geometry->coefficient regressor varies).

Metrics (all at dP level through the compressible isothermal formula):
  LOO    : leave-one-geometry-out, MAPE on the held-out geometry's rows,
           mean over 12 folds  -> interpolation
  LOLO-x : leave ALL of L=x out, MAPE over those geometries' rows
           (L=4 down-extrap, L=8 up-extrap, L=5/6 gap interpolation)
  SH     : Shanghai 16-case standalone RMSRE (Gyroid; t=0.6 extrapolation;
           contains ~6-8% closure floor + possible L6-anomaly confound --
           directional only)
"""
import sys
import warnings
from math import isfinite, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

_PKG = Path(__file__).resolve().parent.parent   # .../sjtu_tpmshx
ROOT = _PKG.parent                              # repo root (data/ lives here)
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

from scipy.interpolate import RBFInterpolator
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import (
    ConstantKernel as C, Matern, WhiteKernel)
from sklearn.linear_model import HuberRegressor

from df_surrogate.surrogate_v3 import SurrogateV3, R_AIR, P_ATM
from solvers.tpms_calc import geometry as tpms_geometry, air_viscosity

K_FLOOR = 1e-12  # effectively no clamp for the zoo (prod clamp = 1e-8)


# ------------------------------------------------------------------
# Model zoo. Each model: fit(ref_subset) -> self; predict(q) -> (K, cF)
# q: dict(L, t, eps, Dh_m)
# ------------------------------------------------------------------

class ProdRBF:
    """Production: RBF cubic s=0.1 on (L, t, eps), K clamp."""
    def __init__(self, clamp=1e-8, kernel="cubic", smoothing=0.1):
        self.clamp = clamp; self.kernel = kernel; self.s = smoothing

    def fit(self, ref):
        X = ref[["L_mm", "t_mm", "eps_f"]].to_numpy(float)
        self.rK = RBFInterpolator(X, np.log10(ref["K"].to_numpy()),
                                  kernel=self.kernel, smoothing=self.s)
        self.rC = RBFInterpolator(X, np.log10(ref["c_F"].to_numpy()),
                                  kernel=self.kernel, smoothing=self.s)
        return self

    def predict(self, q):
        x = np.array([[q["L"], q["t"], q["eps"]]])
        return (max(10.0 ** float(self.rK(x)[0]), self.clamp),
                10.0 ** float(self.rC(x)[0]))


class GPModel:
    """GP Matern-2.5 on (L, t), ML-II length scales, log targets."""
    def fit(self, ref):
        X = ref[["L_mm", "t_mm"]].to_numpy(float)
        self.gps = []
        for col in ("K", "c_F"):
            y = np.log10(ref[col].to_numpy(float))
            kern = (C(1.0, (1e-2, 1e3))
                    * Matern(length_scale=[2.0, 0.2],
                             length_scale_bounds=(1e-2, 1e2), nu=2.5)
                    + WhiteKernel(1e-4, (1e-8, 1e-1)))
            gp = GaussianProcessRegressor(kernel=kern, normalize_y=True,
                                          n_restarts_optimizer=5,
                                          random_state=0)
            gp.fit(X, y)
            self.gps.append(gp)
        return self

    def predict(self, q):
        x = np.array([[q["L"], q["t"]]])
        K = 10.0 ** float(self.gps[0].predict(x)[0])
        cF = 10.0 ** float(self.gps[1].predict(x)[0])
        return max(K, K_FLOOR), cF


class PowerLaw:
    """log10 y = a + b*log10(D_h) + c*eps  (OLS or Huber)."""
    def __init__(self, robust=False):
        self.robust = robust

    def _design(self, Dh, eps):
        return np.column_stack([np.ones(len(Dh)), np.log10(Dh), eps])

    def fit(self, ref):
        Dh = 2.0 * ref["r_h_m"].to_numpy(float)
        eps = ref["eps_f"].to_numpy(float)
        A = self._design(Dh, eps)
        self.coefs = []
        for col in ("K", "c_F"):
            y = np.log10(ref[col].to_numpy(float))
            if self.robust:
                hub = HuberRegressor(epsilon=1.35, alpha=0.0,
                                     fit_intercept=False, max_iter=500)
                hub.fit(A, y)
                self.coefs.append(hub.coef_.copy())
            else:
                c, *_ = np.linalg.lstsq(A, y, rcond=None)
                self.coefs.append(c)
        return self

    def predict(self, q):
        a = self._design(np.array([q["Dh"]]), np.array([q["eps"]]))
        K = 10.0 ** float((a @ self.coefs[0])[0])
        cF = 10.0 ** float((a @ self.coefs[1])[0])
        return max(K, K_FLOOR), cF


class TrendRBF:
    """Universal-kriging lite: OLS linear trend in (L, t) on log10 y,
    cubic RBF (s=0) on the residual over (L, t, eps)."""
    def fit(self, ref):
        X2 = np.column_stack([np.ones(len(ref)),
                              ref["L_mm"].to_numpy(float),
                              ref["t_mm"].to_numpy(float)])
        X3 = ref[["L_mm", "t_mm", "eps_f"]].to_numpy(float)
        self.parts = []
        for col in ("K", "c_F"):
            y = np.log10(ref[col].to_numpy(float))
            c, *_ = np.linalg.lstsq(X2, y, rcond=None)
            resid = y - X2 @ c
            rbf = RBFInterpolator(X3, resid, kernel="cubic", smoothing=0.0)
            self.parts.append((c, rbf))
        return self

    def predict(self, q):
        x2 = np.array([1.0, q["L"], q["t"]])
        x3 = np.array([[q["L"], q["t"], q["eps"]]])
        out = []
        for c, rbf in self.parts:
            out.append(10.0 ** (float(x2 @ c) + float(rbf(x3)[0])))
        return max(out[0], K_FLOOR), out[1]


class Hybrid:
    """K: power law in D_h only (monotone, physics-plausible).
    c_F: pluggable sub-model."""
    def __init__(self, cf_model_factory):
        self.cf_factory = cf_model_factory

    def fit(self, ref):
        Dh = 2.0 * ref["r_h_m"].to_numpy(float)
        A = np.column_stack([np.ones(len(Dh)), np.log10(Dh)])
        y = np.log10(ref["K"].to_numpy(float))
        self.cK, *_ = np.linalg.lstsq(A, y, rcond=None)
        self.cf_model = self.cf_factory().fit(ref)
        return self

    def predict(self, q):
        K = 10.0 ** float(np.array([1.0, np.log10(q["Dh"])]) @ self.cK)
        _, cF = self.cf_model.predict(q)
        return max(K, K_FLOOR), cF


class PLTrendGP:
    """Universal kriging: power-law trend (log y ~ 1 + log Dh + eps, OLS)
    + GP Matern on (L, t) residuals. Near data the GP corrects the trend;
    far away the GP reverts to 0 and the trend extrapolates."""
    def fit(self, ref):
        Dh = 2.0 * ref["r_h_m"].to_numpy(float)
        A = np.column_stack([np.ones(len(Dh)), np.log10(Dh),
                             ref["eps_f"].to_numpy(float)])
        Xg = ref[["L_mm", "t_mm"]].to_numpy(float)
        self.parts = []
        for col in ("K", "c_F"):
            y = np.log10(ref[col].to_numpy(float))
            c, *_ = np.linalg.lstsq(A, y, rcond=None)
            resid = y - A @ c
            kern = (C(0.1, (1e-4, 1e2))
                    * Matern(length_scale=[2.0, 0.2],
                             length_scale_bounds=(1e-2, 1e2), nu=2.5)
                    + WhiteKernel(1e-4, (1e-8, 1e-1)))
            gp = GaussianProcessRegressor(kernel=kern, normalize_y=False,
                                          n_restarts_optimizer=5,
                                          random_state=0)
            gp.fit(Xg, resid)
            self.parts.append((c, gp))
        return self

    def predict(self, q):
        a = np.array([1.0, np.log10(q["Dh"]), q["eps"]])
        xg = np.array([[q["L"], q["t"]]])
        out = []
        for c, gp in self.parts:
            out.append(10.0 ** (float(a @ c) + float(gp.predict(xg)[0])))
        return max(out[0], K_FLOOR), out[1]


class GlobalDP:
    """One-step global fit at the dP level: log10 K = a0 + a1*log10 Dh,
    log10 cF = b0 + b1*log10 Dh + b2*eps, parameters fitted on ALL
    training rows simultaneously by robust (soft-L1) relative-dP
    residuals. Shares strength across geometries — per-geometry quirks
    (e.g. the L6 c_F hump) are regularized instead of memorized."""
    def __init__(self, loss="soft_l1"):
        self.loss = loss

    def fit(self, ref):
        from scipy.optimize import least_squares
        # Assemble per-row arrays with geometry features attached
        feats, rows_data = [], []
        for _, r in ref.iterrows():
            grp = self._rows[(self._rows["L_mm"] == r.L_mm) &
                             (self._rows["t_mm"] == r.t_mm)]
            n = len(grp)
            feats.append(np.tile([np.log10(2.0 * r.r_h_m), r.eps_f], (n, 1)))
            rows_data.append(grp[["G", "mu", "T", "P_in", "dP", "L_ch"]]
                             .to_numpy(float))
        F = np.vstack(feats)
        Rw = np.vstack(rows_data)
        logDh, eps = F[:, 0], F[:, 1]
        G, mu, T, Pin, dPt, Lc = Rw.T

        def resid(p):
            a0, a1, b0, b1, b2 = p
            K = 10.0 ** (a0 + a1 * logDh)
            cF = 10.0 ** (b0 + b1 * logDh + b2 * eps)
            Cc = mu * G / K + cF * G ** 2
            Psq = Pin ** 2 - 2 * R_AIR * T * Cc * Lc
            dPp = np.where(Psq > 0, Pin - np.sqrt(np.maximum(Psq, 0)), Pin)
            return (dPp - dPt) / dPt

        # Init from two-stage OLS power law
        pl = PowerLaw(robust=False).fit(ref)
        p0 = np.concatenate([pl.coefs[0][:2], pl.coefs[1]])
        sol = least_squares(resid, p0, loss=self.loss, f_scale=0.1,
                            max_nfev=2000)
        self.p = sol.x
        return self

    def predict(self, q):
        a0, a1, b0, b1, b2 = self.p
        lD = np.log10(q["Dh"])
        K = 10.0 ** (a0 + a1 * lD)
        cF = 10.0 ** (b0 + b1 * lD + b2 * q["eps"])
        return max(K, K_FLOOR), cF


class PLTrendGPRobust(PLTrendGP):
    """Same universal-kriging structure but Huber-robust trend: the L6
    c_F hump can't bend the extrapolation trend, while the GP residual
    still memorizes it locally for interpolation."""
    def fit(self, ref):
        Dh = 2.0 * ref["r_h_m"].to_numpy(float)
        A = np.column_stack([np.ones(len(Dh)), np.log10(Dh),
                             ref["eps_f"].to_numpy(float)])
        Xg = ref[["L_mm", "t_mm"]].to_numpy(float)
        self.parts = []
        for col in ("K", "c_F"):
            y = np.log10(ref[col].to_numpy(float))
            hub = HuberRegressor(epsilon=1.35, alpha=0.0,
                                 fit_intercept=False, max_iter=500)
            hub.fit(A, y)
            c = hub.coef_.copy()
            resid = y - A @ c
            kern = (C(0.1, (1e-4, 1e2))
                    * Matern(length_scale=[2.0, 0.2],
                             length_scale_bounds=(1e-2, 1e2), nu=2.5)
                    + WhiteKernel(1e-4, (1e-8, 1e-1)))
            gp = GaussianProcessRegressor(kernel=kern, normalize_y=False,
                                          n_restarts_optimizer=5,
                                          random_state=0)
            gp.fit(Xg, resid)
            self.parts.append((c, gp))
        return self


class LogClip:
    """Wrap any model: clip log10 predictions to the training range
    +/- margin dex. Cheap extrapolation guard — coefficients of an
    unseen TPMS geometry have no business being outside the span of
    the trained family by more than ~25%."""
    def __init__(self, inner_factory, margin=0.1):
        self.inner_factory = inner_factory
        self.margin = margin

    def fit(self, ref):
        self.inner = self.inner_factory().fit(ref)
        self.bK = (np.log10(ref["K"].min()) - self.margin,
                   np.log10(ref["K"].max()) + self.margin)
        self.bC = (np.log10(ref["c_F"].min()) - self.margin,
                   np.log10(ref["c_F"].max()) + self.margin)
        return self

    def predict(self, q):
        K, cF = self.inner.predict(q)
        K = 10.0 ** np.clip(np.log10(K), *self.bK)
        cF = 10.0 ** np.clip(np.log10(cF), *self.bC)
        return float(K), float(cF)


class MedianEns:
    """Median of heterogeneous models (log space): disagreement between
    a mean-reverting GP, a robust trend, and a clipped spline is itself
    an extrapolation guard."""
    def __init__(self, factories):
        self.factories = factories

    def fit(self, ref):
        self.models = [f().fit(ref) for f in self.factories]
        return self

    def predict(self, q):
        Ks, cFs = zip(*(m.predict(q) for m in self.models))
        K = 10.0 ** float(np.median(np.log10(Ks)))
        cF = 10.0 ** float(np.median(np.log10(cFs)))
        return K, cF


def make_global_dp(rows):
    def factory():
        m = GlobalDP()
        m._rows = rows
        return m
    return factory


ZOO = [
    ("prod RBF (clamp1e-8)", lambda: ProdRBF(clamp=1e-8)),
    ("RBF noclamp",          lambda: ProdRBF(clamp=K_FLOOR)),
    ("RBF TPS noclamp",      lambda: ProdRBF(clamp=K_FLOOR,
                                             kernel="thin_plate_spline")),
    ("GP Matern (L,t)",      GPModel),
    ("PowerLaw OLS",         lambda: PowerLaw(robust=False)),
    ("PowerLaw Huber",       lambda: PowerLaw(robust=True)),
    ("Trend+RBF",            TrendRBF),
    ("Hyb K-PL / cF-RBF",    lambda: Hybrid(lambda: ProdRBF(clamp=K_FLOOR))),
    ("Hyb K-PL / cF-Huber",  lambda: Hybrid(lambda: PowerLaw(robust=True))),
    ("PL-Trend + GP resid",  PLTrendGP),
    ("GlobalDP soft-L1",     None),  # factory injected per-family in main
    ("PLHub-Trend + GP",     PLTrendGPRobust),
    ("TPS + logclip0.1",     lambda: LogClip(
        lambda: ProdRBF(clamp=K_FLOOR, kernel="thin_plate_spline"))),
    ("PLHubGP + logclip",    lambda: LogClip(PLTrendGPRobust)),
    ("Median(GP,HubGP,TPSc)", lambda: MedianEns([
        GPModel, PLTrendGPRobust,
        lambda: LogClip(lambda: ProdRBF(clamp=K_FLOOR,
                                        kernel="thin_plate_spline"))])),
]


# ------------------------------------------------------------------
# dP-level evaluation
# ------------------------------------------------------------------

def geom_query(tpms, L, t):
    g = tpms_geometry(tpms, float(L), float(t), 16.0)
    return dict(L=float(L), t=float(t), eps=g["epsilon"] / 2.0, Dh=g["D_h"])


def dp_mape_rows(K, cF, grp):
    G = grp["G"].to_numpy(); T = grp["T"].to_numpy()
    mu = grp["mu"].to_numpy(); Pin = grp["P_in"].to_numpy()
    dPt = grp["dP"].to_numpy(); Lc = grp["L_ch"].to_numpy()
    Cc = mu * G / K + cF * G ** 2
    Psq = Pin ** 2 - 2 * R_AIR * T * Cc * Lc
    ok = Psq > 0
    if not ok.any():
        return np.nan
    dPp = Pin[ok] - np.sqrt(Psq[ok])
    return float(np.mean(np.abs(dPp - dPt[ok]) / dPt[ok]) * 100)


def eval_model(name, factory, model_full, tpms, ref, rows):
    # LOO over 12 geometries
    loo = []
    for i in range(len(ref)):
        sub = ref.drop(ref.index[i])
        m = factory().fit(sub)
        r = ref.iloc[i]
        q = geom_query(tpms, r.L_mm, r.t_mm)
        K, cF = m.predict(q)
        grp = rows[(rows["L_mm"] == r.L_mm) & (rows["t_mm"] == r.t_mm)]
        loo.append(dp_mape_rows(K, cF, grp))
    # LOLO per L level
    lolo = {}
    for L_out in (4.0, 5.0, 6.0, 8.0):
        sub = ref[ref["L_mm"] != L_out]
        m = factory().fit(sub)
        errs = []
        for _, r in ref[ref["L_mm"] == L_out].iterrows():
            q = geom_query(tpms, r.L_mm, r.t_mm)
            K, cF = m.predict(q)
            grp = rows[(rows["L_mm"] == r.L_mm) & (rows["t_mm"] == r.t_mm)]
            errs.append(dp_mape_rows(K, cF, grp))
        lolo[L_out] = float(np.nanmean(errs))
    return float(np.nanmean(loo)), lolo


def eval_shanghai_model(model):
    sh = pd.read_excel(
        ROOT / "data" / "raw_data" / "20260401-上海电气天然气加热器实验工况.xlsx",
        engine="openpyxl", sheet_name="Sheet1", header=None, skiprows=2)
    A_FLOW = 36 * 18.0565e-6
    L_DOM = 0.182
    q = geom_query("Gyroid", 7.0, 0.6)
    K, cF = model.predict(q)
    err_sq, n = 0.0, 0
    for ci in range(16):
        m_dot = float(sh.iloc[ci, 5])
        T = float(sh.iloc[ci, 28]) + 273.15
        P_in = P_ATM + float(sh.iloc[ci, 30])
        dP_exp = float(sh.iloc[ci, 30]) - float(sh.iloc[ci, 31])
        G = m_dot / A_FLOW
        mu = air_viscosity(T)
        Cc = mu * G / K + cF * G ** 2
        Psq = P_in ** 2 - 2.0 * R_AIR * T * Cc * L_DOM
        if Psq <= 0:
            continue
        dPp = P_in - sqrt(Psq)
        err_sq += ((dPp - dP_exp) / dP_exp) ** 2
        n += 1
    return (sqrt(err_sq / n) * 100) if n else float("nan"), K, cF


def main():
    for tpms in ("Gyroid", "Diamond"):
        base = SurrogateV3(tpms=tpms)
        ref, rows = base.ref.copy(), base.rows_df
        assert not ref["K"].isna().any(), "NaN K in ref — add backfill"
        print(f"\n=== {tpms} ===")
        print(f"{'model':<22} {'LOO':>6} {'LOLO4':>6} {'LOLO5':>6} "
              f"{'LOLO6':>6} {'LOLO8':>6} {'SH':>6} {'cF(7,.6)':>8}")
        for name, factory in ZOO:
            if name.startswith("GlobalDP"):
                factory = make_global_dp(rows)
            mf = factory().fit(ref)
            loo, lolo = eval_model(name, factory, mf, tpms, ref, rows)
            if tpms == "Gyroid":
                sh, Kq, cFq = eval_shanghai_model(mf)
            else:
                q = geom_query(tpms, 7.0, 0.6)
                Kq, cFq = mf.predict(q)
                sh = float("nan")
            print(f"{name:<22} {loo:6.1f} {lolo[4.0]:6.1f} {lolo[5.0]:6.1f} "
                  f"{lolo[6.0]:6.1f} {lolo[8.0]:6.1f} {sh:6.1f} {cFq:8.1f}")


if __name__ == "__main__":
    main()
