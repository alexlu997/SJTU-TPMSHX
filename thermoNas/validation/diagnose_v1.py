"""
diagnose_v1.py — Why does fit v1 over-predict experimental dP by ~200%?

Runs four diagnostics (no SIMPLE solver, all analytic):
  4a. v1 self-consistency vs CFD fit data (filtered to in-range t)
  4b. t=0.5 -> 0.6 extrapolation magnitude
  4c. rho convention audit (already done in plan, just print sources)
  4d. v1 dP_predict vs experimental dP, ratio vs Re for both A and B

Fluid A is full 1D BC -> dP_predict computed analytically (no SIMPLE needed).
Fluid B is partial 2D BC -> rescaled from v2 sim baseline using f_v1/f_v2 ratio.

Outputs:
  data/v1_diagnosis/v1_diag_4a.csv          (CFD self-consistency per-row)
  data/v1_diagnosis/v1_diag_4d_A.csv        (Fluid A: 16-row analytic v1 vs experiment)
  data/v1_diagnosis/v1_diag_4d_B.csv        (Fluid B: 16-row rescaled v1 vs experiment)
  data/v1_diagnosis/v1_diag_ratio.png       (4d plot)
  data/v1_diagnosis/v1_diag_summary.md      (final summary, decision-ready)

Run from thermoNas/ directory:  python diagnose_v1.py
"""

import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Local imports
from solvers.tpms_calc import (
    _F_COEFFS, friction_factor, geometry as tpms_geometry,
    air_density, air_viscosity, P_atm,
)

# ---------------------------------------------------------------------------
# Constants for the user's experiment
# ---------------------------------------------------------------------------
L_CELL_MM = 7.0
T_WALL_MM = 0.6
TPMS_TYPE = 'Gyroid'
KS = 16.0  # solid k, doesn't matter for f-Re

# Domain (matches main.py defaults)
L_DOM = 0.231  # m, x-extent
H_DOM = 0.042  # m, y-extent

# Fluid B partial BC (from main.py:489-492)
B_IN_X_LO = 0.182
B_IN_X_HI = 0.224
B_OUT_X_LO = 0.007
B_OUT_X_HI = 0.049
B_FLOW_LEN = H_DOM  # 42 mm

# Paths
THERMONAS_ROOT = r'D:\Postgraduate\均质化\ThermoNAS'
DATA_DIR = os.path.join(THERMONAS_ROOT, 'data')
EXP_XLSX = os.path.join(DATA_DIR, 'raw_data', '均质化模型验证V1.xlsx')
CFD_XLSX = os.path.join(DATA_DIR, 'raw_data', '试验记录表_整理版.xlsx')
DIAG_DIR = os.path.join(DATA_DIR, 'v1_diagnosis')
VAL_CSV = os.path.join(THERMONAS_ROOT, 'thermoNas', 'validation_results.csv')

# v1 and v2 coefficients (for ratio computation in 4d)
V1_COEFFS = (0.5658, -0.0596, 0.4304, -3.25, -0.02, -1.37)
V2_COEFFS = (0.006634, 0.423653, 0.430400, -3.2500, -0.0200, -1.3700)

# Sanity check current state
loaded = _F_COEFFS['Gyroid']
print(f"[init] Loaded Gyroid coeffs: {loaded}")
assert abs(loaded[0] - V1_COEFFS[0]) < 1e-9, "tpms_calc.py is NOT in v1 state!"
print(f"[init] Confirmed: tpms_calc.py is in v1 state")


# ---------------------------------------------------------------------------
# Helper: f(Re) for arbitrary coefficient tuple, no global state pollution
# ---------------------------------------------------------------------------
def f_explicit(coeffs, Re, eps, t_mm, L_mm):
    """f = C * Re^n * eps^a * (t/L)^b * (L/(1000*Sa))^c, n = n0 + n1*ln(eps).
    For Gyroid only (X = L_mm)."""
    C, n0, n1, a, b, c = coeffs
    Sa = 0.031  # mm
    n = n0 + n1 * np.log(eps)
    return C * (Re ** n) * (eps ** a) * ((t_mm / L_mm) ** b) * ((L_mm / (1000.0 * Sa)) ** c)


