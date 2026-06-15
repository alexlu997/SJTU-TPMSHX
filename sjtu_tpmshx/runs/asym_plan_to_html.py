"""asym_plan_to_html.py — render the asym-porosity Phase 1 plan (md) → offline HTML.

Wraps the vault markdown in the SJTU academic template
(`vault/templates/academic-report-template-CN.html`): base64-inlines the header
+ gate-watermark PNGs (self-contained, file:// safe), builds the sidebar TOC from
the h2 sections, maps fenced code → `.eq` blocks and blockquotes → `.callout`.
Unicode formulas (φ/δ/ε/≤/×) render as plain text — no MathJax, fully offline.

Output: C:/Users/ALEX/Desktop/asym-porosity-phase1-CFD-plan-CN.html
Usage:  python -u runs/asym_plan_to_html.py
"""
import base64
import re
from pathlib import Path

import markdown

MD = Path(r"D:\Postgraduate\vault\reports\engineering\2026-06-05-asym-porosity-phase1-CFD-plan-CN.md")
TPL = Path(r"D:\Postgraduate\vault\templates\academic-report-template-CN.html")
ASSETS = TPL.parent / "assets"
OUT = Path(r"C:\Users\ALEX\Desktop\asym-porosity-phase1-CFD-plan-CN.html")


def _b64(p: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


def main():
    md_text = MD.read_text(encoding="utf-8")

    # title = first '# ...' line; strip it from the body (own <h1> below)
    m = re.search(r"^# (.+)$", md_text, flags=re.M)
    title = m.group(1).strip() if m else "非对称孔隙率 Phase 1 计划"
    body_md = re.sub(r"^# .+\n", "", md_text, count=1)

    # [[wikilink|alias]] / [[a/b/name]] → plain leaf name (no dead links in HTML)
    body_md = re.sub(r"\[\[([^\]]+)\]\]",
                     lambda mm: mm.group(1).split("|")[0].split("/")[-1], body_md)

    # the **Label**: metadata lines before the first '---' are consecutive →
    # markdown would collapse them into ONE run-on paragraph. Hard-break each
    # (two trailing spaces) so they render as separate lines.
    head, sep, tail = body_md.partition("\n---")
    head = head.replace("\n**", "  \n**")
    body_md = head + sep + tail

    html_body = markdown.markdown(
        body_md, extensions=["tables", "fenced_code", "sane_lists"])

    # fenced code → .eq formula block (monospace, blue left rule, pre-wrap)
    html_body = re.sub(r"<pre><code[^>]*>(.*?)</code></pre>",
                       lambda mm: '<div class="eq">' + mm.group(1) + "</div>",
                       html_body, flags=re.S)
    # blockquote → .callout highlight
    html_body = re.sub(r"<blockquote>\s*(.*?)\s*</blockquote>",
                       lambda mm: '<div class="callout">' + mm.group(1) + "</div>",
                       html_body, flags=re.S)

    # assign ids to h2 + collect sidebar TOC
    toc = []
    n = [0]

    def _h2(mm):
        inner = mm.group(1)
        plain = re.sub(r"<[^>]+>", "", inner)
        sid = "s%d" % n[0]
        n[0] += 1
        toc.append((sid, plain))
        return '<h2 id="%s">%s</h2>' % (sid, inner)

    html_body = re.sub(r"<h2>(.*?)</h2>", _h2, html_body, flags=re.S)
    nav = "\n".join('  <a href="#%s">%s</a>' % (sid, plain) for sid, plain in toc)

    # reuse template <style>…</head> head + the sidebar-nav <script>
    tpl = TPL.read_text(encoding="utf-8")
    style = tpl[tpl.index("<style>"):tpl.index("</head>")]
    script = tpl[tpl.index("<script>"):tpl.index("</script>") + len("</script>")]

    header_b64 = _b64(ASSETS / "sjtu_header.png")
    gate_b64 = _b64(ASSETS / "sjtu_gate.png")

    # CJK override: justify (template default) stretches inter-character gaps
    # ugly in Chinese → left-align body text. Tighten the metadata head block.
    override = """<style>
  .content p, .content li, .content td, .content th { text-align: left; }
  .content > p:first-of-type{ font-size:0.82rem; color:var(--muted); line-height:2.0;
        background:var(--soft); border-left:3px solid var(--accent); border-radius:0 6px 6px 0;
        padding:12px 18px; max-width:none; }
</style>"""

    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>{title}</title>
{style}
{override}
</head><body>

<div class="layout">
<nav class="sidebar">
  <div class="navtitle">目录</div>
{nav}
</nav>

<main class="content">
  <div class="letterhead"><img src="{header_b64}" alt="上海交通大学"></div>
  <h1>{title}</h1>
{html_body}
  <div class="footer-rule">上海交通大学　Shanghai Jiao Tong University · 非对称孔隙率 Phase 1</div>
</main>
</div>

<div class="watermark"><img src="{gate_b64}" alt=""></div>
{script}
</body></html>"""

    OUT.write_text(html, encoding="utf-8")
    print(f"[html] {OUT}")
    print(f"  {len(html):,} chars · {len(toc)} h2 sections · self-contained (base64 imgs, no CDN)")


if __name__ == "__main__":
    main()
