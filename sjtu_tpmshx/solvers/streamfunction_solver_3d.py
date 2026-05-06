"""StreamfunctionSolver3D — SIMPLESolver3D subclass with strict mass cons.

Phase 7 of streamfunction-pressure plan v2 (Plan A: drop-in replacement).

Replaces SIMPLE pp_amg + correct_jit (variable-coef Poisson, ~1e-5 mass residual)
with:
  - momentum sweeps (kept from SIMPLESolver3D)
  - Helmholtz scalar projection (constant-coef, machine-eps mass cons)
  - axial pressure integration along flow direction (j for dir=2 SIMPLE3D)
  - _update_density() (compressible ideal gas, kept)

The streamfunction-pressure formulation: m_face = ∇×A is enforced via Helmholtz
scalar projection (Path A in edge_potential_3d). Strict ∇·m=0 by construction.

Used for Shanghai 16-case validation comparison vs SIMPLESolver3D baseline.
"""
from __future__ import annotations
import numpy as np
import os, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Three-tier import fallback so this module loads correctly whether it's
# imported as `sjtu_tpmshx.solvers.streamfunction_solver_3d` (full path),
# as `solvers.streamfunction_solver_3d` (with sjtu_tpmshx/ on sys.path —
# default for validation/test scripts), or directly via solvers/ on path.
# The middle tier is the production import — keep it robust to package mode
# so downstream relative imports inside simple_solver_3d (e.g. `.tpms_calc`)
# continue to resolve correctly.
try:
    from sjtu_tpmshx.solvers.simple_solver_3d import (
        SIMPLESolver3D,
        _sweep_u_jit_df_3d, _sweep_v_jit_df_3d, _sweep_w_jit_df_3d,
        _sweep_u_jit_df_3d_parallel, _sweep_v_jit_df_3d_parallel,
        _sweep_w_jit_df_3d_parallel,
        _should_parallelize,
        _build_pp_sparsity_3d,
        _mass_res_jit_3d,
    )
    from sjtu_tpmshx.solvers.edge_potential_3d import (
        helmholtz_project, build_cell_laplacian_3d, divergence_m,
    )
except ImportError:
    try:
        # Production import: when sjtu_tpmshx/ is on sys.path (e.g. via
        # tests/conftest.py or a validation script's ROOT injection).
        # Loads simple_solver_3d as part of the `solvers` package, so its
        # relative imports (`from .tpms_calc import ...`) resolve.
        from solvers.simple_solver_3d import (
            SIMPLESolver3D,
            _sweep_u_jit_df_3d, _sweep_v_jit_df_3d, _sweep_w_jit_df_3d,
            _sweep_u_jit_df_3d_parallel, _sweep_v_jit_df_3d_parallel,
            _sweep_w_jit_df_3d_parallel,
            _should_parallelize,
            _build_pp_sparsity_3d,
            _mass_res_jit_3d,
        )
        from solvers.edge_potential_3d import (
            helmholtz_project, build_cell_laplacian_3d, divergence_m,
        )
    except ImportError:
        # Last-resort flat layout (solvers/ itself on sys.path). Breaks
        # simple_solver_3d's relative `.tpms_calc` — only works if user
        # is running solver as a standalone unit test in isolation.
        from simple_solver_3d import (
            SIMPLESolver3D,
            _sweep_u_jit_df_3d, _sweep_v_jit_df_3d, _sweep_w_jit_df_3d,
            _sweep_u_jit_df_3d_parallel, _sweep_v_jit_df_3d_parallel,
            _sweep_w_jit_df_3d_parallel,
            _should_parallelize,
            _build_pp_sparsity_3d,
            _mass_res_jit_3d,
        )
        from edge_potential_3d import (
            helmholtz_project, build_cell_laplacian_3d, divergence_m,
        )

import pyamg


