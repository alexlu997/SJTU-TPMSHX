"""
ltne_energy_3d.py — Full-domain 3D steady-state 2-fluid LTNE solver

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
from numba import njit, prange

from solvers.ltne_energy import solve_full_domain as _solve_full_2d


# ---------------------------------------------------------------------------
# Helmholtz/MAC divergence cleaner (B-plan B2)
# ---------------------------------------------------------------------------

# Relative-divergence threshold below which a face field is treated as already
# solenoidal and the projection solve is skipped (forward-dir fluids).
_PROJ_SKIP_TOL = 1e-9

# Cache: grid shape (Nx,Ny,Nz) -> {'L': graph Laplacian csr, 'ml': AMG hierarchy}.
_LAPLACIAN_AMG_CACHE = {}


def _laplacian_amg_cache(Nx, Ny, Nz):
    """Pure 7-point graph Laplacian + its Ruge-Stuben AMG hierarchy, cached by
    grid shape.

    The projection operator depends only on cell connectivity (unit ±1 face
    couplings — the ε·ρcp·A face weights enter only the post-solve velocity
    correction, never the Laplacian), so a single build is reused across both
    fluids and every outer iteration. This is what makes the AMG-CG path cheap:
    the hierarchy is assembled once per grid, not per solve.
    """
    key = (Nx, Ny, Nz)
    cached = _LAPLACIAN_AMG_CACHE.get(key)
    if cached is not None:
        return cached
    import pyamg
    from scipy.sparse import csr_matrix
    n = Nx * Ny * Nz
    idx = np.arange(n).reshape(Nx, Ny, Nz)
    rows = []; cols = []; vals = []

    def _add(a, b):
        # Symmetric Laplacian coupling for an interior face between cells a,b
        a = a.ravel(); b = b.ravel()
        rows.append(a); cols.append(a); vals.append(np.ones_like(a, np.float64))
        rows.append(a); cols.append(b); vals.append(-np.ones_like(a, np.float64))
        rows.append(b); cols.append(b); vals.append(np.ones_like(b, np.float64))
        rows.append(b); cols.append(a); vals.append(-np.ones_like(b, np.float64))

    if Nx > 1: _add(idx[:-1, :, :], idx[1:, :, :])
    if Ny > 1: _add(idx[:, :-1, :], idx[:, 1:, :])
    if Nz > 1: _add(idx[:, :, :-1], idx[:, :, 1:])
    L = csr_matrix((np.concatenate(vals),
                    (np.concatenate(rows), np.concatenate(cols))),
                   shape=(n, n))
    ml = pyamg.ruge_stuben_solver(L, max_coarse=200)
    cached = {'L': L, 'ml': ml}
    _LAPLACIAN_AMG_CACHE[key] = cached
    return cached


def _project_faces_div_free(uf, vf, wf, eps_f, rcp, dx, dy, dz):
    """Project staggered real-coords face velocities onto a discretely
    solenoidal field so the conservative LTNE kernel telescopes exactly.

    SIMPLE's solver-frame face fluxes are divergence-free, but
    `_solver_staggered_to_real` negates the stream component for reverse-dir
    fluids without reordering the shared cell fields, leaving a per-cell
    real-coords mass divergence of −2·(stream div) (≈17–69 % of the h_v
    scale, measured 2026-06-03). A single MAC/Helmholtz projection removes it:

        F_face = (ε·ρcp·u·A)_face                      (energy mass flux)
        D[c]   = Σ_faces F  (outward)                  (per-cell divergence)
        L φ = D    with L the 7-point graph Laplacian over INTERIOR faces
                   only (homogeneous-Neumann; boundary faces never corrected,
                   so inlet/outlet mass flow + the BC stay untouched)
        F*_face = F_face − (φ[nb] − φ[c])              (interior faces)
        u*_face = u_face + (F*_face − F_face) / C_face

    Returns corrected (uf, vf, wf). Forward-dir fluids are already
    solenoidal (D≈0 ⇒ φ≈0 ⇒ ~no change), so this is safe to apply to all.
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.linalg import spsolve

    Nx, Ny, Nz = eps_f.shape
    Ax = (dy[None, :, None] * dz[None, None, :])   # (1,Ny,Nz)
    Ay = (dx[:, None, None] * dz[None, None, :])   # (Nx,1,Nz)
    Az = (dx[:, None, None] * dy[None, :, None])   # (Nx,Ny,1)

    coef = eps_f * rcp                              # cell ε·ρcp

    # Interior-face coefficients C = ε_f·ρcp·A (arithmetic-mean face value,
    # matching the kernel's face interpolation).
    Cx = 0.5 * (coef[:-1, :, :] + coef[1:, :, :]) * np.broadcast_to(Ax, (Nx-1, Ny, Nz))
    Cy = 0.5 * (coef[:, :-1, :] + coef[:, 1:, :]) * np.broadcast_to(Ay, (Nx, Ny-1, Nz))
    Cz = 0.5 * (coef[:, :, :-1] + coef[:, :, 1:]) * np.broadcast_to(Az, (Nx, Ny, Nz-1))

    # Per-cell divergence from current fluxes (interior + boundary faces).
    AxF = np.broadcast_to(Ax, uf.shape)
    AyF = np.broadcast_to(Ay, vf.shape)
    AzF = np.broadcast_to(Az, wf.shape)
    cf_x = np.empty_like(uf)
    cf_x[1:-1, :, :] = 0.5 * (coef[:-1, :, :] + coef[1:, :, :])
    cf_x[0, :, :] = coef[0, :, :]; cf_x[-1, :, :] = coef[-1, :, :]
    cf_y = np.empty_like(vf)
    cf_y[:, 1:-1, :] = 0.5 * (coef[:, :-1, :] + coef[:, 1:, :])
    cf_y[:, 0, :] = coef[:, 0, :]; cf_y[:, -1, :] = coef[:, -1, :]
    cf_z = np.empty_like(wf)
    cf_z[:, :, 1:-1] = 0.5 * (coef[:, :, :-1] + coef[:, :, 1:])
    cf_z[:, :, 0] = coef[:, :, 0]; cf_z[:, :, -1] = coef[:, :, -1]
    Fx = cf_x * uf * AxF
    Fy = cf_y * vf * AyF
    Fz = cf_z * wf * AzF
    D = ((Fx[1:, :, :] - Fx[:-1, :, :])
         + (Fy[:, 1:, :] - Fy[:, :-1, :])
         + (Fz[:, :, 1:] - Fz[:, :, :-1])).ravel()

    n = Nx * Ny * Nz
    if n == 0:
        return uf, vf, wf

    # #2 — skip the O(N) solve when the field is already (near-)solenoidal.
    # Forward-dir fluids enter divergence-free (the reverse-dir staggered→real
    # transform is what injects divergence); for them φ ~ 0 and the correction
    # is pure roundoff, so returning the input unchanged is both faster and
    # cleaner. The threshold is relative to the face-flux scale and sits far
    # below any physical divergence (reverse-dir D is O(0.1–0.7) of the h_v
    # scale, measured 2026-06-03), so a real correction is never skipped.
    flux_scale = max(float(np.abs(Fx).max()),
                     float(np.abs(Fy).max()),
                     float(np.abs(Fz).max()), 1e-300)
    if float(np.abs(D).max()) <= _PROJ_SKIP_TOL * flux_scale:
        return uf, vf, wf

    # #1 — solve the singular SPD graph-Laplacian system L φ = D with a cached
    # AMG-preconditioned CG. This replaces a dense-bordered direct LU which, at
    # 64k cells, cost ~56 s/solve: the Lagrange border row/column destroyed the
    # sparse fill pattern, making the LU factor near-dense. L is the pure 7-point
    # connectivity Laplacian — a function of (Nx,Ny,Nz) only — so it and its AMG
    # hierarchy are built once (`_laplacian_amg_cache`) and reused everywhere.
    #
    # The bordered Lagrange system [[L,e],[eᵀ,0]][φ;μ]=[D;0] is algebraically
    # equivalent to solving L φ = D − mean(D) with mean(φ)=0 (μ = mean(D)).
    # Projecting D onto range(L) (subtract its mean) makes the singular system
    # consistent for CG; de-meaning φ afterwards removes the null-space part.
    # Both the operator and the mean-zero constraint are reflection-symmetric,
    # so a z-even D yields a z-even φ — preserving the 2026-06-09 z-symmetry fix
    # WITHOUT the corner-pin that originally broke it.
    cache = _laplacian_amg_cache(Nx, Ny, Nz)
    L = cache['L']
    D0 = D - D.mean()
    M = cache['ml'].aspreconditioner(cycle='V')
    from scipy.sparse.linalg import cg as _cg
    phi_flat, info = _cg(L, D0, M=M, rtol=1e-10, maxiter=500)
    if info != 0:
        # Robustness fallback: the original dense-bordered direct solve (exact
        # and symmetric, just slow). Should never trigger for a well-posed L.
        from scipy.sparse import bmat
        e = np.ones((n, 1))
        L_aug = bmat([[L, e], [e.T, None]], format='csr')
        phi_flat = spsolve(L_aug, np.concatenate([D, [0.0]]))[:n]
    phi_flat = phi_flat - phi_flat.mean()
    phi = phi_flat.reshape(Nx, Ny, Nz)

    # Correct interior faces only. With L φ = D (L = graph Laplacian), the
    # per-cell post-correction divergence is D − Lφ = 0 iff the face flux is
    # adjusted by δF_face = +(φ[c+] − φ[c−]) along +axis ⇒ u* = u + δF/C.
    uf = uf.copy(); vf = vf.copy(); wf = wf.copy()
    if Nx > 1:
        dF = phi[1:, :, :] - phi[:-1, :, :]
        uf[1:-1, :, :] += dF / (Cx + 1e-30)
    if Ny > 1:
        dF = phi[:, 1:, :] - phi[:, :-1, :]
        vf[:, 1:-1, :] += dF / (Cy + 1e-30)
    if Nz > 1:
        dF = phi[:, :, 1:] - phi[:, :, :-1]
        wf[:, :, 1:-1] += dF / (Cz + 1e-30)
    return (np.ascontiguousarray(uf), np.ascontiguousarray(vf),
            np.ascontiguousarray(wf))


# Denominator floor (W) for the relative strict-conservation metric. Guards the
# degenerate no-net-heat-exchange cases (equi-T, or one fluid disabled so solid
# equilibrates to the live fluid) where ∫S → 0 and a relative residual divides
# by ~0. Real audit/production sources are O(100 W) ≫ floor, so unaffected; in
# the degenerate cases the absolute residual is machine-level, so eps → ~0.
_Q_FLOOR_W = 1.0


