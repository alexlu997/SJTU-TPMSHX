"""bayes_exam.py — 贝叶斯标定变体：后验带对上海 16 的诚实度（D-2c' 末项）.

D-2c' 的四个变体里，前三个（现行 γ 面 / refit 基 / 物理化）比的都是**点估计**。
贝叶斯标定变体该回答的是另一个问题——**D-2b-4 给出的那条后验带，在面对一份
完全外部的数据集时，诚不诚实？**

这是对 UQ 声明最强的一种检验：带是在试件台架 + 7-6 气侧台架上建的，
上海 16 从未参与过它的构造。

### 方法（为什么不用 MC 穿求解器）

Δp 对 cF **单调**，所以把 γ_total 的后验分位点送进求解器，出来的就**精确是**
Δp 的同阶分位点——不需要 MC 穿 3D 求解器（那要上万次解），只要 5 次。

    γ_total(G,7,0.6) 后验（D-2b-4 per_topo，`gamma_two_layer_surface.csv`）
      2.5%   16%    50%    84%    97.5%
      2.209  2.339  2.469  2.606  2.768

    × DIR_FACTOR 1.274（折算到 0401 交付方向，审计 §14）
      cF: 471.0  498.6  526.3  555.7  590.0

对这 5 个 cF 各跑一次上海门 -> 逐例 Δp 的 [2.5,16,50,84,97.5] 分位 ->
与实测比覆盖率。**名义 68% 带应覆盖约 68%、95% 带约 95%。**

### 两个方向都算

`dir`（×1.274，0401 交付方向）与 `raw`（0407 锚方向）各跑一组——D10 无论
怎么定，覆盖率都已在表里。

用法（从仓库根）:
    python -u sjtu_tpmshx/validation/df_refit/bayes_exam.py

输出: stdout 记分板 + reports/df_refit/bayes_exam.csv。生产零改动。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from sjtu_tpmshx.df_surrogate import backend as _backend
from sjtu_tpmshx.validation.df_refit.shanghai_blind_exam import TwoLayerModel
from sjtu_tpmshx.validation.df_refit.method_matrix import DIR_FACTOR
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
REPORT_DIR = _REPO / "reports" / "df_refit"
_SURF = REPORT_DIR / "gamma_two_layer_surface.csv"
_GATE = (_REPO / "sjtu_tpmshx" / "validation" / "cases"
         / "validate_shanghai_3d_real.py")
_OUT_DIR = _REPO / "sjtu_tpmshx" / "validation"

_QCOL = ["lo95", "lo68", "gamma_total", "hi68", "hi95"]
_QLAB = ["q025", "q16", "q50", "q84", "q975"]
# 环境变量传缩放因子——子进程里 backend 按它建模型
_ENV_SCALE = "TPMSHX_BAYES_SCALE"


class _ScaledModel(TwoLayerModel):
    def __init__(self, tpms: str):
        super().__init__(tpms)
        self._scale = float(os.environ.get(_ENV_SCALE, "1.0"))

    def predict(self, L_mm, t_mm, eps_f=None):
        K, cF = super().predict(L_mm, t_mm, eps_f)
        return K, cF * self._scale


@_backend.register("bayes_scaled")
class _BayesBackend(_backend.DFBackend):
    def _build(self, tpms_type):
        return _ScaledModel(tpms_type)

    def predict_vec(self, L_flat, t_flat, e_flat):
        K = np.empty(L_flat.size)
        cF = np.empty(L_flat.size)
        cache: dict[tuple[float, float], tuple[float, float]] = {}
        for i in range(L_flat.size):
            key = (L_flat[i], t_flat[i])
            if key not in cache:
                cache[key] = self._model.predict(key[0], key[1])
            K[i], cF[i] = cache[key]
        return K, cF


def posterior_scales() -> dict[str, float]:
    """γ 后验五分位相对中位的比值（形状因子，与方向无关）。"""
    d = pd.read_csv(_SURF)
    g = d[(d.variant == "per_topo") & (d.topo == "Gyroid")
          & (d.L == 7.0) & (d.t == 0.6)].iloc[0]
    med = float(g["gamma_total"])
    return {lab: float(g[c]) / med for lab, c in zip(_QLAB, _QCOL)}


def _run(scale: float, suffix: str) -> pd.DataFrame:
    env = dict(os.environ)
    env.update(PYTHONHASHSEED="0", QT_QPA_PLATFORM="offscreen",
               TPMSHX_DF_METHOD="bayes_scaled")
    env[_ENV_SCALE] = repr(scale)
    boot = ("import runpy,sys;"
            "import sjtu_tpmshx.validation.df_refit.bayes_exam;"
            f"sys.argv=['gate','--suffix','{suffix}','--no-gate'];"
            f"runpy.run_path(r'{_GATE}', run_name='__main__')")
    p = subprocess.run([sys.executable, "-u", "-c", boot], cwd=str(_REPO),
                       env=env, capture_output=True, text=True,
                       errors="replace")
    csv = _OUT_DIR / f"shanghai_3d_baseline{suffix}.csv"
    if p.returncode != 0 or not csv.exists():
        raise RuntimeError(f"gate(scale={scale}) rc={p.returncode}\n"
                           f"{p.stdout[-2000:]}\n{p.stderr[-2000:]}")
    return pd.read_csv(csv)


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    sc = posterior_scales()
    print("=" * 78)
    print("D-2c' 贝叶斯标定变体——D-2b-4 后验带对上海 16 的覆盖率检验")
    print("=" * 78)
    print("\n[0] γ_total(G,7,0.6) 后验五分位（相对中位的比值）")
    for lab in _QLAB:
        print(f"    {lab:>5}: x{sc[lab]:.4f}")
    print("    Δp 对 cF 单调 -> 在这 5 个点跑门即**精确**给出 Δp 的同阶分位")

    rows = []
    for dirname, dfac in (("dir(0401 交付方向)", DIR_FACTOR),
                          ("raw(0407 锚方向)", 1.0)):
        print(f"\n[1] {dirname}  DIR={dfac}")
        cols = {}
        for lab in _QLAB:
            s = sc[lab] * dfac
            print(f"    跑 {lab} (scale={s:.4f}) ...")
            d = _run(s, f"_bx_{lab}_{'d' if dfac != 1.0 else 'r'}")
            cols[lab] = d.dP_sim.to_numpy(float)
            meas = d.dP_exp.to_numpy(float)
        in68 = ((meas >= cols["q16"]) & (meas <= cols["q84"]))
        in95 = ((meas >= cols["q025"]) & (meas <= cols["q975"]))
        e50 = (cols["q50"] - meas) / meas
        w68 = float(np.median(cols["q84"] / cols["q16"]))
        w95 = float(np.median(cols["q975"] / cols["q025"]))
        rows.append(dict(direction=dirname, n=len(meas),
                         cover68=float(in68.mean()), cover95=float(in95.mean()),
                         width68=w68, width95=w95,
                         rmsre50=float(np.sqrt(np.mean(e50 ** 2))),
                         bias50=float(np.mean(e50))))
        print(f"    68% 覆盖 {in68.mean():.0%}（名义 68%）  "
              f"95% 覆盖 {in95.mean():.0%}（名义 95%）")
        print(f"    带宽比 68% {w68:.3f} / 95% {w95:.3f}；"
              f"中位线 RMSRE {np.sqrt(np.mean(e50 ** 2)):.2%}")

    out = pd.DataFrame(rows)
    out.to_csv(REPORT_DIR / "bayes_exam.csv", index=False,
               encoding="utf-8-sig")
    print("\n[2] 判读")
    print("  - 覆盖率**远低于**名义 = 带过窄（假自信）；远高于 = 带过宽。")
    print("  - 这是对 D-2b-4 那条带最强的一次检验：带建在试件台架 + 7-6 气侧")
    print("    台架上，**上海 16 从未参与它的构造**。")
    print("  - 带宽比只有 ~1.2-1.3 量级 —— 它只含 HX 层案间散差")
    print("    （标定几何处形状项恒为 0，见审计 §12.2），**不含**流向不确定度、")
    print("    也不含 D12 那条 alpha 出处风险。覆盖不足首先该往这两处找。")
    print(f"\n已写出 {REPORT_DIR / 'bayes_exam.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
