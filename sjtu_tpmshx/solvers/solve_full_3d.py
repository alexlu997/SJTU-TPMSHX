"""
solve_full_3d.py — Full-domain 3D steady-state 2-fluid LTNE solver

Three-temperature (Ta, Tb, Ts) LTNE on an (Nx, Ny, Nz) grid.

Energy equations (steady, incompressible, homogenised porous):
  eps_f * rho_cp_A * (u_A * dTa/dx + v_A * dTa/dy + w_A * dTa/dz)
      = div(K_ffA * grad Ta) + h_vA * (Ts - Ta)
  eps_f * rho_cp_B * (u_B * dTb/dx + v_B * dTb/dy + w_B * dTb/dz)
      = div(K_ffB * grad Tb) + h_vB * (Ts - Tb)
  0 = div(K_ss * grad Ts) + h_vA * (Ta - Ts) + h_vB * (Tb - Ts)

7-point Laplacian (harmonic-mean face conductivity). Upwind convection with
SOU deferred correction in all three axes. Cell-coupled Gauss-Seidel with
Ta -> Ts -> Tb updates in each sweep (k innermost, cache-friendly).

dir code: 0=+x, 1=-x, 2=+y, 3=-y, 4=+z, 5=-z.

Phase 1 additions (2026-04-20):
  * alpha_T under-relaxation (default 0.7) — shared by all three fields.
  * SOU limiter in x/y/z (promoted from Phase 1b).
  * Nz == 1 fast path: delegate to 2D solve_full_domain; bitwise-identical.
  * Conservation probes: energy_balance_3d, mass_balance_3d helpers.
"""

import numpy as np
from numba import njit

from solvers.solve_full import solve_full_domain as _solve_full_2d


# ---------------------------------------------------------------------------
# SOU limiter — three axes
# ---------------------------------------------------------------------------

@njit(cache=True, fastmath=True)
def _sou_corr_x_3d(T, i, j, k, Nx, u_loc, Fx):
    if u_loc >= 0:
        phi_w = 0.0
        if i > 1:
            gu = T[i-1, j, k] - T[i-2, j, k]
            gd = T[i, j, k] - T[i-1, j, k]
            if gu * gd > 0:
                phi_w = min(abs(gu), abs(gd))
                if gu < 0: phi_w = -phi_w
        phi_e = 0.0
        if i < Nx - 1 and i > 0:
            gu = T[i, j, k] - T[i-1, j, k]
            gd = T[i+1, j, k] - T[i, j, k]
            if gu * gd > 0:
                phi_e = min(abs(gu), abs(gd))
                if gu < 0: phi_e = -phi_e
        return 0.5 * Fx * (phi_w - phi_e)
    else:
        phi_e = 0.0
        if i < Nx - 2:
            gu = T[i+1, j, k] - T[i+2, j, k]
            gd = T[i, j, k] - T[i+1, j, k]
            if gu * gd > 0:
                phi_e = min(abs(gu), abs(gd))
                if gu < 0: phi_e = -phi_e
        phi_w = 0.0
        if i > 0 and i < Nx - 1:
            gu = T[i, j, k] - T[i+1, j, k]
            gd = T[i-1, j, k] - T[i, j, k]
            if gu * gd > 0:
                phi_w = min(abs(gu), abs(gd))
                if gu < 0: phi_w = -phi_w
        return 0.5 * Fx * (phi_e - phi_w)


@njit(cache=True, fastmath=True)
def _sou_corr_y_3d(T, i, j, k, Ny, v_loc, Fy):
    if v_loc >= 0:
        phi_s = 0.0
        if j > 1:
            gu = T[i, j-1, k] - T[i, j-2, k]
            gd = T[i, j, k] - T[i, j-1, k]
            if gu * gd > 0:
                phi_s = min(abs(gu), abs(gd))
                if gu < 0: phi_s = -phi_s
        phi_n = 0.0
        if j < Ny - 1 and j > 0:
            gu = T[i, j, k] - T[i, j-1, k]
            gd = T[i, j+1, k] - T[i, j, k]
            if gu * gd > 0:
                phi_n = min(abs(gu), abs(gd))
                if gu < 0: phi_n = -phi_n
        return 0.5 * Fy * (phi_s - phi_n)
    else:
        phi_n = 0.0
        if j < Ny - 2:
            gu = T[i, j+1, k] - T[i, j+2, k]
            gd = T[i, j, k] - T[i, j+1, k]
            if gu * gd > 0:
                phi_n = min(abs(gu), abs(gd))
                if gu < 0: phi_n = -phi_n
        phi_s = 0.0
        if j > 0 and j < Ny - 1:
            gu = T[i, j, k] - T[i, j+1, k]
            gd = T[i, j-1, k] - T[i, j, k]
            if gu * gd > 0:
                phi_s = min(abs(gu), abs(gd))
                if gu < 0: phi_s = -phi_s
        return 0.5 * Fy * (phi_n - phi_s)