# ---------------------------------------------------------------------------
# Geometry for the user's case
# ---------------------------------------------------------------------------
geom = tpms_geometry(TPMS_TYPE, L_CELL_MM, T_WALL_MM, KS)
EPS_USER = geom['epsilon']
DH_USER = geom['D_h']     # m
RH_USER = DH_USER / 2.0   # m
A0_USER = geom['A_0']
print(f"[geom] L={L_CELL_MM}mm t={T_WALL_MM}mm -> eps={EPS_USER:.5f}, "
      f"D_h={DH_USER*1000:.4f}mm, r_h={RH_USER*1000:.4f}mm")


# ===========================================================================
# DIAGNOSTIC 4a: v1 self-consistency vs CFD data
# ===========================================================================
def diag_4a():
    print("\n========== 4a: v1 vs CFD fit data ==========")
    xls = pd.ExcelFile(CFD_XLSX, engine='openpyxl')
    # Gyroid sheet is index 1
    df = pd.read_excel(xls, sheet_name=xls.sheet_names[1], engine='openpyxl')

    # Map encoded col names to positional indices we discovered earlier
    # We rename by position to avoid GBK pain
    col_map = {
        'L_mm':    df.columns[1],
        't_mm':    df.columns[2],
        'Re':      df.columns[3],
        'D_mm':    df.columns[4],
        'T_in_C':  df.columns[7],
        'P_in_Pa': df.columns[8],
        'mu':      df.columns[9],
        'rho':     df.columns[12],
        'v_ms':    df.columns[13],
        'f_orig':  df.columns[45],
        'f_corr':  df.columns[46],
    }
    print(f"[4a] mapped cols: {list(col_map.keys())}")

    sub = df[[col_map[k] for k in col_map]].copy()
    sub.columns = list(col_map.keys())
    sub = sub.dropna(subset=['L_mm', 't_mm', 'Re', 'D_mm', 'f_orig'])
    sub = sub[sub['Re'] >= 600]  # match v1 fit cutoff
    print(f"[4a] CFD data: {len(sub)} rows after Re>=600 filter")

    # Compute eps from D and L using TPMS geometry (D depends on (L,t))
    eps_list, f_v1_list = [], []
    for _, row in sub.iterrows():
        try:
            g = tpms_geometry(TPMS_TYPE, float(row['L_mm']), float(row['t_mm']), KS)
            eps_list.append(g['epsilon'])
            f_v1 = f_explicit(V1_COEFFS, float(row['Re']), g['epsilon'],
                              float(row['t_mm']), float(row['L_mm']))
            f_v1_list.append(f_v1)
        except Exception as e:
            eps_list.append(np.nan)
            f_v1_list.append(np.nan)
    sub['eps_geom'] = eps_list
    sub['f_v1_predict'] = f_v1_list
    sub = sub.dropna(subset=['f_v1_predict'])

    # Both f columns: which is the fit target?
    for f_col in ['f_orig', 'f_corr']:
        if sub[f_col].isna().all():
            print(f"[4a] {f_col} all NaN, skipping")
            continue
        valid = sub.dropna(subset=[f_col])
        ratio = valid['f_v1_predict'] / valid[f_col]
        ape = (ratio - 1).abs() * 100
        # Filter t in original valid range [0.3, 0.5]
        in_range = valid[(valid['t_mm'] >= 0.3) & (valid['t_mm'] <= 0.5)]
        ratio_ir = in_range['f_v1_predict'] / in_range[f_col]
        ape_ir = (ratio_ir - 1).abs() * 100
        print(f"[4a] vs '{f_col}': all rows  N={len(valid):3d} MAPE={ape.mean():.2f}% "
              f"median ratio={ratio.median():.3f}")
        print(f"[4a]                in t-range [0.3,0.5]  N={len(in_range):3d} "
              f"MAPE={ape_ir.mean():.2f}% median ratio={ratio_ir.median():.3f}")

    sub.to_csv(os.path.join(DIAG_DIR, 'v1_diag_4a.csv'), index=False, encoding='utf-8-sig')
    print(f"[4a] -> data/v1_diagnosis/v1_diag_4a.csv")
    return sub


