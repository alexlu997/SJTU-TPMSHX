"""Full trace of non-isothermal D-F dP prediction for Shanghai 16 cases.

Prints EVERY intermediate physical quantity so you can verify the entire chain:
  Excel inputs → air properties → geometry → ConstDF-v1 (K, c_F) →
  1D closed-form dP → SIMPLE non-iso coupled dP → compare with dP_exp.

Re is computed using the C-1 corrected convention: Re = ρ_actual · u · D_h / μ.
"""
import sys, warnings
import numpy as np
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.tpms_calc import (
    geometry as tpms_geometry, air_density, air_viscosity,
    air_conductivity, air_cp, P_atm,
)
from df_fit.predict import predict_K_cF

R_AIR = 287.05

# ── Geometry (same as validate_shanghai.py) ──
TPMS, L_CELL, T_WALL, K_S = 'Gyroid', 7.0, 0.6, 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']; D_H = g['D_h']; A0 = g['A_0']
L_DOM = 0.231; H_DOM = 0.042
N_UNITS = 36
A_FLOW_PER_UNIT = 18.0565e-6   # m², single unit cell effective air cross section
A_FLOW = N_UNITS * A_FLOW_PER_UNIT

# ── ConstDF-v1 surrogate ──
eps_f = EPS / 2.0
K, cF = predict_K_cF(TPMS, L_CELL, T_WALL, eps_f)

print("=" * 90)
print("GEOMETRY (fixed for all 16 cases)")
print("=" * 90)
print(f"  TPMS type        = {TPMS}")
print(f"  L_cell           = {L_CELL} mm")
print(f"  t_wall           = {T_WALL} mm")
print(f"  K_solid          = {K_S} W/(m·K)")
print(f"  eps_full         = {EPS:.4f}")
print(f"  eps_f = eps/2    = {eps_f:.4f}")
print(f"  D_h              = {D_H*1000:.4f} mm")
print(f"  A_0              = {A0:.1f} 1/m")
print(f"  L_dom            = {L_DOM*1000:.0f} mm = {L_DOM/L_CELL*1000:.0f} unit cells × {L_CELL} mm")
print(f"  H_dom            = {H_DOM*1000:.0f} mm")
print(f"  N_units          = {N_UNITS}")
print(f"  A_flow_per_unit  = {A_FLOW_PER_UNIT*1e6:.2f} mm² = ({L_CELL}mm)² × eps_f = {(L_CELL)**2 * eps_f:.2f} mm²")
print(f"  A_flow_total     = {A_FLOW*1e4:.3f} cm²")
print()
print("ConstDF-v1 MLP surrogate call:")
print(f"  predict_K_cF('{TPMS}', L_mm={L_CELL}, t_mm={T_WALL}, eps_f={eps_f:.4f})")
print(f"  → K   = {K:.6e} m²   (Darcy permeability)")
print(f"  → c_F = {cF:.6e} 1/m  (Forchheimer inertia coefficient)")
print(f"  Training range: L [4,8]✓  t [0.3,0.5]✗(Shanghai 0.6 is +20% extrapolation)")
print(f"                  eps_f [0.31,0.44]✓  Re [400,16000]✓(Shanghai 526-9981 all inside)")
print()

# ── Load experimental data ──
DATA = r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
raw = pd.read_excel(DATA, engine='openpyxl', sheet_name='Sheet1', header=None, skiprows=2)

