---
type: report
date: 2026-04-15
tags: [report, diagnostic, ConstDF-v1, residual-structure, Forchheimer-transition, SJTU-TPMSHX]
---

# ConstDF-v1 ΔP 残差结构诊断 —— 2-term D-F 闭合的物理下限

## 一句话结论

所有 24 个训练几何的 in-sample 相对 ΔP 残差(用 ConstDF-v1 全数据 ensemble
算)都呈现**同一个 U 形**:低 Re 正偏、中 Re(≈ 800–2000)负偏(谷底
−15 ~ −25%)、高 Re 回正。这是 2-term Darcy-Forchheimer 闭合形式的
**结构上限**,不是模型容量问题,无法靠更大的 MLP 或更多数据消除。
**ConstDF-v1 LOO ΔP MAPE 12.79% / 16.95% 就是这一形式在本训练集上的
可达下限。**

## 方法

- 用 baseline commit `ab7a39e` 里的 `models/df_surrogate_{diamond,gyroid}.joblib`
  ——即 ConstDF-v1 全数据 5× MLP ensemble
- 对每个训练行(Diamond 145 + Gyroid 183,L=8 已按 Re ≥ 1600 过滤)算
  $$\varepsilon_i = (\Delta P_{{\rm pred},i} - \Delta P_{{\rm obs},i}) / \Delta P_{{\rm obs},i}$$
- **in-sample**(非 LOO):留一会把 generalisation 噪声混进来,而我们要
  隔离的是闭合形式自身的误差分量
- 脚本:`sjtu_tpmshx/df_fit/plot_residual_vs_re.py`
- 图:`reports/figs/df_fit/residual_vs_re.png`,3 行 × 2 列
    - 行 1:signed 散点 + log-Re 分箱中位数平滑
    - 行 2:|residual| 散点 + 平滑
    - 行 3:per-(L, t) 折线(每几何一条,按 Re 升序连点)

## 观察

### 1. U 形是普遍的,不是个别几何的毛病

第 3 行的 per-geometry 轨迹图是核心证据。12 条 Diamond 折线 + 12 条 Gyroid
折线,**几乎每一条都是 U 形**:

- 低 Re 端($Re \sim 10^2$~$10^3$):正残差,模型高估 ΔP,峰值 +30 ~ +50%
- 谷底($Re \approx 800$~$2000$):负残差,模型低估 ΔP,−15 ~ −25%
- 高 Re 端($Re \gtrsim 3000$):回到正残差或零附近

不是"某几个坏几何",是**所有几何共享的系统偏差**。

### 2. Diamond 和 Gyroid 都有,只是振幅不同

第 1 行的 binned-median 黑线在两张图上都在中段 Re 压到负数区。之前基于
row-1 scatter 认为"Gyroid 有驼峰、Diamond 没有"的判断是错的——Diamond 的
U 只是更浅(多数在 ±15% 内),被其他几何的噪声盖住,一画轨迹就显形。

量化:

| TPMS | U 谷底深度(中位数) | 两端峰值(中位数) |
|---|---|---|
| Diamond | ≈ −10% | ≈ +15% |
| Gyroid | ≈ −18% | ≈ +20% |

Gyroid U 更深 ≈ 8pp,正好对应 Gyroid LOO MAPE 比 Diamond 高 4pp。

### 3. U 的中心落在 Forchheimer 过渡区

谷底 Re ≈ 800–2000 正好是多孔介质文献里的 "Forchheimer transition" 区段
——从 Darcy 区(线性)向 Forchheimer 区(二次占主导)切换的过程中,
真实 $\Delta P(u)$ 曲线有一段局部凸度(向上弯)比纯二次项要强,2-term
$(\mu u/K + \rho c_F u^2)$ 体形在数学上无法表达这种局部凸度。

WLS 在这种情况下会选"折中"参数:牺牲谷底的准确性去压低两端的权重
(权重 $w_i = 1/\Delta P_i^2$ 本来就给高 Re 点更低权重),结果就是两端
残差为正、中段为负。

## 解释

### 2-term D-F 的体形极限

记真实的单位长度压降是 $f(u)$,2-term D-F 假设

$$f(u) = a u + b u^2 , \quad a = \mu/K ,\ b = \rho c_F$$

固定 $(a, b)$ 只能表达"线性 + 二次"的两点曲率。如果真实 $f(u)$ 在某个
$u^\star$ 附近有

$$\frac{d^2 f}{d u^2}\bigg|_{u^\star} > 2b$$

(即真实曲线在这里比最佳二次拟合还要"更凸"),那么任何 $(a, b)$ 的选
法都会在 $u^\star$ 附近留下**负残差**(低估),在 $u^\star$ 两侧留下
**正残差**(高估)。U 形残差就是这个现象的视觉签名。

