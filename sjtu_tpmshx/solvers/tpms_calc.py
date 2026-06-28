"""
tpms_calc.py — TPMS Property Calculator

Given TPMS geometry (type, L_cell, t) and flow conditions (u, T_in, P_in),
computes all parameters needed by solve.py:
  epsilon, A_0, D_h, Re, Nu, f, dP/L, H_sf, K_ff, K_ss, rho, mu, k_f

Includes:
  - Geometry via numerical TPMS voxelization (epsilon, A_0 for any L, t)
  - Air property correlations (Sutherland, ideal gas)
  - Nu correlations (Diamond / Gyroid)
  - Darcy-Forchheimer dP closure (no f-Re): dP via df_surrogate K / c_F

Supported TPMS types: 'Diamond', 'Gyroid'
Fluid: air (Pr = 0.72, properties from T_in and P_in)

──────────────────────────────────────────────────────────────────────
REYNOLDS NUMBER CONVENTION (project-wide, confirmed 2026-04-22)
──────────────────────────────────────────────────────────────────────

All Re computations use hydraulic diameter D_h:

    Re = ρ · u · D_h / μ    (single-channel interstitial u)

Training Excel (试验记录表_整理版.xlsx) mass flow back-calculation:
    m_total = Re × μ / D_h × A_cross × 2   (×2 = two TPMS channels)

The ×2 is for converting single-channel to total mass flow, NOT for
the Re definition. Nu correlations fitted on D_h Re.

Nu OUTPUT convention: Nu = h · D_h / k_f   (standard D_h definition).

Nu correlations take D_h-convention Re as input
but output D_h-convention Nu. All solver callers use the correct
convention on both sides, so downstream Q calculations are consistent.
──────────────────────────────────────────────────────────────────────
"""

import functools
import os
import warnings
import numpy as np
from .tpms_geometry import compute_geometry as _tpms_geom

# ── Physical constants ────────────────────────────────────────
Pr    = 0.72       # Prandtl number (air, approximately constant)
Sa_mm = 0.031      # Surface roughness Sa [mm]  (= 31 μm, constant for both TPMS types)
R     = 8.314      # Universal gas constant [J/(mol·K)]
M_air = 0.028966   # Molar mass of dry air [kg/mol]
P_atm = 101325.0   # Standard atmospheric pressure [Pa] (for Re reference density)


# ── Air property correlations ─────────────────────────────────

# Validity ranges for the fitted correlations (per docstrings below).
_AIR_T_RANGE    = (200.0, 1100.0)   # Sutherland + kappa fits
_AIR_CP_RANGE   = (250.0, 1000.0)   # polynomial cp fit
_WATER_T_RANGE  = (273.15, 363.15)  # 0 - 90 °C polynomial water fits

_range_warnings_emitted = set()

# Robustness (2026-06-25): water properties are single-phase liquid fits. Above
# the 1-atm saturation temperature water is two-phase / superheated and these
# correlations are physically meaningless. Warn loudly once (the prop functions
# only receive T, not P, so 373.15 K is used as a conservative threshold).
_WATER_T_SAT_1ATM = 373.15
_WATER_TWO_PHASE_WARNED = set()


def _warn_water_two_phase(T) -> None:
    T_arr = np.asarray(T, dtype=float)
    if T_arr.size == 0:
        return
    T_max = float(T_arr.max())
    if T_max > _WATER_T_SAT_1ATM:
        key = round(T_max, 1)
        if key in _WATER_TWO_PHASE_WARNED:
            return
        _WATER_TWO_PHASE_WARNED.add(key)
        warnings.warn(
            f"water properties requested at T={T_max:.1f} K > 1-atm "
            f"saturation 373.15 K: water is likely two-phase / superheated, "
            "single-phase liquid correlations are not physical here.",
            stacklevel=3)


def _warn_range_once(name: str, T, lo: float, hi: float) -> None:
    """Emit a single UserWarning per (name) key when T goes outside the
    fitted validity range. Keeps logs readable when coupled solvers
    call these functions millions of times per run."""
    T_arr = np.asarray(T, dtype=float)
    if T_arr.size == 0:
        return
    T_min = float(T_arr.min())
    T_max = float(T_arr.max())
    if T_min < lo or T_max > hi:
        key = (name, round(T_min, 1), round(T_max, 1))
        if key in _range_warnings_emitted:
            return
        _range_warnings_emitted.add(key)
        warnings.warn(
            f"{name}: T=[{T_min:.1f}, {T_max:.1f}] K outside fitted range "
            f"[{lo:.1f}, {hi:.1f}] K — extrapolating.",
            stacklevel=3,
        )


