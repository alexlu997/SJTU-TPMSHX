# Spec: ui-cta-and-shortcuts

## ADDED Requirements

### Requirement: Sticky always-visible Compute CTA
Compute 主按钮 SHALL 常驻左面板底部固定条（不随参数滚动消失）；SHALL 是与原顶栏按钮同一 widget 对象（`window.btn_compute`），ticker 状态机、Ctrl+R、信号连接 SHALL 零改动；顶栏 SHALL 不再出现 Compute 按钮。

#### Scenario: CTA visible regardless of scroll
- **WHEN** 左面板滚动到任意位置
- **THEN** btn_compute 可见（位于滚动区外的固定条）

#### Scenario: Ticker still owns the button
- **WHEN** 离屏驱动一次真实 2D compute
- **THEN** 计算期间按钮文本变为 Cancel 计时样式，结束后恢复

### Requirement: Empty-state preset shortcut
空状态 SHALL 含"Load Shanghai preset"按钮，点击 SHALL 调用既有 `_load_named_preset('Shanghai (3D Gyroid)')`；空状态整体（文案+按钮）SHALL 在首次计算后隐藏（现行为保持）。

#### Scenario: One-click runnable config
- **WHEN** 点击空状态 preset 按钮
- **THEN** 输入字段被 Shanghai 预设改写（`_active_preset_name` 置位）

### Requirement: KPI primary tier
KPI 条 Q/ΔP_A/ΔP_B 数值 SHALL 高于 T_out 次要项一档（字号/颜色），caption 与 delta 徽标结构不变。

#### Scenario: Hierarchy present
- **WHEN** 检查 KPI chips QSS
- **THEN** Q/dPA/dPB 数值 chip 含主层标记（10pt/val 色），Tout 为次层

### Requirement: Withdrawn items recorded
RS-1（A/B 并排）与 RS-3（共享色标）SHALL 记录为撤销：RS-3 已由 `chk_sync_colorbar_T` 覆盖，RS-1 与域纵横比（宽扁场图）冲突。

#### Scenario: Design records the withdrawal
- **WHEN** 阅读本 change design.md
- **THEN** 两项撤销及理由在案
