"""
simple_solver.py — 2D SIMPLE solver for porous-media transition zone

Solves steady-state Navier-Stokes + Brinkman porous resistance,
then frozen-velocity temperature field (LTNE: fluid + solid).

All inner loops are Numba-compiled for speed (~50-100x vs pure Python).

Physics (velocity):
  du/dx + dv/dy = 0                                         (continuity)
  rho(u du/dx + v du/dy) = -dP/dx + mu_eff nabla^2 u - Rx  (x-momentum)
  rho(u dv/dx + v dv/dy) = -dP/dy + mu_eff nabla^2 v - Ry  (y-momentum)
  Rx = f rho |U| u / (2 r_h),  Ry = f rho |U| v / (2 r_h)

Physics (temperature, frozen velocity):
  eps rho_cp (u dTf/dx + v dTf/dy) = K_ff nabla^2 Tf + h_v(Ts - Tf)
  0 = K_ss nabla^2 Ts + h_v(Tf - Ts) + h_v2(T_other - Ts)

Staggered grid:  P[i,j] cell centre (Nx,Ny)
                 u[i,j] x-face (Nx+1,Ny)    v[i,j] y-face (Nx,Ny+1)

Velocity convention (IMPORTANT — differs from textbook Brinkman-Forchheimer):
  u, v are *interstitial* (pore-average) velocities, not superficial. Inlet BC
  `v_inlet = m_dot / (rho * A_void)` where A_void = eps_f * A_total; training
  data (df_fit/) uses the same convention. Consequently K and c_F from the D-F
  surrogate are *effective interstitial* coefficients that already absorb the
  eps_f factor — they are not the canonical Darcy/Forchheimer values one would
  cite from a textbook. This is algebraically equivalent to the superficial
  form when eps_f is spatially uniform (e.g. Shanghai). For spatially varying
  eps_f (future zoned-TPMS work) the convection and Laplacian operators on
  interstitial u deviate from the homogenised BFNS derivation — flag before
  extending to non-uniform porosity.
"""

import numpy as np
from numba import njit
from .tpms_calc import (air_density, air_viscosity, P_atm)


# ===================================================================
#  Numba kernels
# ===================================================================

# ── SOU deferred correction for momentum (minmod limiter) ──────────
@njit(cache=True)
def _sou_corr_u_x(u, i, j, Nx, Fe):
    """SOU deferred correction for u-momentum in x-direction.
    u is on x-faces: u[i,j] at face between cells i-1 and i.
    Fe = rho*ue*dy is the east-face convective flux for this u-cell.
    """
    ue_loc = 0.5 * (u[i, j] + u[min(i + 1, Nx), j])
    if ue_loc >= 0:
        phi_w = 0.0
        if i > 2:
            gu = u[i - 1, j] - u[i - 2, j]
            gd = u[i, j] - u[i - 1, j]
            if gu * gd > 0:
                phi_w = min(abs(gu), abs(gd))
                if gu < 0: phi_w = -phi_w
        phi_e = 0.0
        if i + 1 < Nx and i > 1:
            gu = u[i, j] - u[i - 1, j]
            gd = u[i + 1, j] - u[i, j]
            if gu * gd > 0:
                phi_e = min(abs(gu), abs(gd))
                if gu < 0: phi_e = -phi_e
        return 0.5 * Fe * (phi_w - phi_e)
    else:
        phi_e = 0.0
        if i + 2 <= Nx:
            gu = u[i + 1, j] - u[min(i + 2, Nx), j]
            gd = u[i, j] - u[i + 1, j]
            if gu * gd > 0:
                phi_e = min(abs(gu), abs(gd))
                if gu < 0: phi_e = -phi_e
        phi_w = 0.0
        if i > 1 and i + 1 <= Nx:
            gu = u[i, j] - u[i + 1, j]
            gd = u[i - 1, j] - u[i, j]
            if gu * gd > 0:
                phi_w = min(abs(gu), abs(gd))
                if gu < 0: phi_w = -phi_w
        return 0.5 * Fe * (phi_e - phi_w)


@njit(cache=True)
def _sou_corr_u_y(u, i, j, Ny, Fn):
    """SOU deferred correction for u-momentum in y-direction."""
    if Fn >= 0:
        phi_s = 0.0
        if j > 1:
            gu = u[i, j - 1] - u[i, j - 2]
            gd = u[i, j] - u[i, j - 1]
            if gu * gd > 0:
                phi_s = min(abs(gu), abs(gd))
                if gu < 0: phi_s = -phi_s
        phi_n = 0.0
        if j < Ny - 1 and j > 0:
            gu = u[i, j] - u[i, j - 1]
            gd = u[i, j + 1] - u[i, j]
            if gu * gd > 0:
                phi_n = min(abs(gu), abs(gd))
                if gu < 0: phi_n = -phi_n
        return 0.5 * Fn * (phi_s - phi_n)
    else:
        phi_n = 0.0
        if j < Ny - 2:
            gu = u[i, j + 1] - u[i, j + 2]
            gd = u[i, j] - u[i, j + 1]
            if gu * gd > 0:
                phi_n = min(abs(gu), abs(gd))
                if gu < 0: phi_n = -phi_n
        phi_s = 0.0
        if j > 0 and j < Ny - 1:
            gu = u[i, j] - u[i, j + 1]
            gd = u[i, j - 1] - u[i, j]
            if gu * gd > 0:
                phi_s = min(abs(gu), abs(gd))
                if gu < 0: phi_s = -phi_s
        return 0.5 * Fn * (phi_n - phi_s)


@njit(cache=True)
def _sou_corr_v_x(v, i, j, Nx, Fe):
    """SOU deferred correction for v-momentum in x-direction."""
    if Fe >= 0:
        phi_w = 0.0
        if i > 1:
            gu = v[i - 1, j] - v[i - 2, j]
            gd = v[i, j] - v[i - 1, j]
            if gu * gd > 0:
                phi_w = min(abs(gu), abs(gd))
                if gu < 0: phi_w = -phi_w
        phi_e = 0.0
        if i < Nx - 1 and i > 0:
            gu = v[i, j] - v[i - 1, j]
            gd = v[i + 1, j] - v[i, j]
            if gu * gd > 0:
                phi_e = min(abs(gu), abs(gd))
                if gu < 0: phi_e = -phi_e
        return 0.5 * Fe * (phi_w - phi_e)
    else:
        phi_e = 0.0
        if i < Nx - 2:
            gu = v[i + 1, j] - v[i + 2, j]
            gd = v[i, j] - v[i + 1, j]
            if gu * gd > 0:
                phi_e = min(abs(gu), abs(gd))
                if gu < 0: phi_e = -phi_e
        phi_w = 0.0
        if i > 0 and i < Nx - 1:
            gu = v[i, j] - v[i + 1, j]
            gd = v[i - 1, j] - v[i, j]
            if gu * gd > 0:
                phi_w = min(abs(gu), abs(gd))
                if gu < 0: phi_w = -phi_w
        return 0.5 * Fe * (phi_e - phi_w)


@njit(cache=True)
def _sou_corr_v_y(v, i, j, Ny, Fn):
    """SOU deferred correction for v-momentum in y-direction.
    v is on y-faces: v[i,j] at face between cells j-1 and j.
    """
    vn_loc = 0.5 * (v[i, j] + v[i, min(j + 1, Ny)])
    if vn_loc >= 0:
        phi_s = 0.0
        if j > 2:
            gu = v[i, j - 1] - v[i, j - 2]
            gd = v[i, j] - v[i, j - 1]
            if gu * gd > 0:
                phi_s = min(abs(gu), abs(gd))
                if gu < 0: phi_s = -phi_s
        phi_n = 0.0
        if j + 1 <= Ny and j > 1:
            gu = v[i, j] - v[i, j - 1]
            gd = v[i, min(j + 1, Ny)] - v[i, j]
            if gu * gd > 0:
                phi_n = min(abs(gu), abs(gd))
                if gu < 0: phi_n = -phi_n
        return 0.5 * Fn * (phi_s - phi_n)
    else:
        phi_n = 0.0
        if j + 2 <= Ny:
            gu = v[i, j + 1] - v[i, min(j + 2, Ny)]
            gd = v[i, j] - v[i, j + 1]
            if gu * gd > 0:
                phi_n = min(abs(gu), abs(gd))
                if gu < 0: phi_n = -phi_n
        phi_s = 0.0
        if j > 1 and j + 1 <= Ny:
            gu = v[i, j] - v[i, j + 1]
            gd = v[i, j - 1] - v[i, j]
            if gu * gd > 0:
                phi_s = min(abs(gu), abs(gd))
                if gu < 0: phi_s = -phi_s
        return 0.5 * Fn * (phi_n - phi_s)


@njit(cache=True)
def _porous_src_df(umag, K, cF, mu, rho):
    """Linearised porous resistance coefficient [kg/(m3 s)] for ConstDF-v1.

    Darcy-Forchheimer closure: Sp * u = (mu/K) * u + rho * c_F * |u| * u.
    K and c_F are geometry-level constants from the 3D MLP ensemble surrogate
    (see df_fit/predict.py:predict_K_cF). Caller provides K, cF per-row.
    """
    if umag < 1e-10:
        return mu / K  # pure Darcy when velocity vanishes
    return mu / K + rho * cF * umag


@njit(cache=True)
def _umag_u(u, v, i, j, Nx, Ny):
    """Speed at u-face (i,j)."""
    il = max(i - 1, 0); ir = min(i, Nx - 1)
    va = 0.25 * (v[il, j] + v[ir, j] + v[il, j + 1] + v[ir, j + 1])
    return np.sqrt(u[i, j] ** 2 + va ** 2)


