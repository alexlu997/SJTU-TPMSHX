# arch-b-c-e Specification

## Purpose
架构扫描剩余批次的结构约束：kernel import DAG（tpms_props 叶子）、solve 外循环早退判据单源（`_solve_common.LowReExit`）、main.py 尺寸卫生（mixins 模式）。来自 openspec archive `2026-07-02-arch-b-c-e`。

## Requirements

### Requirement: B — kernel import graph is a DAG
`solvers/tpms_props.py` SHALL 为叶子模块（只 import stdlib/numpy/`tpms_geometry`），承载 geometry 与流体物性关联式；`tpms_calc` SHALL 全量 re-export（既有消费者 import 路径不变）。`df_surrogate` SHALL 只在模块层 import `solvers.tpms_props`（sCO2 的 `fluid_props` runtime-only deferral 除外，须注明）；solvers 侧对 `df_surrogate.predict` 的 import SHALL 提升为模块顶层。

#### Scenario: df_surrogate imports without the heavy kernel
- **WHEN** 干净解释器 `import df_surrogate.predict`
- **THEN** `sys.modules` 不含 `solvers.tpms_calc` 与 `solvers.simple_solver`（测试锁定）

#### Scenario: Consumers unchanged
- **WHEN** 既有代码 `from solvers.tpms_calc import geometry, air_viscosity, ...`
- **THEN** 行为与拆分前一致（re-export），golden 2D/3D bit-identical

### Requirement: C — low-Re early-exit criteria single-sourced
2D 与 3D solve() 的早退判据（速度稳定 + 平台失速）SHALL 由 `solvers/_solve_common.py` 单一实现提供；浮点运算次序 SHALL 与现行两份实现逐运算一致（golden 2D/3D bit-identical 硬门，不允许重基线）；`lowre_*` 参数语义与默认值 SHALL 不变；判据命中后的收尾（2D `_enforce_mass_conservation`）SHALL 留在各自 solve()。

#### Scenario: Shared criteria bit-identical
- **WHEN** 抽取后运行 golden 2D 与 3D `--check`（PYTHONHASHSEED=0）
- **THEN** 双 PASS (bit-identical)

#### Scenario: Single definition
- **WHEN** grep 平台失速窗口逻辑（`_stall_window`/`_res_at_window_start` 判据体）
- **THEN** 仅 `_solve_common.py` 一处实现（solve() 只余调用）

### Requirement: E — main.py within maintainable size, behavior preserved
main.py SHALL 依既有 mixins 模式抽出内聚块至 ≤ ~2000 行；抽出块 SHALL 保持方法名/信号连接/属性协议不变（混入解析等价）。panel_vis_3d 仅在存在无 Qt 状态的辅助函数群时抽 helpers，否则 SHALL 记录放弃理由。

#### Scenario: UI tests green after extraction
- **WHEN** 运行离屏 UI pytest（test_main_smoke、test_stylesheet_braces、test_pipeline_ui_hooks、test_main_resultcache_bridges）
- **THEN** 全过，且全量 pytest 0 failed

### Requirement: Gates
每批（B/C/E）SHALL 独立 commit 并在合入前通过：golden 2D/3D bit-identical、全量 pytest 0 failed；推送后 CI SHALL 绿。

#### Scenario: CI green on final push
- **WHEN** 三批推送完成
- **THEN** 最新 master CI run success
