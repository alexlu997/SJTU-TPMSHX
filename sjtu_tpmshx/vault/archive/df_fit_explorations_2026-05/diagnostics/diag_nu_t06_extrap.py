"""diag_nu_t06_extrap.py — diagnose Nu underprediction at t=0.6 extrap.

User report: F7 Gyroid + F4-D Diamond predict Nu ~80 at Shanghai (L=7, t=0.6,
Re~10000), while training table for similar L at Re~10000 shows Nu ~100+.

This script:
  1. Pulls all training rows with L=7 (Diamond + Gyroid)
  2. Filters to Re ∈ [8000, 12000]
  3. Reports Nu_CFD per (t, Re) bin
  4. Computes F4-D / F7 predictions at L=7, t=0.5 (in-sample) and L=7, t=0.6 (extrap)
  5. Quantifies t-extrapolation effect on each variable (ε_f, D_h, L)

Usage:
  python -u -m sjtu_tpmshx.df_fit.diag_nu_t06_extrap
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import (
    geometry as tpms_geometry, _nu_diamond, _nu_gyroid,
    _NU_ROUGHNESS_FACTOR,
)
from df_fit.fit_nu_single_stream import load_data


def report_training(tpms: str, L_target: float = 7.0,
                     Re_lo: float = 8000.0, Re_hi: float = 12000.0):
    print(f"\n{'='*70}")
    print(f"Training table — {tpms}, L={L_target} mm, Re ∈ [{Re_lo:.0f}, {Re_hi:.0f}]")
    print(f"{'='*70}")
    d = load_data(tpms)
    sel = (d['L'] == L_target) & (d['Re_fit'] >= Re_lo) & (d['Re_fit'] <= Re_hi)
    sub = d[sel].sort_values(['t', 'Re_fit'])
    if len(sub) == 0:
        print(f"  (no training rows at L={L_target} in Re window)")
        return
    print(f"  {'t':>4}  {'ε_f':>6}  {'D_h_mm':>7}  {'Re':>6}  {'Nu_CFD':>7}")
    for _, r in sub.iterrows():
        print(f"  {r['t']:>4.2f}  {r['eps_f']:>6.4f}  {r['D_h_mm']:>7.4f}  "
              f"{r['Re_fit']:>6.0f}  {r['Nu']:>7.2f}")


def predict_compare(tpms: str, L_mm: float, Re: float):
    """Predict Nu at multiple t for fixed (L, Re)."""
    print(f"\n{'-'*70}")
    print(f"{tpms} prediction @ L={L_mm} mm, Re={Re:.0f}")
    print(f"{'-'*70}")
    print(f"  {'t':>4}  {'ε_full':>6}  {'ε_f':>6}  {'D_h_mm':>7}  "
          f"{'Nu_smooth':>9}  {'Nu×1.28':>8}  {'(extrap?)'}")
    fn = _nu_diamond if tpms == 'Diamond' else _nu_gyroid
    for t in [0.3, 0.4, 0.5, 0.6]:
        g = tpms_geometry(tpms, L_mm, t, 16.0)
        eps_full = float(g['epsilon'])
        eps_f = eps_full / 2.0
        D_h_mm = float(g['D_h']) * 1000.0
        if tpms == 'Diamond':
            Nu_smooth = fn(Re, eps_f, D_h_mm)
        else:
            Nu_smooth = fn(Re, eps_f, L_mm)
        Nu_rough = Nu_smooth * _NU_ROUGHNESS_FACTOR
        flag = '** EXTRAP **' if t == 0.6 else ''
        print(f"  {t:>4.2f}  {eps_full:>6.4f}  {eps_f:>6.4f}  {D_h_mm:>7.4f}  "
              f"{Nu_smooth:>9.2f}  {Nu_rough:>8.2f}  {flag}")


def decompose(tpms: str, L_mm: float, Re: float, t_a: float, t_b: float):
    """Show variable changes between two t."""
    print(f"\n{'-'*70}")
    print(f"{tpms} variable decomposition L={L_mm} mm, Re={Re:.0f}: "
          f"t={t_a} → t={t_b}")
    print(f"{'-'*70}")
    g_a = tpms_geometry(tpms, L_mm, t_a, 16.0)
    g_b = tpms_geometry(tpms, L_mm, t_b, 16.0)
    eps_fa = float(g_a['epsilon']) / 2
    eps_fb = float(g_b['epsilon']) / 2
    D_a = float(g_a['D_h']) * 1000
    D_b = float(g_b['D_h']) * 1000
    print(f"  ε_f:    {eps_fa:.4f} → {eps_fb:.4f}   (Δ = {(eps_fb-eps_fa)/eps_fa*100:+.2f}%)")
    print(f"  D_h:    {D_a:.4f} → {D_b:.4f} mm   (Δ = {(D_b-D_a)/D_a*100:+.2f}%)")

    # Decompose F-form contributions
    if tpms == 'Diamond':
        # Form: c · Pr^(1/3) · Re^n · ε_f^a · (D_h/Sa)^b
        # n = n0 + n1·ln(ε_f), so Re^n changes too
        from solvers.tpms_calc import Sa_mm
        Re_term_a = Re ** (0.330276 - 0.412748 * np.log(eps_fa))
        Re_term_b = Re ** (0.330276 - 0.412748 * np.log(eps_fb))
        eps_term_a = eps_fa ** 3.506017
        eps_term_b = eps_fb ** 3.506017
        ratio_a = (D_a / (1000 * Sa_mm)) ** 0.174801
        ratio_b = (D_b / (1000 * Sa_mm)) ** 0.174801
        print(f"  Re^n term:           {Re_term_a:>9.3e} → {Re_term_b:>9.3e}   "
              f"({(Re_term_b/Re_term_a-1)*100:+6.2f}%)")
        print(f"  ε_f^a term (a=3.51): {eps_term_a:>9.3e} → {eps_term_b:>9.3e}   "
              f"({(eps_term_b/eps_term_a-1)*100:+6.2f}%)")
        print(f"  (D_h/Sa)^b (b=0.17): {ratio_a:>9.3e} → {ratio_b:>9.3e}   "
              f"({(ratio_b/ratio_a-1)*100:+6.2f}%)")
    else:
        from solvers.tpms_calc import Sa_mm
        # Form: c · exp(a2·(ln Re)²) · Pr^(1/3) · ε_f^b · (L/Sa)^d
        # ε_f^(-0.608), L^0.325 — D_h does NOT enter Gyroid F7
        eps_term_a = eps_fa ** (-0.607828)
        eps_term_b = eps_fb ** (-0.607828)
        L_term = (L_mm / (1000 * Sa_mm)) ** 0.324956
        print(f"  ε_f^b term (b=-0.61): {eps_term_a:>9.3e} → {eps_term_b:>9.3e}   "
              f"({(eps_term_b/eps_term_a-1)*100:+6.2f}%)")
        print(f"  (L/Sa)^d term (constant @ L={L_mm}): {L_term:.3e}")
        print(f"  D_h NOT in Gyroid F7 — only ε_f matters when L fixed")


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("Nu t=0.6 extrapolation diagnostic")
    print("=" * 70)
    print(f"Roughness factor in code: ×{_NU_ROUGHNESS_FACTOR}")

    for tpms in ('Diamond', 'Gyroid'):
        report_training(tpms, L_target=7.0, Re_lo=8000, Re_hi=12000)
        predict_compare(tpms, L_mm=7.0, Re=10000.0)
        decompose(tpms, L_mm=7.0, Re=10000.0, t_a=0.5, t_b=0.6)


if __name__ == '__main__':
    main()
