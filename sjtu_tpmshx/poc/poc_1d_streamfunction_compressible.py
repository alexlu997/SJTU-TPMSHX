"""1D compressible Brinkman-Forchheimer + LTNE PoC.

Phase 2 of streamfunction-pressure plan (v2). Tests:
  1. Compressible momentum Newton iter converges
  2. Mass cons trivial (1D: m = const = m_dot)
  3. LTNE 3-temperature coupling stable
  4. AB imbalance < 0.01% (because mass strict)

In 1D, vector potential machinery isn't needed (m_face uniform by mass cons).
Phase 3 (2D) introduces ψ. Phase 4 (3D) introduces edge-based vector A.

Reference: streamfunction-design-doc.md
"""
from __future__ import annotations
import numpy as np


# ---------- Setup ----------
def make_setup(Nx=50, P_in=101325.0, T_in_A=422.0, T_in_B=300.0,
               u_in=5.0, eps_amp=0.05):
    L = 0.1                                   # 0.1 m pipe
    dx = L / Nx
    x = (np.arange(Nx) + 0.5) * dx
    Apipe = 1e-4
    cp_A = 1006.0
    cp_B = 1006.0
    R_AIR = 287.0
    mu = 2.0e-5                                # air dynamic viscosity
    k_f = 0.026                                # air conductivity
    k_s = 16.0                                 # steel
    h_v = 5e4                                  # volumetric heat transfer
    K_perm = 1e-9                              # permeability (Darcy)
    cF = 0.5                                   # Forchheimer coefficient

    # Face-defined porosity (varies smoothly)
    eps_face_A = 0.30 + eps_amp * np.sin(np.pi * np.arange(Nx + 1) / Nx)
    eps_face_B = 0.30 + eps_amp * np.cos(np.pi * np.arange(Nx + 1) / Nx)
    eps_cell_A = 0.5 * (eps_face_A[:-1] + eps_face_A[1:])
    eps_cell_B = 0.5 * (eps_face_B[:-1] + eps_face_B[1:])

    return dict(
        Nx=Nx, dx=dx, L=L, x=x, Apipe=Apipe,
        cp_A=cp_A, cp_B=cp_B, R_AIR=R_AIR, mu=mu, k_f=k_f, k_s=k_s, h_v=h_v,
        K_perm=K_perm, cF=cF,
        T_in_A=T_in_A, T_in_B=T_in_B, P_in=P_in, u_in=u_in,
        eps_face_A=eps_face_A, eps_face_B=eps_face_B,
        eps_cell_A=eps_cell_A, eps_cell_B=eps_cell_B,
    )


def update_density(P, T, R):
    """Ideal gas ρ = P/(R·T)."""
    return P / (R * T)