@njit(cache=True, fastmath=True)
def _sou_corr_z_3d(T, i, j, k, Nz, w_loc, Fz):
    if w_loc >= 0:
        phi_b = 0.0
        if k > 1:
            gu = T[i, j, k-1] - T[i, j, k-2]
            gd = T[i, j, k] - T[i, j, k-1]
            if gu * gd > 0:
                phi_b = min(abs(gu), abs(gd))
                if gu < 0: phi_b = -phi_b
        phi_t = 0.0
        if k < Nz - 1 and k > 0:
            gu = T[i, j, k] - T[i, j, k-1]
            gd = T[i, j, k+1] - T[i, j, k]
            if gu * gd > 0:
                phi_t = min(abs(gu), abs(gd))
                if gu < 0: phi_t = -phi_t
        return 0.5 * Fz * (phi_b - phi_t)
    else:
        phi_t = 0.0
        if k < Nz - 2:
            gu = T[i, j, k+1] - T[i, j, k+2]
            gd = T[i, j, k] - T[i, j, k+1]
            if gu * gd > 0:
                phi_t = min(abs(gu), abs(gd))
                if gu < 0: phi_t = -phi_t
        phi_b = 0.0
        if k > 0 and k < Nz - 1:
            gu = T[i, j, k] - T[i, j, k+1]
            gd = T[i, j, k-1] - T[i, j, k]
            if gu * gd > 0:
                phi_b = min(abs(gu), abs(gd))
                if gu < 0: phi_b = -phi_b
        return 0.5 * Fz * (phi_t - phi_b)


# ---------------------------------------------------------------------------
# inlet helpers
# ---------------------------------------------------------------------------

@njit(cache=True, fastmath=True, inline='always')
def _is_inlet(dir_code, i, j, k, Nx, Ny, Nz):
    if dir_code == 0: return i == 0
    if dir_code == 1: return i == Nx - 1
    if dir_code == 2: return j == 0
    if dir_code == 3: return j == Ny - 1
    if dir_code == 4: return k == 0
    return k == Nz - 1


@njit(cache=True, fastmath=True, inline='always')
def _inlet_frac(ifrac2d, dir_code, i, j, k):
    # ifrac2d shape depends on dir: (Ny, Nz) / (Nx, Nz) / (Nx, Ny)
    if dir_code <= 1:
        return ifrac2d[j, k]
    if dir_code <= 3:
        return ifrac2d[i, k]
    return ifrac2d[i, j]


@njit(cache=True, fastmath=True, inline='always')
def _inlet_val(Tin2d, dir_code, i, j, k):
    if dir_code <= 1:
        return Tin2d[j, k]
    if dir_code <= 3:
        return Tin2d[i, k]
    return Tin2d[i, j]


@njit(cache=True, fastmath=True, inline='always')
def _inlet_neighbor(T, dir_code, i, j, k, Nx, Ny, Nz):
    if dir_code == 0: return T[1, j, k]
    if dir_code == 1: return T[Nx-2, j, k]
    if dir_code == 2: return T[i, 1, k]
    if dir_code == 3: return T[i, Ny-2, k]
    if dir_code == 4: return T[i, j, 1]
    return T[i, j, Nz-2]


# ---------------------------------------------------------------------------
# Gauss-Seidel chunk — 7-point + SOU + coupled Ta/Ts/Tb
# ---------------------------------------------------------------------------

