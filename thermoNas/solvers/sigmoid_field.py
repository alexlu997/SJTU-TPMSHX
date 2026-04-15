"""
sigmoid_field.py — Continuous L(x,y) and t(x,y) fields via Sigmoid interpolation

Replaces discrete zone assignment with smooth parameter fields.
Control points from the 3×3 inlet/outlet zones + uniform zone are
interpolated using sequential sigmoid paint-over blending.

Includes a precomputed geometry lookup table (LUT) for fast per-cell
evaluation of epsilon(L,t) and A_0(L,t).
"""

import os
import numpy as np
from scipy.interpolate import RegularGridInterpolator

from .tpms_geometry import compute_geometry, _phi_grid, _C_from_tL, _eps_from_C, _A0_from_C
from .tpms_calc import (Pr, Sa_mm, P_atm, _F_COEFFS, _T_TRAIN_MAX, _GAMMA_CORR,
                       air_density, air_viscosity, air_conductivity, air_cp)


# ── Sigmoid basis ────────────────────────────────────────────

def _sigmoid(x, center, width):
    """Smooth sigmoid transition centered at `center`."""
    return 1.0 / (1.0 + np.exp(np.clip(-(x - center) / width, -50, 50)))


def _blend_1d(x, boundaries, values, width):
    """Sequential paint-over sigmoid blend along 1D axis.

    boundaries: N-1 transition points between N regions
    values: list of N value arrays (same shape as x)
    """
    result = values[0].copy() if hasattr(values[0], 'copy') else np.full_like(x, values[0])
    for i, b in enumerate(boundaries):
        alpha = _sigmoid(x, b, width)
        v_next = values[i + 1] if hasattr(values[i + 1], 'copy') else np.full_like(x, values[i + 1])
        result = result * (1.0 - alpha) + v_next * alpha
    return result


# ── 2D Sigmoid field construction ────────────────────────────

def sigmoid_field_2d(XF, YF,
                     ctrl_inlet, ctrl_outlet, val_uniform,
                     y_trans_in, y_trans_out,
                     width_x=0.05, width_y=0.02):
    """Build a smooth 2D field from zone control point values.

    Parameters
    ----------
    XF, YF : 2D arrays (Nx, Ny) — fractional cell centre coordinates [0,1]
    ctrl_inlet : (3, 3) array — values at inlet zone control points [row][col]
                 row 0 = bottom (y=0), col 0 = left (x=0)
    ctrl_outlet : (3, 3) array — values at outlet zone control points
    val_uniform : scalar — uniform zone value
    y_trans_in, y_trans_out : float — fractional transition region sizes
    width_x, width_y : float — sigmoid transition widths

    Returns
    -------
    field : 2D array (Nx, Ny) — smoothly interpolated values
    """
    # X-direction sigmoid weights (shared for all rows)
    s1x = _sigmoid(XF, 1.0 / 3, width_x)
    s2x = _sigmoid(XF, 2.0 / 3, width_x)

    def _xblend(row_vals):
        """Paint-over blend of 3 column values."""
        v = np.full_like(XF, row_vals[0])
        v = v + (row_vals[1] - v) * s1x
        v = v + (row_vals[2] - v) * s2x
        return v

    # Build 7 x-blended layers: 3 inlet + 1 uniform + 3 outlet
    layers = []
    for r in range(3):
        layers.append(_xblend(ctrl_inlet[r]))
    layers.append(np.full_like(XF, val_uniform))
    for r in range(3):
        layers.append(_xblend(ctrl_outlet[r]))

    # Y-direction boundaries (6 transitions between 7 layers)
    dy_in = y_trans_in / 3.0
    dy_out = y_trans_out / 3.0
    y_bounds = [
        dy_in,                          # inlet row 0 → row 1
        2 * dy_in,                      # inlet row 1 → row 2
        y_trans_in,                     # inlet → uniform
        1.0 - y_trans_out,              # uniform → outlet
        1.0 - y_trans_out + dy_out,     # outlet row 0 → row 1
        1.0 - y_trans_out + 2 * dy_out, # outlet row 1 → row 2
    ]

    return _blend_1d(YF, y_bounds, layers, width_y)


# ── Geometry Lookup Table ────────────────────────────────────

