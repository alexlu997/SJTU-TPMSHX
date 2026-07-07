"""3D SIMPLE numba kernels, moved verbatim from simple_solver_3d.py
(openspec split-solver-kernels, 2026-07-03); bit-identical."""
import numpy as np
from numba import njit, prange

from .simple_solver import _WALL_PENALTY_BASE, _WALL_PENALTY_EFOLD
from ._kernels_2d import minmod


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


# ── SOU deferred correction, shared axis kernel (R4, opt-in) ───────
# openspec solver-efficiency-r1-r4. Minmod second-order-upwind deferred
# correction in the 2D N2 telescoping convention (lo-face limiter × Flo,
# hi-face limiter × Fhi — the SAME face fluxes the first-order a_nb use).
# One kernel serves all 9 (component × axis) combinations; the call sites
# only gather the 5-point stencil (clamped indices) and the boundary flags
# that mirror simple_solver.py's _sou_corr_* index conditions. Enabled per
# solve via `use_sou_momentum` (default False → term is exactly 0.0).

@njit(cache=True, fastmath=True, inline='always')
def _sou_axis(p_mm, p_m, p_c, p_p, p_pp,
              lo_pos, hi_pos, hi_neg, lo_neg,
              Flo, Fhi, adv):
    """SOU correction along ONE axis. p_c = this face's value; p_m/p_p the
    axis neighbours (lo/hi side); p_mm/p_pp the second neighbours. Values at
    clamped indices are ignored when the matching flag is False. Flo/Fhi =
    lo/hi-face convective fluxes of this CV; adv selects the upwind branch."""
    if adv >= 0.0:
        lo = minmod(p_m - p_mm, p_c - p_m) if lo_pos else 0.0
        hi = minmod(p_c - p_m, p_p - p_c) if hi_pos else 0.0
        return 0.5 * (Flo * lo - Fhi * hi)
    hi = minmod(p_p - p_pp, p_c - p_p) if hi_neg else 0.0
    lo = minmod(p_c - p_p, p_m - p_c) if lo_neg else 0.0
    return 0.5 * (Fhi * hi - Flo * lo)


# ── SIMPLE Step 1: u-momentum (x-direction), 7-point first-order upwind ──

@njit(cache=True, fastmath=True, inline='always')
def _u_cell_df_3d(u, v, w, P, d_u, i, j, k,
                  Nx, Ny, Nz, dx, dy, dz,
                  rho_field, mu_eff_field, mu_field,
                  K_arr, cF_arr, outlet_frac, inlet_frac, alpha_u, use_sou):
    """One Gauss-Seidel update of the u-face (i, j, k) — shared cell body
    for the serial and parallel sweeps (B6 dedup; previously duplicated
    verbatim). ``inline='always'`` so Numba fuses it into each loop."""
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
    # N4 (2026-07-07): interior conductances use the ACTUAL neighbour-node
    # distance, not the CV width — u-nodes sit on x-interfaces (E neighbour
    # at dx[i], W at dx[i-1]); cross-stream neighbours at 0.5*(dy[j]+dy[j±1])
    # / 0.5*(dz[k]+dz[k±1]). Uniform grids reduce bit-identically.
    De = mu_e * dyj * dzk / dx[ir_r]
    Dw = mu_e * dyj * dzk / dx[il_r]
    Dn = (mu_e * dxi * dzk / (0.5 * (dy[j] + dy[j + 1]))
          if j < Ny - 1 else 2.0 * mu_e * dxi * dzk / dyj)
    Ds = (mu_e * dxi * dzk / (0.5 * (dy[j] + dy[j - 1]))
          if j > 0 else 2.0 * mu_e * dxi * dzk / dyj)
    Dt = (mu_e * dxi * dyj / (0.5 * (dz[k] + dz[k + 1]))
          if k < Nz - 1 else 0.0)
    Db = (mu_e * dxi * dyj / (0.5 * (dz[k] + dz[k - 1]))
          if k > 0 else 0.0)

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
        Sp += _WALL_PENALTY_BASE * wall_out**4 * np.exp(
            -_WALL_PENALTY_EFOLD * (wall_dist - 1)) * aP_nat
    wall_in = 1.0 - 0.5 * (inlet_frac[il_r, k] + inlet_frac[ir_r, k])
    if wall_in > 0.01 and j < 8:
        wall_dist = j + 1
        Sp += _WALL_PENALTY_BASE * wall_in**4 * np.exp(
            -_WALL_PENALTY_EFOLD * (wall_dist - 1)) * aP_nat

    # Pressure gradient source
    p_src = (P[i - 1, j, k] - P[i, j, k]) * dyj * dzk

    aP0 = aE + aW + aN + aS + aT + aB + Sp
    rhs = (aE * uE + aW * uW + aN * uN + aS * uS
           + aT * uT + aB * uB + p_src)
    # R4: minmod SOU deferred correction (flags mirror 2D _sou_corr_u_x/_y).
    # Added via a guarded += so the use_sou=0 rhs expression tree is unchanged
    # (fastmath would re-associate an inline `+ sou` and break bit-identity).
    if use_sou == 1:
        rhs += (_sou_axis(u[max(i - 2, 0), j, k], u[max(i - 1, 0), j, k],
                          u[i, j, k], u[min(i + 1, Nx), j, k],
                          u[min(i + 2, Nx), j, k],
                          i > 2, i > 1 and i + 1 < Nx, i + 2 <= Nx, i > 1,
                          Fw, Fe, ue)
                + _sou_axis(u[i, max(j - 2, 0), k], u[i, max(j - 1, 0), k],
                            u[i, j, k], u[i, min(j + 1, Ny - 1), k],
                            u[i, min(j + 2, Ny - 1), k],
                            j > 1, j > 0 and j < Ny - 1, j < Ny - 2,
                            j > 0 and j < Ny - 1, Fs, Fn, Fn)
                + _sou_axis(u[i, j, max(k - 2, 0)], u[i, j, max(k - 1, 0)],
                            u[i, j, k], u[i, j, min(k + 1, Nz - 1)],
                            u[i, j, min(k + 2, Nz - 1)],
                            k > 1, k > 0 and k < Nz - 1, k < Nz - 2,
                            k > 0 and k < Nz - 1, Fb, Ft, Ft))
    aP = aP0 / alpha_u
    rhs += (1.0 - alpha_u) / alpha_u * aP0 * u[i, j, k]

    u[i, j, k] = rhs / aP
    d_u[i, j, k] = dyj * dzk / aP0


