# Design: simpler-coupling-2d

## Context

**现状（2D 生产求解器 `solvers/simple_solver.py`）**：

- `SIMPLESolver.solve()`（`simple_solver.py:1298`）每外迭代执行：u/v 动量 GS 扫掠（Numba njit，`n_inner=2`，系数在内核内联计算，含 DF 源、Brinkman 壁惩罚、SOU minmod 延迟修正）→ p' 稀疏**直接**解（`_solve_pp_sparse_fast`，scipy spsolve，五点 stencil，稀疏模式缓存）→ `_correct_jit`（P += α_p·Pp，速度用 d·∇Pp 修正）→ `_update_density()`（可压缩 ρ(P,T) + 质量流量入口重施加）。
- d 系数在动量扫掠内填充：`d_u = dy/aP0`、`d_v = dx/aP0`（aP0 = 自然 aP，含 Sp，不含松弛因子）— `simple_solver.py:300,388`。
- SIMPLE 的收敛瓶颈是外迭代数：p' 每次已精确解出（"exact PP gives mass convergence in 1 iter, but P needs more"），P 场靠 α_p=0.3 的欠松弛修正慢慢建立。
- **pysimpler 参考**（`D:\Postgraduate\pysimpler\pysimpler.py`，Tao SIMPLER 的 numpy 蒸馏，已验证）：SIMPLER 六步 — ①无压力动量系数 ②伪速度 û=(Σa_nb·u_nb+b)/aP ③以 û 装配压力方程直接解 P（不松弛）④加压力源解 u* ⑤p' ⑥p' 只修速度。方腔 Re=100 实测外迭代 405→121。
- P 方程与 p' 方程系数**同构**（同一 ρ·A·d 五点 stencil，仅 RHS 不同：div(ρ·û) vs div(ρ·u*)）。

**约束**：

- Golden 2D（`runs/_out/_golden_2d.py`，Pipeline2D 场哈希）必须 bit-identical → 默认路径一行不改。
- 可压缩硬约束：ρ(P,T) 更新、质量流量入口（`_apply_massflux_inlet`，由 `_update_density` 尾部调用）必须原样保留在 SIMPLER 外迭代中。
- 现有动量扫掠内核是 GS 就地更新、系数即算即用（不存数组）→ SIMPLER 的"系数缓存复用"（Tao 的 COFU）无法直接照搬。

## Goals / Non-Goals

**Goals:**

- `solve(coupling='simpler')` opt-in 模式；默认 `'simple'` 路径 bit-identical。
- 伪速度内核与现有动量系数**逐项一致**（DF、壁惩罚、SOU、可变 ρ/μ），仅去掉压力梯度源与欠松弛。
- 基准量化：外迭代数、墙钟、场一致性（SIMPLE vs SIMPLER，同一 Shanghai 风格配置）。
- 明确决策门：墙钟 ≥1.3× 且场一致 → 立后续 change 推广 3D；否则记录负结果。

**Non-Goals:**

- 不改 3D 求解器、pipelines 默认行为、DF/LTNE/Nu 任何闭包。
- 不引入 pysimpler 代码依赖、不做 C++/pybind11 端口（proposal 已记录决策）。
- 不做非等温耦合下的 SIMPLER 调参（基准为等温流动求解，T 场冻结路径不动）。
- 不追求 Tao 式"系数缓存跨步骤复用"的极致——正确性优先，测得数据后再优化。

## Decisions

### D1 — 移植算法而非代码（vs 接入 pysimpler / C++ 化）

见 proposal。pysimpler 是常密度不可压、纯 Python；生产内核已是 Numba 编译 + 稀疏直接解。C++ 化对这些内核预期收益 1.2-2×，成本（工具链/双语言/全基线重验证）不成比例。真正未利用的是 SIMPLER 的**外迭代缩减**（Tao 实测 3.3×）。

### D2 — SIMPLER 六步映射到现有内核结构

```
per outer iter (coupling='simpler'):
  ①② _pseudo_uv_jit_df:  û,v̂ ← (Σa_nb·u_nb + SOU)/aP0   [新内核，无 p_src、无松弛，
                          单遍 Jacobi 式：读 u/v 写 û/v̂；同时填 d_u,d_v；
                          边界面 û,v̂ = u,v 的 BC 值（先整场拷贝再填内部）]
  ③  P 方程:  _assemble_pp_data_jit(…, û, v̂, d_u, d_v, …) → spsolve → P 直接替换
              [复用 PP stencil；出口 Dirichlet P=0 与现行规约一致（出口不修正 ≡ 出口守 0）]
  ④  _sweep_u_jit_df / _sweep_v_jit_df:  现有内核原样（含 α_u 欠松弛，用新 P）
  ⑤  _solve_pp_sparse_fast:  现有 p' 解（用 ④ 后的 d_u,d_v — 见 D4）
  ⑥  _correct_jit(…, alpha_p=0.0, …):  α_p=0 自然跳过 P 修正，只修速度 [零新内核]
  尾部不变: _update_density() → ρ(P,T) + massflux inlet；_mass_res_jit 收敛判据
```

