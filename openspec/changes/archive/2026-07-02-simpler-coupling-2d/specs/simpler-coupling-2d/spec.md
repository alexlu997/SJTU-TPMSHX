# Spec: simpler-coupling-2d

## ADDED Requirements

### Requirement: Opt-in SIMPLER coupling mode
`SIMPLESolver.solve()` SHALL accept a `coupling` keyword with values `'simple'`（默认）and `'simpler'`。`coupling='simple'` SHALL 保持现有代码路径与行为完全不变（bit-identical）。其他取值 SHALL 抛出 `ValueError`。

#### Scenario: Default path unchanged
- **WHEN** `solve()` 以默认参数（或显式 `coupling='simple'`）运行 golden 2D 门（`runs/_out/_golden_2d.py --check`）
- **THEN** 所有标量与场哈希 bit-identical（PASS）

#### Scenario: Invalid coupling value
- **WHEN** 调用 `solve(coupling='piso')`
- **THEN** 抛出 `ValueError`，且不进入迭代

### Requirement: Pseudo-velocity kernel coefficient parity
SIMPLER 模式的伪速度内核 SHALL 使用与 `_sweep_u_jit_df` / `_sweep_v_jit_df` **逐项一致**的动量系数（对流/扩散、D-F 源、Brinkman 壁惩罚、SOU 延迟修正、可变 ρ/μ 面插值），仅省略压力梯度源与欠松弛；SHALL 单遍 Jacobi 式求值（读 u/v，写 û/v̂）；SHALL 同时填充与现有内核同公式的 `d_u`/`d_v`（`d = A/aP0`）；边界面 û/v̂ SHALL 携带 u/v 的边界条件值。

#### Scenario: d-coefficient parity with sweep kernels
- **WHEN** 在**零流动**冻结状态（u=v=0、v_inlet=0，GS 就地更新退化为 Jacobi，两内核所见场逐点相同）上分别运行伪速度内核与现有扫掠内核（n_sweeps=1, α_u=1）
- **THEN** 两者产出的 `d_u`、`d_v` 逐点一致（rtol ≤ 1e-12）；对流/SOU/变 ρμ 项的 parity 由非零流动冻结状态下的单胞手工装配 spot check（rel ≤ 1e-12）补充覆盖（GS 就地更新使非零场下整场 d 比较不适用）

#### Scenario: Pseudo-velocity boundary faces carry BCs
- **WHEN** 伪速度内核运行于含质量流量入口与出口外推 BC 的状态
- **THEN** û 的 x=0/x=W 面为 0（无滑移），v̂ 的入口面等于 `v_inlet_field·inlet_frac`，出口面遵循现行 ρ 加权外推值

### Requirement: SIMPLER pressure equation reuses the PP machinery
SIMPLER 模式 SHALL 以 û/v̂ 为面速度、复用 `_assemble_pp_data_jit` 的五点 stencil（系数 ρ·A·d 不变，仅 RHS 换为伪速度质量不平衡）装配压力方程，稀疏直接解后 SHALL 直接替换 P 场（默认不加松弛；`simpler_relax_p` ∈ (0,1] 作为回退钩子，默认 1.0）。出口 Dirichlet 基准 SHALL 与现行 gauge 规约一致（出口 P=0）。

#### Scenario: Pressure solved directly, not corrected
- **WHEN** SIMPLER 模式完成一次外迭代
- **THEN** P 场来自压力方程的直接解（β=1.0 时逐点等于解出值），p' 步不再修改 P

### Requirement: Velocity-only p-prime correction
SIMPLER 模式的 p' 步 SHALL 复用现有 `_solve_pp_sparse_fast` + `_correct_jit`，以 `alpha_p=0.0` 调用使 P 不被修正，速度修正与出入口 BC 重施加逻辑保持与 SIMPLE 一致。

#### Scenario: p-prime corrects velocities only
- **WHEN** SIMPLER 模式 p' 步执行前后对比 P 场
- **THEN** P 逐点不变，而 u/v 按 `d·∇p'` 被修正，质量残差较修正前下降

### Requirement: Compressible loop invariants preserved
SIMPLER 模式的外迭代 SHALL 原样保留：`_update_density()`（ρ(P,T) 理想气体更新 + `_apply_massflux_inlet` 质量流量入口重施加 + 压力钳位）、`_mass_res_jit` 收敛判据（含 ε·ρ 有效密度）、`_enforce_mass_conservation` 收尾。SHALL NOT 改动任何闭包（DF、Nu、LTNE）。

#### Scenario: Mass-flux inlet pins throughput in SIMPLER mode
- **WHEN** SIMPLER 模式在 ideal_gas + massflux_inlet 配置下收敛
- **THEN** 入口质量流量等于目标 G = v_inlet·ρ_inlet_ref（与 SIMPLE 模式同一判据、同一容差）

### Requirement: Benchmark and decision gate
本 change SHALL 交付基准脚本：同一 Shanghai 风格 2D 配置（air ideal_gas、Gyroid DF、全宽进出口、≥2 档网格），SIMPLE 与 SIMPLER 各自运行至同一 tol，记录外迭代数、JIT 预热后墙钟、场一致性（进出口 ΔP 相对差 ≤1%；v/P 相对 L2 差 ≤1e-2；u 为近零的横向次级速度，按主流尺度 ‖v‖ 归一 ≤1e-2）。结果 SHALL 写入 change 报告：加速 ≥1.3×（细网格档）且场一致 → 标记"3D 推广候选"；否则记录负结果并把 `coupling='simpler'` 在 docstring 标注 experimental。

#### Scenario: Benchmark produces the decision record
- **WHEN** 基准脚本运行完成
- **THEN** 输出两模式的 (外迭代数, 墙钟 s, ΔP_A, 场 L2 差) 表格，且一致性判据的 PASS/FAIL 逐项打印

#### Scenario: Fields agree between couplings
- **WHEN** 两模式在同一配置收敛到 tol=1e-6
- **THEN** ΔP 相对差 ≤1%，u/v/P 相对 L2 差 ≤1e-2

### Requirement: Full test-suite gate
实施完成前 SHALL 通过 `pytest sjtu_tpmshx/tests/ -q` 全量（非仅 golden），SHALL 新增覆盖：coupling 参数校验、d 系数 parity、SIMPLER 小网格收敛冒烟（不可压极限 fluid_type 常密度下 SIMPLE/SIMPLER 同解）。

#### Scenario: Incompressible-limit agreement smoke test
- **WHEN** 常密度（非 ideal_gas）小网格配置下两模式各自收敛
- **THEN** 收敛场满足与基准同款一致性判据（该测试进 pytest，秒级）