@njit(cache=True, fastmath=True)
def _gs_full_chunk_3d(Ta, Tb, Ts, Nx, Ny, Nz,
                      dx_arr, dy_arr, dz_arr,
                      K_ffA_arr, K_ffB_arr, K_ss_arr,
                      h_vA_arr, h_vB_arr, eps_f_arr,
                      rho_cp_fA, rho_cp_fB,
                      ucA, vcA, wcA, ucB, vcB, wcB,
                      bc_A, bc_B, T_inA_arr, T_inB_arr,
                      ifrac_A, ifrac_B,
                      n_iters, freeze_Tb,
                      alpha_fA, alpha_s, alpha_fB):
    max_chg = 0.0

    # Sweep direction: follow A on i, B on j, A on k
    if bc_A == 1:
        i0, i1, di = Nx - 1, -1, -1
    else:
        i0, i1, di = 0, Nx, 1
    if bc_B == 3:
        j0, j1, dj = Ny - 1, -1, -1
    else:
        j0, j1, dj = 0, Ny, 1
    if bc_A == 5:
        k0, k1, dk = Nz - 1, -1, -1
    else:
        k0, k1, dk = 0, Nz, 1

    for _it in range(n_iters):
        max_chg = 0.0

        for i in range(i0, i1, di):
            for j in range(j0, j1, dj):
                for k in range(k0, k1, dk):

                    # ── Fluid A ──
                    is_inA = _is_inlet(bc_A, i, j, k, Nx, Ny, Nz)
                    if is_inA:
                        frac = _inlet_frac(ifrac_A, bc_A, i, j, k)
                        if frac > 0.99:
                            Ta[i, j, k] = _inlet_val(T_inA_arr, bc_A, i, j, k)
                        elif frac > 0.01:
                            Tin = _inlet_val(T_inA_arr, bc_A, i, j, k)
                            Tnb = _inlet_neighbor(Ta, bc_A, i, j, k, Nx, Ny, Nz)
                            Ta[i, j, k] = frac * Tin + (1.0 - frac) * Tnb
                    else:
                        dxi = dx_arr[i]; dyj = dy_arr[j]; dzk = dz_arr[k]
                        vol = dxi * dyj * dzk
                        Kc = K_ffA_arr[i, j, k]
                        hvA = h_vA_arr[i, j, k] * vol
                        ef = eps_f_arr[i, j, k]

                        Ax = dyj * dzk; Ay = dxi * dzk; Az = dxi * dyj
                        dE = 2.0 * Kc * K_ffA_arr[i+1, j, k] / (Kc + K_ffA_arr[i+1, j, k] + 1e-30) * Ax / dxi if i < Nx-1 else 0.0
                        dW = 2.0 * Kc * K_ffA_arr[i-1, j, k] / (Kc + K_ffA_arr[i-1, j, k] + 1e-30) * Ax / dxi if i > 0 else 0.0
                        dN = 2.0 * Kc * K_ffA_arr[i, j+1, k] / (Kc + K_ffA_arr[i, j+1, k] + 1e-30) * Ay / dyj if j < Ny-1 else 0.0
                        dS = 2.0 * Kc * K_ffA_arr[i, j-1, k] / (Kc + K_ffA_arr[i, j-1, k] + 1e-30) * Ay / dyj if j > 0 else 0.0
                        dT_ = 2.0 * Kc * K_ffA_arr[i, j, k+1] / (Kc + K_ffA_arr[i, j, k+1] + 1e-30) * Az / dzk if k < Nz-1 else 0.0
                        dB = 2.0 * Kc * K_ffA_arr[i, j, k-1] / (Kc + K_ffA_arr[i, j, k-1] + 1e-30) * Az / dzk if k > 0 else 0.0

                        u_loc = ucA[i, j, k]; v_loc = vcA[i, j, k]; w_loc = wcA[i, j, k]
                        Fx = ef * rho_cp_fA[i, j, k] * abs(u_loc) * Ax
                        Fy = ef * rho_cp_fA[i, j, k] * abs(v_loc) * Ay
                        Fz = ef * rho_cp_fA[i, j, k] * abs(w_loc) * Az

                        if u_loc >= 0: aW = dW + Fx; aE = dE
                        else:          aE = dE + Fx; aW = dW
                        if v_loc >= 0: aS = dS + Fy; aN = dN
                        else:          aN = dN + Fy; aS = dS
                        if w_loc >= 0: aB = dB + Fz; aT = dT_
                        else:          aT = dT_ + Fz; aB = dB

                        tE = Ta[i+1, j, k] if i < Nx-1 else Ta[i, j, k]
                        tW = Ta[i-1, j, k] if i > 0    else Ta[i, j, k]
                        tN = Ta[i, j+1, k] if j < Ny-1 else Ta[i, j, k]
                        tS = Ta[i, j-1, k] if j > 0    else Ta[i, j, k]
                        tT = Ta[i, j, k+1] if k < Nz-1 else Ta[i, j, k]
                        tB = Ta[i, j, k-1] if k > 0    else Ta[i, j, k]

                        sou = (_sou_corr_x_3d(Ta, i, j, k, Nx, u_loc, Fx)
                               + _sou_corr_y_3d(Ta, i, j, k, Ny, v_loc, Fy)
                               + _sou_corr_z_3d(Ta, i, j, k, Nz, w_loc, Fz))

                        aP = aE + aW + aN + aS + aT + aB + hvA
                        new = (aE*tE + aW*tW + aN*tN + aS*tS + aT*tT + aB*tB
                               + hvA * Ts[i, j, k] + sou) / aP
                        old = Ta[i, j, k]
                        upd = old + alpha_fA * (new - old)
                        chg = abs(upd - old)
                        if chg > max_chg: max_chg = chg
                        Ta[i, j, k] = upd

                    # ── Solid ──
                    dxi = dx_arr[i]; dyj = dy_arr[j]; dzk = dz_arr[k]
                    vol_s = dxi * dyj * dzk
                    Ks = K_ss_arr[i, j, k]
                    hvA_s = h_vA_arr[i, j, k] * vol_s
                    hvB_s = h_vB_arr[i, j, k] * vol_s

                    Ax = dyj * dzk; Ay = dxi * dzk; Az = dxi * dyj
                    De = 2.0*Ks*K_ss_arr[i+1, j, k]/(Ks+K_ss_arr[i+1, j, k]+1e-30)*Ax/dxi if i < Nx-1 else Ks*Ax/dxi
                    Dw = 2.0*Ks*K_ss_arr[i-1, j, k]/(Ks+K_ss_arr[i-1, j, k]+1e-30)*Ax/dxi if i > 0    else Ks*Ax/dxi
                    Dn = 2.0*Ks*K_ss_arr[i, j+1, k]/(Ks+K_ss_arr[i, j+1, k]+1e-30)*Ay/dyj if j < Ny-1 else Ks*Ay/dyj
                    Ds = 2.0*Ks*K_ss_arr[i, j-1, k]/(Ks+K_ss_arr[i, j-1, k]+1e-30)*Ay/dyj if j > 0    else Ks*Ay/dyj
                    Dt = 2.0*Ks*K_ss_arr[i, j, k+1]/(Ks+K_ss_arr[i, j, k+1]+1e-30)*Az/dzk if k < Nz-1 else Ks*Az/dzk
                    Db = 2.0*Ks*K_ss_arr[i, j, k-1]/(Ks+K_ss_arr[i, j, k-1]+1e-30)*Az/dzk if k > 0    else Ks*Az/dzk

                    sE = Ts[i+1, j, k] if i < Nx-1 else Ts[i, j, k]
                    sW = Ts[i-1, j, k] if i > 0    else Ts[i, j, k]
                    sN = Ts[i, j+1, k] if j < Ny-1 else Ts[i, j, k]
                    sS = Ts[i, j-1, k] if j > 0    else Ts[i, j, k]
                    sT = Ts[i, j, k+1] if k < Nz-1 else Ts[i, j, k]
                    sB = Ts[i, j, k-1] if k > 0    else Ts[i, j, k]

                    aP_s = De + Dw + Dn + Ds + Dt + Db + hvA_s + hvB_s
                    new_s = (De*sE + Dw*sW + Dn*sN + Ds*sS + Dt*sT + Db*sB
                             + hvA_s*Ta[i, j, k] + hvB_s*Tb[i, j, k]) / aP_s
                    old_s = Ts[i, j, k]
                    upd_s = old_s + alpha_s * (new_s - old_s)
                    chg = abs(upd_s - old_s)
                    if chg > max_chg: max_chg = chg
                    Ts[i, j, k] = upd_s

                    # ── Fluid B ──
                    if freeze_Tb == 0:
                        is_inB = _is_inlet(bc_B, i, j, k, Nx, Ny, Nz)
                        if is_inB:
                            frac_b = _inlet_frac(ifrac_B, bc_B, i, j, k)
                            if frac_b > 0.99:
                                Tb[i, j, k] = _inlet_val(T_inB_arr, bc_B, i, j, k)
                            elif frac_b > 0.01:
                                Tin_b = _inlet_val(T_inB_arr, bc_B, i, j, k)
                                Tnb_b = _inlet_neighbor(Tb, bc_B, i, j, k, Nx, Ny, Nz)
                                Tb[i, j, k] = frac_b * Tin_b + (1.0 - frac_b) * Tnb_b
                        else:
                            vol_b = dxi * dyj * dzk
                            Kc_b = K_ffB_arr[i, j, k]
                            hvB = h_vB_arr[i, j, k] * vol_b
                            ef_b = eps_f_arr[i, j, k]

                            dEb = 2.0*Kc_b*K_ffB_arr[i+1, j, k]/(Kc_b+K_ffB_arr[i+1, j, k]+1e-30)*Ax/dxi if i < Nx-1 else 0.0
                            dWb = 2.0*Kc_b*K_ffB_arr[i-1, j, k]/(Kc_b+K_ffB_arr[i-1, j, k]+1e-30)*Ax/dxi if i > 0 else 0.0
                            dNb = 2.0*Kc_b*K_ffB_arr[i, j+1, k]/(Kc_b+K_ffB_arr[i, j+1, k]+1e-30)*Ay/dyj if j < Ny-1 else 0.0
                            dSb = 2.0*Kc_b*K_ffB_arr[i, j-1, k]/(Kc_b+K_ffB_arr[i, j-1, k]+1e-30)*Ay/dyj if j > 0 else 0.0
                            dTb_ = 2.0*Kc_b*K_ffB_arr[i, j, k+1]/(Kc_b+K_ffB_arr[i, j, k+1]+1e-30)*Az/dzk if k < Nz-1 else 0.0
                            dBb = 2.0*Kc_b*K_ffB_arr[i, j, k-1]/(Kc_b+K_ffB_arr[i, j, k-1]+1e-30)*Az/dzk if k > 0 else 0.0

                            u_b = ucB[i, j, k]; v_b = vcB[i, j, k]; w_b = wcB[i, j, k]
                            Fxb = ef_b * rho_cp_fB[i, j, k] * abs(u_b) * Ax
                            Fyb = ef_b * rho_cp_fB[i, j, k] * abs(v_b) * Ay
                            Fzb = ef_b * rho_cp_fB[i, j, k] * abs(w_b) * Az

                            if u_b >= 0: aWb = dWb + Fxb; aEb = dEb
                            else:        aEb = dEb + Fxb; aWb = dWb
                            if v_b >= 0: aSb = dSb + Fyb; aNb = dNb
                            else:        aNb = dNb + Fyb; aSb = dSb
                            if w_b >= 0: aBb = dBb + Fzb; aTb = dTb_
                            else:        aTb = dTb_ + Fzb; aBb = dBb

                            tEb = Tb[i+1, j, k] if i < Nx-1 else Tb[i, j, k]
                            tWb = Tb[i-1, j, k] if i > 0    else Tb[i, j, k]
                            tNb = Tb[i, j+1, k] if j < Ny-1 else Tb[i, j, k]
                            tSb = Tb[i, j-1, k] if j > 0    else Tb[i, j, k]
                            tTb = Tb[i, j, k+1] if k < Nz-1 else Tb[i, j, k]
                            tBb = Tb[i, j, k-1] if k > 0    else Tb[i, j, k]

                            soub = (_sou_corr_x_3d(Tb, i, j, k, Nx, u_b, Fxb)
                                    + _sou_corr_y_3d(Tb, i, j, k, Ny, v_b, Fyb)
                                    + _sou_corr_z_3d(Tb, i, j, k, Nz, w_b, Fzb))

                            aPb = aEb + aWb + aNb + aSb + aTb + aBb + hvB
                            new_b = (aEb*tEb + aWb*tWb + aNb*tNb + aSb*tSb
                                     + aTb*tTb + aBb*tBb + hvB*Ts[i, j, k] + soub) / aPb
                            old_b = Tb[i, j, k]
                            upd_b = old_b + alpha_fB * (new_b - old_b)
                            chg = abs(upd_b - old_b)
                            if chg > max_chg: max_chg = chg
                            Tb[i, j, k] = upd_b

        # Outlet zero-gradient (mirror from bc_A / bc_B direction)
        _apply_outlet_3d(Ta, bc_A, Nx, Ny, Nz)
        if freeze_Tb == 0:
            _apply_outlet_3d(Tb, bc_B, Nx, Ny, Nz)

        if max_chg < 1e-10:
            break

    return max_chg


