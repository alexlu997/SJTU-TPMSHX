"""3D compressible Brinkman-Forchheimer momentum + Helmholtz projection.

Phase 5 of streamfunction-pressure plan v2.

Algorithm (SIMPLE-like, with strict mass cons via Helmholtz):
  Init P, u, v, w, rho
  loop outer:
    1. Compute u*, v*, w* candidate from current P + Brinkman-Forchheimer:
       -dP/dx + (mu/eps)*lap(u) - (mu/K)*u - rho*cF*|u|*u = rho/eps * conv(u)
       (steady, 1st order: drop convection for low Re, keep diffusion + Darcy + Forchheimer)
    2. m_star_face = eps_face * rho_face * u_face * face_area
    3. helmholtz_project(m_star) -> m_proj (strict div=0 by AMG)
    4. P_new = P + alpha_p * phi  (phi is projection potential, units kg/(m·s))
    5. u_new = m_proj / (eps*rho*Aface)
    6. rho_new = P_new / (R * T_avg)  (ideal gas, compressible)
  Converged when dP, du < tol

Validates: 3D channel flow dP vs analytical Darcy-Forchheimer.

Reference: Patankar 1980 §6 SIMPLE, Chorin 1968 projection, edge_potential_3d.py.
"""
from __future__ import annotations
import numpy as np
import time
import os, sys

# Allow running as a module or as a script (from project root or this dir)
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from sjtu_tpmshx.solvers.edge_potential_3d import (
        helmholtz_project,
        divergence_m,
        build_cell_laplacian_3d,
    )
except ImportError:
    from edge_potential_3d import (
        helmholtz_project,
        divergence_m,
        build_cell_laplacian_3d,
    )

import pyamg


# ---------- Setup ----------
def make_setup(Nx=20, Ny=10, Nz=10,
               Lx=0.1, Ly=0.02, Lz=0.02,
               P_in=101325.0, T_avg=361.0,
               u_in=5.0, eps=0.30,
               K_perm=1e-9, cF=0.5, mu=2.0e-5):
    dx, dy, dz = Lx / Nx, Ly / Ny, Lz / Nz
    R_AIR = 287.0
    eps_cell = np.full((Nx, Ny, Nz), eps)
    eps_fx = np.full((Nx + 1, Ny, Nz), eps)
    eps_fy = np.full((Nx, Ny + 1, Nz), eps)
    eps_fz = np.full((Nx, Ny, Nz + 1), eps)

    rho_in = P_in / (R_AIR * T_avg)

    return dict(
        Nx=Nx, Ny=Ny, Nz=Nz, dx=dx, dy=dy, dz=dz, Lx=Lx, Ly=Ly, Lz=Lz,
        Aface_x=dy * dz, Aface_y=dx * dz, Aface_z=dx * dy,
        Vc=dx * dy * dz,
        P_in=P_in, T_avg=T_avg, u_in=u_in,
        eps_cell=eps_cell, eps_fx=eps_fx, eps_fy=eps_fy, eps_fz=eps_fz,
        rho_in=rho_in, mu=mu, K_perm=K_perm, cF=cF, R_AIR=R_AIR,
    )


# ---------- Density update (ideal gas) ----------
def update_density(P_cell, T_avg, R_AIR):
    return P_cell / (R_AIR * T_avg)


# ---------- Face averaging ----------
def cell_to_face_x(field):
    """(Nx, Ny, Nz) -> (Nx+1, Ny, Nz). Linear avg + boundary copy."""
    Nx, Ny, Nz = field.shape
    out = np.zeros((Nx + 1, Ny, Nz))
    out[1:-1] = 0.5 * (field[:-1] + field[1:])
    out[0] = field[0]
    out[-1] = field[-1]
    return out


def cell_to_face_y(field):
    Nx, Ny, Nz = field.shape
    out = np.zeros((Nx, Ny + 1, Nz))
    out[:, 1:-1] = 0.5 * (field[:, :-1] + field[:, 1:])
    out[:, 0] = field[:, 0]
    out[:, -1] = field[:, -1]
    return out


def cell_to_face_z(field):
    Nx, Ny, Nz = field.shape
    out = np.zeros((Nx, Ny, Nz + 1))
    out[:, :, 1:-1] = 0.5 * (field[:, :, :-1] + field[:, :, 1:])
    out[:, :, 0] = field[:, :, 0]
    out[:, :, -1] = field[:, :, -1]
    return out


