"""nu_residual_correction.py — Nu correlation residual learning.

Method:
  1. Compute in-sample residuals: r = (Nu_actual - Nu_pred) / Nu_pred
     where Nu_pred from current correlation (Diamond F4-D, Gyroid F7).
  2. Fit smooth g(log_Re, ε_f, L, t) ≈ r using RBF (regularised).
  3. Apply: Nu_corrected = Nu_pred · (1 + g).

Single-stream convention (matches refit fit_nu_single_stream + fit_gyroid_F7):
  ε_f = ε/2, Re = ρ·u·D_h/μ (D_h-based, single-stream u).

Public API:
  get_nu_corrector(tpms) -> NuResidualCorrector  (cached)
  predict_nu_corrected(tpms, Re, eps_f, L_mm, D_h_mm) -> float

Env var toggle:
  TPMSHX_NU_RESIDUAL_CORR=1  → enable; default off (preserves baseline behavior)

Independence from prior dead-ends:
  D-F residual learning gave LOO -4pp Diamond / -2pp Gyroid but Shanghai
  退化 7pp (orthogonal direction). Nu likely similar — LOO improvement, but
  Shanghai t=0.6 extrapolation behavior may differ. Hence default off.
"""
from __future__ import annotations

import sys
from pathlib import Path
import numpy as np

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scipy.interpolate import RBFInterpolator

from solvers.tpms_calc import nu_from_Re

_G_CLAMP = 0.5      # |g| ≤ 0.5 → dP factor in [0.5, 1.5]
_RBF_SMOOTHING = 0.5


class NuResidualCorrector:
    """Smooth Nu residual correction via RBF on (log_Re, ε_f, L, t).

    Built from in-sample training Excel residuals against current
    nu_from_Re prediction (post-refit single-stream Diamond F4-D / Gyroid F7).
    """

    def __init__(self, tpms: str = "Gyroid",
                 smoothing: float = _RBF_SMOOTHING,
                 g_clamp: float = _G_CLAMP):
        self.tpms = tpms
        self._smoothing = float(smoothing)
        self._g_clamp = float(g_clamp)
        self._build()

    def _build(self):
        from df_fit.fit_nu_single_stream import load_data
        d = load_data(self.tpms)
        log_Re = np.log10(d['Re_fit'].to_numpy())
        eps_f = d['eps_f'].to_numpy()
        L_mm = d['L_mm'].to_numpy()
        t_mm = d['t'].to_numpy()
        D_h_mm = d['D_h_mm'].to_numpy()
        Nu_actual = d['Nu'].to_numpy()
        Nu_pred = np.array([
            nu_from_Re(self.tpms, r, ef, lm, dh)
            for r, ef, lm, dh in zip(d['Re_fit'], eps_f, L_mm, D_h_mm)
        ])
        # g_target = (Nu_actual - Nu_pred) / Nu_pred  →  Nu_corr = Nu_pred·(1+g)
        g_target = (Nu_actual - Nu_pred) / Nu_pred

        X = np.column_stack([log_Re, eps_f, L_mm, t_mm])
        self._rbf = RBFInterpolator(
            X, g_target,
            kernel='thin_plate_spline',
            smoothing=self._smoothing)
        self._n_train = len(d)
        self._log_Re_range = (float(log_Re.min()), float(log_Re.max()))
        self._eps_f_range = (float(eps_f.min()), float(eps_f.max()))
        self._g_in_sample = g_target

    def correction(self, Re, eps_f, L_mm, t_mm) -> float:
        """Return g s.t. Nu_corr = Nu_pred · (1 + g). Clamped ±g_clamp."""
        log_Re = float(np.log10(max(float(Re), 1.0)))
        x = np.atleast_2d([log_Re, float(eps_f), float(L_mm), float(t_mm)])
        g = float(self._rbf(x)[0])
        if not np.isfinite(g):
            return 0.0
        return float(np.clip(g, -self._g_clamp, self._g_clamp))

    def correction_vec(self, Re, eps_f, L_mm, t_mm):
        """Vectorised correction."""
        Re = np.asarray(Re, dtype=np.float64)
        ef = np.asarray(eps_f, dtype=np.float64)
        lm = np.asarray(L_mm, dtype=np.float64)
        tm = np.asarray(t_mm, dtype=np.float64)
        shape = np.broadcast(Re, ef, lm, tm).shape
        Re_b = np.broadcast_to(Re, shape).ravel()
        ef_b = np.broadcast_to(ef, shape).ravel()
        lm_b = np.broadcast_to(lm, shape).ravel()
        tm_b = np.broadcast_to(tm, shape).ravel()
        log_Re = np.log10(np.maximum(Re_b, 1.0))
        X = np.column_stack([log_Re, ef_b, lm_b, tm_b])
        g = self._rbf(X)
        g = np.where(np.isfinite(g), g, 0.0)
        g = np.clip(g, -self._g_clamp, self._g_clamp)
        return g.reshape(shape)

    def summary(self):
        return dict(
            tpms=self.tpms,
            n_train=self._n_train,
            log_Re_range=self._log_Re_range,
            eps_f_range=self._eps_f_range,
            g_mean=float(self._g_in_sample.mean()),
            g_std=float(self._g_in_sample.std()),
            g_max_abs=float(np.max(np.abs(self._g_in_sample))),
            g_clamp=self._g_clamp,
        )


