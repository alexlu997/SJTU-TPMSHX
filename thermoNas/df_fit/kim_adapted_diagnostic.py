"""
Kim-2026 adapted to our data: 2-term D-F fit on a **low-Re subset** instead
of a 1-term linear fit on the single lowest Re tail.

Motivation
----------
Kim's strict Method 2 (incremental y = m·u through origin) collapsed our
data to 2 points per geometry because Re > 400 is already past strict
Darcy. That's not enough to fit anything meaningful.

The adaptation is: **use 2-parameter D-F WLS on a growing low-Re subset**
rather than 1-parameter linear. This is mathematically equivalent to
Kim's own Method 1 (Forchheimer plot 1/K_app vs Re, linear extrapolation
to Re=0), which he treats as interchangeable with Method 2.

Three stopping criteria are tried (A, B, C). The goal is to see which
one carves out a sensible "viscous-inertial laminar" subset on our data
and to compare the resulting K with the full-range 2-term WLS K_Q1.

Criterion A — Fixed Re cutoff
    Subset = all points with Re < RE_CUTOFF_A.
    Simple, non-adaptive. Good for sanity check against A=1500 which is
    where our hump residual peaked in earlier diagnostics.

Criterion B — Subset MAPE self-consistency
    Start from the lowest 3 points; fit 2-term D-F WLS; record subset MAPE.
    Add one more point, refit. Stop when the subset MAPE exceeds SUBSET_MAPE_B.
    Returns the largest subset that still fits cleanly as a single 2-term
    D-F closure.

Criterion C — Next-point residual
    Start from the lowest 3 points, fit 2-term D-F WLS. Predict the next
    point. If its relative residual > NEXT_REL_C, stop. Otherwise accept
    and refit on the enlarged subset. This is the direct 2-term analog
    of Kim's Method 2.
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

REPORT_MD = _PROJECT / "reports" / "constdf-v1" / "2026-04-15-kim-adapted-diagnostic.md"

RE_CUTOFF_A = 1500.0      # just before the hump peak
SUBSET_MAPE_B = 3.0       # %
NEXT_REL_C = 5.0          # %
MIN_SUBSET = 3            # absolute minimum for a 2-param fit


# ===================================================================
# Subset 2-term fit helper
# ===================================================================

def _subset_wls(u, dP, mu, rho, L_ch) -> tuple[float, float]:
    """2-term D-F WLS on the given subset. NNLS fallback if negative."""
    inv_K, cF = _wls_momentum(u, dP, mu, rho, L_ch)
    if inv_K < 0.0 or cF < 0.0:
        inv_K, cF = _nnls_momentum(u, dP, mu, rho, L_ch)
    return inv_K, cF


def _subset_mape(u, dP, mu, rho, L_ch, inv_K, cF) -> float:
    dP_pred = (inv_K * mu * u + cF * rho * u ** 2) * L_ch
    rel = np.abs(dP_pred - dP) / np.maximum(np.abs(dP), 1e-12)
    return float(rel.mean() * 100.0)


def _predict_next(u_next, mu_next, rho_next, L_ch, inv_K, cF) -> float:
    return float((inv_K * mu_next * u_next + cF * rho_next * u_next ** 2) * L_ch)


# ===================================================================
# Three criteria
# ===================================================================

def criterion_A(u, dP, mu, rho, L_ch, Re) -> tuple[int, float, float, float]:
    """Fixed Re cutoff."""
    mask = Re < RE_CUTOFF_A
    n = int(mask.sum())
    if n < MIN_SUBSET:
        return n, float("nan"), float("nan"), float("nan")
    inv_K, cF = _subset_wls(u[mask], dP[mask], mu[mask], rho[mask], L_ch)
    K = 1.0 / inv_K if inv_K > 1e-30 else float("nan")
    mape = _subset_mape(u[mask], dP[mask], mu[mask], rho[mask], L_ch, inv_K, cF)
    return n, K, cF, mape


def criterion_B(u, dP, mu, rho, L_ch) -> tuple[int, float, float, float]:
    """Grow subset while subset MAPE stays below SUBSET_MAPE_B."""
    n_total = len(u)
    n_keep = MIN_SUBSET
    if n_total < MIN_SUBSET:
        return n_total, float("nan"), float("nan"), float("nan")
    best = None
    while n_keep <= n_total:
        inv_K, cF = _subset_wls(u[:n_keep], dP[:n_keep],
                                  mu[:n_keep], rho[:n_keep], L_ch)
        K = 1.0 / inv_K if inv_K > 1e-30 else float("nan")
        mape = _subset_mape(u[:n_keep], dP[:n_keep], mu[:n_keep],
                             rho[:n_keep], L_ch, inv_K, cF)
        if mape > SUBSET_MAPE_B:
            break
        best = (n_keep, K, cF, mape)
        n_keep += 1
    if best is None:
        # Even the minimum subset fails; fall back to the smallest fit
        inv_K, cF = _subset_wls(u[:MIN_SUBSET], dP[:MIN_SUBSET],
                                  mu[:MIN_SUBSET], rho[:MIN_SUBSET], L_ch)
        K = 1.0 / inv_K if inv_K > 1e-30 else float("nan")
        mape = _subset_mape(u[:MIN_SUBSET], dP[:MIN_SUBSET],
                             mu[:MIN_SUBSET], rho[:MIN_SUBSET],
                             L_ch, inv_K, cF)
        return MIN_SUBSET, K, cF, mape
    return best


def criterion_C(u, dP, mu, rho, L_ch) -> tuple[int, float, float, float]:
    """2-term fit on N points, predict N+1, stop when next-point residual too big."""
    n_total = len(u)
    if n_total < MIN_SUBSET:
        return n_total, float("nan"), float("nan"), float("nan")
    n_keep = MIN_SUBSET
    while n_keep < n_total:
        inv_K, cF = _subset_wls(u[:n_keep], dP[:n_keep],
                                  mu[:n_keep], rho[:n_keep], L_ch)
        next_pred = _predict_next(u[n_keep], mu[n_keep], rho[n_keep], L_ch, inv_K, cF)
        next_obs = dP[n_keep]
        rel = abs(next_pred - next_obs) / abs(next_obs) * 100.0
        if rel > NEXT_REL_C:
            break
        n_keep += 1
    inv_K, cF = _subset_wls(u[:n_keep], dP[:n_keep], mu[:n_keep], rho[:n_keep], L_ch)
    K = 1.0 / inv_K if inv_K > 1e-30 else float("nan")
    mape = _subset_mape(u[:n_keep], dP[:n_keep], mu[:n_keep], rho[:n_keep],
                         L_ch, inv_K, cF)
    return n_keep, K, cF, mape


def _analyze_one(g: pd.DataFrame) -> dict:
    order = np.argsort(g["Re"].to_numpy())
    Re = g["Re"].to_numpy()[order].astype(float)
    u = g["u_mps"].to_numpy()[order].astype(float)
    dP = g["dP_Pa"].to_numpy()[order].astype(float)
    mu = g["mu"].to_numpy()[order].astype(float)
    rho = g["rho"].to_numpy()[order].astype(float)
    L_mm = float(g["L_mm"].iloc[0])
    L_ch = K_S_CELLS * L_mm * 1e-3

    # Full-range reference
    inv_K_full, cF_full = _subset_wls(u, dP, mu, rho, L_ch)
    K_Q1 = 1.0 / inv_K_full if inv_K_full > 1e-30 else float("nan")
    mape_full = _subset_mape(u, dP, mu, rho, L_ch, inv_K_full, cF_full)

    n_A, K_A, cF_A, mape_A = criterion_A(u, dP, mu, rho, L_ch, Re)
    n_B, K_B, cF_B, mape_B = criterion_B(u, dP, mu, rho, L_ch)
    n_C, K_C, cF_C, mape_C = criterion_C(u, dP, mu, rho, L_ch)

    Re_A = float(Re[Re < RE_CUTOFF_A].max()) if n_A >= MIN_SUBSET else float("nan")
    Re_B = float(Re[n_B - 1]) if n_B >= MIN_SUBSET else float("nan")
    Re_C = float(Re[n_C - 1]) if n_C >= MIN_SUBSET else float("nan")

    return {
        "tpms": g["tpms"].iloc[0],
        "L_mm": L_mm,
        "t_mm": float(g["t_mm"].iloc[0]),
        "n_total": len(u),
        "Re_min": float(Re.min()),
        "Re_max": float(Re.max()),
        # Full-range
        "K_Q1": K_Q1,
        "cF_Q1": cF_full,
        "mape_full": mape_full,
        # A
        "n_A": n_A, "Re_up_A": Re_A, "K_A": K_A, "cF_A": cF_A, "mape_A": mape_A,
        # B
        "n_B": n_B, "Re_up_B": Re_B, "K_B": K_B, "cF_B": cF_B, "mape_B": mape_B,
        # C
        "n_C": n_C, "Re_up_C": Re_C, "K_C": K_C, "cF_C": cF_C, "mape_C": mape_C,
        # Ratios
        "KA_over_KQ1": float(K_A / K_Q1) if np.isfinite(K_A) and np.isfinite(K_Q1) else float("nan"),
        "KB_over_KQ1": float(K_B / K_Q1) if np.isfinite(K_B) and np.isfinite(K_Q1) else float("nan"),
        "KC_over_KQ1": float(K_C / K_Q1) if np.isfinite(K_C) and np.isfinite(K_Q1) else float("nan"),
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

    # Print compact table
    cols = ["tpms", "L_mm", "t_mm", "n_total",
            "K_Q1", "mape_full",
            "n_A", "Re_up_A", "K_A", "mape_A", "KA_over_KQ1",
            "n_B", "Re_up_B", "K_B", "mape_B", "KB_over_KQ1",
            "n_C", "Re_up_C", "K_C", "mape_C", "KC_over_KQ1"]
    with pd.option_context("display.width", 210, "display.max_columns", None,
                            "display.float_format", lambda v: f"{v:.4g}"):
        print(out[cols].to_string(index=False))

    print()
    print("Summary (averages across all 24 geometries):")
    for tpms, group in out.groupby("tpms"):
        print(f"  [{tpms}]")
        print(f"    full MAPE   = {group['mape_full'].mean():5.2f}%")
        print(f"    A  n={group['n_A'].mean():4.1f}  K/KQ1={group['KA_over_KQ1'].mean():.3f}  subset MAPE={group['mape_A'].mean():.2f}%")
        print(f"    B  n={group['n_B'].mean():4.1f}  K/KQ1={group['KB_over_KQ1'].mean():.3f}  subset MAPE={group['mape_B'].mean():.2f}%")
        print(f"    C  n={group['n_C'].mean():4.1f}  K/KQ1={group['KC_over_KQ1'].mean():.3f}  subset MAPE={group['mape_C'].mean():.2f}%")

    # Report
    lines: list[str] = []
    lines.append("---")
    lines.append("type: report")
    lines.append("date: 2026-04-15")
    lines.append("tags: [report, diagnostic, Kim-adapted, K_low, two-term-subset]")
    lines.append("---")
    lines.append("")
    lines.append("# Kim 改造版诊断:2-term D-F 子集拟合")
    lines.append("")
    lines.append("对每个几何按 Re 升序,用三种判据找低 Re 子集,然后在子集上做 2-term D-F WLS。")
    lines.append("")
    lines.append(f"- **A. 固定 Re 阈值** Re < {RE_CUTOFF_A:.0f}")
    lines.append(f"- **B. 子集 MAPE 可控**:从最低 3 点开始增加,子集 MAPE 保持 < {SUBSET_MAPE_B:.0f}%")
    lines.append(f"- **C. 新点残差可控**:新加点的预测残差保持 < {NEXT_REL_C:.0f}%")
    lines.append("")
    lines.append("## 主表")
    lines.append("")
    lines.append("| tpms | L | t | n_tot | K_Q1 | 全 MAPE | A n | A Re↑ | A K | A MAPE | K_A/K_Q1 "
                  "| B n | B Re↑ | K_B | B MAPE | K_B/K_Q1 "
                  "| C n | C Re↑ | K_C | C MAPE | K_C/K_Q1 |")
    lines.append("|------|---|---|-------|------|---------|-----|-------|-----|--------|----------|-----|-------|-----|--------|----------|-----|-------|-----|--------|----------|")
    for _, r in out.iterrows():
        lines.append(
            f"| {r['tpms']} | {r['L_mm']:.0f} | {r['t_mm']:.1f} | {r['n_total']} "
            f"| {r['K_Q1']:.3g} | {r['mape_full']:.2f}% "
            f"| {r['n_A']} | {r['Re_up_A']:.0f} | {r['K_A']:.3g} | {r['mape_A']:.2f}% | {r['KA_over_KQ1']:.3f} "
            f"| {r['n_B']} | {r['Re_up_B']:.0f} | {r['K_B']:.3g} | {r['mape_B']:.2f}% | {r['KB_over_KQ1']:.3f} "
            f"| {r['n_C']} | {r['Re_up_C']:.0f} | {r['K_C']:.3g} | {r['mape_C']:.2f}% | {r['KC_over_KQ1']:.3f} |"
        )
    lines.append("")
    lines.append("## 每 TPMS 平均")
    lines.append("")
    for tpms, group in out.groupby("tpms"):
        lines.append(f"### {tpms}")
        lines.append("")
        lines.append(f"- 全范围拟合 MAPE 平均: {group['mape_full'].mean():.2f}%")
        lines.append(f"- A:平均 n={group['n_A'].mean():.1f}, K_A/K_Q1={group['KA_over_KQ1'].mean():.3f}, 子集 MAPE={group['mape_A'].mean():.2f}%")
        lines.append(f"- B:平均 n={group['n_B'].mean():.1f}, K_B/K_Q1={group['KB_over_KQ1'].mean():.3f}, 子集 MAPE={group['mape_B'].mean():.2f}%")
        lines.append(f"- C:平均 n={group['n_C'].mean():.1f}, K_C/K_Q1={group['KC_over_KQ1'].mean():.3f}, 子集 MAPE={group['mape_C'].mean():.2f}%")
        lines.append("")
    lines.append("## 决策")
    lines.append("")
    lines.append("好的判据要满足:")
    lines.append("")
    lines.append("1. **子集大小 ≥ 3 点**(2-term 拟合最少需要 3 个自由度)")
    lines.append("2. **子集 MAPE < 3%**(说明子集内部仍然是「干净」的 D-F 行为)")
    lines.append("3. **K_subset / K_Q1 差异明显**(说明子集真的捕捉了不同的物理区)")
    lines.append("4. **跨 TPMS 稳定**(不同几何的子集大小、K 比值要一致)")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    txt = main()
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    if txt:
        REPORT_MD.write_text(txt, encoding="utf-8")
        print()
        print(f"Wrote {REPORT_MD.relative_to(_PROJECT)}")
