---
type: report
date: 2026-04-15
tags: [report, audit, calculation-flow, Q-validation, C-1, Re-convention, Nu]
---

# Shanghai Q 验证完整计算流程(Case 16 走一遍,数字全部打出)

## 目的

记录 `validate_shanghai.py` 从读取 Shanghai Excel 原始数据到输出 Q_sim 的
**每一步数值计算**,作为审计基准和未来调试参考。在 2026-04-15 完成两次 Re
约定修复(`ρ_atm → ρ_actual`,`r_h → D_h`)后执行,所以下面的数字反映最终状态
(max |err_Q%| = 3.71% 不含 Case 12 异常)。

以 **Case 16** 为例(high-Re 段,误差最大的 case)。

## Step 0 — 固定几何量(对 16 个 case 不变)

```
TPMS       = Gyroid
L_cell     = 7.0 mm
t_wall     = 0.6 mm
k_solid    = 16 W/(m·K)

(从 tpms_calc.geometry 积分得到)
EPS        = 0.736826       (总孔隙率)
eps_f      = EPS / 2 = 0.368413   (单股流体孔隙率)
D_h        = 3.4236 mm      (水力直径,= 4·eps/A_0)
A_0        = 430.4 m⁻¹      (比表面积,单位体积内固液界面面积)

(validate_shanghai.py 里写死)
L_DOM      = 0.231 m        (样机流道长度)
H_DOM      = 0.042 m        (截面高)
N_UNITS    = 36             (并联单元格数)
A_FLOW_PER_UNIT = 18.0565e-6 m²    (≈ eps_f × L_cell²,单股开流面积)
A_FLOW     = 36 × 18.0565e-6 = 6.5003e-4 m²
```

## Step 1 — 读 Shanghai Excel 原始数据

`data/raw_data/20260401-上海电气天然气加热器实验工况.xlsx`, sheet Sheet1,
skiprows=2, case 16 → row index 15。

| col | 量 | Case 16 值 |
|---:|---|---:|
| 5  | `m_air`(样机空气流量,kg/s)| **0.040984** |
| 28 | `T_Ain_C`(空气入口温度,°C)| 97.51 |
| 30 | `P_Ain_g`(空气入口表压,Pa)| 203,420.5 |
| 24 | `T_Bin_C`(水入口温度,°C)| 38.75 |
| 25 | `T_Bout_C`(水出口温度,°C)| 42.00 |
| **33** | **`Q_exp`**(样机实测空气侧换热量,W)| **2481.3** ← target |

## Step 2 — 推导空气物性(入口态)

```
T_Ain_K   = T_Ain_C + 273.15 = 370.66 K
P_Ain_abs = P_atm + P_Ain_g   = 101325 + 203421 = 304,745.5 Pa

rho_A = air_density(T_Ain_K, P_Ain_abs)
      = P_Ain_abs / (R_air × T_Ain_K)
      = 304745.5 / (287 × 370.66)
      = 2.8644 kg/m³                       ← ideal gas, ACTUAL inlet pressure

mu_A  = air_viscosity(T_Ain_K)             ← Sutherland
      = 2.1627e-5 Pa·s

k_A   = air_conductivity(T_Ain_K)
      = 0.03095 W/(m·K)

cp_A  = air_cp(T_Ain_K)
      = 1020.55 J/(kg·K)
```

**关键**:`rho_A` 用 **actual inlet pressure**(304745 Pa),不是 `P_atm`
(= 101325)。这是 Bug #1 的修复点,2026-04-15 修。修前 rho_ref = 0.96 kg/m³
(atm@370K),修后 rho_A = 2.86 kg/m³,相差 3×,对应 P 变化 3×。

## Step 3 — 单股孔隙速度 u_A

```
u_A = m_air / (rho_A × A_FLOW)
    = 0.040984 / (2.8644 × 6.5003e-4)
    = 22.0112 m/s
```

