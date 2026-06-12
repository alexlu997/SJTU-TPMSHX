"""流体分派 (design 工具薄适配层, B1 1.1 单源化后)。

物性原语与水侧拓扑专属 Nu 系数现单源于 solvers 层
(``solvers.fluid_props.FLUIDS`` 注册表 + ``solvers.nu_correlations``);
本模块只保留 design 工具的便捷接口与历史别名, 不再自带任何数据。
"""
from __future__ import annotations
from dataclasses import dataclass

from solvers import fluid_props as _registry
from solvers.tpms_calc import nu_from_Re
from solvers.nu_correlations import (
    NU_RE_FIT_RANGE,        # air 幂律拟合 Re 窗 (400,16000)
    WATER_NU_RE_RANGE,      # 拓扑专属水侧 Nu 关联式验证 Re 域 (新式)
    WATER_NU_COEFFS,        # 拓扑专属水侧系数 (单源 re-export)
    nu_water_topo,
)

YAN_RE_RANGE = WATER_NU_RE_RANGE        # 向后兼容别名 (旧名, 现已非 Yan)


def nu_re_window(fluid: str):
    """该流体 Nu 关联式的验证 Re 域 (lo, hi)。域外 = 外推, 低置信。
    air → 项目幂律拟合窗 (400,16000); water → 拓扑专属新式 (100,50000)。"""
    return WATER_NU_RE_RANGE if fluid == "water" else NU_RE_FIT_RANGE


@dataclass
class Props:
    rho: float; mu: float; k: float; cp: float; Pr: float


def fluid_props(fluid: str, T_K: float, P_Pa: float) -> Props:
    m = _registry.get(fluid)            # raises ValueError on unknown
    rho = m.rho(T_K, P_Pa) if m.compressible else m.rho(T_K)
    mu = m.mu(T_K); k = m.k(T_K); cp = m.cp(T_K)
    return Props(rho, mu, k, cp, mu * cp / k)


def fluid_nu(fluid: str, topo: str, Re: float, eps_f: float,
             L_mm: float, D_h_mm: float) -> float:
    """单股 Nu。air: 项目幂律×f_rough; water: 拓扑专属 c·Re^a·Pr^(1/3) (Re 100–50000)。"""
    if fluid == "air":
        return nu_from_Re(topo, Re, eps_f, L_mm, D_h_mm)
    if fluid == "water":
        Pr_w = fluid_props("water", 320.0, 2e5).Pr
        return nu_water_topo(topo, Re, Pr_w)
    raise ValueError(f"unknown fluid {fluid!r}")
