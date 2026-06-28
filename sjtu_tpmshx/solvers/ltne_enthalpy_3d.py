"""Option B enthalpy-form 3D LTNE solver (Phase 2.2).

A self-contained conservative LTNE kernel that keeps specific enthalpy ``h`` as
the primary fluid unknown, so the convection telescopes the mass flux ṁ on h
(true enthalpy flux ṁ·h) instead of the legacy ṁ·cp·T. For a strongly
variable-cp fluid (sCO2 across the pseudocritical line) ṁ·cp·T conserves the
wrong quantity (off by ∫T·dcp → the 703 ~41% A/B imbalance); the enthalpy form
closes it. See the validated 1D PoC poc/poc_1d_ltne_enthalpy_optionB.py and the
plan vault reports/method/3d/2026-06-28-3d-ltne-enthalpy-conservative-rewrite-plan-CN.md.

Architecture (numba constraint): the inner Gauss-Seidel sweeps are @njit and
operate purely on precomputed arrays; ALL CoolProp work (the T = T(h,P) inverse
and the cp/k property fields) lives in the Python driver and is refreshed once
per outer (Picard) iteration. This is the separation the production port uses —
the njit kernel never calls CoolProp.

Scope of THIS module: counterflow along x (dir 0/1), uniform porosity, first-
order upwind. It validates the enthalpy formulation + the njit implementation in
3D. Cross-flow, offset porosity, SOU, staggered-face fluxes and red-black
parallelisation are integration-stage work (Phase 2.3+), folded into the
production kernel ltne_energy_3d.py with an ``enthalpy_mode`` route.
"""
from __future__ import annotations

import numpy as np
from numba import njit

from . import sco2_props

_T_LO, _T_HI = 240.0, 420.0