def _conservation_residual_sum(T, Ts, uf, vf, wf, eps_f, K, rcp, hv,
                               dx, dy, dz, dir_code):
    """Rigorous strict-conservation certificate for one fluid phase (B-plan B2).

    Evaluates, on the CONVERGED field, the residual of the *conservative*
    discrete energy equation per cell — using the exact same shared face
    fluxes, harmonic-mean diffusion and hybrid-upwind coefficients as the
    conservative kernel, with the (F_e−F_w+…) net-out term in a_P:

        r[c] = a_P·T_c − Σ a_nb·T_nb − h_v·V·Ts

    Summed over INTERIOR cells (inlet-pinned and outlet zero-grad layers
    excluded), internal faces telescope so Σ r = ∮_∂(interior) flux −
    ∫ source. For a converged conservative solution r→0 per cell ⇒ Σ r→0
    (machine/solver-tol). A non-conservative solution evaluated against this
    discretisation leaves Σ r large. Returns (Σ r, ∫_interior h_v(Ts−T) dV).
    """
    Nx, Ny, Nz = T.shape
    Ax = (dy[None, :, None] * dz[None, None, :])
    Ay = (dx[:, None, None] * dz[None, None, :])
    Az = (dx[:, None, None] * dy[None, :, None])
    vol = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]

    coef = eps_f * rcp
    # Face ε·ρcp (arithmetic mean interior, cell value at boundary) — matches kernel.
    cf_x = np.empty_like(uf); cf_x[1:-1] = 0.5 * (coef[:-1] + coef[1:])
    cf_x[0] = coef[0]; cf_x[-1] = coef[-1]
    cf_y = np.empty_like(vf); cf_y[:, 1:-1] = 0.5 * (coef[:, :-1] + coef[:, 1:])
    cf_y[:, 0] = coef[:, 0]; cf_y[:, -1] = coef[:, -1]
    cf_z = np.empty_like(wf); cf_z[:, :, 1:-1] = 0.5 * (coef[:, :, :-1] + coef[:, :, 1:])
    cf_z[:, :, 0] = coef[:, :, 0]; cf_z[:, :, -1] = coef[:, :, -1]
    Fx = cf_x * uf * np.broadcast_to(Ax, uf.shape)   # (Nx+1,Ny,Nz)
    Fy = cf_y * vf * np.broadcast_to(Ay, vf.shape)
    Fz = cf_z * wf * np.broadcast_to(Az, wf.shape)
    Fe = Fx[1:]; Fw = Fx[:-1]; Fn = Fy[:, 1:]; Fs = Fy[:, :-1]
    Ft = Fz[:, :, 1:]; Fb = Fz[:, :, :-1]
    net_out = (Fe - Fw) + (Fn - Fs) + (Ft - Fb)

    # Harmonic-mean diffusion conductances, shared faces (matches kernel).
    dxe = 0.5 * (dx[:-1] + dx[1:]); dyn = 0.5 * (dy[:-1] + dy[1:])
    dzt = 0.5 * (dz[:-1] + dz[1:])
    dE = np.zeros_like(T); dW = np.zeros_like(T)
    dN = np.zeros_like(T); dS = np.zeros_like(T)
    dT_ = np.zeros_like(T); dB = np.zeros_like(T)
    if Nx > 1:
        h = 2.0 * K[:-1] * K[1:] / (K[:-1] + K[1:] + 1e-30) \
            * np.broadcast_to(Ax, (Nx - 1, Ny, Nz)) / dxe[:, None, None]
        dE[:-1] = h; dW[1:] = h
    if Ny > 1:
        h = 2.0 * K[:, :-1] * K[:, 1:] / (K[:, :-1] + K[:, 1:] + 1e-30) \
            * np.broadcast_to(Ay, (Nx, Ny - 1, Nz)) / dyn[None, :, None]
        dN[:, :-1] = h; dS[:, 1:] = h
    if Nz > 1:
        h = 2.0 * K[:, :, :-1] * K[:, :, 1:] / (K[:, :, :-1] + K[:, :, 1:] + 1e-30) \
            * np.broadcast_to(Az, (Nx, Ny, Nz - 1)) / dzt[None, None, :]
        dT_[:, :, :-1] = h; dB[:, :, 1:] = h

    aE = dE + np.maximum(-Fe, 0.0); aW = dW + np.maximum(Fw, 0.0)
    aN = dN + np.maximum(-Fn, 0.0); aS = dS + np.maximum(Fs, 0.0)
    aT = dT_ + np.maximum(-Ft, 0.0); aB = dB + np.maximum(Fb, 0.0)
    aP = aE + aW + aN + aS + aT + aB + net_out + hv * vol

    # Neighbour T with boundary = self (kernel convention).
    TE = T.copy(); TE[:-1] = T[1:]
    TW = T.copy(); TW[1:] = T[:-1]
    TN = T.copy(); TN[:, :-1] = T[:, 1:]
    TS = T.copy(); TS[:, 1:] = T[:, :-1]
    TT = T.copy(); TT[:, :, :-1] = T[:, :, 1:]
    TB = T.copy(); TB[:, :, 1:] = T[:, :, :-1]
    r = (aP * T - aE * TE - aW * TW - aN * TN - aS * TS - aT * TT - aB * TB
         - hv * vol * Ts)
    # Subtract the conservative HO deferred source so this measures the TRUE
    # residual of the equation the kernel actually solves (FO implicit + sou).
    # The sou itself telescopes, so conservation is preserved; r → 0 at
    # convergence. (For pure-upwind it is identically 0 ⇒ no-op.)
    r = r - _sou_field_cons(T, Fx, Fy, Fz)

    # Interior mask: drop inlet-pinned + outlet zero-grad cell layers.
    interior = np.ones((Nx, Ny, Nz), dtype=bool)
    inlet_outlet = {0: (0, Nx - 1), 1: (Nx - 1, 0), 2: (0, Ny - 1),
                    3: (Ny - 1, 0), 4: (0, Nz - 1), 5: (Nz - 1, 0)}[dir_code]
    ax = 0 if dir_code <= 1 else (1 if dir_code <= 3 else 2)
    for idx in inlet_outlet:
        sl = [slice(None)] * 3; sl[ax] = idx
        interior[tuple(sl)] = False

    src = hv * vol * (Ts - T)
    max_abs_r = float(np.max(np.abs(r[interior]))) if np.any(interior) else 0.0
    return float(np.sum(r[interior])), float(np.sum(src[interior])), max_abs_r


# ---------------------------------------------------------------------------
# SOU limiter — three axes
# ---------------------------------------------------------------------------

@njit(cache=True, fastmath=True, inline='always')
def _va_limit(gu, gd):
    """minmod slope limiter (signed). Returns 0 at extrema (gu*gd<=0), else
    the smaller-magnitude gradient with gu's sign. Factored into a helper
    (2026-05-22) so the SOU stencils read cleanly; behaviour is identical to
    the original inline minmod."""
    if gu * gd <= 0.0:
        return 0.0
    m = abs(gu) if abs(gu) < abs(gd) else abs(gd)
    return m if gu > 0.0 else -m


@njit(cache=True, fastmath=True)
def _sou_corr_x_3d(T, i, j, k, Nx, u_loc, Fx):
    if u_loc >= 0:
        phi_w = 0.0
        if i > 1:
            phi_w = _va_limit(T[i-1, j, k] - T[i-2, j, k],
                              T[i, j, k] - T[i-1, j, k])
        phi_e = 0.0
        if i < Nx - 1 and i > 0:
            phi_e = _va_limit(T[i, j, k] - T[i-1, j, k],
                              T[i+1, j, k] - T[i, j, k])
        return 0.5 * Fx * (phi_w - phi_e)
    else:
        phi_e = 0.0
        if i < Nx - 2:
            phi_e = _va_limit(T[i+1, j, k] - T[i+2, j, k],
                              T[i, j, k] - T[i+1, j, k])
        phi_w = 0.0
        if i > 0 and i < Nx - 1:
            phi_w = _va_limit(T[i, j, k] - T[i+1, j, k],
                              T[i-1, j, k] - T[i, j, k])
        return 0.5 * Fx * (phi_e - phi_w)


@njit(cache=True, fastmath=True)
def _sou_corr_y_3d(T, i, j, k, Ny, v_loc, Fy):
    if v_loc >= 0:
        phi_s = 0.0
        if j > 1:
            phi_s = _va_limit(T[i, j-1, k] - T[i, j-2, k],
                              T[i, j, k] - T[i, j-1, k])
        phi_n = 0.0
        if j < Ny - 1 and j > 0:
            phi_n = _va_limit(T[i, j, k] - T[i, j-1, k],
                              T[i, j+1, k] - T[i, j, k])
        return 0.5 * Fy * (phi_s - phi_n)
    else:
        phi_n = 0.0
        if j < Ny - 2:
            phi_n = _va_limit(T[i, j+1, k] - T[i, j+2, k],
                              T[i, j, k] - T[i, j+1, k])
        phi_s = 0.0
        if j > 0 and j < Ny - 1:
            phi_s = _va_limit(T[i, j, k] - T[i, j+1, k],
                              T[i, j-1, k] - T[i, j, k])
        return 0.5 * Fy * (phi_n - phi_s)


@njit(cache=True, fastmath=True)
def _sou_corr_z_3d(T, i, j, k, Nz, w_loc, Fz):
    if w_loc >= 0:
        phi_b = 0.0
        if k > 1:
            phi_b = _va_limit(T[i, j, k-1] - T[i, j, k-2],
                              T[i, j, k] - T[i, j, k-1])
        phi_t = 0.0
        if k < Nz - 1 and k > 0:
            phi_t = _va_limit(T[i, j, k] - T[i, j, k-1],
                              T[i, j, k+1] - T[i, j, k])
        return 0.5 * Fz * (phi_b - phi_t)
    else:
        phi_t = 0.0
        if k < Nz - 2:
            phi_t = _va_limit(T[i, j, k+1] - T[i, j, k+2],
                              T[i, j, k] - T[i, j, k+1])
        phi_b = 0.0
        if k > 0 and k < Nz - 1:
            phi_b = _va_limit(T[i, j, k] - T[i, j, k+1],
                              T[i, j, k-1] - T[i, j, k])
        return 0.5 * Fz * (phi_t - phi_b)


# ---------------------------------------------------------------------------
# Conservative (telescoping) SOU deferred correction — face-shared.
#
# Unlike _sou_corr_*_3d (cell-local: each cell uses its own |u_c| magnitude, so
# the correction at a shared face differs between the two adjacent cells and
# breaks conservation), these use the SIGNED shared face flux to pick the
# upwind side. The HO increment (T_HO_face − T_up_face) = 0.5·minmod(...) is a
# pure function of the face + neighbour T values, identical from both cells'
# view, so the deferred source Σ_faces ∓F_face·inc telescopes ⇒ strictly
# conservative AND 2nd-order. Source convention matches the kernel:
#   sou = −Σ_faces F_face·(T_HO−T_up)·(outward sign)
# ---------------------------------------------------------------------------

@njit(cache=True, fastmath=True)
def _sou_face_x_cons(T, i, j, k, Nx, Fw, Fe):
    inc_e = 0.0
    if Fe >= 0.0:                      # east face upwind = cell i
        if 0 < i < Nx - 1:
            inc_e = 0.5 * _va_limit(T[i, j, k] - T[i-1, j, k],
                                    T[i+1, j, k] - T[i, j, k])
    else:                              # east face upwind = cell i+1
        if i < Nx - 2:
            inc_e = 0.5 * _va_limit(T[i+1, j, k] - T[i+2, j, k],
                                    T[i, j, k] - T[i+1, j, k])
    inc_w = 0.0
    if Fw >= 0.0:                      # west face upwind = cell i-1
        if i > 1:
            inc_w = 0.5 * _va_limit(T[i-1, j, k] - T[i-2, j, k],
                                    T[i, j, k] - T[i-1, j, k])
    else:                              # west face upwind = cell i
        if 0 < i < Nx - 1:
            inc_w = 0.5 * _va_limit(T[i, j, k] - T[i+1, j, k],
                                    T[i-1, j, k] - T[i, j, k])
    return -Fe * inc_e + Fw * inc_w


@njit(cache=True, fastmath=True)
def _sou_face_y_cons(T, i, j, k, Ny, Fs, Fn):
    inc_n = 0.0
    if Fn >= 0.0:
        if 0 < j < Ny - 1:
            inc_n = 0.5 * _va_limit(T[i, j, k] - T[i, j-1, k],
                                    T[i, j+1, k] - T[i, j, k])
    else:
        if j < Ny - 2:
            inc_n = 0.5 * _va_limit(T[i, j+1, k] - T[i, j+2, k],
                                    T[i, j, k] - T[i, j+1, k])
    inc_s = 0.0
    if Fs >= 0.0:
        if j > 1:
            inc_s = 0.5 * _va_limit(T[i, j-1, k] - T[i, j-2, k],
                                    T[i, j, k] - T[i, j-1, k])
    else:
        if 0 < j < Ny - 1:
            inc_s = 0.5 * _va_limit(T[i, j, k] - T[i, j+1, k],
                                    T[i, j-1, k] - T[i, j, k])
    return -Fn * inc_n + Fs * inc_s


@njit(cache=True, fastmath=True)
def _sou_face_z_cons(T, i, j, k, Nz, Fb, Ft):
    inc_t = 0.0
    if Ft >= 0.0:
        if 0 < k < Nz - 1:
            inc_t = 0.5 * _va_limit(T[i, j, k] - T[i, j, k-1],
                                    T[i, j, k+1] - T[i, j, k])
    else:
        if k < Nz - 2:
            inc_t = 0.5 * _va_limit(T[i, j, k+1] - T[i, j, k+2],
                                    T[i, j, k] - T[i, j, k+1])
    inc_b = 0.0
    if Fb >= 0.0:
        if k > 1:
            inc_b = 0.5 * _va_limit(T[i, j, k-1] - T[i, j, k-2],
                                    T[i, j, k] - T[i, j, k-1])
    else:
        if 0 < k < Nz - 1:
            inc_b = 0.5 * _va_limit(T[i, j, k] - T[i, j, k+1],
                                    T[i, j, k-1] - T[i, j, k])
    return -Ft * inc_t + Fb * inc_b


