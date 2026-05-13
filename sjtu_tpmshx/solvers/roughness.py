"""solvers/roughness.py — Re-dep / scalar wall-roughness correction factors
for air-side Nu and Darcy-Forchheimer friction.

Three modes:

  ``baseline``      no f-side correction; air Nu stays ×1.28 (current production).
                    For backward compat: this is what runs everywhere by default.

  ``norris_1a``     constant f × 1.46 multiplier on Brinkman + Forchheimer
                    coefficients (K /= 1.46, cF *= 1.46). The 1.46 factor is
                    pure Norris (1971) analogy from the existing ×1.28 Nu
                    multiplier:
                        Nu_r/Nu_sm = (f_r/f_sm)^0.68
                        ⇒ f_r/f_sm = 1.28^(1/0.68) ≈ 1.46
                    No new fitted parameter; no Shanghai information used.
                    Nu stays ×1.28 (unchanged).

  ``bhatti_shah_1b`` Re-dependent g(Re, ε/D_h) for BOTH f and Nu via Haaland
                    explicit Colebrook-White friction:
                        f_r/f_sm = f_haaland(Re, ε/D_h) / f_petukhov(Re)
                        Nu_r/Nu_sm = (f_r/f_sm)^0.68               (Norris)
                    Air Nu becomes Re-dependent (overrides ×1.28).
                    Single hyperparameter: ε (literature AM SLM value 50-200 μm).
                    No Shanghai fitting.

References
----------
- Bhatti & Shah 1987, Ch.4 in Kakac, Shah, Aung (eds), Handbook of Single-Phase
  Convective Heat Transfer (Wiley) — Re-dep roughness HT enhancement review.
- Norris 1971, "Some simple approximate heat-transfer correlations for
  turbulent flow in ducts with rough surfaces", ASME — n=0.68 exponent.
- Haaland 1983, "Simple and explicit formulas for the friction factor in
  turbulent pipe flow", J. Fluids Eng. — explicit Colebrook-White approx.
- Petukhov 1970, smooth-wall pipe friction.

Water-side Nu (Yan [6] 2024) ALREADY embeds AM surface roughness; do not
apply this module to water flow.
"""

from __future__ import annotations
import numpy as np


# ─── Smooth-wall friction baselines ─────────────────────────────────


def f_petukhov(Re):
    """Smooth-wall turbulent friction factor (Petukhov 1970).

    Range: Re ~ 3e3 - 5e6. Returns Darcy (Moody) f, not Fanning.
    """
    Re = np.asarray(Re, dtype=np.float64)
    return (0.790 * np.log(Re) - 1.64) ** (-2)


def f_haaland(Re, eps_over_Dh):
    """Rough-wall turbulent friction factor (Haaland 1983 explicit approx
    to Colebrook-White, <= 2 % error). Darcy f.
    """
    Re = np.asarray(Re, dtype=np.float64)
    return (1.0 / (-1.8 * np.log10(
        (eps_over_Dh / 3.7) ** 1.11 + 6.9 / Re))) ** 2


# ─── Public API ─────────────────────────────────────────────────────


def f_enhancement(Re, mode='baseline', eps_um=None, D_h_mm=None):
    """Roughness enhancement factor for friction: f_rough / f_smooth.

    Returns 1.0 for ``baseline`` so default state preserves prior behavior.
    """
    if mode == 'baseline':
        return 1.0
    if mode == 'norris_1a':
        return 1.46
    if mode == 'bhatti_shah_1b':
        if eps_um is None or D_h_mm is None:
            raise ValueError("bhatti_shah_1b needs eps_um + D_h_mm")
        eod = (eps_um * 1e-3) / D_h_mm                  # both in mm now
        return float(f_haaland(Re, eod) / f_petukhov(Re))
    raise ValueError(f"unknown roughness mode {mode!r}")


def nu_extra_factor(Re, mode='baseline', eps_um=None, D_h_mm=None):
    """Multiplier ABOVE the existing ×1.28 baseline Nu in tpms_calc.

    Current `nu_from_Re` already returns ×1.28 × Nu_smooth for air. This
    helper returns the factor required ON TOP of that to reach the
    consistency target. ``baseline`` and ``norris_1a`` return 1.0 (no extra);
    ``bhatti_shah_1b`` returns g_Nu(Re,ε)/1.28 to override.
    """
    if mode in ('baseline', 'norris_1a'):
        return 1.0
    if mode == 'bhatti_shah_1b':
        f_gain = f_enhancement(Re, mode, eps_um, D_h_mm)
        g_nu = f_gain ** 0.68
        return float(g_nu / 1.28)
    raise ValueError(f"unknown roughness mode {mode!r}")


def apply_to_K_cF(K, cF, f_gain):
    """Apply friction enhancement to Darcy-Forchheimer K, cF arrays.

    Brinkman term μ/K scales linearly with f → K_new = K / f_gain.
    Forchheimer term cF ρ |v| v scales linearly with f → cF_new = cF × f_gain.
    """
    return K / float(f_gain), cF * float(f_gain)


def resolve_mode_from_env(default='baseline'):
    """Read mode + eps_um from environment for ad-hoc validation sweeps.

    Env vars:
      TPMSHX_ROUGH_MODE   = baseline | norris_1a | bhatti_shah_1b
      TPMSHX_ROUGH_EPS_UM = ε in micrometres (only used by bhatti_shah_1b)
    """
    import os
    mode = os.environ.get('TPMSHX_ROUGH_MODE', default).strip().lower()
    eps_um = float(os.environ.get('TPMSHX_ROUGH_EPS_UM', '100'))
    return mode, eps_um
