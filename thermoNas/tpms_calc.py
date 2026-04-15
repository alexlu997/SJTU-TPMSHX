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
"""

import functools
import warnings
import numpy as np
from tpms_geometry import compute_geometry as _tpms_geom

# ── Physical constants ────────────────────────────────────────
Pr    = 0.72       # Prandtl number (air, approximately constant)
Sa_mm = 0.031      # Surface roughness Sa [mm]  (= 31 μm, constant for both TPMS types)
R     = 8.314      # Universal gas constant [J/(mol·K)]
M_air = 0.028966   # Molar mass of dry air [kg/mol]
P_atm = 101325.0   # Standard atmospheric pressure [Pa] (for Re reference density)


# ── Air property correlations ─────────────────────────────────

def air_viscosity(T_K: float) -> float:
    """Dynamic viscosity of air via Sutherland's law [Pa·s]."""
    T0, mu0, S = 273.15, 1.716e-5, 110.4
    return mu0 * (T_K / T0) ** 1.5 * (T0 + S) / (T_K + S)


def air_conductivity(T_K: float) -> float:
    """Thermal conductivity of air [W/(m·K)]."""
    return 0.0241 * (T_K / 273.15) ** 0.82


def air_density(T_K, P_Pa: float = 101325.0):
    """Density of air via ideal gas law [kg/m³]. Supports scalar or array T_K."""
    return P_Pa * M_air / (R * T_K)


def air_cp(T_K):
    """Specific heat capacity of air at constant pressure [J/(kg·K)].
    Polynomial fit valid 250-1000K, error < 0.5%.
    Supports scalar or numpy array input.
    """
    dT = T_K - 273.15
    return 1004.5 + 0.172 * dT - 7.56e-5 * dT**2


# ── Nu correlations ───────────────────────────────────────────

def _nu_diamond(Re: float, eps: float, D_h_mm: float) -> float:
    """Diamond TPMS Nu correlation.  Re = ρ u D_h / μ,  D_h in mm."""
    n = 0.618 - 0.800 * np.log(eps)
    return 0.008 * Pr ** (1 / 3) * Re ** n * eps ** 7.41 * (D_h_mm / (1000 * Sa_mm)) ** (-1.92)


def nu_from_Re(tpms_type: str, Re: float, eps: float,
               L_mm: float, D_h_mm: float) -> float:
    """Compute Nu from Re for any TPMS type (public interface)."""
    if tpms_type == 'Diamond':
        return _nu_diamond(Re, eps, D_h_mm)
    return _nu_gyroid(Re, eps, L_mm)


def _nu_gyroid(Re: float, eps: float, L_cell_mm: float) -> float:
    """Gyroid TPMS Nu correlation.  Re = ρ u D_h / μ,  L_cell in mm."""
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
# Re = rho_ref * u * r_h / mu  (rho_ref at atmospheric pressure)
# f  = 2*(dP/L)*r_h / (rho*u^2)
# r_h = D_h / 2 = eps / A_0
# Sa = 31 um = 0.031 mm (surface roughness, constant)
# dP/L = f * rho * u^2 / (2 * r_h)
#
# IMPORTANT: eps in the correlation is the SINGLE-CHANNEL porosity (eps_full/2),
# because each fluid flows through only one side of the TPMS.
# Callers pass full eps; friction_factor() divides by 2 internally.
# Coefficients were reparameterized from the original fit (which used eps_full)
# via: C_new = C_old * 2^a, n0_new = n0_old + n1*ln(2).
#
# Fitted on corrected experimental data, Re >= 600, outliers removed.
# Diamond MAPE: 7.4% (156 pts), Gyroid MAPE: 6.7% (189 pts).
# Valid range: Re 600–30000, eps_full 0.53–0.88, L 4–8mm, t 0.3–0.5mm.

# Coefficients: (C, n0, n1, a, b, c) — reparameterized for single-channel eps
_F_COEFFS = {
    'Diamond': (0.006786, 0.271020, 0.4363, -3.47, -0.50, -1.03),
    'Gyroid':  (0.059472, 0.238731, 0.4304, -3.25, -0.02, -1.37),  # v1 reparam for eps/2
    # v2 backup (eps/2): (0.000697, 0.721984, 0.430400, -3.2500, -0.0200, -1.3700)
    # Original v1 (eps_full): (0.5658, -0.0596, 0.4304, -3.25, -0.02, -1.37)
    # Original v2 (eps_full): (0.006634, 0.423653, 0.430400, -3.25, -0.02, -1.37)
}