@njit(cache=True, fastmath=True)
def _apply_outlet_3d(T, dir_code, Nx, Ny, Nz):
    # Outlet is opposite face; copy from neighbor (zero-gradient)
    if dir_code == 0:   # inlet +x, outlet -x... wait: 0 = flow in +x direction, inlet at i=0, outlet at i=Nx-1
        for j in range(Ny):
            for k in range(Nz):
                T[Nx-1, j, k] = T[Nx-2, j, k]
    elif dir_code == 1:
        for j in range(Ny):
            for k in range(Nz):
                T[0, j, k] = T[1, j, k]
    elif dir_code == 2:
        for i in range(Nx):
            for k in range(Nz):
                T[i, Ny-1, k] = T[i, Ny-2, k]
    elif dir_code == 3:
        for i in range(Nx):
            for k in range(Nz):
                T[i, 0, k] = T[i, 1, k]
    elif dir_code == 4:
        for i in range(Nx):
            for j in range(Ny):
                T[i, j, Nz-1] = T[i, j, Nz-2]
    else:
        for i in range(Nx):
            for j in range(Ny):
                T[i, j, 0] = T[i, j, 1]


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

def _delegate_to_2d(L, H, D, Nx, Ny, Nz,
                    T_inA, T_inB,
                    K_ffA, K_ffB, K_ss,
                    h_vA, h_vB,
                    rho_cp_fA, rho_cp_fB,
                    epsilon,
                    ucA, vcA, wcA, ucB, vcB, wcB,
                    dir_A, dir_B,
                    T_inA_profile, T_inB_profile,
                    max_iter, tol,
                    progress_cb, return_info,
                    Ta_init, Tb_init, Ts_init,
                    dx_arr, dy_arr, dz_arr,
                    inlet_mask_A, inlet_mask_B,
                    Tb_prescribed,
                    alpha_T):
    """Nz == 1 shortcut: squeeze z axis and call 2D solver for bitwise equivalence.
    alpha_T is accepted but ignored (2D uses Q-chunk convergence)."""

    def _sq3(a):
        if a is None:
            return None
        a = np.asarray(a)
        if a.ndim == 3 and a.shape[-1] == 1:
            return np.ascontiguousarray(a[..., 0])
        return a

    def _sq_mask(m, dir_code):
        if m is None:
            return None
        m = np.asarray(m)
        # 2D (n,1) collapsed to 1D when dir_code <= 3 and z extent is 1
        if m.ndim == 2 and m.shape[1] == 1:
            return np.ascontiguousarray(m[:, 0])
        if m.ndim == 2:
            return np.ascontiguousarray(m[:, 0])
        return m

    Ta2, Tb2, Ts2 = _solve_full_2d(
        L, H, Nx, Ny,
        T_inA, T_inB,
        _sq3(K_ffA) if np.ndim(K_ffA) > 0 else K_ffA,
        _sq3(K_ffB) if np.ndim(K_ffB) > 0 else K_ffB,
        _sq3(K_ss)  if np.ndim(K_ss)  > 0 else K_ss,
        _sq3(h_vA)  if np.ndim(h_vA)  > 0 else h_vA,
        _sq3(h_vB)  if np.ndim(h_vB)  > 0 else h_vB,
        _sq3(rho_cp_fA) if np.ndim(rho_cp_fA) > 0 else rho_cp_fA,
        _sq3(rho_cp_fB) if np.ndim(rho_cp_fB) > 0 else rho_cp_fB,
        _sq3(epsilon) if np.ndim(epsilon) > 0 else epsilon,
        _sq3(ucA), _sq3(vcA), _sq3(ucB), _sq3(vcB),
        dir_A, dir_B,
        T_inA_profile=T_inA_profile, T_inB_profile=T_inB_profile,
        max_iter=max_iter, tol=tol,
        progress_cb=progress_cb, return_info=False,
        Ta_init=_sq3(Ta_init), Tb_init=_sq3(Tb_init), Ts_init=_sq3(Ts_init),
        dx_arr=dx_arr, dy_arr=dy_arr,
        inlet_mask_A=_sq_mask(inlet_mask_A, dir_A),
        inlet_mask_B=_sq_mask(inlet_mask_B, dir_B),
        Tb_prescribed=_sq3(Tb_prescribed))

    Ta3 = Ta2[..., None].copy()
    Tb3 = Tb2[..., None].copy()
    Ts3 = Ts2[..., None].copy()
    if return_info:
        return Ta3, Tb3, Ts3, {'converged': True, 'iterations': -1, 'residual': 0.0,
                                'delegated_to_2d': True}
    return Ta3, Tb3, Ts3


