"""
Phase 1 预备：指定配比的非对称 TPMS 固体壁 → STL（marching cubes + trimesh）。

Phase-1 CFD 的几何输入起点（snappyHexMesh 等用 STL 表面）。
⚠ 单胞、box 边未封口（非 watertight）→ 仅几何样本；CFD-ready 周期水密网格
（封口 / 多胞 / 周期 BC）= Phase 1 proper。
用法：python -u runs/asym_export_stl.py
"""
import sys
from pathlib import Path
import numpy as np
from skimage import measure
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from solvers.tpms_geometry import _phi_grid

N = 128
L_mm = 5.0
OUT = Path(__file__).resolve().parents[1] / "runs" / "_out" / "stl"
# (tpms, A 占比, B 占比, 标签)；固体 = 1−A−B
CONFIGS = [
    ("Gyroid", 0.70, 0.20, "70-20-10"),
    ("Diamond", 0.70, 0.20, "70-20-10"),
    ("Gyroid", 0.45, 0.45, "45-45-10-sym"),
]


def export(tpms, A, B, label):
    phi = _phi_grid(tpms, N)
    lo = float(np.quantile(phi, A))
    hi = float(np.quantile(phi, 1.0 - B))
    delta, C = (lo + hi) / 2.0, (hi - lo) / 2.0
    dx = (L_mm / 1000.0) / N
    solid = ((phi >= delta - C) & (phi <= delta + C)).astype(np.float32)
    verts, faces, _, _ = measure.marching_cubes(solid, level=0.5, spacing=(dx, dx, dx))
    mesh = trimesh.Trimesh(vertices=verts, faces=faces)
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"asym_{tpms}_{label}.stl"
    mesh.export(p)
    print(f"[STL] {p.name}  verts={len(verts)} faces={len(faces)} "
          f"wall_area={mesh.area * 1e6:.0f}mm2  (delta={delta:.3f} C={C:.3f})")


if __name__ == "__main__":
    for c in CONFIGS:
        export(*c)
    print(f"\n输出目录: {OUT}")
