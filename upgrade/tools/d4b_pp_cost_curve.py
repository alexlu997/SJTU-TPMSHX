# -*- coding: utf-8 -*-
"""D4(b)-1: pp per-solve cost curve, LU (status quo) vs forced-AMG, 2k-30k cells.

Method: same full-face air-air case at 5 grid sizes; 60 SIMPLE iterations each
(timing study - convergence irrelevant); pp wall via _solve_pp_amg wrapper;
AMG regime = _AMG_GATE monkeypatched to 0 (gate read at call time).
Run: .venv/Scripts/python.exe -u upgrade/tools/d4b_pp_cost_curve.py
"""
import os, sys, time
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(_REPO); sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, 'sjtu_tpmshx', 'tests'))
import sjtu_tpmshx.solvers.simple_solver_3d as ss3d
from sjtu_tpmshx.pipelines.run_stack_3d_stages import _build_3d_problem
from test_wall_refine_3d import _full_face_cfg

pp = {'t': 0.0, 'n': 0}
_orig = ss3d._solve_pp_amg
def _timed(*a, **k):
    t0 = time.perf_counter(); r = _orig(*a, **k)
    pp['t'] += time.perf_counter() - t0; pp['n'] += 1
    return r
ss3d._solve_pp_amg = _timed

GRIDS = [(14,12,12), (17,17,17), (24,22,22), (27,27,27), (31,31,31)]
ITERS = 60

for nx, ny, nz in GRIDS:
    n_cells = nx*ny*nz
    for regime, gate in (('LU', 10**9), ('AMG', 0)):
        old_gate = ss3d._AMG_GATE
        ss3d._AMG_GATE = gate
        try:
            cfg = _full_face_cfg(Nx=nx, Ny=ny, Nz=nz, wall_refine_3d=False)
            prob = _build_3d_problem(cfg)
            sA = prob.sA
            pp.update(t=0.0, n=0)
            t0 = time.perf_counter()
            sA.solve(max_iter=ITERS, tol=1e-30)
            wall = time.perf_counter() - t0
            mc = getattr(sA, '_ml_cache', {}) or {}
            extra = ''
            if regime == 'AMG':
                extra = (f" rebuilds={mc.get('rebuild_count',0)}"
                         f" rebuild_t={mc.get('rebuild_time',0.0):.2f}s"
                         f" bcg_t={mc.get('bcg_time',0.0):.2f}s"
                         f" bcg_fail={mc.get('bcg_fail_count',0)}")
            per = pp['t']/max(pp['n'],1)*1000
            print(f"{n_cells:>6} cells {regime:>3}: pp={pp['t']:7.2f}s/"
                  f"{pp['n']:3d} calls = {per:8.2f} ms/call  wall={wall:7.2f}s{extra}",
                  flush=True)
        finally:
            ss3d._AMG_GATE = old_gate
