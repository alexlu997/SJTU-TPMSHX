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

