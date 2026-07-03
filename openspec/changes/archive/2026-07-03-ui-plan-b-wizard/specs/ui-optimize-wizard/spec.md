# Spec: ui-optimize-wizard

## ADDED Requirements

### Requirement: Three-page wizard
优化页 SHALL 为 QStackedWidget 三页（配置/运行/结果），阶段票据 SHALL 可点击切页；`_set_stage_pill(key,'active')` SHALL 同步翻到对应页——启动→运行页、完成→结果页、错误→配置页均由引擎既有阶段流转驱动。

#### Scenario: Engine drives pages
- **WHEN** `_set_stage_pill('running','active')`
- **THEN** 栈当前页 = 1（运行）

### Requirement: Inline BO parameters
qNEHVI 参数（n_init/n_iter/q_batch/seed/n_rho_loops）SHALL 内联于配置页并附求解次数/时长预估；`_launch` SHALL 优先读取内联值；无向导宿主 SHALL 回退模态对话框。

#### Scenario: Launch consumes inline values
- **WHEN** 点击启动
- **THEN** worker 以内联 spinbox 值构造，无弹窗

### Requirement: Search space on page 1
分区面板 SHALL 迁入配置页「搜索空间」卡；旧 zones|canvas splitter SHALL 退役；Pareto 画布 SHALL 独占结果页。

#### Scenario: Zone panel relocated
- **WHEN** 检查配置页
- **THEN** `_zone_panel` 为其子孙；启动 CTA 在首屏可见
