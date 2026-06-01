"""10kW air-water 空冷器预测定尺 (一次性脚本, 非 production)。
空气热侧 (加压, 绝压), 水冷侧 (38C, 4 t/h)。3 工况, 一台机满足全部。
方形: 自由 s×s, 放开 450 包络。矩形 (后续): H=750 固定, 宽自由。
"""
from __future__ import annotations
import sys, os, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # ...sjtu_tpmshx/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import design.sizing as SZ
from design.cases import DesignCase
from design.sizing import size_fixed_cell
from design.select import enumerate_select, pareto_tags
from design.report import cid, detail_rows
import pandas as pd

XLSX_OUT = r"C:\Users\ALEX\Downloads\quick_design_result.xlsx"
HTML_OUT = r"C:\Users\ALEX\Downloads\quick_design_aircooler_report.html"

# 预测模式: 放开 450mm AM 包络 (运行时覆盖, 不动源码 → UI 不受影响)
SZ.S_MAX = 2.0
SZ.LX_MAX = 2.0

K = 273.15
AIR_DP_PA = 300.0       # 气侧许用压降 [Pa] (风机静压预算) → 钉住迎风面
# (T_in_C, P_kPa_abs, mdot_air, dT=T_in-45)  air cooled to 45C, water 38C/4t·h
ROWS = [(71.0, 145.0, 0.381), (65.6, 182.0, 0.483), (60.3, 242.0, 0.647)]

def build_cases():
    cs = []
    for i, (Tin, Pk, m) in enumerate(ROWS, 1):
        P_h = Pk * 1e3
        cs.append(DesignCase(
            case=i, hot_fluid="air", T_in_h=Tin + K, P_in_h=P_h, mdot_h=m,
            cold_fluid="water", T_in_c=38.0 + K, P_in_c=1.0e6, mdot_c=1.111,
            Q=10_000.0, dPlim_h=AIR_DP_PA / P_h, dPlim_c=1.0,   # 气侧 300Pa, 水侧松(报值)
            dT=Tin - 45.0))                                      # dT → 目标出风45
    return cs

H_RECT = 0.750          # 矩形迎风固定高 [m]

def show(d, tag, height=None):
    print(f"\n[{tag}] feasible={d.feasible} reason={d.reason!r}")
    if not d.feasible:
        return
    if height is None:
        dim = f"s={d.s*1e3:.1f}×{d.s*1e3:.1f}mm Lx={d.Lx*1e3:.1f}mm (方形)"
    else:
        dim = f"W={d.s*1e3:.1f}×H={height*1e3:.0f}mm Lx={d.Lx*1e3:.1f}mm (矩形)"
    print(f"  cell={d.topo} l={d.l} t={d.t}  {dim}  "
          f"V={d.V*1e3:.3f}L wt={d.weight:.3f}kg")
    print(f"  dP_hot_max={d.dP_hot_max*100:.2f}%  dP_cold_max={d.dP_cold_max*100:.2f}%  "
          f"T_out_hot_max={d.T_out_hot_max-K:.2f}C")
    for pc in d.percase:
        print(f"   case{pc['case']}: T_air_out={pc['T_air_out']-K:.2f}C "
              f"T_w_out={pc['T_cold_out']-K:.2f}C Q={pc['Q_W']:.0f}W "
              f"dPh={pc['dP_hot_pa']:.1f}Pa dPc={pc['dP_cold_pa']:.1f}Pa "
              f"Re_h={pc['Re_hot']:.0f} Re_c={pc['Re_cold']:.0f}")

def _summary_rows(results, height):
    """复刻 report.summary_rows, 但矩形 (height!=None) 的 H_mm 取固定高 (而非 W)。"""
    tags = pareto_tags(results)
    H_fix = None if height is None else round(height * 1e3, 2)
    out = []
    for d in results:
        Hmm = H_fix if (height is not None and d.feasible) else round(d.s * 1e3, 2)
        out.append(dict(
            构型=cid(d), 拓扑=d.topo, l_mm=d.l, t_mm=d.t, 布置=d.arrangement,
            可行=("是" if d.feasible else "否"),
            W_mm=round(d.s * 1e3, 2), H_mm=Hmm, Lx_mm=round(d.Lx * 1e3, 2),
            V_L=round(d.V * 1e3, 4), 重量_kg=round(d.weight, 4),
            dP热_max=round(d.dP_hot_max, 4), dP冷_max=round(d.dP_cold_max, 4),
            备注=d.reason, 标记=",".join(tags.get(id(d), []))))
    return out

def _sorted_summary(results, height):
    df = pd.DataFrame(_summary_rows(results, height))
    if not df.empty:
        df = df.sort_values(["可行", "V_L"], ascending=[True, True])
    return df