@njit(cache=True)
def _umag_v(u, v, i, j, Nx, Ny):
    """Speed at v-face (i,j)."""
    jb = max(j - 1, 0); jt = min(j, Ny - 1)
    ua = 0.25 * (u[i, jb] + u[i + 1, jb] + u[i, jt] + u[i + 1, jt])
    return np.sqrt(ua ** 2 + v[i, j] ** 2)


# ── SIMPLE Step 1: x-momentum with D-F closure ───────────────────
@njit(cache=True)
def _sweep_u_jit_df(u, v, P, d_u, inlet_frac, outlet_frac,
                    Nx, Ny, dx_arr, dy_arr, rho_field, mu_eff_field,
                    K_arr, cF_arr, mu_field,
                    alpha_u, n_sweeps):
    """D-F variant of _sweep_u_jit: porous source uses (K, c_F) per row from
    the ConstDF-v1 surrogate, no phi_arr correction (MLP covers training range
    natively). mu_eff_field and mu_field are 2D (Nx, Ny) arrays so that
    viscosity tracks the temperature field in non-isothermal compressible flow.
    """
    for _ in range(n_sweeps):
        for i in range(1, Nx):
            for j in range(Ny):
                dxi = 0.5 * (dx_arr[i - 1] + dx_arr[min(i, Nx - 1)])
                dyj = dy_arr[j]
                vol = dxi * dyj

                il_r = max(i - 1, 0); ir_r = min(i, Nx - 1)
                mu_e = 0.5 * (mu_eff_field[il_r, j] + mu_eff_field[ir_r, j])
                De0 = mu_e * dyj / dxi
                Dn0 = mu_e * dxi / dyj

                uE = u[i + 1, j] if i + 1 < Nx else 0.0
                uW = u[i - 1, j] if i > 1 else 0.0
                uN = u[i, j + 1] if j < Ny - 1 else u[i, j]
                uS = u[i, j - 1] if j > 0 else 0.0

                De = De0; Dw = De0
                Dn = Dn0 if j < Ny - 1 else 0.0
                Ds = Dn0 if j > 0 else 0.0

                ue = 0.5 * (u[i, j] + u[min(i + 1, Nx), j])
                uw = 0.5 * (u[max(i - 1, 0), j] + u[i, j])
                il = max(i - 1, 0); ir = min(i, Nx - 1)
                vn = 0.5 * (v[il, j + 1] + v[ir, j + 1]) if j < Ny - 1 else 0.0
                vs = 0.5 * (v[il, j] + v[ir, j])

                rho_loc = 0.5 * (rho_field[il_r, j] + rho_field[ir_r, j])
                mu_loc  = 0.5 * (mu_field[il_r, j] + mu_field[ir_r, j])

                Fe = rho_loc * ue * dyj; Fw = rho_loc * uw * dyj
                Fn = rho_loc * vn * dxi; Fs = rho_loc * vs * dxi

                aE = De + max(-Fe, 0.0)
                aW = Dw + max(Fw, 0.0)
                aN = Dn + max(-Fn, 0.0)
                aS = Ds + max(Fs, 0.0)

                umag = _umag_u(u, v, i, j, Nx, Ny)
                Sp = _porous_src_df(umag, K_arr[j], cF_arr[j], mu_loc, rho_loc) * vol

                # Brinkman penalty: grid-invariant via aP_natural (matches 3D
                # convention in simple_solver_3d.py). Old form `1e8*...*vol`
                # scaled with cell volume and was grid-dependent.
                aP_nat = aE + aW + aN + aS
                il_u = max(i - 1, 0); ir_u = min(i, Nx - 1)
                wall_out = 1.0 - 0.5 * (outlet_frac[il_u] + outlet_frac[ir_u])
                if wall_out > 0.01 and j >= Ny - 8:
                    wall_dist = Ny - j
                    Sp += 1e3 * wall_out**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat
                wall_in = 1.0 - 0.5 * (inlet_frac[il_u] + inlet_frac[ir_u])
                if wall_in > 0.01 and j < 8:
                    wall_dist = j + 1
                    Sp += 1e3 * wall_in**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat

                p_src = (P[i - 1, j] - P[i, j]) * dyj
                sou = (_sou_corr_u_x(u, i, j, Nx, Fe)
                     + _sou_corr_u_y(u, i, j, Ny, Fn))
                aP0 = aE + aW + aN + aS + Sp
                rhs = aE * uE + aW * uW + aN * uN + aS * uS + p_src + sou
                aP = aP0 / alpha_u
                rhs += (1.0 - alpha_u) / alpha_u * aP0 * u[i, j]

                u[i, j] = rhs / aP
                d_u[i, j] = dyj / aP0

    for j in range(Ny):
        u[0, j] = 0.0; u[Nx, j] = 0.0


# ── SIMPLE Step 2: y-momentum with D-F closure ───────────────────
@njit(cache=True)
def _sweep_v_jit_df(u, v, P, d_v, inlet_frac, v_inlet, outlet_frac,
                    Nx, Ny, dx_arr, dy_arr, rho_field, mu_eff_field,
                    K_arr, cF_arr, mu_field,
                    alpha_u, n_sweeps):
    """D-F variant of _sweep_v_jit, mirrors _sweep_u_jit_df changes.
    mu_eff_field and mu_field are 2D (Nx, Ny) for non-isothermal coupling."""
    for _ in range(n_sweeps):
        for i in range(Nx):
            for j in range(1, Ny):
                jc = min(j, Ny - 1)
                dxi = dx_arr[i]
                dyj = 0.5 * (dy_arr[j - 1] + dy_arr[min(j, Ny - 1)])
                vol = dxi * dyj

                jb = max(j - 1, 0); jt = min(j, Ny - 1)
                mu_e = 0.5 * (mu_eff_field[i, jb] + mu_eff_field[i, jt])
                De0 = mu_e * dyj / dxi
                Dn0 = mu_e * dxi / dyj

                # No-slip at side walls (x=0, x=W): tangential velocity v=0 at
                # wall. Distance from cell centre to wall = dxi/2, so the wall
                # diffusion coefficient is mu_e * dyj / (0.5*dxi) = 2*De0.
                # Previously free-slip (De=0 at i=Nx-1, Dw=0 at i=0); corrected
                # 2026-04-17 to match physical outer-housing walls in TPMS heat
                # exchangers. For symmetry/periodic boundaries, revert to 0/0.
                if i < Nx - 1:
                    vE = v[i + 1, j]; De = De0
                else:
                    vE = 0.0; De = 2.0 * De0   # east wall (no-slip)
                if i > 0:
                    vW = v[i - 1, j]; Dw = De0
                else:
                    vW = 0.0; Dw = 2.0 * De0   # west wall (no-slip)
                vN = v[i, j + 1] if j < Ny - 1 else v[i, j]
                vS = v[i, j - 1]

                Dn = Dn0 if j < Ny - 1 else 0.0
                Ds = Dn0

                ue = 0.5 * (u[i + 1, jb] + u[i + 1, jt]) if i < Nx - 1 else 0.0
                uw = 0.5 * (u[i, jb] + u[i, jt]) if i > 0 else 0.0
                vn = 0.5 * (v[i, j] + v[i, min(j + 1, Ny)])
                vs = 0.5 * (v[i, max(j - 1, 0)] + v[i, j])

                rho_loc = 0.5 * (rho_field[i, jb] + rho_field[i, jt])
                mu_loc  = 0.5 * (mu_field[i, jb] + mu_field[i, jt])

                Fe = rho_loc * ue * dyj; Fw = rho_loc * uw * dyj
                Fn = rho_loc * vn * dxi; Fs = rho_loc * vs * dxi

                aE = De + max(-Fe, 0.0)
                aW = Dw + max(Fw, 0.0)
                aN = Dn + max(-Fn, 0.0)
                aS = Ds + max(Fs, 0.0)

                umag = _umag_v(u, v, i, j, Nx, Ny)
                Sp = _porous_src_df(umag, K_arr[jc], cF_arr[jc], mu_loc, rho_loc) * vol

                # Brinkman penalty — grid-invariant (3D parity, P1b-c)
                aP_nat = aE + aW + aN + aS
                wall_out = 1.0 - outlet_frac[i]
                if wall_out > 0.01 and j >= Ny - 8:
                    wall_dist = Ny - j
                    Sp += 1e3 * wall_out**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat
                wall_in = 1.0 - inlet_frac[i]
                if wall_in > 0.01 and j < 8:
                    wall_dist = j + 1
                    Sp += 1e3 * wall_in**4 * np.exp(-1.5 * (wall_dist - 1)) * aP_nat

                p_src = (P[i, j - 1] - P[i, j]) * dxi
                sou = (_sou_corr_v_x(v, i, j, Nx, Fe)
                     + _sou_corr_v_y(v, i, j, Ny, Fn))
                aP0 = aE + aW + aN + aS + Sp
                rhs = aE * vE + aW * vW + aN * vN + aS * vS + p_src + sou
                aP = aP0 / alpha_u
                rhs += (1.0 - alpha_u) / alpha_u * aP0 * v[i, j]

                v[i, j] = rhs / aP
                d_v[i, j] = dxi / aP0

    for i in range(Nx):
        v[i, 0] = v_inlet * inlet_frac[i]
        if outlet_frac[i] > 0.5:
            if Ny >= 2:
                rho_inner_face = 0.5 * (rho_field[i, Ny-2] + rho_field[i, Ny-1])
                rho_outer_face = rho_field[i, Ny-1]
                v[i, Ny] = v[i, Ny - 1] * rho_inner_face / rho_outer_face
            else:
                v[i, Ny] = v[i, Ny - 1]
        else:
            v[i, Ny] = 0.0


