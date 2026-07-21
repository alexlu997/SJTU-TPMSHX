"""Order-of-accuracy test for the boundary pressure-drop functional.

`SIMPLESolver3D.extract_dP_weighted` differences the first/last CELL-CENTRE
pressures, which sit ~h/2 from the physical inlet/outlet faces — an O(h) offset
that caps the dP functional at ~1st order even on a 2nd-order field.
`extract_dP_face_extrap` extrapolates P to the faces (1.5·P0 − 0.5·P1), removing
that term → ~2nd order.

This is a *functional* order test: feed an analytic, smooth pressure field
sampled at cell centres on refining grids, and measure how fast each extractor's
dP converges to the exact face-to-face Δp. No solver run — isolates the
discretisation order of the reduction itself.
"""
import numpy as np
from types import SimpleNamespace

from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D

LY = 0.042  # streamwise length (m), Shanghai-ish


def _Pfield(y):
    # smooth, with NONZERO, ASYMMETRIC gradient at both end faces so the
    # cell-centre half-cell offset is a genuine O(h) term (no symmetry
    # cancellation). A pressure-drop profile decays ~exponentially streamwise.
    return 1000.0 * np.exp(-3.0 * y / LY)


def _exact_dP():
    return float(_Pfield(0.0) - _Pfield(LY))


def _make_state(Ny):
    # streamwise = axis 1; Nx = Nz = 1. cell centres at (j+0.5)*h.
    h = LY / Ny
    yc = (np.arange(Ny) + 0.5) * h
    P = _Pfield(yc)[None, :, None]          # (1, Ny, 1)
    ones = np.ones((1, 1), dtype=np.float64)
    return SimpleNamespace(P=P, inlet_frac=ones, outlet_frac=ones)


def _orders():
    Nys = [8, 16, 32, 64, 128]
    exact = _exact_dP()
    e_cell, e_face = [], []
    for Ny in Nys:
        s = _make_state(Ny)
        e_cell.append(abs(SIMPLESolver3D.extract_dP_weighted(s) - exact))
        e_face.append(abs(SIMPLESolver3D.extract_dP_face_extrap(s) - exact))
    h = 1.0 / np.array(Nys, dtype=float)
    p_cell = np.polyfit(np.log(h), np.log(e_cell), 1)[0]
    p_face = np.polyfit(np.log(h), np.log(e_face), 1)[0]
    return p_cell, p_face, e_cell, e_face


def test_cell_centre_dp_is_first_order():
    p_cell, _, _, _ = _orders()
    assert 0.7 < p_cell < 1.4, f"cell-centre dP order {p_cell:.2f} (expected ~1)"


def test_face_extrap_dp_is_second_order():
    _, p_face, _, e_face = _orders()
    assert p_face > 1.8, f"face-extrapolated dP order {p_face:.2f} (expected ~2)"


def test_face_is_more_accurate_than_cell():
    _, _, e_cell, e_face = _orders()
    # on the finest grid the 2nd-order extractor must be strictly closer
    assert e_face[-1] < e_cell[-1]


if __name__ == "__main__":
    pc, pf, ec, ef = _orders()
    print(f"cell-centre dP order = {pc:.3f}")
    print(f"face-extrap  dP order = {pf:.3f}")
    print(f"finest-grid err: cell={ec[-1]:.4g}  face={ef[-1]:.4g}  ratio={ec[-1]/ef[-1]:.1f}x")
