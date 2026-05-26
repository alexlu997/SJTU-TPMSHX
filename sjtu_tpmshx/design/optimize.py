"""warm-start 联合精修 (单模块): 从枚举/baseline 最优出发, 对连续 (l,t)
求 min-V (外形由 size_fixed_cell 确定性内定)。= ZONED-OPT Stage B 的单模块退化
(无分区梯度)。连续 l,t 内插训练节点 → 置信低于节点, 以节点最优为下界对照。"""
from __future__ import annotations
import numpy as np
from scipy.optimize import minimize

from .sizing import size_fixed_cell, Design, RHO_S

L_BOUNDS = (4.0, 8.0)        # 训练凸包 [mm]
T_BOUNDS = (0.3, 0.5)

def warm_start_joint(cases, baseline: Design, arrangement: str = "cross",
                     maxiter: int = 40, rho_s: float = RHO_S) -> Design:
    """从 baseline (topo,l,t) warm-start, Nelder-Mead 在凸包内对 (l,t) 求 min-V。
    外形每评估由 size_fixed_cell 内定。不可行/不优于 baseline → 回退 baseline。"""
    topo = baseline.topo

    def obj(x) -> float:
        l, t = float(x[0]), float(x[1])
        if not (L_BOUNDS[0] <= l <= L_BOUNDS[1]
                and T_BOUNDS[0] <= t <= T_BOUNDS[1]):
            return 1e9
        d = size_fixed_cell(cases, topo, l, t, arrangement, rho_s=rho_s)
        return d.V if d.feasible else 1e9

    res = minimize(obj, np.array([baseline.l, baseline.t]),
                   method="Nelder-Mead", bounds=[L_BOUNDS, T_BOUNDS],
                   options={"xatol": 0.05, "fatol": 1e-7, "maxiter": maxiter})
    d = size_fixed_cell(cases, topo, float(res.x[0]), float(res.x[1]),
                        arrangement, rho_s=rho_s)
    if (not d.feasible) or d.V >= baseline.V:      # 下界对照 → 回退
        return baseline
    return d
