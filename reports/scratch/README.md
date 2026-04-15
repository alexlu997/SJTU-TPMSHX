---
type: archive
tags: [scratch, surrogate-exploration, failed-alternatives, ThermoNAS]
---

# Scratch Experiments Archive — ConstDF-v1 之外的探索记录

这里存的是 **绕开 ConstDF-v1 12.79/16.95% LOO MAPE 下限的探索实验**,
全部"不入主干"(代码和 checkpoint 都不进生产),但**结果值得存档**
避免未来会话重跑同样的死路。

## 实验结果总表

| # | 报告 | Diamond LOO | Gyroid LOO | vs v1(12.79/16.95)| 进主干? | 理由 |
|---|---|---:|---:|---|:---:|---|
| 1 | [`2026-04-15-egdip-gompertz-scratch.md`](2026-04-15-egdip-gompertz-scratch.md) | 10.68% | 14.73% | 两侧都更好 ~2-2.2pp | ❌ | Gompertz 4 参数拟合中 $Re_t$ 在多几何上解不到过渡区(L=8 卡在默认 1500,L=4/5 飞出数据范围),提升有限且依赖初值;物理可解释性弱 |
| 2 | [`2026-04-15-egdip-gompertz-fullL8-scratch.md`](2026-04-15-egdip-gompertz-fullL8-scratch.md) | 14.54% | 24.93% | 两侧都变差 | ❌ | 解除 `_L8_RE_MIN=1600` 过滤,想给 Gompertz ramp 提供低 Re 过渡信号,反而污染 fit(L=8 低 Re 段 A<0 问题被激活),**证伪"扩大 Re 范围能让 Gompertz 起作用"** |
| 3 | [`2026-04-15-direct-dp-mlp-scratch.md`](2026-04-15-direct-dp-mlp-scratch.md) | **8.89%** | **14.18%** | 两侧都更好 ~3-4pp | ❌ | Correa 2026 路线,直接 MLP $\log_{10}\Delta P = f(L, t, \varepsilon_f, Re)$,初始架构(hidden 32, 2 层)。**数值上打败 v1**,但 in-sample 3.4/5.1% → LOO 8.9/14.2% 的泛化 gap 偏大 |
| 4 | [`2026-04-15-direct-dp-mlp-reg-scratch.md`](2026-04-15-direct-dp-mlp-reg-scratch.md) | 9.33% | 25.40% | Diamond 略差,Gyroid 崩 | ❌ | 同 #3 但 dropout 0.05→0.15、wd 3e-4→1e-3 正则化加强。目的是收紧 gap,结果 Gyroid in-sample 飙到 13.5%(bias 变大,不是 variance 问题)→ 正则化方向错了 |
| 5 | [`2026-04-15-direct-dp-mlp-wide-scratch.md`](2026-04-15-direct-dp-mlp-wide-scratch.md) | **8.09%** | **9.17%** | **两侧都更好 4.7/7.8pp** ⭐ | ❌ | 同 #3 但 hidden 32→64, 层数 2→3。**数值上是所有探索中最强**,击败 v1 最显著,但**仍不入主干**,原因如下 |

## 为什么最强的 Direct-ΔP wide 变体也不入主干

虽然 Diamond LOO 从 12.79% → 8.09%(−37%),Gyroid LOO 从 16.95% → 9.17%(−46%),但:

1. **失去物理可解释性**:输出是直接的 $\log_{10}\Delta P$,没有 $(K, c_F)$ 可用于下游求解器的 body-force 源项。Correa 2026 paper 本身也是这个路线,放弃 D-F 体形
2. **求解器集成难**:当前 `simple_solver.py` 的 `_porous_src_df` 要求 $(K, c_F)$ 作为输入,直接 MLP 输出 ΔP 没法直接插进动量方程。改造求解器接口的工程成本大
3. **外推风险未知**:训练域内 LOO 是低误差,但 Shanghai 这种 $t=0.6$ 超出训练范围的几何,wide 变体外推的行为**比 ConstDF-v1 更不可预测**(网络更宽更容易学到训练数据特定形状,边界衰减更极端)。ConstDF-v1 的 Shanghai 外推虽然 70% 欠预测,至少方向和物理一致(K 变小 c_F 变小);wide MLP 的外推可能是任意方向
4. **物理闭合形式的论文价值**:保留 D-F 闭合允许在论文里说"我们的代理在保留物理结构的前提下达到 12-17% LOO",这比"我们训了一个黑箱 MLP 达到 8-9% LOO"更有学术论点

**决策时刻**:用户在 2026-04-15 下午明确说"我们先不要追求把 15% 降低到 8%,目前我感觉可以",所以 ConstDF-v1 锁定为基线,wide MLP 的数值优势不被采纳。

## 对应的 Python 代码(scratch,留在原地)

- `thermoNas/df_fit/scratch_direct_dp_mlp.py`
- `thermoNas/df_fit/scratch_egdip_gompertz.py`

这两个脚本产生了上面 5 个报告,**留在原地**不动(移动会破坏 import 路径)。
它们被 `.gitignore` 接管但命名前缀 `scratch_` 明确标识其状态。

## 和 Kim 系列诊断的区别

注意 `reports/constdf-v1/2026-04-15-kim-*.md`(Kim K₁ / Kim-adapted / Kim-constrained)也是
被否的备选方案,但那些**不是** scratch——它们是 ConstDF-v1 baseline 论证里
"为什么不选 Kim 路线"的正式证据,留在主 `reports/` 目录。

**区分原则**:
- **主 `reports/`** = 当前 baseline 的支撑证据 + 已被 baseline 否决的**正式**对照方案
- **`reports/scratch/`** = ConstDF-v1 锁定**之后**为了"想再优化"做的额外探索,全部
  不入主干,但记录失败原因避免重做

## 后续应不应该再尝试

| 场景 | 回这个目录查哪个 |
|---|---|
| 有新 CFD 数据(Re < 400 低 Re 段) | EG-DIP #1 #2 — Gompertz ramp 在新数据上可能真起作用,值得重跑 |
| 决定放弃物理可解释性追求精度 | Direct-ΔP #5(wide)是起点,它已经跑到 8-9% 级 |
| 想做"物理约束的 MLP" | 尝试把 ConstDF-v1 的 $(K, c_F)$ 做成 Re 条件的函数,但保留 D-F 体形。**这是我们还没试过的方向** |

## Metadata

- 创建时间:2026-04-15,合入 commit 待定
- 所有实验基于 2026-04-15 的 ConstDF-v1 baseline(Diamond 12.79 / Gyroid 16.95)
- 未来如果 baseline 换代,这里的数字需要重算或标记为历史