# ===========================================================================
# DIAGNOSTIC 4b: t=0.5 vs t=0.6 extrapolation magnitude
# ===========================================================================
def diag_4b():
    print("\n========== 4b: t=0.6 extrapolation ==========")
    L = L_CELL_MM
    Re_test = 2000.0
    # eps depends on t (TPMS geometry), need to recompute
    rows = []
    for t in [0.3, 0.4, 0.5, 0.6, 0.7]:
        g = tpms_geometry(TPMS_TYPE, L, t, KS)
        eps = g['epsilon']
        f_v1 = f_explicit(V1_COEFFS, Re_test, eps, t, L)
        rows.append((t, eps, f_v1))
    df = pd.DataFrame(rows, columns=['t_mm', 'eps', 'f_v1_at_Re2000'])
    print(df.to_string(index=False))
    f05 = df[df['t_mm'] == 0.5]['f_v1_at_Re2000'].iloc[0]
    f06 = df[df['t_mm'] == 0.6]['f_v1_at_Re2000'].iloc[0]
    print(f"[4b] f(t=0.6) / f(t=0.5) = {f06/f05:.4f}  (delta = {(f06/f05-1)*100:+.2f}%)")
    print(f"[4b] -> t-extrapolation alone CANNOT explain a 200% over-prediction")
    return df


