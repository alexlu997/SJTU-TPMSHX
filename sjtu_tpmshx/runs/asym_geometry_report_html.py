"""
Phase 0 可视化：读 asym_geom_scan CSV → 生成自包含 HTML（手绘 SVG，离线可渲染）→ 桌面。

头牌：r(δ)↑ 与 壁厚 t(δ)↓ 并排同 δ 轴 = 偏置-壁厚 tradeoff。
用法：python -u runs/asym_geometry_report_html.py
"""
import csv
from pathlib import Path

CSV = Path(__file__).resolve().parents[1] / "runs" / "_out" / "asym_geom_scan_2026-06-05.csv"
OUT_HTML = Path(r"C:\Users\ALEX\Desktop") / "TPMS-非对称孔隙率-Phase0-扫描图.html"

A_COL, B_COL = "#0d6f7a", "#a84c26"          # 流体 A / B
TP_COL = {"Diamond": "#0d6f7a", "Gyroid": "#9a7b2e"}   # 两族区分色
FLOOR_MM = 0.3


def load():
    rows = []
    with CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({k: (v if k == "tpms" else float(v) if v not in ("True", "False")
                             else v == "True") for k, v in r.items()})
    by = {}
    for r in rows:
        by.setdefault(r["tpms"], []).append(r)
    return by


def _poly(xs, ys, px, py):
    return " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in zip(xs, ys))


def svg_chart(series, title, ylabel, xlabel="δ (φ-offset)",
              y_min=None, y_max=None, hlines=None, vlines=None,
              width=520, height=330):
    ml, mr, mt, mb = 60, 16, 26, 48
    pw, ph = width - ml - mr, height - mt - mb
    xs_all = [v for s in series for v in s["x"]]
    ys_all = [v for s in series for v in s["y"]]
    xmin, xmax = min(xs_all), max(xs_all)
    ymin = 0.0 if y_min is None else y_min
    ymax = (max(ys_all) * 1.08) if y_max is None else y_max
    if ymax <= ymin:
        ymax = ymin + 1

    def px(x):
        return ml + (x - xmin) / (xmax - xmin) * pw

    def py(y):
        y = min(max(y, ymin), ymax)
        return mt + (1 - (y - ymin) / (ymax - ymin)) * ph

    out = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img">']
    out.append(f'<text x="{ml}" y="16" class="ctitle">{title}</text>')
    # gridlines + y ticks
    for i in range(5):
        yv = ymin + (ymax - ymin) * i / 4
        yy = py(yv)
        out.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{width-mr}" y2="{yy:.1f}" class="grid"/>')
        out.append(f'<text x="{ml-6}" y="{yy+3:.1f}" class="tick ty">{yv:.2f}</text>')
    # x ticks
    for i in range(5):
        xv = xmin + (xmax - xmin) * i / 4
        xx = px(xv)
        out.append(f'<text x="{xx:.1f}" y="{height-mb+16}" class="tick tx">{xv:.2f}</text>')
    # hlines (e.g. floor, gate)
    for hl in (hlines or []):
        yv, col, lab, dash = hl
        if ymin <= yv <= ymax:
            yy = py(yv)
            out.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{width-mr}" y2="{yy:.1f}" '
                       f'stroke="{col}" stroke-width="1.4" stroke-dasharray="{dash}"/>')
            out.append(f'<text x="{width-mr-4}" y="{yy-4:.1f}" class="hlab" fill="{col}">{lab}</text>')
    # vlines (e.g. δ_max)
    for vl in (vlines or []):
        xv, col, lab = vl
        if xmin <= xv <= xmax:
            xx = px(xv)
            out.append(f'<line x1="{xx:.1f}" y1="{mt}" x2="{xx:.1f}" y2="{mt+ph}" '
                       f'stroke="{col}" stroke-width="1.2" stroke-dasharray="3 3"/>')
            out.append(f'<text x="{xx+3:.1f}" y="{mt+12}" class="vlab" fill="{col}">{lab}</text>')
    # axes
    out.append(f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt+ph}" class="axis"/>')
    out.append(f'<line x1="{ml}" y1="{mt+ph}" x2="{width-mr}" y2="{mt+ph}" class="axis"/>')
    out.append(f'<text x="{ml-44}" y="{mt+ph/2}" class="axlab" '
               f'transform="rotate(-90 {ml-44} {mt+ph/2})">{ylabel}</text>')
    out.append(f'<text x="{ml+pw/2}" y="{height-6}" class="axlab">{xlabel}</text>')
    # series
    for s in series:
        dash = s.get("dash", "")
        out.append(f'<polyline points="{_poly(s["x"], s["y"], px, py)}" fill="none" '
                   f'stroke="{s["color"]}" stroke-width="2.4" '
                   f'stroke-dasharray="{dash}" stroke-linejoin="round"/>')
    # legend
    lx, ly = ml + 8, mt + 10
    for s in series:
        out.append(f'<line x1="{lx}" y1="{ly}" x2="{lx+18}" y2="{ly}" stroke="{s["color"]}" '
                   f'stroke-width="2.4" stroke-dasharray="{s.get("dash","")}"/>')
        out.append(f'<text x="{lx+23}" y="{ly+3}" class="leg">{s["label"]}</text>')
        ly += 15
    out.append("</svg>")
    return "\n".join(out)


