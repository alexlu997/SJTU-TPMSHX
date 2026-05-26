"""枚举选型: 遍历 {拓扑×l×t}, 各跑 size_fixed_cell, Pareto-tag。"""
from __future__ import annotations
from .sizing import size_fixed_cell, Design, RHO_S

# t=0.6 超出闭合训练域 {0.3,0.4,0.5} (外推, 低置信; K 外插可能触底钳值), 但按需纳入默认枚举。
NODES = {"topo": ["Diamond", "Gyroid"],
         "l": [4.0, 5.0, 6.0, 8.0], "t": [0.3, 0.4, 0.5, 0.6]}

def enumerate_select(cases, arrangement="cross", nodes=None, rho_s=RHO_S):
    nd = nodes or NODES
    feasible: list[Design] = []
    for topo in nd["topo"]:
        for l in nd["l"]:
            for t in nd["t"]:
                d = size_fixed_cell(cases, topo, l, t, arrangement, rho_s=rho_s)
                if d.feasible:
                    feasible.append(d)
    best = min(feasible, key=lambda d: d.V) if feasible else None
    return feasible, best

def pareto_tags(feasible) -> dict:
    """对每件标记其所属"某目标最优"tag。"""
    tags: dict = {}
    if not feasible:
        return tags
    for key, name in [(lambda d: d.V, "min-V"),
                      (lambda d: d.weight, "min-wt"),
                      (lambda d: d.dP_hot_max, "min-dP")]:
        b = min(feasible, key=key)
        tags.setdefault(id(b), []).append(name)
    return tags
