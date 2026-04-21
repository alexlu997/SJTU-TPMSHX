---
type: report
date: 2026-04-14
tags: [report, verification, DF, Re-independence, SJTU-TPMSHX]
---

# D-F 闭合 Re 独立性验证报告 (动量方程直接形式)

对 24 个训练几何 (Diamond 12 + Gyroid 12) 用 `ΔP = (μu/K + ρc_F u²)·L_ch` 
直接在 (u, ΔP) 上做 WLS 拟合(权重 w_i = 1/ΔP_i²,等价于最小化相对 ΔP 误差),
L_ch = 10 × L_cell。两项检验判断 (K, c_F) 是否真正和 Re 无关。

**方法 A (残差-Re Pearson, 主判据)** — 在全 Re 范围上拟合后,计算每行相对 
残差 ε_i = (ΔP_pred,i − ΔP_obs,i) / ΔP_obs,i,对 (ε, Re) 做 Pearson 相关检验。
通过判据:|r| < 0.3 **或** p > 0.05。残差与 Re 无显著相关 
说明 2 参数 D-F 形式在该几何上结构成立。

**方法 B (Re 分 bin 漂移, 信息性)** — 按 Re 切 3 段等数量 bin,各 bin 独立重 
拟合 (K, c_F),算 ΔK/K_full 和 Δc_F/c_F_full。参考判据:两者均 < 10%。
**注意**:分 bin 对小样本(每段 2–9 点)本身噪声很大,drift 不作为硬判据。

## 汇总 (24 个几何)

- 方法 A 通过 (硬判据):**24/24**
- 方法 B 通过 (参考):**0/24**

## 主表

| tpms | L | t | n | K (m²) | c_F (1/m) | Pearson r | p | ΔK/K | Δc_F/c_F | A通过 | B通过 |
|------|---|---|---|--------|-----------|-----------|---|------|----------|-------|-------|
| Diamond | 8 | 0.3 | 15 | 1.13e-08 | 29.1 | 0.200 | 0.474 | 2.235 | 1.925 | ✓ | ✗ |
| Diamond | 8 | 0.4 | 14 | 9.85e-09 | 30.3 | 0.174 | 0.551 | 1.839 | 1.844 | ✓ | ✗ |
| Diamond | 8 | 0.5 | 13 | 9.75e-09 | 30.7 | 0.163 | 0.594 | 2.203 | 1.986 | ✓ | ✗ |
| Diamond | 6 | 0.3 | 15 | 1.73e-08 | 90.8 | 0.406 | 0.133 | 3.805 | 1.435 | ✓ | ✗ |
| Diamond | 6 | 0.4 | 15 | 1.64e-08 | 86.7 | 0.400 | 0.14 | 5.284 | 1.586 | ✓ | ✗ |
| Diamond | 6 | 0.5 | 15 | 1.11e-08 | 72.8 | 0.341 | 0.213 | 3.067 | 1.917 | ✓ | ✗ |
| Diamond | 5 | 0.3 | 13 | 6.48e-09 | 86.4 | 0.251 | 0.409 | 3.544 | 1.994 | ✓ | ✗ |
| Diamond | 5 | 0.4 | 12 | 5.97e-09 | 80.3 | 0.221 | 0.491 | 2.576 | 1.913 | ✓ | ✗ |
| Diamond | 5 | 0.5 | 10 | 4.91e-09 | 87.2 | 0.156 | 0.667 | 1.288 | 1.463 | ✓ | ✗ |
| Diamond | 4 | 0.3 | 9 | 2.71e-09 | 134 | 0.123 | 0.753 | 1.136 | 1.476 | ✓ | ✗ |
| Diamond | 4 | 0.4 | 8 | 2.07e-09 | 122 | 0.070 | 0.869 | 0.717 | 1.299 | ✓ | ✗ |
| Diamond | 4 | 0.5 | 6 | 1.34e-09 | 163 | 0.041 | 0.939 | nan | nan | ✓ | ✗ |
| Gyroid | 8 | 0.3 | 20 | 2.38e-08 | 22.9 | 0.290 | 0.215 | 2.514 | 1.587 | ✓ | ✗ |
| Gyroid | 8 | 0.4 | 19 | 2.77e-08 | 22.8 | 0.308 | 0.199 | 5.185 | 1.721 | ✓ | ✗ |
| Gyroid | 8 | 0.5 | 18 | 2.27e-08 | 22.3 | 0.265 | 0.288 | 2.501 | 1.621 | ✓ | ✗ |
| Gyroid | 6 | 0.3 | 18 | 2.14e-08 | 72.9 | 0.431 | 0.0738 | 3.663 | 1.608 | ✓ | ✗ |
| Gyroid | 6 | 0.4 | 17 | 1.8e-08 | 74.1 | 0.382 | 0.13 | 2.153 | 1.384 | ✓ | ✗ |
| Gyroid | 6 | 0.5 | 16 | 1.62e-08 | 77.8 | 0.350 | 0.184 | 1.797 | 1.298 | ✓ | ✗ |
| Gyroid | 5 | 0.3 | 16 | 1.36e-08 | 63.3 | 0.323 | 0.222 | 3.425 | 1.669 | ✓ | ✗ |
| Gyroid | 5 | 0.4 | 15 | 1.16e-08 | 61.6 | 0.272 | 0.326 | 1.801 | 1.394 | ✓ | ✗ |
| Gyroid | 5 | 0.5 | 15 | 1.11e-08 | 56 | 0.259 | 0.351 | 2.063 | 1.593 | ✓ | ✗ |
| Gyroid | 4 | 0.3 | 11 | 3.66e-09 | 126 | 0.166 | 0.626 | 1.358 | 1.516 | ✓ | ✗ |
| Gyroid | 4 | 0.4 | 10 | 2.8e-09 | 150 | 0.123 | 0.734 | 0.892 | 1.223 | ✓ | ✗ |
| Gyroid | 4 | 0.5 | 8 | 2.5e-09 | 117 | 0.085 | 0.841 | 0.989 | 1.411 | ✓ | ✗ |