@njit(cache=True, fastmath=True)
def _sou_field_cons(T, Fx, Fy, Fz):
    """Per-cell face-shared SOU deferred-correction field, using the SAME
    helpers as the conservative kernel. Lets the strict-conservation metric
    subtract the exact deferred source so the certificate stays valid with HO
    active (converged: r_FO = sou ⇒ true residual r_FO − sou → 0)."""
    Nx, Ny, Nz = T.shape
    sou = np.zeros_like(T)
    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                sou[i, j, k] = (
                    _sou_face_x_cons(T, i, j, k, Nx, Fx[i, j, k], Fx[i+1, j, k])
                    + _sou_face_y_cons(T, i, j, k, Ny, Fy[i, j, k], Fy[i, j+1, k])
                    + _sou_face_z_cons(T, i, j, k, Nz, Fz[i, j, k], Fz[i, j, k+1]))
    return sou


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
# Gauss-Seidel chunk — STAGGERED face-velocity version (2026-04-25 FV#6)
#
# Uses SIMPLE's staggered face velocities directly so the LTNE advection
# operator shares the discrete ∇·(ρv) = 0 structure of the momentum solver.
# NET_OUT at each cell → 0 (to SIMPLE's residual), making Q_enthalpy match
# Q_source tightly across all grid refinements.
#
# Face velocity arrays:
#   uf : (Nx+1, Ny, Nz) — u at x-faces (signed along +x)
#   vf : (Nx, Ny+1, Nz) — v at y-faces (signed along +y)
#   wf : (Nx, Ny, Nz+1) — w at z-faces (signed along +z)
# ---------------------------------------------------------------------------

@njit(cache=True, fastmath=True)
def _gs_full_chunk_3d_stag(Ta, Tb, Ts, Nx, Ny, Nz,
                            dx_arr, dy_arr, dz_arr,
                            K_ffA_arr, K_ffB_arr, K_ss_arr,
                            h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
                            rho_cp_fA, rho_cp_fB,
                            ufA, vfA, wfA, ufB, vfB, wfB,
                            bc_A, bc_B, T_inA_arr, T_inB_arr,
                            ifrac_A, ifrac_B,
                            n_iters, freeze_Tb,
                            alpha_fA, alpha_s, alpha_fB,
                            chi_B_arr, chi_B_kernel_threshold,
                            mms_S_A_arr, mms_S_B_arr, mms_S_s_arr,
                            conservative):
    max_chg = 0.0

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

                        Ax = dyj * dzk; Ay = dxi * dzk; Az = dxi * dyj
                        # Face spacing δx_e = 0.5(dx_P+dx_E) for conservative
                        # diffusion stencil (#3D-7 fix). Same value used by both
                        # adjacent cells; old /dxi broke symmetry on non-uniform.
                        dxe = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                        dxw = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                        dyn = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                        dys = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                        dzt = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                        dzb = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                        dE = 2.0 * Kc * K_ffA_arr[i+1, j, k] / (Kc + K_ffA_arr[i+1, j, k] + 1e-30) * Ax / dxe if i < Nx-1 else 0.0
                        dW = 2.0 * Kc * K_ffA_arr[i-1, j, k] / (Kc + K_ffA_arr[i-1, j, k] + 1e-30) * Ax / dxw if i > 0 else 0.0
                        dN = 2.0 * Kc * K_ffA_arr[i, j+1, k] / (Kc + K_ffA_arr[i, j+1, k] + 1e-30) * Ay / dyn if j < Ny-1 else 0.0
                        dS = 2.0 * Kc * K_ffA_arr[i, j-1, k] / (Kc + K_ffA_arr[i, j-1, k] + 1e-30) * Ay / dys if j > 0 else 0.0
                        dT_ = 2.0 * Kc * K_ffA_arr[i, j, k+1] / (Kc + K_ffA_arr[i, j, k+1] + 1e-30) * Az / dzt if k < Nz-1 else 0.0
                        dB = 2.0 * Kc * K_ffA_arr[i, j, k-1] / (Kc + K_ffA_arr[i, j, k-1] + 1e-30) * Az / dzb if k > 0 else 0.0

                        # Face-centered staggered velocities (directly from SIMPLE).
                        # u_face_x at (i, i+1), v_face_y at (j, j+1), w_face_z at (k, k+1).
                        u_e = ufA[i+1, j, k]
                        u_w = ufA[i, j, k]
                        v_n = vfA[i, j+1, k]
                        v_s = vfA[i, j, k]
                        w_t = wfA[i, j, k+1]
                        w_b = wfA[i, j, k]

                        # ρcp and eps_f at faces — arithmetic mean of cell values.
                        rcpA_c = rho_cp_fA[i,j,k]; ef_c = eps_fA_arr[i,j,k]
                        rcp_e = 0.5*(rcpA_c + rho_cp_fA[i+1,j,k]) if i < Nx-1 else rcpA_c
                        rcp_w = 0.5*(rho_cp_fA[i-1,j,k] + rcpA_c) if i > 0 else rcpA_c
                        rcp_n = 0.5*(rcpA_c + rho_cp_fA[i,j+1,k]) if j < Ny-1 else rcpA_c
                        rcp_s = 0.5*(rho_cp_fA[i,j-1,k] + rcpA_c) if j > 0 else rcpA_c
                        rcp_t = 0.5*(rcpA_c + rho_cp_fA[i,j,k+1]) if k < Nz-1 else rcpA_c
                        rcp_b = 0.5*(rho_cp_fA[i,j,k-1] + rcpA_c) if k > 0 else rcpA_c
                        ef_e = 0.5*(ef_c + eps_fA_arr[i+1,j,k]) if i < Nx-1 else ef_c
                        ef_w = 0.5*(eps_fA_arr[i-1,j,k] + ef_c) if i > 0 else ef_c
                        ef_n = 0.5*(ef_c + eps_fA_arr[i,j+1,k]) if j < Ny-1 else ef_c
                        ef_s = 0.5*(eps_fA_arr[i,j-1,k] + ef_c) if j > 0 else ef_c
                        ef_t = 0.5*(ef_c + eps_fA_arr[i,j,k+1]) if k < Nz-1 else ef_c
                        ef_b = 0.5*(eps_fA_arr[i,j,k-1] + ef_c) if k > 0 else ef_c

                        # Signed face mass-flux (+axis direction)
                        F_e = ef_e * rcp_e * u_e * Ax
                        F_w = ef_w * rcp_w * u_w * Ax
                        F_n = ef_n * rcp_n * v_n * Ay
                        F_s = ef_s * rcp_s * v_s * Ay
                        F_t = ef_t * rcp_t * w_t * Az
                        F_b = ef_b * rcp_b * w_b * Az

                        # Patankar hybrid upwind on signed face flux
                        aE = dE + max(-F_e, 0.0)
                        aW = dW + max( F_w, 0.0)
                        aN = dN + max(-F_n, 0.0)
                        aS = dS + max( F_s, 0.0)
                        aT = dT_ + max(-F_t, 0.0)
                        aB = dB + max( F_b, 0.0)

                        tE = Ta[i+1, j, k] if i < Nx-1 else Ta[i, j, k]
                        tW = Ta[i-1, j, k] if i > 0    else Ta[i, j, k]
                        tN = Ta[i, j+1, k] if j < Ny-1 else Ta[i, j, k]
                        tS = Ta[i, j-1, k] if j > 0    else Ta[i, j, k]
                        tT = Ta[i, j, k+1] if k < Nz-1 else Ta[i, j, k]
                        tB = Ta[i, j, k-1] if k > 0    else Ta[i, j, k]

                        if conservative == 1:
                            # Strict-conservation (B-plan B2): the SIMPLE
                            # staggered face flux is the SAME value for the two
                            # cells sharing a face (F_e of cell i ≡ F_w of cell
                            # i+1), so advection telescopes. Adding the signed
                            # net-mass-out term to aP completes the Patankar
                            # conservative form — summing the discrete per-cell
                            # balance over the domain then collapses to
                            # ∮F·n dA = ∫S dV (machine-accurate, see 1D PoC).
                            # HO accuracy via face-SHARED SOU deferred
                            # correction (B-plan B4): the increment uses the
                            # signed shared face flux to pick the upwind side,
                            # so it telescopes ⇒ conservation preserved AND
                            # 2nd-order. (cell-local _sou_corr_* would break it.)
                            sou = (_sou_face_x_cons(Ta, i, j, k, Nx, F_w, F_e)
                                   + _sou_face_y_cons(Ta, i, j, k, Ny, F_s, F_n)
                                   + _sou_face_z_cons(Ta, i, j, k, Nz, F_b, F_t))
                            net_out = (F_e - F_w) + (F_n - F_s) + (F_t - F_b)
                            aP = aE + aW + aN + aS + aT + aB + net_out + hvA
                        else:
                            # SOU deferred correction with cell-center velocity
                            u_c_sou = 0.5*(u_e + u_w)
                            v_c_sou = 0.5*(v_n + v_s)
                            w_c_sou = 0.5*(w_t + w_b)
                            Fx_mag = ef_c * rcpA_c * abs(u_c_sou) * Ax
                            Fy_mag = ef_c * rcpA_c * abs(v_c_sou) * Ay
                            Fz_mag = ef_c * rcpA_c * abs(w_c_sou) * Az
                            sou = (_sou_corr_x_3d(Ta, i, j, k, Nx, u_c_sou, Fx_mag)
                                   + _sou_corr_y_3d(Ta, i, j, k, Ny, v_c_sou, Fy_mag)
                                   + _sou_corr_z_3d(Ta, i, j, k, Nz, w_c_sou, Fz_mag))
                            # aP = Σa_nb + hvA. NET_OUT (mass-imbal) tried in
                            # multiple variants (full, interior-only, BC pin
                            # penalty, source split): all destabilise because BC
                            # face flux ≠ adjacent interior face flux when SIMPLE
                            # has any per-cell residual. cell-local stable + 13-22%
                            # AB imbal accepted as discretisation limit.
                            aP = aE + aW + aN + aS + aT + aB + hvA
                        if aP < 1e-30:
                            aP = 1e-30
                        # MMS source injection (volume-integrated, units W).
                        # Default zero-array → production no-op.
                        S_A_cell = mms_S_A_arr[i, j, k] * vol
                        new = (aE*tE + aW*tW + aN*tN + aS*tS + aT*tT + aB*tB
                               + hvA * Ts[i, j, k] + sou + S_A_cell) / aP
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
                    # Face spacing for solid (stag) — same as A
                    dxe_s = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                    dxw_s = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                    dyn_s = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                    dys_s = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                    dzt_s = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                    dzb_s = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                    De = 2.0*Ks*K_ss_arr[i+1, j, k]/(Ks+K_ss_arr[i+1, j, k]+1e-30)*Ax/dxe_s if i < Nx-1 else Ks*Ax/dxi
                    Dw = 2.0*Ks*K_ss_arr[i-1, j, k]/(Ks+K_ss_arr[i-1, j, k]+1e-30)*Ax/dxw_s if i > 0    else Ks*Ax/dxi
                    Dn = 2.0*Ks*K_ss_arr[i, j+1, k]/(Ks+K_ss_arr[i, j+1, k]+1e-30)*Ay/dyn_s if j < Ny-1 else Ks*Ay/dyj
                    Ds = 2.0*Ks*K_ss_arr[i, j-1, k]/(Ks+K_ss_arr[i, j-1, k]+1e-30)*Ay/dys_s if j > 0    else Ks*Ay/dyj
                    Dt = 2.0*Ks*K_ss_arr[i, j, k+1]/(Ks+K_ss_arr[i, j, k+1]+1e-30)*Az/dzt_s if k < Nz-1 else Ks*Az/dzk
                    Db = 2.0*Ks*K_ss_arr[i, j, k-1]/(Ks+K_ss_arr[i, j, k-1]+1e-30)*Az/dzb_s if k > 0    else Ks*Az/dzk

                    sE = Ts[i+1, j, k] if i < Nx-1 else Ts[i, j, k]
                    sW = Ts[i-1, j, k] if i > 0    else Ts[i, j, k]
                    sN = Ts[i, j+1, k] if j < Ny-1 else Ts[i, j, k]
                    sS = Ts[i, j-1, k] if j > 0    else Ts[i, j, k]
                    sT = Ts[i, j, k+1] if k < Nz-1 else Ts[i, j, k]
                    sB = Ts[i, j, k-1] if k > 0    else Ts[i, j, k]

                    aP_s = De + Dw + Dn + Ds + Dt + Db + hvA_s + hvB_s
                    # MMS source for solid (vol-integrated, [W]).
                    S_s_cell = mms_S_s_arr[i, j, k] * vol_s
                    new_s = (De*sE + Dw*sW + Dn*sN + Ds*sS + Dt*sT + Db*sB
                             + hvA_s*Ta[i, j, k] + hvB_s*Tb[i, j, k]
                             + S_s_cell) / aP_s
                    old_s = Ts[i, j, k]
                    upd_s = old_s + alpha_s * (new_s - old_s)
                    chg = abs(upd_s - old_s)
                    if chg > max_chg: max_chg = chg
                    Ts[i, j, k] = upd_s

                    # ── Fluid B ── (stag kernel)
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
                        elif chi_B_arr[i, j, k] < chi_B_kernel_threshold:
                            # H6 ghost-skip: at low-participation cells, leave
                            # Tb at its init value (T_inB throughout). Prevents
                            # stagnant cells from relaxing to local Ts via h_v
                            # and then leaking that hot value into the active
                            # flow channel via 1st-order upwind. Necessary for
                            # offset partial-B cross-flow (T4 Shanghai-like).
                            pass
                        else:
                            vol_b = dxi * dyj * dzk
                            Kc_b = K_ffB_arr[i, j, k]
                            hvB = h_vB_arr[i, j, k] * vol_b

                            # Face spacing for B (stag) — same as A
                            dxe_b = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                            dxw_b = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                            dyn_b = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                            dys_b = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                            dzt_b = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                            dzb_b = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                            dEb = 2.0*Kc_b*K_ffB_arr[i+1, j, k]/(Kc_b+K_ffB_arr[i+1, j, k]+1e-30)*Ax/dxe_b if i < Nx-1 else 0.0
                            dWb = 2.0*Kc_b*K_ffB_arr[i-1, j, k]/(Kc_b+K_ffB_arr[i-1, j, k]+1e-30)*Ax/dxw_b if i > 0 else 0.0
                            dNb = 2.0*Kc_b*K_ffB_arr[i, j+1, k]/(Kc_b+K_ffB_arr[i, j+1, k]+1e-30)*Ay/dyn_b if j < Ny-1 else 0.0
                            dSb = 2.0*Kc_b*K_ffB_arr[i, j-1, k]/(Kc_b+K_ffB_arr[i, j-1, k]+1e-30)*Ay/dys_b if j > 0 else 0.0
                            dTb_ = 2.0*Kc_b*K_ffB_arr[i, j, k+1]/(Kc_b+K_ffB_arr[i, j, k+1]+1e-30)*Az/dzt_b if k < Nz-1 else 0.0
                            dBb = 2.0*Kc_b*K_ffB_arr[i, j, k-1]/(Kc_b+K_ffB_arr[i, j, k-1]+1e-30)*Az/dzb_b if k > 0 else 0.0

                            uB_e = ufB[i+1, j, k]
                            uB_w = ufB[i, j, k]
                            vB_n = vfB[i, j+1, k]
                            vB_s = vfB[i, j, k]
                            wB_t = wfB[i, j, k+1]
                            wB_b = wfB[i, j, k]

                            rcpB_c = rho_cp_fB[i,j,k]; efB_c = eps_fB_arr[i,j,k]
                            rcpB_e = 0.5*(rcpB_c + rho_cp_fB[i+1,j,k]) if i < Nx-1 else rcpB_c
                            rcpB_w = 0.5*(rho_cp_fB[i-1,j,k] + rcpB_c) if i > 0 else rcpB_c
                            rcpB_n = 0.5*(rcpB_c + rho_cp_fB[i,j+1,k]) if j < Ny-1 else rcpB_c
                            rcpB_s = 0.5*(rho_cp_fB[i,j-1,k] + rcpB_c) if j > 0 else rcpB_c
                            rcpB_t = 0.5*(rcpB_c + rho_cp_fB[i,j,k+1]) if k < Nz-1 else rcpB_c
                            rcpB_b = 0.5*(rho_cp_fB[i,j,k-1] + rcpB_c) if k > 0 else rcpB_c
                            efB_e = 0.5*(efB_c + eps_fB_arr[i+1,j,k]) if i < Nx-1 else efB_c
                            efB_w = 0.5*(eps_fB_arr[i-1,j,k] + efB_c) if i > 0 else efB_c
                            efB_n = 0.5*(efB_c + eps_fB_arr[i,j+1,k]) if j < Ny-1 else efB_c
                            efB_s = 0.5*(eps_fB_arr[i,j-1,k] + efB_c) if j > 0 else efB_c
                            efB_t = 0.5*(efB_c + eps_fB_arr[i,j,k+1]) if k < Nz-1 else efB_c
                            efB_b = 0.5*(eps_fB_arr[i,j,k-1] + efB_c) if k > 0 else efB_c

                            FB_e = efB_e * rcpB_e * uB_e * Ax
                            FB_w = efB_w * rcpB_w * uB_w * Ax
                            FB_n = efB_n * rcpB_n * vB_n * Ay
                            FB_s = efB_s * rcpB_s * vB_s * Ay
                            FB_t = efB_t * rcpB_t * wB_t * Az
                            FB_b = efB_b * rcpB_b * wB_b * Az

                            aEb = dEb  + max(-FB_e, 0.0)
                            aWb = dWb  + max( FB_w, 0.0)
                            aNb = dNb  + max(-FB_n, 0.0)
                            aSb = dSb  + max( FB_s, 0.0)
                            aTb = dTb_ + max(-FB_t, 0.0)
                            aBb = dBb  + max( FB_b, 0.0)

                            tEb = Tb[i+1, j, k] if i < Nx-1 else Tb[i, j, k]
                            tWb = Tb[i-1, j, k] if i > 0    else Tb[i, j, k]
                            tNb = Tb[i, j+1, k] if j < Ny-1 else Tb[i, j, k]
                            tSb = Tb[i, j-1, k] if j > 0    else Tb[i, j, k]
                            tTb = Tb[i, j, k+1] if k < Nz-1 else Tb[i, j, k]
                            tBb = Tb[i, j, k-1] if k > 0    else Tb[i, j, k]

                            if conservative == 1:
                                # Strict-conservation B side (mirror of A):
                                # face-shared SOU deferred correction (HO + telescoping).
                                soub = (_sou_face_x_cons(Tb, i, j, k, Nx, FB_w, FB_e)
                                        + _sou_face_y_cons(Tb, i, j, k, Ny, FB_s, FB_n)
                                        + _sou_face_z_cons(Tb, i, j, k, Nz, FB_b, FB_t))
                                net_outB = ((FB_e - FB_w) + (FB_n - FB_s)
                                            + (FB_t - FB_b))
                                aPb = (aEb + aWb + aNb + aSb + aTb + aBb
                                       + net_outB + hvB)
                            else:
                                uBc_sou = 0.5*(uB_e + uB_w)
                                vBc_sou = 0.5*(vB_n + vB_s)
                                wBc_sou = 0.5*(wB_t + wB_b)
                                FxB_mag = efB_c * rcpB_c * abs(uBc_sou) * Ax
                                FyB_mag = efB_c * rcpB_c * abs(vBc_sou) * Ay
                                FzB_mag = efB_c * rcpB_c * abs(wBc_sou) * Az
                                soub = (_sou_corr_x_3d(Tb, i, j, k, Nx, uBc_sou, FxB_mag)
                                        + _sou_corr_y_3d(Tb, i, j, k, Ny, vBc_sou, FyB_mag)
                                        + _sou_corr_z_3d(Tb, i, j, k, Nz, wBc_sou, FzB_mag))
                                aPb = aEb + aWb + aNb + aSb + aTb + aBb + hvB
                            if aPb < 1e-30:
                                aPb = 1e-30
                            # MMS source for B (vol-integrated, [W]).
                            S_B_cell = mms_S_B_arr[i, j, k] * vol_b
                            new_b = (aEb*tEb + aWb*tWb + aNb*tNb + aSb*tSb
                                     + aTb*tTb + aBb*tBb + hvB*Ts[i, j, k]
                                     + soub + S_B_cell) / aPb
                            old_b = Tb[i, j, k]
                            upd_b = old_b + alpha_fB * (new_b - old_b)
                            chg = abs(upd_b - old_b)
                            if chg > max_chg: max_chg = chg
                            Tb[i, j, k] = upd_b

        _apply_outlet_3d(Ta, bc_A, Nx, Ny, Nz)
        if freeze_Tb == 0:
            _apply_outlet_3d(Tb, bc_B, Nx, Ny, Nz)

        if max_chg < 1e-10:
            break
    return max_chg


