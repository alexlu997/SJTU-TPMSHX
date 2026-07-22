"""gamma_specimen.py — 纯试件 γ 候选面（候选 D · D-2b-1，2026-07-22）.

审计 §8 双层架构的第一层：

    γ_specimen(topo, L, t)  —— 只锚 SLM 试件台架（col47，闭式反演，可信层
    L∈{6,8}——iter 68 平反后不变），基 = dev 发展段两段法 CFD 面
    （D-2a 候选，cF_dev）。上海 16 与任何 HX 级实验都不进本层。

模型（每拓扑，贝叶斯线性，Jeffreys 先验，解析后验）：

    ln γ = a_L + b·(t − 0.4)        锚点 6 个（2 层 × 3 t），参数 3 个
    （a_L6, a_L8, b 跨层池化——单层 n=3 拟 2 参自由度太薄，池化换诚实带宽；
    gamma_df v4 的共享曲率同理但曲率项在 n=6 下不可辨识，v1 弃）
    L 方向：ln γ 在 (ln L6, a_L6)→(ln L8, a_L8) 对数线性内插/外推，
    L≤5 沿 v4 flat6 约定截平（γ(L≤5)=γ(L6)，声明带不作物理宣称）

对照组产出（架构提案 §8 的定量缺口表）：γ_specimen(7, 0.6) 的后验带 vs
HX 级需要值 γ_HX_needed = cF_HX_exp / cF_dev(7, 0.6)（G：上海标定 534.8；
D：D_7_6 桥接参照 454.2——均为 HX 级口径，仅作缺口读数不进拟合）。

用法（从仓库根）:
    python -u sjtu_tpmshx/validation/df_refit/gamma_specimen.py

输出: stdout 记分板 + reports/df_refit/gamma_specimen.csv。生产零改动。
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.interpolate import RBFInterpolator

from sjtu_tpmshx.df_surrogate.surrogate_v3 import SurrogateV3
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
_DEV_CSV = (_REPO / "sjtu_tpmshx" / "df_surrogate" / "_prebuilt"
            / "df_cfd_coeffs_dev.csv")
REPORT_DIR = _REPO / "reports" / "df_refit"

_TRUSTED_L = (6.0, 8.0)
_T_CENTER = 0.4
# HX 级需要值（缺口读数专用，不进拟合）：HX 口径 cF_exp（G=上海标定，
# D=D_7_6 桥接参照，见 gamma_df docstring scoreboard）
_HX_CF_EXP = {"Gyroid": 534.8, "Diamond": 454.2}


def _dev_cf_surface(topo: str) -> RBFInterpolator:
    dev = pd.read_csv(_DEV_CSV)
    g = dev[dev.tp == topo]
    pts = np.log(np.column_stack([g.L.to_numpy(float), g.t.to_numpy(float)]))
    return RBFInterpolator(pts, np.log(g.cF.to_numpy(float)),
                           kernel="thin_plate_spline")


def cf_dev(topo: str, L: float, t: float,
           surf: RBFInterpolator | None = None) -> float:
    surf = surf if surf is not None else _dev_cf_surface(topo)
    return float(np.exp(surf(np.log([[L, t]]))[0]))


@dataclass
class SpecimenGamma:
    """每拓扑的 γ_specimen 后验（a_L6, a_L8, b 池化 t 斜率）。"""
    topo: str
    a: dict[float, float]          # ln γ at t=0.4 per trusted L
    b: float                       # pooled t-slope (per mm)
    s2: float                      # 残差方差（无偏）
    XtX_inv: np.ndarray            # 3×3（参数序 [a6, a8, b]）
    dof: int
    n: int

    def _design_row(self, L: float, t: float) -> np.ndarray:
        lnL6, lnL8 = np.log(_TRUSTED_L[0]), np.log(_TRUSTED_L[1])
        lam = (np.log(max(L, _TRUSTED_L[0])) - lnL6) / (lnL8 - lnL6)
        lam = float(np.clip(lam, 0.0, 1.0))       # flat6 + L8 截平（声明带）
        return np.array([1.0 - lam, lam, t - _T_CENTER])

    def predict(self, L: float, t: float) -> float:
        x = self._design_row(L, t)
        beta = np.array([self.a[_TRUSTED_L[0]], self.a[_TRUSTED_L[1]], self.b])
        return float(np.exp(x @ beta))

    def band(self, L: float, t: float, q: float = 0.16
             ) -> tuple[float, float]:
        """γ 的中心 (1−2q) 后验预测带（含参数与残差不确定度）。"""
        x = self._design_row(L, t)
        beta = np.array([self.a[_TRUSTED_L[0]], self.a[_TRUSTED_L[1]], self.b])
        mid = float(x @ beta)
        s_pred = float(np.sqrt(self.s2 * (1.0 + x @ self.XtX_inv @ x)))
        tq = float(stats.t.ppf(1.0 - q, self.dof))
        return float(np.exp(mid - tq * s_pred)), float(np.exp(mid + tq * s_pred))


def fit_specimen_gamma(topo: str) -> tuple[SpecimenGamma, pd.DataFrame]:
    """锚 = cF_exp（SurrogateV3.ref，col47 闭式反演）/ cF_dev，L∈{6,8}。"""
    sv = SurrogateV3(tpms=topo)
    surf = _dev_cf_surface(topo)
    rows = []
    for _, r in sv.ref.iterrows():
        L, t = float(r.L_mm), float(r.t_mm)
        if round(L) not in (6, 8):
            continue
        g = float(r.c_F) / cf_dev(topo, round(L), round(t, 1), surf)
        rows.append(dict(L=float(round(L)), t=float(round(t, 1)),
                         cF_exp=float(r.c_F), gamma=g))
    anch = pd.DataFrame(rows).sort_values(["L", "t"]).reset_index(drop=True)
    if len(anch) < 4:
        raise RuntimeError(f"{topo}: trusted anchors missing ({len(anch)})")

    X = np.stack([
        np.where(anch.L == _TRUSTED_L[0], 1.0, 0.0),
        np.where(anch.L == _TRUSTED_L[1], 1.0, 0.0),
        anch.t.to_numpy(float) - _T_CENTER,
    ], axis=1)
    y = np.log(anch.gamma.to_numpy(float))
    beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = len(y) - 3
    s2 = float(resid @ resid) / dof
    model = SpecimenGamma(
        topo=topo,
        a={_TRUSTED_L[0]: float(beta[0]), _TRUSTED_L[1]: float(beta[1])},
        b=float(beta[2]), s2=s2,
        XtX_inv=np.linalg.inv(X.T @ X), dof=dof, n=len(y))
    return model, anch


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_rows = []
    print("=" * 74)
    print("D-2b-1 γ_specimen 候选面（dev 基，L6/L8 锚，t 斜率池化）")
    print("=" * 74)
    for topo in ("Diamond", "Gyroid"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model, anch = fit_specimen_gamma(topo)
        print(f"\n[{topo}]  锚 n={model.n}  σln={np.sqrt(model.s2):.3f}  "
              f"t 斜率 b={model.b:+.2f}/mm  "
              f"a6={np.exp(model.a[6.0]):.2f} a8={np.exp(model.a[8.0]):.2f}")
        for _, r in anch.iterrows():
            pred = model.predict(r.L, r.t)
            print(f"    锚 L{r.L:.0f} t{r.t:.1f}: γ={r.gamma:.2f} "
                  f"(面回代 {pred:.2f}, 残差 {r.gamma/pred - 1:+.1%})")
            out_rows.append(dict(topo=topo, kind="anchor", L=r.L, t=r.t,
                                 gamma=r.gamma, pred=pred))
        # 对照组：γ(7, 0.6) 后验带 vs HX 需要值
        g7 = model.predict(7.0, 0.6)
        lo68, hi68 = model.band(7.0, 0.6, 0.16)
        lo95, hi95 = model.band(7.0, 0.6, 0.025)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            need = _HX_CF_EXP[topo] / cf_dev(topo, 7.0, 0.6)
        gap = need / g7
        print(f"  γ_specimen(7,0.6) = {g7:.2f}  68%带 [{lo68:.2f},{hi68:.2f}]"
              f"  95%带 [{lo95:.2f},{hi95:.2f}]")
        print(f"  HX 需要值 γ_HX_needed = {need:.2f}  →  缺口 ×{gap:.2f}"
              f"  （95% 带{'内' if lo95 <= need <= hi95 else '外'}"
              f" ⇒ HX 层{'不可' if not (lo95 <= need <= hi95) else '或可'}"
              f"由试件面解释）")
        out_rows.append(dict(topo=topo, kind="gate_geometry", L=7.0, t=0.6,
                             gamma=g7, pred=need, lo68=lo68, hi68=hi68,
                             lo95=lo95, hi95=hi95, hx_gap=gap))
    out = REPORT_DIR / "gamma_specimen.csv"
    pd.DataFrame(out_rows).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
