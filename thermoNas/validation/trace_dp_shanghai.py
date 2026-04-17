"""Trace dP prediction chain for Shanghai 16 cases. Prints every intermediate
quantity so you can see exactly what closes the loop from (m_dot, T, P) to
the final dP_sim reported by validate_shanghai.py.
"""
import sys, os, warnings
import numpy as np
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.tpms_calc import (
    geometry as tpms_geometry, air_density, air_viscosity,
    friction_factor, pressure_drop, P_atm, _F_COEFFS,
)

TPMS = 'Gyroid'; L_CELL = 7.0; T_WALL = 0.6; K_S = 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']; D_H = g['D_h']; A0 = g['A_0']
L_DOM = 0.231; H_DOM = 0.042
N_UNITS = 36
A_FLOW = N_UNITS * 18.0565e-6

DATA = r'D:\Postgraduate\均质化\ThermoNAS\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
df = pd.read_excel(DATA, engine='openpyxl', sheet_name='Sheet1', header=None, skiprows=2)

print(f"Geometry:  {TPMS}  L={L_CELL}mm  t={T_WALL}mm")
print(f"           eps_full={EPS:.4f}  eps_f=eps/2={EPS/2:.4f}")
print(f"           D_h={D_H*1000:.3f}mm  r_h={D_H*500:.3f}mm  A_0={A0:.1f} 1/m")
print(f"           A_flow(prototype)={A_FLOW*1e4:.3f} cm²  L_dom={L_DOM*1000:.0f}mm")
print(f"f-Re coeffs (C,n0,n1,a,b,c) = {_F_COEFFS[TPMS]}")
print(f"n_exp = n0 + n1*ln(eps/2) = {_F_COEFFS[TPMS][1] + _F_COEFFS[TPMS][2]*np.log(EPS/2):.4f}")
print()
print(f"{'C':>2} {'m_air':>7} {'T_in':>6} {'P_in':>8} {'rho':>6} {'mu(e5)':>7} "
      f"{'u_c':>6} {'Re':>7} {'f':>7} {'dP_ana':>8} {'dP_sim':>8} {'dP_exp':>8} "
      f"{'err_ana%':>9} {'err_sim%':>9}")

# read sim results from last run
sim_xlsx = r'D:\Postgraduate\均质化\ThermoNAS\data\shanghai_validation.xlsx'
sim_df = pd.read_excel(sim_xlsx, engine='openpyxl')

for ci in range(16):
    m_air = float(df.iloc[ci, 5])
    T_in_K = float(df.iloc[ci, 28]) + 273.15
    P_in = P_atm + float(df.iloc[ci, 30])
    rho = air_density(T_in_K, P_in)
    rho_ref = air_density(T_in_K, P_atm)
    mu = air_viscosity(T_in_K)
    u_c = m_air / (rho * A_FLOW)
    Re = rho_ref * u_c * (D_H/2) / mu
    f = friction_factor(TPMS, Re, EPS, T_WALL, L_CELL, D_h_mm=D_H*1000)
    dP_per_L = f * rho * u_c**2 / (2.0 * (D_H/2))
    dP_ana = dP_per_L * L_DOM

    P_out = P_in - (P_in - (P_atm + float(df.iloc[ci,31])))  # just to get dP_exp
    dP_exp = float(df.iloc[ci, 30]) - float(df.iloc[ci, 31])
    dP_sim = float(sim_df.iloc[ci]['dP_air_sim'])

    err_ana = (dP_ana - dP_exp)/dP_exp*100
    err_sim = (dP_sim - dP_exp)/dP_exp*100

    print(f"{ci+1:>2} {m_air:>7.4f} {T_in_K-273.15:>6.1f} {P_in:>8.0f} "
          f"{rho:>6.3f} {mu*1e5:>7.3f} {u_c:>6.2f} {Re:>7.0f} {f:>7.4f} "
          f"{dP_ana:>8.0f} {dP_sim:>8.0f} {dP_exp:>8.0f} "
          f"{err_ana:>+8.1f}% {err_sim:>+8.1f}%")
