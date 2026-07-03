# Design: ui-plan-b-wizard

## Context

- 原优化页：op_v 竖排 stage pills / hero KPI / 控制行 / 进度 / 横幅，画布与分区面板挂 QSplitter。真实 BO 参数在 `_show_qnehvi_param_dialog` 模态（启动后才弹）。
- 阶段流转已有完整调用网：launch→(config done, running active)、done→(result active)、error→(pills 重置)。

## Decisions

- **D1 复用重挂**：不重写任何引擎/信号——KPI 标签、火花线、进度条、横幅、取消按钮原对象重挂进对应页；`_opt_status` 上移票据行右端全局可见。
- **D2 翻页驱动**：`_set_stage_pill` 中 state=='active' 时 `stack.setCurrentIndex(map[key])`——引擎所有阶段流转自动带动页面；票据 mousePressEvent 手动切页。错误路径改设 config='active'（原 'done'）以回配置页。
- **D3 参数内联**：五个 spinbox 存 `window._opt_inline_params`；`_launch` 有则直读、无则弹模态（测试/无向导宿主兜底）；求解次数预估逻辑从模态移植。
- **D4 布局教训**：CTA 初版被 p1row 的 stretch 推到卡片折叠线下（880px 卡在 1000px 视口内溢出）——改为 `par_lay.insertWidget(count-1, btn)` 插在尾部 stretch 之前，首屏可见。
- **D5 中文**：票据 1 配置/2 运行/3 结果；KPI 阶段·代数/最优 Q/最优 ΔP/剩余时间；收敛·最优 Q/超体积；启动/取消/空闲提示。运行中技术 status 串（qNEHVI n/N…）保留原样。

## Risks / Trade-offs

- [splitter 退役影响 `_optimize_split` 消费者] → grep 零消费者，安全。
- [分区面板迁移破坏 zone 控件引用] → 面板整体 re-parent，子控件属性名不变。
