"""
ltne_energy.py — Full-domain steady-state 2-fluid LTNE solver

Solves the coupled energy equations on the ENTIRE L × H domain
using spatially-varying velocity fields from SIMPLE solvers.

Supports zone-based partitioning: per-cell K_ff, K_ss, h_v, eps_f
via 2D arrays. Uses harmonic-mean face conductivity at zone interfaces.

Energy equations (steady state, LTNE):
  eps_f * rho_cp_A * (u_Ax * dTa/dx + u_Ay * dTa/dy) = K_ffA * nabla²Ta + h_vA * (Ts - Ta)
  eps_f * rho_cp_B * (u_Bx * dTb/dx + u_By * dTb/dy) = K_ffB * nabla²Tb + h_vB * (Ts - Tb)
  0 = K_ss * nabla²Ts + h_vA * (Ta - Ts) + h_vB * (Tb - Ts)

Velocity fields u_Ax(x,y), u_Ay(x,y), u_Bx(x,y), u_By(x,y) come from
SIMPLE solver (cell-centre interpolated), not assumed uniform.

Cell-coupled Gauss-Seidel: at each cell, update Ta → Ts → Tb sequentially
so that coupling information propagates within a single sweep.
"""

import numpy as np
from sjtu_tpmshx.domain.cancellation import CancelledError
from numba import njit, prange
from ._kernels_2d import minmod


@njit(cache=True)
def _sou_corr_x(T, i, j, Nx, u_loc, Fx_field):
    """Second-order upwind deferred correction in x-direction.

    Net correction = (west-face SOU) - (east-face SOU). Each face's limiter is
    scaled by a FACE-AVERAGED convective flux ``F_face = 0.5*(Fx_P + Fx_nbr)``
    so the two cells sharing a face apply the IDENTICAL extra flux and the
    correction telescopes globally even when ``Fx = eps_f*rho_cp*|u|*dy`` varies
    between neighbours (audit fix: 2d-sou-not-conservative). For a uniform flux
    field this is bit-identical to the legacy ``0.5*Fx*(phi_w - phi_e)``.
    """
    Fp = Fx_field[i, j]
    Fe = 0.5 * (Fp + (Fx_field[i+1, j] if i < Nx - 1 else Fp))   # face i+1/2
    Fw = 0.5 * ((Fx_field[i-1, j] if i > 0 else Fp) + Fp)        # face i-1/2
    if u_loc >= 0:
        phi_w = 0.0
        if i > 1:
            phi_w = minmod(T[i-1,j] - T[i-2,j], T[i,j] - T[i-1,j])
        phi_e = 0.0
        if i < Nx - 1 and i > 0:
            phi_e = minmod(T[i,j] - T[i-1,j], T[i+1,j] - T[i,j])
        return 0.5 * (Fw * phi_w - Fe * phi_e)
    else:
        phi_e = 0.0
        if i < Nx - 2:
            phi_e = minmod(T[i+1,j] - T[i+2,j], T[i,j] - T[i+1,j])
        phi_w = 0.0
        if i > 0 and i < Nx - 1:
            phi_w = minmod(T[i,j] - T[i+1,j], T[i-1,j] - T[i,j])
        return 0.5 * (Fe * phi_e - Fw * phi_w)


@njit(cache=True)
def _sou_corr_y(T, i, j, Ny, v_loc, Fy_field):
    """Second-order upwind deferred correction in y-direction. Face-averaged
    flux (see :func:`_sou_corr_x`) so it telescopes on non-uniform fields."""
    Fp = Fy_field[i, j]
    Fn = 0.5 * (Fp + (Fy_field[i, j+1] if j < Ny - 1 else Fp))   # face j+1/2
    Fs = 0.5 * ((Fy_field[i, j-1] if j > 0 else Fp) + Fp)        # face j-1/2
    if v_loc >= 0:
        phi_s = 0.0
        if j > 1:
            phi_s = minmod(T[i,j-1] - T[i,j-2], T[i,j] - T[i,j-1])
        phi_n = 0.0
        if j < Ny - 1 and j > 0:
            phi_n = minmod(T[i,j] - T[i,j-1], T[i,j+1] - T[i,j])
        return 0.5 * (Fs * phi_s - Fn * phi_n)
    else:
        phi_n = 0.0
        if j < Ny - 2:
            phi_n = minmod(T[i,j+1] - T[i,j+2], T[i,j] - T[i,j+1])
        phi_s = 0.0
        if j > 0 and j < Ny - 1:
            phi_s = minmod(T[i,j] - T[i,j+1], T[i,j-1] - T[i,j])
        return 0.5 * (Fn * phi_n - Fs * phi_s)


