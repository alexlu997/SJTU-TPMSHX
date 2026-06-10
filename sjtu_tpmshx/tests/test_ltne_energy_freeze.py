"""Unit tests for ltne_energy.py Tb_prescribed freezing logic.
Run via:  python test_solve_full_freeze.py
No pytest needed — uses plain assert statements.
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from solvers.ltne_energy import solve_full_domain

def _common_args(Nx=12, Ny=10):
    L, H = 0.1, 0.05
    T_inA, T_inB = 400.0, 300.0
    K_ffA = 0.025; K_ffB = 0.6; K_ss = 16.0
    h_vA = 500.0; h_vB = 2000.0
    rho_cp_fA = 1100.0; rho_cp_fB = 4.18e6
    epsilon = 0.75
    ucA = np.full((Nx, Ny), 1.5);  vcA = np.zeros((Nx, Ny))
    ucB = np.zeros((Nx, Ny));      vcB = np.full((Nx, Ny), -0.1)
    return dict(L=L, H=H, Nx=Nx, Ny=Ny,
                T_inA=T_inA, T_inB=T_inB,
                K_ffA=K_ffA, K_ffB=K_ffB, K_ss=K_ss,
                h_vA=h_vA, h_vB=h_vB,
                rho_cp_fA=rho_cp_fA, rho_cp_fB=rho_cp_fB,
                epsilon=epsilon,
                ucA=ucA, vcA=vcA, ucB=ucB, vcB=vcB,
                dir_A=0, dir_B=3,
                max_iter=2000, tol=1e-6)

def test_none_preserves_old_behavior():
    args = _common_args()
    Ta, Tb, Ts = solve_full_domain(**args, Tb_prescribed=None)
    # Fluid B should have evolved AWAY from the initial 350 K guess
    assert Tb.min() < 340 or Tb.max() > 360, \
        "Tb should change when not prescribed"
    print("test_none_preserves_old_behavior PASS")

def test_prescribed_pins_Tb_exactly():
    args = _common_args()
    Nx, Ny = args['Nx'], args['Ny']
    # Linear Tb from T_Bout=305 at j=0 to T_Bin=300 at j=Ny-1 (weird on purpose
    # to make sure pinning is exact — NOT interpolated from T_inB)
    Tb_1d = 305.0 + (300.0 - 305.0) * (np.arange(Ny) + 0.5) / Ny
    Tb_prescribed = np.broadcast_to(Tb_1d[None, :], (Nx, Ny)).copy()
    Tb_expected = Tb_prescribed.copy()

    Ta, Tb_out, Ts = solve_full_domain(**args, Tb_prescribed=Tb_prescribed)

    # Tb must match exactly — not one byte different
    max_diff = np.max(np.abs(Tb_out - Tb_expected))
    assert max_diff == 0.0, \
        f"Tb_prescribed was not preserved: max |ΔTb| = {max_diff}"
    # Ta should still have evolved and cooled down (since Tb acts as heat sink)
    assert Ta.min() < 399.0, \
        f"Ta did not cool (min={Ta.min():.2f}); freeze broke coupling"
    # Solid should equilibrate between Ta and Tb
    assert Ts.min() > Tb_expected.min() - 1 and Ts.max() < 401.0, \
        f"Ts out of bounds: [{Ts.min():.2f}, {Ts.max():.2f}]"
    print("test_prescribed_pins_Tb_exactly PASS")

def test_prescribed_shape_mismatch_raises():
    args = _common_args()
    bad = np.zeros((args['Nx'] + 1, args['Ny']))
    try:
        solve_full_domain(**args, Tb_prescribed=bad)
    except ValueError as e:
        assert 'shape' in str(e)
        print("test_prescribed_shape_mismatch_raises PASS")
        return
    raise AssertionError("Expected ValueError for shape mismatch")

if __name__ == '__main__':
    test_none_preserves_old_behavior()
    test_prescribed_pins_Tb_exactly()
    test_prescribed_shape_mismatch_raises()
    print("\nAll tests PASS")
