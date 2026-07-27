"""gamma_hx_air.py — γ_HX 气侧提取（候选 D · D-2b-2，2026-07-22）.

审计 §8 双层架构第二层的第一块数据：7-6 样机 HX 级**空气侧**压损实验
（D_7_6: 20260609-水直空气侧 Sheet1，18 工况；G_7_6: 20260407-调换进出口
Sheet1，实测行）。上海 16 例零参与。

口径调和（任务 3.1 的气侧部分，本工具落地）：
  - 通道数约定：表内 样机流量/单个流量 ≈ 34（气）/28（水）——但归约用
    **整机 A_flow**（与 sCO2 载荷同源：D-7-6 工作簿 流通截面积 5.94e-4 m²，
    双流对称芯两侧同几何），u = ṁ_样机/(ρ·A_flow) 为间隙流速，通道数
    只是歧管设计信息不进公式；G 表自带 密度/速度 列反推 A_flux 作自洽核。
  - 压力为表压（进口 0.5-55 kPa 量级），P_abs = 101325 + gauge。
  - 高流量端 Δp/P_abs 达 0.2-0.3 ⇒ 预测必须用可压缩 1D 闭式
    （P_out² = P_in² − 2·R·T̄·C·L，C = μ(T̄)·G/K + γ_spec·cF_dev·G²，
    G = ṁ/A_flow 质量流密度，水平无关）。
  - 几何 7/0.6 恰为 dev 表网格节点——cF_dev/K_dev 直取，零插值。

γ_HX(case) ≜ Δp_meas / Δp_pred(γ_specimen-only)：>1 的部分就是试件层
装不下的 HX 级系统效应（歧管/入口/分配），iter 69 已证 G 侧统计必需。

用法（从仓库根）:
    python -u sjtu_tpmshx/validation/df_refit/gamma_hx_air.py

输出: stdout 记分板 + reports/df_refit/gamma_hx_air.csv。生产零改动。
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from sjtu_tpmshx.validation.df_refit.gamma_specimen import fit_specimen_gamma
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
_DEV_CSV = (_REPO / "sjtu_tpmshx" / "df_surrogate" / "_prebuilt"
            / "df_cfd_coeffs_dev.csv")
REPORT_DIR = _REPO / "reports" / "df_refit"

R_AIR = 287.05
P_ATM = 101325.0
L_FLOW = 0.182                    # 流道长度 m（D-7-6 工作簿 B 列，7-6 同芯）
# 整机每侧流通面积 = ε_side × 迎风面积（42×42mm=1.764e-3 m²）——三方自洽：
#   Diamond 5.94e-4（D-7-6 工作簿 D 列实测值；0.3373×1.764e-3=5.95e-4 ✓）
#   Gyroid  6.50e-4（G 表 密度/速度 列反推恒定值；0.3684×1.764e-3=6.50e-4 ✓）
# 首版曾给 G 误用 D 值（差 ×1.094 ⇒ Forchheimer 项 ×1.20），已纠。
A_FLOW = {"Diamond": 5.94e-4, "Gyroid": 6.50e-4}

_BOOKS = {
    "Diamond": ("20260609-水直空气侧-D_7_6.xlsx", "Sheet1"),
    "Gyroid": ("20260407-上海电气天然气加热器实验工况 -调换进出口-G_7_6.xlsx",
               "Sheet1"),
}
_NEED = ["样机空气流量kg/s", "空气进口温度/℃", "空气出口温度/℃",
         "空气进口压力/Pa", "空气出口压力/Pa"]

# 仪表地板筛（iter 75 补）：两表的**最低流量工况**都远离 γ_HX 平台
#   D 工况1 Δp=893 Pa γ=0.69 / G 工况1 Δp=336 Pa γ=0.33，
#   而次低点已是 4474 / 3925 Pa（γ 1.02 / 1.16）。阈值落在 (893, 3925) Pa
#   这段宽空隙里取任意值结果都不变——2000 取其中段，非刀刃阈值。
#   水侧同类缺陷（G 工况1 Δp=−48.4 Pa 负压差）见 gamma_hx_water。
DP_FLOOR_PA = 2000.0


def _air_mu(T_K: float) -> float:
    """Sutherland（与求解器 air_viscosity 同式，避免拖 solver 依赖）。"""
    return 1.716e-5 * (T_K / 273.15) ** 1.5 * (273.15 + 110.4) / (T_K + 110.4)


def _load_cases(topo: str) -> pd.DataFrame:
    book, sheet = _BOOKS[topo]
    d = pd.read_excel(_REPO / "data" / "raw_data" / book,
                      sheet_name=sheet, header=1)
    missing = [c for c in _NEED if c not in d.columns]
    if missing:
        raise RuntimeError(f"{topo}: 列缺失 {missing} —— 表版式变了，重核列图")
    d = d[d.iloc[:, 0].astype(str).str.startswith("工况")].copy()
    d = d.dropna(subset=_NEED)
    d = d[(d["样机空气流量kg/s"] > 0)
          & (d["空气进口压力/Pa"] > d["空气出口压力/Pa"])]
    d = d.reset_index(drop=True)
    d["case"] = d.iloc[:, 0].astype(str)
    dp = d["空气进口压力/Pa"] - d["空气出口压力/Pa"]
    # 缺陷 1：仪表地板（最低流量端）
    d["dp_floor"] = dp < DP_FLOOR_PA
    # 缺陷 2：除 ṁ 外逐位重复的行——D_7_6 气表 工况10/11 与**同一样机的水表
    # 同名工况**同址复现（gamma_hx_water 已记），两表同源复制粘贴，其一必错
    key = ["空气进口温度/℃", "空气出口温度/℃",
           "空气进口压力/Pa", "空气出口压力/Pa"]
    d["dup_row"] = d.duplicated(subset=key, keep=False)
    d["excluded"] = d.dp_floor | d.dup_row
    return d


def dp_pred_compressible(P_in: float, T_bar: float, G: float, K: float,
                         cF_eff: float, L: float = L_FLOW) -> float | None:
    """可压 1D 闭式 Δp：P_out² = P_in² − 2·R·T̄·(μG/K + cF_eff·G²)·L。

    `cF_eff` 已含 γ（γ_spec 或双层 γ_total）——调用方决定乘几层。
    返回 None = P_out² ≤ 0（谱外/窒息，无稳态解，不可"返回个数字"）。
    """
    C = _air_mu(T_bar) * G / K + cF_eff * G * G
    P_out_sq = P_in ** 2 - 2.0 * R_AIR * T_bar * C * L
    if P_out_sq <= 0:
        return None
    return P_in - float(np.sqrt(P_out_sq))


def _dev_node(topo: str) -> tuple[float, float]:
    dev = pd.read_csv(_DEV_CSV)
    r = dev[(dev.tp == topo) & np.isclose(dev.L, 7.0)
            & np.isclose(dev.t, 0.6)]
    if not len(r):
        raise RuntimeError(f"{topo}: dev 表缺 7/0.6 节点")
    return float(r.K.iloc[0]), float(r.cF.iloc[0])


def run() -> pd.DataFrame:
    rows = []
    for topo in _BOOKS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model, _ = fit_specimen_gamma(topo)
        g_spec = model.predict(7.0, 0.6)
        K_dev, cF_dev = _dev_node(topo)
        d = _load_cases(topo)
        for _, r in d.iterrows():
            mdot = float(r["样机空气流量kg/s"])
            T_in = float(r["空气进口温度/℃"]) + 273.15
            T_out = float(r["空气出口温度/℃"]) + 273.15
            T_bar = 0.5 * (T_in + T_out)
            P_in = P_ATM + float(r["空气进口压力/Pa"])
            dp_meas = (float(r["空气进口压力/Pa"])
                       - float(r["空气出口压力/Pa"]))
            G = mdot / A_FLOW[topo]
            mu = _air_mu(T_bar)
            dp_pred = dp_pred_compressible(P_in, T_bar, G, K_dev,
                                           g_spec * cF_dev)
            if dp_pred is None:
                continue                     # 谱外点不进带
            rho_in = P_in / (R_AIR * T_in)
            Re_in = G * (2 * 1.2995e-3) / mu   # Dh(D7/0.6)≈2.599mm 量级参考
            rows.append(dict(
                topo=topo, mdot=mdot, Re_ref=Re_in,
                dp_meas=dp_meas, dp_pred_spec=dp_pred,
                gamma_hx=dp_meas / dp_pred,
                dp_over_pabs=dp_meas / P_in,
                u_in=G / rho_in, g_spec=g_spec,
                # 下游（gamma_two_layer）复算 Δp 需要的输入，不改任何既有列
                P_in=P_in, T_bar=T_bar, G=G, K_dev=K_dev, cF_dev=cF_dev,
                case=str(r.case), dp_floor=bool(r.dp_floor),
                dup_row=bool(r.dup_row), excluded=bool(r.excluded)))
    return pd.DataFrame(rows)


def main() -> int:
    df = run()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "gamma_hx_air.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print("=" * 74)
    print("D-2b-2 γ_HX 气侧提取（7-6 HX 实验 ÷ 试件层闭式预测，可压缩 1D）")
    print("=" * 74)
    for topo, g_all in df.groupby("topo"):
        g = g_all[~g_all.excluded]
        gs = g.gamma_hx
        print(f"\n[{topo}]  n={len(g)}（原表 {len(g_all)}，剔 "
              f"{int(g_all.excluded.sum())}：仪表地板 "
              f"{int(g_all.dp_floor.sum())} / 重复行 "
              f"{int(g_all.dup_row.sum())}）"
              f"  γ_spec(7,0.6)={g.g_spec.iloc[0]:.2f}"
              f"  Δp/P_abs 范围 [{g.dp_over_pabs.min():.2f},"
              f"{g.dp_over_pabs.max():.2f}]")
        for _, rr in g_all[g_all.excluded].iterrows():
            tag = "仪表地板" if rr.dp_floor else "重复行"
            print(f"    [剔] {rr.case} {tag}: mdot={rr.mdot:.5f} "
                  f"Δp={rr.dp_meas:.0f} -> γ={rr.gamma_hx:.2f}")
        print(f"  γ_HX: 中位 {gs.median():.2f}  [P10,P90]=[{gs.quantile(.1):.2f},"
              f"{gs.quantile(.9):.2f}]  min/max [{gs.min():.2f},{gs.max():.2f}]")
        lo = g[g.mdot <= g.mdot.median()]
        hi = g[g.mdot > g.mdot.median()]
        print(f"  流量分半: 低半中位 {lo.gamma_hx.median():.2f} / "
              f"高半中位 {hi.gamma_hx.median():.2f}"
              f"   (平 => 幅值制; 斜 => 需 γ_HX(Re))")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
