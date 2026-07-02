# Spec: ui-workflow-ia

## ADDED Requirements

### Requirement: Four workflow accordion groups
左面板 SHALL 呈现四段工作流手风琴：Geometry & Structure（默认展开）、Fluids（默认展开）、Grid & Solver（默认折叠）、Boundary Details & Advanced（默认折叠）。widget 属性名、信号连接、`_3d_only_widgets`/`_rect_only_widgets` 可见性门 SHALL 不变。

#### Scenario: Default expansion states
- **WHEN** 离屏构造 Main_Menu
- **THEN** 四组存在；①② `isChecked()` True，③④ False

#### Scenario: Mode gates still work after re-parenting
- **WHEN** combo_dim 切 3D 后展开 Grid & Solver 组
- **THEN** Nz 行可见；切回 2D 后不可见（_on_dim_changed 复断言）

### Requirement: No nested scroll areas in the left panel
左面板 SHALL 只有外层一个 QScrollArea（页级滚动壳弃用）。

#### Scenario: Single scroll area
- **WHEN** 遍历左面板 children
- **THEN** 可见 QScrollArea 数量 == 1

### Requirement: TPMS computed values collapsed until computed
TPMS 的 ε/A₀/D_h/K_ss SHALL 位于"Computed geometry"折叠子区（默认折叠）；`compute_tpms` 成功后 SHALL 自动展开。`collapsible_section` SHALL 暴露 `container._set_expanded(bool)`。

#### Scenario: Auto-expand on compute
- **WHEN** 离屏点击 Compute TPMS Geometry（合法输入）
- **THEN** 子区展开且 `_v_eps` 显示数值

### Requirement: Gates
离屏 UI pytest（含扩展布局卫生测试）与全量 pytest SHALL 0 failed；截图对比 SHALL 确认首屏字段减半与折叠组呈现；CI SHALL 绿。

#### Scenario: Suite green
- **WHEN** 全量 pytest
- **THEN** 0 failed
