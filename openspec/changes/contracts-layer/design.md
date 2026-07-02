# Design: contracts-layer

## Context

- `controllers/compute_config.py`（810 行）实为两层混合：
  1. **纯契约**：ComputeConfig / FluidConfig / GeometryConfig / SolverConfig / PartialBCConfig / ExtrapPolicy / FeatureFlags / ZoneInputConfig 等 dataclass + `bc_to_dict` 等纯函数——pipelines/validation/tests 消费的就是这部分。
  2. **窗口采集**：`from_window(window)` 类函数——读 Qt widget（`combo.currentIndex()`、`ui.zone_table.build_zone_config(window)`）攒配置——这才是 controller 的本职，且是 ui 依赖的唯一来源。
- `ComputeResult` dataclass 在 `controllers/compute_pipeline.py`，被 stages_2d:1895 / stages_3d:675 deferred import。
- `theme_manager` 仅被 `ui/field_factory.py` + 2 个测试消费——UI 关切放错了包。
- 循环现状：pipelines→controllers（顶层 import ComputeConfig）+ controllers→pipelines（deferred import stages）互锁。

## Goals / Non-Goals

**Goals:** import 图成 DAG；pipelines/validation 不再 import controllers；deferred import 只剩真实懒加载；golden 2D+3D bit-identical。
**Non-Goals:** 不改任何 dataclass 字段/默认值/行为；不动 Pipeline2D/3D 编排逻辑本身；不做 ui 包内部重构。

## Decisions

### D1 — 拆分而非整移
`domain/compute_config.py` ← 纯契约部分（dataclasses + 纯函数，零 Qt、零 window 参数）。窗口采集函数留在 `controllers/compute_config.py`（从 domain import 契约类型）。判据：函数签名含 `window`/widget 或 body 摸 Qt 属性 → 留 controllers。`ZoneInputConfig` dataclass 本身进 domain；`build_zone_config(window)` 调用留在 controllers 采集侧 → **controllers→ui 泄漏随拆分自然消失**（采集函数在 controllers 调 ui 合法：等等——controllers 不应 import ui。改为把 zone 采集函数移到 ui 侧或由 main/mixins 注入）。裁决：`from_window` 采集函数的 ui.zone_table 调用改为**参数注入**（`zone_builder: callable = None`），main.py/mixins 调用时传入——controllers 零 ui import。
### D2 — ComputeResult → `domain/compute_result.py`
独立小模块（contracts 的另一半）。stages_2d/3d 顶层 import 之，deferred 消失。
### D3 — theme_manager → `ui/theme_manager.py`
唯一非测试消费者在 ui/。`controllers/__init__.py` 的 re-export 删除，两个测试改 import。ui.theme 的 deferred 变同包顶层 import。
### D4 — import 更新策略
全量机械替换（`from controllers.compute_config import` → `from domain.compute_config import`，约 41 处 + projects/），不留 shim。窗口采集函数的既有调用方（main/mixins）保持 `from controllers.compute_config import from_window...` 不变（该模块仍存在，只是瘦身）。
### D5 — deferred import 提升
拆分落地后，stages_2d/3d 与 compute_pipeline 中**仅为破环**的函数内 import 提升到模块顶；确属启动性能懒加载的（重库：matplotlib/pyvista/sklearn 类）保留并加一行注明。逐个判断，不批量。

## Risks / Trade-offs

- [残留环致 ImportError] → 启动即爆、易定位；`--collect-only` + main.py 冒烟先行。
- [projects/ 外部脚本漏改] → grep 全仓（含 projects/、benchmarks/、examples/、poc/）。
- [zone 采集注入改动调用方行为] → 注入默认值保持现行为（None → 内部按现逻辑 try/except 走 ui.zone_table？不——那就没消掉泄漏。默认 None = 不解析 zone，由 UI 调用方显式传 builder；grep 所有 from_window 调用点确认全部来自 UI 层后才可安全落地，实现时验证）。
- [golden 漂移] → 纯搬移无数值路径变化；bit-identical 门硬性把关。

## Migration Plan

单 commit 原子落地（搬移 + import 更新 + 测试改动）。回滚 = revert 单 commit。门顺序：`--collect-only` → main.py 离屏冒烟（runs/smokes）→ golden 2D+3D `--check` → 全量 pytest → push 看 CI。

## Open Questions

- `compute_pipeline.py` 里 Pipeline2D/3D 对 stages 的 deferred import：拆分后 controllers→pipelines 变单向，可提升为顶层——但 stages 模块 import 本身较重（numba warmup 链），若显著拖 GUI 冷启动则保留懒加载并注明（实现时测 import 耗时定夺）。
