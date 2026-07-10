"""2D SIMPLE numba kernels + pressure-Poisson infra, moved verbatim from simple_solver.py (openspec split-solver-kernels, 2026-07-03); bit-identical."""

import numpy as np
from numba import njit
from ._kernels_2d import minmod


# ===================================================================
#  Numba kernels
# ===================================================================

# ── SOU deferred correction for momentum (minmod limiter) ──────────
# N2 (audit 2026-06-28): the momentum SOU deferred correction must scale the
# west/south-face limiter by the WEST/SOUTH-face flux (Fw/Fs) and the
# east/north-face limiter by the EAST/NORTH-face flux (Fe/Fn) — the SAME face
# fluxes the first-order aE/aW/aN/aS coefficients already use. The legacy form
# scaled BOTH faces by the single cell-east (or north) flux, so at a shared face
# cell i applied Fe(i)·φ_e while cell i+1 applied Fe(i+1)·φ_w ≠ Fw(i+1)=Fe(i):
# the deferred correction did not telescope and injected a spurious momentum
# source wherever ρ·u varied between neighbours (the exact defect already fixed
# in ltne_energy._sou_corr_x/_y). For a uniform flux field (Fe==Fw) this reduces
# to the legacy `0.5*F*(phi_w - phi_e)`, but on a developing / variable-ρ flow it
# differs at truncation level — an intentional 2D-golden re-baseline.
@njit(cache=True)
def _sou_corr_u_x(u, i, j, Nx, Fe, Fw):
    """SOU deferred correction for u-momentum in x-direction.
    u is on x-faces: u[i,j] at face between cells i-1 and i.
    Fe/Fw = rho*u_face*dy are the east/west-face convective fluxes for this
    u-cell (the same fluxes that build aE/aW).
    """
    ue_loc = 0.5 * (u[i, j] + u[min(i + 1, Nx), j])
    if ue_loc >= 0:
        phi_w = 0.0
        if i > 2:
            gu = u[i - 1, j] - u[i - 2, j]
            gd = u[i, j] - u[i - 1, j]
            phi_w = minmod(gu, gd)
        phi_e = 0.0
        if i + 1 < Nx and i > 1:
            gu = u[i, j] - u[i - 1, j]
            gd = u[i + 1, j] - u[i, j]
            phi_e = minmod(gu, gd)
        return 0.5 * (Fw * phi_w - Fe * phi_e)
    else:
        phi_e = 0.0
        if i + 2 <= Nx:
            gu = u[i + 1, j] - u[min(i + 2, Nx), j]
            gd = u[i, j] - u[i + 1, j]
            phi_e = minmod(gu, gd)
        phi_w = 0.0
        if i > 1 and i + 1 <= Nx:
            gu = u[i, j] - u[i + 1, j]
            gd = u[i - 1, j] - u[i, j]
            phi_w = minmod(gu, gd)
        return 0.5 * (Fe * phi_e - Fw * phi_w)


@njit(cache=True)
def _sou_corr_u_y(u, i, j, Ny, Fn, Fs):
    """SOU deferred correction for u-momentum in y-direction."""
    if Fn >= 0:
        phi_s = 0.0
        if j > 1:
            gu = u[i, j - 1] - u[i, j - 2]
            gd = u[i, j] - u[i, j - 1]
            phi_s = minmod(gu, gd)
        phi_n = 0.0
        if j < Ny - 1 and j > 0:
            gu = u[i, j] - u[i, j - 1]
            gd = u[i, j + 1] - u[i, j]
            phi_n = minmod(gu, gd)
        return 0.5 * (Fs * phi_s - Fn * phi_n)
    else:
        phi_n = 0.0
        if j < Ny - 2:
            gu = u[i, j + 1] - u[i, j + 2]
            gd = u[i, j] - u[i, j + 1]
            phi_n = minmod(gu, gd)
        phi_s = 0.0
        if j > 0 and j < Ny - 1:
            gu = u[i, j] - u[i, j + 1]
            gd = u[i, j - 1] - u[i, j]
            phi_s = minmod(gu, gd)
        return 0.5 * (Fn * phi_n - Fs * phi_s)


