"""
Scratch experiment: EG-DIP Gompertz β(Re) surrogate (Singh 2026 inspired).

Replaces the constant Forchheimer coefficient c_F of ConstDF-v1 with a
3-parameter Gompertz ramp:

    β(Re) = β_s · exp( -exp( (Re_t - Re) / λ ) )

and each geometry therefore has 4 parameters (K, β_s, Re_t, λ) rather
than 2. The per-row ΔP loss becomes

    ΔP_pred,i = ( μ_i u_i / K(L, t, ε_f)
                  + ρ_i · β(Re_i; β_s, Re_t, λ)(L, t, ε_f) · u_i² ) · L_ch

with all four parameters output by a 3D MLP ensemble (log10 K, log10 β_s,
Re_t, log10 λ), mirroring ConstDF-v1 architecture and seeding so the LOO
numbers are apples-to-apples against Diamond 12.79% / Gyroid 16.95%.

This is a THROWAWAY diagnostic. It does not modify any existing file,
does not save checkpoints, and only imports load_data / fit_df_per_geom
read-only from the ConstDF-v1 baseline.

Run::

    python -m sjtu_tpmshx.df_fit.scratch_egdip_gompertz

Outputs:
    reports/scratch/2026-04-15-egdip-gompertz-scratch.md
    stdout: per-geom Gompertz fit table + LOO summary
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from scipy.optimize import OptimizeWarning, curve_fit
from torch.optim import Adam

from .fit_df_per_geom import K_S_CELLS, _nnls_momentum, _wls_momentum
from . import load_data as _ld
_ld._L8_RE_MIN = 0.0  # scratch override: keep L=8 low-Re rows (transition regime) for EG-DIP
from .load_data import load_all  # noqa: E402

_THIS = Path(__file__).resolve()
_PROJECT = _THIS.parent.parent.parent

REPORT_MD = _PROJECT / "reports" / "scratch" / "2026-04-15-egdip-gompertz-fullL8-scratch.md"
FIG_DIR = _PROJECT / "reports" / "figs" / "df_fit"
FIG_LOO = FIG_DIR / "egdip_gompertz_fullL8_loo.png"

FEATURES = ["L_mm", "t_mm", "eps_f"]
INPUT_DIM = 3
OUTPUT_DIM = 4  # (log10 K, log10 β_s, Re_t, log10 λ)

# Mirror ConstDF-v1 hyper-parameters exactly
HIDDEN = 32
DROPOUT = 0.05
LR = 1e-3
WEIGHT_DECAY = 3e-4
EPOCHS = 8000
PATIENCE = 800
GRAD_CLIP = 1.0
SEED = 20260414
N_ENSEMBLE = 5

# Gompertz physical clamps
LOG10_K_MIN, LOG10_K_MAX = -16.0, -4.0
LOG10_BETA_S_MIN, LOG10_BETA_S_MAX = -2.0, 6.0
RE_T_MIN, RE_T_MAX = -2000.0, 6000.0     # allow out-of-range as degeneration signal
LOG10_LAM_MIN, LOG10_LAM_MAX = 1.0, 4.0  # λ ∈ [10, 10_000]

# Baseline reference (ConstDF-v1) for the scoreboard line in the report
BASELINE_LOO_MAPE = {"Diamond": 12.79, "Gyroid": 16.95}


# ===================================================================
# Gompertz closed form
# ===================================================================

def _beta_np(Re: np.ndarray, beta_s: float, Re_t: float, lam: float) -> np.ndarray:
    z = np.clip((Re_t - Re) / lam, -50.0, 50.0)
    return beta_s * np.exp(-np.exp(z))


def _beta_torch(Re: torch.Tensor, beta_s: torch.Tensor,
                Re_t: torch.Tensor, lam: torch.Tensor) -> torch.Tensor:
    z = torch.clamp((Re_t - Re) / lam, min=-50.0, max=50.0)
    return beta_s * torch.exp(-torch.exp(z))


def _dp_model_np(u, Re, mu, rho, L_ch, K, beta_s, Re_t, lam):
    beta = _beta_np(Re, beta_s, Re_t, lam)
    return (mu * u / K + rho * beta * u ** 2) * L_ch


# ===================================================================
# Per-geometry 4-parameter Gompertz WLS
# ===================================================================

def _fit_gompertz_one_geom(u, dP, mu, rho, Re, L_ch,
                            K_init, cF_init) -> dict:
    """Fit (K, β_s, Re_t, λ) on one geometry via WLS with w=1/dP² (sigma=dP)."""
    def _f(_unused_x, K, beta_s, Re_t, lam):
        return _dp_model_np(u, Re, mu, rho, L_ch, K, beta_s, Re_t, lam)

    p0 = [float(K_init), float(max(cF_init, 1.0)), 1500.0, 500.0]
    lower = [1e-14, 1e-3, RE_T_MIN, 10.0]
    upper = [1e-4, 1e6, RE_T_MAX, 10_000.0]

    ok = True
    msg = ""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", OptimizeWarning)
            popt, _pcov = curve_fit(
                _f, xdata=np.zeros_like(u), ydata=dP,
                p0=p0, sigma=dP, absolute_sigma=False,
                bounds=(lower, upper), maxfev=20_000,
            )
        K, beta_s, Re_t, lam = (float(v) for v in popt)
    except Exception as exc:  # noqa: BLE001
        ok = False
        msg = str(exc)
        K, beta_s, Re_t, lam = p0

    dP_pred = _dp_model_np(u, Re, mu, rho, L_ch, K, beta_s, Re_t, lam)
    mape = float(np.mean(np.abs(dP_pred - dP) / dP) * 100.0)
    max_err = float(np.max(np.abs(dP_pred - dP) / dP) * 100.0)

    return {
        "K": K, "beta_s": beta_s, "Re_t": Re_t, "lambda": lam,
        "dP_MAPE": mape, "dP_max_err": max_err,
        "fit_ok": ok, "fit_msg": msg,
    }


def _per_geom_gompertz_table(rows_df: pd.DataFrame) -> pd.DataFrame:
    """Per-geometry Gompertz + v1 reference (for init + normalisation)."""
    recs: list[dict] = []
    for (tpms, L, t), g in rows_df.groupby(["tpms", "L_mm", "t_mm"]):
        u = g["u_mps"].to_numpy(dtype=float)
        dP = g["dP_Pa"].to_numpy(dtype=float)
        mu = g["mu"].to_numpy(dtype=float)
        rho = g["rho"].to_numpy(dtype=float)
        Re = g["Re"].to_numpy(dtype=float)
        L_ch = K_S_CELLS * float(L) * 1e-3

        inv_K, cF_v1 = _wls_momentum(u, dP, mu, rho, L_ch)
        if inv_K < 0.0 or cF_v1 < 0.0:
            inv_K, cF_v1 = _nnls_momentum(u, dP, mu, rho, L_ch)
        K_v1 = 1.0 / max(inv_K, 1e-30)

        # v1 per-geom MAPE (for side-by-side column)
        dP_v1 = (mu * u / K_v1 + rho * cF_v1 * u ** 2) * L_ch
        mape_v1 = float(np.mean(np.abs(dP_v1 - dP) / dP) * 100.0)

        fit = _fit_gompertz_one_geom(u, dP, mu, rho, Re, L_ch, K_v1, cF_v1)

        recs.append({
            "tpms": tpms, "L_mm": float(L), "t_mm": float(t),
            "eps_f": float(g["eps_f"].iloc[0]),
            "n_rows": int(len(g)),
            "Re_min": float(Re.min()), "Re_max": float(Re.max()),
            "K_v1": K_v1, "cF_v1": cF_v1, "dP_MAPE_v1": mape_v1,
            "K": fit["K"], "beta_s": fit["beta_s"],
            "Re_t": fit["Re_t"], "lambda": fit["lambda"],
            "dP_MAPE_gp": fit["dP_MAPE"],
            "dP_max_err_gp": fit["dP_max_err"],
            "fit_ok": fit["fit_ok"], "fit_msg": fit["fit_msg"],
        })
    return pd.DataFrame(recs)


# ===================================================================
# Normalisation from per-geom reference
# ===================================================================

def _norm_from_ref(ref: pd.DataFrame) -> dict:
    X_log = np.log10(ref[FEATURES].to_numpy(dtype=float))
    x_mean = X_log.mean(axis=0)
    x_std = X_log.std(axis=0)
    x_std[x_std < 1e-9] = 1.0

    Y = np.column_stack([
        np.log10(ref["K"].to_numpy(dtype=float)),
        np.log10(np.maximum(ref["beta_s"].to_numpy(dtype=float), 1e-6)),
        ref["Re_t"].to_numpy(dtype=float),
        np.log10(np.maximum(ref["lambda"].to_numpy(dtype=float), 1e-3)),
    ])
    y_mean = Y.mean(axis=0)
    y_std = Y.std(axis=0)
    y_std[y_std < 1e-9] = 1.0

    return {
        "x_log_mean": x_mean, "x_log_std": x_std,
        "y_mean": y_mean, "y_std": y_std,
    }


# ===================================================================
# Model
# ===================================================================

class EGDIPMLP(nn.Module):
    def __init__(self, hidden: int = HIDDEN, dropout: float = DROPOUT):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(INPUT_DIM, hidden),
            nn.SiLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden),
            nn.SiLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, OUTPUT_DIM),
        )

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        return self.net(z)


def _decode(out: torch.Tensor, y_mean_t: torch.Tensor, y_std_t: torch.Tensor):
    y = out * y_std_t + y_mean_t
    log_K = torch.clamp(y[:, 0], LOG10_K_MIN, LOG10_K_MAX)
    log_bs = torch.clamp(y[:, 1], LOG10_BETA_S_MIN, LOG10_BETA_S_MAX)
    Re_t = torch.clamp(y[:, 2], RE_T_MIN, RE_T_MAX)
    log_lam = torch.clamp(y[:, 3], LOG10_LAM_MIN, LOG10_LAM_MAX)
    K = torch.pow(10.0, log_K)
    beta_s = torch.pow(10.0, log_bs)
    lam = torch.pow(10.0, log_lam)
    return K, beta_s, Re_t, lam


# ===================================================================
# Rows → tensors
# ===================================================================

def _rows_to_tensors(rows: pd.DataFrame, norm: dict) -> dict:
    L = rows["L_mm"].to_numpy(dtype=float)
    t = rows["t_mm"].to_numpy(dtype=float)
    eps_f = rows["eps_f"].to_numpy(dtype=float)
    u = rows["u_mps"].to_numpy(dtype=float)
    dP = rows["dP_Pa"].to_numpy(dtype=float)
    mu = rows["mu"].to_numpy(dtype=float)
    rho = rows["rho"].to_numpy(dtype=float)
    Re = rows["Re"].to_numpy(dtype=float)
    L_ch = K_S_CELLS * L * 1e-3

    x_log = np.log10(np.column_stack([L, t, eps_f]))
    z = (x_log - norm["x_log_mean"]) / norm["x_log_std"]

    return {
        "z": torch.tensor(z, dtype=torch.float32),
        "u": torch.tensor(u, dtype=torch.float32),
        "dP": torch.tensor(dP, dtype=torch.float32),
        "mu": torch.tensor(mu, dtype=torch.float32),
        "rho": torch.tensor(rho, dtype=torch.float32),
        "Re": torch.tensor(Re, dtype=torch.float32),
        "L_ch": torch.tensor(L_ch, dtype=torch.float32),
    }


# ===================================================================
# Training
# ===================================================================

def _train(rows: pd.DataFrame, norm: dict, seed: int) -> EGDIPMLP:
    torch.manual_seed(seed)
    np.random.seed(seed)

    data = _rows_to_tensors(rows, norm)
    y_mean_t = torch.tensor(norm["y_mean"], dtype=torch.float32)
    y_std_t = torch.tensor(norm["y_std"], dtype=torch.float32)

    model = EGDIPMLP()
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
        out = model(data["z"])
        K, beta_s, Re_t, lam = _decode(out, y_mean_t, y_std_t)
        beta = _beta_torch(data["Re"], beta_s, Re_t, lam)
        dP_pred = (data["mu"] * data["u"] / K
                    + data["rho"] * beta * data["u"] ** 2) * data["L_ch"]
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


def _train_ensemble(rows: pd.DataFrame, norm: dict, base_seed: int
                     ) -> list[EGDIPMLP]:
    models: list[EGDIPMLP] = []
    for k in range(N_ENSEMBLE):
        models.append(_train(rows, norm, seed=base_seed + k * 101))
    return models


def _predict_params(models: list[EGDIPMLP], norm: dict,
                    L_mm: np.ndarray, t_mm: np.ndarray, eps_f: np.ndarray
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Ensemble-averaged (K, β_s, Re_t, λ) in physical units."""
    x_log = np.log10(np.column_stack([L_mm, t_mm, eps_f]))
    z = (x_log - norm["x_log_mean"]) / norm["x_log_std"]
    z_t = torch.tensor(z, dtype=torch.float32)
    y_mean_t = torch.tensor(norm["y_mean"], dtype=torch.float32)
    y_std_t = torch.tensor(norm["y_std"], dtype=torch.float32)

    n = len(L_mm)
    K_acc = np.zeros(n); bs_acc = np.zeros(n)
    Re_t_acc = np.zeros(n); lam_acc = np.zeros(n)

    for m in models:
        m.eval()
        with torch.no_grad():
            K, bs, Re_t, lam = _decode(m(z_t), y_mean_t, y_std_t)
        K_acc += K.numpy()
        bs_acc += bs.numpy()
        Re_t_acc += Re_t.numpy()
        lam_acc += lam.numpy()

    return (K_acc / len(models), bs_acc / len(models),
            Re_t_acc / len(models), lam_acc / len(models))


