"""
Kim-2026 style incremental linear fit diagnostic.

For each geometry, sort rows by Re, then incrementally fit dP = m·u·L_ch
(pure linear through origin — no quadratic term) starting from the lowest
Re points. Stop growing the window when the relative residual on the
**new** point exceeds a threshold; the final m is K_1 = μ_mean·L_ch/m,
the "empirical Darcy permeability" in Kim's sense.

Outputs
-------
- Table per geometry: n_linear (number of low-Re points kept),
  Re_upper (largest Re in the linear subset), K_1, and K_Q1 (from the
  full-range 2-term WLS for comparison).
- Ratio K_1/l^2 (normalised by cell size squared) — Kim reports for
  his gyroid/primitive data that K_1/l² ∈ [0.1, 2] × 10⁻³.
- Visual: per-geometry ΔP-u plot with linear subset highlighted.

This is a DIAGNOSTIC — it does not change the surrogate. It tells us
whether a "pure Darcy" subset exists in our Re range and, if yes, what
K_1 looks like per geometry.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .fit_df_per_geom import K_S_CELLS, _wls_momentum
from .load_data import load_all

_THIS = Path(__file__).resolve()
_PROJECT = _THIS.parent.parent.parent

REPORT_MD = _PROJECT / "reports" / "2026-04-15-kim-k1-diagnostic.md"
FIG_DIR = _PROJECT / "reports" / "figs" / "df_fit" / "kim_k1"

# Growth criterion: stop if the NEWLY added point's relative residual
# against the current linear-only fit exceeds this.
REL_THRESHOLD = 0.05   # 5% — Kim does this visually, 5% is a reasonable auto


def _linear_fit_through_origin(u: np.ndarray, dP: np.ndarray) -> float:
    """Fit dP = m·u forced through origin. Returns m. OLS in dP space."""
    num = float(np.sum(u * dP))
    den = float(np.sum(u * u))
    if den < 1e-30:
        return float("nan")
    return num / den


def _incremental_linear_fit(u_sorted: np.ndarray, dP_sorted: np.ndarray,
                              threshold: float = REL_THRESHOLD) -> int:
    """Start with 2 lowest-u points, keep adding until adding the next one
    produces a relative residual > threshold. Returns the number of points
    kept in the linear subset.
    """
    n = len(u_sorted)
    if n < 2:
        return n
    n_keep = 2
    while n_keep < n:
        # Fit linear-only on current subset
        m = _linear_fit_through_origin(u_sorted[:n_keep], dP_sorted[:n_keep])
        # Predict next point
        next_u = u_sorted[n_keep]
        next_dP_obs = dP_sorted[n_keep]
        next_dP_pred = m * next_u
        rel = abs(next_dP_pred - next_dP_obs) / abs(next_dP_obs)
        if rel > threshold:
            break
        n_keep += 1
    return n_keep


def _analyze_one(g: pd.DataFrame) -> dict:
    order = np.argsort(g["Re"].to_numpy())
    Re = g["Re"].to_numpy()[order].astype(float)
    u = g["u_mps"].to_numpy()[order].astype(float)
    dP = g["dP_Pa"].to_numpy()[order].astype(float)
    mu = g["mu"].to_numpy()[order].astype(float)
    rho = g["rho"].to_numpy()[order].astype(float)
    L_mm = float(g["L_mm"].iloc[0])
    L_ch = K_S_CELLS * L_mm * 1e-3

    n_keep = _incremental_linear_fit(u, dP)
    m = _linear_fit_through_origin(u[:n_keep], dP[:n_keep])
    mu_mean = float(np.mean(mu[:n_keep]))
    K_1 = mu_mean * L_ch / m if m > 0 else float("nan")

    # Also run full-range 2-term WLS for comparison
    inv_K, c_F = _wls_momentum(u, dP, mu, rho, L_ch)
    K_Q1 = 1.0 / inv_K if inv_K > 1e-30 else float("nan")

    L_m = L_mm * 1e-3

    return {
        "tpms": g["tpms"].iloc[0],
        "L_mm": L_mm,
        "t_mm": float(g["t_mm"].iloc[0]),
        "eps_f": float(g["eps_f"].iloc[0]),
        "n_total": int(len(g)),
        "n_linear": int(n_keep),
        "Re_lin_min": float(Re[0]),
        "Re_lin_max": float(Re[n_keep - 1]),
        "u_lin_max": float(u[n_keep - 1]),
        "K_1": K_1,
        "K_Q1": K_Q1,
        "K_1_over_K_Q1": float(K_1 / K_Q1) if np.isfinite(K_1) and np.isfinite(K_Q1) else float("nan"),
        "K_1_norm": float(K_1 / L_m ** 2) if np.isfinite(K_1) else float("nan"),
    }


def _plot_one(g: pd.DataFrame, res: dict, out_path: Path) -> None:
    order = np.argsort(g["Re"].to_numpy())
    u = g["u_mps"].to_numpy()[order].astype(float)
    dP = g["dP_Pa"].to_numpy()[order].astype(float)
    n_keep = res["n_linear"]

    fig, ax = plt.subplots(figsize=(5.5, 4), dpi=120)
    ax.scatter(u[n_keep:], dP[n_keep:], s=28, alpha=0.55,
               color="gray", label="inertial region (excluded)")
    ax.scatter(u[:n_keep], dP[:n_keep], s=40, color="tab:blue",
               label=f"Kim linear subset (n={n_keep})")

    if np.isfinite(res["K_1"]):
        # Plot the linear fit line through origin
        u_grid = np.linspace(0, u.max() * 1.05, 100)
        m = res["K_1"] / (K_S_CELLS * res["L_mm"] * 1e-3) * float(
            np.mean(g["mu"].to_numpy())
        )  # dP = m·u → m = μ·L_ch / K_1
        # simpler: just use the fitted slope
        m = _linear_fit_through_origin(u[:n_keep], dP[:n_keep])
        ax.plot(u_grid, m * u_grid, "r--", lw=1.2,
                label=f"$K_1$-fit slope (K₁={res['K_1']:.2e} m²)")

    ax.set_xlabel("u (m/s)")
    ax.set_ylabel("ΔP (Pa)")
    ax.set_title(f"{res['tpms']}  L={res['L_mm']:.0f}mm  t={res['t_mm']:.1f}mm   "
                  f"Re_lin_max={res['Re_lin_max']:.0f}")
    ax.legend(fontsize=8, loc="best")
    ax.grid(True, ls=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    df = load_all()
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    recs: list[dict] = []
    for key, g in df.groupby(["tpms", "L_mm", "t_mm"], sort=False):
        r = _analyze_one(g)
        recs.append(r)
        fname = f"{key[0]}_L{int(key[1])}_t{int(round(key[2]*10)):02d}.png"
        _plot_one(g, r, FIG_DIR / fname)

    out = pd.DataFrame.from_records(recs).sort_values(
        ["tpms", "L_mm", "t_mm"]
    ).reset_index(drop=True)

    cols = ["tpms", "L_mm", "t_mm", "eps_f", "n_total", "n_linear",
            "Re_lin_min", "Re_lin_max", "u_lin_max", "K_1", "K_Q1",
            "K_1_over_K_Q1", "K_1_norm"]
    with pd.option_context("display.width", 160, "display.float_format",
                            lambda v: f"{v:.4g}"):
        print(out[cols].to_string(index=False))

    # Save report
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("---")
    lines.append("type: report")
    lines.append("date: 2026-04-15")
    lines.append("tags: [report, diagnostic, Kim-2026, K_1, linear-subset]")
    lines.append("---")
    lines.append("")
    lines.append("# Kim-2026 K₁ 增量线性拟合诊断")
    lines.append("")
    lines.append("对每个几何:按 Re 升序,从最低 2 个点开始做 ΔP = m·u 过原点线性拟合,")
    lines.append(f"逐点加入直到新点相对残差 > {REL_THRESHOLD*100:.0f}% 时停。剩下的 ")
    lines.append("`n_linear` 个点构成 Kim 意义上的「线性 / viscous-inertial laminar」子集。")
    lines.append("")
    lines.append(f"- `K_1`  = μ̄ · L_ch / m(Kim 方法 2 的近似 Darcy 渗透率)")
    lines.append(f"- `K_Q1` = 2-term WLS 拟合结果(本流水线 per-geom 的 K)")
    lines.append(f"- `K_1/l²` = Kim 用来横向比较的归一化量(他报告 0.1~2 × 10⁻³)")
    lines.append("")
    lines.append("| tpms | L | t | ε_f | n_tot | n_lin | Re_lin_max | u_lin_max (m/s) | K₁ (m²) | K_Q1 (m²) | K₁/K_Q1 | K₁/l² ×10⁻³ |")
    lines.append("|------|---|---|-----|-------|-------|------------|-----------------|---------|-----------|---------|-------------|")
    for _, r in out.iterrows():
        lines.append(
            f"| {r['tpms']} | {r['L_mm']:.0f} | {r['t_mm']:.1f} | {r['eps_f']:.3f} "
            f"| {r['n_total']} | {r['n_linear']} | {r['Re_lin_max']:.0f} "
            f"| {r['u_lin_max']:.2f} | {r['K_1']:.3g} | {r['K_Q1']:.3g} "
            f"| {r['K_1_over_K_Q1']:.2f} | {r['K_1_norm']*1e3:.3f} |"
        )
    lines.append("")
    lines.append("## 图")
    lines.append("")
    lines.append("每几何的 ΔP-u 散点 + 线性子集 + K₁ 拟合线: `reports/figs/df_fit/kim_k1/*.png`")
    lines.append("")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print()
    print(f"Wrote {REPORT_MD.relative_to(_PROJECT)}")
    print(f"Per-geometry plots in {FIG_DIR.relative_to(_PROJECT)}")


if __name__ == "__main__":
    main()