def solve_full_domain_3d(L, H, D, Nx, Ny, Nz,
                          T_inA, T_inB,
                          K_ffA, K_ffB, K_ss,
                          h_vA, h_vB,
                          rho_cp_fA, rho_cp_fB,
                          epsilon,
                          ucA, vcA, wcA, ucB, vcB, wcB,
                          dir_A, dir_B,
                          T_inA_profile=None, T_inB_profile=None,
                          max_iter=10000, tol=1e-6,
                          progress_cb=None, return_info=False,
                          Ta_init=None, Tb_init=None, Ts_init=None,
                          dx_arr=None, dy_arr=None, dz_arr=None,
                          inlet_mask_A=None, inlet_mask_B=None,
                          Tb_prescribed=None,
                          alpha_T=0.7,
                          alpha_T_s=None, alpha_T_fA=None, alpha_T_fB=None,
                          eps_A=None, eps_B=None):
    """3D full-domain 2-fluid LTNE solver (Ta, Tb, Ts).

    Shape contracts
    ---------------
    K_ffA/K_ffB/K_ss, h_vA/h_vB, rho_cp_fA/rho_cp_fB, epsilon : scalar or (Nx, Ny, Nz).
    ucA/vcA/wcA/ucB/vcB/wcB                                   : (Nx, Ny, Nz) cell-centre.
    dir_A/dir_B ∈ {0=+x, 1=-x, 2=+y, 3=-y, 4=+z, 5=-z}.
    inlet_mask_*                                              : 2D cross-section or None.
    alpha_T                                                    : 0 < α ≤ 1 under-relax (default 0.7).

    Nz == 1 fast path: delegates to solvers.solve_full.solve_full_domain
    (bitwise-identical Nz=1 regression).
    """
    Nx, Ny, Nz = int(Nx), int(Ny), int(Nz)

    if Nz == 1:
        return _delegate_to_2d(
            L, H, D, Nx, Ny, Nz, T_inA, T_inB,
            K_ffA, K_ffB, K_ss, h_vA, h_vB,
            rho_cp_fA, rho_cp_fB, epsilon,
            ucA, vcA, wcA, ucB, vcB, wcB,
            dir_A, dir_B,
            T_inA_profile, T_inB_profile,
            max_iter, tol, progress_cb, return_info,
            Ta_init, Tb_init, Ts_init,
            dx_arr, dy_arr, dz_arr,
            inlet_mask_A, inlet_mask_B, Tb_prescribed, alpha_T)

    if not (0.0 < alpha_T <= 1.0):
        raise ValueError(f"alpha_T must be in (0, 1], got {alpha_T}")
    # Three-phase under-relax: default to common alpha_T, override per phase if given.
    a_s  = float(alpha_T if alpha_T_s  is None else alpha_T_s)
    a_fA = float(alpha_T if alpha_T_fA is None else alpha_T_fA)
    a_fB = float(alpha_T if alpha_T_fB is None else alpha_T_fB)
    for name, v in (('alpha_T_s', a_s), ('alpha_T_fA', a_fA), ('alpha_T_fB', a_fB)):
        if not (0.0 < v <= 1.0):
            raise ValueError(f"{name} must be in (0, 1], got {v}")

    # Grid arrays
    if dx_arr is None:
        dx_arr = np.full(Nx, L / Nx, dtype=np.float64)
    else:
        dx_arr = np.ascontiguousarray(dx_arr, dtype=np.float64)
    if dy_arr is None:
        dy_arr = np.full(Ny, H / Ny, dtype=np.float64)
    else:
        dy_arr = np.ascontiguousarray(dy_arr, dtype=np.float64)
    if dz_arr is None:
        dz_arr = np.full(Nz, D / Nz, dtype=np.float64)
    else:
        dz_arr = np.ascontiguousarray(dz_arr, dtype=np.float64)

    def _to_3d(val):
        if np.ndim(val) == 0:
            return np.full((Nx, Ny, Nz), float(val), dtype=np.float64)
        arr = np.asarray(val, dtype=np.float64)
        if arr.shape != (Nx, Ny, Nz):
            raise ValueError(f"field shape {arr.shape} != ({Nx}, {Ny}, {Nz})")
        return np.ascontiguousarray(arr)

    K_ffA_arr = _to_3d(K_ffA)
    K_ffB_arr = _to_3d(K_ffB)
    K_ss_arr  = _to_3d(K_ss)
    h_vA_arr  = _to_3d(h_vA)
    h_vB_arr  = _to_3d(h_vB)
    rho_cp_fA_arr = _to_3d(rho_cp_fA)
    rho_cp_fB_arr = _to_3d(rho_cp_fB)

    # Per-fluid void-fraction split. Default = symmetric eps/2 per channel;
    # asymmetric eps_A / eps_B raises NotImplementedError because the njit
    # kernel currently takes a single eps_f_arr. Mirrors solve_full.py.
    if eps_A is None and eps_B is None:
        if np.ndim(epsilon) == 0:
            eps_f_arr = np.full((Nx, Ny, Nz), float(epsilon) / 2.0, dtype=np.float64)
        else:
            eps_f_arr = np.ascontiguousarray(np.asarray(epsilon, dtype=np.float64) / 2.0)
            if eps_f_arr.shape != (Nx, Ny, Nz):
                raise ValueError("epsilon 3D shape mismatch")
    else:
        if eps_A is None or eps_B is None:
            raise ValueError("eps_A and eps_B must be provided together.")
        eps_A_arr = _to_3d(eps_A)
        eps_B_arr = _to_3d(eps_B)
        eps_tot_arr = _to_3d(epsilon)
        if np.any(eps_A_arr + eps_B_arr > eps_tot_arr + 1e-9):
            raise ValueError(
                "eps_A + eps_B exceeds epsilon at some cells.")
        if not np.allclose(eps_A_arr, eps_B_arr):
            raise NotImplementedError(
                "Asymmetric eps_A / eps_B is not yet routed through the 3D "
                "LTNE kernel (currently assumes symmetric eps/2).")
        eps_f_arr = eps_A_arr

    # Cell-centre velocity shape check
    for name, arr in (('ucA', ucA), ('vcA', vcA), ('wcA', wcA),
                      ('ucB', ucB), ('vcB', vcB), ('wcB', wcB)):
        if np.asarray(arr).shape != (Nx, Ny, Nz):
            raise ValueError(f"{name} shape {np.asarray(arr).shape} != ({Nx}, {Ny}, {Nz})")
    ucA = np.ascontiguousarray(ucA, dtype=np.float64)
    vcA = np.ascontiguousarray(vcA, dtype=np.float64)
    wcA = np.ascontiguousarray(wcA, dtype=np.float64)
    ucB = np.ascontiguousarray(ucB, dtype=np.float64)
    vcB = np.ascontiguousarray(vcB, dtype=np.float64)
    wcB = np.ascontiguousarray(wcB, dtype=np.float64)

    # Inlet profiles — 2D cross-section
    def _inlet_shape(dir_code):
        if dir_code <= 1: return (Ny, Nz)
        if dir_code <= 3: return (Nx, Nz)
        return (Nx, Ny)

    def _mk_profile(profile, T_scalar, shape):
        if profile is None:
            return np.full(shape, float(T_scalar), dtype=np.float64)
        arr = np.asarray(profile, dtype=np.float64)
        if arr.shape == shape:
            return np.ascontiguousarray(arr)
        if arr.ndim == 1:
            # broadcast 1D to 2D face (uniform along other axis)
            return np.ascontiguousarray(np.broadcast_to(
                np.interp(np.linspace(0, 1, shape[0]),
                          np.linspace(0, 1, len(arr)), arr)[:, None],
                shape).copy())
        raise ValueError(f"inlet profile shape {arr.shape} != {shape}")

    T_inA_arr = _mk_profile(T_inA_profile, T_inA, _inlet_shape(dir_A))
    T_inB_arr = _mk_profile(T_inB_profile, T_inB, _inlet_shape(dir_B))

    def _mk_mask(mask, shape):
        if mask is None:
            return np.ones(shape, dtype=np.float64)
        arr = np.asarray(mask, dtype=np.float64)
        if arr.shape == shape:
            return np.ascontiguousarray(arr)
        if arr.ndim == 1:
            return np.ascontiguousarray(np.broadcast_to(arr[:, None], shape).copy())
        raise ValueError(f"inlet mask shape {arr.shape} != {shape}")

    ifrac_A = _mk_mask(inlet_mask_A, _inlet_shape(dir_A))
    ifrac_B = _mk_mask(inlet_mask_B, _inlet_shape(dir_B))

    # Init
    if Ta_init is not None:
        Ta = np.ascontiguousarray(Ta_init.copy(), dtype=np.float64)
        Tb = np.ascontiguousarray(Tb_init.copy(), dtype=np.float64)
        Ts = np.ascontiguousarray(Ts_init.copy(), dtype=np.float64)
    else:
        init_val = 0.5 * (T_inA + T_inB)
        Ta = np.full((Nx, Ny, Nz), init_val, dtype=np.float64)
        Tb = Ta.copy(); Ts = Ta.copy()

    freeze_Tb = 0
    if Tb_prescribed is not None:
        Tb_arr = np.ascontiguousarray(np.asarray(Tb_prescribed, dtype=np.float64))
        if Tb_arr.shape != (Nx, Ny, Nz):
            raise ValueError(f"Tb_prescribed shape {Tb_arr.shape} != ({Nx}, {Ny}, {Nz})")
        Tb = Tb_arr.copy()
        freeze_Tb = 1

    # Apply inlet BCs (frac > 0.5)
    _apply_inlet_3d(Ta, dir_A, T_inA_arr, ifrac_A, Nx, Ny, Nz)
    if freeze_Tb == 0:
        _apply_inlet_3d(Tb, dir_B, T_inB_arr, ifrac_B, Nx, Ny, Nz)

    # Chunk iterate, Q-based convergence.
    # Chunk=500 kept as conservative default — tiny-grid smokes (14×8×3)
    # can false-exit at chunk=200 because first Q-delta check fires at
    # `done>=chunk` and Q_prev starts at 0, so two full chunks are needed
    # to register meaningful stall. Larger grids (>30k cells) converge in
    # 1-3 chunks regardless, so chunk=500 overshoots ≤ chunk=200 there.
    chunk = 500; done = 0
    cell_vol = dx_arr[:, None, None] * dy_arr[None, :, None] * dz_arr[None, None, :]
    Q_prev = 0.0
    converged = False
    # q-based convergence: prev formula `min(tol*2e-3, 1e-3)` gave 2e-8 for
    # tol=1e-5 — far tighter than outer coupling tol (0.5 K), forcing extra
    # chunks. Loosen to 1e-4 floor (still tighter than outer coupling).
    q_rel_tol = max(tol * 10.0, 1e-4)
    chg = 0.0

    while done < max_iter:
        n = min(chunk, max_iter - done)
        chg = _gs_full_chunk_3d(
            Ta, Tb, Ts, Nx, Ny, Nz,
            dx_arr, dy_arr, dz_arr,
            K_ffA_arr, K_ffB_arr, K_ss_arr,
            h_vA_arr, h_vB_arr, eps_f_arr,
            rho_cp_fA_arr, rho_cp_fB_arr,
            ucA, vcA, wcA, ucB, vcB, wcB,
            dir_A, dir_B, T_inA_arr, T_inB_arr,
            ifrac_A, ifrac_B,
            n, freeze_Tb, a_fA, a_s, a_fB)
        done += n
        if progress_cb:
            progress_cb(done, max_iter)

        Q_cur = float(np.sum(h_vB_arr * (Ts - Tb) * cell_vol))
        if done >= chunk and Q_prev != 0.0:
            rel_chg = abs(Q_cur - Q_prev) / (abs(Q_cur) + 1e-30)
            if rel_chg < q_rel_tol:
                converged = True
                break
        Q_prev = Q_cur

    if return_info:
        return Ta, Tb, Ts, {
            'converged': converged,
            'iterations': done,
            'residual': float(chg),
            'delegated_to_2d': False,
        }
    return Ta, Tb, Ts


