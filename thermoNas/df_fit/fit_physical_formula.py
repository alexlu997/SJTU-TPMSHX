"""
Arm 2: Physical formula surrogates for (K, c_F).

2a  Power-law:   K = C_K * D_h^a * eps_f^b
                  c_F = C_F * D_h^c * eps_f^d
                  6 params, log-log OLS

2b  KC/Ergun:    K = eps_f^3 * D_h^2 / (C_K * (1-eps_f)^2)
                  c_F = C_F * (1-eps_f) / (eps_f^3 * D_h)
                  2 params, geometric-mean estimation
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_THERMONAS = _THIS.parent.parent
if str(_THERMONAS) not in sys.path:
    sys.path.insert(0, str(_THERMONAS))

from solvers.tpms_calc import geometry as tpms_geometry  # noqa: E402

from .eval_arms import (  # noqa: E402
    per_geom_reference, evaluate_arm, compare_arms, load_all,
    TrainPredictFn, PredictFn,
)

_KS = 16.0


# ==================================================================
# 2a: Power-law
# ==================================================================

class PowerLaw:
    """K = C_K * D_h^a * eps_f^b,  c_F = C_F * D_h^c * eps_f^d."""

    def __init__(self, tpms: str = "Gyroid"):
        self.tpms = tpms
        self.log_C_K = self.a = self.b = 0.0
        self.log_C_F = self.c = self.d = 0.0

    def fit(self, ref: pd.DataFrame) -> "PowerLaw":
        D_h = 2.0 * ref["r_h_m"].to_numpy(dtype=float)
        eps_f = ref["eps_f"].to_numpy(dtype=float)
        K = ref["K"].to_numpy(dtype=float)
        cF = ref["c_F"].to_numpy(dtype=float)

        # Design matrix: [1, log10(D_h), log10(eps_f)]
        X = np.column_stack([
            np.ones(len(D_h)), np.log10(D_h), np.log10(eps_f),
        ])

        coef_K, *_ = np.linalg.lstsq(X, np.log10(K), rcond=None)
        self.log_C_K, self.a, self.b = coef_K

        coef_cF, *_ = np.linalg.lstsq(X, np.log10(cF), rcond=None)
        self.log_C_F, self.c, self.d = coef_cF
        return self

    def predict(self, L_mm: float, t_mm: float, eps_f: float,
                ) -> tuple[float, float]:
        D_h = tpms_geometry(self.tpms, L_mm, t_mm, _KS)["D_h"]
        log_K = self.log_C_K + self.a * np.log10(D_h) + self.b * np.log10(eps_f)
        log_cF = self.log_C_F + self.c * np.log10(D_h) + self.d * np.log10(eps_f)
        return float(10.0 ** log_K), float(10.0 ** log_cF)

    def __repr__(self) -> str:
        return (f"PowerLaw(K = 10^{self.log_C_K:.3f} * D_h^{self.a:.3f} "
                f"* eps_f^{self.b:.3f},  "
                f"c_F = 10^{self.log_C_F:.3f} * D_h^{self.c:.3f} "
                f"* eps_f^{self.d:.3f})")


# ==================================================================
# 2b: KC / Ergun
# ==================================================================

class KCErgun:
    """K = eps_f^3 * D_h^2 / (C_K * (1-eps_f)^2),
       c_F = C_F * (1-eps_f) / (eps_f^3 * D_h)."""

    def __init__(self, tpms: str = "Gyroid"):
        self.tpms = tpms
        self.C_K = self.C_F = 1.0

    def fit(self, ref: pd.DataFrame) -> "KCErgun":
        D_h = 2.0 * ref["r_h_m"].to_numpy(dtype=float)
        eps_f = ref["eps_f"].to_numpy(dtype=float)
        K = ref["K"].to_numpy(dtype=float)
        cF = ref["c_F"].to_numpy(dtype=float)

        # Invert formula per geometry, aggregate via geometric mean
        C_K_each = eps_f ** 3 * D_h ** 2 / (K * (1 - eps_f) ** 2)
        self.C_K = float(np.exp(np.mean(np.log(C_K_each))))

        C_F_each = cF * eps_f ** 3 * D_h / (1 - eps_f)
        self.C_F = float(np.exp(np.mean(np.log(C_F_each))))
        return self

    def predict(self, L_mm: float, t_mm: float, eps_f: float,
                ) -> tuple[float, float]:
        D_h = tpms_geometry(self.tpms, L_mm, t_mm, _KS)["D_h"]
        K = eps_f ** 3 * D_h ** 2 / (self.C_K * (1 - eps_f) ** 2)
        cF = self.C_F * (1 - eps_f) / (eps_f ** 3 * D_h)
        return float(K), float(cF)

    def __repr__(self) -> str:
        return f"KCErgun(C_K={self.C_K:.4g}, C_F={self.C_F:.4g})"


# ==================================================================
# eval_arms-compatible callables
# ==================================================================

def make_arm2a(df_all: pd.DataFrame | None = None,
               tpms: str = "Gyroid",
               ) -> tuple[TrainPredictFn, PredictFn]:
    """Arm 2a power-law.  Fits full model, returns LOO and predict callables."""
    if df_all is None:
        df_all = load_all()
    ref_full = per_geom_reference(
        df_all[df_all["tpms"] == tpms].reset_index(drop=True))
    full_model = PowerLaw(tpms).fit(ref_full)
    print(f"  [Arm 2a] {full_model}")

    def train_predict(train_df: pd.DataFrame,
                      L_mm: float, t_mm: float, eps_f: float,
                      ) -> tuple[float, float]:
        ref = per_geom_reference(train_df)
        return PowerLaw(tpms).fit(ref).predict(L_mm, t_mm, eps_f)

    return train_predict, full_model.predict


def make_arm2b(df_all: pd.DataFrame | None = None,
               tpms: str = "Gyroid",
               ) -> tuple[TrainPredictFn, PredictFn]:
    """Arm 2b KC/Ergun.  Fits full model, returns LOO and predict callables."""
    if df_all is None:
        df_all = load_all()
    ref_full = per_geom_reference(
        df_all[df_all["tpms"] == tpms].reset_index(drop=True))
    full_model = KCErgun(tpms).fit(ref_full)
    print(f"  [Arm 2b] {full_model}")

    def train_predict(train_df: pd.DataFrame,
                      L_mm: float, t_mm: float, eps_f: float,
                      ) -> tuple[float, float]:
        ref = per_geom_reference(train_df)
        return KCErgun(tpms).fit(ref).predict(L_mm, t_mm, eps_f)

    return train_predict, full_model.predict


# ==================================================================
# CLI
# ==================================================================

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    warnings.filterwarnings("ignore")

    skip_sh = "--skip-shanghai" in sys.argv
    df_all = load_all()

    tp_2a, pred_2a = make_arm2a(df_all)
    tp_2b, pred_2b = make_arm2b(df_all)

    r2a = evaluate_arm("Arm 2a: Power-law", tp_2a, pred_2a,
                       df_all=df_all, skip_shanghai=skip_sh)
    r2b = evaluate_arm("Arm 2b: KC/Ergun", tp_2b, pred_2b,
                       df_all=df_all, skip_shanghai=skip_sh)
    compare_arms([r2a, r2b])


if __name__ == "__main__":
    main()
