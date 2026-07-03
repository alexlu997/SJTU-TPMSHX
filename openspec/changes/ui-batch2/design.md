# Design: ui-batch2

## Context

- `btn_compute` 建于 ui_builders:214（header_row，BTN_PRIMARY），`run_controller` 的 ticker 对它有状态机：计算中文本→"Cancel · Ns"、点击信号 disconnect/reconnect（787-872）。**复制第二颗按钮 = 复制状态机**，否决；**搬迁同一对象** = 零改线。
- `build_param_tabs` 返回 QScrollArea，`build_ui` 直接 addWidget 进 splitter——换成 wrapper QWidget 调用方无感。
- 空状态（builders_canvas）为 QLabel；`_load_named_preset(name)`（SessionPresetsMixin）接受 builtin 名。
- KPI 条：caption(9pt mono)+value+delta 徽标结构完备；只调 QSS。
- 撤销项：RS-3 已由 `chk_sync_colorbar_T` 覆盖；RS-1 与域纵横比冲突（宽扁场竖排正确），两者不再实施。
- 发现待修注释：builders_canvas:331 提及不存在的 `_relayout_cards()`/`_set_canvas_cols`（死引用，顺手更正）。

## Goals / Non-Goals

**Goals:** CTA 永远可见且贴近参数区；首跑 ≤10 秒可跑；KPI 主次分层。ticker/快捷键（Ctrl+R）/信号全不变。
**Non-Goals:** RS-1/RS-3（撤销，理由如上）；顶栏其余按钮不动；3D 面板不动。

## Decisions

### D1 — CTA wrapper 结构
`build_param_tabs` 返回 `panel = QWidget(VBox[scroll(stretch=1), cta_bar(fixed)])`。cta_bar：`surface_raised` 背景 + 上边框分隔，内含 btn_compute（拉满宽、高 40、BTN_PRIMARY）。btn_compute 构造留在原处（build_ui 顺序：header 先建）？——否：按钮构造**移入** build_param_tabs（cta_bar 内直接建），header_row 处删除。校验 build_ui 中 header 构建顺序与 run_controller 首次引用时机（均运行时 getattr，安全）。
### D2 — 空状态按钮
空状态区域改为小 QVBox 容器（label + 按钮行）：按钮 "⚡ Load Shanghai preset (3D Gyroid)" BTN_SECONDARY，点击 `_load_named_preset('Shanghai (3D Gyroid)')`；隐藏逻辑随 `_empty_state_label` 同步——现隐藏点操作的是 label，改为容器 widget（保留 `window._empty_state_label` 指向 label 以兼容既有 setVisible 调用方？grep 调用方后定：若按 label 隐藏则容器整体挂 label 上——用容器承载并让 `_empty_state_label` 指向容器，文案断言用 findChild）。**实现时 grep `_empty_state_label` 消费者再定**。
### D3 — KPI 分层
Q/dPA/dPB 数值 chip：10pt + `val` 色；ToutA/B 保持 9pt sub_fg。caption 不动。
### D4 — 门
布局卫生测试 +3（cta_bar 存在且含 btn_compute、空状态按钮 wired、KPI 主 chip 字号 QSS 标记）；UI 套件；真实计算截图（吸底条 + KPI）；全量 pytest；CI（依赖 Linux 挂死修复先落地）。

## Risks / Trade-offs

- [btn_compute 构造点变更遗漏引用] → grep btn_compute 全部消费者（run_controller getattr 式，安全）；离屏 smoke 真跑 compute 验证 ticker。
- [空状态容器替换破坏隐藏逻辑] → grep 消费者，测试覆盖"计算后隐藏"。