class GeometryLUT:
    """Precomputed lookup table for epsilon(L,t) and A_0(L,t).

    Uses bilinear interpolation on a regular (L, t) grid.
    Cached to disk as .npz file for fast loading.
    """

    def __init__(self, tpms_type, L_range=(4.0, 8.0), t_range=(0.3, 0.5),
                 n_L=41, n_t=21, N=256, cache_dir=None):
        self.tpms_type = tpms_type
        self.L_vals = np.linspace(L_range[0], L_range[1], n_L)
        self.t_vals = np.linspace(t_range[0], t_range[1], n_t)
        self.N = N

        if cache_dir is None:
            cache_dir = os.path.dirname(os.path.abspath(__file__))
        self._cache_path = os.path.join(
            cache_dir, f'lut_{tpms_type}_{n_L}x{n_t}.npz')

        if not self._load():
            self._precompute()
            self._save()

        # Build interpolators
        self._interp_eps = RegularGridInterpolator(
            (self.L_vals, self.t_vals), self.eps_table, method='linear',
            bounds_error=False, fill_value=None)
        self._interp_A0 = RegularGridInterpolator(
            (self.L_vals, self.t_vals), self.A0_table, method='linear',
            bounds_error=False, fill_value=None)

    def _precompute(self):
        """Compute epsilon and A_0 over the full (L, t) grid."""
        n_L = len(self.L_vals)
        n_t = len(self.t_vals)
        self.eps_table = np.empty((n_L, n_t))
        self.A0_table = np.empty((n_L, n_t))

        phi = _phi_grid(self.tpms_type, self.N)

        for i, L_mm in enumerate(self.L_vals):
            L_m = L_mm / 1000.0
            for j, t_mm in enumerate(self.t_vals):
                tL = t_mm / L_mm
                C = _C_from_tL(self.tpms_type, tL)
                if C < 0:
                    C = 0.0
                self.eps_table[i, j] = _eps_from_C(phi, C)
                self.A0_table[i, j] = _A0_from_C(phi, C, L_m, self.N)

    def _save(self):
        np.savez_compressed(self._cache_path,
                            L_vals=self.L_vals, t_vals=self.t_vals,
                            eps_table=self.eps_table, A0_table=self.A0_table,
                            tpms_type=np.array([self.tpms_type]))

    def _load(self):
        if not os.path.exists(self._cache_path):
            return False
        try:
            data = np.load(self._cache_path, allow_pickle=True)
            if str(data['tpms_type'][0]) != self.tpms_type:
                return False
            if not np.array_equal(data['L_vals'], self.L_vals):
                return False
            if not np.array_equal(data['t_vals'], self.t_vals):
                return False
            self.eps_table = data['eps_table']
            self.A0_table = data['A0_table']
            return True
        except Exception:
            return False

    def query(self, L_arr, t_arr):
        """Bilinear interpolation on the LUT. Supports 2D array inputs.

        Returns (eps_arr, A0_arr) with same shape as input.
        """
        shape = L_arr.shape
        pts = np.stack([L_arr.ravel(), t_arr.ravel()], axis=-1)
        eps = self._interp_eps(pts).reshape(shape)
        A0 = self._interp_A0(pts).reshape(shape)
        return eps, A0


# Singleton LUT cache
_lut_cache = {}


def get_geometry_lut(tpms_type, **kwargs):
    """Get or create a cached GeometryLUT instance."""
    if tpms_type not in _lut_cache:
        _lut_cache[tpms_type] = GeometryLUT(tpms_type, **kwargs)
    return _lut_cache[tpms_type]


# ── Vectorized property computation ──────────────────────────

def _nu_vec(tpms_type, Re, eps, L_mm, D_h_mm):
    """Vectorized Nu computation for arrays."""
    Re = np.maximum(Re, 10.0)
    if tpms_type == 'Diamond':
        n = 0.618 - 0.800 * np.log(eps)
        return 0.008 * Pr**(1/3) * Re**n * eps**7.41 * (D_h_mm / (1000*Sa_mm))**(-1.92)
    else:
        n = 0.177 * Re**0.1 * eps**(-2/3)
        return 0.17 * Pr**(1/3) * Re**n * eps**2.25 * (L_mm / (1000*Sa_mm))**(-2.01)


def _f_vec(tpms_type, Re, eps, t_mm, L_mm, D_h_mm):
    """Vectorized friction factor for arrays."""
    C, n0, n1, a, b, c = _F_COEFFS[tpms_type]
    Re = np.maximum(Re, 10.0)
    eps_f = eps / 2.0  # single-channel porosity
    n = n0 + n1 * np.log(eps_f)
    X = D_h_mm if tpms_type == 'Diamond' else L_mm
    f = C * Re**n * eps_f**a * (t_mm / L_mm)**b * (X / (1000 * Sa_mm))**c
    # Geometry correction for t outside training range
    t_max = _T_TRAIN_MAX.get(tpms_type, 0.5)
    gamma = _GAMMA_CORR.get(tpms_type, 0.0)
    if gamma > 0.0:
        phi = np.where(t_mm > t_max, (t_max / t_mm) ** gamma, 1.0)
        f = f * phi
    return f


