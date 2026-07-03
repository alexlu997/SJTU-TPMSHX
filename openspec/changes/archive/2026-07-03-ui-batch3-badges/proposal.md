# Proposal: ui-batch3-badges

## Why

方案 2 第三批（IA-4，最后一项）。四组手风琴让 ③④ 默认折叠——代价是无效/空字段可能藏在折叠组里，用户直到点 Compute 弹 preflight 模态才发现。组标题徽标把问题隔着折叠暴露出来：`▸ Grid & Solver ⚠2`。

## Capabilities

### New Capabilities
- `ui-group-badges`: 手风琴组标题实时显示组内无效+空字段计数徽标。

## Impact

- `ui/ui_builders.py`：`refresh_group_badges(window)` + 标题渲染统一（chevron+badge）；build 尾部初刷；组 toggle 复刷
- `main.py`：校验回调尾部去抖触发刷新
- 判定与 preflight 同源：`inpError=='true'` 或空文本；隐藏字段（2D/3D、rect/poly 门）不计
