# evaluator-envelope-authority

## Why

架构审计 2026-07 §2（`docs/ARCHITECTURE-AUDIT-2026-07.md`）核实的评估器缺口：

- `core/evaluators.py`（3D BO 评估器）**手抄** 1D 可压缩 D-F 种子代数（本地 `R_AIR=287.05` +
  三处 `P_in² − 2RT·C·L` 内联），不 import `solvers/envelope` 权威——C8 时代的教训正是"复制的
  代数会漂移"；
- 两个 BO 评估器（2D `optimization/evaluator.py`、3D `core/evaluators.py`）都**缺 post-solve
  `gate_solution`**（Mach / 正压门）——管线两侧都有（run_stack_3d:2151,2159）；
- 两评估器都**不传 `rho_inlet_ref`**（stages_2d:546,561 传，防外迭代 ratchet）；
- 警告注册表（extrap/choke 去重集合）**评估器路径不重置**——上一场 BO 战役闩死的警告让本场沉默。

## What Changes

- **切片 A（本变更首个提交，行为逐位等价）**：
  - `core/evaluators.py` 三处种子改调 `envelope.predict_outlet_p_sq`（同式同序同常数，位同）；
    `R_AIR` 保留导出但别名到 `R_AIR_DEFAULT`；
  - `optimizer_qnehvi.run_qnehvi` 战役入口重置两个警告注册表（`_reset_warn_registries`，
    **每战役**而非每评估——500 评估的战役仍去重，粒度对齐 `ComputePipeline.run`）。
- **切片 B（后续迭代）**：两评估器 post-solve 接 `assess_solution_validity`/`gate_solution`
  语义——失败 → `invalid=True` + 罚值（沿用现有 choke 罚值通道），**不 raise**（BO 战役不许中断）。
- **切片 C（后续迭代）**：补传 `rho_inlet_ref`（口径对齐 stages_2d:475 的入口密度）；
  预期 `test_evaluator_frozen_values`（rel=1e-12）可能移动 → 走 upgrade/PROTOCOL.md §5
  有据重基准流程。

## Capabilities

### Modified Capabilities

- 评估器的可压缩种子/门禁与管线共享单一权威；BO 战役警告语义可预期。

## Impact

- **Code**：`core/evaluators.py`（种子三处 + R_AIR 别名）、`optimization/optimizer_qnehvi.py`
  （战役入口重置）；切片 B/C 各自小面积追加。
- **Gates**：全套 suite（含 `test_evaluator_frozen_values` rel=1e-12 数字锁）+ golden 位同；
  新增 `tests/test_evaluator_envelope_authority.py` 四断言锁 wiring。
- **契约**：**Pareto 选点必须经 Pipeline（`verify_pareto_3d` / 生产管线）复核后方可引用数字**——
  评估器是廉价筛选器（legacy 收敛模式、B 侧冷解是有意的吞吐设计），不是数字权威。
- **Out of scope**：评估器全路由进 Pipeline（毁 BO 吞吐预算，审计 §2 verdict 否决）；
  2D 评估器已有的预解 choke raise→罚值通道（aa3f477，不动）。
