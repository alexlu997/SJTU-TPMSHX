"""
validate_shanghai.py — Validate ThermoNAS against Shanghai Electric data.
Air = Fluid A (侧边, +x, full-width), Water = Fluid B (X方向, -y, partial BC)
"""
import os, sys, warnings
import numpy as np
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from tpms_calc import (
    geometry as tpms_geometry, compute as tpms_compute,
    air_density, air_viscosity, air_conductivity, air_cp, P_atm,
    friction_factor, _F_COEFFS, Sa_mm,
)
from simple_solver import SIMPLESolver
from solve_full import solve_full_domain

# ── Closure form selector ──
# Set via env var: CLOSURE=df (default, ConstDF-v1 MLP) or CLOSURE=f_re (legacy).
CLOSURE = os.environ.get('CLOSURE', 'df').lower()
if CLOSURE not in ('df', 'f_re'):
    raise SystemExit(f"CLOSURE must be 'df' or 'f_re', got {CLOSURE!r}")
print(f"[validate_shanghai] closure = {CLOSURE}")

# ── Geometry ──
TPMS = 'Gyroid'; L_CELL = 7.0; T_WALL = 0.6; K_S = 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']; D_H = g['D_h']; R_H = D_H / 2; A0 = g['A_0']
L_DOM = 0.231; H_DOM = 0.042
# C-1: Shanghai Electric 样机 has N_UNITS parallel unit cells (Excel ratio
# c5/c3 = 36.00 exactly across all 16 cases; also (H_DOM/L_cell)² = 36 from
# geometry). We scale A_FLOW to prototype and read prototype-scale mass flows
# below, so Q_sim comes out at the same scale as Q_exp (c33 = 空气换热量 / W).
N_UNITS = 36
A_FLOW_PER_UNIT = 18.0565e-6  # m² — single unit cell effective air cross section
A_FLOW = N_UNITS * A_FLOW_PER_UNIT  # 6.50034e-4 m² — prototype total

from tpms_calc import adaptive_grid
N_X, N_Y = adaptive_grid(L_DOM, H_DOM, D_H, alpha=0.4)

# Fluid B partial BC
B_IN_CTR = 0.203; B_IN_W = 0.042; B_OUT_CTR = 0.028; B_OUT_W = 0.042

# ── Water properties ──
def water_rho(T_K):
    T_C = T_K - 273.15
    return 999.84 - 0.05 * T_C - 0.004 * T_C**2

def water_mu(T_K):
    T_C = T_K - 273.15
    return 1.79e-3 * np.exp(-0.035 * T_C)

def water_k(T_K):
    T_C = T_K - 273.15
    return 0.569 + 0.0019 * T_C - 8e-6 * T_C**2

def water_cp(T_K):
    return 4182.0

# ── Load data ──
DATA_PATH = r'D:\Postgraduate\均质化\ThermoNAS\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
df = pd.read_excel(DATA_PATH, engine='openpyxl', sheet_name='Sheet1', header=None, skiprows=2)

print(f"Geometry: {TPMS} L={L_CELL} t={T_WALL} eps={EPS:.4f} D_h={D_H*1000:.3f}mm")
print(f"Domain: {L_DOM*1000:.0f}x{H_DOM*1000:.0f}mm, Grid: {N_X}x{N_Y}")
print(f"f-Re coeffs: {_F_COEFFS['Gyroid']}")
print()

results = []