**物理含义**:`u_A` 是 Shanghai 样机里 36 个并联 Gyroid 空气通道中,每个通道
内部的 interstitial velocity(单股,不是表观)。因为 m_air 本身就是空气侧的
**全部**质量流(水侧单独走水,不混),**所以 u_A 已经是单股速度,不需要再除 2**。

## Step 4 — Reynolds 数(D_h 约定,actual ρ)

```
Re = rho_A × u_A × D_h / mu_A
   = 2.8644 × 22.0112 × 3.4236e-3 / 2.1627e-5
   = 9980.9
```

这是**两次 bug 修复后的最终版本**:
- 用 `rho_A`(actual pressure 下的 ρ),不是 `rho_ref = air_density(T, P_atm)`
- 用 `D_h`,不是 `r_h = D_h/2`

### Bug 修复历史

| 版本 | 公式 | Case 16 Re | C-1 max Q err |
|---|---|---:|---:|
| 原始(2026-04-13 baseline) | `ρ_atm × u × r_h / μ` | 1,659 | **−21.8%** |
| Fix 1(2026-04-15 上午) | `ρ_actual × u × r_h / μ` | 4,990 | **−4.92%** |
| **Fix 2(2026-04-15 下午)** | **`ρ_actual × u × D_h / μ`** | **9,981** | **−3.71%** |

和 Shanghai Excel col 2 "空气Re" 的设计目标值 9000 对应(11% 差来自工况 ρ 随
P 变化,偏离 CFD 设计时的目标 Re)。

### 训练数据的 Re 约定(解释为什么 D_h 是对的)

训练 Excel `试验记录表_整理版.xlsx` 的 Re 列数字(比如 D_8_03 row 1 的 400)
来自:

```
Re_stored = ρ × (m_cfd / 2) × D_h / (ρ × A_single × μ)
          = ρ × u_single_stream × D_h / μ
```

其中:
- CFD 跑的是 ONE Gyroid 单元格,有两条对称通道(Gyroid 面把空间分成两半)
- CFD 报告的总 mass flow 要除以 2 才能得到"单股流体通过一个通道的 m"
- u_single_stream = (m_cfd / 2) / (ρ × A_single_channel)

训练 Excel col 13 的 u 是 `m_cfd / (ρ × A_single)` 即 **2 × u_single_stream**,
所以训练 Re 公式用 `ρ × u_col13 × r_h / μ`(等价于 `ρ × (u_col13/2) × D_h / μ`)
得到 400 这个数字。

**Shanghai 的 m_air 已经是单股**(只流空气那一条通道),所以 Shanghai u_A 本身
就是 single_stream 速度,直接用 `ρ × u_A × D_h / μ` 就对。训练公式里的 /2
对 Shanghai **不适用**,否则相当于多除以了一次 2。

## Step 5 — Nu → H_sf → h_vA

调用 `tpms_calc.compute(Gyroid, L=7.0, t=0.6, u=22.0112, T=370.66, P=304746)`:

```
内部算 Re = 9980.9(和 Step 4 一致,sanity check ✓)

_nu_gyroid(Re, eps, L_cell):
  n = 0.177 × Re^0.1 × eps^(-2/3)
    = 0.177 × 2.5114 × 1.2258
    = 0.5449
  Nu = 0.17 × Pr^(1/3) × Re^n × eps^2.25 × (L_cell / (1000·Sa))^(-2.01)
     = 0.17 × 0.8963 × 151.05 × 0.5030 × 19.9063
     = 230.454

H_sf = Nu × k_A / D_h
     = 230.454 × 0.03095 / 3.4236e-3
     = 2083.65 W/(m²·K)

h_vA = A_0 × H_sf
     = 430.4 × 2083.65
     = 896,878 W/(m³·K)       ← scalar,整个 2D 场都用这一个值
```

**修前对比**(Fix 2 之前,用 r_h):