# ── Main entry point ─────────────────────────────────────────

def build_continuous_arrays(x, L0, t0, y_trans_inlet, y_trans_outlet,
                            Nx, Ny, L_domain, H_domain,
                            tpms_type, k_s,
                            u_A, u_B, T_inA, T_inB,
                            lut, P_in=101325.0,
                            sigmoid_width_y=0.02, sigmoid_width_x=0.05,
                            fix_L=False, fix_t=False, opt_axis='y',
                            dx_arr=None, dy_arr=None):
    """Build per-cell property arrays from sigmoid-interpolated L(x,y), t(x,y).

    Parameters
    ----------
    x : (36,) array — decision variables [L1,t1,...,L18,t18]
    L0, t0 : uniform zone parameters [mm]
    lut : GeometryLUT instance
    fix_L : if True, all L values fixed to L0 (optimize t only)
    fix_t : if True, all t values fixed to t0 (optimize L only)

    Returns
    -------
    dict with same keys as ZoneConfig.build_grid_arrays(), plus L_field, t_field
    """
    # 1. Extract control point arrays from decision variables
    ctrl_L_in = np.empty((3, 3))
    ctrl_t_in = np.empty((3, 3))
    ctrl_L_out = np.empty((3, 3))
    ctrl_t_out = np.empty((3, 3))
    for iy in range(3):
        for ix in range(3):
            idx_in = (iy * 3 + ix) * 2
            idx_out = 18 + (iy * 3 + ix) * 2
            ctrl_L_in[iy, ix] = L0 if fix_L else float(x[idx_in])
            ctrl_t_in[iy, ix] = t0 if fix_t else float(x[idx_in + 1])
            ctrl_L_out[iy, ix] = L0 if fix_L else float(x[idx_out])
            ctrl_t_out[iy, ix] = t0 if fix_t else float(x[idx_out + 1])

    # 2. Build fractional coordinate grids (support non-uniform)
    if dx_arr is not None:
        x_frac = (np.cumsum(dx_arr) - dx_arr / 2) / L_domain
    else:
        x_frac = np.linspace(0.5 / Nx, 1.0 - 0.5 / Nx, Nx)
    if dy_arr is not None:
        y_frac = (np.cumsum(dy_arr) - dy_arr / 2) / H_domain
    else:
        y_frac = np.linspace(0.5 / Ny, 1.0 - 0.5 / Ny, Ny)
    XF, YF = np.meshgrid(x_frac, y_frac, indexing='ij')  # (Nx, Ny)

    # 3. Sigmoid-interpolate L and t fields
    L_field = sigmoid_field_2d(XF, YF, ctrl_L_in, ctrl_L_out, L0,
                               y_trans_inlet, y_trans_outlet,
                               sigmoid_width_x, sigmoid_width_y)
    t_field = sigmoid_field_2d(XF, YF, ctrl_t_in, ctrl_t_out, t0,
                               y_trans_inlet, y_trans_outlet,
                               sigmoid_width_x, sigmoid_width_y)

    # Clip to valid range
    L_field = np.clip(L_field, 4.0, 8.0)
    t_field = np.clip(t_field, 0.3, 0.5)

    # 4. Query LUT for epsilon and A_0
    eps_arr, A0_arr = lut.query(L_field, t_field)
    D_h_arr = 2.0 * eps_arr / (A0_arr + 1e-30)  # [m]
    r_h_arr = D_h_arr / 2.0

    # 5. Compute fluid properties (vectorized)
    k_fA = air_conductivity(T_inA)
    mu_A = air_viscosity(T_inA)
    rho_ref_A = air_density(T_inA, P_atm)
    k_fB = air_conductivity(T_inB)
    mu_B = air_viscosity(T_inB)
    rho_ref_B = air_density(T_inB, P_atm)

    # Reynolds, Nusselt, heat transfer coefficient
    Re_A = np.maximum(rho_ref_A * u_A * r_h_arr / mu_A, 10.0)
    Re_B = np.maximum(rho_ref_B * u_B * r_h_arr / mu_B, 10.0)

    D_h_mm = D_h_arr * 1000.0
    Nu_A = _nu_vec(tpms_type, Re_A, eps_arr, L_field, D_h_mm)
    Nu_B = _nu_vec(tpms_type, Re_B, eps_arr, L_field, D_h_mm)

    H_sf_A = Nu_A * k_fA / D_h_arr
    H_sf_B = Nu_B * k_fB / D_h_arr
    h_vA_arr = H_sf_A * A0_arr
    h_vB_arr = H_sf_B * A0_arr

    K_ffA_arr = eps_arr * k_fA
    K_ffB_arr = eps_arr * k_fB
    K_ss_arr = (1.0 - eps_arr) * k_s

    return {
        'zone_id': np.zeros((Nx, Ny), dtype=np.int32),  # continuous = single zone
        'eps_arr': eps_arr,
        'eps_f_arr': eps_arr / 2.0,
        'K_ffA_arr': K_ffA_arr,
        'K_ffB_arr': K_ffB_arr,
        'K_ss_arr': K_ss_arr,
        'h_vA_arr': h_vA_arr,
        'h_vB_arr': h_vB_arr,
        'r_h_arr': r_h_arr,
        'A_0_arr': A0_arr,
        'L_field': L_field,
        't_field': t_field,
        'axis': 'continuous',
    }


