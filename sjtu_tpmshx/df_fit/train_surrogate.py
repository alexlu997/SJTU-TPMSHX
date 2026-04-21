"""
Step 4: joint-fit MLP ensemble with constant-coefficient Darcy-Forchheimer
closure (ConstDF-v1).

    surrogate : (L_mm, t_mm, ε_f) → (K, c_F)

K and c_F are geometry-level constants (no Re dependence). The per-row
ΔP loss uses the 2-term Darcy-Forchheimer form with those constants:

    ΔP_pred,i = ( μ_i·u_i / K(L, t, ε_f)
                 + ρ_i · c_F(L, t, ε_f) · u_i² ) · L_ch

Rationale
---------
Per-geometry 2-parameter WLS already passes Re-independence diagnostics on
all 24 geometries (see ``reports/constdf-v1/2026-04-14-DF-re-independence-report.md``).
An MLP jointly fitting (K, c_F)(L, t, ε_f) improves on the Piedra 1-D
power-law baseline by learning the L- and t-trend across geometries while
keeping the solver-side closure simple: one query per cell, no Re callback.

Architecture
------------
    z  = standardise( log10(L, t, ε_f) )              shape (B, 3)
    h1 = SiLU( Linear(3, 32)(z) ),   Dropout(0.05)
    h2 = SiLU( Linear(32, 32)(h1) ), Dropout(0.05)
    y  = Linear(32, 2)(h2)                            shape (B, 2)
    log10 K   = y[·,0] · y_std[0] + y_mean[0]
    log10 c_F = y[·,1] · y_std[1] + y_mean[1]

~1250 parameters per MLP member. 5× ensemble per TPMS.

Normalisation
-------------
Both x_log and y_log statistics come from the per-geometry 2-param WLS
reference table (one row per unique (L, t)), so the input scaling matches
the geometry sampling and the last-layer bias initialises in the right
physical range.

Loss and training
-----------------
Mean squared relative ΔP residual across all training rows. Adam
(lr=1e-3, weight_decay=3e-4), ReduceLROnPlateau, gradient clip 1.0,
early-stopping on training loss plateau.

LOO
---
Leave-one-geometry-out. For each fold, train an ensemble on the remaining
11 geometries, then predict the held-out (L, t)'s single (K, c_F) and use
it to compute ΔP on every held-out row. ΔP MAPE on held-out rows is the
headline metric.
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.optim import Adam

from .fit_df_per_geom import K_S_CELLS, _nnls_momentum, _wls_momentum
from .load_data import load_all

_THIS = Path(__file__).resolve()
_PROJECT = _THIS.parent.parent.parent

MODEL_DIR = _PROJECT / "models"
REPORT_MD = _PROJECT / "reports" / "constdf-v1" / "2026-04-14-DF-surrogate-loo-report.md"
FIG_DIR = _PROJECT / "reports" / "figs" / "df_fit"

FEATURES = ["L_mm", "t_mm", "eps_f"]
INPUT_DIM = 3

# Architecture
HIDDEN = 32
DROPOUT = 0.05

# Training
LR = 1e-3
WEIGHT_DECAY = 3e-4
EPOCHS = 8000
PATIENCE = 800
GRAD_CLIP = 1.0
SEED = 20260414

# Ensemble
N_ENSEMBLE = 5

CKPT_KIND = "joint_mlp_ensemble"


# ===================================================================
# Model
# ===================================================================

class DFMLP(nn.Module):
    """MLP that outputs (standardised log10 K, standardised log10 c_F)
    from 3-dim input (L_mm, t_mm, ε_f)."""

    def __init__(self, hidden: int = HIDDEN, dropout: float = DROPOUT):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(INPUT_DIM, hidden),
            nn.SiLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden),
            nn.SiLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, 2),
        )

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        return self.net(z)


# ===================================================================
# Normalisation helpers
# ===================================================================

def _per_geom_reference(rows_df: pd.DataFrame) -> pd.DataFrame:
    """Per-geometry 2-param WLS (K, c_F). Used for normalisation anchoring."""
    recs: list[dict] = []
    for (tpms, L, t), g in rows_df.groupby(["tpms", "L_mm", "t_mm"]):
        u = g["u_mps"].to_numpy(dtype=float)
        dP = g["dP_Pa"].to_numpy(dtype=float)
        mu = g["mu"].to_numpy(dtype=float)
        rho = g["rho"].to_numpy(dtype=float)
        L_ch = K_S_CELLS * float(L) * 1e-3
        inv_K, cF = _wls_momentum(u, dP, mu, rho, L_ch)
        if inv_K < 0.0 or cF < 0.0:
            inv_K, cF = _nnls_momentum(u, dP, mu, rho, L_ch)
        K = 1.0 / max(inv_K, 1e-30)
        recs.append({
            "tpms": tpms, "L_mm": float(L), "t_mm": float(t),
            "eps_f": float(g["eps_f"].iloc[0]),
            "K": K, "c_F": cF,
        })
    return pd.DataFrame(recs)


def _norm_from_ref(ref: pd.DataFrame) -> dict:
    """Compute (x_log, y_log) stats from the per-geometry reference table."""
    X_log = np.log10(ref[FEATURES].to_numpy(dtype=float))
    x_mean = X_log.mean(axis=0)
    x_std = X_log.std(axis=0)
    x_std[x_std < 1e-9] = 1.0

    Y_log = np.column_stack([
        np.log10(ref["K"].to_numpy(dtype=float)),
        np.log10(ref["c_F"].to_numpy(dtype=float)),
    ])
    y_mean = Y_log.mean(axis=0)
    y_std = Y_log.std(axis=0)
    y_std[y_std < 1e-9] = 1.0

    return {
        "x_log_mean": x_mean,
        "x_log_std": x_std,
        "y_log_mean": y_mean,
        "y_log_std": y_std,
    }


# ===================================================================
# Training loop
# ===================================================================

def _rows_to_tensors(rows: pd.DataFrame, norm: dict):
    L = rows["L_mm"].to_numpy(dtype=float)
    t = rows["t_mm"].to_numpy(dtype=float)
    eps_f = rows["eps_f"].to_numpy(dtype=float)
    u = rows["u_mps"].to_numpy(dtype=float)
    dP = rows["dP_Pa"].to_numpy(dtype=float)
    mu = rows["mu"].to_numpy(dtype=float)
    rho = rows["rho"].to_numpy(dtype=float)
    L_ch = K_S_CELLS * L * 1e-3

    x_log = np.log10(np.column_stack([L, t, eps_f]))
    z = (x_log - norm["x_log_mean"]) / norm["x_log_std"]

    return {
        "z": torch.tensor(z, dtype=torch.float32),
        "u": torch.tensor(u, dtype=torch.float32),
        "dP": torch.tensor(dP, dtype=torch.float32),
        "mu": torch.tensor(mu, dtype=torch.float32),
        "rho": torch.tensor(rho, dtype=torch.float32),
        "L_ch": torch.tensor(L_ch, dtype=torch.float32),
    }


def _forward_K_cF(model: DFMLP, z: torch.Tensor,
                    y_mean: torch.Tensor, y_std: torch.Tensor
                    ) -> tuple[torch.Tensor, torch.Tensor]:
    out = model(z)
    log_K = out[:, 0] * y_std[0] + y_mean[0]
    log_cF = out[:, 1] * y_std[1] + y_mean[1]
    # Clamp extremes to keep 10^x stable during early epochs
    log_K = torch.clamp(log_K, -16.0, -4.0)
    log_cF = torch.clamp(log_cF, -2.0, 6.0)
    K = torch.pow(10.0, log_K)
    cF = torch.pow(10.0, log_cF)
    return K, cF


def _train(rows: pd.DataFrame, norm: dict, seed: int = SEED
            ) -> tuple[DFMLP, list[float]]:
    torch.manual_seed(seed)
    np.random.seed(seed)

    data = _rows_to_tensors(rows, norm)
    y_mean_t = torch.tensor(norm["y_log_mean"], dtype=torch.float32)
    y_std_t = torch.tensor(norm["y_log_std"], dtype=torch.float32)

    model = DFMLP()
    opt = Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        opt, mode="min", factor=0.5, patience=PATIENCE // 4, min_lr=1e-6,
    )

    best_loss = float("inf")
    best_state = None
    patience = 0
    losses: list[float] = []

    for epoch in range(EPOCHS):
        model.train()
        opt.zero_grad()
        K, cF = _forward_K_cF(model, data["z"], y_mean_t, y_std_t)
        dP_pred = (data["mu"] * data["u"] / K + data["rho"] * cF * data["u"] ** 2) * data["L_ch"]
        rel = (dP_pred - data["dP"]) / data["dP"]
        loss = torch.mean(rel ** 2)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP)
        opt.step()

        loss_val = float(loss.item())
        losses.append(loss_val)
        scheduler.step(loss_val)
        if loss_val < best_loss - 1e-8:
            best_loss = loss_val
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            patience = 0
        else:
            patience += 1
            if patience >= PATIENCE:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    return model, losses


# ===================================================================
# Ensemble training + prediction
# ===================================================================

def _train_ensemble(rows: pd.DataFrame, norm: dict, base_seed: int = SEED
                     ) -> tuple[list[DFMLP], list[list[float]]]:
    models: list[DFMLP] = []
    curves: list[list[float]] = []
    for k in range(N_ENSEMBLE):
        m, c = _train(rows, norm, seed=base_seed + k * 101)
        models.append(m)
        curves.append(c)
    return models, curves


def _predict_KcF_vec(models: list[DFMLP], norm: dict,
                      L_mm: np.ndarray, t_mm: np.ndarray,
                      eps_f: np.ndarray
                      ) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised ensemble prediction over aligned arrays. Returns (K, c_F)."""
    x_log = np.log10(np.column_stack([L_mm, t_mm, eps_f]))
    z = (x_log - norm["x_log_mean"]) / norm["x_log_std"]
    z_t = torch.tensor(z, dtype=torch.float32)
    log_K_accum = np.zeros(len(L_mm))
    log_cF_accum = np.zeros(len(L_mm))
    for m in models:
        m.eval()
        with torch.no_grad():
            out = m(z_t).numpy()
        log_K_accum += out[:, 0] * norm["y_log_std"][0] + norm["y_log_mean"][0]
        log_cF_accum += out[:, 1] * norm["y_log_std"][1] + norm["y_log_mean"][1]
    log_K_accum /= len(models)
    log_cF_accum /= len(models)
    return 10.0 ** log_K_accum, 10.0 ** log_cF_accum


