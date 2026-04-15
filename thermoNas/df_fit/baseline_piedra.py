"""
Stage-1 diagnostic baseline (see composed-drifting-melody.md Option C notes).

Piedra et al. 2023 (Fluids 8:312) fit TPMS permeability and Forchheimer
coefficient as a **single-variable power law of porosity alone**:

    K     = A · ε_f ^ B               [m²]
    c_F   = C · ε_f ^ D               [1/m]

Two parameters per output, four parameters per TPMS type total. No L, no t,
no Re. This is the simplest possible surrogate that still has two outputs.

Why build this baseline
-----------------------
Our current 3D-input ensemble MLP has ~1250 parameters and reaches LOO ΔP
MAPE of 12.8 % (Diamond) / 16.9 % (Gyroid). If Piedra's 4-parameter power
law comes anywhere close to that, it means the MLP is not actually making
good use of the extra (L, t) inputs — everything is already latent in ε_f.
If instead Piedra's baseline is clearly worse (e.g. 20 %+), we know the
MLP is learning something non-trivial and it's worth upgrading to a 4D
input (L, t, ε_f, Re) per the Stage-2 plan.

Method
------
Input:  ``data/df_fit/per_geom_fits.csv`` produced by fit_df_per_geom.py.
        One row per (tpms, L, t) with (K, c_F, ε_f, plus CFD rows statistics).

Fit:    In log space → OLS gives the best power-law coefficients.
          log10 K   = log10 A   + B · log10 ε_f
          log10 c_F = log10 C   + D · log10 ε_f

LOO:    Leave out one (L, t) geometry, refit 4 params on remaining 11,
        predict (K, c_F) for the held-out geometry, then use the **raw
        CFD rows** of that held-out geometry to compute per-row ΔP_pred
        via the Darcy-Forchheimer closure:

            ΔP_pred = (μ u / K_pred + ρ c_F_pred u²) · L_ch
            L_ch    = K_S_CELLS · L_cell_m

        Headline LOO metric: mean |ΔP_pred − ΔP_obs| / ΔP_obs across all
        held-out rows, averaged over geometries.

Output
------
- ``reports/constdf-v1/2026-04-14-piedra-baseline.md`` — side-by-side comparison
  table vs the Option-C ensemble numbers loaded from the existing LOO
  report (if that report has been generated).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .fit_df_per_geom import K_S_CELLS
from .load_data import load_all

_THIS = Path(__file__).resolve()
_PROJECT = _THIS.parent.parent.parent

FITS_CSV = _PROJECT / "data" / "df_fit" / "per_geom_fits.csv"
REPORT_MD = _PROJECT / "reports" / "constdf-v1" / "2026-04-14-piedra-baseline.md"


# ===================================================================
# Power-law fit in log space
# ===================================================================

def _fit_power_law(eps_f: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Fit y = A · ε_f ^ B via OLS on log10 values. Returns (A, B)."""
    x_log = np.log10(eps_f)
    y_log = np.log10(y)
    # log y = log A + B · log ε_f → 1D linear regression
    n = len(x_log)
    x_mean = x_log.mean()
    y_mean = y_log.mean()
    denom = np.sum((x_log - x_mean) ** 2)
    if denom < 1e-30:
        return float("nan"), float("nan")
    B = float(np.sum((x_log - x_mean) * (y_log - y_mean)) / denom)
    log_A = float(y_mean - B * x_mean)
    A = 10.0 ** log_A
    return A, B


def _predict(A: float, B: float, eps_f: float) -> float:
    return A * eps_f ** B


# ===================================================================
# Per-TPMS LOO
# ===================================================================

