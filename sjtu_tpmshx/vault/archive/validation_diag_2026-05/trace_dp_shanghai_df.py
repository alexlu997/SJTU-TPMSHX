"""Full trace of the D-F (ConstDF-v1) dP prediction chain on Shanghai 16 cases.

Goal: print every number that goes into the pressure drop, so you can see
exactly how the surrogate (K, c_F) closes the loop with the actual flow
state to produce dP_sim.
"""
import sys, warnings
import numpy as np
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.tpms_calc import geometry as tpms_geometry, air_density, air_viscosity, P_atm
from df_fit.predict import predict_K_cF
from df_fit.load_data import load_all

TPMS = 'Gyroid'; L_CELL = 7.0; T_WALL = 0.6; K_S = 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']; D_H = g['D_h']; A0 = g['A_0']
L_DOM = 0.231; H_DOM = 0.042
N_UNITS = 36
A_FLOW = N_UNITS * 18.0565e-6   # 6.50034e-4 m²

# ── Step 1: surrogate evaluation (single call, no Re/u dependence) ──
eps_f = EPS / 2.0
K, cF = predict_K_cF(TPMS, L_CELL, T_WALL, eps_f)
print(f"Geometry:      {TPMS}  L={L_CELL}mm  t={T_WALL}mm")
print(f"               eps_full={EPS:.4f}  eps_f={eps_f:.4f}")
print(f"               D_h={D_H*1000:.3f}mm  A_flow={A_FLOW*1e4:.3f}cm²  L_dom={L_DOM*1000:.0f}mm")
print()
print(f"ConstDF-v1 surrogate (single call, geometry-only inputs):")
print(f"  predict_K_cF('{TPMS}', L_mm={L_CELL}, t_mm={T_WALL}, eps_f={eps_f:.4f})")
print(f"  → K   = {K:.4e} m²   (Darcy permeability)")
print(f"  → c_F = {cF:.4e} 1/m (Forchheimer coeff)")
print()

# Check against training range
df = load_all()
gy = df[df.tpms=='Gyroid']
print(f"Training ranges (Gyroid, n={len(gy)}):")
print(f"  L_mm  : [{gy.L_mm.min():g}, {gy.L_mm.max():g}]   Shanghai uses 7.0    — IN")
print(f"  t_mm  : [{gy.t_mm.min():g}, {gy.t_mm.max():g}]  Shanghai uses 0.6    — **OUT (+20%)**")
print(f"  eps_f : [{gy.eps_f.min():.4g}, {gy.eps_f.max():.4g}]  Shanghai uses {eps_f:.4f} — IN")
print(f"  u_mps : [{gy.u_mps.min():.3g}, {gy.u_mps.max():.3g}]  Shanghai uses ~4–22   — low end borderline")
print()

# ── Step 2: per-case loop ──
DATA = r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
raw = pd.read_excel(DATA, engine='openpyxl', sheet_name='Sheet1', header=None, skiprows=2)
sim_xlsx = r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\shanghai_validation.xlsx'
sim_df = pd.read_excel(sim_xlsx, engine='openpyxl')

print("Per-case breakdown — all columns derived from (m_air, T_in, P_in, K, c_F):\n")
print(f"{'C':>2} {'m_air':>7} {'T_in':>6} {'P_in':>7} {'rho':>6} {'mu(e5)':>7} "
      f"{'u_c':>6} {'μu/K':>9} {'ρcFu²':>9} "
      f"{'dP_ana':>8} {'dP_sim':>8} {'dP_exp':>8} "
      f"{'f_Darcy':>8} {'err_ana%':>9} {'err_sim%':>9}")

for ci in range(16):
    m_air  = float(raw.iloc[ci, 5])
    T_in_K = float(raw.iloc[ci, 28]) + 273.15
    P_in   = P_atm + float(raw.iloc[ci, 30])
    rho    = air_density(T_in_K, P_in)
    mu     = air_viscosity(T_in_K)
    u_c    = m_air / (rho * A_FLOW)

    # Darcy-Forchheimer per unit length
    darcy_term  = mu * u_c / K              # Pa/m
    forch_term  = rho * cF * u_c**2         # Pa/m
    dPdL        = darcy_term + forch_term
    dP_ana      = dPdL * L_DOM              # Pa (no compressibility)

    # Fraction of Darcy vs Forchheimer in the local pressure gradient
    f_darcy = darcy_term / (darcy_term + forch_term) * 100

    dP_exp = float(raw.iloc[ci, 30]) - float(raw.iloc[ci, 31])
    dP_sim = float(sim_df.iloc[ci]['dP_air_sim'])

    err_ana = (dP_ana - dP_exp)/dP_exp*100
    err_sim = (dP_sim - dP_exp)/dP_exp*100

    print(f"{ci+1:>2} {m_air:>7.4f} {T_in_K-273.15:>6.1f} {P_in:>7.0f} "
          f"{rho:>6.3f} {mu*1e5:>7.3f} {u_c:>6.2f} "
          f"{darcy_term:>9.2e} {forch_term:>9.2e} "
          f"{dP_ana:>8.0f} {dP_sim:>8.0f} {dP_exp:>8.0f} "
          f"{f_darcy:>7.1f}% {err_ana:>+8.1f}% {err_sim:>+8.1f}%")
