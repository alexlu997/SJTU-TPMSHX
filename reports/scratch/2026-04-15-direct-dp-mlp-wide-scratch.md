---
type: report
date: 2026-04-15
tags: [report, surrogate, direct-dP, MLP, Correa, scratch, SJTU-TPMSHX]
---

# Direct-ΔP MLP 代理模型 — wide 变体(scratch 实验)

**本次变体**:HIDDEN 32→64,隐层 2→3,dropout/wd 恢复初始(0.05 / 3e-4)。
目的:regularized 变体让 Gyroid in-sample 飙到 13.52%(bias 问题,不是 variance),
说明 Gyroid L=6 家族泛化不良是 capacity 瓶颈。本变体加宽加深(~4800 参数,
仍远小于 Correa 4 层 256 宽的 ~200k)看能否让 Gyroid in-sample 恢复 5% 级并
把 LOO 从 14.18% 继续压下去。对比:

- 初始版:`reports/scratch/2026-04-15-direct-dp-mlp-scratch.md`(LOO 8.89/14.18)
- 正则版:`reports/scratch/2026-04-15-direct-dp-mlp-reg-scratch.md`(LOO 9.33/25.40,失败)

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
| **Direct-ΔP MLP LOO** | **8.09%** | **9.17%** |
| Δ vs v1 | -4.70pp | -7.78pp |
| 目标 | < 8% | < 8% |
| Diamond full-train in-sample MAPE | 2.83% | |
| Gyroid full-train in-sample MAPE | 2.41% | |

## 方法

**输入**(4D):$(\log_{10} L_{mm}, \log_{10} t_{mm}, \log_{10} \varepsilon_f, \log_{10} Re)$,z-score 归一化。
归一化统计量来自**每折训练 rows**(per-row stats,非 per-geom reference)。

**输出**(1D):标准化的 $\log_{10} \Delta P_\text{Pa}$;推理时反归一化、
clamp 到 $[0.0, 7.0]$,再取 $10^x$ 得物理 ΔP。

**架构**:`Linear(4, 32) → SiLU → Dropout(0.05) → Linear(32, 32) → SiLU → Dropout(0.05) → Linear(32, 1)`

**损失**:$\text{mean}\,((\Delta P_\text{pred} - \Delta P_\text{obs})/\Delta P_\text{obs})^2$(与 v1 同款)

**超参**(与 ConstDF-v1 **完全一致**):Adam(lr=0.001, wd=0.0003),
ReduceLROnPlateau(patience=200, factor=0.5),早停 PATIENCE=800,
grad clip=1.0,epochs≤8000,5 seed ensemble
(base SEED=20260414,member offset +k·101,LOO fold offset +i·7)

**L_ch 注**:K_S_CELLS=10,但本 direct 模型**不进入** L_ch 计算 —— 网络从 $L$ 输入内部学习 ΔP 与 L 的关系

## LOO 每几何 ΔP MAPE

### Diamond

- 几何数: 12
- **Direct-MLP LOO ΔP MAPE**: **8.09%** (v1 基线 12.79%)
- drop-worst LOO MAPE: 7.01%
- LOO 最差几何: 19.91%
- LOO 最差单行: 23.55%