# ── SIMPLE Steps 3-4: pressure correction (sparse direct solver) ──

from scipy import sparse
from scipy.sparse.linalg import spsolve


def _build_pp_sparsity_pattern(Nx, Ny, outlet_frac):
    """Precompute CSR sparsity pattern for the pressure-Poisson operator.

    For each cell (i, j) we allocate up to 5 slots in the CSR data array:
    one for the diagonal (always present), and up to 4 for the east/west/
    north/south off-diagonal couplings. Boundary cells and outlet-reference
    cells have fewer non-zeros, but we still allocate 5 slots each and write
    0.0 into the unused ones at assembly time — simpler bookkeeping and the
    extra zeros cost nothing in the sparse solve.

    Returns a dict with:
        indptr   : int32[N+1]  — CSR row pointer
        indices  : int32[nnz]  — CSR column indices
        cell_base: int32[N]    — data-array offset for cell k's first slot
        cell_kind: int8[N]     — 0=interior, 1=outlet_ref
    All arrays are contiguous and ready to pass to the Numba assembler.
    """
    N = Nx * Ny
    def idx(i, j): return i * Ny + j

    indptr = np.zeros(N + 1, dtype=np.int32)
    indices_list = []
    cell_base = np.zeros(N, dtype=np.int32)
    cell_kind = np.zeros(N, dtype=np.int8)

    pos = 0
    for i in range(Nx):
        for j in range(Ny):
            k = idx(i, j)
            cell_base[k] = pos
            # Outlet reference: diagonal only, Pp = 0.
            # Threshold 0.01 is permissive on purpose — any cell that *might*
            # pass flow becomes a pressure anchor. For Shanghai and optimizer
            # full-width outlets (outlet_frac identically 1.0) this has no
            # effect. For partial-outlet / zoned configurations, the taper
            # logic in __init__ (L1255-1264) keeps outlet_frac of open cells
            # ≥ 0.706 (d=1 of the 4-cell exp decay), so transition cells in
            # (0.01, 0.5] should not normally appear — but if a straddling
            # cell does land in that band, it is pinned here while the v-face
            # sweep treats it as a wall (L567-577). The mismatch is benign
            # only because _correct_jit L781-787 unconditionally re-writes
            # v[i, Ny] via the mass-conservation outflow rule, effectively
            # promoting such a cell to outlet semantics. Audit: 2026-04-19.
            if j == Ny - 1 and outlet_frac[i] > 0.01:
                cell_kind[k] = 1
                indices_list.append(k)
                pos += 1
                indptr[k + 1] = pos
                continue
            # Standard interior/edge cell: diagonal + up-to-4 off-diagonals.
            # Order: [self, E, W, N, S]. Unused neighbours still get a slot
            # pointing back to self (diagonal) with data 0, so the CSR
            # structure is uniform.
            indices_list.append(k)                                      # diag
            indices_list.append(idx(i+1, j) if i < Nx-1 else k)        # E
            indices_list.append(idx(i-1, j) if i > 0    else k)        # W
            indices_list.append(idx(i, j+1) if j < Ny-1 else k)        # N
            indices_list.append(idx(i, j-1) if j > 0    else k)        # S
            pos += 5
            indptr[k + 1] = pos

    indices = np.asarray(indices_list, dtype=np.int32)
    return {
        'indptr': indptr,
        'indices': indices,
        'cell_base': cell_base,
        'cell_kind': cell_kind,
        'nnz': pos,
    }


@njit(cache=True)
def _assemble_pp_data_jit(data, rhs, u, v, d_u, d_v, outlet_frac,
                          Nx, Ny, dx_arr, dy_arr, rho_field,
                          cell_base, cell_kind):
    """Fill CSR `data` array and `rhs` vector for the pressure-Poisson operator.

    For each cell (i, j), writes 5 consecutive slots [diag, E, W, N, S] into
    `data[cell_base[k] : cell_base[k]+5]`, or a single slot [1.0] for outlet
    reference cells. `cell_kind` disambiguates:
        0 = standard interior/edge cell
        1 = outlet reference (Pp = 0 enforced)
    """
    for i in range(Nx):
        for j in range(Ny):
            k = i * Ny + j
            base = cell_base[k]

            if cell_kind[k] == 1:
                # Outlet reference: single diagonal entry = 1.0
                data[base] = 1.0
                rhs[k] = 0.0
                continue

            dxi = dx_arr[i]
            dyj = dy_arr[j]

            # Face densities (linear interpolation from cell centres)
            if i < Nx - 1:
                rho_e = 0.5 * (rho_field[i, j] + rho_field[i+1, j])
            else:
                rho_e = rho_field[i, j]
            if i > 0:
                rho_w = 0.5 * (rho_field[i-1, j] + rho_field[i, j])
            else:
                rho_w = rho_field[i, j]
            if j < Ny - 1:
                rho_n = 0.5 * (rho_field[i, j] + rho_field[i, j+1])
            else:
                rho_n = rho_field[i, j]
            if j > 0:
                rho_s = 0.5 * (rho_field[i, j-1] + rho_field[i, j])
            else:
                rho_s = rho_field[i, j]

            aE = rho_e * d_u[i+1, j] * dyj if i < Nx - 1 else 0.0
            aW = rho_w * d_u[i,   j] * dyj if i > 0      else 0.0
            aN = rho_n * d_v[i, j+1] * dxi if j < Ny - 1 else 0.0
            aS = rho_s * d_v[i, j  ] * dxi if j > 0      else 0.0
            aP = aE + aW + aN + aS

            if aP < 1e-30:
                # Degenerate cell: pin Pp = 0
                data[base] = 1.0
                data[base + 1] = 0.0  # E slot
                data[base + 2] = 0.0  # W
                data[base + 3] = 0.0  # N
                data[base + 4] = 0.0  # S
                rhs[k] = 0.0
                continue

            # Standard 5-point stencil, [diag, E, W, N, S]
            data[base    ] = aP
            data[base + 1] = -aE
            data[base + 2] = -aW
            data[base + 3] = -aN
            data[base + 4] = -aS

            rhs[k] = -((rho_e * u[i+1, j] - rho_w * u[i, j]) * dyj
                      + (rho_n * v[i, j+1] - rho_s * v[i, j]) * dxi)


def _solve_pp_sparse_fast(Pp, u, v, d_u, d_v, outlet_frac,
                          Nx, Ny, dx_arr, dy_arr, rho_field, sparsity):
    """Pressure-Poisson solve with precomputed sparsity pattern.

    Caller must pass `sparsity` as returned by `_build_pp_sparsity_pattern`.
    Returns (A, rhs) alongside writing Pp in place, so regression tests can
    compare the assembled matrix directly.
    """
    N = Nx * Ny
    nnz = sparsity['nnz']
    data = np.zeros(nnz, dtype=np.float64)
    rhs = np.zeros(N, dtype=np.float64)

    _assemble_pp_data_jit(data, rhs, u, v, d_u, d_v, outlet_frac,
                          Nx, Ny, dx_arr, dy_arr, rho_field,
                          sparsity['cell_base'], sparsity['cell_kind'])

    # NOTE: scipy csr_matrix takes ownership of indptr without copying, and
    # spsolve may reorder it in-place. We copy indices/indptr so the cached
    # sparsity pattern is not corrupted across SIMPLE iterations.
    A = sparse.csr_matrix(
        (data, sparsity['indices'].copy(), sparsity['indptr'].copy()),
        shape=(N, N),
    )
    pp_flat = spsolve(A, rhs)
    Pp[:, :] = pp_flat.reshape(Nx, Ny)
    return A, rhs



# ── SIMPLE Step 5: correction ─────────────────────────────────────
@njit(cache=True)
def _correct_jit(u, v, P, Pp, d_u, d_v, inlet_frac, v_inlet, outlet_frac,
                 Nx, Ny, alpha_p, rho_field):
    # Pressure correction (skip only outlet cells at j=Ny-1)
    for i in range(Nx):
        for j in range(Ny):
            if j == Ny - 1 and outlet_frac[i] > 0.01:
                continue  # outlet: Pp=0, no correction
            P[i, j] += alpha_p * Pp[i, j]
    # u correction
    for i in range(1, Nx):
        for j in range(Ny):
            u[i, j] += d_u[i, j] * (Pp[i - 1, j] - Pp[i, j])
    # v correction
    for i in range(Nx):
        for j in range(1, Ny):
            v[i, j] += d_v[i, j] * (Pp[i, j - 1] - Pp[i, j])
    # Re-apply BCs
    for j in range(Ny):
        u[0, j] = 0.0; u[Nx, j] = 0.0
    for i in range(Nx):
        v[i, 0] = v_inlet * inlet_frac[i]
        # Variable density outflow: ρ·v conserved across last face.
        # Wall cells (outlet_frac ≤ 0.5) must pin v=0 — matches _sweep_v_jit_df
        # end-of-sweep BC. Without this gate, zoned / partial-outlet configs
        # drive spurious through-wall flow that the pp-equation sees as mass
        # imbalance. Benign for full-outlet Shanghai (outlet_frac ≡ 1).
        if outlet_frac[i] > 0.5:
            if Ny >= 2:
                rho_inner_face = 0.5 * (rho_field[i, Ny-2] + rho_field[i, Ny-1])
                rho_outer_face = rho_field[i, Ny-1]
                v[i, Ny] = v[i, Ny - 1] * rho_inner_face / rho_outer_face
            else:
                v[i, Ny] = v[i, Ny - 1]
        else:
            v[i, Ny] = 0.0


