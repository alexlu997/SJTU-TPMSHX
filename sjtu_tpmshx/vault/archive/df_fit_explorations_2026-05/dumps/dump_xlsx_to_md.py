"""dump_xlsx_to_md.py — full Excel data dump to markdown tables.

Outputs vault md doc with all 364 experimental rows + 58 columns
(Diamond_汇总 + Gyroid_汇总), preserving block headers (geometry markers).
"""
from __future__ import annotations
import sys, re
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parents[2]
XLSX = PROJECT_ROOT / "data" / "raw_data" / "试验记录表_整理版_v3.1.xlsx"
OUT_MD = PROJECT_ROOT.parent.parent / "vault" / "wiki" / "datasets" / \
         "SJTU-TPMSHX-experimental-dataset-v3.1.md"

# Columns to keep (drop empties at idx 49, 50, 56). Keep all data columns.
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
    out.append(f"### {sheet_name}\n")
    block_rows = []
    cur_block = None
    HDR_RE = re.compile(r'^=+\s*([DG])_(\d+)_(\d+)\s*\((L=\d+mm,\s*t=[\d.]+mm,\s*ε=[\d.]+)\)')

    def flush():
        if not block_rows:
            return
        out.append(f"\n#### {cur_block}\n")
        # markdown table
        out.append('| ' + ' | '.join(hdrs) + ' |')
        out.append('|' + '|'.join(['---'] * len(hdrs)) + '|')
        for r in block_rows:
            out.append('| ' + ' | '.join(fmt(r[c]) for c in KEEP_COLS) + ' |')

    for i, row in df.iterrows():
        if i == 0:
            continue  # skip header row (already captured)
        a = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ''
        m = HDR_RE.search(a)
        if m:
            flush()
            block_rows = []
            tag, L, t = m.group(1), m.group(2), m.group(3)
            cur_block = f"{tag}_{L}_{t} ({m.group(4)})"
            continue
        # data row?
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
    diamond_md = dump_sheet('Diamond_汇总')
    gyroid_md = dump_sheet('Gyroid_汇总')
    print(f"Reading existing vault doc {OUT_MD}...")
    cur = OUT_MD.read_text(encoding='utf-8')

    # Replace any existing "## 完整数据" section, or append.
    sentinel = '\n## 完整实验数据 (xlsx 全 dump)\n'
    if sentinel in cur:
        head = cur.split(sentinel)[0]
    else:
        head = cur.rstrip() + '\n'

    new = head + sentinel + \
          "\n本节为 `试验记录表_整理版_v3.1.xlsx` 全表完整 dump (Diamond_汇总 + Gyroid_汇总), 364 行 × 55 列 (空白列 idx 49/50/56 已去). 按几何分块, 顺序与 xlsx 一致.\n\n" + \
          diamond_md + '\n\n' + gyroid_md + '\n'
    OUT_MD.write_text(new, encoding='utf-8')
    print(f"Wrote {OUT_MD}")
    print(f"Final size: {len(new):,} chars")


if __name__ == '__main__':
    main()