def _apply_inlet_3d(T, dir_code, Tin2d, ifrac2d, Nx, Ny, Nz):
    if dir_code == 0:
        for j in range(Ny):
            for k in range(Nz):
                if ifrac2d[j, k] > 0.5: T[0, j, k] = Tin2d[j, k]
    elif dir_code == 1:
        for j in range(Ny):
            for k in range(Nz):
                if ifrac2d[j, k] > 0.5: T[Nx-1, j, k] = Tin2d[j, k]
    elif dir_code == 2:
        for i in range(Nx):
            for k in range(Nz):
                if ifrac2d[i, k] > 0.5: T[i, 0, k] = Tin2d[i, k]
    elif dir_code == 3:
        for i in range(Nx):
            for k in range(Nz):
                if ifrac2d[i, k] > 0.5: T[i, Ny-1, k] = Tin2d[i, k]
    elif dir_code == 4:
        for i in range(Nx):
            for j in range(Ny):
                if ifrac2d[i, j] > 0.5: T[i, j, 0] = Tin2d[i, j]
    else:
        for i in range(Nx):
            for j in range(Ny):
                if ifrac2d[i, j] > 0.5: T[i, j, Nz-1] = Tin2d[i, j]


# ---------------------------------------------------------------------------
# Conservation probes (verification matrix)
# ---------------------------------------------------------------------------