@njit(cache=True, fastmath=True, parallel=True)
def _gs_full_chunk_3d_stag_rb(Ta, Tb, Ts, Nx, Ny, Nz,
                               dx_arr, dy_arr, dz_arr,
                               K_ffA_arr, K_ffB_arr, K_ss_arr,
                               h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
                               rho_cp_fA, rho_cp_fB,
                               ufA, vfA, wfA, ufB, vfB, wfB,
                               bc_A, bc_B, T_inA_arr, T_inB_arr,
                               ifrac_A, ifrac_B,
                               n_iters, freeze_Tb,
                               alpha_fA, alpha_s, alpha_fB,
                               chi_B_arr, chi_B_kernel_threshold,
                               mms_S_A_arr, mms_S_B_arr, mms_S_s_arr,
                               conservative):
    """Red-black parallel twin of `_gs_full_chunk_3d_stag`.

    Two race-free changes vs the serial kernel make it `prange`-parallelisable:
      1. Cells are swept by checkerboard colour (i+j+k parity). Within a colour
         pass every cell's 7-point neighbours are the OTHER colour (frozen this
         pass), so same-colour cells update independently — no GS read/write race.
      2. The SOU deferred correction reaches 2 cells away (same colour), so it is
         read from a START-OF-SWEEP SNAPSHOT (`Ta_snap`/`Tb_snap`) instead of the
         live field. SOU is a deferred (lagged) correction and the advection
         face fluxes are T-independent, so this changes only the iteration path,
         not the converged fixpoint — Q/dP and the conservation certificate match
         the serial kernel at convergence.

    The per-cell update math is otherwise identical to the serial kernel.
    Parity note: a z-reflection flips colour when Nz is even, so the colour
    SWEEP order is not reflection-symmetric — but neither is the serial
    lexicographic order, and both converge to the same (symmetric) linear-system
    solution, so a converged z-symmetric case stays z-symmetric (verified).
    """
    max_chg = 0.0
    ncell = Nx * Ny * Nz
    nyz = Ny * Nz
    for _it in range(n_iters):
        # Start-of-sweep snapshot for the (2-away, same-colour) deferred SOU.
        Ta_snap = Ta.copy()
        Tb_snap = Tb.copy()
        sweep_chg = 0.0
        for color in range(2):
            color_chg = 0.0
            for idx in prange(ncell):
                i = idx // nyz
                rem = idx - i * nyz
                j = rem // Nz
                k = rem - j * Nz
                if ((i + j + k) & 1) != color:
                    continue
                cell_chg = 0.0

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

                    Ax = dyj * dzk; Ay = dxi * dzk; Az = dxi * dyj
                    dxe = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                    dxw = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                    dyn = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                    dys = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                    dzt = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                    dzb = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                    dE = 2.0 * Kc * K_ffA_arr[i+1, j, k] / (Kc + K_ffA_arr[i+1, j, k] + 1e-30) * Ax / dxe if i < Nx-1 else 0.0
                    dW = 2.0 * Kc * K_ffA_arr[i-1, j, k] / (Kc + K_ffA_arr[i-1, j, k] + 1e-30) * Ax / dxw if i > 0 else 0.0
                    dN = 2.0 * Kc * K_ffA_arr[i, j+1, k] / (Kc + K_ffA_arr[i, j+1, k] + 1e-30) * Ay / dyn if j < Ny-1 else 0.0
                    dS = 2.0 * Kc * K_ffA_arr[i, j-1, k] / (Kc + K_ffA_arr[i, j-1, k] + 1e-30) * Ay / dys if j > 0 else 0.0
                    dT_ = 2.0 * Kc * K_ffA_arr[i, j, k+1] / (Kc + K_ffA_arr[i, j, k+1] + 1e-30) * Az / dzt if k < Nz-1 else 0.0
                    dB = 2.0 * Kc * K_ffA_arr[i, j, k-1] / (Kc + K_ffA_arr[i, j, k-1] + 1e-30) * Az / dzb if k > 0 else 0.0

                    u_e = ufA[i+1, j, k]; u_w = ufA[i, j, k]
                    v_n = vfA[i, j+1, k]; v_s = vfA[i, j, k]
                    w_t = wfA[i, j, k+1]; w_b = wfA[i, j, k]

                    rcpA_c = rho_cp_fA[i,j,k]; ef_c = eps_fA_arr[i,j,k]
                    rcp_e = 0.5*(rcpA_c + rho_cp_fA[i+1,j,k]) if i < Nx-1 else rcpA_c
                    rcp_w = 0.5*(rho_cp_fA[i-1,j,k] + rcpA_c) if i > 0 else rcpA_c
                    rcp_n = 0.5*(rcpA_c + rho_cp_fA[i,j+1,k]) if j < Ny-1 else rcpA_c
                    rcp_s = 0.5*(rho_cp_fA[i,j-1,k] + rcpA_c) if j > 0 else rcpA_c
                    rcp_t = 0.5*(rcpA_c + rho_cp_fA[i,j,k+1]) if k < Nz-1 else rcpA_c
                    rcp_b = 0.5*(rho_cp_fA[i,j,k-1] + rcpA_c) if k > 0 else rcpA_c
                    ef_e = 0.5*(ef_c + eps_fA_arr[i+1,j,k]) if i < Nx-1 else ef_c
                    ef_w = 0.5*(eps_fA_arr[i-1,j,k] + ef_c) if i > 0 else ef_c
                    ef_n = 0.5*(ef_c + eps_fA_arr[i,j+1,k]) if j < Ny-1 else ef_c
                    ef_s = 0.5*(eps_fA_arr[i,j-1,k] + ef_c) if j > 0 else ef_c
                    ef_t = 0.5*(ef_c + eps_fA_arr[i,j,k+1]) if k < Nz-1 else ef_c
                    ef_b = 0.5*(eps_fA_arr[i,j,k-1] + ef_c) if k > 0 else ef_c

                    F_e = ef_e * rcp_e * u_e * Ax
                    F_w = ef_w * rcp_w * u_w * Ax
                    F_n = ef_n * rcp_n * v_n * Ay
                    F_s = ef_s * rcp_s * v_s * Ay
                    F_t = ef_t * rcp_t * w_t * Az
                    F_b = ef_b * rcp_b * w_b * Az

                    aE = dE + max(-F_e, 0.0); aW = dW + max( F_w, 0.0)
                    aN = dN + max(-F_n, 0.0); aS = dS + max( F_s, 0.0)
                    aT = dT_ + max(-F_t, 0.0); aB = dB + max( F_b, 0.0)

                    tE = Ta[i+1, j, k] if i < Nx-1 else Ta[i, j, k]
                    tW = Ta[i-1, j, k] if i > 0    else Ta[i, j, k]
                    tN = Ta[i, j+1, k] if j < Ny-1 else Ta[i, j, k]
                    tS = Ta[i, j-1, k] if j > 0    else Ta[i, j, k]
                    tT = Ta[i, j, k+1] if k < Nz-1 else Ta[i, j, k]
                    tB = Ta[i, j, k-1] if k > 0    else Ta[i, j, k]

                    if conservative == 1:
                        sou = (_sou_face_x_cons(Ta_snap, i, j, k, Nx, F_w, F_e)
                               + _sou_face_y_cons(Ta_snap, i, j, k, Ny, F_s, F_n)
                               + _sou_face_z_cons(Ta_snap, i, j, k, Nz, F_b, F_t))
                        net_out = (F_e - F_w) + (F_n - F_s) + (F_t - F_b)
                        aP = aE + aW + aN + aS + aT + aB + net_out + hvA
                    else:
                        u_c_sou = 0.5*(u_e + u_w); v_c_sou = 0.5*(v_n + v_s)
                        w_c_sou = 0.5*(w_t + w_b)
                        Fx_mag = ef_c * rcpA_c * abs(u_c_sou) * Ax
                        Fy_mag = ef_c * rcpA_c * abs(v_c_sou) * Ay
                        Fz_mag = ef_c * rcpA_c * abs(w_c_sou) * Az
                        sou = (_sou_corr_x_3d(Ta_snap, i, j, k, Nx, u_c_sou, Fx_mag)
                               + _sou_corr_y_3d(Ta_snap, i, j, k, Ny, v_c_sou, Fy_mag)
                               + _sou_corr_z_3d(Ta_snap, i, j, k, Nz, w_c_sou, Fz_mag))
                        aP = aE + aW + aN + aS + aT + aB + hvA
                    if aP < 1e-30:
                        aP = 1e-30
                    S_A_cell = mms_S_A_arr[i, j, k] * vol
                    new = (aE*tE + aW*tW + aN*tN + aS*tS + aT*tT + aB*tB
                           + hvA * Ts[i, j, k] + sou + S_A_cell) / aP
                    old = Ta[i, j, k]
                    upd = old + alpha_fA * (new - old)
                    c = abs(upd - old)
                    if c > cell_chg: cell_chg = c
                    Ta[i, j, k] = upd

                # ── Solid ──
                dxi = dx_arr[i]; dyj = dy_arr[j]; dzk = dz_arr[k]
                vol_s = dxi * dyj * dzk
                Ks = K_ss_arr[i, j, k]
                hvA_s = h_vA_arr[i, j, k] * vol_s
                hvB_s = h_vB_arr[i, j, k] * vol_s
                Ax = dyj * dzk; Ay = dxi * dzk; Az = dxi * dyj
                dxe_s = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                dxw_s = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                dyn_s = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                dys_s = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                dzt_s = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                dzb_s = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                De = 2.0*Ks*K_ss_arr[i+1, j, k]/(Ks+K_ss_arr[i+1, j, k]+1e-30)*Ax/dxe_s if i < Nx-1 else Ks*Ax/dxi
                Dw = 2.0*Ks*K_ss_arr[i-1, j, k]/(Ks+K_ss_arr[i-1, j, k]+1e-30)*Ax/dxw_s if i > 0    else Ks*Ax/dxi
                Dn = 2.0*Ks*K_ss_arr[i, j+1, k]/(Ks+K_ss_arr[i, j+1, k]+1e-30)*Ay/dyn_s if j < Ny-1 else Ks*Ay/dyj
                Ds = 2.0*Ks*K_ss_arr[i, j-1, k]/(Ks+K_ss_arr[i, j-1, k]+1e-30)*Ay/dys_s if j > 0    else Ks*Ay/dyj
                Dt = 2.0*Ks*K_ss_arr[i, j, k+1]/(Ks+K_ss_arr[i, j, k+1]+1e-30)*Az/dzt_s if k < Nz-1 else Ks*Az/dzk
                Db = 2.0*Ks*K_ss_arr[i, j, k-1]/(Ks+K_ss_arr[i, j, k-1]+1e-30)*Az/dzb_s if k > 0    else Ks*Az/dzk
                sE = Ts[i+1, j, k] if i < Nx-1 else Ts[i, j, k]
                sW = Ts[i-1, j, k] if i > 0    else Ts[i, j, k]
                sN = Ts[i, j+1, k] if j < Ny-1 else Ts[i, j, k]
                sS = Ts[i, j-1, k] if j > 0    else Ts[i, j, k]
                sT = Ts[i, j, k+1] if k < Nz-1 else Ts[i, j, k]
                sB = Ts[i, j, k-1] if k > 0    else Ts[i, j, k]
                aP_s = De + Dw + Dn + Ds + Dt + Db + hvA_s + hvB_s
                S_s_cell = mms_S_s_arr[i, j, k] * vol_s
                new_s = (De*sE + Dw*sW + Dn*sN + Ds*sS + Dt*sT + Db*sB
                         + hvA_s*Ta[i, j, k] + hvB_s*Tb[i, j, k]
                         + S_s_cell) / aP_s
                old_s = Ts[i, j, k]
                upd_s = old_s + alpha_s * (new_s - old_s)
                c = abs(upd_s - old_s)
                if c > cell_chg: cell_chg = c
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
                    elif chi_B_arr[i, j, k] < chi_B_kernel_threshold:
                        pass
                    else:
                        vol_b = dxi * dyj * dzk
                        Kc_b = K_ffB_arr[i, j, k]
                        hvB = h_vB_arr[i, j, k] * vol_b
                        dxe_b = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                        dxw_b = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                        dyn_b = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                        dys_b = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                        dzt_b = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                        dzb_b = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                        dEb = 2.0*Kc_b*K_ffB_arr[i+1, j, k]/(Kc_b+K_ffB_arr[i+1, j, k]+1e-30)*Ax/dxe_b if i < Nx-1 else 0.0
                        dWb = 2.0*Kc_b*K_ffB_arr[i-1, j, k]/(Kc_b+K_ffB_arr[i-1, j, k]+1e-30)*Ax/dxw_b if i > 0 else 0.0
                        dNb = 2.0*Kc_b*K_ffB_arr[i, j+1, k]/(Kc_b+K_ffB_arr[i, j+1, k]+1e-30)*Ay/dyn_b if j < Ny-1 else 0.0
                        dSb = 2.0*Kc_b*K_ffB_arr[i, j-1, k]/(Kc_b+K_ffB_arr[i, j-1, k]+1e-30)*Ay/dys_b if j > 0 else 0.0
                        dTb_ = 2.0*Kc_b*K_ffB_arr[i, j, k+1]/(Kc_b+K_ffB_arr[i, j, k+1]+1e-30)*Az/dzt_b if k < Nz-1 else 0.0
                        dBb = 2.0*Kc_b*K_ffB_arr[i, j, k-1]/(Kc_b+K_ffB_arr[i, j, k-1]+1e-30)*Az/dzb_b if k > 0 else 0.0
                        uB_e = ufB[i+1, j, k]; uB_w = ufB[i, j, k]
                        vB_n = vfB[i, j+1, k]; vB_s = vfB[i, j, k]
                        wB_t = wfB[i, j, k+1]; wB_b = wfB[i, j, k]
                        rcpB_c = rho_cp_fB[i,j,k]; efB_c = eps_fB_arr[i,j,k]
                        rcpB_e = 0.5*(rcpB_c + rho_cp_fB[i+1,j,k]) if i < Nx-1 else rcpB_c
                        rcpB_w = 0.5*(rho_cp_fB[i-1,j,k] + rcpB_c) if i > 0 else rcpB_c
                        rcpB_n = 0.5*(rcpB_c + rho_cp_fB[i,j+1,k]) if j < Ny-1 else rcpB_c
                        rcpB_s = 0.5*(rho_cp_fB[i,j-1,k] + rcpB_c) if j > 0 else rcpB_c
                        rcpB_t = 0.5*(rcpB_c + rho_cp_fB[i,j,k+1]) if k < Nz-1 else rcpB_c
                        rcpB_b = 0.5*(rho_cp_fB[i,j,k-1] + rcpB_c) if k > 0 else rcpB_c
                        efB_e = 0.5*(efB_c + eps_fB_arr[i+1,j,k]) if i < Nx-1 else efB_c
                        efB_w = 0.5*(eps_fB_arr[i-1,j,k] + efB_c) if i > 0 else efB_c
                        efB_n = 0.5*(efB_c + eps_fB_arr[i,j+1,k]) if j < Ny-1 else efB_c
                        efB_s = 0.5*(eps_fB_arr[i,j-1,k] + efB_c) if j > 0 else efB_c
                        efB_t = 0.5*(efB_c + eps_fB_arr[i,j,k+1]) if k < Nz-1 else efB_c
                        efB_b = 0.5*(eps_fB_arr[i,j,k-1] + efB_c) if k > 0 else efB_c
                        FB_e = efB_e * rcpB_e * uB_e * Ax
                        FB_w = efB_w * rcpB_w * uB_w * Ax
                        FB_n = efB_n * rcpB_n * vB_n * Ay
                        FB_s = efB_s * rcpB_s * vB_s * Ay
                        FB_t = efB_t * rcpB_t * wB_t * Az
                        FB_b = efB_b * rcpB_b * wB_b * Az
                        aEb = dEb  + max(-FB_e, 0.0); aWb = dWb  + max( FB_w, 0.0)
                        aNb = dNb  + max(-FB_n, 0.0); aSb = dSb  + max( FB_s, 0.0)
                        aTb = dTb_ + max(-FB_t, 0.0); aBb = dBb  + max( FB_b, 0.0)
                        tEb = Tb[i+1, j, k] if i < Nx-1 else Tb[i, j, k]
                        tWb = Tb[i-1, j, k] if i > 0    else Tb[i, j, k]
                        tNb = Tb[i, j+1, k] if j < Ny-1 else Tb[i, j, k]
                        tSb = Tb[i, j-1, k] if j > 0    else Tb[i, j, k]
                        tTb = Tb[i, j, k+1] if k < Nz-1 else Tb[i, j, k]
                        tBb = Tb[i, j, k-1] if k > 0    else Tb[i, j, k]
                        if conservative == 1:
                            soub = (_sou_face_x_cons(Tb_snap, i, j, k, Nx, FB_w, FB_e)
                                    + _sou_face_y_cons(Tb_snap, i, j, k, Ny, FB_s, FB_n)
                                    + _sou_face_z_cons(Tb_snap, i, j, k, Nz, FB_b, FB_t))
                            net_outB = ((FB_e - FB_w) + (FB_n - FB_s)
                                        + (FB_t - FB_b))
                            aPb = (aEb + aWb + aNb + aSb + aTb + aBb
                                   + net_outB + hvB)
                        else:
                            uBc_sou = 0.5*(uB_e + uB_w); vBc_sou = 0.5*(vB_n + vB_s)
                            wBc_sou = 0.5*(wB_t + wB_b)
                            FxB_mag = efB_c * rcpB_c * abs(uBc_sou) * Ax
                            FyB_mag = efB_c * rcpB_c * abs(vBc_sou) * Ay
                            FzB_mag = efB_c * rcpB_c * abs(wBc_sou) * Az
                            soub = (_sou_corr_x_3d(Tb_snap, i, j, k, Nx, uBc_sou, FxB_mag)
                                    + _sou_corr_y_3d(Tb_snap, i, j, k, Ny, vBc_sou, FyB_mag)
                                    + _sou_corr_z_3d(Tb_snap, i, j, k, Nz, wBc_sou, FzB_mag))
                            aPb = aEb + aWb + aNb + aSb + aTb + aBb + hvB
                        if aPb < 1e-30:
                            aPb = 1e-30
                        S_B_cell = mms_S_B_arr[i, j, k] * vol_b
                        new_b = (aEb*tEb + aWb*tWb + aNb*tNb + aSb*tSb
                                 + aTb*tTb + aBb*tBb + hvB*Ts[i, j, k]
                                 + soub + S_B_cell) / aPb
                        old_b = Tb[i, j, k]
                        upd_b = old_b + alpha_fB * (new_b - old_b)
                        c = abs(upd_b - old_b)
                        if c > cell_chg: cell_chg = c
                        Tb[i, j, k] = upd_b

                color_chg = max(color_chg, cell_chg)
            if color_chg > sweep_chg:
                sweep_chg = color_chg

        _apply_outlet_3d(Ta, bc_A, Nx, Ny, Nz)
        if freeze_Tb == 0:
            _apply_outlet_3d(Tb, bc_B, Nx, Ny, Nz)

        max_chg = sweep_chg
        if max_chg < 1e-10:
            break
    return max_chg


