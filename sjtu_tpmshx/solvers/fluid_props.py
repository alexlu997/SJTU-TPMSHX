"""Single source of truth for per-fluid transport properties + Nu dispatch.

Adding a fluid = add one FLUIDS entry. Shim consumers in
``runs/run_calculation{,_3d}.py`` keep their own dict/tuple packing, Prandtl
formula and laminar-Nu floor — this module only selects the per-fluid
*primitives* (which rho/cp/mu/k/nu function to use), collapsing the scattered
``if fluid == 'water': ... else: ...`` branches into one place.

Behavior contract (must stay byte-identical to the old inline dispatch):
  * air.rho == tpms_calc.air_density (P defaults to 101325 like the old lambda)
  * water.rho ignores P (incompressible), like ``lambda T, P=None: water_density(T)``
  * air.nu ignores Pr → tpms_calc.nu_from_Re uses its built-in Pr_AIR default
  * water.nu forwards the caller-computed Pr to tpms_calc.nu_water_from_Re
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import tpms_calc


def _nu_air(tpms_type, Re, eps_f, L_mm, D_h_mm, Pr=None):
    # Air uses nu_from_Re's built-in Pr default (Pr_AIR); any Pr passed in is
    # ignored, matching the air branch in run_calculation{,_3d}.
    return tpms_calc.nu_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm)


def _nu_water(tpms_type, Re, eps_f, L_mm, D_h_mm, Pr):
    return tpms_calc.nu_water_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm, Pr)


@dataclass(frozen=True)
class FluidModel:
    name: str
    compressible: bool
    rho: Callable    # (T[, P]) -> density [kg/m^3]
    cp: Callable     # (T) -> specific heat [J/kg/K]
    mu: Callable     # (T) -> dynamic viscosity [Pa.s]
    k: Callable      # (T) -> thermal conductivity [W/m/K]
    nu: Callable     # (tpms, Re, eps_f, L_mm, D_h_mm, Pr) -> Nu (pre-floor)
    # True when the fluid's Nu/D-F closure was fitted on AM (SLM) data and
    # therefore already CONTAINS surface roughness — the roughness.py
    # multipliers must NOT be applied on top (double-count). Water's
    # Yan [6] 2024 correlation embeds it; air's closure takes the
    # env-gated roughness modes.
    embeds_roughness: bool = False


FLUIDS = {
    'air': FluidModel(
        name='air', compressible=True,
        rho=tpms_calc.air_density,        # (T, P=101325) -> rho
        cp=tpms_calc.air_cp,
        mu=tpms_calc.air_viscosity,
        k=tpms_calc.air_conductivity,
        nu=_nu_air,
        embeds_roughness=False,
    ),
    'water': FluidModel(
        name='water', compressible=False,
        rho=lambda T, P=None: tpms_calc.water_density(T),   # incompressible: P ignored
        cp=tpms_calc.water_cp,
        mu=tpms_calc.water_viscosity,
        k=tpms_calc.water_conductivity,
        nu=_nu_water,
        embeds_roughness=True,
    ),
}


def get(fluid: str) -> FluidModel:
    """Return the FluidModel for ``fluid`` ('air' | 'water'), case-insensitive."""
    try:
        return FLUIDS[fluid.strip().lower()]
    except (KeyError, AttributeError):
        raise ValueError(f"unknown fluid {fluid!r}; known: {sorted(FLUIDS)}")


def flow_model(fluid: str) -> str:
    """SIMPLE-solver fluid_type string for ``fluid``:
    'ideal_gas' (compressible) or 'incompressible'."""
    return 'ideal_gas' if get(fluid).compressible else 'incompressible'
