"""Opt-in 2D red-black energy kernel — compile + functional-equivalence smoke.

`_gs_full_chunk_rb` (2D) is the `prange`-parallel twin of `_gs_full_chunk`, used
only when `_RB_ENERGY_2D` is enabled on a grid above the gate. It sweeps by
checkerboard colour and reads the 2-away SOU from a start-of-sweep snapshot.

Because the 2D kernel is the NON-conservative cell-centre form, the deferred SOU
shifts the converged field slightly more than the 3D conservative kernel (~0.1 K
on advective cases, <0.03% of T). This test forces RB on (gate 0) and checks the
field stays functionally equivalent to the serial kernel — a regression guard,
not a bit-identity claim.
"""

import numpy as np
import pytest
import sjtu_tpmshx.solvers.ltne_energy as le2
from sjtu_tpmshx.solvers.ltne_energy import solve_full_domain


def _args(Nx, Ny):
    return dict(L=0.1, H=0.05, Nx=Nx, Ny=Ny, T_inA=400.0, T_inB=300.0,
                K_ffA=0.6, K_ffB=0.6, K_ss=16.0, h_vA=500.0, h_vB=2000.0,
                rho_cp_fA=1100.0, rho_cp_fB=4.18e6, epsilon=0.75,
                ucA=np.full((Nx, Ny), 0.4), vcA=np.zeros((Nx, Ny)),
                ucB=np.zeros((Nx, Ny)), vcB=np.full((Nx, Ny), -0.1),
                dir_A=0, dir_B=3, max_iter=6000, tol=1e-8)


@pytest.mark.slow
def test_rb_2d_matches_serial(monkeypatch):
    monkeypatch.setattr(le2, '_RB_ENERGY_2D_GATE', 0)   # force RB on a small grid
    a = _args(48, 40)

    monkeypatch.setattr(le2, '_RB_ENERGY_2D', False)
    Ta_s, Tb_s, Ts_s = solve_full_domain(**a, Tb_prescribed=None)

    monkeypatch.setattr(le2, '_RB_ENERGY_2D', True)
    Ta_r, Tb_r, Ts_r = solve_full_domain(**a, Tb_prescribed=None)

    # Functional equivalence (deferred SOU shifts the converged field slightly on
    # the non-conservative 2D kernel; the shift is engineering-negligible).
    dTa = float(np.abs(Ta_s - Ta_r).max())
    dTb = float(np.abs(Tb_s - Tb_r).max())
    dTs = float(np.abs(Ts_s - Ts_r).max())
    assert dTa < 0.3, f"RB 2D T_A diverged from serial: {dTa:.3e} K"
    assert dTb < 0.3, f"RB 2D T_B diverged from serial: {dTb:.3e} K"
    assert dTs < 0.3, f"RB 2D T_s diverged from serial: {dTs:.3e} K"
