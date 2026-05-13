"""validate_shanghai_aligned.py — Shanghai 2D validation with STRICTLY
the same pipeline as run_calculation.py (v1.0.10 UI Compute path).

Differences vs the legacy `validate_shanghai.py`:
  * h_vA / h_vB are real tpms_compute outputs (no 1e10 water shortcut)
  * K_ffA / K_ffB built the same way as run_calculation._run_solvers
  * Outer coupling mirrors run_calculation's 5-iter (drho + dT AND) loop
  * rho / mu / rho_cp fields updated identically
  * dP via `extract_dP_from_simple` (same as UI)

Water side is frozen via Tb_prescribed built from measured T_in / T_out
(linear along streamwise y), since we have no water-side dP/Q reference
to validate — but h_vB is finite + physical (tpms_compute), not 1e10.
"""
from __future__ import annotations
import os, sys, warnings
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from solvers.tpms_calc import (
    geometry as tpms_geometry, compute as tpms_compute,
    air_density, air_viscosity, air_conductivity, air_cp, P_atm,
    water_density, water_viscosity, water_conductivity, water_cp,
    nu_from_Re, nu_water_gyroid_yan6,
)
from solvers.simple_solver import SIMPLESolver
from solvers.solve_full import solve_full_domain
from solvers.df_projection import build_master_refined_grid, extract_dP_from_simple
from df_fit.predict import predict_K_cF
from solvers.roughness import (f_enhancement, nu_extra_factor,
                                 apply_to_K_cF, resolve_mode_from_env)

# 2026-05-13 — roughness mode from env (baseline / norris_1a / bhatti_shah_1b).
_ROUGH_MODE, _ROUGH_EPS = resolve_mode_from_env()
print(f"[Shanghai aligned] roughness mode = {_ROUGH_MODE}"
      f"{f' (ε={_ROUGH_EPS} μm)' if _ROUGH_MODE == 'bhatti_shah_1b' else ''}")

R_AIR_VAL = 287.05

# ── Match run_calculation.py constants ──
_MAX_COUPLING = 5
_COUPLING_TOL = 0.01
_DT_TOL_K     = 1.0
_ALPHA_COUP   = 0.7

# ── Geometry (Shanghai Electric Gyroid prototype) ──
TPMS = 'Gyroid'; L_CELL = 7.0; T_WALL = 0.6; K_S = 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']; EPS_A = g['epsilon_A']; D_H = g['D_h']; R_H = D_H / 2; A0 = g['A_0']
L_DOM = 0.182; H_DOM = 0.042
N_UNITS = 36
A_FLOW_PER_UNIT = 18.0565e-6
A_FLOW = N_UNITS * A_FLOW_PER_UNIT

from solvers.tpms_calc import adaptive_grid
N_X_USER, N_Y_USER = adaptive_grid(L_DOM, H_DOM, D_H, alpha=0.2)
DX_REFINED, DY_REFINED, N_X, N_Y = build_master_refined_grid(
    L_DOM, H_DOM, N_X_USER, N_Y_USER, n_refine=8, first_cell=0.02e-3, growth=1.8)

print(f"[Shanghai aligned] Geometry: {TPMS} L={L_CELL} t={T_WALL} "
      f"eps={EPS:.4f} D_h={D_H*1000:.3f}mm")
print(f"[Shanghai aligned] Domain {L_DOM*1000:.0f}x{H_DOM*1000:.0f}mm, "
      f"Grid {N_X}x{N_Y} (refined)")
K0, cF0 = predict_K_cF(TPMS, L_CELL, T_WALL, EPS_A)
print(f"[Shanghai aligned] D-F ConstDF-v1: K={K0:.3e} m², c_F={cF0:.3e} 1/m\n")


def _apply_rough_to_simple(s, Re_case):
    """Scale SIMPLE internal K, cF arrays by f_enhancement for the current
    case Re. Norris 1a: constant 1.46. Bhatti-Shah 1b: Re-dep Haaland.
    Baseline: no-op."""
    if _ROUGH_MODE == 'baseline':
        return
    f_gain = f_enhancement(Re_case, _ROUGH_MODE,
                            eps_um=_ROUGH_EPS, D_h_mm=D_H * 1000.0)
    s._K_arr = (s._K_arr / f_gain).astype(np.float64, copy=False)
    s._cF_arr = (s._cF_arr * f_gain).astype(np.float64, copy=False)


