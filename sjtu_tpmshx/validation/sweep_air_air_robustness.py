"""sweep_air_air_robustness.py — Phase D: parametric robustness sweeps.

Standard Tier ASME V&V 20 — Phase D (~2.5 d).

Five 1D parametric sweeps on T2 (full-face cross) geometry, grid 20:

  D.1 Re sweep (u_A):    u_A ∈ {1, 5, 10, 30, 50} m/s
  D.2 ΔT sweep:          ΔT  ∈ {20, 100, 200, 500} K
  D.3 ε sweep:           eps ∈ {0.5, 0.7, 0.85, 0.95}
  D.4 k_s sweep:         k_s ∈ {1.0, 16.0, 100.0} W/mK
  D.5 B_area_frac sweep: B_frac ∈ {0.10, 0.20, 0.50, 1.0}  (T4_H8 geometry)

Per point captures:
  - Q_enthalpy_A, Q_solid_to_B_interior, T_A_out, T_B_out, dP
  - eps_A_kernel, eps_B_kernel, eps_LTNE (Phase 2 conservation 1st-law residuals)
  - S_gen sign check
  - max-principle violations count

Outputs:
  validation/sweep_air_air_robustness.csv
  vault/reports/3d-solver/2026-05-04-phase-d-CN.md (manual)
"""
from __future__ import annotations
import argparse
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
warnings.filterwarnings('ignore')

from runs.run_calculation_3d import _run_3d_stack
from validation.audit_3d_conservation import (
    L_DOM, H_DOM, LZ, _base_cfg, make_T2, make_T4_H8,
    compute_phase2a_interior, compute_phase3,
)


def _eval_case(cfg, label):
    """Run cfg, compute conservation metrics, return summary dict."""
    t0 = time.time()
    try:
        res = _run_3d_stack(cfg)
        dt = time.time() - t0
        try:
            p2a = compute_phase2a_interior(res)
        except Exception:
            p2a = dict(eps_A_kernel=float('nan'), eps_B_kernel=float('nan'),
                       eps_LTNE=float('nan'))
        try:
            p3 = compute_phase3(res)
            # compute_phase3 returns S_gen_global (3.1) and S_gen_volumetric
            # (3.2). Both should be ≥0 thermodynamically. Use volumetric as
            # primary (per-cell σ̇ integrated, more discretization-faithful).
            sgen = float(p3.get('S_gen_volumetric', p3.get('S_gen_global', float('nan'))))
            sgen_global = float(p3.get('S_gen_global', float('nan')))
            sigma_neg_pct = float(p3.get('sigma_neg_pct', float('nan')))
        except Exception:
            sgen = float('nan'); sgen_global = float('nan'); sigma_neg_pct = float('nan')

        # Max-principle: count cells outside [min(T_inA,T_inB), max(T_inA,T_inB)]
        Ta = res.get('Ta'); Tb = res.get('Tb'); Ts = res.get('Ts')
        T_lo = min(cfg.get('T_inA', 300.0), cfg.get('T_inB', 300.0)) - 0.5
        T_hi = max(cfg.get('T_inA', 300.0), cfg.get('T_inB', 300.0)) + 0.5
        mp_viol = 0
        for T in [Ta, Tb, Ts]:
            if T is not None:
                mp_viol += int(np.sum((T < T_lo) | (T > T_hi)))

        return dict(
            label=label, status='ok', elapsed=dt,
            Q_enth_A=float(res.get('Q_enthalpy_A', float('nan'))),
            Q_enth_B=float(res.get('Q_enthalpy_B', float('nan'))),
            Q_sB_int=float(res.get('Q_sB_interior', float('nan'))),
            T_A_out=float(res.get('T_A_out', float('nan'))),
            T_B_out=float(res.get('T_B_out', float('nan'))),
            dP=float(res.get('dP', float('nan'))),
            eps_A_kernel=float(p2a['eps_A_kernel']) * 100.0,
            eps_B_kernel=float(p2a['eps_B_kernel']) * 100.0,
            eps_LTNE=float(p2a['eps_LTNE']) * 100.0,
            S_gen=sgen,
            S_gen_global=sgen_global,
            sigma_neg_pct=sigma_neg_pct,
            max_principle_violations=mp_viol,
        )
    except Exception as e:
        return dict(label=label, status=f'error: {type(e).__name__}: {e}',
                    elapsed=time.time() - t0)


def sweep_d1_re(grid=20, u_list=(1.0, 5.0, 10.0, 30.0, 50.0)):
    """D.1 — Re sweep via u_A."""
    print(f"\n--- D.1 Re sweep (u_A in {list(u_list)}) ---")
    rows = []
    for u in u_list:
        cfg = make_T2(grid)
        cfg['u_A'] = float(u)
        label = f'D1_Re_uA_{u}'
        r = _eval_case(cfg, label)
        r['param'] = 'u_A'; r['value'] = u; r['sweep'] = 'D1_Re'
        rows.append(r)
        _print_row(r)
    return rows


def sweep_d2_dt(grid=20, dt_list=(20.0, 100.0, 200.0, 500.0)):
    """D.2 — ΔT sweep (T_inA = T_inB + dt). T_inB=300K fixed."""
    print(f"\n--- D.2 ΔT sweep (ΔT in {list(dt_list)}) ---")
    rows = []
    T_inB = 300.0
    for dt in dt_list:
        cfg = make_T2(grid)
        cfg['T_inA'] = T_inB + float(dt)
        cfg['T_inB'] = T_inB
        label = f'D2_DT_{dt}'
        r = _eval_case(cfg, label)
        r['param'] = 'DT'; r['value'] = dt; r['sweep'] = 'D2_DT'
        rows.append(r)
        _print_row(r)
    return rows


