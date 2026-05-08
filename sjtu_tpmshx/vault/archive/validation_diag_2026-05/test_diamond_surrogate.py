"""
test_diamond_surrogate.py — SurrogateV3(tpms='Diamond') 端到端冒烟测试

Step 1: 初始化 Diamond 模型，打印训练集 (K, c_F) 分布
Step 2: 计算 Diamond 的 LOO MAPE，期望 ≈ 15.94%
Step 3: 在训练域内选一个 case，跑 SIMPLE + D-F，对比 1D 解析结果
Step 4: 验证 predict_K_cF_vec 对 Diamond 混合数组的调用
"""
import os, sys, warnings
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

from df_fit.surrogate_v3 import SurrogateV3
from df_fit.predict import predict_K_cF, predict_K_cF_vec, _CACHE
from solvers.tpms_calc import geometry as tpms_geometry, air_density, air_viscosity, P_atm
from solvers.simple_solver import SIMPLESolver

R_AIR = 287.05

# ────────────────────────────────────────────────────────────────
# Step 1: SurrogateV3("Diamond") 初始化冒烟测试
# ────────────────────────────────────────────────────────────────
print("=" * 60)
print("Step 1: 初始化 SurrogateV3(\"Diamond\")")
print("=" * 60)

m = SurrogateV3("Diamond")
m.summary()

print()
print("训练集详细信息：")
print(f"  几何数: {len(m.ref)}")
print(f"  训练行数: {len(m.rows_df)}")
print(f"  K 范围: [{m.ref.K.min():.3e}, {m.ref.K.max():.3e}]")
print(f"  c_F 范围: [{m.ref.c_F.min():.1f}, {m.ref.c_F.max():.1f}]")

# ────────────────────────────────────────────────────────────────
# Step 2: LOO MAPE 交叉验证
# ────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("Step 2: LOO 交叉验证")
print("=" * 60)

from scipy.interpolate import RBFInterpolator

errs = []
for i_out in range(len(m.ref)):
    X_all = m.ref[["L_mm", "t_mm", "eps_f"]].to_numpy(dtype=float)
    K_all = m.ref["K"].to_numpy(dtype=float)
    cF_all = m.ref["c_F"].to_numpy(dtype=float)

    mask = np.ones(len(m.ref), dtype=bool); mask[i_out] = False
    X_tr = X_all[mask]
    K_tr = K_all[mask]; cF_tr = cF_all[mask]

    try:
        rbf_K_loo = RBFInterpolator(X_tr, np.log10(K_tr),
                                     kernel="thin_plate_spline", smoothing=0)
        rbf_cF_loo = RBFInterpolator(X_tr, np.log10(cF_tr),
                                      kernel="thin_plate_spline", smoothing=0)
    except Exception:
        continue

    x_out = X_all[i_out:i_out+1]
    K_pred = max(10.0 ** float(rbf_K_loo(x_out)[0]), m.K_min)
    cF_pred = 10.0 ** float(rbf_cF_loo(x_out)[0])

    L_mm = float(m.ref.iloc[i_out]['L_mm'])
    t_mm = float(m.ref.iloc[i_out]['t_mm'])
    # Predict dP vs actual training rows' dP
    rows_geom = m.rows_df[(m.rows_df['L_mm'] == L_mm) & (m.rows_df['t_mm'] == t_mm)]
    for _, r in rows_geom.iterrows():
        dP_pred = SurrogateV3.predict_dP(
            K_pred, cF_pred, r['G'], r['T'], r['P_in'], r['mu'], r['L_ch'])
        err = (dP_pred - r['dP']) / r['dP']
        errs.append(err)

errs_arr = np.array(errs)
mape = float(np.mean(np.abs(errs_arr)) * 100)
rmsre = float(np.sqrt(np.mean(errs_arr**2)) * 100)
print(f"  Diamond LOO MAPE: {mape:.2f}%")
print(f"  Diamond LOO RMSRE: {rmsre:.2f}%")
print(f"  n_samples: {len(errs_arr)}")

# ────────────────────────────────────────────────────────────────
# Step 3: Diamond + SIMPLE 端到端单 case
# ────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("Step 3: Diamond + SIMPLE 端到端（训练域中点 L=5, t=0.4）")
print("=" * 60)

L_mm = 5.0; t_mm = 0.4; K_S = 15.0
g = tpms_geometry("Diamond", L_mm, t_mm, K_S)
eps = g['epsilon']; D_h = g['D_h']; r_h = D_h / 2
print(f"  Geometry: eps={eps:.4f}, D_h={D_h*1000:.3f}mm")

