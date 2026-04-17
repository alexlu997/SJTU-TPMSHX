"""
Arm 1: Feature engineering variants for ConstDF MLP.

1a  (D_h, t/L, eps_f)         — D_h replaces L
1b  (D_h, t/L, (1-eps)/eps)   — solid/void ratio replaces eps_f
1c  (D_h, t, L, eps_f)        — D_h as 4th input

All use log10 space.  Same MLP architecture as ConstDF-v1 (hidden=32,
5x ensemble).  Only the input feature vector changes.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.optim import Adam

_THIS = Path(__file__).resolve()
_THERMONAS = _THIS.parent.parent
if str(_THERMONAS) not in sys.path:
    sys.path.insert(0, str(_THERMONAS))

from solvers.tpms_calc import geometry as tpms_geometry  # noqa: E402

from .fit_df_per_geom import K_S_CELLS  # noqa: E402
from .eval_arms import (  # noqa: E402
    per_geom_reference, evaluate_arm, compare_arms, load_all,
    TrainPredictFn, PredictFn,
)

# Reuse training hyper-params from v1
from .train_surrogate import (  # noqa: E402
    HIDDEN, DROPOUT, LR, WEIGHT_DECAY, EPOCHS, PATIENCE,
    GRAD_CLIP, SEED, N_ENSEMBLE,
)

_KS = 16.0

# ==================================================================
# Feature configurations
# ==================================================================

CONFIGS: dict[str, dict] = {
    "1a": dict(name="Arm 1a: (D_h, t/L, eps_f)",
               cols=["D_h", "t_over_L", "eps_f"], dim=3),
    "1b": dict(name="Arm 1b: (D_h, t/L, solid_void)",
               cols=["D_h", "t_over_L", "solid_void"], dim=3),
    "1c": dict(name="Arm 1c: (D_h, t, L, eps_f)",
               cols=["D_h", "t_mm", "L_mm", "eps_f"], dim=4),
}


def _feat_df(df: pd.DataFrame, cfg: dict) -> np.ndarray:
    """Compute feature matrix from a DataFrame that has r_h_m, eps_f, etc."""
    cols = []
    for c in cfg["cols"]:
        if c == "D_h":
            cols.append(2.0 * df["r_h_m"].to_numpy(dtype=float))
        elif c == "t_over_L":
            cols.append(df["t_mm"].to_numpy(dtype=float)
                        / df["L_mm"].to_numpy(dtype=float))
        elif c == "solid_void":
            eps = 2.0 * df["eps_f"].to_numpy(dtype=float)
            cols.append((1.0 - eps) / eps)
        else:
            cols.append(df[c].to_numpy(dtype=float))
    return np.column_stack(cols)


def _feat_point(L_mm: float, t_mm: float, eps_f: float,
                tpms: str, cfg: dict) -> np.ndarray:
    """Feature vector for a single (L, t, eps_f) query."""
    D_h = tpms_geometry(tpms, L_mm, t_mm, _KS)["D_h"]
    eps = 2.0 * eps_f
    m = {"D_h": D_h, "t_over_L": t_mm / L_mm, "eps_f": eps_f,
         "solid_void": (1.0 - eps) / eps, "t_mm": t_mm, "L_mm": L_mm}
    return np.array([m[c] for c in cfg["cols"]], dtype=float)


# ==================================================================
# Flexible MLP (same architecture, variable input dim)
# ==================================================================

class FlexMLP(nn.Module):
    def __init__(self, input_dim: int = 3, hidden: int = HIDDEN,
                 dropout: float = DROPOUT):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden), nn.SiLU(), nn.Dropout(dropout),
            nn.Linear(hidden, hidden),    nn.SiLU(), nn.Dropout(dropout),
            nn.Linear(hidden, 2),
        )

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        return self.net(z)


# ==================================================================
# Training helpers
# ==================================================================

def _norm_flex(ref: pd.DataFrame, cfg: dict) -> dict:
    X_log = np.log10(_feat_df(ref, cfg))
    Y_log = np.column_stack([np.log10(ref["K"].to_numpy(dtype=float)),
                              np.log10(ref["c_F"].to_numpy(dtype=float))])
    x_m, x_s = X_log.mean(0), X_log.std(0)
    y_m, y_s = Y_log.mean(0), Y_log.std(0)
    x_s[x_s < 1e-9] = 1.0
    y_s[y_s < 1e-9] = 1.0
    return dict(x_log_mean=x_m, x_log_std=x_s,
                y_log_mean=y_m, y_log_std=y_s)


def _tensors_flex(rows: pd.DataFrame, norm: dict, cfg: dict) -> dict:
    X = _feat_df(rows, cfg)
    z = (np.log10(X) - norm["x_log_mean"]) / norm["x_log_std"]
    L = rows["L_mm"].to_numpy(dtype=float)
    return dict(
        z=torch.tensor(z, dtype=torch.float32),
        u=torch.tensor(rows["u_mps"].to_numpy(dtype=float), dtype=torch.float32),
        dP=torch.tensor(rows["dP_Pa"].to_numpy(dtype=float), dtype=torch.float32),
        mu=torch.tensor(rows["mu"].to_numpy(dtype=float), dtype=torch.float32),
        rho=torch.tensor(rows["rho"].to_numpy(dtype=float), dtype=torch.float32),
        L_ch=torch.tensor(K_S_CELLS * L * 1e-3, dtype=torch.float32),
    )


def _forward(model, z, ym, ys):
    out = model(z)
    log_K = torch.clamp(out[:, 0] * ys[0] + ym[0], -16.0, -4.0)
    log_cF = torch.clamp(out[:, 1] * ys[1] + ym[1], -2.0, 6.0)
    return torch.pow(10.0, log_K), torch.pow(10.0, log_cF)


def _train_one(rows: pd.DataFrame, norm: dict, cfg: dict,
               seed: int = SEED) -> FlexMLP:
    torch.manual_seed(seed)
    np.random.seed(seed)
    data = _tensors_flex(rows, norm, cfg)
    ym = torch.tensor(norm["y_log_mean"], dtype=torch.float32)
    ys = torch.tensor(norm["y_log_std"], dtype=torch.float32)

    model = FlexMLP(input_dim=cfg["dim"])
    opt = Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(
        opt, "min", factor=0.5, patience=PATIENCE // 4, min_lr=1e-6)

    best_loss, best_sd, wait = float("inf"), None, 0
    for ep in range(EPOCHS):
        model.train()
        opt.zero_grad()
        K, cF = _forward(model, data["z"], ym, ys)
        dP_p = (data["mu"] * data["u"] / K
                + data["rho"] * cF * data["u"] ** 2) * data["L_ch"]
        loss = torch.mean(((dP_p - data["dP"]) / data["dP"]) ** 2)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP)
        opt.step()
        lv = float(loss.item())
        sched.step(lv)
        if lv < best_loss - 1e-8:
            best_loss = lv
            best_sd = {k: v.clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= PATIENCE:
                break
    if best_sd is not None:
        model.load_state_dict(best_sd)
    model.eval()
    return model


def _train_ensemble(rows, norm, cfg, base_seed=SEED):
    return [_train_one(rows, norm, cfg, seed=base_seed + k * 101)
            for k in range(N_ENSEMBLE)]


def _predict_ensemble(models, norm, cfg, L_mm, t_mm, eps_f, tpms="Gyroid"):
    x = _feat_point(L_mm, t_mm, eps_f, tpms, cfg)
    z = (np.log10(x) - norm["x_log_mean"]) / norm["x_log_std"]
    z_t = torch.tensor(z[None, :], dtype=torch.float32)
    log_K = log_cF = 0.0
    for m in models:
        with torch.no_grad():
            out = m(z_t).numpy()[0]
        log_K += out[0] * norm["y_log_std"][0] + norm["y_log_mean"][0]
        log_cF += out[1] * norm["y_log_std"][1] + norm["y_log_mean"][1]
    log_K /= len(models)
    log_cF /= len(models)
    return float(10.0 ** log_K), float(10.0 ** log_cF)


# ==================================================================
# eval_arms-compatible callables
# ==================================================================

def make_arm1(variant: str, df_all: pd.DataFrame | None = None,
              tpms: str = "Gyroid") -> tuple[TrainPredictFn, PredictFn]:
    """Return (train_predict_fn, predict_fn) for a given Arm-1 variant."""
    cfg = CONFIGS[variant]
    if df_all is None:
        df_all = load_all()
    sub = df_all[df_all["tpms"] == tpms].reset_index(drop=True)

    # Full-data model
    ref_full = per_geom_reference(sub)
    norm_full = _norm_flex(ref_full, cfg)
    models_full = _train_ensemble(sub, norm_full, cfg, base_seed=SEED)
    print(f"  [{cfg['name']}] full-model trained, "
          f"dim={cfg['dim']}, features={cfg['cols']}")

    def train_predict(train_df: pd.DataFrame,
                      L_mm: float, t_mm: float, eps_f: float,
                      ) -> tuple[float, float]:
        ref = per_geom_reference(train_df)
        norm = _norm_flex(ref, cfg)
        models = _train_ensemble(train_df, norm, cfg, base_seed=SEED)
        return _predict_ensemble(models, norm, cfg, L_mm, t_mm, eps_f, tpms)

    def predict(L_mm: float, t_mm: float, eps_f: float,
                ) -> tuple[float, float]:
        return _predict_ensemble(
            models_full, norm_full, cfg, L_mm, t_mm, eps_f, tpms)

    return train_predict, predict


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

    results = []
    for var in ("1a", "1b", "1c"):
        tp, pred = make_arm1(var, df_all)
        r = evaluate_arm(CONFIGS[var]["name"], tp, pred,
                         df_all=df_all, skip_shanghai=skip_sh)
        results.append(r)

    compare_arms(results)


if __name__ == "__main__":
    main()