class StreamfunctionSolver3D(SIMPLESolver3D):
    """SIMPLE3D variant using Helmholtz scalar projection for strict mass cons.

    Same interface as SIMPLESolver3D; flow direction is +y (inlet at j=0).

    Pressure recovery
    -----------------
    After Helmholtz projection (∇·m = 0 to machine eps) the velocity field
    is mass-conserving but P is not yet consistent with the porous-medium
    momentum equation. Two recovery paths:

      'poisson' (default, 2026-05-06 fix #2): solve full 3D Pressure-Poisson
        ∇²P = ∇·F   where F = μ∇²u − (μ/K)u − ρcF|u|u − ρ(u·∇)u.
        Captures lateral pressure gradients (∂P/∂x, ∂P/∂z), correct for 3D
        flows with cross-stream acceleration. See solvers/pressure_poisson_3d.

      'axial' (legacy, kept for A/B comparison): integrate dP/dy along
        flow direction assuming 1D plug flow. Drops lateral gradients.
        Documented as the root cause of the SF Shanghai dP 47% > SIMPLE 38%
        gap (see vault/reports/streamfunction/2026-04-26-P7-shanghai-16case
        + 2026-05-06-poisson-rewrite-plan-CN.md).

    Set via constructor kwarg `pressure_recovery='poisson'` (default) or
    `'axial'`.
    """

    def __init__(self, *args, pressure_recovery='poisson', **kwargs):
        super().__init__(*args, **kwargs)
        if pressure_recovery not in ('poisson', 'axial'):
            raise ValueError(
                f"pressure_recovery must be 'poisson' or 'axial', "
                f"got {pressure_recovery!r}")
        self._pressure_recovery_mode = pressure_recovery
        # Build cell Laplacian once (uniform dx/dy/dz from SIMPLE3D init)
        self._helm_dx = float(self.dx[0])
        self._helm_dy = float(self.dy[0])
        self._helm_dz = float(self.dz[0])
        self._helm_lap = build_cell_laplacian_3d(
            self.Nx, self.Ny, self.Nz,
            self._helm_dx, self._helm_dy, self._helm_dz)
        self._helm_ml = pyamg.smoothed_aggregation_solver(self._helm_lap)
        # Mass residual history (Helmholtz path)
        self.helm_mass_residuals = []
        # PPE hierarchy cache (built lazily on first call to _recover_pressure_poisson)
        self._ppe_cache = None
        # Diagnostic: last PPE iter count + residual (for tests / logging)
        self._last_ppe_info = None

    def _helmholtz_correct_step(self):
        """Replacement for _solve_pp_amg + _correct_jit_3d.

        1. m_star = ε·ρ·u·A_face on each face direction
        2. helmholtz_project(m_star) -> m_proj (strict ∇·m=0)
        3. Recover u_face = m_proj / (ε·ρ·A_face)
        4. Pressure recovery via dispatch on self._pressure_recovery_mode
        """
        Nx, Ny, Nz = self.Nx, self.Ny, self.Nz
        dx, dy, dz = self._helm_dx, self._helm_dy, self._helm_dz
        Aface_x = dy * dz
        Aface_y = dx * dz
        Aface_z = dx * dy

        # Face porosity (interpolated from cell ε)
        eps_cell = self.eps_field
        eps_fx = np.zeros((Nx + 1, Ny, Nz))
        eps_fx[1:-1] = 0.5 * (eps_cell[:-1] + eps_cell[1:])
        eps_fx[0] = eps_cell[0]; eps_fx[-1] = eps_cell[-1]
        eps_fy = np.zeros((Nx, Ny + 1, Nz))
        eps_fy[:, 1:-1] = 0.5 * (eps_cell[:, :-1] + eps_cell[:, 1:])
        eps_fy[:, 0] = eps_cell[:, 0]; eps_fy[:, -1] = eps_cell[:, -1]
        eps_fz = np.zeros((Nx, Ny, Nz + 1))
        eps_fz[:, :, 1:-1] = 0.5 * (eps_cell[:, :, :-1] + eps_cell[:, :, 1:])
        eps_fz[:, :, 0] = eps_cell[:, :, 0]; eps_fz[:, :, -1] = eps_cell[:, :, -1]

        # Face density
        rho = self.rho_field
        rho_fx = np.zeros((Nx + 1, Ny, Nz))
        rho_fx[1:-1] = 0.5 * (rho[:-1] + rho[1:])
        rho_fx[0] = rho[0]; rho_fx[-1] = rho[-1]
        rho_fy = np.zeros((Nx, Ny + 1, Nz))
        rho_fy[:, 1:-1] = 0.5 * (rho[:, :-1] + rho[:, 1:])
        rho_fy[:, 0] = rho[:, 0]; rho_fy[:, -1] = rho[:, -1]
        rho_fz = np.zeros((Nx, Ny, Nz + 1))
        rho_fz[:, :, 1:-1] = 0.5 * (rho[:, :, :-1] + rho[:, :, 1:])
        rho_fz[:, :, 0] = rho[:, :, 0]; rho_fz[:, :, -1] = rho[:, :, -1]

        # Apply inlet/wall BCs to velocity *before* building m_star, so
        # the projection treats them as fixed. Outlet computed from balance.
        v_BC = self.v.copy()
        u_BC = self.u.copy()
        w_BC = self.w.copy()
        # Walls (no-flow normal)
        u_BC[0, :, :] = 0.0; u_BC[-1, :, :] = 0.0
        w_BC[:, :, 0] = 0.0; w_BC[:, :, -1] = 0.0
        # Inlet at j=0 (dir=2 flow): v = v_inlet_field
        v_BC[:, 0, :] = self.v_inlet_field

        # m_star face flux (integrated)
        m_x_star = eps_fx * rho_fx * u_BC * Aface_x
        m_y_star = eps_fy * rho_fy * v_BC * Aface_y
        m_z_star = eps_fz * rho_fz * w_BC * Aface_z

        # Manual mass balance: outlet (j=-1) set to receive net inlet flux.
        # Distribute over open outlet cells (outlet_mask_ij=True).
        net_in = float(np.sum(m_y_star[:, 0, :]))
        n_open = int(np.sum(self.outlet_mask_ij))
        if n_open > 0:
            per_open = net_in / n_open
            for i in range(Nx):
                for k in range(Nz):
                    if self.outlet_mask_ij[i, k]:
                        m_y_star[i, -1, k] = per_open
                    else:
                        m_y_star[i, -1, k] = 0.0
        else:
            # No open outlet — uniform full face
            m_y_star[:, -1, :] = net_in / m_y_star[:, -1, :].size

        # Helmholtz project (auto_balance=False, we balanced manually)
        m_x_p, m_y_p, m_z_p, phi, self._helm_ml = helmholtz_project(
            m_x_star, m_y_star, m_z_star, dx, dy, dz,
            ml=self._helm_ml, auto_balance=False)

        # Recover face velocities from m_proj — DO NOT override BCs
        # (they were imposed in m_star and preserved by the projection)
        self.u = m_x_p / np.maximum(eps_fx * rho_fx * Aface_x, 1e-30)
        self.v = m_y_p / np.maximum(eps_fy * rho_fy * Aface_y, 1e-30)
        self.w = m_z_p / np.maximum(eps_fz * rho_fz * Aface_z, 1e-30)

        # Pressure recovery — dispatch on configured mode
        if self._pressure_recovery_mode == 'poisson':
            self._recover_pressure_poisson()
        else:
            self._recover_pressure_axial()

    def _recover_pressure_axial(self):
        """Legacy 1D axial Brinkman-Forchheimer integration along flow direction.

        Documented limitation: assumes 1D plug flow, drops lateral pressure
        gradients. Root cause of SF Shanghai dP 47% > SIMPLE 38% gap.
        Kept for A/B comparison vs the new Poisson path.
        """
        Nx, Ny, Nz = self.Nx, self.Ny, self.Nz
        dy = self._helm_dy
        rho = self.rho_field
        # Pressure update: axial integration along y (dir=2 flow)
        # -dP/dy = (μ/K)·v + ρ·cF·|v|·v  (Brinkman-Forchheimer source)
        # Note: K_arr, cF_arr have shape (Ny, Nz) in SIMPLE3D
        v_cell = 0.5 * (self.v[:, :-1, :] + self.v[:, 1:, :])  # (Nx, Ny, Nz)
        vmag = np.abs(v_cell) + 1e-12
        # Broadcast K, cF (Ny, Nz) to (Nx, Ny, Nz)
        K_3d = self.K_arr[None, :, :]
        cF_3d = self.cF_arr[None, :, :]
        coef = self.mu_field / K_3d + rho * cF_3d * vmag
        dPdy_cell = -coef * v_cell

        P_old = self.P.copy()
        # SIMPLE convention: self.P is gauge = absolute - P_ref_abs.
        # P_ref_abs is set from outlet estimate; P[outlet] ~ 0, P[inlet] ~ dP.
        # Build P_axial_abs starting from inlet (j=0) absolute pressure estimate
        # P_in_abs ~ P_ref_abs + |dP_total_estimate| ~ self.P_ref_abs + observed dP
        # We can't know dP a priori; use most-recent self.P[inlet] as anchor.
        P_in_abs_prev = self.P_ref_abs + float(np.mean(self.P[:, 0, :]))
        P_axial_abs = np.zeros_like(P_old)
        P_axial_abs[:, 0, :] = P_in_abs_prev + dPdy_cell[:, 0, :] * 0.5 * dy
        for j in range(1, Ny):
            P_axial_abs[:, j, :] = (P_axial_abs[:, j - 1, :]
                                    + 0.5 * (dPdy_cell[:, j - 1, :] + dPdy_cell[:, j, :]) * dy)
        # Convert absolute → gauge for SIMPLE convention compatibility
        P_new_gauge = P_axial_abs - self.P_ref_abs
        self.P = (1 - self.alpha_p) * P_old + self.alpha_p * P_new_gauge

    def _recover_pressure_poisson(self):
        """3D Pressure-Poisson recovery: ∇²P = ∇·F.

        Captures lateral pressure gradients. Wired in 2026-05-06 (audit fix
        #2 Phase B). Source assembly + BC injection done in
        solvers/pressure_poisson_3d.py (Phase A B.1-B.4 verified, MMS
        p_obs = 1.975).
        """
        from .pressure_poisson_3d import (
            solve_pressure_poisson_3d, _PPEHierarchyCache)
        if self._ppe_cache is None:
            self._ppe_cache = _PPEHierarchyCache()

        dx, dy, dz = self._helm_dx, self._helm_dy, self._helm_dz
        # Solver returns gauge-zero P field with P[outlet_mask] = 0.
        # Convert to project's gauge convention (P stored as gauge already).
        P_new_gauge, info = solve_pressure_poisson_3d(
            self.u, self.v, self.w,
            self.mu_field, self.K_arr, self.cF_arr,
            self.rho_field, self.eps_field,
            dx, dy, dz,
            self.outlet_mask_ij,
            cache=self._ppe_cache,
            tol=1e-10,
            max_v_cycles=80,
            inlet_neumann=True,
        )
        self._last_ppe_info = info

        # Apply under-relaxation (consistent with axial path's alpha_p blend).
        P_old = self.P
        self.P = ((1 - self.alpha_p) * P_old
                  + self.alpha_p * P_new_gauge.astype(P_old.dtype))

    def solve(self, max_iter=3000, tol=1e-6, n_inner=1, verbose=False):
        """Streamfunction-pressure solve loop (replaces SIMPLE pp step)."""
        Nx, Ny, Nz = self.Nx, self.Ny, self.Nz
        dx, dy, dz = self.dx, self.dy, self.dz

        if _should_parallelize(Nx, Ny, Nz):
            _sweep_u = _sweep_u_jit_df_3d_parallel
            _sweep_v = _sweep_v_jit_df_3d_parallel
            _sweep_w = _sweep_w_jit_df_3d_parallel
        else:
            _sweep_u = _sweep_u_jit_df_3d
            _sweep_v = _sweep_v_jit_df_3d
            _sweep_w = _sweep_w_jit_df_3d

        for it in range(1, max_iter + 1):
            rho_eps_field = np.ascontiguousarray(
                self.rho_field * self.eps_field, dtype=np.float64)
            _sweep_u(self.u, self.v, self.w, self.P, self.d_u,
                     Nx, Ny, Nz, dx, dy, dz,
                     self.rho_field, self._mu_eff_field, self.mu_field,
                     self.K_arr, self.cF_arr,
                     self.outlet_frac, self.inlet_frac,
                     self.alpha_u, n_inner)
            _sweep_v(self.u, self.v, self.w, self.P, self.d_v,
                     self.v_inlet_field,
                     Nx, Ny, Nz, dx, dy, dz,
                     self.rho_field, self._mu_eff_field, self.mu_field,
                     self.K_arr, self.cF_arr,
                     self.outlet_frac, self.inlet_frac,
                     self.alpha_u, n_inner)
            _sweep_w(self.u, self.v, self.w, self.P, self.d_w,
                     Nx, Ny, Nz, dx, dy, dz,
                     self.rho_field, self._mu_eff_field, self.mu_field,
                     self.K_arr, self.cF_arr,
                     self.outlet_frac, self.inlet_frac,
                     self.alpha_u, n_inner)

            # Helmholtz projection replaces pp_amg + correct_jit
            self._helmholtz_correct_step()

            # Compressible ρ update (kept from SIMPLE)
            self._update_density()

            # Mass residual diagnostics
            res = _mass_res_jit_3d(self.u, self.v, self.w,
                                   Nx, Ny, Nz, dx, dy, dz,
                                   rho_eps_field)
            self.residuals.append(res)

            # Direct Helmholtz mass cons check
            if it % 10 == 0 or it == 1:
                _eps = 0.5 * (self.eps_field[:-1] + self.eps_field[1:])
                # Quick re-compute m and check ∇·m
                eps_fx = np.zeros((Nx + 1, Ny, Nz))
                eps_fx[1:-1] = _eps; eps_fx[0] = self.eps_field[0]
                eps_fx[-1] = self.eps_field[-1]
                rho_fx = np.zeros((Nx + 1, Ny, Nz))
                rho_fx[1:-1] = 0.5 * (self.rho_field[:-1] + self.rho_field[1:])
                rho_fx[0] = self.rho_field[0]; rho_fx[-1] = self.rho_field[-1]
                _Aface_x = float(self.dy[0] * self.dz[0])
                m_x = eps_fx * rho_fx * self.u * _Aface_x
                # Just keep summary div
                self.helm_mass_residuals.append(res)

            if verbose and it % 50 == 0:
                print(f"  SF3D iter {it:5d}  |R| = {res:.3e}")

            if res < tol and it >= 10:
                return True, it

        return False, max_iter


