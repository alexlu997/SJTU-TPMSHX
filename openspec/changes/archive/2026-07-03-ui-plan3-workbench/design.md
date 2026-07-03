# Design: ui-plan3-workbench

## Context

- 页签路由：`_switch_tab` 以内部 key（temp/pres/vel/layout/pareto/3d/2d_view）驱动卡片显隐；'2d_view' 已是聚合键（经 combo_2d_field 解析到场卡）——「结果」沿用同一聚合模式即可，**卡片与 key 全不动**。
- 门控：`_update_tab_visibility` rules 字典（2D 结果门 `_has_results_2d`、3D 门 `_3d_view_ready`、pareto 恒真）。
- 消费者：热键/分屏 `_split_with_current`/右键分离菜单全部引用 legacy 按钮对象——按钮**保留不上工具条**则零改。
- 数据源：能量闭合 Q_A/Q_B/Q_net 已在 run_controller:396-408 提取（入 recent-run 记录）；`_live_residuals` deque 供跑中排水；`ComputeResult.diagnostics`（iter_outer/iter_simple_A/B/wall_time_s）、`coeffs`、`warnings`、`extrap_reasons`；3D 有 envelope_valid/envelope_warnings。
- 火花线控件：optimize 面板已有 sparkline 实现，复用。

## Goals / Non-Goals

**Goals:** 三页签；2D/3D 段控随模式门控；侧栏与场同屏呈现可信度；诊断可复制。
**Non-Goals:** 优化页内部（方案乙另 change）；坐标探针改造；卡片渲染管线。

## Decisions

- **D1 'result' 聚合键**：`window._result_view ∈ {'2d','3d'}`。`_switch_tab('result')` → '3d' 态解析 '3d'，'2d' 态走 combo_2d_field 场解析。legacy 直呼（'temp'/'3d'…）反向置 `_result_view` 并点亮结果钮 + 段控。`btn_tab_result` 高亮条件 = active ∈ {temp,pres,vel,3d}。
- **D2 门控**：rules 增 `'result': rules['2d_view'] or rules['3d']`；2D|3D 段控每侧独立 enable；字段段控仅 2d 态 enable。combo_dim 切换时 `_result_view` 复位为对应模式。
- **D3 侧栏**：build_canvas_area 的 `canvas_scroll` 外包 QHBox：`[scroll, sidebar(fixed 298)]`。侧栏三卡：KPI（新建标签，`_refresh_result_sidebar()` 从 `_res_chips` 文本+delta 复制——`_update_result_summary` 尾部钩子调用，零重接线）、可信度、收敛。显隐 = `_has_results and active∈result族`，在 `_switch_tab` phase-2 与结果落地处同步。`_res_bar` 永久隐藏（对象与 chips 保留为数据载体）。
- **D4 诊断数据**：`self._diag_summary = dict(Q_A,Q_B,Q_net,closure_pct,envelope_valid,envelope_warnings,extrap_n,iters,wall_s,coeffs,warnings)`——2D 在 write_result 路径、3D 在 _run_calculation_3d 结果处填；`_begin_compute_ui` 清零 + `self._resid_history=[]`，`_drain_live_residuals` 顺手 append 留存。
- **D5 阶段**：T1 工具条+路由+门控（截图+测试）→ T2 侧栏+数据管道 → T3 对话框+复制摘要。各阶段全量门后可独立提交。

## Risks / Trade-offs

- [聚合键回归] → 锁测试：legacy `_switch_tab('temp')` 后 btn_tab_result ON、段控 2d；3D 同理。
- [侧栏挤压画布] → 298px 固定 + 窗口 <1280 时侧栏改为可折叠（setVisible 按钮）——T2 内实现最小版：折叠按钮常备。
- [能量闭合仅焓差可得时有效] → 缺数据显示 "—" 不装数。
