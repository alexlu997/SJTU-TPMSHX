# compute-contracts Specification

## Purpose
计算契约（`ComputeConfig` 族 / `ComputeResult`）的归属层与 import 方向约束：契约在 `domain/`，窗口采集在 `ui/window_config.py`，controllers 只留编排/状态。来自 openspec archive `2026-07-02-contracts-layer`（架构扫描批次 A）。
## Requirements
### Requirement: Contracts live below every consumer
计算契约（`ComputeConfig` 族 dataclass、`bc_to_dict` 等纯函数、`ComputeResult`）SHALL 位于 `domain/`（`compute_config.py` / `compute_result.py`），SHALL NOT import Qt、ui、controllers、pipelines 中任何一个。`controllers/`、`pipelines/`、`validation/`、`optimization/`、`ui/` SHALL 从 `domain` import 契约。

#### Scenario: Pipelines importable without controllers
- **WHEN** 在干净解释器中 `import pipelines.stages_2d` 与 `import pipelines.stages_3d`
- **THEN** 成功，且 `sys.modules` 不含 `controllers.*`

#### Scenario: Contracts are Qt-free
- **WHEN** 静态扫描 `domain/` 的 import
- **THEN** 无 PySide/PyQt/ui/controllers/pipelines 引用

### Requirement: Controllers keep only window-harvest logic, with no ui imports
`controllers/compute_config.py` SHALL 仅保留读取窗口控件、组装契约对象的采集函数；其对 `ui.zone_table.build_zone_config` 的依赖 SHALL 改为调用方注入（callable 参数），controllers SHALL NOT import ui。`theme_manager` SHALL 移入 `ui/`。

#### Scenario: No upward imports from controllers
- **WHEN** grep `controllers/` 的 import（含函数内）
- **THEN** 无 `from ui`/`import ui` 命中

### Requirement: Cycle-breaking deferred imports eliminated
拆分落地后，`pipelines/stages_2d.py`、`pipelines/stages_3d.py`、`controllers/compute_pipeline.py` 中仅为打破 controllers↔pipelines 环而放进函数体的 import SHALL 提升为模块顶层；保留的函数内 import SHALL 各带一行懒加载理由注释（重库/可选依赖）。

#### Scenario: Remaining deferred imports are annotated
- **WHEN** 审查上述三个模块的函数内 import
- **THEN** 每处要么已提升，要么紧邻注释说明懒加载理由

### Requirement: Behavior-preservation gates
本 change SHALL 通过：golden 2D 与 3D `--check` bit-identical（PYTHONHASHSEED=0）、全量 pytest 0 failed、CI 绿、离屏 UI 冒烟（runs/smokes）通过。SHALL 为单 commit 原子落地。

#### Scenario: Golden gates hold
- **WHEN** 搬移与 import 更新完成后运行两个 golden `--check`
- **THEN** 均 PASS (bit-identical)

### Requirement: Shared stage scaffolding single source
2D/3D 管线的非内核胶水 SHALL 单一来源于 `pipelines/_stage_common.py`：域尺寸单位滑移防火墙（`validate_domain_dims`，>10 m 抛 ValueError）、双侧代理训练域守卫（`surrogate_extrap_reasons`：ImportError → 跳过返回 []，ValueError 上抛）、headline 标量守卫（`safe_float`：None/非数 → nan）、props 槽几何三元组（`geometry_props`）。stages_2d 与 stages_3d SHALL NOT 各自持有这些逻辑的副本。数值内核 SHALL 保持每维独立（统一已被否决）。

#### Scenario: Unit-slip rejected identically in 2D and 3D
- **WHEN** L_dom_m=182.0（把 mm 值误填进米字段）进入任一维度的 parse
- **THEN** 抛 ValueError，消息含 "exceeds" 与 "unit slip"

#### Scenario: Broken extrap guard fails loudly (2D hush removed)
- **WHEN** 代理域检查内部抛 AttributeError
- **THEN** 异常向上传播（不再被 2D 静默吞掉禁用外推警告）

#### Scenario: None headline does not crash 2D finalize
- **WHEN** raw['Q_total'] 为显式 None
- **THEN** ComputeResult.Q_W == nan（而非 TypeError）

#### Scenario: Golden gates bit-identical
- **WHEN** `_golden_2d.py --check` / `_golden_3d.py --check`（PYTHONHASHSEED=0）在本变更前后各跑一次
- **THEN** 四次全部 PASS (bit-identical)

### Requirement: No silent degradation in solver-side exception fallbacks
求解侧（solvers/pipelines/controllers/optimization 生产路径）的异常兜底 SHALL NOT 静默：物理量降级兜底（质量加权 → 朴素均值、ṁ→0、GP 未拟合继续）SHALL 发 warning；仅预期异常 SHALL 用窄类型捕获（如属性缺失 → AttributeError）；确属设计的 broad except（stdout tee、JIT warmup、LUT 缓存回退、UI 进度回调守卫）SHALL 带注释说明理由。UI 层 best-effort（会话恢复等）不在此约束内。

#### Scenario: Flux-weighting failure is loud
- **WHEN** `_face_flux_weights` 在 `_mass_weighted_T_out` 内抛异常
- **THEN** 返回朴素均值兜底且发 UserWarning（含失败原因与"T_out/Q degraded"）

#### Scenario: Production GP fit failure warns
- **WHEN** `fit_gpytorch_mll` 抛异常且 verbose=False
- **THEN** 发 warning（不再静默继续未拟合 GP）

#### Scenario: Golden unchanged
- **WHEN** 金档 2D/3D --check 在本变更后运行
- **THEN** PASS (bit-identical)

### Requirement: Central logging with GUI-capture-safe stdout handler
生产包（solvers/pipelines/controllers/df_surrogate/optimization/core/ui 库路径）的运行时输出 SHALL 走 `logutil.get_logger`（`tpmshx` 根 logger）。Handler SHALL 逐条解析当前 `sys.stdout`（非创建时绑定）——保证 `compute_orchestrator` 的 `redirect_stdout` 求解日志捕获不丢日志。默认渲染 SHALL 为裸消息（与旧 print 字节兼容）；`TPMSHX_LOG_TS=1` SHALL 加时间戳前缀；`TPMSHX_LOG_LEVEL` SHALL 控制级别（默认 INFO）。@njit 内与 CLI/`__main__` 路径的 print SHALL 保留。既有 `verbose` 门语义 SHALL 不变（logging 级别在其上叠加过滤，不替代）。

#### Scenario: Solve-log viewer still captures solver output
- **WHEN** GUI 跑一次 compute（orchestrator redirect_stdout 捕获）
- **THEN** 日志缓冲含转换后的 logger 输出（如 "[3D grid]" 行）

#### Scenario: Default output unchanged
- **WHEN** 未设任何 TPMSHX_LOG_* 环境变量跑一次求解
- **THEN** stdout 逐行字符串与转换前 print 输出一致

#### Scenario: Level filter works
- **WHEN** `TPMSHX_LOG_LEVEL=ERROR` 下跑求解
- **THEN** info 级求解 chatter 不出现

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