# Geometry correction for t outside training range [0.3, 0.5]mm.
# phi(t) = (t_max/t)^gamma when t > t_max, else 1.0.
# Calibrated on (L=7, t=0.6) experimental data: gamma=4.523.
_T_TRAIN_MAX = {'Diamond': 0.5, 'Gyroid': 0.5}   # mm, training upper bound
_GAMMA_CORR  = {'Diamond': 0.0, 'Gyroid': 4.523}  # 0 = no correction (no data)


def _phi_t_correction(tpms_type: str, t_mm: float) -> float:
    """Geometry correction factor for t outside training range."""
    t_max = _T_TRAIN_MAX.get(tpms_type, 0.5)
    gamma = _GAMMA_CORR.get(tpms_type, 0.0)
    if gamma > 0.0 and t_mm > t_max:
        return (t_max / t_mm) ** gamma
    return 1.0


def friction_factor(tpms_type: str, Re: float, eps: float,
                    t_mm: float, L_mm: float,
                    D_h_mm: float = None) -> float:
    """
    Dimensionless friction factor for TPMS porous media.

    f = C * Re^n * eps^a * (t/L)^b * (X/(1000*Sa))^c
    n = n0 + n1*ln(eps)

    Length scale X: D_h (Diamond) or L (Gyroid), same as Nu correlation.

    Parameters
    ----------
    tpms_type : 'Diamond' or 'Gyroid'
    Re        : Reynolds number = rho_ref * u * r_h / mu  [-]
    eps       : porosity [-]
    t_mm      : wall thickness [mm]
    L_mm      : unit cell size [mm]
    D_h_mm    : hydraulic diameter [mm]. If None, computed from
                TPMS geometry (requires tpms_geometry module).

    Returns
    -------
    f : friction factor [-]
    """
    if D_h_mm is None:
        g = _tpms_geom(tpms_type, L_mm, t_mm)
        D_h_mm = g['D_h'] * 1000.0

    C, n0, n1, a, b, c = _F_COEFFS[tpms_type]
    eps_f = eps / 2.0  # single-channel porosity (each fluid occupies one side of TPMS)
    n = n0 + n1 * np.log(eps_f)

    # Length scale: Diamond uses D_h, Gyroid uses L (same as Nu)
    if tpms_type == 'Diamond':
        X = D_h_mm
    else:
        X = L_mm

    f = C * Re**n * eps_f**a * (t_mm / L_mm)**b * (X / (1000 * Sa_mm))**c
    return f * _phi_t_correction(tpms_type, t_mm)


def pressure_drop(tpms_type: str, L_mm: float, t_mm: float,
                  eps: float, D_h: float, u_c: float,
                  mu: float, rho: float, T_K: float) -> dict:
    """
    Pressure drop via f–Re correlation.

    Parameters
    ----------
    tpms_type : 'Diamond' or 'Gyroid'
    L_mm      : unit cell size [mm]
    t_mm      : wall thickness [mm]
    eps       : porosity [-]
    D_h       : hydraulic diameter [m]  (= 2*eps/A_0)
    u_c       : pore (interstitial) velocity [m/s]
    mu        : dynamic viscosity [Pa·s]
    rho       : density [kg/m³] (actual, used for dP calculation)
    T_K       : inlet temperature [K] (used for reference density in Re)

    Returns
    -------
    dict with keys: f, Re, dP_per_L
    """
    r_h     = D_h / 2.0
    rho_ref = air_density(T_K, P_atm)        # reference density at atmospheric pressure
    Re      = rho_ref * u_c * r_h / mu       # Re uses reference density
    f       = friction_factor(tpms_type, Re, eps, t_mm, L_mm,
                              D_h_mm=D_h * 1000.0 if D_h is not None else None)
    dP_per_L = f * rho * u_c**2 / (2.0 * r_h)  # dP uses ACTUAL density

    if Re < 600:
        warnings.warn(
            f"{tpms_type}: Re = {Re:.1f} < 600. "
            "f-Re correlation has reduced accuracy below Re = 600.",
            UserWarning, stacklevel=2)

    return {'f': f, 'Re': Re, 'dP_per_L': dP_per_L}


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
    # Re uses REFERENCE density (atmospheric pressure at inlet T),
    # consistent with how CFD data defined Re.
    # This ensures Re is independent of inlet pressure buildup.
    r_h     = D_h_m / 2.0
    rho_ref = air_density(T_in_K, P_atm)
    Re      = rho_ref * u * r_h / mu

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

    # ── Pressure drop via f-Re correlation ──────────────────────
    dp = pressure_drop(tpms_type, L_cell_mm, t_mm, eps, D_h_m, u, mu, rho, T_in_K)

    # ── Effective thermal conductivities (volume-averaged) ────
    K_ff = eps * k_f               # fluid phase [W/(m·K)]
    K_ss = (1.0 - eps) * k_s      # solid phase [W/(m·K)]

    return {
        'epsilon':  eps,
        'A_0':      A0,
        'D_h':      D_h_m,
        'Re':       Re,
        'Nu':       Nu,
        'f':        dp['f'],
        'dP_per_L': dp['dP_per_L'],
        'H_sf':     H_sf,
        'K_ff':     K_ff,
        'K_ss':     K_ss,
        'rho':      rho,
        'mu':       mu,
        'k_f':      k_f,
    }