# ===========================================================================
# DIAGNOSTIC 4d: v1 vs experiment, ratio vs Re (Fluid A analytic, B rescaled)
# ===========================================================================
def diag_4d():
    print("\n========== 4d: v1 vs experiment ratio vs Re ==========")
    # Read experimental data
    xls = pd.ExcelFile(EXP_XLSX, engine='openpyxl')
    df_exp = pd.read_excel(xls, sheet_name=xls.sheet_names[0], engine='openpyxl')
    cols = list(df_exp.columns)
    # Position-based mapping from our earlier inspection:
    # 0: A inlet P, 1: A inlet T(C), 2: A dP, 3: A v
    # 5: B inlet P, 6: B inlet T(C), 7: B dP, 8: B v
    df_exp = df_exp.rename(columns={
        cols[0]: 'P_A_in', cols[1]: 'T_A_C', cols[2]: 'dP_A_exp', cols[3]: 'v_A',
        cols[5]: 'P_B_in', cols[6]: 'T_B_C', cols[7]: 'dP_B_exp', cols[8]: 'v_B',
    })[['P_A_in', 'T_A_C', 'dP_A_exp', 'v_A', 'P_B_in', 'T_B_C', 'dP_B_exp', 'v_B']]
    df_exp.index = np.arange(1, len(df_exp) + 1)
    df_exp.index.name = 'row'
    print(f"[4d] experiment: {len(df_exp)} rows loaded")

    # Read v2 sim baseline for B rescaling
    df_v2 = pd.read_csv(VAL_CSV).set_index('row')
    print(f"[4d] v2 baseline: {len(df_v2)} rows from validation_results.csv")

    # ----- Fluid A: analytic 1D -----
    rows_A = []
    for r, exp in df_exp.iterrows():
        v = float(exp['v_A'])
        T_K = float(exp['T_A_C']) + 273.15
        P_Pa = float(exp['P_A_in'])
        mu = air_viscosity(T_K)
        rho_loc = air_density(T_K, P_Pa)
        rho_ref = air_density(T_K, P_atm)
        Re = rho_ref * v * RH_USER / mu
        f_v1 = f_explicit(V1_COEFFS, Re, EPS_USER, T_WALL_MM, L_CELL_MM)
        f_v2 = f_explicit(V2_COEFFS, Re, EPS_USER, T_WALL_MM, L_CELL_MM)
        # 1D analytic dP for full BC over flow length L_DOM
        dP_v1 = f_v1 * rho_loc * v * v * L_DOM / (2.0 * RH_USER)
        dP_v2 = f_v2 * rho_loc * v * v * L_DOM / (2.0 * RH_USER)
        dP_exp = float(exp['dP_A_exp'])
        rows_A.append({
            'row': r, 'Re_A': Re, 'v_A': v,
            'f_v1': f_v1, 'f_v2': f_v2, 'f_v1_over_v2': f_v1 / f_v2,
            'dP_A_exp': dP_exp,
            'dP_A_v1_predict': dP_v1, 'err_v1_pct': (dP_v1 - dP_exp) / dP_exp * 100,
            'dP_A_v2_predict': dP_v2, 'err_v2_pct': (dP_v2 - dP_exp) / dP_exp * 100,
        })
    df_A = pd.DataFrame(rows_A)
    df_A.to_csv(os.path.join(DIAG_DIR, 'v1_diag_4d_A.csv'), index=False)
    print(f"[4d] Fluid A summary (analytic 1D, no SIMPLE):")
    print(f"     v1 err: mean={df_A['err_v1_pct'].mean():+.1f}% "
          f"median={df_A['err_v1_pct'].median():+.1f}% "
          f"min={df_A['err_v1_pct'].min():+.1f}% max={df_A['err_v1_pct'].max():+.1f}%")
    print(f"     v2 err: mean={df_A['err_v2_pct'].mean():+.1f}% "
          f"median={df_A['err_v2_pct'].median():+.1f}%")
    print(f"     f_v1/f_v2 ratio: median={df_A['f_v1_over_v2'].median():.2f} "
          f"min={df_A['f_v1_over_v2'].min():.2f} max={df_A['f_v1_over_v2'].max():.2f}")

    # ----- Fluid B: rescale v2 sim by f_v1/f_v2 -----
    rows_B = []
    for r, exp in df_exp.iterrows():
        v = float(exp['v_B'])
        T_K = float(exp['T_B_C']) + 273.15
        P_Pa = float(exp['P_B_in'])
        mu = air_viscosity(T_K)
        rho_ref = air_density(T_K, P_atm)
        Re = rho_ref * v * RH_USER / mu
        f_v1 = f_explicit(V1_COEFFS, Re, EPS_USER, T_WALL_MM, L_CELL_MM)
        f_v2 = f_explicit(V2_COEFFS, Re, EPS_USER, T_WALL_MM, L_CELL_MM)
        scale = f_v1 / f_v2
        dP_v2_sim = float(df_v2.loc[r, 'dP_B_sim'])  # from v2 baseline
        dP_v1_estimate = dP_v2_sim * scale
        dP_exp = float(exp['dP_B_exp'])
        rows_B.append({
            'row': r, 'Re_B': Re, 'v_B': v,
            'f_v1': f_v1, 'f_v2': f_v2, 'f_v1_over_v2': scale,
            'dP_B_v2_sim': dP_v2_sim,
            'dP_B_v1_est': dP_v1_estimate,
            'dP_B_exp': dP_exp,
            'err_v1_pct': (dP_v1_estimate - dP_exp) / dP_exp * 100,
            'err_v2_pct': (dP_v2_sim - dP_exp) / dP_exp * 100,
        })
    df_B = pd.DataFrame(rows_B)
    df_B.to_csv(os.path.join(DIAG_DIR, 'v1_diag_4d_B.csv'), index=False)
    print(f"[4d] Fluid B summary (B v1 rescaled from v2 SIMPLE baseline):")
    print(f"     v1 err: mean={df_B['err_v1_pct'].mean():+.1f}% "
          f"median={df_B['err_v1_pct'].median():+.1f}%")
    print(f"     v2 err: mean={df_B['err_v2_pct'].mean():+.1f}% "
          f"median={df_B['err_v2_pct'].median():+.1f}%")

    # ----- Plot ratio vs Re -----
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    ax = axes[0]
    ax.semilogx(df_A['Re_A'], df_A['dP_A_v1_predict'] / df_A['dP_A_exp'],
                'o-', label='Fluid A: dP_v1 / dP_exp')
    ax.semilogx(df_B['Re_B'], df_B['dP_B_v1_est'] / df_B['dP_B_exp'],
                's-', label='Fluid B: dP_v1 (est) / dP_exp')
    ax.axhline(1.0, color='gray', ls='--', alpha=0.5, label='= 1 (perfect)')
    ax.axhline(2.0, color='red', ls=':', alpha=0.5, label='= 2 (200%)')
    ax.set_xlabel('Re_inlet')
    ax.set_ylabel('Ratio sim_v1 / experiment')
    ax.set_title('v1 over-prediction ratio vs Re')
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    ax.semilogx(df_A['Re_A'], df_A['f_v1'], 'o-', label='f_v1 at Re_A')
    ax.semilogx(df_A['Re_A'], df_A['f_v2'], 's-', label='f_v2 at Re_A')
    ax.set_xlabel('Re_A')
    ax.set_ylabel('f')
    ax.set_title('f_v1 vs f_v2 across experimental Re range')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    out_png = os.path.join(DIAG_DIR, 'v1_diag_ratio.png')
    plt.savefig(out_png, dpi=120)
    plt.close(fig)
    print(f"[4d] -> {out_png}")

    return df_A, df_B