def air_viscosity(T_K: float) -> float:
    """Dynamic viscosity of air via Sutherland's law [Pa·s]."""
    _warn_range_once('air_viscosity', T_K, *_AIR_T_RANGE)
    T0, mu0, S = 273.15, 1.716e-5, 110.4
    return mu0 * (T_K / T0) ** 1.5 * (T0 + S) / (T_K + S)


def air_conductivity(T_K: float) -> float:
    """Thermal conductivity of air [W/(m·K)]."""
    _warn_range_once('air_conductivity', T_K, *_AIR_T_RANGE)
    return 0.0241 * (T_K / 273.15) ** 0.82


def air_density(T_K, P_Pa: float = 101325.0):
    """Density of air via ideal gas law [kg/m³]. Accepts scalar or ndarray T_K;
    return type matches input shape."""
    return P_Pa * M_air / (R * T_K)


def air_cp(T_K):
    """Specific heat capacity of air [J/(kg·K)] (250-1000 K, < 0.5% error).
    Accepts scalar or ndarray T_K; return type matches input shape."""
    _warn_range_once('air_cp', T_K, *_AIR_CP_RANGE)
    dT = T_K - 273.15
    return 1004.5 + 0.172 * dT - 7.56e-5 * dT**2


# ── Water property correlations ───────────────────────────────

def water_density(T_K):
    """Density of liquid water [kg/m³]. Polynomial valid 0-90 °C."""
    _warn_range_once('water_density', T_K, *_WATER_T_RANGE)
    _warn_water_two_phase(T_K)
    T_C = np.asarray(T_K, dtype=float) - 273.15
    return 999.84 - 0.05 * T_C - 0.004 * T_C**2


def water_viscosity(T_K):
    """Dynamic viscosity of liquid water [Pa·s].

    Vogel form (Andrade equation), NIST 0–90 °C max error < 2 %:
        mu = 2.414e-5 * 10^(247.8 / (T_K - 140))   [Pa·s, T_K in K]

    Replaced legacy `1.79e-3·exp(-0.035·T_C)` (2026-04-29) which decayed
    far too fast (-33 % at 40 °C, -53 % at 60 °C vs NIST). The legacy
    formula matched only 0–15 °C; Shanghai water bulk T 20-40 °C was
    systematically under-viscous → over-predicted Re_water ~50 % at hi T.
    """
    _warn_range_once('water_viscosity', T_K, *_WATER_T_RANGE)
    _warn_water_two_phase(T_K)
    T_K_arr = np.asarray(T_K, dtype=float)
    # Floor the (T-140) denominator at 10 K so the 10**(247.8/denom) term stays
    # finite: at T~141 K the raw exponent ~247.8 overflows to +inf in float64
    # (robustness 2026-06-25). Physical liquid water (T>=273 K -> denom>=133)
    # is far above the floor, so this is bit-identical in range.
    denom = np.maximum(T_K_arr - 140.0, 10.0)
    return 2.414e-5 * 10.0 ** (247.8 / denom)


def water_conductivity(T_K):
    """Thermal conductivity of liquid water [W/(m·K)]. Linear fit 0-90 °C."""
    _warn_range_once('water_conductivity', T_K, *_WATER_T_RANGE)
    T_C = np.asarray(T_K, dtype=float) - 273.15
    return 0.569 + 0.0018 * T_C


def water_cp(T_K):
    """Specific heat of liquid water [J/(kg·K)]. ~constant 280-370 K."""
    _warn_range_once('water_cp', T_K, *_WATER_T_RANGE)
    return 4182.0


def nu_water_gyroid_yan6(Re, Pr):
    """Water-side Nusselt number for Gyroid TPMS, Yan et al 2024 [6].

        Nu = 0.471 · Re^0.627 · Pr^(1/3)

    Source: K. Yan, H. Deng, Y. Xiao, J. Wang, Y. Luo,
    'Thermo-hydraulic performance evaluation through experiment and
    simulation of additive manufactured Gyroid-structured heat exchanger',
    Appl. Therm. Eng. 241 (2024) 122402.
    doi:10.1016/j.applthermaleng.2024.122402

    Validated range: 150 < Re < 3000 (water, AM Gyroid).

    Convention:
      Re = ρ·u·D_h / μ        (single-stream, D_h = 4·ε_A/A_0)
      Nu = h_sf · D_h / k_f   (face heat-transfer coefficient h_sf)
      Pr = μ·c_p / k_f

    Notes:
      * Experiment + CFD double-fit on AM gyroid sample (cell 20 mm).
      * Surface roughness from AM is naturally embedded; do not apply
        an extra ×1.28 roughness factor on top.
      * Project Shanghai cases 3-16 (Re 173-1146) fall in-range.
      * Cases 1-2 (Re 54, 108) extrapolate to lower Re, ≈ -9 % on Nu
        relative to Yan [58] in-range; acceptable since h_vB dominates U.
    """
    return 0.471 * Re ** 0.627 * Pr ** (1.0 / 3.0)


