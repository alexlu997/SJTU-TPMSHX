"""analyze_nu_v41.py — error analysis for v4.1 user-locked Nu fits (deepseek).

Both TPMS use Nu_pre_deepseek column from 试验记录表_整理版_v3.1.xlsx:
  Diamond: Nu = 0.0944 · Pr^(1/3) · Re^0.8273  · (D_h/L)^0.226
  Gyroid:  Nu = 0.126  · Pr^(1/3) · Re^0.7898  · (D_h/L)^0.2409

Evaluates directly on the data they were fit on. Produces:
  - parity plot Nu_pred vs Nu_exp (Diamond + Gyroid)
  - 2x3 panel: per-geom RMSRE bars / residual vs Re / histogram
  - per-geom breakdown table (printed)

Saves figs to vault/reports/methodology/figs/ and reports/figs/.
"""
from __future__ import annotations
import sys
import re
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
XLSX = PROJECT_ROOT / "data" / "raw_data" / "试验记录表_整理版_v3.1.xlsx"
VAULT_FIGS = PROJECT_ROOT.parent.parent / "vault" / "reports" / "methodology" / "figs"
REPO_FIGS = PROJECT_ROOT / "reports" / "figs"
VAULT_FIGS.mkdir(parents=True, exist_ok=True)
REPO_FIGS.mkdir(parents=True, exist_ok=True)

PR_AIR = 0.72
PR13 = PR_AIR ** (1.0 / 3.0)


def nu_pred(tpms: str, Re, D_h_mm, L_mm) -> np.ndarray:
    Re = np.asarray(Re, dtype=float)
    D_h_mm = np.asarray(D_h_mm, dtype=float)
    L_mm = np.asarray(L_mm, dtype=float)
    if tpms == 'Diamond':
        return 0.0944 * PR13 * Re ** 0.8273 * (D_h_mm / L_mm) ** 0.226
    return 0.126 * PR13 * Re ** 0.7898 * (D_h_mm / L_mm) ** 0.2409


HDR_RE = re.compile(r"L=(\d+)mm,\s*t=([\d.]+)mm,\s*ε=([\d.]+)")


def load_geom(sheet: str) -> pd.DataFrame:
    """Load + parse group headers; return rows with L, t, eps, Re, D_h, Nu_exp."""
    df = pd.read_excel(XLSX, sheet_name=sheet, header=None, engine='openpyxl')
    rows = []
    cur_L = cur_t = cur_eps = None
    for _, r in df.iterrows():
        s = str(r.iloc[0])
        m = HDR_RE.search(s)
        if m:
            cur_L, cur_t, cur_eps = float(m.group(1)), float(m.group(2)), float(m.group(3))
            continue
        try:
            Re = float(r.iloc[3])
            D_h = float(r.iloc[4])
            Nu_exp = float(r.iloc[40])  # col 40 (0-idx) = "Nu" header (col AO 1-idx)
        except (ValueError, TypeError):
            continue
        if not (np.isfinite(Re) and np.isfinite(D_h) and np.isfinite(Nu_exp)):
            continue
        rows.append({'L': cur_L, 't': cur_t, 'eps': cur_eps,
                     'Re': Re, 'D_h_mm': D_h, 'Nu_exp': Nu_exp})
    return pd.DataFrame(rows)


def compute_metrics(d: pd.DataFrame, tpms: str) -> pd.DataFrame:
    d = d.copy()
    d['Nu_pred'] = nu_pred(tpms, d['Re'].values, d['D_h_mm'].values, d['L'].values)
    d['rel_err'] = (d['Nu_pred'] - d['Nu_exp']) / d['Nu_exp']
    return d


def overall_stats(d: pd.DataFrame) -> dict:
    e = d['rel_err'].values
    return dict(
        n=len(e),
        rmsre=float(np.sqrt(np.mean(e**2)) * 100),
        bias=float(np.mean(e) * 100),
        max_abs=float(np.max(np.abs(e)) * 100),
    )