# ---------------------------------------------------------------------------
# Gauss-Seidel chunk — face-centered Patankar with Moukalled BC source
# (2026-04-26 strict-conservation refactor; PoC validated AB imbal < 0.1% in 1D)
# ---------------------------------------------------------------------------

@njit(cache=True, fastmath=True)
def _is_bc_face_inlet(face_dir, dir_code):
    """Return 1 if the given face direction (0=W, 1=E, 2=S, 3=N, 4=B, 5=T)
    matches the inlet face for this fluid's flow direction (dir_code), else 0.

    dir_code: 0=+x→inlet at W (face 0), 1=-x→inlet at E (face 1),
              2=+y→inlet at S (face 2), 3=-y→inlet at N (face 3),
              4=+z→inlet at B (face 4), 5=-z→inlet at T (face 5).
    """
    return 1 if face_dir == dir_code else 0


@njit(cache=True, fastmath=True)
def _is_bc_face_outlet(face_dir, dir_code):
    """Return 1 if face is outlet for this fluid. Outlet is opposite face of
    inlet: dir 0↔1, 2↔3, 4↔5."""
    if dir_code == 0 and face_dir == 1: return 1
    if dir_code == 1 and face_dir == 0: return 1
    if dir_code == 2 and face_dir == 3: return 1
    if dir_code == 3 and face_dir == 2: return 1
    if dir_code == 4 and face_dir == 5: return 1
    if dir_code == 5 and face_dir == 4: return 1
    return 0