@njit(cache=True, fastmath=True)
def _gs_enthalpy_sweeps_3d(hA, hB, Ts,
                           dhA, dhB, cpA, cpB,
                           TA_star, TB_star, hA_star, hB_star,
                           epsA, epsB, FmA, FmB,
                           hvA, hvB, ks, dx, dy, dz,
                           h_in_A, h_in_B, dir_A, dir_B,
                           n_sweep, omega, h_lo_A, h_hi_A, h_lo_B, h_hi_B):
    """In-place Gauss-Seidel sweeps for the enthalpy-form LTNE system.

    hA/hB: fluid enthalpy fields (primary unknowns). Ts: solid temperature.
    dhA/dhB: h-space diffusivity (eps·k/cp) fields. cpA/cpB, TA_star/TB_star,
    hA_star/hB_star: frozen-per-outer linearisation data. FmA/FmB: signed
    per-column x mass flux [kg/s]. Counterflow in x (dir 0=+x, 1=−x).
    """
    Nx, Ny, Nz = hA.shape
    Vc = dx * dy * dz
    Ax = dy * dz
    Ay = dx * dz
    Az = dx * dy

    inA_i = 0 if dir_A == 0 else Nx - 1
    outA_i = Nx - 1 if dir_A == 0 else 0
    inB_i = 0 if dir_B == 0 else Nx - 1
    outB_i = Nx - 1 if dir_B == 0 else 0

    for _ in range(n_sweep):
        # ── Fluid A (enthalpy) ──
        for i in range(Nx):
            for j in range(Ny):
                for k in range(Nz):
                    cpi = cpA[i, j, k] if cpA[i, j, k] > 1e-30 else 1e-30
                    # x diffusion faces (h-space)
                    dW = 0.5 * (dhA[i, j, k] + (dhA[i - 1, j, k] if i > 0 else dhA[i, j, k]))
                    dE = 0.5 * (dhA[i, j, k] + (dhA[i + 1, j, k] if i < Nx - 1 else dhA[i, j, k]))
                    DxW = dW * Ax / dx
                    DxE = dE * Ax / dx
                    # y/z diffusion faces
                    dS = 0.5 * (dhA[i, j, k] + (dhA[i, j - 1, k] if j > 0 else dhA[i, j, k]))
                    dN = 0.5 * (dhA[i, j, k] + (dhA[i, j + 1, k] if j < Ny - 1 else dhA[i, j, k]))
                    dB = 0.5 * (dhA[i, j, k] + (dhA[i, j, k - 1] if k > 0 else dhA[i, j, k]))
                    dT = 0.5 * (dhA[i, j, k] + (dhA[i, j, k + 1] if k < Nz - 1 else dhA[i, j, k]))
                    DyS = dS * Ay / dy if j > 0 else 0.0
                    DyN = dN * Ay / dy if j < Ny - 1 else 0.0
                    DzB = dB * Az / dz if k > 0 else 0.0
                    DzT = dT * Az / dz if k < Nz - 1 else 0.0
                    # convection (x only), signed mass flux constant in i
                    aW = DxW + (FmA if FmA > 0.0 else 0.0)
                    aE = DxE + (-FmA if FmA < 0.0 else 0.0)
                    aN = DyN; aS = DyS; aT = DzT; aB = DzB
                    hp_imp = hvA * Vc / cpi
                    aP = aE + aW + aN + aS + aT + aB + hp_imp
                    S = hvA * Vc * (Ts[i, j, k] - TA_star[i, j, k] + hA_star[i, j, k] / cpi)
                    # inlet Dirichlet (extra half-cell diffusion conductance)
                    if i == inA_i:
                        D_bc = 2.0 * dhA[i, j, k] * Ax / dx
                        a_in = D_bc + (abs(FmA))
                        S += a_in * h_in_A
                        if dir_A == 0:
                            aW = 0.0
                        else:
                            aE = 0.0
                        aP += D_bc  # add the half-cell conductance to the diagonal
                    if i == outA_i:
                        if dir_A == 0:
                            aE = 0.0
                        else:
                            aW = 0.0
                    nb = 0.0
                    if i > 0:
                        nb += aW * hA[i - 1, j, k]
                    if i < Nx - 1:
                        nb += aE * hA[i + 1, j, k]
                    if j > 0:
                        nb += aS * hA[i, j - 1, k]
                    if j < Ny - 1:
                        nb += aN * hA[i, j + 1, k]
                    if k > 0:
                        nb += aB * hA[i, j, k - 1]
                    if k < Nz - 1:
                        nb += aT * hA[i, j, k + 1]
                    new = (nb + S) / (aP if aP > 1e-30 else 1e-30)
                    upd = (1.0 - omega) * hA[i, j, k] + omega * new
                    if upd < h_lo_A:
                        upd = h_lo_A
                    elif upd > h_hi_A:
                        upd = h_hi_A
                    hA[i, j, k] = upd

        # ── Fluid B (enthalpy) ──
        for i in range(Nx):
            for j in range(Ny):
                for k in range(Nz):
                    cpi = cpB[i, j, k] if cpB[i, j, k] > 1e-30 else 1e-30
                    dW = 0.5 * (dhB[i, j, k] + (dhB[i - 1, j, k] if i > 0 else dhB[i, j, k]))
                    dE = 0.5 * (dhB[i, j, k] + (dhB[i + 1, j, k] if i < Nx - 1 else dhB[i, j, k]))
                    DxW = dW * Ax / dx
                    DxE = dE * Ax / dx
                    dS = 0.5 * (dhB[i, j, k] + (dhB[i, j - 1, k] if j > 0 else dhB[i, j, k]))
                    dN = 0.5 * (dhB[i, j, k] + (dhB[i, j + 1, k] if j < Ny - 1 else dhB[i, j, k]))
                    dBf = 0.5 * (dhB[i, j, k] + (dhB[i, j, k - 1] if k > 0 else dhB[i, j, k]))
                    dTf = 0.5 * (dhB[i, j, k] + (dhB[i, j, k + 1] if k < Nz - 1 else dhB[i, j, k]))
                    DyS = dS * Ay / dy if j > 0 else 0.0
                    DyN = dN * Ay / dy if j < Ny - 1 else 0.0
                    DzB = dBf * Az / dz if k > 0 else 0.0
                    DzT = dTf * Az / dz if k < Nz - 1 else 0.0
                    aW = DxW + (FmB if FmB > 0.0 else 0.0)
                    aE = DxE + (-FmB if FmB < 0.0 else 0.0)
                    aN = DyN; aS = DyS; aT = DzT; aB = DzB
                    hp_imp = hvB * Vc / cpi
                    aP = aE + aW + aN + aS + aT + aB + hp_imp
                    S = hvB * Vc * (Ts[i, j, k] - TB_star[i, j, k] + hB_star[i, j, k] / cpi)
                    if i == inB_i:
                        D_bc = 2.0 * dhB[i, j, k] * Ax / dx
                        a_in = D_bc + (abs(FmB))
                        S += a_in * h_in_B
                        if dir_B == 0:
                            aW = 0.0
                        else:
                            aE = 0.0
                        aP += D_bc
                    if i == outB_i:
                        if dir_B == 0:
                            aE = 0.0
                        else:
                            aW = 0.0
                    nb = 0.0
                    if i > 0:
                        nb += aW * hB[i - 1, j, k]
                    if i < Nx - 1:
                        nb += aE * hB[i + 1, j, k]
                    if j > 0:
                        nb += aS * hB[i, j - 1, k]
                    if j < Ny - 1:
                        nb += aN * hB[i, j + 1, k]
                    if k > 0:
                        nb += aB * hB[i, j, k - 1]
                    if k < Nz - 1:
                        nb += aT * hB[i, j, k + 1]
                    new = (nb + S) / (aP if aP > 1e-30 else 1e-30)
                    upd = (1.0 - omega) * hB[i, j, k] + omega * new
                    if upd < h_lo_B:
                        upd = h_lo_B
                    elif upd > h_hi_B:
                        upd = h_hi_B
                    hB[i, j, k] = upd

        # ── Solid (T_s) — diffusion + LTNE source, adiabatic ends ──
        for i in range(Nx):
            for j in range(Ny):
                for k in range(Nz):
                    # linearised fluid temperatures from current h (no CoolProp)
                    TAl = TA_star[i, j, k] + (hA[i, j, k] - hA_star[i, j, k]) / (
                        cpA[i, j, k] if cpA[i, j, k] > 1e-30 else 1e-30)
                    TBl = TB_star[i, j, k] + (hB[i, j, k] - hB_star[i, j, k]) / (
                        cpB[i, j, k] if cpB[i, j, k] > 1e-30 else 1e-30)
                    epsS_e = 1.0 - 0.5 * (epsA[i, j, k] + epsB[i, j, k])
                    DxW = epsS_e * ks * Ax / dx if i > 0 else 0.0
                    DxE = epsS_e * ks * Ax / dx if i < Nx - 1 else 0.0
                    DyS = epsS_e * ks * Ay / dy if j > 0 else 0.0
                    DyN = epsS_e * ks * Ay / dy if j < Ny - 1 else 0.0
                    DzB = epsS_e * ks * Az / dz if k > 0 else 0.0
                    DzT = epsS_e * ks * Az / dz if k < Nz - 1 else 0.0
                    aP = (DxW + DxE + DyS + DyN + DzB + DzT
                          + (hvA + hvB) * Vc)
                    nb = 0.0
                    if i > 0:
                        nb += DxW * Ts[i - 1, j, k]
                    if i < Nx - 1:
                        nb += DxE * Ts[i + 1, j, k]
                    if j > 0:
                        nb += DyS * Ts[i, j - 1, k]
                    if j < Ny - 1:
                        nb += DyN * Ts[i, j + 1, k]
                    if k > 0:
                        nb += DzB * Ts[i, j, k - 1]
                    if k < Nz - 1:
                        nb += DzT * Ts[i, j, k + 1]
                    S = (hvA * TAl + hvB * TBl) * Vc
                    new = (nb + S) / (aP if aP > 1e-30 else 1e-30)
                    Ts[i, j, k] = (1.0 - omega) * Ts[i, j, k] + omega * new