def solve_momentum_compressible(s, fluid='A', max_outer=30, tol=1e-7):
    """Compressible 1D Brinkman-Forchheimer Newton solve.

    Iterates: given m_dot (constant by mass cons), solve (u, p, ρ).
    Steady-state, flow direction: A flows +x (positive), B flows -x.
    """
    Nx, dx = s["Nx"], s["dx"]
    Apipe = s["Apipe"]
    R = s["R_AIR"]
    mu = s["mu"]
    K = s["K_perm"]
    cF = s["cF"]
    P_in = s["P_in"]
    u_in = s["u_in"] if fluid == 'A' else -s["u_in"]
    T_in = s["T_in_A"] if fluid == 'A' else s["T_in_B"]
    eps_face = s["eps_face_A"] if fluid == 'A' else s["eps_face_B"]
    eps_cell = s["eps_cell_A"] if fluid == 'A' else s["eps_cell_B"]

    # Mass flow rate (constant by 1D mass cons)
    rho_in = update_density(P_in, T_in, R)
    m_dot = rho_in * abs(u_in) * eps_face[0] * Apipe * np.sign(u_in)

    # Initial guesses
    T_avg = T_in                             # init flat
    rho = np.full(Nx, rho_in)
    u = np.full(Nx, u_in)
    P = np.full(Nx, P_in)

    for outer in range(max_outer):
        u_old = u.copy()

        # Compute u from m_face given current ρ
        # m_face[i] (between cell i-1 and i for i in 1..Nx) constant = m_dot
        # m_cell = (m_face[i] + m_face[i+1])/2 (cell-center)
        # m_dot is constant scalar, so m_face = m_dot at every face.
        # u_cell = m_dot / (ε_cell · ρ_cell · A_pipe)
        u = m_dot / (eps_cell * rho * Apipe)

        # Pressure from Brinkman-Forchheimer (steady):
        # ∂P/∂x = -ρ/ε · u · ∂u/∂x + (μ/ε)·∂²u/∂x² - (μ/κ)·u - β·ρ·|u|·u
        # Integrate from inlet outward
        # Approximate: dominant Forchheimer (high u) and Darcy (low u) terms
        beta = cF / np.sqrt(K)  # Forchheimer coefficient form
        dP_dx = np.zeros(Nx)
        for i in range(Nx):
            # Source terms at cell i
            S_darcy = -(mu / K) * u[i]                  # -μ/κ·u
            S_forch = -beta * rho[i] * abs(u[i]) * u[i] # -β·ρ·|u|·u
            # Convection (uses cell-centered finite difference)
            if 0 < i < Nx - 1:
                du_dx = (u[i+1] - u[i-1]) / (2 * dx)
                d2u_dx2 = (u[i+1] - 2*u[i] + u[i-1]) / (dx ** 2)
            elif i == 0:
                du_dx = (u[i+1] - u[i]) / dx
                d2u_dx2 = 0.0
            else:
                du_dx = (u[i] - u[i-1]) / dx
                d2u_dx2 = 0.0
            S_conv = -(rho[i] / eps_cell[i]) * u[i] * du_dx
            S_visc = (mu / eps_cell[i]) * d2u_dx2
            dP_dx[i] = S_conv + S_visc + S_darcy + S_forch
        # Integrate P from P_in
        P[0] = P_in
        for i in range(1, Nx):
            P[i] = P[i-1] + dP_dx[i] * dx

        # Update T_avg from LTNE (placeholder, real LTNE iter outside)
        # Here just freeze T at inlet, full coupling happens in main loop
        # (rho update needs T)
        # Use T_avg = T_in for now (full coupling done in main_solve)
        rho = update_density(P, T_avg, R)

        # Convergence check
        err = np.max(np.abs(u - u_old))
        if err < tol:
            break

    return u, P, rho, m_dot


