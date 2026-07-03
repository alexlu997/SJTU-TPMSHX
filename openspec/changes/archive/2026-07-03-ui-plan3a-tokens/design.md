# Design: ui-plan3a-tokens

## Context

审计（2026-07-03）：字号 73 处中 65 已在阶上（残 13pt×1，11pt×4 本就是 FONT_SECTION）；圆角 68 处 10 种取值（4×17、6×26 主导）；ui 层游离 hex 26 处（#3B82F6×10、#22C55E×6、#FFFFFF×4 等）；INP/VAL 已等宽。theme.py 自带 FONT_*/SPACE_*/RADIUS_* 常量但 builder 不引用。

## Goals / Non-Goals

**Goals:** 代码回归自家规范；亮色主题经 token 继承修正；数值右对齐。
**Non-Goals:** 间距栅格重排（SPACE 阶已一致，重排=不可见 churn）；换色换性格（那是方向 B）；20/22/34pt 展示字号（logo/大数字，语义合法）。

## Decisions

- **D1 圆角**：全部常规圆角→6px。RADIUS_CARD 12→6（影响 BTN_PRIMARY/header 卡）；`_frame` 硬编码 8→RADIUS_INPUT；builder 游离值逐个替换。pill 语义（RADIUS_TAB 14、胶囊 18）保留。4→6 的 17 处属可见微调（更圆一点），一批内完成保持一致。
- **D2 hex→token**：新增 token `err="#DC2626"`、`search_hl="#F59E0B"`（两主题同值起步，亮色可后调）；`#3B82F6`→`accent_primary`、`#22C55E`→`accent_green`、`#FFFFFF`→`tab_on_fg` 或按语义、其余按语义就近映射。KPI `_chip_num_primary_qss` 用的 `_t['val']` 已合规。
- **D3 右对齐**：`field_factory.line_edit` 加 `le.setAlignment(AlignRight|AlignVCenter)`；影响全部参数输入框。placeholder/单位换算文案不受影响。
- **D4 验证**：`test_ui_layout_hygiene` 加 3 锁（无游离圆角 grep 断言、ui 层无 hex 断言、输入右对齐）；暗/亮双主题截图对比；全量 pytest。
- **D5 分批**：批 1 = theme.py + field_factory + builders_domain/fluids/base/ui_builders；批 2 = builders_canvas + mixins + 对话框类。每批 UI 套件 + 截图。

## Risks / Trade-offs

- [4→6 视觉微变] → 方向 A 的目的本身；截图前后对比留档。
- [hex 语义映射错位] → 每处按上下文人工判断，不用正则盲替。
- [right-align 与内联单位输入（"5 mm"）] → 输入时左起打字不受对齐影响，仅显示位置变；试用后不适可单点回退。
