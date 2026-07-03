# ui-layout-hygiene Delta — split-ui-main

## ADDED Requirements

### Requirement: Main_Menu mixin layout after split-ui-main
`Main_Menu` 的快捷键（ShortcutsMixin：_setup_shortcuts/_cycle_tab/_scrub_recent 等）、IO 动作（IOActionsMixin：导出/存取配置/复制图像）、ResultCache 属性桥（ResultBridgeMixin：_has_results* 等 @property 对）SHALL 各住独立 mixin（`ui/mixins/shortcuts.py`、`io_actions.py`、`result_bridge.py`），方法体逐字迁移、MRO 追加三项。结果侧栏三函数 SHALL 住 `ui/builders_sidebar.py`，`builders_canvas` re-export（既有 `from ui.builders_canvas import refresh_result_sidebar` 面不变）。不拆项 SHALL 记录决策：panel_vis_3d（整体 Qt 类无非 Qt 缝）、`build_canvas_area` 单体（嵌套闭包持 Qt 局部态）、run_controller/optimize_panel（单一职责内聚）。

#### Scenario: Window constructs with the extended MRO
- **WHEN** 离屏构造 Main_Menu（test_main_smoke）
- **THEN** 构造成功，快捷键/属性桥行为与拆分前一致（hygiene 锁全绿）

#### Scenario: Sidebar import surface unchanged
- **WHEN** run_controller 执行 `from ui.builders_canvas import refresh_result_sidebar`
- **THEN** import 成功并解析到迁移后的实现
