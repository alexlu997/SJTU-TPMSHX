"""asym_ntop_expressions_html.py — nTop Evaluate-Expression sheet → offline HTML.

nTop workflow = import ONE φ field per topology into an Evaluate Expression
block, then build the offset solid/void with the per-case parameters δ, C:

    φ (Gyroid/Diamond trig sum, k = 2π/L)        ← the single imported equation
    solid  = { δ−C ≤ φ ≤ δ+C }                    ← threshold the field
    void_A = { φ < δ−C = φ_lo }  (gas, large)
    void_B = { φ > δ+C = φ_hi }  (liquid, small)

C is constant per topology (Diamond 0.3714 / Gyroid 0.3809); δ varies per case.
Emits the φ equation (copy button) + a per-case parameter table (δ, φ_lo, φ_hi,
ε targets). Self-contained (no CDN), offline.

Reads geom_cases from runs/_out/asym_cfd/asym_cfd_worklist.xlsx.
Output: C:/Users/ALEX/Desktop/asym-ntop-expressions.html
Usage:  python -u runs/cfd_asym/asym_ntop_expressions_html.py
"""
import html as _html
from pathlib import Path

import pandas as pd

XLSX = Path(__file__).resolve().parents[1] / "_out" / "asym_cfd" / "asym_cfd_worklist.xlsx"
OUT = Path(r"C:\Users\ALEX\Desktop\asym-ntop-expressions.html")

PHI = {
    "Gyroid": "sin(k*x)*cos(k*y) + sin(k*y)*cos(k*z) + sin(k*z)*cos(k*x)",
    "Diamond": ("sin(k*x)*sin(k*y)*sin(k*z) + sin(k*x)*cos(k*y)*cos(k*z) "
                "+ cos(k*x)*sin(k*y)*cos(k*z) + cos(k*x)*cos(k*y)*sin(k*z)"),
}


def _box(expr: str) -> str:
    esc = _html.escape(expr)
    return (f'<code class="ex">{esc}</code>'
            f'<button class="cp" onclick="cp(this)" data-x="{esc}">复制 φ</button>')


def main():
    g = pd.read_excel(XLSX, sheet_name="geom_cases", engine="openpyxl")
    sections = []
    for tpms in ["Diamond", "Gyroid"]:
        sub = g[g["lattice"] == tpms].sort_values("split_r")
        C = float(sub["C"].iloc[0])
        rows = []
        for _, r in sub.iterrows():
            anchor = " class=\"anchor\"" if r["split_r"] == 1.0 else ""
            rows.append(
                f"<tr{anchor}><td>{r['split_r']:g}</td><td>{r['delta']:.4f}</td>"
                f"<td>{C:.4f}</td><td><b>{r['phi_lo']:.4f}</b></td>"
                f"<td><b>{r['phi_hi']:.4f}</b></td>"
                f"<td class=\"eps\">{r['eps_A']:.3f}</td>"
                f"<td class=\"eps\">{r['eps_B']:.3f}</td></tr>")
        sections.append(f"""
  <h2 id="{tpms}">{tpms} <span class="cc">C = {C:g}（每 case 不变）</span></h2>
  <div class="phi">
    <div class="plab">φ 方程（导入 Evaluate Expression，整个族一次）：</div>
    {_box(PHI[tpms])}
  </div>
  <table>
    <thead><tr><th>r</th><th>δ (offset)</th><th>C</th><th>φ_lo = δ−C</th>
      <th>φ_hi = δ+C</th><th>ε_A 靶</th><th>ε_B 靶</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>""")

    page = _PAGE.replace("{{BODY}}", "".join(sections))
    OUT.write_text(page, encoding="utf-8")
    print(f"[html] {OUT}  (2 φ equations + 12-case δ/C params, self-contained)")


