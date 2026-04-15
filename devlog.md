# ThermoNAS 开发日志

> 每天记录做了什么、遇到了什么问题、怎么解决的、改了哪些代码/方程。
> 按**倒序**（最新在上），方便快速查看最近进展。

## 如何记录每天

每一天一个 `## YYYY-MM-DD` 段落，下面用如下子段落：

```markdown
## 2026-MM-DD

### 🎯 本日目标
（如果是计划好的工作）

### ✅ 完成的事
（要点列表）

### 🐛 发现的问题 / 遇到的困难
（问题描述、怎么发现的、影响范围）

### 🔧 解决方案
（怎么解决的、为什么这么解决、是否治本）

### 🧪 验证/测试
（跑了什么测试、结果怎样）

### 📐 方程/算法改动
（如果改了物理模型或数学公式，详细写改动前后对比、量纲校核）

### 📁 代码改动文件清单
（`file.py:line_range` — 改了什么）

### 📚 产出文件
（新增的 md/csv/png 等）

### ⏭️ 待办 / 后续问题
（遗留未解决的 / 下次要做的）

### 💡 学到的 / 重要发现
（物理、算法、数值上的 insight）
```

并不是所有段落每天都要写，按当天实际情况挑着填。

---

## 2026-04-14

### 🎯 本日目标

启动 D-1 子项目（GUI bug 修复）。原本范围："修两个和 dark/light 主题切换有关的 bug + 不动其他"。最终走向："完全删掉 dark mode，GUI light-only"。

### ✅ 完成的事

1. **Bug 1 调试**：toggle 按钮失效。systematic-debugging 走完。
   - 现象：点 Light/Dark 按钮，UI 视觉上不切换
   - offscreen probe（headless Qt）能完整复现 state 切换 + pixel 切换 — 复现不出来 bug
   - 用户在真实 Windows 后端跑 + 把 stderr 重定向，才暴露 Qt 输出几百行 `Could not parse stylesheet` warning
   - 走查产生失败 stylesheet 的 widget 类型（QLabel / QComboBox / QFrame）→ 定位到 3 处 string-formatting 手误（见下）

2. **Bug 2 调试**：Pressure tab 下的 ΔP summary card 被冻结在初次渲染时刻的 theme
   - 静态走读 `theme.apply_theme` 直接定位：它只迭代 `ax.texts / spines / ticks / labels`，**没碰 `ax.patches`**
   - `plot_pressure` 画的 `FancyBboxPatch` 卡片背景 + `ax3.plot()` 分割 Line2D 因此永远是初次绘图时刻的颜色
   - 写了一个独立 regression test 直接画 synthetic pressure plot + toggle，断言 patch facecolor 跟着切 → 修复前 fail
   - 修复方案（短暂落地过）：在 plot_pressure 暴露 `self._dp_card_rect / self._dp_divider_line`，apply_theme 里就地改色，不重画 figure → 无 flicker

3. **Bug 1 + Bug 2 修复都验证通过后，用户决定整体放弃 dark mode**，理由是参数面板还有局部没切干净（截图对比能看出来），打磨成本 > 价值，light-only 已经够用

4. **删 dark mode 干净化**：
   - `theme.py`：删 `_THEMES['dark']`、删 `apply_theme()` (~140 行)、`_build_styles()` 去掉 `theme_name` 参数
   - `main.py`：删 `_toggle_theme()`、删 module-level `_current_theme`、import 不再带 `apply_theme`
   - `ui_builders.py`：删 header 上的 `_btn_theme` 按钮 + signal 连接、删所有 `_current_theme = m._current_theme` 读取、`_THEMES_local[_current_theme]` → `_THEMES_local['light']`
   - `matplotlib_canvas.py`：删 module-level `_current_theme`、删 `_dp_card_colors()`、删 `self._dp_card_rect / self._dp_divider_line` 暴露、`plot_pressure` ΔP card 颜色 inline 回 light 值
   - `layout_drawer.py / optimize_panel.py / polygon_calc.py / run_calculation.py`：批量替换 `_THEMES[_main(_mod)?._current_theme]` → `_THEMES['light']`
   - `test_main_smoke.py`：删 `test_main_menu_theme_toggle`，留 startup
   - 删 `test_theme_dp_card.py`（Bug 2 的回归测试，dark 没了所以这个 test 没意义）
   - 把 Bug 1 的回归测试改名 `test_theme_stylesheet_braces.py` → `test_stylesheet_braces.py`，作为通用 CSS sanity check 留下
   - 写 `.gitignore`（之前没有，导致 thermoNas 仓库索引里堆了一堆 `__pycache__/*.pyc`）

