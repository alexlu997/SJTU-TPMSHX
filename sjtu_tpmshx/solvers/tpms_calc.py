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
    """Density of air via ideal gas law [kg/m³]. Supports scalar or array T_K."""
    return P_Pa * M_air / (R * T_K)


def air_cp(T_K):
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
    """Dynamic viscosity of liquid water [Pa·s]. Exponential fit 0-90 °C."""
    _warn_range_once('water_viscosity', T_K, *_WATER_T_RANGE)
    T_C = np.asarray(T_K, dtype=float) - 273.15
    return 1.79e-3 * np.exp(-0.035 * T_C)


def water_conductivity(T_K):
    """Thermal conductivity of liquid water [W/(m·K)]. Linear fit 0-90 °C."""
    _warn_range_once('water_conductivity', T_K, *_WATER_T_RANGE)
    T_C = np.asarray(T_K, dtype=float) - 273.15
    return 0.569 + 0.0018 * T_C


def water_cp(T_K):
    """Specific heat of liquid water [J/(kg·K)]. ~constant 280-370 K."""
    _warn_range_once('water_cp', T_K, *_WATER_T_RANGE)
    return 4182.0


# ── Nu correlations ───────────────────────────────────────────

def _nu_diamond(Re: float, eps: float, D_h_mm: float) -> float:
    """Diamond TPMS Nu correlation.

    INPUT  convention: Re = ρ·u·D_h / μ
    OUTPUT convention: Nu = h·D_h / k_f
    """
    n = 0.618 - 0.800 * np.log(eps)
    return 0.008 * Pr ** (1 / 3) * Re ** n * eps ** 7.41 * (D_h_mm / (1000 * Sa_mm)) ** (-1.92)


def nu_from_Re(tpms_type: str, Re: float, eps: float,
               L_mm: float, D_h_mm: float) -> float:
    """Compute Nu from Re for any TPMS type (public interface)."""
    if tpms_type == 'Diamond':
        return _nu_diamond(Re, eps, D_h_mm)
    return _nu_gyroid(Re, eps, L_mm)


def _nu_gyroid(Re: float, eps: float, L_cell_mm: float) -> float:
    """Gyroid TPMS Nu correlation.

    INPUT  convention: Re = ρ·u·D_h / μ
    OUTPUT convention: Nu = h·D_h / k_f

    L_cell_mm is in mm (Gyroid uses unit cell size as length scale).
    """
    n = 0.177 * Re ** 0.1 * eps ** (-2 / 3)
    return 0.17 * Pr ** (1 / 3) * Re ** n * eps ** 2.25 * (L_cell_mm / (1000 * Sa_mm)) ** (-2.01)


# ── Friction factor f–Re correlation ───────────────────────────
#
# F1 power-law form (both Diamond and Gyroid):
#   f = C * Re^n * eps^a * (t/L)^b * (X/(1000*Sa))^c
#   n = n0 + n1*ln(eps)
#
# Length scale X differs by TPMS type (same convention as Nu):
#   Diamond: X = D_h  (hydraulic diameter, mm)
#   Gyroid:  X = L    (unit cell size, mm)
#
# Re convention (r_h, see module docstring): Re = rho_ref * u * r_h / mu
#   where r_h = D_h / 2 = eps / A_0 and rho_ref is at atmospheric pressure.
# Equivalent: Re = rho_ref * u * D_h / (2*mu)   ("D_h with single-stream m/2")
#
# f  = 2*(dP/L)*r_h / (rho*u^2)
# ── Geometry-only interface (no fluid needed) ─────────────────

def geometry(tpms_type: str, L_cell_mm: float, t_mm: float, k_s: float) -> dict:
    """
    Return TPMS geometric properties without fluid information.

    Parameters
    ----------
    tpms_type : 'Diamond' or 'Gyroid'
    L_cell_mm : unit cell size [mm]
    t_mm      : wall thickness [mm]
    k_s       : solid thermal conductivity [W/(m·K)]

    Returns
    -------
    dict with keys: epsilon, A_0, D_h, K_ss
    """
    g = _tpms_geom(tpms_type, L_cell_mm, t_mm)
    return {
        'epsilon': g['epsilon'],
        'A_0':     g['A_0'],
        'D_h':     g['D_h'],
        'K_ss':    (1.0 - g['epsilon']) * k_s,
    }


def adaptive_grid(L_domain, H_domain, D_h, alpha=0.4):
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
            k_s: float) -> dict:
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
        A_0       – specific surface area [m⁻¹]
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

    # ── Air properties at inlet conditions ────────────────────
    mu  = air_viscosity(T_in_K)
    k_f = air_conductivity(T_in_K)
    rho = air_density(T_in_K, P_in_Pa)

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
    if tpms_type == 'Diamond':
        Nu = _nu_diamond(Re, eps, D_h_mm)
    else:
        Nu = _nu_gyroid(Re, eps, L_cell_mm)

    H_sf = Nu * k_f / D_h_m        # face heat transfer coefficient [W/(m²·K)]

    # ── Pressure drop via ConstDF-v1 D-F surrogate ──────────────
    # dP/L = μu/K + ρ c_F u² (interstitial form; matches simple_solver
    # convention, see df_fit/predict.py).
    try:
        from df_fit.predict import predict_K_cF
    except ImportError:
        from sjtu_tpmshx.df_fit.predict import predict_K_cF
    K_df, cF_df = predict_K_cF(tpms_type, float(L_cell_mm), float(t_mm),
                               float(eps) / 2.0)
    dP_per_L = mu * u / K_df + rho * cF_df * u * u

    # ── Effective thermal conductivities (volume-averaged) ────
    K_ff = eps * k_f               # fluid phase [W/(m·K)]
    K_ss = (1.0 - eps) * k_s      # solid phase [W/(m·K)]

    return {
        'epsilon':  eps,
        'A_0':      A0,
        'D_h':      D_h_m,
        'Re':       Re,
        'Nu':       Nu,
        'K_df':     K_df,       # permeability [m²] (ConstDF-v1)
        'cF_df':    cF_df,      # Forchheimer coeff [1/m] (ConstDF-v1)
        'dP_per_L': dP_per_L,
        'H_sf':     H_sf,
        'K_ff':     K_ff,
        'K_ss':     K_ss,
        'rho':      rho,
        'mu':       mu,
        'k_f':      k_f,
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
