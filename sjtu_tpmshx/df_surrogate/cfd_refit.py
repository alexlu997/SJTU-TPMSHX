"""cfd_refit — Darcy–Forchheimer backend with a CFD-refit permeability K.

Motivation (2026-06-30): `smooth_df`/`gamma_df` force K onto a single-parameter
`Dh²` trend (`logK = 2·logDh + b0K`, ~53 % RMSRE vs per-geometry CFD). That is
invisible in the air production window (Re 400–16k, Darcy share 1–6 %) but
under-predicts the low-Re **water** Δp (Re 100–1100, Darcy share 9–28 %). A fresh
re-extraction from the raw water CFD (`water-cfd-raw.xlsx`, 40 geometries) with a
**2-stage decoupled** fit — c_F from the high-Re Forchheimer plateau, then K from
the low-Re Darcy region holding c_F fixed — collapses the K/Dh² scatter from 24.7×
to 1.3–1.6× and interpolates (log-space thin-plate spline over (log L, log t)) at
K LOO RMSRE ≈ 6 % (Gyroid) / 20 % (Diamond).

This backend keeps **`c_F` from `gamma_df`** (the Shanghai-3D-calibrated value —
the headline depends on it) and replaces **only K** with the clean CFD surface.
Shanghai is preserved by construction (c_F identical, K is a 1–6 % Darcy
correction there); the low-Re water-side Δp improves. The full smooth-CFD c_F
surface (cF LOO 5–14 %) is validated separately but NOT used here, because the
Shanghai headline requires the roughness-calibrated c_F (registration contract:
a backend must reproduce the Shanghai 3D gate — training-domain LOO is not
sufficient). See openspec/changes/df-coeffs-cfd-refit.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

_PREBUILT = Path(__file__).resolve().parent / "_prebuilt" / "df_cfd_refit_coeffs.csv"


class CFDRefitModel:
    """(L_mm, t_mm, eps_f) → (K [m²], c_F [1/m]); K from the CFD surface,
    c_F delegated to GammaDF (Shanghai-calibrated)."""

    def __init__(self, tpms: str):
        from scipy.interpolate import RBFInterpolator
        from .gamma_df import GammaDF
        self.tpms = tpms
        self._gamma = GammaDF(tpms=tpms)          # c_F source (gate-calibrated)
        rows = [r.split(",") for r in
                _PREBUILT.read_text().strip().splitlines()[1:]]
        pts, logK = [], []
        for tp, L, t, K, cF, eps, Dh in rows:
            if tp != tpms:
                continue
            pts.append([np.log(float(L)), np.log(float(t))])
            logK.append(np.log(float(K)))
        self._logK = RBFInterpolator(np.array(pts), np.array(logK),
                                     kernel="thin_plate_spline")

    def _K(self, L_mm: float, t_mm: float) -> float:
        x = np.array([[np.log(float(L_mm)), np.log(float(t_mm))]])
        return float(np.exp(self._logK(x)[0]))

    def predict(self, L_mm: float, t_mm: float,
                eps_f: float | None = None) -> tuple[float, float]:
        _, cF = self._gamma.predict(L_mm, t_mm, eps_f)
        return self._K(L_mm, t_mm), float(cF)

    # diagnostics passthrough mirrors GammaDF where useful
    def summary(self) -> None:
        print(f"CFDRefit[{self.tpms}]  K=CFD-surface(TPS, log-space)  "
              f"c_F=gamma_df(gate-calibrated)")


from .backend import DFBackend, register  # noqa: E402  (backend is import-safe)


@register("cfd_refit")
class CFDRefitBackend(DFBackend):
    def _build(self, tpms_type):
        return CFDRefitModel(tpms_type)
