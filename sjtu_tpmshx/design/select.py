"""枚举选型: 遍历 {拓扑×l×t}, 各跑 size_fixed_cell, Pareto-tag。"""
from __future__ import annotations
from .sizing import size_fixed_cell, Design, RHO_S

# t=0.6 超出闭合训练域 {0.3,0.4,0.5} (外推, 低置信; K 外插可能触底钳值), 但按需纳入默认枚举。
NODES = {"topo": ["Diamond", "Gyroid"],
         "l": [4.0, 5.0, 6.0, 8.0], "t": [0.3, 0.4, 0.5, 0.6]}

def enumerate_select(cases, arrangement="cross", nodes=None, rho_s=RHO_S, n_jobs=1):
    """枚举 {拓扑×l×t}, 各跑 size_fixed_cell, 取可行件 + min-V best。
    候选彼此独立 → n_jobs!=1 时用 joblib(loky 进程, 绕 GIL)跨候选并行
    (size_fixed_cell 为顶层函数, 可 pickle); n_jobs=1 走串行(确定性/测试)。
    结果顺序按 combos 不变, 故并行与串行 feasible/best 一致。"""
    nd = nodes or NODES
    combos = [(topo, l, t) for topo in nd["topo"]
              for l in nd["l"] for t in nd["t"]]
    if n_jobs == 1 or len(combos) <= 1:
        results = [size_fixed_cell(cases, topo, l, t, arrangement, rho_s=rho_s)
                   for topo, l, t in combos]
    else:
        from joblib import Parallel, delayed
        results = Parallel(n_jobs=n_jobs, backend="loky")(
            delayed(size_fixed_cell)(cases, topo, l, t, arrangement, rho_s=rho_s)
            for topo, l, t in combos)
    feasible: list[Design] = [d for d in results if d.feasible]
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
