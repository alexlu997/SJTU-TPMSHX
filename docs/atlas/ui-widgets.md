# ui — 其余组件
生成日期 2026-07-10，基于 commit f33d30e 附近的 master

本篇覆盖 `sjtu_tpmshx/ui/` 中除主窗口（`sjtu_tpmshx/main.py` 的 `Main_Menu`，见 `sjtu_tpmshx/main.py:117`）与 `ui/mixins/` 之外的全部文件：对话框、控件、页面构建器、matplotlib/PyVista 绘图层与纯工具模块。所有断言均已在代码中核实；无法核实处标注「未验证」。

## 定位与功能

该目录是 PySide6 桌面 GUI 的组件层。主窗口 `Main_Menu` 以 mixin 组合方式持有行为（`sjtu_tpmshx/main.py:117`），本层提供：

1. **页面构建器**（`ui_builders.py` + `builders_*.py`）：自由函数 `build_xxx(window)`，把控件以属性形式挂到 `window` 上（如 `window.combo_tpms`），保持 legacy 访问模式（`sjtu_tpmshx/ui/ui_builders.py:1`）。
2. **绘图层**：2D matplotlib 画布（`matplotlib_canvas.py`）、2D/3D 计算结果渲染（`plot_2d_results.py` / `plot_3d_results.py`）、嵌入式 PyVistaQt 3D 面板（`panel_vis_3d.py`）。
3. **主题系统**：`theme.py`（无 Qt 依赖的 token 与 QSS 字符串生成）→ `theme_manager.py`（`QObject` 包装、信号）→ `field_factory.py`（依赖注入的控件工厂）。
4. **纯逻辑模块**（可 headless 导入，不含 Qt import）：`window_config.py`、`preflight.py`、`expr_eval.py`、`fmt.py`、`math_symbols.py`、`vis3d_constants.py`、`theme.py`、`ui_constants.py`。
5. **交互增强**：命令面板、坐标探针、字段右键菜单、表达式求值、微动画、sparkline、skeleton 占位等。
6. **后台任务面板**：qNEHVI 优化（`optimize_panel.py`）与快速设计（`quick_design_panel.py`），均用 lazy 导入的 `QThread` worker 使 UI 不阻塞。

导入约定：整个仓库用**顶层包名** `ui.*` / `solvers.*`（非 `sjtu_tpmshx.ui.*`）互相引用（如 `sjtu_tpmshx/ui/panel_vis_3d.py:45`、`sjtu_tpmshx/ui/plot_3d_results.py:21`）；`main.py` 启动时把 `sjtu_tpmshx/` 目录与其父目录都插入 `sys.path` 以兼容两种导入方式（`sjtu_tpmshx/main.py:7`–`14`）。`ui/__init__.py` 为 0 字节空文件。

## 文件一览（每文件一行职责）

