"""
surrogate_domain.py — ConstDF-v1 surrogate training-window guard.

Provides `check_surrogate_domain_at_point` for callers that need to verify a
single (u, T, P, L, t) point lies inside the surrogate's fitted Re / L / t
window before evaluation. Out-of-window inputs raise unless `allow_extrap=True`
(or env `TPMSHX_ALLOW_EXTRAP=1`), in which case a list of reason strings is
returned for caller-side surfacing (UI watermarks, plot overlays, etc.).

This file used to live in `optimization.optimizer` but was hoisted out when the
patch-zoning optimizer was retired in favor of the continuous-field design.
"""
from __future__ import annotations
from typing import List

from sjtu_tpmshx.solvers.tpms_props import air_density, air_viscosity, geometry as _geom

# ConstDF-v1 surrogate fitted window — single source in df_surrogate/_domain.py.
from ._domain import (
    TRAIN_L as _SURROGATE_L_MM,
    TRAIN_T as _SURROGATE_T_MM,
    TRAIN_RE as _SURROGATE_RE,
)


def check_surrogate_domain_at_point(tpms_type: str,
                                    L_mm: float,
                                    t_mm: float,
                                    k_s: float,
                                    u: float,
                                    T: float,
                                    P: float = 101325.0,
                                    side: str = 'A',
                                    allow_extrap: bool = False,
                                    fluid: str = 'air') -> List[str]:
    """Point-form surrogate-domain check for the Compute path.

    Computes Re from (ρ(T,P), u, D_h(L_mm, t_mm), μ(T)) and verifies
    Re ∈ _SURROGATE_RE, L_mm ∈ _SURROGATE_L_MM, t_mm ∈ _SURROGATE_T_MM.

    Parameters
    ----------
    tpms_type : str — 'Diamond' or 'Gyroid' (used for D_h via tpms_calc.geometry)
    L_mm, t_mm : unit cell + wall [mm]
    k_s : solid conductivity [W/(m K)] (only forwarded; not bound-checked)
    u, T, P : velocity [m/s], temperature [K], pressure [Pa]
    side : 'A' or 'B' — labels the failing side in error / warning text
    allow_extrap : bool — when True (or env TPMSHX_ALLOW_EXTRAP=1), out-of-window
        inputs warn instead of raising; this function returns the reason strings
        so callers can surface them on results / plots.

    Returns
    -------
    list[str] — empty if fully inside; populated with reason strings if any
    boundary is violated. When `allow_extrap=False` and reasons exist, raises
    ValueError instead of returning.

    Raises
    ------
    ValueError when out-of-window and `allow_extrap` is False.
    """
    import os as _os
    import warnings as _w

    if _os.environ.get('TPMSHX_ALLOW_EXTRAP', '').lower() in ('1', 'true', 'yes'):
        allow_extrap = True

    # Re uses the ACTUAL fluid's ρ, μ. air/water keep the air-property path
    # (byte-identical to the historical guard — water rarely trips the window
    # and re-deriving its Re would shift the validated boundary), but sCO2 is
    # real-gas: its ρ swings ×3-4 vs air at the same (T,P), so an air-property
    # Re would be meaningless in the warning. Forward the sCO2 (T,P) props.
    if fluid == 'sco2':
        # Deferred ON PURPOSE (runtime-only upward dep): fluid_props sits
        # ABOVE df_surrogate in the import DAG (arch-b-c-e batch B) and pulls
        # CoolProp; only the sCO2 path needs it.
        from sjtu_tpmshx.solvers.fluid_props import get as _get_fluid
        _m = _get_fluid('sco2')
        rho = float(_m.rho(T, P))
        mu = float(_m.mu(T, P))
    else:
        rho = air_density(T, P)
        mu  = air_viscosity(T)
    D_h = _geom(tpms_type, L_mm, t_mm, k_s)['D_h']
    Re = rho * u * D_h / mu

    reasons: list[str] = []
    if fluid == 'sco2':
        from sjtu_tpmshx.solvers.nu_correlations import SCO2_NU_RE_RANGE
        if not SCO2_NU_RE_RANGE[0] <= Re <= SCO2_NU_RE_RANGE[1]:
            reasons.append(
                f"Fluid {side}: Re = {Re:.0f} outside sCO2 CFD Nu window "
                f"[{SCO2_NU_RE_RANGE[0]:.0f}, {SCO2_NU_RE_RANGE[1]:.0f}]."
            )
        if float(L_mm) not in {4.0, 5.0, 6.0, 7.0, 8.0}:
            reasons.append("sCO2 V1 L_cell must be an exact 4..8 mm node.")
        if float(t_mm) not in {0.3, 0.4, 0.5, 0.6}:
            reasons.append("sCO2 V1 wall thickness must be an exact 0.3..0.6 mm node.")
    elif Re < _SURROGATE_RE[0] or Re > _SURROGATE_RE[1]:
        reasons.append(
            f"Fluid {side}: Re = {Re:.0f} outside ConstDF-v1 window "
            f"[{_SURROGATE_RE[0]:.0f}, {_SURROGATE_RE[1]:.0f}] "
            f"(u={u} m/s, T={T} K, P={P:.0f} Pa, L={L_mm}mm, t={t_mm}mm)."
        )
    if fluid != 'sco2' and not (_SURROGATE_L_MM[0] <= L_mm <= _SURROGATE_L_MM[1]):
        reasons.append(
            f"L_cell = {L_mm} mm outside ConstDF-v1 range "
            f"[{_SURROGATE_L_MM[0]}, {_SURROGATE_L_MM[1]}] mm."
        )
    if fluid != 'sco2' and not (_SURROGATE_T_MM[0] <= t_mm <= _SURROGATE_T_MM[1]):
        reasons.append(
            f"Wall thickness t = {t_mm} mm outside ConstDF-v1 range "
            f"[{_SURROGATE_T_MM[0]}, {_SURROGATE_T_MM[1]}] mm."
        )

    if reasons:
        if allow_extrap:
            for r in reasons:
                _w.warn("[surrogate extrap] " + r, stacklevel=2)
        else:
            raise ValueError(" | ".join(reasons))
    return reasons
