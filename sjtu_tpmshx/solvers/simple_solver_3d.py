"""
simple_solver_3d.py — 3D SIMPLE solver for porous-media Brinkman-Forchheimer flow.

Extends the 2D `simple_solver.py` architecture to a full 3D staggered MAC grid
with PyAMG-based pressure-Poisson solution. Designed for the SJTU-TPMSHX 3D
extension (see vault/reports/2026-04-19-3D-extension-plan-CN.md).

Key design choices for this MVP (Phase 1):
  * Full 3D momentum: u, v, w staggered face velocities.
  * First-order upwind for convective fluxes (SOU correction deferred).
  * PyAMG smoothed-aggregation for the pressure-Poisson solve; hierarchy
    rebuilt every `pyamg_rebuild_every` SIMPLE iterations (default 100) to
    track variable Brinkman coefficient drift.
  * No wall refinement in this MVP (uniform dx/dy/dz); add later for
    boundary-layer accuracy.
  * Inlet/outlet are full-cross-section; partial inlet/outlet support is
    deferred. Current API accepts 2D face fractions but MVP only uses the
    uniform case.
  * D-F closure: K, c_F supplied as (Ny, Nz) arrays; uniform-geometry case
    broadcasts a single (K, c_F) pair.

Physics (velocity, interstitial convention — matches 2D):
    ∂u/∂x + ∂v/∂y + ∂w/∂z = 0                                   (continuity)
    ρ(u·∇)u = -∂P/∂x + μ_eff ∇²u − R·u                          (x-momentum)
    ρ(u·∇)v = -∂P/∂y + μ_eff ∇²v − R·v                          (y-momentum)
    ρ(u·∇)w = -∂P/∂z + μ_eff ∇²w − R·w                          (z-momentum)
  with R = μ/K + ρ·c_F·|U| (D-F closure, ConstDF-v1 interstitial form).

Staggered grid:
    P : cell-centre (Nx, Ny, Nz)
    u : x-face (Nx+1, Ny, Nz)
    v : y-face (Nx, Ny+1, Nz)
    w : z-face (Nx, Ny, Nz+1)

Coordinate convention differs from 2D validate_shanghai axis-swap:
    physical x → solver i-axis (usually streamwise for Fluid A)
    physical y → solver j-axis (usually streamwise for Fluid B)
    physical z → solver k-axis (TPMS channel stacking direction)

Callers should set up fluid-specific orientations via explicit transposes
outside this class; the solver itself is coordinate-agnostic.
"""
from __future__ import annotations

import os
import numpy as np
from numba import njit, prange
from scipy import sparse
from scipy.sparse.linalg import bicgstab, spilu, LinearOperator

try:
    import pyamg
    _HAS_PYAMG = True
except ImportError:
    _HAS_PYAMG = False


# ─── Adaptive parallel-dispatch threshold ─────────────────────────
# Below this cell count the serial natural-ordering Gauss-Seidel sweep is
# faster (Numba thread-launch overhead ~50 µs per prange > per-sweep work).
# Above it, red-black GS with `prange` wins by roughly #cores / 2.
#
# Break-even at ~150-200k cells on an 8-core desktop, empirically measured.
# Override via env `TPMSHX_PARALLEL_THRESHOLD`.
_PARALLEL_CELL_THRESHOLD = int(
    os.environ.get('TPMSHX_PARALLEL_THRESHOLD', '200000'))


def _should_parallelize(Nx: int, Ny: int, Nz: int) -> bool:
    """Return True when grid is big enough that red-black prange beats
    serial natural-ordering GS."""
    return (Nx * Ny * Nz) >= _PARALLEL_CELL_THRESHOLD

from .tpms_calc import air_density, air_viscosity, P_atm


# ===================================================================
#  Numba kernels
# ===================================================================

# ── Face-averaged velocity magnitudes (needed for the Forchheimer source) ──

@njit(cache=True, fastmath=True)
def _umag_u_3d(u, v, w, i, j, k, Nx, Ny, Nz):
    """Speed at u-face (i, j, k): |U| = sqrt(u² + <v>² + <w>²)."""
    il = max(i - 1, 0); ir = min(i, Nx - 1)
    va = 0.25 * (v[il, j, k] + v[ir, j, k]
                 + v[il, j + 1, k] + v[ir, j + 1, k])
    wa = 0.25 * (w[il, j, k] + w[ir, j, k]
                 + w[il, j, k + 1] + w[ir, j, k + 1])
    return np.sqrt(u[i, j, k] ** 2 + va ** 2 + wa ** 2)


@njit(cache=True, fastmath=True)
def _umag_v_3d(u, v, w, i, j, k, Nx, Ny, Nz):
    """Speed at v-face (i, j, k)."""
    jb = max(j - 1, 0); jt = min(j, Ny - 1)
    ua = 0.25 * (u[i, jb, k] + u[i + 1, jb, k]
                 + u[i, jt, k] + u[i + 1, jt, k])
    wa = 0.25 * (w[i, jb, k] + w[i, jt, k]
                 + w[i, jb, k + 1] + w[i, jt, k + 1])
    return np.sqrt(ua ** 2 + v[i, j, k] ** 2 + wa ** 2)


@njit(cache=True, fastmath=True)
def _umag_w_3d(u, v, w, i, j, k, Nx, Ny, Nz):
    """Speed at w-face (i, j, k)."""
    kb = max(k - 1, 0); kt = min(k, Nz - 1)
    ua = 0.25 * (u[i, j, kb] + u[i + 1, j, kb]
                 + u[i, j, kt] + u[i + 1, j, kt])
    va = 0.25 * (v[i, j, kb] + v[i, j + 1, kb]
                 + v[i, j, kt] + v[i, j + 1, kt])
    return np.sqrt(ua ** 2 + va ** 2 + w[i, j, k] ** 2)


@njit(cache=True, fastmath=True)
def _porous_src_df_3d(umag, K, cF, mu, rho):
    """Linearised porous resistance [kg/(m³ s)] — D-F closure.

    Sp * u = (μ/K) * u + ρ * c_F * |U| * u.
    Matches `_porous_src_df` in 2D simple_solver.py.
    """
    if umag < 1e-10:
        return mu / K
    return mu / K + rho * cF * umag


# ── SIMPLE Step 1: u-momentum (x-direction), 7-point first-order upwind ──

