---
type: report
date: 2026-04-15
tags: [audit, convention, Reynolds-number, Nusselt, tpms_calc, bugfix-cosmetic]
---

# Re / Nu 约定审计报告

## 起因

在 Shanghai 验证调试过程中,用户对 `Re` 的约定产生怀疑——训练 Excel 里
的 Re 列可能和项目代码中使用的约定不一致。由于 Nu 关联式显式依赖 Re,
如果约定错配可能会造成 Q 预测的系统性误差(C-1 高 Re 段有 21.8% Q 误差
的遗留问题)。

本报告审计了 `tpms_calc.py`、`simple_solver.py`、`fvm_solver.py`、
`sigmoid_field.py` 里所有涉及 Re、$r_h$、$D_h$ 的代码位置,做了实证
验证,得到明确结论。

## 核心结论

**代码没有 Re 约定 bug**。C-1 21.8% Q 误差的原因不在这里。**但
`_nu_diamond` / `_nu_gyroid` 的 docstring 写错了**——原先写 Re 用 $D_h$,
实际用的是 $r_h$,经实证验证。本报告对此做了纯注释/文档修复,数值完全
不变。

## 项目全局 Re 约定

**所有参与计算的位置统一使用**:

$$Re = \frac{\rho \cdot u \cdot r_h}{\mu}, \qquad r_h = D_h/2$$

等价地(用户偏好的表达):

$$Re = \frac{\rho \cdot u \cdot D_h}{2\mu} = \frac{\rho \cdot (u/2) \cdot D_h}{\mu}$$

其中 "/2" 对应"单股流体处理"(每种流体占两个通道之一,把总 $\dot m$ 除
以 2 得到单流等效)。数学上两种表达完全等价。

训练 Excel `试验记录表_整理版.xlsx` 的 Re 列用此约定(L=6、L=8 几何已
实证核对;L=4 几何 Re 列数值异常,但**不影响下游计算**,因为:
- MLP 不以 Re 为输入
- `_L8_RE_MIN = 1600` 过滤只针对 L=8)

## 实证测试 1:Nu 列的定义

**问题**:训练 Excel col 40 `Nu` 用的是 $Nu = h \cdot D_h / k_f$
(标准 $D_h$ 定义) 还是 $Nu = h \cdot r_h / k_f$?

**方法**:对 Diamond 和 Gyroid 若干几何,从 col 39 `h/W/m2K` 和 col 40
`Nu` 反算两种定义下的 Nu,看哪种匹配 Excel 值。

**结果**(部分):

| 几何 | `h·D_h/k_f` 误差 | `h·r_h/k_f` 误差 |
|---|---:|---:|
| D_4_03 | 3.1% | 51.6% |
| D_6_04 | 3.2% | 51.6% |
| G_4_04 | 11.2% | 55.6% |
| G_6_04 | 3-4% | ~52% |

**Nu 列使用标准 $D_h$ 定义**。3-11% 的小误差来自空气物性温度取值小差异,
不是约定问题。

## 实证测试 2:Nu 关联式的 Re 约定

**问题**:`_nu_diamond(Re, eps, D_h_mm)` 和 `_nu_gyroid(Re, eps, L_cell_mm)`
接受的 Re 是 $r_h$ 约定还是 $D_h$ 约定?(docstring 原本写 $D_h$)

**方法**:对训练 Excel 中若干已知 Re (在 r_h 约定下)的行,分别用
`_nu_*(Re)` 和 `_nu_*(2×Re)` 计算,和 Excel Nu 列对比。

**结果**(部分):

| 几何 | Re_excel | Nu_stored | `_nu(Re_rh)` 误差 | `_nu(Re_Dh=2Re_rh)` 误差 |
|---|---:|---:|---:|---:|
| D_8_03 | 400 | 11.606 | +4.6% | +75.2% |
| D_8_03 | 600 | 16.786 | −2.2% | +63.7% |
| D_6_04 | 400 | 17.970 | +2.1% | +84.4% |
| G_8_03 | 600 | 18.393 | −1.8% | +52.2% |
| G_6_04 | 600 | 30.289 | −0.7% | +59.0% |