| 文件 | 行数 | 职责 |
|---|---|---|
| `__init__.py` | 0 | 空包标记 |
| `builders_base.py` | 267 | 页面构建共享行工厂：`section`/`collapsible_section`/`row`/`res_row`/`add_row`（Phase-5 起委托 `FieldFactory`，`sjtu_tpmshx/ui/builders_base.py:53`）、`_ResultLabel`、`right_align_combo` |
| `builders_canvas.py` | 1325 | 右侧画布区：结果卡片（temp/pres/vel/layout/pareto/3d）、tab 工具栏、zoom；含 3D 面板 offscreen guard（见下） |
| `builders_domain.py` | 410 | Geometry 页构建 + 2D/3D 维度切换（`_on_dim_changed`）+ CPU cores spinbox（接 `solvers.threads`，`sjtu_tpmshx/ui/builders_domain.py:282`） |
| `builders_fluids.py` | 266 | Boundary Conditions 页：Fluid A/B 输入卡、partial-pipe BC（inlet/outlet centre/width，含 3D z 向行，`sjtu_tpmshx/ui/builders_fluids.py:21`） |
| `builders_sidebar.py` | 149 | 结果 tab 诊断侧栏（固定宽 298 px，`sjtu_tpmshx/ui/builders_sidebar.py:13`） |
| `command_palette.py` | 462 | Ctrl+K 模糊搜索命令面板（`CommandPalette(QDialog)`），动作源每次打开时由 `build_actions(window)` 动态生成 |
| `coord_inspector.py` | 349 | 坐标探针右侧 dock（`CoordInspector(QDockWidget)`）：光标点处 Ta/Tb/Ts/u/v/P 读数，可 pin 对比 |
| `delegates.py` | 34 | `SelectAllDelegate(QStyledItemDelegate)`：表格编辑时全选文本 |
| `demo_vis_3d.py` | 292 | 独立脚本：跑 Shanghai case 8 粗网格并渲染 2×2 PyVista 演示图；依赖 gitignored 实验数据 xlsx（`sjtu_tpmshx/ui/demo_vis_3d.py:59`–`60`） |
| `expr_eval.py` | 173 | AST 白名单安全表达式求值（无 `eval()`），LineEdit 提交时把 `0.042/2` 替换为数值 |
| `field_factory.py` | 238 | `FieldFactory`：ThemeManager 依赖注入的控件工厂 + 进程级单例（`set_default_factory`/`default_factory`） |
| `field_menu.py` | 144 | LineEdit 右键菜单（Revert/Copy as expression）+ 最近 5 个值历史 |
| `fmt.py` | 73 | 无 Qt 格式化工具：`si`/`pct`/`preset_display`/`duration` |
| `glass_panel.py` | 87 | dark 主题静态模糊渐变背景 QPixmap 生成（`generate_blurred_bg`） |
| `layout_drawer.py` | 628 | Layout 画布几何绘制：2D 矩形/多边形、3D 长方体线框 + inlet/outlet 着色 |
| `math_symbols.py` | 152 | Qt 标签用 Unicode 希腊字母/下标转换（`to_unicode`/`greek`）；matplotlib 请直接用 mathtext；依赖顶层 `logutil`（`sjtu_tpmshx/ui/math_symbols.py:23`） |
| `matplotlib_canvas.py` | 273 | `MatplotlibCanvas(FigureCanvasQTAgg)`：温度/压力/zone 云图；`pad_field_to_edges` 把 cell-center 场外插到域边界 |
| `microanim.py` | 149 | 微动画：`pulse_glow`（完成脉冲）、`toast`（浮动提示） |
| `optimize_panel.py` | 1153 | qNEHVI 连续场优化器 UI 绑定：QThread worker、KPI/进度/Pareto 渲染、点选回填设计 |
| `panel_vis_3d.py` | 1659 | `ThreeDVisPanel(QWidget)`：嵌入 `pyvistaqt.QtInteractor` 的体渲染 + 切片面板；**模块顶层 import pyvista/pyvistaqt** |
| `plot_2d_results.py` | 275 | 2D 计算结果渲染入口 `finalize_plots(window)`、温度三联图 |
| `plot_3d_results.py` | 416 | 3D 结果渲染入口 `finalize_plots_3d(window) -> bool`（推场进 3D 面板 + 可选 mid-z 2D 切片） |
| `preflight.py` | 270 | 网格合法性预检（纯函数、无 PySide6，`sjtu_tpmshx/ui/preflight.py:3`） |
| `quick_design_panel.py` | 524 | 快速设计面板：lazy QThread worker 调 `design.*` 后端（枚举选型/固定单元 sizing） |
| `responsive.py` | 48 | `ResponsiveRow(QWidget)`：宽度阈值以下横排转竖排 |
| `sensitivity.py` | 386 | `SensitivityDialog(QDialog)`：N×N 0-D surrogate（`tpms_calc.compute`）参数扫描热图，点单元格回填主输入 |
| `session_overview.py` | 197 | `OverviewDialog(QDialog)`：会话 KPI 仪表盘 + Q 历史 sparkline（Ctrl+D） |
| `skeleton.py` | 141 | `Skeleton(QWidget)`：shimmer 占位（pareto/3d 两种布局），隐藏时停 QTimer |
| `sparkline.py` | 130 | `Sparkline(QWidget)`：无 matplotlib 的轻量折线，push 非法值静默拒绝 |
| `theme.py` | 577 | 主题单一真源：`_THEMES` 色板、字号/间距/圆角常量、`_build_styles()` QSS 生成、`apply_mpl_theme()`；模块顶层无任何 import（纯 Python） |
| `theme_manager.py` | 164 | `ThemeManager(QObject)`：样式字典缓存 + `theme_changed` 信号 + `bind_to_module` 向 `main` 镜像 legacy 全局变量 |
| `ui_builders.py` | 790 | 顶层装配：`build_ui`/`build_param_tabs`/`build_page_zones`/`switch_param_tab` |
| `ui_constants.py` | 24 | UI 数值常量：toast 时长、`VV_VELOCITY_LIMIT_MS`、`RE_NU_LO/HI` |
| `vis3d_constants.py` | 114 | 3D 可视化共享常量 `FIELD_ORDER`/`FIELD_META`（cmap=turbo/cividis）+ VTK plane widget 降调；无 Qt |
| `window_config.py` | 488 | 窗口收割适配器：`config_from_window(window) -> ComputeConfig`；duck-typed，**刻意不 import Qt**（`sjtu_tpmshx/ui/window_config.py:8`–`9`） |
| `zone_editor.py` | 174 | `ZoneHandleManager`：Layout 画布上可拖拽 zone 边界手柄（仅 1-D y 轴 MVP） |
| `zone_table.py` | 186 | "Define zones" 表格逻辑；对优化器已 DEPRECATED（`sjtu_tpmshx/ui/zone_table.py:3`–`5`，新代码用 `solvers.continuous_field.ContinuousFieldConfig`） |

## 公开接口（关键函数/类）

