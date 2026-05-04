"""nu_error_analysis_shanghai.py — Shanghai 16-case Nu prediction error analysis.

Computes:
  Nu_exp  derived from experimental Q + LMTD
  Nu_pred from Gyroid correlation (tpms_calc.nu_from_Re)
  Relative error per case

Plots: 4-panel figure (parity, error-bar, Nu-vs-Re, error histogram).

Output: data/shanghai_nu_error.csv + reports/figs/shanghai_nu_error.png

Method (ε-NTU, water C_max → ∞ limit):
  ε = (T_Ain - T_Aout) / (T_Ain - T_Bin)        (effectiveness, air = C_min)
  NTU = -ln(1 - ε)                              (cross-flow with water-mixed)
  UA = NTU · m_air · cp_air
  A_tot = A_0 · V_HX
  h_eff = UA / A_tot
  Nu_exp = h_eff · D_h / k_air

Rationale: Shanghai water-side has m_water·cp >> m_air·cp (perfect heat sink
limit). Air = C_min. T_Bout ≈ T_Bin (small water ΔT). ε-NTU avoids LMTD
degeneracy when T_Aout ≈ T_Bin (high effectiveness, dT2 → 0).

Assumes air-side dominant resistance (1/h_air >> 1/h_water + R_wall).
"""
from __future__ import annotations

import sys, warnings
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
    geometry as tpms_geometry,
    nu_from_Re,
    air_density, air_viscosity, air_conductivity, air_cp,
)

R_AIR = 287.05

# Shanghai geometry (matches validate_shanghai_3d_real)
TPMS = "Gyroid"
L_CELL = 7.0       # mm
T_WALL = 0.6       # mm
K_S = 16.0
L_DOM = 0.182      # streamwise length (m)
H_DOM = 0.042      # cross-stream height (m)
LZ = 0.042         # depth (m)

