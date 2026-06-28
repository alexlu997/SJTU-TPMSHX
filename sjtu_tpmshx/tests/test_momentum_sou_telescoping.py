"""N2 (full-debug audit 2026-06-28): the momentum SOU deferred correction must
scale each face's limiter by THAT face's convective flux (Fw west, Fe east) so it
telescopes — the legacy form used one cell-flux for both faces, injecting a
spurious momentum source where ρ·u varied between neighbours (the defect already
fixed in ltne_energy._sou_corr_x/_y).

Flux-isolation: helper(Fe=1,Fw=0) returns -0.5·φ_e (east limiter only);
helper(Fe=0,Fw=1) returns +0.5·φ_w (west limiter only). Telescoping requires the
east limiter of cell i to equal the west limiter of cell i+1 at the shared face
(φ_e(i) == φ_w(i+1)), so the corrections cancel when the shared-face flux matches.
"""
import numpy as np
import pytest

from solvers.simple_solver import (
    _sou_corr_u_x, _sou_corr_u_y, _sou_corr_v_x, _sou_corr_v_y,
)


def _convex_line(n):
    """Monotone-increasing convex profile -> non-zero minmod limiters."""
    return np.array([1.0 + 0.1 * ii + 0.01 * ii * ii for ii in range(n)])


def test_sou_corr_u_x_telescopes_at_shared_x_face():
    Nx, Ny = 12, 1
    u = np.zeros((Nx + 1, Ny))
    u[:, 0] = _convex_line(Nx + 1)
    j, i = 0, 5
    east_i = _sou_corr_u_x(u, i, j, Nx, 1.0, 0.0)        # -0.5·φ_e(i)
    west_ip1 = _sou_corr_u_x(u, i + 1, j, Nx, 0.0, 1.0)  # +0.5·φ_w(i+1)
    assert abs(east_i) > 0.0                              # limiter active
    assert east_i == pytest.approx(-west_ip1)            # φ_e(i) == φ_w(i+1)


def test_sou_corr_v_y_telescopes_at_shared_y_face():
    Nx, Ny = 1, 12
    v = np.zeros((Nx, Ny + 1))
    v[0, :] = _convex_line(Ny + 1)
    i, j = 0, 5
    north_j = _sou_corr_v_y(v, i, j, Ny, 1.0, 0.0)        # -0.5·φ_n(j)
    south_jp1 = _sou_corr_v_y(v, i, j + 1, Ny, 0.0, 1.0)  # +0.5·φ_s(j+1)
    assert abs(north_j) > 0.0
    assert north_j == pytest.approx(-south_jp1)


def test_sou_corr_u_x_uniform_flux_reduces_to_legacy():
    """Fe==Fw==F -> 0.5·(F·φ_w − F·φ_e) = 0.5·F·(φ_w − φ_e): the legacy scalar
    form, so a uniform-flux region is unchanged (the golden re-baseline is driven
    only by the variable-flux cells)."""
    Nx, Ny = 12, 1
    u = np.zeros((Nx + 1, Ny))
    u[:, 0] = _convex_line(Nx + 1)
    j, i, F = 0, 5, 2.3
    full = _sou_corr_u_x(u, i, j, Nx, F, F)
    pe = _sou_corr_u_x(u, i, j, Nx, 1.0, 0.0)   # -0.5·φ_e
    pw = _sou_corr_u_x(u, i, j, Nx, 0.0, 1.0)   # +0.5·φ_w
    assert full == pytest.approx(F * (pw + pe))  # = 0.5·F·(φ_w − φ_e)


def test_sou_corr_v_x_and_u_y_accept_two_fluxes():
    """The cross-derivative helpers carry the same two-flux signature."""
    Nx, Ny = 12, 12
    a = np.zeros((Nx + 1, Ny + 1))
    a[:, :] = _convex_line(Nx + 1)[:, None] + _convex_line(Ny + 1)[None, :]
    # just exercise the signatures (telescoping covered by the streamwise pair)
    assert isinstance(float(_sou_corr_v_x(a, 5, 5, Nx, 1.0, 0.5)), float)
    assert isinstance(float(_sou_corr_u_y(a, 5, 5, Ny, 1.0, 0.5)), float)