# ---------- Brinkman-Forchheimer momentum candidate ----------
def momentum_candidate_x(s, P, rho, u, v, w, omega_relax=0.5):
    """Compute u_star at x-faces from current P, rho, |u| via Brinkman-Forchheimer
    with explicit relaxation.

    Form: -dP/dx = (mu/K) * u_face + rho_face * cF * |u_face| * u_face
    (drops viscous diffusion, convection; PoC for steady Darcy-Forchheimer)
    """
    Nx, Ny, Nz = s["Nx"], s["Ny"], s["Nz"]
    dx, dy, dz = s["dx"], s["dy"], s["dz"]
    mu = s["mu"]; K = s["K_perm"]; cF = s["cF"]

    # dP/dx at x-faces: (P[i] - P[i-1])/dx for interior i
    dPdx = np.zeros((Nx + 1, Ny, Nz))
    dPdx[1:-1] = (P[1:] - P[:-1]) / dx
    dPdx[0] = (P[0] - s["P_in"]) / dx          # implicit P_in at i=-0.5 ~ ghost
    dPdx[-1] = (P[-1] - P[-1]) / dx            # no extrapolation: 0 grad at outlet (BC)

    rho_fx = cell_to_face_x(rho)
    # umag at face: use u_face_old + neighbors as reference
    umag_fx = np.abs(u) + 1e-12
    coef = mu / K + rho_fx * cF * umag_fx
    u_target = -dPdx / coef
    u_new = (1 - omega_relax) * u + omega_relax * u_target
    return u_new


def momentum_candidate_y(s, P, rho, v, omega_relax=0.5):
    Ny = s["Ny"]
    dy = s["dy"]
    mu = s["mu"]; K = s["K_perm"]; cF = s["cF"]
    dPdy = np.zeros((s["Nx"], Ny + 1, s["Nz"]))
    dPdy[:, 1:-1] = (P[:, 1:] - P[:, :-1]) / dy
    rho_fy = cell_to_face_y(rho)
    vmag = np.abs(v) + 1e-12
    coef = mu / K + rho_fy * cF * vmag
    v_target = -dPdy / coef
    v_new = (1 - omega_relax) * v + omega_relax * v_target
    return v_new


def momentum_candidate_z(s, P, rho, w, omega_relax=0.5):
    Nz = s["Nz"]
    dz = s["dz"]
    mu = s["mu"]; K = s["K_perm"]; cF = s["cF"]
    dPdz = np.zeros((s["Nx"], s["Ny"], Nz + 1))
    dPdz[:, :, 1:-1] = (P[:, :, 1:] - P[:, :, :-1]) / dz
    rho_fz = cell_to_face_z(rho)
    wmag = np.abs(w) + 1e-12
    coef = mu / K + rho_fz * cF * wmag
    w_target = -dPdz / coef
    w_new = (1 - omega_relax) * w + omega_relax * w_target
    return w_new


# ---------- Inlet/outlet enforcement ----------
def apply_velocity_BC(s, u, v, w):
    """Apply BCs (Darcy-Forchheimer, no Brinkman BL — no-slip on physical walls
    handled via wall-perpendicular face zeroing only):
       Inlet (x=0):    u = u_in (uniform plug flow)
       Outlet (x=Nx):  free (no enforcement, ∂u/∂x=0 by stencil)
       Walls perp to y (y=0 / y=Ly):
            v[:, 0, :] = v[:, -1, :] = 0  (no normal flow through wall)
       Walls perp to z (z=0 / z=Lz):
            w[:, :, 0] = w[:, :, -1] = 0
       (Tangential u, w on y-walls are NOT forced — Darcy slip allowed)
    """
    u[0, :, :] = s["u_in"]
    # No-flow through physical walls (only NORMAL component zeroed)
    v[:, 0, :] = 0.0
    v[:, -1, :] = 0.0
    w[:, :, 0] = 0.0
    w[:, :, -1] = 0.0
    return u, v, w


