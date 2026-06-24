"""Unit contract for `_project_faces_div_free` (LTNE div-free face projection).

The projection removes the *zero-mean* (interior-correctable) part of the
real-coords face-flux divergence so the conservative kernel telescopes. It must:

  #1  drive the zero-mean divergence to ~0 (the projection actually works),
      regardless of the linear solver used underneath (direct LU or AMG-CG);
  #1b preserve z-reflection symmetry (a z-even divergence -> z-even u/v
      correction, z-odd w correction) — the reason the constraint pins the MEAN
      of phi, not a corner cell (z-symmetry bug, 2026-06-09);
  #2  return an already-(near-)solenoidal field UNCHANGED (bit-exact), skipping
      the O(N) solve entirely — forward-dir fluids are solenoidal by
      construction and must not be perturbed.

These pin behavior before the perf refactor (dense-bordered direct LU ->
cached AMG-preconditioned CG on the plain sparse Laplacian).
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from solvers.ltne_energy_3d import _project_faces_div_free


def _cell_div(uf, vf, wf, eps_f, rcp, dx, dy, dz):
    """Per-cell energy-mass-flux divergence — mirror of the production formula."""
    Nx, Ny, Nz = eps_f.shape
    Ax = dy[None, :, None] * dz[None, None, :]
    Ay = dx[:, None, None] * dz[None, None, :]
    Az = dx[:, None, None] * dy[None, :, None]
    coef = eps_f * rcp
    cf_x = np.empty_like(uf)
    cf_x[1:-1, :, :] = 0.5 * (coef[:-1, :, :] + coef[1:, :, :])
    cf_x[0, :, :] = coef[0, :, :]; cf_x[-1, :, :] = coef[-1, :, :]
    cf_y = np.empty_like(vf)
    cf_y[:, 1:-1, :] = 0.5 * (coef[:, :-1, :] + coef[:, 1:, :])
    cf_y[:, 0, :] = coef[:, 0, :]; cf_y[:, -1, :] = coef[:, -1, :]
    cf_z = np.empty_like(wf)
    cf_z[:, :, 1:-1] = 0.5 * (coef[:, :, :-1] + coef[:, :, 1:])
    cf_z[:, :, 0] = coef[:, :, 0]; cf_z[:, :, -1] = coef[:, :, -1]
    Fx = cf_x * uf * np.broadcast_to(Ax, uf.shape)
    Fy = cf_y * vf * np.broadcast_to(Ay, vf.shape)
    Fz = cf_z * wf * np.broadcast_to(Az, wf.shape)
    return ((Fx[1:, :, :] - Fx[:-1, :, :])
            + (Fy[:, 1:, :] - Fy[:, :-1, :])
            + (Fz[:, :, 1:] - Fz[:, :, :-1]))


def _uniform_props(Nx, Ny, Nz, L=0.18, H=0.05, D=0.04):
    eps_f = np.full((Nx, Ny, Nz), 0.25)
    rcp = np.full((Nx, Ny, Nz), 1.2 * 1005.0)
    dx = np.full(Nx, L / Nx); dy = np.full(Ny, H / Ny); dz = np.full(Nz, D / Nz)
    return eps_f, rcp, dx, dy, dz


def test_projection_removes_zero_mean_divergence():
    """#1 — interior projection kills the correctable (zero-mean) divergence.

    A generic non-solenoidal field has a large zero-mean divergence component.
    After projection the per-cell divergence must collapse to a spatial
    CONSTANT (= the net boundary imbalance, which interior faces cannot fix),
    i.e. its zero-mean part -> ~0. A loosely-converged solve leaves residual
    structure and fails this.
    """
    Nx, Ny, Nz = 12, 10, 8
    eps_f, rcp, dx, dy, dz = _uniform_props(Nx, Ny, Nz)
    rng = np.random.default_rng(0)
    uf = rng.standard_normal((Nx + 1, Ny, Nz))
    vf = rng.standard_normal((Nx, Ny + 1, Nz))
    wf = rng.standard_normal((Nx, Ny, Nz + 1))

    D_in = _cell_div(uf, vf, wf, eps_f, rcp, dx, dy, dz)
    zm_in = np.abs(D_in - D_in.mean()).max()
    assert zm_in > 1e-3, "test field must carry a real zero-mean divergence"

    out_uf, out_vf, out_wf = _project_faces_div_free(
        uf, vf, wf, eps_f, rcp, dx, dy, dz)
    D_out = _cell_div(out_uf, out_vf, out_wf, eps_f, rcp, dx, dy, dz)
    zm_out = np.abs(D_out - D_out.mean()).max()

    assert zm_out / zm_in < 1e-8, (
        f"zero-mean divergence not removed: {zm_out:.3e} / {zm_in:.3e} "
        f"= {zm_out / zm_in:.3e} (solver under-converged?)")


def test_projection_preserves_z_symmetry():
    """#1b — a z-even divergence yields z-even u/v and z-odd w corrections."""
    Nx, Ny, Nz = 10, 8, 8
    eps_f, rcp, dx, dy, dz = _uniform_props(Nx, Ny, Nz)
    rng = np.random.default_rng(1)
    # z-even u/v, z-odd w  -> a z-even divergence field
    half = rng.standard_normal((Nx + 1, Ny, Nz // 2))
    uf = np.concatenate([half, np.flip(half, axis=-1)], axis=-1)
    halfv = rng.standard_normal((Nx, Ny + 1, Nz // 2))
    vf = np.concatenate([halfv, np.flip(halfv, axis=-1)], axis=-1)
    wf = np.zeros((Nx, Ny, Nz + 1))

    out_uf, out_vf, out_wf = _project_faces_div_free(
        uf, vf, wf, eps_f, rcp, dx, dy, dz)

    asym_u = np.abs(out_uf - np.flip(out_uf, axis=-1)).max()
    asym_v = np.abs(out_vf - np.flip(out_vf, axis=-1)).max()
    assert asym_u < 1e-9, f"u correction not z-even: {asym_u:.3e}"
    assert asym_v < 1e-9, f"v correction not z-even: {asym_v:.3e}"


def test_solenoidal_input_returned_unchanged():
    """#2 — a (near-)solenoidal field is returned bit-exact (solve skipped).

    Forward-dir fluids enter already divergence-free; the projection must not
    perturb them. A field whose relative divergence sits below the skip
    threshold must come back identical (no spurious O(roundoff) correction).
    """
    Nx, Ny, Nz = 12, 10, 8
    eps_f, rcp, dx, dy, dz = _uniform_props(Nx, Ny, Nz)
    # Uniform axial flow is exactly solenoidal; add a tiny perturbation so the
    # field carries a nonzero-but-negligible divergence (current code would
    # still apply an O(1e-11) correction; the skip must return it unchanged).
    uf = np.full((Nx + 1, Ny, Nz), 3.0)
    rng = np.random.default_rng(2)
    uf = uf + 1e-11 * rng.standard_normal(uf.shape)
    vf = np.zeros((Nx, Ny + 1, Nz))
    wf = np.zeros((Nx, Ny, Nz + 1))

    D = _cell_div(uf, vf, wf, eps_f, rcp, dx, dy, dz)
    coef = eps_f * rcp
    Ax = (dy[None, :, None] * dz[None, None, :])
    flux_scale = float(np.abs(coef[:1] * uf[:1] * Ax).max())
    assert np.abs(D).max() <= 1e-9 * flux_scale, "test field not in skip regime"

    uf_in, vf_in, wf_in = uf.copy(), vf.copy(), wf.copy()
    out_uf, out_vf, out_wf = _project_faces_div_free(
        uf, vf, wf, eps_f, rcp, dx, dy, dz)

    assert np.array_equal(out_uf, uf_in), "solenoidal uf was perturbed"
    assert np.array_equal(out_vf, vf_in), "solenoidal vf was perturbed"
    assert np.array_equal(out_wf, wf_in), "solenoidal wf was perturbed"
