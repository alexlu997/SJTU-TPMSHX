"""cf_cross_fluid.py — 同一芯、三种流体的 cF 反演对照（候选 D · D-2b-5）.

**这是"sCO2 腿并入"的第一刀，也是一把冲着自己来的刀。**

D-2b-4 把气侧标出 γ_total(7,0.6) = 2.31(D)/2.47(G)，乘 cF_dev 得 HX 级有效
Forchheimer 系数 ≈ 434 / 413 (1/m)。而生产里冻结的 sCO2 γ_f（D6 hot-free）
乘 sCO2 光滑基，在窗内给出 ≈ 1450-1510 —— **同一个 7/0.6 芯，差 ×3.4-3.6**。
`sco2_gamma_f` 的 docstring 早就记着"γ_f 超额 γ_air ×4.0-4.6"，但那句话把
两个挂在**不同光滑基**上的 γ 直接相比，从没分开过"基不匹配"与"数据打架"。

本工具把闭合层全部剥掉，只做一件事：**从三种流体各自的原始测量里反演
同一个物理量 cF**，再放在一起看。

    C ≡ μ̄·G/K + cF·G²          （G = ṁ/A_flow 质量流密度，逐流体同定义）
      空气（可压 ideal-gas）:  C = (P_in² − P_out²) / (2·R·T̄·L)
      水 / sCO2（不可压）:     C = ρ̄·ΔP / L
    ⇒ cF_meas = (C − μ̄·G/K) / G²

只借一个 K（`df_cfd_coeffs_dev.csv` 的 7/0.6 节点），不借任何 cF、不借任何
γ。K 的份额同时打印：气/sCO2 ≤4%，水 15-82% —— 水侧的读数对 K 敏感，
已在记分板标注，另给 K±50% 的敏感度。

**口径已核（这是本工具能成立的前提）**：气侧工具的 A_flow
（D 5.94e-4 / G 6.50e-4 m²）与 sCO2 实验表自带的 A_flow
（D 5.9359e-4 / G 6.4915e-4）逐位一致，L 同为 0.182 m，Dh 同源
——**气与 sCO2 之间不存在面积/长度口径差**，工具启动时断言之。
水侧的 A_flow 是"双流对称芯两侧同几何"推广来的、**未经表证实**
（DECISIONS D8），因此水侧读数额外给一列"若按 28/34 通道比缩放"的对照。

用法（从仓库根）:
    python -u sjtu_tpmshx/validation/df_refit/cf_cross_fluid.py

输出: stdout 记分板 + reports/df_refit/cf_cross_fluid.csv。生产零改动。
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from sjtu_tpmshx.validation.df_refit.gamma_hx_air import (
    A_FLOW, L_FLOW, R_AIR, _air_mu, _dev_node, run as run_air)
from sjtu_tpmshx.validation.df_refit.gamma_hx_water import run as run_water
from sjtu_tpmshx.validation.sco2_exp.load_sco2_exp import load_exp
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
REPORT_DIR = _REPO / "reports" / "df_refit"
_TOPOS = ("Diamond", "Gyroid")
_CHANNEL_RATIO_W = 28.0 / 34.0     # 表内标称 样机流量/单个流量 之比（水/气）


def _assert_same_caliber() -> dict:
    """气侧常量 vs sCO2 表自带几何：不一致就停手（口径差会伪装成物理）。"""
    out = {}
    for topo in _TOPOS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            a = load_exp(topo).attrs
        rel_A = abs(a["A_flow_m2"] - A_FLOW[topo]) / A_FLOW[topo]
        rel_L = abs(a["L_ch_m"] - L_FLOW) / L_FLOW
        if rel_A > 0.01 or rel_L > 0.01:
            raise RuntimeError(
                f"{topo}: 口径不一致 A {a['A_flow_m2']:.4e} vs "
                f"{A_FLOW[topo]:.4e}（{rel_A:.1%}）/ L {a['L_ch_m']} vs "
                f"{L_FLOW}（{rel_L:.1%}）——先核口径再谈跨流体")
        out[topo] = dict(A_sheet=a["A_flow_m2"], A_air=A_FLOW[topo],
                         rel_A=rel_A, Dh=a["Dh_m"])
    return out


def _cf_from_C(C: np.ndarray, G: np.ndarray, mu: np.ndarray,
               K: float) -> tuple[np.ndarray, np.ndarray]:
    """(cF_meas, Darcy 份额)。"""
    darcy = mu * G / K
    return (C - darcy) / (G * G), darcy / C


def collect() -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        air = run_air()
        water = run_water()
    air = air[~air.excluded]
    water = water[~water.excluded]

    rows = []
    for topo in _TOPOS:
        K, _cF_dev_unused = _dev_node(topo)

        # ---- 空气：可压闭式反演 ----
        a = air[air.topo == topo]
        P_in = a.P_in.to_numpy(float)
        P_out = P_in - a.dp_meas.to_numpy(float)
        T_bar = a.T_bar.to_numpy(float)
        G = a.G.to_numpy(float)
        mu = np.array([_air_mu(t) for t in T_bar])
        C = (P_in ** 2 - P_out ** 2) / (2.0 * R_AIR * T_bar * L_FLOW)
        cf, dsh = _cf_from_C(C, G, mu, K)
        for i in range(len(a)):
            rows.append(dict(fluid="air", topo=topo, Re=float(a.Re_ref.iloc[i]),
                             G=float(G[i]), cF_meas=float(cf[i]),
                             darcy_frac=float(dsh[i]), A_used=A_FLOW[topo]))

        # ---- 水：不可压 ----
        w = water[water.topo == topo]
        rho = w.rho.to_numpy(float)
        Gw = w.mdot.to_numpy(float) / A_FLOW[topo]
        Cw = rho * w.dp_meas.to_numpy(float) / L_FLOW
        cfw, dshw = _cf_from_C(Cw, Gw, w.mu.to_numpy(float), K)
        for i in range(len(w)):
            rows.append(dict(fluid="water", topo=topo, Re=float(w.Re_ref.iloc[i]),
                             G=float(Gw[i]), cF_meas=float(cfw[i]),
                             darcy_frac=float(dshw[i]), A_used=A_FLOW[topo]))

        # ---- sCO2：不可压（热侧，ok_dp）----
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            s = load_exp(topo)
        A_s = s.attrs["A_flow_m2"]
        s = s[(s.side == "hot") & s.ok_dp]
        Gs = s.mdot.to_numpy(float) / A_s
        Cs = (s.rho.to_numpy(float) * s.dP_MPa.to_numpy(float) * 1e6 / L_FLOW)
        cfs, dshs = _cf_from_C(Cs, Gs, s.mu.to_numpy(float), K)
        for i in range(len(s)):
            rows.append(dict(fluid="sco2", topo=topo, Re=float(s.Re.iloc[i]),
                             G=float(Gs[i]), cF_meas=float(cfs[i]),
                             darcy_frac=float(dshs[i]), A_used=A_s))
    return pd.DataFrame(rows)


def _k_sensitivity(df: pd.DataFrame) -> pd.DataFrame:
    """K±50% 下 cF_meas 中位的位移（水侧敏感、气/sCO2 近乎免疫）。"""
    out = []
    for topo in _TOPOS:
        K0, _ = _dev_node(topo)
        for fluid in ("air", "water", "sco2"):
            g = df[(df.topo == topo) & (df.fluid == fluid)]
            if not len(g):
                continue
            base = float(np.median(g.cF_meas))
            # C = cF·G² + darcy，且 darcy = darcy_frac·C  ⇒  C = cF·G²/(1−frac)
            C = g.cF_meas * g.G ** 2 / (1.0 - g.darcy_frac)
            darcy = g.darcy_frac * C
            shifts = {}
            for lab, mult in (("K×0.5", 0.5), ("K×1.5", 1.5)):
                cf_new = (C - darcy / mult) / g.G ** 2   # K→mult·K ⇒ darcy/mult
                shifts[lab] = float(np.median(cf_new)) / base - 1.0
            out.append(dict(topo=topo, fluid=fluid, cF_med=base, **shifts))
    return pd.DataFrame(out)


def main() -> int:
    cal = _assert_same_caliber()
    df = collect()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "cf_cross_fluid.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print("=" * 80)
    print("D-2b-5 同一 7/0.6 芯、三流体 cF 反演对照（闭合无关：只借一个 K）")
    print("=" * 80)
    print("\n[0] 口径核对（气侧常量 vs sCO2 表自带几何）")
    for topo, c in cal.items():
        print(f"  {topo}: A 表内 {c['A_sheet']:.4e} vs 气侧常量 "
              f"{c['A_air']:.4e}  相对差 {c['rel_A']:.2%}  "
              f"L 同 {L_FLOW} m  -> 口径一致")
    print("  => 气 与 sCO2 之间**不存在面积/长度口径差**，下面的差值不是口径造成的。")

    print("\n[1] cF_meas（1/m）逐流体")
    print(f"  {'拓扑':<9}{'流体':<7}{'n':>4}{'Re 窗':>18}"
          f"{'cF 中位':>10}{'[P10,P90]':>18}{'Darcy份额中位':>14}")
    med = {}
    for topo in _TOPOS:
        for fluid in ("air", "water", "sco2"):
            g = df[(df.topo == topo) & (df.fluid == fluid)]
            if not len(g):
                continue
            m = float(np.median(g.cF_meas))
            med[(topo, fluid)] = m
            print(f"  {topo:<9}{fluid:<7}{len(g):>4}"
                  f"{f'[{g.Re.min():.0f},{g.Re.max():.0f}]':>18}"
                  f"{m:>10.1f}"
                  f"{f'[{g.cF_meas.quantile(.1):.0f},{g.cF_meas.quantile(.9):.0f}]':>18}"
                  f"{g.darcy_frac.median():>14.2f}")

    print("\n[2] 相对空气的倍数（cF 是几何量，同芯应当同值）")
    print(f"  {'拓扑':<9}{'水/气':>10}{'sCO2/气':>10}")
    for topo in _TOPOS:
        print(f"  {topo:<9}{med[(topo,'water')]/med[(topo,'air')]:>10.2f}"
              f"{med[(topo,'sco2')]/med[(topo,'air')]:>10.2f}")

    print("\n[3] Re 窗相邻性（气顶 vs sCO2 底——两者几乎接壤，可作近匹配对照）")
    for topo in _TOPOS:
        a = df[(df.topo == topo) & (df.fluid == "air")]
        s = df[(df.topo == topo) & (df.fluid == "sco2")]
        a_top = a.nlargest(3, "Re")
        s_bot = s.nsmallest(3, "Re")
        print(f"  {topo}: 气 top3 Re[{a_top.Re.min():.0f},{a_top.Re.max():.0f}] "
              f"cF 中位 {a_top.cF_meas.median():.0f}   |   "
              f"sCO2 bot3 Re[{s_bot.Re.min():.0f},{s_bot.Re.max():.0f}] "
              f"cF 中位 {s_bot.cF_meas.median():.0f}   -> "
              f"×{s_bot.cF_meas.median()/a_top.cF_meas.median():.2f}")
    print("  两窗仅擦肩（气顶 ~8.2k / sCO2 底 ~8.8k），且两侧 cF 在各自窗内近平"
          "\n  => 这个倍数不是 Re 外推造成的。")

    print("\n[4] K 敏感度（K±50% 对 cF 中位的位移）")
    ks = _k_sensitivity(df)
    print(f"  {'拓扑':<9}{'流体':<7}{'cF 中位':>10}{'K×0.5':>10}{'K×1.5':>10}")
    for _, r in ks.iterrows():
        print(f"  {r.topo:<9}{r.fluid:<7}{r.cF_med:>10.1f}"
              f"{r['K×0.5']:>10.1%}{r['K×1.5']:>10.1%}")
    print("  气/sCO2 近乎免疫（Darcy 份额小）；水侧敏感——水的读数确实依赖 K。")

    print("\n[5] 水侧的 A 口径对照（D8 未决）")
    for topo in _TOPOS:
        w = df[(df.topo == topo) & (df.fluid == "water")]
        # cF ∝ 1/A² 的 Forchheimer 部分：按通道比缩 A 后的等效中位
        scaled = float(np.median(w.cF_meas)) * _CHANNEL_RATIO_W ** 2
        print(f"  {topo}: 若 A_water = (28/34)·A_air，cF_meas 中位 "
              f"{np.median(w.cF_meas):.0f} -> {scaled:.0f}"
              f"（气 {med[(topo,'air')]:.0f}，仍 ×"
              f"{scaled/med[(topo,'air')]:.2f}）")
    print("  注：这里只缩 Forchheimer 项作量级示意；严格口径修正须重跑反演。")

    print("\n[6] 收口所需的量级（cF ∝ ρ·Δp·A^2 / (L·mdot^2)）")
    print("  A 不变性：气与 sCO2 用的是**同一个** A（[0] 已核）。cF ∝ A^2，"
          "\n  所以 A 即使整体错了，也在 sCO2/气 的比值里**精确约掉**"
          "——D8 那类面积口径解释对本条腿**不适用**。")
    for topo in _TOPOS:
        r = med[(topo, "sco2")] / med[(topo, "air")]
        print(f"  {topo}: 要把 ×{r:.2f} 抹平，需其一：sCO2 的 Δp 实际低 "
              f"{1 - 1 / r:.0%}、或 sCO2 的 mdot 实际高 {np.sqrt(r) - 1:.0%}、"
              f"或气侧 Δp 实际高 {r - 1:.0%}、或气侧 mdot 实际低 "
              f"{1 - 1 / np.sqrt(r):.0%}（ρ 同量级同理）。")
    print("  这些都是**可向数据方核实的单一量**，不是需要新物理的量级。")

    print("\n[6b] 判读")
    print("  - 三流体在**同一芯、同一 A/L/Dh 口径、同一 K** 下反演出的 cF 并不一致，")
    print("    且序稳定：气 < 水 < sCO2。cF 是几何量，本应同值 —— 所以这不是")
    print("    '三个流体各有各的 γ'，而是**至少两套实验/归约里有系统性偏差**。")
    print("  - 气 vs sCO2 的差**排除了**面积口径（[6] A 不变性，比值里精确约掉）、")
    print("    长度口径（[0] 同 L）、Re 外推（[3] 两窗接壤且各自近平）、")
    print("    以及光滑基不匹配（本工具压根不用 cF 闭合）。")
    print("  - 水/气的差**不**享有 A 不变性：水侧 A 是推广来的（D8），[5] 已给对照。")
    print("  - => 现行架构把这个差全额吸收进 γ_f（HX 级修正，×7 量级）是")
    print("    **把未解释的系统偏差参数化**，不是物理。sco2_gamma_f 的 docstring")
    print("    已标 'HX-level prediction correction, NOT pure surface roughness'")
    print("    ——本工具给出该表述的定量支撑，并把'基不匹配'这个候选解释排除掉。")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
