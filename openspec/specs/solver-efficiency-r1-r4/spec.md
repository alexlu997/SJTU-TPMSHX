# solver-efficiency-r1-r4 Specification

## Purpose
2D SIMPLE 求解器的低速/平台早退判据（R1，3D 判据回流）、密度更新零分配（R2）、3D gate 阶段剖析证据（R3）、3D 动量 SOU opt-in（R4）。结果与决策记录见 `reports/solver-efficiency-r1-r4/CONCLUSIONS.md`（openspec archive `2026-07-02-solver-efficiency-r1-r4`）。

## Requirements

### Requirement: R1 — 2D low-Re/plateau early-exit, velocity-stability gated
2D `SIMPLESolver.solve()` SHALL 增加与 3D `simple_solver_3d.py` 同构的 A+B 早退判据：(B) `max|Δu,Δv|/scale < lowre_vel_tol` 速度增量退出；(A) 残差窗口内改善 < `lowre_stall_ratio` 且速度近静止（10×vel_tol）的平台失速退出。两者 SHALL 仅在 `it >= 20` 且速度稳定时触发（场在动绝不早退）。属性与默认值 SHALL 与 3D 一致（`lowre_early_exit=True`, `lowre_vel_tol=1e-4`, `lowre_stall_window=30`, `lowre_stall_ratio=1e-3`）。早退路径 SHALL 与严格收敛路径同样执行 `_enforce_mass_conservation()` 并返回 `(True, it)`。

#### Scenario: Plateaued cross-flow solve exits early
- **WHEN** golden air-air 管线 B 侧 solve（现状燃尽 10000 iter，残差平台 1.3e-3）在 R1 后运行
- **THEN** 该 solve 在场静止后早退（迭代数 ≪ 10000），管线总墙钟较 47.6 s 显著下降（≥5×）

#### Scenario: Moving field never exits early
- **WHEN** 场仍在演化（`max|Δv|/scale ≥ lowre_vel_tol`）
- **THEN** 两个早退判据均不触发，行为与现状逐迭代一致

#### Scenario: lowre_early_exit=False restores legacy behavior
- **WHEN** 求解器属性 `lowre_early_exit=False`
- **THEN** solve() 行为与 R1 之前 bit-identical

### Requirement: R1 — intentional golden re-baseline with guard
R1 落地 SHALL 重捕获 golden 2D 基线，且 SHALL 附带：新旧 headline 标量（Q, dP_A, dP_B, T_out）相对差记录（预期 <0.5%）、`validate_shanghai_aligned.py` RMSRE 与 README 基准（~8.4%）偏差 ≤0.5pp、全量 pytest 通过。

#### Scenario: Shanghai 2D baseline reproduced after re-baseline
- **WHEN** R1 合入后运行 `validate_shanghai_aligned.py`
- **THEN** dP RMSRE 与 README 记录的 2D 基准一致（±0.5pp）

### Requirement: R2 — density update without per-iteration allocations
`_update_density()` SHALL 用持久缓冲消除 `P_abs`/`rho_new` 的每迭代分配，且 SHALL 保持数值 bit-identical（在 R1 之前单独验证 golden `--check` PASS）。

#### Scenario: Bit-identical before re-baseline
- **WHEN** 仅 R2 应用时运行 golden 2D `--check`（对 pre-change 基线）
- **THEN** PASS (bit-identical)

### Requirement: R3 — 3D stage-share profile as decision record
本 change SHALL 交付 gate 配置（`validate_shanghai_3d_real`，默认 20×10×3 kernel runner，≥2 case）的 cProfile 阶段分解（3D SIMPLE 动量扫掠 / PP 解 / LTNE 能量 / 其他），写入 `reports/solver-efficiency-r1-r4/CONCLUSIONS.md`，并 SHALL 给出行动决策（单阶段 >40% → 列为候选立项；否则记录"无行动"）。R3 SHALL NOT 修改 3D 求解器代码。

#### Scenario: Profile report exists with decision
- **WHEN** R3 完成
- **THEN** 报告含阶段 cumtime 占比表 + 明确的行动/无行动结论

### Requirement: R4 — opt-in 3D momentum SOU with grid-convergence evidence
3D 动量内核 SHALL 增加 minmod SOU 延迟修正（2D N2 telescoping 面通量口径），由 `use_sou_momentum`（默认 False）控制；默认路径 SHALL **ULP 级等价**：flag off 的场与 pre-R4 代码逐点相对差 ≤1e-12（实测 1e-16~1e-14，源于 fastmath 内核加分支后的重编译指令重排——严格 bit-identity 需完整复制 3 份 cell body，违背精简约束，故按 repo 惯例做有意、有据的 golden 3D 重基线并记录数值证据）。限幅逻辑 SHALL 集中在单一共享 helper（不得按 u/v/w×x/y/z 复制 9 份限幅代码）。本 change SHALL 交付 ≥2 档网格的 SOU on/off dP 对比证据入报告；"SOU 扶正为默认"明确留待后续 change。

#### Scenario: Default path ULP-equivalent, re-baselined with evidence
- **WHEN** `use_sou_momentum` 未设置时运行 3D stack，对比 pre-R4 代码的同配置输出
- **THEN** 全部场逐点相对差 ≤1e-12（证据入报告），golden 3D 以 flag-off 输出重基线（PYTHONHASHSEED 固定）

#### Scenario: SOU changes coarse-grid solution measurably or not — recorded either way
- **WHEN** 基准在 ≥2 档网格上运行 SOU on/off
- **THEN** 报告记录各档 dP 及差异，并给出是否值得扶正的结论

### Requirement: Full test-suite gate
实施完成前 SHALL 通过全量 `pytest sjtu_tpmshx/tests/ -q`，并新增：R1 早退行为测试（合成平台工况早退、`lowre_early_exit=False` 回退）、R4 flag 默认 off 的零变化测试与 SOU 修正量对拍测试。

#### Scenario: Suite green with new coverage
- **WHEN** 运行全量 pytest
- **THEN** 0 failed，新增测试全过
