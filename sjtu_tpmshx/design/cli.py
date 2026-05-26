"""快速设计 CLI: auto (枚举选胞元) / fixed (指定胞元只定外形)。"""
from __future__ import annotations
import argparse, sys
import pandas as pd

from .cases import load_cases
from .sizing import size_fixed_cell
from .select import enumerate_select, pareto_tags

def _parse_cell(s):           # "Diamond,7,0.5"
    topo, l, t = s.split(","); return topo, float(l), float(t)

def _parse_nodes(s):          # "Diamond,Gyroid:6,7:0.4,0.5"
    topo, ls, ts = s.split(":")
    return {"topo": topo.split(","),
            "l": [float(x) for x in ls.split(",")],
            "t": [float(x) for x in ts.split(",")]}

def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TPMS 快速设计 (单模块)")
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--mode", choices=["auto", "fixed"], default="auto",
                    help="fixed=baseline(固定 l,t); auto=优化(放开 l,t 枚举)")
    ap.add_argument("--cell", help="fixed 模式: topo,l,t")
    ap.add_argument("--nodes", help="auto 模式: topo:l:t 列表")
    ap.add_argument("--arrangement", choices=["cross","counter"], default="cross")
    ap.add_argument("--refine", action="store_true",
                    help="auto 后对最优件做 warm-start 联合精修 (连续 l,t)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    cases = load_cases(a.xlsx)

    rows = []
    if a.mode == "fixed":
        topo, l, t = _parse_cell(a.cell)
        d = size_fixed_cell(cases, topo, l, t, a.arrangement)
        cand, tags = [d] if d.feasible else [], {}
    else:
        nodes = _parse_nodes(a.nodes) if a.nodes else None
        cand, best = enumerate_select(cases, a.arrangement, nodes)
        if a.refine and best is not None:           # Stage B warm-start 精修
            from .optimize import warm_start_joint
            ref = warm_start_joint(cases, best, a.arrangement)
            if ref is not best:
                cand.append(ref)
        tags = pareto_tags(cand)
    for d in cand:
        rows.append(dict(topo=d.topo, l=d.l, t=d.t,
                         W_mm=d.s*1e3, H_mm=d.s*1e3, Lx_mm=d.Lx*1e3,
                         V_L=d.V*1e3, weight_kg=d.weight,
                         dP_hot=d.dP_hot_max, dP_cold=d.dP_cold_max,
                         T_out_hot_max=d.T_out_hot_max,
                         tags=",".join(tags.get(id(d), []))))
    if not rows:
        print("INFEASIBLE: 无单模块可行件 (≤450mm)", file=sys.stderr)
        return 0
    df = pd.DataFrame(rows).sort_values("V_L")
    df.to_excel(a.out, index=False)
    print(df.to_string(index=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(run())
