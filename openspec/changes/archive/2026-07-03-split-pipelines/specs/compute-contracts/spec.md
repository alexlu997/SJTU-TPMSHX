# compute-contracts Delta — split-pipelines

## ADDED Requirements

### Requirement: Pipelines module layout — cfg boundary vs engine
2D/3D 计算管线 SHALL 按职责分模块：`stages_2d`/`stages_3d` 只保留 cfg 边界（parse/build/run_cfg/finalize）并 SHALL 全量 re-export 迁出符号（外部 import 面零变更）；引擎与后处理住 `solve_2d`（2D 外循环 + Q/压力后处理）、`run_stack_3d`（3D 核心循环 `_run_3d_stack` + 守恒诊断 + 并行/剖析助手）、`flux_3d`（面通量加权 + 粗糙度施加）、`grid_3d`（轴映射/分区场/网格构建）。依赖方向 SHALL 保持 DAG：flux_3d/grid_3d ← run_stack_3d ← stages_3d；solve_2d ← stages_2d；引擎模块 SHALL NOT 反向 import stages_*。拆分 SHALL 为逐字搬移（浮点运算顺序不变）。

#### Scenario: External import surface unchanged
- **WHEN** 任一既有消费方执行 `from pipelines.stages_3d import _run_3d_stack`（或 tests 里的其余 ~15 个内部名）
- **THEN** import 成功且解析到迁移后的实现

#### Scenario: Golden bit-identical across the split
- **WHEN** 金档 2D/3D --check 在拆分后运行（PYTHONHASHSEED=0）
- **THEN** PASS (bit-identical)

#### Scenario: No cycles
- **WHEN** 运行 test_import_dag（或直接 import 各引擎模块）
- **THEN** 无循环 import 错误
