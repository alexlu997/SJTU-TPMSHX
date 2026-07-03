# Proposal: ui-plan3-workbench

## Why

用户选定右侧界面方案 III「工作台」：页签收敛为 几何布局｜结果｜优化，2D/3D 合并进「结果」页内切换（同一份数据两种渲染），右侧 298px 常显侧栏把 `ComputeResult` 里**算了但从未上屏**的可信度数据变成界面功能——能量平衡闭合（Q_A/Q_B/Q_net）、包络有效性、外推警告、收敛历史、迭代/耗时、闭合系数。

## Capabilities

### New Capabilities
- `ui-result-workbench`: 三页签工作台、结果页 2D/3D 切换、常显诊断侧栏、诊断详情对话框（含一键复制摘要）。

## Impact

- `builders_canvas.py`：工具条重排（结果聚合钮 + 2D|3D 段控 + 右端动作）、canvas 区包 HBox 加侧栏、KPI 带退役（侧栏卡替代，读同一数据）
- `tab_view.py`：`_switch_tab` 增 'result' 解析（沿用 '2d_view' 聚合模式）、`_update_tab_visibility` 增 result/段控门
- `run_controller.py`：2D/3D 结果路径落 `_diag_summary`（能量闭合/包络/外推/迭代/耗时）+ 残差历史留存 + 侧栏刷新钩子
- 兼容层：legacy 按钮（temp/pres/vel/3d/2d_view）保留对象不上工具条——热键/分屏/右键分离/路由零改
- 分三个内部阶段（T1 页签收敛 → T2 侧栏 → T3 诊断对话框），每阶段测试+截图可停
