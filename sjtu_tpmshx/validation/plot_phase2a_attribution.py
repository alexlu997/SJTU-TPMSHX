"""
plot_phase2a_attribution.py — Phase 2-a 三嫌疑归因条形图

Inputs: manual summary of P2-a experiments
Output: vault/reports/2026-04-20-phase2a-attribution.png
"""

from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(r'D:\Postgraduate\vault\reports\2026-04-20-phase2a-attribution.png')

# Waterfall: starting RMSRE_dP → what each contribution changes it to
# Baseline 3D uniform 16 case: 44.52%
# + wall refinement: 38.89%  (-5.63pp = "端部过渡" partial)
# Stops there. 2D baseline 32.34% shown as target reference.

stages = ['3D baseline\n(uniform, no refine)',
          '+ wall refinement\n(6-wall BL)',
          '+ inlet profile\n(parabolic/edge $\\eta$=0.3-0.8)',
          '3D final (P1b-b)\n[current state]',
          '2D baseline\n[target]']
values = [44.52, 38.89, 38.89 - 0.2, 38.89, 32.34]
colors = ['tab:red', 'tab:orange', 'tab:gray', 'tab:blue', 'tab:green']

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

# Left: waterfall
xpos = np.arange(len(stages))
bars = ax1.bar(xpos, values, color=colors, edgecolor='k', linewidth=0.8)
for i, (b, v) in enumerate(zip(bars, values)):
    ax1.text(b.get_x() + b.get_width() / 2, v + 0.5, f"{v:.2f}%",
             ha='center', fontsize=10, fontweight='bold')
ax1.axhline(32.34, color='tab:green', ls='--', lw=1.5, alpha=0.6,
            label='2D baseline 32.34%')
ax1.set_xticks(xpos)
ax1.set_xticklabels(stages, fontsize=9, rotation=15, ha='right')
ax1.set_ylabel('RMSRE_dP [%]')
ax1.set_title('(a) P2-a waterfall — dP RMSRE contribution by fix')
ax1.set_ylim(0, 50)
ax1.grid(True, alpha=0.3, axis='y')
ax1.legend(loc='upper right', fontsize=9)

# Right: three-suspect attribution bar
suspects = ['Manifold maldistrib.\n(inlet profile)',
            'z-secondary flow\n(single-channel sym.)',
            'End transition / BL\n(wall refinement)',
            'Unexplained\n(numerical)']
contributions = [0.5, 0.0, 5.63, 6.55]   # pp each reduces 3D RMSRE_dP
ap_colors = ['tab:red', 'lightgray', 'tab:orange', 'tab:purple']
xp = np.arange(len(suspects))
bars = ax2.bar(xp, contributions, color=ap_colors, edgecolor='k', linewidth=0.8)
for i, (b, v) in enumerate(zip(bars, contributions)):
    ax2.text(b.get_x() + b.get_width() / 2, v + 0.15, f"{v:.2f} pp",
             ha='center', fontsize=10, fontweight='bold')
ax2.set_xticks(xp)
ax2.set_xticklabels(suspects, fontsize=9, rotation=15, ha='right')
ax2.set_ylabel('RMSRE_dP contribution [pp]')
ax2.set_title('(b) Three-suspect attribution (3D Shanghai)')
ax2.set_ylim(0, 8)
ax2.grid(True, alpha=0.3, axis='y')

# Annotate: total gap
total_gap = 44.52 - 32.34
ax2.text(0.02, 0.95,
         f"Total 3D uniform vs 2D: {total_gap:.2f}pp\n"
         f"Explained (wall refine): 5.63pp\n"
         f"Unexplained: 6.55pp -> P2-b manifold",
         transform=ax2.transAxes, fontsize=9,
         verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

fig.suptitle('Phase 2-a — Shanghai dP attribution experiment results', fontsize=13, y=1.00)
fig.tight_layout()
fig.savefig(OUT, dpi=300, bbox_inches='tight')
print(f"Saved: {OUT}")
