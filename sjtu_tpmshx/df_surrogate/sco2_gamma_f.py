"""sco2_gamma_f.py — sCO2 rough-wall friction correction γ_f (production).

    cF_effective(Re_in) = γ_f(tp, Re_in) · cF_smooth_sco2(tp, L, t, Re_in)
    γ_f(tp, Re)         = Γ₀ · (Re / Re_c)^Δ          [IN-WINDOW ONLY]

Multi-fidelity anchor for the sCO2 pressure drop: the smooth-wall unit-cell
CFD closure (``sco2_df``) supplies the shape; the D-7-6 / G-7-6 heat-
exchanger experiments (sCO2–sCO2 counterflow, 2026-07) supply the amplitude
and its mild Re-slope. Decision record: DECISIONS D6 (2026-07-22) — Alex
picked the HOT side ("趋势与 CFD 一致，cold 侧趋势不对"); the six-variant
Bayesian evidence (validation/sco2_exp/gamma_f_variants.py, hot-free own
medAPE 2 %/1 % D/G, 68 % band coverage 80/84 %) is archived in
reports/sco2_exp/gamma_f_variants.csv.

SEMANTICS — read before touching:

* This is an **HX-level prediction correction**, NOT pure surface roughness:
  γ_f exceeds the air-side specimen roughness at the same geometry
  (γ_air(7/0.6) = 1.53/1.96) by ×4.0–4.6 — the anchor experiments are
  heat-exchanger cores, so manifold/entrance/instrument systematics are
  absorbed alongside SLM roughness (exam_sco2 XFLUID finding).
  ** UPDATE 2026-07-25 (iter 76, audit §13): that ×4.0–4.6 compared two γ's
  sitting on DIFFERENT smooth bases, so it conflated "base mismatch" with
  "data disagreement". The closure-free check is
  ``validation/df_refit/cf_cross_fluid.py``, which inverts cF straight from
  each fluid's raw measurements on the SAME core, same A/L/Dh, same K:
  air 430/401 vs sCO2 1522/1512 (1/m, D/G) — ×3.5/×3.8. Base mismatch is
  NOT the explanation (the two smooth bases differ by only 1.03–1.17× at the
  relevant Re), and neither is flow area: air and sCO2 use the same A_flow
  and cF ∝ A², so A cancels EXACTLY in that ratio. The gap is an
  unexplained systematic between two experiment campaigns, and γ_f currently
  absorbs all of it — see DECISIONS D9 before treating γ_f as physics.**
  Fit support
  is the 7/0.6 geometry ONLY; applying to other (L, t) rides on the
  γ-geometry-independence assumption (to be tested in the air/water phase).
* **Window discipline** (subst.v2 use-card red line): the power law is an
  interpolation over the experimental Re window. Outside the window this
  module returns 1.0 — i.e. FALLS BACK TO THE SMOOTH-WALL CLOSURE — and
  emits a one-shot warning. It never extrapolates the slope and never
  silently clamps.
* **Base-relative**: γ_f ≡ f_exp / f_cfd(sco2_df + CFD-refit K as of
  **2026-07-25**). Swapping or refitting that smooth base INVALIDATES these
  constants — ``test_sco2_gamma_f.py`` recomputes the fit from the raw
  experiment Excel against the live base and fails loudly on drift. It did
  exactly that on the 2026-07-25 base rebuild (iter 78); the constants below
  were re-derived, not the tolerance loosened.
* Kill switch: env ``TPMSHX_SCO2_GAMMA_F=0`` restores the smooth-wall
  behaviour (pre-2026-07-22), e.g. for comparing against CFD.

Uncertainty (for downstream UQ consumers): ln-space residual σln is frozen
per topology; the 68 % multiplicative prediction band is approximately
exp(±σln·t₆₈) ≈ ±6.0 % (Diamond) / ±3.7 % (Gyroid) at mid-window.
"""
from __future__ import annotations