@njit(cache=True)
def _sou_corr_v_x(v, i, j, Nx, Fe, Fw):
    """SOU deferred correction for v-momentum in x-direction."""
    if Fe >= 0:
        phi_w = 0.0
        if i > 1:
            gu = v[i - 1, j] - v[i - 2, j]
            gd = v[i, j] - v[i - 1, j]
            phi_w = minmod(gu, gd)
        phi_e = 0.0
        if i < Nx - 1 and i > 0:
            gu = v[i, j] - v[i - 1, j]
            gd = v[i + 1, j] - v[i, j]
            phi_e = minmod(gu, gd)
        return 0.5 * (Fw * phi_w - Fe * phi_e)
    else:
        phi_e = 0.0
        if i < Nx - 2:
            gu = v[i + 1, j] - v[i + 2, j]
            gd = v[i, j] - v[i + 1, j]
            phi_e = minmod(gu, gd)
        phi_w = 0.0
        if i > 0 and i < Nx - 1:
            gu = v[i, j] - v[i + 1, j]
            gd = v[i - 1, j] - v[i, j]
            phi_w = minmod(gu, gd)
        return 0.5 * (Fe * phi_e - Fw * phi_w)


@njit(cache=True)
def _sou_corr_v_y(v, i, j, Ny, Fn, Fs):
    """SOU deferred correction for v-momentum in y-direction.
    v is on y-faces: v[i,j] at face between cells j-1 and j.
    """
    vn_loc = 0.5 * (v[i, j] + v[i, min(j + 1, Ny)])
    if vn_loc >= 0:
        phi_s = 0.0
        if j > 2:
            gu = v[i, j - 1] - v[i, j - 2]
            gd = v[i, j] - v[i, j - 1]
            phi_s = minmod(gu, gd)
        phi_n = 0.0
        if j + 1 <= Ny and j > 1:
            gu = v[i, j] - v[i, j - 1]
            gd = v[i, min(j + 1, Ny)] - v[i, j]
            phi_n = minmod(gu, gd)
        return 0.5 * (Fs * phi_s - Fn * phi_n)
    else:
        phi_n = 0.0
        if j + 2 <= Ny:
            gu = v[i, j + 1] - v[i, min(j + 2, Ny)]
            gd = v[i, j] - v[i, j + 1]
            phi_n = minmod(gu, gd)
        phi_s = 0.0
        if j > 1 and j + 1 <= Ny:
            gu = v[i, j] - v[i, j + 1]
            gd = v[i, j - 1] - v[i, j]
            phi_s = minmod(gu, gd)
        return 0.5 * (Fn * phi_n - Fs * phi_s)


# Brinkman wall-penalty coefficients (P1b-c, B6 naming). Within 8 cells of a
# blocked inlet/outlet face the momentum source gains
# `BASE · frac⁴ · exp(−EFOLD·(dist−1)) · aP_natural` — a grid-invariant
# no-slip layer. EFOLD=1.5 → the penalty e-folds over 1.5 cells (fits the
# Brinkman layer δ_B ≈ 0.05 mm at production grids); BASE=1e3 dominates aP
# without losing float64 precision at any tested resolution. Captured as
# compile-time constants by the Numba kernels here and in simple_solver_3d.
_WALL_PENALTY_BASE = 1e3
_WALL_PENALTY_EFOLD = 1.5


