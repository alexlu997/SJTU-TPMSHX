"""
tpms_calc.py — TPMS Property Calculator

Given TPMS geometry (type, L_cell, t) and flow conditions (u, T_in, P_in),
computes all parameters needed by solve.py:
  epsilon, A_0, D_h, Re, Nu, f, dP/L, H_sf, K_ff, K_ss, rho, mu, k_f

Includes:
  - Geometry via numerical TPMS voxelization (epsilon, A_0 for any L, t)
  - Air property correlations (Sutherland, ideal gas)
  - Nu correlations (Diamond / Gyroid)
  - f-Re friction factor correlations (Diamond / Gyroid)

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
    """Specific heat capacity of air at constant pressure [J/(kg·K)].
    Polynomial fit valid 250-1000K, error < 0.5%.
    Supports scalar or numpy array input.
    """
    _warn_range_once('air_cp', T_K, *_AIR_CP_RANGE)
    dT = T_K - 273.15
    return 1004.5 + 0.172 * dT - 7.56e-5 * dT**2


# ── Water property correlations ───────────────────────────────

def water_density(T_K):
    """Density of liquid water [kg/m³]. Polynomial valid 0-90 °C."""
    _warn_range_once('water_density', T_K, *_WATER_T_RANGE)
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
    T_K_arr = np.asarray(T_K, dtype=float)
    return 2.414e-5 * 10.0 ** (247.8 / (T_K_arr - 140.0))


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
# nu_water_from_Re (Pr-substitution onto the air-fit Nu correlation, with
# Yan [6] available for Gyroid). Treat water dP as engineering estimate;
# water Q is publication-grade for Gyroid and engineering for Diamond.
_SUPPORTED_FLUIDS = {'air', 'water'}


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

    Air + water are supported (option B, 2026-05-09). sCO2 still blocks
    pending a fitted Nu / f-Re / D-F surrogate.

    For water:
      * Properties: NIST-grade rho/mu/k (Vogel viscosity, < 2 % vs NIST 0–90 °C).
      * Nu (heat transfer): nu_water_from_Re — Pr-substitution onto the
        air-fit Diamond / Gyroid correlations (Reynolds analogy). Gyroid
        case 1 also has nu_water_gyroid_yan6 (Yan 2024 [6]) for direct
        cross-check.
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

_NU_ROUGHNESS_FACTOR = 1.28
# Roughness-driven heat-transfer enhancement factor (2026-04-28 re-enable).
#
# Physical rationale (NEW — distinct from 2026-04-23 CFD3 reason):
#   The Nu correlation `_nu_diamond` / `_nu_gyroid` is fitted on CFD data
#   that uses idealised SMOOTH walls. The physical TPMS specimens
#   (additively-manufactured, e.g. SLM Inconel/Ti-6Al-4V) carry surface
#   roughness Sa ≈ 30 µm which augments wall heat transfer beyond the
#   smooth-wall CFD prediction. We therefore rescale the Nu output by a
#   global enhancement factor:
#
#       φ_rough = mean over angles of  Q_exp / Q_DB(Re)
#
#   where Q_exp is the measured experimental heat-transfer rate and
#   Q_DB is the Dittus-Boelter prediction at the matched Re. Averaging
#   across multiple as-printed angles (0°, 30°, 45°, 60°, 90°) on the
#   characterisation rig gives φ_rough ≈ 1.28.
#
# This factor multiplies the smooth-wall Nu uniformly. It is NOT a
# Re-convention correction, NOT a fitting residual, and NOT a Pr
# adjustment — it captures roughness-driven turbulence enhancement
# inside the TPMS channels that CFD smooth-wall cases cannot resolve.
#
# Applied identically in `nu_from_Re` (air, this file) and the inline
# copy `solvers.sigmoid_field._nu_vec` (vectorised path). Both must
# stay in lock-step; sigmoid_field imports the constant from here so a
# single edit propagates.
#
# Historical context (do NOT conflate the two reasons):
#   - CFD3-era (≤ 2026-04-23): ×1.28 was a Re-convention compensation
#     when the production code used a different Re definition than the
#     fit. Removed in 2026-04-23 once Re conventions were aligned.
#   - 2026-04-28: re-introduced with the above experimental-rough
#     justification, and now physically meaningful.
#
# KNOWN LIMITATIONS — Re/geometry-independent scalar (paper disclosure):
#   1. **Re-independent**: Roughness-driven Nu enhancement is physically
#      Re-dependent (Bhatti-Shah 2010, Gnielinski rough-wall correction):
#         laminar Re < 2000  : ε/D_h has minimal effect (φ ≈ 1.0)
#         transition 2-4 k   : φ ramps as turbulent BL forms
#         turbulent  Re > 4 k: φ asymptotes to ~1.2-1.4 at ε/D_h ≈ 1%
#      A constant ×1.28 over-corrects in the laminar part of the fit
#      window (Re ∈ [400, 2000]) and is roughly correct in turbulent.
#      The Shanghai air-side dataset spans Re [526, 9981]; the residual
#      RMSRE of 2.02% indicates the over/under-correction averages out
#      across that distribution but does not validate the factor at
#      individual operating points.
#   2. **Geometry-independent**: same φ for Diamond + Gyroid + all
#      (L, t). Wall curvature differs → equivalent sand-grain roughness
#      differs → φ should vary by 5-10% across the design space. Not
#      captured.
#   3. **Decoupled from f / dP**: Reynolds analogy expects roughness
#      affects friction f and Nu together via approximately
#         Nu_rough/Nu_smooth ≈ (f_rough/f_smooth)^0.5
#      Our dP path uses the ConstDF-v1 D-F surrogate which DOES not
#      apply a smooth-vs-rough rescale, so the φ Nu correction is
#      thermally one-sided. Acceptable when only Q is reported as
#      production; flag when dP and Q are both production-grade.
#   4. **Sa = 31 µm is global**: SLM Ra varies with strut orientation
#      (~25 µm horizontal, ~50 µm vertical for typical Inconel 718).
#      One value approximates a print-orientation-averaged effective
#      roughness; per-cell anisotropy not captured.
#
# RECOMMENDED FUTURE WORK:
#   Replace the scalar φ with a Re-dependent enhancement function:
#       Nu_rough(Re, ε/D_h) = Nu_smooth(Re) · g(Re, ε/D_h)
#   where g is fit from Bhatti-Shah / Nikuradse style correlations or
#   re-fit directly on experimental data (skip smooth-wall CFD ground
#   truth). Until then, restrict published Nu/Q claims to the Shanghai
#   parameter window and document the φ scope in any methods section.
#
# STATUS UPDATE 2026-05-14 (limitation #3 above — current standing):
#   `solvers/roughness.py` `norris_1a` mode is now a no-op for friction
#   (multiplier 1.0). The ×1.28 Nu factor here is the ONLY roughness
#   compensation; it lives on the Q side only because c_F is trained
#   on real SLM dP (encodes Sa-driven friction implicitly — any f-side
#   multiplier would double-count). Earlier 1.46 / 1.28 f-side revisions
#   reverted on 2026-05-14.
#   The full Re-dep g(Re, ε/D_h) still lives under mode 'bhatti_shah_1b'.
#   Active in 3D paths only (UI 3D + BO 3D + validate_shanghai_3d_real);
#   2D over-corrects under Norris and stays at baseline. Production 3D
#   mode = `norris_1a` (alias of baseline for f).
#   ⚠ TEMPORARY per user 2026-05-14 — replacement candidates in memory.


def _nu_diamond(Re: float, eps_f: float, L_mm: float, D_h_mm: float) -> float:
    """Diamond TPMS Nu correlation (single-stream convention, simple PL 3p).

    INPUT:
      Re    = ρ·u·D_h / μ           (D_h-based, single-stream u)
      eps_f = ε_full / 2             (single-stream porosity, unused — kept for API)
      L_mm:    unit cell size [mm]
      D_h_mm:  hydraulic diameter [mm]

    OUTPUT: Nu = h·D_h / k_f         (standard, smooth wall)

    Form (3p pure power-law, Pr^(1/3) explicit, Pr=0.72 air const):
      Nu = c · Pr^(1/3) · Re^a · (D_h/L)^d

    Refit 2026-04-28 on 试验记录表_整理版_v3.1.xlsx (Diamond_汇总 sheet,
    Nu_pre_deepseek column, all blocks consistent). Coefficients per
    user-locked fit: c=0.0944, a=0.8273, d=0.226. Numerically identical
    to 2026-04-27 v4 fit within rounding (was c=0.094440, d=0.2260).
    Boundary effect coefficient ignored (smooth-wall reference).
    """
    del eps_f  # not used — kept for backward-compatible signature
    return 0.0944 * Pr ** (1/3) * Re ** 0.8273 * (D_h_mm / L_mm) ** 0.226


_NU_RE_FIT_MIN = 400.0
_NU_RE_FIT_MAX = 16000.0
_NU_EXTRAP_WARNED = {'lo': False, 'hi': False}


def nu_from_Re(tpms_type: str, Re: float, eps_f: float,
               L_mm: float, D_h_mm: float) -> float:
    """Compute Nu from Re for any TPMS type (public interface).

    Convention (post-refit 2026-04-26):
      Re input:   D_h-based, single-stream u
      eps_f input: single-stream porosity = full TPMS ε / 2
      Nu output:  standard h·D_h / k_f

    Caller must pass ε_f = g['epsilon'] / 2.0 (NOT full ε).
    See `fit_nu_single_stream.py` and audit doc for derivation.

    Out-of-fit Re emits a one-shot UserWarning per direction (low/high)
    instead of clipping or raising — extrapolated Nu is still returned so
    the user can see the prediction. Fit window: Re ∈ [400, 16000].
    """
    Re_f = float(Re)
    if Re_f < _NU_RE_FIT_MIN and not _NU_EXTRAP_WARNED['lo']:
        import warnings as _w_nu
        _w_nu.warn(
            f"[Nu extrap] Re={Re_f:.0f} < fit floor {_NU_RE_FIT_MIN:.0f} "
            f"(tpms={tpms_type}); Nu correlation extrapolated. "
            "Suppressing further low-Re warnings this session.",
            stacklevel=2)
        _NU_EXTRAP_WARNED['lo'] = True
    elif Re_f > _NU_RE_FIT_MAX and not _NU_EXTRAP_WARNED['hi']:
        import warnings as _w_nu
        _w_nu.warn(
            f"[Nu extrap] Re={Re_f:.0f} > fit ceiling {_NU_RE_FIT_MAX:.0f} "
            f"(tpms={tpms_type}); Nu correlation extrapolated. "
            "Suppressing further high-Re warnings this session.",
            stacklevel=2)
        _NU_EXTRAP_WARNED['hi'] = True
    if tpms_type == 'Diamond':
        Nu_smooth = _nu_diamond(Re_f, eps_f, L_mm, D_h_mm)
    else:
        Nu_smooth = _nu_gyroid(Re_f, eps_f, L_mm, D_h_mm)
    return _NU_ROUGHNESS_FACTOR * Nu_smooth


def nu_water_from_Re(tpms_type: str, Re: float, eps_f: float,
                     L_mm: float, D_h_mm: float, Pr_water: float) -> float:
    """Water-side Nu via Pr-substitution into the air-fitted correlation.

    Reynolds analogy (Dittus-Boelter, Sieder-Tate basis): Pr enters Nu
    as Pr^(1/3), so swapping the working fluid only rescales Nu by
    (Pr_water / Pr_air)^(1/3). Re uses water properties.

    Air-side Nu uses 3p pure power-law (Re, D_h/L, Pr^(1/3)) fit on
    试验记录表_整理版_v3 (Pr=0.72 air const explicit). Water side rescales by
    (Pr_water/Pr_air)^(1/3) on top, since Pr^(1/3) is multiplicative in form.
    **Not independently fitted on water-side data** (training set is air-only).
    Use for engineering h_water estimate; quote Reynolds-analogy + literature
    cross-check (Wakao-Kaguei packed bed, Dittus-Boelter pipe) when reporting.
    """
    Re_f = float(Re)
    Nu_air = nu_from_Re(tpms_type, Re_f, eps_f, L_mm, D_h_mm)
    return Nu_air * (Pr_water / Pr) ** (1.0 / 3.0)


def _nu_gyroid(Re: float, eps_f: float, L_mm: float, D_h_mm: float) -> float:
    """Gyroid TPMS Nu correlation (single-stream convention, simple PL 3p).

    INPUT:
      Re    = ρ·u·D_h / μ           (D_h-based, single-stream u)
      eps_f = ε_full / 2             (single-stream porosity, unused — kept for API)
      L_mm:    unit cell size [mm]
      D_h_mm:  hydraulic diameter [mm]

    OUTPUT: Nu = h·D_h / k_f         (standard, smooth wall)

    Form (3p pure power-law, Pr^(1/3) explicit, Pr=0.72 air const):
      Nu = c · Pr^(1/3) · Re^a · (D_h/L)^d

    Refit 2026-04-28 on 试验记录表_整理版_v3.1.xlsx (Gyroid_汇总 sheet,
    Nu_pre_deepseek column). User-locked fit: c=0.126, a=0.7898, d=0.2409.
    Numerically ≈ log-LSQ optimum (drift d 0.2409 vs 0.2325 in v4 only).
    Boundary effect coefficient ignored (smooth-wall reference).
    """
    del eps_f  # not used — kept for backward-compatible signature
    return 0.126 * Pr ** (1/3) * Re ** 0.7898 * (D_h_mm / L_mm) ** 0.2409


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
             chi_s: float | None = None) -> dict:
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

    Returns
    -------
    dict with keys: epsilon, epsilon_A, epsilon_B, A_0, D_h, K_ss

    Notes
    -----
    epsilon_A = epsilon_B = epsilon / 2 are the per-stream void fractions for
    the bicontinuous sheet HX (two fluid channels sharing the void equally).
    D_h is the single-stream hydraulic diameter D_h = 4·epsilon_A / A_0.
    """
    g = _tpms_geom(tpms_type, L_cell_mm, t_mm)
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
        f         – friction factor (from f-Re correlation) [-]
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
    # 2026-05-09 — water dispatch added (option B). Water rho is taken
    # incompressible (P_in_Pa ignored). Air uses ideal-gas density.
    if fluid_type == 'water':
        mu  = float(water_viscosity(T_in_K))
        k_f = float(water_conductivity(T_in_K))
        rho = float(water_density(T_in_K))
        cp_f = float(water_cp(T_in_K))
    else:
        mu  = air_viscosity(T_in_K)
        k_f = air_conductivity(T_in_K)
        rho = air_density(T_in_K, P_in_Pa)
        cp_f = air_cp(T_in_K)

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

    # Warn if outside correlation valid range
    if not (600 <= Re <= 30000):
        warnings.warn(
            f"{tpms_type}: Re = {Re:.1f} is outside the validated range [600, 30000]. "
            "Correlation accuracy may be reduced.",
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
    # Water path already routes through nu_water_from_Re → nu_from_Re,
    # so it picked up ×1.28 correctly; only the air branch was buggy.
    if fluid_type == 'water':
        # Pr-substitution onto the air-fit correlation (Reynolds analogy).
        # Pr_water = mu * cp / k_f. Falls back to nu_water_from_Re for
        # consistent dispatch over Diamond / Gyroid.
        Pr_water = mu * cp_f / k_f
        Nu = nu_water_from_Re(tpms_type, Re, eps_A, L_cell_mm, D_h_mm,
                              Pr_water)
    else:
        Nu = nu_from_Re(tpms_type, Re, eps_A, L_cell_mm, D_h_mm)

    H_sf = Nu * k_f / D_h_m        # face heat transfer coefficient [W/(m²·K)]

    # ── Pressure drop via ConstDF-v1 D-F surrogate ──────────────
    # dP/L = μu/K + ρ c_F u² (interstitial form; matches simple_solver
    # convention, see df_fit/predict.py).
    from df_fit.predict import predict_K_cF
    K_df, cF_df = predict_K_cF(tpms_type, float(L_cell_mm), float(t_mm),
                               float(eps) / 2.0)
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