# ===================================================================
# LOO
# ===================================================================

def train_and_loo(df_all: pd.DataFrame, tpms: str
                   ) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    sub = df_all[df_all["tpms"] == tpms].reset_index(drop=True)
    ref = _per_geom_gompertz_table(sub).sort_values(["L_mm", "t_mm"]).reset_index(drop=True)

    n_rows = len(sub)
    n_geoms = len(ref)
    n_params = sum(p.numel() for p in EGDIPMLP().parameters())
    n_bad = int((~ref["fit_ok"]).sum())
    print(f"  [{tpms}] rows={n_rows}  geoms={n_geoms}  params={n_params} "
          f"× ensemble={N_ENSEMBLE}   per-geom Gompertz fails={n_bad}")

    # Full-data training MAPE (in-sample)
    norm = _norm_from_ref(ref)
    full_models = _train_ensemble(sub, norm, base_seed=SEED)

    L_arr = sub["L_mm"].to_numpy(dtype=float)
    t_arr = sub["t_mm"].to_numpy(dtype=float)
    eps_f_arr = sub["eps_f"].to_numpy(dtype=float)
    u_arr = sub["u_mps"].to_numpy(dtype=float)
    dP_arr = sub["dP_Pa"].to_numpy(dtype=float)
    mu_arr = sub["mu"].to_numpy(dtype=float)
    rho_arr = sub["rho"].to_numpy(dtype=float)
    Re_arr = sub["Re"].to_numpy(dtype=float)
    L_ch_arr = K_S_CELLS * L_arr * 1e-3

    K_e, bs_e, Ret_e, lam_e = _predict_params(
        full_models, norm, L_arr, t_arr, eps_f_arr,
    )
    beta_e = _beta_np(Re_arr, bs_e, Ret_e, lam_e)
    dP_pred_full = (mu_arr * u_arr / K_e + rho_arr * beta_e * u_arr ** 2) * L_ch_arr
    train_mape = float(np.mean(np.abs(dP_pred_full - dP_arr) / dP_arr) * 100.0)
    print(f"  [{tpms}] full-train ΔP MAPE (ensemble-avg): {train_mape:.2f}%")

    # LOO
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
        models_i = _train_ensemble(train_rows, norm_i, base_seed=SEED + i * 7)

        K_arr, bs_arr, Ret_arr, lam_arr = _predict_params(
            models_i, norm_i,
            np.array([L_out]), np.array([t_out]), np.array([eps_f_out]),
        )
        K_pred = float(K_arr[0]); bs_pred = float(bs_arr[0])
        Ret_pred = float(Ret_arr[0]); lam_pred = float(lam_arr[0])

        u = test_rows["u_mps"].to_numpy(dtype=float)
        dP_obs = test_rows["dP_Pa"].to_numpy(dtype=float)
        mu = test_rows["mu"].to_numpy(dtype=float)
        rho = test_rows["rho"].to_numpy(dtype=float)
        Re = test_rows["Re"].to_numpy(dtype=float)
        L_ch = K_S_CELLS * L_out * 1e-3

        beta = _beta_np(Re, bs_pred, Ret_pred, lam_pred)
        dP_pred = (mu * u / K_pred + rho * beta * u ** 2) * L_ch
        rel = np.abs(dP_pred - dP_obs) / dP_obs
        dP_mape = float(rel.mean() * 100.0)
        dP_max = float(rel.max() * 100.0)

        rows.append({
            "tpms": tpms, "L_mm": L_out, "t_mm": t_out,
            "n_test_rows": int(len(test_rows)),
            "K_ref": float(r["K"]), "K_pred": K_pred,
            "bs_ref": float(r["beta_s"]), "bs_pred": bs_pred,
            "Ret_ref": float(r["Re_t"]), "Ret_pred": Ret_pred,
            "lam_ref": float(r["lambda"]), "lam_pred": lam_pred,
            "dP_MAPE": dP_mape, "dP_max_err": dP_max,
            "dP_MAPE_v1_pergeom": float(r["dP_MAPE_v1"]),
            "dP_MAPE_gp_pergeom": float(r["dP_MAPE_gp"]),
        })

    loo = pd.DataFrame(rows)
    return ref, loo, train_mape


