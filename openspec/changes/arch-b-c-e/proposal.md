# Proposal: arch-b-c-e

## Why

2026-07-02 架构扫描的剩余三个批次（B/E/C，用户指令"完成B-E-C"）。B：solvers↔df_surrogate 互赖靠 ~8 处函数内 deferred import 压住，kernel 内部不是 DAG。C：2D/3D 求解器 solve() 外循环判据双份维护——R1 已实证这种漂移的代价（3D 修了早退、2D 漏了一年、golden 管线慢 164×）。E：main.py 2696 行 / panel_vis_3d 1659 行超重，混入模式已存在但未抽完。

## What Changes

- **B（kernel DAG）**：抽叶子模块 `solvers/tpms_props.py`（geometry + air/water 物性关联式 + 常数 + 范围警告助手）；`tpms_calc` 全量 re-export（约 50 个消费者零改动）。df_surrogate 全部改 import 叶子；solvers 侧（tpms_calc/df_projection/simple_solver/polygon_fvm）的 deferred df import 提升顶层。新方向：`tpms_props ← df_surrogate ← {tpms_calc, simple_solver, ...}`。新增 import-DAG 测试。
- **C（solve 骨架单源）**：新 `solvers/_solve_common.py`：低速早退判据（速度稳定门控 + 平台失速）单一实现，2D/3D solve() 都调用；浮点运算次序与现行逐字节一致（纯 Python 层，无 numba/fastmath 风险）→ golden 2D/3D bit-identical 硬门。massflux 捕获两侧形状不同（标量 vs 场），不强行合并。
- **E（UI 减肥）**：main.py 按既有 mixins 模式抽 1-2 个内聚块（目标 ≤2000 行）；panel_vis_3d 视内聚度抽辅助模块。行为零变化（离屏 pytest UI 测试 + golden 门）。

## Capabilities

### New Capabilities
- `arch-b-c-e`: kernel import-DAG 约束、solve 骨架单源约束、UI 模块尺寸卫生——含各自验收门。

### Modified Capabilities
（无行为变化。）

## Impact

- 代码：solvers/（B+C）、df_surrogate/（B）、main.py + ui/（E）。
- 门：golden 2D/3D bit-identical（B/C 是纯结构；C 的共享判据必须逐浮点一致）、全量 pytest、CI 绿。
- 风险：B 的搬移遗漏内部依赖（import 即爆，易查）；C 的判据抽取引入次序差（golden 把关）；E 的 Qt 信号连接搬移错位（UI 测试把关）。