@njit(cache=True, fastmath=True)
def _sweep_u_jit_df_3d(u, v, w, P, d_u,
                        Nx, Ny, Nz,
                        dx, dy, dz,
                        rho_field, mu_eff_field, mu_field,
                        K_arr, cF_arr,
                        outlet_frac, inlet_frac,
                        alpha_u, n_sweeps, use_sou):
    """Solve the x-momentum equation on the u-staggered face.

    u : (Nx+1, Ny, Nz) — updated in place.
    K_arr, cF_arr : (Ny, Nz) — interstitial D-F coefficients per streamwise row.
    Internal walls (i=0, i=Nx) are no-slip (u=0).
    Cell body shared with the parallel variant via `_u_cell_df_3d`.
    """
    for _ in range(n_sweeps):
        for i in range(1, Nx):
            for j in range(Ny):
                for k in range(Nz):
                    _u_cell_df_3d(u, v, w, P, d_u, i, j, k,
                                  Nx, Ny, Nz, dx, dy, dz,
                                  rho_field, mu_eff_field, mu_field,
                                  K_arr, cF_arr, outlet_frac, inlet_frac,
                                  alpha_u, use_sou)

    # No-slip BC at x-walls
    for j in range(Ny):
        for k in range(Nz):
            u[0, j, k] = 0.0
            u[Nx, j, k] = 0.0


# Parallel red-black Gauss-Seidel variant of `_sweep_u_jit_df_3d`. Dispatched
# when grid ≥ `_PARALLEL_CELL_THRESHOLD`. Same cell body (`_u_cell_df_3d`);
# the triple loop is split into two colour passes with `(i+j+k) % 2 == color`
# filtering — each pass writes only same-colour cells, reads only
# opposite-colour neighbours, so `prange` on i is race-free.
@njit(cache=True, fastmath=True, parallel=True)
def _sweep_u_jit_df_3d_parallel(u, v, w, P, d_u,
                                 Nx, Ny, Nz,
                                 dx, dy, dz,
                                 rho_field, mu_eff_field, mu_field,
                                 K_arr, cF_arr,
                                 outlet_frac, inlet_frac,
                                 alpha_u, n_sweeps, use_sou):
    for _ in range(n_sweeps):
        for color in range(2):
            for i in prange(1, Nx):
                for j in range(Ny):
                    for k in range(Nz):
                        if (i + j + k) % 2 != color:
                            continue
                        _u_cell_df_3d(u, v, w, P, d_u, i, j, k,
                                      Nx, Ny, Nz, dx, dy, dz,
                                      rho_field, mu_eff_field, mu_field,
                                      K_arr, cF_arr, outlet_frac,
                                      inlet_frac, alpha_u, use_sou)
    for j in range(Ny):
        for k in range(Nz):
            u[0, j, k] = 0.0
            u[Nx, j, k] = 0.0