# ── SIMPLE Step 6: convergence ────────────────────────────────────
@njit(cache=True)
def _mass_res_jit(u, v, Nx, Ny, dx_arr, dy_arr, rho_field):
    """Global mass conservation residual for variable-density flow.

    Returns max |Q(j) - Q_inlet| / Q_inlet where Q(j) = Σ_i ρ_face·v[i,j]·dx[i]
    is the cross-sectional MASS flux (not volumetric).
    """
    # Inlet mass flux (j=0): rho at face = rho at cell j=0 (boundary)
    Q_in = 0.0
    for i in range(Nx):
        Q_in += rho_field[i, 0] * abs(v[i, 0]) * dx_arr[i]
    if Q_in < 1e-30:
        return 0.0
    Rmax = 0.0
    for j in range(1, Ny + 1):
        Q_j = 0.0
        for i in range(Nx):
            # rho at v-face (i, j): average of cells j-1 and j
            if j < Ny:
                rho_f = 0.5 * (rho_field[i, j - 1] + rho_field[i, j])
            else:
                rho_f = rho_field[i, Ny - 1]
            Q_j += rho_f * v[i, j] * dx_arr[i]
        R = abs(Q_j - Q_in) / Q_in
        if R > Rmax:
            Rmax = R
    return Rmax


# ── Temperature solver (frozen velocity) ──────────────────────────
@njit(cache=True)
def _solve_temp_jit(Tf, Ts, u, v, inlet_mask,
                    Nx, Ny, dx_arr, dy_arr, eps,
                    K_ff, K_ss, h_v, h_v2, rho_cp_f,
                    T_in, T_other,
                    max_iter, tol):
    """
    Iterate fluid + solid temperature to steady state.
    dx_arr: 1D [Nx], dy_arr: 1D [Ny] — non-uniform cell widths.
    """
    for it in range(max_iter):
        max_chg = 0.0

        # ── Fluid temperature ──
        for i in range(Nx):
            for j in range(Ny):
                dxi = dx_arr[i]; dyj = dy_arr[j]
                vol = dxi * dyj
                Df_e = K_ff * dyj / dxi; Df_n = K_ff * dxi / dyj
                hv  = h_v * vol

                # Diffusion coefficients (0 at boundaries = adiabatic)
                dE = Df_e if i < Nx - 1 else 0.0
                dW = Df_e if i > 0      else 0.0
                dN = Df_n if j < Ny - 1 else 0.0
                dS = Df_n if j > 0      else 0.0

                # Convective fluxes (staggered velocities at cell faces)
                Fe = eps * rho_cp_f * u[i + 1, j] * dyj
                Fw = eps * rho_cp_f * u[i, j]     * dyj
                Fn = eps * rho_cp_f * v[i, j + 1] * dxi
                Fs = eps * rho_cp_f * v[i, j]     * dxi

                aE = dE + max(-Fe, 0.0)
                aW = dW + max(Fw, 0.0)
                aN = dN + max(-Fn, 0.0)
                aS = dS + max(Fs, 0.0)

                # Neighbours (adiabatic = zero-grad at boundaries)
                tE = Tf[i + 1, j] if i < Nx - 1 else Tf[i, j]
                tW = Tf[i - 1, j] if i > 0      else Tf[i, j]
                tN = Tf[i, j + 1] if j < Ny - 1 else Tf[i, j]
                if j > 0:
                    tS = Tf[i, j - 1]
                else:
                    tS = T_in if inlet_mask[i] else Tf[i, j]

                aP = aE + aW + aN + aS + hv
                rhs = aE * tE + aW * tW + aN * tN + aS * tS + hv * Ts[i, j]
                # Note: hv and hv2_loc computed per-cell above

                Tf_new = rhs / aP
                chg = abs(Tf_new - Tf[i, j])
                if chg > max_chg:
                    max_chg = chg
                Tf[i, j] = Tf_new

        # ── Solid temperature ──
        for i in range(Nx):
            for j in range(Ny):
                dxi = dx_arr[i]; dyj = dy_arr[j]
                Ds_e_loc = K_ss * dyj / dxi; Ds_n_loc = K_ss * dxi / dyj
                hv_loc = h_v * dxi * dyj
                hv2_loc2 = h_v2 * dxi * dyj

                sE = Ts[i + 1, j] if i < Nx - 1 else Ts[i, j]
                sW = Ts[i - 1, j] if i > 0      else Ts[i, j]
                sN = Ts[i, j + 1] if j < Ny - 1 else Ts[i, j]
                sS = Ts[i, j - 1] if j > 0      else Ts[i, j]

                aP_s = 2.0 * Ds_e_loc + 2.0 * Ds_n_loc + hv_loc + hv2_loc2
                rhs_s = (Ds_e_loc * (sE + sW) + Ds_n_loc * (sN + sS)
                         + hv_loc * Tf[i, j] + hv2_loc2 * T_other)

                Ts_new = rhs_s / aP_s
                chg = abs(Ts_new - Ts[i, j])
                if chg > max_chg:
                    max_chg = chg
                Ts[i, j] = Ts_new

        if max_chg < tol:
            return it + 1

    return max_iter


# ===================================================================
#  Adaptive grid generation
# ===================================================================

def _aligned_grid(N, L, breakpoints):
    """Generate 1D grid with cell edges aligned to breakpoint positions.

    Breakpoints are positions where inlet/outlet meets wall. Cell edges
    are guaranteed to fall exactly on these positions, eliminating the
    velocity discontinuity within any single cell.

    Parameters
    ----------
    N : int — total number of cells
    L : float — domain length [m]
    breakpoints : iterable of float — positions [m] to align cell edges to

    Returns
    -------
    dx_arr : (N,) array — cell widths [m]
    """
    # Build sorted unique segment boundaries [0, bp1, bp2, ..., L]
    eps_b = L * 0.001
    bps = sorted(set([0.0] + [bp for bp in breakpoints
                               if eps_b < bp < L - eps_b] + [L]))

    if len(bps) <= 2:
        return np.full(N, L / N, dtype=np.float64)

    # Segments and their lengths
    segments = [(bps[i], bps[i + 1]) for i in range(len(bps) - 1)]
    lengths = [s[1] - s[0] for s in segments]
    total = sum(lengths)

    # Distribute cells proportional to segment length (min 2 per segment)
    n_cells = [max(2, round(N * l / total)) for l in lengths]
    # Adjust last segment to match total N
    diff = N - sum(n_cells)
    n_cells[-1] += diff
    if n_cells[-1] < 2:
        n_cells[-1] = 2
        n_cells[-2] -= (2 - n_cells[-1])

    # Build dx array: uniform within each segment
    dx_list = []
    for (lo, hi), nc in zip(segments, n_cells):
        seg_dx = (hi - lo) / nc
        dx_list.extend([seg_dx] * nc)

    return np.array(dx_list, dtype=np.float64)


def build_wall_refined_1d(W, N_bulk, n_refine=8, first_cell=0.02e-3, growth=1.8):
    """Build a 1D cross-stream grid with geometric refinement at both walls.

    Layout: [refine_fine → refine_coarse | uniform bulk | refine_coarse → refine_fine]
    Total cells = 2*n_refine + N_bulk.

    Parameters
    ----------
    W : float — domain width (cross-stream extent) [m]
    N_bulk : int — number of uniform bulk cells in the interior
    n_refine : int — refinement layers per wall (default 8)
    first_cell : float — thickness of cell touching the wall [m] (default 0.02 mm)
    growth : float — geometric growth ratio (default 1.8)

    Returns
    -------
    dx_arr : np.ndarray shape (2*n_refine + N_bulk,), sum == W

    Used to resolve Brinkman boundary layer at outer housing walls. See
    vault/reports/2026-04-17-shanghai-dP-error-analysis-CN.md §12.
    """
    refine_sizes = np.array([first_cell * growth**k for k in range(n_refine)], dtype=np.float64)
    total_refine = 2.0 * refine_sizes.sum()
    bulk_width = W - total_refine
    if bulk_width <= 0:
        raise ValueError(
            f"build_wall_refined_1d: refinement {total_refine*1000:.3f}mm exceeds "
            f"domain width {W*1000:.3f}mm. Reduce n_refine or first_cell.")
    bulk_cell = bulk_width / N_bulk
    bulk = np.full(N_bulk, bulk_cell, dtype=np.float64)
    return np.concatenate([refine_sizes, bulk, refine_sizes[::-1]])


# ===================================================================
#  SIMPLESolver class
# ===================================================================

