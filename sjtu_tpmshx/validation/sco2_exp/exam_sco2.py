"""exam_sco2.py — sCO2 标定考卷（候选 D · D-1sc，2026-07-22）.

一条命令跑分，冻结 D-2sc（γ_f 修正试点）开工前的基准，并提供试点必须
复用的纪律件（窗守卫 / holdout 切分）。设计依据 docs/DF-CALIBRATION-AUDIT-
2026-07.md §4-§5；上海 3D 门是空气-水域的盲考，**管不到 sCO2**——本考卷
就是 sCO2 域内验证的全部合法手段（D-7-6/G-7-6 实验既是标定源，域内没有
真盲考，只有以下四类自检；真盲考在候选 D 的水/空气阶段）：

  [BASE]   基准题——产线光滑壁闭合 vs 实验的逐点 γ 带（γ_Nu / γ_f 分侧
           中位数与 [P10,P90]）。D-2sc 修正的目标 = 把这些带收拢到 1。
  [HOLD]   holdout 题——γ(Re)=Γ₀·Re^Δ 幂律的点级 LOO 与 Re 对半外推
           （低半拟合→高半预测、反向）。量化关联式在窗内的插值稳定性，
           为 hot/cold 选侧证据包供数。
  [XFLUID] 跨流体粗糙度一致性——同一试件（7/0.6 SLM 批次）的 sCO2 γ_f
           vs **独立的空气侧证据** = 产线 gamma_df 的 γ_air(7,0.6)
           （纯试件锚插值，D_7_6 空气盲测 454 vs ~454 验证过）。
           粗糙度是表面属性、弱流体相关 ⇒ 若 γ_f ≫ γ_air，说明修正卡
           吸收的不只是粗糙度，还有 HX 级系统效应（歧管/入口/传感器），
           修正的适用面须如实标注为"HX 级预测修正"而非"纯粗糙度"。
           历史 D-7-6 sCO2 Δp 比 ~3.4（ledger SCO2-CFD）为同族数据的
           早期口径，仅作连续性参照，不是独立轴。
  [GUARD]  窗守卫题——`assert_in_window` 在实验 Re 窗外必须 fail-loud
           （subst.v2 取用卡红线：仅窗内插值，cold 侧禁外推）。D-2sc 的
           修正模块必须 import 本守卫，不许自带地板。

用法（从仓库根）:
    python -u sjtu_tpmshx/validation/sco2_exp/exam_sco2.py

输出: stdout 记分板 + reports/sco2_exp/exam_sco2.csv（长表: item/topo/
side/metric/value）。数据完整性旗标计数（ok_dp/ok_dT/ok_hb/ok_done）
一并落表——重跑时计数漂移 = 数据源变了，先查数据再谈数字。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from sjtu_tpmshx.validation.sco2_exp.compare_exp_vs_cfd import analyse
from sjtu_tpmshx.validation.sco2_exp.load_sco2_exp import load_exp
from sjtu_tpmshx.df_surrogate.gamma_df import GammaDF
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

REPORT_DIR = Path(__file__).resolve().parents[3] / "reports" / "sco2_exp"

# 历史连续性参照（非独立轴）：ledger SCO2-CFD 语义红线行记载的 D-7-6
# sCO2 早期分析 —— 真件 Δp ≈ 3.4× 光滑 CFD（单几何）。与本考卷的 cold 侧
# γ_f 同族同源，只用来确认新旧分析口径连续。独立轴 = γ_air（见 XFLUID）。
D76_SCO2_DP_RATIO = 3.4

_TOPOS = ("Diamond", "Gyroid")


# ── [GUARD] 实验 Re 窗（数据自导出，冻结于加载时刻）──────────────────


class OutsideExperimentalWindow(ValueError):
    """γ 修正被要求在实验 Re 窗外取值 —— subst.v2 取用卡红线，fail-loud。"""


_WINDOW_CACHE: dict[str, tuple[float, float]] = {}


def re_window(topo: str) -> tuple[float, float]:
    """该拓扑实验覆盖的 Re 窗 [min, max]（Nu 集 ∪ f 集，数据自导出）。"""
    if topo not in _WINDOW_CACHE:
        r = analyse(topo)
        lo = min(float(r["nu_set"]["Re"].min()), float(r["f_set"]["Re"].min()))
        hi = max(float(r["nu_set"]["Re"].max()), float(r["f_set"]["Re"].max()))
        _WINDOW_CACHE[topo] = (lo, hi)
    return _WINDOW_CACHE[topo]


def assert_in_window(Re, topo: str) -> None:
    """D-2sc 修正模块的强制守卫：窗外即抛，绝不静默钳制。"""
    lo, hi = re_window(topo)
    Re = np.asarray(Re, dtype=float)
    if np.any(Re < lo) or np.any(Re > hi):
        bad_lo, bad_hi = float(Re.min()), float(Re.max())
        raise OutsideExperimentalWindow(
            f"{topo}: Re∈[{bad_lo:.0f},{bad_hi:.0f}] 超出实验窗 "
            f"[{lo:.0f},{hi:.0f}] —— γ 修正仅窗内插值（subst.v2 取用卡；"
            f"cold 侧斜率窗外物理不合理）。窗外请回落光滑壁闭合并声明。")


# ── [HOLD] holdout 纪律件（幂律 y = Γ₀·Re^Δ 的两种检验）───────────────


def _power_fit(lnx: np.ndarray, lny: np.ndarray) -> tuple[float, float]:
    A = np.column_stack([np.ones_like(lnx), lnx])
    beta, *_ = np.linalg.lstsq(A, lny, rcond=None)
    return float(np.exp(beta[0])), float(beta[1])


def loo_medape(Re: np.ndarray, y: np.ndarray) -> float:
    """点级 leave-one-out：逐点剔除重拟、预测被剔点，medAPE。"""
    lnx, lny = np.log(Re), np.log(y)
    n = len(lnx)
    ape = np.empty(n)
    idx = np.arange(n)
    for i in range(n):
        m = idx != i
        G0, d = _power_fit(lnx[m], lny[m])
        ape[i] = abs(G0 * Re[i] ** d - y[i]) / y[i]
    return float(np.median(ape))


def re_split_medape(Re: np.ndarray, y: np.ndarray) -> dict[str, float]:
    """Re 对半 holdout：低半拟合→预测高半（fwd），及反向（rev）。
    量化"窗内另一半"的外推稳定性——比 LOO 更接近 D-2sc 的真实使用面。"""
    order = np.argsort(Re)
    Re_s, y_s = Re[order], y[order]
    half = len(Re_s) // 2
    out = {}
    for tag, (tr, te) in (("fwd", (slice(None, half), slice(half, None))),
                          ("rev", (slice(half, None), slice(None, half)))):
        G0, d = _power_fit(np.log(Re_s[tr]), np.log(y_s[tr]))
        ape = np.abs(G0 * Re_s[te] ** d - y_s[te]) / y_s[te]
        out[tag] = float(np.median(ape))
    return out


# ── 记分板 ─────────────────────────────────────────────────────────────


def _band(s: pd.Series) -> tuple[float, float, float]:
    return (float(s.median()), float(s.quantile(0.10)),
            float(s.quantile(0.90)))


def run_exam() -> pd.DataFrame:
    rows: list[dict] = []

    def _add(item, topo, side, metric, value):
        rows.append(dict(item=item, topo=topo, side=side,
                         metric=metric, value=float(value)))

    # [DATA] 完整性旗标计数（load 不删行只打标——计数漂移 = 数据源变化）
    for topo in _TOPOS:
        df = load_exp(topo)
        _add("DATA", topo, "-", "rows_total", len(df))
        for flag in ("ok_dp", "ok_dT", "ok_hb", "ok_done"):
            if flag in df.columns:
                _add("DATA", topo, "-", f"{flag}_true", int(df[flag].sum()))

    for topo in _TOPOS:
        r = analyse(topo)

        # [BASE] 光滑基 vs 实验：γ 逐点带
        med, p10, p90 = _band(r["nu_set"]["gamma_Nu"])
        for m, v in (("gamma_nu_med", med), ("gamma_nu_p10", p10),
                     ("gamma_nu_p90", p90)):
            _add("BASE", topo, "pooled", m, v)
        for side, g in r["f_set"].groupby("side"):
            med, p10, p90 = _band(g["gamma_f"])
            for m, v in (("gamma_f_med", med), ("gamma_f_p10", p10),
                         ("gamma_f_p90", p90)):
                _add("BASE", topo, side, m, v)
            fn = r["gamma_fn"][f"f_{side}"]
            _add("BASE", topo, side, "gamma_f_G0", fn["G0"])
            _add("BASE", topo, side, "gamma_f_dexp", fn["d"])

        # [HOLD] γ_f / γ_Nu 幂律的 LOO 与 Re 对半
        for side, g in r["f_set"].groupby("side"):
            Re = g["Re"].to_numpy(float)
            y = g["gamma_f"].to_numpy(float)
            _add("HOLD", topo, side, "gamma_f_loo_medape",
                 loo_medape(Re, y))
            sp = re_split_medape(Re, y)
            _add("HOLD", topo, side, "gamma_f_resplit_fwd", sp["fwd"])
            _add("HOLD", topo, side, "gamma_f_resplit_rev", sp["rev"])
        Re = r["nu_set"]["Re"].to_numpy(float)
        y = r["nu_set"]["gamma_Nu"].to_numpy(float)
        _add("HOLD", topo, "pooled", "gamma_nu_loo_medape",
             loo_medape(Re, y))

        # [XFLUID] 跨流体粗糙度一致性（同试件 7/0.6，一阶可比、标注近似）。
        # γ_air = 产线 gamma_df 的 γ 面在 (7, 0.6) 的值。注意 Gyroid 的这个
        # 值今天仍穿 L7=534.8 上海标定点（审计 §3，退役在 D-2b）——Diamond
        # 是干净的试件锚插值，一致性判读以 Diamond 为准。
        gamma_air = float(GammaDF(topo).gamma(7.0, 0.6))
        _add("XFLUID", topo, "-", "gamma_air_cf_ratio_7_06", gamma_air)
        _add("XFLUID", topo, "-", "d76_sco2_dp_ratio_hist", D76_SCO2_DP_RATIO)
        for side, g in r["f_set"].groupby("side"):
            _add("XFLUID", topo, side, "gamma_f_med_over_gamma_air",
                 float(g["gamma_f"].median()) / gamma_air)

        # [GUARD] 窗常数落表 + 守卫行为自检
        lo, hi = re_window(topo)
        _add("GUARD", topo, "-", "re_window_lo", lo)
        _add("GUARD", topo, "-", "re_window_hi", hi)
        assert_in_window([lo, hi], topo)          # 窗内边界必须通过
        for probe in (lo * 0.5, hi * 2.0):        # 窗外必须抛
            try:
                assert_in_window(probe, topo)
            except OutsideExperimentalWindow:
                pass
            else:
                raise AssertionError(
                    f"{topo}: 窗守卫在 Re={probe:.0f} 未触发 —— 考卷失效")
        _add("GUARD", topo, "-", "guard_selftest_ok", 1.0)

    return pd.DataFrame(rows)


def main() -> int:
    df = run_exam()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "exam_sco2.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print("=" * 72)
    print("sCO2 考卷（D-1sc 基准冻结）— 产线光滑壁闭合 vs 实验")
    print("=" * 72)
    for topo in _TOPOS:
        d = df[df.topo == topo]
        lo = d[d.metric == "re_window_lo"].value.iloc[0]
        hi = d[d.metric == "re_window_hi"].value.iloc[0]
        print(f"\n[{topo}]  实验 Re 窗 [{lo:,.0f}, {hi:,.0f}]")
        gnu = d[d.metric == "gamma_nu_med"].value.iloc[0]
        print(f"  γ_Nu  中位 {gnu:.3f}   "
              f"(LOO medAPE "
              f"{d[d.metric == 'gamma_nu_loo_medape'].value.iloc[0]:.1%})")
        for side in ("hot", "cold"):
            ds = d[d.side == side]
            if ds.empty:
                continue
            med = ds[ds.metric == "gamma_f_med"].value.iloc[0]
            g0 = ds[ds.metric == "gamma_f_G0"].value.iloc[0]
            dx = ds[ds.metric == "gamma_f_dexp"].value.iloc[0]
            loo = ds[ds.metric == "gamma_f_loo_medape"].value.iloc[0]
            fwd = ds[ds.metric == "gamma_f_resplit_fwd"].value.iloc[0]
            rev = ds[ds.metric == "gamma_f_resplit_rev"].value.iloc[0]
            print(f"  γ_f·{side:<4} 中位 {med:5.2f}   函数 {g0:.3g}·Re^{dx:+.3f}"
                  f"   LOO {loo:.1%}  Re对半 fwd {fwd:.1%} / rev {rev:.1%}")
        ga = d[d.metric == "gamma_air_cf_ratio_7_06"].value.iloc[0]
        print(f"  跨流体独立轴: γ_air(7/0.6)={ga:.2f} (空气试件锚产线面)"
              f" · 历史 D-7-6 sCO2 Δp 比 ~{D76_SCO2_DP_RATIO} (同族参照)")
        rh = d[(d.metric == "gamma_f_med_over_gamma_air")]
        if not rh.empty:
            pairs = "  ".join(f"{row.side} ×{row.value:.1f}"
                              for row in rh.itertuples())
            print(f"  γ_f/γ_air 超额倍数: {pairs}"
                  f"   (≫1 ⇒ 修正含 HX 级系统效应，非纯粗糙度)")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