# ── Fluid type validation ─────────────────────────────────────

# 2026-05-09 (option B) — water unblocked for the 2D Compute path. The
# D-F surrogate (predict_K_cF) was fitted on air training data only, so the
# per-cell K / c_F coefficients for water are NOT physically calibrated; the
# water-side dP is a placeholder. Heat transfer is still rigorous via
# nu_water_topo (per-topology direct water-CFD fit, WATER_NU_COEFFS, Re
# 100-50000, smooth-wall, no air ×1.28). Treat water dP as engineering
# estimate; water Q is publication-grade for Gyroid and engineering for Diamond.
_SUPPORTED_FLUIDS = {'air', 'water', 'sco2'}


def parse_fluid_type(combo):
    """Normalise a QComboBox current text to an internal fluid_type key.

    Returns one of: 'air', 'water', 'sco2'.
    """
    t = combo.currentText().lower().replace('₂', '2')
    if 'co2' in t or 'sco' in t:
        return 'sco2'
    if 'water' in t:
        return 'water'
    return 'air'


def validate_fluid_type(fluid_type: str, side: str) -> None:
    """Raise NotImplementedError for fluid types without fitted correlations.

    Air + water + sCO2 are supported. sCO2 (2026-06): Diamond-only Nu
    (nu_sco2_topo, D-7-6) + cF×SCO2_CF_SCALE + CoolProp real-gas props; wired in
    the 2D and 3D pipelines (Phase A = incompressible). sCO2 on a non-Diamond
    lattice still raises (nu_sco2_topo Diamond-only).

    For water:
      * Properties: NIST-grade rho/mu/k (Vogel viscosity, < 2 % vs NIST 0–90 °C).
      * Nu (heat transfer): nu_water_topo — per-topology direct water-CFD
        fit (WATER_NU_COEFFS, Re 100-50000, smooth-wall, no air ×1.28).
        nu_water_from_Re (Pr-substitution) and nu_water_gyroid_yan6 (Yan
        2024 [6]) are retired to cross-check / test only.
      * dP closure: predict_K_cF reuses the air-fit ConstDF-v1 K/c_F. NOT
        physically calibrated for water; dP for water side is engineering
        placeholder. Use validate_shanghai_lumped_dual_nu.py for Shanghai
        air-water Q validation (the production paper baseline).
    """
    if fluid_type not in _SUPPORTED_FLUIDS:
        label = {'water': 'Water', 'sco2': 'sCO₂'}.get(fluid_type, fluid_type)
        raise NotImplementedError(
            f"Fluid {side} = {label} is not supported yet — no fitted "
            f"correlations (Nu / f-Re / D-F surrogate) for this fluid. "
            f"Select Air for now."
        )


# ── Nu correlations ───────────────────────────────────────────
# Single source of truth lives in `solvers.nu_correlations` (2026-05-28
# audit Item 1 / H1). Detailed roughness rationale + known limitations
# moved to that module's docstring.

from .nu_correlations import (
    nu_from_Re,
    nu_vec,
    nu_water_from_Re,
    nu_water_topo,
    nu_sco2_topo,
    NU_ROUGHNESS_FACTOR as _NU_ROUGHNESS_FACTOR,  # back-compat re-export
    NU_RE_FIT_RANGE,
    WATER_NU_RE_RANGE,
    NU_COEFFS,
    SCO2_NU_COEFFS,
    SCO2_NU_RE_RANGE,
)

# Per-fluid Re fit windows for the compute()-level out-of-range warning. The
# Nu correlations have DIFFERENT validated Re ranges per fluid; warning every
# fluid against the air window (400,16000) mis-flagged in-range water/sCO2 and
# silently passed out-of-range sCO2 below 9000 (audit 2026-06-28 N5).
_RE_FIT_RANGE_BY_FLUID = {
    'air': NU_RE_FIT_RANGE,
    'water': WATER_NU_RE_RANGE,
    'sco2': SCO2_NU_RE_RANGE,
}


