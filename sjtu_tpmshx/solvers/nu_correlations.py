"""Nu correlations — single source of truth for scalar + vector paths.

Replaces the previous lock-step pattern where Nu coefficients lived in BOTH
``tpms_calc._nu_diamond`` / ``_nu_gyroid`` (scalar path) AND
``sigmoid_field._nu_vec`` (vector path). After 2026-05-28 refactor (per
audit finding H1), both call sites import from here, so refitting Nu
requires editing exactly ``NU_COEFFS`` below.

API
---
``nu_from_Re(tpms, Re, eps_f, L_mm, D_h_mm)``       — scalar path, air
``nu_vec(tpms, Re_arr, L_mm, D_h_mm, *, Re_floor=10)`` — vector path, air
``nu_water_topo(tpms, Re, Pr_water)`` — PRODUCTION water (per-topology direct
                                       water-CFD fit, WATER_NU_COEFFS)
``nu_water_from_Re(tpms, Re, eps_f, L_mm, D_h_mm, Pr_water)`` — legacy Pr-sub
                                       water (cross-check / test-only)

Roughness factor
----------------
``NU_ROUGHNESS_FACTOR = 1.28`` — SLM Sa≈31 µm roughness enhancement.
Multiplies the smooth-wall Nu uniformly. See
``vault/reports/method/2026-04-28-nu-correlation-v4-3p-PL-CN.md`` for the
experimental derivation (φ_rough = ⟨Q_exp / Q_DB(Re)⟩ across 0°/30°/45°/
60°/90° print angles ≈ 1.28).

Form
----
3p pure power-law (refit 2026-04-28 on 试验记录表_整理版_v3.1.xlsx)::

    Nu_smooth = c · Pr^(1/3) · Re^a · (D_h/L)^d
    Nu        = NU_ROUGHNESS_FACTOR · Nu_smooth

Convention
----------
``Re = ρ·u·D_h / μ``      (D_h-based, single-stream u)
``eps_f = ε_full / 2``    (single-stream porosity — currently unused in Nu,
                          kept for API back-compat)
``Nu = h · D_h / k_f``    (standard, smooth wall)
"""
from __future__ import annotations

import warnings
import numpy as np

# ── Constants ────────────────────────────────────────────────────────────

Pr_AIR = 0.72
NU_ROUGHNESS_FACTOR = 1.28           # SLM Sa≈31 µm enhancement (φ_rough)
NU_RE_FIT_RANGE = (400.0, 16000.0)   # Re fit window for extrap warnings
NU_LAM_FLOOR = 4.36                  # laminar Hagen-Poiseuille limit — floor
                                     # for local-Re h_v paths (wall cells with
                                     # u→0 must not extrapolate Nu→0). Single
                                     # source for the 2D and 3D h_v builders.

# 3p PL coefficients (refit 2026-04-28; user-locked).
# Refitting Nu = edit this dict, nothing else.
NU_COEFFS = {
    'Diamond': {'c': 0.0944, 'a': 0.8273, 'd': 0.226},
    'Gyroid':  {'c': 0.126,  'a': 0.7898, 'd': 0.2409},
}

# Module-level mutable: one-shot extrap warning per (tpms, side).
# Set is a session-scoped registry; clear by importer if tests need fresh
# warnings (rare — most tests should suppress via warnings.catch_warnings).
_EXTRAP_WARNED: set[tuple[str, str]] = set()


# ── Internal ─────────────────────────────────────────────────────────────

def _smooth_nu(tpms_type, Re, L_mm, D_h_mm, *, Pr=Pr_AIR):
    """Smooth-wall Nu (no roughness factor). Vector-friendly: accepts scalar
    or ndarray Re / L_mm / D_h_mm via numpy broadcasting."""
    c = NU_COEFFS[tpms_type]
    return c['c'] * Pr ** (1/3) * Re ** c['a'] * (D_h_mm / L_mm) ** c['d']


def _warn_extrap(tpms_type, Re_min, Re_max):
    """One-shot warning per (tpms, 'lo'|'hi') when Re leaves the fit window."""
    lo, hi = NU_RE_FIT_RANGE
    for side, oob in (('lo', Re_min < lo), ('hi', Re_max > hi)):
        if oob and (tpms_type, side) not in _EXTRAP_WARNED:
            _EXTRAP_WARNED.add((tpms_type, side))
            warnings.warn(
                f"[Nu extrap] {tpms_type}: Re=[{Re_min:.0f},{Re_max:.0f}] "
                f"outside fit window [{lo:.0f},{hi:.0f}]. "
                "Suppressing further warnings for this (tpms, side).",
                stacklevel=3)