def _run_simple_A(rho_field, mu_field, u_in, T_in, P_ref_abs_seed, Re_case=None):
    """Build + solve SIMPLE for Fluid A (+x, full-width).

    Mirrors run_calculation.py._run_simple (closure) but with Shanghai-
    specific axis mapping baked in: Fluid A flows along real +x, so
    SIMPLE's streamwise axis (y) maps to real x, and SIMPLE's cross-
    stream axis (x) maps to real y.
    """
    s = SIMPLESolver(
        H_DOM, L_DOM, N_Y, N_X,
        TPMS, L_CELL, T_WALL,
        EPS, R_H,
        rho_field, mu_field, T_in,
        0.0, H_DOM, u_in,
        outlet_lo=0.0, outlet_hi=H_DOM,
        P_ref_abs=P_ref_abs_seed,
        wall_refine=False,
    )
    s.dx_arr = DY_REFINED.copy()
    s.dy_arr = DX_REFINED.copy()
    if Re_case is not None:
        _apply_rough_to_simple(s, Re_case)
    s.solve(max_iter=3000, tol=1e-4, verbose=False)
    # Cell-centre velocity in real-coord (N_X, N_Y) shape
    v_cell = 0.5 * (s.v[:, :-1] + s.v[:, 1:])   # (N_Y, N_X)
    ucA_real = np.ascontiguousarray(v_cell.T, dtype=np.float64)  # (N_X, N_Y)
    vcA_real = np.zeros((N_X, N_Y), dtype=np.float64)
    return ucA_real, vcA_real, s


def _transform_rho_mu_to_simple_coords(field_real):
    """(N_X, N_Y) real-coord 2D field → SIMPLE coords (N_Y, N_X) for
    Fluid A (+x). Same transform run_calculation.py._run_simple uses.
    """
    if np.ndim(field_real) != 2:
        return field_real
    return np.ascontiguousarray(field_real.T, dtype=np.float64)


def _transform_simple_P_to_real(s):
    """SIMPLE P + P_ref_abs → real-coord (N_X, N_Y) absolute P field."""
    P_loc = s.P_ref_abs + s.P   # (N_Y, N_X) solver coords for dir_A=+x
    return np.ascontiguousarray(P_loc.T, dtype=np.float64)


# ── Load Shanghai cases ──
DATA_PATH = r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
df = pd.read_excel(DATA_PATH, engine='openpyxl', sheet_name='Sheet1',
                   header=None, skiprows=2)

results = []

