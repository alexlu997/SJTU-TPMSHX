"""cross_check_water_nu.py — sanity-check water-side Nu derivation.

Compares `nu_water_from_Re` (Pr-substituted air-fitted correlation, ×1.28)
against literature baselines + direct AM-Gyroid fit:

  Wakao-Kaguei (1982) — packed-bed Nu (general porous media):
    Nu_w = 2 + 1.1 · Re^0.6 · Pr^(1/3)
  Dittus-Boelter (1930)  — turbulent pipe (heating):
    Nu_w = 0.023 · Re^0.8 · Pr^0.4
  Yan [6] 2024 — AM Gyroid HX (direct experimental fit, Gyroid only):
    Nu_w = 0.471 · Re^0.627 · Pr^(1/3)    valid 150 < Re < 3000

Wakao + DB are NOT TPMS-specific (order-of-magnitude bracketing). Yan [6]
IS TPMS-specific and is the project's production water-side correlation
(post-2026-04-29, memory project_water_nu_yan6). If our derived
nu_water_from_Re (Pr-sub Reynolds analogy) tracks Yan [6] reasonably,
the Pr-substitution is defensible as an engineering fallback.

Pr_water is now computed dynamically from Vogel-form water properties
at a representative Shanghai water bulk T ≈ 30°C (was hardcoded 5.0;
audit 2026-05-28 M3).

Outputs:
  reports/figs/nu/water_nu_cross_check.png         (Nu vs Re overlay)
  data/water_nu_cross_check.csv                 (per-Re table)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import (
    geometry as tpms_geometry, nu_from_Re, nu_water_from_Re,
    nu_water_gyroid_yan6,
    water_viscosity, water_cp, water_conductivity,
)

# Shanghai geometry — canonical from configs/shanghai_baseline.json
# (Item 3 / AR8, 2026-05-28).
from configs import load_shanghai_baseline
from domain.compute_config import ComputeConfig
# Audit C3 (2026-05-28): sourced through ComputeConfig.
_SH = load_shanghai_baseline()
_SH_CC = ComputeConfig.from_dict(_SH)
TPMS = _SH_CC.geometry.tpms
L_CELL = _SH_CC.geometry.L_cell_mm
T_WALL = _SH_CC.geometry.t_wall_mm
K_S = _SH_CC.geometry.k_s_W_mK


def wakao_kaguei(Re: float, Pr: float) -> float:
    """Packed-bed Nu (Wakao & Kaguei 1982). Lower bound for porous media."""
    return 2.0 + 1.1 * Re ** 0.6 * Pr ** (1.0 / 3.0)


def dittus_boelter(Re: float, Pr: float) -> float:
    """Turbulent pipe Nu (heating). Valid Re > 4000; below that is laminar.

    For Re < 2300, fully developed laminar pipe Nu ≈ 4.36 (constant Q wall)
    — use `pipe_laminar` for low-Re compare.
    """
    return 0.023 * Re ** 0.8 * Pr ** 0.4


def pipe_laminar(Re: float, Pr: float) -> float:
    """Constant: Nu = 4.36 (fully developed laminar pipe, const-Q wall)."""
    return 4.36


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
    EPS = float(g['epsilon'])
    eps_A = float(g['epsilon_A'])
    eps_f = eps_A   # legacy alias for downstream nu_from_Re signature
    D_H = float(g['D_h'])

    # Shanghai water-side Re range (from validate_shanghai_lumped output)
    Re_w_range = np.array([66, 135, 232, 328, 458, 619, 729, 851, 902,
                            1021, 1125, 1236, 1365, 1467, 1625, 1755])
    # Pr_water: dynamic from Vogel-form water_* at representative Shanghai
    # water bulk T ≈ 30°C (was hardcoded 5.0; M3 fix 2026-05-28).
    T_water_repr_K = 303.15   # ~30°C
    mu_w = float(water_viscosity(T_water_repr_K))
    cp_w = float(water_cp(T_water_repr_K))
    k_w  = float(water_conductivity(T_water_repr_K))
    Pr_water = mu_w * cp_w / k_w
    Pr_air = 0.72
    print(f"  Pr_water (T={T_water_repr_K-273.15:.0f}°C, Vogel μ) = {Pr_water:.2f}")

    rows = []
    for Re in Re_w_range:
        Nu_ours = nu_water_from_Re(TPMS, float(Re), eps_f,
                                    L_CELL, D_H * 1000.0, Pr_water)
        Nu_air_only = nu_from_Re(TPMS, float(Re), eps_f,
                                   L_CELL, D_H * 1000.0)
        Nu_wk = wakao_kaguei(float(Re), Pr_water)
        Nu_db = dittus_boelter(float(Re), Pr_water)
        Nu_pipe = pipe_laminar(float(Re), Pr_water)
        # Yan [6] 2024 direct fit (Gyroid only; valid 150 < Re < 3000)
        if TPMS == 'Gyroid':
            Nu_yan = float(nu_water_gyroid_yan6(float(Re), Pr_water))
        else:
            Nu_yan = float('nan')
        # Lower bound = max(laminar, Dittus-Boelter); upper = Wakao
        Nu_lo = max(Nu_pipe, Nu_db) if Re > 4000 else Nu_pipe
        Nu_hi = Nu_wk
        rows.append(dict(
            Re=Re,
            Nu_ours=Nu_ours,
            Nu_Yan6=Nu_yan,
            Nu_air_at_same_Re=Nu_air_only,
            Nu_Wakao_Kaguei=Nu_wk,
            Nu_Dittus_Boelter=Nu_db,
            Nu_pipe_laminar=Nu_pipe,
            ratio_ours_to_WK=Nu_ours / Nu_wk,
            ratio_ours_to_Yan=(Nu_ours / Nu_yan) if Nu_yan == Nu_yan else float('nan'),
            in_band=(Nu_lo <= Nu_ours <= Nu_hi),
        ))

    df = pd.DataFrame(rows)
    print(f"Cross-check: water Nu (Pr={Pr_water}) on Shanghai water Re range")
    print(f"  TPMS={TPMS} L={L_CELL}mm t={T_WALL}mm ε_f={eps_f:.4f}")
    print()
    print(df.to_string(index=False, float_format=lambda x: f'{x:.2f}'))

    # ── Stats ──
    r_wk_min = df['ratio_ours_to_WK'].min()
    r_wk_max = df['ratio_ours_to_WK'].max()
    n_in = int(df['in_band'].sum())
    n_total = len(df)
    print()
    print(f"  Nu_ours / Nu_WakaoKaguei  range = [{r_wk_min:.2f}, {r_wk_max:.2f}]")
    print(f"  In band [pipe_laminar/turb, Wakao]: {n_in}/{n_total}")
    print()
    if n_in == n_total:
        print("  → Nu_ours within physical bracketing band ✓ defensible")
    elif r_wk_max < 1.0:
        print("  → Nu_ours below Wakao (TPMS smoother than packed bed) — "
              "expected")
    else:
        print("  → Nu_ours overshoots Wakao — review")

    csv_path = _PROJECT / 'data' / 'water_nu_cross_check.csv'
    csv_path.parent.mkdir(exist_ok=True)
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"\nSaved CSV: {csv_path}")

    # ── Figure ──
    fig, ax = plt.subplots(figsize=(9, 6))
    # Bracket band: lower = max(pipe lam, Dittus-Boelter), upper = Wakao
    Nu_lo_band = np.maximum(df['Nu_pipe_laminar'].to_numpy(),
                              df['Nu_Dittus_Boelter'].to_numpy())
    ax.fill_between(df['Re'], Nu_lo_band, df['Nu_Wakao_Kaguei'],
                     color='gray', alpha=0.15,
                     label='Physical band (pipe lam – Wakao packed bed)')
    ax.plot(df['Re'], df['Nu_ours'], 'o-', color='#d62728', lw=2, ms=8,
             label=f'Ours: Pr-subst. (Pr_w={Pr_water:.2f}, ×1.28 rough)')
    if TPMS == 'Gyroid':
        ax.plot(df['Re'], df['Nu_Yan6'], '*-', color='#ff7f0e', lw=2, ms=10,
                 label='Yan [6] 2024 (AM Gyroid direct fit, production)')
    ax.plot(df['Re'], df['Nu_Wakao_Kaguei'], 's--', color='#1f77b4',
             lw=1.5, ms=7, label='Wakao-Kaguei 1982 (packed bed, upper)')
    ax.plot(df['Re'], df['Nu_Dittus_Boelter'], '^--', color='#2ca02c',
             lw=1.5, ms=7, label='Dittus-Boelter (turb pipe, Re>4000)')
    ax.plot(df['Re'], df['Nu_pipe_laminar'], '-.', color='#9467bd',
             lw=1.2, label='Pipe laminar Nu=4.36 (low-Re floor)')
    ax.plot(df['Re'], df['Nu_air_at_same_Re'], 'd:', color='gray',
             lw=1.2, ms=6, alpha=0.7,
             label='Same correlation, Pr_air (no Pr-subst)')
    ax.set_xlabel('Re_water', fontsize=12)
    ax.set_ylabel('Nu_water', fontsize=12)
    ax.set_title(f'Water-side Nu cross-check (Pr={Pr_water:.2f}, '
                  f'TPMS={TPMS} L={L_CELL}mm t={T_WALL}mm)',
                  fontsize=13, fontweight='bold')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(alpha=0.3)
    ax.set_xscale('log')
    ax.set_yscale('log')

    fig_dir = _PROJECT / 'reports' / 'figs' / 'nu'
    fig_dir.mkdir(parents=True, exist_ok=True)
    fig_path = fig_dir / 'water_nu_cross_check.png'
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved figure: {fig_path}")


if __name__ == '__main__':
    main()