### 🐛 发现的问题 / 遇到的困难

1. **Bug 1 根因 — Python f-string 手误传染 3 处**

   3 处都是同一个错误：在**非 f-string** 的字符串拼接段写了 `}}`，作者大概以为是 f-string escape。但只有 f-string 里 `}}` 才会被解析成单个 `}`，普通字符串里 `}}` 就是字面的两个右大括号。结果产生的 CSS 多了一个 `}`，Qt 解析失败。

   位置：
   - `theme.py:_title()` 末行 → `_T_NEUTRAL / _T_HOT / _T_COLD`（section 标题 QLabel）
   - `theme.py:_build_styles()` COMBO 末行 → `_COMBO`（所有 QComboBox）
   - `ui_builders.py` 卡片 QFrame `setStyleSheet` 末行

   为什么启动也不报错？Qt 解析失败时退回默认样式 + warning 写到 qWarning（很多 Qt platform 下默认不到 stderr）。GUI 看起来没崩，开发者从来不知道这些 widget 应该长什么样，所以一直没被发现。Toggle 是把它拽出来的契机：toggle 用 detach + 新建 cw + 重建 UI 的策略，而这个策略对**没切换的元素**（即 stylesheet 仍然解析失败、保留 Qt 默认渲染的元素）和**正确切换的元素**（centralwidget bg 等）会产生明显视觉割裂。

2. **Bug 2 根因 — apply_theme 没迭代 patches**

   `theme.apply_theme` step 6 只对每个 canvas 做：`fig.patch.set_facecolor` + `ax.set_facecolor` + tick / spine / xaxis.label / yaxis.label / title / `ax.texts` / `fig.texts` 的颜色更新。它**不会**走 `ax.patches`。`plot_pressure` 的 ΔP card 用 `FancyBboxPatch` 加在 ax3 上，所以永远跟着初次渲染时刻的 theme 不动。

   也是**一个隐蔽的代码债**：apply_theme 是"所有可能 theme-依赖的元素都要在这里 in-place 更新"的策略，但它本身没有任何机制保证能覆盖所有元素。任何后续添加的 patch / line / collection 都会自动悄悄违反这个契约。这种 implicit-coverage 的策略本身就脆弱，dark mode 删掉之后这个问题也跟着消失。

3. **offscreen Qt 复现不出 Bug 1**

   花了不少时间在 `QT_QPA_PLATFORM=offscreen` 下尝试复现 toggle 失效——state 切换、像素抓取、模拟 click、widget tree walk，全都"看起来正常"。最后是用户在真实 Windows 后端 + 把 stderr 重定向到 log 才把 `Could not parse stylesheet` 几百行 warning 暴露出来。教训：**offscreen 后端会吞掉 qWarning**，不能把 offscreen 测试通过当作"功能正常"的证据，特别是涉及 Qt CSS / stylesheet / 窗口系统的部分。

### 🔧 解决方案

最终的决定 = **删 dark mode**。理由：
- Bug 1 + Bug 2 的修复都已经能跑通，但用户截图对比发现还有别的局部 dark 没切干净（参数面板若干角落）
- 继续把所有 dark 切干净的工作量 >> 直接删掉的工作量
- light-only 已经满足实际使用需求
- dark 模式本来也只是装饰性功能，不影响任何科研产出
- 删掉之后 theme.py 从 288 → ~110 行，main.py 少 20 行的 `_toggle_theme`，apply_theme (~140 行) 整个消失。代码债大幅减少。

### 🧪 验证/测试