def per_geom_stats(d: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (L, t), g in d.groupby(['L', 't']):
        e = g['rel_err'].values
        out.append({
            'L': int(L), 't': float(t),
            'n': len(e),
            'eps': float(g['eps'].iloc[0]),
            'RMSRE_pct': float(np.sqrt(np.mean(e**2)) * 100),
            'bias_pct': float(np.mean(e) * 100),
        })
    return pd.DataFrame(out).sort_values(['L', 't']).reset_index(drop=True)


def plot_parity(dD: pd.DataFrame, dG: pd.DataFrame, savepath: Path):
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2))
    for ax, d, name, color_col in [
        (axes[0], dD, 'Diamond', 'Re'),
        (axes[1], dG, 'Gyroid', 'Re'),
    ]:
        sc = ax.scatter(d['Nu_exp'], d['Nu_pred'], c=d[color_col],
                        cmap='viridis', s=14, alpha=0.75, edgecolor='none')
        plt.colorbar(sc, ax=ax, label='Re')
        nu_max = max(d['Nu_exp'].max(), d['Nu_pred'].max()) * 1.05
        nu_min = min(d['Nu_exp'].min(), d['Nu_pred'].min()) * 0.95
        xs = np.linspace(nu_min, nu_max, 100)
        ax.plot(xs, xs, 'k-', lw=1.2, label='y=x')
        ax.plot(xs, xs * 1.10, 'r--', lw=1.0, alpha=0.7, label='±10%')
        ax.plot(xs, xs * 0.90, 'r--', lw=1.0, alpha=0.7)
        ax.plot(xs, xs * 1.20, 'r:', lw=0.9, alpha=0.6, label='±20%')
        ax.plot(xs, xs * 0.80, 'r:', lw=0.9, alpha=0.6)
        s = overall_stats(d)
        ax.set_xlabel('Nu_exp')
        ax.set_ylabel('Nu_pred')
        ax.set_title(f"{name} (N={s['n']}, RMSRE={s['rmsre']:.2f}%, "
                     f"bias={s['bias']:+.2f}%, max|err|={s['max_abs']:.1f}%)")
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(alpha=0.3)
        ax.set_xlim(nu_min, nu_max)
        ax.set_ylim(nu_min, nu_max)
    fig.suptitle("Nu v4.1 Parity (Diamond + Gyroid both Nu_pre_deepseek)",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(savepath, dpi=140)
    plt.close(fig)
    print(f"  saved {savepath}")


def plot_error_analysis(dD: pd.DataFrame, dG: pd.DataFrame,
                         pgD: pd.DataFrame, pgG: pd.DataFrame,
                         savepath: Path):
    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    for row, (d, pg, name, overall) in enumerate([
        (dD, pgD, 'Diamond', overall_stats(dD)),
        (dG, pgG, 'Gyroid', overall_stats(dG)),
    ]):
        # 1. Per-geom RMSRE bars
        ax = axes[row, 0]
        labels = [f"L={int(r['L'])} t={r['t']:.1f}" for _, r in pg.iterrows()]
        rmsre = pg['RMSRE_pct'].values
        bias = pg['bias_pct'].values
        colors = []
        for rs, bi in zip(rmsre, bias):
            if abs(bi) > 10:
                colors.append('#d62728')
            elif rs > 15:
                colors.append('#ff7f0e')
            else:
                colors.append('#2ca02c')
        ax.bar(range(len(labels)), rmsre, color=colors, edgecolor='black', lw=0.4)
        ax.axhline(overall['rmsre'], color='blue', ls='--', lw=1.2,
                   label=f"overall {overall['rmsre']:.2f}%")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=8)
        ax.set_ylabel('LOO-style RMSRE [%]')
        ax.set_title(f"{name} per-geom RMSRE (locked-coef in-sample)")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3, axis='y')

        # 2. Residual vs Re, color by eps
        ax = axes[row, 1]
        sc = ax.scatter(d['Re'], d['rel_err'] * 100, c=d['eps'],
                        cmap='plasma', s=14, alpha=0.75, edgecolor='none')
        plt.colorbar(sc, ax=ax, label='ε')
        ax.axhline(0, color='black', lw=0.6)
        ax.axhline(10, color='red', ls='--', lw=0.8, alpha=0.7)
        ax.axhline(-10, color='red', ls='--', lw=0.8, alpha=0.7)
        ax.axhline(20, color='red', ls=':', lw=0.7, alpha=0.5)
        ax.axhline(-20, color='red', ls=':', lw=0.7, alpha=0.5)
        ax.set_xscale('log')
        ax.set_xlabel('Re')
        ax.set_ylabel('relative error [%]')
        ax.set_title(f"{name} residual vs Re")
        ax.grid(alpha=0.3, which='both')

        # 3. Histogram
        ax = axes[row, 2]
        e_pct = d['rel_err'].values * 100
        ax.hist(e_pct, bins=30, color='#1f77b4', alpha=0.7, edgecolor='black', lw=0.4)
        ax.axvline(overall['bias'], color='blue', ls='--', lw=1.2,
                   label=f"bias {overall['bias']:+.2f}%")
        ax.axvline(overall['rmsre'], color='red', ls=':', lw=1.0,
                   label=f"±RMSRE {overall['rmsre']:.2f}%")
        ax.axvline(-overall['rmsre'], color='red', ls=':', lw=1.0)
        ax.set_xlabel('relative error [%]')
        ax.set_ylabel('count')
        ax.set_title(f"{name} residual histogram (N={overall['n']})")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3, axis='y')
    fig.suptitle("Nu v4.1 Error Analysis  (Diamond + Gyroid both Nu_pre_deepseek) "
                 " — locked coefficients evaluated in-sample",
                 fontsize=13)
    fig.tight_layout()
    fig.savefig(savepath, dpi=140)
    plt.close(fig)
    print(f"  saved {savepath}")


