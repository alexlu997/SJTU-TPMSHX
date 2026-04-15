"""
Kim-2026 adapted via constrained 1-parameter fit.

Approach
--------
The 2-parameter-on-subset approach is ill-conditioned in our Re range,
so drop one degree of freedom:

1. Fit 2-term D-F WLS on the FULL Re range for each geometry.
   This gives (K_Q1, c_F_full).
2. Take c_F_full as the "high-Re anchor". It is well-determined because
   at large Re the u² term dominates.
3. For the low-Re subset (Re < CUTOFF), subtract the Forchheimer
   contribution using c_F_full from each observed ΔP:

       ΔP_darcy,i = ΔP_obs,i − ρ_i · c_F_full · u_i² · L_ch

4. Fit ΔP_darcy = (μ · L_ch / K_1) · u through origin on the low-Re subset
   (1-parameter linear WLS, weight 1/ΔP_obs²).
5. Report K_1 and compare to the full-range K_Q1.

This is Kim's philosophy (low-Re subset + linear fit) applied to our
situation where the "data range is above strict Darcy". The c_F anchor
lets us exploit whatever low-Re leverage we do have without ill-
conditioning.

Three cutoff schemes are tried to see how sensitive K_1 is to the choice:
  - **CUTOFF_REL_ENDS_LOW** = drop the top fraction (30%) of Re points
  - **CUTOFF_RE_1500** = Re < 1500 (near the hump peak)
  - **CUTOFF_RE_1000** = Re < 1000 (stricter)

If K_1 is similar across cutoffs, we have a robust Kim-adapted value.
If it varies a lot, the approach is still unreliable on our data.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .fit_df_per_geom import K_S_CELLS, _nnls_momentum, _wls_momentum
from .load_data import load_all

_THIS = Path(__file__).resolve()
_PROJECT = _THIS.parent.parent.parent

REPORT_MD = _PROJECT / "reports" / "2026-04-15-kim-constrained-diagnostic.md"

MIN_SUBSET = 3


def _full_fit(u, dP, mu, rho, L_ch) -> tuple[float, float]:
    """Full-range 2-term WLS → (K_Q1, c_F_full)."""
    inv_K, cF = _wls_momentum(u, dP, mu, rho, L_ch)
    if inv_K < 0.0 or cF < 0.0:
        inv_K, cF = _nnls_momentum(u, dP, mu, rho, L_ch)
    K = 1.0 / inv_K if inv_K > 1e-30 else float("nan")
    return K, cF


def _k1_constrained(u_sub, dP_sub, mu_sub, rho_sub, L_ch, c_F_full) -> float:
    """Weighted 1-parameter fit of (dP - rho·c_F·u²·L_ch) = (μ·L_ch/K)·u.

    Closed-form WLS with weight w_i = 1/dP_obs,i²:
        slope = Σ(w² · x · y) / Σ(w² · x²)
    where x = μ_i·u_i·L_ch, y = dP_i − ρ_i·c_F_full·u_i²·L_ch,
    and coefficient = 1/K so K = 1/slope.
    """
    if len(u_sub) < 1:
        return float("nan")
    forch = rho_sub * c_F_full * u_sub ** 2 * L_ch
    y = dP_sub - forch
    x = mu_sub * u_sub * L_ch
    w2 = (1.0 / dP_sub) ** 2
    num = float(np.sum(w2 * x * y))
    den = float(np.sum(w2 * x * x))
    if den < 1e-30:
        return float("nan")
    slope = num / den        # this is 1/K
    if slope <= 0:
        return float("nan")
    return 1.0 / slope


def _subset_mape(u, dP, mu, rho, L_ch, K, c_F) -> float:
    """Subset MAPE with given (K, c_F)."""
    if not np.isfinite(K) or K <= 0:
        return float("inf")
    dP_pred = (mu * u / K + c_F * rho * u ** 2) * L_ch
    rel = np.abs(dP_pred - dP) / np.maximum(np.abs(dP), 1e-12)
    return float(rel.mean() * 100.0)


def _analyze_one(g: pd.DataFrame) -> dict:
    order = np.argsort(g["Re"].to_numpy())
    Re = g["Re"].to_numpy()[order].astype(float)
    u = g["u_mps"].to_numpy()[order].astype(float)
    dP = g["dP_Pa"].to_numpy()[order].astype(float)
    mu = g["mu"].to_numpy()[order].astype(float)
    rho = g["rho"].to_numpy()[order].astype(float)
    L_mm = float(g["L_mm"].iloc[0])
    L_ch = K_S_CELLS * L_mm * 1e-3

    K_Q1, c_F_full = _full_fit(u, dP, mu, rho, L_ch)
    full_mape = _subset_mape(u, dP, mu, rho, L_ch, K_Q1, c_F_full)

    # Three cutoff strategies
    # (1) drop top 30% of Re points
    n_30 = max(MIN_SUBSET, int(np.ceil(len(u) * 0.70)))
    K1_30 = _k1_constrained(u[:n_30], dP[:n_30], mu[:n_30], rho[:n_30],
                              L_ch, c_F_full)
    mape_30 = _subset_mape(u[:n_30], dP[:n_30], mu[:n_30], rho[:n_30],
                            L_ch, K1_30, c_F_full)

    # (2) Re < 1500
    mask_1500 = Re < 1500.0
    n_1500 = int(mask_1500.sum())
    if n_1500 >= MIN_SUBSET:
        K1_1500 = _k1_constrained(
            u[mask_1500], dP[mask_1500], mu[mask_1500], rho[mask_1500],
            L_ch, c_F_full,
        )
        mape_1500 = _subset_mape(
            u[mask_1500], dP[mask_1500], mu[mask_1500], rho[mask_1500],
            L_ch, K1_1500, c_F_full,
        )
    else:
        K1_1500 = float("nan")
        mape_1500 = float("nan")

    # (3) Re < 1000
    mask_1000 = Re < 1000.0
    n_1000 = int(mask_1000.sum())
    if n_1000 >= MIN_SUBSET:
        K1_1000 = _k1_constrained(
            u[mask_1000], dP[mask_1000], mu[mask_1000], rho[mask_1000],
            L_ch, c_F_full,
        )
        mape_1000 = _subset_mape(
            u[mask_1000], dP[mask_1000], mu[mask_1000], rho[mask_1000],
            L_ch, K1_1000, c_F_full,
        )
    else:
        K1_1000 = float("nan")
        mape_1000 = float("nan")

    return {
        "tpms": g["tpms"].iloc[0],
        "L_mm": L_mm,
        "t_mm": float(g["t_mm"].iloc[0]),
        "n_total": len(u),
        "Re_min": float(Re.min()),
        "Re_max": float(Re.max()),
        "K_Q1": K_Q1,
        "c_F_full": c_F_full,
        "full_mape": full_mape,
        "n_30": n_30, "K1_drop30": K1_30, "mape_drop30": mape_30,
        "K1_d30_over_KQ1": float(K1_30 / K_Q1) if np.isfinite(K1_30) and np.isfinite(K_Q1) else float("nan"),
        "n_1500": n_1500, "K1_1500": K1_1500, "mape_1500": mape_1500,
        "K1_1500_over_KQ1": float(K1_1500 / K_Q1) if np.isfinite(K1_1500) and np.isfinite(K_Q1) else float("nan"),
        "n_1000": n_1000, "K1_1000": K1_1000, "mape_1000": mape_1000,
        "K1_1000_over_KQ1": float(K1_1000 / K_Q1) if np.isfinite(K1_1000) and np.isfinite(K_Q1) else float("nan"),
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    df = load_all()
    recs: list[dict] = []
    for key, g in df.groupby(["tpms", "L_mm", "t_mm"], sort=False):
        recs.append(_analyze_one(g))

    out = pd.DataFrame.from_records(recs).sort_values(
        ["tpms", "L_mm", "t_mm"]
    ).reset_index(drop=True)

    cols = ["tpms", "L_mm", "t_mm", "n_total", "K_Q1", "c_F_full", "full_mape",
            "n_30", "K1_drop30", "K1_d30_over_KQ1", "mape_drop30",
            "n_1500", "K1_1500", "K1_1500_over_KQ1",
            "n_1000", "K1_1000", "K1_1000_over_KQ1"]
    with pd.option_context("display.width", 210, "display.max_columns", None,
                            "display.float_format", lambda v: f"{v:.4g}"):
        print(out[cols].to_string(index=False))

    print()
    print("Summary:")
    for tpms, group in out.groupby("tpms"):
        print(f"  [{tpms}]")
        print(f"    K1/KQ1 @ drop top 30%  : {group['K1_d30_over_KQ1'].mean():.3f} "
              f"(range {group['K1_d30_over_KQ1'].min():.3f} - {group['K1_d30_over_KQ1'].max():.3f})")
        valid = group.dropna(subset=["K1_1500_over_KQ1"])
        if len(valid) > 0:
            print(f"    K1/KQ1 @ Re<1500       : {valid['K1_1500_over_KQ1'].mean():.3f} "
                  f"(range {valid['K1_1500_over_KQ1'].min():.3f} - {valid['K1_1500_over_KQ1'].max():.3f}, "
                  f"{len(valid)} geoms)")
        valid = group.dropna(subset=["K1_1000_over_KQ1"])
        if len(valid) > 0:
            print(f"    K1/KQ1 @ Re<1000       : {valid['K1_1000_over_KQ1'].mean():.3f} "
                  f"(range {valid['K1_1000_over_KQ1'].min():.3f} - {valid['K1_1000_over_KQ1'].max():.3f}, "
                  f"{len(valid)} geoms)")

    # Write minimal report
    lines: list[str] = []
    lines.append("---")
    lines.append("type: report")
    lines.append("date: 2026-04-15")
    lines.append("tags: [report, diagnostic, Kim-constrained, K_1]")
    lines.append("---")
    lines.append("")
    lines.append("# Kim 改造 v2:固定 c_F,只在低 Re 子集上反推 K_1")
    lines.append("")
    lines.append("### 方法")
    lines.append("")
    lines.append("1. 用**全范围** 2 参数 D-F WLS 拟 (K_Q1, c_F_full)")
    lines.append("2. 低 Re 子集上从 ΔP_obs 里减掉 Forchheimer 贡献: "
                  "ΔP_darcy = ΔP_obs − ρ·c_F_full·u²·L_ch")
    lines.append("3. 在子集上拟 ΔP_darcy = (μ·L_ch/K_1)·u 1 参数过原点 WLS")
    lines.append("4. K_1 = 斜率的倒数乘 μ̄·L_ch")
    lines.append("")
    lines.append("三种子集选法对照:")
    lines.append("")
    lines.append("- **drop30%**:丢掉最高 30% Re 点")
    lines.append("- **Re<1500**:固定 Re 阈值")
    lines.append("- **Re<1000**:更严格阈值")
    lines.append("")
    lines.append("## 主表")
    lines.append("")
    lines.append("| tpms | L | t | n_tot | K_Q1 | c_F_full | 全 MAPE | drop30 n | K₁ | K₁/K_Q1 "
                  "| Re<1500 n | K₁ | K₁/K_Q1 | Re<1000 n | K₁ | K₁/K_Q1 |")
    lines.append("|------|---|---|-------|------|----------|---------|----------|-----|---------|-----------|-----|---------|-----------|-----|---------|")
    for _, r in out.iterrows():
        def fmt(x, fmt_str="{:.3g}"):
            return fmt_str.format(x) if np.isfinite(x) else "—"
        lines.append(
            f"| {r['tpms']} | {r['L_mm']:.0f} | {r['t_mm']:.1f} | {r['n_total']} "
            f"| {fmt(r['K_Q1'])} | {fmt(r['c_F_full'])} | {fmt(r['full_mape'], '{:.2f}%')} "
            f"| {r['n_30']} | {fmt(r['K1_drop30'])} | {fmt(r['K1_d30_over_KQ1'], '{:.3f}')} "
            f"| {r['n_1500']} | {fmt(r['K1_1500'])} | {fmt(r['K1_1500_over_KQ1'], '{:.3f}')} "
            f"| {r['n_1000']} | {fmt(r['K1_1000'])} | {fmt(r['K1_1000_over_KQ1'], '{:.3f}')} |"
        )
    lines.append("")
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print()
    print(f"Wrote {REPORT_MD.relative_to(_PROJECT)}")


if __name__ == "__main__":
    main()
