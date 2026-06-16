"""
诊断：现行 Nu 关联式的 (D_h/L) 能否用孔隙率 ε 替换 / 是否该加 ε？

在**对称**训练数据 (试验记录表) 上，对实验 Nu (col40) 拟合 3 种 log-PL 形式：
  A 现行  Nu ∝ Re^a·(D_h/L)^d
  B 替换  Nu ∝ Re^a·ε^e
  C 都加  Nu ∝ Re^a·ε^e·(D_h/L)^d
比 R² / RMSE + corr(logε, log D_h/L)。

结论 (2026-06-05)：ε 与 D_h/L 在对称数据上 **corr≈0.999 共线** → B 与 A 拟合
**完全一样**，C 几乎无增益。∴ 现行数据**分不出** ε vs D_h/L 谁是真驱动；
**不改生产**（换=纯标签 + 微扰 Shanghai 风险）。真正分辨须**非对称数据 (Phase 1)**
——那时 offset 让 ε 与 D_h/L 解耦，可定形式（见 asym-porosity Phase 1 计划）。

用法：python -u runs/nu_eps_vs_dhl_diag.py
"""
import sys
from pathlib import Path
import numpy as np
import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from solvers.tpms_geometry import compute_geometry

XLSX = Path(__file__).resolve().parents[2] / "data" / "raw_data" / "试验记录表_整理版.xlsx"
SHEETS = {"Diamond": "Diamond_汇总", "Gyroid": "Gyroid_汇总"}
_COL_L, _COL_T, _COL_RE, _COL_NU = 1, 2, 3, 40
N = 128


def _geo_cache():
    cache = {}

    def get(tp, L, t):
        k = (tp, float(L), float(t))
        if k not in cache:
            g = compute_geometry(tp, float(L), float(t), N)
            cache[k] = (g["epsilon"], g["D_h"] * 1000.0 / float(L))  # ε, D_h/L
        return cache[k]
    return get


def _fit(y, cols, Nu):
    X = np.column_stack([np.ones_like(y)] + cols)
    coef = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ coef
    r2 = 1 - np.sum(resid ** 2) / np.sum((y - y.mean()) ** 2)
    rmse = np.sqrt(np.mean((np.exp(X @ coef) / Nu - 1) ** 2)) * 100
    return r2, rmse, coef


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    geo = _geo_cache()
    for tp, sheet in SHEETS.items():
        ws = wb[sheet]
        Re, Nu, eps, dhl = [], [], [], []
        for r in ws.iter_rows(min_row=2, values_only=True):
            try:
                L, t, re, nu = float(r[_COL_L]), float(r[_COL_T]), float(r[_COL_RE]), float(r[_COL_NU])
            except (TypeError, ValueError):
                continue
            if nu <= 0 or re <= 0:
                continue
            e, d = geo(tp, L, t)
            Re.append(re); Nu.append(nu); eps.append(e); dhl.append(d)
        Re, Nu, eps, dhl = map(np.array, (Re, Nu, eps, dhl))
        y, lRe, leps, ldhl = np.log(Nu), np.log(Re), np.log(eps), np.log(dhl)
        A = _fit(y, [lRe, ldhl], Nu)
        B = _fit(y, [lRe, leps], Nu)
        C = _fit(y, [lRe, leps, ldhl], Nu)
        corr = np.corrcoef(leps, ldhl)[0, 1]
        print(f"=== {tp} (n={len(Nu)})  corr(logε, log Dh/L) = {corr:.3f} ===")
        print(f"  A 现行 Re+Dh/L   : R2={A[0]:.4f} RMSE={A[1]:4.1f}%  (a={A[2][1]:.3f} d={A[2][2]:.3f})")
        print(f"  B 替换 Re+ε      : R2={B[0]:.4f} RMSE={B[1]:4.1f}%  (a={B[2][1]:.3f} e={B[2][2]:.3f})")
        print(f"  C 都加 Re+ε+Dh/L : R2={C[0]:.4f} RMSE={C[1]:4.1f}%")
    print("\n结论: ε 与 D_h/L 对称数据上共线(~0.999) → 不改生产; ε 留 Phase 1 非对称数据定。")


if __name__ == "__main__":
    main()
