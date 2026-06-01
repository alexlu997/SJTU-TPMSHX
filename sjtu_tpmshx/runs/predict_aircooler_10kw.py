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

import math
import design.sizing as SZ
from design.cases import DesignCase
from design.sizing import size_fixed_cell, solve_Lx, Design
from design.select import enumerate_select, pareto_tags
from design.forward import forward, dP_fracs
from design.fluids import nu_re_window
from design.report import cid, detail_rows
from solvers.tpms_calc import geometry as _geom
import pandas as pd

try:                                   # GBK console 无法编码 ²/中文 → 强制 UTF-8 stdout
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

XLSX_OUT = r"C:\Users\ALEX\Downloads\quick_design_result.xlsx"
HTML_OUT = r"C:\Users\ALEX\Downloads\quick_design_aircooler_report.html"

AREA2 = 0.075        # 解读2: 总迎风面积 [m²] = 750 cm² (方形边 = sqrt = 273.9mm)
DP_DEGEN = 0.30      # dP frac > 此 → 退化标记 (同 sizing.DP_DEGEN_FRAC)

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

def size_fixed_area(cases, topo, l, t, A_f, arr="cross", k_s=16.0,
                    prop_model="mean", rho_s=7900.0):
    """解读2: 迎风总面积固定 = A_f (方形, 边=sqrt(A_f)), 仅深度 Lx 自由。
    面积固定 → 不能放大迎风降气阻; 取全 K 冷却所需 Lx, 照实报两侧 dP。
    feasible = 冷却可达 (Lx≤cap); 气侧 dP 超 300Pa 仅标记 (不当不可行, 让用户看数)。"""
    s = math.sqrt(A_f)
    geo = _geom(topo, l, t, k_s, N=128); EPS = geo["epsilon"]
    Lx, seed = 0.0, None                       # 全 K 冷却 Lx (固定 s)
    for c in cases:
        lx, r = solve_Lx(c, topo, l, t, s, arr, k_s=k_s, prop_model=prop_model, seed=seed)
        if lx is None:
            return Design(False, topo, l, t, s, arrangement=arr,
                          reason="冷却不可达@固定面积")
        if r is not None:
            seed = r.fields
        Lx = max(Lx, lx)
    if Lx > SZ.LX_MAX:
        return Design(False, topo, l, t, s, arrangement=arr, reason="Lx>cap@固定面积")
    percase, dPh, dPc, Tout = [], 0.0, 0.0, 0.0
    re_h = re_c = 0.0; warns = set()
    for c in cases:
        r = forward(c, topo, l, t, s, Lx, arr, k_s=k_s, prop_model=prop_model)
        percase.append(dict(
            case=c.case, hot_fluid=c.hot_fluid, cold_fluid=c.cold_fluid,
            T_air_out=r.T_out_hot, T_cold_out=r.T_out_cold, Q_W=r.Q_hot,
            dP_hot_frac=r.dP_hot_frac, dP_hot_pa=r.dP_hot_frac * c.P_in_h,
            dP_cold_frac=r.dP_cold_frac, dP_cold_pa=r.dP_cold_frac * c.P_in_c,
            Re_hot=r.Re_hot, Re_cold=r.Re_cold))
        dPh = max(dPh, r.dP_hot_frac); dPc = max(dPc, r.dP_cold_frac)
        Tout = max(Tout, r.T_out_hot)
        re_h = max(re_h, r.Re_hot); re_c = max(re_c, r.Re_cold)
        hlo, hhi = nu_re_window(c.hot_fluid); clo, chi = nu_re_window(c.cold_fluid)
        if r.Re_hot < hlo: warns.add("热Re↓外推")
        if r.Re_hot > hhi: warns.add("热Re↑外推")
        if r.Re_cold < clo: warns.add("冷Re↓外推")
        if r.Re_cold > chi: warns.add("冷Re↑外推")
        if r.dP_hot_frac > c.dPlim_h: warns.add("气dP>300Pa")   # 面积固定下气阻可能超限
        if r.dP_hot_frac > DP_DEGEN: warns.add("热dP退化")
        if r.dP_cold_frac > DP_DEGEN: warns.add("冷dP退化")
    V = A_f * Lx
    return Design(True, topo, l, t, s, Lx, arr, V, (1.0 - EPS) * V * rho_s,
                  dPh, dPc, Tout, reason="", percase=percase, height=0.0,
                  Re_hot_max=re_h, Re_cold_max=re_c, validity=";".join(sorted(warns)))

def enumerate_area(cases, A_f, arr="cross", prop_model="mean"):
    """解读2 枚举: 全 NODES 各跑 size_fixed_area, 取 min-V best。"""
    from design.select import NODES
    combos = [(tp, l, t) for tp in NODES["topo"] for l in NODES["l"] for t in NODES["t"]]
    results = [size_fixed_area(cases, tp, l, t, A_f, arr, prop_model=prop_model)
               for tp, l, t in combos]
    feas = [d for d in results if d.feasible]
    best = min(feas, key=lambda d: d.V) if feas else None
    return results, best

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