| 量 | 修前(r_h) | **修后(D_h)** | 比值 |
|---|---:|---:|---:|
| Re | 4,990 | **9,981** | 2.00 |
| Nu | 115.77 | **230.45** | 1.99 |
| H_sf | 1,046.77 W/(m²·K) | **2,083.65 W/(m²·K)** | 1.99 |
| h_vA | 450,566 W/(m³·K) | **896,878 W/(m³·K)** | 1.99 |

h_vA 翻倍(Nu 随 Re 的 n≈0.55 次幂,但因为 Re 加倍所以 Nu 也基本加倍)。

## Step 6 — 有效热导(静态导热 × 孔隙率)

```
K_ffA = eps_f × k_A              = 0.368413 × 0.03095 = 0.01140 W/(m·K)
K_ffB = eps_f × k_water(T_Bin_K)  = 0.00990 W/(m·K)    (水侧对流导热,入口温度)
K_ss  = (1 − EPS) × k_solid       = 0.2632 × 16        = 4.2108 W/(m·K)
```

**注意**:**没有 thermal dispersion 修正项**。纯静态导热乘孔隙率。Popov 2025
论证过高 Pe 段应该加一个 $k_\text{disp} \propto \text{Pe}$ 项,但没做。剩下的
2-4% 系统欠预测**可能**部分来自这里(次级,不再是主因)。

## Step 7 — 水侧冻结(C-1 约定)

```
h_vB = 1.0e10 W/(m³·K)                     ← 视作理想无限大换热
Tb_prescribed(x, y) = T_Bout + (T_Bin − T_Bout) × (y / H_DOM)
                   = 42.00 + (38.75 − 42.00) × (y / 0.042)    [℃,线性]
```

物理含义:水侧的 T(x, y) 场**被固定**成按 y 方向从实测 T_Bout 到 T_Bin 的线性
分布,不参与迭代。因为 `h_vB = 1e10`,固体 T_s 会被强制拉到这个 prescribed
Tb 场(C-1 约定:假设水侧换热完美,只验证空气侧模型)。

## Step 8 — LTNE 温度场求解(`solve_full.solve_full_domain`)

**网格**:`adaptive_grid(0.231, 0.042, D_h=3.4236e-3, alpha=0.4)` 返回 `N_X=169, N_Y=31`。

**速度场**:
```python
ucA_real = np.full((169, 31), u_A=22.0112)    ← 常数填充,不用 SIMPLE 的输出
vcA_real = np.zeros((169, 31))                ← 无横向速度
```

**为什么硬填常数**:validate_shanghai.py line 108-126 的注释记录了一个遗留问题
——SIMPLESolver 输出的 u 场比 u_A 大约 **3 倍**(疑似 eps_f 双重计数,下游 C-3
scope)。当 C-1 做验证时,为了绕开这个 bug,直接用常数 u_A 填充。**这是一个
workaround,不是物理最优**,但让 Q 验证可以进行。

**方程**(LTNE,三耦合):

```
fluid A:   eps_f · rho_cp_A · (u·∇)T_A  =  K_ffA · ∇²T_A  +  h_vA · (T_s − T_A)
solid:     0  =  K_ss · ∇²T_s  +  h_vA · (T_A − T_s)  +  h_vB · (T_b − T_s)
fluid B:   T_b(x,y) 冻结 = Tb_prescribed(固定不迭代)
```

**传入数值**:
```
T_Ain_K   = 370.66 K
T_Bin_K   = 311.90 K (水,入口)
K_ffA     = 0.01140 W/(m·K)
K_ffB     = 0.00990 W/(m·K)
K_ss      = 4.2108 W/(m·K)
h_vA      = 896,878 W/(m³·K)    ← 本次修复后的值
h_vB      = 1e10 W/(m³·K)
rho_cp_A  = rho_A × cp_A = 2.8644 × 1020.55 = 2923.31 J/(m³·K)
dir_A     = 0                    ← air 向 +x 方向流
dir_B     = 3                    ← water 向 −y 方向流(C-1 约定)
```

