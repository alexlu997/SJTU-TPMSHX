# Proposal: solver-efficiency-r1-r4

## Why

simpler-coupling-2d 的剖析暴露了真正的 2D 瓶颈：golden 管线里 B 侧（横流）SIMPLE solve 每次燃尽 10000 外迭代不收敛（绝对质量残差平台 1.3e-3 > tol 5e-4，场早已静止），PP spsolve 因此占管线墙钟 74%（总 47.6 s）。同一疾病 3D 已治愈（`lowre_early_exit`，速度稳定性门控），但从未回流 2D。另有三项后续：密度更新分配开销、3D 阶段占比未实测、3D 动量对流格式仍为一阶（2D 有 SOU）。

## What Changes

- **R1**：把 3D 的 A+B early-exit（速度稳定 + 平台失速）移植进 2D `SIMPLESolver.solve()`，默认开启（与 3D 一致）。**golden 2D 有意重基线**（退出迭代点不同 → 场哈希变；场变化在平台噪声内），门槛 = Shanghai 2D aligned 验证 RMSRE 复现（README 基准 ~8.4%）+ 全量 pytest。预期管线墙钟 ~10×↓。
- **R2**：`_update_density` 持久缓冲消除每迭代临时分配（占管线 7.3%）。bit-identical（在 R1 之前实施并用 golden `--check` 验证）。
- **R3**：`validate_shanghai_3d_real` gate 配置 cProfile 阶段分解（AMG/动量扫掠/LTNE 能量/耦合），结论写入 reports；只测不动 3D 代码，行动决策以证据记录。
- **R4**：3D 动量 SOU（minmod，2D N2 telescoping 口径）opt-in（`use_sou_momentum=False` 默认 → golden 3D 不动），小型网格收敛对比（一阶 vs SOU）作为"是否扶正"的证据记录。

## Capabilities

### New Capabilities
- `solver-efficiency-r1-r4`: 2D 低速早退判据、密度更新零分配、3D 阶段剖析证据、3D 动量 SOU opt-in——含各自不变量与验收门。

### Modified Capabilities

（无——`simpler-coupling-2d` spec 的默认路径 bit-identical 要求由 R1 重基线例外覆盖：R1 是有意、有门槛的重基线，非回归。）

## Impact

- 代码：`solvers/simple_solver.py`（R1+R2）、`solvers/simple_solver_3d.py`（R4）、新基准/剖析脚本、新测试。
- 基线：golden 2D 重基线（R1，有意）；golden 3D 必须 PASS（R2/R4 默认路径不动 3D；R4 flag 默认 off）。
- 无新依赖。
