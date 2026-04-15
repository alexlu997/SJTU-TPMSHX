"""
Scratch experiment: direct-ΔP data-driven MLP (Correa 2026 style).

Bypasses the Darcy-Forchheimer closure entirely. A 4-input MLP maps

    (log10 L_mm, log10 t_mm, log10 ε_f, log10 Re)  →  log10 ΔP_Pa

per TPMS type, trained on per-row relative ΔP loss. No K, no c_F, no
momentum equation — the network learns ΔP directly from geometry + flow.

Apples-to-apples with ConstDF-v1: identical LOO protocol, identical
ensemble/seed scheme, identical Adam/scheduler/early-stopping config.
Only the input/output heads and the loss path differ.

Does NOT modify any existing file. Writes report to
reports/scratch/2026-04-15-direct-dp-mlp-scratch.md.

Run::

    python -m thermoNas.df_fit.scratch_direct_dp_mlp
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.optim import Adam

from .fit_df_per_geom import K_S_CELLS  # only for diagnostic text
from .load_data import load_all

_THIS = Path(__file__).resolve()
_PROJECT = _THIS.parent.parent.parent

REPORT_MD = _PROJECT / "reports" / "scratch" / "2026-04-15-direct-dp-mlp-wide-scratch.md"
FIG_DIR = _PROJECT / "reports" / "figs" / "df_fit"
FIG_LOO = FIG_DIR / "direct_dp_mlp_wide_loo.png"

FEATURES = ["L_mm", "t_mm", "eps_f", "Re"]
INPUT_DIM = 4
OUTPUT_DIM = 1

# Wide variant (2026-04-15): regularized run (dropout 0.15, wd 1e-3) made
# Gyroid in-sample blow up to 13.52% → bias, not variance. Revert dropout/wd,
# bump capacity: 3 hidden layers × 64 units (from 2 × 32).
HIDDEN = 64             # was 32
N_HIDDEN_LAYERS = 3     # was 2
DROPOUT = 0.05          # reverted
LR = 1e-3
WEIGHT_DECAY = 3e-4     # reverted
EPOCHS = 8000
PATIENCE = 800
GRAD_CLIP = 1.0
SEED = 20260414
N_ENSEMBLE = 5

# Physical clamp on predicted log10 ΔP
LOG10_DP_MIN = 0.0   # 1 Pa
LOG10_DP_MAX = 7.0   # 1e7 Pa

BASELINE_LOO_MAPE = {"Diamond": 12.79, "Gyroid": 16.95}


# ===================================================================
# Model
# ===================================================================

class DirectDPMLP(nn.Module):
    """4-input → 1-output MLP predicting standardized log10 ΔP."""

    def __init__(self, hidden: int = HIDDEN, dropout: float = DROPOUT,
                  n_hidden_layers: int = N_HIDDEN_LAYERS):
        super().__init__()
        layers: list[nn.Module] = [nn.Linear(INPUT_DIM, hidden), nn.SiLU(), nn.Dropout(dropout)]
        for _ in range(n_hidden_layers - 1):
            layers += [nn.Linear(hidden, hidden), nn.SiLU(), nn.Dropout(dropout)]
        layers += [nn.Linear(hidden, OUTPUT_DIM)]
        self.net = nn.Sequential(*layers)

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        return self.net(z)


# ===================================================================
# Normalisation from raw rows
# ===================================================================

def _norm_from_rows(rows: pd.DataFrame) -> dict:
    """z-score statistics from per-row training data."""
    X_log = np.log10(rows[FEATURES].to_numpy(dtype=float))
    x_mean = X_log.mean(axis=0)
    x_std = X_log.std(axis=0)
    x_std[x_std < 1e-9] = 1.0

    y_log = np.log10(rows["dP_Pa"].to_numpy(dtype=float))
    y_mean = float(y_log.mean())
    y_std = float(y_log.std())
    if y_std < 1e-9:
        y_std = 1.0

    return {
        "x_log_mean": x_mean, "x_log_std": x_std,
        "y_log_mean": y_mean, "y_log_std": y_std,
    }


def _rows_to_tensors(rows: pd.DataFrame, norm: dict) -> dict:
    X_log = np.log10(rows[FEATURES].to_numpy(dtype=float))
    z = (X_log - norm["x_log_mean"]) / norm["x_log_std"]
    dP = rows["dP_Pa"].to_numpy(dtype=float)
    return {
        "z": torch.tensor(z, dtype=torch.float32),
        "dP": torch.tensor(dP, dtype=torch.float32),
    }


def _forward_dP(model: DirectDPMLP, z: torch.Tensor,
                 y_mean: float, y_std: float) -> torch.Tensor:
    out = model(z).squeeze(-1)
    log_dP = out * y_std + y_mean
    log_dP = torch.clamp(log_dP, LOG10_DP_MIN, LOG10_DP_MAX)
    return torch.pow(10.0, log_dP)


# ===================================================================
# Training
# ===================================================================

def _train(rows: pd.DataFrame, norm: dict, seed: int) -> DirectDPMLP:
    torch.manual_seed(seed)
    np.random.seed(seed)

    data = _rows_to_tensors(rows, norm)
    y_mean = float(norm["y_log_mean"])
    y_std = float(norm["y_log_std"])

    model = DirectDPMLP()
    opt = Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        opt, mode="min", factor=0.5, patience=PATIENCE // 4, min_lr=1e-6,
    )

    best_loss = float("inf")
    best_state = None
    patience = 0

    for _ in range(EPOCHS):
        model.train()
        opt.zero_grad()
        dP_pred = _forward_dP(model, data["z"], y_mean, y_std)
        rel = (dP_pred - data["dP"]) / data["dP"]
        loss = torch.mean(rel ** 2)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP)
        opt.step()

        loss_val = float(loss.item())
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
    return model


def _train_ensemble(rows: pd.DataFrame, norm: dict,
                     base_seed: int) -> list[DirectDPMLP]:
    return [_train(rows, norm, seed=base_seed + k * 101)
             for k in range(N_ENSEMBLE)]


def _predict_dP_vec(models: list[DirectDPMLP], norm: dict,
                    rows: pd.DataFrame) -> np.ndarray:
    """Ensemble-mean prediction in **log space**, then 10^x."""
    X_log = np.log10(rows[FEATURES].to_numpy(dtype=float))
    z = (X_log - norm["x_log_mean"]) / norm["x_log_std"]
    z_t = torch.tensor(z, dtype=torch.float32)
    y_mean = float(norm["y_log_mean"])
    y_std = float(norm["y_log_std"])

    log_dP_acc = np.zeros(len(rows))
    for m in models:
        m.eval()
        with torch.no_grad():
            out = m(z_t).squeeze(-1).numpy()
        log_dP_acc += out * y_std + y_mean
    log_dP_acc /= len(models)
    log_dP_acc = np.clip(log_dP_acc, LOG10_DP_MIN, LOG10_DP_MAX)
    return 10.0 ** log_dP_acc


# ===================================================================
# LOO
# ===================================================================

def train_and_loo(df_all: pd.DataFrame, tpms: str
                   ) -> tuple[pd.DataFrame, float]:
    sub = df_all[df_all["tpms"] == tpms].reset_index(drop=True)
    geoms = (sub[["L_mm", "t_mm", "eps_f"]].drop_duplicates()
              .sort_values(["L_mm", "t_mm"]).reset_index(drop=True))

    n_rows = len(sub)
    n_geoms = len(geoms)
    n_params = sum(p.numel() for p in DirectDPMLP().parameters())
    print(f"  [{tpms}] rows={n_rows}  geoms={n_geoms}  params={n_params} "
          f"× ensemble={N_ENSEMBLE}")

    # Full-data training MAPE (in-sample)
    norm = _norm_from_rows(sub)
    full_models = _train_ensemble(sub, norm, base_seed=SEED)
    dP_pred_full = _predict_dP_vec(full_models, norm, sub)
    dP_obs = sub["dP_Pa"].to_numpy(dtype=float)
    train_mape = float(np.mean(np.abs(dP_pred_full - dP_obs) / dP_obs) * 100.0)
    print(f"  [{tpms}] full-train ΔP MAPE (ensemble-avg): {train_mape:.2f}%")

    # Leave-one-geometry-out
    records: list[dict] = []
    for i, g in geoms.iterrows():
        L_out = float(g["L_mm"])
        t_out = float(g["t_mm"])

        mask_out = (sub["L_mm"] == L_out) & (sub["t_mm"] == t_out)
        train_rows = sub[~mask_out].reset_index(drop=True)
        test_rows = sub[mask_out].reset_index(drop=True)

        norm_i = _norm_from_rows(train_rows)
        models_i = _train_ensemble(train_rows, norm_i, base_seed=SEED + i * 7)

        dP_pred = _predict_dP_vec(models_i, norm_i, test_rows)
        dP_obs_test = test_rows["dP_Pa"].to_numpy(dtype=float)
        rel = np.abs(dP_pred - dP_obs_test) / dP_obs_test
        dP_mape = float(rel.mean() * 100.0)
        dP_max = float(rel.max() * 100.0)

        records.append({
            "tpms": tpms, "L_mm": L_out, "t_mm": t_out,
            "n_test_rows": int(len(test_rows)),
            "Re_min": float(test_rows["Re"].min()),
            "Re_max": float(test_rows["Re"].max()),
            "dP_obs_mean": float(dP_obs_test.mean()),
            "dP_pred_mean": float(dP_pred.mean()),
            "dP_MAPE": dP_mape, "dP_max_err": dP_max,
        })

    return pd.DataFrame(records), train_mape


# ===================================================================
# Reporting
# ===================================================================

def _plot_loo(loo: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=120)
    labels = [f"{r.tpms[0]}{int(r.L_mm)}/{r.t_mm:.1f}" for r in loo.itertuples()]
    colors = ["tab:blue" if r.tpms == "Diamond" else "tab:orange"
               for r in loo.itertuples()]
    ax.bar(labels, loo["dP_MAPE"], color=colors, alpha=0.8)
    ax.set_ylabel("LOO ΔP MAPE (%)")
    ax.set_xlabel("held-out geometry")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=7)
    ax.axhline(8.0, ls="--", lw=0.8, color="g", alpha=0.6, label="8% target")
    ax.axhline(12.79, ls=":", lw=0.8, color="tab:blue", alpha=0.6,
                label="v1 Diamond 12.79%")
    ax.axhline(16.95, ls=":", lw=0.8, color="tab:orange", alpha=0.6,
                label="v1 Gyroid 16.95%")
    ax.set_title("Direct-ΔP MLP LOO ΔP MAPE per held-out geometry (scratch)")
    ax.grid(True, ls=":", alpha=0.4, axis="y")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def _render_markdown(loo_all: pd.DataFrame,
                      train_mapes: dict[str, float]) -> str:
    L: list[str] = []
    L.append("---")
    L.append("type: report")
    L.append("date: 2026-04-15")
    L.append("tags: [report, surrogate, direct-dP, MLP, Correa, scratch, ThermoNAS]")
    L.append("---")
    L.append("")
    L.append("# Direct-ΔP MLP 代理模型 — wide 变体(scratch 实验)")
    L.append("")
    L.append("**本次变体**:HIDDEN 32→64,隐层 2→3,dropout/wd 恢复初始(0.05 / 3e-4)。")
    L.append("目的:regularized 变体让 Gyroid in-sample 飙到 13.52%(bias 问题,不是 variance),")
    L.append("说明 Gyroid L=6 家族泛化不良是 capacity 瓶颈。本变体加宽加深(~4800 参数,")
    L.append("仍远小于 Correa 4 层 256 宽的 ~200k)看能否让 Gyroid in-sample 恢复 5% 级并")
    L.append("把 LOO 从 14.18% 继续压下去。对比:")
    L.append("")
    L.append("- 初始版:`reports/scratch/2026-04-15-direct-dp-mlp-scratch.md`(LOO 8.89/14.18)")
    L.append("- 正则版:`reports/scratch/2026-04-15-direct-dp-mlp-reg-scratch.md`(LOO 9.33/25.40,失败)")
    L.append("")
    L.append("**动机**:ConstDF-v1 之后的 5 种 D-F 闭合类改进(死路 1-6+6a)全部失败,")
    L.append("核心限制是数据 Re 下限(400/1600)钳死了所有物理驱动闭合形式。本次绕开")
    L.append("D-F 闭合,按 Correa 2026(Gyroid,3.53% MAPE)思路训一个纯数据驱动 MLP,")
    L.append("输入 $(L, t, \\varepsilon_f, Re)$,直接输出 $\\log_{10} \\Delta P_\\text{Pa}$,")
    L.append("看能否突破 v1 的 12.79/16.95% 基线。")
    L.append("")
    L.append("**Scratch 定位**:不入主干,不改 v1,和前两个 Gompertz scratch 并列存档。")
    L.append("")

    L.append("## 记分板")
    L.append("")
    L.append("| | Diamond | Gyroid |")
    L.append("|---|---|---|")
    L.append(f"| ConstDF-v1 LOO (baseline) | {BASELINE_LOO_MAPE['Diamond']:.2f}% | {BASELINE_LOO_MAPE['Gyroid']:.2f}% |")
    d_loo = loo_all[loo_all["tpms"] == "Diamond"]["dP_MAPE"].mean()
    g_loo = loo_all[loo_all["tpms"] == "Gyroid"]["dP_MAPE"].mean()
    L.append(f"| **Direct-ΔP MLP LOO** | **{d_loo:.2f}%** | **{g_loo:.2f}%** |")
    L.append(f"| Δ vs v1 | {d_loo - BASELINE_LOO_MAPE['Diamond']:+.2f}pp | {g_loo - BASELINE_LOO_MAPE['Gyroid']:+.2f}pp |")
    L.append(f"| 目标 | < 8% | < 8% |")
    for tpms, mape in train_mapes.items():
        L.append(f"| {tpms} full-train in-sample MAPE | {mape:.2f}% | |")
    L.append("")

    L.append("## 方法")
    L.append("")
    L.append("**输入**(4D):$(\\log_{10} L_{mm}, \\log_{10} t_{mm}, \\log_{10} \\varepsilon_f, \\log_{10} Re)$,z-score 归一化。")
    L.append(f"归一化统计量来自**每折训练 rows**(per-row stats,非 per-geom reference)。")
    L.append("")
    L.append("**输出**(1D):标准化的 $\\log_{10} \\Delta P_\\text{Pa}$;推理时反归一化、")
    L.append(f"clamp 到 $[{LOG10_DP_MIN}, {LOG10_DP_MAX}]$,再取 $10^x$ 得物理 ΔP。")
    L.append("")
    L.append("**架构**:`Linear(4, 32) → SiLU → Dropout(0.05) → Linear(32, 32) → SiLU → Dropout(0.05) → Linear(32, 1)`")
    L.append("")
    L.append("**损失**:$\\text{mean}\\,((\\Delta P_\\text{pred} - \\Delta P_\\text{obs})/\\Delta P_\\text{obs})^2$(与 v1 同款)")
    L.append("")
    L.append(f"**超参**(与 ConstDF-v1 **完全一致**):Adam(lr={LR}, wd={WEIGHT_DECAY}),")
    L.append(f"ReduceLROnPlateau(patience={PATIENCE // 4}, factor=0.5),早停 PATIENCE={PATIENCE},")
    L.append(f"grad clip={GRAD_CLIP},epochs≤{EPOCHS},{N_ENSEMBLE} seed ensemble")
    L.append(f"(base SEED={SEED},member offset +k·101,LOO fold offset +i·7)")
    L.append("")
    L.append(f"**L_ch 注**:K_S_CELLS={K_S_CELLS},但本 direct 模型**不进入** L_ch 计算 —— 网络从 $L$ 输入内部学习 ΔP 与 L 的关系")
    L.append("")

    L.append("## LOO 每几何 ΔP MAPE")
    L.append("")
    for tpms, group in loo_all.groupby("tpms"):
        g = group.reset_index(drop=True)
        dP_sorted = sorted(g["dP_MAPE"].to_numpy())
        dP_drop_worst = float(np.mean(dP_sorted[:-1])) if len(dP_sorted) > 1 else float("nan")
        L.append(f"### {tpms}")
        L.append("")
        L.append(f"- 几何数: {len(g)}")
        L.append(f"- **Direct-MLP LOO ΔP MAPE**: **{g['dP_MAPE'].mean():.2f}%** "
                  f"(v1 基线 {BASELINE_LOO_MAPE[tpms]:.2f}%)")
        L.append(f"- drop-worst LOO MAPE: {dP_drop_worst:.2f}%")
        L.append(f"- LOO 最差几何: {g['dP_MAPE'].max():.2f}%")
        L.append(f"- LOO 最差单行: {g['dP_max_err'].max():.2f}%")
        L.append("")
        L.append("| L | t | n | Re range | dP_obs mean | dP_pred mean | ΔP MAPE% | max% |")
        L.append("|---|---|---|----------|-------------|--------------|----------|------|")
        for _, r in g.iterrows():
            L.append(
                f"| {r['L_mm']:.0f} | {r['t_mm']:.1f} | {r['n_test_rows']} "
                f"| {r['Re_min']:.0f}–{r['Re_max']:.0f} "
                f"| {r['dP_obs_mean']:.3g} | {r['dP_pred_mean']:.3g} "
                f"| {r['dP_MAPE']:.2f} | {r['dP_max_err']:.2f} |"
            )
        L.append("")

    L.append("## 图")
    L.append("")
    L.append(f"- LOO bar chart: `{FIG_LOO.relative_to(_PROJECT).as_posix()}`")
    L.append("")

    L.append("## 判据")
    L.append("")
    L.append("- **两个 TPMS 都 < 8%** → 升级为 DirectMLP-v1 主干,归档 ConstDF-v1 为备份")
    L.append("- **一个 < 8% 一个 > 12%** → 非对称成功(和 Re-dep v2 同症),归档备案")
    L.append("- **两个都 ≥ 12%** → 死路 7,写入 memory,接入 ConstDF-v1 到求解器")
    L.append("- **一个 / 两个在 8-12% 区间** → 小幅改善但不达目标,保留 v1 主干")
    L.append("")
    L.append("**注**:direct-MLP 的 full-train in-sample MAPE 是 LOO 的理论上界。")
    L.append("若 in-sample 就达不到 8%,说明 4D 输入对本数据集表达力不足,")
    L.append("考虑加 hidden size(3 层 × 64)或加输入维度(显式 u/ρ/μ)作为 follow-up。")
    L.append("")
    return "\n".join(L)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    df_all = load_all()
    print(f"Loaded {len(df_all)} rows from training Excel")
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    all_loo: list[pd.DataFrame] = []
    train_mapes: dict[str, float] = {}

    for tpms in ["Diamond", "Gyroid"]:
        loo, train_mape = train_and_loo(df_all, tpms)
        all_loo.append(loo)
        train_mapes[tpms] = train_mape
        print(f"  [{tpms}] LOO ΔP MAPE = {loo['dP_MAPE'].mean():6.2f}% "
              f"(v1 baseline {BASELINE_LOO_MAPE[tpms]:.2f}%, "
              f"max {loo['dP_MAPE'].max():.1f}%)")

    loo_all = pd.concat(all_loo, ignore_index=True)
    _plot_loo(loo_all, FIG_LOO)

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(_render_markdown(loo_all, train_mapes),
                          encoding="utf-8")
    print(f"\nWrote {REPORT_MD.relative_to(_PROJECT)}")
    print(f"Wrote {FIG_LOO.relative_to(_PROJECT)}")


if __name__ == "__main__":
    main()