- `build_ui(window)` — `sjtu_tpmshx/ui/ui_builders.py:41`。构建整个主窗口，控件挂 `window` 属性。调用方：`ui/mixins/ui_builder.py:23`（`Main_Menu._build_ui`，由 `sjtu_tpmshx/main.py:219` 触发）。
- `build_canvas_area(window) -> QWidget` — `sjtu_tpmshx/ui/builders_canvas.py:39`。调用方：`sjtu_tpmshx/ui/ui_builders.py:234`。
- `build_page_domain(window)` / `build_page_fluids(window)` — `sjtu_tpmshx/ui/builders_domain.py:52` / `sjtu_tpmshx/ui/builders_fluids.py:91`。调用方：`ui_builders.build_param_tabs`（`sjtu_tpmshx/ui/ui_builders.py:287`）。
- `MatplotlibCanvas(nrows=1, ncols=3, figsize=(15,4.5))` — `sjtu_tpmshx/ui/matplotlib_canvas.py:65`。继承 `FigureCanvasQTAgg`；用 `Figure()` 而非 `plt.subplots()` 避免 pyplot Gcf 泄漏（`sjtu_tpmshx/ui/matplotlib_canvas.py:66`–`71`）。方法：`plot_zones`（:93）、`plot_temperature`（:174）、`plot_pressure`（:215）。实例化处：`sjtu_tpmshx/ui/builders_canvas.py:523`–`527`。
- `finalize_plots(window)` — `sjtu_tpmshx/ui/plot_2d_results.py:125`。调用方：`ui/mixins/run_controller.py:354`。
- `finalize_plots_3d(window) -> bool` — `sjtu_tpmshx/ui/plot_3d_results.py:62`。返回 False 表示解算成功但可视化失败（面板 init 异常或 offscreen 无面板），调用方不得自动切到 3D tab（`sjtu_tpmshx/ui/plot_3d_results.py:66`–`72`）。调用方：`ui/mixins/run_controller.py:564`。读 `window._result_3d`（`ComputeResult`，`sjtu_tpmshx/ui/plot_3d_results.py:80`–`88`）。
- `ThreeDVisPanel(QWidget)` — `sjtu_tpmshx/ui/panel_vis_3d.py:197`。数据入口 `set_fields(...)` / `load_shanghai_demo(...)`（docstring `sjtu_tpmshx/ui/panel_vis_3d.py:20`–`24`）。唯一 GUI 实例化点：`sjtu_tpmshx/main.py:1435`–`1436`（`_lazy_init_3d_panel`，用户首次切 3D tab 才构建）。
- `config_from_window(window, *, strict=False, force_3d=None) -> ComputeConfig` — `sjtu_tpmshx/ui/window_config.py:407`。`strict=True` 时 `_validate_required_widgets` 汇总列出全部空/非数值必填控件并 raise `ValueError`（:418–:429）。调用方：`ui/mixins/run_controller.py:88`、`:260`；测试 `tests/test_compute_config.py:31`。
- `compute_preflight(...)` + `FluidCfg` / `Preflight` dataclass — `sjtu_tpmshx/ui/preflight.py:116` / `:39` / `:51`。调用方：`sjtu_tpmshx/main.py:849`。壁面加密几何级数常量 n=8、first_cell=0.02 mm、growth=1.8，总加密宽 ≈5.46 mm（`sjtu_tpmshx/ui/preflight.py:27`–`31`）。
- `eval_expr(text) -> float|None` / `is_expression(text)` / `install_expression_eval(window)` — `sjtu_tpmshx/ui/expr_eval.py:55` / `:38` / `:135`。AST 节点白名单 `sjtu_tpmshx/ui/expr_eval.py:30`–`35`；非有限结果（`1/0`、`log(0)`）返回 None（:130–:131）。调用方：`sjtu_tpmshx/main.py:285`。
- `CommandPalette(QDialog)` / `build_actions(w)` / `install_command_palette(window)` — `sjtu_tpmshx/ui/command_palette.py:110` / `:275` / `:451`。调用方：`sjtu_tpmshx/main.py:276`。
- `CoordInspector(QDockWidget)` / `install_coord_inspector(window)` — `sjtu_tpmshx/ui/coord_inspector.py:122` / `:332`。调用方：`sjtu_tpmshx/main.py:278`。
- `ThemeManager(QObject)` — `sjtu_tpmshx/ui/theme_manager.py:46`。信号 `theme_changed(str)`（:59）；`bind_to_module(mod)` 把样式镜像成 `mod._BG` 等 legacy 全局（:138–:147，`_LEGACY_GLOBALS` 见 :36–:43）。theme 模块 lazy import，pytest collection 不触发 Qt（:63–:66）。
- `FieldFactory` / `default_factory()` / `set_default_factory(f)` — `sjtu_tpmshx/ui/field_factory.py:83` / `:65` / `:57`。`default_factory` 无已装工厂时自建 fallback（headless 测试可用，:66–:80）。
- `theme.get_theme()` / `set_theme(name)` / `get_density()` / `set_density(name)` / `apply_mpl_theme()` — `sjtu_tpmshx/ui/theme.py:233` / `:241` / `:259` / `:263` / `:502`。密度档 `compact/cozy/comfortable`（:225–:230）。
- `run_optimize(window)` / `cancel_optimize(window)` / `show_pareto(window, res)` / `load_pareto_solution(window, x)` — `sjtu_tpmshx/ui/optimize_panel.py:636` / `:905` / `:912` / `:1090`。worker 类由 `_make_worker_class()`（:46）lazy 构建，内部 `from PySide6.QtCore import QThread, Signal`（:56），run 中调 `optimization.optimizer_qnehvi.run_qnehvi`（:84, :110）。调用方：`ui/mixins/optimize_ui.py:25`–`:49`。
- `run_quick_design(window)` / `build_quick_design_dialog(parent)` — `sjtu_tpmshx/ui/quick_design_panel.py:160` / `:200`。worker 调 `design.cases/sizing/select/optimize`（:81–:103）。
- `draw_layout(window)` — `sjtu_tpmshx/ui/layout_drawer.py:11`。按 `combo_dim` 分派 2D/3D（:24–:34）。调用方：`ui/mixins/fluid_input.py:441`。
- `zone_*` 系列 — `sjtu_tpmshx/ui/zone_table.py:16`–`:138`（`build_zone_config` :138）。调用方：`ui/mixins/zone_panel.py:23`–`:51`、`ui/window_config.py:364`。
- `Sparkline.push(value)` — `sjtu_tpmshx/ui/sparkline.py:24`（非数值/非有限静默拒绝）。
- `fmt.preset_display(name)` — `sjtu_tpmshx/ui/fmt.py:53`：内部 preset 键保留 "Shanghai (…)" 拼写，用户可见处显示为「算例工况」（:60）。