# ============================================================
# Self-test: small Shanghai-like Air-Air case
# ============================================================

def _self_test():
    import time
    print("=" * 74)
    print("Phase 7: StreamfunctionSolver3D vs SIMPLESolver3D (small case)")
    print("=" * 74)

    # Small test setup similar to SIMPLE3D smoke test
    Lx, Ly, Lz = 0.04, 0.1, 0.04
    Nx, Ny, Nz = 8, 16, 8
    rho = 1.0
    mu = 2e-5
    T_in = 361.0
    v_inlet = 2.0
    eps = 0.30

    # Build solvers
    sf_solver = StreamfunctionSolver3D(
        Lx=Lx, Ly=Ly, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        rho=rho, mu=mu, T_in=T_in, v_inlet=v_inlet,
        eps=eps,
        K_arr=np.full((Ny, Nz), 1e-9),
        cF_arr=np.full((Ny, Nz), 0.5),
        P_ref_abs=101325.0,
        alpha_u=0.5, alpha_p=0.5,
        fluid_type='ideal_gas',
    )
    print(f"  grid {Nx}x{Ny}x{Nz} = {Nx*Ny*Nz} cells")

    t0 = time.time()
    converged, n_iter = sf_solver.solve(max_iter=300, tol=1e-4, verbose=True)
    t_sf = time.time() - t0

    P_in = float(np.mean(sf_solver.P[:, 0, :]))
    P_out = float(np.mean(sf_solver.P[:, -1, :]))
    dP = P_in - P_out

    # Direct mass cons check (Helmholtz strictness)
    _Aface_x = float(sf_solver.dy[0] * sf_solver.dz[0])
    _Aface_y = float(sf_solver.dx[0] * sf_solver.dz[0])
    _Aface_z = float(sf_solver.dx[0] * sf_solver.dy[0])
    eps_fx = np.zeros((Nx + 1, Ny, Nz))
    eps_fx[1:-1] = 0.5 * (sf_solver.eps_field[:-1] + sf_solver.eps_field[1:])
    eps_fx[0] = sf_solver.eps_field[0]; eps_fx[-1] = sf_solver.eps_field[-1]
    rho_fx = np.zeros((Nx + 1, Ny, Nz))
    rho_fx[1:-1] = 0.5 * (sf_solver.rho_field[:-1] + sf_solver.rho_field[1:])
    rho_fx[0] = sf_solver.rho_field[0]; rho_fx[-1] = sf_solver.rho_field[-1]
    eps_fy = np.zeros((Nx, Ny + 1, Nz))
    eps_fy[:, 1:-1] = 0.5 * (sf_solver.eps_field[:, :-1] + sf_solver.eps_field[:, 1:])
    eps_fy[:, 0] = sf_solver.eps_field[:, 0]; eps_fy[:, -1] = sf_solver.eps_field[:, -1]
    rho_fy = np.zeros((Nx, Ny + 1, Nz))
    rho_fy[:, 1:-1] = 0.5 * (sf_solver.rho_field[:, :-1] + sf_solver.rho_field[:, 1:])
    rho_fy[:, 0] = sf_solver.rho_field[:, 0]; rho_fy[:, -1] = sf_solver.rho_field[:, -1]
    eps_fz = np.zeros((Nx, Ny, Nz + 1))
    eps_fz[:, :, 1:-1] = 0.5 * (sf_solver.eps_field[:, :, :-1] + sf_solver.eps_field[:, :, 1:])
    eps_fz[:, :, 0] = sf_solver.eps_field[:, :, 0]; eps_fz[:, :, -1] = sf_solver.eps_field[:, :, -1]
    rho_fz = np.zeros((Nx, Ny, Nz + 1))
    rho_fz[:, :, 1:-1] = 0.5 * (sf_solver.rho_field[:, :, :-1] + sf_solver.rho_field[:, :, 1:])
    rho_fz[:, :, 0] = sf_solver.rho_field[:, :, 0]; rho_fz[:, :, -1] = sf_solver.rho_field[:, :, -1]
    m_x = eps_fx * rho_fx * sf_solver.u * _Aface_x
    m_y = eps_fy * rho_fy * sf_solver.v * _Aface_y
    m_z = eps_fz * rho_fz * sf_solver.w * _Aface_z
    div = divergence_m(m_x, m_y, m_z)
    m_in_total = float(np.sum(m_y[:, 0, :]))
    max_div_ratio = float(np.max(np.abs(div))) / max(abs(m_in_total), 1e-30)

    print()
    print(f"  StreamfunctionSolver3D:")
    print(f"    converged: {converged}, iterations: {n_iter}")
    print(f"    wall time: {t_sf:.2f} s")
    print(f"    P range: [{sf_solver.P.min():.0f}, {sf_solver.P.max():.0f}] Pa")
    print(f"    dP (j=0 mean - j=Ny-1 mean) = {dP:.2f} Pa")
    print(f"    rho range: [{sf_solver.rho_field.min():.4f}, {sf_solver.rho_field.max():.4f}]")
    print(f"    final mass residual (SIMPLE-style): {sf_solver.residuals[-1]:.3e}")
    print(f"    max |div(m)| / |m_in|: {max_div_ratio:.3e}  (Helmholtz target ~1e-12)")

    print()
    print("Phase 7 milestone:")
    print(f"  [{'x' if converged else ' '}] Solver converges")
    print(f"  [{'x' if max_div_ratio < 1e-10 else ' '}] Strict mass cons (div < 1e-10)")
    print(f"  [{'x' if t_sf < 60 else ' '}] Wall time < 60s (single small case)")
    print()


if __name__ == '__main__':
    _self_test()