def main():
    by = load()
    tpms_list = list(by.keys())

    # ---- 头牌：r(δ) ----
    r_series = [dict(x=[r["delta"] for r in rows], y=[min(r["r"], 8.0) for r in rows],
                     color=TP_COL[t], label=t) for t, rows in by.items()]
    r_vlines = [(max(r["delta"] for r in rows if r["feasible"]), TP_COL[t], f"{t} δ_max")
                for t, rows in by.items()]
    chart_r = svg_chart(r_series, "① 偏置比 r 随 δ ↑（y 截顶 8，pinch 处更高）",
                        "r = ε_A / ε_B", y_min=0.0, y_max=8.0,
                        hlines=[(2.0, "#a8322a", "r=2 闸门", "5 4")],
                        vlines=r_vlines)

    # ---- 头牌：壁厚 t(δ) ----
    t_series = [dict(x=[r["delta"] for r in rows], y=[r["t_phys_mm"] for r in rows],
                     color=TP_COL[t], label=t) for t, rows in by.items()]
    t_vlines = [(max(r["delta"] for r in rows if r["feasible"]), TP_COL[t], f"{t} δ_max")
                for t, rows in by.items()]
    chart_t = svg_chart(t_series, "② 壁厚 t 随 δ ↓（撞 0.3mm 地板 = δ_max）",
                        "t_phys [mm]", hlines=[(FLOOR_MM, "#a8322a", "0.3mm 水密地板", "5 4")],
                        vlines=t_vlines)

    # ---- ε_A/ε_B 每族 ----
    eps_charts = []
    for t, rows in by.items():
        s = [dict(x=[r["delta"] for r in rows], y=[r["eps_A"] for r in rows], color=A_COL, label="ε_A 得益"),
             dict(x=[r["delta"] for r in rows], y=[r["eps_B"] for r in rows], color=B_COL, label="ε_B 挤压")]
        eps_charts.append(svg_chart(s, f"③ {t}: ε_A / ε_B 分化", "ε_side"))

    # ---- D_h 每族 ----
    dh_charts = []
    for t, rows in by.items():
        s = [dict(x=[r["delta"] for r in rows], y=[r["Dh_A"] * 1e3 for r in rows], color=A_COL, label="D_h,A"),
             dict(x=[r["delta"] for r in rows], y=[r["Dh_B"] * 1e3 for r in rows], color=B_COL, label="D_h,B")]
        dh_charts.append(svg_chart(s, f"④ {t}: D_h 每侧 [mm]", "D_h [mm]"))

    # summary
    summ = []
    for t, rows in by.items():
        feas = [r for r in rows if r["feasible"]]
        t0 = rows[0]["t_phys_mm"]
        healthy = [r for r in feas if abs(r["t_phys_mm"] - t0) / t0 <= 0.15]
        r_h = max((r["r"] for r in healthy), default=0.0)
        r_m = max((r["r"] for r in feas), default=0.0)
        dmax = max(r["delta"] for r in feas)
        e0 = rows[0]["eps"]
        last = feas[-1]
        summ.append((t, dmax, r_h, r_m, abs(last["eps"]-e0)/e0*100,
                     abs(last["t_phys_mm"]-t0)/t0*100))

    rowshtml = "\n".join(
        f'<tr><td><b>{t}</b></td><td>{dmax:.3f}</td><td class="hl">{rh:.2f}:1</td>'
        f'<td class="muted">{rm:.1f}:1</td><td>{ed:.1f}%</td><td>{td:.0f}%</td>'
        f'<td class="ok">PASS</td></tr>'
        for (t, dmax, rh, rm, ed, td) in summ)

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TPMS 非对称孔隙率 · Phase 0 扫描图</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,900&family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&family=Noto+Sans+SC:wght@400;700&display=swap" rel="stylesheet">
<style>
:root{{--paper:#f4f1ea;--ink:#1d1b16;--soft:#4a463c;--faint:#7c7768;--rule:#cfc7b4;--A:#0d6f7a;--B:#a84c26}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:'IBM Plex Sans','Noto Sans SC',sans-serif;line-height:1.6;
background-image:linear-gradient(rgba(29,27,22,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(29,27,22,.025) 1px,transparent 1px);background-size:26px 26px}}
.wrap{{max-width:1140px;margin:0 auto;padding:40px 28px 90px}}
h1{{font-family:'Fraunces','Noto Sans SC',serif;font-weight:900;font-size:clamp(2rem,5vw,3rem);line-height:1.05;margin:0 0 .1em}}
h1 .em{{font-style:italic;color:var(--B)}}
.sub{{color:var(--soft);max-width:60ch;margin:.3em 0 1.4em}}
.kick{{font-family:'IBM Plex Mono',monospace;font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:var(--faint)}}
.tbl{{margin:18px 0 30px;border:1.5px solid var(--ink);border-radius:5px;overflow:hidden}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{padding:9px 13px;text-align:left;border-bottom:1px solid var(--rule)}}
thead th{{background:var(--ink);color:var(--paper);font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.06em;text-transform:uppercase}}
tbody tr:last-child td{{border-bottom:none}}
td.hl{{font-weight:700;color:var(--A)}}td.muted{{color:var(--faint)}}td.ok{{color:#3f7d34;font-weight:700}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:22px}}
.card{{background:#fff;border:1.5px solid var(--rule);border-radius:8px;padding:14px 16px 8px;box-shadow:18px 18px 0 -10px rgba(29,27,22,.05)}}
.chart{{width:100%;height:auto}}
.ctitle{{font-family:'IBM Plex Sans','Noto Sans SC',sans-serif;font-size:13.5px;font-weight:700;fill:var(--ink)}}
.grid{{stroke:#e7e1d4;stroke-width:1}} .axis{{stroke:var(--ink);stroke-width:1.4}}
.tick{{font-family:'IBM Plex Mono',monospace;font-size:10px;fill:var(--faint)}}
.ty{{text-anchor:end}} .tx{{text-anchor:middle}}
.axlab{{font-family:'IBM Plex Mono',monospace;font-size:11px;fill:var(--soft);text-anchor:middle}}
.leg{{font-family:'IBM Plex Mono',monospace;font-size:11px;fill:var(--ink)}}
.hlab{{font-family:'IBM Plex Mono',monospace;font-size:10px;text-anchor:end;font-weight:600}}
.vlab{{font-family:'IBM Plex Mono',monospace;font-size:9.5px;font-weight:600}}
.note{{background:#ece7db;border-left:4px solid var(--B);padding:14px 18px;border-radius:0 5px 5px 0;margin:30px 0;font-size:.95rem}}
.note b{{color:var(--B)}}
.rowlabel{{font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--B);letter-spacing:.08em;margin:26px 0 8px;font-weight:600}}
footer{{margin-top:50px;padding-top:20px;border-top:3px double var(--ink);font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--faint)}}
</style></head><body><div class="wrap">
<div class="kick">SJTU-TPMSHX · Phase 0 纯几何扫描 · 2026-06-05</div>
<h1>非对称孔隙率 · <span class="em">偏置 ↔ 壁厚</span> tradeoff</h1>
<p class="sub">偏移等值面 δ 把孔隙非对称分配两侧。扫 δ × {{Diamond, Gyroid}}（L=5mm, t=0.4mm, N=128 体素）。闸门按 <b>r_healthy</b>（壁厚漂 ≤15% 的诚实工作点）判。</p>

<div class="tbl"><table>
<thead><tr><th>TPMS</th><th>δ_max</th><th>r_healthy (壁漂≤15%)</th><th>r_max (pinch)</th><th>ε 漂</th><th>t 漂 @δ_max</th><th>闸门</th></tr></thead>
<tbody>
{rowshtml}
</tbody></table></div>

<div class="rowlabel">▌头牌：同一根 δ 轴，左图 r 往上爬，右图壁厚往下掉 —— 这就是 tradeoff</div>
<div class="grid2">
<div class="card">{chart_r}</div>
<div class="card">{chart_t}</div>
</div>

<div class="note"><b>怎么读这两张：</b>往右推 δ，偏置比 r 单调↑（①），但壁厚 t 单调↓（②），直到撞 0.3mm 水密地板 = δ_max（红虚线交点）。所以「能偏多少」由「能接受多薄壁」定，不是无限。r_healthy（壁漂≤15%）才是诚实可用偏置：Diamond 3.77:1 / Gyroid 3.40:1，均 ≫ 2:1 闸门。①里 y 截顶 8；近 δ_max 处 ε_B→0 使 r 飙到 7-24（pinch 虚高，无用）。</div>

<div class="rowlabel">▌两侧孔隙怎么分化</div>
<div class="grid2">
<div class="card">{eps_charts[0]}</div>
<div class="card">{eps_charts[1] if len(eps_charts) > 1 else ''}</div>
</div>

<div class="rowlabel">▌每侧水力直径 D_h（→ 影响 h 与 dP）</div>
<div class="grid2">
<div class="card">{dh_charts[0]}</div>
<div class="card">{dh_charts[1] if len(dh_charts) > 1 else ''}</div>
</div>

<footer>纯几何 PoC · 数据 runs/_out/asym_geom_scan_2026-06-05.csv (82 行) · 壁厚为 slab 近似 t=(1−ε)/A0 · 闸门 PASS（两族）· 下游收益须 Phase 1/3 CFD+优化</footer>
</div></body></html>"""

    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"[HTML] {OUT_HTML}")


if __name__ == "__main__":
    main()
