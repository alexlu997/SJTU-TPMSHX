"""GammaDF — multi-fidelity rough-wall D-F surrogate (opt-in, 2026-06-12).

    c_F,rough(tp, L, t) = c_F,smooth(tp, L, t) * gamma(tp, L, t)
    K               (tp, L, t) = SmoothDF pure D_h^2 trend  (SMOOTH-wall)

Multi-fidelity split: the smooth CFD surface (SmoothDF, 40 geometries,
water+air) supplies the geometric SHAPE; the experimental anchors (col47
convention, SLM-rough specimens) supply the roughness AMPLITUDE gamma.

gamma model (v4, see desktop doc 2026-06-12-gamma-multifidelity-df-CN.html
and research scripts temp_df_gamma_mf*.py):

  anchors   gamma = cF_exp(col47) / cF_smooth(Re_ref=2530), trusted layers
            L6 / L8 only (L4/L5 anchors physically falsified: raw col43
            itself shows rough <= smooth there).
  t-dir     ln gamma = a_layer + b_layer*(t-0.4) + c_shared*clip(t-0.4)^2.
            Shared curvature c only when both trusted layers' individual
            curvatures agree in sign (Diamond yes ~-3.5, Gyroid no -> 0).
            Curvature active only inside t in [0.3, 0.5]; linear
            continuation outside (guards the t=0.6 extrapolation).
  L-dir     Gyroid: log-quadratic through (L6, L7=Shanghai calibration
            534.8, L8).  Diamond: log-linear L6 -> L8 (no D L7 calibration;
            blind-validated on the excluded D_7_6 specimen: 454.2 vs ~454).
  L4/L5     flat6: gamma(L<=5, t) = max(1, gamma(L6, t)) — minimal
            continuation of the trusted L8->L6 rise; declared band
            [smooth, Colebrook] via `lowL_band`.  Floor max(1,.) applies
            ONLY here; the trusted region (L>=6) is anchor-faithful
            (gamma(G8) ~ 0.87-0.92 is the Re_ref-convention anchor value,
            NOT a physics violation — clamping it to 1 was the v3 bug).

Scoreboard (2026-06-12, temp_df_gamma_mf3.py):
  trusted LOO     Diamond RMSRE 2.5% (max 2.9) / Gyroid 2.6% (max 4.0)
  Shanghai gate   cF(G7/t0.6) = 534.8 — IDENTICAL to production by
                  construction (calibration point)
  D7 blind        454.2 vs bridged specimen reference ~454 (production
                  RBF extrapolates 745, end-to-end dP RMSRE 67.4%)

SEMANTICS / LIMITS
  c_F : ROUGH (col47 core-only convention, THIS SLM batch's roughness —
        re-calibrate gamma if the print process changes).
  K   : SMOOTH trend, no roughness correction (deliberate: K weakly
        identified + Forchheimer dominates the production window Re
        400-16k; Darcy-share cost ~1-6% there, grows below Re~400).
  Differs from the production RBF K everywhere (incl. the gate point) —
  only c_F is gate-identical.  Geometry domain: gamma evaluated with L
  clamped to [4, 8]; t handled by linear continuation outside [0.3, 0.5].
  Diamond / Gyroid only (no experimental anchors for other lattices).

NOT the production default.  Opt in per call (method="gamma_df"), or
globally via env TPMSHX_DF_METHOD=gamma_df.  Default switch requires the
Shanghai 3D gate re-run (K differs) + L4/L5 arbitration (rough-wall CFD
or boundary-coefficient re-derivation).
"""
from __future__ import annotations

import numpy as np

from .smooth_df import SmoothDF, _geom

RE_REF = 2530.0          # geometric mean of production window 400-16000
GATE_CF_G7 = 534.8       # production / Shanghai-3D-validated cF, Gyroid L7/t0.6
_TRUSTED_L = (6, 8)
_T_CENTER = 0.4
_T_HALF = 0.1            # curvature active for |t - 0.4| <= 0.1