def solve_ltne_enthalpy_3d(Nx, Ny, Nz, Lx, Ly, Lz, eps, k_s,
                           m_dot_A, m_dot_B, h_vA, h_vB,
                           T_inA, T_inB, P, P_B=None, dir_A=0, dir_B=1,
                           n_outer=3000, n_sweep=3, omega=0.6, tol=2e-5):
    """Python Picard driver around the njit enthalpy sweeps. CoolProp T(h,P)
    inverse + cp/k property fields refreshed once per outer iteration.

    Per-side pressure: ``P`` is fluid A's pressure, ``P_B`` fluid B's (defaults
    to ``P``). The 703 recuperator runs hot ≈8 MPa / cold ≈18.5 MPa."""
    P_A = float(P)
    P_B = float(P_B) if P_B is not None else P_A
    dx, dy, dz = Lx / Nx, Ly / Ny, Lz / Nz
    shape = (Nx, Ny, Nz)
    epsA = np.full(shape, 0.5 * eps)
    epsB = np.full(shape, 0.5 * eps)
    # per-column signed x mass flux (total split over the Ny·Nz cross-section)
    FmA = float(m_dot_A) / (Ny * Nz)
    FmB = float(m_dot_B) / (Ny * Nz)

    h_in_A = float(sco2_props.sco2_enthalpy(T_inA, P_A))
    h_in_B = float(sco2_props.sco2_enthalpy(T_inB, P_B))
    # clamp the iterate to a generous window around the two inlet temperatures
    T_lo = max(min(T_inA, T_inB) - 40.0, 230.0)
    T_hi = max(T_inA, T_inB) + 40.0
    h_lo_A = float(sco2_props.sco2_enthalpy(T_lo, P_A))
    h_hi_A = float(sco2_props.sco2_enthalpy(T_hi, P_A))
    h_lo_B = float(sco2_props.sco2_enthalpy(T_lo, P_B))
    h_hi_B = float(sco2_props.sco2_enthalpy(T_hi, P_B))

    hA = np.full(shape, h_in_A)
    hB = np.full(shape, h_in_B)
    Ts = np.full(shape, 0.5 * (T_inA + T_inB))

    n_done = 0
    for outer in range(n_outer):
        T_A = sco2_props.sco2_temperature_field(hA, P_A)
        T_B = sco2_props.sco2_temperature_field(hB, P_B)
        cpA = sco2_props.sco2_cp_field(T_A, P_A)
        cpB = sco2_props.sco2_cp_field(T_B, P_B)
        kA = sco2_props.sco2_conductivity_field(T_A, P_A)
        kB = sco2_props.sco2_conductivity_field(T_B, P_B)
        dhA = epsA * kA / np.maximum(cpA, 1e-30)   # h-space diffusivity
        dhB = epsB * kB / np.maximum(cpB, 1e-30)
        hA_star = hA.copy(); hB_star = hB.copy()

        _gs_enthalpy_sweeps_3d(
            hA, hB, Ts, dhA, dhB, cpA, cpB, T_A, T_B, hA_star, hB_star,
            epsA, epsB, FmA, FmB, float(h_vA), float(h_vB), float(k_s),
            dx, dy, dz, h_in_A, h_in_B, int(dir_A), int(dir_B),
            int(n_sweep), float(omega), h_lo_A, h_hi_A, h_lo_B, h_hi_B)

        n_done = outer + 1
        denom = max(abs(h_in_A - h_in_B), 1.0)
        if (max(np.max(np.abs(hA - hA_star)),
                np.max(np.abs(hB - hB_star))) / denom) < tol:
            break

    return dict(Ta=sco2_props.sco2_temperature_field(hA, P_A),
                Tb=sco2_props.sco2_temperature_field(hB, P_B),
                Ts=Ts, hA=hA, hB=hB, n_outer=n_done, P_A=P_A, P_B=P_B)