for ci in range(16):
    case = ci + 1

    # ── Case inputs ──
    m_air = float(df.iloc[ci, 5])
    T_Ain_C = float(df.iloc[ci, 28]); T_Ain_K = T_Ain_C + 273.15
    P_Ain_g = float(df.iloc[ci, 30])
    P_Ain = P_atm + P_Ain_g

    m_water = float(df.iloc[ci, 7])
    T_Bin_C = float(df.iloc[ci, 24]); T_Bin_K = T_Bin_C + 273.15
    T_Bout_C = float(df.iloc[ci, 25]); T_Bout_K = T_Bout_C + 273.15

    P_Aout_g = float(df.iloc[ci, 31])
    dP_A_exp = P_Ain_g - P_Aout_g
    Q_exp = float(df.iloc[ci, 33])

    # ── Scalar fluid properties at inlet (for first-iter seeds) ──
    rho_A0 = float(air_density(T_Ain_K, P_Ain))
    mu_A0  = float(air_viscosity(T_Ain_K))
    cp_A0  = float(air_cp(T_Ain_K))
    u_A    = m_air / (rho_A0 * A_FLOW)

    rho_B0 = float(water_density(T_Bin_K))
    mu_B0  = float(water_viscosity(T_Bin_K))
    cp_B0  = float(water_cp(T_Bin_K))
    u_B    = m_water / (rho_B0 * A_FLOW)

    # ── LTNE coefficients via tpms_compute (same as run_calculation) ──
    # Fluid A: air
    r_A = tpms_compute(TPMS, L_CELL, T_WALL, u_A, T_Ain_K, P_Ain, K_S)
    h_vA = A0 * r_A['H_sf']
    # 2026-05-13 — bhatti_shah_1b overrides scalar ×1.28 baked into tpms_compute
    # with Re-dep g_Nu(Re,ε)/1.28. Norris (1a) leaves Nu unchanged.
    _Re_A_case = rho_A0 * abs(u_A) * D_H / mu_A0
    if _ROUGH_MODE != 'baseline':
        h_vA *= nu_extra_factor(_Re_A_case, _ROUGH_MODE,
                                 eps_um=_ROUGH_EPS, D_h_mm=D_H * 1000.0)
    k_A  = r_A['k_f']
    K_ffA = EPS_A * k_A

    # Fluid B: water. Use Yan et al 2024 [6] gyroid water correlation:
    #   Nu = 0.471 · Re^0.627 · Pr^(1/3)   (Re 150-3000 in-range)
    # Replaces legacy air-fit + Pr substitution form (2026-04-29).
    # Cases 1-2 (Re 54, 108) extrapolate; err vs in-range ref ≈ -9 %.
    k_B  = float(water_conductivity(T_Bin_K))
    Pr_B = float(mu_B0 * cp_B0 / k_B)
    Re_B = rho_B0 * abs(u_B) * D_H / mu_B0
    Nu_B = float(nu_water_gyroid_yan6(max(Re_B, 1.0), Pr_B))
    H_sf_B = Nu_B * k_B / D_H
    h_vB = A0 * H_sf_B
    K_ffB = EPS_A * k_B    # symmetric sheet HX: ε_B = ε_A

    K_ss = (1.0 - EPS) * K_S

    # ── Water-side frozen Tb: linear between T_in / T_out along +y (dir_B=3
    # = -y so inlet at high y, outlet at low y — match run_calculation convention) ──
    y_edges = np.concatenate([[0.0], np.cumsum(DY_REFINED)])
    y_centers = 0.5 * (y_edges[:-1] + y_edges[1:])
    Tb_1d = T_Bout_K + (T_Bin_K - T_Bout_K) * (y_centers / H_DOM)
    Tb_prescribed = np.broadcast_to(Tb_1d[None, :], (N_X, N_Y)).copy()

    # ── Seed P_ref_abs via 1D compressible closed-form estimate ──
    G_A = m_air / A_FLOW
    C_est = mu_A0 * G_A / K0 + cF0 * G_A**2
    P_out_sq = P_Ain**2 - 2.0 * R_AIR_VAL * T_Ain_K * C_est * L_DOM
    P_ref_abs_seed = float(np.sqrt(max(P_out_sq, 1.0e4)))

    # ── Outer coupling loop — mirrors run_calculation.py._run_solvers ──
    rho_A_field_real = np.full((N_X, N_Y), rho_A0, dtype=np.float64)
    mu_A_field_real  = np.full((N_X, N_Y), mu_A0,  dtype=np.float64)
    rho_cp_A_real    = rho_A0 * cp_A0  # scalar initial — becomes 2D after first energy solve

    Ta = Tb = Ts = None
    Ta_prev = Tb_prev = None
    coupling_converged = False
    outer_iters = 0

    ucB_real = np.zeros((N_X, N_Y), dtype=np.float64)
    vcB_real = np.zeros((N_X, N_Y), dtype=np.float64)

    for _coup_it in range(_MAX_COUPLING):
        outer_iters = _coup_it + 1

        # 1. SIMPLE with current rho / mu fields (transform to SIMPLE coords)
        rho_A_simple = _transform_rho_mu_to_simple_coords(rho_A_field_real)
        mu_A_simple  = _transform_rho_mu_to_simple_coords(mu_A_field_real)
        ucA_real, vcA_real, sA = _run_simple_A(
            rho_A_simple, mu_A_simple, u_A, T_Ain_K, P_ref_abs_seed,
            Re_case=_Re_A_case)

        # 2. Energy solve with Tb prescribed
        Ta, Tb, Ts, e_info = solve_full_domain(
            L_DOM, H_DOM, N_X, N_Y,
            T_Ain_K, T_Bin_K,
            K_ffA, K_ffB, K_ss,
            h_vA, h_vB,
            rho_cp_A_real, rho_B0 * cp_B0,  # fluid-B rho_cp scalar (frozen Tb)
            EPS,
            ucA_real, vcA_real, ucB_real, vcB_real,
            dir_A=0, dir_B=3,
            Tb_prescribed=Tb_prescribed,
            tol=0.5, max_iter=5000, return_info=True,
            dx_arr=DX_REFINED, dy_arr=DY_REFINED,
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
        )

        # 3. Update rho / mu / rho_cp from per-cell T and local absolute P
        P_abs_A = _transform_simple_P_to_real(sA)  # (N_X, N_Y)
        rho_A_new = air_density(Ta, P_abs_A).astype(np.float64)
        mu_A_new  = air_viscosity(Ta).astype(np.float64)
        rho_cp_A_new = rho_A_new * air_cp(Ta).astype(np.float64)

        # 4. Convergence diagnostics (drho mass-flux weighted AND dT max)
        w = np.sqrt(ucA_real ** 2 + vcA_real ** 2) + 1e-12
        drho_A = float(np.sum(np.abs((rho_A_new - rho_A_field_real) /
                                      rho_A_field_real) * w) / np.sum(w))
        if Ta_prev is not None:
            dT_A = float(np.max(np.abs(Ta - Ta_prev)))
        else:
            dT_A = float('inf')

        print(f"  Case {case:2d} [iter {_coup_it+1}] drho_A={drho_A:.4f} "
              f"dT_A={dT_A:.2f}K  T_avg={float(Ta.mean()):.1f}K")

        if drho_A < _COUPLING_TOL and dT_A < _DT_TOL_K:
            coupling_converged = True
            break

        # 5. Under-relax + prep next iteration
        Ta_prev = Ta.copy()
        rho_A_field_real = _ALPHA_COUP * rho_A_new + (1.0 - _ALPHA_COUP) * rho_A_field_real
        mu_A_field_real  = _ALPHA_COUP * mu_A_new  + (1.0 - _ALPHA_COUP) * mu_A_field_real
        if np.ndim(rho_cp_A_real) == 0:
            rho_cp_A_real = rho_cp_A_new.copy()
        else:
            rho_cp_A_real = _ALPHA_COUP * rho_cp_A_new + (1.0 - _ALPHA_COUP) * rho_cp_A_real

    # ── Extract dP (pipe-weighted) via same utility as UI ──
    dP_A_sim = float(extract_dP_from_simple(sA))

    # ── Q_sim: enthalpy-based (Option C, 2026-04-24 alignment with UI 2D).
    # Old code reported Q_enthalpy_A. Q_solid_B is kept as a diagnostic — it
    # is the signed volume integral ∑h_vB·(Ts−Tb), the quantity that flipped
    # negative before the Option-C refactor. Q_total_max matches the UI
    # Q_total = max(|Q_A|, |Q_B|). B is prescribed via Tb so Q_enthalpy_B
    # cannot be independently recovered; fall back to Q_enthalpy_A.
    cell_area = DX_REFINED[:, None] * DY_REFINED[None, :]
    Q_solid_A = float(np.sum(h_vA * (Ta - Ts) * cell_area))   # air → solid
    Q_solid_B = float(np.sum(h_vB * (Ts - Tb) * cell_area))   # solid → water
    eb_resid_pct = (Q_solid_A - Q_solid_B) / max(abs(Q_solid_A), 1e-30) * 100.0
    T_A_out_mean = float(np.mean(Ta[-1, :]))
    Q_enthalpy_A = float(m_air * cp_A0 * (T_Ain_K - T_A_out_mean))
    Q_enthalpy_B_est = float(np.sum(h_vB * (Ts - Tb) * cell_area))  # = Q_solid_B
    Q_total_max = max(abs(Q_enthalpy_A), abs(Q_enthalpy_B_est))
    Q_sim = Q_enthalpy_A  # keep as primary vs experiment (m·cp·ΔT matches)

    err_dP = (dP_A_sim - dP_A_exp) / dP_A_exp * 100 if dP_A_exp != 0 else float('nan')
    err_Q  = (Q_sim   - Q_exp ) / Q_exp   * 100 if Q_exp   != 0 else float('nan')

    results.append({
        'Case': case, 'u_air': round(u_A, 2), 'u_water': round(u_B, 4),
        'T_air_in': round(T_Ain_C, 1), 'T_water_in': round(T_Bin_C, 1),
        'P_in_abs_kPa': round(P_Ain / 1000.0, 1),
        'dP_air_exp': round(dP_A_exp), 'dP_air_sim': round(dP_A_sim),
        'err_dP%': round(err_dP, 1),
        'Q_exp': round(Q_exp, 1), 'Q_sim': round(Q_sim, 1), 'err_Q%': round(err_Q, 1),
        'Q_solid_A': round(Q_solid_A, 1),
        'Q_solid_B': round(Q_solid_B, 1),
        'eb_resid%': round(eb_resid_pct, 4),
        'Q_enthalpy_A': round(Q_enthalpy_A, 1),
        'Q_total_max': round(Q_total_max, 1),
        'outer_iters': outer_iters, 'converged': coupling_converged,
        'h_vA': round(h_vA, 1), 'h_vB': round(h_vB, 1),
    })

    print(f"Case {case:2d}: dP {dP_A_exp:.0f}/{dP_A_sim:.0f} ({err_dP:+.0f}%)  "
          f"Q {Q_exp:.0f}/{Q_sim:.0f} ({err_Q:+.1f}%)  "
          f"Q_sA={Q_solid_A:.1f} Q_sB={Q_solid_B:.1f} eb={eb_resid_pct:+.3f}%  "
          f"iters={outer_iters} conv={coupling_converged}\n")


# ── Summary + save ──
out_df = pd.DataFrame(results)
err_dp = np.array([r['err_dP%'] for r in results])
err_q  = np.array([r['err_Q%']  for r in results])
print('='*72)
print(f"RMSRE_dP = {np.sqrt(np.mean(err_dp**2)):.2f}%   "
      f"mean_bias_dP = {np.mean(err_dp):+.2f}%   "
      f"max|err_dP| = {np.max(np.abs(err_dp)):.1f}%")
print(f"RMSRE_Q  = {np.sqrt(np.mean(err_q**2)):.2f}%   "
      f"mean_bias_Q  = {np.mean(err_q):+.2f}%   "
      f"max|err_Q|  = {np.max(np.abs(err_q)):.1f}%")

out_path = r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\shanghai_validation_aligned.xlsx'
out_df.to_excel(out_path, index=False, engine='openpyxl')
print(f"\nSaved: {out_path}")
