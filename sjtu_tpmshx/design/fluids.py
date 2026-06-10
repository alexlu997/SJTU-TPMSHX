"""流体分派: 按 {air, water} 返回物性与 Nu (复用 tpms_calc 闭合)。"""
from __future__ import annotations
from dataclasses import dataclass

from solvers.tpms_calc import (
    air_density, air_viscosity, air_conductivity, air_cp,
    water_density, water_viscosity, water_conductivity, water_cp,
    nu_from_Re,
)
from solvers.nu_correlations import NU_RE_FIT_RANGE   # air 幂律拟合 Re 窗 (400,16000)

WATER_NU_RE_RANGE = (100.0, 50000.0)   # 拓扑专属水侧 Nu 关联式验证 Re 域 (新式)
YAN_RE_RANGE = WATER_NU_RE_RANGE        # 向后兼容别名 (旧名, 现已非 Yan)

# 拓扑专属水侧 Nu = c·Re^a·Pr^(1/3)。取代旧的"两拓扑共用 Yan[6] Gyroid 式
# (0.471·Re^0.627, Diamond 借用)"; 现各拓扑独立。新 Gyroid 系数与 Yan 互验 ±1%,
# 新 Diamond 比借用值低 5–12% (Diamond 终于用自身物性而非借 Gyroid)。
WATER_NU_COEFFS = {
    'Diamond': {'c': 0.3427, 'a': 0.6626},
    'Gyroid':  {'c': 0.4445, 'a': 0.6361},
}

def nu_re_window(fluid: str):
    """该流体 Nu 关联式的验证 Re 域 (lo, hi)。域外 = 外推, 低置信。
    air → 项目幂律拟合窗 (400,16000); water → 拓扑专属新式 (100,50000)。"""
    return WATER_NU_RE_RANGE if fluid == "water" else NU_RE_FIT_RANGE

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
    """单股 Nu。air: 项目幂律×f_rough; water: 拓扑专属 c·Re^a·Pr^(1/3) (Re 100–50000)。"""
    if fluid == "air":
        return nu_from_Re(topo, Re, eps_f, L_mm, D_h_mm)
    if fluid == "water":
        Pr_w = fluid_props("water", 320.0, 2e5).Pr
        co = WATER_NU_COEFFS[topo]
        return co['c'] * max(Re, 1.0) ** co['a'] * Pr_w ** (1 / 3)
    raise ValueError(f"unknown fluid {fluid!r}")
