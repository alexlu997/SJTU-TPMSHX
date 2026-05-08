"""plot_shanghai_q_v41.py — Shanghai 16-case Q validation figure for v4.1 Nu fit.

Forward path: Nu_pred (deepseek 3p PL) → h → NTU → ε-NTU → Q_pred.
Reads CSV produced by validate_shanghai_lumped_v3.py and plots:
  - Q_pred vs Q_exp parity
  - per-case relative error bar
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSV = PROJECT_ROOT / "data" / "shanghai_validation_lumped_v3.csv"
VAULT_FIGS = PROJECT_ROOT.parent.parent / "vault" / "reports" / "methodology" / "figs"
REPO_FIGS = PROJECT_ROOT / "reports" / "figs"
VAULT_FIGS.mkdir(parents=True, exist_ok=True)
REPO_FIGS.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(CSV)
print(df.columns.tolist())
print(df.head())

Q_exp = df['Q_exp'].to_numpy()
Q_S8 = df['Q_S8'].to_numpy()
Re = df['Re_A'].to_numpy()
err_S8 = (Q_S8 - Q_exp) / Q_exp * 100

rmsre = float(np.sqrt(np.mean(err_S8**2)))
bias = float(np.mean(err_S8))
mae = float(np.max(np.abs(err_S8)))
print(f"\nMethod A (deepseek 3p PL): RMSRE={rmsre:.2f}% bias={bias:+.2f}% max|err|={mae:.2f}%")

fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

ax = axes[0]
sc = ax.scatter(Q_exp, Q_S8, c=Re, cmap='viridis', s=60, alpha=0.85, edgecolor='black', lw=0.5)
plt.colorbar(sc, ax=ax, label='Re_air')
qmax = max(Q_exp.max(), Q_S8.max()) * 1.05
qmin = min(Q_exp.min(), Q_S8.min()) * 0.95
xs = np.linspace(qmin, qmax, 100)
ax.plot(xs, xs, 'k-', lw=1.2, label='y=x')
ax.plot(xs, xs * 1.05, 'r--', lw=0.9, alpha=0.7, label='±5%')
ax.plot(xs, xs * 0.95, 'r--', lw=0.9, alpha=0.7)
ax.plot(xs, xs * 1.10, 'r:', lw=0.7, alpha=0.5, label='±10%')
ax.plot(xs, xs * 0.90, 'r:', lw=0.7, alpha=0.5)
for i, (qx, qp, c) in enumerate(zip(Q_exp, Q_S8, df['case'].to_numpy())):
    ax.annotate(str(int(c)), (qx, qp), fontsize=7, alpha=0.7,
                xytext=(3, 3), textcoords='offset points')
ax.set_xlabel('Q_exp [W]')
ax.set_ylabel('Q_pred [W]')
ax.set_title(f"Shanghai 16-case Q parity (Nu v4.1 deepseek)\n"
             f"RMSRE={rmsre:.2f}%, bias={bias:+.2f}%, max|err|={mae:.2f}%")
ax.legend(loc='upper left', fontsize=9)
ax.grid(alpha=0.3)
ax.set_xlim(qmin, qmax)
ax.set_ylim(qmin, qmax)

ax = axes[1]
cases = df['case'].to_numpy().astype(int)
colors = ['#d62728' if abs(e) > 5 else ('#ff7f0e' if abs(e) > 3 else '#2ca02c')
          for e in err_S8]
ax.bar(cases, err_S8, color=colors, edgecolor='black', lw=0.4)
ax.axhline(0, color='black', lw=0.6)
ax.axhline(rmsre, color='blue', ls='--', lw=1.0, label=f'+RMSRE {rmsre:.2f}%')
ax.axhline(-rmsre, color='blue', ls='--', lw=1.0)
ax.axhline(5, color='red', ls=':', lw=0.8, alpha=0.6, label='±5%')
ax.axhline(-5, color='red', ls=':', lw=0.8, alpha=0.6)
ax.set_xlabel('Case # (Re_air ascending)')
ax.set_ylabel('Q relative error [%]')
ax.set_title('Per-case Q error (forward Nu→h→ε-NTU→Q)')
ax.set_xticks(cases)
ax.legend(fontsize=9)
ax.grid(alpha=0.3, axis='y')

# Re labels on x-axis (secondary)
ax2 = ax.twiny()
ax2.set_xticks(cases)
ax2.set_xticklabels([f'{int(r)}' for r in Re], rotation=45, ha='left', fontsize=7)
ax2.set_xlabel('Re_air', fontsize=8)
ax2.set_xlim(ax.get_xlim())

fig.suptitle("Shanghai Electric 16-case Q validation — Nu v4.1 (D+G deepseek)",
             fontsize=13)
fig.tight_layout()

for outdir in [VAULT_FIGS, REPO_FIGS]:
    out = outdir / "2026-04-28-shanghai-Q-v4.1-validation.png"
    fig.savefig(out, dpi=140)
    print(f"  saved {out}")
plt.close(fig)
