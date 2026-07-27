"""compare_smooth_df.py — sCO2 CFD (双拓扑, 光滑壁) vs SmoothDF 跨流体检验
+ 固定 K 的 sCO2 cF 重标定（见同目录 README）.

用法:
    python sjtu_tpmshx/validation/sco2_cfd/compare_smooth_df.py

问题设定
--------
SmoothDF（water+air 训练, `df_surrogate/smooth_df.py`）宣称跨流体误差 ~19%。
本脚本用 Diamond + Gyroid sCO2 单胞 CFD 回答两个问题：

1. **验证**：SmoothDF 对 sCO2 的 dp/L 预测误差多大？若落在其自报跨流体
   误差带内，则光滑 D-F 面无需为 sCO2 单独分层。
2. **标定**：固定 K（本数据 Re>=2600, Darcy 份额不可辨识——f=A/Re+B 拟出的
   A 吸收的是湍流斜率而非渗透率, 与 load_data.py 的过渡区结论一致），
   逐几何重拟 B（Forchheimer 水平）与池化 m（Re 斜率），
   给出 B_sco2/B_smooth 比值面。

口径
----
点级拟合量 = dpdl_Pa_m（原始 dp/L），模型 = mu·u/K + rho·B·(Re/1000)^(-m)·u²,
u 为间隙平均流速, Re 用 repo Dh（load_sco2_cfd 已重算）。
物性态池化：f 对 (P, Tref) 不敏感（27 态均值比 1.000, 个例散差 ±10–25%），
全部点参与拟合，散差自然进入残差。

输出
----
reports/sco2_cfd/df_smoothdf_vs_sco2.csv   逐几何: K/B_smooth, 预测误差,
                                           B_sco2, 比值, 重拟误差
stdout                                     汇总判决
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PKG_ROOT = _THIS.parent.parent.parent          # .../sjtu_tpmshx

from sjtu_tpmshx.df_surrogate.load_sco2_cfd import LATTICES, load_core  # noqa: E402
from sjtu_tpmshx.df_surrogate.smooth_df import SmoothDF, _geom          # noqa: E402

REPORT_DIR = _PKG_ROOT.parent / "reports" / "sco2_cfd"


def _rmsre(pred, obs):
    r = (pred - obs) / obs
    return float(np.sqrt(np.mean(r * r)))


def _medape(pred, obs):
    return float(np.median(np.abs((pred - obs) / obs)))


# 拟合数学已单源化到生产模块 df_surrogate/sco2_df.py（2026-07-15, cF 入产线
# 时迁移）；此处保留旧名薄别名，供本目录脚本与 make_error_report 复用。
from sjtu_tpmshx.df_surrogate.sco2_df import fit_B as _fit_B                  # noqa: E402
from sjtu_tpmshx.df_surrogate.sco2_df import fit_pooled_m as _fit_pooled_m    # noqa: E402

def _run_lattice(tpms: str, sm: SmoothDF) -> pd.DataFrame:
    core = load_core(tpms)
    m_water = sm._lat[tpms]["m"]
    m_sco2 = _fit_pooled_m(core, sm, tpms)   # fixed-K pooled Re-slope

    rows = []
    err_pred_all, err_refit_all = [], []
    for gid, d in core.groupby("geometry_id"):
        L, t = float(d["L_mm"].iloc[0]), float(d["t_mm"].iloc[0])
        K, B_smooth = sm.predict_K_B(tpms, L, t)
        _, Dh = _geom(tpms, L, t)
        u, rho, mu = (d["Um_m_s"].values, d["rho_kg_m3"].values,
                      d["mu_Pa_s"].values)
        y = d["dpdl_Pa_m"].values

        # 1) production-surface prediction, as the solver would evaluate it
        pred = np.array([sm.predict_dpdl(tpms, L, t, ui, ri, mi)
                         for ui, ri, mi in zip(u, rho, mu)])
        # 2) sCO2 refit: K fixed, pooled m_sco2, per-geometry B
        B_sco2 = _fit_B(d, K, m_sco2)
        refit = mu * u / K + rho * B_sco2 \
            * (d["Re"].values / 1000.0) ** (-m_sco2) * u ** 2

        err_pred_all.append((pred - y) / y)
        err_refit_all.append((refit - y) / y)
        rows.append(dict(
            tpms=tpms, geometry_id=gid, L_mm=L, t_mm=t, Dh_mm=Dh * 1e3,
            n=len(d), m_sco2=m_sco2, m_water=m_water,
            K_m2=K, B_smooth=B_smooth, B_sco2=B_sco2,
            B_ratio=B_sco2 / B_smooth,
            darcy_share_max=float(np.max(mu * u / K / y)),
            rmsre_smoothdf=_rmsre(pred, y), medape_smoothdf=_medape(pred, y),
            bias_smoothdf=float(np.median((pred - y) / y)),
            rmsre_refit=_rmsre(refit, y), medape_refit=_medape(refit, y),
        ))

    out = pd.DataFrame(rows).sort_values(["L_mm", "t_mm"])
    ep = np.concatenate(err_pred_all)
    er = np.concatenate(err_refit_all)
    print(f"\n===== {tpms} ({len(core)} cases) =====")
    print(f"m: water/air pooled = {m_water:.4f}  |  sCO2 pooled = "
          f"{m_sco2:.4f}")
    print(out[["geometry_id", "Dh_mm", "n", "B_smooth", "B_sco2", "B_ratio",
               "darcy_share_max", "rmsre_smoothdf", "bias_smoothdf",
               "rmsre_refit"]].round(4).to_string(index=False))
    print(f"SmoothDF 直接预测 : RMSRE {np.sqrt(np.mean(ep**2)):.1%}  "
          f"medAPE {np.median(np.abs(ep)):.1%}  "
          f"中位偏置 {np.median(ep):+.1%}")
    print(f"sCO2 重拟 (K 固定) : RMSRE {np.sqrt(np.mean(er**2)):.1%}  "
          f"medAPE {np.median(np.abs(er)):.1%}")
    print(f"B_ratio: 中位 {out.B_ratio.median():.3f}  "
          f"范围 [{out.B_ratio.min():.3f}, {out.B_ratio.max():.3f}]")
    return out


def main() -> None:
    sm = SmoothDF()
    frames = [_run_lattice(tpms, sm) for tpms in LATTICES]
    out = pd.concat(frames, ignore_index=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = REPORT_DIR / "df_smoothdf_vs_sco2.csv"
    out.to_csv(csv_path, index=False)
    print(f"\n已写出 {csv_path}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    main()