def write_xlsx_interps(path, edge_res, edge_h, area_res):
    """两解读 × 汇总/明细 = 4 sheet, 列同 report.write_xlsx。
    解读1 (一条边750mm, 矩形 H=edge_h); 解读2 (总面积固定, 方形)。"""
    sheets = {
        "解读1_一条边750-汇总": _sorted_summary(edge_res, edge_h),
        "解读1_一条边750-明细": pd.DataFrame(detail_rows(edge_res) or [{"提示": "无可行"}]),
        "解读2_总面积750-汇总": _sorted_summary(area_res, None),
        "解读2_总面积750-明细": pd.DataFrame(detail_rows(area_res) or [{"提示": "无可行"}]),
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

def write_html(path, edge_res, edge_h, area_res, A_f):
    K0 = 273.15
    be, la = _best(edge_res), _lowdp(edge_res)
    ba = _best(area_res)
    side = math.sqrt(A_f) * 1e3        # 解读2 方形边 [mm]
    def cells(d, h):
        if d is None:
            return ("—",) * 8
        dim = (f"{d.s*1e3:.0f}×{d.s*1e3:.0f}×{d.Lx*1e3:.1f}" if h is None
               else f"{d.s*1e3:.0f}×{h*1e3:.0f}×{d.Lx*1e3:.1f}")
        air_dp = max(pc["dP_hot_pa"] for pc in d.percase)
        wat_dp = max(pc["dP_cold_pa"] for pc in d.percase) / 1e3
        flag = getattr(d, "validity", "") or "—"
        return (f"{d.topo} l{d.l:g}/t{d.t:g}", dim, f"{d.V*1e3:.2f}",
                f"{d.weight:.1f}", f"{air_dp:.0f}", f"{wat_dp:.1f}",
                f"{d.T_out_hot_max-K0:.1f}", flag)
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
    for tag, d, h in [("解读1 一条边750 · min-V", be, edge_h),
                      ("解读1 一条边750 · 低水阻", la, edge_h),
                      ("解读2 总面积750 · min-V", ba, None)]:
        c = cells(d, h)
        cmp_rows += "<tr><td>" + tag + "</td>" + "".join(f"<td>{x}</td>" for x in c) + "</tr>"
    case_rows = ""
    for c in CASES:
        case_rows += (f"<tr><td>{c.case}</td><td>{c.T_in_h-K0:.1f}</td>"
                      f"<td>{c.P_in_h/1e3:.0f}</td><td>{c.mdot_h:.3f}</td><td>45</td>"
                      f"<td>{c.T_in_c-K0:.0f}</td><td>{c.P_in_c/1e6:.1f}</td>"
                      f"<td>{c.mdot_c:.3f}</td><td>10.0</td></tr>")
    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>10kW 空冷器 TPMS 快速设计预测</title><style>
body{{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;max-width:1100px;
margin:24px auto;padding:0 18px;color:#1a1a1a;line-height:1.5}}
h1{{font-size:22px;border-bottom:3px solid #2c5aa0;padding-bottom:6px}}
h2{{font-size:17px;color:#2c5aa0;margin-top:28px}}h3{{font-size:14px;margin-top:18px}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin:8px 0}}
th,td{{border:1px solid #ccc;padding:4px 7px;text-align:center}}
th{{background:#2c5aa0;color:#fff;font-weight:600}}
tr.infeas{{color:#999;background:#fafafa}}tr.feas:nth-child(even){{background:#f0f5fb}}
.note{{background:#fff8e6;border-left:4px solid #e0a800;padding:8px 12px;margin:10px 0;font-size:13px}}
.key{{background:#e8f4ea;border-left:4px solid #2e8b57;padding:8px 12px;margin:10px 0;font-size:13px}}
.warn{{background:#fdecea;border-left:4px solid #c0392b;padding:8px 12px;margin:10px 0;font-size:13px}}
code{{background:#eee;padding:1px 4px;border-radius:3px}}
caption{{font-size:11px;color:#666;caption-side:bottom;padding-top:4px}}
</style></head><body>
<h1>10kW 空冷器 — TPMS 换热器快速设计预测报告</h1>
<p style="color:#666;font-size:13px">生成 2026-06-01 · SJTU-TPMSHX 快速设计模块 (LTNE 叉流, 均温物性) · 迎风「750」两种解读</p>

<h2>1. 设计工况 (空气热侧 → 冷却到 45°C, 水冷侧)</h2>
<table><thead><tr><th>工况</th><th>进风温 °C</th><th>空气绝压 kPa</th><th>空气 mdot kg/s</th>
<th>出风温 °C</th><th>进水温 °C</th><th>水绝压 MPa</th><th>水 mdot kg/s</th><th>散热 kW</th></tr></thead>
<tbody>{case_rows}</tbody><caption>进风温由 Q=10kW + 体积流量 0.25 m³/s(均温密度) + 出风45°C 反推; 空气绝压为给定加压值; 一台机须同时满足全部工况。</caption></table>

<h2>2. 「750」两种解读 (甲方未说明)</h2>
<ul style="font-size:13px">
<li><b>解读1 — 一条边 = 750mm</b>: 矩形迎风, 一边固定 750mm, 另一边 + 深度自由, 求 min-V。
迎风可放大 → 气侧 dP 自动压到 ≤300Pa (优化器钉住)。原图「750×高度」字面读法。</li>
<li><b>解读2 — 总迎风面积 = 750 cm² (0.075 m²)</b>: 方形迎风 (边 = {side:.0f}mm), 仅深度自由。
<b>面积固定 → 不能放大迎风降气阻</b>; 取冷却所需 Lx, 照实报气侧 dP (可能 ≫300Pa)。⚠ 750 的单位是假设。</li>
</ul>

<h2>3. 方法与约束</h2>
<ul style="font-size:13px">
<li>叉流 (空气 +x / 水 +y), LTNE 均质化 3D 内核塌 2D, 物性取进出口<b>均温</b>; 材料 304SS (k=16)。</li>
<li>解读1 气侧许用 dP ≤ 300 Pa (作可行门); 解读2 面积固定, 气 dP 照实报 + 超 300 标记。</li>
<li>枚举 Diamond+Gyroid × l{{4–8}} × t{{0.3–0.6}} = 40 构型, 目标 min 体积; 放开 450mm AM 包络。</li>
</ul>

<h2>4. 推荐结果对比</h2>
<table><thead><tr><th>方案</th><th>胞元</th><th>尺寸 W×H×Lx mm</th><th>体积 L</th>
<th>重量 kg</th><th>气侧 dP Pa</th><th>水侧 dP kPa</th><th>出风温 °C</th><th>验证/标记</th></tr></thead>
<tbody>{cmp_rows}</tbody><caption>dP 为全工况最大值。解读2 若「气dP>300Pa」= 在该固定面积下风机静压须 &gt; 300Pa。</caption></table>
<div class="key"><b>解读1 洞察:</b> 一条边 750mm 把对应方向迎风拉大 → 水/气速降 → min-V 件水侧 dP 比等体积自由方形低。
迎风可调 → 气 dP 守在 300Pa。</div>
<div class="warn"><b>解读2 风险:</b> 总面积仅 0.075 m² (方形边 {side:.0f}mm) → 空气面速 ≈ {0.25/A_f:.1f} m/s, 远高于解读1。
面积固定无法靠放大迎风降气阻 → 气侧 dP 多半 <b>≫ 300 Pa</b> (见表「气dP>300Pa」标记), 须配高静压风机, 或加大迎风面积。</div>

<h2>5. 全枚举 (40 构型)</h2>
{tbl(edge_res, edge_h, "解读1 — 一条边 750mm (矩形, 另一边自由)")}
{tbl(area_res, None, f"解读2 — 总面积 750 cm² (方形边 {side:.0f}mm, 仅深度自由)")}

<h2>6. 注意事项 (Caveats)</h2>
<div class="note"><ul style="margin:0">
<li><b>「750」单位/含义为假设</b>: 解读2 按 750 cm²=0.075 m²。若实为他值, 数全变 — 须甲方确认。</li>
<li><b>气侧 Nu 低 Re 外推</b>: 大迎风 → 气 Re 偏低, 部分近/低于拟合窗 [400,16000] 下沿; 见各行「验证域」。</li>
<li><b>水侧 Nu</b>: Yan[6] gyroid, 域 [150,3000]; Diamond 水侧借用 gyroid (气侧控阻, 影响小)。</li>
<li><b>dP = D-F 芯体预测</b>, ~几十% 不确定度, <b>不含进出口集管/风口损失</b> (实物另加)。</li>
<li><b>制造</b>: 超 450mm AM 包络须分段堆叠 (叉流 z 均匀, 性能线性可拆); 进风温/空气压力为反推/假设值。</li>
</ul></div>

<h2>7. 产物</h2>
<ul style="font-size:13px">
<li>枚举结果 Excel: <code>{XLSX_OUT}</code> (解读1/解读2 × 汇总/明细 4 sheet)</li>
<li>修正工况 Excel: <code>D:\\Postgraduate\\工况_修正.xlsx</code> · 脚本: <code>runs\\predict_aircooler_10kw.py</code></li>
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
        print("[run] 解读1: 一条边 750mm (rect) enumerate ...")
        edge, be = enumerate_select(cases, "cross", n_jobs=-1, prop_model="mean",
                                    height=H_RECT)
        print(f"[run] 解读2: 总面积 {AREA2} m² (square {math.sqrt(AREA2)*1e3:.0f}mm) enumerate ...")
        area, ba = enumerate_area(cases, AREA2, "cross", prop_model="mean")
        show(be, "解读1 一条边750 min-V", height=H_RECT)
        if ba: show(ba, "解读2 总面积750 min-V")
        else: print("[解读2] 无可行 (全部冷却不可达?)")
        write_xlsx_interps(XLSX_OUT, edge, H_RECT, area)
        write_html(HTML_OUT, edge, H_RECT, area, AREA2)
    print(f"\n[elapsed] {time.time()-t0:.1f}s")
