"""asym_ntop_expressions_html.py — nTop Evaluate-Expression sheet → offline HTML.

For each of the 12 offset-TPMS cases emits the copy-paste-ready implicit-field
expressions for nTopology's Evaluate Expression block:

    void_A field = φ − phi_lo      (nTop "inside = field<0" → A = {φ < phi_lo})
    void_B field = phi_hi − φ      (inside where φ > phi_hi → B)

with φ the Gyroid/Diamond trig sum (k = 2π/L). Define a variable k = 2*pi/5 in
nTop first (or replace k with 1.2566370614). Each expression has a copy button;
the page is self-contained (no CDN), offline.

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


def _num(v):
    """Format a threshold like nTop wants: parenthesize negatives."""
    return f"({v:g})" if v < 0 else f"{v:g}"


def _expr_void_A(phi, phi_lo):
    return f"{phi} - {_num(phi_lo)}"


def _expr_void_B(phi, phi_hi):
    return f"{_num(phi_hi)} - ({phi})"


def main():
    g = pd.read_excel(XLSX, sheet_name="geom_cases", engine="openpyxl")
    cards = []
    n = 0
    for tpms in ["Diamond", "Gyroid"]:
        phi = PHI[tpms]
        sub = g[g["lattice"] == tpms].sort_values("split_r")
        rows_html = []
        for _, r in sub.iterrows():
            split = r["split_r"]
            lo, hi = float(r["phi_lo"]), float(r["phi_hi"])
            eA, eB = float(r["eps_A"]), float(r["eps_B"])
            vA = _expr_void_A(phi, lo)
            vB = _expr_void_B(phi, hi)
            n += 2
            rows_html.append(f"""
      <div class="case">
        <div class="chead"><b>{tpms} · r={split:g}</b>
          <span class="tag">φ_lo={lo:g} · φ_hi={hi:g}</span>
          <span class="tag eps">ε_A→{eA:.3f} · ε_B→{eB:.3f}</span></div>
        <div class="row"><span class="lab">void_A (大/气)</span>
          {_box(vA)}</div>
        <div class="row"><span class="lab">void_B (小/液)</span>
          {_box(vB)}</div>
      </div>""")
        cards.append(f'<h2 id="{tpms}">{tpms} <span class="cc">'
                     f'(C={sub["C"].iloc[0]:g})</span></h2>' + "".join(rows_html))

    body = "".join(cards)
    page = _PAGE.replace("{{PHI_G}}", _html.escape(PHI["Gyroid"])) \
                .replace("{{PHI_D}}", _html.escape(PHI["Diamond"])) \
                .replace("{{BODY}}", body) \
                .replace("{{NEXPR}}", str(n))
    OUT.write_text(page, encoding="utf-8")
    print(f"[html] {OUT}  ({n} expressions, self-contained)")


def _box(expr: str) -> str:
    esc = _html.escape(expr)
    return (f'<code class="ex">{esc}</code>'
            f'<button class="cp" onclick="cp(this)" data-x="{esc}">复制</button>')


_PAGE = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>nTop 表达式 — 非对称孔隙率 12 case</title>
<style>
:root{--ink:#11151c;--mut:#5b6470;--acc:#014198;--soft:#f3f6fb;--line:#d7dee8;--ok:#0a7d3c;}
*{box-sizing:border-box}
body{font-family:"Source Han Sans SC","Microsoft YaHei",system-ui,sans-serif;color:var(--ink);
     max-width:1080px;margin:0 auto;padding:26px 30px 70px;line-height:1.6;background:#fff}
h1{font-size:1.5rem;border-bottom:3px solid var(--acc);padding-bottom:12px;margin:0 0 6px}
.sub{color:var(--mut);font-size:.86rem;margin:0 0 22px}
h2{font-size:1.2rem;color:var(--acc);margin:34px 0 12px;border-left:5px solid var(--acc);padding-left:12px}
h2 .cc{color:var(--mut);font-weight:400;font-size:.82rem}
.common{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:0 0 8px}
.common b{color:var(--acc)}
code,.ex{font-family:"Cascadia Code",Consolas,monospace;font-size:.8rem}
.common code{background:#fff;border:1px solid var(--line);border-radius:5px;padding:6px 10px;display:block;
     margin:6px 0;white-space:pre-wrap;word-break:break-word}
.case{border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:10px 0;background:#fff;
     box-shadow:0 1px 6px rgba(1,65,152,.05)}
.chead{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:8px}
.chead b{font-size:1rem}
.tag{font-size:.72rem;color:var(--mut);background:var(--soft);border:1px solid var(--line);
     border-radius:20px;padding:2px 10px;font-family:"Cascadia Code",Consolas,monospace}
.tag.eps{color:var(--ok);border-color:#bfe6cd;background:#f0faf3}
.row{display:flex;gap:10px;align-items:flex-start;margin:6px 0}
.lab{flex:0 0 110px;font-size:.78rem;color:var(--mut);padding-top:7px}
.ex{flex:1;background:var(--soft);border:1px solid var(--line);border-radius:6px;padding:7px 11px;
     white-space:pre-wrap;word-break:break-word;color:#16202b}
.cp{flex:0 0 auto;border:1px solid var(--acc);background:#fff;color:var(--acc);border-radius:6px;
     padding:6px 12px;font-size:.76rem;cursor:pointer;transition:all .12s}
.cp:hover{background:var(--acc);color:#fff}
.cp.done{background:var(--ok);border-color:var(--ok);color:#fff}
.note{font-size:.8rem;color:var(--mut);border-left:3px solid var(--acc);background:#fbfcfd;
     padding:9px 16px;border-radius:0 6px 6px 0;margin:14px 0}
</style></head><body>
<h1>nTop 表达式 — 非对称孔隙率 12 case</h1>
<p class="sub">Evaluate Expression 导入 · {{NEXPR}} 个表达式 · void = 互补半空间 · 离线自包含</p>

<div class="common">
<b>先定变量</b>：<code>k = 2*pi/5</code>　（或把表达式里 k 全替成 <code>1.2566370614</code>；x,y,z = 空间坐标 mm）<br>
<b>nTop 约定</b>：implicit body「inside = 场值 &lt; 0」。下面 void_A 场在 φ&lt;φ_lo 处为负、void_B 场在 φ&gt;φ_hi 处为负。<br>
<b>φ 基式</b>（已嵌入每个表达式，无需单独建）：<br>
Gyroid：<code>{{PHI_G}}</code>
Diamond：<code>{{PHI_D}}</code>
</div>

<p class="note">用法：每 case 把 <b>void_A</b>、<b>void_B</b> 两条分别粘进各自的 Evaluate Expression → 得隐式场 → 体（场&lt;0）。
取 1×3 核心(5×5×15mm) + 端面直拉伸 15mm。<b>建好验体积分数 = ε 靶（绿标）再 mesh。</b>先建 Diamond r1 验约定。</p>

{{BODY}}

<script>
function cp(b){
  var t=b.getAttribute('data-x');
  (navigator.clipboard&&navigator.clipboard.writeText(t)||Promise.reject()).then(
    function(){done(b)},
    function(){var ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);
      ta.select();try{document.execCommand('copy')}catch(e){}document.body.removeChild(ta);done(b)});
}
function done(b){var o=b.textContent;b.textContent='已复制';b.classList.add('done');
  setTimeout(function(){b.textContent=o;b.classList.remove('done')},1100);}
</script>
</body></html>"""


if __name__ == "__main__":
    main()