# ── SIMPLE Step 2: v-momentum (y-direction) ────────────────────────

@njit(cache=True, fastmath=True, inline='always')
def _v_cell_df_3d(u, v, w, P, d_v, i, j, k,
                  Nx, Ny, Nz, dx, dy, dz,
                  rho_field, mu_eff_field, mu_field,
                  K_arr, cF_arr, outlet_frac, inlet_frac, alpha_u, use_sou):
    """One Gauss-Seidel update of the v-face (i, j, k) — shared cell body
    for the serial and parallel sweeps (B6 dedup)."""
    jc = min(j, Ny - 1)
    dxi = dx[i]
    dyj = 0.5 * (dy[j - 1] + dy[min(j, Ny - 1)])
    dzk = dz[k]
    vol = dxi * dyj * dzk

    jb = max(j - 1, 0); jt = min(j, Ny - 1)
    mu_e = 0.5 * (mu_eff_field[i, jb, k]
                  + mu_eff_field[i, jt, k])

    # N4 (2026-07-07): actual neighbour-node distances — E/W v-neighbours at
    # 0.5*(dx[i]+dx[i±1]); N/S at dy[jt]/dy[jb] (v-nodes on y-interfaces);
    # T/B at 0.5*(dz[k]+dz[k±1]). Walls keep the half-cell 2× form.
    De = (mu_e * dyj * dzk / (0.5 * (dx[i] + dx[i + 1]))
          if i < Nx - 1 else 2.0 * mu_e * dyj * dzk / dxi)
    Dw = (mu_e * dyj * dzk / (0.5 * (dx[i] + dx[i - 1]))
          if i > 0 else 2.0 * mu_e * dyj * dzk / dxi)
    Dn = mu_e * dxi * dzk / dy[jt] if j < Ny - 1 else 0.0
    Ds = mu_e * dxi * dzk / dy[jb]
    Dt = (mu_e * dxi * dyj / (0.5 * (dz[k] + dz[k + 1]))
          if k < Nz - 1 else 0.0)
    Db = (mu_e * dxi * dyj / (0.5 * (dz[k] + dz[k - 1]))
          if k > 0 else 0.0)

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
        Sp += _WALL_PENALTY_BASE * wall_out**4 * np.exp(
            -_WALL_PENALTY_EFOLD * (wall_dist - 1)) * aP_nat
    wall_in = 1.0 - inlet_frac[i, k]
    if wall_in > 0.01 and j < 8:
        wall_dist = j + 1
        Sp += _WALL_PENALTY_BASE * wall_in**4 * np.exp(
            -_WALL_PENALTY_EFOLD * (wall_dist - 1)) * aP_nat

    p_src = (P[i, j - 1, k] - P[i, j, k]) * dxi * dzk

    aP0 = aE + aW + aN + aS + aT + aB + Sp
    rhs = (aE * vE + aW * vW + aN * vN + aS * vS
           + aT * vT + aB * vB + p_src)
    # R4: minmod SOU deferred correction (flags mirror 2D _sou_corr_v_x/_y).
    # Guarded += keeps the use_sou=0 rhs expression tree unchanged (fastmath).
    if use_sou == 1:
        rhs += (_sou_axis(v[max(i - 2, 0), j, k], v[max(i - 1, 0), j, k],
                          v[i, j, k], v[min(i + 1, Nx - 1), j, k],
                          v[min(i + 2, Nx - 1), j, k],
                          i > 1, i > 0 and i < Nx - 1, i < Nx - 2,
                          i > 0 and i < Nx - 1, Fw, Fe, Fe)
                + _sou_axis(v[i, max(j - 2, 0), k], v[i, max(j - 1, 0), k],
                            v[i, j, k], v[i, min(j + 1, Ny), k],
                            v[i, min(j + 2, Ny), k],
                            j > 2, j > 1, j + 2 <= Ny, j > 1,
                            Fs, Fn, vn)
                + _sou_axis(v[i, j, max(k - 2, 0)], v[i, j, max(k - 1, 0)],
                            v[i, j, k], v[i, j, min(k + 1, Nz - 1)],
                            v[i, j, min(k + 2, Nz - 1)],
                            k > 1, k > 0 and k < Nz - 1, k < Nz - 2,
                            k > 0 and k < Nz - 1, Fb, Ft, Ft))
    aP = aP0 / alpha_u
    rhs += (1.0 - alpha_u) / alpha_u * aP0 * v[i, j, k]

    v[i, j, k] = rhs / aP
    d_v[i, j, k] = dxi * dzk / aP0