@njit(cache=True)
def _porous_src_df(umag, K, cF, mu, rho):
    """Linearised porous resistance coefficient [kg/(m3 s)] for ConstDF-v1.

    Darcy-Forchheimer closure: Sp * u = (mu/K) * u + rho * c_F * |u| * u.
    K and c_F are geometry-level constants from the DF surrogate
    (df_surrogate/predict.py:predict_K_cF), default backend "gamma_df"
    (switched rbf → gamma_df 2026-06-12; RBF is opt-in via env
    TPMSHX_DF_METHOD=rbf). Caller provides K, cF per-cell (2026-07-10
    lateral-K: kernels now consume 2D (Nx, Ny) fields; a laterally-uniform
    field reproduces the historical per-row behaviour bit-identically).
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
                    K_arr, cF_arr, mu_field, eps_field,
                    alpha_u, n_sweeps):
    """D-F variant of _sweep_u_jit: porous source uses (K, c_F) per row from
    the ConstDF-v1 surrogate, no phi_arr correction (MLP covers training range
    natively). mu_eff_field and mu_field are 2D (Nx, Ny) arrays so that
    viscosity tracks the temperature field in non-isothermal compressible flow.

    M2 (2026-07-09, VANS ∇ε): momentum discretizes the ε-DIVIDED volume-
    averaged form  (1/ε_P)∇·(ε ρ u u) = −∇p + (1/ε_P)∇·(μ ∇u) + f_DF —
    every flux face carries the ratio r_f = ε_f / ε_CV multiplying both the
    convective flux F_f and the diffusion conductance D_f. The pressure term
    needs NO factor in this form (−ε∇p/ε cancels exactly) and the DF drag
    stays untouched (experiment-anchored calibration absorbed its volume
    convention). Uniform ε → all r ≡ 1.0 bit-exactly (arithmetic means of
    equal values are exact; ×1.0 is an IEEE no-op), so the pre-M2 fields are
    reproduced bit-identically — that is the regression gate.
    """
    for _ in range(n_sweeps):
        for i in range(1, Nx):
            for j in range(Ny):
                dxi = 0.5 * (dx_arr[i - 1] + dx_arr[min(i, Nx - 1)])
                dyj = dy_arr[j]
                vol = dxi * dyj

                il_r = max(i - 1, 0); ir_r = min(i, Nx - 1)
                mu_e = 0.5 * (mu_eff_field[il_r, j] + mu_eff_field[ir_r, j])

                # M2: ε at the u-CV centre + the four flux-face ratios.
                # u-node sits on the x-interface between cells il_r/ir_r, so
                # its E/W flux faces are the CELL CENTRES; N/S faces are the
                # 4-cell corners.
                eps_u = 0.5 * (eps_field[il_r, j] + eps_field[ir_r, j])
                r_e = eps_field[ir_r, j] / eps_u
                r_w = eps_field[il_r, j] / eps_u
                r_n = (0.25 * (eps_field[il_r, j] + eps_field[ir_r, j]
                               + eps_field[il_r, j + 1]
                               + eps_field[ir_r, j + 1]) / eps_u
                       if j < Ny - 1 else 1.0)
                r_s = (0.25 * (eps_field[il_r, j] + eps_field[ir_r, j]
                               + eps_field[il_r, j - 1]
                               + eps_field[ir_r, j - 1]) / eps_u
                       if j > 0 else 1.0)

                # N4 (2026-07-07): diffusion conductances use the ACTUAL
                # neighbour-node distance, not the CV width. u-nodes sit on
                # x-interfaces: E neighbour at dx[i], W at dx[i-1]; cross-
                # stream neighbours at 0.5*(dy[j]+dy[j±1]). Uniform grids
                # reduce to the old dxi/dyj form bit-identically.
                De = r_e * mu_e * dyj / dx_arr[ir_r]
                Dw = r_w * mu_e * dyj / dx_arr[il_r]
                Dn = (r_n * mu_e * dxi / (0.5 * (dy_arr[j] + dy_arr[j + 1]))
                      if j < Ny - 1 else 0.0)
                Ds = (r_s * mu_e * dxi / (0.5 * (dy_arr[j] + dy_arr[j - 1]))
                      if j > 0 else 0.0)

                uE = u[i + 1, j] if i + 1 < Nx else 0.0
                uW = u[i - 1, j] if i > 1 else 0.0
                uN = u[i, j + 1] if j < Ny - 1 else u[i, j]
                uS = u[i, j - 1] if j > 0 else 0.0

                ue = 0.5 * (u[i, j] + u[min(i + 1, Nx), j])
                uw = 0.5 * (u[max(i - 1, 0), j] + u[i, j])
                il = max(i - 1, 0); ir = min(i, Nx - 1)
                vn = 0.5 * (v[il, j + 1] + v[ir, j + 1]) if j < Ny - 1 else 0.0
                vs = 0.5 * (v[il, j] + v[ir, j])

                rho_loc = 0.5 * (rho_field[il_r, j] + rho_field[ir_r, j])
                mu_loc  = 0.5 * (mu_field[il_r, j] + mu_field[ir_r, j])

                Fe = r_e * rho_loc * ue * dyj; Fw = r_w * rho_loc * uw * dyj
                Fn = r_n * rho_loc * vn * dxi; Fs = r_s * rho_loc * vs * dxi

                aE = De + max(-Fe, 0.0)
                aW = Dw + max(Fw, 0.0)
                aN = Dn + max(-Fn, 0.0)
                aS = Ds + max(Fs, 0.0)

                umag = _umag_u(u, v, i, j, Nx, Ny)
                # 2026-07-10 lateral-K: K/cF are 2D (Nx, Ny) SIMPLE-coord
                # fields. u-node straddles cells il_r/ir_r laterally → arith
                # mean. Laterally-uniform fields give 0.5*(a+a) = a exactly
                # (IEEE), reproducing the old per-row K_arr[j] bit-identically.
                K_u = 0.5 * (K_arr[il_r, j] + K_arr[ir_r, j])
                cF_u = 0.5 * (cF_arr[il_r, j] + cF_arr[ir_r, j])
                Sp = _porous_src_df(umag, K_u, cF_u, mu_loc, rho_loc) * vol

                # Brinkman penalty: grid-invariant via aP_natural (matches 3D
                # convention in simple_solver_3d.py). Old form `1e8*...*vol`
                # scaled with cell volume and was grid-dependent.
                aP_nat = aE + aW + aN + aS
                il_u = max(i - 1, 0); ir_u = min(i, Nx - 1)
                wall_out = 1.0 - 0.5 * (outlet_frac[il_u] + outlet_frac[ir_u])
                if wall_out > 0.01 and j >= Ny - 8:
                    wall_dist = Ny - j
                    Sp += _WALL_PENALTY_BASE * wall_out**4 * np.exp(
                        -_WALL_PENALTY_EFOLD * (wall_dist - 1)) * aP_nat
                wall_in = 1.0 - 0.5 * (inlet_frac[il_u] + inlet_frac[ir_u])
                if wall_in > 0.01 and j < 8:
                    wall_dist = j + 1
                    Sp += _WALL_PENALTY_BASE * wall_in**4 * np.exp(
                        -_WALL_PENALTY_EFOLD * (wall_dist - 1)) * aP_nat

                p_src = (P[i - 1, j] - P[i, j]) * dyj
                sou = (_sou_corr_u_x(u, i, j, Nx, Fe, Fw)
                     + _sou_corr_u_y(u, i, j, Ny, Fn, Fs))
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
def _sweep_v_jit_df(u, v, P, d_v, inlet_frac, v_inlet_field, outlet_frac,
                    Nx, Ny, dx_arr, dy_arr, rho_field, mu_eff_field,
                    K_arr, cF_arr, mu_field, eps_field,
                    alpha_u, n_sweeps):
    """D-F variant of _sweep_v_jit, mirrors _sweep_u_jit_df changes.
    mu_eff_field and mu_field are 2D (Nx, Ny) for non-isothermal coupling.
    M2 (2026-07-09): VANS ε-ratio factors — see _sweep_u_jit_df docstring;
    v-node sits on the y-interface between cells jb/jt, so N/S flux faces
    are the cell centres and E/W faces are the 4-cell corners. Wall
    branches (no-slip conductance) carry no ratio: the wall face has no
    ε gradient across it (zero-normal-gradient ε at the housing)."""
    for _ in range(n_sweeps):
        for i in range(Nx):
            for j in range(1, Ny):
                jc = min(j, Ny - 1)
                dxi = dx_arr[i]
                dyj = 0.5 * (dy_arr[j - 1] + dy_arr[min(j, Ny - 1)])
                vol = dxi * dyj

                jb = max(j - 1, 0); jt = min(j, Ny - 1)
                mu_e = 0.5 * (mu_eff_field[i, jb] + mu_eff_field[i, jt])

                # M2: ε at the v-CV centre + flux-face ratios (uniform → 1.0
                # bit-exactly).
                eps_v = 0.5 * (eps_field[i, jb] + eps_field[i, jt])
                r_n = eps_field[i, jt] / eps_v
                r_s = eps_field[i, jb] / eps_v
                r_e = (0.25 * (eps_field[i, jb] + eps_field[i, jt]
                               + eps_field[i + 1, jb] + eps_field[i + 1, jt])
                       / eps_v if i < Nx - 1 else 1.0)
                r_w = (0.25 * (eps_field[i, jb] + eps_field[i, jt]
                               + eps_field[i - 1, jb] + eps_field[i - 1, jt])
                       / eps_v if i > 0 else 1.0)

                # No-slip at side walls (x=0, x=W): tangential velocity v=0 at
                # wall. Distance from cell centre to wall = dxi/2, so the wall
                # diffusion coefficient is mu_e * dyj / (0.5*dxi).
                # Previously free-slip (De=0 at i=Nx-1, Dw=0 at i=0); corrected
                # 2026-04-17 to match physical outer-housing walls in TPMS heat
                # exchangers. For symmetry/periodic boundaries, revert to 0/0.
                # N4 (2026-07-07): interior conductances use the ACTUAL
                # neighbour-node distances — E/W v-neighbours sit at
                # 0.5*(dx[i]+dx[i±1]), N/S at dy[j]/dy[j-1] (v-nodes on
                # y-interfaces). Uniform grids reduce bit-identically.
                if i < Nx - 1:
                    vE = v[i + 1, j]
                    De = r_e * mu_e * dyj / (0.5 * (dx_arr[i] + dx_arr[i + 1]))
                else:
                    vE = 0.0; De = 2.0 * mu_e * dyj / dxi   # east wall (no-slip)
                if i > 0:
                    vW = v[i - 1, j]
                    Dw = r_w * mu_e * dyj / (0.5 * (dx_arr[i] + dx_arr[i - 1]))
                else:
                    vW = 0.0; Dw = 2.0 * mu_e * dyj / dxi   # west wall (no-slip)
                vN = v[i, j + 1] if j < Ny - 1 else v[i, j]
                vS = v[i, j - 1]

                Dn = r_n * mu_e * dxi / dy_arr[jt] if j < Ny - 1 else 0.0
                Ds = r_s * mu_e * dxi / dy_arr[jb]

                ue = 0.5 * (u[i + 1, jb] + u[i + 1, jt]) if i < Nx - 1 else 0.0
                uw = 0.5 * (u[i, jb] + u[i, jt]) if i > 0 else 0.0
                vn = 0.5 * (v[i, j] + v[i, min(j + 1, Ny)])
                vs = 0.5 * (v[i, max(j - 1, 0)] + v[i, j])

                rho_loc = 0.5 * (rho_field[i, jb] + rho_field[i, jt])
                mu_loc  = 0.5 * (mu_field[i, jb] + mu_field[i, jt])

                Fe = r_e * rho_loc * ue * dyj; Fw = r_w * rho_loc * uw * dyj
                Fn = r_n * rho_loc * vn * dxi; Fs = r_s * rho_loc * vs * dxi

                aE = De + max(-Fe, 0.0)
                aW = Dw + max(Fw, 0.0)
                aN = Dn + max(-Fn, 0.0)
                aS = Ds + max(Fs, 0.0)

                umag = _umag_v(u, v, i, j, Nx, Ny)
                # 2026-07-10 lateral-K: K/cF are 2D (Nx, Ny). v-node keeps the
                # legacy streamwise pick K[jc] (a jb/jt mean would move
                # streamwise-graded cases), extended laterally to column i.
                Sp = _porous_src_df(umag, K_arr[i, jc], cF_arr[i, jc], mu_loc, rho_loc) * vol

                # Brinkman penalty — grid-invariant (3D parity, P1b-c)
                aP_nat = aE + aW + aN + aS
                wall_out = 1.0 - outlet_frac[i]
                if wall_out > 0.01 and j >= Ny - 8:
                    wall_dist = Ny - j
                    Sp += _WALL_PENALTY_BASE * wall_out**4 * np.exp(
                        -_WALL_PENALTY_EFOLD * (wall_dist - 1)) * aP_nat
                wall_in = 1.0 - inlet_frac[i]
                if wall_in > 0.01 and j < 8:
                    wall_dist = j + 1
                    Sp += _WALL_PENALTY_BASE * wall_in**4 * np.exp(
                        -_WALL_PENALTY_EFOLD * (wall_dist - 1)) * aP_nat

                p_src = (P[i, j - 1] - P[i, j]) * dxi
                sou = (_sou_corr_v_x(v, i, j, Nx, Fe, Fw)
                     + _sou_corr_v_y(v, i, j, Ny, Fn, Fs))
                aP0 = aE + aW + aN + aS + Sp
                rhs = aE * vE + aW * vW + aN * vN + aS * vS + p_src + sou
                aP = aP0 / alpha_u
                rhs += (1.0 - alpha_u) / alpha_u * aP0 * v[i, j]

                v[i, j] = rhs / aP
                d_v[i, j] = dxi / aP0

    for i in range(Nx):
        v[i, 0] = v_inlet_field[i] * inlet_frac[i]
        if outlet_frac[i] > 0.5:
            if Ny >= 2:
                # M2: extrapolate conserving ε·ρ·v (VANS mass flux), mirroring
                # the 3D outlet convention. The ε ratio multiplies AFTER the
                # legacy ρ chain so uniform ε (ratio = 1.0 exactly) reproduces
                # the pre-M2 float sequence bit-identically.
                rho_inner_face = 0.5 * (rho_field[i, Ny-2] + rho_field[i, Ny-1])
                rho_outer_face = rho_field[i, Ny-1]
                eps_inner_face = 0.5 * (eps_field[i, Ny-2] + eps_field[i, Ny-1])
                eps_outer_face = eps_field[i, Ny-1]
                v[i, Ny] = (v[i, Ny - 1] * rho_inner_face / rho_outer_face
                            * (eps_inner_face / eps_outer_face))
            else:
                v[i, Ny] = v[i, Ny - 1]
        else:
            v[i, Ny] = 0.0


# ── SIMPLER steps 1-2: pseudo-velocities (opt-in coupling='simpler') ──
# openspec change simpler-coupling-2d. Patankar/Tao SIMPLER: û/v̂ are the
# momentum equations WITHOUT the pressure-gradient source, evaluated in a
# single Jacobi pass over the frozen (u, v) state:  hat = (Σ a_nb·φ_nb + SOU)/aP0.
# The caller pre-copies u→uhat / v→vhat so boundary faces carry the BC values
# (Tao Main95.f:528-539 fills UHAT boundaries with the real BC velocity).
#
# COEFFICIENT PARITY: the aE/aW/aN/aS/Sp blocks below MUST stay line-for-line
# identical to _sweep_u_jit_df / _sweep_v_jit_df (DF source, Brinkman wall
# penalty, SOU deferred correction, variable-ρ/μ face interpolation) minus the
# pressure source and under-relaxation. Update BOTH kernels when touching either.

@njit(cache=True)
def _pseudo_u_jit_df(u, v, uhat, d_u, inlet_frac, outlet_frac,
                     Nx, Ny, dx_arr, dy_arr, rho_field, mu_eff_field,
                     K_arr, cF_arr, mu_field, eps_field):
    """SIMPLER pseudo-velocity û. Writes uhat interior + fills d_u = dy/aP0.
    M2 (2026-07-09): VANS ε-ratio factors mirror _sweep_u_jit_df
    (coefficient-parity contract)."""
    for i in range(1, Nx):
        for j in range(Ny):
            dxi = 0.5 * (dx_arr[i - 1] + dx_arr[min(i, Nx - 1)])
            dyj = dy_arr[j]
            vol = dxi * dyj

            il_r = max(i - 1, 0); ir_r = min(i, Nx - 1)
            mu_e = 0.5 * (mu_eff_field[il_r, j] + mu_eff_field[ir_r, j])

            # M2: ε-ratio factors — mirrors _sweep_u_jit_df.
            eps_u = 0.5 * (eps_field[il_r, j] + eps_field[ir_r, j])
            r_e = eps_field[ir_r, j] / eps_u
            r_w = eps_field[il_r, j] / eps_u
            r_n = (0.25 * (eps_field[il_r, j] + eps_field[ir_r, j]
                           + eps_field[il_r, j + 1]
                           + eps_field[ir_r, j + 1]) / eps_u
                   if j < Ny - 1 else 1.0)
            r_s = (0.25 * (eps_field[il_r, j] + eps_field[ir_r, j]
                           + eps_field[il_r, j - 1]
                           + eps_field[ir_r, j - 1]) / eps_u
                   if j > 0 else 1.0)

            # N4 (2026-07-07): mirrors _sweep_u_jit_df — actual neighbour-node
            # distances (coefficient-parity contract).
            De = r_e * mu_e * dyj / dx_arr[ir_r]
            Dw = r_w * mu_e * dyj / dx_arr[il_r]
            Dn = (r_n * mu_e * dxi / (0.5 * (dy_arr[j] + dy_arr[j + 1]))
                  if j < Ny - 1 else 0.0)
            Ds = (r_s * mu_e * dxi / (0.5 * (dy_arr[j] + dy_arr[j - 1]))
                  if j > 0 else 0.0)

            uE = u[i + 1, j] if i + 1 < Nx else 0.0
            uW = u[i - 1, j] if i > 1 else 0.0
            uN = u[i, j + 1] if j < Ny - 1 else u[i, j]
            uS = u[i, j - 1] if j > 0 else 0.0

            ue = 0.5 * (u[i, j] + u[min(i + 1, Nx), j])
            uw = 0.5 * (u[max(i - 1, 0), j] + u[i, j])
            il = max(i - 1, 0); ir = min(i, Nx - 1)
            vn = 0.5 * (v[il, j + 1] + v[ir, j + 1]) if j < Ny - 1 else 0.0
            vs = 0.5 * (v[il, j] + v[ir, j])

            rho_loc = 0.5 * (rho_field[il_r, j] + rho_field[ir_r, j])
            mu_loc  = 0.5 * (mu_field[il_r, j] + mu_field[ir_r, j])

            Fe = r_e * rho_loc * ue * dyj; Fw = r_w * rho_loc * uw * dyj
            Fn = r_n * rho_loc * vn * dxi; Fs = r_s * rho_loc * vs * dxi

            aE = De + max(-Fe, 0.0)
            aW = Dw + max(Fw, 0.0)
            aN = Dn + max(-Fn, 0.0)
            aS = Ds + max(Fs, 0.0)

            umag = _umag_u(u, v, i, j, Nx, Ny)
            # 2026-07-10 lateral-K: mirrors _sweep_u_jit_df (parity contract).
            K_u = 0.5 * (K_arr[il_r, j] + K_arr[ir_r, j])
            cF_u = 0.5 * (cF_arr[il_r, j] + cF_arr[ir_r, j])
            Sp = _porous_src_df(umag, K_u, cF_u, mu_loc, rho_loc) * vol

            aP_nat = aE + aW + aN + aS
            il_u = max(i - 1, 0); ir_u = min(i, Nx - 1)
            wall_out = 1.0 - 0.5 * (outlet_frac[il_u] + outlet_frac[ir_u])
            if wall_out > 0.01 and j >= Ny - 8:
                wall_dist = Ny - j
                Sp += _WALL_PENALTY_BASE * wall_out**4 * np.exp(
                    -_WALL_PENALTY_EFOLD * (wall_dist - 1)) * aP_nat
            wall_in = 1.0 - 0.5 * (inlet_frac[il_u] + inlet_frac[ir_u])
            if wall_in > 0.01 and j < 8:
                wall_dist = j + 1
                Sp += _WALL_PENALTY_BASE * wall_in**4 * np.exp(
                    -_WALL_PENALTY_EFOLD * (wall_dist - 1)) * aP_nat

            sou = (_sou_corr_u_x(u, i, j, Nx, Fe, Fw)
                 + _sou_corr_u_y(u, i, j, Ny, Fn, Fs))
            aP0 = aE + aW + aN + aS + Sp
            uhat[i, j] = (aE * uE + aW * uW + aN * uN + aS * uS + sou) / aP0
            d_u[i, j] = dyj / aP0

    for j in range(Ny):
        uhat[0, j] = 0.0; uhat[Nx, j] = 0.0


@njit(cache=True)
def _pseudo_v_jit_df(u, v, vhat, d_v, inlet_frac, v_inlet_field, outlet_frac,
                     Nx, Ny, dx_arr, dy_arr, rho_field, mu_eff_field,
                     K_arr, cF_arr, mu_field, eps_field):
    """SIMPLER pseudo-velocity v̂. Writes vhat interior + fills d_v = dx/aP0.
    M2 (2026-07-09): VANS ε-ratio factors mirror _sweep_v_jit_df
    (coefficient-parity contract)."""
    for i in range(Nx):
        for j in range(1, Ny):
            jc = min(j, Ny - 1)
            dxi = dx_arr[i]
            dyj = 0.5 * (dy_arr[j - 1] + dy_arr[min(j, Ny - 1)])
            vol = dxi * dyj

            jb = max(j - 1, 0); jt = min(j, Ny - 1)
            mu_e = 0.5 * (mu_eff_field[i, jb] + mu_eff_field[i, jt])

            # M2: ε-ratio factors — mirrors _sweep_v_jit_df.
            eps_v = 0.5 * (eps_field[i, jb] + eps_field[i, jt])
            r_n = eps_field[i, jt] / eps_v
            r_s = eps_field[i, jb] / eps_v
            r_e = (0.25 * (eps_field[i, jb] + eps_field[i, jt]
                           + eps_field[i + 1, jb] + eps_field[i + 1, jt])
                   / eps_v if i < Nx - 1 else 1.0)
            r_w = (0.25 * (eps_field[i, jb] + eps_field[i, jt]
                           + eps_field[i - 1, jb] + eps_field[i - 1, jt])
                   / eps_v if i > 0 else 1.0)

            # N4 (2026-07-07): mirrors _sweep_v_jit_df — actual neighbour-node
            # distances (coefficient-parity contract).
            if i < Nx - 1:
                vE = v[i + 1, j]
                De = r_e * mu_e * dyj / (0.5 * (dx_arr[i] + dx_arr[i + 1]))
            else:
                vE = 0.0; De = 2.0 * mu_e * dyj / dxi   # east wall (no-slip)
            if i > 0:
                vW = v[i - 1, j]
                Dw = r_w * mu_e * dyj / (0.5 * (dx_arr[i] + dx_arr[i - 1]))
            else:
                vW = 0.0; Dw = 2.0 * mu_e * dyj / dxi   # west wall (no-slip)
            vN = v[i, j + 1] if j < Ny - 1 else v[i, j]
            vS = v[i, j - 1]

            Dn = r_n * mu_e * dxi / dy_arr[jt] if j < Ny - 1 else 0.0
            Ds = r_s * mu_e * dxi / dy_arr[jb]

            ue = 0.5 * (u[i + 1, jb] + u[i + 1, jt]) if i < Nx - 1 else 0.0
            uw = 0.5 * (u[i, jb] + u[i, jt]) if i > 0 else 0.0
            vn = 0.5 * (v[i, j] + v[i, min(j + 1, Ny)])
            vs = 0.5 * (v[i, max(j - 1, 0)] + v[i, j])

            rho_loc = 0.5 * (rho_field[i, jb] + rho_field[i, jt])
            mu_loc  = 0.5 * (mu_field[i, jb] + mu_field[i, jt])

            Fe = r_e * rho_loc * ue * dyj; Fw = r_w * rho_loc * uw * dyj
            Fn = r_n * rho_loc * vn * dxi; Fs = r_s * rho_loc * vs * dxi

            aE = De + max(-Fe, 0.0)
            aW = Dw + max(Fw, 0.0)
            aN = Dn + max(-Fn, 0.0)
            aS = Ds + max(Fs, 0.0)

            umag = _umag_v(u, v, i, j, Nx, Ny)
            # 2026-07-10 lateral-K: mirrors _sweep_v_jit_df (parity contract).
            Sp = _porous_src_df(umag, K_arr[i, jc], cF_arr[i, jc], mu_loc, rho_loc) * vol

            aP_nat = aE + aW + aN + aS
            wall_out = 1.0 - outlet_frac[i]
            if wall_out > 0.01 and j >= Ny - 8:
                wall_dist = Ny - j
                Sp += _WALL_PENALTY_BASE * wall_out**4 * np.exp(
                    -_WALL_PENALTY_EFOLD * (wall_dist - 1)) * aP_nat
            wall_in = 1.0 - inlet_frac[i]
            if wall_in > 0.01 and j < 8:
                wall_dist = j + 1
                Sp += _WALL_PENALTY_BASE * wall_in**4 * np.exp(
                    -_WALL_PENALTY_EFOLD * (wall_dist - 1)) * aP_nat

            sou = (_sou_corr_v_x(v, i, j, Nx, Fe, Fw)
                 + _sou_corr_v_y(v, i, j, Ny, Fn, Fs))
            aP0 = aE + aW + aN + aS + Sp
            vhat[i, j] = (aE * vE + aW * vW + aN * vN + aS * vS + sou) / aP0
            d_v[i, j] = dxi / aP0

    for i in range(Nx):
        vhat[i, 0] = v_inlet_field[i] * inlet_frac[i]
        if outlet_frac[i] > 0.5:
            if Ny >= 2:
                # M2: ε·ρ·v-conserving extrapolation — mirrors _sweep_v_jit_df
                # (ε ratio multiplies AFTER the legacy ρ chain for uniform-ε
                # bit-identity).
                rho_inner_face = 0.5 * (rho_field[i, Ny-2] + rho_field[i, Ny-1])
                rho_outer_face = rho_field[i, Ny-1]
                eps_inner_face = 0.5 * (eps_field[i, Ny-2] + eps_field[i, Ny-1])
                eps_outer_face = eps_field[i, Ny-1]
                vhat[i, Ny] = (vhat[i, Ny - 1] * rho_inner_face / rho_outer_face
                               * (eps_inner_face / eps_outer_face))
            else:
                vhat[i, Ny] = vhat[i, Ny - 1]
        else:
            vhat[i, Ny] = 0.0


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
def _correct_jit(u, v, P, Pp, d_u, d_v, inlet_frac, v_inlet_field, outlet_frac,
                 Nx, Ny, alpha_p, rho_field, eps_field):
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
        v[i, 0] = v_inlet_field[i] * inlet_frac[i]
        # Variable density outflow: ρ·v conserved across last face.
        # Wall cells (outlet_frac ≤ 0.5) must pin v=0 — matches _sweep_v_jit_df
        # end-of-sweep BC. Without this gate, zoned / partial-outlet configs
        # drive spurious through-wall flow that the pp-equation sees as mass
        # imbalance. Benign for full-outlet Shanghai (outlet_frac ≡ 1).
        if outlet_frac[i] > 0.5:
            if Ny >= 2:
                # M2: ε·ρ·v-conserving — mirrors the sweep/pseudo outlet BC
                # (ε ratio after the legacy ρ chain; uniform ε bit-identical).
                rho_inner_face = 0.5 * (rho_field[i, Ny-2] + rho_field[i, Ny-1])
                rho_outer_face = rho_field[i, Ny-1]
                eps_inner_face = 0.5 * (eps_field[i, Ny-2] + eps_field[i, Ny-1])
                eps_outer_face = eps_field[i, Ny-1]
                v[i, Ny] = (v[i, Ny - 1] * rho_inner_face / rho_outer_face
                            * (eps_inner_face / eps_outer_face))
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