# A_FLOW: void cross-section per unit (validate_shanghai_3d_real convention)
N_UNITS = 36
A_FLOW_PER_UNIT = 18.0565e-6
A_FLOW = N_UNITS * A_FLOW_PER_UNIT


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    warnings.filterwarnings('ignore')

    data_path = _PROJECT / 'data' / 'raw_data' / '20260401-上海电气天然气加热器实验工况.xlsx'
    df = pd.read_excel(data_path, engine='openpyxl', sheet_name='Sheet1',
                       header=None, skiprows=2)

    geom = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
    eps = float(geom['epsilon'])
    D_h = float(geom['D_h'])      # m
    A_0 = float(geom['A_0'])      # 1/m (specific area)
    V_HX = L_DOM * H_DOM * LZ
    A_tot = A_0 * V_HX            # m^2
    print(f"Geometry: TPMS={TPMS} L={L_CELL}mm t={T_WALL}mm")
    print(f"          eps={eps:.4f} D_h={D_h*1000:.3f}mm A_0={A_0:.1f} 1/m")
    print(f"          V_HX={V_HX*1e6:.1f} cm^3, A_tot={A_tot:.4f} m^2")
    print()

    rows = []
    for ci in range(16):
        case = ci + 1
        m_air = float(df.iloc[ci, 5])
        T_Ain_C = float(df.iloc[ci, 28])
        T_Aout_C = float(df.iloc[ci, 29])
        P_Ain_g = float(df.iloc[ci, 30])
        T_Bin_C = float(df.iloc[ci, 24])
        T_Bout_C = float(df.iloc[ci, 25])
        Q_exp = float(df.iloc[ci, 33])

        T_Ain = T_Ain_C + 273.15
        T_Aout = T_Aout_C + 273.15
        T_Bin = T_Bin_C + 273.15
        T_Bout = T_Bout_C + 273.15
        P_Ain = 101325.0 + P_Ain_g
        # Use T_inlet for Re convention (matches validate_shanghai_3d_real
        # and ConstDF-v1 training Re definition; memory project_thermonas_c1
        # canon Shanghai Re = [526, 9981]).
        rho_A_in = air_density(T_Ain, P_Ain)
        mu_A_in = air_viscosity(T_Ain)
        u_A = m_air / (rho_A_in * A_FLOW)
        Re_air = rho_A_in * u_A * D_h / mu_A_in

        # Use T_avg for thermophysical props in ε-NTU calc (more representative
        # of mean fluid state across HX)
        T_avg = 0.5 * (T_Ain + T_Aout)
        rho_A = air_density(T_avg, P_Ain)
        mu_A = air_viscosity(T_avg)
        k_A = air_conductivity(T_avg)
        cp_A = air_cp(T_avg)

        # ε-NTU method (water side perfect sink, air = C_min)
        # ε = (T_Ain - T_Aout) / (T_Ain - T_Bin)  for C_max -> infinity
        denom = T_Ain - T_Bin
        if abs(denom) < 1e-9:
            eps_eff = 0.0
        else:
            eps_eff = (T_Ain - T_Aout) / denom
        eps_eff = max(min(eps_eff, 0.999), 0.001)  # clamp for ln stability
        NTU = -np.log(1.0 - eps_eff)
        UA = NTU * m_air * cp_A   # W/K
        h_eff = UA / A_tot         # W/(m^2·K)
        Nu_exp = h_eff * D_h / k_A
        # Keep LMTD diagnostic
        dT1 = T_Ain - T_Bout
        dT2 = T_Aout - T_Bin
        if dT1 * dT2 > 0 and dT1 != dT2:
            LMTD_diag = (dT1 - dT2) / np.log(dT1 / dT2)
        else:
            LMTD_diag = max(dT1, dT2)  # degenerate fallback

        # Predicted Nu from correlation
        # Single-stream convention (post-refit 2026-04-26): pass ε_A = ε/2
        Nu_pred = nu_from_Re(TPMS, Re_air, 0.5 * eps, L_CELL, D_h * 1000)

        err = (Nu_pred - Nu_exp) / Nu_exp * 100 if Nu_exp > 0 else float('nan')

        rows.append(dict(
            case=case, Re=Re_air, u_air=u_A,
            T_Ain_K=T_Ain, T_Aout_K=T_Aout, T_Bin_K=T_Bin, T_Bout_K=T_Bout,
            Q_exp=Q_exp, eps_eff=eps_eff, NTU=NTU, LMTD_diag=LMTD_diag,
            h_eff=h_eff,
            Nu_exp=Nu_exp, Nu_pred=Nu_pred, err_pct=err,
        ))

    out_df = pd.DataFrame(rows)
    print("Per-case Nu analysis (ε-NTU method, air = C_min):")
    print(f"{'Case':>4} {'Re':>6} {'eps':>6} {'NTU':>5} {'Nu_exp':>8} {'Nu_pred':>8} {'err%':>7}")
    for r in rows:
        print(f"  {r['case']:2d}  {r['Re']:6.0f}  {r['eps_eff']:.3f}  "
              f"{r['NTU']:.2f}  {r['Nu_exp']:7.2f}  {r['Nu_pred']:7.2f}  {r['err_pct']:+6.2f}%")

    # Save CSV
    csv_out = _PROJECT / 'data' / 'shanghai_nu_error.csv'
    out_df.to_csv(csv_out, index=False, encoding='utf-8-sig')
    print(f"\nSaved CSV: {csv_out}")

    err = np.array([r['err_pct'] for r in rows])
    rmsre = float(np.sqrt(np.mean(err ** 2)))
    bias = float(np.mean(err))
    maxabs = float(np.max(np.abs(err)))
    print(f"\nSummary statistics:")
    print(f"  RMSRE_Nu      : {rmsre:.2f}%")
    print(f"  mean bias     : {bias:+.2f}%")
    print(f"  max |err_Nu|  : {maxabs:.2f}%")

    # ============================================================
    # 4-panel error analysis figure
    # ============================================================
    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    plt.subplots_adjust(hspace=0.32, wspace=0.30)

    cases = np.array([r['case'] for r in rows])
    Re_arr = np.array([r['Re'] for r in rows])
    Nu_e = np.array([r['Nu_exp'] for r in rows])
    Nu_p = np.array([r['Nu_pred'] for r in rows])

    # 1. Parity plot
    ax = axes[0, 0]
    nu_min = min(Nu_e.min(), Nu_p.min()) * 0.9
    nu_max = max(Nu_e.max(), Nu_p.max()) * 1.05
    ax.plot([nu_min, nu_max], [nu_min, nu_max], 'k--', linewidth=1, label='y=x')
    # ±20% band
    ax.fill_between([nu_min, nu_max], [nu_min*0.8, nu_max*0.8],
                     [nu_min*1.2, nu_max*1.2], color='gray', alpha=0.15,
                     label='±20%')
    sc = ax.scatter(Nu_e, Nu_p, c=Re_arr, cmap='turbo',
                     s=70, edgecolors='black', linewidths=0.6)
    cbar = plt.colorbar(sc, ax=ax)
    cbar.set_label('Re', fontsize=10)
    ax.set_xlabel('Nu (experimental)', fontsize=11)
    ax.set_ylabel('Nu (predicted)', fontsize=11)
    ax.set_title('Parity plot: Nu_pred vs Nu_exp', fontsize=12, fontweight='bold')
    ax.legend(loc='upper left')
    ax.grid(alpha=0.3)
    for c, x, y in zip(cases, Nu_e, Nu_p):
        ax.annotate(str(int(c)), (x, y), fontsize=8, alpha=0.7,
                     xytext=(4, -3), textcoords='offset points')

    # 2. Relative error per case (bar)
    ax = axes[0, 1]
    colors = ['#d62728' if abs(e) > 20 else '#ff7f0e' if abs(e) > 10 else '#2ca02c'
              for e in err]
    ax.bar(cases, err, color=colors, edgecolor='black', linewidth=0.5)
    ax.axhline(0, color='black', linewidth=0.6)
    ax.axhline(rmsre, color='blue', linestyle=':', linewidth=1, label=f'+RMSRE={rmsre:.1f}%')
    ax.axhline(-rmsre, color='blue', linestyle=':', linewidth=1)
    ax.axhline(bias, color='red', linestyle='--', linewidth=1, label=f'bias={bias:+.1f}%')
    ax.set_xlabel('Case index', fontsize=11)
    ax.set_ylabel('err = (Nu_pred - Nu_exp)/Nu_exp × 100 [%]', fontsize=11)
    ax.set_title(f'Relative error per case  (RMSRE={rmsre:.2f}%, bias={bias:+.2f}%)',
                 fontsize=12, fontweight='bold')
    ax.set_xticks(cases)
    ax.legend(loc='upper right')
    ax.grid(alpha=0.3, axis='y')

    # 3. Nu vs Re (both pred + exp)
    ax = axes[1, 0]
    Re_sort = np.argsort(Re_arr)
    ax.plot(Re_arr[Re_sort], Nu_e[Re_sort], 'o-', color='#1f77b4',
             label='experimental (from Q+LMTD)', markersize=8, linewidth=1.5)
    ax.plot(Re_arr[Re_sort], Nu_p[Re_sort], 's--', color='#d62728',
             label='predicted (Gyroid correlation)', markersize=8, linewidth=1.5)
    ax.set_xlabel('Re (=ρ·u·D_h/μ)', fontsize=11)
    ax.set_ylabel('Nu (=h·D_h/k_f)', fontsize=11)
    ax.set_title('Nu vs Re — experimental vs predicted', fontsize=12, fontweight='bold')
    ax.legend(loc='upper left')
    ax.grid(alpha=0.3)
    ax.set_xscale('log')
    ax.set_yscale('log')

    # 4. Error histogram
    ax = axes[1, 1]
    ax.hist(err, bins=8, color='#1f77b4', edgecolor='black', alpha=0.8)
    ax.axvline(0, color='black', linewidth=0.8)
    ax.axvline(bias, color='red', linestyle='--', linewidth=1.5,
               label=f'mean bias={bias:+.2f}%')
    ax.axvline(rmsre, color='blue', linestyle=':', linewidth=1.5,
               label=f'+RMSRE={rmsre:.2f}%')
    ax.axvline(-rmsre, color='blue', linestyle=':', linewidth=1.5)
    ax.set_xlabel('Relative error [%]', fontsize=11)
    ax.set_ylabel('Frequency', fontsize=11)
    ax.set_title('Error distribution', fontsize=12, fontweight='bold')
    ax.legend(loc='upper left')
    ax.grid(alpha=0.3, axis='y')

    fig.suptitle(f'Shanghai 16-case Nu error analysis '
                  f'(Gyroid L={L_CELL}mm, t={T_WALL}mm, eps={eps:.4f})',
                  fontsize=14, fontweight='bold')

    fig_dir = _PROJECT / 'reports' / 'figs'
    fig_dir.mkdir(parents=True, exist_ok=True)
    fig_path = fig_dir / 'shanghai_nu_error.png'
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved figure: {fig_path}")


if __name__ == '__main__':
    main()
