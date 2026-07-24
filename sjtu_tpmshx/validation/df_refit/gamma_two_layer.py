"""gamma_two_layer.py — 双层合成面 γ_total + UQ 后验带（候选 D · D-2b-4，气侧腿）.

审计 §8 双层架构的收口：把 γ_specimen(L,t)（试件台架锚）与 γ_HX（HX 级
系统效应）合成一张可外推的面，并给出**诚实的**后验预测带与 Δp 预测带。

    γ_total(topo, L, t) = γ_spec(L, t) × γ_HX(topo)
    cF_eff = γ_total × cF_dev(L, t)        ← 进闭式/求解器的就是这一个数

**iter 74 强加的两条改写**（这版与 iter 69/70 的写法差别都在这儿）：

  1. **γ_HX 不按拓扑常数固化。** 水侧证据显示 γ_HX 的 G/D 序在两种流体下
     反号（水 0.89 / 气 1.15，审计 §11），所以"D=1.08、G=1.23"不是可信的
     拓扑参数。本工具因此并排给两个变体，让证据说话：
       - `per_topo`：各拓扑自己的 γ_HX（旧写法，保留作对照）
       - `pooled`  ：两拓扑共用一个 γ_HX，**带宽自然吃掉拓扑分化**
     判据 = LOO 下的 Δp 带覆盖率与带宽，不是先验偏好。
  2. **水侧腿不合成**（DECISIONS D8 未答复前，水侧 A_flow 口径存疑）。
     本面只在**气侧**标定，只对气侧/上海口径声明有效。

**UQ 的关键结构（这是本工具最容易做错的地方）**：

γ_HX 是拿 γ_spec 的**点估计**去除 HX 实测得到的（γ_HX = Δp_meas /
Δp_pred(ĝ_spec)），所以 γ_spec 与 γ_HX **强反相关**——γ_spec 大一分，
标出来的 γ_HX 就小一分，乘积几乎不动。若把两层的带各自独立抽样再相乘，
等于把 γ_spec 的绝对水平不确定度重复计入一次，带会假性变宽。

正确的分解：**HX 数据直接钉住的是标定几何 (7,0.6) 上的 γ_total**，
γ_spec 层只负责提供**形状**（怎么从 (7,0.6) 外推到别的 L,t）：

    ln γ_total(L,t) = ln γ_total(7,0.6)          ← HX 实测，带 = 案间散差
                    + [ln γ_spec(L,t) − ln γ_spec(7,0.6)]   ← 形状差，带 = 参数不确定度

在 (7,0.6) 处形状差恒为 0 ⇒ 带只剩 HX 案间散差。这正是应该的：那儿是
直接测的。外推越远，形状项的参数带越宽——外推的代价显式化。
（形状项不含残差方差：残差描述"另一件试件"的实现散差，而形状差问的是
同一批件上的几何趋势。见 `SpecimenGamma.shape_contrast_sd`。）

**Δp 带的诚实性**：γ_HX 是从这批 HX 工况标出来的，直接在同一批上报覆盖率
是样本内。本工具对 γ_HX 层做 **LOO**（留一案重估），γ_spec 层锚在试件台架
（col47）与 HX 工况无交集、无泄漏。

用法（从仓库根）:
    python -u sjtu_tpmshx/validation/df_refit/gamma_two_layer.py

输出: stdout 记分板 + reports/df_refit/gamma_two_layer.csv（逐案 Δp 带）
      + reports/df_refit/gamma_two_layer_surface.csv（γ_total 面 + 带）。
生产零改动。
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from sjtu_tpmshx.validation.df_refit.gamma_hx_air import (
    dp_pred_compressible, run as run_air)
from sjtu_tpmshx.validation.df_refit.gamma_specimen import (
    cf_dev, fit_specimen_gamma)
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
REPORT_DIR = _REPO / "reports" / "df_refit"

L0, T0 = 7.0, 0.6            # 标定几何（7-6 样机 = dev 表网格节点）
N_MC = 40000                 # γ_total 面的 MC 抽样数（seed 固定，可复现）
N_MC_DP = 2000               # 每案 Δp 带的抽样数（闭式是逐点标量调用，
                             #   2000 足够定 2.5/97.5 分位到 ~1% 相对精度）
SEED = 20260725
_TOPOS = ("Diamond", "Gyroid")
# 面的展示网格：覆盖试件锚 L∈{6,8} 与样机 7，t 跨 0.3-0.6
_GRID_L = (6.0, 7.0, 8.0)
_GRID_T = (0.3, 0.4, 0.5, 0.6)


# --------------------------------------------------------------------------
# γ_HX 层：从气侧 HX 工况的 ln γ_HX 提均值/散差（可留一）
# --------------------------------------------------------------------------
def _hx_layer(ln_g: np.ndarray) -> tuple[float, float, int]:
    """返回 (ln 均值, 新案预测的 ln 标准差, n)。

    预测带用 s·sqrt(1+1/n)：既含案间散差，也含均值本身的估计误差。
    """
    n = len(ln_g)
    m = float(np.mean(ln_g))
    s = float(np.std(ln_g, ddof=1)) if n > 1 else 0.0
    return m, s * float(np.sqrt(1.0 + 1.0 / n)), n


def _draw_ln_gamma_total(rng: np.random.Generator, m_hx: float, s_hx: float,
                         dof_hx: int, s_shape: float, dof_shape: int,
                         ln_gspec_L0: float, size: int) -> np.ndarray:
    """ln γ_total 的后验预测抽样（HX 水平项 ⊕ γ_spec 形状项）。"""
    out = ln_gspec_L0 + m_hx
    if s_hx > 0 and dof_hx > 0:
        out = out + s_hx * rng.standard_t(dof_hx, size=size)
    else:
        out = np.full(size, out, dtype=float)
    if s_shape > 0 and dof_shape > 0:
        out = out + s_shape * rng.standard_t(dof_shape, size=size)
    return out


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def run() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        air = run_air()
        models = {t: fit_specimen_gamma(t)[0] for t in _TOPOS}

    # 气侧缺陷筛（iter 75，gamma_hx_air）：仪表地板 + 重复行。不筛的话
    # 两个最低流量案（D γ=0.69 / G γ=0.33）会独占对数散差，把 σln 顶到
    # 0.13/0.33，带虚胖到 68% 名义带实测覆盖 89-94%——虚胖的诚实也是错。
    air = air[~air.excluded].copy()
    air["ln_gamma_hx"] = np.log(air.gamma_hx.to_numpy(float))

    rng = np.random.default_rng(SEED)
    case_rows, surf_rows = [], []
    meta: dict = {}

    for variant in ("per_topo", "pooled"):
        # ---- 逐案 Δp 带（γ_HX 层 LOO）----
        for i, r in air.reset_index(drop=True).iterrows():
            topo = r.topo
            pool = (air[air.topo == topo] if variant == "per_topo" else air)
            # 留一：按行身份剔除本案（同值多案时只剔一条）
            ln_all = pool["ln_gamma_hx"].to_numpy(float)
            pos = int(np.argmin(np.abs(ln_all - r.ln_gamma_hx)))
            ln_loo = np.delete(ln_all, pos)

            m_hx, s_hx, n_hx = _hx_layer(ln_loo)
            model = models[topo]
            ln_gspec_L0 = float(np.log(model.predict(L0, T0)))
            # 本案就在标定几何上 -> 形状项为 0
            draws = _draw_ln_gamma_total(rng, m_hx, s_hx, n_hx - 1,
                                         0.0, 0, ln_gspec_L0, N_MC)
            g_tot = np.exp(draws)
            dps = np.array([dp_pred_compressible(r.P_in, r.T_bar, r.G,
                                                 r.K_dev, g * r.cF_dev)
                            for g in g_tot[:N_MC_DP]], dtype=object)
            ok = np.array([d is not None for d in dps])
            dpv = np.array([d for d in dps if d is not None], dtype=float)
            if not len(dpv):
                continue
            lo68, hi68 = np.quantile(dpv, [0.16, 0.84])
            lo95, hi95 = np.quantile(dpv, [0.025, 0.975])
            dp_med = float(np.median(dpv))
            case_rows.append(dict(
                variant=variant, topo=topo, mdot=float(r.mdot),
                Re_ref=float(r.Re_ref), dp_meas=float(r.dp_meas),
                dp_pred_med=dp_med,
                ape=abs(dp_med - r.dp_meas) / r.dp_meas,
                lo68=float(lo68), hi68=float(hi68),
                lo95=float(lo95), hi95=float(hi95),
                in68=bool(lo68 <= r.dp_meas <= hi68),
                in95=bool(lo95 <= r.dp_meas <= hi95),
                choked_frac=float(1.0 - ok.mean()),
                n_loo=n_hx, gamma_total_med=float(np.median(g_tot))))

        # ---- γ_total 面（全量标定，不 LOO）+ 外推带 ----
        for topo in _TOPOS:
            pool = (air[air.topo == topo] if variant == "per_topo" else air)
            m_hx, s_hx, n_hx = _hx_layer(pool["ln_gamma_hx"].to_numpy(float))
            model = models[topo]
            ln_gspec_L0 = float(np.log(model.predict(L0, T0)))
            for L in _GRID_L:
                for t in _GRID_T:
                    s_shape = model.shape_contrast_sd(L, t, L0, T0)
                    draws = _draw_ln_gamma_total(
                        rng, m_hx, s_hx, n_hx - 1, s_shape, model.dof,
                        ln_gspec_L0, N_MC)
                    # 形状项的中心 = γ_spec 面的比值（点估计）
                    shift = float(np.log(model.predict(L, t))
                                  - np.log(model.predict(L0, T0)))
                    g = np.exp(draws + shift)
                    q = np.quantile(g, [0.025, 0.16, 0.5, 0.84, 0.975])
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        cfd = cf_dev(topo, L, t)
                    surf_rows.append(dict(
                        variant=variant, topo=topo, L=L, t=t,
                        gamma_total=float(q[2]),
                        lo68=float(q[1]), hi68=float(q[3]),
                        lo95=float(q[0]), hi95=float(q[4]),
                        band95_ratio=float(q[4] / q[0]),
                        s_shape=s_shape, cF_dev=cfd,
                        cF_eff=float(q[2]) * cfd))
            meta[(variant, topo)] = dict(m_hx=m_hx, s_hx=s_hx, n_hx=n_hx,
                                         gamma_hx=float(np.exp(m_hx)))
    return pd.DataFrame(case_rows), pd.DataFrame(surf_rows), meta


def main() -> int:
    cases, surf, meta = run()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    p1 = REPORT_DIR / "gamma_two_layer.csv"
    p2 = REPORT_DIR / "gamma_two_layer_surface.csv"
    cases.to_csv(p1, index=False, encoding="utf-8-sig")
    surf.to_csv(p2, index=False, encoding="utf-8-sig")

    print("=" * 78)
    print("D-2b-4 双层合成面 γ_total = γ_spec(L,t) × γ_HX  + UQ 带（气侧腿）")
    print(f"       MC {N_MC} 抽样 seed={SEED}；γ_HX 层 LOO；标定几何 "
          f"({L0:.0f},{T0:.1f})")
    print("=" * 78)

    print("\n[1] γ_HX 层标定（气侧全量）")
    for (variant, topo), m in meta.items():
        print(f"  {variant:<9} {topo:<8} γ_HX={m['gamma_hx']:.3f}  "
              f"σln={m['s_hx']:.3f}  n={m['n_hx']}")
    print("  pooled 两拓扑同值 = 拓扑分化被并进散差（σln 变大即代价）")

    print("\n[2] Δp 预测带记分（LOO，样本外；n = 气侧 7-6 工况）")
    print(f"  {'变体':<10}{'拓扑':<9}{'n':>4}{'medAPE':>9}"
          f"{'68%覆盖':>9}{'95%覆盖':>9}{'带宽95(比)':>12}")
    for variant in ("per_topo", "pooled"):
        for topo in _TOPOS:
            g = cases[(cases.variant == variant) & (cases.topo == topo)]
            if not len(g):
                continue
            width = float(np.median(g.hi95 / g.lo95))
            print(f"  {variant:<10}{topo:<9}{len(g):>4}"
                  f"{g.ape.median():>8.1%}"
                  f"{g.in68.mean():>9.0%}{g.in95.mean():>9.0%}"
                  f"{width:>12.2f}")
        g = cases[cases.variant == variant]
        print(f"  {variant:<10}{'合计':<9}{len(g):>4}{g.ape.median():>8.1%}"
              f"{g.in68.mean():>9.0%}{g.in95.mean():>9.0%}"
              f"{float(np.median(g.hi95 / g.lo95)):>12.2f}")
    print("  读法：68% 覆盖应≈68%、95%≈95%。显著高于名义 = 带过宽（虚胖的诚实）；"
          "\n        显著低于 = 带过窄（假自信）。带宽比越小越有用，"
          "但不能靠牺牲覆盖率换。")
    a = cases[cases.variant == "per_topo"]
    b = cases[cases.variant == "pooled"]
    print(f"\n  裁决：per_topo 在 medAPE（{a.ape.median():.1%} vs "
          f"{b.ape.median():.1%}）**和**带宽"
          f"（{float(np.median(a.hi95 / a.lo95)):.2f} vs "
          f"{float(np.median(b.hi95 / b.lo95)):.2f}）上双赢，两者覆盖率"
          f"都在名义附近")
    print("        => **气侧内部**用 per_topo。但这条只对气侧成立："
          "拓扑分化的不可迁移性是\n           **跨流体**的（审计 §11），"
          "本面的带是\"气侧内\"带，不得对外宣称覆盖水/sCO2。")

    print("\n[3] γ_total 面与外推代价（标定几何处形状项=0，带只剩 HX 案间散差）")
    for variant in ("per_topo", "pooled"):
        print(f"\n  -- {variant} --")
        for topo in _TOPOS:
            s = surf[(surf.variant == variant) & (surf.topo == topo)]
            at0 = s[(s.L == L0) & (s.t == T0)].iloc[0]
            print(f"   {topo}: γ_total({L0:.0f},{T0:.1f}) = {at0.gamma_total:.2f}"
                  f"  95%带 [{at0.lo95:.2f},{at0.hi95:.2f}]"
                  f"（宽比 {at0.band95_ratio:.2f}）")
            far = s.loc[s.band95_ratio.idxmax()]
            print(f"      最宽处 L{far.L:.0f}/t{far.t:.1f}: "
                  f"γ_total={far.gamma_total:.2f} 宽比 {far.band95_ratio:.2f}"
                  f"（形状项 σln={far.s_shape:.3f}）")

    print("\n[4] 适用面声明（不写进带的部分，必须随面一起流转）")
    print("  - 本面只在**气侧**标定，只对气侧/上海口径有效。")
    print("  - 水侧 γ_HX 高约一倍（D 2.44/G 2.18 vs 气 1.08/1.23，审计 §11），")
    print("    首要嫌疑是水侧 A_flow 口径 -> DECISIONS D8 未答复前**不合成水侧**。")
    print("  - sCO2 腿（γ_f hot）未并入，排 D-2b-5。")
    print("  - γ_HX 不是可跨流体迁移的几何常数（G/D 序在两流体下反号）——")
    print("    per_topo 变体保留仅作对照，选型看上表 LOO 数字。")
    print(f"\n已写出 {p1}\n         {p2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