class SIMPLESolver:
    """2D steady SIMPLE on staggered grid for porous-media transition zone.

    Parameters of note
    ------------------
    wall_refine : bool (default True)
        If True, use geometric refinement near cross-stream walls to resolve
        the Brinkman boundary layer (δ_B ≈ 0.05 mm for typical TPMS). Adds
        2*n_wall_refine cells on top of Nx. Automatically disabled when any
        external 2D field (rho, T_field) is passed at init or when inlet/outlet
        is not full-width, because downstream consumers expect matched Nx.

        Production paths (optimizer, validate_shanghai, run_calculation) pass
        wall_refine=False because their outer coupling loops feed SIMPLE outputs
        back to solvers that expect the coarse (pre-refine) Nx. Standalone
        diagnostic / visualisation scripts benefit from the default (True) and
        can see the Brinkman BL directly.

    n_wall_refine : int (default 8)
        Refinement layers per wall.
    wall_first_cell : float (default 0.02e-3 m)
        First cell thickness at the wall (should be < δ_B for full resolution).
    """

    def __init__(self, W, H, Nx, Ny,
                 tpms_type, L_cell_mm, t_mm, eps, r_h,
                 rho, mu, T_in,
                 inlet_lo, inlet_hi, v_inlet,
                 outlet_lo=None, outlet_hi=None,
                 P_ref=0.0, zone_config=None, zone_arrays=None,
                 y_breakpoints=None,
                 fluid_type='ideal_gas',
                 R_gas=287.05,
                 T_field=None,
                 P_ref_abs=None,
                 alpha_rho=0.3,
                 wall_refine=True,
                 n_wall_refine=8,
                 wall_first_cell=0.02e-3,
                 **_legacy_kw):
        # Historical 'closure' kwarg is accepted but ignored; ConstDF-v1 D-F
        # is the only closure since 2026-04-19 f-Re cleanup.
        _legacy_kw.pop('closure', None)

        # Wall refinement (cross-stream, x direction): geometric grid at both
        # side walls to resolve Brinkman boundary layer. Default ON since
        # 2026-04-17. Adds 2*n_wall_refine cells on top of Nx (interpreted as
        # bulk cell count). Disabled if inlet/outlet are not full-width
        # (x_breaks present) or if the user passes wall_refine=False.
        x_breaks = []
        if inlet_lo > W * 0.001:
            x_breaks.append(inlet_lo)
        if inlet_hi < W * 0.999:
            x_breaks.append(inlet_hi)
        if outlet_lo is not None and outlet_lo > W * 0.001:
            x_breaks.append(outlet_lo)
        if outlet_hi is not None and outlet_hi < W * 0.999:
            x_breaks.append(outlet_hi)

        # Wall refinement is only safe when all external 2D fields (rho, T_field)
        # are scalars — otherwise the user's pre-built fields won't match the
        # refined Nx. Auto-disable if any 2D array is passed.
        external_2d = (np.ndim(rho) == 2) or (T_field is not None and np.ndim(T_field) == 2)
        self._wall_refined = False
        if (wall_refine and len(x_breaks) == 0 and n_wall_refine > 0
                and not external_2d):
            try:
                dx_refined = build_wall_refined_1d(
                    W, N_bulk=Nx, n_refine=n_wall_refine,
                    first_cell=wall_first_cell, growth=1.8)
                Nx = Nx + 2 * n_wall_refine   # actual cell count after refinement
                self._wall_refined = True
            except ValueError:
                dx_refined = None  # fall back to uniform
        else:
            dx_refined = None

        # Domain
        self.Nx, self.Ny = Nx, Ny
        self.dx, self.dy = W / Nx, H / Ny  # scalar for backward compat

        # Aligned grid: cell edges at inlet/outlet-wall junctions
        if self._wall_refined and dx_refined is not None:
            self.dx_arr = dx_refined
        else:
            self.dx_arr = _aligned_grid(Nx, W, x_breaks)
        # y-direction: aligned if y_breakpoints provided, else uniform
        self.dy_arr = _aligned_grid(Ny, H, y_breakpoints or [])

        # Porous medium (scalar, kept for temperature solver & backward compat)
        self.eps = eps
        self.r_h = r_h
        self.mu_eff = mu / eps
        # Per-cell porosity (2D #2 fix). Default uniform; caller sets
        # eps_field for zoned. Used in continuity: ∇·(ε·ρ·u) = 0 macroscopic
        # form. Without ε factor, zoned-ε cases miss ∇ε term and accumulate
        # 5-20% per-cell mass divergence.
        self.eps_field = np.full((Nx, Ny), float(eps), dtype=np.float64)

        # Fluid — rho can be scalar or 2D array (Nx, Ny)
        if np.ndim(rho) == 0:
            self.rho_field = np.full((Nx, Ny), float(rho), dtype=np.float64)
        else:
            self.rho_field = np.ascontiguousarray(rho, dtype=np.float64)
        self.rho = float(self.rho_field.mean())  # scalar mean for backwards-compat
        # mu can be scalar or 2D array (Nx, Ny) — 2D supports non-isothermal
        # coupling where viscosity tracks the temperature field.
        if np.ndim(mu) == 0:
            self.mu = float(mu)
        else:
            self.mu = float(np.asarray(mu, dtype=np.float64).mean())

        # Compressible flow: pressure-density coupling
        self.fluid_type = fluid_type
        self.R_gas = R_gas
        self.alpha_rho = alpha_rho
        if P_ref_abs is None:
            self.P_ref_abs = P_atm + P_ref
        else:
            self.P_ref_abs = float(P_ref_abs)
        if T_field is None:
            self.T_field = np.full((Nx, Ny), float(T_in), dtype=np.float64)
        elif np.ndim(T_field) == 0:
            self.T_field = np.full((Nx, Ny), float(T_field), dtype=np.float64)
        else:
            self.T_field = np.ascontiguousarray(T_field, dtype=np.float64)

        # Non-isothermal coupling: 2D viscosity fields that track T_field.
        # Authoritative arrays consumed by D-F sweeps; update via
        # _refresh_mu_from_T whenever T_field changes.
        if np.ndim(mu) == 0:
            self.mu_field = np.full((Nx, Ny), float(mu), dtype=np.float64)
        else:
            self.mu_field = np.ascontiguousarray(mu, dtype=np.float64)
        self._mu_eff_field = self.mu_field / float(eps)

        # ── ConstDF-v1 surrogate: precompute (K, c_F) per row ──
        # Broadcast for uniform geometry; per-row predictions for zone_config
        # graded designs. zone_arrays path doesn't carry L/t/eps metadata, so
        # it falls back to the uniform (scalar) prediction.
        from df_fit.predict import predict_K_cF, predict_K_cF_vec

        if zone_config is not None:
            # Per-row (L, t, eps_f) → batched prediction
            L_row = np.empty(Ny, dtype=np.float64)
            t_row = np.empty(Ny, dtype=np.float64)
            eps_f_row = np.empty(Ny, dtype=np.float64)
            dy_val = H / Ny
            for j in range(Ny):
                yc_frac = (j + 0.5) * dy_val / H
                z = zone_config.zones[-1]
                for zz in zone_config.zones:
                    if zz.y_frac_start <= yc_frac < zz.y_frac_end:
                        z = zz; break
                L_row[j] = z.L_mm
                t_row[j] = z.t_mm
                z_eps = z.props_A['epsilon'] if z.props_A else eps
                eps_f_row[j] = 0.5 * z_eps  # ε_A: per-stream void fraction
            K_vec, cF_vec = predict_K_cF_vec(tpms_type, L_row, t_row, eps_f_row)
            self._K_arr = K_vec.astype(np.float64)
            self._cF_arr = cF_vec.astype(np.float64)
        else:
            # Uniform (or zone_arrays fallback): single (K, c_F), broadcast
            K_val, cF_val = predict_K_cF(
                tpms_type, float(L_cell_mm), float(t_mm), 0.5 * float(eps),
            )
            self._K_arr = np.full(Ny, K_val, dtype=np.float64)
            self._cF_arr = np.full(Ny, cF_val, dtype=np.float64)

        # Inlet — use overlap fraction for exact mass conservation
        self.v_inlet = v_inlet
        x_lo_edge = np.concatenate(([0.0], np.cumsum(self.dx_arr[:-1])))
        x_hi_edge = np.cumsum(self.dx_arr)
        self.inlet_frac = np.clip(
            (np.minimum(x_hi_edge, inlet_hi) - np.maximum(x_lo_edge, inlet_lo)) / self.dx_arr,
            0.0, 1.0)
        # Smooth lateral edges: 4-cell exponential taper at wall/open boundary
        inf_raw = self.inlet_frac.copy()
        for i in range(Nx):
            if inf_raw[i] > 0.99:
                for d in range(1, 5):
                    if (i - d >= 0 and inf_raw[i - d] < 0.01) or \
                       (i + d < Nx and inf_raw[i + d] < 0.01):
                        self.inlet_frac[i] = 1.0 - 0.8 * np.exp(-1.0 * d)
                        break
        self.inlet_mask = self.inlet_frac > 0.01     # boolean for temperature BC

        # Outlet — partial or full-width, with smooth lateral transition
        if outlet_lo is not None and outlet_hi is not None:
            self.outlet_frac = np.clip(
                (np.minimum(x_hi_edge, outlet_hi) - np.maximum(x_lo_edge, outlet_lo)) / self.dx_arr,
                0.0, 1.0).astype(np.float64)
            # Smooth lateral edges: 4-cell exponential taper at wall/open boundary
            of_raw = self.outlet_frac.copy()
            for i in range(Nx):
                if of_raw[i] > 0.99:
                    # Open cell — check distance to nearest wall
                    for d in range(1, 5):
                        if (i - d >= 0 and of_raw[i - d] < 0.01) or \
                           (i + d < Nx and of_raw[i + d] < 0.01):
                            self.outlet_frac[i] = 1.0 - 0.8 * np.exp(-1.0 * d)
                            break
        else:
            self.outlet_frac = np.ones(Nx, dtype=np.float64)

        # Fields
        self.u  = np.zeros((Nx + 1, Ny))
        self.v  = np.zeros((Nx, Ny + 1))
        self.P  = np.full((Nx, Ny), P_ref)
        self.Pp = np.zeros((Nx, Ny))
        self.d_u = np.zeros((Nx + 1, Ny))
        self.d_v = np.zeros((Nx, Ny + 1))

        # Temperature (allocated on demand)
        self.Tf = None
        self.Ts = None

        # (v_inlet is a fixed-velocity BC; density updates do not modify it)

        self._pp_sparsity = None  # lazily built on first solve() call
        self._set_bc()
        self.residuals = []

        # If an explicit non-uniform T_field was passed (not the default T_in
        # broadcast), refresh mu_field / mu_eff_field to match. For the default
        # uniform T_in case the initial scalar-broadcast from L846-848 is
        # already consistent with Sutherland at T_in, but calling it is cheap
        # and guarantees mu_field is in sync with T_field at all times.
        if self.fluid_type == 'ideal_gas':
            self._refresh_mu_from_T()

    def _set_bc(self):
        Nx, Ny = self.Nx, self.Ny
        self.u[0, :] = 0.0;  self.u[Nx, :] = 0.0
        for i in range(Nx):
            self.v[i, 0] = self.v_inlet * self.inlet_frac[i]
            self.v[i, Ny] = self.v[i, Ny - 1]

    def update_rho_field(self, rho_field):
        """Update density field for variable-density coupling iterations."""
        self.rho_field = np.ascontiguousarray(rho_field, dtype=np.float64)
        self.rho = float(self.rho_field.mean())

    def _update_density(self):
        """Update rho_field from pressure field (ideal gas: rho = P_abs / (R*T)).
        Under-relaxed to avoid oscillation. v_inlet stays fixed (velocity-inlet
        BC); mass flux at inlet floats with density. No-op for incompressible.

        Clipping policy (2026-05-06 fix #1):
            Clip the *physical inputs* (P_abs) to the HX operating envelope
            [10 kPa, 1 MPa], then derive ρ from ρ = P/(R·T). Do NOT clip ρ
            directly — that would silently break the ideal-gas relation.
            Previous code clipped ρ ∈ [0.01, 100] kg/m³ which corresponds to
            P~770 Pa or P~78×STP, far outside any real HX state, and could
            decouple ρ from (P,T) during transient iterations.
        """
        if self.fluid_type != 'ideal_gas':
            return
        P_abs = self.P_ref_abs + self.P
        # 2026-05-07: clip widened from [10 kPa, 1 MPa] to [1 kPa, 10 MPa]
        # so SIMPLE transients on high-u cases (u>10 m/s, Forchheimer
        # branch) don't trip the clip and stall outer convergence. See
        # simple_solver_3d.py:_update_density for the full rationale.
        try:
            n_lo = int(np.count_nonzero(P_abs < 1.0e3))
            n_hi = int(np.count_nonzero(P_abs > 10.0e6))
            self._p_clip_hits = (
                getattr(self, '_p_clip_hits', 0) + n_lo + n_hi)
        except Exception:
            pass
        np.clip(P_abs, 1.0e3, 10.0e6, out=P_abs)  # 1 kPa .. 10 MPa
        rho_new = P_abs / (self.R_gas * self.T_field)
        # No ρ clip: ρ derives from (P,T); clipping ρ violates ideal gas law.
        self.rho_field = (self.alpha_rho * rho_new
                          + (1.0 - self.alpha_rho) * self.rho_field)

    def update_T_field(self, T_field):
        """Update temperature field. Also refreshes mu_field / mu_eff_field via
        Sutherland so that non-isothermal D-F coupling stays consistent.

        If wall refinement is on and the incoming T_field has the pre-refine
        shape, we linearly interpolate along the cross-stream axis so the user
        can keep passing fields at their original resolution (common in the
        non-isothermal coupling loop of validate_shanghai.py).
        """
        if np.ndim(T_field) == 0:
            self.T_field = np.full((self.Nx, self.Ny), float(T_field), dtype=np.float64)
        else:
            T_in = np.asarray(T_field, dtype=np.float64)
            if T_in.shape != (self.Nx, self.Ny) and self._wall_refined:
                # Interpolate cross-stream axis from pre-refine Nx to refined Nx
                T_in = self._interp_to_refined_cross(T_in)
            self.T_field = np.ascontiguousarray(T_in, dtype=np.float64)
        if self.fluid_type == 'ideal_gas':
            self._refresh_mu_from_T()

    def _interp_to_refined_cross(self, field_2d):
        """Interpolate a (Nx_coarse, Ny) field onto refined (Nx, Ny) grid along
        cross-stream axis (axis=0). Uses cell-center physical positions."""
        Nx_in, Ny_in = field_2d.shape
        if Ny_in != self.Ny:
            raise ValueError(
                f"field Ny mismatch: got {Ny_in}, expected {self.Ny}")
        # Cell-center positions (pre-refine uniform)
        W_total = self.dx_arr.sum()
        dx_coarse = W_total / Nx_in
        y_coarse = (np.arange(Nx_in) + 0.5) * dx_coarse
        # Refined cell centers
        y_edges = np.concatenate([[0.0], np.cumsum(self.dx_arr)])
        y_refined = 0.5 * (y_edges[:-1] + y_edges[1:])
        # Linear interp per y-column (streamwise index)
        out = np.empty((self.Nx, self.Ny), dtype=np.float64)
        for j in range(self.Ny):
            out[:, j] = np.interp(y_refined, y_coarse, field_2d[:, j])
        return out

    def _refresh_mu_from_T(self):
        """Recompute mu_field and mu_eff_field from self.T_field via Sutherland.
        Called after update_T_field (and once during __init__ for ideal gas)."""
        from .tpms_calc import air_viscosity
        mu_new = air_viscosity(self.T_field).astype(np.float64)
        self.mu_field = np.ascontiguousarray(mu_new)
        # Per-cell μ/ε (zoned ε support); falls back to uniform self.eps.
        eps_eff = self.eps_field if hasattr(self, 'eps_field') else self.eps
        self._mu_eff_field = np.ascontiguousarray(mu_new / eps_eff)

    # ──────────────── velocity solve ──────────────────────────────
    def solve(self, max_iter=3000, tol=1e-6,
              alpha_u=0.7, alpha_p=0.3,
              n_inner=2,
              verbose=True, progress_cb=None):
        """
        Run SIMPLE iterations. PP equation solved by sparse direct solver.

        Returns (converged: bool, iterations: int).
        """
        Nx, Ny = self.Nx, self.Ny
        dx_a, dy_a = self.dx_arr, self.dy_arr

        for it in range(1, max_iter + 1):
            # Effective density for continuity (#2 fix): ε·ρ. Uniform ε →
            # multiplicative constant (no functional change). Zoned ε →
            # captures macroscopic ∇·(ε·ρ·u)=0 form. Momentum unchanged
            # (uses interstitial u with ε encoded in K).
            # Reuse a persistent buffer instead of allocating ε·ρ every outer
            # iteration. Bit-identical to ascontiguousarray(rho*eps): same
            # float64 products, and rho_eps_field is only read (PP solve + mass
            # residual) within this iteration, never retained across iters.
            if getattr(self, '_rho_eps', None) is None or \
                    self._rho_eps.shape != self.rho_field.shape:
                self._rho_eps = np.empty_like(self.rho_field)
            np.multiply(self.rho_field, self.eps_field, out=self._rho_eps)
            rho_eps_field = self._rho_eps
            _sweep_u_jit_df(self.u, self.v, self.P, self.d_u,
                            self.inlet_frac, self.outlet_frac,
                            Nx, Ny, dx_a, dy_a, self.rho_field, self._mu_eff_field,
                            self._K_arr, self._cF_arr, self.mu_field,
                            alpha_u, n_inner)
            _sweep_v_jit_df(self.u, self.v, self.P, self.d_v,
                            self.inlet_frac, self.v_inlet, self.outlet_frac,
                            Nx, Ny, dx_a, dy_a, self.rho_field, self._mu_eff_field,
                            self._K_arr, self._cF_arr, self.mu_field,
                            alpha_u, n_inner)
            if self._pp_sparsity is None:
                self._pp_sparsity = _build_pp_sparsity_pattern(Nx, Ny, self.outlet_frac)
            _solve_pp_sparse_fast(self.Pp, self.u, self.v, self.d_u, self.d_v,
                                  self.outlet_frac,
                                  Nx, Ny, dx_a, dy_a, rho_eps_field,
                                  self._pp_sparsity)
            _correct_jit(self.u, self.v, self.P, self.Pp,
                         self.d_u, self.d_v,
                         self.inlet_frac, self.v_inlet, self.outlet_frac,
                         Nx, Ny, alpha_p, self.rho_field)
            self._update_density()  # compressible: update rho from P

            res = _mass_res_jit(self.u, self.v, Nx, Ny, dx_a, dy_a, rho_eps_field)
            self.residuals.append(res)

            # Live progress hook for UI sparklines — throttled to every
            # 20 iters so a compute with 5000 iters pushes 250 samples max.
            if progress_cb is not None and (it % 20 == 0 or it == 1):
                try:
                    progress_cb(it, float(res))
                except Exception:
                    pass

            if verbose and it % 200 == 0:
                print(f"  iter {it:5d}  |R| = {res:.3e}")
            # Require minimum iterations for pressure field to develop
            # (exact PP gives mass convergence in 1 iter, but P needs more)
            if res < tol and it >= 20:
                if verbose:
                    print(f"  [OK] Converged at iter {it}, |R| = {res:.3e}")
                self._enforce_mass_conservation(verbose=verbose)
                return True, it

        if verbose:
            print(f"  [!!] NOT converged after {max_iter} iters, |R| = {res:.3e}")

        # Post-solve: enforce mass conservation at partial outlet
        self._enforce_mass_conservation(verbose=verbose)

        return False, max_iter

    def get_wall_masked_velocity(self):
        """Return velocity fields with wall-region velocities tapered.
        Matches the 8-cell Brinkman penalty zone at both inlet and outlet."""
        Nx, Ny = self.Nx, self.Ny
        u_masked = self.u.copy()
        v_masked = self.v.copy()

        def _taper(frac_arr, j_range_fn):
            for i in range(Nx):
                if frac_arr[i] < 0.5:
                    for j, wd in j_range_fn(Ny):
                        taper = 1.0 - np.exp(-1.5 * (wd - 1))
                        v_masked[i, j] *= taper
                        v_masked[i, j + 1] *= taper
                        if i < Nx:
                            u_masked[i, j] *= taper
                        if i + 1 <= Nx:
                            u_masked[i + 1, j] *= taper

        # Outlet wall (j near Ny)
        _taper(self.outlet_frac, lambda Ny: [(j, Ny - j) for j in range(max(0, Ny - 8), Ny)])
        # Inlet wall (j near 0)
        _taper(self.inlet_frac, lambda Ny: [(j, j + 1) for j in range(min(8, Ny))])

        return u_masked, v_masked

    def _enforce_mass_conservation(self, verbose=True):
        """Scale outlet velocities to enforce global MASS conservation
        (variable density: ∫ρv dx at outlet = ∫ρv dx at inlet).

        Why this exists (2026-05-06 fix #3 documentation):
            For PARTIAL outlets (outlet_frac < 1 on some cells, e.g. manifold
            geometry in Shanghai HX), the pp-equation pins P=0 only at active
            outlet cells. Closed outlet cells are treated as walls (v=0). After
            the pp solve, global ∫ρv at the outlet face may drift from inlet
            mass flux by O(pp_residual). This post-hoc rescale snaps the global
            balance to machine precision.

            For FULL outlet (outlet_frac == 1 everywhere), pp-equation balances
            mass naturally and `scale ≈ 1.000`. The rescale is a no-op.

            **Diagnostic**: |scale - 1| > 1e-3 indicates pp-equation didn't
            converge mass-wise; it warrants tightening `tol` or adding outlet
            iterations rather than relying on the rescale.

            To disable (e.g. for V&V where post-hoc band-aids are unwanted),
            set `self.enforce_outlet_mass_balance = False` after construction.
        """
        # Allow opt-out (default keeps backward-compatible behaviour)
        if not getattr(self, 'enforce_outlet_mass_balance', True):
            self._last_outlet_mass_scale = 1.0
            return
        Nx, Ny = self.Nx, self.Ny
        inlet_mass = 0.0
        outlet_mass = 0.0
        for i in range(Nx):
            inlet_mass += self.rho_field[i, 0] * self.v[i, 0] * self.dx_arr[i]
            if self.outlet_frac[i] > 0.5:
                outlet_mass += self.rho_field[i, Ny - 1] * self.v[i, Ny] * self.dx_arr[i]
        if abs(outlet_mass) > 1e-15:
            scale = inlet_mass / outlet_mass
            self._last_outlet_mass_scale = float(scale)
            # Diagnostic: warn if rescale magnitude > 0.1% — indicates loose
            # pp-equation convergence, not a healthy "free" mass balance.
            if verbose and abs(scale - 1.0) > 1e-3:
                print(f"  [WARN] outlet mass rescale = {scale:.6f} "
                      f"(|Δ| = {abs(scale-1)*100:.3f}%); "
                      f"pp-equation residual likely loose at outlet face.")
            for i in range(Nx):
                if self.outlet_frac[i] > 0.5:
                    self.v[i, Ny] *= scale
        else:
            self._last_outlet_mass_scale = 1.0

    # ──────────────── temperature solve ───────────────────────────
    def solve_temperature(self, K_ff, K_ss, h_v, rho_cp_f,
                          T_in, T_other=None, h_v2=0.0,
                          max_iter=5000, tol=1e-4, verbose=True):
        """
        Solve LTNE temperature with frozen velocity field.

        Parameters
        ----------
        K_ff      : fluid effective conductivity [W/(m K)]   (= eps * k_f)
        K_ss      : solid effective conductivity [W/(m K)]   (= (1-eps) * k_s)
        h_v       : volumetric HTC, fluid <-> solid [W/(m3 K)]  (= H_sf * A_0)
        rho_cp_f  : fluid volumetric heat capacity [J/(m3 K)]
        T_in      : fluid inlet temperature [K]
        T_other   : other-fluid temperature [K] (scalar).
                    If None, solid is adiabatic (h_v2 forced to 0).
        h_v2      : volumetric HTC, other-fluid <-> solid [W/(m3 K)]
        """
        Nx, Ny = self.Nx, self.Ny
        if T_other is None:
            T_other = T_in
            h_v2 = 0.0

        # Initialise temperature fields
        self.Tf = np.full((Nx, Ny), T_in)
        self.Ts = np.full((Nx, Ny), 0.5 * (T_in + T_other))

        iters = _solve_temp_jit(
            self.Tf, self.Ts, self.u, self.v, self.inlet_mask,
            Nx, Ny, self.dx_arr, self.dy_arr, self.eps,
            K_ff, K_ss, h_v, h_v2, rho_cp_f,
            T_in, T_other, max_iter, tol)

        if verbose:
            tag = "[OK]" if iters < max_iter else "[!!]"
            print(f"  {tag} Temperature: {iters} iters, "
                  f"Tf=[{self.Tf.min():.2f}, {self.Tf.max():.2f}], "
                  f"Ts=[{self.Ts.min():.2f}, {self.Ts.max():.2f}]")
        return iters < max_iter, iters

    # ──────────────── output for coupling ─────────────────────────
    def _check_uniform(self, j, threshold):
        """Check if cross-section j has uniform flow.

        Two conditions must BOTH be met:
        1. Main flow (v) uniformity:  std(v) / mean(v) < threshold
        2. Transverse flow (u) negligible: mean(|u|) / mean(v) < threshold

        References:
          - Mueller & Chiou (1988): 5% CV = significant maldistribution
          - Lalot et al. (1999): relative std dev for HX flow distribution
          - Default threshold 5% is standard for heat exchanger applications
        """
        Nx, Ny = self.Nx, self.Ny
        v_row = self.v[:, j]
        v_mean = v_row.mean()
        if v_mean < 1e-10:
            return False

        # Condition 1: main flow uniformity (coefficient of variation)
        cv_v = v_row.std() / v_mean
        if cv_v >= threshold:
            return False

        # Condition 2: transverse velocity negligible
        # u lives on x-faces: u[0..Nx, j]. Average |u| at internal faces.
        u_at_j = self.u[1:Nx, j]   # internal x-face velocities at row j
        u_ratio = np.abs(u_at_j).mean() / v_mean
        if u_ratio >= threshold:
            return False

        return True

    def detect_uniform_boundary(self, threshold=0.045):
        """Find the first cross-section (from pipe side) where flow is uniform.

        Scans from j=1 (near pipe) toward j=Ny-1 (far from pipe).
        Checks both v-uniformity AND u-negligibility.

        Parameters
        ----------
        threshold : float, default 0.05 (5%, standard for HX applications)

        Returns
        -------
        j_uniform : int   (row index where flow becomes uniform, or Ny-1)
        depth     : float (transition zone depth in metres)
        """
        for j in range(1, self.Ny):
            if self._check_uniform(j, threshold):
                return j, j * self.dy
        return self.Ny - 1, (self.Ny - 1) * self.dy

    def detect_nonuniform_boundary(self, threshold=0.045):
        """Scan from the UNIFORM side (top, j=Ny-1) toward the pipe (j=0).

        Find the first cross-section that is NOT uniform (where converging
        effects begin). Uses same dual check as detect_uniform_boundary.

        Returns
        -------
        j_start : int   (last uniform row, counting from top)
        depth   : float (outlet transition zone depth in metres)
        """
        for j in range(self.Ny - 1, 0, -1):
            if not self._check_uniform(j, threshold):
                depth = (self.Ny - 1 - j) * self.dy
                return j + 1, depth
        return 0, (self.Ny - 1) * self.dy

    def get_profile_at(self, j_row):
        """Extract velocity + temperature profiles at a specific row j."""
        Nx, Ny = self.Nx, self.Ny
        j = min(max(j_row, 0), Ny - 1)
        out = {
            'v_exit': self.v[:, j].copy(),
            'u_exit': self.u[1:Nx, j].copy(),
            # cell-center / face x-coords from per-cell dx_arr (correct on
            # non-uniform grids; == arange*dx on uniform grids).
            'x_v':   np.cumsum(self.dx_arr) - 0.5 * self.dx_arr,
            'x_u':   np.cumsum(self.dx_arr)[:Nx - 1],
            'j_row':  j,
            'depth':  float(np.sum(self.dy_arr[:j])),
        }
        if self.Tf is not None:
            out['Tf_exit'] = self.Tf[:, j].copy()
            out['Ts_exit'] = self.Ts[:, j].copy()
        return out

    def get_exit_profile(self):
        """Velocity + temperature at exit (top boundary) for uniform-zone BC."""
        Nx, Ny = self.Nx, self.Ny
        out = {
            'v_exit': self.v[:, Ny - 1].copy(),
            'u_exit': self.u[1:Nx, Ny - 1].copy(),
            'x_v':   np.cumsum(self.dx_arr) - 0.5 * self.dx_arr,
            'x_u':   np.cumsum(self.dx_arr)[:Nx - 1],
        }
        if self.Tf is not None:
            out['Tf_exit'] = self.Tf[:, Ny - 1].copy()
            out['Ts_exit'] = self.Ts[:, Ny - 1].copy()
        return out

    def get_fields_trimmed(self, j_start=0, j_end=None):
        """Return 2D fields trimmed to rows [j_start, j_end).

        Useful for extracting just the transition zone portion for plotting.
        """
        if j_end is None:
            j_end = self.Ny
        out = {'v': self.v[:, j_start:j_end+1].copy(),
               'u': self.u[:, j_start:j_end].copy(),
               'P': self.P[:, j_start:j_end].copy()}
        if self.Tf is not None:
            out['Tf'] = self.Tf[:, j_start:j_end].copy()
            out['Ts'] = self.Ts[:, j_start:j_end].copy()
        return out

    @staticmethod
    def solve_outlet_transition(W, H_search, Nx, Ny,
                                tpms_type, L_cell_mm, t_mm, eps, r_h,
                                rho, mu, T_uni_exit,
                                pipe_lo, pipe_hi, u_exit,
                                K_ff, K_ss, h_v, rho_cp_f,
                                T_other=None, h_v2=0.0,
                                threshold=0.02):
        """Solve outlet transition zone (uniform flow → converging to pipe).

        Uses the flip trick: solve bottom-inlet SIMPLE (spreading flow),
        then flip the domain vertically. The velocity field is approximately
        correct (porous media ≈ reversible). Temperature is solved with
        the flipped velocity and proper outlet BCs.

        Returns
        -------
        dict with keys: depth, dP, j_boundary, Tf_field, Ts_field, v_field, solver
        """
        # Step 1: Solve spreading flow (pipe at bottom) on oversized domain
        s = SIMPLESolver(W, H_search, Nx, Ny,
                         tpms_type, L_cell_mm, t_mm, eps, r_h,
                         rho, mu, T_uni_exit,
                         pipe_lo, pipe_hi, u_exit)
        s.solve(max_iter=3000, tol=1e-6, verbose=False)

        # Step 2: Detect where spreading flow becomes uniform
        j_uni, depth = s.detect_uniform_boundary(threshold)

        # Step 3: Solve temperature with correct BCs
        # The "inlet" of the outlet trans zone is the uniform zone exit (T_uni_exit)
        # which is already set as T_in for this solver.
        s.solve_temperature(K_ff, K_ss, h_v, rho_cp_f,
                            T_in=T_uni_exit, T_other=T_other,
                            h_v2=h_v2, verbose=False)

        # Step 4: Detect the outlet boundary from the uniform side
        j_start, depth_out = s.detect_nonuniform_boundary(threshold)

        # Pressure drop in the transition zone portion only
        if j_uni > 0:
            dP = abs(s.P[:, :j_uni+1].max() - s.P[:, :j_uni+1].min())
        else:
            dP = 0.0

        return {
            'depth': depth_out,
            'depth_spreading': depth,   # from inlet-like detection
            'dP': dP,
            'j_boundary': j_start,
            'solver': s,
        }

    def mass_flow_in(self):
        # Weight by per-cell dx_arr (== scalar dx on uniform grids).
        return self.rho * np.sum(self.v[self.inlet_mask, 0]
                                 * self.dx_arr[self.inlet_mask])

    def mass_flow_out(self):
        return self.rho * np.sum(self.v[:, self.Ny] * self.dx_arr)


