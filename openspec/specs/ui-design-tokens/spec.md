# Spec: ui-design-tokens

## Purpose
设计令牌纪律：圆角/色值单一来源于 theme.py，锁测试禁散落 hex 与私设半径。（结构修复 2026-07-03：补 Purpose 头，内容不变。）

## Requirements

### Requirement: Radius two-tier policy
UI 圆角 SHALL 只取两档：常规 6px（`RADIUS_INPUT`/`RADIUS_CARD`）与语义 pill（`RADIUS_TAB` 14 / 既有胶囊 18）；builder QSS SHALL 无 1/2/3/4/7/8/10/12px 游离取值。

#### Scenario: No stray radii
- **WHEN** grep `border-radius:(1|2|3|4|7|8|10|12)px` on ui/
- **THEN** 零命中（mock/注释除外）

### Requirement: No hex outside theme
除 theme.py 外 ui 层 SHALL 无硬编码 6 位 hex 颜色——一律经 theme token；红色错误边框与搜索高亮 SHALL 成为 token（亮暗主题可独立调）。

#### Scenario: Light theme inherits fixes
- **WHEN** 切亮色主题
- **THEN** 原 26 处硬编码位置随 token 取亮色值，无暗色残留

### Requirement: Type scale closed
字号 SHALL 落在 FONT_* 阶（8/9/10/11/12pt + 展示位 20/22/34）；越界值归位。

#### Scenario: 13pt eliminated
- **WHEN** grep `font-size:13pt`
- **THEN** 零命中

### Requirement: Numeric inputs right-aligned
`FieldFactory.line_edit` 产出的数值输入 SHALL 右对齐（等宽已有）——小数点/量级对齐可扫读。

#### Scenario: Alignment set
- **WHEN** 检查任一参数输入框
- **THEN** alignment 含 AlignRight
