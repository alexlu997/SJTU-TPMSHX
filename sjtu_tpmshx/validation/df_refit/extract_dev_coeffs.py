"""extract_dev_coeffs.py — 水 CFD (K, cF) 的"发展段"重提取（候选 D · D-2a）.

背景（iter 65-66，2026-07-22）：sCO2 与水共用的 CFD 后处理里，dp_core 是
含入口周期的 3 段整核压降。逐段实测（p0..p3 四截面）显示入口段污染不对称：

    dp 段1/段2（中位）   Diamond 1.082 / Gyroid 1.414
    整核 / 发展段(2+3)   Diamond 1.015 / Gyroid **1.155**

真实 HX 流向 ~26 胞元，入口占比 ~4% ⇒ 均质化闭合应取**周期发展值**。
现行 `_prebuilt/df_cfd_coeffs.csv`（2026-06-30 两段法，K 已入产线）整体
建立在 dp_core 上——Gyroid 侧 cF 由此高 ~15%。

**iter 72 重提（R2，2026-07-23）**：数据源切换到修正上传
（`load_water_cfd`，Water-CFD/水数值模拟数据.xlsx）。修正上传的原始物理量
（p0..p3/dp/mdot/ρ/h）与旧 water-cfd-raw.xlsx 逐位相同，但 **Um 是修正量**
（旧值不闭合连续性，逐几何偏 ×0.83..×1.16；新值 r=mdot/(ρ·Um·L²)=ε/2
精确闭合，台账 NU-REFIT-0723）——iter 66 首版用旧 Um，cF 隐含位移
−26%..+45%（D_7_6 +28.5%），本版全面取代。D_7_3/4/5 的 mdot/Um 质量
不闭合仍 +3.9/5.4/7.3%（谁权威待数据方）：**带病入表 + `flow_suspect`
列标记**（cF/K ±10%/∓5% 级警示；RBF 面在节点处精确、不污染邻点读数）。

本工具做三件事：
  1. 用与 06-30 相同的两段法在 **dp_core** 上提取 → 与 06-30 生产表逐几何
     对照（该列现在的读数 = 方法差 × Um 修正的合成，作 Um 修正的量化留痕）；
  2. 同一数学切到 **发展段 dp = (p1−p3)/2 周期**（段 2+3 均值）→ 候选表
     `_prebuilt/df_cfd_coeffs_dev.csv`（不覆盖生产表）；
  3. 三基对比表：per-geometry cF/K 的 dev vs core vs SmoothDF(Re_ref)，
     量化各拓扑位移（dev/core 比是 u 不变量，入口污染结论跨 Um 修正成立）。

两段法 Re 切点冻结为 Re_hi≥12800 / Re_lo≤400（iter 66 对 06-30 生产表
网格反演所得，PROGRESS iter66 存证；生产表是旧 Um 基，新数据上重新校准
无意义——切点语义是流态分段，冻结沿用）。掩码用 CSV 名义 Re 标签
（`Re_nominal`，与校准时同口径）。

用法（从仓库根）:
    python -u sjtu_tpmshx/validation/df_refit/extract_dev_coeffs.py

输出: stdout 记分板 + _prebuilt/df_cfd_coeffs_dev.csv +
reports/df_refit/dev_vs_core_vs_smoothdf.csv。生产零改动（golden 位同）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from sjtu_tpmshx.df_surrogate.load_water_cfd import load_water
from sjtu_tpmshx.df_surrogate.smooth_df import SmoothDF
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
CORE_CSV = (_REPO / "sjtu_tpmshx" / "df_surrogate" / "_prebuilt"
            / "df_cfd_coeffs.csv")
DEV_CSV = (_REPO / "sjtu_tpmshx" / "df_surrogate" / "_prebuilt"
           / "df_cfd_coeffs_dev.csv")
REPORT_DIR = _REPO / "reports" / "df_refit"

RE_REF = 2530.0          # gamma_df anchor convention (production window center)
RE_HI = 12800.0          # 两段法切点（iter 66 校准冻结，见模块 docstring）
RE_LO = 400.0
_TOPOS = ("Diamond", "Gyroid")


def _fit_K_cF_nnls(dpdl: np.ndarray, u: np.ndarray, rho: np.ndarray,
                   mu: np.ndarray) -> tuple[float, float]:
    """单发 NNLS on (Δp/L)/u = μ·(1/K) + ρ·cF·u。仅作参照——方法校准实测
    它复现不了 06-30 生产表（K 偏 4-7×：湍流斜率漏进 Darcy 项），两段法
    （下）才是正主。保留以便对比表引用。"""
    y = dpdl / u
    X = np.column_stack([mu, rho * u])
    s = np.linalg.norm(X, axis=0)
    beta, _ = nnls(X / s, y)
    beta = beta / s
    invK, cF = float(beta[0]), float(beta[1])
    K = 1.0 / invK if invK > 0 else float("inf")
    return K, cF


def _fit_K_cF_2stage(dpdl: np.ndarray, u: np.ndarray, rho: np.ndarray,
                     mu: np.ndarray, Re: np.ndarray,
                     re_hi: float, re_lo: float) -> tuple[float, float]:
    """两段解耦拟合（06-30 方法的字面实现，2 轮迭代收敛）：

      阶段1  cF = median((dpdl − μ·u/K̂) / (ρ·u²))  在 Re ≥ re_hi 平台段
      阶段2  K  = median( μ·u / (dpdl − ρ·cF·u²) )  在 Re ≤ re_lo Darcy 段

    首轮 K̂=∞（平台段 Darcy 份额小），一次回代即稳（第 3 轮变化 <1e-3）。
    re_hi / re_lo 由 `_calibrate_thresholds` 对生产表反演确定。"""
    hi = Re >= re_hi
    lo = Re <= re_lo
    if hi.sum() < 3 or lo.sum() < 3:
        return float("nan"), float("nan")
    K = float("inf")
    cF = float("nan")
    for _ in range(3):
        darcy = mu[hi] * u[hi] / K if np.isfinite(K) else 0.0
        cF = float(np.median((dpdl[hi] - darcy) / (rho[hi] * u[hi] ** 2)))
        resid = dpdl[lo] - rho[lo] * cF * u[lo] ** 2
        good = resid > 0
        if good.sum() < 3:
            return float("nan"), float("nan")
        K = float(np.median(mu[lo][good] * u[lo][good] / resid[good]))
    return K, cF


def _load_geometry_rows(topo: str) -> pd.DataFrame:
    d = load_water(topo)
    need = ["geometry_id", "Re_nominal", "rho_kg_m3", "mu_Pa_s", "Um_m_s",
            "p0_Pa", "p1_Pa", "p2_Pa", "p3_Pa", "dp_core_Pa",
            "core_length_m", "period_length_m", "L_mm", "t_mm"]
    d = d.dropna(subset=need)
    # 发展段压降密度：(p1−p3) 跨 2 个周期
    d = d[(d.p1_Pa - d.p3_Pa) > 0]
    d["dpdl_dev"] = (d.p1_Pa - d.p3_Pa) / (2.0 * d.period_length_m)
    d["dpdl_core"] = d.dp_core_Pa / d.core_length_m
    return d


def run() -> pd.DataFrame:
    sm = SmoothDF()
    core_ref = pd.read_csv(CORE_CSV)
    rows = []
    for topo in _TOPOS:
        d = _load_geometry_rows(topo)
        for gid, g in d.groupby("geometry_id"):
            L = float(g.L_mm.iloc[0])
            t = round(float(g.t_mm.iloc[0]), 1)
            u = g.Um_m_s.to_numpy(float)
            rho = g.rho_kg_m3.to_numpy(float)
            mu = g.mu_Pa_s.to_numpy(float)
            Re = g.Re_nominal.to_numpy(float)
            K_dev, cF_dev = _fit_K_cF_2stage(
                g.dpdl_dev.to_numpy(float), u, rho, mu, Re, RE_HI, RE_LO)
            K_core, cF_core = _fit_K_cF_2stage(
                g.dpdl_core.to_numpy(float), u, rho, mu, Re, RE_HI, RE_LO)
            ref = core_ref[(core_ref.tp == topo)
                           & (np.isclose(core_ref.L, L))
                           & (np.isclose(core_ref.t, t))]
            K_06, cF_06 = ((float(ref.K.iloc[0]), float(ref.cF.iloc[0]))
                           if len(ref) else (np.nan, np.nan))
            cF_smoothdf = float(sm.predict_cF(topo, L, t, RE_REF))
            rows.append(dict(
                tp=topo, L=L, t=t, n=len(g),
                flow_suspect=bool(g.flow_suspect.iloc[0]),
                K_dev=K_dev, cF_dev=cF_dev,
                K_core=K_core, cF_core=cF_core,
                K_prod_csv=K_06, cF_prod_csv=cF_06,
                cF_smoothdf_at_ReRef=cF_smoothdf,
            ))
    return pd.DataFrame(rows)


def main() -> int:
    df = run()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_cmp = REPORT_DIR / "dev_vs_core_vs_smoothdf.csv"
    df.to_csv(out_cmp, index=False, encoding="utf-8-sig")

    dev = df[["tp", "L", "t", "K_dev", "cF_dev", "n", "flow_suspect"]].rename(
        columns={"K_dev": "K", "cF_dev": "cF"})
    dev.to_csv(DEV_CSV, index=False, encoding="utf-8")

    print("=" * 76)
    print(f"D-2a 发展段重提取（修正上传基，R2）—— 切点冻结 Re_hi≥{RE_HI:.0f} "
          f"Re_lo≤{RE_LO:.0f}")
    print("core 复现 vs 06-30 生产表（≠1 = Um 修正 × 方法差 的合成留痕）")
    print("=" * 76)
    for topo in _TOPOS:
        d = df[df.tp == topo].dropna(subset=["cF_prod_csv"])
        r_cf = d.cF_core / d.cF_prod_csv
        r_k = d.K_core / d.K_prod_csv
        print(f"[{topo}] core/生产表: cF med={r_cf.median():.4f} "
              f"[{r_cf.min():.3f},{r_cf.max():.3f}]  "
              f"K med={r_k.median():.4f} [{r_k.min():.3f},{r_k.max():.3f}]")
    print()
    print("发展段 vs core（入口污染的系数级后果；u 不变量，应与 iter 66 一致）")
    for topo in _TOPOS:
        d = df[df.tp == topo]
        rc = d.cF_dev / d.cF_core
        rk = d.K_dev / d.K_core
        print(f"[{topo}] cF_dev/cF_core med={rc.median():.4f} "
              f"[{rc.min():.3f},{rc.max():.3f}]  "
              f"K_dev/K_core med={rk.median():.4f} "
              f"[{rk.min():.3f},{rk.max():.3f}]")
    print()
    print("SmoothDF(Re_ref) vs 发展段 cF（形状基对比；SmoothDF 预构建表仍是"
          "旧 Um 基，此列水平差含该失配——候选 D 重建 SmoothDF 时更新）")
    for topo in _TOPOS:
        d = df[df.tp == topo]
        rs = d.cF_smoothdf_at_ReRef / d.cF_dev
        print(f"[{topo}] SmoothDF/cF_dev med={rs.median():.4f} "
              f"[{rs.min():.3f},{rs.max():.3f}]")
    sus = df[df.flow_suspect]
    if len(sus):
        print("\nflow_suspect 几何（mdot/Um 不闭合，cF/K 带 ±10%/-+5% 级警示）: "
              + ", ".join(f"{r.tp[0]}_{r.L:.0f}_{r.t*10:.0f}"
                          for _, r in sus.iterrows()))
    print(f"\n候选表已写出 {DEV_CSV}")
    print(f"对比表已写出 {out_cmp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
