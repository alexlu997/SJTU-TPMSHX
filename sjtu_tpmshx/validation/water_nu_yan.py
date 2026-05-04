"""water_nu_yan.py — Compute water-side Nu using Yan [6] + Yan [58] correlations.

Diagnostic only — does not alter the SIMPLE / LTNE solver. Reads Shanghai
16-case mass flow + inlet temperature, computes:

  Re_w = rho(T_in) * u * D_h / mu(T_in)
  Pr_w = mu * cp / k
  Nu_Yan6 = 0.471 * Re^0.627 * Pr^(1/3)        (Gyroid exp, Re 150-3000)
  Nu_Yan58_G = 0.606 * Re^0.589 * Pr^0.33       (Gyroid CFD, Re 40-440)
  h_sf = Nu * k / D_h                           [W/m²/K]
  h_v  = h_sf * A_0                             [W/m³/K]

Refs:
  Yan [6]  Appl. Therm. Eng. 241 (2024) 122402 — gyroid AM exp + sim
  Yan [58] Appl. Therm. Eng. 230 (2023) 120748 — 4-geom CFD laminar

D_h convention: 4·ε_A/A_0 (single-stream sheet HX) = 4·V_c/A_s (Yan/Iyer
volumetric form) — mathematically identical, no unit conversion needed.

Usage:  PYTHONPATH=. python validation/water_nu_yan.py
"""
from __future__ import annotations
import sys
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

from solvers.tpms_calc import (
    geometry as tpms_geometry,
    water_density, water_viscosity, water_conductivity, water_cp,
    Sa_mm as _Sa_mm,
)


# ── Geometry ─────────────────────────────────────────────────────
TPMS, L_CELL, T_WALL, K_S = 'Gyroid', 7.0, 0.6, 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = float(g['epsilon'])
EPS_A = float(g['epsilon_A'])
D_H = float(g['D_h'])
A_0 = float(g['A_0'])

# Shanghai prototype: 36 parallel channels
N_UNITS = 36
A_FLOW_PER_UNIT = 18.0565e-6   # ε_A · L_cell² (m²)
A_FLOW = N_UNITS * A_FLOW_PER_UNIT


# ── Yan correlations ─────────────────────────────────────────────
def nu_yan6_gyroid(Re: float, Pr: float) -> float:
    """Yan et al 2024 [6] — Gyroid water exp + sim, Re 150-3000."""
    return 0.471 * Re ** 0.627 * Pr ** (1.0 / 3.0)


def nu_yan58_gyroid(Re: float, Pr: float) -> float:
    """Yan et al 2023 [58] — Gyroid water CFD laminar, Re 40-440."""
    return 0.606 * Re ** 0.589 * Pr ** 0.33


def nu_yan58_diamond(Re: float, Pr: float) -> float:
    """Yan et al 2023 [58] — Diamond water CFD laminar, Re 40-380."""
    return 0.683 * Re ** 0.56 * Pr ** 0.33


def nu_code_legacy(Re: float, Pr: float, eps: float, L_mm: float) -> float:
    """Project current code h_vB Nu (validate_shanghai_aligned.py:159-161).

    'Legacy Gyroid pre-2026-04-26 full-eps form with water Pr substituted.'
    Used for h_vB in Shanghai aligned validation.
    """
    Re_safe = max(Re, 1.0)
    n = 0.177 * Re_safe ** 0.1 * eps ** (-2.0 / 3.0)
    Nu = (0.17 * Pr ** (1.0 / 3.0) * Re_safe ** n * eps ** 2.25
          * (L_mm / (1000.0 * _Sa_mm)) ** (-2.01))
    return Nu


