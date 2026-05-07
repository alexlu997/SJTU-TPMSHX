"""validate_shanghai_3d_pp_compare.py — Shanghai 16-case 3D triple comparison.

Phase C of 2026-05-06 streamfunction P-Poisson rewrite (audit fix #2).
See vault/reports/streamfunction/2026-05-06-poisson-rewrite-plan-CN.md §4 Phase C.

Runs each Shanghai case under THREE pressure-recovery paths back-to-back:

  1. SIMPLE 3D                          — production baseline (memory:
                                            Nz=10 dP 44.66% / Q 2.29%)
  2. StreamfunctionSolver3D + axial     — legacy P7 (memory: dP 47%, 8pp
                                            worse than SIMPLE)
  3. StreamfunctionSolver3D + poisson   — new (Phase B integrated, MMS
                                            p_obs=1.975 verified)

Outputs a CSV with one row per (case, path) and a summary table comparing
RMSRE_dP / RMSRE_Q / max mass_rel across paths. Phase D paper writeup
will cite these numbers.

V&V scope (plan §3.5)
---------------------
This script is VALIDATION. The PPE solver was already verified (MMS
B.4). Differences between paths reveal physics, not solver bugs. Three
outcome scenarios per plan §4 Phase C Day 3:

  - dP > 50%: investigate as bug (BC, source, AMG)
  - dP ∈ [38%, 50%]: acceptable, write up as method
  - dP < 38%: dig deeper — Poisson outperforms SIMPLE? Could be
    closure error correlation OR genuine improvement; need GCI.

Usage
-----
  python -u validation/validate_shanghai_3d_pp_compare.py [--cases N] [--nz Z] [--quick]
"""
from __future__ import annotations
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
warnings.filterwarnings('ignore')

from solvers.simple_solver_3d import SIMPLESolver3D
from solvers.streamfunction_solver_3d import StreamfunctionSolver3D
import validation.validate_shanghai_3d_real as v3d
from validation._provenance import write_csv_with_provenance

_SCRIPT_REL = 'sjtu_tpmshx/validation/validate_shanghai_3d_pp_compare.py'


# ---------------------------------------------------------------- factories


def _factory_simple():
    """Plain SIMPLE 3D — baseline."""
    return SIMPLESolver3D


def _factory_sf_axial():
    """SF + 1D axial pressure recovery (legacy)."""
    class _SF_Axial(StreamfunctionSolver3D):
        def __init__(self, *args, **kwargs):
            kwargs['pressure_recovery'] = 'axial'
            super().__init__(*args, **kwargs)
    return _SF_Axial


def _factory_sf_poisson():
    """SF + 3D Pressure-Poisson recovery (new)."""
    class _SF_Poisson(StreamfunctionSolver3D):
        def __init__(self, *args, **kwargs):
            kwargs['pressure_recovery'] = 'poisson'
            super().__init__(*args, **kwargs)
    return _SF_Poisson


PATHS = {
    'simple':     _factory_simple,
    'sf_axial':   _factory_sf_axial,
    'sf_poisson': _factory_sf_poisson,
}


# ---------------------------------------------------------------- runner