这不依赖任何具体物理(drag crisis、inertial core flow、TPMS 拓扑 3D 效应),
只是"用二次函数去拟一条三次以上曲率的曲线"的几何后果。

### 文献对应

- **Barree & Conway (SPE 89325, 2004)**:早期提出 Forchheimer 系数 $\beta$
  不是常数,随 Re 变化,在过渡区"凸起"
- **Balhoff, Mikelić, Wheeler (2010)**:从均质化严格证明了
  $\Delta P = \mu u/K + \rho c_F u^2 + c_3 u^3 + O(u^4)$,三次系数 $c_3$
  符号未定,但非零项意味着 2-term 必然在某个 Re 段系统性偏
- **Popov 2025**(TPMS 专题):直接报过这个 U 形残差,称之为 "intermediate
  Reynolds regime discrepancy",并把它归因于 thermal dispersion 的动量侧反向
  耦合

(文献笔记全在 vault,`Balhoff-Mikelic-Wheeler-2010-Polynomial-Filtration-Laws.md`
和 `Popov-2025-TPMS-Two-Medium-SJTU-TPMSHX.md`)

## 对 ConstDF-v1 的含义

**1. 12–17% 是形式极限,不是参数极限。** 无论怎么调 MLP 超参、怎么加
geometry 通道、怎么换归一化,只要保留 2-term D-F 闭合,MAPE 下限就是 U 振
幅的一半左右。Diamond 约 10–12%,Gyroid 约 16–18%。**这正好是我们测到的
LOO 数字。**

**2. v2(Re-dependent K/c_F)之所以在 Diamond 上从 12.79% 降到 8.25%,是因
为 MLP 把 $K(Re)$ 和 $c_F(Re)$ 弯成了能吸收 U 曲率的形状。但 Gyroid 上从
16.95% 退到 24.21% 的原因同样出在这里:12 个几何 × 145–183 行的数据量,
不足以稳定训出 4 维输入的 MLP,尤其当 Gyroid 的 U 更深、对"弯成什么形
状"更敏感。**v2 失败不是路线错,是数据量不够支撑多出来一个输入维度的
额外自由度。

**3. 要真正穿透 12–17% 的下限,要么:**
- 保留 D-F 体形 → 加 3 次项(BMW 路线),风险:$c_3$ 符号/量级凭经验,过
  拟合概率高
- 抛弃 D-F 体形 → 直接 MLP → ΔP/L(Correa 2026 路线,3.5%),代价:失去
  物理可解释性、求解器耦合复杂
- 补 Re < 100 的 CFD 点 → 让 Re-dependent 方案有足够训练信号(被用户明确
  拒绝)

ConstDF-v1 是"保留体形 + 现有数据量 + LOO 稳健"三者的唯一交点。

## 对下游求解器评估的预测

把 ConstDF-v1 接进 `simple_solver._porous_src`,跑 Shanghai 16-case vs
C-1 baseline 时,**预期的误差方向是系统性的,不是随机的**:

| 工况 Re 段 | 预期偏差方向 | 量级 |
|---|---|---|
| $Re \lesssim 500$ | ΔP **高估** | +5 ~ +15% |
| $Re \approx 800$–$2000$ | ΔP **低估** | −10 ~ −20% |
| $Re \gtrsim 3000$ | ΔP 接近或略高估 | 0 ~ +10% |

如果 Shanghai case 的设计 Re 主要落在 U 谷底附近,总 ΔP 会系统性偏低,
**这不是求解器耦合 bug,是代理模型的结构偏差**——看到这个现象时应准确
归因。

## 这张图**不能**说什么

- **不是 LOO 残差**:用的是 full-data ensemble 在训练行上评估。LOO 会在
  形式误差之上再加一层泛化噪声,但形式误差的 U 形状不会因 LOO 消失
- **不是"已证" 驼峰 = Forchheimer transition**:U 形状和 Forchheimer 过渡
  *consistent*,但单凭残差图不能证明机制。若要硬主张机制,要补分区域
  的雷诺数诊断(边界层厚度、惯性子层判据)或者 DNS 对比
- **不等于"v1 一定不能改进"**:3 次项、局部多项式、分段模型都可能继续
  降低 MAPE。只是都会以"失去物理可解释性 / 需要更多数据 / 数值稳定性"
  其中之一为代价

## 相关

- 图:[`figs/df_fit/residual_vs_re.png`](figs/df_fit/residual_vs_re.png)
- 脚本:`sjtu_tpmshx/df_fit/plot_residual_vs_re.py`
- 上游 ensemble:`models/df_surrogate_{diamond,gyroid}.joblib`(ConstDF-v1)
- 对比报告:
  - [`2026-04-14-DF-surrogate-loo-report.md`](2026-04-14-DF-surrogate-loo-report.md) — LOO 主结果
  - [`2026-04-14-DF-re-independence-report.md`](2026-04-14-DF-re-independence-report.md) — Pearson Re 独立性前置