# 中等 Re 工况
u_air = 5.0  # m/s
T_in = 300.0  # K
rho = air_density(T_in, P_atm); mu = air_viscosity(T_in)
Re = rho * u_air * D_h / mu
G = rho * u_air
print(f"  工况: u={u_air} m/s, T={T_in}K, Re={Re:.0f}")

K_d, cF_d = predict_K_cF("Diamond", L_mm, t_mm, eps/2.0)
print(f"  SurrogateV3: K={K_d:.3e}, c_F={cF_d:.2f}")

# 1D 公式预测 dP
L_DOM = 0.08  # 80 mm 流道
C = mu * G / K_d + cF_d * G**2
P_out_sq = P_atm**2 - 2 * R_AIR * T_in * C * L_DOM
dP_1d = P_atm - np.sqrt(max(P_out_sq, 1e4))
print(f"  1D 公式: dP = {dP_1d:.1f} Pa")

# SIMPLE 预测 dP
Nx_s = 30; Ny_s = 15
sA = SIMPLESolver(
    0.04, L_DOM, Ny_s, Nx_s, "Diamond", L_mm, t_mm,
    eps, r_h, rho, mu, T_in,
    0.0, 0.04, u_air,
    outlet_lo=0.0, outlet_hi=0.04,
    P_ref_abs=float(np.sqrt(max(P_out_sq, 1e4))),
)
sA.solve(max_iter=3000, tol=1e-4, verbose=False)

wI = sA.inlet_frac; wO = sA.outlet_frac
mI = wI > 0.01; mO = wO > 0.5
dP_simple = float(np.average(sA.P[mI, 0], weights=wI[mI])
                - np.average(sA.P[mO, -1], weights=wO[mO]))
print(f"  SIMPLE P 场: dP = {dP_simple:.1f} Pa")

diff_pct = (dP_simple - dP_1d) / dP_1d * 100
print(f"  SIMPLE vs 1D: 差 {diff_pct:+.2f}%（预期 <1 pp, 纯数值一致性）")

# ────────────────────────────────────────────────────────────────
# Step 4: predict_K_cF_vec 对 Diamond 数组的调用
# ────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("Step 4: predict_K_cF_vec Diamond 数组")
print("=" * 60)

L_arr = np.array([4.0, 5.0, 6.0, 7.0, 8.0])
t_arr = np.array([0.3, 0.4, 0.3, 0.4, 0.5])
eps_f_arr = np.empty_like(L_arr)
for i in range(len(L_arr)):
    g_i = tpms_geometry("Diamond", float(L_arr[i]), float(t_arr[i]), K_S)
    eps_f_arr[i] = g_i['epsilon'] / 2.0

K_vec, cF_vec = predict_K_cF_vec("Diamond", L_arr, t_arr, eps_f_arr)
print(f"  L_arr: {L_arr}")
print(f"  t_arr: {t_arr}")
print(f"  K_vec: {K_vec}")
print(f"  cF_vec: {cF_vec}")

# 验证与单点调用一致
print()
print("  与单点预测对比：")
for i in range(len(L_arr)):
    K_single, cF_single = predict_K_cF("Diamond", float(L_arr[i]), float(t_arr[i]), float(eps_f_arr[i]))
    K_ok = abs(K_vec[i] - K_single) < 1e-12
    cF_ok = abs(cF_vec[i] - cF_single) < 1e-8
    status = "✓" if (K_ok and cF_ok) else "✗"
    print(f"  [{i}] L={L_arr[i]}, t={t_arr[i]}: vec=({K_vec[i]:.3e}, {cF_vec[i]:.1f}), "
          f"single=({K_single:.3e}, {cF_single:.1f}) {status}")

# 验证 _CACHE 的 Gyroid/Diamond 独立
print()
print("  _CACHE 独立性验证：")
m_G = SurrogateV3("Gyroid")
print(f"  Diamond cache hit: {'Diamond' in _CACHE}")
print(f"  Gyroid cache hit: {'Gyroid' in _CACHE}")

print()
print("=" * 60)
print("Task 1 总结")
print("=" * 60)
print(f"  Diamond LOO MAPE = {mape:.2f}%（目标 15~17%）")
print(f"  Diamond + SIMPLE end-to-end: dP_1D = {dP_1d:.1f}, dP_SIMPLE = {dP_simple:.1f}")
print(f"  SIMPLE vs 1D 差: {diff_pct:+.2f}% (目标 <3%)")
print(f"  predict_K_cF_vec Diamond: {'正确' if K_ok and cF_ok else '不一致'}")
