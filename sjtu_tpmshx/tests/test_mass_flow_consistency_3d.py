"""3D solver mass-flow consistency tests — pins Category B (mixed-basis PPE) bug.

Pre-fix: both tests are EXPECTED to FAIL with a ~2x discrepancy when eps=0.5.
Post-fix: both tests should PASS.

Bug source (per 2026-05-14 audit, vault/reports/3d-solver/
2026-05-14-flow-topology/audit_notes.md):
    simple_solver(_3d).py PPE assembly mixes interstitial matrix
    (rho * eps coefficients) with superficial RHS (rho * u divergence).
    With eps=0.5 the pressure correction is ~2x scaled, propagating an
    inconsistent mass-flow factor through the solution.

Streamwise convention for SIMPLESolver3D:
    - inlet face = j=0 plane:  v[:, 0, :]
    - outlet face = j=Ny plane: v[:, Ny, :]
    - inlet face area = Lx * Lz, dy spacing irrelevant for inflow integral
    - face integral: sum_{i,k} rho_face * v_face * (dx_i * dz_k)
"""
import sys
import warnings
from pathlib import Path

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

warnings.filterwarnings('ignore')

import numpy as np
import pytest

from solvers.simple_solver_3d import SIMPLESolver3D


def _build_uniform_box(Nx=8, Ny=8, Nz=8,
                       Lx=0.02, Ly=0.02, Lz=0.02,
                       eps=0.5, rho=1.225, mu=1.8e-5,
                       K=1e-8, cF=0.55,
                       U_super=0.5):
    """Build a uniform porous box: ε=0.5 D-F closure, scalar v_inlet=U_super.

    Use incompressible fluid (constant rho) so the steady mass-flow check
    decouples cleanly from the compressible BC density update.
    """
    K_arr = np.full((Ny, Nz), K, dtype=np.float64)
    cF_arr = np.full((Ny, Nz), cF, dtype=np.float64)
    sol = SIMPLESolver3D(
        Lx=Lx, Ly=Ly, Lz=Lz,
        Nx=Nx, Ny=Ny, Nz=Nz,
        rho=rho, mu=mu, T_in=300.0,
        v_inlet=U_super,
        eps=eps,
        K_arr=K_arr, cF_arr=cF_arr,
        P_ref_abs=101325.0,
        fluid_type='incompressible',
    )
    return sol


def test_uniform_box_mass_conservation():
    """Uniform porous box, eps=0.5: inlet mass-flow == outlet mass-flow at steady.

    Independent of which convention the solver uses internally — must hold
    for any consistent steady-state SIMPLE result. If the PPE mixes bases,
    the pressure correction is asymmetric and inlet/outlet integrals diverge.
    """
    sol = _build_uniform_box()
    conv, it = sol.solve(max_iter=500, tol=1e-6)
    print(f"[conservation] converged={conv} iters={it}")

    dx = sol.dx[:, None]   # (Nx, 1)
    dz = sol.dz[None, :]   # (1, Nz)

    m_in = float(np.sum(sol.v[:, 0, :]
                        * sol.rho_field[:, 0, :]
                        * dx * dz))
    m_out = float(np.sum(sol.v[:, -1, :]
                         * sol.rho_field[:, -1, :]
                         * dx * dz))
    ratio = m_out / m_in if abs(m_in) > 1e-30 else float('inf')
    print(f"[conservation] m_in={m_in:.6g} m_out={m_out:.6g} "
          f"ratio_out/in={ratio:.4f}")

    assert m_in == pytest.approx(m_out, rel=5e-3), (
        f"Mass conservation broken: in={m_in:.6g} out={m_out:.6g} "
        f"ratio={ratio:.3f}"
    )


def test_uniform_box_bc_matches_inlet_integral():
    """BC injects v_inlet at j=0. Inlet face integral rho*v*dA should equal rho*U*A_face.

    Pre-fix expectation: if PPE bug propagates back to v[:, 0, :] during
    pressure correction, the inlet face integral departs from rho*U_super*A_face
    by an eps factor (~2x with eps=0.5).
    Post-fix expectation: BC preserves v_inlet at face → integral matches target.
    """
    Lx, Ly, Lz = 0.02, 0.02, 0.02
    eps = 0.5
    rho = 1.225
    U_super = 0.5

    sol = _build_uniform_box(
        Nx=8, Ny=8, Nz=8,
        Lx=Lx, Ly=Ly, Lz=Lz,
        eps=eps, rho=rho, U_super=U_super,
    )
    conv, it = sol.solve(max_iter=500, tol=1e-6)
    print(f"[bc-integral] converged={conv} iters={it}")

    A_face = Lx * Lz
    m_target = rho * U_super * A_face   # superficial reference
    dx = sol.dx[:, None]
    dz = sol.dz[None, :]
    m_in = float(np.sum(sol.v[:, 0, :]
                        * sol.rho_field[:, 0, :]
                        * dx * dz))
    ratio = m_in / m_target if abs(m_target) > 1e-30 else float('inf')
    print(f"[bc-integral] m_target={m_target:.6g} "
          f"m_in_face_integral={m_in:.6g} ratio={ratio:.4f}")

    assert m_in == pytest.approx(m_target, rel=2e-3), (
        f"BC-vs-integral mismatch: target={m_target:.6g} "
        f"face_integral={m_in:.6g} ratio={ratio:.3f}"
    )


if __name__ == '__main__':
    test_uniform_box_mass_conservation()
    test_uniform_box_bc_matches_inlet_integral()
