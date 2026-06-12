# -*- coding: utf-8 -*-
"""D_7_6 specimen 3D validation — the second end-to-end dP gate.

Specimen: Diamond L=7 mm / t=0.6 mm, SLM, 26 cells flow (0.182 m) x
36 cells frontal (42x42 mm) — same architecture as the Shanghai HX.
Data: 20260609-水直空气侧-D_7_6.xlsx Sheet1 (air-side total dP,
17 valid cases, Re 423-8069; case index 11 excluded — duplicated
sensor block of case 10, verified 2026-06-11).

This gate exists because the production RBF extrapolation at Diamond
L7/t0.6 was falsified here (dP RMSRE 67.4% / bias +64%); the calibrated
override (predict.py _OVERRIDES, cF=454.3) brings it to ~14% / ~0%.
Run with TPMSHX_DF_OVERRIDES=0 to reproduce the failure mode.

dP-only gate: the water side of this specimen is plumbed straight-through
(水直), which differs from the Shanghai cross-flow architecture this
pipeline models — Q numbers are reported but NOT scored.

Usage:  python -m validation.validate_d76_3d [--nx 20 --ny 10 --nz 3]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
ROOT = _THIS.parent.parent
sys.path.insert(0, str(ROOT))

from solvers.tpms_calc import geometry as tpms_geometry  # noqa: E402
import validation.validate_shanghai_3d_real as V          # noqa: E402
from validation._metrics import rmsre_from_pct             # noqa: E402

DATA_XLSX = ROOT.parent / 'data' / 'raw_data' / '20260609-水直空气侧-D_7_6.xlsx'
N_CASES = 18
EXCLUDE = {11}          # duplicated sensor block (= case 10's T/P columns)


def _patch_to_d76():
    """Repoint validate_shanghai_3d_real module globals at the D_7_6 specimen."""
    g = tpms_geometry('Diamond', 7.0, 0.6, 16.0)
    V.TPMS = 'Diamond'
    V.L_CELL = 7.0
    V.T_WALL = 0.6
    V.EPS = g['epsilon']
    V.EPS_A = g['epsilon_A']
    V.D_H = g['D_h']
    V.R_H = g['D_h'] / 2
    V.A0 = g['A_0']
    V.A_FLOW = V.EPS_A * 36 * 49e-6     # 36-cell frontal, void fraction
    # L_DOM / H_DOM / LZ identical to Shanghai (0.182 / 0.042 / 0.042)


def main(nx=20, ny=10, nz=3) -> dict:
    _patch_to_d76()
    df = pd.read_excel(DATA_XLSX, engine='openpyxl', sheet_name='Sheet1',
                       header=None, skiprows=2)
    print(f"D_7_6 3D validation (Diamond L=7 t=0.6, eps={V.EPS:.4f}, "
          f"D_H={V.D_H*1000:.3f} mm, A_FLOW={V.A_FLOW*1e6:.0f} mm2)")
    print(f"Grid {nx}x{ny}x{nz}; cases 1-{N_CASES} excl {sorted(c+1 for c in EXCLUDE)}\n")
    errs = []
    for ci in range(N_CASES):
        if ci in EXCLUDE:
            continue
        r = V._run_one_case(ci, df, nx, ny, nz, wall_refine=False,
                            profile_kind='uniform', profile_eta=0.0,
                            max_outer=V.MAX_OUTER)
        errs.append((ci + 1, r['err_dP%'], bool(r['pressure_state_valid'])))
        print(f"Case {ci+1:2d}: dP {r['dP_exp']:.0f}/{r['dP_sim']:.0f} "
              f"({r['err_dP%']:+.1f}%)  [P-valid={r['pressure_state_valid']}]")
    ok = np.array([e for _, e, v in errs if v and np.isfinite(e)])
    n_inv = sum(1 for _, _, v in errs if not v)
    res = dict(rmsre_dP=rmsre_from_pct(ok), bias=float(ok.mean()),
               n_valid=len(ok), n_invalid=n_inv)
    print(f"\nRMSRE_dP = {res['rmsre_dP']:.2f}%   bias = {res['bias']:+.1f}%   "
          f"valid {res['n_valid']}/{res['n_valid']+n_inv}")
    print("(gate reference 2026-06-11: override ON ~14.1%/+0.2%; OFF ~67.4%/+64%)")
    return res


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--nx', type=int, default=20)
    ap.add_argument('--ny', type=int, default=10)
    ap.add_argument('--nz', type=int, default=3)
    a = ap.parse_args()
    main(a.nx, a.ny, a.nz)
