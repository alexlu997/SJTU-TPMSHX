# Proposal: ui-layout-fixes

## Why

UI 分析（2026-07-03，离屏截图 + 布局代码勘察）确认三个布局缺陷（用户选定方案 1）：
1. 1600×1000 窗口下左面板参数卡出现**内部横向滚动条**、输入框被右缘裁切——根因：`FieldFactory.row` 的 col0 标签（富文本、不折行）把网格最小宽度顶超面板宽度，QScrollArea 默认 AsNeeded 横条接管。
2. 流体 A/B 双卡 QHBoxLayout 并排，窄面板下同样裁切——`builders_fluids.py:113-118` 注释里自己预告了"resize-to-stack responsive pass"待做。
3. 首屏空画布 = 两行文字 + 虚线框，引导性弱。

## What Changes

- **标签折行**：参数行标签 `setWordWrap(True)`（`FieldFactory.row/add_row/res_row` 一处改，全参数页生效）；三个参数页 QScrollArea 设 `ScrollBarAlwaysOff`（横向）——widgetResizable 下内容宽被钉到视口宽，标签折行替代裁切。
- **响应式双卡**：新 `ui/responsive.py::ResponsiveRow`（QBoxLayout 方向按宽度阈值翻转，resizeEvent 驱动，~30 行），替换 `_fluids_row`；阈值 520px（代码注释既定值）。
- **结构化空状态**：三步引导（配参数 → Compute → 查看场图）+ 快捷键提示，纯排版无资产，复用主题令牌。
- **门**：离屏 UI pytest 全过 + 前后截图对比（豆腐块环境仍可判结构：滚动条消失、无裁切、堆叠触发）+ 全量 pytest。

## Capabilities

### New Capabilities
- `ui-layout-hygiene`: 参数面板无内部横向滚动、窄宽度自适应堆叠、空状态引导——布局卫生约束。

### Modified Capabilities
（无求解器/契约变化。）

## Impact

- 代码：`ui/field_factory.py`、`ui/builders_domain.py`/`builders_fluids.py`/`builders_zones.py`（滚动条策略）、`ui/builders_canvas.py`（空状态）、新 `ui/responsive.py`。
- golden 不涉及（纯 UI）；求解零变化。
