# Design: ui-layout-fixes

## Context

- 参数行 = `FieldFactory.row`：QGridLayout col0 标签（stretch 3）/ col1 输入（stretch 2）。标签富文本不折行 → 网格 minimumWidth 由最长标签决定 → 超过左面板视口（~470px@1600 窗口）→ QScrollArea 横条 + 视觉裁切。
- 流体页：`_fluids_row` QHBoxLayout 硬并排（builders_fluids.py:113），窄面板裁切；注释预告堆叠 pass。
- 空状态：builders_canvas.py:340 两行 QLabel。
- 既有门可用：离屏 UI pytest（test_main_smoke 等 23 个）+ pytest 截图 grabber（本会话已验可产 PNG）。

## Goals / Non-Goals

**Goals:** 任意 ≥360px 面板宽下参数卡零横向滚动/零裁切；A/B 卡 <520px 自动竖排；空状态三步引导。零行为变化（信号/属性/字段名全不动）。
**Non-Goals:** 不动信息架构（方案 2）、不动视觉识别/主题（方案 3）、不改字号令牌。

## Decisions

### D1 — 折行在 factory 层做一次
`FieldFactory.label()`（row/add_row/res_row 共用入口）加 `setWordWrap(True)`。全局参数页生效、单点维护。风险：个别短标签行高波动——网格 verticalSpacing 8 吸收；若某页明显变丑，逐页豁免（不预期）。
### D2 — 横条策略 AlwaysOff 而非修最小宽
三个参数页 QScrollArea（domain/fluids/zones）`setHorizontalScrollBarPolicy(AlwaysOff)`。widgetResizable=True 时视口宽即内容宽 → 折行接管。不去逐个调 QLineEdit 最小宽（治标）。
### D3 — ResponsiveRow：resizeEvent 翻转 QBoxLayout 方向
```python
class ResponsiveRow(QWidget):     # ui/responsive.py
    def __init__(self, threshold=520, spacing=10): ...
    def addWidget(self, w): ...
    def resizeEvent(self, ev):    # width < threshold → TopToBottom else LeftToRight
```
确定性、可离屏测试（resize→方向断言）。不用自定义 FlowLayout（过度）。`section()` 直接往其 layout addWidget——签名兼容（section 接受 parent_lay）。
### D4 — 空状态：结构化三步
QLabel 富文本（HTML 有序列表式排版）或小 QVBox 三行：`① 左侧填几何与流体参数 → ② 点 Compute（Ctrl+R）→ ③ 在此查看温度/压力/速度场`。保留虚线框容器，令牌取色。文案按 frontend-design 写作原则：动词开头、指路不抒情。
### D5 — 验收：结构级截图对比
pytest grabber 产前后 PNG：断言级检查用 Qt API（无横条可见：`scroll.horizontalScrollBar().maximum()==0`；窄宽下 ResponsiveRow.direction==TopToBottom）写进新测试 `tests/test_ui_layout_hygiene.py`——比像素对比稳。

## Risks / Trade-offs

- [折行引发个别页面行高变化] → 离屏截图人查 + UI 测试；不影响功能。
- [AlwaysOff 在极窄面板（<300px）挤压输入] → splitter 已有最小宽约束；spec 下限定 360px。
- [ResponsiveRow 翻转时机抖动] → 阈值滞后不做（简单优先），翻转是幂等布局操作。

## Migration Plan

单 commit。回滚 = revert。门：UI pytest + 新布局卫生测试 + 全量 pytest（快速确认无误伤）。