_CACHE: dict = {}


def get_nu_corrector(tpms: str) -> NuResidualCorrector:
    if tpms not in _CACHE:
        _CACHE[tpms] = NuResidualCorrector(tpms=tpms)
    return _CACHE[tpms]


def predict_nu_corrected(tpms_type, Re, eps_f, L_mm, D_h_mm,
                          t_mm) -> float:
    """Nu_pred · (1 + g) — residual-corrected Nu."""
    Nu_base = nu_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm)
    corr = get_nu_corrector(tpms_type)
    g = corr.correction(Re, eps_f, L_mm, t_mm)
    return float(Nu_base * (1.0 + g))


# ============================================================
# LOO test
# ============================================================

def loo_test(tpms: str = "Gyroid"):
    """Leave-one-geometry-out: refit RBF without held geometry, test on it."""
    from df_fit.fit_nu_single_stream import load_data
    d = load_data(tpms)
    geoms = sorted(set(zip(d['L'], d['t'])))
    err_baseline = []
    err_corrected = []
    for L_t, t_t in geoms:
        sel_test = (d['L'] == L_t) & (d['t'] == t_t)
        d_test = d[sel_test]
        d_train = d[~sel_test]
        if len(d_train) < 20 or len(d_test) == 0:
            continue
        # Build LOO corrector
        log_Re_tr = np.log10(d_train['Re_fit'].to_numpy())
        eps_f_tr = d_train['eps_f'].to_numpy()
        L_mm_tr = d_train['L_mm'].to_numpy()
        t_mm_tr = d_train['t'].to_numpy()
        D_h_mm_tr = d_train['D_h_mm'].to_numpy()
        Nu_pred_tr = np.array([
            nu_from_Re(tpms, r, ef, lm, dh)
            for r, ef, lm, dh in zip(d_train['Re_fit'], eps_f_tr,
                                       L_mm_tr, D_h_mm_tr)
        ])
        g_tr = (d_train['Nu'].to_numpy() - Nu_pred_tr) / Nu_pred_tr
        X_tr = np.column_stack([log_Re_tr, eps_f_tr, L_mm_tr, t_mm_tr])
        try:
            rbf = RBFInterpolator(X_tr, g_tr, kernel='thin_plate_spline',
                                    smoothing=_RBF_SMOOTHING)
        except Exception:
            continue
        # Test
        log_Re_te = np.log10(d_test['Re_fit'].to_numpy())
        eps_f_te = d_test['eps_f'].to_numpy()
        L_mm_te = d_test['L_mm'].to_numpy()
        t_mm_te = d_test['t'].to_numpy()
        D_h_mm_te = d_test['D_h_mm'].to_numpy()
        Nu_pred_te = np.array([
            nu_from_Re(tpms, r, ef, lm, dh)
            for r, ef, lm, dh in zip(d_test['Re_fit'], eps_f_te,
                                       L_mm_te, D_h_mm_te)
        ])
        Nu_actual = d_test['Nu'].to_numpy()
        # Baseline error
        err_b = (Nu_pred_te - Nu_actual) / Nu_actual
        err_baseline.extend(err_b.tolist())
        # Corrected error
        X_te = np.column_stack([log_Re_te, eps_f_te, L_mm_te, t_mm_te])
        g_te = rbf(X_te)
        g_te = np.clip(g_te, -_G_CLAMP, _G_CLAMP)
        Nu_corr_te = Nu_pred_te * (1.0 + g_te)
        err_c = (Nu_corr_te - Nu_actual) / Nu_actual
        err_corrected.extend(err_c.tolist())

    err_baseline = np.array(err_baseline)
    err_corrected = np.array(err_corrected)
    rmsre_b = float(np.sqrt(np.mean(err_baseline**2))*100)
    rmsre_c = float(np.sqrt(np.mean(err_corrected**2))*100)
    bias_b = float(np.mean(err_baseline)*100)
    bias_c = float(np.mean(err_corrected)*100)
    return dict(rmsre_baseline=rmsre_b, rmsre_corrected=rmsre_c,
                bias_baseline=bias_b, bias_corrected=bias_c,
                delta=rmsre_b - rmsre_c)


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("Nu Residual Correction — LOO comparison\n" + "=" * 60)
    for tpms in ('Diamond', 'Gyroid'):
        print(f"\n--- {tpms} ---")
        corr = NuResidualCorrector(tpms=tpms)
        s = corr.summary()
        for k, v in s.items():
            print(f"  {k}: {v}")
        loo = loo_test(tpms)
        print(f"\n  LOO comparison:")
        print(f"    baseline:  RMSRE {loo['rmsre_baseline']:.2f}%   bias {loo['bias_baseline']:+.2f}%")
        print(f"    corrected: RMSRE {loo['rmsre_corrected']:.2f}%   bias {loo['bias_corrected']:+.2f}%")
        print(f"    Δ:         {loo['delta']:+.2f}pp ({'improved' if loo['delta']>0 else 'regressed'})")


if __name__ == '__main__':
    main()
