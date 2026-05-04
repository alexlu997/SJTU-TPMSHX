"""audit_excel_u_re.py — verify Excel u/Re convention.

For each row: compute X = Re_excel · μ / (ρ · u_excel). Compare X to:
  - D_h        (D_h convention, Re = ρ·u·D_h/μ)
  - D_h / 2    (r_h convention)
  - D_h / 4    (??)

If X ≈ D_h: Excel u is single-stream + Re uses D_h
If X ≈ D_h/2: Excel Re uses r_h, u single-stream
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import geometry as tpms_geometry

XLSX = _PROJECT / 'data' / 'raw_data' / '试验记录表_整理版.xlsx'
K_S = 16.0


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    for tpms in ('Diamond', 'Gyroid'):
        df = pd.read_excel(XLSX, sheet_name=f'{tpms}_汇总',
                           engine='openpyxl', header=None, skiprows=2)
        L_col = pd.to_numeric(df.iloc[:, 1], errors='coerce')
        mask = L_col.notna()
        df = df[mask].reset_index(drop=True)
        rows = []
        for idx in range(min(50, len(df))):
            try:
                L = float(df.iloc[idx, 1])
                t = float(df.iloc[idx, 2])
                Re = float(df.iloc[idx, 3])
                mu = float(df.iloc[idx, 9])
                rho = float(df.iloc[idx, 12])
                u = float(df.iloc[idx, 13])
                geom = tpms_geometry(tpms, L, t, K_S)
                D_h = float(geom['D_h'])
                X = Re * mu / (rho * u)   # implied length scale
                rows.append(dict(L=L, t=t, Re=Re, u=u, X=X, D_h=D_h,
                                  X_over_Dh=X / D_h))
            except Exception:
                pass

        d = pd.DataFrame(rows)
        if len(d) == 0:
            continue
        ratio = d['X_over_Dh']
        print(f"\n=== {tpms} ({len(d)} rows) ===")
        print(f"X = Re·μ/(ρ·u)  vs  D_h:")
        print(f"  X / D_h:  mean={ratio.mean():.4f}  median={ratio.median():.4f}  "
              f"std={ratio.std():.4f}")
        print(f"  D_h convention => 1.0    r_h => 0.5    D_h/4 => 0.25")
        # First few rows
        print(f"  Sample (L, t, Re, u, X, D_h, X/D_h):")
        for _, r in d.head(5).iterrows():
            print(f"    L={r['L']:.0f} t={r['t']:.1f}: Re={r['Re']:.0f}  "
                  f"u={r['u']:.3f}  X={r['X']*1000:.3f}mm  D_h={r['D_h']*1000:.3f}mm  "
                  f"ratio={r['X_over_Dh']:.4f}")


if __name__ == '__main__':
    main()
