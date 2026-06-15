"""asym_export_cfd_cases.py — Phase 1 CFD case generator for asymmetric porosity.

⚠ DEPRECATED (2026-06-15): geometry now built in nTopology (user decision). This
marching-cubes STL exporter is retired for Phase 1. Use the finalized design
matrix from runs/asym_build_cfd_design_xlsx.py (→ asym_cfd_design_matrix.xlsx)
and feed geom_cases to nTop. See vault plan §4–§5. Kept for history only.

Given Phase-1 design points (tpms × target split (A%,B%) × per-side Re), emit:
  (a) per-side solid-wall STL (marching cubes, reuse asym_geometry) for ANSYS
      Fluent meshing — ONE offset cell per (tpms, split); both fluid channels
      are the complementary voids of the same wall.
  (b) a manifest CSV `cfd_cases.csv` listing every case + its geometry
      (C, δ, ε_A, ε_B, D_h_A, D_h_B) + per-side Re + the **P1.0 domain-envelope
      flag** `skip_nu` (Re inside the symmetric Nu fit window → Nu κ≈1, skip
      the Nu-CFD; dP-CFD always runs because dP is the primary deliverable).

The CFD itself is run MANUALLY in ANSYS Fluent (pressure-based SIMPLE,
ρ=ρ(P,T) ideal-gas, translational-periodic BC, coupled wall). Its per-side
dP / Nu results feed `df_surrogate.ingest_cfd_kappa` → the κ table.

Usage:  python -u runs/asym_export_cfd_cases.py
Output: runs/_out/asym_cfd/{cfd_cases.csv, stl/asym_<tpms>_<label>.stl}
"""
import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from solvers.tpms_geometry import _phi_grid
from solvers.nu_correlations import NU_RE_FIT_RANGE, WATER_NU_RE_RANGE
from runs.asym_target_scan import solve_target

N = 128
OUT = Path(__file__).resolve().parents[1] / "runs" / "_out" / "asym_cfd"

# Design points: (tpms, L_mm, t_mm, [(A_frac, B_frac, label), ...]).
# Targets span symmetric → r≈2.9 usable band (Phase-0 connectivity limit).
TPMS_POINTS = [
    ("Diamond", 5.0, 0.5),
    ("Gyroid", 5.0, 0.5),
]
TARGETS = [
    (0.45, 0.45, "45-45-10-sym"),
    (0.55, 0.35, "55-35-10"),
    (0.60, 0.30, "60-30-10"),
    (0.65, 0.25, "65-25-10"),
]
# Per-side Reynolds sweep (air side high-Re, water/liquid side low-Re).
RE_AIR = [600.0, 2000.0, 6000.0, 12000.0]
RE_LIQ = [150.0, 500.0, 1500.0, 3000.0]


def _in_window(re, window):
    lo, hi = window
    return bool(lo <= re <= hi)


def export_stl(phi, C, delta, L_m, path):
    """Solid-wall STL (marching cubes). Single cell, box edges open
    (not watertight) — Fluent meshing seals + applies periodic BC."""
    from skimage import measure
    import trimesh
    dx = L_m / N
    solid = ((phi >= delta - C) & (phi <= delta + C)).astype(np.float32)
    verts, faces, _, _ = measure.marching_cubes(solid, level=0.5, spacing=(dx, dx, dx))
    mesh = trimesh.Trimesh(vertices=verts, faces=faces)
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(path)
    return mesh.area * 1e6  # mm^2


def main(write_stl=True):
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for tpms, L_mm, t_mm in TPMS_POINTS:
        phi = _phi_grid(tpms, N)
        L_m = L_mm / 1000.0
        for A, B, label in TARGETS:
            g = solve_target(phi, A, B, L_m)
            eps_sym = 0.5 * (g["eps_A"] + g["eps_B"])
            stl_name = f"asym_{tpms}_{label}.stl"
            if write_stl:
                try:
                    area = export_stl(phi, g["C"], g["delta"], L_m, OUT / "stl" / stl_name)
                    print(f"[STL] {stl_name}  wall_area={area:.0f}mm2  "
                          f"epsA={g['eps_A']:.3f} epsB={g['eps_B']:.3f} "
                          f"conn={'OK' if g['pA'] and g['pB'] else 'CUT'}")
                except Exception as e:  # skimage/trimesh optional
                    print(f"[STL] {stl_name} SKIPPED ({e})")
            # one manifest row per (case, side, Re)
            for side, eps_side, Dh, re_list, win in (
                ("A", g["eps_A"], g["Dh_A"], RE_AIR, NU_RE_FIT_RANGE),
                ("B", g["eps_B"], g["Dh_B"], RE_LIQ, WATER_NU_RE_RANGE),
            ):
                for re in re_list:
                    rows.append(dict(
                        case_id=f"{tpms}_{label}_{side}_Re{int(re)}",
                        tpms=tpms, L_mm=L_mm, t_mm=t_mm,
                        C=round(g["C"], 6), delta=round(g["delta"], 6),
                        side=side, eps_side=round(eps_side, 6),
                        eps_sym=round(eps_sym, 6),
                        r_ratio=round(eps_side / eps_sym, 6) if eps_sym > 0 else 0.0,
                        Dh_mm=round(Dh * 1e3, 6), Re=re,
                        stl=stl_name,
                        skip_nu=_in_window(re, win),   # P1.0: in-window → Nu κ≈1
                    ))
    manifest = OUT / "cfd_cases.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    n_skip = sum(1 for r in rows if r["skip_nu"])
    print(f"\n[manifest] {manifest}  ({len(rows)} cases, "
          f"{n_skip} skip-Nu / {len(rows) - n_skip} need-Nu; dP-CFD all cases)")
    print(f"[next] run Fluent per case → results CSV → "
          f"python -m df_surrogate.ingest_cfd_kappa <results.csv>")


if __name__ == "__main__":
    main()