# ── Geometry-only interface (no fluid needed) ─────────────────
# (Legacy f-Re comments removed 2026-04-23 — f-Re was purged from the
# project on 2026-04-19 in favour of the single-closure ConstDF-v1 D-F
# surrogate. Historical r_h = D_h/2 convention is obsolete — Re is
# D_h-based everywhere; see module docstring.)

# Solid-conduction anisotropy / tortuosity correction.
# The homogenised `K_ss = (1 - eps) * k_s` assumes parallel solid paths
# aligned with the heat-flow direction. Real TPMS wall networks follow
# curved wall paths, so the effective solid conductivity is reduced by
# a chi_s ∈ (0, 1] factor. Default 1.0 preserves the historical value;
# set via environment variable or direct assignment for calibrated runs.
# TODO: replace with numerical homogenisation from a unit-cell simulation
# once the data are fitted (same path as ConstDF-v1 for K_ff).
CHI_S = float(os.environ.get('TPMSHX_CHI_S', '1.0'))

# Fluid-phase thermal dispersion coefficient. K_ff = ε·k_f + C_DISP·ρcp·|u|·D_h.
# Zero default = pure molecular conduction (previous behaviour). Calibrate
# from experimental Nu–Pe data; typical range 0.05-0.3 for TPMS.
C_DISP = 0.0


def geometry(tpms_type: str, L_cell_mm: float, t_mm: float, k_s: float,
             chi_s: float | None = None, N: int = 128) -> dict:
    """
    Return TPMS geometric properties without fluid information.

    Parameters
    ----------
    tpms_type : 'Diamond' or 'Gyroid'
    L_cell_mm : unit cell size [mm]
    t_mm      : wall thickness [mm]
    k_s       : solid thermal conductivity [W/(m·K)]
    chi_s     : solid tortuosity / anisotropy factor (optional, overrides the
                module-level `CHI_S`). K_ss = chi_s * (1 - eps) * k_s.
    N         : voxelisation grid resolution (default 128 as of audit M-d /
                P3 2026-05-28; was 256). The phi grid is N^3 float64
                (16 MiB at N=128 vs 128 MiB at N=256), so the lower default
                cuts per-process memory ~8x for parallel BO with un-shared
                lru_caches. epsilon drift <0.3 % and A_0 drift <1 % vs
                N=256, guarded by test_tpms_geometry_n128.

    Returns
    -------
    dict with keys: epsilon, epsilon_A, epsilon_B, A_0, D_h, K_ss

    Notes
    -----
    epsilon_A = epsilon_B = epsilon / 2 are the per-stream void fractions for
    the bicontinuous sheet HX (two fluid channels sharing the void equally).
    D_h is the single-stream hydraulic diameter D_h = 4·epsilon_A / A_0.
    """
    g = _tpms_geom(tpms_type, L_cell_mm, t_mm, N)
    chi = float(CHI_S if chi_s is None else chi_s)
    return {
        'epsilon':   g['epsilon'],
        'epsilon_A': g['epsilon_A'],
        'epsilon_B': g['epsilon_B'],
        'A_0':       g['A_0'],
        'D_h':       g['D_h'],
        'K_ss':      chi * (1.0 - g['epsilon']) * k_s,
    }


def adaptive_grid(L_domain: float, H_domain: float,
                  D_h: float, alpha: float = 0.4) -> tuple:
    """Compute grid dimensions for a target dx/D_h ratio.

    Parameters
    ----------
    L_domain, H_domain : float — domain size [m]
    D_h    : float — hydraulic diameter [m]
    alpha  : float — target dx/D_h (0.8 coarse, 0.4 display, 0.2 fine)

    Returns
    -------
    Nx, Ny : int
    """
    Nx = max(20, round(L_domain / (alpha * D_h)))
    Ny = max(10, round(H_domain / (alpha * D_h)))
    return Nx, Ny


# ── Main interface ────────────────────────────────────────────

