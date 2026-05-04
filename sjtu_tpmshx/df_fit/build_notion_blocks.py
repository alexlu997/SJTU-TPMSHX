"""build_notion_blocks.py — split xlsx dump per geometry block, output as Python literals.

Reads vault md doc + extracts each `## D_X_YY` or `## G_X_YY` section.
Outputs to data/notion_blocks.txt with one block per section, easy to copy.
"""
from __future__ import annotations
import sys, re
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT = PROJECT_ROOT / "data" / "notion_blocks.txt"

def extract_blocks(md_path: Path) -> list:
    text = md_path.read_text(encoding='utf-8')
    pattern = re.compile(r'^## ([DG])_(\d+)_(\d+)\s*\(([^)]+)\)\s*$', re.M)
    matches = list(pattern.finditer(text))
    blocks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        title = f"{m.group(1)}_{m.group(2)}_{m.group(3)} ({m.group(4)})"
        body = text[start:end].strip()
        # strip the leading "## ..." since we'll set title separately
        body_no_h2 = re.sub(r'^## .*?\n', '', body, count=1).strip()
        blocks.append((title, body_no_h2))
    return blocks


def main():
    diamond_md = PROJECT_ROOT / "data" / "xlsx_dump_Diamond_汇总.md"
    gyroid_md = PROJECT_ROOT / "data" / "xlsx_dump_Gyroid_汇总.md"
    diamond_blocks = extract_blocks(diamond_md)
    gyroid_blocks = extract_blocks(gyroid_md)
    out_dir = PROJECT_ROOT / "data" / "notion_blocks"
    out_dir.mkdir(parents=True, exist_ok=True)
    for t, b in diamond_blocks + gyroid_blocks:
        # Use the block tag (e.g. D_8_03) as filename
        tag = t.split(' ', 1)[0]
        full = f"# {t}\n\n{b}"
        (out_dir / f"{tag}.md").write_text(full, encoding='utf-8')
    files = sorted(out_dir.glob('*.md'))
    print(f"Wrote {len(files)} block files in {out_dir}")
    for f in files:
        print(f"  {f.name}: {f.stat().st_size:,} bytes")


if __name__ == '__main__':
    main()