- `test_main_smoke.py`（startup）：PASS
- `test_stylesheet_braces.py`（brace balance + Qt parse warnings on Main_Menu build）：PASS（0 parse failures）
- 删 `__pycache__` 重跑也 PASS（防止旧字节码污染）

### 📁 代码改动文件清单

详见两个 commit:
- `d1a2bed` — baseline（D-1 Bug 1+2 fix landed，含已经写好的 dp_card 回归测试）
- 第二个 commit — 删 dark mode

### 📚 产出文件

- `.gitignore`（新增）
- `test_stylesheet_braces.py`（从 `test_theme_stylesheet_braces.py` 改名 + 简化）

### ⏭️ 待办 / 后续问题

- D-1 spec 还没写。是否补一份 retroactive spec 记一下"原本要修两个 bug，最终选择删 dark mode"的决策？或者这条 devlog 已经够档案
- D-2 / D-3 GUI 打磨任务还没开。等用户具体提需求
- ThermoNAS 主仓库（`D:/Postgraduate/均质化/ThermoNAS/thermoNas/`）这次才第一次有 git commit。之前 staged 了 ~300 个文件（CSVdata + pyc）从来没 commit。需要决定那些 baseline / CSV / npz / log 文件要不要也入库

### 💡 学到的 / 重要发现

1. **Python f-string 的 `}}` 是双刃剑**。在 f-string 里 `}}` 是单个 `}` 的 escape；在普通字符串里它就是两个字面 `}`。把 f-string 段和普通段混拼接时极容易手误。**只要 stylesheet 是用 Python 字符串拼接 + Qt CSS 喂 setStyleSheet 这种模式，就需要一个 brace-balance 的回归测试守门**——因为 Qt 的 parse error 默认是 silent 的。
2. **Qt offscreen 后端会吞 qWarning**。不能把 offscreen 测试通过当作"功能正常"的证据，特别是涉及 Qt CSS / stylesheet / 窗口系统的部分。需要测试时显式安装 `qInstallMessageHandler` 拦截 warning 并断言 0 个。
3. **systematic-debugging 在两个 bug 上是反差教学**。Bug 2 是"静态走读直接定位"的代表（10 分钟）；Bug 1 是"必须拿到真实 stderr 才能定位"的代表（一开始 offscreen 复现失败后一度束手无策）。两者都遵守了"先复现再改"的纪律——Bug 1 没拿到 stderr 之前我没动一行代码，避免了瞎修。
4. **代码债的隐式契约比显式契约更危险**。`apply_theme` 的"覆盖所有 theme-依赖元素"是一个**只存在于作者脑子里**的契约。新加 patch / line / collection 时没人提醒你"哎，apply_theme 没更新这种东西哦"。这种 bug 一定会越积越多。删 dark mode 不仅是放弃功能，也是**消除一份脆弱契约**。

---

## 2026-04-09（今天）

一个大工作日：从**变密度 SIMPLE 扩展验证**开始，中间做了一堆**可视化改进**，然后**对接用户实验数据做了 dP 验证**，发现 2 个 bug 并做了**f-Re 关联式重拟合 (v2)**。

### ✅ 完成的事

1. **变密度 SIMPLE 扩展独立验证**（8 项全通过）
   - 标量 ρ 退化、线性热冷却、线性冷加热、部分 pipe BC、自持耦合环、ΔP vs f-Re、极端 2.5× ρ 比、非均匀 dx_arr
   - 中截面 $\int\rho v$ 守恒到机器精度，ΔP_SIMPLE vs f-Re 三种模式全在 2% 内

2. **速度云图可视化大改造**（多轮迭代）
   - 发现 A 侧 6% 变密度变化被原 `[0, fmax]` 色条压缩到看不见（只占 5.7% 色条宽度）
   - 几轮演化：百分位 + active-flow 屏蔽 → `set_under(背景色)` → 去白色换 `PowerNorm(γ=0.5)` → 最终定在 `PowerNorm(γ=0.4)` 让 1-3 m/s 的停滞区能清晰看见
   - 补上 hover 功能（`canvas_vel.axes` 之前没赋值，hover 一直静默失败）
   - card 外框加大（2px 边框 + 5px accent + 12px 圆角 + 16px 内边距）
   - 补 x 轴标签裁剪问题（card 变大后 subplots_adjust bottom 不够，从 0.04 改到 0.06-0.07）

