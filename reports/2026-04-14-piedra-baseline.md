---
type: report
date: 2026-04-14
tags: [report, surrogate, baseline, Piedra, power-law, DF]
---

# Piedra-2023 Style Power-Law Baseline vs Option-C MLP

Diagnostic run: fit Piedra's 4-parameter power law 
(K = A · ε_f^B, c_F = C · ε_f^D) on our per-geometry (K, c_F) values, 
then LOO-validate on raw CFD rows. If this simple baseline tracks the 3D-input 
MLP ensemble on LOO ΔP MAPE, the extra (L, t) inputs are not contributing useful 
information beyond ε_f alone.

## Full-data power laws (for sanity)

**Diamond**

- $K = 9.422e-07 \cdot \varepsilon_f^{4.828}$  [m²]
- $c_F = 3.141 \cdot \varepsilon_f^{-3.052}$  [1/m]

**Gyroid**

- $K = 7.444e-06 \cdot \varepsilon_f^{6.789}$  [m²]
- $c_F = 0.9954 \cdot \varepsilon_f^{-4.293}$  [1/m]

## LOO ΔP MAPE per geometry

| tpms | L | t | n_rows | K_ref | K_pred | \|ΔK/K\|% | c_F_ref | c_F_pred | \|Δc_F/c_F\|% | ΔP MAPE% | ΔP max% |
|------|---|---|--------|-------|--------|------------|---------|----------|---------------|----------|---------|
| Diamond | 4 | 0.3 | 9 | 2.71e-09 | 7.05e-09 | 159.84 | 134.1 | 68.98 | 48.57 | 55.94 | 59.73 |
| Diamond | 4 | 0.4 | 8 | 2.07e-09 | 3.69e-09 | 78.22 | 122.2 | 109 | 10.83 | 31.22 | 36.67 |
| Diamond | 4 | 0.5 | 6 | 1.34e-09 | 1.82e-09 | 35.94 | 163.2 | 198.7 | 21.75 | 10.35 | 16.69 |
| Diamond | 5 | 0.3 | 13 | 6.48e-09 | 9.82e-09 | 51.63 | 86.38 | 55.05 | 36.27 | 36.62 | 45.94 |
| Diamond | 5 | 0.4 | 12 | 5.97e-09 | 5.71e-09 | 4.38 | 80.32 | 78.95 | 1.70 | 11.21 | 29.16 |
| Diamond | 5 | 0.5 | 10 | 4.91e-09 | 3.08e-09 | 37.30 | 87.25 | 117 | 34.10 | 46.50 | 74.85 |
| Diamond | 6 | 0.3 | 15 | 1.73e-08 | 1.1e-08 | 36.55 | 90.82 | 44.68 | 50.80 | 29.13 | 59.63 |
| Diamond | 6 | 0.4 | 15 | 1.64e-08 | 7.43e-09 | 54.57 | 86.72 | 62.03 | 28.47 | 22.56 | 130.54 |
| Diamond | 6 | 0.5 | 15 | 1.11e-08 | 4.89e-09 | 56.14 | 72.76 | 84.48 | 16.11 | 55.53 | 178.75 |
| Diamond | 8 | 0.3 | 15 | 1.13e-08 | 1.73e-08 | 52.65 | 29.06 | 47.5 | 63.45 | 17.68 | 67.87 |
| Diamond | 8 | 0.4 | 14 | 9.85e-09 | 1.22e-08 | 23.98 | 30.3 | 55.2 | 82.18 | 27.61 | 85.88 |
| Diamond | 8 | 0.5 | 13 | 9.75e-09 | 8.73e-09 | 10.46 | 30.74 | 65.04 | 111.56 | 57.34 | 117.94 |
| Gyroid | 4 | 0.3 | 11 | 3.66e-09 | 1.26e-08 | 242.93 | 126.2 | 56.29 | 55.40 | 63.95 | 68.01 |
| Gyroid | 4 | 0.4 | 10 | 2.8e-09 | 6.54e-09 | 133.89 | 150.4 | 84.62 | 43.72 | 51.64 | 55.80 |
| Gyroid | 4 | 0.5 | 8 | 2.5e-09 | 2.73e-09 | 9.12 | 116.9 | 196.7 | 68.32 | 22.51 | 49.88 |
| Gyroid | 5 | 0.3 | 16 | 1.36e-08 | 1.72e-08 | 26.77 | 63.33 | 45.3 | 28.47 | 27.60 | 38.96 |
| Gyroid | 5 | 0.4 | 15 | 1.16e-08 | 9.74e-09 | 15.81 | 61.58 | 66 | 7.17 | 11.73 | 41.09 |
| Gyroid | 5 | 0.5 | 15 | 1.11e-08 | 4.88e-09 | 55.85 | 55.99 | 104.4 | 86.51 | 100.06 | 164.34 |
| Gyroid | 6 | 0.3 | 18 | 2.14e-08 | 2.14e-08 | 0.01 | 72.86 | 35.82 | 50.84 | 39.33 | 51.54 |
| Gyroid | 6 | 0.4 | 17 | 1.8e-08 | 1.38e-08 | 23.36 | 74.09 | 50.58 | 31.73 | 21.09 | 50.10 |
| Gyroid | 6 | 0.5 | 16 | 1.62e-08 | 8.52e-09 | 47.44 | 77.79 | 68.63 | 11.78 | 23.66 | 104.85 |
| Gyroid | 8 | 0.3 | 20 | 2.38e-08 | 3.11e-08 | 30.59 | 22.92 | 37.71 | 64.53 | 27.66 | 89.96 |
| Gyroid | 8 | 0.4 | 19 | 2.77e-08 | 2.04e-08 | 26.50 | 22.83 | 44.91 | 96.66 | 70.75 | 135.52 |
| Gyroid | 8 | 0.5 | 18 | 2.27e-08 | 1.51e-08 | 33.80 | 22.26 | 53.65 | 141.05 | 100.43 | 178.52 |

## Summary: Piedra baseline vs Option-C MLP ensemble

| TPMS | Metric | Piedra baseline | Option-C MLP (prior run) |
|------|--------|-----------------|--------------------------|
| Diamond | LOO ΔP MAPE | **33.47%** | 12.79% |
| Diamond | LOO ΔP max  | 57.34% | 18.3% |
| Diamond | LOO K MAPE  | 50.14% | 18.05% |
| Diamond | LOO c_F MAPE| 42.15% | 16.43% |
| Gyroid | LOO ΔP MAPE | **46.70%** | 16.95% |
| Gyroid | LOO ΔP max  | 100.43% | 24.0% |
| Gyroid | LOO K MAPE  | 53.84% | 11.78% |
| Gyroid | LOO c_F MAPE| 57.18% | 19.35% |

## 决策门

- **Piedra ≈ MLP (差 < 2 个百分点)** → MLP 对 (L, t) 没有真正利用 → 证据支持 
  Stage-2 加 Re 输入(因为 MLP 容量还够,只是缺信息)
- **Piedra 明显更差 (差 > 5 个百分点)** → MLP 学到 (L, t) 非平凡贡献 → Stage-2 
  加 Re 输入仍有道理,但注意不要破坏 (L, t) 的学习
- **Piedra 明显更好** → 异常,MLP 在过拟合或训练失败 → 检查 Option-C 代码