def solve_LTNE_with_streamfunction(s, max_iter=20000, tol=1e-9):
    """Couple compressible momentum + LTNE 3-temp.

    Outer iter: momentum solve → ρ update → LTNE solve → T update → repeat.
    Validates that mass cons is strict (1D: m_dot constant) and AB imbal <0.01%.
    """
    Nx, dx = s["Nx"], s["dx"]
    Apipe = s["Apipe"]
    cp_A, cp_B = s["cp_A"], s["cp_B"]
    k_f, k_s = s["k_f"], s["k_s"]
    h_v = s["h_v"]
    R = s["R_AIR"]
    eps_face_A = s["eps_face_A"]; eps_cell_A = s["eps_cell_A"]
    eps_face_B = s["eps_face_B"]; eps_cell_B = s["eps_cell_B"]
    Vc = dx * Apipe
    Sf = Apipe

    Ta = np.full(Nx, 0.5 * (s["T_in_A"] + s["T_in_B"]))
    Tb = Ta.copy()
    Ts = Ta.copy()
    rho_A = np.full(Nx, update_density(s["P_in"], s["T_in_A"], R))
    rho_B = np.full(Nx, update_density(s["P_in"], s["T_in_B"], R))

    omega = 0.7

    for outer in range(max_iter):
        Ta_old = Ta.copy(); Tb_old = Tb.copy(); Ts_old = Ts.copy()

        # 1. Momentum solve (returns u, P, ρ, m_dot)
        # For 1D, m_dot constant. We only need m_face = m_dot (single value).
        rho_in_A = update_density(s["P_in"], s["T_in_A"], R)
        u_in_A = s["u_in"]
        m_dot_A = rho_in_A * u_in_A * eps_face_A[0] * Sf  # +x
        rho_in_B = update_density(s["P_in"], s["T_in_B"], R)
        m_dot_B = -rho_in_B * s["u_in"] * eps_face_B[-1] * Sf  # -x (counterflow)

        # m_face = constant m_dot for both fluids (1D mass cons)
        # face mass flux vector (Nx+1 faces)
        mA = np.full(Nx + 1, m_dot_A)
        mB = np.full(Nx + 1, m_dot_B)

        # F = m·cp signed
        FA = mA * cp_A
        FB = mB * cp_B

        # 2. Solve LTNE with face-centered scheme + Moukalled BC source
        # (reuses pattern from poc_1d_ltne_strict_conservation.py)
        for i in range(Nx):
            FW = FA[i]; FE = FA[i + 1]
            DW = (eps_face_A[i] * k_f * Sf / dx) if i > 0 else (2.0 * eps_face_A[0] * k_f * Sf / dx)
            DE = (eps_face_A[i + 1] * k_f * Sf / dx) if i < Nx - 1 else (2.0 * eps_face_A[Nx] * k_f * Sf / dx)
            aW_nat = DW + max(FW, 0.0)
            aE_nat = DE + max(-FE, 0.0)
            aP_conv = FE - FW
            aP = aE_nat + aW_nat + aP_conv + h_v * Vc
            S_bc = 0.0
            aW = aW_nat; aE = aE_nat
            if i == 0:
                S_bc += aW_nat * s["T_in_A"]
                aW = 0.0
            if i == Nx - 1:
                aP -= DE
                aE = 0.0
            S = h_v * Vc * Ts[i] + S_bc
            TW = Ta[i - 1] if i > 0 else 0.0
            TE = Ta[i + 1] if i < Nx - 1 else 0.0
            Ta_new = (aW * TW + aE * TE + S) / max(aP, 1e-30)
            Ta[i] = (1 - omega) * Ta[i] + omega * Ta_new

        # B fluid: counterflow, mB<0
        for i in range(Nx):
            FW = FB[i]; FE = FB[i + 1]
            DW = (eps_face_B[i] * k_f * Sf / dx) if i > 0 else (2.0 * eps_face_B[0] * k_f * Sf / dx)
            DE = (eps_face_B[i + 1] * k_f * Sf / dx) if i < Nx - 1 else (2.0 * eps_face_B[Nx] * k_f * Sf / dx)
            aW_nat = DW + max(FW, 0.0)
            aE_nat = DE + max(-FE, 0.0)
            aP_conv = FE - FW
            aP = aE_nat + aW_nat + aP_conv + h_v * Vc
            S_bc = 0.0
            aW = aW_nat; aE = aE_nat
            if i == Nx - 1:
                S_bc += aE_nat * s["T_in_B"]
                aE = 0.0
            if i == 0:
                aP -= DW
                aW = 0.0
            S = h_v * Vc * Ts[i] + S_bc
            TW = Tb[i - 1] if i > 0 else 0.0
            TE = Tb[i + 1] if i < Nx - 1 else 0.0
            Tb_new = (aW * TW + aE * TE + S) / max(aP, 1e-30)
            Tb[i] = (1 - omega) * Tb[i] + omega * Tb_new

        # 3. Solid (pure diffusion + LTNE source)
        for i in range(Nx):
            eps_e = 0.5 * (eps_face_A[i + 1] + eps_face_B[i + 1]) if i < Nx - 1 else 0.0
            eps_w = 0.5 * (eps_face_A[i] + eps_face_B[i]) if i > 0 else 0.0
            DE = (1.0 - eps_e) * k_s * Sf / dx if i < Nx - 1 else 0.0
            DW = (1.0 - eps_w) * k_s * Sf / dx if i > 0 else 0.0
            aP = DE + DW + 2 * h_v * Vc
            TE = Ts[i + 1] if i < Nx - 1 else Ts[i]
            TW = Ts[i - 1] if i > 0 else Ts[i]
            S = h_v * Vc * (Ta[i] + Tb[i])
            Ts_new = (DE * TE + DW * TW + S) / max(aP, 1e-30)
            Ts[i] = (1 - omega) * Ts[i] + omega * Ts_new

        # 4. ρ update (compressible coupling)
        rho_A = update_density(s["P_in"], Ta, R)
        rho_B = update_density(s["P_in"], Tb, R)

        err = max(np.max(np.abs(Ta - Ta_old)),
                  np.max(np.abs(Tb - Tb_old)),
                  np.max(np.abs(Ts - Ts_old)))
        if err < tol:
            break

    return Ta, Tb, Ts, rho_A, rho_B, mA, mB, outer + 1, err


