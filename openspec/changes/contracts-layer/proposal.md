# Proposal: contracts-layer

## Why

架构扫描（2026-07-02）确认最大结构债：计算契约（`ComputeConfig`、`ComputeResult`）住在 `controllers/`，而下层 `pipelines/` 与旁路 `validation/` 都要用 → controllers↔pipelines 双向循环，靠 ~50 处函数内 deferred import 压住（stages_2d 26 处、stages_3d 18 处、compute_pipeline 6 处）。另有 controllers→ui 两处反向泄漏（`ui.zone_table.build_zone_config`、`ui.theme`）。这让 pipelines/validation 无法脱离 controllers 独立导入与测试，import 图不是 DAG。

## What Changes

- **契约下沉**：`controllers/compute_config.py`（整模块：ComputeConfig 族 dataclass + bc_to_dict 等纯函数）移至 `domain/compute_config.py`；`ComputeResult` dataclass 从 `controllers/compute_pipeline.py` 移至 `domain/compute_result.py`。`domain/` 现有章程（纯函数、无 Qt）正好匹配。
- **全量改 import**（约 41 处 + projects/ 脚本），**不留 controllers 转发 shim**（精简要求；一次机械替换）。
- **消 controllers→ui 泄漏**：
  - `compute_config` 对 `ui.zone_table.build_zone_config` 的 deferred 依赖：按实现时勘察结果，把 zone 构建纯逻辑下沉或改为调用方注入（design 记录两方案取舍）。
  - `theme_manager` 对 `ui.theme` 的依赖：theme_manager 本质是 UI 关切 → 移入 `ui/`（或实现时确认最小代价方案）。
- **deferred import 清理**：循环消失后，把 stages_2d/stages_3d/compute_pipeline 中仅为破环的函数内 import 提升到模块顶（其余为启动性能的懒加载则保留并注明）。
- **门**：golden 2D+3D bit-identical（纯搬移）、全量 pytest、CI 绿。

## Capabilities

### New Capabilities
- `compute-contracts`: 计算契约（config/result）的归属层与 import 方向约束。

### Modified Capabilities

（无行为变化——纯结构。）

## Impact

- 触及 ~45 个文件的 import 行；`controllers/` 从 8 模块减到 6-7；`domain/` 从 2 模块升为承载契约的中立层。
- 外部消费者（projects/ 驱动脚本、runs/、tests/）import 路径变化 —— 单 commit 内原子完成。
- 风险：循环残留导致 import error（启动即爆，易查）；golden 保证数值零变化。