@njit(cache=True, fastmath=True, inline='always')
def _v_bc_3d(v, v_inlet_field, rho_field, eps_field, outlet_frac, Nx, Ny, Nz):
    """Inlet + outlet BC tail shared by the serial and parallel v-sweeps."""
    for i in range(Nx):
        for k in range(Nz):
            v[i, 0, k] = v_inlet_field[i, k]
            # Gate outflow by outlet_frac — wall cells pin v=0 (consistent
            # with _correct_jit_3d).
            if outlet_frac[i, k] > 0.5:
                if Ny >= 2:
                    # N1 (2026-06-28): the continuity operator is ∇·(ε·ρ·u)=0
                    # (PPE/residual receive ε·ρ, and the residual's outlet face
                    # uses the cell ε·ρ), so the outlet extrapolation must
                    # conserve ε·ρ·v — else a y-zoned ε leaves a persistent
                    # outlet-cell divergence 0.5·v·ρ·(ε_{Ny-1}−ε_{Ny-2}). For a
                    # uniform-ε column ε cancels analytically; branch on it so
                    # the original ρ-ratio expression is kept bit-for-bit
                    # (golden-identical), and only the zoned column pays the ε·ρ
                    # form (whose FP rounding differs at the last bit).
                    if eps_field[i, Ny - 2, k] == eps_field[i, Ny - 1, k]:
                        rho_inner_face = 0.5 * (rho_field[i, Ny - 2, k]
                                                + rho_field[i, Ny - 1, k])
                        rho_outer_face = rho_field[i, Ny - 1, k]
                        v[i, Ny, k] = (v[i, Ny - 1, k]
                                       * rho_inner_face / rho_outer_face)
                    else:
                        er_inner = 0.5 * (
                            eps_field[i, Ny - 2, k] * rho_field[i, Ny - 2, k]
                            + eps_field[i, Ny - 1, k] * rho_field[i, Ny - 1, k])
                        er_outer = (eps_field[i, Ny - 1, k]
                                    * rho_field[i, Ny - 1, k])
                        v[i, Ny, k] = v[i, Ny - 1, k] * er_inner / er_outer
                else:
                    v[i, Ny, k] = v[i, Ny - 1, k]
            else:
                v[i, Ny, k] = 0.0


@njit(cache=True, fastmath=True)
def _sweep_v_jit_df_3d(u, v, w, P, d_v,
                        v_inlet_field,
                        Nx, Ny, Nz,
                        dx, dy, dz,
                        rho_field, eps_field, mu_eff_field, mu_field,
                        K_arr, cF_arr,
                        outlet_frac, inlet_frac,
                        alpha_u, n_sweeps, use_sou):
    """Solve the y-momentum equation on the v-staggered face.

    Inlet BC applied at j=0 (v[i, 0, k] = v_inlet_field[i, k]) — accepts
    non-uniform inlet profile for manifold mal-distribution modeling (P2).
    Outlet j=Ny preserves rho*v mass flux for variable-density flow.
    Cell body shared with the parallel variant via `_v_cell_df_3d`.
    """
    for _ in range(n_sweeps):
        for i in range(Nx):
            for j in range(1, Ny):
                for k in range(Nz):
                    _v_cell_df_3d(u, v, w, P, d_v, i, j, k,
                                  Nx, Ny, Nz, dx, dy, dz,
                                  rho_field, mu_eff_field, mu_field,
                                  K_arr, cF_arr, outlet_frac, inlet_frac,
                                  alpha_u, use_sou)

    # Apply BCs
    _v_bc_3d(v, v_inlet_field, rho_field, eps_field, outlet_frac, Nx, Ny, Nz)