## 关键配置项与开关（默认值 + 定义处）

- `TOAST_MS_BRIEF=2000` / `TOAST_MS_SHORT=3000` / `TOAST_MS_MED=5000` — `sjtu_tpmshx/ui/ui_constants.py:11`–`13`。
- `VV_VELOCITY_LIMIT_MS = 10.0`（V&V 验证过的速度上限，超出触发状态栏提示）— `sjtu_tpmshx/ui/ui_constants.py:18`。
- `RE_NU_LO = 600` / `RE_NU_HI = 30000`（Nu 关联式 v4.1 标定 Re 区间，界外 UI 标红）— `sjtu_tpmshx/ui/ui_constants.py:23`–`24`。
- 主题：`_active_theme` 默认 `'dark'`（`sjtu_tpmshx/ui/theme.py:219`；`get_theme` 读 `_THEMES[_active_theme]`，`sjtu_tpmshx/ui/theme.py:233`–`234`）；密度默认 `_active_density='cozy'`（`sjtu_tpmshx/ui/theme.py:230`）。
- `FIELD_ORDER` / `FIELD_META`（3D 面板字段顺序与 cmap：物理场 turbo、设计场 L_mm 用 cividis）— `sjtu_tpmshx/ui/vis3d_constants.py:20`–`50`。
- preflight 阈值：`_STREAM_MIN_CELLS=20`、`_INLET_MIN_CELLS=3`、`_RICHARDSON_WARN_CELLS=500_000` — `sjtu_tpmshx/ui/preflight.py:33`–`35`。
- 3D 卡片懒加载：`window.canvas_3d` 初始为 `None`（卡片内先放占位 QWidget），PyVistaQt 初始化推迟到用户切 3D tab（~1–2 s VTK/OpenGL 开销）— `sjtu_tpmshx/ui/builders_canvas.py:529`–`532`、`:559`、`sjtu_tpmshx/main.py:1414`。
- 温度三联图 colorbar 同步开关 `chk_sync_colorbar_T`（默认勾选）— `sjtu_tpmshx/ui/builders_canvas.py:607`–`608`，消费于 `sjtu_tpmshx/ui/plot_2d_results.py:20`–`23`。
- 优化面板 `allow_extrap`：读 `window.chk_allow_extrap`，与 env `TPMSHX_ALLOW_EXTRAP=1` 等效（surrogate 域外从 ValueError 降级为 warning）— `sjtu_tpmshx/ui/optimize_panel.py:242`–`251`；Compute 路径同名开关由 `_read_extrap_policy` 收割（`sjtu_tpmshx/ui/window_config.py:399`–`404`）。
- CPU 核数 spinbox：默认 `solvers.threads.get_solver_threads()`，范围 1–`max_threads()` — `sjtu_tpmshx/ui/builders_domain.py:302`–`304`；headless/批处理用 env `TPMSHX_NUM_THREADS`（tooltip，`sjtu_tpmshx/ui/builders_domain.py:309`–`310`；env 的实际消费在 `solvers/threads.py`，本篇未核实其内部）。

### 环境变量一览（本目录消费的）

