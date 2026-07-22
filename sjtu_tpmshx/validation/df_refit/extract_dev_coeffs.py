"""extract_dev_coeffs.py — 水 CFD (K, cF) 的"发展段"重提取（候选 D · D-2a）.

背景（iter 65-66，2026-07-22）：sCO2 与水共用的 CFD 后处理里，dp_core 是
含入口周期的 3 段整核压降。逐段实测（p0..p3 四截面）显示入口段污染不对称：

    dp 段1/段2（中位）   Diamond 1.082 / Gyroid 1.414
    整核 / 发展段(2+3)   Diamond 1.015 / Gyroid **1.155**

真实 HX 流向 ~26 胞元，入口占比 ~4% ⇒ 均质化闭合应取**周期发展值**。
现行 `_prebuilt/df_cfd_coeffs.csv`（2026-06-30 两段法，K 已入产线）整体
建立在 dp_core 上——Gyroid 侧 cF 由此高 ~15%。

本工具做三件事：
  1. 用与 06-30 相同的拟合数学（`(Δp/L)/u = μ/K + ρ·cF·u`，NNLS 非负）
     在 **dp_core** 上复现提取 → 与现表逐几何对照（方法校准，防"换了
     数学再换数据"的双变量混淆）；
  2. 同一数学切到 **发展段 dp = (p1−p3)/2 周期**（段 2+3 均值）→ 候选表
     `_prebuilt/df_cfd_coeffs_dev.csv`（不覆盖生产表）；
  3. 三基对比表：per-geometry cF/K 的 dev vs core vs SmoothDF(Re_ref)，
     量化各拓扑位移（D-2c 对比矩阵与 D-3 换默认的输入）。

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

from sjtu_tpmshx.df_surrogate.smooth_df import SmoothDF
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
WATER_XLSX = _REPO / "data" / "raw_data" / "water-cfd-raw.xlsx"
CORE_CSV = (_REPO / "sjtu_tpmshx" / "df_surrogate" / "_prebuilt"
            / "df_cfd_coeffs.csv")
DEV_CSV = (_REPO / "sjtu_tpmshx" / "df_surrogate" / "_prebuilt"
           / "df_cfd_coeffs_dev.csv")
REPORT_DIR = _REPO / "reports" / "df_refit"

RE_REF = 2530.0          # gamma_df anchor convention (production window center)
_SHEETS = {"Diamond": ["D-4", "D-5", "D-6", "D-7", "D-8"],
           "Gyroid": ["G-4", "G-5", "G-6", "G-7", "G-8"]}


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
    xl = pd.ExcelFile(WATER_XLSX)
    frames = [xl.parse(s) for s in _SHEETS[topo]]
    d = pd.concat(frames, ignore_index=True)
    need = ["geometry_id", "Re", "rho_kg_m3", "mu_Pa_s", "Um_m_s",
            "p0_Pa", "p1_Pa", "p2_Pa", "p3_Pa", "dp_core_Pa",
            "core_length_m", "period_length_m",
            "cell_size_mm", "wall_thickness_mm"]
    d = d.dropna(subset=need)
    # 发展段压降密度：(p1−p3) 跨 2 个周期
    d = d[(d.p1_Pa - d.p3_Pa) > 0]
    d["dpdl_dev"] = (d.p1_Pa - d.p3_Pa) / (2.0 * d.period_length_m)
    d["dpdl_core"] = d.dp_core_Pa / d.core_length_m
    return d


def _calibrate_thresholds(core_ref: pd.DataFrame,
                          data: dict[str, pd.DataFrame]
                          ) -> tuple[float, float, float]:
    """反演 06-30 的 Re 切点：在候选网格上找使 core-dp 两段法最贴生产表的
    (re_hi, re_lo)，目标 = cF 与 K 的 median|ratio−1| 之和。校准结果与
    最优失配一并返回，主程序把它印出来作方法校准证据。"""
    best = (None, None, np.inf)
    for re_hi in (1600.0, 3200.0, 6400.0, 12800.0):
        for re_lo in (150.0, 200.0, 400.0, 800.0):
            errs_cf, errs_k = [], []
            for topo, d in data.items():
                for gid, g in d.groupby("geometry_id"):
                    L = float(g.cell_size_mm.iloc[0])
                    t = float(g.wall_thickness_mm.iloc[0]) / 10.0
                    K, cF = _fit_K_cF_2stage(
                        g.dpdl_core.to_numpy(float),
                        g.Um_m_s.to_numpy(float),
                        g.rho_kg_m3.to_numpy(float),
                        g.mu_Pa_s.to_numpy(float),
                        g.Re.to_numpy(float), re_hi, re_lo)
                    ref = core_ref[(core_ref.tp == topo)
                                   & (np.isclose(core_ref.L, L))
                                   & (np.isclose(core_ref.t, t))]
                    if len(ref) and np.isfinite(cF):
                        errs_cf.append(cF / float(ref.cF.iloc[0]) - 1.0)
                        errs_k.append(K / float(ref.K.iloc[0]) - 1.0)
            if not errs_cf:
                continue
            score = (np.median(np.abs(errs_cf))
                     + np.median(np.abs(errs_k)))
            if score < best[2]:
                best = (re_hi, re_lo, float(score))
    return best


def run() -> tuple[pd.DataFrame, tuple[float, float, float]]:
    sm = SmoothDF()
    core_ref = pd.read_csv(CORE_CSV)
    data = {topo: _load_geometry_rows(topo) for topo in _SHEETS}
    re_hi, re_lo, cal_score = _calibrate_thresholds(core_ref, data)

    rows = []
    for topo, d in data.items():
        for gid, g in d.groupby("geometry_id"):
            L = float(g.cell_size_mm.iloc[0])
            t = float(g.wall_thickness_mm.iloc[0]) / 10.0   # tcode/10 约定
            u = g.Um_m_s.to_numpy(float)
            rho = g.rho_kg_m3.to_numpy(float)
            mu = g.mu_Pa_s.to_numpy(float)
            Re = g.Re.to_numpy(float)
            K_dev, cF_dev = _fit_K_cF_2stage(
                g.dpdl_dev.to_numpy(float), u, rho, mu, Re, re_hi, re_lo)
            K_core, cF_core = _fit_K_cF_2stage(
                g.dpdl_core.to_numpy(float), u, rho, mu, Re, re_hi, re_lo)
            ref = core_ref[(core_ref.tp == topo)
                           & (np.isclose(core_ref.L, L))
                           & (np.isclose(core_ref.t, t))]
            K_06, cF_06 = ((float(ref.K.iloc[0]), float(ref.cF.iloc[0]))
                           if len(ref) else (np.nan, np.nan))
            cF_smoothdf = float(sm.predict_cF(topo, L, t, RE_REF))
            rows.append(dict(
                tp=topo, L=L, t=t, n=len(g),
                K_dev=K_dev, cF_dev=cF_dev,
                K_core=K_core, cF_core=cF_core,
                K_prod_csv=K_06, cF_prod_csv=cF_06,
                cF_smoothdf_at_ReRef=cF_smoothdf,
            ))
    return pd.DataFrame(rows), (re_hi, re_lo, cal_score)


def main() -> int:
    df, (re_hi, re_lo, cal_score) = run()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_cmp = REPORT_DIR / "dev_vs_core_vs_smoothdf.csv"
    df.to_csv(out_cmp, index=False, encoding="utf-8-sig")

    dev = df[["tp", "L", "t", "K_dev", "cF_dev", "n"]].rename(
        columns={"K_dev": "K", "cF_dev": "cF"})
    dev.to_csv(DEV_CSV, index=False, encoding="utf-8")

    print("=" * 76)
    print(f"D-2a 发展段重提取 —— 两段法阈值自校准: Re_hi≥{re_hi:.0f} "
          f"Re_lo≤{re_lo:.0f}（失配分 {cal_score:.4f}）")
    print("方法校准（core 复现 vs 06-30 生产表）")
    print("=" * 76)
    for topo in _SHEETS:
        d = df[df.tp == topo].dropna(subset=["cF_prod_csv"])
        r_cf = d.cF_core / d.cF_prod_csv
        r_k = d.K_core / d.K_prod_csv
        print(f"[{topo}] core 复现/生产表: cF med={r_cf.median():.4f} "
              f"[{r_cf.min():.3f},{r_cf.max():.3f}]  "
              f"K med={r_k.median():.4f} [{r_k.min():.3f},{r_k.max():.3f}]")
    print()
    print("发展段 vs core（入口污染的系数级后果）")
    for topo in _SHEETS:
        d = df[df.tp == topo]
        rc = d.cF_dev / d.cF_core
        rk = d.K_dev / d.K_core
        print(f"[{topo}] cF_dev/cF_core med={rc.median():.4f} "
              f"[{rc.min():.3f},{rc.max():.3f}]  "
              f"K_dev/K_core med={rk.median():.4f} "
              f"[{rk.min():.3f},{rk.max():.3f}]")
    print()
    print("SmoothDF(Re_ref) vs 发展段 cF（形状基对比的绝对水平差）")
    for topo in _SHEETS:
        d = df[df.tp == topo]
        rs = d.cF_smoothdf_at_ReRef / d.cF_dev
        print(f"[{topo}] SmoothDF/cF_dev med={rs.median():.4f} "
              f"[{rs.min():.3f},{rs.max():.3f}]")
    print(f"\n候选表已写出 {DEV_CSV}")
    print(f"对比表已写出 {out_cmp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