import os
import warnings

from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

# Frozen posterior means of the hot-free fit (full precision — regenerate via
# validation/sco2_exp/gamma_f_variants.fit_gamma on the hot f_set; the
# cross-check test enforces agreement). n = fit-set size; window = the fit's
# own Re support (slightly narrower than exam_sco2's pooled exam window —
# interpolation-only discipline binds to what the FIT saw).
#
# RE-FROZEN 2026-07-25 (iter 78, ledger SCO2-F-REFIT-0725): the smooth base
# `sco2_df` was rebuilt on the corrected 2026-07-23 CFD export (20 D / 17 G
# geometries, 9799 cases — was 15/12, 7000). Because γ_f ≡ f_exp/f_cfd is
# base-relative, the constants MUST move with the base — and they moved in
# the compensating direction: dexp absorbed the pooled-m shift almost
# exactly (D 0.1262→0.1177 vs m 0.1808→0.1721), so the PRODUCT that
# production actually consumes, γ_f(Re)·cF_smooth(7,0.6,Re), is invariant to
# <=0.02 % across the whole fit window. Re_c / window / n / sig_ln are
# untouched (the EXPERIMENT did not change). Off-anchor geometries DO move
# (base −8…−13 % at Re 2e4) — that is the new CFD's information, not drift.
GAMMA_F_HOT: dict[str, dict[str, float]] = {
    "Diamond": dict(
        G0=6.8944008137665165,
        dexp=0.11774435618983282,
        Re_c=18842.643482804368,
        sig_ln=0.05948535319139833,
        re_lo=8801.07548108971,
        re_hi=40949.35902093758,
        n=51,
    ),
    "Gyroid": dict(
        G0=7.715203938698979,
        dexp=0.09208167893287889,
        Re_c=22517.82778604547,
        sig_ln=0.03630540714998968,
        re_lo=10632.405680243332,
        re_hi=48961.25289670842,
        n=44,
    ),
}

_WARNED: set[tuple[str, str]] = set()


def _enabled() -> bool:
    return os.environ.get("TPMSHX_SCO2_GAMMA_F", "1") != "0"


def gamma_f_sco2(tpms: str, Re_in: float) -> float:
    """γ_f at the run's inlet Reynolds number; 1.0 (smooth wall) off-window.

    Off-window fallback is DELIBERATE (never extrapolate the slope): the
    caller keeps the smooth-wall closure and the one-shot warning tells the
    user the prediction reverted to the pre-anchor semantics there.
    """
    if not _enabled():
        return 1.0
    p = GAMMA_F_HOT.get(tpms)
    if p is None:
        # Not an anchored topology (only Diamond/Gyroid have experiments).
        key = (str(tpms), "topo")
        if key not in _WARNED:
            _WARNED.add(key)
            warnings.warn(
                f"[sCO2 gamma_f] no experimental anchor for topology "
                f"{tpms!r} — smooth-wall cF kept (gamma_f = 1).",
                stacklevel=2)
        return 1.0
    Re = float(Re_in)
    if Re < p["re_lo"] or Re > p["re_hi"]:
        key = (tpms, "window")
        if key not in _WARNED:
            _WARNED.add(key)
            warnings.warn(
                f"[sCO2 gamma_f] {tpms}: Re_in={Re:,.0f} outside the "
                f"experimental window [{p['re_lo']:,.0f}, {p['re_hi']:,.0f}] "
                f"— falling back to the SMOOTH-WALL closure there "
                f"(gamma_f = 1; the correction never extrapolates its "
                f"slope — subst.v2 use-card discipline). Expect real "
                f"printed-part dP several times higher.",
                stacklevel=2)
        return 1.0
    return float(p["G0"] * (Re / p["Re_c"]) ** p["dexp"])


def reset_warn_registry() -> None:
    """Test hook (mirrors the pipeline warn-registry convention)."""
    _WARNED.clear()