| 变量 | 作用 | 判定处 |
|---|---|---|
| `QT_QPA_PLATFORM=offscreen` | 跳过 3D 面板构建（`_vis3d_import_error='headless/offscreen — 3D panel skipped'`） | `sjtu_tpmshx/ui/builders_canvas.py:535`–`538` |
| `TPMSHX_DISABLE_3D_PANEL`（`1/true/yes`） | 同上，显式禁用 3D 面板 | `sjtu_tpmshx/ui/builders_canvas.py:536`–`537` |
| `TPMSHX_EAGER_3D_SLICES=1` | 3D 结果落地后立即把 mid-z 切片渲染到 2D 画布（默认 `0` 不渲染，`window._rendered_3d_slices=False`） | `sjtu_tpmshx/ui/plot_3d_results.py:175`–`179` |
| `QT_REDUCED_MOTION`（`1/true`） | 3D 面板减少动画 | `sjtu_tpmshx/ui/panel_vis_3d.py:919` |
| `TPMSHX_ALLOW_EXTRAP=1` | surrogate 域外降级为 warning（与 UI 复选框等效；消费点在 surrogate 层，此处仅注释提及） | `sjtu_tpmshx/ui/optimize_panel.py:244` |
| `TPMSHX_NUM_THREADS` | 并行能量核线程数（headless 场景替代 spinbox；消费点在 `solvers/threads`，未验证） | 提及于 `sjtu_tpmshx/ui/builders_domain.py:279`、`:310` |

## 边界·假设·适用范围

- **Qt 绑定假设**：全目录硬编码 PySide6（无 PyQt5/PySide2 兼容层）。依赖声明 `PySide6>=6.7`（`requirements.txt:23`）、`pyvista>=0.45` / `pyvistaqt>=0.11`（`requirements.txt:19`–`20`）、`matplotlib>=3.8`（`requirements.txt:18`）。历史教训：v1 optimize 面板误写 PyQt6 导致整个 Optimize 按钮静默失效（`sjtu_tpmshx/ui/optimize_panel.py:50`–`54`）——移植时不得混用 Qt 绑定。
- **matplotlib 后端**：`main.py` 启动即 `matplotlib.use("QtAgg")`（`sjtu_tpmshx/main.py:18`）；`matplotlib_canvas.py:10` 直接 `from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg`——导入该模块要求 Qt 绑定已安装（但不要求显示器）。
- **单位约定**：域尺寸 L/H/Lz 与 pipe centre/width 为 m（`sjtu_tpmshx/ui/builders_fluids.py:22`–`29`）；绘图轴与 zone 表以 mm 显示（×1000 转换，`sjtu_tpmshx/ui/layout_drawer.py:20`）；TPMS 单胞 L_cell 与壁厚 t 为 mm（`sjtu_tpmshx/ui/sensitivity.py:23`–`24`）；温度 K、压力 Pa（3D 面板显示 kPa，`P_kPa` 为绝对压 `P_ref_abs+gauge`，`sjtu_tpmshx/ui/panel_vis_3d.py:16`）。快速设计面板矩形迎风高输入 mm→m（`sjtu_tpmshx/ui/quick_design_panel.py:45`）。
- **数据流假设**：结果渲染读 `window._compute_results`（2D，`sjtu_tpmshx/ui/coord_inspector.py:49`）/ `window._result_3d`（3D `ComputeResult`，`sjtu_tpmshx/ui/plot_3d_results.py:80`）；构建器约定所有控件是 `window` 的属性。`window_config.py` 与 `preflight.py` duck-typed，可用纯 Python stub 测试（`sjtu_tpmshx/ui/window_config.py:8`–`9`、`sjtu_tpmshx/ui/preflight.py:3`–`5`）。
- **数值限制提示**（UI 层面，非物理求解）：preflight 规则见 `sjtu_tpmshx/ui/preflight.py:7`–`19`（加密序列放不下→ERROR、inlet 覆盖 0 cell→ERROR、流向 <20 cell→WARNING、2D Richardson >500k cell→WARNING）；`_render_2d_slices_from_3d` 自带渲染器，因为 3D 加密网格非均匀，legacy 2D 绘图函数假设 `np.linspace` 均匀间距（`sjtu_tpmshx/ui/plot_3d_results.py:187`–`189`）。
- **sensitivity 面板走 0-D `tpms_calc.compute` 关联式而非 SIMPLE 求解器**（`sjtu_tpmshx/ui/sensitivity.py:3`–`6`），其 Q 排名用启发式 ΔT=40 K（`sjtu_tpmshx/ui/sensitivity.py:43`）——不可当求解器精度引用。
- **expr_eval 安全性**：仅接受二元/一元运算、数值常量、`math` 白名单函数（`sjtu_tpmshx/ui/expr_eval.py:14`–`35`），`^` 按 Excel 习惯转 `**`（:64）。

## 可扩展接口（hooks、注册点、私有 kwargs、env、预留分支）