求解器是 FVM(Patankar-style) Gauss-Seidel 迭代,收敛判据 `max|ΔT| < 1e-6`。

## Step 9 — 从出口温度场反算 Q_sim

```
Ta[-1, :] shape = (31,)    ← i=Nx-1 是出口列(dir_A=0 对应 +x)
  min  = 311.962 K   (38.81 °C)
  max  = 315.110 K   (41.96 °C)
  mean = 313.5360 K  (40.39 °C)

T_A_out_sim = np.mean(Ta[-1, :]) = 313.5360 K

ΔT_air = T_Ain_K − T_A_out_sim
       = 370.66 − 313.5360
       = 57.1241 K

Q_sim = m_air × cp_A × ΔT_air
      = 0.040984 × 1020.55 × 57.1241
      = 2389.32 W
```

**为什么用算术平均**:因为 `ucA_real` 是常数场,所有 y 位置 u 相同,ρ 也是单个
scalar(虽然物理上 ρ 应该随 P 变),所以"算术平均"和"质量加权平均"在数值上
完全相等。

## 最终

```
Q_sim = 2389.32 W    (solver 输出)
Q_exp = 2481.30 W    (Shanghai Excel col 33)

err = (Q_sim − Q_exp) / Q_exp = −3.709%
```

## Shanghai 16-case 汇总(2026-04-15 双重修复后)

| Case | u_A | Re(D_h) | dP_exp | dP_sim | dP err | Q_exp | Q_sim | Q err |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1  | 3.916 | 526 | 1149 | 1721 | +49.8% | 248 | 245 | −1.21% |
| 2  | 8.025 | 1002 | 5195 | 6392 | +23.0% | 621 | 618 | −0.48% |
| 3  | 11.60 | 1480 | 11103 | 13307 | +19.9% | 975 | 969 | −0.62% |
| 4  | 14.39 | 1978 | 18456 | 21658 | +17.3% | 1269 | 1263 | −0.47% |
| 5  | 18.65 | 2957 | 36260 | 42321 | +16.7% | 1891 | 1880 | −0.58% |
| 6  | 21.25 | 3928 | 58703 | 66570 | +13.4% | 2514 | 2488 | −1.03% |
| 7  | 21.78 | 4460 | 71067 | 78468 | +10.4% | 2606 | 2577 | −1.11% |
| 8  | 22.06 | 5051 | 81997 | 89370 | +9.0% | 2796 | 2779 | −0.61% |
| 9  | 22.11 | 5642 | 94497 | 100619 | +6.5% | 2783 | 2752 | −1.11% |
| 10 | 22.13 | 6248 | 106605 | 111780 | +4.9% | 2776 | 2739 | −1.33% |
| 11 | 22.18 | 6860 | 118287 | 123077 | +4.1% | 2780 | 2738 | −1.51% |
| **12** | 22.28 | 7478 | 129213 | 134414 | +4.0% | **2536** | **2680** | **+5.68%** ⚠ |
| 13 | 22.44 | 8076 | 140259 | 146380 | +4.4% | 2727 | 2665 | −2.27% |
| 14 | 22.38 | 8714 | 151917 | 157631 | +3.8% | 2648 | 2580 | −2.57% |
| 15 | 22.21 | 9345 | 165067 | 169177 | +2.5% | 2561 | 2478 | −3.24% |
| 16 | 22.01 | 9981 | 178684 | 180732 | +1.2% | 2481 | 2389 | −3.71% |

### 汇总统计

| | dP_air(f_re 路径) | **Q(本次修复后)** |
|---|---:|---:|
| max \|err\| | 49.8%(Case 1) | **5.68%(Case 12 异常)** |
| max \|err\|(除 Case 12) | — | **3.71%(Case 16)** |
| mean \|err\| | 11.92% | **1.72%** |
| signed mean | +11.92%(全正) | −1.01%(弱系统欠) |

