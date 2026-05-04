"""dump_xlsx_split.py — split xlsx into per-sheet markdown files.

Outputs Diamond + Gyroid full markdown tables to separate files for Notion upload.
Also fixes title wording (TPMS HX 试验数据集, not 风洞).
"""
from __future__ import annotations
import sys, re, json
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parents[2]
XLSX = PROJECT_ROOT / "data" / "raw_data" / "试验记录表_整理版_v3.1.xlsx"
OUT_DIR = PROJECT_ROOT / "data"

KEEP_COLS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17,
             18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32,
             33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47,
             48, 51, 52, 53, 54, 55, 57]


def fmt(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ''
    if isinstance(v, float):
        if abs(v) < 1e-4 and v != 0:
            return f'{v:.4e}'
        if abs(v) >= 10000:
            return f'{v:.1f}'
        if abs(v) >= 100:
            return f'{v:.3f}'
        if abs(v) >= 10:
            return f'{v:.4f}'
        return f'{v:.5f}'
    return str(v)


def dump_sheet(sheet_name: str) -> str:
    df = pd.read_excel(XLSX, sheet_name=sheet_name, engine='openpyxl', header=None)
    hdrs = [str(df.iloc[0, c]) if pd.notna(df.iloc[0, c]) else f'col{c}' for c in KEEP_COLS]
    out = []
    block_rows = []
    cur_block = None
    HDR_RE = re.compile(r'^=+\s*([DG])_(\d+)_(\d+)\s*\((L=\d+mm,\s*t=[\d.]+mm,\s*ε=[\d.]+)\)')

    def flush():
        if not block_rows:
            return
        out.append(f"\n## {cur_block}\n")
        out.append('| ' + ' | '.join(hdrs) + ' |')
        out.append('|' + '|'.join(['---'] * len(hdrs)) + '|')
        for r in block_rows:
            out.append('| ' + ' | '.join(fmt(r[c]) for c in KEEP_COLS) + ' |')

    for i, row in df.iterrows():
        if i == 0:
            continue
        a = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ''
        m = HDR_RE.search(a)
        if m:
            flush()
            block_rows = []
            tag, L, t = m.group(1), m.group(2), m.group(3)
            cur_block = f"{tag}_{L}_{t} ({m.group(4)})"
            continue
        try:
            re_v = float(row.iloc[3])
            if not np.isfinite(re_v):
                continue
            block_rows.append(row)
        except (ValueError, TypeError):
            continue
    flush()
    return '\n'.join(out)


def main():
    print(f"Reading {XLSX.name}...")
    for sheet in ['Diamond_汇总', 'Gyroid_汇总']:
        md = dump_sheet(sheet)
        out = OUT_DIR / f"xlsx_dump_{sheet}.md"
        out.write_text(md, encoding='utf-8')
        print(f"  {sheet}: {len(md):,} chars → {out}")


if __name__ == '__main__':
    main()