# ===================================================================
#  Convenience function
# ===================================================================

def solve_transition_zone(W, H, Nx, Ny,
                          tpms_type, L_cell_mm, t_mm, eps, r_h,
                          T_in, P_in,
                          inlet_lo, inlet_hi, v_inlet,
                          # temperature params (optional)
                          K_ff=None, K_ss=None, h_v=None,
                          rho_cp_f=None, T_other=None, h_v2=0.0,
                          **kwargs):
    """
    One-call interface: velocity solve + optional temperature solve.
    """
    rho = air_density(T_in, P_in)
    mu  = air_viscosity(T_in)

    solver = SIMPLESolver(W, H, Nx, Ny,
                          tpms_type, L_cell_mm, t_mm, eps, r_h,
                          rho, mu, T_in,
                          inlet_lo, inlet_hi, v_inlet)

    ok_v, it_v = solver.solve(**{k: v for k, v in kwargs.items()
                                 if k in ('max_iter', 'tol', 'alpha_u',
                                          'alpha_p', 'n_inner', 'verbose')})

    ok_t = None
    if K_ff is not None:
        ok_t, _ = solver.solve_temperature(
            K_ff, K_ss, h_v, rho_cp_f, T_in,
            T_other=T_other, h_v2=h_v2,
            verbose=kwargs.get('verbose', True))

    return {
        'u': solver.u.copy(), 'v': solver.v.copy(), 'P': solver.P.copy(),
        'Tf': solver.Tf.copy() if solver.Tf is not None else None,
        'Ts': solver.Ts.copy() if solver.Ts is not None else None,
        'converged_v': ok_v, 'converged_T': ok_t,
        'iterations_v': it_v,
        'residuals': solver.residuals,
        'exit': solver.get_exit_profile(),
        'solver': solver,
    }


