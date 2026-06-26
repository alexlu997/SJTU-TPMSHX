"""Supercritical CO2 transport/thermo properties via CoolProp (Span-Wagner).

Phase A backend for the ``'sco2'`` fluid (2026-06-26). Unlike air (ideal-gas,
T-only) and water (incompressible, T-only), sCO2 properties depend on BOTH
temperature and pressure — strongly so near the pseudocritical line. All
functions therefore take ``(T_K, P_Pa)``.

CoolProp's CO2 model is the Span-Wagner reference EOS; equilibrium properties
(ρ, cp, h) match REFPROP exactly, transport (μ, k) within ~1 %
(see vault [[reference_coolprop_refprop_co2]]).

Far-from-critical use is robust; near the critical point (304 K / 7.38 MPa)
the property derivatives are stiff — that regime is Phase C, not Phase A.
"""
from __future__ import annotations

from functools import lru_cache

try:
    from CoolProp.CoolProp import PropsSI as _PropsSI
    _HAVE_COOLPROP = True
except Exception:                       # pragma: no cover - import guard
    _HAVE_COOLPROP = False

    def _PropsSI(*_a, **_k):
        raise ImportError(
            "CoolProp is required for the sCO2 fluid but is not installed. "
            "`pip install CoolProp` (see requirements.txt).")


_FLUID = "CO2"


@lru_cache(maxsize=4096)
def _prop(key: str, T_K: float, P_Pa: float) -> float:
    """Cached scalar CoolProp query. CO2 EOS calls are ~µs but repeat heavily
    across solver iterations at near-identical (T,P); cache keeps it cheap."""
    return float(_PropsSI(key, "T", float(T_K), "P", float(P_Pa), _FLUID))


def sco2_density(T_K: float, P_Pa: float) -> float:
    """ρ [kg/m³] = ρ(T, P) — real-gas, NOT ideal."""
    return _prop("D", T_K, P_Pa)


def sco2_cp(T_K: float, P_Pa: float) -> float:
    """Isobaric specific heat cp [J/(kg·K)] = cp(T, P)."""
    return _prop("C", T_K, P_Pa)


def sco2_viscosity(T_K: float, P_Pa: float) -> float:
    """Dynamic viscosity μ [Pa·s] = μ(T, P)."""
    return _prop("V", T_K, P_Pa)


def sco2_conductivity(T_K: float, P_Pa: float) -> float:
    """Thermal conductivity k [W/(m·K)] = k(T, P)."""
    return _prop("L", T_K, P_Pa)


def sco2_enthalpy(T_K: float, P_Pa: float) -> float:
    """Specific enthalpy h [J/kg] = h(T, P). Used for enthalpy-based duty
    Q = ṁ·Δh (sCO2 cp is not constant across a HX temperature span)."""
    return _prop("H", T_K, P_Pa)