# ===================================================================
# Per-TPMS training + LOO
# ===================================================================

def train_and_loo(df_all: pd.DataFrame, tpms: str
                    ) -> tuple[dict, pd.DataFrame, list[float]]:
    sub = df_all[df_all["tpms"] == tpms].reset_index(drop=True)
    ref = _per_geom_reference(sub).sort_values(["L_mm", "t_mm"]).reset_index(drop=True)
    n_rows = len(sub)
    n_geoms = len(ref)
    n_params = sum(p.numel() for p in DFMLP().parameters())
    print(f"  [{tpms}] rows={n_rows}  geoms={n_geoms}  params={n_params} "
          f"× ensemble={N_ENSEMBLE}")

    # ── Full-data ensemble ──
    norm = _norm_from_ref(ref)
    full_models, loss_curves = _train_ensemble(sub, norm, base_seed=SEED)
    loss_curve = loss_curves[0]

    # Full-data training ΔP MAPE (ensemble-averaged per-row K, c_F)
    L_arr = sub["L_mm"].to_numpy(dtype=float)
    t_arr = sub["t_mm"].to_numpy(dtype=float)
    eps_f_arr = sub["eps_f"].to_numpy(dtype=float)
    u_arr = sub["u_mps"].to_numpy(dtype=float)
    dP_arr = sub["dP_Pa"].to_numpy(dtype=float)
    mu_arr = sub["mu"].to_numpy(dtype=float)
    rho_arr = sub["rho"].to_numpy(dtype=float)
    L_ch_arr = K_S_CELLS * L_arr * 1e-3
    K_e, cF_e = _predict_KcF_vec(full_models, norm, L_arr, t_arr, eps_f_arr)
    dP_pred_full = (mu_arr * u_arr / K_e + rho_arr * cF_e * u_arr ** 2) * L_ch_arr
    train_mape = float(np.mean(np.abs(dP_pred_full - dP_arr) / dP_arr) * 100.0)
    print(f"  [{tpms}] full-train ΔP MAPE (ensemble-avg): {train_mape:.2f}%")

    ckpt = {
        "kind": CKPT_KIND,
        "tpms_type": tpms,
        "feature_names": list(FEATURES),
        "x_log_mean": norm["x_log_mean"].astype(np.float64),
        "x_log_std": norm["x_log_std"].astype(np.float64),
        "y_log_mean": norm["y_log_mean"].astype(np.float64),
        "y_log_std": norm["y_log_std"].astype(np.float64),
        "state_dicts": [
            {k: v.cpu().numpy() for k, v in m.state_dict().items()}
            for m in full_models
        ],
        "n_ensemble": N_ENSEMBLE,
        "architecture": {"hidden": HIDDEN, "dropout": DROPOUT, "activation": "SiLU"},
        "K_S_CELLS": K_S_CELLS,
        "train_dP_MAPE": train_mape,
    }

    # ── Leave-one-geometry-out ──
    rows: list[dict] = []
    for i, r in ref.iterrows():
        L_out = float(r["L_mm"])
        t_out = float(r["t_mm"])
        eps_f_out = float(r["eps_f"])

        mask_out = (sub["L_mm"] == L_out) & (sub["t_mm"] == t_out)
        train_rows = sub[~mask_out].reset_index(drop=True)
        test_rows = sub[mask_out].reset_index(drop=True)

        train_ref = ref[~((ref["L_mm"] == L_out) & (ref["t_mm"] == t_out))].reset_index(drop=True)
        norm_i = _norm_from_ref(train_ref)
        models_i, _ = _train_ensemble(train_rows, norm_i, base_seed=SEED + i * 7)

        # Single (K, c_F) for the held-out geometry
        K_arr, cF_arr = _predict_KcF_vec(
            models_i, norm_i,
            np.array([L_out]), np.array([t_out]), np.array([eps_f_out]),
        )
        K_pred = float(K_arr[0])
        cF_pred = float(cF_arr[0])

        # Per-row ΔP on held-out rows using the single constant pair
        u = test_rows["u_mps"].to_numpy(dtype=float)
        dP_obs = test_rows["dP_Pa"].to_numpy(dtype=float)
        mu = test_rows["mu"].to_numpy(dtype=float)
        rho = test_rows["rho"].to_numpy(dtype=float)
        L_ch = K_S_CELLS * L_out * 1e-3
        dP_pred = (mu * u / K_pred + rho * cF_pred * u ** 2) * L_ch
        rel = np.abs(dP_pred - dP_obs) / dP_obs
        dP_mape = float(rel.mean() * 100.0)
        dP_max = float(rel.max() * 100.0)

        K_ref = float(r["K"])
        cF_ref = float(r["c_F"])

        rows.append({
            "tpms": tpms,
            "L_mm": L_out,
            "t_mm": t_out,
            "n_test_rows": int(len(test_rows)),
            "K_ref_2p": K_ref,
            "K_pred": K_pred,
            "cF_ref_2p": cF_ref,
            "cF_pred": cF_pred,
            "dP_MAPE": dP_mape,
            "dP_max_err": dP_max,
        })

    loo = pd.DataFrame(rows)
    return ckpt, loo, loss_curve


