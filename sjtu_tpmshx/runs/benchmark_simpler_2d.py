"""Benchmark: SIMPLE vs SIMPLER coupling, 2D production solver.

openspec change `simpler-coupling-2d`, tasks 1.2 (profile) + 4.1 (benchmark).

Shanghai-style standalone config (air ideal-gas, mass-flux inlet, Gyroid DF,
full-width inlet/outlet, wall_refine=False), two grids. Per (grid, coupling):
outer iterations to tol, post-JIT-warmup wall time, ΔP, and field agreement
(SIMPLER vs SIMPLE reference). Also cProfile stage breakdown for the SIMPLE
run (design D4 gate: splu reuse only worth it if PP solve > 40 % of wall).

    python -u sjtu_tpmshx/runs/benchmark_simpler_2d.py
"""
import cProfile
import io
import os
import pstats
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import numpy as np
from solvers.simple_solver import SIMPLESolver

R_GAS = 287.05
T_IN = 422.0
P_OUT_ABS = 192362.0            # outlet (gauge-0) absolute datum, Shanghai-like
RHO_IN = P_OUT_ABS / (R_GAS * T_IN)
V_INLET = 15.0                  # interstitial, m/s
TOL = 1e-6
MAX_ITER = 5000

GRIDS = [(40, 80), (80, 160)]


def make_solver(Nx, Ny):
    return SIMPLESolver(
        W=0.042, H=0.182, Nx=Nx, Ny=Ny,
        tpms_type='Gyroid', L_cell_mm=7.0, t_mm=0.6, eps=0.6, r_h=1e-3,
        rho=RHO_IN, mu=2.35e-5, T_in=T_IN,
        inlet_lo=0.0, inlet_hi=0.042, v_inlet=V_INLET,
        P_ref_abs=P_OUT_ABS, rho_inlet_ref=RHO_IN,
        wall_refine=False,
    )


def run_case(Nx, Ny, coupling):
    s = make_solver(Nx, Ny)
    t0 = time.perf_counter()
    conv, iters = s.solve(max_iter=MAX_ITER, tol=TOL, coupling=coupling,
                          verbose=False)
    wall = time.perf_counter() - t0
    dP = float(s.P[:, 0].mean() - s.P[:, -1].mean())
    return s, conv, iters, wall, dP


def profile_simple(Nx, Ny):
    """cProfile stage breakdown of one SIMPLE run (task 1.2 / design D4)."""
    s = make_solver(Nx, Ny)
    prof = cProfile.Profile()
    prof.enable()
    s.solve(max_iter=MAX_ITER, tol=TOL, verbose=False)
    prof.disable()
    buf = io.StringIO()
    st = pstats.Stats(prof, stream=buf)
    total = st.total_tt
    stage_t = {}
    for (fn_file, _line, fn_name), (_cc, _nc, _tt, ct, _callers) in st.stats.items():
        for key in ('_sweep_u_jit_df', '_sweep_v_jit_df',
                    '_solve_pp_sparse_fast', 'spsolve',
                    '_assemble_pp_data_jit', '_correct_jit',
                    '_update_density', '_mass_res_jit'):
            if fn_name == key:
                stage_t[key] = stage_t.get(key, 0.0) + ct
    print(f"\n  [profile SIMPLE {Nx}x{Ny}] total {total:.2f}s")
    for k, v in sorted(stage_t.items(), key=lambda kv: -kv[1]):
        print(f"    {k:26s} {v:8.2f}s  ({100.0 * v / total:5.1f} %)")
    pp = stage_t.get('_solve_pp_sparse_fast', 0.0)
    print(f"    -> PP-solve share {100.0 * pp / total:.1f} %"
          f"  (design D4 splu gate: > 40 %)")
    return 100.0 * pp / total


def main():
    print("JIT warmup (tiny grid, both couplings)...")
    for cpl in ('simple', 'simpler'):
        s = make_solver(12, 24)
        s.solve(max_iter=30, tol=1e-6, coupling=cpl, verbose=False)

    rows = []
    all_pass = True
    for (Nx, Ny) in GRIDS:
        sA, convA, itA, wallA, dPA = run_case(Nx, Ny, 'simple')
        sB, convB, itB, wallB, dPB = run_case(Nx, Ny, 'simpler')

        rel_dP = abs(dPB - dPA) / abs(dPA)
        # u is the near-zero cross-stream secondary velocity: normalise by the
        # primary-flow scale ||v|| (spec / test convention)
        du = float(np.linalg.norm(sB.u - sA.u) / np.linalg.norm(sA.v))
        dv = float(np.linalg.norm(sB.v - sA.v) / np.linalg.norm(sA.v))
        dp_l2 = float(np.linalg.norm(sB.P - sA.P) / np.linalg.norm(sA.P))
        ok_dP = rel_dP <= 0.01
        ok_flds = (du <= 1e-2) and (dv <= 1e-2) and (dp_l2 <= 1e-2)
        all_pass &= convA and convB and ok_dP and ok_flds

        rows.append(dict(Nx=Nx, Ny=Ny,
                         it_simple=itA, it_simpler=itB,
                         wall_simple=wallA, wall_simpler=wallB,
                         speedup=wallA / wallB,
                         dP_simple=dPA, dP_simpler=dPB,
                         rel_dP=rel_dP, u_l2=du, v_l2=dv, P_l2=dp_l2,
                         conv=(convA and convB)))

        print(f"\n== grid {Nx}x{Ny} ==")
        print(f"  SIMPLE : conv={convA} iters={itA:5d} wall={wallA:7.2f}s"
              f" dP={dPA:10.1f} Pa")
        print(f"  SIMPLER: conv={convB} iters={itB:5d} wall={wallB:7.2f}s"
              f" dP={dPB:10.1f} Pa")
        print(f"  speedup(wall) = {wallA / wallB:5.2f}x"
              f"   iter ratio = {itA / max(itB, 1):5.2f}x")
        print(f"  agreement: rel dP={rel_dP:.2e} ({'PASS' if ok_dP else 'FAIL'})"
              f"  u_L2={du:.2e} v_L2={dv:.2e} P_L2={dp_l2:.2e}"
              f" ({'PASS' if ok_flds else 'FAIL'})")

    pp_share = profile_simple(*GRIDS[0])

    out_dir = os.path.join(os.path.dirname(_ROOT), 'reports',
                           'simpler-coupling-2d')
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, 'benchmark_simple_vs_simpler_2d.csv')
    keys = list(rows[0].keys())
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write(','.join(keys) + '\n')
        for r in rows:
            f.write(','.join(str(r[k]) for k in keys) + '\n')
    print(f"\n[csv] {csv_path}")

    fine = rows[-1]
    print("\n== decision gate (spec: fine grid, wall speedup >= 1.3x"
          " AND fields agree) ==")
    verdict = ('CANDIDATE-FOR-3D' if (fine['speedup'] >= 1.3 and all_pass)
               else 'NEGATIVE-RESULT (keep coupling=simpler experimental)')
    print(f"  fine-grid speedup {fine['speedup']:.2f}x, agreement "
          f"{'PASS' if all_pass else 'FAIL'}, PP share {pp_share:.1f} % "
          f"-> {verdict}")


if __name__ == '__main__':
    main()
