# Design: arch-b-c-e

## Context

- **B**：df_surrogate 顶层只需 `geometry`/`air_viscosity`/`air_density`/`P_atm`（load_data/residual_correction/smooth_df/surrogate_v3 顶层 import solvers.tpms_calc；predict/surrogate_domain 函数内 deferred）。`geometry()` 是 `tpms_geometry.compute_geometry`（已是叶子）的薄包装 + CHI_S。反向：tpms_calc.compute():489、df_projection ×3、simple_solver.__init__、polygon_fvm ×3 deferred import df_surrogate.predict。
- **C**：R1 移植后 2D/3D 各有一份逐行相同的早退块（`simple_solver.py` solve 尾部 / `simple_solver_3d.py:1641-1671`）+ 相同的 getattr 参数簇。纯 Python 层（不在 numba 内核里）。
- **E**：main.py 2696 行；`ui/mixins/` 已有 9 个混入（run_controller/ui_builder/fluid_input/optimize_ui/zone_panel...）。

## Goals / Non-Goals

**Goals:** kernel import 图成 DAG 且有测试锁定；早退判据单源且 golden bit-identical；main.py ≤ ~2000 行。
**Non-Goals:** 不合并 2D/3D massflux 捕获（标量 vs (Nx,Nz) 场，形状语义不同）；不统一 numba 内核；不动 panel_vis_3d 的渲染逻辑本身（只按内聚度抽块，若无干净切面则记录放弃理由）；不改任何默认行为。

## Decisions

### D1 — B：叶子 = `solvers/tpms_props.py`，tpms_calc 全量 re-export
移动块：常数（P_atm/R/M_air/Pr/Sa_mm？——仅移 df 需要的 + 物性函数自身依赖的；Pr/Sa_mm 留 tpms_calc）、`_AIR/_WATER` 范围常数与 `_warn_*` 助手、air_*(4)/water_*(4) 物性函数、`CHI_S`、`geometry()`。`tpms_calc` 头部 `from .tpms_props import (...)` 显式名单 re-export——50 个既有消费者零改动、bit-identical。
df_surrogate 5 文件 + predict/surrogate_domain 的 deferred 全改 `from solvers.tpms_props import ...`（提升顶层）。surrogate_domain 的 sCO2 `fluid_props` deferral 保留 + 注明（runtime-only 上行，fluid_props 在新 DAG 中位于 df 之上）。
solvers 侧 deferred df import 提升顶层（tpms_calc/df_projection/simple_solver/polygon_fvm）。predict.py import 链验证过是轻的（backend 构建仍惰性，4.4s 初始化不动）。
**DAG 测试**：fresh import `df_surrogate.predict` 后 `sys.modules` 无 `solvers.tpms_calc`/`solvers.simple_solver`；`import solvers.tpms_calc` 成功（拉 df_surrogate 合法）。

### D2 — C：`solvers/_solve_common.py` 的 `LowReExit`
```python
class LowReExit:
    def __init__(self, solver, min_iter): ...   # getattr 读 lowre_* 四参数 + 拷贝初始速度场
    def check(self, vels, res, it) -> bool      # (B)速度增量 + (A)平台失速；尾部更新 _prev
```
浮点次序契约：`max(|Δ| per field) / max(max|field| per field, 1e-30)`，与两份现行代码逐运算一致（2D 两场、3D 三场——`vels` 元组变长，max 归约次序 = 现行书写次序）。solve() 调用点：判据命中后各自做收尾（2D `_enforce_mass_conservation`、3D 直接 return）——收尾不进共享类。golden 2D/3D bit-identical 是硬门；若因归约次序打不平则调整实现直至打平（不允许重基线）。

### D3 — E：main.py 抽块策略
先扫 main.py 方法分组（读时定），优先抽：①结果写回/绘图胶水（write_result 族）②菜单/工具栏构建。落到既有 mixins 或新 mixin 文件，保持 `Main_Menu(Mixin1, ..., QMainWindow)` 模式。每抽一块跑 UI pytest 子集。panel_vis_3d：仅当存在无状态辅助函数群（非 Qt 方法）才抽 `panel_vis_3d_helpers.py`，否则记录"无干净切面，放弃"。

## Risks / Trade-offs

- [B 搬移漏内部依赖] → import 即爆；`--collect-only` + 全量 pytest 把关。
- [B 提升顶层 import 拖慢冷启动] → predict 链轻（backend 惰性构建不变）；若 UI 冷启动可感知退化，改回 deferred + 注明（非环，纯性能）。
- [C 次序差] → golden 双门硬性把关，不平不合。
- [E 信号/属性搬移错位] → 离屏 UI 测试（test_main_smoke/test_stylesheet_braces/test_pipeline_ui_hooks 等）+ 手动构造冒烟。

## Migration Plan

三个独立小 commit（B → C → E），各自过门后推送；CI 绿后归档。回滚粒度 = 单 commit revert。
