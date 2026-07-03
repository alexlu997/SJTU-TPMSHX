# Spec: ui-chinese-chrome

## ADDED Requirements

### Requirement: Chinese chrome, untouched physics labels
界面 chrome（顶栏按钮、画布页签、手风琴组名、区块标题、空状态、导出菜单、CTA、onboarding）SHALL 为中文；物理量行标签、单位、符号（ε、D_h、ΔP、Nu、K/°C）、内部信号/属性名/key SHALL 保持原样；快捷键（Ctrl+R 等）SHALL 不变。

#### Scenario: No mixed chrome on one screen
- **WHEN** 检查顶栏 + 页签 + 组名
- **THEN** 无英文 chrome 文案（WS: A、K/°C 等标识符除外）

#### Scenario: Internal keys stable
- **WHEN** `_resolve_2d_view_card` / `_switch_tab` 运行
- **THEN** 仍以原英文串作 key 解析（combo 条目未改值，仅不可见）

### Requirement: Withdrawn item recorded
③ 原"计算完成自动跳结果页签"子项 SHALL 记录为撤销——`run_controller.py:603/670` 已实现该行为。

#### Scenario: Recorded
- **WHEN** 阅读本 change proposal/design
- **THEN** 撤销及既有实现位置在案
