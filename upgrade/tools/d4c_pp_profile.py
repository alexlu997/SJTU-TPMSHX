# -*- coding: utf-8 -*-
"""D4(c) profile: (1) wall_refine anomaly dissection, (2) 32k AMG pp share."""
import os, sys, time, cProfile, pstats, io as _io
os.chdir(r'E:\LWH\SJTU-TPMSHX-upgrade'); sys.path.insert(0, r'E:\LWH\SJTU-TPMSHX-upgrade')
sys.path.insert(0, os.path.join(r'E:\LWH\SJTU-TPMSHX-upgrade','sjtu_tpmshx','tests'))
import sjtu_tpmshx.solvers.simple_solver_3d as ss3d
from sjtu_tpmshx.pipelines.stages_3d import _run_3d_stack
from test_wall_refine_3d import _full_face_cfg
from test_partial_bc_ghost_b import _partial_bc_air_air_cfg

# --- shared pp timing shim (wrap module-level pp solvers) -------------------
pp_stats = {'amg_t': 0.0, 'amg_n': 0}
_orig_amg = ss3d._solve_pp_amg
def _timed_amg(*a, **k):
    t0 = time.perf_counter(); r = _orig_amg(*a, **k)
    pp_stats['amg_t'] += time.perf_counter() - t0; pp_stats['amg_n'] += 1
    return r
ss3d._solve_pp_amg = _timed_amg

def run_case(tag, cfg):
    pp_stats.update(amg_t=0.0, amg_n=0)
    t0 = time.perf_counter()
    res = _run_3d_stack(cfg)
    wall = time.perf_counter() - t0
    print(f"[{tag}] wall={wall:.1f}s pp_amg={pp_stats['amg_t']:.1f}s "
          f"({100*pp_stats['amg_t']/wall:.1f}%) amg_calls={pp_stats['amg_n']} "
          f"converged={res.get('converged')}")
    return wall, res

# (1) wall_refine anomaly: iterations vs per-iter cost
print("=== part 1: wall_refine refined case ===")
w_ref, r_ref = run_case("refined", _full_face_cfg())
print("=== part 1b: uniform control ===")
w_uni, r_uni = run_case("uniform", _full_face_cfg(wall_refine_3d=False))

# cProfile a SHORT refined re-run? too heavy; instead re-run refined capturing
# top python-level hotspots only if it was NOT pp-dominated:
if pp_stats['amg_t'] / max(w_ref, 1e-9) < 0.5:
    print("=== part 1c: cProfile refined (top 15 cumulative) ===")
    pr = cProfile.Profile(); pr.enable()
    _run_3d_stack(_full_face_cfg())
    pr.disable()
    sbuf = _io.StringIO()
    pstats.Stats(pr, stream=sbuf).sort_stats('cumulative').print_stats(15)
    print('\n'.join(sbuf.getvalue().splitlines()[:30]))

# (2) 32k AMG production-shaped case pp share
print("=== part 2: 40x40x20 = 32k AMG case ===")
cfg32 = _partial_bc_air_air_cfg(Nx=40, Ny=40, Nz=20)
run_case("32k", cfg32)