def main():
    print(f"Loading {XLSX.name}...")
    dD_raw = load_geom('Diamond_汇总')
    dG_raw = load_geom('Gyroid_汇总')
    print(f"  Diamond N={len(dD_raw)}  Gyroid N={len(dG_raw)}")

    dD = compute_metrics(dD_raw, 'Diamond')
    dG = compute_metrics(dG_raw, 'Gyroid')

    sD = overall_stats(dD)
    sG = overall_stats(dG)
    print()
    print("=== Overall ===")
    print(f"  Diamond: N={sD['n']}  RMSRE={sD['rmsre']:.2f}%  "
          f"bias={sD['bias']:+.2f}%  max|err|={sD['max_abs']:.1f}%")
    print(f"  Gyroid:  N={sG['n']}  RMSRE={sG['rmsre']:.2f}%  "
          f"bias={sG['bias']:+.2f}%  max|err|={sG['max_abs']:.1f}%")

    pgD = per_geom_stats(dD)
    pgG = per_geom_stats(dG)
    print()
    print("=== Diamond per-geom ===")
    print(pgD.to_string(index=False))
    print()
    print("=== Gyroid per-geom ===")
    print(pgG.to_string(index=False))

    # save figs to BOTH locations
    for figs_dir in [VAULT_FIGS, REPO_FIGS]:
        plot_parity(dD, dG, figs_dir / "2026-04-28-nu-v4.1-parity.png")
        plot_error_analysis(dD, dG, pgD, pgG,
                             figs_dir / "2026-04-28-nu-v4.1-error-analysis.png")

    # save per-geom CSVs
    out_csv_D = PROJECT_ROOT / "data" / "nu_v4.1_per_geom_Diamond.csv"
    out_csv_G = PROJECT_ROOT / "data" / "nu_v4.1_per_geom_Gyroid.csv"
    pgD.to_csv(out_csv_D, index=False, encoding='utf-8-sig')
    pgG.to_csv(out_csv_G, index=False, encoding='utf-8-sig')
    print(f"\n  saved {out_csv_D}")
    print(f"  saved {out_csv_G}")


if __name__ == '__main__':
    main()
