"""validate_shanghai_lumped_v3.py — Shanghai 16-case Q via lumped ε-NTU
using v3 (CFD4) Nu predictions, comparing two paths:

  A. Pure S8 closed-form (Gyroid 7p, LOO 17.38%, no ×1.28)
  C. S8 + Gradient Boosting (data-driven, LOO 11.47%, no ×1.28)

Pipeline (no ×1.28, smooth-wall Nu only):
  1. Re_A = ρ_A·u·D_h/μ_A
  2. Nu_A = predict(Re_A, ε_f, L=7, D_h, t=0.6)   ← method A or C
  3. h_A = Nu_A·k_A/D_h
  4. NTU = h_A·A_tot/(m·cp); ε_eff = 1 − exp(−NTU)
  5. Q_pred = ε_eff·m·cp·(T_Ain − T_Bin)

Outputs both A + C results in single CSV / figure for direct comparison.
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
    geometry as tpms_geometry,
    air_density, air_viscosity, air_conductivity, air_cp,
    P_atm, Pr as Pr_AIR, Sa_mm,
)
from df_fit.fit_nu_single_stream import load_data

# ── Shanghai geom (matches existing scripts) ──
TPMS = "Gyroid"
L_CELL = 7.0
T_WALL = 0.6
K_S = 16.0
L_DOM, H_DOM, LZ = 0.182, 0.042, 0.042
N_UNITS = 36
A_FLOW_PER_UNIT = 18.0565e-6
A_FLOW = N_UNITS * A_FLOW_PER_UNIT


# ── Method A: 3p pure power-law (试验记录表_v3.1 fit, user-locked 2026-04-28) ──
# Form: Nu = c · Pr^(1/3) · Re^a · (D_h/L)^d    (Pr=0.72 air const explicit)
# Both Diamond + Gyroid use Nu_pre_deepseek column from xlsx.
NU3_GYROID = dict(c=0.126, a=0.7898, d=0.2409)
NU3_DIAMOND = dict(c=0.0944, a=0.8273, d=0.226)


def nu_4p(Re, eps_f, L_mm, D_h_mm, tpms='Gyroid'):
    """Kept name for back-compat; now 3p pure power-law + explicit Pr^(1/3)."""
    del eps_f
    p = NU3_GYROID if tpms == 'Gyroid' else NU3_DIAMOND
    return (p['c'] * Pr_AIR ** (1/3)
            * max(Re, 1.0) ** p['a'] * (D_h_mm / L_mm) ** p['d'])


# Backwards-compat alias
def nu_S8_gyroid(Re, eps_f, L_mm, D_h_mm, t_mm):
    return nu_4p(Re, eps_f, L_mm, D_h_mm, 'Gyroid')


# ── Method C: Gradient Boosting on log-features ──
def build_gb_predictor():
    """Train GB on full Gyroid CFD4 dataset; return predict(Re, eps_f, L, D, t) -> Nu."""
    from sklearn.ensemble import GradientBoostingRegressor
    d = load_data('Gyroid')
    Re = d['Re_fit'].to_numpy()
    eps_f = d['eps_f'].to_numpy()
    L = d['L_mm'].to_numpy()
    D = d['D_h_mm'].to_numpy()
    t = d['t'].to_numpy()
    X = np.column_stack([np.log(Re), np.log(eps_f),
                         np.log(L / (1000 * Sa_mm)),
                         np.log(D / (1000 * Sa_mm)),
                         np.log(t / (1000 * Sa_mm))])
    y = np.log(d['Nu'].to_numpy())
    gb = GradientBoostingRegressor(n_estimators=300, max_depth=4,
                                    learning_rate=0.05, random_state=42)
    gb.fit(X, y)
    print(f"  GB trained on {len(d)} Gyroid rows, "
          f"in-sample log-MSE={np.mean((gb.predict(X)-y)**2):.4f}")

    def predict(Re_v, eps_f_v, L_mm, D_h_mm, t_mm):
        Xp = np.array([[np.log(max(Re_v, 1.0)),
                         np.log(eps_f_v),
                         np.log(L_mm / (1000 * Sa_mm)),
                         np.log(D_h_mm / (1000 * Sa_mm)),
                         np.log(t_mm / (1000 * Sa_mm))]])
        return float(np.exp(gb.predict(Xp)[0]))
    return predict


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
    EPS = float(g['epsilon'])
    EPS_F = float(g['epsilon_A'])  # ε_A: per-stream void fraction (legacy name EPS_F kept for downstream)
    D_H = float(g['D_h'])
    A_0 = float(g['A_0'])
    V_HX = L_DOM * H_DOM * LZ
    A_tot = A_0 * V_HX

    print(f"Shanghai lumped ε-NTU (v3 CFD4, smooth-wall, NO ×1.28)")
    print(f"  TPMS={TPMS}  L={L_CELL}  t={T_WALL}  ε={EPS:.4f}  ε_f={EPS_F:.4f}")
    print(f"  D_h={D_H*1000:.3f}mm  A_tot={A_tot:.4f}m²")
    print()

    # Build GB predictor
    print("Training GB (Method C)...")
    gb_predict = build_gb_predictor()
    print()

    # Load Shanghai cases
    data_path = (_PROJECT / 'data' / 'raw_data'
                 / '20260401-上海电气天然气加热器实验工况.xlsx')
    df = pd.read_excel(data_path, sheet_name='Sheet1', engine='openpyxl',
                       header=None, skiprows=2)

    rows = []
    print(f"{'Case':>4} {'Re_A':>6} | "
          f"{'Nu_A_S8':>7} {'Q_S8':>7} {'errS8%':>7} | "
          f"{'Nu_A_GB':>7} {'Q_GB':>7} {'errGB%':>7} | "
          f"{'Q_exp':>7}")
    print("─" * 100)
    for ci in range(16):
        m_air = float(df.iloc[ci, 5])
        T_Ain = float(df.iloc[ci, 28]) + 273.15
        T_Aout = float(df.iloc[ci, 29]) + 273.15
        P_Ain = P_atm + float(df.iloc[ci, 30])
        T_Bin = float(df.iloc[ci, 24]) + 273.15
        Q_exp = float(df.iloc[ci, 33])

        rho_in_A = air_density(T_Ain, P_Ain)
        mu_in_A = air_viscosity(T_Ain)
        u_A = m_air / (rho_in_A * A_FLOW)
        Re_A = rho_in_A * u_A * D_H / mu_in_A

        T_avg_A = 0.5 * (T_Ain + T_Aout)
        cp_A = air_cp(T_avg_A)
        k_A = air_conductivity(T_avg_A)

        # ── Method A: S8 (smooth) ──
        Nu_A_S8 = nu_S8_gyroid(Re_A, EPS_F, L_CELL, D_H * 1000.0, T_WALL)
        h_S8 = Nu_A_S8 * k_A / D_H
        UA_S8 = h_S8 * A_tot
        C_min = m_air * cp_A
        NTU_S8 = UA_S8 / C_min
        eps_S8 = 1.0 - np.exp(-NTU_S8)
        Q_S8 = eps_S8 * C_min * (T_Ain - T_Bin)
        err_S8 = (Q_S8 - Q_exp) / Q_exp * 100.0

        # ── Method A_rough: S8 × 1.28 ──
        Nu_A_S8r = Nu_A_S8 * 1.28
        h_S8r = Nu_A_S8r * k_A / D_H
        NTU_S8r = h_S8r * A_tot / C_min
        eps_S8r = 1.0 - np.exp(-NTU_S8r)
        Q_S8r = eps_S8r * C_min * (T_Ain - T_Bin)
        err_S8r = (Q_S8r - Q_exp) / Q_exp * 100.0

        # ── Method C: GB ──
        Nu_A_GB = gb_predict(Re_A, EPS_F, L_CELL, D_H * 1000.0, T_WALL)
        h_GB = Nu_A_GB * k_A / D_H
        UA_GB = h_GB * A_tot
        NTU_GB = UA_GB / C_min
        eps_GB = 1.0 - np.exp(-NTU_GB)
        Q_GB = eps_GB * C_min * (T_Ain - T_Bin)
        err_GB = (Q_GB - Q_exp) / Q_exp * 100.0

        rows.append(dict(
            case=ci + 1, Re_A=Re_A,
            Nu_A_S8=Nu_A_S8, NTU_S8=NTU_S8, eps_S8=eps_S8,
            Q_S8=Q_S8, err_S8_pct=err_S8,
            Nu_A_S8r=Nu_A_S8r, eps_S8r=eps_S8r,
            Q_S8r=Q_S8r, err_S8r_pct=err_S8r,
            Nu_A_GB=Nu_A_GB, NTU_GB=NTU_GB, eps_GB=eps_GB,
            Q_GB=Q_GB, err_GB_pct=err_GB,
            Q_exp=Q_exp, T_Ain=T_Ain, T_Bin=T_Bin, m_air=m_air,
        ))
        print(f"  {ci+1:2d}  {Re_A:6.0f} | "
              f"S8 {Nu_A_S8:6.2f} Q {Q_S8:7.1f} ({err_S8:+5.2f}%) | "
              f"S8×1.28 {Nu_A_S8r:6.2f} Q {Q_S8r:7.1f} ({err_S8r:+5.2f}%) | "
              f"Q_exp {Q_exp:7.1f}")

    out = pd.DataFrame(rows)
    csv_path = _PROJECT / 'data' / 'shanghai_validation_lumped_v3.csv'
    csv_path.parent.mkdir(exist_ok=True)
    out.to_csv(csv_path, index=False, encoding='utf-8-sig')

    err_S8 = out['err_S8_pct'].to_numpy()
    err_S8r = out['err_S8r_pct'].to_numpy()
    err_GB = out['err_GB_pct'].to_numpy()
    rmsre_S8 = float(np.sqrt(np.mean(err_S8**2)))
    rmsre_S8r = float(np.sqrt(np.mean(err_S8r**2)))
    rmsre_GB = float(np.sqrt(np.mean(err_GB**2)))
    bias_S8 = float(np.mean(err_S8))
    bias_S8r = float(np.mean(err_S8r))
    bias_GB = float(np.mean(err_GB))
    max_S8 = float(np.max(np.abs(err_S8)))
    max_S8r = float(np.max(np.abs(err_S8r)))
    max_GB = float(np.max(np.abs(err_GB)))

    print()
    print(f"  ── Method A (S8 smooth, no roughness) ──")
    print(f"     RMSRE_Q = {rmsre_S8:.2f}%   bias = {bias_S8:+.2f}%   max|err| = {max_S8:.2f}%")
    print(f"  ── Method A × 1.28 (S8 + roughness factor) ──")
    print(f"     RMSRE_Q = {rmsre_S8r:.2f}%   bias = {bias_S8r:+.2f}%   max|err| = {max_S8r:.2f}%")
    print(f"  ── Method C (Gradient Boosting smooth) ──")
    print(f"     RMSRE_Q = {rmsre_GB:.2f}%   bias = {bias_GB:+.2f}%   max|err| = {max_GB:.2f}%")
    print()
    print(f"Saved CSV: {csv_path}")

    # ── Figure: 4-panel comparison ──
    fig, axes = plt.subplots(2, 2, figsize=(15, 11))
    cases = out['case'].to_numpy()
    Re_arr = out['Re_A'].to_numpy()
    Q_e = out['Q_exp'].to_numpy()
    Q_S8_arr = out['Q_S8'].to_numpy()
    Q_GB_arr = out['Q_GB'].to_numpy()

    # 1. Parity plot
    ax = axes[0, 0]
    q_min = min(Q_e.min(), Q_S8_arr.min(), Q_GB_arr.min()) * 0.9
    q_max = max(Q_e.max(), Q_S8_arr.max(), Q_GB_arr.max()) * 1.05
    ax.plot([q_min, q_max], [q_min, q_max], 'k--', lw=1, label='y=x')
    ax.fill_between([q_min, q_max], [q_min*0.9, q_max*0.9],
                     [q_min*1.1, q_max*1.1], color='gray', alpha=0.15,
                     label='±10%')
    ax.scatter(Q_e, Q_S8_arr, s=80, c='#d62728', edgecolors='black',
               label=f'A: S8 (RMSRE={rmsre_S8:.1f}%)', alpha=0.85)
    ax.scatter(Q_e, Q_GB_arr, s=80, c='#1f77b4', edgecolors='black',
               label=f'C: GB (RMSRE={rmsre_GB:.1f}%)', alpha=0.85, marker='s')
    ax.set_xlabel('Q_exp [W]')
    ax.set_ylabel('Q_pred [W]')
    ax.set_title('Parity — Method A (S8) vs Method C (GB)', fontweight='bold')
    ax.legend(loc='upper left')
    ax.grid(alpha=0.3)

    # 2. Bar errors
    ax = axes[0, 1]
    width = 0.4
    x = np.arange(len(cases))
    ax.bar(x - width/2, err_S8, width, color='#d62728', edgecolor='black',
           label='A: S8')
    ax.bar(x + width/2, err_GB, width, color='#1f77b4', edgecolor='black',
           label='C: GB')
    ax.axhline(0, color='black', lw=0.5)
    ax.axhline(rmsre_S8, color='#d62728', ls=':', lw=1)
    ax.axhline(-rmsre_S8, color='#d62728', ls=':', lw=1)
    ax.axhline(rmsre_GB, color='#1f77b4', ls=':', lw=1)
    ax.axhline(-rmsre_GB, color='#1f77b4', ls=':', lw=1)
    ax.set_xticks(x); ax.set_xticklabels([str(c) for c in cases])
    ax.set_xlabel('Case')
    ax.set_ylabel('err_Q [%]')
    ax.set_title('Per-case error (A vs C)', fontweight='bold')
    ax.legend()
    ax.grid(alpha=0.3, axis='y')

    # 3. Q vs Re_air
    ax = axes[1, 0]
    isort = np.argsort(Re_arr)
    ax.plot(Re_arr[isort], Q_e[isort], 'o-', color='black',
             label='Q_exp', ms=8, lw=1.8)
    ax.plot(Re_arr[isort], Q_S8_arr[isort], 's--', color='#d62728',
             label='A: S8', ms=8, lw=1.4)
    ax.plot(Re_arr[isort], Q_GB_arr[isort], '^--', color='#1f77b4',
             label='C: GB', ms=8, lw=1.4)
    ax.set_xlabel('Re_air')
    ax.set_ylabel('Q [W]')
    ax.set_title('Q vs Re — pred vs exp', fontweight='bold')
    ax.legend(loc='upper left')
    ax.grid(alpha=0.3)

    # 4. Nu_A predicted per Re (just info)
    ax = axes[1, 1]
    Nu_S8_arr = out['Nu_A_S8'].to_numpy()
    Nu_GB_arr = out['Nu_A_GB'].to_numpy()
    ax.plot(Re_arr[isort], Nu_S8_arr[isort], 's-', color='#d62728',
             label='A: S8 Nu_pred', ms=8, lw=1.4)
    ax.plot(Re_arr[isort], Nu_GB_arr[isort], '^-', color='#1f77b4',
             label='C: GB Nu_pred', ms=8, lw=1.4)
    ax.set_xlabel('Re_air')
    ax.set_ylabel(r'$Nu_A = h \cdot D_h / k_f$')
    ax.set_title(f'Predicted Nu (Shanghai L=7,t=0.6 EXTRAP, ε_f={EPS_F:.3f})',
                  fontweight='bold')
    ax.legend(loc='upper left')
    ax.grid(alpha=0.3)

    fig.suptitle(f'Shanghai 16-case Q validation — v3 (CFD4) smooth-wall '
                  f'(NO ×1.28)  Gyroid L=7 t=0.6',
                  fontsize=14, fontweight='bold')
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    fig_dir = _PROJECT / 'reports' / 'figs'
    fig_dir.mkdir(parents=True, exist_ok=True)
    fig_path = fig_dir / 'shanghai_lumped_v3_AC_compare.png'
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    vault = Path(r'D:\Postgraduate\vault\reports\methodology\figs')
    vault.mkdir(parents=True, exist_ok=True)
    plt.savefig(vault / 'shanghai_lumped_v3_AC_compare.png', dpi=150,
                bbox_inches='tight')
    plt.close()
    print(f"Saved figure: {fig_path}")
    print(f"Saved figure: {vault / 'shanghai_lumped_v3_AC_compare.png'}")


if __name__ == '__main__':
    main()
