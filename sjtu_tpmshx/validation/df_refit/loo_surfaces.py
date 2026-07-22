"""loo_surfaces.py — cF/K 候选面的留一几何 LOO 考卷（候选 D · D-2a-2）.

对两个提取基（dev = 发展段〔D-2a-1 候选〕；core = 06-30 生产表）各建
log-TPS(logL, logt) 面，逐拓扑做 leave-one-geometry-out：

    LOO 预测 (L_i, t_i) ← 其余 19 几何的 TPS  →  APE vs 该基自身真值

再加第三方：SmoothDF(Re_ref=2530) 对 dev 真值的残差（旧形状基距新基多远
——含 ×1.53 水平项与形状散差两部分，水平项单列）。参照系（不复算，引自
openspec df-coeffs-cfd-refit 2026-06-30 实测）：gamma_df 试件锚面对 CFD
真值 LOO 87%(G)/122%(D)——试件锚面本就不是为插值 CFD 而生，列出仅为
量级坐标。

插值器与生产同款（scipy RBFInterpolator, thin_plate_spline，log 空间——
`gamma_df._cfd_K_surface` 的约定），LOO 结论可直接迁移到生产面形式。

用法（从仓库根）:
    python -u sjtu_tpmshx/validation/df_refit/loo_surfaces.py

输出: stdout 记分板 + reports/df_refit/loo_surfaces.csv。生产零改动。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import RBFInterpolator

from sjtu_tpmshx.df_surrogate.smooth_df import SmoothDF
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
_PREBUILT = _REPO / "sjtu_tpmshx" / "df_surrogate" / "_prebuilt"
REPORT_DIR = _REPO / "reports" / "df_refit"

RE_REF = 2530.0
_BASES = {
    "dev": _PREBUILT / "df_cfd_coeffs_dev.csv",
    "core": _PREBUILT / "df_cfd_coeffs.csv",
}
_GAMMA_DF_SURFACE_LOO_REF = {"Gyroid": 0.87, "Diamond": 1.22}   # 06-30 实测


def _loo_tps(pts: np.ndarray, logv: np.ndarray) -> np.ndarray:
    """留一 log-TPS：返回每点的 LOO 预测（log 空间）。"""
    n = len(logv)
    out = np.empty(n)
    idx = np.arange(n)
    for i in range(n):
        m = idx != i
        rbf = RBFInterpolator(pts[m], logv[m], kernel="thin_plate_spline")
        out[i] = float(rbf(pts[i:i + 1])[0])
    return out


def run() -> pd.DataFrame:
    sm = SmoothDF()
    rows = []
    for base, path in _BASES.items():
        df = pd.read_csv(path)
        for topo, g in df.groupby("tp"):
            pts = np.log(np.column_stack([g.L.to_numpy(float),
                                          g.t.to_numpy(float)]))
            for qty in ("cF", "K"):
                truth = g[qty].to_numpy(float)
                pred = np.exp(_loo_tps(pts, np.log(truth)))
                ape = np.abs(pred - truth) / truth
                rows.append(dict(base=base, topo=topo, qty=qty,
                                 metric="loo_medape",
                                 value=float(np.median(ape))))
                rows.append(dict(base=base, topo=topo, qty=qty,
                                 metric="loo_rmsre",
                                 value=float(np.sqrt(np.mean(ape ** 2)))))
                rows.append(dict(base=base, topo=topo, qty=qty,
                                 metric="loo_maxape",
                                 value=float(ape.max())))
    # SmoothDF(Re_ref) vs dev 真值：水平项 + 去水平后的形状散差
    dev = pd.read_csv(_BASES["dev"])
    for topo, g in dev.groupby("tp"):
        sd = np.array([sm.predict_cF(topo, float(r.L), float(r.t), RE_REF)
                       for r in g.itertuples()])
        truth = g.cF.to_numpy(float)
        ratio = sd / truth
        level = float(np.exp(np.median(np.log(ratio))))
        shape_ape = np.abs(ratio / level - 1.0)
        rows.append(dict(base="smoothdf", topo=topo, qty="cF",
                         metric="level_ratio", value=level))
        rows.append(dict(base="smoothdf", topo=topo, qty="cF",
                         metric="shape_medape",
                         value=float(np.median(shape_ape))))
        rows.append(dict(base="smoothdf", topo=topo, qty="cF",
                         metric="shape_maxape", value=float(shape_ape.max())))
    return pd.DataFrame(rows)


def main() -> int:
    df = run()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "loo_surfaces.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print("=" * 74)
    print("D-2a-2 候选面 LOO 考卷（留一几何，log-TPS，生产同款插值器）")
    print("=" * 74)
    for topo in ("Diamond", "Gyroid"):
        print(f"\n[{topo}]  （参照：gamma_df 试件锚面 LOO "
              f"{_GAMMA_DF_SURFACE_LOO_REF[topo]:.0%}，06-30 实测）")
        for base in ("dev", "core"):
            d = df[(df.base == base) & (df.topo == topo)]
            for qty in ("cF", "K"):
                q = d[d.qty == qty]
                med = q[q.metric == "loo_medape"].value.iloc[0]
                rms = q[q.metric == "loo_rmsre"].value.iloc[0]
                mx = q[q.metric == "loo_maxape"].value.iloc[0]
                print(f"  {base:<5} {qty:<3} LOO medAPE {med:6.1%}  "
                      f"RMSRE {rms:6.1%}  max {mx:6.1%}")
        s = df[(df.base == "smoothdf") & (df.topo == topo)]
        lvl = s[s.metric == "level_ratio"].value.iloc[0]
        shp = s[s.metric == "shape_medape"].value.iloc[0]
        mxs = s[s.metric == "shape_maxape"].value.iloc[0]
        print(f"  SmoothDF vs dev: 水平 ×{lvl:.2f} · 去水平形状散差 "
              f"med {shp:.1%} / max {mxs:.1%}")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