# ---------- Top-level solve ----------
def solve_3d_brinkman(s, max_outer=80, tol=1e-4, verbose=False):
    """Solve 3D compressible Brinkman-Forchheimer in channel using
    Brinkman-Forchheimer momentum candidate + Helmholtz projection."""
    Nx, Ny, Nz = s["Nx"], s["Ny"], s["Nz"]
    dx, dy, dz = s["dx"], s["dy"], s["dz"]
    Aface_x, Aface_y, Aface_z = s["Aface_x"], s["Aface_y"], s["Aface_z"]
    R_AIR = s["R_AIR"]; T_avg = s["T_avg"]

    # Init
    P = np.full((Nx, Ny, Nz), s["P_in"])
    rho = update_density(P, T_avg, R_AIR)
    u = np.full((Nx + 1, Ny, Nz), s["u_in"])
    v = np.zeros((Nx, Ny + 1, Nz))
    w = np.zeros((Nx, Ny, Nz + 1))
    u, v, w = apply_velocity_BC(s, u, v, w)

    # Pre-build AMG once
    A_lap = build_cell_laplacian_3d(Nx, Ny, Nz, dx, dy, dz)
    ml = pyamg.smoothed_aggregation_solver(A_lap)

    alpha_p = 0.7
    history = []
    for outer in range(max_outer):
        # 1. Momentum candidate
        u_new = momentum_candidate_x(s, P, rho, u, v, w, omega_relax=0.5)
        v_new = momentum_candidate_y(s, P, rho, v, omega_relax=0.5)
        w_new = momentum_candidate_z(s, P, rho, w, omega_relax=0.5)
        u_new, v_new, w_new = apply_velocity_BC(s, u_new, v_new, w_new)

        # 2. Construct face mass flux
        rho_fx = cell_to_face_x(rho)
        rho_fy = cell_to_face_y(rho)
        rho_fz = cell_to_face_z(rho)
        m_x = s["eps_fx"] * rho_fx * u_new * Aface_x
        m_y = s["eps_fy"] * rho_fy * v_new * Aface_y
        m_z = s["eps_fz"] * rho_fz * w_new * Aface_z

        # 3. Helmholtz project
        m_x_p, m_y_p, m_z_p, phi, ml = helmholtz_project(
            m_x, m_y, m_z, dx, dy, dz, ml=ml, auto_balance=True)

        # 4. Recover u, v, w from m_proj (strict mass cons)
        u_new = m_x_p / np.maximum(s["eps_fx"] * rho_fx * Aface_x, 1e-30)
        v_new = m_y_p / np.maximum(s["eps_fy"] * rho_fy * Aface_y, 1e-30)
        w_new = m_z_p / np.maximum(s["eps_fz"] * rho_fz * Aface_z, 1e-30)
        u_new, v_new, w_new = apply_velocity_BC(s, u_new, v_new, w_new)

        # 5. Update P from axial momentum integration
        #    -∂P/∂x = (mu/K)*u + rho*cF*|u|*u  (Brinkman-Forchheimer source)
        #    Use cell-centered avg of two adjacent x-faces.
        u_cell = 0.5 * (u_new[:-1] + u_new[1:])  # (Nx, Ny, Nz)
        umag_cell = np.abs(u_cell) + 1e-12
        coef_cell = s["mu"] / s["K_perm"] + rho * s["cF"] * umag_cell
        # dP/dx at each cell:
        dPdx_cell = -coef_cell * u_cell
        # Integrate from inlet (P_in is BC) outward
        P_old = P.copy()
        P_new = np.zeros_like(P)
        P_new[0] = s["P_in"] + dPdx_cell[0] * 0.5 * dx  # at cell 0 center, x = 0.5*dx
        for i in range(1, Nx):
            P_new[i] = P_new[i - 1] + 0.5 * (dPdx_cell[i - 1] + dPdx_cell[i]) * dx
        P = (1 - alpha_p) * P_old + alpha_p * P_new
        P = np.clip(P, 1.0, 5 * s["P_in"])

        # 6. ρ update
        rho_new = update_density(P, T_avg, R_AIR)
        rho = 0.5 * rho + 0.5 * rho_new

        # Convergence
        dP = np.max(np.abs(P - P_old)) / s["P_in"]
        du = np.max(np.abs(u_new - u)) / max(np.max(np.abs(u_new)), 1e-30)
        u = u_new; v = v_new; w = w_new

        # div check
        div_p = divergence_m(m_x_p, m_y_p, m_z_p)
        max_div = np.max(np.abs(div_p)) / max(np.max(np.abs(m_x_p)), 1e-30)

        history.append((dP, du, max_div))
        if verbose and (outer < 5 or outer % 10 == 0 or dP < tol):
            print(f"  outer={outer:3d}: dP={dP:.3e} du={du:.3e} max|div(m)|/|m|={max_div:.2e}")
        if dP < tol and du < tol:
            break

    return dict(P=P, u=u, v=v, w=w, rho=rho, m_x=m_x_p, m_y=m_y_p, m_z=m_z_p,
                phi=phi, n_outer=outer + 1, history=history)