def compute_dP_continuous(L_field, t_field, eps_arr, D_h_arr,
                          u_A, u_B, rho_A, rho_B, mu_A, mu_B,
                          tpms_type, L_domain, H_domain, Nx, Ny,
                          T_inA=400.0, T_inB=300.0):
    """Compute pressure drop from continuous fields via per-cell integration.

    Returns (dP_A, dP_B) separately.
    """
    r_h_arr = D_h_arr / 2.0
    D_h_mm = D_h_arr * 1000.0
    rho_ref_A = air_density(T_inA, P_atm)
    rho_ref_B = air_density(T_inB, P_atm)

    Re_A = np.maximum(rho_ref_A * u_A * r_h_arr / mu_A, 10.0)
    Re_B = np.maximum(rho_ref_B * u_B * r_h_arr / mu_B, 10.0)

    f_A = _f_vec(tpms_type, Re_A, eps_arr, t_field, L_field, D_h_mm)
    f_B = _f_vec(tpms_type, Re_B, eps_arr, t_field, L_field, D_h_mm)

    dx = L_domain / Nx
    dy = H_domain / Ny

    # A flows in x: sum along x (axis=0), average over y
    dP_A = float(np.mean(np.sum(f_A * rho_A * u_A**2 / (2.0 * r_h_arr) * dx, axis=0)))

    # B flows in y: sum along y (axis=1), average over x
    dP_B = float(np.mean(np.sum(f_B * rho_B * u_B**2 / (2.0 * r_h_arr) * dy, axis=1)))

    return dP_A, dP_B


# ── Standalone test ──────────────────────────────────────────

if __name__ == '__main__':
    print("=== GeometryLUT Test ===")
    lut = get_geometry_lut('Diamond')
    print(f"LUT shape: {lut.eps_table.shape}")

    # Verify against direct computation
    for L, t in [(4.0, 0.3), (6.0, 0.4), (8.0, 0.5)]:
        g = compute_geometry('Diamond', L, t)
        L_a = np.array([[L]]); t_a = np.array([[t]])
        eps_lut, A0_lut = lut.query(L_a, t_a)
        print(f"  L={L}, t={t}: eps_direct={g['epsilon']:.4f} eps_LUT={eps_lut[0,0]:.4f} "
              f"A0_direct={g['A_0']:.1f} A0_LUT={A0_lut[0,0]:.1f}")

    print("\n=== Sigmoid Field Test ===")
    Nx, Ny = 30, 15
    x = np.array([6.0, 0.3] * 18)  # uniform
    x[0:2] = [4.0, 0.4]  # make one inlet zone different
    za = build_continuous_arrays(
        x, 6.0, 0.3, 0.2, 0.2,
        Nx, Ny, 0.1, 0.05,
        'Diamond', 15.0,
        10.0, 10.0, 400.0, 300.0,
        lut)
    print(f"  L_field range: [{za['L_field'].min():.2f}, {za['L_field'].max():.2f}]")
    print(f"  t_field range: [{za['t_field'].min():.3f}, {za['t_field'].max():.3f}]")
    print(f"  eps range: [{za['eps_arr'].min():.4f}, {za['eps_arr'].max():.4f}]")
    print(f"  h_vA range: [{za['h_vA_arr'].min():.0f}, {za['h_vA_arr'].max():.0f}]")
    print("=== All tests passed ===")