@functools.lru_cache(maxsize=4096)
def compute(tpms_type: str,
            L_cell_mm: float,
            t_mm: float,
            u: float,
            T_in_K: float,
            P_in_Pa: float,
            k_s: float,
            fluid_type: str = 'air') -> dict:
    """
    Compute all TPMS heat-transfer and fluid properties.

    Parameters
    ----------
    tpms_type : 'Diamond' or 'Gyroid'
    L_cell_mm : TPMS unit cell size [mm]  (valid range: 4–8 mm)
    t_mm      : wall thickness [mm]        (valid range: 0.3–0.5 mm)
    u         : fluid (air) velocity [m/s]
    T_in_K    : inlet temperature [K]
    P_in_Pa   : inlet pressure [Pa]
    k_s       : solid thermal conductivity [W/(m·K)]

    Returns
    -------
    dict with keys:
        epsilon   – porosity [-]
        A_0       – single-side specific surface area [m⁻¹] (area seen by one
                    fluid stream per unit total volume — NOT double-sided;
                    see tpms_geometry.py for derivation). h_vA = A_0 × H_sf_A
                    and h_vB = A_0 × H_sf_B therefore do NOT double-count.
        D_h       – hydraulic diameter [m]
        Re        – Reynolds number (based on D_h, interstitial velocity) [-]
        Nu        – Nusselt number [-]
        K_df      – permeability [m²] (ConstDF-v1 D-F closure)
        cF_df     – Forchheimer coefficient [1/m] (ConstDF-v1 D-F closure)
        dP_per_L  – pressure drop per unit length [Pa/m]
        H_sf      – face heat transfer coefficient [W/(m²·K)]
        K_ff      – fluid effective thermal conductivity [W/(m·K)]
        K_ss      – solid effective thermal conductivity [W/(m·K)]
        rho       – air density [kg/m³]
        mu        – air dynamic viscosity [Pa·s]
        k_f       – air thermal conductivity [W/(m·K)]
    """
    # ── Geometry from numerical computation ─────────────────────
    g = _tpms_geom(tpms_type, L_cell_mm, t_mm)
    eps   = g['epsilon']
    A0    = g['A_0']
    D_h_m = g['D_h']
    D_h_mm = D_h_m * 1000.0        # [mm]  (used in Nu correlation)

    # ── Fluid properties at inlet conditions ──────────────────
    # B1 1.1 (2026-06-12): property primitives via the fluid_props
    # registry (water rho ignores P — incompressible; air ideal-gas).
    # Function-level import: fluid_props imports tpms_calc at module level.
    from solvers import fluid_props as _fluids
    _m = _fluids.get(fluid_type)
    # Pass P to all primitives: air/water ignore it (T-only), sCO2 needs it
    # (real-gas cp/mu/k/rho depend on both T and P). Widened 2026-06-26.
    mu = float(_m.mu(T_in_K, P_in_Pa))
    k_f = float(_m.k(T_in_K, P_in_Pa))
    rho = float(_m.rho(T_in_K, P_in_Pa))
    cp_f = float(_m.cp(T_in_K, P_in_Pa))

    # ── Reynolds number ──────────────────────────────────────
    # Re = rho * u * D_h / mu   (length scale = D_h, not r_h)
    #
    # Uses ACTUAL inlet density (at inlet T and inlet P), because physical
    # Nu depends on true Re, not on a canonical atmospheric Re (previous
    # bug was rho_ref=P_atm, which under-predicted high-Re Q by ~22%).
    #
    # D_h convention: Re = ρ·u·D_h / μ (single-channel interstitial u).
    # Training Excel: m_total = Re × μ / D_h × A × 2 (×2 for two channels).
    # Nu correlations fitted on D_h-convention Re.
    Re = rho * u * D_h_m / mu

    # Warn if outside correlation valid range. Single-sourced to the per-fluid
    # fit windows in nu_correlations (was a duplicate hard-coded [600, 30000];
    # unified 2026-06-25). Fluid-aware since 2026-06-28 (N5): water/sCO2 have
    # their own windows, so warning them against the air window mis-flagged.
    _nu_lo, _nu_hi = _RE_FIT_RANGE_BY_FLUID.get(fluid_type, NU_RE_FIT_RANGE)
    if not (_nu_lo <= Re <= _nu_hi):
        warnings.warn(
            f"{tpms_type}: Re = {Re:.1f} is outside the validated range "
            f"[{_nu_lo:.0f}, {_nu_hi:.0f}]. Correlation accuracy may be reduced.",
            UserWarning, stacklevel=2
        )

    # ── Nusselt number and heat transfer coefficient ──────────
    # Single-stream convention (post-refit 2026-04-26): pass ε_A (per-stream
    # void fraction; sheet HX splits ε equally between two fluid channels).
    eps_A = 0.5 * eps
    # 2026-05-09 — route air through nu_from_Re() (not _nu_diamond / _nu_gyroid
    # directly). nu_from_Re applies the ×1.28 _NU_ROUGHNESS_FACTOR
    # (production, see memory project_nu_v3_cfd4_s8 — Shanghai Q RMSRE 2.02%
    # only with ×1.28 applied). Direct calls to _nu_diamond / _nu_gyroid
    # returned the smooth-wall Nu, which under-displayed Nu in the UI by 28%
    # while the SIMPLE/LTNE runtime correctly used ×1.28 via nu_from_Re —
    # cosmetic mismatch that confused users sanity-checking Nu vs Q.
    # Water path routes through nu_water_topo (per-topology direct water-CFD
    # fit, no ×1.28); the ×1.28 _NU_ROUGHNESS_FACTOR is AIR-only. Only the
    # air branch was ever buggy on the ×1.28 display.
    # B1 1.1: Nu via the registry's per-fluid dispatch — water forwards the
    # caller-computed Pr to nu_water_topo; the air adapter ignores Pr and
    # uses nu_from_Re's built-in Pr_AIR.
    Pr_f = mu * cp_f / k_f
    Nu = _m.nu(tpms_type, Re, eps_A, L_cell_mm, D_h_mm, Pr_f)

    H_sf = Nu * k_f / D_h_m        # face heat transfer coefficient [W/(m²·K)]

    # ── Pressure drop via ConstDF-v1 D-F surrogate ──────────────
    # dP/L = μu/K + ρ c_F u² (interstitial form; matches simple_solver
    # convention, see df_surrogate/predict.py).
    from df_surrogate.predict import predict_K_cF, SCO2_CF_SCALE
    K_df, cF_df = predict_K_cF(tpms_type, float(L_cell_mm), float(t_mm),
                               float(eps) / 2.0)
    # sCO2: predict_K_cF returns the GEOMETRIC (air/water-anchored) cF; the
    # D-7-6 field-calibrated effective cF is geometric × SCO2_CF_SCALE (3.39),
    # applied inside the SIMPLE solver for the field path. The lumped compute()
    # path must apply it too, else the UI/quick-estimate dP for sCO2 reads ~3.4×
    # too low (audit 2026-06-28). air/water keep the geometric cF (×1.0).
    if fluid_type == 'sco2':
        cF_df = cF_df * SCO2_CF_SCALE
    dP_per_L = mu * u / K_df + rho * cF_df * u * u

    # ── Effective thermal conductivities (volume-averaged) ────
    # Fluid phase: molecular only by default. Optional thermal dispersion
    # K_disp = C_DISP * ρ·cp·|u|·D_h captures tortuous-channel mixing at
    # high Pe. Zero default preserves prior behaviour; calibrate per TPMS
    # from experimental Nu vs Pe data and expose via compute_ext if needed.
    K_ff = eps * k_f
    if C_DISP > 0.0:
        K_ff = K_ff + C_DISP * rho * cp_f * abs(u) * D_h_m
    K_ss = CHI_S * (1.0 - eps) * k_s

    return {
        'epsilon':   eps,
        'epsilon_A': eps_A,
        'epsilon_B': eps_A,     # symmetric sheet HX: ε_B = ε_A = ε/2
        'A_0':       A0,
        'D_h':       D_h_m,
        'Re':        Re,
        'Nu':        Nu,
        'K_df':      K_df,      # permeability [m²] (ConstDF-v1)
        'cF_df':     cF_df,     # Forchheimer coeff [1/m] (ConstDF-v1)
        'dP_per_L':  dP_per_L,
        'H_sf':      H_sf,
        'K_ff':      K_ff,
        'K_ss':      K_ss,
        'rho':       rho,
        'mu':        mu,
        'k_f':       k_f,
    }


# ── Quick verification ────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 60)
    for name in ('Diamond', 'Gyroid'):
        print(f"{name}  L=8mm  t=0.3mm  u=3m/s  T=300K  P=101325Pa")
        r = compute(name, 8.0, 0.3, 3.0, 300.0, 101325.0, k_s=17.0)
        for k, v in r.items():
            print(f"  {k:10s} = {v:.6g}")
        L_domain = 0.10  # m
        dP = r['dP_per_L'] * L_domain
        print(f"  {'dP':10s} = {dP:.1f} Pa  (L_domain={L_domain}m)")
        print()
    print("=" * 60)