@njit(cache=True, fastmath=True)
def _ifrac_at_face(ifrac, dir_code, i, j, k, Nx, Ny, Nz):
    """Lookup partial-inlet fraction at the inlet face for cell (i,j,k).

    Returns 0 if cell is not on the inlet face. ifrac shape depends on dir_code:
    dir 0/1 → (Ny,Nz); 2/3 → (Nx,Nz); 4/5 → (Nx,Ny).
    """
    if dir_code == 0 and i == 0:    return ifrac[j, k]
    if dir_code == 1 and i == Nx-1: return ifrac[j, k]
    if dir_code == 2 and j == 0:    return ifrac[i, k]
    if dir_code == 3 and j == Ny-1: return ifrac[i, k]
    if dir_code == 4 and k == 0:    return ifrac[i, j]
    if dir_code == 5 and k == Nz-1: return ifrac[i, j]
    return 0.0


@njit(cache=True, fastmath=True)
def _Tin_at_face(T_in_arr, dir_code, i, j, k, Nx, Ny, Nz):
    """Lookup inlet temperature at face for cell (i,j,k)."""
    if dir_code == 0 and i == 0:    return T_in_arr[j, k]
    if dir_code == 1 and i == Nx-1: return T_in_arr[j, k]
    if dir_code == 2 and j == 0:    return T_in_arr[i, k]
    if dir_code == 3 and j == Ny-1: return T_in_arr[i, k]
    if dir_code == 4 and k == 0:    return T_in_arr[i, j]
    if dir_code == 5 and k == Nz-1: return T_in_arr[i, j]
    return 0.0


# ---------------------------------------------------------------------------
# Gauss-Seidel chunk — 7-point + SOU + coupled Ta/Ts/Tb  (cell-centered u)
# ---------------------------------------------------------------------------

