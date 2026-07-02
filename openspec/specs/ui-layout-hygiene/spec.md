# Spec: ui-layout-hygiene

## ADDED Requirements

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
