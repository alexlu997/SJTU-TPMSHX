"""Q_total must stay non-negative and symmetric under T-swap (Option C).

After the Option-C redefinition `Q_total = max(|Q_A_enthalpy|, |Q_B_enthalpy|)`
a swap of (T_inA, T_inB) that keeps |ΔT| fixed should yield the same Q_total
up to solver numerics. This regression guards against accidental regressions
back to the signed ∑h_vB·(Ts−Tb) convention.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from runs.run_calculation import _enthalpy_balance_2d
from optimization.optimizer import (
    _enthalpy_flux_2d, _enthalpy_flux_3d, _q_total_from_enthalpy,
)


def _synthetic_field_2d(T_inA, T_inB, dir_A=0, dir_B=3, Nx=20, Ny=10):
    """Fake but sign-correct enthalpy setup: uniform density field, flow
    fields with unit velocity along the declared direction, linear T ramp
    between inlet and outlet so H_in − H_out is non-zero."""
    rho_cp = np.full((Nx, Ny), 1200.0 * 1005.0)  # ρ·cp rough air
    # A flows +x (dir=0): inlet at i=0 carries T_inA, outlet cools to T_inA − ΔT.
    dT = 20.0
    Ta = np.empty((Nx, Ny))
    for i in range(Nx):
        frac = i / max(Nx - 1, 1)
        Ta[i, :] = T_inA - dT * frac if dir_A == 0 else T_inA + dT * frac
    # B flows -y (dir=3): inlet at j=Ny−1.
    Tb = np.empty((Nx, Ny))
    for j in range(Ny):
        frac = (Ny - 1 - j) / max(Ny - 1, 1)
        Tb[:, j] = T_inB + dT * frac if dir_B == 3 else T_inB - dT * frac
    ucA = np.full((Nx, Ny), 1.0)
    vcA = np.zeros((Nx, Ny))
    ucB = np.zeros((Nx, Ny))
    vcB = np.full((Nx, Ny), -0.5)
    dx = np.full(Nx, 0.01)  # 1 cm cells
    dy = np.full(Ny, 0.005)
    return Ta, Tb, ucA, vcA, ucB, vcB, rho_cp, dx, dy


def test_enthalpy_flux_2d_sign_convention():
    """H_in − H_out positive when fluid cools (T_out < T_in)."""
    T_inA, T_inB = 400.0, 300.0
    Ta, Tb, ucA, vcA, ucB, vcB, rho_cp, dx, dy = _synthetic_field_2d(T_inA, T_inB)
    Q_A = _enthalpy_flux_2d(Ta, ucA, vcA, rho_cp, 0, dx, dy)
    Q_B = _enthalpy_flux_2d(Tb, ucB, vcB, rho_cp, 3, dx, dy)
    assert Q_A > 0, f"A should give up heat; got {Q_A}"
    assert Q_B < 0, f"B should absorb heat (signed convention); got {Q_B}"
    print(f"test_enthalpy_flux_2d_sign_convention PASS (Q_A={Q_A:.1f}, Q_B={Q_B:.1f})")


def test_q_total_invariant_under_T_swap():
    """max(|Q_A|, |Q_B|) is the same whether A or B is the hot side."""
    Ta1, Tb1, ucA, vcA, ucB, vcB, rho_cp, dx, dy = _synthetic_field_2d(400.0, 300.0)
    Q_A1 = _enthalpy_flux_2d(Ta1, ucA, vcA, rho_cp, 0, dx, dy)
    Q_B1 = _enthalpy_flux_2d(Tb1, ucB, vcB, rho_cp, 3, dx, dy)
    Q_total_normal = _q_total_from_enthalpy(Q_A1, Q_B1)

    Ta2, Tb2, _, _, _, _, _, _, _ = _synthetic_field_2d(300.0, 400.0)
    Q_A2 = _enthalpy_flux_2d(Ta2, ucA, vcA, rho_cp, 0, dx, dy)
    Q_B2 = _enthalpy_flux_2d(Tb2, ucB, vcB, rho_cp, 3, dx, dy)
    Q_total_swapped = _q_total_from_enthalpy(Q_A2, Q_B2)

    assert Q_total_normal > 0 and Q_total_swapped > 0
    rel = abs(Q_total_normal - Q_total_swapped) / Q_total_normal
    assert rel < 1e-6, (
        f"Q_total not symmetric: normal={Q_total_normal:.1f}, "
        f"swapped={Q_total_swapped:.1f}, rel={rel:.2e}")
    print(f"test_q_total_invariant_under_T_swap PASS ({Q_total_normal:.1f} W)")


def test_q_total_non_negative():
    """max(|.|,|.|) is non-negative by definition."""
    assert _q_total_from_enthalpy(-1000.0, 500.0) == 1000.0
    assert _q_total_from_enthalpy(0.0, 0.0) == 0.0
    assert _q_total_from_enthalpy(-5.0, -10.0) == 10.0
    print("test_q_total_non_negative PASS")


def test_enthalpy_balance_2d_matches_flux_when_mask_full():
    """run_calculation._enthalpy_balance_2d with full-face masks matches
    the optimizer's mask-free _enthalpy_flux_2d."""
    Ta, _, ucA, vcA, _, _, rho_cp, dx, dy = _synthetic_field_2d(400.0, 300.0)
    Q_flux = _enthalpy_flux_2d(Ta, ucA, vcA, rho_cp, 0, dx, dy)
    Q_bal = _enthalpy_balance_2d(Ta, ucA, vcA, rho_cp, 0, dx, dy)
    assert abs(Q_flux - Q_bal) < 1e-6, (Q_flux, Q_bal)
    print("test_enthalpy_balance_2d_matches_flux_when_mask_full PASS")