@njit(cache=True, fastmath=True)
def _gs_full_chunk_3d(Ta, Tb, Ts, Nx, Ny, Nz,
                      dx_arr, dy_arr, dz_arr,
                      K_ffA_arr, K_ffB_arr, K_ss_arr,
                      h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
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

                        Ax = dyj * dzk; Ay = dxi * dzk; Az = dxi * dyj
                        # Face spacing δx_e (#3D-7 fix) — conservative diffusion
                        dxe = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                        dxw = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                        dyn = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                        dys = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                        dzt = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                        dzb = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                        dE = 2.0 * Kc * K_ffA_arr[i+1, j, k] / (Kc + K_ffA_arr[i+1, j, k] + 1e-30) * Ax / dxe if i < Nx-1 else 0.0
                        dW = 2.0 * Kc * K_ffA_arr[i-1, j, k] / (Kc + K_ffA_arr[i-1, j, k] + 1e-30) * Ax / dxw if i > 0 else 0.0
                        dN = 2.0 * Kc * K_ffA_arr[i, j+1, k] / (Kc + K_ffA_arr[i, j+1, k] + 1e-30) * Ay / dyn if j < Ny-1 else 0.0
                        dS = 2.0 * Kc * K_ffA_arr[i, j-1, k] / (Kc + K_ffA_arr[i, j-1, k] + 1e-30) * Ay / dys if j > 0 else 0.0
                        dT_ = 2.0 * Kc * K_ffA_arr[i, j, k+1] / (Kc + K_ffA_arr[i, j, k+1] + 1e-30) * Az / dzt if k < Nz-1 else 0.0
                        dB = 2.0 * Kc * K_ffA_arr[i, j, k-1] / (Kc + K_ffA_arr[i, j, k-1] + 1e-30) * Az / dzb if k > 0 else 0.0

                        # Cell-local upwind (2026-04-25 FV#5): match 2D scheme.
                        # Each cell uses its own |u_c| for face flux magnitudes.
                        # F_x = F_w = ρcp·|u_c|·Ax → NET_OUT = 0 at cell level by
                        # construction, so the Patankar aP=Σa_nb + hvA form is
                        # locally conservative without a NET_OUT correction.
                        # Face-centered interpolation (FV-1) was theoretically
                        # more accurate but introduced a ~3× Q_enthalpy/Q_source
                        # mismatch because cell-averaged face u did not satisfy
                        # discrete mass conservation cell-wise. 2D has used this
                        # cell-local pattern forever with <1% AB imbalance.
                        u_c = ucA[i,j,k]; v_c = vcA[i,j,k]; w_c = wcA[i,j,k]
                        rcpA_c = rho_cp_fA[i,j,k]; ef_c = eps_fA_arr[i,j,k]
                        Fx = ef_c * rcpA_c * abs(u_c) * Ax
                        Fy = ef_c * rcpA_c * abs(v_c) * Ay
                        Fz = ef_c * rcpA_c * abs(w_c) * Az

                        if u_c >= 0.0: aW = dW + Fx; aE = dE
                        else:          aE = dE + Fx; aW = dW
                        if v_c >= 0.0: aS = dS + Fy; aN = dN
                        else:          aN = dN + Fy; aS = dS
                        if w_c >= 0.0: aB = dB + Fz; aT = dT_
                        else:          aT = dT_ + Fz; aB = dB

                        tE = Ta[i+1, j, k] if i < Nx-1 else Ta[i, j, k]
                        tW = Ta[i-1, j, k] if i > 0    else Ta[i, j, k]
                        tN = Ta[i, j+1, k] if j < Ny-1 else Ta[i, j, k]
                        tS = Ta[i, j-1, k] if j > 0    else Ta[i, j, k]
                        tT = Ta[i, j, k+1] if k < Nz-1 else Ta[i, j, k]
                        tB = Ta[i, j, k-1] if k > 0    else Ta[i, j, k]

                        sou = (_sou_corr_x_3d(Ta, i, j, k, Nx, u_c, Fx)
                               + _sou_corr_y_3d(Ta, i, j, k, Ny, v_c, Fy)
                               + _sou_corr_z_3d(Ta, i, j, k, Nz, w_c, Fz))

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
                    # Face spacing for solid (cell-local kernel)
                    dxe_s = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                    dxw_s = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                    dyn_s = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                    dys_s = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                    dzt_s = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                    dzb_s = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                    De = 2.0*Ks*K_ss_arr[i+1, j, k]/(Ks+K_ss_arr[i+1, j, k]+1e-30)*Ax/dxe_s if i < Nx-1 else Ks*Ax/dxi
                    Dw = 2.0*Ks*K_ss_arr[i-1, j, k]/(Ks+K_ss_arr[i-1, j, k]+1e-30)*Ax/dxw_s if i > 0    else Ks*Ax/dxi
                    Dn = 2.0*Ks*K_ss_arr[i, j+1, k]/(Ks+K_ss_arr[i, j+1, k]+1e-30)*Ay/dyn_s if j < Ny-1 else Ks*Ay/dyj
                    Ds = 2.0*Ks*K_ss_arr[i, j-1, k]/(Ks+K_ss_arr[i, j-1, k]+1e-30)*Ay/dys_s if j > 0    else Ks*Ay/dyj
                    Dt = 2.0*Ks*K_ss_arr[i, j, k+1]/(Ks+K_ss_arr[i, j, k+1]+1e-30)*Az/dzt_s if k < Nz-1 else Ks*Az/dzk
                    Db = 2.0*Ks*K_ss_arr[i, j, k-1]/(Ks+K_ss_arr[i, j, k-1]+1e-30)*Az/dzb_s if k > 0    else Ks*Az/dzk

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

                            # Face spacing for B (cell-local kernel)
                            dxe_b = 0.5 * (dxi + dx_arr[i+1]) if i < Nx-1 else dxi
                            dxw_b = 0.5 * (dx_arr[i-1] + dxi) if i > 0    else dxi
                            dyn_b = 0.5 * (dyj + dy_arr[j+1]) if j < Ny-1 else dyj
                            dys_b = 0.5 * (dy_arr[j-1] + dyj) if j > 0    else dyj
                            dzt_b = 0.5 * (dzk + dz_arr[k+1]) if k < Nz-1 else dzk
                            dzb_b = 0.5 * (dz_arr[k-1] + dzk) if k > 0    else dzk
                            dEb = 2.0*Kc_b*K_ffB_arr[i+1, j, k]/(Kc_b+K_ffB_arr[i+1, j, k]+1e-30)*Ax/dxe_b if i < Nx-1 else 0.0
                            dWb = 2.0*Kc_b*K_ffB_arr[i-1, j, k]/(Kc_b+K_ffB_arr[i-1, j, k]+1e-30)*Ax/dxw_b if i > 0 else 0.0
                            dNb = 2.0*Kc_b*K_ffB_arr[i, j+1, k]/(Kc_b+K_ffB_arr[i, j+1, k]+1e-30)*Ay/dyn_b if j < Ny-1 else 0.0
                            dSb = 2.0*Kc_b*K_ffB_arr[i, j-1, k]/(Kc_b+K_ffB_arr[i, j-1, k]+1e-30)*Ay/dys_b if j > 0 else 0.0
                            dTb_ = 2.0*Kc_b*K_ffB_arr[i, j, k+1]/(Kc_b+K_ffB_arr[i, j, k+1]+1e-30)*Az/dzt_b if k < Nz-1 else 0.0
                            dBb = 2.0*Kc_b*K_ffB_arr[i, j, k-1]/(Kc_b+K_ffB_arr[i, j, k-1]+1e-30)*Az/dzb_b if k > 0 else 0.0

                            # Cell-local upwind (2026-04-25 FV#5): match A branch + 2D.
                            uBc = ucB[i,j,k]; vBc = vcB[i,j,k]; wBc = wcB[i,j,k]
                            rcpB_c = rho_cp_fB[i,j,k]; efB_c = eps_fB_arr[i,j,k]
                            FxB = efB_c * rcpB_c * abs(uBc) * Ax
                            FyB = efB_c * rcpB_c * abs(vBc) * Ay
                            FzB = efB_c * rcpB_c * abs(wBc) * Az

                            if uBc >= 0.0: aWb = dWb + FxB; aEb = dEb
                            else:          aEb = dEb + FxB; aWb = dWb
                            if vBc >= 0.0: aSb = dSb + FyB; aNb = dNb
                            else:          aNb = dNb + FyB; aSb = dSb
                            if wBc >= 0.0: aBb = dBb + FzB; aTb = dTb_
                            else:          aTb = dTb_ + FzB; aBb = dBb

                            tEb = Tb[i+1, j, k] if i < Nx-1 else Tb[i, j, k]
                            tWb = Tb[i-1, j, k] if i > 0    else Tb[i, j, k]
                            tNb = Tb[i, j+1, k] if j < Ny-1 else Tb[i, j, k]
                            tSb = Tb[i, j-1, k] if j > 0    else Tb[i, j, k]
                            tTb = Tb[i, j, k+1] if k < Nz-1 else Tb[i, j, k]
                            tBb = Tb[i, j, k-1] if k > 0    else Tb[i, j, k]

                            soub = (_sou_corr_x_3d(Tb, i, j, k, Nx, uBc, FxB)
                                    + _sou_corr_y_3d(Tb, i, j, k, Ny, vBc, FyB)
                                    + _sou_corr_z_3d(Tb, i, j, k, Nz, wBc, FzB))

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
                    alpha_T,
                    q_rel_tol=None, conv_chunk=None):
    """Nz == 1 shortcut: squeeze z axis and call 2D solver for bitwise equivalence.
    alpha_T is accepted but ignored (2D uses Q-chunk convergence).
    q_rel_tol / conv_chunk passed through to the 2D solver (None = legacy)."""

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
        Tb_prescribed=_sq3(Tb_prescribed),
        q_rel_tol=q_rel_tol, conv_chunk=conv_chunk)

    Ta3 = Ta2[..., None].copy()
    Tb3 = Tb2[..., None].copy()
    Ts3 = Ts2[..., None].copy()
    if return_info:
        return Ta3, Tb3, Ts3, {'converged': True, 'iterations': -1, 'residual': 0.0,
                                'delegated_to_2d': True}
    return Ta3, Tb3, Ts3


# Diagnostic-only convergence trace (point 0 quantify, 2026-05-22). When set
# to a list, the LTNE loop appends per-chunk (done, rel_chg, max|ΔT|, mean|ΔT|,
# Q_B) so a caller can tell slow-but-converging from stalled/oscillating.
# None in production → zero overhead, no behaviour change.
_CONV_TRACE = None