class GammaDF:
    """Rough-wall (K, c_F) predictor; same interface as SurrogateV3."""

    def __init__(self, tpms: str = "Gyroid",
                 smooth: SmoothDF | None = None):
        if tpms not in ("Diamond", "Gyroid"):
            raise ValueError(f"GammaDF supports Diamond/Gyroid, got {tpms!r}")
        self.tpms = tpms
        self.sm = smooth if smooth is not None else SmoothDF()
        self.m_lat = float(self.sm._lat[tpms]["m"])

        # experimental anchors (col47 convention) from the production
        # calibration table — single source, no re-derivation here
        from .surrogate_v3 import SurrogateV3
        sv = SurrogateV3(tpms=tpms)
        self.anchors = {(round(float(g.L_mm)), round(float(g.t_mm), 1)):
                        float(g.c_F) for _, g in sv.ref.iterrows()}

        self._gamma_anch = {(L, t): cf / self.cf_smooth(L, t)
                            for (L, t), cf in self.anchors.items()
                            if L in _TRUSTED_L}
        if not self._gamma_anch:
            raise RuntimeError(f"no trusted (L6/L8) anchors for {tpms}")

        self.use_curvature = self._curvature_signs_agree()
        self._par, self._c = self._fit_tmodel()

        # Gyroid L7 Shanghai calibration (gate-point identity)
        self.gamma_g7 = (GATE_CF_G7 / self.cf_smooth(7.0, 0.6)
                         if tpms == "Gyroid" else None)

    # ---------------- smooth base ----------------
    def cf_smooth(self, L_mm: float, t_mm: float) -> float:
        """Smooth-wall c_F at the Re_ref convention point."""
        _, B = self.sm.predict_K_B(self.tpms, float(L_mm), float(t_mm))
        return B * (RE_REF / 1000.0) ** (-self.m_lat)

    # ---------------- t-model ----------------
    def _layer_pts(self, L: int):
        return sorted((t, np.log(g)) for (LL, t), g in
                      self._gamma_anch.items() if LL == L)

    def _curvature_signs_agree(self) -> bool:
        signs = []
        for L in _TRUSTED_L:
            pts = self._layer_pts(L)
            if len(pts) < 3:
                return False
            ts = np.array([p[0] for p in pts])
            ys = np.array([p[1] for p in pts])
            c = np.polyfit(ts - _T_CENTER, ys, 2)[0]
            signs.append(np.sign(c))
        return bool(signs[0] == signs[1] and signs[0] != 0)

    def _fit_tmodel(self):
        """LS fit ln g = a_L + b_L*x + c*x^2 (c shared, optional)."""
        rows, y = [], []
        layers = list(_TRUSTED_L)
        for li, L in enumerate(layers):
            for (t, lg) in self._layer_pts(L):
                x = t - _T_CENTER
                r = [0.0] * (2 * len(layers))
                r[2 * li], r[2 * li + 1] = 1.0, x
                if self.use_curvature:
                    r.append(x * x)
                rows.append(r); y.append(lg)
        coef, *_ = np.linalg.lstsq(np.array(rows), np.array(y), rcond=None)
        par = {L: (float(coef[2 * i]), float(coef[2 * i + 1]))
               for i, L in enumerate(layers)}
        c = float(coef[-1]) if self.use_curvature else 0.0
        return par, c

    def _ev(self, L_layer: int, t: float) -> float:
        """gamma on a trusted layer; curvature clipped to the data range."""
        a, b = self._par[L_layer]
        x = t - _T_CENTER
        xi = float(np.clip(x, -_T_HALF, _T_HALF))
        return float(np.exp(a + b * x + self._c * xi * xi))

    # ---------------- gamma ----------------
    def _gamma_trusted(self, L: float, t: float) -> float:
        g6, g8 = self._ev(6, t), self._ev(8, t)
        if self.tpms == "Gyroid":
            g7 = self.gamma_g7 * (self._ev(6, t) / self._ev(6, 0.6))
            coef = np.polyfit([6.0, 7.0, 8.0], np.log([g6, g7, g8]), 2)
            return float(np.exp(np.polyval(coef, L)))
        return float(np.exp(np.interp(L, [6.0, 8.0],
                                      [np.log(g6), np.log(g8)])))

    def _gamma_lowL(self, t: float) -> float:
        """flat6 point estimate with the extrapolation-region floor."""
        return max(1.0, self._ev(6, t))

    def gamma(self, L_mm: float, t_mm: float) -> float:
        L = float(np.clip(L_mm, 4.0, 8.0))
        t = float(t_mm)
        if L >= 6.0:
            return self._gamma_trusted(L, t)
        if L <= 5.0:
            return self._gamma_lowL(t)
        w = L - 5.0
        return (1.0 - w) * self._gamma_lowL(t) + w * self._gamma_trusted(6.0, t)

    def lowL_band(self, L_mm: float, t_mm: float) -> tuple[float, float]:
        """Declared gamma uncertainty band for L<=5: (1, Colebrook-extrap).

        Colebrook form gamma = c0/[log10(3.7 Dh/ks)]^2 fitted on the two
        trusted layers; unfittable for Gyroid (gamma(G8)<1) -> falls back
        to the flat6 value, i.e. band upper == point estimate.
        """
        t = float(t_mm)
        g6, g8 = self._ev(6, t), self._ev(8, t)
        lo = 1.0
        Dh6 = _geom(self.tpms, 6.0, t)[1]
        Dh8 = _geom(self.tpms, 8.0, t)[1]
        from scipy.optimize import brentq

        def eqs(ks):
            return (g6 * np.log10(3.7 * Dh6 / ks) ** 2
                    - g8 * np.log10(3.7 * Dh8 / ks) ** 2)
        try:
            ks = brentq(eqs, 1e-7, 2e-3)
            c0 = g6 * np.log10(3.7 * Dh6 / ks) ** 2
            Dh = _geom(self.tpms, float(np.clip(L_mm, 4.0, 8.0)), t)[1]
            hi = max(1.0, float(c0 / np.log10(3.7 * Dh / ks) ** 2))
        except ValueError:
            hi = self._gamma_lowL(t)
        return lo, hi

    # ---------------- public interface (SurrogateV3-compatible) ----------------
    def predict(self, L_mm: float, t_mm: float,
                eps_f: float | None = None) -> tuple[float, float]:
        """(K [m^2], c_F [1/m]).  eps_f accepted for interface
        compatibility; geometry is derived internally from (L, t)."""
        K, _ = self.sm.predict_K_B(self.tpms, float(L_mm), float(t_mm))
        cF = self.cf_smooth(L_mm, t_mm) * self.gamma(L_mm, t_mm)
        return float(K), float(cF)

    def summary(self) -> None:
        print(f"GammaDF[{self.tpms}]  m_lat={self.m_lat:.3f}  "
              f"shared_curvature={'%.2f' % self._c if self.use_curvature else 'off'}")
        for (L, t), g in sorted(self._gamma_anch.items()):
            print(f"  anchor {self.tpms[0]}_{L}_{t}: gamma={g:.3f} "
                  f"(fit {self._ev(L, t):.3f})")
        if self.gamma_g7 is not None:
            print(f"  G7 calibration gamma={self.gamma_g7:.3f} "
                  f"-> cF(7,0.6)={self.predict(7.0, 0.6)[1]:.1f}")