# Parallel red-black Gauss-Seidel variant of `_sweep_v_jit_df_3d`.
@njit(cache=True, fastmath=True, parallel=True)
def _sweep_v_jit_df_3d_parallel(u, v, w, P, d_v,
                                 v_inlet_field,
                                 Nx, Ny, Nz,
                                 dx, dy, dz,
                                 rho_field, eps_field, mu_eff_field, mu_field,
                                 K_arr, cF_arr,
                                 outlet_frac, inlet_frac,
                                 alpha_u, n_sweeps, use_sou):
    for _ in range(n_sweeps):
        for color in range(2):
            for i in prange(Nx):
                for j in range(1, Ny):
                    for k in range(Nz):
                        if (i + j + k) % 2 != color:
                            continue
                        _v_cell_df_3d(u, v, w, P, d_v, i, j, k,
                                      Nx, Ny, Nz, dx, dy, dz,
                                      rho_field, mu_eff_field, mu_field,
                                      K_arr, cF_arr, outlet_frac,
                                      inlet_frac, alpha_u, use_sou)
    _v_bc_3d(v, v_inlet_field, rho_field, eps_field, outlet_frac, Nx, Ny, Nz)


# ── SIMPLE Step 3: w-momentum (z-direction) — new in 3D ────────────

@njit(cache=True, fastmath=True, inline='always')
def _w_cell_df_3d(u, v, w, P, d_w, i, j, k,
                  Nx, Ny, Nz, dx, dy, dz,
                  rho_field, mu_eff_field, mu_field,
                  K_arr, cF_arr, outlet_frac, inlet_frac, alpha_u, use_sou):
    """One Gauss-Seidel update of the w-face (i, j, k) — shared cell body
    for the serial and parallel sweeps (B6 dedup)."""
    kc = min(k, Nz - 1)
    dxi = dx[i]
    dyj = dy[j]
    dzk = 0.5 * (dz[k - 1] + dz[min(k, Nz - 1)])
    vol = dxi * dyj * dzk

    kb = max(k - 1, 0); kt = min(k, Nz - 1)
    mu_e = 0.5 * (mu_eff_field[i, j, kb]
                  + mu_eff_field[i, j, kt])

    # N4 (2026-07-07): actual neighbour-node distances — E/W w-neighbours at
    # 0.5*(dx[i]+dx[i±1]), N/S at 0.5*(dy[j]+dy[j±1]); T/B at dz[kt]/dz[kb]
    # (w-nodes on z-interfaces). Walls keep the half-cell 2× form.
    De = (mu_e * dyj * dzk / (0.5 * (dx[i] + dx[i + 1]))
          if i < Nx - 1 else 2.0 * mu_e * dyj * dzk / dxi)
    Dw_ = (mu_e * dyj * dzk / (0.5 * (dx[i] + dx[i - 1]))
           if i > 0 else 2.0 * mu_e * dyj * dzk / dxi)
    Dn = (mu_e * dxi * dzk / (0.5 * (dy[j] + dy[j + 1]))
          if j < Ny - 1 else 2.0 * mu_e * dxi * dzk / dyj)
    Ds = (mu_e * dxi * dzk / (0.5 * (dy[j] + dy[j - 1]))
          if j > 0 else 2.0 * mu_e * dxi * dzk / dyj)
    Dt = mu_e * dxi * dyj / dz[kt] if k < Nz - 1 else 0.0
    Db = mu_e * dxi * dyj / dz[kb]

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
        Sp += _WALL_PENALTY_BASE * wall_out**4 * np.exp(
            -_WALL_PENALTY_EFOLD * (wall_dist - 1)) * aP_nat
    wall_in = 1.0 - 0.5 * (inlet_frac[i, kb] + inlet_frac[i, kt])
    if wall_in > 0.01 and j < 8:
        wall_dist = j + 1
        Sp += _WALL_PENALTY_BASE * wall_in**4 * np.exp(
            -_WALL_PENALTY_EFOLD * (wall_dist - 1)) * aP_nat

    p_src = (P[i, j, k - 1] - P[i, j, k]) * dxi * dyj

    aP0 = aE + aW + aN + aS + aT + aB + Sp
    rhs = (aE * wE + aW * wW + aN * wN + aS * wS
           + aT * wT + aB * wB + p_src)
    # R4: minmod SOU deferred correction (cross axes mirror v; parallel = z).
    # Guarded += keeps the use_sou=0 rhs expression tree unchanged (fastmath).
    if use_sou == 1:
        rhs += (_sou_axis(w[max(i - 2, 0), j, k], w[max(i - 1, 0), j, k],
                          w[i, j, k], w[min(i + 1, Nx - 1), j, k],
                          w[min(i + 2, Nx - 1), j, k],
                          i > 1, i > 0 and i < Nx - 1, i < Nx - 2,
                          i > 0 and i < Nx - 1, Fw_, Fe, Fe)
                + _sou_axis(w[i, max(j - 2, 0), k], w[i, max(j - 1, 0), k],
                            w[i, j, k], w[i, min(j + 1, Ny - 1), k],
                            w[i, min(j + 2, Ny - 1), k],
                            j > 1, j > 0 and j < Ny - 1, j < Ny - 2,
                            j > 0 and j < Ny - 1, Fs, Fn, Fn)
                + _sou_axis(w[i, j, max(k - 2, 0)], w[i, j, max(k - 1, 0)],
                            w[i, j, k], w[i, j, min(k + 1, Nz)],
                            w[i, j, min(k + 2, Nz)],
                            k > 2, k > 1, k + 2 <= Nz, k > 1,
                            Fb, Ft, wn))
    aP = aP0 / alpha_u
    rhs += (1.0 - alpha_u) / alpha_u * aP0 * w[i, j, k]

    w[i, j, k] = rhs / aP
    d_w[i, j, k] = dxi * dyj / aP0