@njit(cache=True)
def _gs_full_chunk(Ta, Tb, Ts, Nx, Ny, dx_arr, dy_arr,
                   K_ffA_arr, K_ffB_arr, K_ss_arr,
                   h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
                   rho_cp_fA, rho_cp_fB,
                   ucA, vcA, ucB, vcB,
                   bc_A, bc_B, T_inA_arr, T_inB_arr,
                   ifrac_A, ifrac_B,
                   n_iters, freeze_Tb, sou_B):
    """Cell-coupled Gauss-Seidel: at each cell update Ta → Ts → Tb.
    dx_arr: 1D [Nx], dy_arr: 1D [Ny] — non-uniform cell widths.

    A3 (2026-07-06) — shared-face convection: the upwind base flux is now
    the SIGNED shared-face flux Fe = 0.5*(F_P + F_E) (same face averaging
    as the SOU correction), so the two cells sharing a face apply the
    IDENTICAL flux — removing the cell-local |u|-magnitude mismatch that
    leaked enthalpy on non-uniform (eps*rho_cp*u) fields. The net signed
    outflow is deliberately NOT added to aP (Patankar mass-consistent /
    temperature-form): the governing LTNE equation is eps*rho_cp*u·grad(T)
    = div(F T) − T div(F), and with the 2D CELL-CENTRE interpolated
    velocities the discrete div(F) is nonzero, so keeping net_out would
    make a uniform temperature field a non-fixed-point (verified: it broke
    the isothermal outer-loop consistency test). The 3D staggered kernel
    can keep net_out because its face velocities are discretely
    divergence-free. Uniform-flux fields reproduce the legacy scheme
    exactly. ``sou_B`` (0/1) optionally enables the
    face-consistent SOU for fluid B — RE-TESTED 2026-07-06 (A3): even in
    the telescoping face-consistent form the B-side deferred correction
    still oscillates (residual plateaus ~1 K, serial/red-black fixed
    points differ ~0.4 K on a uniform counterflow case), confirming the
    2026-06-24 diagnosis that the instability is the deferred-correction
    fixed point on a near-isothermal high-rho_cp field, NOT the old
    non-conservative flux. Default stays OFF (accuracy cost documented
    <0.4% of Q); the conservative BASE flux above is the A3 fix.
    """
    max_chg = 0.0

    # Determine sweep direction: compromise between A and B
    # i-direction: follow A's preference
    if bc_A == 1:
        i0, i1, di = Nx - 1, -1, -1
    else:
        i0, i1, di = 0, Nx, 1
    # j-direction: follow B's preference
    if bc_B == 3:
        j0, j1, dj = Ny - 1, -1, -1
    else:
        j0, j1, dj = 0, Ny, 1

    # Per-cell convective flux fields (velocity / rho_cp / eps_f frozen
    # across the GS sweep). SIGNED fields drive the conservative face
    # fluxes; the SOU helpers take the ABS fields (their limiter branches
    # on the local velocity sign).
    FxA = np.empty((Nx, Ny)); FyA = np.empty((Nx, Ny))
    FxAs = np.empty((Nx, Ny)); FyAs = np.empty((Nx, Ny))
    FxB = np.empty((Nx, Ny)); FyB = np.empty((Nx, Ny))
    FxBs = np.empty((Nx, Ny)); FyBs = np.empty((Nx, Ny))
    for _i in range(Nx):
        for _j in range(Ny):
            _efr = eps_fA_arr[_i, _j] * rho_cp_fA[_i, _j]
            FxAs[_i, _j] = _efr * ucA[_i, _j] * dy_arr[_j]
            FyAs[_i, _j] = _efr * vcA[_i, _j] * dx_arr[_i]
            FxA[_i, _j] = abs(FxAs[_i, _j])
            FyA[_i, _j] = abs(FyAs[_i, _j])
            _efrB = eps_fB_arr[_i, _j] * rho_cp_fB[_i, _j]
            FxBs[_i, _j] = _efrB * ucB[_i, _j] * dy_arr[_j]
            FyBs[_i, _j] = _efrB * vcB[_i, _j] * dx_arr[_i]
            FxB[_i, _j] = abs(FxBs[_i, _j])
            FyB[_i, _j] = abs(FyBs[_i, _j])

    for _it in range(n_iters):
        max_chg = 0.0

        for i in range(i0, i1, di):
            for j in range(j0, j1, dj):

                # ── Update Fluid A ──
                is_inlet_A = ((bc_A == 0 and i == 0) or (bc_A == 1 and i == Nx-1) or
                              (bc_A == 2 and j == 0) or (bc_A == 3 and j == Ny-1))
                # Numerical regularisation at partial-width inlet cells.
                # Not a physical face-flux BC — for cells that are partly open
                # and partly covered by a wall (0.01 < inlet_frac < 0.99), T is
                # set by a linear blend between T_in and the first interior
                # neighbour. Fully open (frac > 0.99) pins T exactly to T_in.
                # Side-effect: T near partial-width edges inherits a small
                # bias from the interior neighbour. To replace with a rigorous
                # face-flux BC, rewrite as source term inside the non-inlet
                # branch below and drop this special-case.
                if is_inlet_A:
                    fidx = j if bc_A <= 1 else i
                    frac = ifrac_A[fidx]
                    if frac > 0.99:
                        if bc_A <= 1:
                            Ta[i, j] = T_inA_arr[j]
                        else:
                            Ta[i, j] = T_inA_arr[i]
                    elif frac > 0.01:
                        T_in_val = T_inA_arr[j] if bc_A <= 1 else T_inA_arr[i]
                        if bc_A == 0:   T_nbr = Ta[1, j]
                        elif bc_A == 1: T_nbr = Ta[Nx-2, j]
                        elif bc_A == 2: T_nbr = Ta[i, 1]
                        else:           T_nbr = Ta[i, Ny-2]
                        Ta[i, j] = frac * T_in_val + (1.0 - frac) * T_nbr
                else:
                    dxi = dx_arr[i]; dyj = dy_arr[j]
                    vol = dxi * dyj
                    K = K_ffA_arr[i, j]
                    hvA = h_vA_arr[i, j] * vol

                    # Face spacing δx_e = 0.5·(dx_P + dx_E) ensures conservative
                    # diffusion stencil — same value used by cell P (as east-flux)
                    # and cell E (as west-flux) at shared face. Old /dxi used cell
                    # P width only; non-uniform grids broke face-flux symmetry.
                    dxe = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                    dxw = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                    dyn = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                    dys = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                    dE = 2.0*K*K_ffA_arr[i+1,j]/(K+K_ffA_arr[i+1,j]+1e-30)*dyj/dxe if i < Nx-1 else 0.0
                    dW = 2.0*K*K_ffA_arr[i-1,j]/(K+K_ffA_arr[i-1,j]+1e-30)*dyj/dxw if i > 0 else 0.0
                    dN = 2.0*K*K_ffA_arr[i,j+1]/(K+K_ffA_arr[i,j+1]+1e-30)*dxi/dyn if j < Ny-1 else 0.0
                    dS = 2.0*K*K_ffA_arr[i,j-1]/(K+K_ffA_arr[i,j-1]+1e-30)*dxi/dys if j > 0 else 0.0

                    u_loc = ucA[i,j]; v_loc = vcA[i,j]
                    # A3: signed shared-face fluxes (arithmetic mean of the
                    # two cells' signed fluxes — identical value on both
                    # sides of a face ⇒ globally telescoping). Domain-edge
                    # faces fall back to the cell's own flux.
                    FxP = FxAs[i, j]; FyP = FyAs[i, j]
                    Fe = 0.5 * (FxP + (FxAs[i+1, j] if i < Nx-1 else FxP))
                    Fw = 0.5 * ((FxAs[i-1, j] if i > 0 else FxP) + FxP)
                    Fn = 0.5 * (FyP + (FyAs[i, j+1] if j < Ny-1 else FyP))
                    Fs = 0.5 * ((FyAs[i, j-1] if j > 0 else FyP) + FyP)
                    aE = dE + max(-Fe, 0.0)
                    aW = dW + max(Fw, 0.0)
                    aN = dN + max(-Fn, 0.0)
                    aS = dS + max(Fs, 0.0)

                    tE = Ta[i+1,j] if i < Nx-1 else Ta[i,j]
                    tW = Ta[i-1,j] if i > 0    else Ta[i,j]
                    tN = Ta[i,j+1] if j < Ny-1 else Ta[i,j]
                    tS = Ta[i,j-1] if j > 0    else Ta[i,j]

                    sou = (_sou_corr_x(Ta, i, j, Nx, u_loc, FxA)
                           + _sou_corr_y(Ta, i, j, Ny, v_loc, FyA))

                    aP = aE + aW + aN + aS + hvA
                    new = (aE*tE + aW*tW + aN*tN + aS*tS + hvA*Ts[i,j] + sou) / aP
                    chg = abs(new - Ta[i,j])
                    if chg > max_chg: max_chg = chg
                    Ta[i,j] = new

                # ── Update Solid (using just-updated Ta, old Tb) ──
                dxi = dx_arr[i]; dyj = dy_arr[j]
                vol_s = dxi * dyj
                Ks_loc = K_ss_arr[i, j]
                hvA_s = h_vA_arr[i, j] * vol_s
                hvB_s = h_vB_arr[i, j] * vol_s

                # Face spacing for solid diffusion stencil (conservative)
                dxe_s = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                dxw_s = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                dyn_s = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                dys_s = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                Ds_e = 2.0*Ks_loc*K_ss_arr[i+1,j]/(Ks_loc+K_ss_arr[i+1,j]+1e-30)*dyj/dxe_s if i < Nx-1 else Ks_loc*dyj/dxi
                Ds_w = 2.0*Ks_loc*K_ss_arr[i-1,j]/(Ks_loc+K_ss_arr[i-1,j]+1e-30)*dyj/dxw_s if i > 0    else Ks_loc*dyj/dxi
                Ds_n = 2.0*Ks_loc*K_ss_arr[i,j+1]/(Ks_loc+K_ss_arr[i,j+1]+1e-30)*dxi/dyn_s if j < Ny-1 else Ks_loc*dxi/dyj
                Ds_s = 2.0*Ks_loc*K_ss_arr[i,j-1]/(Ks_loc+K_ss_arr[i,j-1]+1e-30)*dxi/dys_s if j > 0    else Ks_loc*dxi/dyj

                sE = Ts[i+1,j] if i < Nx-1 else Ts[i,j]
                sW = Ts[i-1,j] if i > 0    else Ts[i,j]
                sN = Ts[i,j+1] if j < Ny-1 else Ts[i,j]
                sS = Ts[i,j-1] if j > 0    else Ts[i,j]

                aP_s = Ds_e + Ds_w + Ds_n + Ds_s + hvA_s + hvB_s
                new_s = (Ds_e*sE + Ds_w*sW + Ds_n*sN + Ds_s*sS + hvA_s*Ta[i,j] + hvB_s*Tb[i,j]) / aP_s
                chg = abs(new_s - Ts[i,j])
                if chg > max_chg: max_chg = chg
                Ts[i,j] = new_s

                # ── Update Fluid B (using just-updated Ts) ──
                # C-1: when freeze_Tb == 1, Tb is pinned to a prescribed field;
                # skip the entire B update. Solid equation still uses the pinned
                # Tb via hvB_s*Tb[i,j] above, so the air→solid→water coupling
                # remains intact.
                if freeze_Tb == 0:
                    is_inlet_B = ((bc_B == 0 and i == 0) or (bc_B == 1 and i == Nx-1) or
                                  (bc_B == 2 and j == 0) or (bc_B == 3 and j == Ny-1))
                    if is_inlet_B:
                        fidx_b = j if bc_B <= 1 else i
                        frac_b = ifrac_B[fidx_b]
                        if frac_b > 0.99:
                            if bc_B <= 1:
                                Tb[i, j] = T_inB_arr[j]
                            else:
                                Tb[i, j] = T_inB_arr[i]
                        elif frac_b > 0.01:
                            T_in_b = T_inB_arr[j] if bc_B <= 1 else T_inB_arr[i]
                            if bc_B == 0:   T_nbr_b = Tb[1, j]
                            elif bc_B == 1: T_nbr_b = Tb[Nx-2, j]
                            elif bc_B == 2: T_nbr_b = Tb[i, 1]
                            else:           T_nbr_b = Tb[i, Ny-2]
                            Tb[i, j] = frac_b * T_in_b + (1.0 - frac_b) * T_nbr_b
                    else:
                        dxi = dx_arr[i]; dyj = dy_arr[j]
                        vol_b = dxi * dyj
                        K = K_ffB_arr[i, j]
                        hvB = h_vB_arr[i, j] * vol_b

                        # Face spacing for B diffusion stencil (conservative)
                        dxe = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                        dxw = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                        dyn = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                        dys = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                        dE = 2.0*K*K_ffB_arr[i+1,j]/(K+K_ffB_arr[i+1,j]+1e-30)*dyj/dxe if i < Nx-1 else 0.0
                        dW = 2.0*K*K_ffB_arr[i-1,j]/(K+K_ffB_arr[i-1,j]+1e-30)*dyj/dxw if i > 0 else 0.0
                        dN = 2.0*K*K_ffB_arr[i,j+1]/(K+K_ffB_arr[i,j+1]+1e-30)*dxi/dyn if j < Ny-1 else 0.0
                        dS = 2.0*K*K_ffB_arr[i,j-1]/(K+K_ffB_arr[i,j-1]+1e-30)*dxi/dys if j > 0 else 0.0

                        u_loc = ucB[i,j]; v_loc = vcB[i,j]
                        # A3: conservative signed shared-face fluxes (see the
                        # fluid-A block).
                        FxP = FxBs[i, j]; FyP = FyBs[i, j]
                        Fe = 0.5 * (FxP + (FxBs[i+1, j] if i < Nx-1 else FxP))
                        Fw = 0.5 * ((FxBs[i-1, j] if i > 0 else FxP) + FxP)
                        Fn = 0.5 * (FyP + (FyBs[i, j+1] if j < Ny-1 else FyP))
                        Fs = 0.5 * ((FyBs[i, j-1] if j > 0 else FyP) + FyP)
                        aE = dE + max(-Fe, 0.0)
                        aW = dW + max(Fw, 0.0)
                        aN = dN + max(-Fn, 0.0)
                        aS = dS + max(Fs, 0.0)

                        tE = Tb[i+1,j] if i < Nx-1 else Tb[i,j]
                        tW = Tb[i-1,j] if i > 0    else Tb[i,j]
                        tN = Tb[i,j+1] if j < Ny-1 else Tb[i,j]
                        tS = Tb[i,j-1] if j > 0    else Tb[i,j]

                        # History: fluid-B SOU was disabled 2026-06-24 — the
                        # then NON-conservative correction injected spurious
                        # ρcp-scaled energy and destabilised the outer
                        # coupling at fine grids (water dT_B oscillated at
                        # N=80). A3 (2026-07-06) re-enables it in the
                        # face-consistent telescoping form, gated by sou_B
                        # (kill switch: solve_full_domain(use_sou_B=False)).
                        if sou_B == 1:
                            sou = (_sou_corr_x(Tb, i, j, Nx, u_loc, FxB)
                                   + _sou_corr_y(Tb, i, j, Ny, v_loc, FyB))
                        else:
                            sou = 0.0

                        aP = aE + aW + aN + aS + hvB
                        new = (aE*tE + aW*tW + aN*tN + aS*tS + hvB*Ts[i,j] + sou) / aP
                        chg = abs(new - Tb[i,j])
                        if chg > max_chg: max_chg = chg
                        Tb[i,j] = new

        # Outlet zero-gradient BCs
        if bc_A == 0:
            for j2 in range(Ny): Ta[Nx-1,j2] = Ta[Nx-2,j2]
        elif bc_A == 1:
            for j2 in range(Ny): Ta[0,j2] = Ta[1,j2]
        elif bc_A == 2:
            for i2 in range(Nx): Ta[i2,Ny-1] = Ta[i2,Ny-2]
        else:
            for i2 in range(Nx): Ta[i2,0] = Ta[i2,1]

        # C-1: skip Tb outlet BC copy when freeze_Tb == 1 (Tb is pinned)
        if freeze_Tb == 0:
            if bc_B == 0:
                for j2 in range(Ny): Tb[Nx-1,j2] = Tb[Nx-2,j2]
            elif bc_B == 1:
                for j2 in range(Ny): Tb[0,j2] = Tb[1,j2]
            elif bc_B == 2:
                for i2 in range(Nx): Tb[i2,Ny-1] = Tb[i2,Ny-2]
            else:
                for i2 in range(Nx): Tb[i2,0] = Tb[i2,1]

        if max_chg < 1e-10:
            break

    return max_chg