def enthalpy_metrics_3d(res, case):
    """Conservation metrics. Q_enth via TRUE enthalpy at the stream boundaries;
    Q_solid via the volumetric LTNE exchange."""
    Ta, Tb, Ts = res["Ta"], res["Tb"], res["Ts"]
    Nx, Ny, Nz = Ta.shape
    P_A = res.get("P_A", case["P"])
    P_B = res.get("P_B", case.get("P_B", P_A))
    Vc = (case["Lx"] / Nx) * (case["Ly"] / Ny) * (case["Lz"] / Nz)
    mA = abs(case["m_dot_A"]); mB = abs(case["m_dot_B"])
    hvA, hvB = case["h_vA"], case["h_vB"]
    dir_A, dir_B = case["dir_A"], case["dir_B"]

    outA = -1 if dir_A == 0 else 0
    outB = -1 if dir_B == 0 else 0
    hA_out = float(np.mean(sco2_props.sco2_enthalpy_field(Ta[outA, :, :], P_A)))
    hB_out = float(np.mean(sco2_props.sco2_enthalpy_field(Tb[outB, :, :], P_B)))
    h_in_A = float(sco2_props.sco2_enthalpy(case["T_inA"], P_A))
    h_in_B = float(sco2_props.sco2_enthalpy(case["T_inB"], P_B))

    Q_enth_A = mA * abs(hA_out - h_in_A)
    Q_enth_B = mB * abs(hB_out - h_in_B)
    Q_sA = float(np.sum(hvA * (Ts - Ta) * Vc))
    Q_sB = float(np.sum(hvB * (Ts - Tb) * Vc))

    AB_imbal = abs(Q_enth_A - Q_enth_B) / max(Q_enth_A, Q_enth_B, 1e-30)
    e_imb_LTNE = abs(Q_sA + Q_sB) / max(abs(Q_sA), abs(Q_sB), 1e-30)
    diff_A = abs(Q_enth_A - abs(Q_sA)) / max(Q_enth_A, 1e-30)
    diff_B = abs(Q_enth_B - abs(Q_sB)) / max(Q_enth_B, 1e-30)
    return dict(Q_enth_A=Q_enth_A, Q_enth_B=Q_enth_B, Q_sA=Q_sA, Q_sB=Q_sB,
                AB_imbal=AB_imbal, e_imb_LTNE=e_imb_LTNE,
                diff_A=diff_A, diff_B=diff_B)