**替代方案**：重构现有扫掠内核加 `pressure_on` 开关复用系数代码 — 拒绝：触碰默认路径编译单元，golden bit-identity 风险（Numba 重编译顺序/常量折叠差异虽理论无影响，但"默认路径零改动"是最强保证）。伪速度内核**有意**复制系数代码块，头注标明"必须与 `_sweep_u_jit_df` 系数逐项同步"。

### D3 — P 直接替换，不加松弛（Tao 式），保留回退钩子

SIMPLER 的收益正来自 P 不欠松弛。但本求解器有 pysimpler 没有的反馈环：ρ(P,T) 更新（α_rho=0.3 已有欠松弛）+ 质量流量入口。若 P 直接替换与 ρ 反馈耦合振荡，回退方案：`P ← (1-β)·P_old + β·P_new`，β 作为 `simpler_relax_p`（默认 1.0）暴露。**先按 β=1.0 实施**，基准中若残差振荡/发散再启用 β<1，并把实测行为记入报告。

### D4 — 每外迭代两次 spsolve（正确性优先），LU 复用作为测后优化

⑤ 的 p' 方程用 ④ 之后的 d_u/d_v（与现行 SIMPLE 语义一致）；③ 的 P 方程用 ①② 伪速度阶段的 d_u/d_v。两组 d 数值略有漂移 → 两个矩阵不严格相同 → 先各自 spsolve（代码最简、语义最清晰）。

**优化路径（profile 后决定）**：Tao 语义是整个外迭代冻结一套系数 → ⑤ 复用 ①② 的 d（矩阵与 ③ 相同）→ `splu` 一次分解、两次回代，第二次椭圆解近乎免费。作为 task 阶段的可选项：仅当 profiling 显示 PP 解占墙钟 >40% 时实施，且需在基准中单独对比两种 d 语义的收敛行为。

### D5 — 基准配置与判定

- 直接实例化 `SIMPLESolver`（绕过 Pipeline2D，隔离速度求解本身）：air `ideal_gas` + massflux inlet + Gyroid DF（Shanghai 风格参数，借 golden cfg 的量级：L_cell=7mm、t=0.6mm、v~10-20 m/s、T~322-422K）、全宽进出口、`wall_refine=False`、中等网格（~40×80）+ 一档细网格（~80×160）验证趋势。
- 记录：外迭代数至 tol=1e-6、墙钟（JIT 预热后计时）、SIMPLE vs SIMPLER 收敛场一致性。
- 一致性判据：ΔP（进出口压降）相对差 ≤1%；u/v/P 场相对 L2 差 ≤1e-2（两种耦合是不同迭代路径，到同一 tol 的场本就有迭代残余差；判据按"工程一致"定）。
- 决策门：墙钟加速 ≥1.3×（细网格档）→ 后续 change 评估 3D/AMG 推广；<1.3× 或不一致 → 负结果记录进 change 报告，`coupling='simpler'` 保留为 experimental 并在 docstring 标注。

### D6 — 入参校验

`solve(coupling=...)` 仅接受 `'simple' | 'simpler'`，其余 `ValueError`。参数经 `solve()` 传入而非 `__init__`（与 `alpha_u/alpha_p/n_inner` 同层级，便于同一 solver 实例两模式对比基准）。

## Risks / Trade-offs

- **[可压缩 P 直接替换振荡]** ρ(P) 正反馈可能让无松弛 P 替换失稳 → D3 的 β 回退钩子；基准记录实际行为。这是本实验的核心未知数。
- **[伪速度内核系数漂移]** 复制的系数代码块与 `_sweep_u_jit_df` 将来不同步 → 头注互指 + 新增 pytest：构造小网格，断言伪速度内核在"补回压力源并做 GS 迭代"退化形式下与现有扫掠一步结果一致（或至少 d_u/d_v 两内核逐点一致）。
- **[壁惩罚/部分进出口配置未覆盖]** 基准只测全宽进出口 → SIMPLER 模式 docstring 标注"partial-BC 配置未基准化"；不影响默认路径。
- **[SOU 延迟修正在 û 中的处理]** û 含 SOU 项（与动量 RHS 一致）；SOU 依赖当前 u 场 — Jacobi 单遍读旧场，自洽。若引发 P 方程 RHS 噪声，退化选项：û 去掉 SOU（记录偏差）。
- **[负结果]** SIMPLER 在此物理组合下可能无净收益（GS 扫掠 + 精确 p' 直接解的 SIMPLE 已比教科书 SIMPLE 强得多）→ 这本身是有效结论，写入报告，flag 保留 experimental。

## Migration Plan

纯增量 opt-in：默认行为不变，无迁移。回滚 = 删除新内核 + solve 分支（默认路径无 diff）。

## Open Questions

- ③ 的 P 方程出口 Dirichlet 用 0（现行 gauge）——若基准显示入口锚定配置下 P 场绝对量漂移，改为出口行直接钉现 P 值（保 gauge 连续性）。基准中验证。
- 3D 推广（AMG 下两次椭圆解的成本比 2D 直接解更敏感）——另立 change，以本实验数据决策。