# ===================================================================
# Reporting
# ===================================================================

def _plot_loo(loo: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=120)
    labels = [f"{r.tpms[0]}{int(r.L_mm)}/{r.t_mm:.1f}" for r in loo.itertuples()]
    colors = ["tab:blue" if r.tpms == "Diamond" else "tab:orange" for r in loo.itertuples()]
    ax.bar(labels, loo["dP_MAPE"], color=colors, alpha=0.8)
    ax.set_ylabel("LOO ΔP MAPE (%)")
    ax.set_xlabel("held-out geometry")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=7)
    ax.axhline(8.0, ls="--", lw=0.8, color="g", alpha=0.6, label="8% target")
    ax.axhline(12.79, ls=":", lw=0.8, color="tab:blue", alpha=0.6, label="v1 Diamond 12.79%")
    ax.axhline(16.95, ls=":", lw=0.8, color="tab:orange", alpha=0.6, label="v1 Gyroid 16.95%")
    ax.set_title("EG-DIP Gompertz LOO ΔP MAPE per held-out geometry (scratch)")
    ax.grid(True, ls=":", alpha=0.4, axis="y")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def _render_markdown(ref_all: pd.DataFrame, loo_all: pd.DataFrame,
                      train_mapes: dict[str, float]) -> str:
    L: list[str] = []
    L.append("---")
    L.append("type: report")
    L.append("date: 2026-04-15")
    L.append("tags: [report, surrogate, EG-DIP, Gompertz, scratch, SJTU-TPMSHX]")
    L.append("---")
    L.append("")
    L.append("# EG-DIP Gompertz β(Re) 代理模型 — full-L8 变体(scratch 实验)")
    L.append("")
    L.append("**本次变体**:relative `load_data._L8_RE_MIN = 0.0`,**保留 L=8 低 Re 过渡段**")
    L.append("(每 TPMS 多 18 行,合计 +36 行)。目的:给 Gompertz ramp 提供过渡区梯度信号,")
    L.append("看 L=8 三个几何的 $Re_t$ 能否从初值 1500 解锁到数据范围内。对比第一版本(filtered)见")
    L.append("`reports/scratch/2026-04-15-egdip-gompertz-scratch.md`。")
    L.append("")
    L.append("**一句话**:按 Singh 2026 的 Gompertz β(Re) 形式,把 ConstDF-v1 ")
    L.append("的常系数 $c_F$ 替换为 $\\beta(Re) = \\beta_s \\exp(-\\exp((Re_t - Re)/\\lambda))$,")
    L.append("每几何 4 参数 $(K, \\beta_s, Re_t, \\lambda)$,LOO 看能否把 ΔP MAPE ")
    L.append("从 Diamond 12.79% / Gyroid 16.95% 压到 6-8% 目标。")
    L.append("")
    L.append("**定位**:scratch 诊断,**不入主干**。代码 `sjtu_tpmshx/df_fit/scratch_egdip_gompertz.py`,")
    L.append("不修改 v1 任何文件,不保存 checkpoint。")
    L.append("")

    L.append("## 记分板")
    L.append("")
    L.append("| | Diamond | Gyroid |")
    L.append("|---|---|---|")
    L.append(f"| ConstDF-v1 LOO (baseline) | {BASELINE_LOO_MAPE['Diamond']:.2f}% | {BASELINE_LOO_MAPE['Gyroid']:.2f}% |")
    for tpms in ["Diamond", "Gyroid"]:
        g = loo_all[loo_all["tpms"] == tpms]
        if not g.empty:
            pass
    d_loo = loo_all[loo_all["tpms"] == "Diamond"]["dP_MAPE"].mean()
    g_loo = loo_all[loo_all["tpms"] == "Gyroid"]["dP_MAPE"].mean()
    L.append(f"| **EG-DIP Gompertz LOO** | **{d_loo:.2f}%** | **{g_loo:.2f}%** |")
    L.append(f"| Δ vs v1 | {d_loo - BASELINE_LOO_MAPE['Diamond']:+.2f}pp | {g_loo - BASELINE_LOO_MAPE['Gyroid']:+.2f}pp |")
    L.append(f"| 目标 | 6-8% | 6-8% |")
    for tpms, mape in train_mapes.items():
        L.append(f"| {tpms} full-train in-sample MAPE | {mape:.2f}% | |")
    L.append("")

    L.append("## 方法(与 ConstDF-v1 对齐的部分)")
    L.append("")
    L.append("- 架构:`Linear(3,32) → SiLU → Dropout(0.05) → Linear(32,32) → SiLU → Dropout(0.05) → Linear(32,4)`")
    L.append(f"- 输出:$(\\log_{{10}} K, \\log_{{10}} \\beta_s, Re_t, \\log_{{10}} \\lambda)$,各自 z-score 反归一化后 clamp 到物理范围")
    L.append(f"- 优化:Adam(lr={LR}, wd={WEIGHT_DECAY}),ReduceLROnPlateau,早停 patience={PATIENCE},grad clip={GRAD_CLIP}")
    L.append(f"- 归一化锚点:每几何 4 参数 curve_fit(scipy, WLS with sigma=dP)")
    L.append(f"- Ensemble:{N_ENSEMBLE} seeds,base seed={SEED},LOO fold i 用 base_seed+i·7(与 v1 一致)")
    L.append(f"- L_ch = {K_S_CELLS} · L_cell,损失 = $\\text{{mean}}\\,((\\Delta P_\\text{{pred}} - \\Delta P_\\text{{obs}})/\\Delta P_\\text{{obs}})^2$")
    L.append("")

    L.append("## 每几何 4 参数拟合诊断")
    L.append("")
    L.append("| tpms | L | t | n | Re range | K | β_s | Re_t | λ | v1 MAPE% | Gp MAPE% | ok |")
    L.append("|------|---|---|---|----------|---|-----|------|---|----------|----------|-----|")
    for _, r in ref_all.iterrows():
        in_range = r["Re_min"] <= r["Re_t"] <= r["Re_max"]
        flag_ret = f"{r['Re_t']:.0f}" + ("" if in_range else "⚠")
        ok_flag = "✓" if r["fit_ok"] else "✗"
        L.append(
            f"| {r['tpms']} | {r['L_mm']:.0f} | {r['t_mm']:.1f} | {r['n_rows']} "
            f"| {r['Re_min']:.0f}–{r['Re_max']:.0f} "
            f"| {r['K']:.3g} | {r['beta_s']:.3g} | {flag_ret} | {r['lambda']:.0f} "
            f"| {r['dP_MAPE_v1']:.2f} | {r['dP_MAPE_gp']:.2f} | {ok_flag} |"
        )
    L.append("")
    L.append("**⚠** 表示 $Re_t$ 落在该几何训练数据 Re 范围之外 → Gompertz 退化为")
    L.append("该几何上常数 $\\beta \\approx \\beta_s$(Re 远大于 Re_t)或 $\\beta \\approx 0$")
    L.append("(Re 远小于 Re_t)。退化几何的 Gompertz MAPE 应该 ≈ v1 MAPE,如果明显更小")
    L.append("通常是 $(K, \\beta_s)$ 多自由度在近似的同时折中了。")
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
        L.append(f"- **EG-DIP LOO ΔP MAPE**: **{g['dP_MAPE'].mean():.2f}%** "
                  f"(v1 基线 {BASELINE_LOO_MAPE[tpms]:.2f}%)")
        L.append(f"- drop-worst LOO MAPE: {dP_drop_worst:.2f}%")
        L.append(f"- LOO 最差几何: {g['dP_MAPE'].max():.2f}%")
        L.append(f"- LOO 最差单行: {g['dP_max_err'].max():.2f}%")
        L.append("")
        L.append("| L | t | n | K_pred | β_s,pred | Re_t,pred | λ_pred | ΔP MAPE% | max% |")
        L.append("|---|---|---|--------|----------|-----------|--------|----------|------|")
        for _, r in g.iterrows():
            L.append(
                f"| {r['L_mm']:.0f} | {r['t_mm']:.1f} | {r['n_test_rows']} "
                f"| {r['K_pred']:.3g} | {r['bs_pred']:.3g} | {r['Ret_pred']:.0f} "
                f"| {r['lam_pred']:.0f} | {r['dP_MAPE']:.2f} | {r['dP_max_err']:.2f} |"
            )
        L.append("")

    L.append("## 图")
    L.append("")
    L.append(f"- LOO bar chart: `{FIG_LOO.relative_to(_PROJECT).as_posix()}`")
    L.append("")

    L.append("## 结论(由上面的数字判读)")
    L.append("")
    L.append("根据记分板填入:")
    L.append("- **成功判据**:两个 TPMS 类型都从 v1 下降 ≥ 5pp,且落在 6-8% 目标区")
    L.append("  → 把这个实验升级为 v2-Gompertz 主干。")
    L.append("- **部分成功**:一个 TPMS 改善 ≥ 5pp,另一个 < 2pp 变化 → 几何差异显著,")
    L.append("  需要先在 per-geom 诊断里找出哪些几何的 $Re_t$ 落在数据范围内。")
    L.append("- **失败**:两个 TPMS 变化 < 2pp 或出现退化 → Re 范围(最低 400)不够深入")
    L.append("  过渡区,Gompertz 形式和 ConstDF 在本数据集上等价。下一步需要补 Re<100 的 CFD")
    L.append("  或换别的物理驱动形式。**此时应保留 ConstDF-v1 作基线**。")
    L.append("")
    L.append("**注意**:per-geom Gompertz MAPE(上表 `Gp MAPE%` 列)是 LOO 的理论上界 ——")
    L.append("如果 per-geom 就压不到 8% 以下,LOO 不可能更好。若两者都达不到,问题在物理形式")
    L.append("而不是 MLP 容量。")
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

    all_ref: list[pd.DataFrame] = []
    all_loo: list[pd.DataFrame] = []
    train_mapes: dict[str, float] = {}

    for tpms in ["Diamond", "Gyroid"]:
        ref, loo, train_mape = train_and_loo(df_all, tpms)
        all_ref.append(ref)
        all_loo.append(loo)
        train_mapes[tpms] = train_mape
        print(f"  [{tpms}] LOO ΔP MAPE = {loo['dP_MAPE'].mean():6.2f}% "
              f"(v1 baseline {BASELINE_LOO_MAPE[tpms]:.2f}%, "
              f"max {loo['dP_MAPE'].max():.1f}%)")

    ref_all = pd.concat(all_ref, ignore_index=True)
    loo_all = pd.concat(all_loo, ignore_index=True)

    _plot_loo(loo_all, FIG_LOO)

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(_render_markdown(ref_all, loo_all, train_mapes),
                          encoding="utf-8")
    print(f"\nWrote {REPORT_MD.relative_to(_PROJECT)}")
    print(f"Wrote {FIG_LOO.relative_to(_PROJECT)}")


if __name__ == "__main__":
    main()
