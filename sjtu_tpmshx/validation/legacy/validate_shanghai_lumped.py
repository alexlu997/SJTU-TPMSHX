"""validate_shanghai_lumped.py — Shanghai 16-case Q via lumped ε-NTU
forward prediction + per-case error figure + dual-side Nu derivation.

Pipeline (5 algebraic steps, no spatial discretisation):
  1. Re_air = ρ_A·u·D_h/μ_A                            (inlet T props)
  2. Nu_air = nu_from_Re(TPMS, Re_air, ε/2, L, D_h_mm) (incl. ×1.28 roughness)
  3. h_air  = Nu_air · k_A / D_h
  4. NTU    = h_air · A_tot / (m_air · cp_air),  ε_eff = 1 − exp(−NTU)
  5. Q_pred = ε_eff · m_air·cp_air · (T_Ain − T_Bin)

Water-side Nu is derived from the SAME correlation form by substituting
water Pr (Pr enters as Pr^(1/3) factor, Re uses water properties):
  Nu_water = (Pr_water/Pr_air)^(1/3) · base_correlation_at(Re_water, ε_f, geom)
This gives a coarse Nu_water for documentation; not used in Q calc since
water side is treated as C_max → ∞ in this lumped formulation.

Outputs:
  data/shanghai_validation_lumped.csv         (per-case)
  reports/figs/shanghai_lumped_error.png      (4-panel error analysis)
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
    geometry as tpms_geometry, nu_from_Re,
    air_density, air_viscosity, air_conductivity, air_cp,
    water_density, water_viscosity, water_conductivity, water_cp,
    P_atm, Pr as Pr_AIR,
)

# Shanghai geometry (matches validate_shanghai_aligned + validate_shanghai_3d_real)
TPMS = "Gyroid"
L_CELL = 7.0       # mm
T_WALL = 0.6       # mm
K_S = 16.0
L_DOM = 0.182      # m, streamwise length
H_DOM = 0.042      # m, cross-stream height
LZ    = 0.042      # m, depth (water-direction)

N_UNITS = 36
A_FLOW_PER_UNIT = 18.0565e-6   # m² per channel (single-stream void)
A_FLOW = N_UNITS * A_FLOW_PER_UNIT


def _nu_water_via_pr_subst(Re_w: float, eps_f: float, L_mm: float,
                            D_h_mm: float, Pr_w: float) -> float:
    """Derive water-side Nu by substituting Pr_water into the same Nu form.

    nu_from_Re bakes in Pr_air (=0.72) via Pr^(1/3) factor. To get water
    Nu at the same TPMS surface we re-scale by (Pr_w/Pr_air)^(1/3) and
    pass water Re — coarse but standard Reynolds-analogy approach.
    """
    Nu_air_form = nu_from_Re(TPMS, Re_w, eps_f, L_mm, D_h_mm)
    return Nu_air_form * (Pr_w / Pr_AIR) ** (1.0/3.0)


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
    EPS = float(g['epsilon'])
    EPS_A = float(g['epsilon_A'])
    D_H = float(g['D_h'])         # m
    A_0 = float(g['A_0'])         # 1/m
    V_HX = L_DOM * H_DOM * LZ
    A_tot = A_0 * V_HX             # m²

    print(f"Shanghai lumped ε-NTU validation")
    print(f"  TPMS={TPMS}  L={L_CELL}mm  t={T_WALL}mm  ε={EPS:.4f}")
    print(f"  D_h={D_H*1000:.3f}mm  A_0={A_0:.1f} 1/m  A_tot={A_tot:.4f}m²")
    print()

    data_path = (_PROJECT / 'data' / 'raw_data'
                 / '20260401-上海电气天然气加热器实验工况.xlsx')
    df = pd.read_excel(data_path, sheet_name='Sheet1', engine='openpyxl',
                       header=None, skiprows=2)

    rows = []
    print(f"{'Case':>4} {'Re_A':>6} {'Nu_A':>5} {'NTU':>5} "
          f"{'ε':>6} {'Q_pred':>7} {'Q_exp':>7} {'err%':>7} "
          f"{'Re_B':>5} {'Nu_B':>5}")
    print("─" * 78)
    for ci in range(16):
        m_air = float(df.iloc[ci, 5])
        T_Ain  = float(df.iloc[ci, 28]) + 273.15
        T_Aout = float(df.iloc[ci, 29]) + 273.15
        P_Ain  = P_atm + float(df.iloc[ci, 30])
        T_Bin  = float(df.iloc[ci, 24]) + 273.15
        T_Bout = float(df.iloc[ci, 25]) + 273.15
        m_water = float(df.iloc[ci, 7])
        Q_exp  = float(df.iloc[ci, 33])

        # ── air side ──
        rho_in_A = air_density(T_Ain, P_Ain)
        mu_in_A  = air_viscosity(T_Ain)
        u_A = m_air / (rho_in_A * A_FLOW)
        Re_A = rho_in_A * u_A * D_H / mu_in_A

        T_avg_A = 0.5 * (T_Ain + T_Aout)
        cp_A = air_cp(T_avg_A)
        k_A  = air_conductivity(T_avg_A)

        Nu_A = nu_from_Re(TPMS, Re_A, EPS_A, L_CELL, D_H * 1000.0)
        h_A = Nu_A * k_A / D_H
        UA = h_A * A_tot
        C_min = m_air * cp_A
        NTU = UA / C_min
        eps_eff = 1.0 - np.exp(-NTU)
        Q_pred = eps_eff * C_min * (T_Ain - T_Bin)
        err = (Q_pred - Q_exp) / Q_exp * 100.0

        # ── water side (derived Nu via Pr substitution; not used in Q) ──
        T_avg_B = 0.5 * (T_Bin + T_Bout)
        rho_B = water_density(T_avg_B)
        mu_B  = water_viscosity(T_avg_B)
        k_B   = water_conductivity(T_avg_B)
        cp_B  = water_cp(T_avg_B)
        Pr_B  = mu_B * cp_B / k_B
        u_B = m_water / (rho_B * A_FLOW)
        Re_B = rho_B * u_B * D_H / mu_B
        Nu_B = _nu_water_via_pr_subst(Re_B, EPS_A, L_CELL,
                                       D_H * 1000.0, Pr_B)
        h_B = Nu_B * k_B / D_H

        rows.append(dict(
            case=ci + 1,
            Re_A=Re_A, Nu_A=Nu_A, h_A=h_A,
            NTU=NTU, eps_eff=eps_eff,
            Q_pred=Q_pred, Q_exp=Q_exp, err_pct=err,
            T_Ain=T_Ain, T_Aout=T_Aout,
            T_Bin=T_Bin, T_Bout=T_Bout,
            m_air=m_air, P_Ain=P_Ain, m_water=m_water,
            Re_B=Re_B, Nu_B=Nu_B, h_B=h_B, Pr_B=Pr_B,
        ))
        print(f"  {ci+1:2d}  {Re_A:6.0f}  {Nu_A:5.1f}  {NTU:5.2f}  "
              f"{eps_eff:.4f}  {Q_pred:7.1f}  {Q_exp:7.1f}  {err:+6.2f}% "
              f"{Re_B:5.0f}  {Nu_B:5.1f}")

    out = pd.DataFrame(rows)
    csv_path = _PROJECT / 'data' / 'shanghai_validation_lumped.csv'
    csv_path.parent.mkdir(exist_ok=True)
    out.to_csv(csv_path, index=False, encoding='utf-8-sig')

    err = out['err_pct'].to_numpy()
    rmsre = float(np.sqrt(np.mean(err**2)))
    bias = float(np.mean(err))
    maxabs = float(np.max(np.abs(err)))
    print()
    print(f"  RMSRE_Q     = {rmsre:.2f}%")
    print(f"  mean bias   = {bias:+.2f}%")
    print(f"  max |err|   = {maxabs:.2f}%")
    print()
    print(f"Saved CSV: {csv_path}")

    # ============================================================
    # 4-panel error analysis figure
    # ============================================================
    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    plt.subplots_adjust(hspace=0.32, wspace=0.30)

    cases = out['case'].to_numpy()
    Re_arr = out['Re_A'].to_numpy()
    Q_e = out['Q_exp'].to_numpy()
    Q_p = out['Q_pred'].to_numpy()

    # 1. Parity plot Q
    ax = axes[0, 0]
    q_min = min(Q_e.min(), Q_p.min()) * 0.9
    q_max = max(Q_e.max(), Q_p.max()) * 1.05
    ax.plot([q_min, q_max], [q_min, q_max], 'k--', lw=1, label='y=x')
    ax.fill_between([q_min, q_max], [q_min*0.9, q_max*0.9],
                     [q_min*1.1, q_max*1.1], color='gray', alpha=0.15,
                     label='±10%')
    sc = ax.scatter(Q_e, Q_p, c=Re_arr, cmap='turbo',
                     s=70, edgecolors='black', linewidths=0.6)
    plt.colorbar(sc, ax=ax, label='Re_air')
    for c, x, y in zip(cases, Q_e, Q_p):
        ax.annotate(str(int(c)), (x, y), fontsize=8, alpha=0.7,
                     xytext=(4, -3), textcoords='offset points')
    ax.set_xlabel('Q_exp [W]', fontsize=11)
    ax.set_ylabel('Q_pred [W]', fontsize=11)
    ax.set_title('Parity plot: Q_pred vs Q_exp (lumped ε-NTU)',
                  fontsize=12, fontweight='bold')
    ax.legend(loc='upper left')
    ax.grid(alpha=0.3)

    # 2. Per-case relative error bar
    ax = axes[0, 1]
    colors = ['#d62728' if abs(e) > 10 else '#ff7f0e' if abs(e) > 5
              else '#2ca02c' for e in err]
    ax.bar(cases, err, color=colors, edgecolor='black', linewidth=0.5)
    ax.axhline(0, color='black', lw=0.6)
    ax.axhline(rmsre, color='blue', ls=':', lw=1, label=f'+RMSRE={rmsre:.2f}%')
    ax.axhline(-rmsre, color='blue', ls=':', lw=1)
    ax.axhline(bias, color='red', ls='--', lw=1, label=f'bias={bias:+.2f}%')
    ax.set_xlabel('Case index', fontsize=11)
    ax.set_ylabel('err = (Q_pred - Q_exp)/Q_exp × 100 [%]', fontsize=11)
    ax.set_title(f'Relative Q error per case (RMSRE={rmsre:.2f}%, '
                  f'bias={bias:+.2f}%, max={maxabs:.2f}%)',
                  fontsize=12, fontweight='bold')
    ax.set_xticks(cases)
    ax.legend(loc='upper right')
    ax.grid(alpha=0.3, axis='y')

    # 3. Q vs Re_air (both pred + exp)
    ax = axes[1, 0]
    isort = np.argsort(Re_arr)
    ax.plot(Re_arr[isort], Q_e[isort], 'o-', color='#1f77b4',
             label='Q_exp (measured)', ms=8, lw=1.5)
    ax.plot(Re_arr[isort], Q_p[isort], 's--', color='#d62728',
             label='Q_pred (lumped ε-NTU)', ms=8, lw=1.5)
    ax.set_xlabel('Re_air', fontsize=11)
    ax.set_ylabel('Q [W]', fontsize=11)
    ax.set_title('Q vs Re — predicted vs measured',
                  fontsize=12, fontweight='bold')
    ax.legend(loc='upper left')
    ax.grid(alpha=0.3)

    # 4. Error histogram
    ax = axes[1, 1]
    ax.hist(err, bins=8, color='#1f77b4', edgecolor='black', alpha=0.8)
    ax.axvline(0, color='black', lw=0.8)
    ax.axvline(bias, color='red', ls='--', lw=1.5,
               label=f'mean bias={bias:+.2f}%')
    ax.axvline(rmsre, color='blue', ls=':', lw=1.5,
               label=f'+RMSRE={rmsre:.2f}%')
    ax.axvline(-rmsre, color='blue', ls=':', lw=1.5)
    ax.set_xlabel('Q relative error [%]', fontsize=11)
    ax.set_ylabel('Frequency', fontsize=11)
    ax.set_title('Error distribution', fontsize=12, fontweight='bold')
    ax.legend(loc='upper left')
    ax.grid(alpha=0.3, axis='y')

    fig.suptitle(f'Shanghai 16-case lumped ε-NTU Q validation '
                  f'({TPMS} L={L_CELL}mm t={T_WALL}mm, ε={EPS:.4f})',
                  fontsize=14, fontweight='bold')

    fig_dir = _PROJECT / 'reports' / 'figs'
    fig_dir.mkdir(parents=True, exist_ok=True)
    fig_path = fig_dir / 'shanghai_lumped_error.png'
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved figure: {fig_path}")


if __name__ == '__main__':
    main()
