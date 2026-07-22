"""gamma_f_variants.py — D-2sc 选侧证据包：γ_f 六变体贝叶斯对比（2026-07-22）.

候选 D · sCO2 试点的核心证据脚本。对 subst.v2 取用卡的 γ_f 修正做六个
标定变体，量化各自把光滑壁 CFD f 修到实验 f 的能力，供 Alex 裁 hot/cold
选侧（DECISIONS D6）：

    变体 = 拟合侧 {hot, cold, pooled} × 斜率 {free: γ=Γ₀·(Re/Re_c)^Δ,
                                              amp:  γ=Γ₀（纯幅值, Δ≡0}}

模型与后验（log 空间线性高斯，Jeffreys 无信息先验，解析后验）:
    ln γ = ln Γ₀ + Δ·ln(Re/Re_c) + ε,  ε ~ N(0, σ²)
    Re_c = 拟合集 Re 几何中心（中心化使 Γ₀ 与 Δ 后验近独立）
    free: 标准贝叶斯线性回归 → 预测 t 分布（n−2 自由度）
    amp : 均值模型 → t（n−1 自由度）
    γ 预测带（Re* 处）: γ̂·exp(±t_q·s_pred) —— **乘法带**。

Δp 带即 f 带（恒等式）：实验约化 f = ΔP·Dh/(L·ρ̄·ū²/2)，逐工况因子由实测
状态固定 ⇒ APE(Δp) ≡ APE(f)，预测带同构传递。故本脚本全部在 f 空间评估，
结论直接就是 Δp 结论——无需跑求解器。

评估轴（每拓扑）:
    own    拟合侧自评 medAPE（in-sample 拟合质量）
    cross  跨侧预测 medAPE（**域内最接近独立验证的轴**——两侧是独立回路
           与仪表；若 hot 拟合预测不了 cold、反之亦然，则侧间系统差为真）
    cover  68%/95% 后验预测带覆盖率（标定的 UQ 是否诚实）
    ref    γ_air(7/0.6) 恒等参照行（纯粗糙度假设 + 空气锚——量化
           "HX 级系统效应"份额；exam_sco2 XFLUID 发现的定量化）

窗纪律：全部评估点过 exam_sco2.assert_in_window（守卫契约演示——D-2sc
产线接线时修正模块必须同样 import，窗外 fail-loud 不许静默钳制）。

用法（从仓库根）:
    python -u sjtu_tpmshx/validation/sco2_exp/gamma_f_variants.py

输出: stdout 记分板 + reports/sco2_exp/gamma_f_variants.csv。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from sjtu_tpmshx.validation.sco2_exp.compare_exp_vs_cfd import analyse
from sjtu_tpmshx.validation.sco2_exp.exam_sco2 import assert_in_window
from sjtu_tpmshx.df_surrogate.gamma_df import GammaDF
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

REPORT_DIR = Path(__file__).resolve().parents[3] / "reports" / "sco2_exp"

_TOPOS = ("Diamond", "Gyroid")
_SIDES = ("hot", "cold")
_FITS = ("hot", "cold", "pooled")


# ── 贝叶斯幂律标定（解析后验） ─────────────────────────────────────────


@dataclass
class GammaPosterior:
    """ln γ = b0 + b1·x 的后验（x = ln(Re/Re_c)；amp 变体 b1 ≡ 0）。"""
    Re_c: float
    b0: float                 # 后验均值 ln Γ₀
    b1: float                 # 后验均值 Δ
    s2: float                 # σ² 的无偏估计
    XtX_inv: np.ndarray | None  # free: 2×2；amp: None
    n: int
    dof: int

    @property
    def G0(self) -> float:
        return float(np.exp(self.b0))

    def predict(self, Re: np.ndarray) -> np.ndarray:
        x = np.log(np.asarray(Re, float) / self.Re_c)
        return np.exp(self.b0 + self.b1 * x)

    def band(self, Re: np.ndarray, q: float) -> tuple[np.ndarray, np.ndarray]:
        """γ 的中心 (1−2q) 后验预测带（如 q=0.16 → 68% 带）。"""
        Re = np.asarray(Re, float)
        x = np.log(Re / self.Re_c)
        if self.XtX_inv is None:
            lever = 1.0 / self.n
        else:
            X = np.column_stack([np.ones_like(x), x])
            lever = np.einsum("ij,jk,ik->i", X, self.XtX_inv, X)
        s_pred = np.sqrt(self.s2 * (1.0 + lever))
        t = float(stats.t.ppf(1.0 - q, self.dof))
        mid = self.b0 + self.b1 * x
        return np.exp(mid - t * s_pred), np.exp(mid + t * s_pred)


def fit_gamma(Re: np.ndarray, gamma: np.ndarray, slope_free: bool
              ) -> GammaPosterior:
    lnRe = np.log(Re)
    Re_c = float(np.exp(lnRe.mean()))
    x = lnRe - np.log(Re_c)
    y = np.log(gamma)
    n = len(y)
    if slope_free:
        X = np.column_stack([np.ones_like(x), x])
        beta, res, *_ = np.linalg.lstsq(X, y, rcond=None)
        dof = n - 2
        rss = float(res[0]) if res.size else float(((y - X @ beta) ** 2).sum())
        return GammaPosterior(Re_c, float(beta[0]), float(beta[1]),
                              rss / dof, np.linalg.inv(X.T @ X), n, dof)
    b0 = float(y.mean())
    dof = n - 1
    return GammaPosterior(Re_c, b0, 0.0, float(((y - b0) ** 2).sum()) / dof,
                          None, n, dof)


# ── 证据矩阵 ───────────────────────────────────────────────────────────


def _medape(pred: np.ndarray, obs: np.ndarray) -> float:
    return float(np.median(np.abs((pred - obs) / obs)))


def run_variants() -> pd.DataFrame:
    rows: list[dict] = []

    def _add(topo, fit, slope, eval_side, metric, value):
        rows.append(dict(topo=topo, fit=fit, slope=slope,
                         eval=eval_side, metric=metric, value=float(value)))

    for topo in _TOPOS:
        r = analyse(topo)
        fs = r["f_set"]
        assert_in_window(fs["Re"].to_numpy(float), topo)   # 守卫契约

        eval_sets = {s: g for s, g in fs.groupby("side")}
        fit_sets = dict(eval_sets)
        fit_sets["pooled"] = fs

        # γ_air 恒等参照（纯粗糙度 + 空气锚假设——预期大失败，量化
        # HX 级系统效应份额；Gyroid 值今天仍穿 534.8 上海点，标注）
        g_air = float(GammaDF(topo).gamma(7.0, 0.6))
        for s in _SIDES:
            g = eval_sets[s]
            pred = g_air * g["f_cfd"].to_numpy(float)
            _add(topo, "gamma_air_ref", "amp", s, "medape",
                 _medape(pred, g["f"].to_numpy(float)))
        _add(topo, "gamma_air_ref", "amp", "-", "G0", g_air)

        for fit_side in _FITS:
            gfit = fit_sets[fit_side]
            for slope, slope_free in (("free", True), ("amp", False)):
                post = fit_gamma(gfit["Re"].to_numpy(float),
                                 gfit["gamma_f"].to_numpy(float), slope_free)
                _add(topo, fit_side, slope, "-", "G0", post.G0)
                _add(topo, fit_side, slope, "-", "dexp", post.b1)
                _add(topo, fit_side, slope, "-", "sigma_ln",
                     float(np.sqrt(post.s2)))
                _add(topo, fit_side, slope, "-", "n_fit", post.n)
                # γ 带宽（窗几何中心处，68% 半宽相对值——报告用）
                lo68, hi68 = post.band(np.array([post.Re_c]), 0.16)
                _add(topo, fit_side, slope, "-", "gamma_band68_relhalf",
                     float((hi68[0] - lo68[0]) / (2 * post.predict(
                         np.array([post.Re_c]))[0])))

                for ev in _SIDES:
                    g = eval_sets[ev]
                    Re = g["Re"].to_numpy(float)
                    f_meas = g["f"].to_numpy(float)
                    f_cfd = g["f_cfd"].to_numpy(float)
                    pred = post.predict(Re) * f_cfd
                    _add(topo, fit_side, slope, ev, "medape",
                         _medape(pred, f_meas))
                    for q, tag in ((0.16, "cover68"), (0.025, "cover95")):
                        lo, hi = post.band(Re, q)
                        inside = ((f_meas >= lo * f_cfd)
                                  & (f_meas <= hi * f_cfd))
                        _add(topo, fit_side, slope, ev, tag,
                             float(inside.mean()))
    return pd.DataFrame(rows)


def main() -> int:
    df = run_variants()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "gamma_f_variants.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print("=" * 78)
    print("D-2sc γ_f 六变体证据包 —— f 空间 medAPE（≡ Δp medAPE，见 docstring）")
    print("=" * 78)
    for topo in _TOPOS:
        d = df[df.topo == topo]
        print(f"\n[{topo}]")
        ga = d[(d.fit == "gamma_air_ref") & (d.metric == "G0")].value.iloc[0]
        mh = d[(d.fit == "gamma_air_ref")
               & (d["eval"] == "hot") & (d.metric == "medape")].value.iloc[0]
        mc = d[(d.fit == "gamma_air_ref")
               & (d["eval"] == "cold") & (d.metric == "medape")].value.iloc[0]
        print(f"  参照 γ_air={ga:.2f}（纯粗糙度假设）:  "
              f"hot medAPE {mh:.0%} · cold {mc:.0%}   ← HX 级系统效应份额")
        hdr = (f"  {'拟合':<8}{'斜率':<6}{'Γ₀':>7}{'Δ':>8}{'σln':>7}"
               f"{'带68±':>7} | {'own':>6} {'cross':>6} | "
               f"{'hot':>6} {'cold':>6} | cov68 h/c")
        print(hdr)
        for fit_side in _FITS:
            for slope in ("free", "amp"):
                dd = d[(d.fit == fit_side) & (d.slope == slope)]
                g0 = dd[dd.metric == "G0"].value.iloc[0]
                dx = dd[dd.metric == "dexp"].value.iloc[0]
                sl = dd[dd.metric == "sigma_ln"].value.iloc[0]
                bw = dd[dd.metric == "gamma_band68_relhalf"].value.iloc[0]
                m = {ev: dd[(dd["eval"] == ev)
                            & (dd.metric == "medape")].value.iloc[0]
                     for ev in _SIDES}
                c68 = {ev: dd[(dd["eval"] == ev)
                              & (dd.metric == "cover68")].value.iloc[0]
                       for ev in _SIDES}
                if fit_side == "pooled":
                    own = 0.5 * (m["hot"] + m["cold"])
                    cross = float("nan")
                else:
                    own = m[fit_side]
                    cross = m["cold" if fit_side == "hot" else "hot"]
                cr = "   n/a" if np.isnan(cross) else f"{cross:6.0%}"
                print(f"  {fit_side:<8}{slope:<6}{g0:7.2f}{dx:+8.3f}{sl:7.3f}"
                      f"{bw:7.1%} | {own:6.0%} {cr} | "
                      f"{m['hot']:6.0%} {m['cold']:6.0%} | "
                      f"{c68['hot']:.0%}/{c68['cold']:.0%}")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