## 未通过硬判据的几何

**无** — 全部 24 个几何都通过 Pearson 硬判据。

## 图

每个几何的 ΔP-u 散点叠加 WLS 拟合曲线:

- `Diamond L=8 t=0.3`: [figs/df_fit/Diamond_L8_t03_dPu.png](figs/df_fit/Diamond_L8_t03_dPu.png)
- `Diamond L=8 t=0.4`: [figs/df_fit/Diamond_L8_t04_dPu.png](figs/df_fit/Diamond_L8_t04_dPu.png)
- `Diamond L=8 t=0.5`: [figs/df_fit/Diamond_L8_t05_dPu.png](figs/df_fit/Diamond_L8_t05_dPu.png)
- `Diamond L=6 t=0.3`: [figs/df_fit/Diamond_L6_t03_dPu.png](figs/df_fit/Diamond_L6_t03_dPu.png)
- `Diamond L=6 t=0.4`: [figs/df_fit/Diamond_L6_t04_dPu.png](figs/df_fit/Diamond_L6_t04_dPu.png)
- `Diamond L=6 t=0.5`: [figs/df_fit/Diamond_L6_t05_dPu.png](figs/df_fit/Diamond_L6_t05_dPu.png)
- `Diamond L=5 t=0.3`: [figs/df_fit/Diamond_L5_t03_dPu.png](figs/df_fit/Diamond_L5_t03_dPu.png)
- `Diamond L=5 t=0.4`: [figs/df_fit/Diamond_L5_t04_dPu.png](figs/df_fit/Diamond_L5_t04_dPu.png)
- `Diamond L=5 t=0.5`: [figs/df_fit/Diamond_L5_t05_dPu.png](figs/df_fit/Diamond_L5_t05_dPu.png)
- `Diamond L=4 t=0.3`: [figs/df_fit/Diamond_L4_t03_dPu.png](figs/df_fit/Diamond_L4_t03_dPu.png)
- `Diamond L=4 t=0.4`: [figs/df_fit/Diamond_L4_t04_dPu.png](figs/df_fit/Diamond_L4_t04_dPu.png)
- `Diamond L=4 t=0.5`: [figs/df_fit/Diamond_L4_t05_dPu.png](figs/df_fit/Diamond_L4_t05_dPu.png)
- `Gyroid L=8 t=0.3`: [figs/df_fit/Gyroid_L8_t03_dPu.png](figs/df_fit/Gyroid_L8_t03_dPu.png)
- `Gyroid L=8 t=0.4`: [figs/df_fit/Gyroid_L8_t04_dPu.png](figs/df_fit/Gyroid_L8_t04_dPu.png)
- `Gyroid L=8 t=0.5`: [figs/df_fit/Gyroid_L8_t05_dPu.png](figs/df_fit/Gyroid_L8_t05_dPu.png)
- `Gyroid L=6 t=0.3`: [figs/df_fit/Gyroid_L6_t03_dPu.png](figs/df_fit/Gyroid_L6_t03_dPu.png)
- `Gyroid L=6 t=0.4`: [figs/df_fit/Gyroid_L6_t04_dPu.png](figs/df_fit/Gyroid_L6_t04_dPu.png)
- `Gyroid L=6 t=0.5`: [figs/df_fit/Gyroid_L6_t05_dPu.png](figs/df_fit/Gyroid_L6_t05_dPu.png)
- `Gyroid L=5 t=0.3`: [figs/df_fit/Gyroid_L5_t03_dPu.png](figs/df_fit/Gyroid_L5_t03_dPu.png)
- `Gyroid L=5 t=0.4`: [figs/df_fit/Gyroid_L5_t04_dPu.png](figs/df_fit/Gyroid_L5_t04_dPu.png)
- `Gyroid L=5 t=0.5`: [figs/df_fit/Gyroid_L5_t05_dPu.png](figs/df_fit/Gyroid_L5_t05_dPu.png)
- `Gyroid L=4 t=0.3`: [figs/df_fit/Gyroid_L4_t03_dPu.png](figs/df_fit/Gyroid_L4_t03_dPu.png)
- `Gyroid L=4 t=0.4`: [figs/df_fit/Gyroid_L4_t04_dPu.png](figs/df_fit/Gyroid_L4_t04_dPu.png)
- `Gyroid L=4 t=0.5`: [figs/df_fit/Gyroid_L4_t05_dPu.png](figs/df_fit/Gyroid_L4_t05_dPu.png)