3. **velocity-temperature 耦合收敛判据修复**
   - UI 报 "not converged after 5 iters (drho_A=0.0011, drho_B=0.0132)"
   - 把 `max(|Δρ|)` 换成**质量通量加权 L1 相对变化**
   - 5 iter 上限命中 → 3 iter 提前 break，警告消失

4. **几何默认值更新**
   - 从 100×50mm 改到用户实验的 **42×231mm**（Gyroid 7/0.6）
   - Fluid A 全宽 +x（L=231mm），Fluid B partial BC 对角 -y
   - 中途对 "侧边" vs "X方向" 的映射搞反过一次，后来根据用户澄清 + 数据 A/B 比反推确定 **侧边=A, X方向=B**

5. **两个 bug 修复 + 一次 f-Re 关联式重拟合**
   - **dP row-mean dilution bug**：partial BC 下 `P_fB[:, 0].mean()` 被 wall cell 稀释到真实值的 1/15（见下面 🐛 部分）
   - **f-Re 关联式重拟合 v2**：基于 14 个实验点拟合 (C, n0)，Fluid A 误差从 +220% → ±4%

### 🐛 发现的问题 / 遇到的困难

1. **ΔP 算法 bug (row-mean dilution)**
   - 症状：`dP_B sim = 9692 Pa` vs 实验 `140775 Pa`，低了 14×
   - 调查：写诊断脚本逐行检查 `simpB.P[:, 0]` 和 `simpB.P[:, -1]`，发现 row mean 包含大部分 wall cell 的"其他"压力，稀释了真实的 pipe inlet/outlet 压力差
   - 数字证据：row mean = 220672 Pa，pipe-weighted mean = 432753 Pa（差一倍）

2. **f-Re 关联式对 t=0.6mm 外推偏高 2 倍**
   - 症状：修完 dP bug 后，sim dP 比实验仍然高 100-240%
   - 诊断：用 1D 公式 $f = 2 r_h (dP/L) / (\rho v^2)$ 从实验反推 f_exp，和关联式的 f_sim 做逐行对比
   - 发现：**所有 14 个有效 Re 点的 f_sim/f_exp ≈ 2.1-2.7**
   - 根因：`tpms_calc.py:97` 注释说关联式拟合区间 t ∈ [0.3, 0.5]mm，用户实验 t=0.6mm **外推**

3. **CFD 和实验的 f-Re 斜率符号相反**（物理上值得记录）
   - CFD 拟合给 Gyroid at ε=0.737 的 **n_eff = -0.19**（f 随 Re 减小，Darcy-Forchheimer 理论）
   - 实验数据给 **n_eff ≈ +0.29**（f 随 Re 缓慢增加）
   - **这两个不可能同时拟合**，必须取舍
   - 可能原因：入口/出口动能损失污染 dP 测量、ρ_local vs ρ_ref 约定在高压下的差异、3D 打印几何与理想几何的差异

4. **14 个实验点参数空间退化**
   - 全部在同一 (L=7, t=0.6, ε=0.737) 下，无法约束 a, b, c（它们需要 (ε, t/L, X) 变化才能 fit）
   - 尝试 6 参数全拟合 → 系数撞边界、R² 崩溃
   - 最终只拟合 **2 个参数 (C, n0)**，其余 4 个保持原 CFD 值

### 🔧 解决方案

1. **dP row-mean bug 修复**（`main.py:2714-2752`）
   - 用 `simpA.inlet_frac / outlet_frac` 做管道加权的 P 平均
   - 直接在 SIMPLE gauge 压力上计算 `dP = P_pipe_inlet_gauge - P_pipe_outlet_gauge`
   - 对全宽 BC（A 侧）：所有 frac=1，pipe-weighted = row mean，结果不变 ✓
   - 对 partial BC（B 侧）：wall cell 权重为 0，精确得到管道进出口压差

