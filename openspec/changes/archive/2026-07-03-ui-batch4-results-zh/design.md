# Design: ui-batch4-results-zh

## Context

- 2D 场选择 = `combo_2d_field`（builders_canvas:151），消费者 `tab_view.py` 以 `currentText()` 英文串作 key（`_resolve_2d_view_card`、`_switch_tab` 反向同步）、门控 `setEnabled`（tab_view:91-93）。
- Export 菜单两项（builders_canvas:243-244），`_export_figure` 在 main.py:1810。
- 页签英文文本：Temperature/Pressure/Velocity/Geometry/Optimize/3D View/2D View/Fit View/Export。
- 计算后自动跳页签已存在 → 撤销该子项。

## Goals / Non-Goals

**Goals:** 场切换 1 击；图像 1 击进剪贴板；chrome 全中文；快捷键/信号/内部 key 零变。
**Non-Goals:** 物理量行标签、单位、日志/异常文本、代码注释——不翻；亮色主题、字阶（方案 3）。

## Decisions

- **D1 分段按钮**：隐藏 combo 保留为**状态源**（内部英文 key 不动），新增 3 个 QPushButton「温度｜速度｜压力」驱动 `setCurrentIndex`；`currentIndexChanged` 既有 handler 复用 + 新增分段重绘（反向同步：热键/代码路径改 combo 时按钮态跟随）。门控：tab_view:93 同步 `window._2d_field_seg` 容器 setEnabled。样式复用 `_PTAB_ON/OFF` 变体。
- **D2 复制剪贴板**：`main._copy_figure_clipboard` = 解析当前 `_active_tab` → 对应 FigureCanvas → `widget.grab()` → `QGuiApplication.clipboard().setImage`；Export 菜单第三项「复制当前图像」。无画布时状态栏提示。
- **D3 中文清单**（chrome only）：页签 温度/压力/速度/几何布局/优化/3D 视图/2D 视图；Fit View→适应视图；Export ▾→导出 ▾；组名 ①几何与结构 ②流体 ③网格与求解器 ④边界细节与高级；区名 域几何/TPMS 结构/几何计算值/材料属性/网格设置(rect)/网格划分(poly)/高级/流体 A·B 进出口；CTA「▶ 计算」（&mnemonic 对 CJK 无效→去掉）；空状态三步+「⚡ 载入上海工况 (3D Gyroid)」；Preview→预览布局；Export 菜单项中文；onboarding 中文。K/°C、WS: A、载入 ▾（已中文）不动。
- **D4 测试**：`_EXPECTED_GROUPS` 中文键；空状态标记 ">1<" 不变 + "计算" 代 "Compute"；`switch_param_tab` 名单中文；`_resolve_2d_view_card` 行为锁（分段点击→切卡）。

## Risks / Trade-offs

- [英文串既是 UI 又是 key 的隐性耦合] → 只把 combo 条目"藏"起来不改值；grep "Temperature" 全消费者核对。
- [grab() 截图含主题背景] → 可接受（所见即所得）；高保真导出走既有 PNG 路径。
