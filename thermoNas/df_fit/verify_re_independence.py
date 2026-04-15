"""
Step 3: verify that the two Darcy-Forchheimer parameters (K and c_F) are
Reynolds-number-independent, now at the momentum-equation level (no f).

The structural assumption behind D-F is that, for a fixed geometry, a single
pair (K, c_F) reproduces ΔP across the whole Re range:

    ΔP = ( μ u / K  +  ρ c_F u² ) · L_ch                               (1)

Two complementary checks on each geometry:

1) Residual-Re correlation (hard gate)
   Fit (1) on the full Re range with the same WLS loss as ``fit_df_per_geom``
   (weights w_i = 1/ΔP_i², which minimises mean squared relative ΔP error).
   Compute per-row relative residuals
       ε_i = (ΔP_pred,i − ΔP_obs,i) / ΔP_obs,i
   and Pearson-test ε against Re. If the D-F functional form is adequate
   for this geometry, ε should be uncorrelated with Re (|r| small or
   p > 0.05). Systematic Re dependence means the 2-parameter closure is
   missing structure.

2) Re-bin drift (informational)
   Split Re into three equal-count bins (low / mid / high Re), refit (K, c_F)
   in each bin, and report ΔK/K_full and Δc_F/c_F_full. A truly Re-independent
   closure should show < 10 % drift. This is informational only — with small
   bins of 2-9 points the per-bin fit uncertainty is often above 10 % just
   from sampling noise.

Output
------
- reports/constdf-v1/2026-04-14-DF-re-independence-report.md (table + discussion)
- reports/figs/df_fit/{tpms}_L{L}_t{t}_dPu.png (24 per-geometry plots)
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from .fit_df_per_geom import K_S_CELLS, _nnls_momentum, _wls_momentum
from .load_data import load_all

_THIS = Path(__file__).resolve()
_THERMONAS = _THIS.parent.parent
_PROJECT = _THERMONAS.parent

REPORT_MD = _PROJECT / "reports" / "2026-04-14-DF-re-independence-report.md"
FIG_DIR = _PROJECT / "reports" / "figs" / "df_fit"

# Gate thresholds
R_THRESHOLD = 0.30        # |Pearson r| below which residual-Re correlation is considered weak
P_THRESHOLD = 0.05        # p-value above which residual-Re correlation is not significant
DRIFT_THRESHOLD = 0.10    # reference max tolerated drift for Re-binned K / c_F
N_BINS = 3


def _fit_wls(u: np.ndarray, dP: np.ndarray, mu: np.ndarray, rho: np.ndarray,
              L_ch: float) -> tuple[float, float]:
    """WLS fit with NNLS fallback, returning (K, c_F).

    Same fitting procedure as ``fit_df_per_geom._fit_group`` so full-range
    and per-bin results can be compared apples-to-apples.
    """
    inv_K, cF = _wls_momentum(u, dP, mu, rho, L_ch)
    if inv_K < 0.0 or cF < 0.0:
        inv_K, cF = _nnls_momentum(u, dP, mu, rho, L_ch)
    K = 1.0 / inv_K if inv_K > 1e-30 else float("nan")
    return K, cF


def _predict_dP(u: np.ndarray, mu: np.ndarray, rho: np.ndarray,
                 L_ch: float, K: float, c_F: float) -> np.ndarray:
    inv_K = 1.0 / K if np.isfinite(K) and K > 0 else 0.0
    return (inv_K * mu * u + c_F * rho * u ** 2) * L_ch


def _rel_resid(dP_obs: np.ndarray, dP_pred: np.ndarray) -> np.ndarray:
    return (dP_pred - dP_obs) / np.maximum(np.abs(dP_obs), 1e-12)


def _pearson_full(Re: np.ndarray, rel_eps: np.ndarray) -> tuple[float, float]:
    if len(Re) < 3:
        return float("nan"), float("nan")
    r, p = stats.pearsonr(Re, rel_eps)
    return float(r), float(p)


def _bin_fits(u: np.ndarray, dP: np.ndarray, mu: np.ndarray, rho: np.ndarray,
                Re: np.ndarray, L_ch: float):
    """Partition by Re into equal-count bins and fit (K, c_F) on each bin."""
    order = np.argsort(Re)
    n = len(Re)
    Ks: list[float] = []
    cFs: list[float] = []
    ranges: list[tuple[float, float]] = []
    for b in range(N_BINS):
        lo = int(round(b * n / N_BINS))
        hi = int(round((b + 1) * n / N_BINS))
        if hi - lo < 3:
            Ks.append(float("nan"))
            cFs.append(float("nan"))
            ranges.append((float("nan"), float("nan")))
            continue
        idx = order[lo:hi]
        K_b, cF_b = _fit_wls(u[idx], dP[idx], mu[idx], rho[idx], L_ch)
        Ks.append(K_b)
        cFs.append(cF_b)
        ranges.append((float(Re[idx].min()), float(Re[idx].max())))
    return Ks, cFs, ranges


def _drift(values: list[float], reference: float) -> float:
    arr = np.array([v for v in values if np.isfinite(v)])
    if len(arr) < 2 or not np.isfinite(reference) or abs(reference) < 1e-30:
        return float("nan")
    return float((arr.max() - arr.min()) / abs(reference))


def _plot_fit(tpms: str, L: float, t: float,
               u: np.ndarray, dP: np.ndarray, mu: np.ndarray, rho: np.ndarray,
               L_ch: float, K: float, c_F: float, out_path: Path) -> None:
    u_grid = np.linspace(u.min(), u.max(), 200)
    mu_rep = float(np.mean(mu))
    rho_rep = float(np.mean(rho))
    inv_K = 1.0 / K if np.isfinite(K) and K > 0 else 0.0
    dP_grid = (inv_K * mu_rep * u_grid + c_F * rho_rep * u_grid ** 2) * L_ch

    fig, ax = plt.subplots(figsize=(5, 3.5), dpi=120)
    ax.scatter(u, dP, s=28, alpha=0.75, label="CFD")
    ax.plot(u_grid, dP_grid, "r-", lw=1.5,
            label=f"D-F fit\nK={K:.3g} m² c_F={c_F:.3g} 1/m")
    ax.set_xlabel("u (m/s)")
    ax.set_ylabel("ΔP (Pa)")
    ax.set_title(f"{tpms}  L={L:.0f}mm  t={t:.1f}mm  n={len(u)}")
    ax.legend(fontsize=8, loc="best")
    ax.grid(True, ls=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def analyze() -> pd.DataFrame:
    df = load_all()
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    for key, g in df.groupby(["tpms", "L_mm", "t_mm"], sort=False):
        u = g["u_mps"].to_numpy(dtype=float)
        dP = g["dP_Pa"].to_numpy(dtype=float)
        mu = g["mu"].to_numpy(dtype=float)
        rho = g["rho"].to_numpy(dtype=float)
        Re = g["Re"].to_numpy(dtype=float)
        L_mm = float(key[1])
        L_ch = K_S_CELLS * L_mm * 1e-3

        # Full-range fit
        K_full, cF_full = _fit_wls(u, dP, mu, rho, L_ch)

        # Residual-Re Pearson
        dP_pred = _predict_dP(u, mu, rho, L_ch, K_full, cF_full)
        rel_eps = _rel_resid(dP, dP_pred)
        r, p = _pearson_full(Re, rel_eps)

        # Re-bin drift
        K_bins, cF_bins, ranges = _bin_fits(u, dP, mu, rho, Re, L_ch)
        dK = _drift(K_bins, K_full)
        dcF = _drift(cF_bins, cF_full)

        pass_pearson = (np.isfinite(r) and np.isfinite(p)
                        and (abs(r) < R_THRESHOLD or p > P_THRESHOLD))
        pass_drift = (np.isfinite(dK) and np.isfinite(dcF)
                      and dK < DRIFT_THRESHOLD and dcF < DRIFT_THRESHOLD)
        overall = bool(pass_pearson)

        # Save per-geometry ΔP-u plot
        fname = f"{key[0]}_L{int(L_mm)}_t{int(round(key[2]*10)):02d}_dPu.png"
        _plot_fit(key[0], L_mm, key[2], u, dP, mu, rho, L_ch,
                   K_full, cF_full, FIG_DIR / fname)

        records.append({
            "tpms": key[0],
            "L_mm": L_mm,
            "t_mm": float(key[2]),
            "n_points": int(len(Re)),
            "K_full": K_full,
            "c_F_full": cF_full,
            "pearson_r": r,
            "pearson_p": p,
            "pass_pearson": bool(pass_pearson),
            "K_lo": K_bins[0], "K_mid": K_bins[1], "K_hi": K_bins[2],
            "cF_lo": cF_bins[0], "cF_mid": cF_bins[1], "cF_hi": cF_bins[2],
            "dK_over_K": dK,
            "dcF_over_cF": dcF,
            "pass_drift": bool(pass_drift),
            "overall_pass": overall,
            "figure": f"figs/df_fit/{fname}",
        })
    return pd.DataFrame.from_records(records)


def _render_markdown(res: pd.DataFrame) -> str:
    n = len(res)
    n_pass_pearson = int(res["pass_pearson"].sum())
    n_pass_drift = int(res["pass_drift"].sum())

    lines: list[str] = []
    lines.append("---")
    lines.append("type: report")
    lines.append("date: 2026-04-14")
    lines.append("tags: [report, verification, DF, Re-independence, ThermoNAS]")
    lines.append("---")
    lines.append("")
    lines.append("# D-F 闭合 Re 独立性验证报告 (动量方程直接形式)")
    lines.append("")
    lines.append("对 24 个训练几何 (Diamond 12 + Gyroid 12) 用 `ΔP = (μu/K + ρc_F u²)·L_ch` ")
    lines.append("直接在 (u, ΔP) 上做 WLS 拟合(权重 w_i = 1/ΔP_i²,等价于最小化相对 ΔP 误差),")
    lines.append(f"L_ch = {K_S_CELLS} × L_cell。两项检验判断 (K, c_F) 是否真正和 Re 无关。")
    lines.append("")
    lines.append("**方法 A (残差-Re Pearson, 主判据)** — 在全 Re 范围上拟合后,计算每行相对 ")
    lines.append("残差 ε_i = (ΔP_pred,i − ΔP_obs,i) / ΔP_obs,i,对 (ε, Re) 做 Pearson 相关检验。")
    lines.append(f"通过判据:|r| < {R_THRESHOLD} **或** p > {P_THRESHOLD}。残差与 Re 无显著相关 ")
    lines.append("说明 2 参数 D-F 形式在该几何上结构成立。")
    lines.append("")
    lines.append("**方法 B (Re 分 bin 漂移, 信息性)** — 按 Re 切 3 段等数量 bin,各 bin 独立重 ")
    lines.append(f"拟合 (K, c_F),算 ΔK/K_full 和 Δc_F/c_F_full。参考判据:两者均 < {DRIFT_THRESHOLD:.0%}。")
    lines.append("**注意**:分 bin 对小样本(每段 2–9 点)本身噪声很大,drift 不作为硬判据。")
    lines.append("")
    lines.append(f"## 汇总 ({n} 个几何)")
    lines.append("")
    lines.append(f"- 方法 A 通过 (硬判据):**{n_pass_pearson}/{n}**")
    lines.append(f"- 方法 B 通过 (参考):**{n_pass_drift}/{n}**")
    lines.append("")
    lines.append("## 主表")
    lines.append("")
    lines.append("| tpms | L | t | n | K (m²) | c_F (1/m) | Pearson r | p | ΔK/K | Δc_F/c_F | A通过 | B通过 |")
    lines.append("|------|---|---|---|--------|-----------|-----------|---|------|----------|-------|-------|")
    for _, row in res.iterrows():
        lines.append(
            f"| {row['tpms']} | {row['L_mm']:.0f} | {row['t_mm']:.1f} | {row['n_points']} "
            f"| {row['K_full']:.3g} | {row['c_F_full']:.3g} "
            f"| {row['pearson_r']:.3f} | {row['pearson_p']:.3g} "
            f"| {row['dK_over_K']:.3f} | {row['dcF_over_cF']:.3f} "
            f"| {'✓' if row['pass_pearson'] else '✗'} "
            f"| {'✓' if row['pass_drift'] else '✗'} |"
        )
    lines.append("")

    fails = res[~res["overall_pass"]]
    lines.append("## 未通过硬判据的几何")
    lines.append("")
    if fails.empty:
        lines.append("**无** — 全部 24 个几何都通过 Pearson 硬判据。")
    else:
        lines.append(f"共 {len(fails)} 个几何,主要原因见下(|r| 或 p 值):")
        lines.append("")
        for _, row in fails.iterrows():
            lines.append(
                f"- **{row['tpms']} L={row['L_mm']:.0f} t={row['t_mm']:.1f}**: "
                f"Pearson |r|={abs(row['pearson_r']):.2f}, p={row['pearson_p']:.2g}"
            )
    lines.append("")
    lines.append("## 图")
    lines.append("")
    lines.append("每个几何的 ΔP-u 散点叠加 WLS 拟合曲线:")
    lines.append("")
    for _, row in res.iterrows():
        lines.append(
            f"- `{row['tpms']} L={row['L_mm']:.0f} t={row['t_mm']:.1f}`: "
            f"[{row['figure']}]({row['figure']})"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    res = analyze()
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(_render_markdown(res), encoding="utf-8")
    print(f"Wrote {REPORT_MD.relative_to(_PROJECT)}")
    print(f"Wrote {len(res)} figures to {FIG_DIR.relative_to(_PROJECT)}")
    print()

    cols = ["tpms", "L_mm", "t_mm", "pearson_r", "pearson_p",
            "dK_over_K", "dcF_over_cF", "pass_pearson", "pass_drift", "overall_pass"]
    with pd.option_context("display.width", 140, "display.float_format",
                            lambda v: f"{v:.3g}"):
        print(res[cols].to_string(index=False))

    print()
    n = len(res)
    print(f"pass_pearson : {int(res['pass_pearson'].sum())}/{n}")
    print(f"pass_drift   : {int(res['pass_drift'].sum())}/{n}")
    print(f"overall_pass : {int(res['overall_pass'].sum())}/{n}")


if __name__ == "__main__":
    main()