@njit(cache=True, parallel=True)
def _gs_full_chunk_rb(Ta, Tb, Ts, Nx, Ny, dx_arr, dy_arr,
                      K_ffA_arr, K_ffB_arr, K_ss_arr,
                      h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
                      rho_cp_fA, rho_cp_fB,
                      ucA, vcA, ucB, vcB,
                      bc_A, bc_B, T_inA_arr, T_inB_arr,
                      ifrac_A, ifrac_B,
                      n_iters, freeze_Tb, sou_B):
    """Red-black `prange`-parallel twin of `_gs_full_chunk` (2D).

    Same construction as the 3D `_gs_full_chunk_3d_stag_rb`: cells are swept by
    checkerboard colour (i+j parity) so same-colour cells update independently,
    and the 2-away SOU deferred correction is read from a start-of-sweep snapshot
    (the only same-colour dependency). Converges to the same field as the serial
    kernel; used on large 2D grids (> `_RB_ENERGY_2D_GATE`).
    """
    max_chg = 0.0
    ncell = Nx * Ny
    # Per-cell convective flux fields (frozen across the sweep). Signed
    # fields drive the conservative face fluxes; abs fields feed the SOU
    # helpers — see the serial kernel (A3 2026-07-06).
    FxA = np.empty((Nx, Ny)); FyA = np.empty((Nx, Ny))
    FxAs = np.empty((Nx, Ny)); FyAs = np.empty((Nx, Ny))
    FxB = np.empty((Nx, Ny)); FyB = np.empty((Nx, Ny))
    FxBs = np.empty((Nx, Ny)); FyBs = np.empty((Nx, Ny))
    for _ii in range(Nx):
        for _jj in range(Ny):
            _efr = eps_fA_arr[_ii, _jj] * rho_cp_fA[_ii, _jj]
            FxAs[_ii, _jj] = _efr * ucA[_ii, _jj] * dy_arr[_jj]
            FyAs[_ii, _jj] = _efr * vcA[_ii, _jj] * dx_arr[_ii]
            FxA[_ii, _jj] = abs(FxAs[_ii, _jj])
            FyA[_ii, _jj] = abs(FyAs[_ii, _jj])
            _efrB = eps_fB_arr[_ii, _jj] * rho_cp_fB[_ii, _jj]
            FxBs[_ii, _jj] = _efrB * ucB[_ii, _jj] * dy_arr[_jj]
            FyBs[_ii, _jj] = _efrB * vcB[_ii, _jj] * dx_arr[_ii]
            FxB[_ii, _jj] = abs(FxBs[_ii, _jj])
            FyB[_ii, _jj] = abs(FyBs[_ii, _jj])
    for _it in range(n_iters):
        Ta_snap = Ta.copy()
        Tb_snap = Tb.copy()
        sweep_chg = 0.0
        for color in range(2):
            color_chg = 0.0
            for idx in prange(ncell):
                i = idx // Ny
                j = idx - i * Ny
                if ((i + j) & 1) != color:
                    continue
                cell_chg = 0.0

                # ── Fluid A ──
                is_inlet_A = ((bc_A == 0 and i == 0) or (bc_A == 1 and i == Nx-1) or
                              (bc_A == 2 and j == 0) or (bc_A == 3 and j == Ny-1))
                if is_inlet_A:
                    fidx = j if bc_A <= 1 else i
                    frac = ifrac_A[fidx]
                    if frac > 0.99:
                        if bc_A <= 1:
                            Ta[i, j] = T_inA_arr[j]
                        else:
                            Ta[i, j] = T_inA_arr[i]
                    elif frac > 0.01:
                        T_in_val = T_inA_arr[j] if bc_A <= 1 else T_inA_arr[i]
                        if bc_A == 0:   T_nbr = Ta[1, j]
                        elif bc_A == 1: T_nbr = Ta[Nx-2, j]
                        elif bc_A == 2: T_nbr = Ta[i, 1]
                        else:           T_nbr = Ta[i, Ny-2]
                        Ta[i, j] = frac * T_in_val + (1.0 - frac) * T_nbr
                else:
                    dxi = dx_arr[i]; dyj = dy_arr[j]
                    vol = dxi * dyj
                    K = K_ffA_arr[i, j]
                    hvA = h_vA_arr[i, j] * vol
                    dxe = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                    dxw = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                    dyn = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                    dys = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                    dE = 2.0*K*K_ffA_arr[i+1,j]/(K+K_ffA_arr[i+1,j]+1e-30)*dyj/dxe if i < Nx-1 else 0.0
                    dW = 2.0*K*K_ffA_arr[i-1,j]/(K+K_ffA_arr[i-1,j]+1e-30)*dyj/dxw if i > 0 else 0.0
                    dN = 2.0*K*K_ffA_arr[i,j+1]/(K+K_ffA_arr[i,j+1]+1e-30)*dxi/dyn if j < Ny-1 else 0.0
                    dS = 2.0*K*K_ffA_arr[i,j-1]/(K+K_ffA_arr[i,j-1]+1e-30)*dxi/dys if j > 0 else 0.0
                    u_loc = ucA[i,j]; v_loc = vcA[i,j]
                    # A3: conservative signed shared-face fluxes (serial twin).
                    FxP = FxAs[i, j]; FyP = FyAs[i, j]
                    Fe = 0.5 * (FxP + (FxAs[i+1, j] if i < Nx-1 else FxP))
                    Fw = 0.5 * ((FxAs[i-1, j] if i > 0 else FxP) + FxP)
                    Fn = 0.5 * (FyP + (FyAs[i, j+1] if j < Ny-1 else FyP))
                    Fs = 0.5 * ((FyAs[i, j-1] if j > 0 else FyP) + FyP)
                    aE = dE + max(-Fe, 0.0)
                    aW = dW + max(Fw, 0.0)
                    aN = dN + max(-Fn, 0.0)
                    aS = dS + max(Fs, 0.0)
                    tE = Ta[i+1,j] if i < Nx-1 else Ta[i,j]
                    tW = Ta[i-1,j] if i > 0    else Ta[i,j]
                    tN = Ta[i,j+1] if j < Ny-1 else Ta[i,j]
                    tS = Ta[i,j-1] if j > 0    else Ta[i,j]
                    sou = (_sou_corr_x(Ta_snap, i, j, Nx, u_loc, FxA)
                           + _sou_corr_y(Ta_snap, i, j, Ny, v_loc, FyA))
                    aP = aE + aW + aN + aS + hvA
                    new = (aE*tE + aW*tW + aN*tN + aS*tS + hvA*Ts[i,j] + sou) / aP
                    c = abs(new - Ta[i,j])
                    if c > cell_chg: cell_chg = c
                    Ta[i,j] = new

                # ── Solid ──
                dxi = dx_arr[i]; dyj = dy_arr[j]
                vol_s = dxi * dyj
                Ks_loc = K_ss_arr[i, j]
                hvA_s = h_vA_arr[i, j] * vol_s
                hvB_s = h_vB_arr[i, j] * vol_s
                dxe_s = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                dxw_s = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                dyn_s = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                dys_s = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                Ds_e = 2.0*Ks_loc*K_ss_arr[i+1,j]/(Ks_loc+K_ss_arr[i+1,j]+1e-30)*dyj/dxe_s if i < Nx-1 else Ks_loc*dyj/dxi
                Ds_w = 2.0*Ks_loc*K_ss_arr[i-1,j]/(Ks_loc+K_ss_arr[i-1,j]+1e-30)*dyj/dxw_s if i > 0    else Ks_loc*dyj/dxi
                Ds_n = 2.0*Ks_loc*K_ss_arr[i,j+1]/(Ks_loc+K_ss_arr[i,j+1]+1e-30)*dxi/dyn_s if j < Ny-1 else Ks_loc*dxi/dyj
                Ds_s = 2.0*Ks_loc*K_ss_arr[i,j-1]/(Ks_loc+K_ss_arr[i,j-1]+1e-30)*dxi/dys_s if j > 0    else Ks_loc*dxi/dyj
                sE = Ts[i+1,j] if i < Nx-1 else Ts[i,j]
                sW = Ts[i-1,j] if i > 0    else Ts[i,j]
                sN = Ts[i,j+1] if j < Ny-1 else Ts[i,j]
                sS = Ts[i,j-1] if j > 0    else Ts[i,j]
                aP_s = Ds_e + Ds_w + Ds_n + Ds_s + hvA_s + hvB_s
                new_s = (Ds_e*sE + Ds_w*sW + Ds_n*sN + Ds_s*sS + hvA_s*Ta[i,j] + hvB_s*Tb[i,j]) / aP_s
                c = abs(new_s - Ts[i,j])
                if c > cell_chg: cell_chg = c
                Ts[i,j] = new_s

                # ── Fluid B ──
                if freeze_Tb == 0:
                    is_inlet_B = ((bc_B == 0 and i == 0) or (bc_B == 1 and i == Nx-1) or
                                  (bc_B == 2 and j == 0) or (bc_B == 3 and j == Ny-1))
                    if is_inlet_B:
                        fidx_b = j if bc_B <= 1 else i
                        frac_b = ifrac_B[fidx_b]
                        if frac_b > 0.99:
                            if bc_B <= 1:
                                Tb[i, j] = T_inB_arr[j]
                            else:
                                Tb[i, j] = T_inB_arr[i]
                        elif frac_b > 0.01:
                            T_in_b = T_inB_arr[j] if bc_B <= 1 else T_inB_arr[i]
                            if bc_B == 0:   T_nbr_b = Tb[1, j]
                            elif bc_B == 1: T_nbr_b = Tb[Nx-2, j]
                            elif bc_B == 2: T_nbr_b = Tb[i, 1]
                            else:           T_nbr_b = Tb[i, Ny-2]
                            Tb[i, j] = frac_b * T_in_b + (1.0 - frac_b) * T_nbr_b
                    else:
                        dxi = dx_arr[i]; dyj = dy_arr[j]
                        vol_b = dxi * dyj
                        K = K_ffB_arr[i, j]
                        hvB = h_vB_arr[i, j] * vol_b
                        dxe = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                        dxw = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                        dyn = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                        dys = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                        dE = 2.0*K*K_ffB_arr[i+1,j]/(K+K_ffB_arr[i+1,j]+1e-30)*dyj/dxe if i < Nx-1 else 0.0
                        dW = 2.0*K*K_ffB_arr[i-1,j]/(K+K_ffB_arr[i-1,j]+1e-30)*dyj/dxw if i > 0 else 0.0
                        dN = 2.0*K*K_ffB_arr[i,j+1]/(K+K_ffB_arr[i,j+1]+1e-30)*dxi/dyn if j < Ny-1 else 0.0
                        dS = 2.0*K*K_ffB_arr[i,j-1]/(K+K_ffB_arr[i,j-1]+1e-30)*dxi/dys if j > 0 else 0.0
                        u_loc = ucB[i,j]; v_loc = vcB[i,j]
                        # A3: conservative signed shared-face fluxes; SOU
                        # re-enabled in face-consistent form, gated by sou_B
                        # (see the serial kernel for the 2026-06-24 history).
                        FxP = FxBs[i, j]; FyP = FyBs[i, j]
                        Fe = 0.5 * (FxP + (FxBs[i+1, j] if i < Nx-1 else FxP))
                        Fw = 0.5 * ((FxBs[i-1, j] if i > 0 else FxP) + FxP)
                        Fn = 0.5 * (FyP + (FyBs[i, j+1] if j < Ny-1 else FyP))
                        Fs = 0.5 * ((FyBs[i, j-1] if j > 0 else FyP) + FyP)
                        aE = dE + max(-Fe, 0.0)
                        aW = dW + max(Fw, 0.0)
                        aN = dN + max(-Fn, 0.0)
                        aS = dS + max(Fs, 0.0)
                        tE = Tb[i+1,j] if i < Nx-1 else Tb[i,j]
                        tW = Tb[i-1,j] if i > 0    else Tb[i,j]
                        tN = Tb[i,j+1] if j < Ny-1 else Tb[i,j]
                        tS = Tb[i,j-1] if j > 0    else Tb[i,j]
                        if sou_B == 1:
                            sou = (_sou_corr_x(Tb_snap, i, j, Nx, u_loc, FxB)
                                   + _sou_corr_y(Tb_snap, i, j, Ny, v_loc, FyB))
                        else:
                            sou = 0.0
                        aP = aE + aW + aN + aS + hvB
                        new = (aE*tE + aW*tW + aN*tN + aS*tS + hvB*Ts[i,j] + sou) / aP
                        c = abs(new - Tb[i,j])
                        if c > cell_chg: cell_chg = c
                        Tb[i,j] = new

                color_chg = max(color_chg, cell_chg)
            if color_chg > sweep_chg:
                sweep_chg = color_chg

        # Outlet zero-gradient BCs
        if bc_A == 0:
            for j2 in range(Ny): Ta[Nx-1,j2] = Ta[Nx-2,j2]
        elif bc_A == 1:
            for j2 in range(Ny): Ta[0,j2] = Ta[1,j2]
        elif bc_A == 2:
            for i2 in range(Nx): Ta[i2,Ny-1] = Ta[i2,Ny-2]
        else:
            for i2 in range(Nx): Ta[i2,0] = Ta[i2,1]
        if freeze_Tb == 0:
            if bc_B == 0:
                for j2 in range(Ny): Tb[Nx-1,j2] = Tb[Nx-2,j2]
            elif bc_B == 1:
                for j2 in range(Ny): Tb[0,j2] = Tb[1,j2]
            elif bc_B == 2:
                for i2 in range(Nx): Tb[i2,Ny-1] = Tb[i2,Ny-2]
            else:
                for i2 in range(Nx): Tb[i2,0] = Tb[i2,1]

        max_chg = sweep_chg
        if max_chg < 1e-10:
            break

    return max_chg


