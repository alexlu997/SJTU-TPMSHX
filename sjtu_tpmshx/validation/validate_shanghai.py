"""
validate_shanghai.py — Validate SJTU-TPMSHX against Shanghai Electric data.
Air = Fluid A (侧边, +x, full-width), Water = Fluid B (X方向, -y, partial BC)
"""
import os, sys, warnings
import numpy as np
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.tpms_calc import (
    geometry as tpms_geometry, compute as tpms_compute,
    air_density, air_viscosity, air_conductivity, air_cp, P_atm, Sa_mm,
)
from solvers.simple_solver import SIMPLESolver
from solvers.solve_full import solve_full_domain
from df_fit.predict import predict_K_cF

R_AIR_VAL = 287.05  # J/(kg·K), matches SIMPLESolver's default R_gas

# ── Outer SIMPLE ↔ solve_full coupling (non-isothermal) ──
# C-2 2026-04-15 update: Shanghai is a heat exchanger, so air temperature
# rises ~60 K along the channel. Isothermal SIMPLE underestimates dP by ~10%
# (mostly via ρ(T) and μ(T) in the Forchheimer term). We iterate:
#   1. SIMPLE momentum with current T_field
#   2. solve_full temperature using SIMPLE's velocity
#   3. Feed Ta back into SIMPLE.update_T_field (auto-refreshes mu_field)
#   4. Repeat until ΔT_max < OUTER_TOL
MAX_OUTER = 8         # outer iterations (typically 3-5 suffice)
OUTER_TOL = 0.5       # K, ΔT_max convergence criterion
ALPHA_T   = 0.6       # under-relaxation factor for T_field update

# ── Geometry ──
TPMS = 'Gyroid'; L_CELL = 7.0; T_WALL = 0.6; K_S = 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']; EPS_A = g['epsilon_A']; D_H = g['D_h']; R_H = D_H / 2; A0 = g['A_0']
L_DOM = 0.182; H_DOM = 0.042
# C-1: Shanghai Electric 样机 has N_UNITS parallel unit cells (Excel ratio
# c5/c3 = 36.00 exactly across all 16 cases; also (H_DOM/L_cell)² = 36 from
# geometry). We scale A_FLOW to prototype and read prototype-scale mass flows
# below, so Q_sim comes out at the same scale as Q_exp (c33 = 空气换热量 / W).
N_UNITS = 36
# A_FLOW_PER_UNIT is the *void* (pore) cross section: 18.0565 mm² per unit cell
# ≈ eps_f × L_cell² (e.g. 0.368 × 49 mm² for L=7 mm). Consequently the velocity
# u_A = m_air / (rho_A * A_FLOW) computed below is the *interstitial* (pore-
# average) velocity, matching the training-data convention in df_fit/ and the
# solver convention documented in simple_solver.py. K and c_F from the D-F
# surrogate are effective interstitial coefficients (absorb the eps_f factor).
A_FLOW_PER_UNIT = 18.0565e-6  # m² — single unit cell void (interstitial) cross section
A_FLOW = N_UNITS * A_FLOW_PER_UNIT  # 6.50034e-4 m² — prototype total

from solvers.tpms_calc import adaptive_grid
from solvers.df_projection import build_master_refined_grid
N_X_USER, N_Y_USER = adaptive_grid(L_DOM, H_DOM, D_H, alpha=0.2)  # user resolution
# Master refined grid: 4-wall Brinkman BL resolution
DX_REFINED, DY_REFINED, N_X, N_Y = build_master_refined_grid(
    L_DOM, H_DOM, N_X_USER, N_Y_USER, n_refine=8, first_cell=0.02e-3, growth=1.8)
print(f"[Shanghai] User grid {N_X_USER}×{N_Y_USER} → refined {N_X}×{N_Y}")

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
DATA_PATH = r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
df = pd.read_excel(DATA_PATH, engine='openpyxl', sheet_name='Sheet1', header=None, skiprows=2)

