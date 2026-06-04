"""Ground-truth: a reverse-direction (-y) fluid B must produce the exact
y-mirror image of the same case run as a forward (+y) fluid.

Physics: relabeling B's flow +y <-> -y with the inlet/outlet y-mirrored is
the SAME physical problem. So Tb_rev(x, y, z) == Tb_fwd(x, H-y, z) (and Ta, Ts).
Fluid A is air +x with a full-face (y-symmetric) inlet, so the whole coupled
solution mirrors.

This isolates the reverse-dir velocity-transform handling
(_solver_staggered_to_real / _solver_velocity_to_real): the forward (+y, dir=2,
is_reverse=False) path is the trusted reference; the reverse (-y, dir=3) path is
under test. A missing stream-axis flip in the reverse handling breaks the
mirror symmetry.
"""
import sys
from pathlib import Path
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controllers.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig,
    PartialBCConfig, ExtrapPolicy, FeatureFlags,
)
import runs.run_calculation_3d as R


def _cfg(dir_B, in_ctr, out_ctr):
    cc = ComputeConfig(
        fluid_A=FluidConfig(type='air',   u_mps=12.0,  T_in_K=420.0, P_in_Pa=150000.0),
        fluid_B=FluidConfig(type='water', u_mps=0.30,  T_in_K=300.0, P_in_Pa=120000.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.5,
                                k_s_W_mK=16.0, L_dom_m=0.10, H_dom_m=0.042, Lz_m=0.030),
        solver=SolverConfig(Nx=12, Ny=12, Nz=4),
        # A: +x, full-face on the cross (y) faces -> y-symmetric
        bc_A=PartialBCConfig(dir=0, in_ctr=0.021, in_w=0.042,
                             out_ctr=0.021, out_w=0.042),
        # B: dir_B with staggered x-strips (cross-stream = x for +/-y flow)
        bc_B=PartialBCConfig(dir=dir_B, in_ctr=in_ctr, in_w=0.042,
                             out_ctr=out_ctr, out_w=0.042),
        extrap=ExtrapPolicy(allow=True),
        flags=FeatureFlags(wall_refine_3d=False),
    )
    return R._parse_inputs_3d_cfg(cc)


def test_reverse_y_is_mirror_of_forward_y():
    # FORWARD +y (dir=2): inlet at BOTTOM (y=0) x-strip @0.07, outlet TOP @0.03
    cfg_fwd = _cfg(dir_B=2, in_ctr=0.07, out_ctr=0.03)
    # REVERSE -y (dir=3): inlet at TOP (y=H) x-strip @0.07, outlet BOTTOM @0.03
    # This is the exact y-mirror of the forward case.
    cfg_rev = _cfg(dir_B=3, in_ctr=0.07, out_ctr=0.03)

    res_fwd = R._run_3d_stack(cfg_fwd)
    res_rev = R._run_3d_stack(cfg_rev)

    Tb_fwd = res_fwd['Tb']
    Tb_rev = res_rev['Tb']
    # mirror the forward field along the real y-axis (axis=1)
    Tb_fwd_mirrored = Tb_fwd[:, ::-1, :]

    # Relative L2 mismatch of the (cold) water field, normalized by the
    # driving temperature span so the gate is dimensionless.
    span = float(Tb_fwd.max() - Tb_fwd.min())
    assert span > 1.0, "degenerate: no thermal variation to compare"
    rel = float(np.sqrt(np.mean((Tb_rev - Tb_fwd_mirrored) ** 2)) / span)
    # Gate 0.05: the reverse-dir transform bug gave rel ≈ 0.54 (and a spurious
    # >100°C over-boiling peak). With the stream-axis flip in the velocity
    # transforms + no mask in/out swap, rel ≈ 0.02 — the residual is genuine
    # numerical asymmetry between two independent SIMPLE+LTNE solves on this
    # coarse 12³ grid (convergence tol + half-cell mask placement), NOT the
    # systematic mirror error. 0.05 sits 10× below the bug, 2.5× above the
    # converged residual.
    assert rel < 0.05, (
        f"reverse(-y) B is NOT the y-mirror of forward(+y): "
        f"rel L2 = {rel:.4f} (gate 0.05; bug regime ≈ 0.54). "
        f"Tb_fwd[max/min]={Tb_fwd.max()-273.15:.1f}/{Tb_fwd.min()-273.15:.1f}C "
        f"Tb_rev[max/min]={Tb_rev.max()-273.15:.1f}/{Tb_rev.min()-273.15:.1f}C"
    )
