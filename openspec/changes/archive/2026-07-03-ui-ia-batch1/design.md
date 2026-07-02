# Design: ui-ia-batch1

## Context

- `build_param_tabs`（ui_builders:247）：外层 QScrollArea → 2 个 QGroupBox 手风琴（可勾选折叠）→ 各含一个**页级 QScrollArea**（嵌套滚动）。
- domain 页 `lay` 顺序：Domain Geometry / TPMS Structure（含 computed res_rows 5-8）/ Material / Grid Settings（`sec_solver_rect`，已注册 `_rect_only_widgets`）/ Advanced 折叠（3 开关）/ Mesh Settings（`sec_solver_poly`）。
- fluids 页：ResponsiveRow（A/B 卡）/ pipe A / pipe B（`_build_pipe_section`，sec 注册 `_rect_only_widgets`）/ poly pipe label+frame（默认 hide）/ Preview 按钮。
- `switch_param_tab` 无调用者；`_accordion_groups` 仅本模块用。

## Goals / Non-Goals

**Goals:** 首屏输入字段 ~10（①②展开）；③④默认折叠；嵌套滚动消除；TPMS computed 折叠+算后自动展开；widget 属性名/信号/可见性门（_3d_only/_rect_only）全部不变。
**Non-Goals:** 吸底 CTA、preset 按钮、右侧改造（第二批）；流体卡内 computed 迁移（后批）；徽标（第三批）。

## Decisions

### D1 — section 注册表 + 重挂（不改 widget）
页 builder 建 widget 时同步登记 `window._ia_sections[key] = container`（domain：domain_geometry/tpms_structure/tpms_computed/material/grid_rect/advanced_flags/mesh_poly；fluids：fluids_row/pipe_a/pipe_b/poly_pipe_label/poly_pipe_frame/preview_btn）。`_build_pipe_section` 加注册。`build_param_tabs` 不再挂页壳：四组各建内容 QWidget（margins 6,4,8,6 / spacing 12 与原页一致），按序 addWidget 注册容器（re-parent 语义）。页壳（QScrollArea）弃用不挂——builder 仍被调用（widget 创建 + 副作用注册），返回值忽略；壳无 parent 由 Python 引用消亡。
### D2 — 组默认态与标题
`("Geometry & Structure", True), ("Fluids", True), ("Grid & Solver", False), ("Boundary Details & Advanced", False)`。流向 combo 在④——默认 A:+x/B:−y 覆盖标准横流工况，自定义方向属"边界细节"，组名点明。`switch_param_tab` 名单同步（无调用者，防御性更新）。
### D3 — TPMS computed 迁移
res_rows 5-8 + `_computed_divider` 从 g0 移出：`collapsible_section(window, lay, "Computed geometry", expanded=False)` 紧随 TPMS Structure 之后；res_row 改建于新 grid。`collapsible_section` 给 container 附 `_set_expanded(bool)`（复用内部 `_apply`）。`main.compute_tpms` 成功路径尾部 `getattr(self._ia_sections.get('tpms_computed'), '_set_expanded', lambda *_: None)(True)` 风格的守卫调用。
### D4 — 验证
`test_ui_layout_hygiene.py` 扩展：四组存在且默认态正确（③④ `isChecked()==False`）；`_ia_sections` 关键键存在；嵌套 QScrollArea 计数（左面板内可见 QScrollArea ==1）。加 compute_tpms 自动展开测试（离屏点按钮）。

## Risks / Trade-offs

- [re-parent 后 Qt 可见性继承异常（组折叠 setVisible 与 _3d_only 门交互）] → 与现状同构（原来页 setVisible 亦如此）；`_on_dim_changed` 在组展开 toggle 时由 collapsible/组信号再断言——组 toggled 已连接 page.setVisible，现改为 content.setVisible + 追加 `_on_dim_changed(window)` 调用（对齐 builders_domain Advanced 的 on_toggle 先例）。
- [弃用页壳遗漏子件] → 清单法（上文全量 inventory）+ 截图对比逐 section 点数。
- [session 恢复展开态?] → 组展开态本就不持久化，行为同现状。

## Migration Plan

单 commit。回滚 revert。门：布局卫生扩展测试 → 离屏 UI 套件 → 截图 → 全量 pytest → CI。
