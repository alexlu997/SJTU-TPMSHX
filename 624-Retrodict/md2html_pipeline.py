"""md2html_pipeline.py — 把 COMPUTATION-PIPELINE-CN.md 转成配色 HTML.

自包含, 无第三方库。处理本文档用到的 markdown 子集:
标题/围栏代码/引用(含⚠告警样式)/表格/无序列表/水平线/行内(**bold** `code`)。
"""
from __future__ import annotations
import html
import re
from pathlib import Path

_THIS = Path(__file__).resolve()
SRC = _THIS.parent / "COMPUTATION-PIPELINE-CN.md"
DST = _THIS.parent / "COMPUTATION-PIPELINE-CN.html"

CSS = """
 body{font:15px/1.7 'Segoe UI',-apple-system,Roboto,'Microsoft YaHei',sans-serif;
      max-width:1000px;margin:32px auto;padding:0 22px;color:#1a1a1a;background:#fff}
 h1{border-bottom:3px solid #5b8def;padding-bottom:8px;color:#15307a}
 h2{margin-top:36px;color:#1f4db8;border-left:5px solid #5b8def;padding-left:11px}
 h3{margin-top:26px;color:#2a5bb0}
 code{background:#eef1f6;padding:1px 5px;border-radius:3px;font-size:13px;
      font-family:'Cascadia Code','Fira Code',Consolas,monospace}
 pre{background:#1e2430;color:#e6e9ef;padding:14px 16px;border-radius:8px;
     overflow-x:auto;font-size:13px;line-height:1.55}
 pre code{background:none;color:inherit;padding:0;font-size:13px}
 blockquote{margin:14px 0;padding:10px 16px;background:#f1f5fd;
     border-left:4px solid #5b8def;border-radius:0 6px 6px 0;color:#33425e}
 blockquote.warn{background:#fdf3e7;border-left-color:#e8870a;color:#7a4a08}
 blockquote.warn2{background:#fdeceb;border-left-color:#d62728;color:#7a1d1e}
 table{border-collapse:collapse;width:100%;margin:14px 0;font-size:13.5px}
 th,td{border:1px solid #cfd6e0;padding:6px 10px;text-align:left}
 th{background:#eef2fb;color:#15307a}
 tr:nth-child(even) td{background:#fafbfd}
 hr{border:none;border-top:1px solid #dde2ea;margin:26px 0}
 ul{padding-left:22px}
 a{color:#1f4db8}
 .upd{color:#888;font-size:12px}
"""


def inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+?)`", r"<code>\1</code>", s)
    return s


def conv(md: str) -> str:
    lines = md.split("\n")
    out, i, n = [], 0, len(lines)
    while i < n:
        ln = lines[i]
        # fenced code
        if ln.strip().startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(html.escape(lines[i], quote=False))
                i += 1
            i += 1
            out.append("<pre><code>" + "\n".join(buf) + "</code></pre>")
            continue
        # heading
        m = re.match(r"^(#{1,3})\s+(.*)$", ln)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            i += 1
            continue
        # hr
        if ln.strip() == "---":
            out.append("<hr>")
            i += 1
            continue
        # blockquote (merge consecutive >)
        if ln.startswith(">"):
            buf, warn = [], 0
            while i < n and lines[i].startswith(">"):
                t = lines[i][1:].lstrip()
                if "⚠⚠" in t:
                    warn = 2
                elif "⚠" in t and warn < 2:
                    warn = 1
                buf.append(inline(t))
                i += 1
            cls = {0: "", 1: " class='warn'", 2: " class='warn2'"}[warn]
            out.append(f"<blockquote{cls}>" + "<br>".join(buf)
                       + "</blockquote>")
            continue
        # table
        if ln.lstrip().startswith("|") and i + 1 < n \
           and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            hdr = [c.strip() for c in ln.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < n and lines[i].lstrip().startswith("|"):
                rows.append([c.strip() for c in
                             lines[i].strip().strip("|").split("|")])
                i += 1
            t = ["<table><thead><tr>"
                 + "".join(f"<th>{inline(h)}</th>" for h in hdr)
                 + "</tr></thead><tbody>"]
            for r in rows:
                t.append("<tr>" + "".join(f"<td>{inline(c)}</td>"
                                          for c in r) + "</tr>")
            t.append("</tbody></table>")
            out.append("".join(t))
            continue
        # unordered list (merge)
        if re.match(r"^\s*-\s+", ln):
            buf = []
            while i < n and re.match(r"^\s*-\s+", lines[i]):
                buf.append("<li>" + inline(re.sub(r"^\s*-\s+", "",
                                                  lines[i])) + "</li>")
                i += 1
            out.append("<ul>" + "".join(buf) + "</ul>")
            continue
        # blank
        if ln.strip() == "":
            i += 1
            continue
        # paragraph (merge until blank/structural)
        buf = []
        while i < n and lines[i].strip() != "" \
                and not re.match(r"^(#{1,3}\s|>|```|\s*-\s|\s*\|)", lines[i]) \
                and lines[i].strip() != "---":
            buf.append(inline(lines[i]))
            i += 1
        out.append("<p>" + "<br>".join(buf) + "</p>")
    return "\n".join(out)


# KaTeX 渲染 (公式用 $...$ / $$...$$; 代码块/行内 code 默认被 auto-render 忽略)。
KATEX = (
    "<link rel='stylesheet' "
    "href='https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css'>\n"
    "<script defer "
    "src='https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js'></script>\n"
    "<script defer "
    "src='https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js' "
    "onload=\"renderMathInElement(document.body,{delimiters:["
    "{left:'$$',right:'$$',display:true},"
    "{left:'$',right:'$',display:false}],throwOnError:false});\"></script>\n"
)


def main():
    md = SRC.read_text(encoding="utf-8")
    body = conv(md)
    doc = (f"<!DOCTYPE html>\n<html lang='zh'>\n<head>\n<meta charset='UTF-8'>"
           f"\n<meta name='viewport' content='width=device-width,"
           f"initial-scale=1'>\n<title>TPMS 逆向定尺 — 计算流程规格</title>\n"
           f"{KATEX}"
           f"<style>{CSS}</style>\n</head>\n<body>\n{body}\n"
           f"<hr><p class='upd'>由 COMPUTATION-PIPELINE-CN.md 生成 "
           f"(md2html_pipeline.py)。源 md 为权威, 改 md 后重跑本脚本。</p>\n"
           f"</body>\n</html>\n")
    DST.write_text(doc, encoding="utf-8")
    print(f"[written] {DST.name}  ({len(doc)} bytes)")


if __name__ == "__main__":
    main()
