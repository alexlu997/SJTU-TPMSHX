"""
Phase 0 驱动：扫偏移 δ，量 ε_A/ε_B/A0/D_h/t/连通性，出 CSV + 闸门判定。

纯几何，无 CFD。用法：python -u runs/asym_geometry_scan.py
计划：vault/reports/engineering/2026-06-05-asym-porosity-phase0-PLAN-CN.md
"""
import sys
import csv
from pathlib import Path

import numpy as np

# 包根入 sys.path（runs/ 脚本惯例）：parents[1] = sjtu_tpmshx/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solvers.tpms_geometry import _phi_grid, _C_from_tL, compute_geometry
from solvers.asym_geometry import (
    eps_sides, a0_sides, dh_sides, wall_thickness, percolates_z, find_delta_max,
)

N = 128
CASES = [
    ('Diamond', 5.0, 0.4),
    ('Gyroid', 5.0, 0.4),
]
WALL_FLOOR_M = 0.3e-3   # 本项目水密壁厚地板
OUT_CSV = (Path(__file__).resolve().parents[1] / "runs" / "_out"
           / "asym_geom_scan_2026-06-05.csv")


def scan_one(tpms, L_mm, t_mm):
    phi = _phi_grid(tpms, N)
    L_m = L_mm / 1000.0
    C = _C_from_tL(tpms, t_mm / L_mm)
    phimax = float(np.max(np.abs(phi)))
    dmax = find_delta_max(phi, C, L_m, N, wall_floor_m=WALL_FLOOR_M)
    deltas = np.linspace(0.0, min(dmax * 1.15, phimax), 41)
    rows = []
    for d in deltas:
        eps_A, eps_B, eps = eps_sides(phi, C, d)
        A0_A, A0_B = a0_sides(phi, C, d, L_m, N)
        Dh_A, Dh_B = dh_sides(phi, C, d, L_m, N)
        t = wall_thickness(phi, C, d, L_m, N)
        pA = percolates_z(phi < (d - C))
        pB = percolates_z(phi > (d + C))
        r = eps_A / eps_B if eps_B > 1e-9 else float('inf')
        rows.append(dict(tpms=tpms, L_mm=L_mm, t_mm=t_mm, delta=float(d), C=C,
                         eps_A=eps_A, eps_B=eps_B, eps=eps, r=r,
                         A0_A=A0_A, A0_B=A0_B, Dh_A=Dh_A, Dh_B=Dh_B,
                         t_phys_mm=t * 1000.0, perc_A=pA, perc_B=pB,
                         feasible=bool(pA and pB and t >= WALL_FLOOR_M)))
    return rows, dmax


def main():
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    all_rows = []
    summary = []
    for tpms, L, t in CASES:
        rows, dmax = scan_one(tpms, L, t)
        all_rows += rows
        feas = [x for x in rows if x['feasible']]
        r_max = max((x['r'] for x in feas), default=0.0)
        e0, t0 = rows[0]['eps'], rows[0]['t_phys_mm']
        last = feas[-1] if feas else rows[0]
        eps_drift = abs(last['eps'] - e0) / e0 * 100
        t_drift = abs(last['t_phys_mm'] - t0) / t0 * 100
        # r_healthy = 工作点 r（壁厚漂 <=15%），避开 pinch 处 eps_B->0 把 r_max 抬虚
        healthy = [x for x in feas if abs(x['t_phys_mm'] - t0) / t0 <= 0.15]
        r_healthy = max((x['r'] for x in healthy), default=0.0)
        ref = compute_geometry(tpms, L, t, N)
        anchor_ok = abs(rows[0]['A0_A'] - ref['A_0']) / ref['A_0'] < 0.03
        summary.append(dict(tpms=tpms, dmax=dmax, r_max=r_max, r_healthy=r_healthy,
                            eps_drift_pct=eps_drift, t_drift_pct=t_drift,
                            anchor_ok=anchor_ok))
    with OUT_CSV.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        w.writerows(all_rows)
    print(f"[CSV] {OUT_CSV}  ({len(all_rows)} rows)")
    print("\n=== Phase 0 GATE (r_healthy = r @ wall-drift <=15%, honest) ===")
    for s in summary:
        # 闸门按 r_healthy（诚实工作点），非 pinch 处虚高的 r_max
        verdict = "PASS" if (s['r_healthy'] >= 2.0 and s['anchor_ok']) else "HOLD"
        print(f"  {s['tpms']:8s} delta_max={s['dmax']:.3f}  "
              f"r_healthy={s['r_healthy']:.2f}  r_max={s['r_max']:.2f}(pinch)  "
              f"eps_drift={s['eps_drift_pct']:.1f}%  t_drift_atmax={s['t_drift_pct']:.1f}%  "
              f"anchor={'OK' if s['anchor_ok'] else 'FAIL'}  -> {verdict}")
    return all_rows, summary


if __name__ == "__main__":
    main()
