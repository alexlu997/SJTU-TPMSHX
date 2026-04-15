"""
Step 5: runtime inference for the constant-coefficient joint-fit MLP ensemble.

Interface
---------
    predict_K_cF(tpms_type, L_mm, t_mm, eps_f) -> (K, c_F)
    predict_K_cF_vec(tpms_type, L_mm_arr, t_mm_arr, eps_f_arr)
                                                 -> (K_arr, c_F_arr)
    predict_dP(tpms_type, L_mm, t_mm, eps_f, u, rho, mu, L_channel_m)
                                                 -> dP [Pa]

K and c_F are constants per geometry (no Re dependence). The surrogate is a
3-input × 2-output MLP ensemble per TPMS type, trained in
``train_surrogate.py`` (ConstDF-v1).

Usage
-----
    >>> from thermoNas.df_fit.predict import predict_K_cF, predict_dP
    >>> K, cF = predict_K_cF('Diamond', 5.0, 0.4, 0.347)
    >>> dP = predict_dP('Diamond', L_mm=5.0, t_mm=0.4, eps_f=0.347,
    ...                  u=3.0, rho=1.2, mu=1.85e-5, L_channel_m=0.05)

Smoke test
----------
Re-predicts every training row's K, c_F (constant per geometry), then
computes the Darcy-Forchheimer ΔP and reports per-TPMS MAPE vs observed dP.
Integrity gate at 25 %.
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import torch

from .train_surrogate import CKPT_KIND, DFMLP, K_S_CELLS

_THIS = Path(__file__).resolve()
_PROJECT = _THIS.parent.parent.parent

MODEL_DIR = _PROJECT / "models"

# Integrity gate (file-health check only, not an accuracy claim).
TRAIN_DP_MAPE_CEIL = 25.0  # %


_CACHE: dict[str, dict] = {}


def _rebuild_models(ckpt: dict) -> list[DFMLP]:
    arch = ckpt["architecture"]
    models: list[DFMLP] = []
    for sd in ckpt["state_dicts"]:
        m = DFMLP(hidden=int(arch["hidden"]), dropout=float(arch["dropout"]))
        m.load_state_dict({k: torch.tensor(v) for k, v in sd.items()})
        m.eval()
        models.append(m)
    return models


def _load(tpms_type: str) -> dict:
    key = tpms_type
    if key in _CACHE:
        return _CACHE[key]

    path = MODEL_DIR / f"df_surrogate_{tpms_type.lower()}.joblib"
    if not path.exists():
        raise FileNotFoundError(
            f"Surrogate model not found: {path}\n"
            "Run `python -m thermoNas.df_fit.train_surrogate` first."
        )
    ckpt = joblib.load(path)
    if ckpt.get("kind") != CKPT_KIND:
        raise ValueError(
            f"Unexpected surrogate kind in {path}: {ckpt.get('kind')!r}. "
            f"Expected {CKPT_KIND!r}. Re-run train_surrogate.py to rebuild."
        )
    ckpt["_models"] = _rebuild_models(ckpt)
    _CACHE[key] = ckpt
    return ckpt


def _ensemble_log_outputs(ckpt: dict, z: np.ndarray
                           ) -> tuple[np.ndarray, np.ndarray]:
    """Run all ensemble members on (B, 3) standardised input and return
    un-normalised (log10 K, log10 c_F) averaged across members."""
    z_t = torch.tensor(z, dtype=torch.float32)
    n_batch = z.shape[0]
    log_K_accum = np.zeros(n_batch)
    log_cF_accum = np.zeros(n_batch)
    n = len(ckpt["_models"])
    for m in ckpt["_models"]:
        with torch.no_grad():
            out = m(z_t).numpy()
        log_K_accum += out[:, 0] * ckpt["y_log_std"][0] + ckpt["y_log_mean"][0]
        log_cF_accum += out[:, 1] * ckpt["y_log_std"][1] + ckpt["y_log_mean"][1]
    return log_K_accum / n, log_cF_accum / n


def predict_K_cF(tpms_type: str, L_mm: float, t_mm: float,
                  eps_f: float) -> tuple[float, float]:
    """Return ensemble-averaged (K [m²], c_F [1/m]) constants for this geometry."""
    ckpt = _load(tpms_type)
    x_log = np.log10(np.array([[L_mm, t_mm, eps_f]], dtype=np.float64))
    z = (x_log - ckpt["x_log_mean"]) / ckpt["x_log_std"]
    log_K, log_cF = _ensemble_log_outputs(ckpt, z)
    return float(10.0 ** log_K[0]), float(10.0 ** log_cF[0])


def predict_K_cF_vec(tpms_type: str, L_mm: np.ndarray, t_mm: np.ndarray,
                      eps_f: np.ndarray
                      ) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised variant for solver iteration over grid cells."""
    ckpt = _load(tpms_type)
    x_log = np.log10(
        np.column_stack([L_mm, t_mm, eps_f]).astype(np.float64)
    )
    z = (x_log - ckpt["x_log_mean"]) / ckpt["x_log_std"]
    log_K, log_cF = _ensemble_log_outputs(ckpt, z)
    return 10.0 ** log_K, 10.0 ** log_cF


def predict_dP(tpms_type: str, L_mm: float, t_mm: float, eps_f: float,
                u: float, rho: float, mu: float,
                L_channel_m: float) -> float:
    """Compute ΔP via the constant-coefficient Darcy-Forchheimer closure."""
    K, c_F = predict_K_cF(tpms_type, L_mm, t_mm, eps_f)
    return (mu * u / K + rho * c_F * u ** 2) * L_channel_m


def smoke_test() -> None:
    """Predict K, c_F on every training row, compute ΔP via D-F, and
    report per-TPMS MAPE against observed dP."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    from .load_data import load_all

    df = load_all()
    print(f"Smoke test on {len(df)} training rows")
    per_tpms_mape: dict[str, float] = {}
    for tpms, g in df.groupby("tpms"):
        L = g["L_mm"].to_numpy(dtype=float)
        t = g["t_mm"].to_numpy(dtype=float)
        eps_f = g["eps_f"].to_numpy(dtype=float)
        u = g["u_mps"].to_numpy(dtype=float)
        dP_obs = g["dP_Pa"].to_numpy(dtype=float)
        mu = g["mu"].to_numpy(dtype=float)
        rho = g["rho"].to_numpy(dtype=float)
        L_ch = K_S_CELLS * L * 1e-3

        K, cF = predict_K_cF_vec(str(tpms), L, t, eps_f)
        dP_pred = (mu * u / K + rho * cF * u ** 2) * L_ch
        rel = np.abs(dP_pred - dP_obs) / dP_obs
        mape = float(rel.mean() * 100.0)
        per_tpms_mape[str(tpms)] = mape
        print(f"  [{tpms}] n={len(g)}  ΔP MAPE = {mape:6.2f}%  "
              f"(max {rel.max()*100:.1f}%)")

    worst = max(per_tpms_mape.values())
    if worst >= TRAIN_DP_MAPE_CEIL:
        raise SystemExit(
            f"SMOKE TEST FAIL: training ΔP MAPE exceeds integrity ceiling "
            f"({worst:.2f}% > {TRAIN_DP_MAPE_CEIL}%). "
            "Model file may be corrupted — re-run train_surrogate."
        )
    print(f"\nSMOKE TEST PASS (worst {worst:.2f}% < {TRAIN_DP_MAPE_CEIL}%)")


if __name__ == "__main__":
    smoke_test()