# Energy GS kernel selector. The red-black `prange`-parallel twin
# (`_gs_full_chunk_3d_stag_rb`) converges to the same solution as the serial
# lexicographic `_gs_full_chunk_3d_stag` but uses all cores. Gated by grid size:
# below `_RB_ENERGY_GATE` cells the thread-launch overhead outweighs the benefit
# AND small grids stay bit-for-bit on the proven serial reference (so the test
# suite is unaffected). Set `_RB_ENERGY=False` to force serial everywhere.
_RB_ENERGY = True
_RB_ENERGY_GATE = 30_000


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
                          eps_A=None, eps_B=None,
                          ufA=None, vfA=None, wfA=None,
                          ufB=None, vfB=None, wfB=None,
                          chi_B_field=None,
                          chi_B_kernel_threshold=0.0,
                          mms_S_A_field=None,
                          mms_S_B_field=None,
                          mms_S_s_field=None,
                          conservative_ltne=False,
                          cancel_check=None,
                          q_rel_tol=None, conv_chunk=None):
    """3D full-domain 2-fluid LTNE solver (Ta, Tb, Ts).

    Shape contracts
    ---------------
    K_ffA/K_ffB/K_ss, h_vA/h_vB, rho_cp_fA/rho_cp_fB : scalar or (Nx, Ny, Nz).
    epsilon : scalar or (Nx, Ny, Nz). **Pass the FULL porosity ε_full**
              (= ε_A + ε_B for symmetric Gyroid). The kernel internally
              applies a SINGLE halving `eps_f = 0.5 * epsilon` (see
              ~line 1391) to get the single-channel ε_A = ε_full/2 used
              in the convective face flux F = ε_f · ρcp · u · A_face.
              Do NOT pre-halve at the call site — that double-halves to
              ε_full/4 (the 2026-05-14 regression; fixed under Option A
              on 2026-05-19, every production caller now passes full ε,
              guarded by tests/test_eps_contract_3d.py). The explicit
              `eps_A` / `eps_B` kwargs below ARE single-channel and are
              consumed without further halving. Rationale + Shanghai
              case-1 evidence: run_calculation_3d.py:~2009 comment.
    ucA/vcA/wcA/ucB/vcB/wcB    : (Nx, Ny, Nz) cell-centre.
    dir_A/dir_B ∈ {0=+x, 1=-x, 2=+y, 3=-y, 4=+z, 5=-z}.
    inlet_mask_*               : 2D cross-section or None.
    alpha_T                    : 0 < α ≤ 1 under-relax (default 0.7).

    Nz == 1 fast path: delegates to solvers.ltne_energy.solve_full_domain
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
            inlet_mask_A, inlet_mask_B, Tb_prescribed, alpha_T,
            q_rel_tol=q_rel_tol, conv_chunk=conv_chunk)

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

    # Per-fluid single-channel void fractions. Default (eps_A/eps_B None) =
    # symmetric ε_A = ε_B = ε/2 — both names bind the SAME array object, so the
    # dual-ε kernel reproduces the legacy single-eps_f arithmetic bit-for-bit.
    # Explicit eps_A/eps_B (asymmetric offset-isosurface δ) are single-channel
    # per-side fractions, routed per-side through the kernel WITHOUT further
    # halving (caller passes ε_A, ε_B directly; see docstring).
    if eps_A is None and eps_B is None:
        if np.ndim(epsilon) == 0:
            eps_fA_arr = np.full((Nx, Ny, Nz), 0.5 * float(epsilon), dtype=np.float64)
        else:
            eps_fA_arr = np.ascontiguousarray(0.5 * np.asarray(epsilon, dtype=np.float64))
            if eps_fA_arr.shape != (Nx, Ny, Nz):
                raise ValueError("epsilon 3D shape mismatch")
        eps_fB_arr = eps_fA_arr
    else:
        if eps_A is None or eps_B is None:
            raise ValueError("eps_A and eps_B must be provided together.")
        eps_fA_arr = _to_3d(eps_A)
        eps_fB_arr = _to_3d(eps_B)
        eps_tot_arr = _to_3d(epsilon)
        if np.any(eps_fA_arr + eps_fB_arr > eps_tot_arr + 1e-9):
            raise ValueError(
                "eps_A + eps_B exceeds epsilon at some cells.")

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

    # Init — each fluid seeded with its own inlet temperature (2026-04-24 FV
    # fix). Previous 0.5·(T_inA+T_inB) seed left non-pipe cells at the inlet
    # face holding a mid-T value (e.g. 361 K for Shanghai A=422/B=300) that
    # diffused back into the pipe region as a virtual heat source, breaking
    # energy balance by 20-25% in partial-inlet geometries. Pinning each
    # fluid field to its physically-correct inlet T avoids the source; Ts
    # keeps the mid value as a neutral guess.
    if Ta_init is not None:
        Ta = np.ascontiguousarray(Ta_init.copy(), dtype=np.float64)
        Tb = np.ascontiguousarray(Tb_init.copy(), dtype=np.float64)
        Ts = np.ascontiguousarray(Ts_init.copy(), dtype=np.float64)
    else:
        # Per-fluid seed (2026-04-24): each fluid starts at its own inlet T
        # so partial-inlet non-pipe cells don't hold a mid-T (361K for
        # Shanghai A=422/B=300) that diffuses back in as a virtual heat
        # source and breaks energy balance by 20-25%.
        Ta = np.full((Nx, Ny, Nz), float(T_inA), dtype=np.float64)
        Tb = np.full((Nx, Ny, Nz), float(T_inB), dtype=np.float64)
        Ts = np.full((Nx, Ny, Nz), 0.5 * (T_inA + T_inB), dtype=np.float64)

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

    # Chunk iterate, convergence = (Q stable) AND (field stable per chunk).
    # chunk=250 (2026-06-24): the old chunk=500 forced >=2 chunks (=1000 sweeps)
    # because the first Q-delta check is skipped (Q_prev starts at 0), so a
    # field that converged within the first chunk still ran a second, fully
    # redundant one (measured: the 2nd 500-sweep chunk changed the 40^3 field by
    # 1.7e-13 — pure waste; halving energy time at identical Q/dP). A finer
    # chunk detects convergence earlier. The tiny-grid false-exit the old
    # comment guarded against is now prevented by the `max ΔT < T_abs_tol`
    # AND-guard in the convergence test below (Q-stable alone could false-exit;
    # Q-stable AND field-stable cannot), so 250 is safe on small grids too.
    chunk = 250 if conv_chunk is None else int(conv_chunk); done = 0
    cell_vol = dx_arr[:, None, None] * dy_arr[None, :, None] * dz_arr[None, None, :]
    Q_prev = 0.0
    Ta_prev = Ta.copy(); Tb_prev = Tb.copy(); Ts_prev = Ts.copy()
    converged = False
    q_tol = max(tol * 10.0, 1e-4) if q_rel_tol is None else float(q_rel_tol)
    T_abs_tol = 0.01  # K between chunks — mirror 2D ltne_energy.py (#4)
    chg = 0.0

    # Dispatch: if caller passed staggered face velocities (ufA, vfA, wfA)
    # use the mass-conserving staggered kernel; else fall back to the
    # legacy cell-centered kernel (still valid but has Q_enthalpy ↔ Q_source
    # drift on ρ-varying flows due to cell-averaged face u).
    use_stag = (ufA is not None and vfA is not None and wfA is not None
                and ufB is not None and vfB is not None and wfB is not None)
    # Strict energy-conservation path (B-plan B2): only the staggered kernel
    # carries the shared face fluxes needed for telescoping, so it is a hard
    # prerequisite for the conservative form.
    _cons = 1 if conservative_ltne else 0
    if conservative_ltne and not use_stag:
        raise ValueError(
            "conservative_ltne=True requires staggered face velocities "
            "(ufA/vfA/wfA + ufB/vfB/wfB); pass them (force_cc_ltne=False).")
    if use_stag:
        ufA = np.ascontiguousarray(ufA, dtype=np.float64)
        vfA = np.ascontiguousarray(vfA, dtype=np.float64)
        wfA = np.ascontiguousarray(wfA, dtype=np.float64)
        ufB = np.ascontiguousarray(ufB, dtype=np.float64)
        vfB = np.ascontiguousarray(vfB, dtype=np.float64)
        wfB = np.ascontiguousarray(wfB, dtype=np.float64)
        if ufA.shape != (Nx+1, Ny, Nz):
            raise ValueError(f"ufA shape {ufA.shape} != ({Nx+1}, {Ny}, {Nz})")
        if vfA.shape != (Nx, Ny+1, Nz):
            raise ValueError(f"vfA shape {vfA.shape} != ({Nx}, {Ny+1}, {Nz})")
        if wfA.shape != (Nx, Ny, Nz+1):
            raise ValueError(f"wfA shape {wfA.shape} != ({Nx}, {Ny}, {Nz+1})")

    # H6 ghost-pin support: build chi_B_arr (default ones) for kernel pass-through
    if chi_B_field is None:
        chi_B_arr = np.ones((Nx, Ny, Nz), dtype=np.float64)
    else:
        chi_B_arr = np.ascontiguousarray(chi_B_field, dtype=np.float64)
        if chi_B_arr.shape != (Nx, Ny, Nz):
            raise ValueError(
                f"chi_B_field shape {chi_B_arr.shape} != ({Nx},{Ny},{Nz})")
    chi_B_thr = float(chi_B_kernel_threshold)

    # MMS source field arrays (default zeros = no-op).
    def _mms_arr(field):
        if field is None:
            return np.zeros((Nx, Ny, Nz), dtype=np.float64)
        arr = np.ascontiguousarray(field, dtype=np.float64)
        if arr.shape != (Nx, Ny, Nz):
            raise ValueError(
                f"MMS source field shape {arr.shape} != ({Nx},{Ny},{Nz})")
        return arr
    mms_S_A_arr = _mms_arr(mms_S_A_field)
    mms_S_B_arr = _mms_arr(mms_S_B_field)
    mms_S_s_arr = _mms_arr(mms_S_s_field)

    # B-plan B2: make the real-coords face fluxes discretely solenoidal so the
    # conservative kernel telescopes exactly. Required because the reverse-dir
    # transform leaves a per-cell mass divergence; forward fluids are unchanged.
    if _cons == 1:
        ufA, vfA, wfA = _project_faces_div_free(
            ufA, vfA, wfA, eps_fA_arr, rho_cp_fA_arr, dx_arr, dy_arr, dz_arr)
        ufB, vfB, wfB = _project_faces_div_free(
            ufB, vfB, wfB, eps_fB_arr, rho_cp_fB_arr, dx_arr, dy_arr, dz_arr)

    while done < max_iter:
        n = min(chunk, max_iter - done)
        if use_stag:
            _use_rb = _RB_ENERGY and (Nx * Ny * Nz > _RB_ENERGY_GATE)
            _stag_fn = (_gs_full_chunk_3d_stag_rb if _use_rb
                        else _gs_full_chunk_3d_stag)
            chg = _stag_fn(
                Ta, Tb, Ts, Nx, Ny, Nz,
                dx_arr, dy_arr, dz_arr,
                K_ffA_arr, K_ffB_arr, K_ss_arr,
                h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
                rho_cp_fA_arr, rho_cp_fB_arr,
                ufA, vfA, wfA, ufB, vfB, wfB,
                dir_A, dir_B, T_inA_arr, T_inB_arr,
                ifrac_A, ifrac_B,
                n, freeze_Tb, a_fA, a_s, a_fB,
                chi_B_arr, chi_B_thr,
                mms_S_A_arr, mms_S_B_arr, mms_S_s_arr,
                _cons)
        else:
            chg = _gs_full_chunk_3d(
                Ta, Tb, Ts, Nx, Ny, Nz,
                dx_arr, dy_arr, dz_arr,
                K_ffA_arr, K_ffB_arr, K_ss_arr,
                h_vA_arr, h_vB_arr, eps_fA_arr, eps_fB_arr,
                rho_cp_fA_arr, rho_cp_fB_arr,
                ucA, vcA, wcA, ucB, vcB, wcB,
                dir_A, dir_B, T_inA_arr, T_inB_arr,
                ifrac_A, ifrac_B,
                n, freeze_Tb, a_fA, a_s, a_fB)
        done += n
        if progress_cb:
            progress_cb(done, max_iter)
        # Cooperative cancel (point 4): bail between GS chunks so a long LTNE
        # solve aborts promptly instead of waiting out all max_iter sweeps.
        if cancel_check is not None and cancel_check():
            break

        # Convergence: AND of (relative ΔQ_B) and (max |ΔT*|). Q-only
        # could flag converged while Ta/Ts drifted — especially when Tb
        # is frozen (prescribed validation cases) the B-interface Q is
        # decoupled from A-side relaxation.
        Q_cur = float(np.sum(h_vB_arr * (Ts - Tb) * cell_vol))
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
            # Converge on BOTH Q-stable AND field-stable (max per-chunk ΔT below
            # T_abs_tol). Q-alone can false-exit while Ta/Ts still drift (10-15%
            # Q error — 2026-04-24 FV finding); field-stable alone can false-exit
            # while Q drifts. Requiring both is robust AND lets a genuinely
            # converged solve stop at the first qualifying chunk instead of
            # overshooting to max_iter (2026-06-24 — with chunk=250 this halves
            # energy sweeps at bit-identical Q/dP on the 40^3 benchmark).
            if rel_chg < q_tol and max(dTa_max, dTb_max, dTs_max) < T_abs_tol:
                converged = True
                break
        Q_prev = Q_cur
        Ta_prev = Ta.copy(); Tb_prev = Tb.copy(); Ts_prev = Ts.copy()

    info = {
        'converged': converged,
        'iterations': done,
        'residual': float(chg),
        'delegated_to_2d': False,
    }
    if _cons == 1:
        # Strict-conservation certificate: residual of the conservative
        # discretisation on the converged field. The summed form is the global
        # balance ∮_∂interior − ∫interior S; the cell-max form (normalised by
        # the mean per-cell source) certifies per-cell ∮F·n = ∫S.
        ncell = Ta.size
        rA, QA, mA = _conservation_residual_sum(
            Ta, Ts, ufA, vfA, wfA, eps_fA_arr, K_ffA_arr, rho_cp_fA_arr,
            h_vA_arr, dx_arr, dy_arr, dz_arr, dir_A)
        info['eps_A_strict'] = abs(rA) / max(abs(QA), _Q_FLOOR_W)
        info['eps_A_strict_cellmax'] = mA * ncell / max(abs(QA), _Q_FLOOR_W)
        if freeze_Tb == 0:
            rB, QB, mB = _conservation_residual_sum(
                Tb, Ts, ufB, vfB, wfB, eps_fB_arr, K_ffB_arr, rho_cp_fB_arr,
                h_vB_arr, dx_arr, dy_arr, dz_arr, dir_B)
            info['eps_B_strict'] = abs(rB) / max(abs(QB), _Q_FLOOR_W)
            info['eps_B_strict_cellmax'] = mB * ncell / max(abs(QB), _Q_FLOOR_W)
        else:
            info['eps_B_strict'] = 0.0
            info['eps_B_strict_cellmax'] = 0.0
    if return_info:
        return Ta, Tb, Ts, info
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
    """Pre-compile the LTNE GS kernels on import so the user's first 3D Run does
    not pay the multi-second numba compile. Best-effort, never raises.

    E1 (audit 2026-06-28): must warm the DEFAULT-path STAGGERED kernels
    (_gs_full_chunk_3d_stag + the >30k-cell red-black _stag_rb), not just the
    legacy cell-centered kernel. PRODUCTION runs conservative_ltne=True (injected
    by the pipeline cfg.get('conservative_ltne', True) and core.evaluators —
    solve_full_domain_3d's OWN signature default is False), so the stag kernel is
    what production dispatches (the cc kernel is unreachable once
    conservative_ltne=True). The prior warmup also passed one too few `eps`
    args (34 vs 35), so its TypeError was swallowed and it compiled NOTHING.
    """
    try:
        Nx = Ny = Nz = 4
        Ta = np.full((Nx, Ny, Nz), 300.0)
        Tb = np.full((Nx, Ny, Nz), 290.0)
        Ts = np.full((Nx, Ny, Nz), 295.0)
        dx = np.full(Nx, 0.01); dy = np.full(Ny, 0.01); dz = np.full(Nz, 0.01)
        K = np.full((Nx, Ny, Nz), 0.1); hv = np.full((Nx, Ny, Nz), 100.0)
        ef = np.full((Nx, Ny, Nz), 0.5); rcp = np.full((Nx, Ny, Nz), 1000.0)
        uc = np.full((Nx, Ny, Nz), 0.5); v0 = np.zeros((Nx, Ny, Nz))
        TinA = np.full((Ny, Nz), 300.0); TinB = np.full((Nx, Nz), 290.0)
        fA = np.ones((Ny, Nz)); fB = np.ones((Nx, Nz))
        chi = np.ones((Nx, Ny, Nz)); mms = np.zeros((Nx, Ny, Nz))
        # staggered face velocities for the conservative default path
        ufA = np.full((Nx + 1, Ny, Nz), 0.5)
        vfA = np.zeros((Nx, Ny + 1, Nz)); wfA = np.zeros((Nx, Ny, Nz + 1))
        ufB = np.full((Nx + 1, Ny, Nz), 0.5)
        vfB = np.zeros((Nx, Ny + 1, Nz)); wfB = np.zeros((Nx, Ny, Nz + 1))
        # legacy cell-centered kernel (force_cc_ltne fallback path)
        _gs_full_chunk_3d(
            Ta.copy(), Tb.copy(), Ts.copy(), Nx, Ny, Nz, dx, dy, dz,
            K, K, K, hv, hv, ef, ef, rcp, rcp,
            uc, v0, v0, uc, v0, v0,
            0, 3, TinA, TinB, fA, fB, 1, 0, 0.7, 0.7, 0.7)
        # default-path staggered kernels (serial + red-black), conservative form
        for _stag in (_gs_full_chunk_3d_stag, _gs_full_chunk_3d_stag_rb):
            _stag(
                Ta.copy(), Tb.copy(), Ts.copy(), Nx, Ny, Nz, dx, dy, dz,
                K, K, K, hv, hv, ef, ef, rcp, rcp,
                ufA, vfA, wfA, ufB, vfB, wfB,
                0, 3, TinA, TinB, fA, fB, 1, 0, 0.7, 0.7, 0.7,
                chi, 0.5, mms, mms, mms, 1)
    except Exception:
        pass


_warmup_jit()