def loo_piedra(fits: pd.DataFrame, rows: pd.DataFrame, tpms: str) -> pd.DataFrame:
    """Leave-one-geometry-out with Piedra 4-parameter power law.

    Returns a DataFrame with per-held-out-geometry ΔP MAPE (on that
    geometry's raw CFD rows).
    """
    sub_fits = fits[fits["tpms"] == tpms].reset_index(drop=True)
    sub_rows = rows[rows["tpms"] == tpms].reset_index(drop=True)
    records: list[dict] = []

    for i, target in sub_fits.iterrows():
        L_out = float(target["L_mm"])
        t_out = float(target["t_mm"])
        eps_f_out = float(target["eps_f"])

        train_fits = sub_fits.drop(index=i).reset_index(drop=True)
        eps_f_train = train_fits["eps_f"].to_numpy(dtype=float)
        K_train = train_fits["K"].to_numpy(dtype=float)
        cF_train = train_fits["c_F"].to_numpy(dtype=float)

        A_K, B_K = _fit_power_law(eps_f_train, K_train)
        A_c, B_c = _fit_power_law(eps_f_train, cF_train)
        K_pred = _predict(A_K, B_K, eps_f_out)
        cF_pred = _predict(A_c, B_c, eps_f_out)

        # Evaluate ΔP on the held-out geometry's raw CFD rows
        held_rows = sub_rows[(sub_rows["L_mm"] == L_out)
                              & (sub_rows["t_mm"] == t_out)]
        u = held_rows["u_mps"].to_numpy(dtype=float)
        dP_obs = held_rows["dP_Pa"].to_numpy(dtype=float)
        mu = held_rows["mu"].to_numpy(dtype=float)
        rho = held_rows["rho"].to_numpy(dtype=float)
        L_ch = K_S_CELLS * L_out * 1e-3
        dP_pred = (mu * u / K_pred + rho * cF_pred * u ** 2) * L_ch
        rel = np.abs(dP_pred - dP_obs) / dP_obs
        dP_mape = float(rel.mean() * 100.0)
        dP_max = float(rel.max() * 100.0)

        records.append({
            "tpms": tpms,
            "L_mm": L_out,
            "t_mm": t_out,
            "eps_f": eps_f_out,
            "n_rows": int(len(held_rows)),
            "K_ref": float(target["K"]),
            "K_pred": K_pred,
            "K_rel_err": abs(K_pred - target["K"]) / abs(target["K"]),
            "cF_ref": float(target["c_F"]),
            "cF_pred": cF_pred,
            "cF_rel_err": abs(cF_pred - target["c_F"]) / abs(target["c_F"]),
            "A_K": A_K, "B_K": B_K, "A_c": A_c, "B_c": B_c,
            "dP_MAPE": dP_mape,
            "dP_max_err": dP_max,
        })

    return pd.DataFrame.from_records(records)


# ===================================================================
# Full-data fit summary
# ===================================================================

def full_fit(fits: pd.DataFrame, tpms: str) -> dict:
    """Fit on ALL 12 geometries for one TPMS. Used for the "in-sample" row
    and to print the final 4-parameter form for the report."""
    sub = fits[fits["tpms"] == tpms]
    eps_f = sub["eps_f"].to_numpy(dtype=float)
    K = sub["K"].to_numpy(dtype=float)
    cF = sub["c_F"].to_numpy(dtype=float)
    A_K, B_K = _fit_power_law(eps_f, K)
    A_c, B_c = _fit_power_law(eps_f, cF)
    return {"A_K": A_K, "B_K": B_K, "A_c": A_c, "B_c": B_c}


# ===================================================================
# Reporting
# ===================================================================