def test_enthalpy_balance_2d_mask_gates_integral():
    """Mask halving cross-axis should roughly halve the integral."""
    Ta, _, ucA, vcA, _, _, rho_cp, dx, dy = _synthetic_field_2d(400.0, 300.0)
    Q_full = _enthalpy_balance_2d(Ta, ucA, vcA, rho_cp, 0, dx, dy)
    mask = np.zeros(Ta.shape[1])
    mask[: Ta.shape[1] // 2] = 1.0
    Q_half = _enthalpy_balance_2d(Ta, ucA, vcA, rho_cp, 0, dx, dy,
                                   inlet_mask=mask, outlet_mask=mask)
    assert 0.45 * Q_full < Q_half < 0.55 * Q_full, (Q_full, Q_half)
    print("test_enthalpy_balance_2d_mask_gates_integral PASS")


def test_enthalpy_flux_3d_dir_invariance():
    """Q magnitude should be roughly equal whether A streams +x or +y
    (geometry is cube so physics is isotropic for this synthetic field)."""
    Nx = Ny = Nz = 8
    rho_cp = np.full((Nx, Ny, Nz), 1.2 * 1005.0)
    dx = np.full(Nx, 0.01); dy = np.full(Ny, 0.01); dz = np.full(Nz, 0.01)
    uc = np.full((Nx, Ny, Nz), 1.0); vc = np.zeros_like(uc); wc = np.zeros_like(uc)
    T = np.empty((Nx, Ny, Nz))
    for i in range(Nx):
        T[i, :, :] = 400.0 - 20.0 * i / (Nx - 1)  # cool along +x
    Q_x = _enthalpy_flux_3d(T, uc, vc, wc, rho_cp, 0, dx, dy, dz)

    T_y = np.empty((Nx, Ny, Nz))
    for j in range(Ny):
        T_y[:, j, :] = 400.0 - 20.0 * j / (Ny - 1)  # cool along +y
    uc_y = np.zeros_like(uc); vc_y = np.full_like(uc, 1.0); wc_y = np.zeros_like(uc)
    Q_y = _enthalpy_flux_3d(T_y, uc_y, vc_y, wc_y, rho_cp, 2, dx, dy, dz)

    assert abs(Q_x - Q_y) / Q_x < 1e-6, (Q_x, Q_y)
    print(f"test_enthalpy_flux_3d_dir_invariance PASS ({Q_x:.2f} W)")


if __name__ == '__main__':
    test_enthalpy_flux_2d_sign_convention()
    test_q_total_invariant_under_T_swap()
    test_q_total_non_negative()
    test_enthalpy_balance_2d_matches_flux_when_mask_full()
    test_enthalpy_balance_2d_mask_gates_integral()
    test_enthalpy_flux_3d_dir_invariance()
    print("\nAll tests PASS")
