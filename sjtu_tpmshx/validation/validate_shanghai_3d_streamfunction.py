"""validate_shanghai_3d_streamfunction.py — P7 Shanghai 3D w/ streamfunction-pressure.

Monkey-patches `SIMPLESolver3D` -> `StreamfunctionSolver3D` in the existing
`validate_shanghai_3d_real` validation script, then runs N cases.

This is the P7 (Plan A) drop-in: keeps all LTNE / TPMS / outer-coupling logic,
only replaces the SIMPLE pp_correction step with Helmholtz scalar projection
(strict mass cons, machine-precision).
"""
from __future__ import annotations
import os, sys, warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from solvers.streamfunction_solver_3d import StreamfunctionSolver3D
import solvers.simple_solver_3d as _ss3d_module

# Monkey-patch BEFORE importing the validation module
_ss3d_module.SIMPLESolver3D = StreamfunctionSolver3D

# Now import the validation script with the patched SIMPLESolver3D
import validation.validate_shanghai_3d_real as v3d
v3d.SIMPLESolver3D = StreamfunctionSolver3D

import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', type=int, default=2, help='Run first N cases (default 2)')
    ap.add_argument('--nx', type=int, default=20)
    ap.add_argument('--ny', type=int, default=10)
    ap.add_argument('--nz', type=int, default=3)
    ap.add_argument('--wall-refine', action='store_true')
    ap.add_argument('--max-outer', type=int, default=v3d.MAX_OUTER)
    args = ap.parse_args()

    data_path = r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'
    df = pd.read_excel(data_path, engine='openpyxl', sheet_name='Sheet1',
                       header=None, skiprows=2)

    print(f"P7 Shanghai 3D validation w/ StreamfunctionSolver3D (Helmholtz mass cons)")
    print(f"Cases: first {args.cases}")
    print()

    results = []
    for ci in range(args.cases):
        try:
            r = v3d._run_one_case(ci, df, args.nx, args.ny, args.nz,
                                   wall_refine=args.wall_refine,
                                   profile_kind='uniform', profile_eta=0.0,
                                   max_outer=args.max_outer)
            results.append(r)
            print(f"Case {r['case']:2d}: dP exp/sim {r['dP_exp']:.0f}/{r['dP_sim']:.0f} "
                  f"({r['err_dP%']:+.1f}%)  Q exp/sim {r['Q_exp']:.0f}/{r['Q_sim']:.0f} "
                  f"({r['err_Q%']:+.1f}%)  outer={r['outer_iters']}  "
                  f"[mass_rel={r['mass_rel_A']:.2e}]")
        except Exception as e:
            print(f"Case {ci:2d}: FAILED with {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()

    if results:
        err_dP = np.array([r['err_dP%'] for r in results])
        err_Q = np.array([r['err_Q%'] for r in results])
        rmsre_dP = float(np.sqrt(np.mean(err_dP ** 2)))
        rmsre_Q = float(np.sqrt(np.mean(err_Q ** 2)))
        mass_rel_max = float(max([r['mass_rel_A'] for r in results]))
        print()
        print("=" * 70)
        print(f"  StreamfunctionSolver3D summary ({len(results)} cases):")
        print(f"  RMSRE_dP      : {rmsre_dP:.2f}%")
        print(f"  RMSRE_Q       : {rmsre_Q:.2f}%")
        print(f"  max mass_rel  : {mass_rel_max:.2e}  (SIMPLE typical 1e-3—1e-5)")
        print("=" * 70)


if __name__ == '__main__':
    main()