| L | t | n | Re range | dP_obs mean | dP_pred mean | ΔP MAPE% | max% |
|---|---|---|----------|-------------|--------------|----------|------|
| 4 | 0.3 | 9 | 600–2500 | 1.65e+04 | 1.54e+04 | 7.48 | 12.31 |
| 4 | 0.4 | 8 | 600–2000 | 1.86e+04 | 1.79e+04 | 4.98 | 10.00 |
| 4 | 0.5 | 6 | 600–1600 | 2.51e+04 | 1.98e+04 | 19.91 | 23.55 |
| 5 | 0.3 | 13 | 600–4500 | 1.47e+04 | 1.49e+04 | 3.24 | 6.29 |
| 5 | 0.4 | 12 | 600–4000 | 1.39e+04 | 1.49e+04 | 7.92 | 9.81 |
| 5 | 0.5 | 10 | 600–3000 | 1.23e+04 | 1.38e+04 | 11.37 | 13.72 |
| 6 | 0.3 | 15 | 400–5000 | 9.86e+03 | 9.39e+03 | 5.82 | 11.45 |
| 6 | 0.4 | 15 | 400–5000 | 1.13e+04 | 1.04e+04 | 6.17 | 9.23 |
| 6 | 0.5 | 15 | 400–5000 | 1.29e+04 | 1.18e+04 | 9.37 | 12.85 |
| 8 | 0.3 | 15 | 1600–11000 | 1.67e+04 | 1.8e+04 | 9.24 | 11.81 |
| 8 | 0.4 | 14 | 1600–10000 | 1.72e+04 | 1.65e+04 | 3.67 | 6.93 |
| 8 | 0.5 | 13 | 1600–9000 | 1.63e+04 | 1.73e+04 | 7.88 | 10.46 |

### Gyroid

- 几何数: 12
- **Direct-MLP LOO ΔP MAPE**: **9.17%** (v1 基线 16.95%)
- drop-worst LOO MAPE: 8.07%
- LOO 最差几何: 21.30%
- LOO 最差单行: 41.24%

| L | t | n | Re range | dP_obs mean | dP_pred mean | ΔP MAPE% | max% |
|---|---|---|----------|-------------|--------------|----------|------|
| 4 | 0.3 | 11 | 600–3500 | 1.3e+04 | 1.17e+04 | 7.94 | 15.36 |
| 4 | 0.4 | 10 | 600–3000 | 1.36e+04 | 1.18e+04 | 13.56 | 19.43 |
| 4 | 0.5 | 8 | 800–2500 | 1.52e+04 | 1.72e+04 | 13.04 | 14.90 |
| 5 | 0.3 | 16 | 600–7000 | 1.03e+04 | 1.11e+04 | 11.80 | 24.94 |
| 5 | 0.4 | 15 | 600–6000 | 9.51e+03 | 9.9e+03 | 3.46 | 9.60 |
| 5 | 0.5 | 15 | 600–6000 | 1.05e+04 | 1.19e+04 | 21.30 | 41.24 |
| 6 | 0.3 | 18 | 400–8000 | 9.81e+03 | 8.61e+03 | 12.25 | 15.75 |
| 6 | 0.4 | 17 | 400–7000 | 9.11e+03 | 8.65e+03 | 4.49 | 7.23 |
| 6 | 0.5 | 16 | 400–6000 | 8.61e+03 | 7.97e+03 | 9.17 | 18.07 |
| 8 | 0.3 | 20 | 1600–16000 | 1.37e+04 | 1.34e+04 | 3.39 | 6.77 |
| 8 | 0.4 | 19 | 1600–15000 | 1.27e+04 | 1.28e+04 | 4.31 | 16.58 |
| 8 | 0.5 | 18 | 1600–14000 | 1.24e+04 | 1.2e+04 | 5.33 | 9.67 |

## 图

- LOO bar chart: `reports/figs/df_fit/direct_dp_mlp_wide_loo.png`

## 判据

- **两个 TPMS 都 < 8%** → 升级为 DirectMLP-v1 主干,归档 ConstDF-v1 为备份
- **一个 < 8% 一个 > 12%** → 非对称成功(和 Re-dep v2 同症),归档备案
- **两个都 ≥ 12%** → 死路 7,写入 memory,接入 ConstDF-v1 到求解器
- **一个 / 两个在 8-12% 区间** → 小幅改善但不达目标,保留 v1 主干

**注**:direct-MLP 的 full-train in-sample MAPE 是 LOO 的理论上界。
若 in-sample 就达不到 8%,说明 4D 输入对本数据集表达力不足,
考虑加 hidden size(3 层 × 64)或加输入维度(显式 u/ρ/μ)作为 follow-up。