# ── Load SIMPLE results (from latest validate_shanghai.py run) ──
sim_df = pd.read_excel(r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\shanghai_validation.xlsx', engine='openpyxl')

print("=" * 90)
print("PER-CASE TRACE")
print("=" * 90)

for ci in range(16):
    case = ci + 1
    print(f"\n{'─'*90}")
    print(f"CASE {case}")
    print(f"{'─'*90}")

    # ── Step 1: Read Excel inputs ──
    m_air   = float(raw.iloc[ci, 5])   # c5: 样机空气流量 kg/s
    T_Ain_C = float(raw.iloc[ci, 28])  # c28: 空气进口温度 °C
    T_Ain_K = T_Ain_C + 273.15
    P_Ain_g = float(raw.iloc[ci, 30])  # c30: 空气进口表压 Pa
    P_Aout_g = float(raw.iloc[ci, 31]) # c31: 空气出口表压 Pa
    P_Ain   = P_atm + P_Ain_g          # 绝对压力
    dP_exp  = P_Ain_g - P_Aout_g       # 实验压降
    Q_exp   = float(raw.iloc[ci, 33])  # c33: 空气换热量 W

    print(f"  Excel inputs:")
    print(f"    m_air     = {m_air:.4f} kg/s       (c5, 样机空气流量)")
    print(f"    T_Ain     = {T_Ain_C:.1f} °C = {T_Ain_K:.2f} K   (c28)")
    print(f"    P_Ain_g   = {P_Ain_g:.0f} Pa gauge  (c30)")
    print(f"    P_Aout_g  = {P_Aout_g:.0f} Pa gauge  (c31)")
    print(f"    P_Ain_abs = P_atm + P_Ain_g = {P_atm:.0f} + {P_Ain_g:.0f} = {P_Ain:.0f} Pa")
    print(f"    dP_exp    = c30 − c31 = {dP_exp:.0f} Pa")
    print(f"    Q_exp     = {Q_exp:.0f} W    (c33, 空气换热量)")

    # ── Step 2: Compute air properties at inlet ──
    rho_A  = air_density(T_Ain_K, P_Ain)       # ρ = P/(R·T)
    mu_A   = air_viscosity(T_Ain_K)             # Sutherland
    k_A    = air_conductivity(T_Ain_K)
    cp_A   = air_cp(T_Ain_K)
    u_A    = m_air / (rho_A * A_FLOW)           # interstitial velocity
    G      = m_air / A_FLOW                     # mass flux (constant along channel)
    Re     = rho_A * u_A * D_H / mu_A           # C-1 correct convention

    print(f"\n  Air properties at inlet (ideal gas + Sutherland):")
    print(f"    ρ_A    = P_Ain / (R·T) = {P_Ain:.0f} / ({R_AIR:.2f}·{T_Ain_K:.2f}) = {rho_A:.4f} kg/m³")
    print(f"    μ_A    = Sutherland({T_Ain_K:.2f}) = {mu_A:.4e} Pa·s")
    print(f"    k_A    = {k_A:.4e} W/(m·K)")
    print(f"    cp_A   = {cp_A:.1f} J/(kg·K)")
    print(f"    u_A    = m / (ρ·A_flow) = {m_air:.4f} / ({rho_A:.4f}·{A_FLOW:.4e}) = {u_A:.3f} m/s (interstitial)")
    print(f"    G      = m / A_flow = {G:.3f} kg/(m²·s)")
    print(f"    Re     = ρ·u·D_h/μ = {rho_A:.4f}·{u_A:.3f}·{D_H:.6f}/{mu_A:.4e} = {Re:.0f}")

    # ── Step 3: D-F analytical pressure drop (1D incompressible) ──
    darcy  = mu_A * u_A / K           # Pa/m
    forch  = rho_A * cF * u_A**2      # Pa/m
    dPdL   = darcy + forch
    dP_inc = dPdL * L_DOM
    f_darcy = darcy / (darcy + forch) * 100

    print(f"\n  D-F analytical (1D incompressible, inlet ρ/μ/u):")
    print(f"    Darcy      = μ·u/K       = {mu_A:.4e}·{u_A:.3f}/{K:.4e} = {darcy:.2e} Pa/m")
    print(f"    Forchheimer= ρ·c_F·u²    = {rho_A:.4f}·{cF:.2f}·{u_A:.3f}² = {forch:.2e} Pa/m")
    print(f"    total dP/L = {dPdL:.2e} Pa/m   (Darcy {f_darcy:.1f}%, Forch {100-f_darcy:.1f}%)")
    print(f"    dP_inc     = dP/L × L_dom = {dPdL:.2e} × {L_DOM} = {dP_inc:.0f} Pa")

    # ── Step 4: 1D compressible isothermal closed-form ──
    K_term = mu_A * G / K
    F_term = cF * G**2
    P_out_sq = P_Ain**2 - 2.0 * R_AIR * T_Ain_K * (K_term + F_term) * L_DOM
    dP_1Dc = P_Ain - np.sqrt(max(P_out_sq, 1.0))

    print(f"\n  1D compressible isothermal closed-form:")
    print(f"    C = μG/K + cF·G² = {K_term:.1f} + {F_term:.1f} = {K_term+F_term:.1f}")
    print(f"    P_out² = P_in² − 2·R·T·C·L = {P_Ain**2:.3e} − {2*R_AIR*T_Ain_K*(K_term+F_term)*L_DOM:.3e}")
    print(f"    dP_1Dc = {dP_1Dc:.0f} Pa")

    # ── Step 5: 1D compressible non-isothermal (average-T) ──
    T_Aout_est = T_Ain_K - Q_exp / (m_air * cp_A)
    T_avg = 0.5 * (T_Ain_K + T_Aout_est)
    mu_avg = air_viscosity(T_avg)
    K_nc = mu_avg * G / K
    F_nc = cF * G**2
    P_out_sq_nc = P_Ain**2 - 2.0 * R_AIR * T_avg * (K_nc + F_nc) * L_DOM
    dP_1Dnc = P_Ain - np.sqrt(max(P_out_sq_nc, 1.0))

    print(f"\n  1D compressible non-isothermal (Q_exp-based T_avg):")
    print(f"    T_Aout_est = T_in − Q/(m·cp) = {T_Ain_K:.2f} − {Q_exp:.0f}/({m_air:.4f}·{cp_A:.1f}) = {T_Aout_est:.2f} K ({T_Aout_est-273.15:.1f}°C)")
    print(f"    T_avg      = ({T_Ain_K:.2f} + {T_Aout_est:.2f})/2 = {T_avg:.2f} K")
    print(f"    μ_avg      = Sutherland({T_avg:.1f}) = {mu_avg:.4e} Pa·s")
    print(f"    dP_1Dnc    = {dP_1Dnc:.0f} Pa")

    # ── Step 6: SIMPLE non-isothermal coupled result (from validate_shanghai.py) ──
    dP_sim = float(sim_df.iloc[ci]['dP_air_sim'])
    Q_sim_val = sim_df.iloc[ci]['Q_sim']
    Q_sim = float(Q_sim_val) if Q_sim_val != 'NaN' else float('nan')
    err_dP = float(sim_df.iloc[ci]['err_dP%'])
    err_Q  = sim_df.iloc[ci]['err_Q%']
    outer  = int(sim_df.iloc[ci]['outer_iters'])

    print(f"\n  SIMPLE non-isothermal coupled result (from validate_shanghai.py):")
    print(f"    dP_sim     = {dP_sim:.0f} Pa   (outer iters = {outer})")
    print(f"    Q_sim      = {Q_sim:.0f} W")

    # ── Step 7: Error summary ──
    err_inc = (dP_inc - dP_exp) / dP_exp * 100
    err_1Dc = (dP_1Dc - dP_exp) / dP_exp * 100
    err_1Dnc = (dP_1Dnc - dP_exp) / dP_exp * 100

    print(f"\n  Error summary:")
    print(f"    {'Method':<30s} {'dP (Pa)':>10} {'err%':>8}")
    print(f"    {'1D incompressible':<30s} {dP_inc:>10.0f} {err_inc:>+7.1f}%")
    print(f"    {'1D compressible isothermal':<30s} {dP_1Dc:>10.0f} {err_1Dc:>+7.1f}%")
    print(f"    {'1D compressible non-iso':<30s} {dP_1Dnc:>10.0f} {err_1Dnc:>+7.1f}%")
    print(f"    {'SIMPLE non-iso coupled':<30s} {dP_sim:>10.0f} {err_dP:>+7.1f}%")
    print(f"    {'Experiment':<30s} {dP_exp:>10.0f}")
    print(f"    Q:  sim={Q_sim:.0f}  exp={Q_exp:.0f}  err_Q={err_Q}%")

# ── Summary table ──
print(f"\n{'='*90}")
print("SUMMARY TABLE")
print(f"{'='*90}")
print(f"{'C':>2} {'Re':>6} {'m_air':>7} {'T_in':>5} {'P_abs':>7} {'ρ':>6} {'u':>6} {'μ(e5)':>6}"
      f" {'dP_sim':>7} {'dP_exp':>7} {'err%':>6} {'Q_sim':>6} {'Q_exp':>6} {'eQ%':>5} {'oi':>2}")
for ci in range(16):
    m = float(raw.iloc[ci, 5])
    T = float(raw.iloc[ci, 28]) + 273.15
    P = P_atm + float(raw.iloc[ci, 30])
    rho = air_density(T, P); mu = air_viscosity(T)
    u = m / (rho * A_FLOW)
    Re = rho * u * D_H / mu
    dP_e = float(raw.iloc[ci, 30]) - float(raw.iloc[ci, 31])
    dP_s = float(sim_df.iloc[ci]['dP_air_sim'])
    Q_e = float(raw.iloc[ci, 33])
    Q_s_v = sim_df.iloc[ci]['Q_sim']
    Q_s = float(Q_s_v) if Q_s_v != 'NaN' else float('nan')
    err_p = float(sim_df.iloc[ci]['err_dP%'])
    err_q = sim_df.iloc[ci]['err_Q%']
    oi = int(sim_df.iloc[ci]['outer_iters'])
    print(f"{ci+1:>2} {Re:>6.0f} {m:>7.4f} {T-273.15:>5.1f} {P/1000:>7.1f} {rho:>6.3f} {u:>6.2f} {mu*1e5:>6.3f}"
          f" {dP_s:>7.0f} {dP_e:>7.0f} {err_p:>+5.1f}% {Q_s:>6.0f} {Q_e:>6.0f} {err_q!s:>5} {oi:>2}")
