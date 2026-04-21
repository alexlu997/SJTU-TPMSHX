---
title: SJTU-TPMSHX 压降与换热量预测方法
date: 2026-04-16
tags: [SJTU-TPMSHX, D-F, 压降, 换热, TPMS, 方法论]
---

# SJTU-TPMSHX 压降 (dP) 与换热量 (Q) 预测方法

## 一、压降预测

### 1.1 物理模型：1D 可压缩等温 Darcy-Forchheimer

从 D-F 局部动量方程出发：

$$-\frac{dP}{dx} = \frac{\mu}{K} u + \rho c_F u^2$$

两边乘密度 ρ，用质量通量 G = ρu（沿程守恒）代换：

$$-\rho \frac{dP}{dx} = \frac{\mu}{K} G + c_F G^2$$

右边为常数。代入理想气体 ρ = P/(RT)，积分从入口到出口：

$$P_{in}^2 - P_{out}^2 = 2RT \left( \frac{\mu G}{K} + c_F G^2 \right) L$$

预测时：

$$P_{out} = \sqrt{P_{in}^2 - 2RT \left( \frac{\mu G}{K} + c_F G^2 \right) L}$$
$$\Delta P = P_{in} - P_{out}$$

**为什么用 G 而非 u**：可压缩流中 ρ 和 u 沿程都变，但 G = ρu 守恒，使方程右边为常数，可以解析积分。当 dP/P → 0 时退化为不可压形式 dP = (μu/K + ρc_F u²)·L。

### 1.2 参数标定流程

**数据来源**：试验记录表_整理版.xlsx

- dP_raw：col 43 (Pressureloss_TPMS)，TPMS 区域压损（含边界效应）
- G：col 48 (AW)，质量通量 kg/(m²·s)
- T：col 7，进口温度（等温假设）
- μ：Sutherland 公式(T)
- P_in = P_atm + dP_raw，P_out = P_atm（出口表压为 0）

**Step 1：可压缩 WLS 拟合（每个几何）**

对每个几何 (L, t) 的 n 行数据，构造：

$$y_i = \frac{P_{in,i}^2 - P_{atm}^2}{2 R T_i L_{ch}}$$

其中 L_ch = K_S_CELLS × L_mm × 10⁻³（训练 CFD 域长度，K_S_CELLS = 10）。

线性方程：y_i = μ_i G_i · (1/K) + G_i² · c_F

WLS 求解（权重 w = 1/y），得到 (1/K_raw, c_F_raw)。

**Step 2：边界效应修正**

每个几何一个实验标定系数 α（来自 sheet "边界效应系数"，范围 0.37-0.53）：

$$c_F = \alpha \times c_{F,raw}$$
$$K = K_{raw} / \alpha$$

**Step 3：RBF 插值**

对新几何 (L, t, ε_f)：
- c_F：RBF 精确插值（薄板样条核，12 个 Gyroid 训练点）
- K：RBF 插值 + 钳位 K ≥ 10⁻⁷（物理依据：使 Darcy 项占比 ≤ 15%）

K 钳位原因：训练数据最低 Re ≈ 400，此时 Forchheimer 已主导。L=8 的 K 在 WLS 中无约束（Re ≥ 1600 全在 Forchheimer 区）。钳位值 10⁻⁷ 保证在 Re > 500 时 Darcy 占比 < 15%，不干扰预测。

**注意**：L=8 几何剔除了 Re < 1600 的数据（过渡区，D-F 模型不适用）。

### 1.3 精度

| 指标 | 值 |
|------|-----|
| 训练集域内 dP MAPE（per-geometry WLS） | 1-4% |
| LOO dP MAPE（留一几何交叉验证） | 15.7% |
| Shanghai 16 case RMSRE | 10.3% |
| Shanghai 逆拟合最优 c_F | 372.7 (RMSRE=4.5%) |
| 模型预测 Shanghai c_F | 340.7 |

### 1.4 代码入口