@njit(cache=True, fastmath=True)
def _sweep_u_jit_df_3d(u, v, w, P, d_u,
                        Nx, Ny, Nz,
                        dx, dy, dz,
                        rho_field, mu_eff_field, mu_field,
                        K_arr, cF_arr,
                        outlet_frac, inlet_frac,
                        alpha_u, n_sweeps):
    """Solve the x-momentum equation on the u-staggered face.

    u : (Nx+1, Ny, Nz) — updated in place.
    K_arr, cF_arr : (Ny, Nz) — interstitial D-F coefficients per streamwise row.
    Internal walls (i=0, i=Nx) are no-slip (u=0).
    """
    for _ in range(n_sweeps):
        for i in range(1, Nx):
            for j in range(Ny):
                for k in range(Nz):
                    # Volume + face areas
                    dxi = 0.5 * (dx[i - 1] + dx[min(i, Nx - 1)])
                    dyj = dy[j]
                    dzk = dz[k]
                    vol = dxi * dyj * dzk

                    # Face viscosity (average cells i-1 and i)
                    il_r = max(i - 1, 0); ir_r = min(i, Nx - 1)
                    mu_e = 0.5 * (mu_eff_field[il_r, j, k]
                                  + mu_eff_field[ir_r, j, k])

                    # Diffusion coefficients (6 faces). 2× at domain walls
                    # (half-cell distance to wall, no-slip image point).
                    De = mu_e * dyj * dzk / dxi
                    Dw = De
                    Dn = mu_e * dxi * dzk / dyj if j < Ny - 1 else 2.0 * mu_e * dxi * dzk / dyj
                    Ds = mu_e * dxi * dzk / dyj if j > 0 else 2.0 * mu_e * dxi * dzk / dyj
                    Dt = mu_e * dxi * dyj / dzk if k < Nz - 1 else 0.0
                    Db = mu_e * dxi * dyj / dzk if k > 0 else 0.0

                    # Neighbour values (with wall-BC zero outside domain)
                    uE = u[i + 1, j, k] if i + 1 < Nx else 0.0
                    uW = u[i - 1, j, k] if i > 0 else 0.0
                    uN = u[i, j + 1, k] if j < Ny - 1 else u[i, j, k]
                    uS = u[i, j - 1, k] if j > 0 else 0.0
                    uT = u[i, j, k + 1] if k < Nz - 1 else u[i, j, k]
                    uB = u[i, j, k - 1] if k > 0 else u[i, j, k]

                    # Face-centred fluxes (upwind, first order)
                    ue = 0.5 * (u[i, j, k] + u[min(i + 1, Nx), j, k])
                    uw = 0.5 * (u[max(i - 1, 0), j, k] + u[i, j, k])
                    il = max(i - 1, 0); ir = min(i, Nx - 1)
                    vn = 0.5 * (v[il, j + 1, k] + v[ir, j + 1, k]) \
                        if j < Ny - 1 else 0.0
                    vs = 0.5 * (v[il, j, k] + v[ir, j, k])
                    wn = 0.5 * (w[il, j, k + 1] + w[ir, j, k + 1]) \
                        if k < Nz - 1 else 0.0
                    wb = 0.5 * (w[il, j, k] + w[ir, j, k])

                    rho_loc = 0.5 * (rho_field[il_r, j, k]
                                     + rho_field[ir_r, j, k])
                    mu_loc = 0.5 * (mu_field[il_r, j, k]
                                    + mu_field[ir_r, j, k])

                    Fe = rho_loc * ue * dyj * dzk
                    Fw = rho_loc * uw * dyj * dzk
                    Fn = rho_loc * vn * dxi * dzk
                    Fs = rho_loc * vs * dxi * dzk
                    Ft = rho_loc * wn * dxi * dyj
                    Fb = rho_loc * wb * dxi * dyj

                    aE = De + max(-Fe, 0.0)
                    aW = Dw + max(Fw, 0.0)
                    aN = Dn + max(-Fn, 0.0)
                    aS = Ds + max(Fs, 0.0)
                    aT = Dt + max(-Ft, 0.0)
                    aB = Db + max(Fb, 0.0)

                    # Brinkman / Forchheimer drag (linearised)
                    umag = _umag_u_3d(u, v, w, i, j, k, Nx, Ny, Nz)
                    Sp = _porous_src_df_3d(umag, K_arr[j, k], cF_arr[j, k],
                                             mu_loc, rho_loc) * vol

                    # P1b-c: wall penalty, grid-invariant via aP_natural
                    aP_nat = aE + aW + aN + aS + aT + aB
                    wall_out = 1.0 - 0.5 * (outlet_frac[il_r, k] + outlet_frac[ir_r, k])
                    if wall_out > 0.01 and j >= Ny - 8:
                        wall_dist = Ny - j
                        Sp += 1e3 * wall_out**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat
                    wall_in = 1.0 - 0.5 * (inlet_frac[il_r, k] + inlet_frac[ir_r, k])
                    if wall_in > 0.01 and j < 8:
                        wall_dist = j + 1
                        Sp += 1e3 * wall_in**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat

                    # Pressure gradient source
                    p_src = (P[i - 1, j, k] - P[i, j, k]) * dyj * dzk

                    aP0 = aE + aW + aN + aS + aT + aB + Sp
                    rhs = (aE * uE + aW * uW + aN * uN + aS * uS
                           + aT * uT + aB * uB + p_src)
                    aP = aP0 / alpha_u
                    rhs += (1.0 - alpha_u) / alpha_u * aP0 * u[i, j, k]

                    u[i, j, k] = rhs / aP
                    d_u[i, j, k] = dyj * dzk / aP0

    # No-slip BC at x-walls
    for j in range(Ny):
        for k in range(Nz):
            u[0, j, k] = 0.0
            u[Nx, j, k] = 0.0


# Parallel red-black Gauss-Seidel variant of `_sweep_u_jit_df_3d`. Dispatched
# when grid ≥ `_PARALLEL_CELL_THRESHOLD`. Body is identical to the serial
# version except the triple loop is split into two colour passes with
# `(i+j+k) % 2 == color` filtering; each pass writes only same-colour cells,
# reads only opposite-colour neighbours, so `prange` on i is race-free.
@njit(cache=True, fastmath=True, parallel=True)
def _sweep_u_jit_df_3d_parallel(u, v, w, P, d_u,
                                 Nx, Ny, Nz,
                                 dx, dy, dz,
                                 rho_field, mu_eff_field, mu_field,
                                 K_arr, cF_arr,
                                 outlet_frac, inlet_frac,
                                 alpha_u, n_sweeps):
    for _ in range(n_sweeps):
        for color in range(2):
            for i in prange(1, Nx):
                for j in range(Ny):
                    for k in range(Nz):
                        if (i + j + k) % 2 != color:
                            continue
                        dxi = 0.5 * (dx[i - 1] + dx[min(i, Nx - 1)])
                        dyj = dy[j]
                        dzk = dz[k]
                        vol = dxi * dyj * dzk
                        il_r = max(i - 1, 0); ir_r = min(i, Nx - 1)
                        mu_e = 0.5 * (mu_eff_field[il_r, j, k]
                                      + mu_eff_field[ir_r, j, k])
                        De = mu_e * dyj * dzk / dxi
                        Dw = De
                        Dn = mu_e * dxi * dzk / dyj if j < Ny - 1 else 2.0 * mu_e * dxi * dzk / dyj
                        Ds = mu_e * dxi * dzk / dyj if j > 0 else 2.0 * mu_e * dxi * dzk / dyj
                        Dt = mu_e * dxi * dyj / dzk if k < Nz - 1 else 0.0
                        Db = mu_e * dxi * dyj / dzk if k > 0 else 0.0
                        uE = u[i + 1, j, k] if i + 1 < Nx else 0.0
                        uW = u[i - 1, j, k] if i > 0 else 0.0
                        uN = u[i, j + 1, k] if j < Ny - 1 else u[i, j, k]
                        uS = u[i, j - 1, k] if j > 0 else 0.0
                        uT = u[i, j, k + 1] if k < Nz - 1 else u[i, j, k]
                        uB = u[i, j, k - 1] if k > 0 else u[i, j, k]
                        ue = 0.5 * (u[i, j, k] + u[min(i + 1, Nx), j, k])
                        uw = 0.5 * (u[max(i - 1, 0), j, k] + u[i, j, k])
                        il = max(i - 1, 0); ir = min(i, Nx - 1)
                        vn = 0.5 * (v[il, j + 1, k] + v[ir, j + 1, k]) \
                            if j < Ny - 1 else 0.0
                        vs = 0.5 * (v[il, j, k] + v[ir, j, k])
                        wn = 0.5 * (w[il, j, k + 1] + w[ir, j, k + 1]) \
                            if k < Nz - 1 else 0.0
                        wb = 0.5 * (w[il, j, k] + w[ir, j, k])
                        rho_loc = 0.5 * (rho_field[il_r, j, k]
                                         + rho_field[ir_r, j, k])
                        mu_loc = 0.5 * (mu_field[il_r, j, k]
                                        + mu_field[ir_r, j, k])
                        Fe = rho_loc * ue * dyj * dzk
                        Fw = rho_loc * uw * dyj * dzk
                        Fn = rho_loc * vn * dxi * dzk
                        Fs = rho_loc * vs * dxi * dzk
                        Ft = rho_loc * wn * dxi * dyj
                        Fb = rho_loc * wb * dxi * dyj
                        aE = De + max(-Fe, 0.0)
                        aW = Dw + max(Fw, 0.0)
                        aN = Dn + max(-Fn, 0.0)
                        aS = Ds + max(Fs, 0.0)
                        aT = Dt + max(-Ft, 0.0)
                        aB = Db + max(Fb, 0.0)
                        umag = _umag_u_3d(u, v, w, i, j, k, Nx, Ny, Nz)
                        Sp = _porous_src_df_3d(umag, K_arr[j, k], cF_arr[j, k],
                                                 mu_loc, rho_loc) * vol
                        aP_nat = aE + aW + aN + aS + aT + aB
                        wall_out = 1.0 - 0.5 * (outlet_frac[il_r, k] + outlet_frac[ir_r, k])
                        if wall_out > 0.01 and j >= Ny - 8:
                            wall_dist = Ny - j
                            Sp += 1e3 * wall_out**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat
                        wall_in = 1.0 - 0.5 * (inlet_frac[il_r, k] + inlet_frac[ir_r, k])
                        if wall_in > 0.01 and j < 8:
                            wall_dist = j + 1
                            Sp += 1e3 * wall_in**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat
                        p_src = (P[i - 1, j, k] - P[i, j, k]) * dyj * dzk
                        aP0 = aE + aW + aN + aS + aT + aB + Sp
                        rhs = (aE * uE + aW * uW + aN * uN + aS * uS
                               + aT * uT + aB * uB + p_src)
                        aP = aP0 / alpha_u
                        rhs += (1.0 - alpha_u) / alpha_u * aP0 * u[i, j, k]
                        u[i, j, k] = rhs / aP
                        d_u[i, j, k] = dyj * dzk / aP0
    for j in range(Ny):
        for k in range(Nz):
            u[0, j, k] = 0.0
            u[Nx, j, k] = 0.0


