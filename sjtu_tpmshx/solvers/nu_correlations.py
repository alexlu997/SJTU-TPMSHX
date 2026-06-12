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
``nu_water_from_Re(tpms, Re, eps_f, L_mm, D_h_mm, Pr_water)`` — Pr-sub water

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

    Not independently fitted on water data — engineering-grade estimate.
    Use ``solvers.tpms_calc.nu_water_gyroid_yan6`` for Gyroid water Re
    150-3000 where the Yan [6] 2024 direct correlation is preferred.
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


def nu_water_topo(tpms_type, Re, Pr_water):
    """Topology-specific direct water Nu = c·Re^a·Pr^(1/3) (table above).
    ``max(Re, 1.0)`` floor preserved verbatim from the design-tool fit."""
    co = WATER_NU_COEFFS[tpms_type]
    return co['c'] * max(Re, 1.0) ** co['a'] * Pr_water ** (1 / 3)