# Diagnostic-only convergence trace (point 0 quantify, 2026-05-22) — mirrors
# ltne_energy_3d._CONV_TRACE. None in production → zero overhead.
_CONV_TRACE = None

# Red-black parallel 2D energy kernel selector (mirrors ltne_energy_3d).
# OPT-IN (default off): the 2D cell-centre SOU (`_sou_corr_x/y`, minmod limiter)
# is now globally conservative (face-consistent flux since 2026-06-25), but the
# RB kernel still reads the 2-away SOU stencil from a start-of-sweep snapshot,
# and that lag is more sensitive here than the 3D face-shared deferred form
# (which matches serial to ~1e-5 K), so the RB converged field can differ from
# serial by
# ~0.1 K on strongly-advective cases (still <0.03% of T, Q-negligible). 2D grids
# are also usually < the gate (so RB rarely fires anyway). Enable explicitly
# (`_RB_ENERGY_2D = True`) for large 2D runs where the small difference is
# acceptable. The 3D path is default-on because its conservative kernel is clean.
_RB_ENERGY_2D = False
_RB_ENERGY_2D_GATE = 30_000


def solve_full_domain(L, H, Nx, Ny,
                      T_inA, T_inB,
                      K_ffA, K_ffB, K_ss,
                      h_vA, h_vB,
                      rho_cp_fA, rho_cp_fB,
                      epsilon,
                      ucA, vcA, ucB, vcB,
                      dir_A, dir_B,
                      T_inA_profile=None, T_inB_profile=None,
                      max_iter=50000, tol=1e-6,
                      progress_cb=None, return_info=False,
                      Ta_init=None, Tb_init=None, Ts_init=None,
                      dx_arr=None, dy_arr=None,
                      inlet_mask_A=None, inlet_mask_B=None,
                      Tb_prescribed=None,
                      eps_A=None, eps_B=None,
                      q_rel_tol=None, conv_chunk=None,
                      use_sou_B=False, cancel_check=None):
    """Full-domain steady-state 2-fluid LTNE solver.

    q_rel_tol : float or None — per-chunk Q-relative convergence threshold.
                None (default) keeps the legacy `min(tol*2e-3, 1e-3)` (very
                tight, rarely fires → runs to max_iter). Callers that only need
                a converged field (e.g. the design sizing tool) can pass a
                looser, effective value (e.g. 1e-4) so the solve early-stops at
                true convergence instead of burning max_iter.
    conv_chunk : int or None — GS sweeps between convergence checks. None →
                legacy 500. A smaller value (e.g. 100) lets the early-stop
                trigger sooner. Default None preserves bitwise legacy behaviour.

    Parameters
    ----------
    K_ffA, K_ffB, K_ss : scalar or 2D array (Nx, Ny)
    h_vA, h_vB         : scalar or 2D array (Nx, Ny)
    epsilon             : scalar or 2D array (Nx, Ny)
    ucA, vcA : 2D arrays (Nx, Ny) — Fluid A cell-centre x/y velocity
    ucB, vcB : 2D arrays (Nx, Ny) — Fluid B cell-centre x/y velocity
    dir_A, dir_B : int — flow direction (0=+x, 1=-x, 2=+y, 3=-y)
    return_info : bool — if True, return (Ta, Tb, Ts, info_dict)
    Ta_init, Tb_init, Ts_init : 2D arrays (Nx, Ny) — warm-start initial guess
    Tb_prescribed : 2D array (Nx, Ny) or None
        If provided, Tb is pinned to this field and NOT updated by the solver.
        Solid equation still couples via h_vB·(Tb − Ts). Use for validation
        cases where the water-side temperature is measured and should be
        imposed rather than solved.

    Returns
    -------
    Ta, Tb, Ts : 2D arrays (Nx, Ny)
    info : dict (only if return_info=True) — convergence metadata
    """
    Nx, Ny = int(Nx), int(Ny)
    # Non-uniform grid: use provided arrays or generate uniform
    if dx_arr is None:
        dx_arr = np.full(Nx, L / Nx, dtype=np.float64)
    else:
        dx_arr = np.ascontiguousarray(dx_arr, dtype=np.float64)
    if dy_arr is None:
        dy_arr = np.full(Ny, H / Ny, dtype=np.float64)
    else:
        dy_arr = np.ascontiguousarray(dy_arr, dtype=np.float64)

    # Promote scalars to uniform 2D arrays
    def _to_2d(val, Nx, Ny):
        if np.ndim(val) == 0:
            return np.full((Nx, Ny), float(val), dtype=np.float64)
        return np.ascontiguousarray(np.asarray(val, dtype=np.float64))

    K_ffA_arr = _to_2d(K_ffA, Nx, Ny)
    K_ffB_arr = _to_2d(K_ffB, Nx, Ny)
    K_ss_arr  = _to_2d(K_ss,  Nx, Ny)
    h_vA_arr  = _to_2d(h_vA,  Nx, Ny)
    h_vB_arr  = _to_2d(h_vB,  Nx, Ny)
    rho_cp_fA_arr = _to_2d(rho_cp_fA, Nx, Ny)
    rho_cp_fB_arr = _to_2d(rho_cp_fB, Nx, Ny)

    # Per-fluid void-fraction split. Default is symmetric 50/50
    # (ε_A = ε_B = ε/2) — matches symmetric bicontinuous sheet TPMS.
    #
    # **eps_A / eps_B kwargs are private hooks, NOT a public API** — they
    # carry distinct per-side void fractions ε_A, ε_B (offset-isosurface δ)
    # already split UPSTREAM in the pipeline so they sum to ε; the kernel
    # consumes them without re-halving (mirrors the 3D asym path). The UI /
    # optimizer never pass them and get the symmetric ε/2 split below.
    # The kernel takes eps_fA_arr / eps_fB_arr; the symmetric path passes the
    # SAME array object to both sides so δ=0 is bit-identical (golden gate).
    if eps_A is None and eps_B is None:
        if np.ndim(epsilon) == 0:
            eps_f_arr = np.full((Nx, Ny), 0.5 * float(epsilon), dtype=np.float64)
        else:
            eps_f_arr = np.ascontiguousarray(
                0.5 * np.asarray(epsilon, dtype=np.float64))
        eps_fA_arr = eps_f_arr
        eps_fB_arr = eps_f_arr   # same object → bit-identical to legacy
    else:
        if eps_A is None or eps_B is None:
            raise ValueError("eps_A and eps_B must be provided together.")
        eps_A_arr = _to_2d(eps_A, Nx, Ny)
        eps_B_arr = _to_2d(eps_B, Nx, Ny)
        eps_tot_arr = _to_2d(epsilon, Nx, Ny)
        # Two-sided (2026-07-13 audit): a sum BELOW ε is just as wrong as one
        # above it — accidentally pre-halved per-side values (the historical
        # double-halving bug class) used to sail through the one-sided check
        # with half the convective capacity.
        if np.any(np.abs(eps_A_arr + eps_B_arr - eps_tot_arr) > 1e-9):
            raise ValueError(
                "eps_A + eps_B must equal epsilon cell-wise (they partition "
                "the total void fraction). A sum above ε over-fills the void; "
                "a sum below it usually means the caller passed PRE-HALVED "
                "per-side values (double-halving bug class).")
        # Asymmetric ε_A ≠ ε_B is now routed per-side through the kernel: fluid
        # A's convection is weighted by ε_A, fluid B's by ε_B. A symmetric
        # explicit input (ε_A = ε_B = ε/2) reproduces the default path because
        # the two arrays carry the same values.
        eps_fA_arr = eps_A_arr
        eps_fB_arr = eps_B_arr

    # Inlet boundary codes
    bc_A = dir_A
    bc_B = dir_B

    # Build inlet profiles
    def _arr(profile, T_scalar, n):
        if profile is not None:
            a = np.asarray(profile, dtype=np.float64)
            if len(a) != n:
                a = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(a)), a)
            return a
        return np.full(n, T_scalar)

    nA = Ny if dir_A <= 1 else Nx
    nB = Ny if dir_B <= 1 else Nx
    T_inA_arr = _arr(T_inA_profile, T_inA, nA)
    T_inB_arr = _arr(T_inB_profile, T_inB, nB)

    # Inlet fractions: continuous 0-1 for smooth blending at wall/open transition
    if inlet_mask_A is None:
        ifrac_A = np.ones(nA, dtype=np.float64)
    else:
        ifrac_A = np.ascontiguousarray(np.asarray(inlet_mask_A, dtype=np.float64))
    if inlet_mask_B is None:
        ifrac_B = np.ones(nB, dtype=np.float64)
    else:
        ifrac_B = np.ascontiguousarray(np.asarray(inlet_mask_B, dtype=np.float64))

    # Initialise (warm start if provided)
    if Ta_init is not None:
        Ta = np.ascontiguousarray(Ta_init.copy(), dtype=np.float64)
        Tb = np.ascontiguousarray(Tb_init.copy(), dtype=np.float64)
        Ts = np.ascontiguousarray(Ts_init.copy(), dtype=np.float64)
    else:
        # Per-fluid cold-start seed (Ta=T_inA, Tb=T_inB), matching the 3D kernel
        # and the 2D caller's documented intent (pipelines/solve_2d.py, the
        # T_s_init warm-start block in _run_solvers).
        # The old 0.5*(T_inA+T_inB) seed for ALL THREE left partial-inlet
        # off-pipe cells (inlet frac<=0.01, never updated by a governing
        # equation — see the inlet branch above) FROZEN at the mid-T, which
        # diffuses back through the solid h_v coupling as a virtual heat source
        # (~12-18% Q_A / ~14K T_out_B on partial-B cross-flow geometries; audit
        # 2026-06-28, found by the ultracode workflow). Full-face / prescribed-Tb
        # paths are seed-independent at convergence (no frozen cells) → unchanged.
        # Ts keeps the 0.5-mean (solid sits between the streams); its energy
        # equation updates it every sweep regardless.
        Ta = np.full((Nx, Ny), float(T_inA))
        Tb = np.full((Nx, Ny), float(T_inB))
        Ts = np.full((Nx, Ny), 0.5 * (T_inA + T_inB))

    # C-1: if a prescribed Tb field is provided, pin Tb to it
    freeze_Tb = 0
    if Tb_prescribed is not None:
        Tb_arr = np.ascontiguousarray(np.asarray(Tb_prescribed, dtype=np.float64))
        if Tb_arr.shape != (Nx, Ny):
            raise ValueError(
                f"Tb_prescribed shape {Tb_arr.shape} != expected ({Nx}, {Ny})"
            )
        Tb = Tb_arr.copy()
        freeze_Tb = 1

    # Apply inlet BCs with continuous blending (frac > 0.5 gets T_in)
    if bc_A == 0:
        for j in range(Ny):
            if ifrac_A[j] > 0.5: Ta[0, j] = T_inA_arr[j]
    elif bc_A == 1:
        for j in range(Ny):
            if ifrac_A[j] > 0.5: Ta[Nx-1, j] = T_inA_arr[j]
    elif bc_A == 2:
        for i in range(Nx):
            if ifrac_A[i] > 0.5: Ta[i, 0] = T_inA_arr[i]
    else:
        for i in range(Nx):
            if ifrac_A[i] > 0.5: Ta[i, Ny-1] = T_inA_arr[i]

    # C-1: skip Tb inlet BC initialisation when freeze_Tb == 1 (Tb is pinned)
    if freeze_Tb == 0:
        if bc_B == 0:
            for j in range(Ny):
                if ifrac_B[j] > 0.5: Tb[0, j] = T_inB_arr[j]
        elif bc_B == 1:
            for j in range(Ny):
                if ifrac_B[j] > 0.5: Tb[Nx-1, j] = T_inB_arr[j]
        elif bc_B == 2:
            for i in range(Nx):
                if ifrac_B[i] > 0.5: Tb[i, 0] = T_inB_arr[i]
        else:
            for i in range(Nx):
                if ifrac_B[i] > 0.5: Tb[i, Ny-1] = T_inB_arr[i]

    # Iterate in chunks. Convergence uses AND of three criteria (#6):
    #   (1) relative change in Q_B interface integral  < q_rel_tol
    #   (2) max|ΔTa|, max|ΔTb|, max|ΔTs| between chunks < T_rel_tol·|T|
    # Q-only could flag converged while T-fields were still drifting
    # (rho = P/(R·T) damps T swings at fixed Q). T-only is grid-dependent.
    chunk = 500 if conv_chunk is None else int(conv_chunk);  done = 0
    cell_area = dx_arr[:, None] * dy_arr[None, :]
    Q_prev = 0.0
    Ta_prev = Ta.copy(); Tb_prev = Tb.copy(); Ts_prev = Ts.copy()
    converged = False
    q_tol = min(tol * 2e-3, 1e-3) if q_rel_tol is None else float(q_rel_tol)
    T_abs_tol = 0.01  # K between chunks
    # 2026-05-20 code-bug sweep (Tier 23): pre-init `chg` so the
    # `return_info` path (L551 `float(chg)`) cannot hit NameError when
    # the while loop never executes (max_iter <= 0). ltne_energy_3d.py
    # already guards this; mirror it here.
    chg = 0.0

    _use_rb = _RB_ENERGY_2D and (Nx * Ny > _RB_ENERGY_2D_GATE)
    _gs_fn = _gs_full_chunk_rb if _use_rb else _gs_full_chunk
    while done < max_iter:
        if cancel_check is not None and cancel_check():
            raise CancelledError("compute cancelled by user")
        n = min(chunk, max_iter - done)
        chg = _gs_fn(
            Ta, Tb, Ts, Nx, Ny, dx_arr, dy_arr,
            K_ffA_arr, K_ffB_arr, K_ss_arr,
            h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
            rho_cp_fA_arr, rho_cp_fB_arr,
            ucA, vcA, ucB, vcB,
            bc_A, bc_B, T_inA_arr, T_inB_arr,
            ifrac_A, ifrac_B,
            n, freeze_Tb, 1 if use_sou_B else 0)
        done += n
        if progress_cb:
            progress_cb(done, max_iter)
        if cancel_check is not None and cancel_check():
            raise CancelledError("compute cancelled by user")

        Q_cur = float(np.sum(h_vB_arr * (Ts - Tb) * cell_area))
        dTa_max = float(np.max(np.abs(Ta - Ta_prev)))
        dTb_max = float(np.max(np.abs(Tb - Tb_prev)))
        dTs_max = float(np.max(np.abs(Ts - Ts_prev)))
        if _CONV_TRACE is not None:
            _rc = (abs(Q_cur - Q_prev) / (abs(Q_cur) + 1e-30)
                   if (done >= chunk and Q_prev != 0.0) else float('nan'))
            _CONV_TRACE.append((done, _rc,
                                max(dTa_max, dTb_max, dTs_max),
                                float(np.mean(np.abs(Tb - Tb_prev))),
                                Q_cur))
        if done >= chunk and Q_prev != 0.0:
            rel_chg = abs(Q_cur - Q_prev) / (abs(Q_cur) + 1e-30)
            T_ok = (dTa_max < T_abs_tol and dTb_max < T_abs_tol
                    and dTs_max < T_abs_tol)
            if rel_chg < q_tol and T_ok:
                converged = True
                break
        Q_prev = Q_cur
        Ta_prev = Ta.copy(); Tb_prev = Tb.copy(); Ts_prev = Ts.copy()

    if return_info:
        return Ta, Tb, Ts, {
            'converged': converged,
            'iterations': done,
            'residual': float(chg),
        }
    return Ta, Tb, Ts