print(f"Geometry: {TPMS} L={L_CELL} t={T_WALL} eps={EPS:.4f} D_h={D_H*1000:.3f}mm")
print(f"Domain: {L_DOM*1000:.0f}x{H_DOM*1000:.0f}mm, Grid: {N_X}x{N_Y}")
K_pred_header, cF_pred_header = predict_K_cF(TPMS, L_CELL, T_WALL, EPS_A)
print(f"D-F coeffs (ConstDF-v1): K={K_pred_header:.4e} m², c_F={cF_pred_header:.4e} 1/m")
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
    u_A = m_air / (rho_A * A_FLOW)  # interstitial (pore-average) velocity; see A_FLOW block above

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
    # C-2 (2026-04-15 SIMPLE audit): P_ref_abs sets the *outlet* absolute
    # pressure anchor (via outlet cell Pp=0 pinning). Default None → P_atm,
    # which treats each case as a 1 atm problem and non-physically inflates
    # Forchheimer resistance. We seed P_ref_abs with a 1D compressible
    # closed-form estimate of the real outlet pressure:
    #     P_out² = P_Ain² − 2·R·T·(μG/K + c_F·G²)·L_dom
    # so SIMPLE's converged state matches the correct isothermal compressible
    # physics to within a few percent of the closed-form 1D answer.
    K_pred, cF_pred = predict_K_cF(TPMS, L_CELL, T_WALL, EPS_A)
    G_est = m_air / A_FLOW
    C_est = mu_A * G_est / K_pred + cF_pred * G_est**2
    P_out_sq = P_Ain**2 - 2.0 * R_AIR_VAL * T_Ain_K * C_est * L_DOM
    P_out_est = float(np.sqrt(max(P_out_sq, 1.0e4)))  # guard underflow

    sA = SIMPLESolver(H_DOM, L_DOM, N_Y, N_X, TPMS, L_CELL, T_WALL,
                      EPS, R_H, rho_A, mu_A, T_Ain_K,
                      0.0, H_DOM, u_A, outlet_lo=0.0, outlet_hi=H_DOM,
                      P_ref_abs=P_out_est,
                      wall_refine=False)
    # Apply master refined grid (4-wall BL resolved): Fluid A SIMPLE coord =
    # (real y for dx, real x for dy). solve_full_domain downstream also runs on
    # this same refined grid so all shapes match.
    sA.dx_arr = DY_REFINED.copy()
    sA.dy_arr = DX_REFINED.copy()
    # Outer iteration 0: isothermal first pass (T_field = T_Ain_K default)
    cA, nA = sA.solve(max_iter=3000, tol=1e-4, verbose=False)

    # C-2 (2026-04-15 non-isothermal coupling): use SIMPLE's actual velocity
    # field for the temperature solver. Coordinate convention:
    #   sA.v shape = (sA.Nx=N_Y, sA.Ny+1=N_X+1), y-face staggered, stream=j
    #   solve_full expects ucA shape = (N_X, N_Y), cell-centred, stream=i
    # So: cell-centre along j, then transpose to swap (cross-stream, stream) →
    # (stream, cross-stream).
    def _sA_to_ucA(sA_local):
        v_cell = 0.5 * (sA_local.v[:, :-1] + sA_local.v[:, 1:])  # (N_Y, N_X)
        return np.ascontiguousarray(v_cell.T, dtype=np.float64)  # (N_X, N_Y)

    def _compute_h_vA_field(Ta_field, ucA_field, sA_local):
        """Compute 2D h_vA field from local (T, v, P) using Gyroid Nu correlation.
        Uses exact P from SIMPLE (transposed) for local density — no approximation.
        All arrays in solve_full convention: (N_X, N_Y) = (stream, cross-stream)."""
        from solvers.tpms_calc import Pr, Sa_mm
        # Transpose SIMPLE's P field to solve_full convention
        P_abs_sf = np.ascontiguousarray(
            (sA_local.P_ref_abs + sA_local.P).T, dtype=np.float64)  # (N_X, N_Y)
        rho_local = P_abs_sf / (R_AIR_VAL * Ta_field)
        mu_local  = air_viscosity(Ta_field)
        k_local   = air_conductivity(Ta_field)
        Re_local  = rho_local * np.abs(ucA_field) * D_H / mu_local
        Re_local  = np.clip(Re_local, 1.0, None)
        # Gyroid Nu: n = 0.177 * Re^0.1 * eps^(-2/3)
        #            Nu = 0.17 * Pr^(1/3) * Re^n * eps^2.25 * (L/(1000*Sa))^(-2.01)
        n_field  = 0.177 * Re_local**0.1 * EPS**(-2.0/3.0)
        Nu_field = (0.17 * Pr**(1.0/3.0) * Re_local**n_field
                    * EPS**2.25 * (L_CELL / (1000.0 * Sa_mm))**(-2.01))
        H_sf_field = Nu_field * k_local / D_H
        return A0 * H_sf_field

    # Water side: frozen via Tb_prescribed, no velocity needed
    ucB_real = np.zeros((N_X, N_Y), dtype=np.float64)
    vcB_real = np.zeros((N_X, N_Y), dtype=np.float64)
    vcA_real = np.zeros((N_X, N_Y), dtype=np.float64)  # air is 1D, no cross-stream

    # ── C-1: Water side is frozen. Construct prescribed Tb from measured
    #    T_w_in (c24) and T_w_out (c25), linear along y. Water flows in -y
    #    (dir_B=3): inlet at y=H_DOM (high j), outlet at y=0 (low j).
    #    solve_full.py convention: j=0 is at y≈dy/2, j=Ny-1 is at y≈H_DOM-dy/2.
    # Cell-centre y coordinates from the refined grid (not uniform)
    y_edges = np.concatenate([[0.0], np.cumsum(DY_REFINED)])
    y_centers = 0.5 * (y_edges[:-1] + y_edges[1:])
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

    # ── Temperature solver constants (geometry / Nu at inlet) ──
    eps_f = EPS_A   # alias
    K_ffA = eps_f * k_A
    K_ffB = eps_f * k_B
    K_ss = (1.0 - EPS) * K_S
    r_A = tpms_compute(TPMS, L_CELL, T_WALL, u_A, T_Ain_K, P_Ain, K_S)
    h_vA = A0 * r_A['H_sf']
    h_vB = 1.0e10  # water side perfect heat sink (see C-1)
    rho_cp_A = rho_A * cp_A
    rho_cp_B = rho_B * cp_B

    # ── Outer SIMPLE ↔ solve_full coupling loop (non-isothermal) ──
    Ta = Tb = Ts = None
    Ta_prev = None
    outer_iters = 0
    T_A_out_sim = float('nan'); Q_sim = float('nan')
    try:
        for outer_iter in range(MAX_OUTER):
            outer_iters = outer_iter + 1
            ucA_real = _sA_to_ucA(sA)

            # Update h_vA field from local (T, v, P) after first iteration
            if Ta is not None:
                h_vA = _compute_h_vA_field(Ta, ucA_real, sA)

            result = solve_full_domain(
                L_DOM, H_DOM, N_X, N_Y,
                T_Ain_K, T_Bin_K,
                K_ffA, K_ffB, K_ss,
                h_vA, h_vB,
                rho_cp_A, rho_cp_B,
                EPS,
                ucA_real, vcA_real, ucB_real, vcB_real,
                dir_A=0, dir_B=3,
                Tb_prescribed=Tb_prescribed,
                max_iter=50000, tol=1e-6,
                return_info=True,
                dx_arr=DX_REFINED, dy_arr=DY_REFINED,  # 4-wall refined grid
            )
            if isinstance(result, tuple) and len(result) == 4:
                Ta, Tb, Ts, info = result
            else:
                Ta, Tb, Ts = result[:3]; info = {}

            # Convergence check on air temperature field
            if Ta_prev is not None:
                dT_max = float(np.abs(Ta - Ta_prev).max())
                if dT_max < OUTER_TOL:
                    break
            Ta_prev = Ta.copy()

            # Inject T_field back into SIMPLE (with under-relaxation after iter 0)
            # Coordinate: solve_full Ta shape = (N_X, N_Y), SIMPLE T_field shape
            # = (sA.Nx=N_Y, sA.Ny=N_X), so transpose.
            T_field_new = np.ascontiguousarray(Ta.T, dtype=np.float64)
            if outer_iter > 0:
                T_field_mixed = ALPHA_T * T_field_new + (1.0 - ALPHA_T) * sA.T_field
                sA.update_T_field(T_field_mixed)
            else:
                sA.update_T_field(T_field_new)

            # Re-seed P_ref_abs using the updated T_field mean temperature
            T_avg = float(sA.T_field.mean())
            mu_avg = air_viscosity(T_avg)
            C_avg = mu_avg * G_est / K_pred + cF_pred * G_est**2
            P_out_sq_new = P_Ain**2 - 2.0 * R_AIR_VAL * T_avg * C_avg * L_DOM
            sA.P_ref_abs = float(np.sqrt(max(P_out_sq_new, 1.0e4)))

            # Re-solve SIMPLE momentum under the new T/μ/ρ field
            sA.solve(max_iter=3000, tol=1e-4, verbose=False)

        # Read converged Q and dP from final iterate
        T_A_out_sim = float(np.mean(Ta[-1, :]))
        Q_sim = m_air * cp_A * (T_Ain_K - T_A_out_sim)
    except Exception as e:
        print(f"  Case {case}: coupled solve error: {e}")

    # Final dP from the last SIMPLE state (pipe-weighted over inlet/outlet rows)
    wA_in = sA.inlet_frac; wA_out = sA.outlet_frac
    mA_in = wA_in > 0.01; mA_out = wA_out > 0.5
    dP_A_sim = (np.average(sA.P[mA_in, 0], weights=wA_in[mA_in])
              - np.average(sA.P[mA_out, -1], weights=wA_out[mA_out])) if mA_in.any() and mA_out.any() else 0.0

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
        'outer_iters': outer_iters,
    })

    q_str = f"{Q_sim:.0f}" if not np.isnan(Q_sim) else "NaN"
    eq_str = f"{err_Q:+.0f}%" if not np.isnan(err_Q) else "NaN"
    print(f"Case {case:2d}: dP {dP_A_exp:.0f}/{dP_A_sim:.0f} ({err_dP:+.0f}%)  "
          f"Q {Q_exp:.0f}/{q_str} ({eq_str})  outer={outer_iters}  [A:{'ok' if cA else 'NC'}]")

# ── Save ──
out_df = pd.DataFrame(results)
out_path = r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\shanghai_validation.xlsx'
out_df.to_excel(out_path, index=False, engine='openpyxl')
print(f"\nSaved: {out_path}")