2. **耦合判据修复**（`main.py:2621-2633`）
   - 从 `max(|Δρ|/ρ̄)` 换成 $\sum_i w_i |Δρ_i / ρ_i| / \sum_i w_i$，$w_i = |u_i|$
   - 物理解释：$\nabla \cdot (\rho u) = 0$ 只有 $u \neq 0$ 的 cell 才对解有贡献
   - 收敛比从 0.75（退化成线性）恢复到理论预测的 0.3（几何收敛）

3. **f-Re 关联式重拟合**（`tpms_calc.py:102`）
   - 只改 Gyroid 的 (C, n0)：`0.5658 → 0.006634`, `-0.0596 → +0.4237`
   - 保持 (n1, a, b, c) 不变，保证其他几何的形状因子不被破坏
   - 公式形式完全不变，**f 仍然严格无量纲**

### 🧪 验证/测试

- **dP row-mean 修复验证**：对 Row 16 手工对比 row-mean (9.7k) vs pipe-weighted (432k) vs 实验 (140k)
- **耦合判据修复验证**：默认 case 从 5 iter 降到 3 iter，无警告
- **16 工况端到端验证**（用 `perf_test.py`）：
  - Fluid A Row 3-16 |mean err| = **3.74%**（目标 <15% ✅）
  - Fluid A 最大单点误差 = 8.92%
  - Fluid B Row 3-16 |mean err| = 40.22%（仍高，2D partial BC 效应）

### 📐 方程/算法改动

#### (1) 耦合收敛判据（`main.py:2621-2633`）

**旧**：
$$
\text{drho}_A = \frac{\max_i |\rho^{new}_{A,i} - \rho^{old}_{A,i}|}{\bar\rho_A}
$$

**新**（mass-flux weighted L1）：
$$
\text{drho}_A = \frac{\sum_i w_i \left|\frac{\rho^{new}_{A,i} - \rho^{old}_{A,i}}{\rho^{old}_{A,i}}\right|}{\sum_i w_i}, \quad w_i = \sqrt{u_{A,i}^2 + v_{A,i}^2}
$$

#### (2) dP 计算（`main.py:2714-2752`）

**旧**：
$$
\Delta P_B = P_{in,B}^{user} - \text{mean}(P_{fB}[:, j=\text{outlet row}])
$$

**新**（pipe-weighted from SIMPLE gauge directly）：
$$
\Delta P_B = \frac{\sum_i w_{in,i} \cdot P_{g,B}[i, 0]}{\sum_i w_{in,i}} - \frac{\sum_i w_{out,i} \cdot P_{g,B}[i, -1]}{\sum_i w_{out,i}}
$$

其中 $w_{in,i} = \text{inlet\_frac}_i$，$w_{out,i} = \text{outlet\_frac}_i$（SIMPLE 内部 1D 掩码）。

#### (3) Gyroid f-Re 关联式（`tpms_calc.py:102`）

**公式形式不变**（量纲保持无量纲）：
$$
f = C \cdot Re^{n} \cdot \varepsilon^a \cdot (t/L)^b \cdot \left(\frac{X}{1000 S_a}\right)^c, \quad n = n_0 + n_1 \ln\varepsilon
$$

**系数更新**（只改 C 和 n0）：
| 系数 | 旧 (v1) | 新 (v2) |
|---|---|---|
| C | 0.5658 | **0.006634** |
| $n_0$ | -0.0596 | **+0.4237** |
| $n_1$ | 0.4304 | 不变 |
| a | -3.25 | 不变 |
| b | -0.02 | 不变 |
| c | -1.37 | 不变 |

**在 ε=0.737 下的等效 Re 指数**：v1 是 **-0.19**，v2 是 **+0.29**（反号！）。

**代价**：v2 在原 195 CFD 拟合点的 MAPE 从 8% 劣化到 45%。v1 和 v2 不能共存，要用哪个取决于对比对象是 CFD 还是实验。

### 📁 代码改动文件清单