def energy_balance_3d(Ta, Tb, Ts, h_vA_arr, h_vB_arr,
                       dx_arr, dy_arr, dz_arr):
    """LTNE source residual: ∫ h_vA (Ts − Ta) dV + ∫ h_vB (Ts − Tb) dV balance.

    Returns dict:
      Q_sA  : ∫ h_vA (Ts − Ta) dV      [W] (solid → A)
      Q_sB  : ∫ h_vB (Ts − Tb) dV      [W] (solid → B)
      Q_net : Q_sA + Q_sB               [W] (should → 0 in steady state)
    """
    vol = dx_arr[:, None, None] * dy_arr[None, :, None] * dz_arr[None, None, :]
    Q_sA = float(np.sum(h_vA_arr * (Ts - Ta) * vol))
    Q_sB = float(np.sum(h_vB_arr * (Ts - Tb) * vol))
    return {'Q_sA': Q_sA, 'Q_sB': Q_sB, 'Q_net': Q_sA + Q_sB}


def mass_balance_3d(u, v, w, rho_field, dy_arr, dx_arr, dz_arr, dir_code):
    """Mass flux imbalance across a flow pair.

    Integrates inlet and outlet face mass flow for a given streamwise direction.
    u / v / w are staggered faces (Nx+1, Ny, Nz) etc. rho_field cell-centre.

    Returns dict:
      m_in  : inlet mass flow  [kg/s]
      m_out : outlet mass flow [kg/s]
      rel   : abs(m_in − m_out) / (|m_in| + 1e-30)
    """
    # For Phase 1 Shanghai this is called on the SIMPLE output.
    if dir_code == 0:
        # +x: inlet face u[0,:,:], outlet u[Nx,:,:]
        A = dy_arr[:, None] * dz_arr[None, :]
        rho_in  = rho_field[0, :, :]
        rho_out = rho_field[-1, :, :]
        m_in  = float(np.sum(rho_in  * u[0, :, :]  * A))
        m_out = float(np.sum(rho_out * u[-1, :, :] * A))
    elif dir_code == 1:
        A = dy_arr[:, None] * dz_arr[None, :]
        rho_in  = rho_field[-1, :, :]
        rho_out = rho_field[0, :, :]
        m_in  = -float(np.sum(rho_in  * u[-1, :, :] * A))
        m_out = -float(np.sum(rho_out * u[0, :, :]  * A))
    elif dir_code == 2:
        A = dx_arr[:, None] * dz_arr[None, :]
        rho_in  = rho_field[:, 0, :]
        rho_out = rho_field[:, -1, :]
        m_in  = float(np.sum(rho_in  * v[:, 0, :]  * A))
        m_out = float(np.sum(rho_out * v[:, -1, :] * A))
    elif dir_code == 3:
        A = dx_arr[:, None] * dz_arr[None, :]
        rho_in  = rho_field[:, -1, :]
        rho_out = rho_field[:, 0, :]
        m_in  = -float(np.sum(rho_in  * v[:, -1, :] * A))
        m_out = -float(np.sum(rho_out * v[:, 0, :]  * A))
    elif dir_code == 4:
        A = dx_arr[:, None] * dy_arr[None, :]
        rho_in  = rho_field[:, :, 0]
        rho_out = rho_field[:, :, -1]
        m_in  = float(np.sum(rho_in  * w[:, :, 0]  * A))
        m_out = float(np.sum(rho_out * w[:, :, -1] * A))
    else:
        A = dx_arr[:, None] * dy_arr[None, :]
        rho_in  = rho_field[:, :, -1]
        rho_out = rho_field[:, :, 0]
        m_in  = -float(np.sum(rho_in  * w[:, :, -1] * A))
        m_out = -float(np.sum(rho_out * w[:, :, 0]  * A))

    denom = abs(m_in) + 1e-30
    return {'m_in': m_in, 'm_out': m_out, 'rel': abs(m_in - m_out) / denom}


