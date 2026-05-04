"""audit_excel_columns.py — read Excel directly, verify Re convention."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import geometry as tpms_geometry

XLSX = Path(r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data\试验记录表_整理版_v2.xlsx')


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    print(f"File: {XLSX}")
    print(f"Sheets: {pd.ExcelFile(XLSX).sheet_names}")

    for tpms in ('Diamond', 'Gyroid'):
        sheet = f'{tpms}_汇总'
        print(f"\n{'='*72}\nSheet: {sheet}\n{'='*72}")
        # Read header rows
        df_head = pd.read_excel(XLSX, sheet_name=sheet, engine='openpyxl',
                                header=None, nrows=2)
        print(f"\nHeader row 0: {df_head.iloc[0, :15].to_list()}")
        print(f"Header row 1: {df_head.iloc[1, :15].to_list()}")

        # Read data
        df = pd.read_excel(XLSX, sheet_name=sheet, engine='openpyxl',
                           header=None, skiprows=2)
        L_col = pd.to_numeric(df.iloc[:, 1], errors='coerce')
        df = df[L_col.notna()].reset_index(drop=True)

        # Take 3 sample rows: pick L=8, 3 different t, mid-Re
        print(f"\nSample audit rows (verifying Re vs ρ·u·D_h/μ):")
        print(f"  {'L':>3}  {'t':>4}  {'col3=Re_excel':>13}  {'u':>7}  "
              f"{'ρ':>6}  {'μ':>10}  {'D_h_geom_mm':>11}  "
              f"{'Re_Dh_calc':>10}  {'Re_rh_calc':>10}  {'col3/Re_Dh':>10}")
        # Pick a few representative rows
        targets = [(8, 0.5), (6, 0.4), (4, 0.3)]
        for L_t, t_t in targets:
            sel = (df.iloc[:, 1] == L_t) & (df.iloc[:, 2] == t_t)
            sub = df[sel].head(3)
            for _, r in sub.iterrows():
                try:
                    L = float(r.iloc[1])
                    t = float(r.iloc[2])
                    Re_excel = float(r.iloc[3])
                    mu = float(r.iloc[9])
                    rho = float(r.iloc[12])
                    u = float(r.iloc[13])
                    geom = tpms_geometry(tpms, L, t, 16.0)
                    D_h_m = float(geom['D_h'])
                    D_h_mm = D_h_m * 1000
                    Re_Dh = rho * u * D_h_m / mu
                    Re_rh = rho * u * (D_h_m/2) / mu
                    ratio = Re_excel / Re_Dh
                    # Pull Excel col 4 "D/mm" — what length scale Excel actually used
                    D_excel_mm = float(r.iloc[4])
                    Re_from_D_excel = rho * u * (D_excel_mm/1000.0) / mu
                    print(f"  {L:>3.0f}  {t:>4.1f}  {Re_excel:>8.0f}  "
                          f"{u:>7.3f}  {rho:>6.4f}  {mu:>10.4e}  "
                          f"D_geom={D_h_mm:>6.4f}  D_xls={D_excel_mm:>6.4f}  "
                          f"Re(D_xls)={Re_from_D_excel:>6.0f}  "
                          f"col3/Re(D_xls)={Re_excel/Re_from_D_excel:>5.3f}")
                except Exception as e:
                    print(f"  ERR: {e}")


if __name__ == '__main__':
    main()