- `thermoNas/main.py:337-338` — L, H 默认从 0.10/0.05 改到 0.231/0.042
- `thermoNas/main.py:476-479` — A pipe 中心/宽度改 0.021/0.042
- `thermoNas/main.py:488-491` — B pipe 中心/宽度改 0.203/0.042 和 0.028/0.042
- `thermoNas/main.py:354-359` — TPMS 默认从 Diamond 8/0.3 改到 Gyroid 7/0.6
- `thermoNas/main.py:2621-2633` — 耦合 drho 判据改为质量通量加权 L1
- `thermoNas/main.py:2714-2752` — dP 计算改为管道加权，修复 row-mean dilution bug
- `thermoNas/main.py:750-784` — canvas card 外框加大（2px/5px/12px/16px）
- `thermoNas/main.py:2954-3010` — 速度云图改 PowerNorm(γ=0.4)，加 hover 轴注册
- `thermoNas/main.py:2933, 3010` — temp/vel subplots_adjust bottom 加宽（防 x 标签裁剪）
- `thermoNas/main.py:3629` — pressure GridSpec bottom 加宽
- `thermoNas/tpms_calc.py:102` — Gyroid `_F_COEFFS` 元组：(C, n0) 更新到 v2

### 📚 产出文件

- `data/v2_fitting/fit_report_gyroid_v2.md` — 完整 Gyroid 重拟合报告（10 个章节，含量纲校核、16 工况端到端对比、局限性）
- `thermoNas/validation_results.csv` — 16 工况仿真 vs 实验完整数据（CSV）

### ⏭️ 待办 / 后续问题

1. **Fluid B 还差 40%**
   - 不是 f-Re 关联式问题（A 侧同一关联式已 ±4%）
   - 是 2D partial BC 流动的**额外损失**：inlet 收缩、对角转折、corner 加速
   - 需要独立的 CFD 标定 → 对 Gyroid 7/0.6 partial BC 几何做 full-scale CFD，和 ThermoNAS 2D SIMPLE 对比，校准等效损失系数

2. **Row 1-2（Re_ref < 600）外推区**
   - 关联式下限 Re=600，用户实验 row 1-2 在 Re=263-528
   - 两行误差依然大（row 1: +100%, row 2: -18%），但不在拟合目标里
   - 如果关心低 Re，需要拟合范围延伸

3. **Re 定义一致性问题**（潜在 follow-up）
   - 关联式里 Re 用 $\rho_\text{ref}$（atmospheric）定义
   - Solver drag 用 $\rho_\text{local}$ 算 force
   - 高压下 $\rho_\text{local}/\rho_\text{ref}$ 最高到 3，混用约定可能是系统偏差的一部分
   - 未修，由 refit 的系数被动吸收

4. **CFD vs 实验的斜率符号分歧**
   - 这是个**物理问题**，不是代码问题
   - 需要额外的实验或 CFD 数据来判断哪个是对的
   - 可能的污染源：入口动能损失、plenum-pipe 过渡、测量位置约定等

### 💡 学到的 / 重要发现

1. **Max-based 收敛判据在 partial BC 下是错的**：wall 扩散噪声会永久拖住判据。质量通量加权是正确的替代。

2. **Partial BC 下的 dP 计算必须用管道加权**：row mean 混合 wall cell，会把真实 pipe 压差稀释几十倍。是个隐蔽的 bug，默认 case（full-width A）永远碰不到，只有真的 partial BC 验证时才暴露。

3. **14 个实验点在同一几何下只能约束 2 个 DOF**：想拟合 6 个系数是妄想，优化器会 overfit 到无意义的局部极小。

4. **CFD 和真实实验可能在 f-Re 斜率符号上都不一致**：这不是数值精度问题，是物理测量/建模约定差异。选边站（这次选实验）是务实做法。

5. **色条 `PowerNorm(γ=0.4)` 对变密度流场特别合适**：Forchheimer 区 $u \propto \sqrt{\nabla P}$，sqrt-scale colorbar 相当于对压力梯度做线性映射，物理意义清晰。

6. **Card 外框加大后 subplot 可能被裁**：调 `subplots_adjust(bottom=...)` 是最快的修法，顺便也把 hspace 略放宽。

---

<!-- 新的日期写在这上面 -->