# ── Pressure field post-processing ────────────────────────────

def compute_pressure_field(tpms_type: str, T_f: np.ndarray,
                           L_mm: float, t_mm: float,
                           eps: float, D_h: float,
                           u: float, P_in: float,
                           dx: float, dy: float,
                           flow_dir: str = '+x',
                           eps_arr=None, D_h_arr=None,
                           L_mm_arr=None, t_mm_arr=None) -> np.ndarray:
    """
    Compute 2D pressure field from temperature field using local fluid properties.

    At each grid point, local T -> local rho, mu -> local Re, f -> local dP/dx.
    Then integrate along flow direction.

    Supports per-cell TPMS parameters via optional *_arr arguments (2D arrays).
    If not provided, scalar values are used uniformly.

    Parameters
    ----------
    tpms_type : 'Diamond' or 'Gyroid'
    T_f       : 2D temperature field [K], shape (N_x, N_y)
    L_mm, t_mm: TPMS geometry [mm] (scalar, used if *_arr not given)
    eps       : porosity [-] (scalar, used if eps_arr not given)
    D_h       : hydraulic diameter [m] (scalar, used if D_h_arr not given)
    u         : pore velocity [m/s]
    P_in      : inlet pressure [Pa]
    dx, dy    : grid spacing [m]
    flow_dir  : '+x', '-x', '+y', '-y'
    eps_arr   : optional 2D array (N_x, N_y), per-cell porosity
    D_h_arr   : optional 2D array (N_x, N_y), per-cell hydraulic diameter [m]
    L_mm_arr  : optional 2D array (N_x, N_y), per-cell unit cell size [mm]
    t_mm_arr  : optional 2D array (N_x, N_y), per-cell wall thickness [mm]

    Returns
    -------
    P : 2D pressure field [Pa], same shape as T_f
    """
    N_x, N_y = T_f.shape
    P = np.zeros_like(T_f)

    # Helper to get per-cell or scalar value
    def _val(arr, scalar, i, j):
        return arr[i, j] if arr is not None else scalar

    def _dP_local(i_prev, j_prev, i_cur, j_cur):
        """Compute local pressure drop from previous cell to current."""
        T_local = T_f[i_prev, j_prev]
        mu_local = air_viscosity(T_local)
        rho_local = air_density(T_local, P[i_prev, j_prev])
        rho_ref = air_density(T_local, P_atm)

        eps_loc = _val(eps_arr, eps, i_prev, j_prev)
        D_h_loc = _val(D_h_arr, D_h, i_prev, j_prev)
        L_loc   = _val(L_mm_arr, L_mm, i_prev, j_prev)
        t_loc   = _val(t_mm_arr, t_mm, i_prev, j_prev)
        r_h_loc = D_h_loc / 2.0

        Re_local = max(rho_ref * u * r_h_loc / mu_local, 10.0)
        f_local = friction_factor(tpms_type, Re_local, eps_loc,
                                  t_loc, L_loc, D_h_loc * 1000.0)
        return f_local * rho_local * u**2 / (2.0 * r_h_loc)

    if flow_dir == '+x':
        P[0, :] = P_in
        for i in range(1, N_x):
            for j in range(N_y):
                P[i, j] = P[i-1, j] - _dP_local(i-1, j, i, j) * dx

    elif flow_dir == '-x':
        P[-1, :] = P_in
        for i in range(N_x - 2, -1, -1):
            for j in range(N_y):
                P[i, j] = P[i+1, j] - _dP_local(i+1, j, i, j) * dx

    elif flow_dir == '-y':
        P[:, -1] = P_in
        for j in range(N_y - 2, -1, -1):
            for i in range(N_x):
                P[i, j] = P[i, j+1] - _dP_local(i, j+1, i, j) * dy

    elif flow_dir == '+y':
        P[:, 0] = P_in
        for j in range(1, N_y):
            for i in range(N_x):
                P[i, j] = P[i, j-1] - _dP_local(i, j-1, i, j) * dy

    return P


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
