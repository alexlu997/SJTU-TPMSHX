# Proposal: ui-plan3a-tokens

## Why

方案 3 方向 A（用户选定）：工程蓝·现状精修。审计结论——theme.py **已有**字阶/间距/圆角常量与等宽数值栈，但 builder 层与自家规范脱节：圆角实际 10 种取值（1–18px，常量声称 6/12）、26 处游离 hex 绕过 token（亮色主题因此失真）、字阶仅 1 处越界（13pt）。A 的实质 = 让代码回归自家规范 + 补两处可见增强。

## Capabilities

### New Capabilities
- `ui-design-tokens`: 圆角双档统一、hex 全量 token 化、字阶收口、数值输入右对齐；亮色主题对比度校验。

## Impact

- `theme.py`：RADIUS_CARD 12→6（与 RADIUS_INPUT 并档）；`_frame` 8px→常量；游离 `#DC2626/#F59E0B` 提升为 token（`err`/`search_hl`）
- builder/mixin 层：圆角 1/2/3/4/7/8/10/12 → 6（语义圆角 14/18 pill 保留）；26 处 hex → `_t[...]` token；13pt→12
- `field_factory.line_edit`：数值输入右对齐（mono 已有）
- 亮色主题：token 化后截图校验对比度
- 分两小批提交（theme+左面板 → 画布+对话框），每批截图回归
