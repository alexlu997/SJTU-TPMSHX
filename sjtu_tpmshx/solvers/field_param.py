"""
field_param.py — Continuous L(x,y), t(x,y) field parametrization for
optimization-friendly TPMS heat-exchanger design.

Replaces the discrete patch-zoning representation (18 patches × {L, t} = 36-D)
with a low-dimensional control-point representation (4×4 × {L, t} with optional
Y-mirror = 16-D) interpolated via bicubic B-spline tensor products. Gives:

  * smooth, manufacturable graded-TPMS fields by construction (no patch
    boundaries, no geometric jumps);
  * substantially smaller search space for the optimizer (16-D vs 36-D)
    while remaining expressive enough to describe the physically meaningful
    inlet-dense / outlet-coarse and lateral-graded patterns.

Per-cell TPMS properties (ε, K, h_v, …) are then assembled by querying
``tpms_calc.compute`` at quantized (L, t) values for caching, and packed into
the same 2-D-array dict that the SIMPLE solver consumes via
``ZoneConfig.build_grid_arrays``. This makes ContinuousFieldConfig a drop-in
substitute on the consumer side — only the producer (the optimizer's decision
encoding) changes.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple

from scipy.interpolate import RectBivariateSpline

from . import tpms_calc


# ─── Default decision-vector layout ─────────────────────────────────

DEFAULT_N_CTRL_X = 4
DEFAULT_N_CTRL_Y = 4
DEFAULT_SYMMETRIC_Y = True

DEFAULT_L_BOUNDS = (3.0, 10.0)   # mm
DEFAULT_T_BOUNDS = (0.2, 0.8)    # mm
DEFAULT_RATIO_BOUNDS = (0.05, 0.25)   # t / L


def decision_dim(n_ctrl_x: int = DEFAULT_N_CTRL_X,
                 n_ctrl_y: int = DEFAULT_N_CTRL_Y,
                 symmetric_y: bool = DEFAULT_SYMMETRIC_Y) -> int:
    """Return number of optimizer decision variables for the given layout.

    With symmetric_y, only the lower half of the y-axis is stored (rounded
    up for odd My); the upper half is mirrored at decode time.
    """
    My_eff = (n_ctrl_y + 1) // 2 if symmetric_y else n_ctrl_y
    return 2 * n_ctrl_x * My_eff   # ×2 for {L, t}


def decision_bounds(n_ctrl_x: int = DEFAULT_N_CTRL_X,
                    n_ctrl_y: int = DEFAULT_N_CTRL_Y,
                    symmetric_y: bool = DEFAULT_SYMMETRIC_Y,
                    L_bounds: Tuple[float, float] = DEFAULT_L_BOUNDS,
                    t_bounds: Tuple[float, float] = DEFAULT_T_BOUNDS
                    ) -> Tuple[np.ndarray, np.ndarray]:
    """Return (lb, ub) numpy arrays of length decision_dim(...)."""
    My_eff = (n_ctrl_y + 1) // 2 if symmetric_y else n_ctrl_y
    n_per_field = n_ctrl_x * My_eff
    lb = np.concatenate([np.full(n_per_field, L_bounds[0]),
                         np.full(n_per_field, t_bounds[0])])
    ub = np.concatenate([np.full(n_per_field, L_bounds[1]),
                         np.full(n_per_field, t_bounds[1])])
    return lb, ub


def decode_decision_vector(x: np.ndarray,
                           n_ctrl_x: int = DEFAULT_N_CTRL_X,
                           n_ctrl_y: int = DEFAULT_N_CTRL_Y,
                           symmetric_y: bool = DEFAULT_SYMMETRIC_Y
                           ) -> Tuple[np.ndarray, np.ndarray]:
    """Decode flat decision vector → full (Mx, My) control grids for L and t.

    Layout: x = [L_unique_flat, t_unique_flat]. Under symmetric_y, the unique
    half is the first ⌈My/2⌉ rows along y; the remaining rows are mirrored
    in place from the half (excluding the seam row when My is odd).
    """
    x = np.asarray(x, dtype=np.float64)
    My_eff = (n_ctrl_y + 1) // 2 if symmetric_y else n_ctrl_y
    n_per_field = n_ctrl_x * My_eff
    expected = 2 * n_per_field
    if x.size != expected:
        raise ValueError(
            f"decision vector length {x.size} != expected {expected} "
            f"for layout n_ctrl=({n_ctrl_x},{n_ctrl_y}) symmetric_y={symmetric_y}"
        )

    L_half = x[:n_per_field].reshape(n_ctrl_x, My_eff)
    t_half = x[n_per_field:].reshape(n_ctrl_x, My_eff)

    if symmetric_y:
        # Mirror along y: drop the seam (centre row) when My is odd
        seam_skip = n_ctrl_y % 2
        L_mirror = L_half[:, ::-1][:, seam_skip:]
        t_mirror = t_half[:, ::-1][:, seam_skip:]
        L_full = np.concatenate([L_half, L_mirror], axis=1)
        t_full = np.concatenate([t_half, t_mirror], axis=1)
    else:
        L_full = L_half
        t_full = t_half

    assert L_full.shape == (n_ctrl_x, n_ctrl_y), \
        f"decode: L_full shape {L_full.shape} != ({n_ctrl_x},{n_ctrl_y})"
    return L_full, t_full


def encode_decision_vector(L_ctrl: np.ndarray,
                           t_ctrl: np.ndarray,
                           symmetric_y: bool = DEFAULT_SYMMETRIC_Y) -> np.ndarray:
    """Inverse of decode_decision_vector — useful for warm-starts / tests.

    With symmetric_y, only the lower half is taken; the function does NOT
    enforce symmetry of the input (caller's responsibility). Use a symmetric
    seed if you want symmetric_y=True to round-trip exactly.
    """
    L_ctrl = np.asarray(L_ctrl, dtype=np.float64)
    t_ctrl = np.asarray(t_ctrl, dtype=np.float64)
    if symmetric_y:
        Mx, My = L_ctrl.shape
        My_eff = (My + 1) // 2
        return np.concatenate([L_ctrl[:, :My_eff].ravel(),
                               t_ctrl[:, :My_eff].ravel()])
    return np.concatenate([L_ctrl.ravel(), t_ctrl.ravel()])


# ─── ContinuousFieldConfig ──────────────────────────────────────────


@dataclass
class ContinuousFieldConfig:
    """Continuous spatial field of (L, t) parameters via B-spline interpolation
    over a coarse control grid. Drop-in producer for ZoneConfig.build_grid_arrays.

    Parameters
    ----------
    ctrl_x : (Mx,) array — control x positions [m] sorted, in [0, L_domain]
    ctrl_y : (My,) array — control y positions [m] sorted, in [0, H_domain]
    L_ctrl : (Mx, My) array — L value at each control point [mm]
    t_ctrl : (Mx, My) array — t value at each control point [mm]
    tpms_type : 'Diamond' | 'Gyroid'
    k_s : solid conductivity [W/(m K)]
    L_domain, H_domain : HX domain size [m]
    spline_order : 3 = bicubic (default), 1 = bilinear (degenerate fallback)
    L_bounds, t_bounds : physical clamps applied after spline evaluation
                         (defensive — splines can overshoot near boundaries)
    """

    ctrl_x: np.ndarray
    ctrl_y: np.ndarray
    L_ctrl: np.ndarray
    t_ctrl: np.ndarray
    tpms_type: str
    k_s: float
    L_domain: float
    H_domain: float
    spline_order: int = 3
    L_bounds: Tuple[float, float] = DEFAULT_L_BOUNDS
    t_bounds: Tuple[float, float] = DEFAULT_T_BOUNDS

    def __post_init__(self):
        self.ctrl_x = np.asarray(self.ctrl_x, dtype=np.float64)
        self.ctrl_y = np.asarray(self.ctrl_y, dtype=np.float64)
        self.L_ctrl = np.asarray(self.L_ctrl, dtype=np.float64)
        self.t_ctrl = np.asarray(self.t_ctrl, dtype=np.float64)

        Mx = self.ctrl_x.size
        My = self.ctrl_y.size
        if self.L_ctrl.shape != (Mx, My):
            raise ValueError(
                f"L_ctrl shape {self.L_ctrl.shape} != ({Mx},{My})")
        if self.t_ctrl.shape != (Mx, My):
            raise ValueError(
                f"t_ctrl shape {self.t_ctrl.shape} != ({Mx},{My})")
        if Mx < 2 or My < 2:
            raise ValueError(
                f"Need ≥2 control points per axis; got Mx={Mx}, My={My}")

        kx = min(self.spline_order, Mx - 1)
        ky = min(self.spline_order, My - 1)
        # RectBivariateSpline requires Mx > kx and My > ky
        self._L_spline = RectBivariateSpline(
            self.ctrl_x, self.ctrl_y, self.L_ctrl, kx=kx, ky=ky)
        self._t_spline = RectBivariateSpline(
            self.ctrl_x, self.ctrl_y, self.t_ctrl, kx=kx, ky=ky)

    # ─── Field evaluation ────────────────────────────────────────────

    def L_at(self, x: float, y: float) -> float:
        """Evaluate L(x,y) at one point [m] → mm. Clamped to L_bounds."""
        v = float(self._L_spline(x, y, grid=False))
        return float(np.clip(v, self.L_bounds[0], self.L_bounds[1]))

    def t_at(self, x: float, y: float) -> float:
        v = float(self._t_spline(x, y, grid=False))
        return float(np.clip(v, self.t_bounds[0], self.t_bounds[1]))

    def evaluate_grid(self, Nx: int, Ny: int,
                      dx_arr: Optional[np.ndarray] = None,
                      dy_arr: Optional[np.ndarray] = None
                      ) -> Tuple[np.ndarray, np.ndarray]:
        """Evaluate L, t at cell centers of (Nx, Ny) grid. Returns
        (L_field, t_field) each shape (Nx, Ny), values in mm, clamped.
        """
        if dx_arr is not None:
            dx = np.asarray(dx_arr, dtype=np.float64)
            x_cum = np.concatenate([[0.0], np.cumsum(dx)])
            xc = 0.5 * (x_cum[:-1] + x_cum[1:])
        else:
            xc = (np.arange(Nx) + 0.5) * (self.L_domain / Nx)
        if dy_arr is not None:
            dy = np.asarray(dy_arr, dtype=np.float64)
            y_cum = np.concatenate([[0.0], np.cumsum(dy)])
            yc = 0.5 * (y_cum[:-1] + y_cum[1:])
        else:
            yc = (np.arange(Ny) + 0.5) * (self.H_domain / Ny)

        L_field = self._L_spline(xc, yc, grid=True)   # shape (Nx, Ny)
        t_field = self._t_spline(xc, yc, grid=True)
        np.clip(L_field, self.L_bounds[0], self.L_bounds[1], out=L_field)
        np.clip(t_field, self.t_bounds[0], self.t_bounds[1], out=t_field)
        return L_field, t_field

    # ─── Per-cell property assembly ──────────────────────────────────

    def build_grid_arrays(self, Nx: int, Ny: int,
                          u_A: float, u_B: float,
                          T_inA: float, T_inB: float,
                          P_in: float = 101325.0,
                          dx_arr: Optional[np.ndarray] = None,
                          dy_arr: Optional[np.ndarray] = None,
                          quant_L: float = 0.05,
                          quant_t: float = 0.01) -> dict:
        """Build per-cell property arrays. Drop-in for ZoneConfig.build_grid_arrays.

        Strategy
        --------
        1. Evaluate (L, t) at every cell center via spline → (Nx, Ny) field.
        2. Quantize to (quant_L, quant_t) mm grid so we don't call
           ``tpms_calc.compute`` Nx·Ny times — typically a few hundred unique
           (L, t) combos at most.
        3. Pull props from the cache and pack into the standard dict shape.
        """
        L_field, t_field = self.evaluate_grid(Nx, Ny, dx_arr, dy_arr)
        L_q = np.round(L_field / quant_L) * quant_L
        t_q = np.round(t_field / quant_t) * quant_t

        eps_arr   = np.empty((Nx, Ny), dtype=np.float64)
        eps_f_arr = np.empty((Nx, Ny), dtype=np.float64)
        K_ffA_arr = np.empty((Nx, Ny), dtype=np.float64)
        K_ffB_arr = np.empty((Nx, Ny), dtype=np.float64)
        K_ss_arr  = np.empty((Nx, Ny), dtype=np.float64)
        h_vA_arr  = np.empty((Nx, Ny), dtype=np.float64)
        h_vB_arr  = np.empty((Nx, Ny), dtype=np.float64)
        r_h_arr   = np.empty((Nx, Ny), dtype=np.float64)
        A_0_arr   = np.empty((Nx, Ny), dtype=np.float64)

        cache: dict = {}
        for i in range(Nx):
            for j in range(Ny):
                key = (round(float(L_q[i, j]), 4),
                       round(float(t_q[i, j]), 4))
                if key not in cache:
                    pA = tpms_calc.compute(self.tpms_type, key[0], key[1],
                                           u_A, T_inA, P_in, self.k_s)
                    pB = tpms_calc.compute(self.tpms_type, key[0], key[1],
                                           u_B, T_inB, P_in, self.k_s)
                    cache[key] = (pA, pB)
                pA, pB = cache[key]
                eps_arr[i, j]   = pA['epsilon']
                eps_f_arr[i, j] = pA['epsilon_A']
                K_ffA_arr[i, j] = pA['K_ff']
                K_ffB_arr[i, j] = pB['K_ff']
                K_ss_arr[i, j]  = pA['K_ss']
                h_vA_arr[i, j]  = pA['H_sf'] * pA['A_0']
                h_vB_arr[i, j]  = pB['H_sf'] * pB['A_0']
                r_h_arr[i, j]   = pA['D_h'] / 2.0
                A_0_arr[i, j]   = pA['A_0']

        return {
            'zone_id':   np.zeros((Nx, Ny), dtype=np.int32),  # not used downstream
            'eps_arr':   eps_arr,
            'eps_f_arr': eps_f_arr,
            'K_ffA_arr': K_ffA_arr,
            'K_ffB_arr': K_ffB_arr,
            'K_ss_arr':  K_ss_arr,
            'h_vA_arr':  h_vA_arr,
            'h_vB_arr':  h_vB_arr,
            'r_h_arr':   r_h_arr,
            'A_0_arr':   A_0_arr,
            'axis': 'continuous',
            'L_field': L_field,
            't_field': t_field,
            'cache_size': len(cache),
        }

    # ─── Manufacturability checks ────────────────────────────────────

    def manufacturability_penalty(self,
                                  grad_threshold: float = 0.5,
                                  ratio_bounds: Tuple[float, float] = DEFAULT_RATIO_BOUNDS,
                                  weight_grad: float = 100.0,
                                  weight_ratio: float = 1000.0) -> float:
        """Soft penalty (≥ 0) for manufacturability hazards.

        Penalizes:
          * inter-control-point gradient |ΔL| > grad_threshold · L_avg
            (graded TPMS surface tearing risk per Yang 2018);
          * t/L ratio outside ratio_bounds (physically implausible aspect).

        Returns 0.0 when clean. Caller adds this to the dP objective so the
        optimizer learns to avoid hazards rather than the optimizer-side
        constraint machinery rejecting samples (which destabilizes BO).
        """
        pen = 0.0

        L = self.L_ctrl
        L_avg = float(L.mean())
        if L.shape[0] > 1:
            dLx = np.abs(np.diff(L, axis=0)).max()
        else:
            dLx = 0.0
        if L.shape[1] > 1:
            dLy = np.abs(np.diff(L, axis=1)).max()
        else:
            dLy = 0.0
        grad_max = max(dLx, dLy)
        if grad_max > grad_threshold * L_avg:
            pen += weight_grad * (grad_max - grad_threshold * L_avg)

        ratio = self.t_ctrl / np.maximum(self.L_ctrl, 1e-9)
        rmin, rmax = ratio_bounds
        if ratio.max() > rmax:
            pen += weight_ratio * (float(ratio.max()) - rmax)
        if ratio.min() < rmin:
            pen += weight_ratio * (rmin - float(ratio.min()))

        return float(pen)


# ─── Constructor for the optimizer ──────────────────────────────────


def from_decision_vector(x: np.ndarray,
                         tpms_type: str,
                         k_s: float,
                         L_domain: float,
                         H_domain: float,
                         n_ctrl_x: int = DEFAULT_N_CTRL_X,
                         n_ctrl_y: int = DEFAULT_N_CTRL_Y,
                         symmetric_y: bool = DEFAULT_SYMMETRIC_Y,
                         spline_order: int = 3,
                         L_bounds: Tuple[float, float] = DEFAULT_L_BOUNDS,
                         t_bounds: Tuple[float, float] = DEFAULT_T_BOUNDS
                         ) -> ContinuousFieldConfig:
    """Build a ContinuousFieldConfig from a flat optimizer decision vector.

    Control point positions are equispaced along each axis covering the full
    [0, L_domain] × [0, H_domain] domain.
    """
    L_ctrl, t_ctrl = decode_decision_vector(x, n_ctrl_x, n_ctrl_y, symmetric_y)
    ctrl_x = np.linspace(0.0, L_domain, n_ctrl_x)
    ctrl_y = np.linspace(0.0, H_domain, n_ctrl_y)
    return ContinuousFieldConfig(
        ctrl_x=ctrl_x, ctrl_y=ctrl_y,
        L_ctrl=L_ctrl, t_ctrl=t_ctrl,
        tpms_type=tpms_type, k_s=k_s,
        L_domain=L_domain, H_domain=H_domain,
        spline_order=spline_order,
        L_bounds=L_bounds, t_bounds=t_bounds,
    )


# ─── Convenience: uniform-field constructor ────────────────────────


def uniform_field(L_mm: float, t_mm: float,
                  tpms_type: str, k_s: float,
                  L_domain: float, H_domain: float,
                  n_ctrl_x: int = DEFAULT_N_CTRL_X,
                  n_ctrl_y: int = DEFAULT_N_CTRL_Y) -> ContinuousFieldConfig:
    """Build a uniform-field config (useful for sanity checks vs single-zone)."""
    L_ctrl = np.full((n_ctrl_x, n_ctrl_y), L_mm, dtype=np.float64)
    t_ctrl = np.full((n_ctrl_x, n_ctrl_y), t_mm, dtype=np.float64)
    ctrl_x = np.linspace(0.0, L_domain, n_ctrl_x)
    ctrl_y = np.linspace(0.0, H_domain, n_ctrl_y)
    return ContinuousFieldConfig(
        ctrl_x=ctrl_x, ctrl_y=ctrl_y,
        L_ctrl=L_ctrl, t_ctrl=t_ctrl,
        tpms_type=tpms_type, k_s=k_s,
        L_domain=L_domain, H_domain=H_domain,
    )


# ─── Standalone smoke test ──────────────────────────────────────────

if __name__ == '__main__':
    print("=== field_param.py smoke test ===\n")

    # Test 1: decode/encode round-trip (symmetric)
    n_ctrl_x = 4
    n_ctrl_y = 4
    sym = True
    L_seed = np.array([[5.0, 6.0, 6.0, 5.0],
                       [5.5, 6.5, 6.5, 5.5],
                       [6.0, 7.0, 7.0, 6.0],
                       [5.5, 6.5, 6.5, 5.5]], dtype=np.float64)
    t_seed = np.full((4, 4), 0.4)
    x = encode_decision_vector(L_seed, t_seed, symmetric_y=sym)
    print(f"  decision_dim = {decision_dim(n_ctrl_x, n_ctrl_y, sym)} "
          f"(actual x.size = {x.size})")
    assert x.size == decision_dim(n_ctrl_x, n_ctrl_y, sym)

    L_dec, t_dec = decode_decision_vector(x, n_ctrl_x, n_ctrl_y, sym)
    assert np.allclose(L_dec, L_seed), f"L round-trip failed:\n{L_dec}\nvs\n{L_seed}"
    assert np.allclose(t_dec, t_seed)
    print("  PASS round-trip encode/decode (symmetric)\n")

    # Test 2: uniform field returns uniform
    fc = uniform_field(6.0, 0.4, 'Diamond', 15.0, 0.1, 0.1)
    L_field, t_field = fc.evaluate_grid(20, 20)
    assert np.allclose(L_field, 6.0, atol=1e-9)
    assert np.allclose(t_field, 0.4, atol=1e-9)
    print(f"  uniform field eval: L_mean={L_field.mean():.4f}, "
          f"t_mean={t_field.mean():.4f}")
    print("  PASS uniform field\n")

    # Test 3: build_grid_arrays returns expected dict keys
    arrays = fc.build_grid_arrays(20, 20, u_A=5.0, u_B=3.0,
                                   T_inA=400.0, T_inB=300.0)
    expected_keys = {'eps_arr', 'eps_f_arr', 'K_ffA_arr', 'K_ffB_arr',
                     'K_ss_arr', 'h_vA_arr', 'h_vB_arr', 'r_h_arr',
                     'A_0_arr', 'L_field', 't_field', 'axis', 'cache_size',
                     'zone_id'}
    assert expected_keys.issubset(set(arrays.keys()))
    print(f"  arrays keys OK; cache_size = {arrays['cache_size']} "
          f"(uniform field → expect 1)")
    assert arrays['cache_size'] == 1
    print("  PASS build_grid_arrays\n")

    # Test 4: penalty zero on smooth config
    pen = fc.manufacturability_penalty()
    assert pen == 0.0
    print(f"  penalty(uniform) = {pen}  PASS\n")

    # Test 5: penalty fires on steep gradient
    L_steep = np.array([[3.0, 3.0, 3.0, 3.0],
                        [10.0, 10.0, 10.0, 10.0],
                        [3.0, 3.0, 3.0, 3.0],
                        [10.0, 10.0, 10.0, 10.0]], dtype=np.float64)
    fc_steep = ContinuousFieldConfig(
        ctrl_x=np.linspace(0, 0.1, 4),
        ctrl_y=np.linspace(0, 0.1, 4),
        L_ctrl=L_steep, t_ctrl=t_seed,
        tpms_type='Diamond', k_s=15.0,
        L_domain=0.1, H_domain=0.1,
    )
    pen_steep = fc_steep.manufacturability_penalty()
    print(f"  penalty(steep) = {pen_steep:.2f}")
    assert pen_steep > 0.0
    print("  PASS smoothness penalty\n")

    print("=== All smoke tests passed ===")