for ci in range(16):
    case = ci + 1

    # ── Air (Fluid A) ──
    m_air = float(df.iloc[ci, 5])  # c5 = 样机空气流量 kg/s (was c3 = 单个)
    T_Ain_C = float(df.iloc[ci, 28]); T_Ain_K = T_Ain_C + 273.15
    P_Ain_g = float(df.iloc[ci, 30])
    P_Ain = P_atm + P_Ain_g
    rho_A = air_density(T_Ain_K, P_Ain)
    mu_A = air_viscosity(T_Ain_K)
    k_A = air_conductivity(T_Ain_K)
    cp_A = air_cp(T_Ain_K)
    u_A = m_air / (rho_A * A_FLOW)

    # ── Water (Fluid B) ──
    m_water = float(df.iloc[ci, 7])  # c7 = 样机水流量 kg/s (was c4 = 单个)
    T_Bin_C = float(df.iloc[ci, 24]); T_Bin_K = T_Bin_C + 273.15
    T_Bout_C = float(df.iloc[ci, 25]); T_Bout_K = T_Bout_C + 273.15  # C-1: 水出口温度 (实测)
    rho_B = water_rho(T_Bin_K)
    mu_B = water_mu(T_Bin_K)
    k_B = water_k(T_Bin_K)
    cp_B = water_cp(T_Bin_K)
    u_B = m_water / (rho_B * A_FLOW)

    # ── Experimental values ──
    P_Aout_g = float(df.iloc[ci, 31])
    dP_A_exp = P_Ain_g - P_Aout_g
    dP_B_exp = float(df.iloc[ci, 32])
    Q_exp = float(df.iloc[ci, 33])  # air-side Q

    # ── SIMPLE for Fluid A (air, +x, full-width) ──
    # is_x=True: SIMPLESolver(W=H, H=L, Nx=N_Y, Ny=N_X)
    sA = SIMPLESolver(H_DOM, L_DOM, N_Y, N_X, TPMS, L_CELL, T_WALL,
                      EPS, R_H, rho_A, mu_A, T_Ain_K,
                      0.0, H_DOM, u_A, outlet_lo=0.0, outlet_hi=H_DOM,
                      closure=CLOSURE)
    cA, nA = sA.solve(max_iter=3000, tol=1e-4, verbose=False)

    # dP_A: pipe-weighted
    wA_in = sA.inlet_frac; wA_out = sA.outlet_frac
    mA_in = wA_in > 0.01; mA_out = wA_out > 0.5
    dP_A_sim = (np.average(sA.P[mA_in, 0], weights=wA_in[mA_in])
              - np.average(sA.P[mA_out, -1], weights=wA_out[mA_out])) if mA_in.any() and mA_out.any() else 0.0

    # C-1: for the temperature solver, use a uniform u_A velocity field instead
    # of the SIMPLE-derived ucA_real. Rationale: SIMPLESolver returns an
    # internal velocity convention that differs from u_A = m_dot/(rho*A_FLOW)
    # by a factor of ~3 (likely an eps_f / porosity double-count between the
    # SIMPLE internal representation and solve_full.py's advection term
    # Fx = eps_f * rho_cp * u * dy). Using the SIMPLE field directly inflates
    # the effective mass-flow in solve_full by 3x, divides NTU by 3, and
    # artificially degrades Q_sim by ~13 percentage points at high Re.
    # Note: this does NOT affect dP_A_sim above — that's still computed from
    # SIMPLE's internal P field. Only the temperature solver uses this override.
    # The SIMPLE/solve_full velocity convention reconciliation is C-3 scope.
    ucA_real = np.full((N_X, N_Y), u_A, dtype=np.float64)
    vcA_real = np.zeros((N_X, N_Y), dtype=np.float64)

    # ── C-1: Water side is frozen. Construct prescribed Tb from measured
    #    T_w_in (c24) and T_w_out (c25), linear along y. Water flows in -y
    #    (dir_B=3): inlet at y=H_DOM (high j), outlet at y=0 (low j).
    #    solve_full.py convention: j=0 is at y≈dy/2, j=Ny-1 is at y≈H_DOM-dy/2.
    dy_cell = H_DOM / N_Y
    y_centers = (np.arange(N_Y) + 0.5) * dy_cell
    Tb_1d = T_Bout_K + (T_Bin_K - T_Bout_K) * (y_centers / H_DOM)
    # Sanity: Tb_1d[-1] ≈ T_Bin_K (inlet row), Tb_1d[0] ≈ T_Bout_K (outlet row)
    Tb_prescribed = np.broadcast_to(Tb_1d[None, :], (N_X, N_Y)).copy()

    # Water velocity field is no longer needed (Tb update is skipped entirely)
    zero_field_B = np.zeros((N_X, N_Y), dtype=np.float64)
    ucB_real = zero_field_B
    vcB_real = zero_field_B

    # Water-side sim dP is no longer available (placeholder for compat with
    # the print line below — dP_B_exp is read but never compared to sim)
    cB = True  # "converged" placeholder for the per-case status line
    dP_B_sim = 0.0

    # ── Temperature solver ──
    eps_f = EPS / 2.0
    K_ffA = eps_f * k_A
    K_ffB = eps_f * k_B
    K_ss = (1.0 - EPS) * K_S

    # h_v from Nu: air side
    r_A = tpms_compute(TPMS, L_CELL, T_WALL, u_A, T_Ain_K, P_Ain, K_S)
    h_vA = A0 * r_A['H_sf']

    # C-1: water side treated as perfect heat sink.
    # Rationale: user intent is to freeze water at measured T_in/T_out and
    # only validate the air-side prediction model. The Gyroid Nu correlation
    # is validated for Re in [600, 30000] but water-side Re drops below 25
    # for most Shanghai cases, giving a meaningless extrapolated h_vB that
    # artificially becomes the heat-transfer bottleneck. Setting h_vB -> inf
    # makes Ts track Tb_prescribed exactly, eliminating water as a confound.
    # See docs/superpowers/specs/2026-04-13-thermonas-c1-audit-water-fixed-bc-design.md
    h_vB = 1.0e10  # W/(m^3 K) — effectively infinite water-side coupling

    rho_cp_A = rho_A * cp_A
    rho_cp_B = rho_B * cp_B

    try:
        result = solve_full_domain(
            L_DOM, H_DOM, N_X, N_Y,
            T_Ain_K, T_Bin_K,
            K_ffA, K_ffB, K_ss,
            h_vA, h_vB,
            rho_cp_A, rho_cp_B,
            EPS,
            ucA_real, vcA_real, ucB_real, vcB_real,
            dir_A=0, dir_B=3,
            Tb_prescribed=Tb_prescribed,  # C-1: freeze water side
            max_iter=50000, tol=1e-6,
            return_info=True,
        )
        if isinstance(result, tuple) and len(result) == 4:
            Ta, Tb, Ts, info = result
        else:
            Ta, Tb, Ts = result[:3]; info = {}

        # Q from air outlet temperature
        # A flows +x: outlet at x=L (i=Nx-1)
        T_A_out_sim = np.mean(Ta[-1, :])
        Q_sim = m_air * cp_A * (T_Ain_K - T_A_out_sim)
    except Exception as e:
        Q_sim = float('nan')
        T_A_out_sim = float('nan')
        print(f"  Case {case}: temperature solver error: {e}")

    err_dP = (dP_A_sim - dP_A_exp) / dP_A_exp * 100 if dP_A_exp != 0 else float('nan')
    err_Q = (Q_sim - Q_exp) / Q_exp * 100 if (Q_exp != 0 and not np.isnan(Q_sim)) else float('nan')

    results.append({
        'Case': case, 'u_air': round(u_A, 2), 'u_water': round(u_B, 4),
        'T_air_in': round(T_Ain_C, 1), 'T_water_in': round(T_Bin_C, 1),
        'dP_air_exp': round(dP_A_exp), 'dP_air_sim': round(dP_A_sim),
        'err_dP%': round(err_dP, 1),
        'Q_exp': round(Q_exp, 1),
        'Q_sim': round(Q_sim, 1) if not np.isnan(Q_sim) else 'NaN',
        'err_Q%': round(err_Q, 1) if not np.isnan(err_Q) else 'NaN',
    })

    q_str = f"{Q_sim:.0f}" if not np.isnan(Q_sim) else "NaN"
    eq_str = f"{err_Q:+.0f}%" if not np.isnan(err_Q) else "NaN"
    print(f"Case {case:2d}: dP_air {dP_A_exp:.0f}/{dP_A_sim:.0f} ({err_dP:+.0f}%)  "
          f"Q {Q_exp:.0f}/{q_str} ({eq_str})  [A:{'ok' if cA else 'NC'} B:fixed]")

# ── Save ──
out_df = pd.DataFrame(results)
out_path = r'D:\Postgraduate\均质化\ThermoNAS\data\shanghai_validation.xlsx'
out_df.to_excel(out_path, index=False, engine='openpyxl')
print(f"\nSaved: {out_path}")