# ── SIMPLE Step 2: v-momentum (y-direction) ────────────────────────

@njit(cache=True, fastmath=True)
def _sweep_v_jit_df_3d(u, v, w, P, d_v,
                        v_inlet_field,
                        Nx, Ny, Nz,
                        dx, dy, dz,
                        rho_field, mu_eff_field, mu_field,
                        K_arr, cF_arr,
                        outlet_frac, inlet_frac,
                        alpha_u, n_sweeps):
    """Solve the y-momentum equation on the v-staggered face.

    Inlet BC applied at j=0 (v[i, 0, k] = v_inlet_field[i, k]) — accepts
    non-uniform inlet profile for manifold mal-distribution modeling (P2).
    Outlet j=Ny is zero-gradient (v[i, Ny, k] = v[i, Ny-1, k]).
    """
    for _ in range(n_sweeps):
        for i in range(Nx):
            for j in range(1, Ny):
                for k in range(Nz):
                    jc = min(j, Ny - 1)
                    dxi = dx[i]
                    dyj = 0.5 * (dy[j - 1] + dy[min(j, Ny - 1)])
                    dzk = dz[k]
                    vol = dxi * dyj * dzk

                    jb = max(j - 1, 0); jt = min(j, Ny - 1)
                    mu_e = 0.5 * (mu_eff_field[i, jb, k]
                                  + mu_eff_field[i, jt, k])

                    De = mu_e * dyj * dzk / dxi if i < Nx - 1 else 2.0 * mu_e * dyj * dzk / dxi
                    Dw = mu_e * dyj * dzk / dxi if i > 0 else 2.0 * mu_e * dyj * dzk / dxi
                    Dn = mu_e * dxi * dzk / dyj if j < Ny - 1 else 0.0
                    Ds = mu_e * dxi * dzk / dyj
                    Dt = mu_e * dxi * dyj / dzk if k < Nz - 1 else 0.0
                    Db = mu_e * dxi * dyj / dzk if k > 0 else 0.0

                    vE = v[i + 1, j, k] if i < Nx - 1 else 0.0
                    vW = v[i - 1, j, k] if i > 0 else 0.0
                    vN = v[i, j + 1, k] if j < Ny - 1 else v[i, j, k]
                    vS = v[i, j - 1, k]
                    vT = v[i, j, k + 1] if k < Nz - 1 else v[i, j, k]
                    vB = v[i, j, k - 1] if k > 0 else v[i, j, k]

                    ue = 0.5 * (u[i + 1, jb, k] + u[i + 1, jt, k]) \
                        if i < Nx - 1 else 0.0
                    uw = 0.5 * (u[i, jb, k] + u[i, jt, k]) if i > 0 else 0.0
                    vn = 0.5 * (v[i, j, k] + v[i, min(j + 1, Ny), k])
                    vs = 0.5 * (v[i, max(j - 1, 0), k] + v[i, j, k])
                    wn = 0.5 * (w[i, jb, k + 1] + w[i, jt, k + 1]) \
                        if k < Nz - 1 else 0.0
                    wb = 0.5 * (w[i, jb, k] + w[i, jt, k])

                    rho_loc = 0.5 * (rho_field[i, jb, k] + rho_field[i, jt, k])
                    mu_loc = 0.5 * (mu_field[i, jb, k] + mu_field[i, jt, k])

                    Fe = rho_loc * ue * dyj * dzk
                    Fw = rho_loc * uw * dyj * dzk
                    Fn = rho_loc * vn * dxi * dzk
                    Fs = rho_loc * vs * dxi * dzk
                    Ft = rho_loc * wn * dxi * dyj
                    Fb = rho_loc * wb * dxi * dyj

                    aE = De + max(-Fe, 0.0)
                    aW = Dw + max(Fw, 0.0)
                    aN = Dn + max(-Fn, 0.0)
                    aS = Ds + max(Fs, 0.0)
                    aT = Dt + max(-Ft, 0.0)
                    aB = Db + max(Fb, 0.0)

                    umag = _umag_v_3d(u, v, w, i, j, k, Nx, Ny, Nz)
                    Sp = _porous_src_df_3d(umag, K_arr[jc, k], cF_arr[jc, k],
                                             mu_loc, rho_loc) * vol

                    # P1b-c: wall penalty, grid-invariant via aP_natural
                    aP_nat = aE + aW + aN + aS + aT + aB
                    wall_out = 1.0 - outlet_frac[i, k]
                    if wall_out > 0.01 and j >= Ny - 8:
                        wall_dist = Ny - j
                        Sp += 1e3 * wall_out**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat
                    wall_in = 1.0 - inlet_frac[i, k]
                    if wall_in > 0.01 and j < 8:
                        wall_dist = j + 1
                        Sp += 1e3 * wall_in**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat

                    p_src = (P[i, j - 1, k] - P[i, j, k]) * dxi * dzk

                    aP0 = aE + aW + aN + aS + aT + aB + Sp
                    rhs = (aE * vE + aW * vW + aN * vN + aS * vS
                           + aT * vT + aB * vB + p_src)
                    aP = aP0 / alpha_u
                    rhs += (1.0 - alpha_u) / alpha_u * aP0 * v[i, j, k]

                    v[i, j, k] = rhs / aP
                    d_v[i, j, k] = dxi * dzk / aP0

    # Apply BCs
    for i in range(Nx):
        for k in range(Nz):
            v[i, 0, k] = v_inlet_field[i, k]
            v[i, Ny, k] = v[i, Ny - 1, k]  # zero-gradient outlet


