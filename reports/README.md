---
type: index
updated: 2026-04-15
---

# ThermoNAS D-F 代理模型 — 报告索引

按"是否构成当前 baseline 证据"分两组。文件名保留日期前缀,便于和 git
历史、devlog 对应。

## 当前真相(支撑 ConstDF-v1 baseline)

| 文件 | 一句话结论 |
|---|---|
| [`2026-04-14-DF-re-independence-report.md`](2026-04-14-DF-re-independence-report.md) | 24/24 几何通过 Pearson 残差-Re 检验 → 2 参数 D-F 在当前训练 Re 范围内统计独立于 Re,**论文级证据**,作为 ConstDF-v1 的物理合法性依据 |
| [`2026-04-14-DF-surrogate-loo-report.md`](2026-04-14-DF-surrogate-loo-report.md) | ConstDF-v1 LOO 主结果:**Diamond 12.79% / Gyroid 16.95%**(由 `train_surrogate.py` 自动写入,跑训练即覆盖) |
| [`2026-04-15-DF-residual-structure-diagnostic.md`](2026-04-15-DF-residual-structure-diagnostic.md) | 残差 vs Re 诊断:**U 形残差在 24 个几何上普遍存在**,谷底 Re ≈ 800–2000,论证 12–17% MAPE 是 2-term D-F 闭合形式的结构下限,不是模型容量问题 |

## 被否方案(负结果归档,作"为什么不选 X"的论据)

| 文件 | 被否原因 |
|---|---|
| [`2026-04-14-piedra-baseline.md`](2026-04-14-piedra-baseline.md) | Piedra 4 参数幂律 LOO Diamond 33% / Gyroid 47%,远差于 3D MLP → 证明 (L, t) 输入对代理有用,不只 ε_f |
| [`2026-04-15-kim-k1-diagnostic.md`](2026-04-15-kim-k1-diagnostic.md) | Kim 严格 K₁ 线性子集判据下,大多几何只剩 ≤ 2 个点,样本不够拟合 |
| [`2026-04-15-kim-adapted-diagnostic.md`](2026-04-15-kim-adapted-diagnostic.md) | Kim 2-term 在低 Re 子集上的三种判据(固定 Re 阈、子集 MAPE、新点残差),没一个比全范围 K_Q1 更好 |
| [`2026-04-15-kim-constrained-diagnostic.md`](2026-04-15-kim-constrained-diagnostic.md) | Kim 固定 c_F、反推 K₁ 的方案,全范围 MAPE 比直接 K_Q1 **大** 0.3–8pp |

## 当前 baseline(只看一眼)

**ConstDF-v1** = 常系数 2 参数 Darcy-Forchheimer + 3 输入(L, t, ε_f)→ (K, c_F)
MLP ensemble(5×),per-TPMS。LOO ΔP MAPE Diamond 12.79% / Gyroid 16.95%。
代码在 `thermoNas/df_fit/`,baseline git commit `ab7a39e`。

详细方案对比和物理限制讨论见 `~/.claude/projects/D--Postgraduate/memory/project_thermonas_df_baseline.md`。

## 相关产物(本目录外)

- 训练曲线 / LOO 图: [`figs/df_fit/`](figs/df_fit/)
- 模型 ckpt: `../models/df_surrogate_{diamond,gyroid}.joblib`(被 `.gitignore` 排除,可重生)
- 训练数据: `../data/`(被 `.gitignore` 排除)

## 缺失记录

- `2026-04-14-DF-vs-fRe-closure-experiment.md` — memory 引用过,目录里没找到,
  全项目搜也没。可能从未写出,或是 v2 实验过程中删掉。如需重做,从 git
  commit ab7a39e 之前的 v2 状态没法恢复(那段没进 git)。