**`_nu_*` 是在 $r_h$-约定 Re 上拟合的**,虽然 docstring 写的是 $D_h$。
这是 docstring 错误,不是功能 bug。

## 实证测试 3:数据流完整性

从 CFD 到 Q 预测的完整数据流:

```
CFD 原始 (h, Re)        训练 Excel           关联式             Solver 使用
────────────────        ──────────          ──────             ─────────
真实 h [W/m²/K]  ────→  col 39: h           —                  —
真实 Nu = h·D_h/k ──→   col 40: Nu          —                  —
Re = ρ·u·r_h/μ  ────→   col 3: Re           —                  —
                         │                   │                  │
                         └──→ 拟合 ──→       _nu_*(Re, ...)      │
                                             输入: r_h-Re        │
                                             输出: D_h-Nu        │
                                             │                  │
                                             └──→ 被 solver 调用 │
                                                                 │
         Re_local = ρ·u·r_h/μ    (r_h 约定 ✓,和拟合一致)        │
         Nu = _nu_*(Re_local)    (D_h 约定输出 ✓)                │
         h_sf = Nu × k_f / D_h   (D_h 定义,和 Nu 输出一致 ✓)    │
         h_v = h_sf × A_0        (✓)                             │
```

**全链路每一步的约定都对齐**,**没有 2× 错配**。

## 三个 Nu 调用点的审计

| 文件 | 行号 | Re 计算 | Nu 调用 | 判定 |
|---|---:|---|---|---|
| `tpms_calc.py` | 312-328 | `r_h = D_h/2; Re = ρ·u·r_h/μ` | `_nu_diamond(Re, ...)` | ✅ |
| `fvm_solver.py` | 827-841 | `r_h = D_h/2; Re_local = ρ·u·r_h/μ` | `nu_from_Re(..., Re_local)` | ✅ |
| `sigmoid_field.py` | 290-305 | `r_h_arr = D_h_arr/2; Re_A = ρ·u·r_h/μ` | `_nu_vec(tpms, Re_A, ...)` | ✅ |

三处全部传 $r_h$-约定 Re 给 $r_h$-约定的 Nu 拟合,**一致**。

## 其他被审计的位置

| 文件 | 审计项 | 判定 |
|---|---|---|
| `load_data.py` | `_COL_RE = 3` 直接读训练 Re 列 | ✅(L=6/L=8 一致,L=4 污点但不影响) |
| `load_data.py` | `_L8_RE_MIN = 1600` L=8 过滤 | ✅(在 r_h 约定下) |
| `fit_df_per_geom.py` | WLS 用 (u, dP, ρ, μ) | ✅(不涉及 Re) |
| `train_surrogate.py` | MLP 用 (u, dP, ρ, μ)+ 几何输入 | ✅(不涉及 Re) |
| `simple_solver.py:_porous_src`(f_re) | `Re = ρ·u·r_h/μ`;`_f_re(Re, ...)` | ✅(_F_COEFFS 同 r_h 约定拟合) |
| `simple_solver.py:_porous_src_df`(df) | 直接用 (K, cF, μ, ρ, u) | ✅(不涉及 Re) |
| `validate_shanghai.py` | `u_A = m_air/(ρ·A_FLOW)` | ✅(单通道 interstitial,和训练 col 13 同约定) |

## 修复内容(纯注释/文档)

### 修复 1:`_nu_diamond` docstring

```python
# 原(错):
"""Diamond TPMS Nu correlation.  Re = ρ u D_h / μ,  D_h in mm."""
```

```python
# 新:
"""Diamond TPMS Nu correlation.

INPUT  convention: Re = ρ·u·r_h / μ    (hydraulic radius, r_h = D_h/2)
OUTPUT convention: Nu = h·D_h / k_f    (hydraulic diameter, standard)

D_h_mm is in mm. This is a mixed convention — Re uses r_h but Nu
uses D_h — because the fit was trained on the project's training
Excel where the Re column uses r_h convention and the Nu column
uses the standard D_h definition (empirically verified).
"""
```