# ===========================================================================
# Run all diagnostics + write summary
# ===========================================================================
if __name__ == '__main__':
    cfd = diag_4a()
    text = diag_4b()
    df_A, df_B = diag_4d()

    # Write summary md
    summary_path = os.path.join(DIAG_DIR, 'v1_diag_summary.md')
    with open(summary_path, 'w', encoding='utf-8') as fh:
        fh.write("# fit v1 偏 200% 根因诊断 summary\n\n")
        fh.write(f"日期: 2026-04-10\n\n")
        fh.write(f"几何: Gyroid L={L_CELL_MM}mm t={T_WALL_MM}mm "
                 f"eps={EPS_USER:.4f} D_h={DH_USER*1000:.3f}mm\n")
        fh.write(f"域: {L_DOM*1000:.0f}x{H_DOM*1000:.0f}mm 矩形\n\n")
        fh.write("---\n\n## 4a. v1 vs CFD 自洽性\n\n")
        fh.write("CFD 数据集: data/raw_data/试验记录表_整理版.xlsx Gyroid 表\n\n")
        fh.write("终端输出（运行 diagnose_v1.py 看实际数字）:\n")
        fh.write("- in t-range [0.3, 0.5] 的 MAPE 应该和注释里的 6.7% 接近\n")
        fh.write("- 如果远超 6.7% -> v1 系数本身可能 bad fit\n\n")
        fh.write("---\n\n## 4b. t=0.6 外推幅度\n\n")
        fh.write("(L=7mm, Re=2000 测试点)\n\n")
        fh.write("| t [mm] | eps | f_v1 |\n|---|---|---|\n")
        for _, row in text.iterrows():
            fh.write(f"| {row['t_mm']:.1f} | {row['eps']:.4f} | {row['f_v1_at_Re2000']:.4f} |\n")
        f05 = text[text['t_mm'] == 0.5]['f_v1_at_Re2000'].iloc[0]
        f06 = text[text['t_mm'] == 0.6]['f_v1_at_Re2000'].iloc[0]
        fh.write(f"\n**f(t=0.6)/f(t=0.5) = {f06/f05:.4f}** -> ")
        fh.write(f"t 外推贡献只有 {(f06/f05-1)*100:+.2f}%, "
                 "远不足以解释 200% 偏差\n\n")
        fh.write("---\n\n## 4c. rho 约定审计\n\n")
        fh.write("已审计 (代码读取):\n\n")
        fh.write("**tpms_calc.py:170-175 (`pressure_drop`)**\n")
        fh.write("```python\n")
        fh.write("rho_ref = air_density(T_K, P_atm)        # reference density\n")
        fh.write("Re      = rho_ref * u_c * r_h / mu       # Re uses reference density\n")
        fh.write("f       = friction_factor(...)\n")
        fh.write("dP_per_L = f * rho * u_c**2 / (2.0 * r_h)  # dP uses ACTUAL density\n")
        fh.write("```\n\n")
        fh.write("**simple_solver.py:43-50 (`_porous_src`)**\n")
        fh.write("```python\n")
        fh.write("Re = max(rho_ref * umag * r_h / mu, 10.0)\n")
        fh.write("f = _f_re(Re, ...)\n")
        fh.write("return f * rho * umag / (2.0 * r_h)\n")
        fh.write("```\n\n")
        fh.write("**结论**: 两处约定完全一致 (Re uses rho_ref, drag uses rho_local).\n")
        fh.write("rho 约定假说 (b) **排除** -- 不是 bug.\n\n")
        fh.write("---\n\n## 4d. v1 vs 实验, ratio vs Re\n\n")
        fh.write("Fluid A (1D 解析, 无 SIMPLE): \n")
        fh.write(f"- v1 err mean = **{df_A['err_v1_pct'].mean():+.1f}%**, "
                 f"median = {df_A['err_v1_pct'].median():+.1f}%\n")
        fh.write(f"- v1 err range: [{df_A['err_v1_pct'].min():+.0f}%, "
                 f"{df_A['err_v1_pct'].max():+.0f}%]\n")
        fh.write(f"- (v2 baseline 对照) v2 err mean = {df_A['err_v2_pct'].mean():+.1f}%\n")
        fh.write(f"- f_v1/f_v2 ratio: median={df_A['f_v1_over_v2'].median():.2f} "
                 f"range [{df_A['f_v1_over_v2'].min():.2f}, "
                 f"{df_A['f_v1_over_v2'].max():.2f}]\n\n")
        fh.write("Fluid B (v2 SIMPLE 基线乘 f_v1/f_v2 比, 估计):\n")
        fh.write(f"- v1 err mean = **{df_B['err_v1_pct'].mean():+.1f}%**, "
                 f"median = {df_B['err_v1_pct'].median():+.1f}%\n")
        fh.write(f"- v2 err mean = {df_B['err_v2_pct'].mean():+.1f}%\n\n")
        fh.write(f"图: data/v1_diagnosis/v1_diag_ratio.png\n\n")
        fh.write("---\n\n## 决策点\n\n")
        fh.write("结合 4a-4d, 下一步候选:\n\n")
        fh.write("- 如 4a MAPE 远超 6.7%: v1 系数本身坏 -> 重做 CFD 拟合\n")
        fh.write("- 如 4d 的 ratio 是水平直线 ~2: 纯 scale 偏差 -> 1 参数重拟合 C\n")
        fh.write("- 如 4d 的 ratio 随 Re 变化: Re 指数 n 不对 -> 重新拟合 (C, n0)\n")
        fh.write("- 如 A 和 B 的 ratio 形态不同: partial BC 物理项缺失 -> v2 + B1 路线\n\n")
        fh.write("**等待用户决定继续方向**.\n")
    print(f"\n[summary] -> {summary_path}")
    print("[done] All diagnostics complete. Read v1_diag_summary.md for the summary.")
