"""audit_cfd4.py — verify CFD4 column positions + Re/u convention vs CFD3."""
from __future__ import annotations
import sys
from pathlib import Path
import re
import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import geometry as tpms_geometry

XLSX = Path(r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data\副本试验记录表_CFD4.xlsx')

SHEET_RE = re.compile(r'^(Diamond|Gyroid)(\d+)_(\d+)$')


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print(f"File: {XLSX}\n")

    sheets = pd.ExcelFile(XLSX).sheet_names
    geom_sheets = [s for s in sheets if SHEET_RE.match(s)]
    print(f"Geometry sheets: {len(geom_sheets)}")

    # Show header for one sheet to confirm column map
    sheet0 = 'Diamond8_5'
    print(f"\nHeader for {sheet0}:")
    df_h = pd.read_excel(XLSX, sheet_name=sheet0, engine='openpyxl',
                         header=None, nrows=1)
    for j in range(min(45, df_h.shape[1])):
        v = df_h.iloc[0, j]
        if pd.notna(v):
            print(f"  col {j:>2}: {v}")

    # Audit Re convention + u convention across geom sheets
    print(f"\n{'='*100}")
    print(f"Re / u audit (col 0 Re vs ρ·u·D/μ, ρ·u·(D/2)/μ — using D_geom from tpms_geometry):")
    print(f"{'='*100}")
    print(f"  {'sheet':<12}  {'L':>3}  {'t':>4}  {'col0 Re':>7}  "
          f"{'u_xls':>7}  {'ρ':>6}  {'D_geom_mm':>9}  "
          f"{'ρuD/μ':>7}  {'col0/(ρuD/μ)':>13}  "
          f"{'2·u_xls':>7}  {'ρ(2u)D/μ':>9}  {'col0/(ρ2uD/μ)':>13}")
    for sheet in geom_sheets:
        m = SHEET_RE.match(sheet)
        tpms = m.group(1)
        L = float(m.group(2))
        t = float(m.group(3)) / 10.0
        df = pd.read_excel(XLSX, sheet_name=sheet, engine='openpyxl',
                           header=None, skiprows=1)
        # Take first valid row
        for idx in range(len(df)):
            try:
                Re_col = float(df.iloc[idx, 0])
                D_xls = float(df.iloc[idx, 1])
                mu = float(df.iloc[idx, 6])
                rho = float(df.iloc[idx, 9])
                u = float(df.iloc[idx, 10])
                if np.isnan(Re_col):
                    continue
                geom = tpms_geometry(tpms, L, t, 16.0)
                D_geom = float(geom['D_h'])
                Re_uD = rho * u * D_geom / mu
                Re_2uD = rho * (2 * u) * D_geom / mu
                print(f"  {sheet:<12}  {L:>3.0f}  {t:>4.1f}  "
                      f"{Re_col:>7.0f}  {u:>7.3f}  {rho:>6.4f}  "
                      f"{D_geom*1000:>9.4f}  {Re_uD:>7.0f}  "
                      f"{Re_col/Re_uD:>13.4f}  "
                      f"{2*u:>7.3f}  {Re_2uD:>9.0f}  "
                      f"{Re_col/Re_2uD:>13.4f}")
                break
            except Exception:
                continue

    # Deep look for Nu column — find the col with header "Nu"
    print(f"\n\nNu column location ({sheet0}):")
    df_h = pd.read_excel(XLSX, sheet_name=sheet0, engine='openpyxl', header=None, nrows=1)
    for j in range(df_h.shape[1]):
        v = df_h.iloc[0, j]
        if pd.notna(v) and str(v).strip() == 'Nu':
            print(f"  Nu at col {j}")
            break

    # Sample Nu values for several geometries (Re=400 first row)
    print(f"\n\nSample Nu @ first row (target Re=400) per geometry:")
    print(f"  {'sheet':<12}  {'L':>3}  {'t':>4}  {'Re':>4}  {'u':>6}  {'Nu (col 37)':>11}")
    for sheet in geom_sheets:
        m = SHEET_RE.match(sheet)
        tpms = m.group(1)
        L = float(m.group(2))
        t = float(m.group(3)) / 10.0
        df = pd.read_excel(XLSX, sheet_name=sheet, engine='openpyxl',
                           header=None, skiprows=1)
        for idx in range(len(df)):
            try:
                Re_col = float(df.iloc[idx, 0])
                if np.isnan(Re_col):
                    continue
                u = float(df.iloc[idx, 10])
                Nu = float(df.iloc[idx, 37])
                print(f"  {sheet:<12}  {L:>3.0f}  {t:>4.1f}  {Re_col:>4.0f}  "
                      f"{u:>6.3f}  {Nu:>11.4f}")
                break
            except Exception:
                continue


if __name__ == '__main__':
    main()