## Case 12 为什么是异常点

看原始 Excel 数据:

| Case | m_air | T_Ain | P_Ain_g | **Q_exp** |
|---:|---:|---:|---:|---:|
| 10 | 0.0273 | 131.24 | 119142 | **2775.8** |
| 11 | 0.0296 | 123.81 | 132580 | **2780.0** |
| **12** | 0.0319 | **117.10** | 145241 | **🔴 2535.9** |
| 13 | 0.0342 | 112.85 | 158100 | **2726.9** |
| 14 | 0.0364 | 106.77 | 171769 | **2648.0** |

**所有输入(m, T, P)都是单调变化的,只有 Q_exp 在 Case 12 突然低 200 W
然后 Case 13 又回来**。我们的 solver 输出 Q_sim 11→12→13 = 2738, 2680,
2665 是光滑单调下降(合理)。Case 12 的 Q_exp 几乎肯定是实验测量/录入异常,
不是 solver 问题。

## 误差分析图

保存在 `reports/figs/shanghai/shanghai_validation_post_fix.png`,4 个子图:

1. **左上** dP parity(log-log),颜色=Re,low-Re 段点偏离 y=x 最远
2. **右上** Q parity,几乎全部点在 ±5% 带内,只有 Case 12 跳出
3. **左下** dP err vs Re,单调从 +50% 降到 +1%(f_re 低 Re 外推问题,和本次
   修复无关)
4. **右下** Q err vs Re,大多 case 在 −1 ~ −4%,Case 12 突兀在 +5.7%

## 还剩下什么

### Q 侧 ✓(已基本完成)

残余的 Case 13-16 约 3-4% 系统欠预测**可能**来自:

1. **`h_vA` 是 scalar 不随位置变**——真实 Nu 应局部变化
2. **Thermal dispersion 缺失**(Popov A1)——在高 Pe 段是次级效应(不再是主因)
3. **可压缩性次级效应**——沿流道 ρ 从 2.86 降到 ~0.96,u 从 22 涨到 65 m/s,
   但 solver 用常数 u_A

3-4% 已在工程精度内,不建议继续深挖。

### dP 侧(f_re 路径)⚠(仍在)

f_re path 的 Re 计算(`simple_solver._porous_src`)和 `pressure_drop()` 还在用
老约定 `ρ_atm + r_h`。Shanghai dP 从低 Re 的 +50% 递减到高 Re 的 +1%,
单调正偏。**两次 Re 修复对 dP 没有任何影响**(dP 路径独立)。

要修 dP,需要:
1. 把 `_porous_src` 里 `rho_ref = air_density(T_in, P_atm)` 改成用 local ρ
2. 把 `_f_re` 的调用里 `r_h` 改成 `D_h`
3. 重跑 Shanghai 看 dP 改善情况
4. 这会改变 C-1 dP 基准,需要更新 `validation_snapshot_c1.csv` 的 dP 参考

**是一个独立决策**,不在本次修复范围内。

## 相关 commit

- Q 路径修复(本次):`tpms_calc.py:compute()` 的 Re 公式修改,待 commit
- Shanghai DF 集成(4-15 早):`a621755 feat(solver): add closure='df' path`
- Re/Nu 约定审计(4-15 中):`c01d45b docs(audit): Re/Nu convention audit`
- ConstDF-v1 baseline:`ab7a39e baseline: ConstDF-v1 D-F surrogate`

## 结论一句话

**Shanghai C-1 的 21.8% 高 Re Q 误差**(原始 2026-04-13 C-1 baseline 遗留的最
大已知问题)**已被追溯到 `tpms_calc.compute()` 里 Re 约定的两个 bug,并已修复**,
**新的 max |err_Q%| = 3.71%**(Case 12 异常除外)。**不是 thermal dispersion**。
f_re 路径的 dP 侧误差(Case 1 +50% 等)**是独立问题**,本次未修。