def _render_markdown(loo_all: pd.DataFrame,
                      full: dict[str, dict]) -> str:
    lines: list[str] = []
    lines.append("---")
    lines.append("type: report")
    lines.append("date: 2026-04-14")
    lines.append("tags: [report, surrogate, baseline, Piedra, power-law, DF]")
    lines.append("---")
    lines.append("")
    lines.append("# Piedra-2023 Style Power-Law Baseline vs Option-C MLP")
    lines.append("")
    lines.append("Diagnostic run: fit Piedra's 4-parameter power law ")
    lines.append("(K = A · ε_f^B, c_F = C · ε_f^D) on our per-geometry (K, c_F) values, ")
    lines.append("then LOO-validate on raw CFD rows. If this simple baseline tracks the 3D-input ")
    lines.append("MLP ensemble on LOO ΔP MAPE, the extra (L, t) inputs are not contributing useful ")
    lines.append("information beyond ε_f alone.")
    lines.append("")
    lines.append("## Full-data power laws (for sanity)")
    lines.append("")
    for tpms, f in full.items():
        lines.append(f"**{tpms}**")
        lines.append("")
        lines.append(f"- $K = {f['A_K']:.4g} \\cdot \\varepsilon_f^{{{f['B_K']:.3f}}}$  [m²]")
        lines.append(f"- $c_F = {f['A_c']:.4g} \\cdot \\varepsilon_f^{{{f['B_c']:.3f}}}$  [1/m]")
        lines.append("")

    lines.append("## LOO ΔP MAPE per geometry")
    lines.append("")
    lines.append("| tpms | L | t | n_rows | K_ref | K_pred | \\|ΔK/K\\|% | c_F_ref | c_F_pred | \\|Δc_F/c_F\\|% | ΔP MAPE% | ΔP max% |")
    lines.append("|------|---|---|--------|-------|--------|------------|---------|----------|---------------|----------|---------|")
    for _, r in loo_all.iterrows():
        lines.append(
            f"| {r['tpms']} | {r['L_mm']:.0f} | {r['t_mm']:.1f} | {r['n_rows']} "
            f"| {r['K_ref']:.3g} | {r['K_pred']:.3g} | {r['K_rel_err']*100:.2f} "
            f"| {r['cF_ref']:.4g} | {r['cF_pred']:.4g} | {r['cF_rel_err']*100:.2f} "
            f"| {r['dP_MAPE']:.2f} | {r['dP_max_err']:.2f} |"
        )
    lines.append("")

    lines.append("## Summary: Piedra baseline vs Option-C MLP ensemble")
    lines.append("")
    lines.append("| TPMS | Metric | Piedra baseline | Option-C MLP (prior run) |")
    lines.append("|------|--------|-----------------|--------------------------|")
    prior = {"Diamond": {"dP_MAPE": 12.79, "dP_max": 18.3,
                          "K_err": 18.05, "cF_err": 16.43},
             "Gyroid":  {"dP_MAPE": 16.95, "dP_max": 24.0,
                          "K_err": 11.78, "cF_err": 19.35}}
    for tpms, group in loo_all.groupby("tpms"):
        p = prior.get(tpms, {})
        lines.append(
            f"| {tpms} | LOO ΔP MAPE | **{group['dP_MAPE'].mean():.2f}%** "
            f"| {p.get('dP_MAPE', 'n/a')}% |")
        lines.append(
            f"| {tpms} | LOO ΔP max  | {group['dP_MAPE'].max():.2f}% "
            f"| {p.get('dP_max', 'n/a')}% |")
        lines.append(
            f"| {tpms} | LOO K MAPE  | {group['K_rel_err'].mean()*100:.2f}% "
            f"| {p.get('K_err', 'n/a')}% |")
        lines.append(
            f"| {tpms} | LOO c_F MAPE| {group['cF_rel_err'].mean()*100:.2f}% "
            f"| {p.get('cF_err', 'n/a')}% |")
    lines.append("")
    lines.append("## 决策门")
    lines.append("")
    lines.append("- **Piedra ≈ MLP (差 < 2 个百分点)** → MLP 对 (L, t) 没有真正利用 → 证据支持 ")
    lines.append("  Stage-2 加 Re 输入(因为 MLP 容量还够,只是缺信息)")
    lines.append("- **Piedra 明显更差 (差 > 5 个百分点)** → MLP 学到 (L, t) 非平凡贡献 → Stage-2 ")
    lines.append("  加 Re 输入仍有道理,但注意不要破坏 (L, t) 的学习")
    lines.append("- **Piedra 明显更好** → 异常,MLP 在过拟合或训练失败 → 检查 Option-C 代码")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    if not FITS_CSV.exists():
        raise SystemExit(
            f"Missing {FITS_CSV}. Run thermoNas.df_fit.fit_df_per_geom first."
        )
    fits = pd.read_csv(FITS_CSV)
    print(f"Loaded {len(fits)} per-geometry fits from "
          f"{FITS_CSV.relative_to(_PROJECT)}")

    rows = load_all()
    print(f"Loaded {len(rows)} raw CFD rows from training Excel")
    print()

    full: dict[str, dict] = {}
    loo_frames: list[pd.DataFrame] = []
    for tpms in ["Diamond", "Gyroid"]:
        full[tpms] = full_fit(fits, tpms)
        f = full[tpms]
        print(f"[{tpms}] full-data power law:")
        print(f"  K    = {f['A_K']:.4g} * eps_f^{f['B_K']:.3f}")
        print(f"  c_F  = {f['A_c']:.4g} * eps_f^{f['B_c']:.3f}")

        loo = loo_piedra(fits, rows, tpms)
        loo_frames.append(loo)
        print(f"  LOO ΔP MAPE    = {loo['dP_MAPE'].mean():6.2f}% "
              f"(max {loo['dP_MAPE'].max():.1f}%)")
        print(f"  LOO K  MAPE    = {loo['K_rel_err'].mean()*100:6.2f}% "
              f"(max {loo['K_rel_err'].max()*100:.1f}%)")
        print(f"  LOO c_F MAPE   = {loo['cF_rel_err'].mean()*100:6.2f}% "
              f"(max {loo['cF_rel_err'].max()*100:.1f}%)")
        print()

    loo_all = pd.concat(loo_frames, ignore_index=True)
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(_render_markdown(loo_all, full), encoding="utf-8")
    print(f"Wrote {REPORT_MD.relative_to(_PROJECT)}")


if __name__ == "__main__":
    main()