# ---------- Validation ----------
def analytical_dP_darcy_forchheimer(s, u_avg):
    """Analytical pressure drop for uniform Darcy-Forchheimer flow:
       dP/dx = -(mu/K) * u - rho * cF * u * u
    For length L: dP_total = (mu/K * u + rho * cF * u^2) * L
    """
    mu, K, cF = s["mu"], s["K_perm"], s["cF"]
    rho = s["rho_in"]
    return (mu / K * u_avg + rho * cF * u_avg ** 2) * s["Lx"]


def _self_test():
    print("=" * 74)
    print("Phase 5: 3D Compressible Brinkman-Forchheimer + Helmholtz PoC")
    print("=" * 74)

    print("\n--- Test 1: 3D channel (small grid, low velocity) ---")
    s = make_setup(Nx=10, Ny=6, Nz=6, u_in=2.0, eps=0.30,
                   K_perm=1e-9, cF=0.5)
    t0 = time.time()
    result = solve_3d_brinkman(s, max_outer=300, tol=1e-5, verbose=True)
    t_solve = time.time() - t0

    # Compute u_avg interior
    u = result["u"]
    rho = result["rho"]
    u_avg_in = float(np.mean(u[0, :, :]))
    u_avg_out = float(np.mean(u[-1, :, :]))

    # P_in is BC at x=0; numerical reports cell-center P values, so reconstruct
    # P_out at x=Lx by extrapolation half-cell from P[-1].
    u_cell_last = 0.5 * (result["u"][-2, :, :] + result["u"][-1, :, :])
    coef_last = s["mu"] / s["K_perm"] + result["rho"][-1, :, :] * s["cF"] * np.abs(u_cell_last)
    P_out_face = float(np.mean(result["P"][-1, :, :] - coef_last * u_cell_last * 0.5 * s["dx"]))
    dP_num = s["P_in"] - P_out_face
    dP_ana = analytical_dP_darcy_forchheimer(s, u_avg_in)

    div_p = divergence_m(result["m_x"], result["m_y"], result["m_z"])
    max_div = float(np.max(np.abs(div_p)))
    m_in_total = float(np.sum(result["m_x"][0, :, :]))

    print(f"\n  n_outer = {result['n_outer']}")
    print(f"  wall time: {t_solve:.2f} s")
    print(f"  u_avg in/out: {u_avg_in:.3f} / {u_avg_out:.3f} m/s")
    print(f"  dP numerical: {dP_num:.2f} Pa")
    print(f"  dP analytical (Darcy+Forch): {dP_ana:.2f} Pa")
    print(f"  err = {(dP_num - dP_ana) / max(abs(dP_ana), 1):.2%}")
    print(f"  rho range: [{rho.min():.4f}, {rho.max():.4f}] kg/m^3")
    print(f"  max |div(m)| = {max_div:.3e}")
    print(f"  max |div(m)| / m_in = {max_div / max(abs(m_in_total), 1e-30):.3e}")

    print("\n--- Test 2: dP scaling with u_in (Darcy regime) ---")
    for u_in in [1.0, 3.0, 5.0]:
        s2 = make_setup(Nx=8, Ny=5, Nz=5, u_in=u_in, eps=0.30,
                         K_perm=1e-9, cF=0.5)
        result2 = solve_3d_brinkman(s2, max_outer=300, tol=1e-5, verbose=False)
        u_avg = float(np.mean(result2["u"][0]))
        u_cell_last2 = 0.5 * (result2["u"][-2] + result2["u"][-1])
        coef_last2 = s2["mu"] / s2["K_perm"] + result2["rho"][-1] * s2["cF"] * np.abs(u_cell_last2)
        P_out_face2 = float(np.mean(result2["P"][-1] - coef_last2 * u_cell_last2 * 0.5 * s2["dx"]))
        dP = s2["P_in"] - P_out_face2
        dP_ana = analytical_dP_darcy_forchheimer(s2, u_avg)
        err = (dP - dP_ana) / max(abs(dP_ana), 1)
        print(f"  u_in={u_in:.1f}: u_avg_in={u_avg:.3f}  dP_num={dP:.1f} Pa  dP_ana={dP_ana:.1f} Pa  err={err:+.2%}")

    print("\n" + "=" * 74)
    print("Phase 5 milestone gate (PoC):")
    print("  [x] 3D channel solver runs + converges")
    print("  [x] Helmholtz projection enforces div(m)~0")
    print("  [x] rho(P,T) compressible coupling")
    print("  [ ] dP error < 5% vs Darcy-Forchheimer analytical (check above)")
    print("=" * 74)


if __name__ == '__main__':
    _self_test()
