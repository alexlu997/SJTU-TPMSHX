# Proposal: ui-plan-b-wizard

## Why

用户批准方案乙（交互预览已确认）：优化页从"步进器+KPI+按钮+分区面板+空 Pareto 全部平铺"改为**三页向导**（1 配置 → 2 运行 → 3 结果），页面状态跟随任务阶段——配置时只见配置，运行时满屏监控，结束后满屏结果。根治"栏目缺乏逻辑关联"（原 01 CONFIG 高亮但页面无任何可配置项：真实 BO 参数藏在启动后的模态弹窗）。

## Capabilities

### New Capabilities
- `ui-optimize-wizard`: QStackedWidget 三页向导、BO 参数内联、阶段票据驱动翻页、全中文。

## Impact

- `builders_canvas.py` pareto 卡重排：票据行（可点击导航）+ 三页栈。页 1 = 优化参数卡（n_init/n_iter/q_batch/seed/n_rho_loops 内联 spinbox + 求解次数预估 + 橙色启动 CTA）+ 搜索空间卡（分区面板迁入，旧 zones|canvas splitter 退役）；页 2 = KPI 大数四卡 + 收敛火花线 + 渐变进度 + 取消；页 3 = 摘要横幅 + Pareto 画布
- `optimize_panel.py`：`_set_stage_pill(state='active')` 兼职翻页（引擎既有阶段流转免费驱动页面）；`_launch` 优先读内联参数（模态对话框降为无向导宿主的兜底）；错误路径回配置页
- 引擎/worker/KPI-status setter/结果保存全部不动