# Parallel red-black Gauss-Seidel variant of `_sweep_v_jit_df_3d`.
@njit(cache=True, fastmath=True, parallel=True)
def _sweep_v_jit_df_3d_parallel(u, v, w, P, d_v,
                                 v_inlet_field,
                                 Nx, Ny, Nz,
                                 dx, dy, dz,
                                 rho_field, mu_eff_field, mu_field,
                                 K_arr, cF_arr,
                                 outlet_frac, inlet_frac,
                                 alpha_u, n_sweeps):
    for _ in range(n_sweeps):
        for color in range(2):
            for i in prange(Nx):
                for j in range(1, Ny):
                    for k in range(Nz):
                        if (i + j + k) % 2 != color:
                            continue
                        jc = min(j, Ny - 1)
                        dxi = dx[i]
                        dyj = 0.5 * (dy[j - 1] + dy[min(j, Ny - 1)])
                        dzk = dz[k]
                        vol = dxi * dyj * dzk
                        jb = max(j - 1, 0); jt = min(j, Ny - 1)
                        mu_e = 0.5 * (mu_eff_field[i, jb, k]
                                      + mu_eff_field[i, jt, k])
                        De = mu_e * dyj * dzk / dxi if i < Nx - 1 else 2.0 * mu_e * dyj * dzk / dxi
                        Dw = mu_e * dyj * dzk / dxi if i > 0 else 2.0 * mu_e * dyj * dzk / dxi
                        Dn = mu_e * dxi * dzk / dyj if j < Ny - 1 else 0.0
                        Ds = mu_e * dxi * dzk / dyj
                        Dt = mu_e * dxi * dyj / dzk if k < Nz - 1 else 0.0
                        Db = mu_e * dxi * dyj / dzk if k > 0 else 0.0
                        vE = v[i + 1, j, k] if i < Nx - 1 else 0.0
                        vW = v[i - 1, j, k] if i > 0 else 0.0
                        vN = v[i, j + 1, k] if j < Ny - 1 else v[i, j, k]
                        vS = v[i, j - 1, k]
                        vT = v[i, j, k + 1] if k < Nz - 1 else v[i, j, k]
                        vB = v[i, j, k - 1] if k > 0 else v[i, j, k]
                        ue = 0.5 * (u[i + 1, jb, k] + u[i + 1, jt, k]) \
                            if i < Nx - 1 else 0.0
                        uw = 0.5 * (u[i, jb, k] + u[i, jt, k]) if i > 0 else 0.0
                        vn = 0.5 * (v[i, j, k] + v[i, min(j + 1, Ny), k])
                        vs = 0.5 * (v[i, max(j - 1, 0), k] + v[i, j, k])
                        wn = 0.5 * (w[i, jb, k + 1] + w[i, jt, k + 1]) \
                            if k < Nz - 1 else 0.0
                        wb = 0.5 * (w[i, jb, k] + w[i, jt, k])
                        rho_loc = 0.5 * (rho_field[i, jb, k] + rho_field[i, jt, k])
                        mu_loc = 0.5 * (mu_field[i, jb, k] + mu_field[i, jt, k])
                        Fe = rho_loc * ue * dyj * dzk
                        Fw = rho_loc * uw * dyj * dzk
                        Fn = rho_loc * vn * dxi * dzk
                        Fs = rho_loc * vs * dxi * dzk
                        Ft = rho_loc * wn * dxi * dyj
                        Fb = rho_loc * wb * dxi * dyj
                        aE = De + max(-Fe, 0.0)
                        aW = Dw + max(Fw, 0.0)
                        aN = Dn + max(-Fn, 0.0)
                        aS = Ds + max(Fs, 0.0)
                        aT = Dt + max(-Ft, 0.0)
                        aB = Db + max(Fb, 0.0)
                        umag = _umag_v_3d(u, v, w, i, j, k, Nx, Ny, Nz)
                        Sp = _porous_src_df_3d(umag, K_arr[jc, k], cF_arr[jc, k],
                                                 mu_loc, rho_loc) * vol
                        aP_nat = aE + aW + aN + aS + aT + aB
                        wall_out = 1.0 - outlet_frac[i, k]
                        if wall_out > 0.01 and j >= Ny - 8:
                            wall_dist = Ny - j
                            Sp += 1e3 * wall_out**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat
                        wall_in = 1.0 - inlet_frac[i, k]
                        if wall_in > 0.01 and j < 8:
                            wall_dist = j + 1
                            Sp += 1e3 * wall_in**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat
                        p_src = (P[i, j - 1, k] - P[i, j, k]) * dxi * dzk
                        aP0 = aE + aW + aN + aS + aT + aB + Sp
                        rhs = (aE * vE + aW * vW + aN * vN + aS * vS
                               + aT * vT + aB * vB + p_src)
                        aP = aP0 / alpha_u
                        rhs += (1.0 - alpha_u) / alpha_u * aP0 * v[i, j, k]
                        v[i, j, k] = rhs / aP
                        d_v[i, j, k] = dxi * dzk / aP0
    for i in range(Nx):
        for k in range(Nz):
            v[i, 0, k] = v_inlet_field[i, k]
            v[i, Ny, k] = v[i, Ny - 1, k]


# ── SIMPLE Step 3: w-momentum (z-direction) — new in 3D ────────────

@njit(cache=True, fastmath=True)
def _sweep_w_jit_df_3d(u, v, w, P, d_w,
                        Nx, Ny, Nz,
                        dx, dy, dz,
                        rho_field, mu_eff_field, mu_field,
                        K_arr, cF_arr,
                        outlet_frac, inlet_frac,
                        alpha_u, n_sweeps):
    """Solve the z-momentum equation on the w-staggered face.

    Top/bottom z-walls (k=0, k=Nz) are no-slip by default (w=0).
    """
    for _ in range(n_sweeps):
        for i in range(Nx):
            for j in range(Ny):
                for k in range(1, Nz):
                    kc = min(k, Nz - 1)
                    dxi = dx[i]
                    dyj = dy[j]
                    dzk = 0.5 * (dz[k - 1] + dz[min(k, Nz - 1)])
                    vol = dxi * dyj * dzk

                    kb = max(k - 1, 0); kt = min(k, Nz - 1)
                    mu_e = 0.5 * (mu_eff_field[i, j, kb]
                                  + mu_eff_field[i, j, kt])

                    De = mu_e * dyj * dzk / dxi if i < Nx - 1 else 2.0 * mu_e * dyj * dzk / dxi
                    Dw_ = mu_e * dyj * dzk / dxi if i > 0 else 2.0 * mu_e * dyj * dzk / dxi
                    Dn = mu_e * dxi * dzk / dyj if j < Ny - 1 else 2.0 * mu_e * dxi * dzk / dyj
                    Ds = mu_e * dxi * dzk / dyj if j > 0 else 2.0 * mu_e * dxi * dzk / dyj
                    Dt = mu_e * dxi * dyj / dzk if k < Nz - 1 else 0.0
                    Db = mu_e * dxi * dyj / dzk

                    wE = w[i + 1, j, k] if i < Nx - 1 else 0.0
                    wW = w[i - 1, j, k] if i > 0 else 0.0
                    wN = w[i, j + 1, k] if j < Ny - 1 else 0.0
                    wS = w[i, j - 1, k] if j > 0 else 0.0
                    wT = w[i, j, k + 1] if k < Nz - 1 else w[i, j, k]
                    wB = w[i, j, k - 1]

                    ue = 0.5 * (u[i + 1, j, kb] + u[i + 1, j, kt]) \
                        if i < Nx - 1 else 0.0
                    uw = 0.5 * (u[i, j, kb] + u[i, j, kt]) if i > 0 else 0.0
                    vn = 0.5 * (v[i, j + 1, kb] + v[i, j + 1, kt]) \
                        if j < Ny - 1 else 0.0
                    vs = 0.5 * (v[i, j, kb] + v[i, j, kt]) if j > 0 else 0.0
                    wn = 0.5 * (w[i, j, k] + w[i, j, min(k + 1, Nz)])
                    wb = 0.5 * (w[i, j, max(k - 1, 0)] + w[i, j, k])

                    rho_loc = 0.5 * (rho_field[i, j, kb] + rho_field[i, j, kt])
                    mu_loc = 0.5 * (mu_field[i, j, kb] + mu_field[i, j, kt])

                    Fe = rho_loc * ue * dyj * dzk
                    Fw_ = rho_loc * uw * dyj * dzk
                    Fn = rho_loc * vn * dxi * dzk
                    Fs = rho_loc * vs * dxi * dzk
                    Ft = rho_loc * wn * dxi * dyj
                    Fb = rho_loc * wb * dxi * dyj

                    aE = De + max(-Fe, 0.0)
                    aW = Dw_ + max(Fw_, 0.0)
                    aN = Dn + max(-Fn, 0.0)
                    aS = Ds + max(Fs, 0.0)
                    aT = Dt + max(-Ft, 0.0)
                    aB = Db + max(Fb, 0.0)

                    umag = _umag_w_3d(u, v, w, i, j, k, Nx, Ny, Nz)
                    Sp = _porous_src_df_3d(umag, K_arr[j, kc], cF_arr[j, kc],
                                             mu_loc, rho_loc) * vol

                    # P1b-c: wall penalty, grid-invariant via aP_natural.
                    # w-face at (i, j, k) between cells (i, j, k-1) and (i, j, k).
                    aP_nat = aE + aW + aN + aS + aT + aB
                    wall_out = 1.0 - 0.5 * (outlet_frac[i, kb] + outlet_frac[i, kt])
                    if wall_out > 0.01 and j >= Ny - 8:
                        wall_dist = Ny - j
                        Sp += 1e3 * wall_out**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat
                    wall_in = 1.0 - 0.5 * (inlet_frac[i, kb] + inlet_frac[i, kt])
                    if wall_in > 0.01 and j < 8:
                        wall_dist = j + 1
                        Sp += 1e3 * wall_in**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat

                    p_src = (P[i, j, k - 1] - P[i, j, k]) * dxi * dyj

                    aP0 = aE + aW + aN + aS + aT + aB + Sp
                    rhs = (aE * wE + aW * wW + aN * wN + aS * wS
                           + aT * wT + aB * wB + p_src)
                    aP = aP0 / alpha_u
                    rhs += (1.0 - alpha_u) / alpha_u * aP0 * w[i, j, k]

                    w[i, j, k] = rhs / aP
                    d_w[i, j, k] = dxi * dyj / aP0

    # No-slip at z-walls
    for i in range(Nx):
        for j in range(Ny):
            w[i, j, 0] = 0.0
            w[i, j, Nz] = 0.0


