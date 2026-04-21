---
type: report
date: 2026-04-15
tags: [report, surrogate, direct-dP, MLP, Correa, scratch, SJTU-TPMSHX]
---

# Direct-ΔP MLP 代理模型 — regularized 变体(scratch 实验)

**本次变体**:DROPOUT 0.05→0.15,WEIGHT_DECAY 3e-4→1e-3,其余与初始版本一致。
目的:收紧 in-sample→LOO 泛化 gap(初始 Diamond 3.42→8.89,Gyroid 5.06→14.18)。
对比初始版本见 `reports/scratch/2026-04-15-direct-dp-mlp-scratch.md`。

**动机**:ConstDF-v1 之后的 5 种 D-F 闭合类改进(死路 1-6+6a)全部失败,
核心限制是数据 Re 下限(400/1600)钳死了所有物理驱动闭合形式。本次绕开
D-F 闭合,按 Correa 2026(Gyroid,3.53% MAPE)思路训一个纯数据驱动 MLP,
输入 $(L, t, \varepsilon_f, Re)$,直接输出 $\log_{10} \Delta P_\text{Pa}$,
看能否突破 v1 的 12.79/16.95% 基线。

**Scratch 定位**:不入主干,不改 v1,和前两个 Gompertz scratch 并列存档。

## 记分板

| | Diamond | Gyroid |
|---|---|---|
| ConstDF-v1 LOO (baseline) | 12.79% | 16.95% |
| **Direct-ΔP MLP LOO** | **9.33%** | **25.40%** |
| Δ vs v1 | -3.46pp | +8.45pp |
| 目标 | < 8% | < 8% |
| Diamond full-train in-sample MAPE | 5.20% | |
| Gyroid full-train in-sample MAPE | 13.52% | |

## 方法

**输入**(4D):$(\log_{10} L_{mm}, \log_{10} t_{mm}, \log_{10} \varepsilon_f, \log_{10} Re)$,z-score 归一化。
归一化统计量来自**每折训练 rows**(per-row stats,非 per-geom reference)。

**输出**(1D):标准化的 $\log_{10} \Delta P_\text{Pa}$;推理时反归一化、
clamp 到 $[0.0, 7.0]$,再取 $10^x$ 得物理 ΔP。

**架构**:`Linear(4, 32) → SiLU → Dropout(0.05) → Linear(32, 32) → SiLU → Dropout(0.05) → Linear(32, 1)`

**损失**:$\text{mean}\,((\Delta P_\text{pred} - \Delta P_\text{obs})/\Delta P_\text{obs})^2$(与 v1 同款)

**超参**(与 ConstDF-v1 **完全一致**):Adam(lr=0.001, wd=0.001),
ReduceLROnPlateau(patience=200, factor=0.5),早停 PATIENCE=800,
grad clip=1.0,epochs≤8000,5 seed ensemble
(base SEED=20260414,member offset +k·101,LOO fold offset +i·7)

**L_ch 注**:K_S_CELLS=10,但本 direct 模型**不进入** L_ch 计算 —— 网络从 $L$ 输入内部学习 ΔP 与 L 的关系

## LOO 每几何 ΔP MAPE

### Diamond

- 几何数: 12
- **Direct-MLP LOO ΔP MAPE**: **9.33%** (v1 基线 12.79%)
- drop-worst LOO MAPE: 7.34%
- LOO 最差几何: 31.24%
- LOO 最差单行: 33.02%