def _run_case_under_path(case_idx, path_name, df, Nx, Ny, Nz, max_outer):
    """Patch v3d.SIMPLESolver3D, run case, restore. Returns result dict."""
    cls = PATHS[path_name]()
    orig = v3d.SIMPLESolver3D
    v3d.SIMPLESolver3D = cls
    try:
        r = v3d._run_one_case(case_idx, df, Nx, Ny, Nz,
                              wall_refine=False,
                              profile_kind='uniform', profile_eta=0.0,
                              max_outer=max_outer)
    finally:
        v3d.SIMPLESolver3D = orig
    r['path'] = path_name
    return r


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', type=int, default=16,
                    help='Run first N cases (default 16)')
    ap.add_argument('--nx', type=int, default=20)
    ap.add_argument('--ny', type=int, default=10)
    ap.add_argument('--nz', type=int, default=3,
                    help='3 for fast iteration; 10 for production parity')
    ap.add_argument('--max-outer', type=int, default=v3d.MAX_OUTER)
    ap.add_argument('--quick', action='store_true',
                    help='Shortcut: 3 cases × Nz=3 × max-outer=2 (smoke test)')
    ap.add_argument('--paths', type=str, default='simple,sf_axial,sf_poisson',
                    help='Comma-separated subset of paths to run')
    args = ap.parse_args()

    if args.quick:
        args.cases = 3
        args.nz = 3
        args.max_outer = 2

    paths_to_run = [p.strip() for p in args.paths.split(',') if p.strip()]
    for p in paths_to_run:
        if p not in PATHS:
            sys.exit(f"Unknown path: {p}. Choose from {list(PATHS)}")

    data_path = (Path(__file__).resolve().parents[2]
                 / 'data' / 'raw_data'
                 / '20260401-上海电气天然气加热器实验工况.xlsx')
    if not data_path.exists():
        # Fallback to legacy hard-coded path (memory: hardcoded path audit)
        data_path = Path(r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data'
                         r'\20260401-上海电气天然气加热器实验工况.xlsx')
    df = pd.read_excel(data_path, engine='openpyxl', sheet_name='Sheet1',
                       header=None, skiprows=2)

    print('=' * 78)
    print(f'Shanghai 3D PPE comparison — {args.cases} cases × {len(paths_to_run)} paths')
    print(f'  Grid: {args.nx} x {args.ny} x {args.nz}  '
          f'max_outer={args.max_outer}')
    print(f'  Paths: {paths_to_run}')
    print('=' * 78)

    rows = []
    t_total = time.time()
    for ci in range(args.cases):
        for path in paths_to_run:
            t0 = time.time()
            try:
                r = _run_case_under_path(ci, path, df, args.nx, args.ny,
                                         args.nz, args.max_outer)
                elapsed = time.time() - t0
                r['elapsed_s'] = round(elapsed, 1)
                rows.append(r)
                print(f"  [{path:11s}] case {r['case']:2d}: "
                      f"dP_sim {r['dP_sim']:7.0f} ({r['err_dP%']:+6.1f}%)  "
                      f"Q_sim {r['Q_sim']:6.0f} ({r['err_Q%']:+5.1f}%)  "
                      f"mass {r['mass_rel_A']:.1e}  {elapsed:5.1f}s")
            except Exception as e:
                elapsed = time.time() - t0
                print(f"  [{path:11s}] case {ci:2d}: FAILED ({type(e).__name__}: "
                      f"{str(e)[:60]}) {elapsed:.1f}s")
                rows.append({
                    'case': ci, 'path': path, 'failed': str(e),
                    'elapsed_s': round(elapsed, 1),
                })
    total_elapsed = time.time() - t_total

    # Save CSV
    out_csv = Path(__file__).parent / 'shanghai_3d_pp_compare.csv'
    write_csv_with_provenance(pd.DataFrame(rows), out_csv, _SCRIPT_REL,
                              encoding='utf-8-sig')
    print(f"\nSaved: {out_csv}")

    # Summary per path
    print('\n' + '=' * 78)
    print('PATH COMPARISON SUMMARY')
    print('=' * 78)
    print(f"{'path':<14}{'N':<5}{'RMSRE_dP%':<12}{'RMSRE_Q%':<12}"
          f"{'max|err_dP|':<14}{'max|err_Q|':<14}{'max mass_rel':<14}{'wall_s':<8}")
    print('-' * 78)
    for path in paths_to_run:
        rs = [r for r in rows if r.get('path') == path and 'err_dP%' in r]
        if not rs:
            print(f"{path:<14}{0:<5}{'(no data)':<12}")
            continue
        err_dP = np.array([r['err_dP%'] for r in rs])
        err_Q = np.array([r['err_Q%'] for r in rs])
        m_rel = np.array([r['mass_rel_A'] for r in rs])
        rmsre_dP = float(np.sqrt(np.mean(err_dP ** 2)))
        rmsre_Q = float(np.sqrt(np.mean(err_Q ** 2)))
        max_dP = float(np.max(np.abs(err_dP)))
        max_Q = float(np.max(np.abs(err_Q)))
        max_m = float(np.max(m_rel))
        wall = float(sum(r['elapsed_s'] for r in rs))
        print(f"{path:<14}{len(rs):<5}{rmsre_dP:<12.2f}{rmsre_Q:<12.2f}"
              f"{max_dP:<14.2f}{max_Q:<14.2f}{max_m:<14.1e}{wall:<8.0f}")
    print(f"\nTotal wall time: {total_elapsed:.0f} s")
    print('=' * 78)

    # Quick interpretation hint per plan §4 Phase C Day 3
    if all(p in [r.get('path') for r in rows] for p in ['simple', 'sf_poisson']):
        rs_simp = [r for r in rows if r.get('path') == 'simple' and 'err_dP%' in r]
        rs_poiss = [r for r in rows if r.get('path') == 'sf_poisson' and 'err_dP%' in r]
        if rs_simp and rs_poiss:
            r_simp = float(np.sqrt(np.mean(
                np.array([r['err_dP%'] for r in rs_simp]) ** 2)))
            r_poiss = float(np.sqrt(np.mean(
                np.array([r['err_dP%'] for r in rs_poiss]) ** 2)))
            print('\nInterpretation hint (plan §4 Phase C Day 3):')
            if r_poiss > 50.0:
                print(f"  dP_Poisson = {r_poiss:.1f}% > 50% — investigate as bug.")
            elif r_poiss < r_simp:
                print(f"  dP_Poisson = {r_poiss:.1f}% < SIMPLE = {r_simp:.1f}% "
                      f"— Poisson outperforms baseline. "
                      f"Run GCI before claiming as method finding.")
            else:
                print(f"  dP_Poisson = {r_poiss:.1f}% in [{r_simp:.1f}%, 50%] "
                      f"— acceptable; write up as SF method.")


if __name__ == '__main__':
    main()