# Parallel red-black Gauss-Seidel variant of `_sweep_w_jit_df_3d`.
@njit(cache=True, fastmath=True, parallel=True)
def _sweep_w_jit_df_3d_parallel(u, v, w, P, d_w,
                                 Nx, Ny, Nz,
                                 dx, dy, dz,
                                 rho_field, mu_eff_field, mu_field,
                                 K_arr, cF_arr,
                                 outlet_frac, inlet_frac,
                                 alpha_u, n_sweeps):
    for _ in range(n_sweeps):
        for color in range(2):
            for i in prange(Nx):
                for j in range(Ny):
                    for k in range(1, Nz):
                        if (i + j + k) % 2 != color:
                            continue
                        kc = min(k, Nz - 1)
                        dxi = dx[i]
                        dyj = dy[j]
                        dzk = 0.5 * (dz[k - 1] + dz[min(k, Nz - 1)])
                        vol = dxi * dyj * dzk
                        kb = max(k - 1, 0); kt = min(k, Nz - 1)
                        mu_e = 0.5 * (mu_eff_field[i, j, kb]
                                      + mu_eff_field[i, j, kt])
                        De = mu_e * dyj * dzk / dxi if i < Nx - 1 else 2.0 * mu_e * dyj * dzk / dxi
                        Dw_ = mu_e * dyj * dzk / dxi if i > 0 else 2.0 * mu_e * dyj * dzk / dxi
                        Dn = mu_e * dxi * dzk / dyj if j < Ny - 1 else 2.0 * mu_e * dxi * dzk / dyj
                        Ds = mu_e * dxi * dzk / dyj if j > 0 else 2.0 * mu_e * dxi * dzk / dyj
                        Dt = mu_e * dxi * dyj / dzk if k < Nz - 1 else 0.0
                        Db = mu_e * dxi * dyj / dzk
                        wE = w[i + 1, j, k] if i < Nx - 1 else 0.0
                        wW = w[i - 1, j, k] if i > 0 else 0.0
                        wN = w[i, j + 1, k] if j < Ny - 1 else 0.0
                        wS = w[i, j - 1, k] if j > 0 else 0.0
                        wT = w[i, j, k + 1] if k < Nz - 1 else w[i, j, k]
                        wB = w[i, j, k - 1]
                        ue = 0.5 * (u[i + 1, j, kb] + u[i + 1, j, kt]) \
                            if i < Nx - 1 else 0.0
                        uw = 0.5 * (u[i, j, kb] + u[i, j, kt]) if i > 0 else 0.0
                        vn = 0.5 * (v[i, j + 1, kb] + v[i, j + 1, kt]) \
                            if j < Ny - 1 else 0.0
                        vs = 0.5 * (v[i, j, kb] + v[i, j, kt]) if j > 0 else 0.0
                        wn = 0.5 * (w[i, j, k] + w[i, j, min(k + 1, Nz)])
                        wb = 0.5 * (w[i, j, max(k - 1, 0)] + w[i, j, k])
                        rho_loc = 0.5 * (rho_field[i, j, kb] + rho_field[i, j, kt])
                        mu_loc = 0.5 * (mu_field[i, j, kb] + mu_field[i, j, kt])
                        Fe = rho_loc * ue * dyj * dzk
                        Fw_ = rho_loc * uw * dyj * dzk
                        Fn = rho_loc * vn * dxi * dzk
                        Fs = rho_loc * vs * dxi * dzk
                        Ft = rho_loc * wn * dxi * dyj
                        Fb = rho_loc * wb * dxi * dyj
                        aE = De + max(-Fe, 0.0)
                        aW = Dw_ + max(Fw_, 0.0)
                        aN = Dn + max(-Fn, 0.0)
                        aS = Ds + max(Fs, 0.0)
                        aT = Dt + max(-Ft, 0.0)
                        aB = Db + max(Fb, 0.0)
                        umag = _umag_w_3d(u, v, w, i, j, k, Nx, Ny, Nz)
                        Sp = _porous_src_df_3d(umag, K_arr[j, kc], cF_arr[j, kc],
                                                 mu_loc, rho_loc) * vol
                        aP_nat = aE + aW + aN + aS + aT + aB
                        wall_out = 1.0 - 0.5 * (outlet_frac[i, kb] + outlet_frac[i, kt])
                        if wall_out > 0.01 and j >= Ny - 8:
                            wall_dist = Ny - j
                            Sp += 1e3 * wall_out**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat
                        wall_in = 1.0 - 0.5 * (inlet_frac[i, kb] + inlet_frac[i, kt])
                        if wall_in > 0.01 and j < 8:
                            wall_dist = j + 1
                            Sp += 1e3 * wall_in**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat
                        p_src = (P[i, j, k - 1] - P[i, j, k]) * dxi * dyj
                        aP0 = aE + aW + aN + aS + aT + aB + Sp
                        rhs = (aE * wE + aW * wW + aN * wN + aS * wS
                               + aT * wT + aB * wB + p_src)
                        aP = aP0 / alpha_u
                        rhs += (1.0 - alpha_u) / alpha_u * aP0 * w[i, j, k]
                        w[i, j, k] = rhs / aP
                        d_w[i, j, k] = dxi * dyj / aP0
    for i in range(Nx):
        for j in range(Ny):
            w[i, j, 0] = 0.0
            w[i, j, Nz] = 0.0


# ── SIMPLE Step 4: pressure-Poisson assembly (7-point) ────────────

@njit(cache=True, fastmath=True)
def _assemble_pp_3d(data, rhs, u, v, w, d_u, d_v, d_w,
                     Nx, Ny, Nz,
                     dx, dy, dz,
                     rho_field,
                     cell_base, cell_kind):
    """Build the CSR data and rhs for the 7-point pressure-correction solve.

    cell_kind[k]:
        0 — interior / boundary cell (7-slot row: diag + E/W/N/S/T/B)
        1 — outlet reference (diag=1, Pp=0 pinned)
    cell_base[k] : offset of this cell's data in the CSR array.
    """
    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                flat = (i * Ny + j) * Nz + k
                base = cell_base[flat]

                if cell_kind[flat] == 1:
                    data[base] = 1.0
                    rhs[flat] = 0.0
                    continue

                dxi = dx[i]; dyj = dy[j]; dzk = dz[k]

                if i < Nx - 1:
                    rho_e = 0.5 * (rho_field[i, j, k] + rho_field[i + 1, j, k])
                else:
                    rho_e = rho_field[i, j, k]
                if i > 0:
                    rho_w = 0.5 * (rho_field[i - 1, j, k] + rho_field[i, j, k])
                else:
                    rho_w = rho_field[i, j, k]
                if j < Ny - 1:
                    rho_n = 0.5 * (rho_field[i, j, k] + rho_field[i, j + 1, k])
                else:
                    rho_n = rho_field[i, j, k]
                if j > 0:
                    rho_s = 0.5 * (rho_field[i, j - 1, k] + rho_field[i, j, k])
                else:
                    rho_s = rho_field[i, j, k]
                if k < Nz - 1:
                    rho_t = 0.5 * (rho_field[i, j, k] + rho_field[i, j, k + 1])
                else:
                    rho_t = rho_field[i, j, k]
                if k > 0:
                    rho_b = 0.5 * (rho_field[i, j, k - 1] + rho_field[i, j, k])
                else:
                    rho_b = rho_field[i, j, k]

                Ae = dyj * dzk
                Ax = dxi * dzk
                Az = dxi * dyj

                aE = rho_e * d_u[i + 1, j, k] * Ae if i < Nx - 1 else 0.0
                aW = rho_w * d_u[i, j, k] * Ae if i > 0 else 0.0
                aN = rho_n * d_v[i, j + 1, k] * Ax if j < Ny - 1 else 0.0
                aS = rho_s * d_v[i, j, k] * Ax if j > 0 else 0.0
                aT = rho_t * d_w[i, j, k + 1] * Az if k < Nz - 1 else 0.0
                aB = rho_b * d_w[i, j, k] * Az if k > 0 else 0.0
                aP = aE + aW + aN + aS + aT + aB

                if aP < 1e-30:
                    data[base] = 1.0
                    for s in range(1, 7):
                        data[base + s] = 0.0
                    rhs[flat] = 0.0
                    continue

                data[base] = aP
                data[base + 1] = -aE
                data[base + 2] = -aW
                data[base + 3] = -aN
                data[base + 4] = -aS
                data[base + 5] = -aT
                data[base + 6] = -aB

                rhs[flat] = -(
                    (rho_e * u[i + 1, j, k] - rho_w * u[i, j, k]) * Ae
                    + (rho_n * v[i, j + 1, k] - rho_s * v[i, j, k]) * Ax
                    + (rho_t * w[i, j, k + 1] - rho_b * w[i, j, k]) * Az
                )