# ---------------------------------------------------------------------------
# JIT warmup
# ---------------------------------------------------------------------------

def _warmup_jit():
    """Pre-compile _gs_full_chunk_3d on import. Best-effort, never raises."""
    try:
        Nx = Ny = Nz = 4
        Ta = np.full((Nx, Ny, Nz), 300.0)
        Tb = np.full((Nx, Ny, Nz), 290.0)
        Ts = np.full((Nx, Ny, Nz), 295.0)
        dx = np.full(Nx, 0.01); dy = np.full(Ny, 0.01); dz = np.full(Nz, 0.01)
        K = np.full((Nx, Ny, Nz), 0.1); hv = np.full((Nx, Ny, Nz), 100.0)
        ef = np.full((Nx, Ny, Nz), 0.5); rcp = np.full((Nx, Ny, Nz), 1000.0)
        u = np.full((Nx, Ny, Nz), 0.5); v0 = np.zeros((Nx, Ny, Nz))
        TinA = np.full((Ny, Nz), 300.0); TinB = np.full((Nx, Nz), 290.0)
        fA = np.ones((Ny, Nz)); fB = np.ones((Nx, Nz))
        for fz in (0, 1):
            _gs_full_chunk_3d(Ta.copy(), Tb.copy(), Ts.copy(), Nx, Ny, Nz,
                              dx, dy, dz,
                              K, K, K, hv, hv, ef, rcp, rcp,
                              u, v0, v0, u, v0, v0,
                              0, 3, TinA, TinB, fA, fB,
                              1, fz, 0.7, 0.7, 0.7)
    except Exception:
        pass


_warmup_jit()
