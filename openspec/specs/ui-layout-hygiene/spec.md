# Spec: ui-layout-hygiene

## Purpose
左面板布局卫生（无横向滚动、响应式流体卡、结构化空状态）与 UI 结构变更的零行为约束。来自 openspec archive `ui-layout-fixes`（结构修复于 2026-07-03：早期归档把 delta 头 "## ADDED Requirements" 留在主 spec，重整为标准 `## Requirements`，内容不变）。
## Requirements
### Requirement: Parameter cards never scroll horizontally
面板宽 ≥360px 时，三个参数页（domain/fluids/zones）的 QScrollArea SHALL 无横向滚动（策略 AlwaysOff），行标签 SHALL 折行而非撑宽网格；输入控件 SHALL 完整可见。

#### Scenario: No horizontal scrollbar at default window size
- **WHEN** 1600×1000 离屏构造 Main_Menu
- **THEN** 三个参数页 `horizontalScrollBar().maximum() == 0`

### Requirement: Fluid A/B cards stack responsively
流体 A/B 卡 SHALL 置于 `ResponsiveRow`：可用宽 <640px 时竖排、≥640px 并排（实测默认窗宽下该行仅得 521px，520 阈值擦线导致并排挤压）；两种状态下均无裁切。

#### Scenario: Direction flips with width
- **WHEN** ResponsiveRow resize 到 400px / 800px
- **THEN** 布局方向分别为 TopToBottom / LeftToRight

### Requirement: Structured empty state
首屏画布空状态 SHALL 呈现三步引导（填参数 → Compute（含快捷键）→ 查看场图），文案动词开头、主题令牌取色；计算后 SHALL 隐藏（现行为不变）。

#### Scenario: Empty state present before first compute
- **WHEN** 构造后未计算
- **THEN** `_empty_state_label` 可见且含三步文案

### Requirement: Zero behavioral change
本 change SHALL NOT 改动信号连接、widget 属性名、字段默认值、求解路径；离屏 UI pytest 与全量 pytest SHALL 全绿。

#### Scenario: UI suite green
- **WHEN** 运行离屏 UI pytest + 新 `test_ui_layout_hygiene.py`
- **THEN** 0 failed

### Requirement: Main_Menu mixin layout after split-ui-main
`Main_Menu` 的快捷键（ShortcutsMixin：_setup_shortcuts/_cycle_tab/_scrub_recent 等）、IO 动作（IOActionsMixin：导出/存取配置/复制图像）、ResultCache 属性桥（ResultBridgeMixin：_has_results* 等 @property 对）SHALL 各住独立 mixin（`ui/mixins/shortcuts.py`、`io_actions.py`、`result_bridge.py`），方法体逐字迁移、MRO 追加三项。结果侧栏三函数 SHALL 住 `ui/builders_sidebar.py`，`builders_canvas` re-export（既有 `from ui.builders_canvas import refresh_result_sidebar` 面不变）。不拆项 SHALL 记录决策：panel_vis_3d（整体 Qt 类无非 Qt 缝）、`build_canvas_area` 单体（嵌套闭包持 Qt 局部态）、run_controller/optimize_panel（单一职责内聚）。

#### Scenario: Window constructs with the extended MRO
- **WHEN** 离屏构造 Main_Menu（test_main_smoke）
- **THEN** 构造成功，快捷键/属性桥行为与拆分前一致（hygiene 锁全绿）

#### Scenario: Sidebar import surface unchanged
- **WHEN** run_controller 执行 `from ui.builders_canvas import refresh_result_sidebar`
- **THEN** import 成功并解析到迁移后的实现