- **进程级工厂注入**：`set_default_factory(factory)`（`sjtu_tpmshx/ui/field_factory.py:57`）——`Main_Menu.__init__` 装配后所有 `builders_base` helper 走同一 ThemeManager；不装则自动 fallback（:65–:80）。
- **主题热更新**：`ThemeManager.theme_changed(str)` 信号（`sjtu_tpmshx/ui/theme_manager.py:59`）+ `bind_to_module` legacy 镜像（:138）；`set_accent_override(hex)` 全主题改 `accent_primary`（`sjtu_tpmshx/ui/theme.py:248`–`254`，重置只能靠重导入模块，:255–:256）。
- **画布复用钩子**：`window._reuse_canvases` dict 存在时跳过重建 MatplotlibCanvas（主题切换路径，`sjtu_tpmshx/ui/builders_canvas.py:514`–`521`）。
- **3D 面板懒加载点**：`window._lazy_init_3d_panel`（`sjtu_tpmshx/main.py:1414`）；`plot_3d_results.finalize_plots_3d` 在 `canvas_3d is None` 时尝试调用（`sjtu_tpmshx/ui/plot_3d_results.py:100`–`106`）。
- **优化器 evaluator 注入**：`_OptimizeWorker(..., evaluator_fn=None)`——None → 2D `evaluate_design`（`run_qnehvi` 默认）；3D 模式传 `evaluate_design_3d`（M0 dimension-follows-Compute，`sjtu_tpmshx/ui/optimize_panel.py:76`–`79`）；3D 判定 `_is_3d_mode(window)`（:538）。
- **命令面板动作注册**：`build_actions(w)` 集中定义全部 Action（`sjtu_tpmshx/ui/command_palette.py:275`），新增全局动作在此追加即可。
- **`FieldSpec`/`CONFIG_FIELDS` 表驱动字段接线**：新增一个 ComputeConfig 标量字段只需在表中加一行（dataclass slot ↔ Qt widget ↔ parse kind ↔ 必填校验，`sjtu_tpmshx/ui/window_config.py:69`–`75`）。
- **coord_inspector 字段目录**：`_FIELD_TABLE`（`sjtu_tpmshx/ui/coord_inspector.py:33`–`43`）追加即可读新场。
- **预留/未实现分支**：`zone_editor.ZoneHandleManager` 仅支持 1-D y 轴 zoning，grid 模式与 x 轴回退到表格编辑（`sjtu_tpmshx/ui/zone_editor.py:3`–`7`、`:48`–`49`）。

## 已知不足与 TODO

- 代码内无 `TODO`/`FIXME`/`XXX` 标记，也无 `NotImplementedError` raise（全目录 grep 仅命中 `builders_fluids.py:137`、`:192` 两处**提及**求解器侧 fluid-type 门会 raise 的注释/tooltip 文案，UI 本身不 raise）。
- `zone_table.py` 对优化器路径已弃用，仅服务 "Define zones" tab（`sjtu_tpmshx/ui/zone_table.py:3`–`5`）。
- `theme_manager.py` docstring 声称 `ui.theme.set_theme` 是「persistent `.theme` marker」的写入者（`sjtu_tpmshx/ui/theme_manager.py:18`–`19`），但 `theme.py` 的 `set_theme` 只改模块全局、无任何磁盘写入（`sjtu_tpmshx/ui/theme.py:241`–`245`；grep 全文件无 open/write）——**文档与代码不符**；持久化若存在应在 main.py 侧，未验证。
- `set_accent_override(None)` 的重置路径未实现（注释明言靠重导入模块，`sjtu_tpmshx/ui/theme.py:255`–`256`）。
- `matplotlib_canvas.py` docstring 自称 "Light-only as of D-1（dark mode 已移除）"（`sjtu_tpmshx/ui/matplotlib_canvas.py:3`–`5`），但 `theme.py` 明确有 light + dark 两套 `_THEMES`（`sjtu_tpmshx/ui/theme.py:1`、`:46`）且画布按 `get_theme()` 取色——该 docstring 疑为过时残留，存疑。
- `optimize_panel.py` docstring 自述 "minimal first cut"、富交互 deliberately deferred（`sjtu_tpmshx/ui/optimize_panel.py:9`–`20`），实际文件已 1153 行，docstring 与现状的差距未逐项核对。
- `plot_2d_results.py` 顶层 `import matplotlib.pyplot as plt`（`sjtu_tpmshx/ui/plot_2d_results.py:14`）——与 `matplotlib_canvas.py:66`–`71` 刻意避开 pyplot Gcf 的做法不一致（此处仅用 `plt.MaxNLocator` 一类工具时无害，但导入即初始化 pyplot 状态机）。

## 服务器移植注意（Windows Server 2022 headless）

> 说明：移植目标是 **Windows Server 2022**，与开发机同为 Windows（非 Linux）。以下按条重新核实：不再成立的风险已删除或标注"不适用"，仍然真实但需换症状/解法的风险已重写，纯粹的"与 Linux 不同"式对比因两端现在都是 Windows 而直接删除。