# ── Public API ───────────────────────────────────────────────────────────

def nu_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm, *, Pr=Pr_AIR):
    """Nu (air, smooth × roughness). ``eps_f`` kept for back-compat
    signature; currently unused in the Nu formula.

    Accepts scalar OR ndarray ``Re``. The scalar branch is byte-identical to
    the historical implementation (``float(Re)`` into ``_smooth_nu``); the
    array branch (2026-06-09) forwards the array straight through — same
    element-wise formula ``_smooth_nu`` already serves to ``nu_vec`` — so a
    per-cell loop and a single vectorised call give identical results. NOTE:
    no ``Re_floor`` is applied here (unlike ``nu_vec``'s floor=10); callers
    that need a floor apply their own (e.g. the LTNE h_v path floors at 1.0)."""
    del eps_f
    Re_arr = np.asarray(Re, dtype=np.float64)
    if Re_arr.ndim == 0:
        _warn_extrap(tpms_type, float(Re_arr), float(Re_arr))
        return NU_ROUGHNESS_FACTOR * _smooth_nu(
            tpms_type, float(Re_arr), L_mm, D_h_mm, Pr=Pr)
    if Re_arr.size:
        _warn_extrap(tpms_type, float(Re_arr.min()), float(Re_arr.max()))
    return NU_ROUGHNESS_FACTOR * _smooth_nu(
        tpms_type, Re_arr, L_mm, D_h_mm, Pr=Pr)


def nu_vec(tpms_type, Re, L_mm, D_h_mm, *, Re_floor=10.0, Pr=Pr_AIR):
    """Vectorised Nu. ``Re_floor=10`` matches legacy
    ``sigmoid_field._nu_vec`` behaviour (prevents Re^a blow-up at u→0).
    L_mm / D_h_mm accept scalar or ndarray broadcastable to ``Re``."""
    Re_arr = np.maximum(np.asarray(Re, dtype=np.float64), Re_floor)
    if Re_arr.size:
        _warn_extrap(tpms_type, float(Re_arr.min()), float(Re_arr.max()))
    return NU_ROUGHNESS_FACTOR * _smooth_nu(
        tpms_type, Re_arr, L_mm, D_h_mm, Pr=Pr)


def nu_water_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm, Pr_water):
    """Water-side Nu via Pr-substitution onto the air-fit correlation
    (Reynolds analogy, Dittus-Boelter / Sieder-Tate basis).

    Legacy / cross-check only — NOT the production water path. Production
    water Nu now uses ``nu_water_topo`` (per-topology direct water-CFD fit,
    ``WATER_NU_COEFFS``). This function and ``nu_water_gyroid_yan6`` (Yan
    [6] 2024) are retained for cross-check / test only.
    """
    return nu_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm) \
           * (Pr_water / Pr_AIR) ** (1/3)


# ── Topology-specific DIRECT water fits (design-tool lineage) ────────
# Single-sourced here in B1 1.1 (2026-06-12); previously a private dict in
# design/fluids.py. These are a THIRD water-Nu lineage, deliberately
# distinct from both nu_water_from_Re (Pr-substitution) above and
# tpms_calc.nu_water_gyroid_yan6 (Yan [6]): direct per-topology fits
# Nu = c·Re^a·Pr^(1/3) on water CFD, Re 100-50000. New-Gyroid
# cross-checks Yan within ±1 %; new-Diamond sits 5-12 % below the old
# borrowed-Gyroid value (Diamond finally uses its own physics).
WATER_NU_RE_RANGE = (100.0, 50000.0)
WATER_NU_COEFFS = {
    'Diamond': {'c': 0.3427, 'a': 0.6626},
    'Gyroid':  {'c': 0.4445, 'a': 0.6361},
}

# One-shot extrapolation warning per side for the water Nu fit (robustness
# 2026-06-25): the air path already warns outside its window; the water path
# previously extrapolated silently.
_WATER_NU_WARNED: set[str] = set()


def _warn_water_nu(Re_min, Re_max):
    lo, hi = WATER_NU_RE_RANGE
    for side, oob in (('lo', Re_min < lo), ('hi', Re_max > hi)):
        if oob and side not in _WATER_NU_WARNED:
            _WATER_NU_WARNED.add(side)
            warnings.warn(
                f"[water Nu extrap] Re=[{Re_min:.0f},{Re_max:.0f}] outside "
                f"water-CFD fit window [{lo:.0f},{hi:.0f}].", stacklevel=3)