def write_xlsx_combined(path, sq, rect, height):
    """方形/矩形 × 构型汇总/工况明细 = 4 sheet, 列同 report.write_xlsx。"""
    sheets = {
        "方形-构型汇总": _sorted_summary(sq, None),
        "方形-工况明细": pd.DataFrame(detail_rows(sq) or [{"提示": "无可行构型"}]),
        "矩形-构型汇总": _sorted_summary(rect, height),
        "矩形-工况明细": pd.DataFrame(detail_rows(rect) or [{"提示": "无可行构型"}]),
    }
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name, index=False)
    print(f"[xlsx] {path}")

def _best(results):
    feas = [d for d in results if d.feasible]
    return min(feas, key=lambda d: d.V) if feas else None

def _lowdp(results):
    feas = [d for d in results if d.feasible]
    return min(feas, key=lambda d: d.dP_cold_max) if feas else None

def write_html(path, sq, rect, height):
    K0 = 273.15
    bs, br = _best(sq), _best(rect)
    lo = _lowdp(rect)
    def cells(d, h):
        dim = (f"{d.s*1e3:.0f}×{d.s*1e3:.0f}×{d.Lx*1e3:.1f}" if h is None
               else f"{d.s*1e3:.0f}×{h*1e3:.0f}×{d.Lx*1e3:.1f}")
        air_dp = max(pc["dP_hot_pa"] for pc in d.percase)        # 绝对 dP [Pa] (跨工况max)
        wat_dp = max(pc["dP_cold_pa"] for pc in d.percase) / 1e3  # [kPa]
        return (f"{d.topo} l{d.l:g}/t{d.t:g}", dim, f"{d.V*1e3:.2f}",
                f"{d.weight:.1f}", f"{air_dp:.0f}", f"{wat_dp:.1f}",
                f"{d.T_out_hot_max-K0:.1f}")
    def tbl(results, h, title):
        df = _sorted_summary(results, h)
        head = "".join(f"<th>{c}</th>" for c in df.columns)
        body = ""
        for _, r in df.iterrows():
            tds = "".join(f"<td>{('' if v is None else v)}</td>" for v in r)
            cls = ' class="feas"' if r["可行"] == "是" else ' class="infeas"'
            body += f"<tr{cls}>{tds}</tr>"
        return f"<h3>{title}</h3><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    cmp_rows = ""
    for tag, d, h in [("方形 min-V", bs, None), ("矩形 min-V (H=750)", br, height),
                      ("矩形 低水阻", lo, height)]:
        if d is None:
            continue
        c = cells(d, h)
        cmp_rows += ("<tr><td>" + tag + "</td>" +
                     "".join(f"<td>{x}</td>" for x in c) + "</tr>")
    case_rows = ""
    for c in CASES:
        case_rows += (f"<tr><td>{c.case}</td><td>{c.T_in_h-K0:.1f}</td>"
                      f"<td>{c.P_in_h/1e3:.0f}</td><td>{c.mdot_h:.3f}</td><td>45</td>"
                      f"<td>{c.T_in_c-K0:.0f}</td><td>{c.P_in_c/1e6:.1f}</td>"
                      f"<td>{c.mdot_c:.3f}</td><td>10.0</td></tr>")
    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>10kW 空冷器 TPMS 快速设计预测</title><style>