1. **import 与实例化的失败点区分**：
   - 仅 `import`：本目录除 `demo_vis_3d.py` 外的模块在装齐 `PySide6/matplotlib/pyvista/pyvistaqt/numpy` 后均可无显示环境导入（Qt widget 类定义不需要 display；`window_config/preflight/expr_eval/fmt/math_symbols/vis3d_constants/theme/ui_constants` 更是完全无 Qt import）。
   - **实例化任何 QWidget 需要 `QApplication`**；Windows Server 上同样常无交互式桌面会话（Server Core 没有 GUI shell；即便是带 Desktop Experience 的版本，以服务/计划任务方式无人登录跑批时也处于 Session 0 隔离、没有当前用户桌面），此时须设 `QT_QPA_PLATFORM=offscreen`。这是 Qt 官方跨平台机制（`QApplication` 支持的通用 platform plugin，Windows/Linux 注册方式一致，都是同一个环境变量），**不是 X11/Wayland 专属方案**，不需要按 Linux 思路准备"显示服务器"。已实测本机（Python 3.12 + PySide6）`site-packages/PySide6/plugins/platforms/` 下自带 `qoffscreen.dll`，随 pip wheel 一起装好，**不需要额外安装任何运行库**——这一点比 Linux 更省心（Linux 版 offscreen 插件依赖系统 `libxcb-*`/`libEGL`/`libGL`，缺失时常需另装 xvfb；这条在 Windows Server 上不适用）。
   - **最危险的是 `ThreeDVisPanel`**：模块顶层 `import pyvista` + `from pyvistaqt import QtInteractor`（`sjtu_tpmshx/ui/panel_vis_3d.py:34`–`35`），构造时创建 VTK OpenGL 上下文。仓库已内置双 guard：`QT_QPA_PLATFORM=offscreen` 或 `TPMSHX_DISABLE_3D_PANEL=1` 时 `builders_canvas` 直接跳过 3D 面板（`sjtu_tpmshx/ui/builders_canvas.py:534`–`538`），`finalize_plots_3d` 对无面板情形返回 False 并仅记 warning（`sjtu_tpmshx/ui/plot_3d_results.py:107`–`114`）。**Windows Server 上务必设其一**：无独立显卡/驱动的服务器 VM 上，VTK 走 Windows 的 WGL 创建 OpenGL 上下文可能直接失败，具体报错形态与 Linux 缺 Mesa/OSMesa 时不同（未验证，本篇未在实体 Server VM 上复现），但两条既有 guard 能完全绕开这个问题，比逐一排查 GPU 驱动更可靠。
2. **`demo_vis_3d.py` 不能在裸服务器上跑**：顶层 import pyvista 且做 VTK 渲染（`sjtu_tpmshx/ui/demo_vis_3d.py:23`），并硬依赖 gitignored 数据 `<repo>/data/raw_data/20260401-上海电气天然气加热器实验工况.xlsx`（`sjtu_tpmshx/ui/demo_vis_3d.py:59`–`60`）；:61–:62 另有硬编码开发机绝对路径（`D:\Postgraduate\Homogenize\SJTU-TPMSHX\data\raw_data\…`）的 legacy 兜底，只能在原开发机上救 fresh worktree——裸服务器/其他机器两条路径都不存在，无法运行（该结论与目标平台是 Windows 还是 Linux 无关，两条路径本身就是这台开发机独有的）。
3. **sys.path 约定**：模块间用顶层包名 `ui.*`/`solvers.*` 互引（如 `sjtu_tpmshx/ui/plot_3d_results.py:21`）；任何独立脚本/测试入口必须把 `sjtu_tpmshx/` 目录加入 `sys.path`（`main.py` 自己做了双路径注入，`sjtu_tpmshx/main.py:7`–`14`；pytest 由 `pytest.ini` `testpaths=sjtu_tpmshx/tests` 配合 rootdir 解决）。改成 `sjtu_tpmshx.ui.*` 绝对导入是大手术，勿轻动。
4. **编码——这条不会因为搬到 Windows Server 而消失，反而要重点提防**：源码含大量中文字符串/docstring（如 `sjtu_tpmshx/ui/builders_sidebar.py:1`、`sjtu_tpmshx/ui/quick_design_panel.py:1`、`sjtu_tpmshx/ui/builders_canvas.py:500`–`501`），文件本身 UTF-8 保存，但风险从来不在"文件编码"，而在**运行时默认编码**：中文 Windows / Windows Server 的系统默认代码页仍是 GBK/CP936（本机实测：Python 3.12 下 `locale.getpreferredencoding()` → `'cp936'`，`sys.flags.utf8_mode` → `0`，UTF-8 模式未默认开启；Windows Server 2022 中文区域设置预期同样如此，这是 Windows 平台默认行为，与"是否是 Linux"无关——未在实体 Server 上复测，标记未验证）。已知的具体坑：
   - `sjtu_tpmshx/df_surrogate/surrogate_v3.py:149`–`155` 的注释记录了一次真实事故：`_log.info` 里若含中文，GBK 控制台下子进程按 GBK 字节写出日志，而 pytest 的 capture 流按 UTF-8 读取，一行中文即可污染后续所有测试的 teardown（`UnicodeDecodeError`）——**这个事故本身就是在 Windows 开发机上发生的，不是"Linux 特有、迁移后自动消失"的问题**，搬到 Windows Server 只会原样保留。
   - 现有自救仅两处、都是显式 `sys.stdout.reconfigure(encoding='utf-8')`（`sjtu_tpmshx/ui/demo_vis_3d.py:30`、`sjtu_tpmshx/ui/math_symbols.py:134`），且都包在 `try/except AttributeError` 里（重定向到文件的旧式流没有 `.reconfigure`）；`main.py` 里另有多处 `open(..., encoding='utf-8')`（如 `main.py:58`、`:319`、`:1033`、`:1563`、`:1574`、`:1585`）是可推广的正确写法，但全仓库未见统一约定，也未见设置 `PYTHONUTF8`/`PYTHONIOENCODING` 环境变量（grep 全仓库两者均无命中）。
   - 部署建议（本次核实后新增，代码里尚无对应实现）：无人值守启动脚本里显式设 `PYTHONUTF8=1`（Python 3.7+ 支持）或 `PYTHONIOENCODING=utf-8`，或用 `python -X utf8` 启动；`chcp 65001` **不能替代**上述设置——它只改当前控制台的活动代码页，不改 Python `locale.getpreferredencoding()` 依赖的系统 ANSI 代码页，二者是 Windows 上两个独立的机制（此为 Windows 平台通用知识，未针对本仓库代码路径专门复测）。