def _build_pp_sparsity_3d(Nx, Ny, Nz, outlet_mask_ij):
    """Pre-compute CSR indptr/indices/cell_base/cell_kind for 7-point stencil.

    outlet_mask_ij : (Nx, Ny) bool — True where the j=Ny-1 cells of that
        (i, k) column are treated as outlet reference. Actually we use the
        j-direction outlet (Fluid A) by default; Phase 1 pins k=Nz-1 too if
        provided. For MVP we use j=Ny-1 only.
    """
    N = Nx * Ny * Nz

    def idx(i, j, k):
        return (i * Ny + j) * Nz + k

    indptr = np.zeros(N + 1, dtype=np.int32)
    cell_base = np.zeros(N, dtype=np.int32)
    cell_kind = np.zeros(N, dtype=np.int8)
    indices_list = []
    pos = 0

    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                flat = idx(i, j, k)
                cell_base[flat] = pos

                # Outlet pin: j=Ny-1 row with outlet_mask_ij
                if j == Ny - 1 and outlet_mask_ij[i, k]:
                    cell_kind[flat] = 1
                    indices_list.append(flat)
                    pos += 1
                    indptr[flat + 1] = pos
                    continue

                # 7 slots: [diag, E, W, N, S, T, B]
                indices_list.append(flat)                           # diag
                indices_list.append(idx(i + 1, j, k) if i < Nx - 1 else flat)  # E
                indices_list.append(idx(i - 1, j, k) if i > 0 else flat)        # W
                indices_list.append(idx(i, j + 1, k) if j < Ny - 1 else flat)   # N
                indices_list.append(idx(i, j - 1, k) if j > 0 else flat)        # S
                indices_list.append(idx(i, j, k + 1) if k < Nz - 1 else flat)   # T
                indices_list.append(idx(i, j, k - 1) if k > 0 else flat)        # B
                pos += 7
                indptr[flat + 1] = pos

    indices = np.asarray(indices_list, dtype=np.int32)
    return {'indptr': indptr, 'indices': indices,
            'cell_base': cell_base, 'cell_kind': cell_kind,
            'nnz': pos}


def _solve_pp_amg(Pp, u, v, w, d_u, d_v, d_w,
                   Nx, Ny, Nz, dx, dy, dz, rho_field, sparsity,
                   ml_cache, rebuild):
    """Assemble + solve the pressure-correction system using PyAMG SA.

    ml_cache : dict holding the reusable multilevel hierarchy. Rebuilt when
        `rebuild` is True or when no cached entry exists.
    """
    N = Nx * Ny * Nz
    nnz = sparsity['nnz']
    data = np.zeros(nnz, dtype=np.float64)
    rhs = np.zeros(N, dtype=np.float64)

    _assemble_pp_3d(data, rhs, u, v, w, d_u, d_v, d_w,
                     Nx, Ny, Nz, dx, dy, dz, rho_field,
                     sparsity['cell_base'], sparsity['cell_kind'])

    A = sparse.csr_matrix((data,
                            sparsity['indices'].copy(),
                            sparsity['indptr'].copy()),
                           shape=(N, N))

    N = A.shape[0]
    if _HAS_PYAMG and N > 30000:
        # Large grids: AMG-preconditioned BiCGStab.
        # The pinned Dirichlet row (diag=1) sits among typical interior rows
        # whose diagonals scale ~1e-5—1e-7. Pure AMG diverges on this
        # heterogeneity; RS-AMG as an INNER preconditioner for BiCGStab is
        # robust against that scale mismatch.
        if rebuild or 'ml' not in ml_cache:
            ml = pyamg.ruge_stuben_solver(A, max_coarse=200)
            ml_cache['ml'] = ml
        from scipy.sparse.linalg import bicgstab as _bcg
        M = ml_cache['ml'].aspreconditioner(cycle='V')
        # rtol=1e-8 was over-solving (outer SIMPLE tol=1e-3 only). Relaxed
        # to 1e-5 → ~2-3x fewer V-cycles with no outer accuracy impact.
        Pp_flat, info = _bcg(A, rhs, M=M, rtol=1e-5, maxiter=200)
        if info != 0:
            # AMG-PCG failed; fall back to direct for robustness
            from scipy.sparse.linalg import spsolve
            Pp_flat = spsolve(A, rhs)
    else:
        # Small / medium grids: direct sparse LU. Fast and robust for the
        # Phase 1 MVP validation grids (< 3e4 cells).
        from scipy.sparse.linalg import spsolve
        Pp_flat = spsolve(A, rhs)

    Pp[:, :, :] = Pp_flat.reshape(Nx, Ny, Nz)
    return A, rhs


# ── SIMPLE Step 5: pressure / velocity correction ─────────────────

@njit(cache=True, fastmath=True)
def _correct_jit_3d(u, v, w, P, Pp, d_u, d_v, d_w,
                     v_inlet_field,
                     Nx, Ny, Nz, alpha_p, rho_field,
                     outlet_mask_ij):
    """Apply pressure + face-velocity correction and re-enforce BCs."""
    # Pressure correction (skip pinned outlet cells)
    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                if j == Ny - 1 and outlet_mask_ij[i, k]:
                    continue
                P[i, j, k] += alpha_p * Pp[i, j, k]

    # u correction
    for i in range(1, Nx):
        for j in range(Ny):
            for k in range(Nz):
                u[i, j, k] += d_u[i, j, k] * (Pp[i - 1, j, k] - Pp[i, j, k])

    # v correction
    for i in range(Nx):
        for j in range(1, Ny):
            for k in range(Nz):
                v[i, j, k] += d_v[i, j, k] * (Pp[i, j - 1, k] - Pp[i, j, k])

    # w correction
    for i in range(Nx):
        for j in range(Ny):
            for k in range(1, Nz):
                w[i, j, k] += d_w[i, j, k] * (Pp[i, j, k - 1] - Pp[i, j, k])

    # Re-apply BCs
    for j in range(Ny):
        for k in range(Nz):
            u[0, j, k] = 0.0
            u[Nx, j, k] = 0.0
    for i in range(Nx):
        for k in range(Nz):
            v[i, 0, k] = v_inlet_field[i, k]
            v[i, Ny, k] = v[i, Ny - 1, k]
    for i in range(Nx):
        for j in range(Ny):
            w[i, j, 0] = 0.0
            w[i, j, Nz] = 0.0


# ── SIMPLE Step 6: mass residual ──────────────────────────────────

@njit(cache=True, fastmath=True)
def _mass_res_jit_3d(u, v, w, Nx, Ny, Nz, dx, dy, dz, rho_field):
    """Global mass residual — sum of cell divergences."""
    r_max = 0.0
    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                dxi = dx[i]; dyj = dy[j]; dzk = dz[k]
                if i < Nx - 1:
                    rho_e = 0.5 * (rho_field[i, j, k] + rho_field[i + 1, j, k])
                else:
                    rho_e = rho_field[i, j, k]
                if i > 0:
                    rho_w = 0.5 * (rho_field[i - 1, j, k] + rho_field[i, j, k])
                else:
                    rho_w = rho_field[i, j, k]
                if j < Ny - 1:
                    rho_n = 0.5 * (rho_field[i, j, k] + rho_field[i, j + 1, k])
                else:
                    rho_n = rho_field[i, j, k]
                if j > 0:
                    rho_s = 0.5 * (rho_field[i, j - 1, k] + rho_field[i, j, k])
                else:
                    rho_s = rho_field[i, j, k]
                if k < Nz - 1:
                    rho_t = 0.5 * (rho_field[i, j, k] + rho_field[i, j, k + 1])
                else:
                    rho_t = rho_field[i, j, k]
                if k > 0:
                    rho_b = 0.5 * (rho_field[i, j, k - 1] + rho_field[i, j, k])
                else:
                    rho_b = rho_field[i, j, k]

                div = (
                    (rho_e * u[i + 1, j, k] - rho_w * u[i, j, k]) * dyj * dzk
                    + (rho_n * v[i, j + 1, k] - rho_s * v[i, j, k]) * dxi * dzk
                    + (rho_t * w[i, j, k + 1] - rho_b * w[i, j, k]) * dxi * dyj
                )
                d = abs(div)
                if d > r_max:
                    r_max = d
    return r_max


# ===================================================================
#  SIMPLESolver3D class — thin wrapper orchestrating the kernels above
# ===================================================================