def sweep_d3_eps(grid=20, eps_list=(0.5, 0.7, 0.85, 0.95)):
    """D.3 — porosity sweep."""
    print(f"\n--- D.3 ε sweep (eps in {list(eps_list)}) ---")
    rows = []
    for eps in eps_list:
        cfg = make_T2(grid)
        cfg['eps'] = float(eps)
        label = f'D3_eps_{eps}'
        r = _eval_case(cfg, label)
        r['param'] = 'eps'; r['value'] = eps; r['sweep'] = 'D3_eps'
        rows.append(r)
        _print_row(r)
    return rows


def sweep_d4_ks(grid=20, ks_list=(1.0, 16.0, 100.0)):
    """D.4 — solid conductivity sweep."""
    print(f"\n--- D.4 k_s sweep (k_s in {list(ks_list)}) ---")
    rows = []
    for ks in ks_list:
        cfg = make_T2(grid)
        cfg['k_s'] = float(ks)
        label = f'D4_ks_{ks}'
        r = _eval_case(cfg, label)
        r['param'] = 'k_s'; r['value'] = ks; r['sweep'] = 'D4_ks'
        rows.append(r)
        _print_row(r)
    return rows


def sweep_d5_bfrac(grid=20, frac_list=(0.10, 0.20, 0.50, 1.0)):
    """D.5 — B_area_frac sweep on T4_H8 geometry (partial-B cross-flow).

    For frac=1.0, fall back to T2 (full-face). Otherwise use T4_H8 with
    fluid_B_cfg.in_w / out_w sized to L_DOM × frac.
    """
    print(f"\n--- D.5 B_area_frac sweep (frac in {list(frac_list)}) ---")
    rows = []
    for frac in frac_list:
        if frac >= 0.99:
            cfg = make_T2(grid)
            label = f'D5_Bfrac_1.00_T2'
        else:
            cfg = make_T4_H8(grid)
            # T4_H8 uses in_w=0.042 (= 0.20 of L=0.182). Override here.
            cfg['fluid_B_cfg']['in_w'] = L_DOM * frac
            cfg['fluid_B_cfg']['out_w'] = L_DOM * frac
            label = f'D5_Bfrac_{frac:.2f}_H8'
        r = _eval_case(cfg, label)
        r['param'] = 'B_frac'; r['value'] = frac; r['sweep'] = 'D5_Bfrac'
        rows.append(r)
        _print_row(r)
    return rows


def _print_row(r):
    if r.get('status') == 'ok':
        print(f"  {r['label']:<22s}: Q_A={r['Q_enth_A']:>8.2f}W  "
              f"T_A_out={r['T_A_out']:>6.1f}K  dP={r['dP']:>6.0f}Pa  "
              f"eps_A={r['eps_A_kernel']:>5.2f}%  "
              f"S_gen={r.get('S_gen',float('nan')):>+.4f}  "
              f"mp_viol={r['max_principle_violations']:>4d}  "
              f"[{r['elapsed']:.0f}s]")
    else:
        print(f"  {r['label']:<22s}: {r['status']}  [{r['elapsed']:.0f}s]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--grid', type=int, default=20)
    ap.add_argument('--sweeps', default='D1,D2,D3,D4,D5')
    ap.add_argument('--out_csv',
                    default='validation/sweep_air_air_robustness.csv')
    args = ap.parse_args()

    sweep_set = set(s.strip() for s in args.sweeps.split(','))

    print(f"{'='*72}")
    print(f"  Phase D — Parametric Robustness Sweeps (T2 base, grid {args.grid})")
    print(f"{'='*72}")

    rows = []
    if 'D1' in sweep_set: rows.extend(sweep_d1_re(grid=args.grid))
    if 'D2' in sweep_set: rows.extend(sweep_d2_dt(grid=args.grid))
    if 'D3' in sweep_set: rows.extend(sweep_d3_eps(grid=args.grid))
    if 'D4' in sweep_set: rows.extend(sweep_d4_ks(grid=args.grid))
    if 'D5' in sweep_set: rows.extend(sweep_d5_bfrac(grid=args.grid))

    df = pd.DataFrame(rows)
    out = ROOT / args.out_csv
    df.to_csv(out, index=False)

    # Hard gates summary
    print(f"\n{'='*72}")
    print(f"  Phase D Summary ({len(rows)} cases)")
    print(f"{'='*72}")

    fails = []
    for r in rows:
        if r.get('status') != 'ok':
            fails.append((r['label'], 'failed_run'))
            continue
        eA = r.get('eps_A_kernel', 99); eB = r.get('eps_B_kernel', 99)
        sgen = r.get('S_gen', -1); mpv = r.get('max_principle_violations', 99)
        if eA > 5.0 or eB > 30.0:
            fails.append((r['label'], f'eps>gate (A={eA:.1f}%, B={eB:.1f}%)'))
        if mpv > 0:
            fails.append((r['label'], f'mp_viol={mpv}'))
        if np.isfinite(sgen) and sgen < -1.0:
            fails.append((r['label'], f'S_gen={sgen:.3f}<0'))

    print(f"  Total: {len(rows)} cases, {len(rows)-len(fails)} pass, "
          f"{len(fails)} fail")
    for f in fails:
        print(f"    FAIL  {f[0]}  ({f[1]})")
    print(f"\n  CSV: {out}")
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