### 修复 2:`_nu_gyroid` docstring

类似修复,同样的混合约定说明。

### 修复 3:`tpms_calc.py` 模块顶部增加"Reynolds Number Convention"全局声明

在模块 docstring 里加入一段显著的声明块,写明:
- 项目全局 Re 约定为 $r_h$(= $D_h/2$)
- 和"$D_h$ + 单股 m/2"等价的数学表达
- 训练 Excel Re 列用此约定
- f-Re 和 Nu 关联式都在此约定下拟合
- Nu 输出用标准 $D_h$ 定义
- Nu 关联式的"混合约定"含义

### 修复 4:`tpms_calc.py` 里 `_F_COEFFS` 段的旧注释

原注释只写 `Re = rho_ref * u * r_h / mu` 没有和 $D_h$ 约定做对照。
新注释加入"等价表达"的说明,避免误导。

## 数值验证

修复后 smoke test:
```
_nu_diamond(400, 0.855, 3.585) = 12.1442
_nu_gyroid(400, 0.884, 8.0)    = 14.2942
```

和修复前完全相同(因为只改了注释,没改公式)。

全量验证:重跑 `CLOSURE=f_re python validate_shanghai.py`,16 个
case 的 dP_A_sim 和 Q_sim **字字不变**:

| Case | dP_A 修前 → 修后 | Q 修前 → 修后 |
|---|---|---|
| 1 | 1721 → 1721 | 245 → 245 |
| 8 | 89370 → 89370 | 2610 → 2610 |
| 16 | 180732 → 180732 | 1941 → 1941 |

**证实 Nu docstring 修正是纯文档改动,行为不变**。

## 这次审计**没有**解释的遗留问题

### C-1 Q 误差 21.8%(高 Re 段)仍在

来源**不在** Re 约定。下一步嫌疑:

1. **`solve_full.py` 里的"3× 速度约定"bug**。`validate_shanghai.py:108-118`
   已有开发者留下的警告:"SIMPLESolver returns an internal velocity
   convention that differs from u_A by a factor of ~3 (likely an eps_f /
   porosity double-count)"。3 ≈ $1/\varepsilon_f$,很可能是
   SIMPLE(interstitial)→ solve_full(误用为 Darcy)的约定不一致。
   **影响 Q 不影响 dP**(和 C-1 的现象吻合)
2. **Thermal dispersion 缺失**(Popov 2025 论证)。$K_{ff}^\text{eff}$ 没
   有 Péclet 修正,高 Re 段被低估,对应 C-1 高 Re 段误差增长
3. LTE / LTNE 建模选择或边界条件问题

### Shanghai df 欠 70%(Case 16)仍在

来源是 ConstDF-v1 MLP 在 t=0.6 外推失效,特别是 $c_F$ 被冻结在
t=0.5 水平。见 [`2026-04-15-DF-residual-structure-diagnostic.md`]。
这和 Re 约定无关,通过补 (L=7, t=0.6) CFD 数据重训解决。

## 下一步

按用户决策的顺序:

1. ~~重跑 f_re baseline,确认 Nu docstring 修正零影响~~ ✅ 已完成
2. **本报告 + docstring 修复一起 commit 到 git**(下一步)
3. **转去查 `solve_full.py` 的"3× 速度约定"问题**,这是 C-1 21.8%
   Q 误差的最可能单一来源

## 相关文件

- `thermoNas/tpms_calc.py`(修改:_nu_diamond / _nu_gyroid docstring,
  模块顶部 Re 约定声明,f-Re 注释补充)
- `reports/shanghai-validation/2026-04-15-Re-Nu-convention-audit.md`(本文件)
- `reports/constdf-v1/2026-04-15-DF-residual-structure-diagnostic.md`(独立的 U 形残差分析)