@njit(cache=True, fastmath=True)
def _sweep_w_jit_df_3d(u, v, w, P, d_w,
                        Nx, Ny, Nz,
                        dx, dy, dz,
                        rho_field, mu_eff_field, mu_field,
                        K_arr, cF_arr,
                        outlet_frac, inlet_frac,
                        alpha_u, n_sweeps, use_sou):
    """Solve the z-momentum equation on the w-staggered face.

    Top/bottom z-walls (k=0, k=Nz) are no-slip by default (w=0).
    Cell body shared with the parallel variant via `_w_cell_df_3d`.
    """
    for _ in range(n_sweeps):
        for i in range(Nx):
            for j in range(Ny):
                for k in range(1, Nz):
                    _w_cell_df_3d(u, v, w, P, d_w, i, j, k,
                                  Nx, Ny, Nz, dx, dy, dz,
                                  rho_field, mu_eff_field, mu_field,
                                  K_arr, cF_arr, outlet_frac, inlet_frac,
                                  alpha_u, use_sou)

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
                                 alpha_u, n_sweeps, use_sou):
    for _ in range(n_sweeps):
        for color in range(2):
            for i in prange(Nx):
                for j in range(Ny):
                    for k in range(1, Nz):
                        if (i + j + k) % 2 != color:
                            continue
                        _w_cell_df_3d(u, v, w, P, d_w, i, j, k,
                                      Nx, Ny, Nz, dx, dy, dz,
                                      rho_field, mu_eff_field, mu_field,
                                      K_arr, cF_arr, outlet_frac,
                                      inlet_frac, alpha_u, use_sou)
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


# ── SIMPLE Step 5: pressure / velocity correction ─────────────────

@njit(cache=True, fastmath=True)
def _correct_jit_3d(u, v, w, P, Pp, d_u, d_v, d_w,
                     v_inlet_field,
                     Nx, Ny, Nz, alpha_p, rho_field, eps_field,
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
            # Wall cells (outlet_mask_ij=False) pin v=0; open cells preserve
            # rho*v mass flux across the outlet for compressible runs.
            if outlet_mask_ij[i, k]:
                if Ny >= 2:
                    # N1 (2026-06-28): conserve ε·ρ·v (continuity operator), not
                    # ρ·v — matches _v_bc_3d. Uniform-ε column keeps the original
                    # ρ-ratio expression bit-for-bit (golden-identical); zoned ε
                    # uses the ε·ρ form so the outlet cell telescopes.
                    if eps_field[i, Ny - 2, k] == eps_field[i, Ny - 1, k]:
                        rho_inner_face = 0.5 * (rho_field[i, Ny - 2, k]
                                                + rho_field[i, Ny - 1, k])
                        rho_outer_face = rho_field[i, Ny - 1, k]
                        v[i, Ny, k] = (v[i, Ny - 1, k]
                                       * rho_inner_face / rho_outer_face)
                    else:
                        er_inner = 0.5 * (
                            eps_field[i, Ny - 2, k] * rho_field[i, Ny - 2, k]
                            + eps_field[i, Ny - 1, k] * rho_field[i, Ny - 1, k])
                        er_outer = (eps_field[i, Ny - 1, k]
                                    * rho_field[i, Ny - 1, k])
                        v[i, Ny, k] = v[i, Ny - 1, k] * er_inner / er_outer
                else:
                    v[i, Ny, k] = v[i, Ny - 1, k]
            else:
                v[i, Ny, k] = 0.0
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