# ===================================================================
# Reporting
# ===================================================================

def _plot_loss(curves: dict[str, list[float]], out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 4), dpi=120)
    for name, c in curves.items():
        ax.plot(c, label=name, lw=1.2)
    ax.set_xlabel("epoch")
    ax.set_ylabel("mean squared relative ΔP residual")
    ax.set_yscale("log")
    ax.set_title("joint-fit ConstDF-v1 training curves (first ensemble member)")
    ax.grid(True, ls=":", alpha=0.5)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def _plot_loo(loo: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=120)
    labels = [f"{r.tpms[0]}{int(r.L_mm)}/{r.t_mm:.1f}" for r in loo.itertuples()]
    colors = ["tab:blue" if r.tpms == "Diamond" else "tab:orange" for r in loo.itertuples()]
    ax.bar(labels, loo["dP_MAPE"], color=colors, alpha=0.8)
    ax.set_ylabel("LOO ΔP MAPE (%)")
    ax.set_xlabel("held-out geometry (Tpms·L/t)")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=7)
    ax.axhline(10.0, ls="--", lw=0.8, color="k", alpha=0.5, label="10% target")
    ax.set_title("LOO ΔP MAPE per held-out geometry (ConstDF-v1: constant K, c_F)")
    ax.grid(True, ls=":", alpha=0.4, axis="y")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def _render_markdown(loo_all: pd.DataFrame, train_mapes: dict[str, float]) -> str:
    lines: list[str] = []
    lines.append("---")
    lines.append("type: report")
    lines.append("date: 2026-04-14")
    lines.append("tags: [report, surrogate, joint-fit, MLP, DF, ConstDF-v1, SJTU-TPMSHX]")
    lines.append("---")
    lines.append("")
    lines.append("# D-F 代理模型 LOO 验证报告 (ConstDF-v1)")
    lines.append("")
    lines.append("## 方法")
    lines.append("")
    lines.append("每个 TPMS 类型独立训练一个 3 输入 × 2 输出的 MLP ensemble(5×):")
    lines.append("")
    lines.append("```")
    lines.append("输入: (log10 L, log10 t, log10 ε_f) → z-score 归一化")
    lines.append("MLP:  Linear(3, 32) → SiLU → Dropout(0.05)")
    lines.append("      Linear(32, 32) → SiLU → Dropout(0.05)")
    lines.append("      Linear(32, 2)")
    lines.append("输出: (log10 K, log10 c_F) ← 反归一化到物理空间")
    lines.append("")
    lines.append("ΔP_pred,i = ( μ_i u_i / K(L, t, ε_f)")
    lines.append("            + ρ_i c_F(L, t, ε_f) · u_i² ) · L_ch")
    lines.append("")
    lines.append("L_ch = K_S_CELLS · L_cell_m,    K_S_CELLS = 10")
    lines.append("损失 = mean ( (ΔP_pred - ΔP_obs) / ΔP_obs )²")
    lines.append("优化 = Adam(lr=1e-3, wd=3e-4) + ReduceLROnPlateau + 早停")
    lines.append("```")
    lines.append("")
    lines.append("K 和 c_F 是几何级常数(无 Re 依赖)。Re 独立性前置证据见 ")
    lines.append("`reports/constdf-v1/2026-04-14-DF-re-independence-report.md` —— 24/24 几何")
    lines.append("通过 Pearson 残差-Re 检验,物理上 2 参数 D-F 闭合在当前训练集")
    lines.append("Re 范围内是合法的。")
    lines.append("")
    lines.append("## 全数据训练集 ΔP MAPE (in-sample)")
    lines.append("")
    for tpms, mape in train_mapes.items():
        lines.append(f"- **{tpms}**: {mape:.2f}%")
    lines.append("")
    lines.append("## LOO ΔP MAPE 结果")
    lines.append("")
    lines.append("每折留一个 (L, t) 几何,用剩 11 个几何的所有 CFD 行训练 5× ensemble,")
    lines.append("在留出几何上查询单一 (K, c_F),代入 D-F 算每行 ΔP,对比 CFD。")
    lines.append("")

    for tpms, group in loo_all.groupby("tpms"):
        dP_sorted = sorted(group["dP_MAPE"].to_numpy())
        dP_drop_worst = float(np.mean(dP_sorted[:-1])) if len(dP_sorted) > 1 else float("nan")
        lines.append(f"### {tpms}")
        lines.append("")
        lines.append(f"- 几何数: {len(group)}")
        lines.append(f"- **ΔP LOO MAPE**:            **{group['dP_MAPE'].mean():.2f}%**")
        lines.append(f"- ΔP LOO MAPE (drop worst):    {dP_drop_worst:.2f}%")
        lines.append(f"- ΔP LOO 最差几何:             {group['dP_MAPE'].max():.2f}%")
        lines.append(f"- ΔP LOO 最差单行:             {group['dP_max_err'].max():.2f}%")
        lines.append("")
        lines.append("| L | t | n rows | K_ref (2p) | K_pred | c_F_ref (2p) | c_F_pred | ΔP MAPE% | ΔP max% |")
        lines.append("|---|---|--------|------------|--------|--------------|----------|----------|---------|")
        for _, r in group.iterrows():
            lines.append(
                f"| {r['L_mm']:.0f} | {r['t_mm']:.1f} | {r['n_test_rows']} "
                f"| {r['K_ref_2p']:.3g} | {r['K_pred']:.3g} "
                f"| {r['cF_ref_2p']:.4g} | {r['cF_pred']:.4g} "
                f"| {r['dP_MAPE']:.2f} | {r['dP_max_err']:.2f} |"
            )
        lines.append("")

    lines.append("## 图")
    lines.append("")
    lines.append("- 训练曲线: `figs/df_fit/loss_curves.png`")
    lines.append("- LOO 每几何 ΔP MAPE: `figs/df_fit/loo_parity.png`")
    lines.append("")
    lines.append("## 注")
    lines.append("")
    lines.append("- `K_ref (2p)` / `c_F_ref (2p)` 来自 Step 2 的每几何 2 参数 WLS,作为")
    lines.append("  参考,代理模型目标是在 LOO 下尽量接近这些常数。")
    lines.append("- `K_pred` / `c_F_pred` 是 LOO 留出几何的 ensemble 平均预测,代入该几何")
    lines.append("  所有 CFD 行做 per-row ΔP 残差。")
    lines.append("- **ΔP MAPE 是主指标**,汇总到 TPMS 级给出论文可引用的代理精度。")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    df_all = load_all()
    print(f"Loaded {len(df_all)} rows from training Excel")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    all_loo: list[pd.DataFrame] = []
    all_curves: dict[str, list[float]] = {}
    train_mapes: dict[str, float] = {}

    for tpms in ["Diamond", "Gyroid"]:
        ckpt, loo, curve = train_and_loo(df_all, tpms)
        all_loo.append(loo)
        all_curves[tpms] = curve
        train_mapes[tpms] = ckpt["train_dP_MAPE"]
        path = MODEL_DIR / f"df_surrogate_{tpms.lower()}.joblib"
        joblib.dump(ckpt, path)
        print(f"  [{tpms}] wrote {path.relative_to(_PROJECT)}")
        print(f"  [{tpms}] LOO ΔP MAPE = {loo['dP_MAPE'].mean():6.2f}% "
              f"(max {loo['dP_MAPE'].max():.1f}%, drop-worst "
              f"{np.mean(sorted(loo['dP_MAPE'])[:-1]):.2f}%)")

    loo_all = pd.concat(all_loo, ignore_index=True)
    _plot_loss(all_curves, FIG_DIR / "loss_curves.png")
    _plot_loo(loo_all, FIG_DIR / "loo_parity.png")
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(_render_markdown(loo_all, train_mapes), encoding="utf-8")
    print(f"\nWrote {REPORT_MD.relative_to(_PROJECT)}")


if __name__ == "__main__":
    main()