| L | t | n | Re range | dP_obs mean | dP_pred mean | ΔP MAPE% | max% |
|---|---|---|----------|-------------|--------------|----------|------|
| 4 | 0.3 | 9 | 600–2500 | 1.65e+04 | 1.53e+04 | 7.99 | 14.47 |
| 4 | 0.4 | 8 | 600–2000 | 1.86e+04 | 1.78e+04 | 5.44 | 12.90 |
| 4 | 0.5 | 6 | 600–1600 | 2.51e+04 | 1.71e+04 | 31.24 | 33.02 |
| 5 | 0.3 | 13 | 600–4500 | 1.47e+04 | 1.42e+04 | 2.29 | 8.72 |
| 5 | 0.4 | 12 | 600–4000 | 1.39e+04 | 1.47e+04 | 7.33 | 10.57 |
| 5 | 0.5 | 10 | 600–3000 | 1.23e+04 | 1.4e+04 | 13.09 | 17.35 |
| 6 | 0.3 | 15 | 400–5000 | 9.86e+03 | 9.16e+03 | 7.43 | 12.65 |
| 6 | 0.4 | 15 | 400–5000 | 1.13e+04 | 1.01e+04 | 7.69 | 13.81 |
| 6 | 0.5 | 15 | 400–5000 | 1.29e+04 | 1.19e+04 | 6.97 | 13.11 |
| 8 | 0.3 | 15 | 1600–11000 | 1.67e+04 | 1.83e+04 | 12.64 | 18.64 |
| 8 | 0.4 | 14 | 1600–10000 | 1.72e+04 | 1.57e+04 | 6.87 | 14.12 |
| 8 | 0.5 | 13 | 1600–9000 | 1.63e+04 | 1.57e+04 | 2.95 | 10.87 |

### Gyroid

- 几何数: 12
- **Direct-MLP LOO ΔP MAPE**: **25.40%** (v1 基线 16.95%)
- drop-worst LOO MAPE: 23.62%
- LOO 最差几何: 44.95%
- LOO 最差单行: 67.05%

| L | t | n | Re range | dP_obs mean | dP_pred mean | ΔP MAPE% | max% |
|---|---|---|----------|-------------|--------------|----------|------|
| 4 | 0.3 | 11 | 600–3500 | 1.3e+04 | 9.59e+03 | 27.20 | 34.08 |
| 4 | 0.4 | 10 | 600–3000 | 1.36e+04 | 9.76e+03 | 28.17 | 33.53 |
| 4 | 0.5 | 8 | 800–2500 | 1.52e+04 | 1.04e+04 | 32.04 | 33.42 |
| 5 | 0.3 | 16 | 600–7000 | 1.03e+04 | 1.27e+04 | 35.73 | 50.45 |
| 5 | 0.4 | 15 | 600–6000 | 9.51e+03 | 1.1e+04 | 19.22 | 30.24 |
| 5 | 0.5 | 15 | 600–6000 | 1.05e+04 | 1.38e+04 | 44.95 | 67.05 |
| 6 | 0.3 | 18 | 400–8000 | 9.81e+03 | 6.85e+03 | 28.95 | 32.34 |
| 6 | 0.4 | 17 | 400–7000 | 9.11e+03 | 6.14e+03 | 31.37 | 34.09 |
| 6 | 0.5 | 16 | 400–6000 | 8.61e+03 | 5.43e+03 | 37.07 | 39.07 |
| 8 | 0.3 | 20 | 1600–16000 | 1.37e+04 | 1.37e+04 | 4.07 | 8.29 |
| 8 | 0.4 | 19 | 1600–15000 | 1.27e+04 | 1.26e+04 | 9.61 | 24.71 |
| 8 | 0.5 | 18 | 1600–14000 | 1.24e+04 | 1.2e+04 | 6.44 | 13.51 |

## 图

- LOO bar chart: `reports/figs/df_fit/direct_dp_mlp_reg_loo.png`

## 判据

- **两个 TPMS 都 < 8%** → 升级为 DirectMLP-v1 主干,归档 ConstDF-v1 为备份
- **一个 < 8% 一个 > 12%** → 非对称成功(和 Re-dep v2 同症),归档备案
- **两个都 ≥ 12%** → 死路 7,写入 memory,接入 ConstDF-v1 到求解器
- **一个 / 两个在 8-12% 区间** → 小幅改善但不达目标,保留 v1 主干

**注**:direct-MLP 的 full-train in-sample MAPE 是 LOO 的理论上界。
若 in-sample 就达不到 8%,说明 4D 输入对本数据集表达力不足,
考虑加 hidden size(3 层 × 64)或加输入维度(显式 u/ρ/μ)作为 follow-up。