# ── Main ─────────────────────────────────────────────────────────
def main():
    DATA_PATH = (r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data'
                 r'\20260401-上海电气天然气加热器实验工况.xlsx')
    df = pd.read_excel(DATA_PATH, engine='openpyxl', sheet_name='Sheet1',
                       header=None, skiprows=2)

    print(f"Geometry: {TPMS} L={L_CELL}mm t={T_WALL}mm")
    print(f"  ε={EPS:.4f}  ε_A={EPS_A:.4f}  D_h={D_H*1000:.3f}mm  "
          f"A_0={A_0:.1f}m²/m³  A_flow={A_FLOW*1e6:.1f}mm²\n")

    rows = []
    for ci in range(16):
        m_w = float(df.iloc[ci, 7])
        T_in_K = float(df.iloc[ci, 24]) + 273.15

        rho = float(water_density(T_in_K))
        mu = float(water_viscosity(T_in_K))
        cp = float(water_cp(T_in_K))
        k = float(water_conductivity(T_in_K))

        u = m_w / (rho * A_FLOW)
        Re = rho * u * D_H / mu
        Pr = mu * cp / k

        # Yan [6] gyroid (covers Re 150-3000)
        Nu_Y6 = nu_yan6_gyroid(Re, Pr)
        in_range_Y6 = 150.0 <= Re <= 3000.0
        h_sf_Y6 = Nu_Y6 * k / D_H
        h_v_Y6 = h_sf_Y6 * A_0

        # Yan [58] gyroid (covers Re 40-440)
        Nu_Y58_G = nu_yan58_gyroid(Re, Pr)
        in_range_Y58_G = 40.0 <= Re <= 440.0
        h_sf_Y58_G = Nu_Y58_G * k / D_H
        h_v_Y58_G = h_sf_Y58_G * A_0

        # Project current code Nu (legacy form used in validate_shanghai_aligned)
        Nu_code = nu_code_legacy(Re, Pr, EPS, L_CELL)
        h_sf_code = Nu_code * k / D_H
        h_v_code = h_sf_code * A_0

        rows.append({
            'case':        ci + 1,
            'T_in_C':      T_in_K - 273.15,
            'mu_mPas':     mu * 1e3,
            'Re_w':        Re,
            'Pr_w':        Pr,
            'Nu_code':     Nu_code,
            'h_v_code':    h_v_code,
            'Nu_Yan6':     Nu_Y6,
            'in_Yan6':     in_range_Y6,
            'h_v_Yan6':    h_v_Y6,
            'err_Yan6_pct': (Nu_Y6 / Nu_code - 1) * 100,
            'Nu_Yan58_G':  Nu_Y58_G,
            'in_Yan58_G':  in_range_Y58_G,
            'h_v_Yan58_G': h_v_Y58_G,
            'err_Yan58_pct': (Nu_Y58_G / Nu_code - 1) * 100,
        })

    out = pd.DataFrame(rows)

    # ── Pretty print: 误差表 ──
    print(f"{'case':>4} | {'T_in':>5} | {'Re_w':>5} | {'Pr':>4} || "
          f"{'Nu_code':>7} {'Nu_Yan6':>7} {'Nu_Y58G':>7} || "
          f"{'err_Y6%':>7} {'err_Y58%':>8} || {'flag_Y6':>7} {'flag_Y58':>8}")
    print('-' * 115)
    for r in rows:
        f6 = 'OK' if r['in_Yan6'] else 'EXT'
        f58 = 'OK' if r['in_Yan58_G'] else 'EXT'
        print(f"  {r['case']:2d}  | {r['T_in_C']:5.1f} | {r['Re_w']:5.0f} | "
              f"{r['Pr_w']:4.2f} || {r['Nu_code']:7.2f} {r['Nu_Yan6']:7.2f} "
              f"{r['Nu_Yan58_G']:7.2f} || "
              f"{r['err_Yan6_pct']:+7.2f} {r['err_Yan58_pct']:+8.2f} || "
              f"{f6:>7} {f58:>8}")

    # ── RMSRE summary ──
    import math
    e6 = [r['err_Yan6_pct'] for r in rows]
    e58 = [r['err_Yan58_pct'] for r in rows]
    rmsre6 = math.sqrt(sum(x*x for x in e6) / len(e6))
    rmsre58 = math.sqrt(sum(x*x for x in e58) / len(e58))
    bias6 = sum(e6) / len(e6)
    bias58 = sum(e58) / len(e58)
    print('-' * 115)
    print(f"  全 16 cases:")
    print(f"  Yan [6]:   RMSRE={rmsre6:.2f}%  bias={bias6:+.2f}%  "
          f"max|err|={max(abs(x) for x in e6):.2f}%")
    print(f"  Yan [58]G: RMSRE={rmsre58:.2f}%  bias={bias58:+.2f}%  "
          f"max|err|={max(abs(x) for x in e58):.2f}%")
    e6_in = [r['err_Yan6_pct'] for r in rows if r['in_Yan6']]
    e58_in = [r['err_Yan58_pct'] for r in rows if r['in_Yan58_G']]
    print(f"\n  仅 in-range:")
    print(f"  Yan [6]   ({len(e6_in)}/16): "
          f"RMSRE={math.sqrt(sum(x*x for x in e6_in)/len(e6_in)):.2f}%  "
          f"bias={sum(e6_in)/len(e6_in):+.2f}%")
    print(f"  Yan [58]G ({len(e58_in)}/16): "
          f"RMSRE={math.sqrt(sum(x*x for x in e58_in)/len(e58_in)):.2f}%  "
          f"bias={sum(e58_in)/len(e58_in):+.2f}%")

    # ── Save ──
    out_path = (r'D:\Postgraduate\均质化\SJTU-TPMSHX\data'
                r'\water_nu_yan_comparison.xlsx')
    out.to_excel(out_path, index=False, engine='openpyxl')
    print(f"\nSaved: {out_path}")


if __name__ == '__main__':
    main()