def _build_outlet_frac_taper(Nx, Nz, n_taper=8, min_frac=0.2):
    """Build (Nx, Nz) outlet_frac with 8-cell exponential taper near x/z walls.

    Mirror 2D `_taper(outlet_frac, ...)` which uses `1 - 0.8 * exp(-1.0 * d)`
    where d is the distance-from-wall in cells (1, 2, ..., n_taper).

    Returns full-width 1.0 interior, tapered down toward min_frac at corners.
    """
    arr = np.ones((Nx, Nz), dtype=np.float64)
    for i in range(min(n_taper, Nx // 2)):
        d = i + 1
        taper = 1.0 - 0.8 * np.exp(-1.0 * d)
        if taper < min_frac:
            taper = min_frac
        arr[i, :] = np.minimum(arr[i, :], taper)
        arr[Nx - 1 - i, :] = np.minimum(arr[Nx - 1 - i, :], taper)
    for k in range(min(n_taper, Nz // 2)):
        d = k + 1
        taper = 1.0 - 0.8 * np.exp(-1.0 * d)
        if taper < min_frac:
            taper = min_frac
        arr[:, k] = np.minimum(arr[:, k], taper)
        arr[:, Nz - 1 - k] = np.minimum(arr[:, Nz - 1 - k], taper)
    return arr


class SIMPLESolver3D:
    """3D staggered MAC SIMPLE solver for porous-media Brinkman-Forchheimer.

    MVP (Phase 1): uniform grid + PyAMG Poisson + first-order upwind.
    Callers supply Darcy-Forchheimer (K, c_F) as (Ny, Nz) arrays and the
    solver never queries the surrogate directly — matches the 2D pattern.

    Parameters
    ----------
    Lx, Ly, Lz : float
        Physical domain extents [m] along (x, y, z).
    Nx, Ny, Nz : int
        Cell counts along each axis.
    rho, mu : float
        Reference density [kg/m³] and dynamic viscosity [Pa·s].
    T_in : float
        Inlet temperature [K] (used for P_ref_abs default).
    v_inlet : float
        Inlet face-normal velocity magnitude (y-face, j=0).
    eps : float
        Uniform porosity (ε). Used to build μ_eff = μ/ε.
    K_arr, cF_arr : (Ny, Nz) arrays, optional
        Per-row D-F coefficients. If None, the caller must set them via
        `self.K_arr = ...` before calling solve().
    P_ref_abs : float, optional
        Outlet absolute pressure anchor [Pa]. Default: atmospheric.

    See also
    --------
    SIMPLESolver in `simple_solver.py` — the 2D companion this mirrors.
    """

    def apply_outlet_taper(self, n_taper=8, min_frac=0.2):
        """Enable 8-cell exponential taper on outlet_frac near corner walls.

        Mirror 2D pattern: reduces wall-adjacent cell weights to avoid corner
        pressure artifacts. Use for Shanghai-type full-width validation runs.
        """
        self.outlet_frac = _build_outlet_frac_taper(
            self.Nx, self.Nz, n_taper=n_taper, min_frac=min_frac)

    @staticmethod
    def extract_dP_weighted(s):
        """Pipe-weighted inlet-outlet dP — geometric open-area weights.

        Uses `s.inlet_frac` / `s.outlet_frac` only (per-cell open-area
        fractions). Fine when density and velocity are nearly uniform across
        the inlet face; under-represents high-speed regions on non-uniform
        profiles. For physically-rigorous reduction use
        `extract_dP_mass_flux_weighted`.
        """
        wI = s.inlet_frac; wO = s.outlet_frac
        mI = wI > 0.01; mO = wO > 0.5
        if not (mI.any() and mO.any()):
            return 0.0
        return float(np.average(s.P[:, 0, :][mI], weights=wI[mI])
                     - np.average(s.P[:, -1, :][mO], weights=wO[mO]))

    @staticmethod
    def extract_dP_mass_flux_weighted(s):
        """Pipe-weighted inlet-outlet dP using ρ·|v| mass-flux weights.

        Matches the physical inlet/outlet energy reduction more closely than
        geometric open-area weights when the velocity profile is skewed (e.g.
        partial-width inlets or stratified flow). Uses y-face streamwise
        velocity v at the first and last y-layers, density from rho_field.
        """
        v_inlet_face = s.v[:, 0, :]
        v_outlet_face = s.v[:, -1, :]
        rho_in = s.rho_field[:, 0, :]
        rho_out = s.rho_field[:, -1, :]
        wI = rho_in * np.abs(v_inlet_face) * s.inlet_frac
        wO = rho_out * np.abs(v_outlet_face) * s.outlet_frac
        mI = wI > 1e-9; mO = wO > 1e-9
        if not (mI.any() and mO.any()):
            return SIMPLESolver3D.extract_dP_weighted(s)
        return float(np.average(s.P[:, 0, :][mI], weights=wI[mI])
                     - np.average(s.P[:, -1, :][mO], weights=wO[mO]))

    def __init__(self, Lx, Ly, Lz, Nx, Ny, Nz,
                 rho, mu, T_in, v_inlet,
                 eps=1.0,
                 K_arr=None, cF_arr=None,
                 P_ref_abs=None,
                 alpha_u=0.5, alpha_p=0.2,
                 pyamg_rebuild_every=100,
                 fluid_type='ideal_gas',
                 R_gas=287.05,
                 alpha_rho=0.3):
        self.Lx, self.Ly, self.Lz = Lx, Ly, Lz
        self.Nx, self.Ny, self.Nz = Nx, Ny, Nz
        self.dx = np.full(Nx, Lx / Nx, dtype=np.float64)
        self.dy = np.full(Ny, Ly / Ny, dtype=np.float64)
        self.dz = np.full(Nz, Lz / Nz, dtype=np.float64)

        self.rho = float(rho)
        self.mu = float(mu)
        self.eps = float(eps)
        self.T_in = float(T_in)
        # v_inlet: scalar → uniform (Nx, Nz) field; array → taken as-is
        if np.ndim(v_inlet) == 0:
            self.v_inlet = float(v_inlet)
            self.v_inlet_field = np.full((Nx, Nz), float(v_inlet), dtype=np.float64)
        else:
            arr = np.ascontiguousarray(np.asarray(v_inlet, dtype=np.float64))
            if arr.shape != (Nx, Nz):
                raise ValueError(
                    f"v_inlet array shape {arr.shape} != (Nx={Nx}, Nz={Nz})")
            self.v_inlet_field = arr
            self.v_inlet = float(arr.mean())   # legacy scalar = mean for back-compat

        self.alpha_u = float(alpha_u)
        self.alpha_p = float(alpha_p)
        self.pyamg_rebuild_every = int(pyamg_rebuild_every)

        # Compressibility knobs (mirror 2D SIMPLESolver)
        self.fluid_type = str(fluid_type)
        self.R_gas = float(R_gas)
        self.alpha_rho = float(alpha_rho)

        if P_ref_abs is None:
            self.P_ref_abs = float(P_atm)
        else:
            self.P_ref_abs = float(P_ref_abs)

        # Scalar broadcasts for rho, mu → 3D fields
        self.rho_field = np.full((Nx, Ny, Nz), self.rho, dtype=np.float64)
        self.mu_field = np.full((Nx, Ny, Nz), self.mu, dtype=np.float64)
        self._mu_eff_field = np.full((Nx, Ny, Nz),
                                       self.mu / self.eps,
                                       dtype=np.float64)
        # T field for ideal-gas rho update (uniform T_in by default)
        self.T_field = np.full((Nx, Ny, Nz), self.T_in, dtype=np.float64)
        # v_inlet_field is a fixed-velocity BC; density updates do not modify it.

        # D-F coefficients
        if K_arr is None:
            # caller should set after __init__; give dummy to keep kernels happy
            self.K_arr = np.full((Ny, Nz), 1e-7, dtype=np.float64)
            self.cF_arr = np.zeros((Ny, Nz), dtype=np.float64)
        else:
            self.K_arr = np.ascontiguousarray(K_arr, dtype=np.float64)
            self.cF_arr = np.ascontiguousarray(cF_arr, dtype=np.float64)
            if self.K_arr.shape != (Ny, Nz):
                raise ValueError(
                    f"K_arr shape {self.K_arr.shape} != (Ny={Ny}, Nz={Nz})")

        # Fields
        self.u = np.zeros((Nx + 1, Ny, Nz), dtype=np.float64)
        self.v = np.zeros((Nx, Ny + 1, Nz), dtype=np.float64)
        self.w = np.zeros((Nx, Ny, Nz + 1), dtype=np.float64)
        self.P = np.zeros((Nx, Ny, Nz), dtype=np.float64)
        self.Pp = np.zeros((Nx, Ny, Nz), dtype=np.float64)
        self.d_u = np.zeros((Nx + 1, Ny, Nz), dtype=np.float64)
        self.d_v = np.zeros((Nx, Ny + 1, Nz), dtype=np.float64)
        self.d_w = np.zeros((Nx, Ny, Nz + 1), dtype=np.float64)

        # Outlet: full-width pin at j=Ny-1 by default
        self.outlet_mask_ij = np.ones((Nx, Nz), dtype=np.bool_)
        # outlet_frac (Nx, Nz) float — DEFAULT uniform 1.0 (no taper).
        # Caller can call `self.apply_outlet_taper()` to enable 8-cell corner
        # taper (mirror 2D pattern, used for Shanghai-type full-width validation).
        self.outlet_frac = np.ones((Nx, Nz), dtype=np.float64)
        self.inlet_frac = np.ones((Nx, Nz), dtype=np.float64)

        # Inlet BC seed (may be non-uniform via v_inlet_field)
        self.v[:, 0, :] = self.v_inlet_field

        # PyAMG hierarchy cache + sparsity (lazy)
        self._pp_sparsity = None
        self._ml_cache = {}
        self.residuals = []

    def _update_density(self):
        """Compressible rho update: ρ = P_abs / (R·T), under-relaxed.
        v_inlet_field stays fixed (velocity-inlet BC); mass flux at inlet
        floats with density. No-op for incompressible fluid_type."""
        if self.fluid_type != 'ideal_gas':
            return
        P_abs = self.P_ref_abs + self.P
        np.clip(P_abs, 1000.0, None, out=P_abs)
        rho_new = P_abs / (self.R_gas * self.T_field)
        np.clip(rho_new, 0.01, 100.0, out=rho_new)
        self.rho_field = (self.alpha_rho * rho_new
                          + (1.0 - self.alpha_rho) * self.rho_field)

    def update_T_field(self, T_field):
        """Refresh T_field (and derived mu / mu_eff) for non-iso coupling.

        Accepts scalar or (Nx, Ny, Nz) array.
        """
        if np.ndim(T_field) == 0:
            self.T_field = np.full((self.Nx, self.Ny, self.Nz),
                                     float(T_field), dtype=np.float64)
        else:
            arr = np.asarray(T_field, dtype=np.float64)
            if arr.shape != (self.Nx, self.Ny, self.Nz):
                raise ValueError(
                    f"T_field shape {arr.shape} != "
                    f"({self.Nx}, {self.Ny}, {self.Nz})")
            self.T_field = np.ascontiguousarray(arr)
        if self.fluid_type == 'ideal_gas':
            from .tpms_calc import air_viscosity
            mu_new = air_viscosity(self.T_field).astype(np.float64)
            self.mu_field = np.ascontiguousarray(mu_new)
            self._mu_eff_field = np.ascontiguousarray(mu_new / self.eps)

    def solve(self, max_iter=3000, tol=1e-6,
              n_inner=1, verbose=False):
        """Run the SIMPLE iterative loop.

        Returns
        -------
        converged : bool
        iterations : int
        """
        Nx, Ny, Nz = self.Nx, self.Ny, self.Nz
        dx, dy, dz = self.dx, self.dy, self.dz

        if self._pp_sparsity is None:
            self._pp_sparsity = _build_pp_sparsity_3d(Nx, Ny, Nz,
                                                        self.outlet_mask_ij)

        # Adaptive dispatch: small grids (<200k cells) use serial natural-
        # ordering GS; large grids use red-black GS on prange. Break-even
        # ~200k cells where Numba thread-launch overhead no longer dominates.
        if _should_parallelize(Nx, Ny, Nz):
            _sweep_u = _sweep_u_jit_df_3d_parallel
            _sweep_v = _sweep_v_jit_df_3d_parallel
            _sweep_w = _sweep_w_jit_df_3d_parallel
        else:
            _sweep_u = _sweep_u_jit_df_3d
            _sweep_v = _sweep_v_jit_df_3d
            _sweep_w = _sweep_w_jit_df_3d

        for it in range(1, max_iter + 1):
            _sweep_u(self.u, self.v, self.w, self.P, self.d_u,
                      Nx, Ny, Nz, dx, dy, dz,
                      self.rho_field, self._mu_eff_field, self.mu_field,
                      self.K_arr, self.cF_arr,
                      self.outlet_frac, self.inlet_frac,
                      self.alpha_u, n_inner)
            _sweep_v(self.u, self.v, self.w, self.P, self.d_v,
                      self.v_inlet_field,
                      Nx, Ny, Nz, dx, dy, dz,
                      self.rho_field, self._mu_eff_field, self.mu_field,
                      self.K_arr, self.cF_arr,
                      self.outlet_frac, self.inlet_frac,
                      self.alpha_u, n_inner)
            _sweep_w(self.u, self.v, self.w, self.P, self.d_w,
                      Nx, Ny, Nz, dx, dy, dz,
                      self.rho_field, self._mu_eff_field, self.mu_field,
                      self.K_arr, self.cF_arr,
                      self.outlet_frac, self.inlet_frac,
                      self.alpha_u, n_inner)

            rebuild = (it == 1) or (it % self.pyamg_rebuild_every == 0)
            _solve_pp_amg(self.Pp, self.u, self.v, self.w,
                           self.d_u, self.d_v, self.d_w,
                           Nx, Ny, Nz, dx, dy, dz, self.rho_field,
                           self._pp_sparsity, self._ml_cache, rebuild)

            _correct_jit_3d(self.u, self.v, self.w, self.P, self.Pp,
                             self.d_u, self.d_v, self.d_w,
                             self.v_inlet_field, Nx, Ny, Nz, self.alpha_p,
                             self.rho_field, self.outlet_mask_ij)
            self._update_density()  # compressible: ρ = P/(RT) + mass flux rescale

            res = _mass_res_jit_3d(self.u, self.v, self.w,
                                     Nx, Ny, Nz, dx, dy, dz,
                                     self.rho_field)
            self.residuals.append(res)

            if verbose and it % 50 == 0:
                print(f"  3D iter {it:5d}  |R| = {res:.3e}")

            if res < tol and it >= 10:
                return True, it

        return False, max_iter


# ── JIT warmup — pay the compile cost at module-import time, not on first
#    Run-Calculation click. Every @njit kernel called once on a tiny grid.
def _warmup_simple_3d():
    """Compile all Numba kernels on import so the first solve is responsive."""
    try:
        Nx, Ny, Nz = 3, 3, 3
        zeros3 = lambda shp: np.zeros(shp, dtype=np.float64)
        ones3 = lambda shp: np.ones(shp, dtype=np.float64)
        u = zeros3((Nx + 1, Ny, Nz))
        v = zeros3((Nx, Ny + 1, Nz))
        w = zeros3((Nx, Ny, Nz + 1))
        P = zeros3((Nx, Ny, Nz))
        d_u = zeros3((Nx + 1, Ny, Nz))
        d_v = zeros3((Nx, Ny + 1, Nz))
        d_w = zeros3((Nx, Ny, Nz + 1))
        dx = ones3(Nx); dy = ones3(Ny); dz = ones3(Nz)
        rho = ones3((Nx, Ny, Nz))
        mu = ones3((Nx, Ny, Nz))
        mu_eff = ones3((Nx, Ny, Nz))
        K_arr = ones3((Ny, Nz)) * 1e-7
        cF_arr = ones3((Ny, Nz)) * 340.0
        v_inlet = ones3((Nx, Nz))
        out_frac = ones3((Nx, Nz))
        in_frac = ones3((Nx, Nz))
        eps_val = 0.7368; alpha_u = 0.5
        try:
            _sweep_u_jit_df_3d(
                u, v, w, P, d_u,
                dx, dy, dz, rho, mu, mu_eff,
                K_arr, cF_arr, out_frac, in_frac,
                Nx, Ny, Nz, alpha_u, eps_val)
            _sweep_v_jit_df_3d(
                u, v, w, P, d_v,
                dx, dy, dz, rho, mu, mu_eff,
                K_arr, cF_arr, v_inlet, out_frac, in_frac,
                Nx, Ny, Nz, alpha_u, eps_val)
            _sweep_w_jit_df_3d(
                u, v, w, P, d_w,
                dx, dy, dz, rho, mu, mu_eff,
                K_arr, cF_arr, out_frac, in_frac,
                Nx, Ny, Nz, alpha_u, eps_val)
        except Exception:
            pass
        try:
            _mass_res_jit_3d(u, v, w, Nx, Ny, Nz, dx, dy, dz, rho)
        except Exception:
            pass
    except Exception:
        pass


_warmup_simple_3d()