_PAGE = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>nTop φ 方程 + 参数 — 非对称孔隙率</title>
<style>
:root{--ink:#11151c;--mut:#5b6470;--acc:#014198;--soft:#f3f6fb;--line:#d7dee8;--ok:#0a7d3c;}
*{box-sizing:border-box}
body{font-family:"Source Han Sans SC","Microsoft YaHei",system-ui,sans-serif;color:var(--ink);
     max-width:1000px;margin:0 auto;padding:26px 30px 70px;line-height:1.6;background:#fff}
h1{font-size:1.5rem;border-bottom:3px solid var(--acc);padding-bottom:12px;margin:0 0 6px}
.sub{color:var(--mut);font-size:.86rem;margin:0 0 22px}
h2{font-size:1.2rem;color:var(--acc);margin:36px 0 12px;border-left:5px solid var(--acc);padding-left:12px}
h2 .cc{color:var(--mut);font-weight:400;font-size:.8rem}
code,.ex{font-family:"Cascadia Code",Consolas,monospace;font-size:.82rem}
.common{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:0 0 8px}
.common b{color:var(--acc)}
.common code{background:#fff;border:1px solid var(--line);border-radius:5px;padding:3px 8px}
.phi{margin:8px 0 6px}
.plab{font-size:.82rem;color:var(--mut);margin-bottom:6px}
.phi .ex{display:inline-block;width:calc(100% - 96px);vertical-align:middle;background:var(--soft);
     border:1px solid var(--line);border-radius:6px;padding:9px 12px;white-space:pre-wrap;
     word-break:break-word;color:#16202b}
.cp{vertical-align:middle;margin-left:8px;border:1px solid var(--acc);background:#fff;color:var(--acc);
     border-radius:6px;padding:8px 12px;font-size:.78rem;cursor:pointer;transition:all .12s}
.cp:hover{background:var(--acc);color:#fff}
.cp.done{background:var(--ok);border-color:var(--ok);color:#fff}
table{border-collapse:collapse;width:100%;margin:10px 0 4px;font-size:.84rem;
     font-variant-numeric:tabular-nums;font-family:"Cascadia Code",Consolas,monospace}
th,td{border-bottom:1px solid var(--line);padding:7px 12px;text-align:center}
thead th{border-top:2px solid var(--acc);border-bottom:1.5px solid var(--acc);font-weight:600;
     font-family:"Source Han Sans SC","Microsoft YaHei",sans-serif}
tbody tr:last-child td{border-bottom:2px solid var(--acc)}
tbody tr.anchor{background:#eef6ee}
td.eps{color:var(--ok)}
.note{font-size:.8rem;color:var(--mut);border-left:3px solid var(--acc);background:#fbfcfd;
     padding:9px 16px;border-radius:0 6px 6px 0;margin:14px 0}
</style></head><body>
<h1>nTop φ 方程 + 偏移参数 — 非对称孔隙率 12 case</h1>
<p class="sub">每族导入 1 个 φ 方程 → 用 δ、C 做偏移阈值 · 离线自包含</p>

<div class="common">
<b>先定变量</b>：<code>k = 2*pi/5</code>（= 1.2566370614；x,y,z = 空间坐标 mm，L=5mm）。<br>
<b>导入</b>：把下面对应族的 <b>φ 方程</b>粘进 Evaluate Expression（整族一次）。<br>
<b>做几何</b>（用每 case 的 δ、C）：固体壁 <code>δ−C ≤ φ ≤ δ+C</code> = <code>φ_lo ≤ φ ≤ φ_hi</code>；
　void_A（大/气）<code>φ &lt; φ_lo</code>；void_B（小/液）<code>φ &gt; φ_hi</code>。<br>
<b>等价</b>：若用「偏移+厚度」节点 → 偏移 = <code>δ</code>、半厚 = <code>C</code>（先 <code>φ − δ</code> 再阈值 <code>±C</code>）。
</div>

<p class="note">用法：导 φ（一次）→ 每 case 取 δ、C（或 φ_lo/φ_hi）阈值出 void_A、void_B → 各取 1×3 核心(5×5×15mm)+端面直拉伸 15mm。
<b>建好验体积分数 = ε 靶（绿列）再 mesh。</b>先建 Diamond r1 验约定（ε_A=ε_B=0.348）。</p>

{{BODY}}

<script>
function cp(b){var t=b.getAttribute('data-x');
  (navigator.clipboard&&navigator.clipboard.writeText(t)||Promise.reject()).then(
    function(){done(b)},
    function(){var ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);
      ta.select();try{document.execCommand('copy')}catch(e){}document.body.removeChild(ta);done(b)});}
function done(b){var o=b.textContent;b.textContent='已复制';b.classList.add('done');
  setTimeout(function(){b.textContent=o;b.classList.remove('done')},1100);}
</script>
</body></html>"""


if __name__ == "__main__":
    main()