def nu_water_topo(tpms_type, Re, Pr_water):
    """Topology-specific direct water Nu = c·Re^a·Pr^(1/3) (table above).
    ``np.maximum(Re, 1.0)`` floor (array-safe; identical to the design-tool
    fit's ``max(Re, 1.0)`` for scalar Re, but also works on per-cell arrays
    when the solver routes its vectorised water path through here)."""
    Re_safe = np.maximum(Re, 1.0)             # original expression (unchanged)
    _Re_arr = np.asarray(Re_safe, dtype=np.float64)
    if _Re_arr.size:
        _warn_water_nu(float(_Re_arr.min()), float(_Re_arr.max()))
    co = WATER_NU_COEFFS[tpms_type]
    return co['c'] * Re_safe ** co['a'] * Pr_water ** (1 / 3)


# ── Supercritical CO2 DIRECT fit (Phase A, far-from-critical) ────────
# Source: D-7-6 experiment (Diamond 7mm/0.6mm, sCO2 counterflow, 51 cases),
# fitted 2026-06-26. See vault report
# reports/engineering/sco2/2026-06-26-sco2-nu-correlation-construction-CN.md.
#
# Form  Nu = c·Re^a·Pr^(1/3)  (no ×1.28 roughness — the SLM roughness is
# already baked into the experimental data, same convention as water).
#
# Reduction caveat: the experiment back-computes Nu from a CONSTRUCTED wall
# temperature (mean of the two bulk streams), so Nu ∝ 1/ΔT_streams. Small-ΔT
# cases are artifact-contaminated and were filtered (ΔT_streams>10 °C, hot+cold
# merged). a≈0.75 is stable across all filter thresholds; c≈0.28 (±~10 %).
# Validated against GOLD subset; beats the GPT-5.5 baseline (0.708·Re^0.663)
# on all clean data (RMSRE 8.7 % @ΔT>15 vs 12.6 %).
#
# VALIDITY: Diamond only (single geometry — other cells extrapolate); Re∈
# [9e3, 4.1e4]; Pr≈0.8 (far-from-critical). NOT valid near the pseudocritical
# line (precooler 307 K/7.7 MPa, cp spike) — that needs a Jackson/Pitla
# property-ratio correction, out of scope for this fit.
SCO2_NU_RE_RANGE = (9000.0, 41000.0)
SCO2_NU_COEFFS = {
    'Diamond': {'c': 0.28, 'a': 0.75},
}

_SCO2_NU_WARNED: set[str] = set()


def _warn_sco2_nu(Re_min, Re_max):
    lo, hi = SCO2_NU_RE_RANGE
    for side, oob in (('lo', Re_min < lo), ('hi', Re_max > hi)):
        if oob and side not in _SCO2_NU_WARNED:
            _SCO2_NU_WARNED.add(side)
            warnings.warn(
                f"[sCO2 Nu extrap] Re=[{Re_min:.0f},{Re_max:.0f}] outside "
                f"D-7-6 fit window [{lo:.0f},{hi:.0f}].", stacklevel=3)


def nu_sco2_topo(tpms_type, Re, Pr_sco2):
    """Supercritical-CO2 Nu = c·Re^a·Pr^(1/3) (Diamond only; table above).
    Array-safe ``np.maximum(Re, 1.0)`` floor, mirroring ``nu_water_topo``.

    Raises KeyError for topologies without an sCO2 fit (only Diamond has
    D-7-6 data; do not silently borrow another topology's coefficients).
    Far-from-critical only — see SCO2_NU_COEFFS docstring."""
    if tpms_type not in SCO2_NU_COEFFS:
        raise NotImplementedError(
            f"sCO2 Nu fit only available for {sorted(SCO2_NU_COEFFS)} "
            f"(D-7-6 single-geometry experiment); {tpms_type!r} unsupported.")
    Re_safe = np.maximum(Re, 1.0)
    _Re_arr = np.asarray(Re_safe, dtype=np.float64)
    if _Re_arr.size:
        _warn_sco2_nu(float(_Re_arr.min()), float(_Re_arr.max()))
    co = SCO2_NU_COEFFS[tpms_type]
    return co['c'] * Re_safe ** co['a'] * Pr_sco2 ** (1 / 3)
