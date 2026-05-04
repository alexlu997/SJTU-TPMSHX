"""diag_nu_t06_v2.py — broader scan: training (L, t) coverage + Nu vs Re."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import (
    geometry as tpms_geometry, _nu_diamond, _nu_gyroid,
    _NU_ROUGHNESS_FACTOR,
)
from df_fit.fit_nu_single_stream import load_data


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("Nu training coverage + L=7/t=0.6 extrapolation context")
    print("=" * 70)

    for tpms in ('Diamond', 'Gyroid'):
        d = load_data(tpms)
        geoms = sorted(set(zip(d['L'], d['t'])))
        print(f"\n--- {tpms} training (L, t) coverage: {geoms}")

        # Re~10000 across whatever (L, t) we have
        sel = (d['Re_fit'] >= 8000) & (d['Re_fit'] <= 12000)
        sub = d[sel].sort_values(['L', 't', 'Re_fit'])
        print(f"\n  Training rows in Re ∈ [8000, 12000]: {len(sub)}")
        if len(sub) > 0:
            print(f"  {'L':>4}  {'t':>4}  {'ε_f':>6}  {'D_h_mm':>7}  "
                  f"{'Re':>6}  {'Nu_CFD':>7}")
            for _, r in sub.iterrows():
                print(f"  {r['L']:>4.1f}  {r['t']:>4.2f}  {r['eps_f']:>6.4f}  "
                      f"{r['D_h_mm']:>7.4f}  {r['Re_fit']:>6.0f}  {r['Nu']:>7.2f}")

        # Compare Shanghai prediction L=7 t=0.6 across Re sweep
        print(f"\n  Shanghai L=7 t=0.6 prediction sweep:")
        print(f"  {'Re':>6}  {'Nu_smooth':>9}  {'Nu×1.28':>8}")
        L_mm = 7.0
        t = 0.6
        g = tpms_geometry(tpms, L_mm, t, 16.0)
        eps_f = float(g['epsilon']) / 2.0
        D_h_mm = float(g['D_h']) * 1000.0
        for Re in [800, 2000, 4000, 7000, 10000, 16000, 22000]:
            if tpms == 'Diamond':
                Nu_s = _nu_diamond(Re, eps_f, D_h_mm)
            else:
                Nu_s = _nu_gyroid(Re, eps_f, L_mm)
            print(f"  {Re:>6.0f}  {Nu_s:>9.2f}  {Nu_s*_NU_ROUGHNESS_FACTOR:>8.2f}")


if __name__ == '__main__':
    main()