# ===================================================================
#  Verification
# ===================================================================

if __name__ == '__main__':
    import time
    import warnings; warnings.filterwarnings('ignore')
    from .tpms_calc import compute as tpms_compute

    tpms = 'Diamond';  L_mm = 6.0;  t_mm = 0.4
    props = tpms_compute(tpms, L_mm, t_mm, 3.0, 300.0, 101325.0, 17.0)
    eps = props['epsilon'];  r_h = props['D_h'] / 2.0

    W, H = 0.03, 0.02;  Nx, Ny = 30, 20;  v_in = 3.0

    # ── Test 1: full-width inlet (uniform flow check) ──
    print("=" * 60)
    print("Test 1: full-width inlet")
    print("=" * 60)
    rho = air_density(300.0, 101325.0);  mu = air_viscosity(300.0)
    s = SIMPLESolver(W, H, Nx, Ny,
                     tpms, L_mm, t_mm, eps, r_h, rho, mu, 300.0,
                     0.0, W, v_in)

    print("  (first call includes Numba JIT compilation...)")
    t0 = time.time()
    ok, it = s.solve(max_iter=500, tol=1e-7, verbose=False)
    t1 = time.time()
    v_int = s.v[:, 1:-1];  u_int = s.u[1:-1, :]
    print(f"  time = {t1-t0:.2f}s  (includes JIT)")
    print(f"  converged={ok}, iters={it}")
    print(f"  v: mean={v_int.mean():.4f} std={v_int.std():.2e} (expect {v_in})")
    print(f"  u: mean={u_int.mean():.2e} (expect 0)")

    # Re-run to measure pure execution time
    s2 = SIMPLESolver(W, H, Nx, Ny,
                      tpms, L_mm, t_mm, eps, r_h, rho, mu, 300.0,
                      0.0, W, v_in)
    t0 = time.time()
    s2.solve(max_iter=500, tol=1e-7, verbose=False)
    t1 = time.time()
    print(f"  pure solve time (no JIT) = {t1-t0:.2f}s")
    print()

    # ── Test 2: half-width inlet + temperature ──
    print("=" * 60)
    print("Test 2: half-width inlet + temperature (T_other=400K)")
    print("=" * 60)
    inlet_lo = 0.25 * W;  inlet_hi = 0.75 * W
    s3 = SIMPLESolver(W, H, Nx, Ny,
                      tpms, L_mm, t_mm, eps, r_h, rho, mu, 300.0,
                      inlet_lo, inlet_hi, v_in)
    t0 = time.time()
    ok_v, it_v = s3.solve(max_iter=3000, tol=1e-6, verbose=False)
    t1 = time.time()
    print(f"  Velocity: converged={ok_v}, iters={it_v}, time={t1-t0:.2f}s")
    print(f"  m_in={s3.mass_flow_in():.6f}  m_out={s3.mass_flow_out():.6f}")

    # Temperature: Fluid B enters at 300K, Fluid A (other side) at 400K
    K_ff = eps * props['k_f']
    K_ss = (1.0 - eps) * 17.0
    A_0  = props['A_0']
    H_sf = props['H_sf']      # face HTC [W/(m2 K)]
    h_v  = H_sf * A_0         # volumetric HTC [W/(m3 K)]
    cp_air = 1005.0
    rho_cp = rho * cp_air

    t0 = time.time()
    ok_t, it_t = s3.solve_temperature(
        K_ff, K_ss, h_v, rho_cp,
        T_in=300.0, T_other=400.0, h_v2=h_v * 0.5)
    t1 = time.time()
    print(f"  Temperature: time={t1-t0:.2f}s")

    ex = s3.get_exit_profile()
    print(f"  Exit v: mean={ex['v_exit'].mean():.3f}")
    if 'Tf_exit' in ex:
        print(f"  Exit Tf: mean={ex['Tf_exit'].mean():.2f}K "
              f"(entered at 300K, other=400K)")
    print("=" * 60)