body{{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;max-width:1080px;
margin:24px auto;padding:0 18px;color:#1a1a1a;line-height:1.5}}
h1{{font-size:22px;border-bottom:3px solid #2c5aa0;padding-bottom:6px}}
h2{{font-size:17px;color:#2c5aa0;margin-top:28px}}h3{{font-size:14px;margin-top:18px}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin:8px 0}}
th,td{{border:1px solid #ccc;padding:4px 7px;text-align:center}}
th{{background:#2c5aa0;color:#fff;font-weight:600}}
tr.infeas{{color:#999;background:#fafafa}}tr.feas:nth-child(even){{background:#f0f5fb}}
.note{{background:#fff8e6;border-left:4px solid #e0a800;padding:8px 12px;margin:10px 0;font-size:13px}}
.key{{background:#e8f4ea;border-left:4px solid #2e8b57;padding:8px 12px;margin:10px 0;font-size:13px}}
code{{background:#eee;padding:1px 4px;border-radius:3px}}
caption{{font-size:11px;color:#666;caption-side:bottom;padding-top:4px}}
</style></head><body>
<h1>10kW 空冷器 — TPMS 换热器快速设计预测报告</h1>
<p style="color:#666;font-size:13px">生成 2026-06-01 · 求解器 SJTU-TPMSHX 快速设计模块 (LTNE 叉流, 均温物性)</p>

<h2>1. 设计工况 (空气热侧 → 冷却到 45°C, 水冷侧)</h2>
<table><thead><tr><th>工况</th><th>进风温 °C</th><th>空气绝压 kPa</th><th>空气 mdot kg/s</th>
<th>出风温 °C</th><th>进水温 °C</th><th>水绝压 MPa</th><th>水 mdot kg/s</th><th>散热 kW</th></tr></thead>
<tbody>{case_rows}</tbody><caption>进风温由 Q=10kW + 体积流量 0.25 m³/s(均温密度) + 出风45°C 反推; 空气绝压为给定加压值; 一台机须同时满足全部工况。</caption></table>

<h2>2. 方法与约束</h2>
<ul style="font-size:13px">
<li>叉流 (空气 +x / 水 +y), LTNE 均质化 3D 内核塌 2D x-y, 物性取进出口<b>均温</b>。</li>
<li><b>气侧许用压降 ≤ 300 Pa</b> (风机静压预算) — 钉住迎风面 (否则优化器无限缩迎风→超音速空气)。</li>
<li>水侧压降不设限, 仅预测报出。材料 304SS (k=16 W/m·K)。</li>
<li>枚举 Diamond+Gyroid × l{{4–8}} × t{{0.3–0.6}} = 40 构型, 目标 min 体积。</li>
<li>预测模式: 放开 450mm AM 包络。方形 = 自由 s×s; 矩形 = 高 H=750mm 固定, 宽自由。</li>
</ul>

<h2>3. 推荐结果</h2>
<table><thead><tr><th>方案</th><th>胞元</th><th>尺寸 W×H×Lx mm</th><th>体积 L</th>
<th>重量 kg</th><th>气侧 dP Pa</th><th>水侧 dP kPa</th><th>出风温 °C</th></tr></thead>
<tbody>{cmp_rows}</tbody><caption>dP 为全工况最大值 (气侧卡 case3 高压工况, 出风卡 case1)。</caption></table>
<div class="key"><b>关键洞察:</b> 矩形高 H=750mm 把水侧迎风 (Lx×H) 拉大 → 水速降 → 同体积下
<b>水侧 dP 比方形低 ~4×</b> (同胞元 Diamond l4/t0.4: 方形 56 kPa vs 矩形 14 kPa)。H=750 反而帮水侧。</div>

<h2>4. 全枚举 (40 构型 × 方形/矩形)</h2>
{tbl(sq, None, "方形 (自由 s×s)")}
{tbl(rect, height, "矩形 (H=750mm 固定, 宽自由)")}

<h2>5. 注意事项 (Caveats)</h2>
<div class="note"><ul style="margin:0">
<li><b>气侧 Nu 低 Re 外推:</b> 大迎风 → 气 Re ~430–1100, case1 近拟合窗下沿 [400,16000], 轻微外推。</li>
<li><b>水侧 Nu:</b> Yan[6] gyroid 关联, Re 460–930 在域 [150,3000] ✓; Diamond 水侧借用 gyroid (气侧控阻, 影响小)。</li>
<li><b>dP = D-F 芯体预测</b>, ~几十% 不确定度, <b>不含进出口集管/风口损失</b> (实物需另加)。</li>
<li><b>制造:</b> 超 450mm AM 包络; 矩形 H=750 须 z 向<b>分段堆叠</b> (叉流 z 均匀, 性能线性可拆)。</li>
<li><b>进风温/空气压力为反推/假设值</b> (客户图未给), 须与实物核对。</li>
</ul></div>

<h2>6. 产物</h2>
<ul style="font-size:13px">
<li>枚举结果 Excel: <code>{XLSX_OUT}</code> (方形/矩形 × 构型汇总/工况明细 4 sheet)</li>
<li>修正工况 Excel: <code>D:\\Postgraduate\\工况_修正.xlsx</code></li>
<li>脚本: <code>sjtu_tpmshx\\runs\\predict_aircooler_10kw.py</code></li>
</ul>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[html] {path}")

CASES = build_cases()

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "sanity"
    cases = build_cases()
    t0 = time.time()
    if mode == "sanity":
        d = size_fixed_cell(cases, "Diamond", 6.0, 0.4, "cross", prop_model="mean")
        show(d, "square Diamond,6,0.4")
    elif mode == "square":
        results, best = enumerate_select(cases, "cross", n_jobs=-1, prop_model="mean")
        for d in results:
            if d.feasible:
                show(d, f"sq {d.topo},{d.l},{d.t}")
        if best:
            show(best, "BEST-square min-V")
    elif mode == "rect":
        results, best = enumerate_select(cases, "cross", n_jobs=-1,
                                         prop_model="mean", height=H_RECT)
        for d in results:
            if d.feasible:
                show(d, f"rect {d.topo},{d.l},{d.t}", height=H_RECT)
        if best:
            show(best, "BEST-rect min-V", height=H_RECT)
    elif mode == "report":
        print("[run] square enumerate ...")
        sq, bs = enumerate_select(cases, "cross", n_jobs=-1, prop_model="mean")
        print("[run] rect enumerate (H=750) ...")
        rect, br = enumerate_select(cases, "cross", n_jobs=-1, prop_model="mean",
                                    height=H_RECT)
        show(bs, "BEST-square min-V")
        show(br, "BEST-rect min-V", height=H_RECT)
        write_xlsx_combined(XLSX_OUT, sq, rect, H_RECT)
        write_html(HTML_OUT, sq, rect, H_RECT)
    print(f"\n[elapsed] {time.time()-t0:.1f}s")
