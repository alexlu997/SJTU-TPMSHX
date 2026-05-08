"""audit_cfd3_excel.py — audit CFD3 raw Excel structure + Re convention."""
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

XLSX = Path(r'D:\WECHAT\聊天记录\xwechat_files\wxid_mdo0kw39z37m12_69df\msg\file\2026-04\试验记录表_CFD3.xlsx')


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    print(f"File: {XLSX}")
    sheets = pd.ExcelFile(XLSX).sheet_names
    print(f"\nSheets ({len(sheets)}): {sheets}")

    # Pick first 3 sheets for header inspection
    for sheet in sheets[:3]:
        print(f"\n{'='*72}\nSheet: {sheet}\n{'='*72}")
        df_head = pd.read_excel(XLSX, sheet_name=sheet, engine='openpyxl',
                                header=None, nrows=3)
        for i in range(min(3, len(df_head))):
            row = df_head.iloc[i, :].dropna().to_list()
            print(f"  row {i}: {row[:20]}")

    # Audit: pick D_8_05 (Diamond L=8 t=0.5) and G_8_05 if present
    for tpms_short, full in [('D_8_05', 'Diamond'), ('G_8_05', 'Gyroid'),
                              ('D_4_03', 'Diamond'), ('G_4_03', 'Gyroid')]:
        if tpms_short not in sheets:
            continue
        L_str = tpms_short.split('_')[1]
        t_str = tpms_short.split('_')[2]
        L = float(L_str)
        t = float(t_str) / 10.0
        print(f"\n{'-'*72}\nSheet {tpms_short} → {full} L={L} t={t}\n{'-'*72}")
        # Inspect header
        df_head = pd.read_excel(XLSX, sheet_name=tpms_short, engine='openpyxl',
                                header=None, nrows=4)
        print(f"  row 0: {df_head.iloc[0, :15].to_list()}")
        if len(df_head) > 1:
            print(f"  row 1: {df_head.iloc[1, :15].to_list()}")
        # Read data assuming row 0 is header
        df = pd.read_excel(XLSX, sheet_name=tpms_short, engine='openpyxl')
        print(f"  Cols ({len(df.columns)}): {df.columns.to_list()[:20]}")
        print(f"  Rows: {len(df)}")
        if len(df) > 0:
            print(f"  First 3 rows:")
            for i in range(min(3, len(df))):
                print(f"    {df.iloc[i, :15].to_dict()}")


if __name__ == '__main__':
    main()
