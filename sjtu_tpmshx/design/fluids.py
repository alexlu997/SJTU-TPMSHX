"""流体分派: 按 {air, water} 返回物性与 Nu (复用 tpms_calc 闭合)。"""
from __future__ import annotations
from dataclasses import dataclass

from solvers.tpms_calc import (
    air_density, air_viscosity, air_conductivity, air_cp,
    water_density, water_viscosity, water_conductivity, water_cp,
    nu_from_Re, nu_water_gyroid_yan6,
)
from solvers.nu_correlations import NU_RE_FIT_RANGE   # air 幂律拟合 Re 窗 (400,16000)

YAN_RE_RANGE = (150.0, 3000.0)      # Yan[6] 水侧 gyroid 验证 Re 域

def nu_re_window(fluid: str):
    """该流体 Nu 关联式的验证 Re 域 (lo, hi)。域外 = 外推, 低置信。
    air → 项目幂律拟合窗; water → Yan[6] 实验域。"""
    return YAN_RE_RANGE if fluid == "water" else NU_RE_FIT_RANGE

@dataclass
class Props:
    rho: float; mu: float; k: float; cp: float; Pr: float

def fluid_props(fluid: str, T_K: float, P_Pa: float) -> Props:
    if fluid == "air":
        rho = air_density(T_K, P_Pa); mu = air_viscosity(T_K)
        k = air_conductivity(T_K);    cp = air_cp(T_K)
    elif fluid == "water":
        rho = water_density(T_K); mu = water_viscosity(T_K)
        k = water_conductivity(T_K); cp = water_cp(T_K)
    else:
        raise ValueError(f"unknown fluid {fluid!r}")
    return Props(rho, mu, k, cp, mu * cp / k)

def fluid_nu(fluid: str, topo: str, Re: float, eps_f: float,
             L_mm: float, D_h_mm: float) -> float:
    """单股 Nu。air: 项目幂律×f_rough; water: Yan[6] (Re 150–3000)。"""
    if fluid == "air":
        return nu_from_Re(topo, Re, eps_f, L_mm, D_h_mm)
    if fluid == "water":
        Pr_w = fluid_props("water", 320.0, 2e5).Pr
        return float(nu_water_gyroid_yan6(max(Re, 1.0), Pr_w))
    raise ValueError(f"unknown fluid {fluid!r}")
