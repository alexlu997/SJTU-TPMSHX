"""查 RBF 在 t=0.6 附近的外推行为"""
import sys, numpy as np
sys.stdout.reconfigure(encoding='utf-8')

from df_fit.surrogate_v3 import SurrogateV3

m = SurrogateV3("Gyroid")
print("=== 训练集 (L, t, K, c_F) ===")
print(f"{'L':>3} {'t':>4} {'eps_f':>7} {'K':>10} {'c_F':>8}")
for _, r in m.ref.iterrows():
    K = f"{r.K:.3e}" if r.K is not None and not np.isnan(r.K) else "N/A"
    print(f"{r.L_mm:3.0f} {r.t_mm:4.1f} {r.eps_f:7.4f} {K:>10} {r.c_F:8.1f}")

print("\n=== c_F 按 L 分组，随 t 变化趋势 ===")
for L in sorted(m.ref.L_mm.unique()):
    sub = m.ref[m.ref.L_mm == L].sort_values("t_mm")
    print(f"\nL = {L}:")
    for _, r in sub.iterrows():
        print(f"  t={r.t_mm:.1f}  c_F={r.c_F:.1f}  K={r.K:.3e}")

print("\n=== 预测 L=7 在不同 t 下的 c_F（观察外推行为）===")
print(f"{'L':>3} {'t':>4} {'K':>10} {'c_F':>8}  备注")
for t in [0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7]:
    K, cF = m.predict(7.0, t)
    note = ""
    if t > 0.5:
        note = "← 外推（训练最大 t=0.5）"
    print(f"  7 {t:4.2f} {K:10.3e} {cF:8.1f}  {note}")

print("\n=== 预测 L=7 外推线性趋势 ===")
# 看训练集里 L 接近 7 的是 L=6 和 L=8
# 对 L=6，t 从 0.3→0.5 趋势
print("\nL=6 训练点:")
sub = m.ref[m.ref.L_mm == 6].sort_values("t_mm")
for _, r in sub.iterrows():
    print(f"  t={r.t_mm:.1f}  c_F={r.c_F:.1f}")
print("\nL=8 训练点:")
sub = m.ref[m.ref.L_mm == 8].sort_values("t_mm")
for _, r in sub.iterrows():
    print(f"  t={r.t_mm:.1f}  c_F={r.c_F:.1f}")

# 用 L=6 的 t=0.3,0.4,0.5 外推到 t=0.6（对数空间线性）
L6 = m.ref[m.ref.L_mm == 6].sort_values("t_mm")
if len(L6) >= 3:
    t_vals = L6.t_mm.values
    cF_vals = L6.c_F.values
    # 对数空间线性拟合
    p = np.polyfit(t_vals, np.log(cF_vals), 1)
    cF_t06_L6 = np.exp(np.polyval(p, 0.6))
    print(f"\n  L=6 log-线性外推到 t=0.6: c_F = {cF_t06_L6:.1f}")

L8 = m.ref[m.ref.L_mm == 8].sort_values("t_mm")
if len(L8) >= 3:
    t_vals = L8.t_mm.values
    cF_vals = L8.c_F.values
    p = np.polyfit(t_vals, np.log(cF_vals), 1)
    cF_t06_L8 = np.exp(np.polyval(p, 0.6))
    print(f"  L=8 log-线性外推到 t=0.6: c_F = {cF_t06_L8:.1f}")

# L=7, t=0.6 用 L=6 和 L=8 结果的内插（对 L 线性）
if len(L6) >= 3 and len(L8) >= 3:
    cF_L7_t06_linear = 0.5 * (cF_t06_L6 + cF_t06_L8)
    print(f"\n  L=7, t=0.6 手动估计（L 内插 + t 外推）: c_F ≈ {cF_L7_t06_linear:.1f}")

K_rbf, cF_rbf = m.predict(7.0, 0.6)
print(f"  L=7, t=0.6 RBF 预测: c_F = {cF_rbf:.1f}")
print(f"\n  差异比: RBF / 手动估计 = {cF_rbf / cF_L7_t06_linear:.3f}")