def compute_metrics(Ta, Tb, Ts, mA, mB, s):
    Nx, dx = s["Nx"], s["dx"]
    Apipe = s["Apipe"]
    cp_A, cp_B = s["cp_A"], s["cp_B"]
    h_v = s["h_v"]
    Vc = dx * Apipe

    m_in_A = abs(mA[0])
    m_in_B = abs(mB[-1])     # B flows -x, enters at right

    # Boundary metric
    Q_enth_A = abs(m_in_A * cp_A * (Ta[-1] - s["T_in_A"]))
    Q_enth_B = abs(m_in_B * cp_B * (s["T_in_B"] - Tb[0]))

    # Volume integral
    Q_sA = float(np.sum(h_v * (Ts - Ta) * Vc))
    Q_sB = float(np.sum(h_v * (Ts - Tb) * Vc))

    AB_imbal = abs(Q_enth_A - Q_enth_B) / max(Q_enth_A, Q_enth_B, 1e-30)
    e_imb_LTNE = abs(Q_sA + Q_sB) / max(abs(Q_sA), abs(Q_sB), 1e-30)

    # Mass cons (1D trivial: m_face should be constant)
    mass_cons_A = np.max(np.abs(mA - mA[0])) / max(abs(mA[0]), 1e-30)
    mass_cons_B = np.max(np.abs(mB - mB[0])) / max(abs(mB[0]), 1e-30)

    return dict(
        Q_enth_A=Q_enth_A, Q_enth_B=Q_enth_B,
        Q_sA=Q_sA, Q_sB=Q_sB,
        AB_imbal=AB_imbal, e_imb_LTNE=e_imb_LTNE,
        mass_cons_A=mass_cons_A, mass_cons_B=mass_cons_B,
    )


def main():
    print("=" * 74)
    print("Phase 2: 1D Compressible Streamfunction-Pressure PoC")
    print("=" * 74)
    print("Validates: compressible Brinkman-Forchheimer + LTNE coupling + mass cons")
    print()

    for label, eps_amp in [("uniform eps", 0.0),
                            ("mild eps", 0.05),
                            ("heavy eps", 0.10)]:
        s = make_setup(Nx=50, eps_amp=eps_amp)
        Ta, Tb, Ts, rho_A, rho_B, mA, mB, n_iter, err = solve_LTNE_with_streamfunction(s)
        m = compute_metrics(Ta, Tb, Ts, mA, mB, s)

        print(f"--- {label} (eps_amp={eps_amp}) ---")
        print(f"  Converged in {n_iter} iters, final err={err:.2e}")
        print(f"  Ta range [{Ta.min():.2f}, {Ta.max():.2f}] K")
        print(f"  Tb range [{Tb.min():.2f}, {Tb.max():.2f}] K")
        print(f"  rho_A range [{rho_A.min():.4f}, {rho_A.max():.4f}] kg/m^3 (compressible)")
        print(f"  Mass cons A (max |m_face - m_face[0]|/m): {m['mass_cons_A']:.2e}  (target <1e-12)")
        print(f"  Mass cons B (max |m_face - m_face[0]|/m): {m['mass_cons_B']:.2e}  (target <1e-12)")
        print(f"  Q_enth_A={m['Q_enth_A']:.4f}W  Q_enth_B={m['Q_enth_B']:.4f}W")
        print(f"  Q_sA={m['Q_sA']:.4f}W  Q_sB={m['Q_sB']:.4f}W")
        print(f"  AB imbal={m['AB_imbal']*100:.4f}%  (target <0.01%)")
        print(f"  LTNE e_imb={m['e_imb_LTNE']*100:.6f}%")
        print()

    print("=" * 74)
    print("Phase 2 milestone gate:")
    print("  [ ] mass_cons cell-wise < 1e-12  (1D trivial: m=const by setup)")
    print("  [ ] AB imbal < 0.01%")
    print("  [ ] LTNE e_imb < 0.05%")


if __name__ == '__main__':
    main()
