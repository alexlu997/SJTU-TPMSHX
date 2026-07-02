# Proposal: ui-ia-batch1

## Why

方案 2（信息架构重组）第一批，用户确认开工。现状：左面板两个全展开手风琴组（Geometry / Boundary Conditions），首屏 20+ 字段无优先级；computed 只读值混在输入流；低频项（partial BC 12 字段等）与核心项平铺。

## What Changes

- **IA-1 四段工作流手风琴**（重挂容器，widget/信号零改动）：
  - ① Geometry & Structure（展开）：Domain Geometry、TPMS Structure
  - ② Fluids（展开）：Fluid A/B 卡（ResponsiveRow）、Preview Layout 按钮
  - ③ Grid & Solver（**折叠**）：Grid Settings、Mesh Settings（poly）、Material Properties
  - ④ Boundary Details & Advanced（**折叠**）：Fluid A/B Inlet/Outlet（流向+partial BC）、Polygon Pipe Edges、既有 Advanced 开关组
  - 嵌套滚动区消除（页级 QScrollArea 壳弃用，section 直挂组布局——外层滚动已有）
- **IA-2（本批范围 = TPMS computed）**：TPMS 卡的 4 行 computed（ε/A₀/D_h/K_ss）移入独立折叠子区"Computed geometry"，默认折叠，`compute_tpms` 算完自动展开。流体卡内 computed 留待后批（卡内 COMPUTED 分隔线已有，噪声较小）。
- `collapsible_section` 暴露 `container._set_expanded(bool)`（自动展开钩子）。
- 门：布局卫生测试扩展（四组存在/默认态）、离屏 UI pytest、截图对比、全量 pytest、CI。

## Capabilities

### New Capabilities
- `ui-workflow-ia`: 左面板四段工作流分组与默认展开态、computed 降噪约束。

### Modified Capabilities
（无求解/契约变化。）

## Impact

- 代码：`ui/ui_builders.py`（build_param_tabs 重组）、`ui/builders_domain.py`/`builders_fluids.py`（section 注册 + computed 迁移）、`ui/builders_base.py`（_set_expanded）、main.py（compute_tpms 一行钩子）。
- 风险点：`_3d_only_widgets`/`_rect_only_widgets` 注册与可见性门在重挂后必须继续生效（widget 级，理论不受容器影响）；session 持久化按 widget 属性名（不变）。
