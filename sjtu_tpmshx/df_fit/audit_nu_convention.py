"""audit_nu_convention.py — verify Nu correlation convention.

Question: does current Nu formula expect (full ε, D_h Re) or (half ε, r_h Re)?

Method: take training Excel Nu column, compare against formula evaluated under
both conventions. Whichever gives smaller error is the fit convention.

Excel columns (per Re-Nu-convention-audit doc):
  col  3: Re
  col 39: h [W/(m²·K)]
  col 40: Nu (= h·D_h/k_f standard definition)
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

from solvers.tpms_calc import (
    geometry as tpms_geometry, nu_from_Re,
    air_viscosity, air_conductivity, air_density,
)

XLSX = _PROJECT / 'data' / 'raw_data' / '试验记录表_整理版.xlsx'

# Column indices (zero-based, matches load_data.py + audit doc)
_COL_L = 1; _COL_T = 2; _COL_RE = 3; _COL_T_C = 7
_COL_MU = 9; _COL_RHO = 12; _COL_U = 13
_COL_DP = 47
_COL_H = None    # need to find
_COL_NU = None

K_S = 16.0


def find_h_nu_cols(df, tpms='Diamond'):
    """Find h and Nu columns by header text in row 0."""
    h_col = nu_col = None
    for col in range(df.shape[1]):
        v0 = str(df.iloc[0, col]) if pd.notna(df.iloc[0, col]) else ''
        v1 = str(df.iloc[1, col]) if pd.notna(df.iloc[1, col]) else ''
        text = (v0 + ' ' + v1).strip()
        if 'h/W/m2K' in text or 'h_sf' in text.lower() or text == 'h':
            h_col = col
        if 'Nu' in text and ('Nusselt' in text or text.strip() == 'Nu'):
            nu_col = col
    return h_col, nu_col


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    print("Nu Convention Audit\n" + "=" * 60)
    for tpms in ('Diamond', 'Gyroid'):
        sheet = f"{tpms}_汇总"
        df = pd.read_excel(XLSX, sheet_name=sheet, engine='openpyxl', header=None)
        # Find h/Nu columns
        # Per Re-Nu-convention-audit.md: col 39 = h, col 40 = Nu
        col_h, col_nu = 39, 40

        # Read header text
        h0 = str(df.iloc[0, col_h]) if pd.notna(df.iloc[0, col_h]) else ''
        h1 = str(df.iloc[1, col_h]) if pd.notna(df.iloc[1, col_h]) else ''
        nu0 = str(df.iloc[0, col_nu]) if pd.notna(df.iloc[0, col_nu]) else ''
        nu1 = str(df.iloc[1, col_nu]) if pd.notna(df.iloc[1, col_nu]) else ''
        print(f"\n{tpms}:  col 39 header = '{h0}|{h1}'  col 40 = '{nu0}|{nu1}'")

        # Skip 2 header rows
        df = df.iloc[2:].reset_index(drop=True)
        # Filter rows with valid L
        L_col = pd.to_numeric(df.iloc[:, _COL_L], errors='coerce')
        mask = L_col.notna()
        df = df[mask].reset_index(drop=True)

        # Sample: take first 30 rows across geometries
        results = []
        for idx in range(min(50, len(df))):
            try:
                L = float(df.iloc[idx, _COL_L])
                t = float(df.iloc[idx, _COL_T])
                Re_excel = float(df.iloc[idx, _COL_RE])
                Nu_excel = float(df.iloc[idx, col_nu])
                T_C = float(df.iloc[idx, _COL_T_C])
                u = float(df.iloc[idx, _COL_U])
                T_K = T_C + 273.15

                geom = tpms_geometry(tpms, L, t, K_S)
                eps_full = float(geom['epsilon'])
                eps_half = eps_full / 2.0
                D_h_m = float(geom['D_h'])
                D_h_mm = D_h_m * 1000.0
                r_h_m = D_h_m / 2.0
                L_cell_mm = L

                # 4 convention tests
                # full ε + D_h Re (current code)
                Nu_full_Dh = nu_from_Re(tpms, Re_excel, eps_full, L_cell_mm, D_h_mm)
                # full ε + r_h Re (Re halved)
                Nu_full_rh = nu_from_Re(tpms, Re_excel * 0.5, eps_full, L_cell_mm, D_h_mm)
                # half ε + D_h Re
                Nu_half_Dh = nu_from_Re(tpms, Re_excel, eps_half, L_cell_mm, D_h_mm)
                # half ε + r_h Re
                Nu_half_rh = nu_from_Re(tpms, Re_excel * 0.5, eps_half, L_cell_mm, D_h_mm)

                results.append(dict(
                    L=L, t=t, Re_excel=Re_excel, Nu_excel=Nu_excel,
                    Nu_full_Dh=Nu_full_Dh, err_full_Dh=(Nu_full_Dh - Nu_excel) / Nu_excel * 100,
                    Nu_full_rh=Nu_full_rh, err_full_rh=(Nu_full_rh - Nu_excel) / Nu_excel * 100,
                    Nu_half_Dh=Nu_half_Dh, err_half_Dh=(Nu_half_Dh - Nu_excel) / Nu_excel * 100,
                    Nu_half_rh=Nu_half_rh, err_half_rh=(Nu_half_rh - Nu_excel) / Nu_excel * 100,
                ))
            except Exception as e:
                pass

        if not results:
            print(f"  no data rows")
            continue

        rdf = pd.DataFrame(results)
        # Stats
        print(f"\n  {len(rdf)} rows tested")
        print(f"  Convention                     |   bias%   RMSRE%   max|err|%")
        for label, col in [
            ('full ε + D_h Re (current code)', 'err_full_Dh'),
            ('full ε + r_h Re                ', 'err_full_rh'),
            ('half ε + D_h Re                ', 'err_half_Dh'),
            ('half ε + r_h Re                ', 'err_half_rh'),
        ]:
            errs = rdf[col].to_numpy()
            errs = errs[np.isfinite(errs)]
            if len(errs) == 0:
                continue
            bias = float(np.mean(errs))
            rmsre = float(np.sqrt(np.mean(errs ** 2)))
            maxabs = float(np.max(np.abs(errs)))
            print(f"  {label} | {bias:+7.2f}  {rmsre:6.2f}  {maxabs:6.2f}")

        # Sample rows
        print(f"\n  Sample rows:")
        print(f"  L  t   Re_exc  Nu_exc  Nu(f+Dh)  Nu(f+rh)  Nu(h+Dh)  Nu(h+rh)")
        for _, r in rdf.head(8).iterrows():
            print(f"  {r['L']:.0f}  {r['t']:.1f}  {r['Re_excel']:6.0f}  "
                  f"{r['Nu_excel']:6.2f}  {r['Nu_full_Dh']:7.2f}  {r['Nu_full_rh']:7.2f}  "
                  f"{r['Nu_half_Dh']:7.2f}  {r['Nu_half_rh']:7.2f}")


if __name__ == '__main__':
    main()