```python
from sjtu_tpmshx.df_fit.predict import predict_K_cF, predict_dP_compressible

# 获取 D-F 系数
K, c_F = predict_K_cF('Gyroid', L_mm=7.0, t_mm=0.6, eps_f=0.368)

# 1D 可压缩压降预测
dP = predict_dP_compressible('Gyroid', L_mm=7.0, t_mm=0.6, eps_f=0.368,
                              G=63.05, T=370.7, P_in=304746,
                              mu=2.16e-5, L=0.231)
```

核心文件：
- `sjtu_tpmshx/df_fit/surrogate_v3.py` — SurrogateV3 模型（标定 + RBF + 钳位）
- `sjtu_tpmshx/df_fit/predict.py` — 统一接口

---

## 二、换热量预测

### 2.1 方法

Q 的预测**不依赖 SIMPLE 求解器**。流程：

1. **速度场**：均匀速度 u = G/ρ（多孔介质近似 plug flow）
2. **换热系数**：Nu 关联式 → h_vA = A₀ · H_sf（来自 tpms_compute）
3. **温度场**：solve_full_domain（2D 能量方程求解器）
4. **换热量**：Q = m_air · cp · (T_in - T_out)

验证表明（Shanghai 16 case）：用均匀速度场和 SIMPLE 2D 速度场算出的 Q **逐 case 误差 < 1W**，完全等价。

### 2.2 关键参数

- h_vA：体积换热系数，由 Gyroid Nu 关联式计算：
  - n = 0.177 · Re^0.1 · ε^(-2/3)
  - Nu = 0.17 · Pr^(1/3) · Re^n · ε^2.25 · (L/(1000·S_a))^(-2.01)
  - H_sf = Nu · k / D_h
  - h_vA = A₀ · H_sf

- K_ss = (1 - ε) · k_s：固相等效热导率，k_s = 16 W/(m·K)（316L 不锈钢）
- 水侧：Tb 由实测入口/出口温度线性插值（prescribed），h_vB = 10¹⁰（完美热沉）

### 2.3 Shanghai Q 精度

Q 误差范围 -3.7% ~ +5.7%，与 SIMPLE 耦合方案完全一致。

### 2.4 代码入口

```python
from solvers.tpms_calc import compute as tpms_compute
from solvers.solve_full import solve_full_domain

# 换热系数
r = tpms_compute('Gyroid', L_cell, t_wall, u, T_in, P_in, K_S)
h_vA = A0 * r['H_sf']

# 温度场（均匀速度，无需 SIMPLE）
ucA = np.full((N_X, N_Y), u_A)  # 均匀速度代替 SIMPLE
Ta, Tb, Ts, info = solve_full_domain(...)

# 换热量
Q = m_air * cp * (T_in - np.mean(Ta[-1, :]))
```

---

## 三、与旧方法 (v1) 的区别

| | v1 (旧) | v3 (现) |
|---|---|---|
| D-F 公式 | 不可压: dP = (μu/K + ρc_F u²)·L | 1D 可压缩: P²形式 |
| 速度变量 | u (m/s)，沿程变化 | G (kg/m²s)，沿程守恒 |
| 压降列 | col 47 (修正压损) | col 43 (Pressureloss_TPMS) |
| 边界效应 | 未修正 | × α 系数 |
| 代理模型 | MLP (~1250 参数) | RBF (12 个插值点) |
| K 处理 | 和 c_F 一起由 MLP 预测 | RBF + 钳位 ≥ 10⁻⁷ |
| c_F 量级 | 22-150 | 187-1680 |
| Shanghai RMSRE | 74-82% | 10.3% |
| dP 验证 | SIMPLE (2D 可压缩) | 1D 可压缩公式（与标定一致） |
| Q 验证 | SIMPLE + solve_full | 均匀速度 + solve_full |

**v1 误差大的根因**：不可压公式 + 错误的压降列 + 无边界修正，导致 c_F 被系统性低估 10-30 倍。