def _warmup_jit():
    """Pre-compile _assemble_pp_data_jit on import.

    Builds a tiny 4x4 sparsity pattern and runs one assembly to touch the
    compiled path. Failures are silently caught — warmup is best-effort.
    """
    try:
        import numpy as _np
        _Nx, _Ny = 4, 4
        _u = _np.zeros((_Nx + 1, _Ny), dtype=_np.float64)
        _v = _np.zeros((_Nx, _Ny + 1), dtype=_np.float64)
        _d_u = _np.full((_Nx + 1, _Ny), 0.05, dtype=_np.float64)
        _d_v = _np.full((_Nx, _Ny + 1), 0.05, dtype=_np.float64)
        _rho = _np.full((_Nx, _Ny), 1.0, dtype=_np.float64)
        _outlet = _np.zeros(_Nx, dtype=_np.float64)
        _outlet[_Nx // 2] = 1.0
        _dx = _np.full(_Nx, 0.01, dtype=_np.float64)
        _dy = _np.full(_Ny, 0.01, dtype=_np.float64)
        _pat = _build_pp_sparsity_pattern(_Nx, _Ny, _outlet)
        _data = _np.zeros(_pat['nnz'], dtype=_np.float64)
        _rhs = _np.zeros(_Nx * _Ny, dtype=_np.float64)
        _assemble_pp_data_jit(_data, _rhs, _u, _v, _d_u, _d_v, _outlet,
                              _Nx, _Ny, _dx, _dy, _rho,
                              _pat['cell_base'], _pat['cell_kind'])
    except Exception:
        pass  # warmup is best-effort; never block import


_warmup_jit()