def _warmup_jit():
    """Pre-compile _gs_full_chunk on module import.

    Triggers JIT compilation with a tiny 4x4 dummy problem so the first real
    call doesn't pay the ~15-60 second compilation cost. Failures are
    silently caught — we never block module import on a warmup hiccup.
    """
    try:
        import numpy as _np
        _Nx, _Ny = 4, 4
        _Ta = _np.full((_Nx, _Ny), 300.0, dtype=_np.float64)
        _Tb = _np.full((_Nx, _Ny), 290.0, dtype=_np.float64)
        _Ts = _np.full((_Nx, _Ny), 295.0, dtype=_np.float64)
        _dx = _np.full(_Nx, 0.01, dtype=_np.float64)
        _dy = _np.full(_Ny, 0.01, dtype=_np.float64)
        _K = _np.full((_Nx, _Ny), 0.1, dtype=_np.float64)
        _hv = _np.full((_Nx, _Ny), 100.0, dtype=_np.float64)
        _ef = _np.full((_Nx, _Ny), 0.5, dtype=_np.float64)
        _rcp = _np.full((_Nx, _Ny), 1000.0, dtype=_np.float64)
        _u = _np.full((_Nx, _Ny), 0.5, dtype=_np.float64)
        _v = _np.zeros((_Nx, _Ny), dtype=_np.float64)
        # dir_A=0 => inlet at i=0, T_inA_arr len = Ny
        # dir_B=3 => inlet at j=Ny-1, T_inB_arr len = Nx
        _TinA = _np.full(_Ny, 300.0, dtype=_np.float64)
        _TinB = _np.full(_Nx, 290.0, dtype=_np.float64)
        _fracA = _np.ones(_Ny, dtype=_np.float64)
        _fracB = _np.ones(_Nx, dtype=_np.float64)
        # Compile path 1: freeze_Tb=0 (normal coupled solve, sou_B on)
        _gs_full_chunk(_Ta.copy(), _Tb.copy(), _Ts.copy(),
                       _Nx, _Ny, _dx, _dy,
                       _K, _K, _K, _hv, _hv, _ef, _ef, _rcp, _rcp,
                       _u, _v, _u, _v,
                       0, 3, _TinA, _TinB, _fracA, _fracB,
                       1, 0, 1)
        # Compile path 2: freeze_Tb=1 (C-1 prescribed-Tb path)
        _gs_full_chunk(_Ta.copy(), _Tb.copy(), _Ts.copy(),
                       _Nx, _Ny, _dx, _dy,
                       _K, _K, _K, _hv, _hv, _ef, _ef, _rcp, _rcp,
                       _u, _v, _u, _v,
                       0, 3, _TinA, _TinB, _fracA, _fracB,
                       1, 1, 1)
    except Exception:
        pass  # warmup is best-effort; never block import


_warmup_jit()