5. **字体假设**：`apply_mpl_theme` 的 sans 栈顺序为 `Fira Sans`/`Inter` 优先，其后 `Segoe UI`/`Helvetica`/`Arial`（+ Segoe UI Symbol/Emoji），`DejaVu Sans` 兜底（`sjtu_tpmshx/ui/theme.py:546`–`548`，代码注释自述目的是 "ensures every Windows/Linux/Mac box ends with a valid glyph source"）。迁移到 Windows Server 后这一条风险比原先设想的更小：`Segoe UI`（含 Symbol/Emoji 变体）是 Windows 系统自带字体，Server 版同样预装（Windows 平台常识，未在实体 Server 上逐一核实），大概率命中栈第 3 顺位而非落到 `DejaVu Sans`；`Fira Sans`/`Inter`/`Fira Code`（QSS 里同理，`theme.py:304` 附近注释）是否已装，取决于这台机器有没有装过设计字体包，这与"服务器是 Linux 还是 Windows"无关——开发机与服务器同为 Windows 只是让两边字体环境更可能凑巧一致，不能当作已验证。`DejaVu Sans` 由 matplotlib 自带分发（随 mpl-data 走，不依赖操作系统预装），任何平台的兜底路径都必然可用，故功能层面无风险。
6. **matplotlib 后端**：`main.py:18` 强制 `QtAgg`。纯批处理脚本不要 import `main`/`ui.matplotlib_canvas`，或先 `matplotlib.use('Agg')` 并绕开本目录的 Qt 画布。
7. **线程/并行**：GUI 后台任务全部是 `QThread`（`sjtu_tpmshx/ui/optimize_panel.py:56`–`58`、`sjtu_tpmshx/ui/quick_design_panel.py:69`–`71`）；求解核线程数 headless 场景用 env `TPMSHX_NUM_THREADS`（`sjtu_tpmshx/ui/builders_domain.py:309`–`310` tooltip；实现在 `solvers/threads.py`，未在本篇核实）。优化 worker 另用 joblib `n_jobs`（`sjtu_tpmshx/ui/optimize_panel.py:106`–`107`）。
8. **平台特定代码——此条因目标改为 Windows Server 而不再是风险点**：`glass_panel.py` 的噪点混合注释假设 QImage 内存序为 "BGRA on Windows"（`sjtu_tpmshx/ui/glass_panel.py:78`）。旧文档担心的是"这条 Windows 假设在 Linux 上是否也成立"，现在服务器同为 Windows，代码注释里的假设与部署平台直接一致，**不再需要任何跨平台验证**；纯装饰用途，异常时整段 try/except 跳过（:84–:85），风险已随目标平台变更而消解。
9. **已知 CI 教训——注意这是 CI 基础设施层面的历史记录，与本次"生产环境部署到 Windows Server"是两回事**：本仓库 CI 目前仍运行在 `ubuntu-latest`（`.github/workflows/ci.yml:23`，`:27` 强制 `QT_QPA_PLATFORM: offscreen`），不因本次生产服务器目标平台调整而自动改变，除非另立工单调整 CI 本身。历史教训拆开看：
   - Onboarding 弹窗曾挂死 CI（fresh checkout 无 `.first_run_done` 标记时，`QMessageBox.exec()` 在 offscreen 平台下无人可点，阻塞到 CI 45 分钟超时杀死）——该问题已在代码层修复，不依赖"哪个 OS 的 CI"：`main.py:1012`–`1014` 用 `QApplication.instance().platformName() == 'offscreen'` 判断跳过弹窗，`platformName()` 是 Qt 的跨平台通用属性，Windows/Linux 行为一致，因此这个修复对 Windows Server 同样生效，无需为服务器额外处理。
   - "日志行里的中文在 GBK 终端下污染 pytest capture"——这条在当前 `ubuntu-latest` CI 上"统一 UTF-8 locale 可规避"是成立的，但**不能照搬到 Windows Server 生产环境**：详见本节第 4 条，Windows 上没有等价的一步式"locale 转 UTF-8"操作，需要显式设 `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8` 或改代码里的 `encoding=` 参数，二者不是同一件事，不要混为一谈。
