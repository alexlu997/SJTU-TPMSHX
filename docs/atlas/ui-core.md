# ui — 主窗口与 mixins

生成日期 2026-07-10，基于 commit f33d30e 附近的 master

## 定位与功能

本章覆盖桌面 GUI 的主窗口层：`sjtu_tpmshx/main.py`（`Main_Menu` 主窗口 + 程序入口）、`sjtu_tpmshx/ui/mixins/` 全部 13 个 mixin，以及 UI 状态到求解器配置的唯一转换器 `sjtu_tpmshx/ui/window_config.py`。

主窗口 `Main_Menu` 是历史上的「god object」，现已按行为切片拆分为 13 个 mixin，通过多重继承组装：`class Main_Menu(RunHistoryMixin, DialogsMixin, ZonePanelMixin, OptimizeUIMixin, TabViewMixin, UIBuilderMixin, FluidInputMixin, RunControllerMixin, AppearanceMixin, SessionPresetsMixin, ShortcutsMixin, IOActionsMixin, ResultBridgeMixin, QMainWindow)`（`sjtu_tpmshx/main.py:117-121`）。每个 mixin 只在调用时依赖 `self`（活动窗口），不在 import 时依赖 `main` 模块全局量，保持 import 图无环：`main` → `ui.mixins.*`，从不反向（`sjtu_tpmshx/ui/mixins/__init__.py:1-9`）。需要 `main` 中符号（`__version__`、`_git_commit_hash`）的 mixin 采用惰性 `__import__` 解析（`sjtu_tpmshx/ui/mixins/io_actions.py:19-29`、`sjtu_tpmshx/ui/mixins/run_history.py:41-51`）。

计算路径分工（移植时的关键分界）：

- Qt 控件读取只发生一次，在主线程上，由 `ui.window_config.config_from_window` 完成，产出纯数据 `ComputeConfig`（`domain.compute_config` 的 dataclass）；工作线程只见 `ComputeConfig`，不触碰 Qt（`sjtu_tpmshx/ui/mixins/run_controller.py:85-93`、`sjtu_tpmshx/ui/window_config.py:407-485`）。
- 数值求解在 `controllers/compute_pipeline.py` 的 `Pipeline2D` / `Pipeline3D`（工作线程闭包内构造，`sjtu_tpmshx/ui/mixins/run_controller.py:96-120`、`281-297`），线程生命周期由 `controllers.compute_orchestrator.ComputeOrchestrator` 管理（`sjtu_tpmshx/controllers/compute_orchestrator.py:151`），其 Qt signal（started/progress/finished/error/cancelled）在构造函数中接线（`sjtu_tpmshx/main.py:193-203`）。
- 结果回写：`write_result` 把 `ComputeResult` dataclass 拷贝到遗留窗口属性（`sjtu_tpmshx/ui/mixins/run_controller.py:368-489`）；这些遗留属性名本身经 `ResultBridgeMixin` 的 property 桥接到 `controllers.result_cache.ResultCache`（`sjtu_tpmshx/ui/mixins/result_bridge.py:22-88`）。

## 文件一览

主窗口（包根，不在 ui/ 下）：

| 文件 | 职责 |
| --- | --- |
| `sjtu_tpmshx/main.py`（1604 行） | `Main_Menu` 主窗口类 + `if __name__ == "__main__"` 入口（`main.py:1523`）。保留在此文件的行为：构造与控制器组装（`main.py:122-291`）、拖放加载 preset JSON（`main.py:293-343`）、Shanghai 预设 `_apply_shanghai_defaults`（`main.py:363`）、TPMS 几何计算 `compute_tpms`（`main.py:556`）、输入预检 `_validate_inputs_preflight`（`main.py:698`）/ `_preflight_grid`（`main.py:754`）、统一字段校验器 `_attach_field_validation`（`main.py:1253`）、`closeEvent`（`main.py:915`）、3D 面板懒初始化 `_lazy_init_3d_panel`（`main.py:1414`）、无障碍标注、About/引导对话框。 |

`sjtu_tpmshx/ui/mixins/`（13 个 mixin + `__init__.py`）：

| 文件 | 职责 |
| --- | --- |
| `__init__.py`（25 行） | 重导出 13 个 mixin；docstring 记录组装契约（`mixins/__init__.py:8`）。 |
| `run_controller.py`（1213 行） | 计算入口 `run_calculation` / `_run_calculation_3d` / `_run_polygon_calculation`、orchestrator 五个 signal 处理器、结果写入 `write_result`、计算期 UI 生命周期（按钮变取消、进度条、残差 sparkline、诊断摘要对话框）。 |
| `fluid_input.py`（450 行） | 流体 Auto-fill（`_auto_fill_fluid`，调用求解器闭包计算）、K/°C 单位转换（`_temp_to_K` / `_set_temp_K` / `_toggle_temp_unit`）、流向/形状变更处理、遗留 per-side BC 读取 `_fluid_config`、出口温度后处理 `_update_tout`。 |
| `session_presets.py`（559 行） | 用户 preset、A/B/C 工作区（workspace）切换、会话自动持久化（`_save_session` / `_restore_session`）；持有 `_SESSION_LINE_EDITS/_SESSION_COMBOS/_SESSION_CHECKS` 允许名单。 |
| `run_history.py`（371 行） | 最近运行环形缓冲（`_push_recent_run`）、持久 JSONL 时间线（`.session_timeline.jsonl`）、可复现链接 token、结果溯源 tooltip、「复制输入为 Python」导出。 |
| `tab_view.py`（588 行） | 页签可见性规则 `_update_tab_visibility`（`tab_view.py:34`）、`_switch_tab`（`tab_view.py:210`）、2D/3D 结果视图切换 `_toggle_result_view`（`tab_view.py:188`）、画布缩放与 3D/2D 画布 detach/reattach（`tab_view.py:451-572`）。 |
| `ui_builder.py`（237 行） | 页面/画布构建的薄委托（转发到 `ui.ui_builders` / `ui.builders_*`），加上状态栏常驻控件、全局 undo 栈（QUndoStack, `ui_builder.py:116`）、字段帮助 tooltip、状态日志安装。 |
| `io_actions.py`（321 行） | 结果导出 CSV/NPZ（`io_actions.py:56`）、config JSON 存取（`io_actions.py:133/182`）、图像剪贴板复制与带元数据的 PNG/SVG/PDF 导出。 |
| `appearance.py`（245 行） | 主题/密度/强调色切换（写 `.theme`/`.density`/`.accent` 点文件并 `os.execv` 重启进程，`appearance.py:183`）、左面板折叠、3D 沉浸模式。 |
| `shortcuts.py`（139 行） | 全部键盘快捷键接线（`_setup_shortcuts`，`shortcuts.py:26`；Ctrl+R = 计算，Ctrl+Return = 优化）。 |
| `dialogs.py`（229 行） | 只读信息对话框：会话总览（委托 `ui.session_overview`）、求解日志查看器。 |
| `zone_panel.py`（52 行） | 分区（zone）编辑器按钮处理，全部薄委托到 `ui.zone_table`。 |
| `optimize_ui.py`（58 行） | qNEHVI 优化面板处理器，全部薄委托到 `ui.optimize_panel`；quick-design 对话框启动器。 |
| `result_bridge.py`（89 行) | 遗留结果属性名（`_compute_results`、`_result_3d`、`_has_results*`、`_drawn_tabs`）到 `ResultCache` 的 property 桥。 |

本章重点关联的 ui/ 模块（各有独立职责，另章详述）：`ui/window_config.py`（控件→ComputeConfig 适配器，本章覆盖）、`ui/ui_builders.py` + `ui/builders_{base,domain,fluids,canvas,sidebar}.py`（控件构建）、`ui/zone_table.py`、`ui/optimize_panel.py`、`ui/plot_2d_results.py` / `ui/plot_3d_results.py`（渲染）、`ui/preflight.py`（网格预检计算）、`ui/theme.py` / `ui/theme_manager.py` / `ui/field_factory.py`（样式 DI）、`ui/panel_vis_3d.py`（PyVista 3D 面板）。

## 公开接口

### 主窗口生命周期

- `Main_Menu.__init__(self)`（`sjtu_tpmshx/main.py:122`）— 组装顺序固定：ThemeManager/SignalRouter → FieldFactory DI（`main.py:189-190`）→ ComputeOrchestrator + signal 接线（`main.py:193-203`）→ SessionManager/ResultCache（`main.py:211-212`）→ `_build_ui()` → 校验器/状态栏/undo → `_apply_shanghai_defaults()` → `_restore_session()`（`main.py:247-251`）。调用方：入口块 `main.py:1601`。
- `closeEvent(event)`（`sjtu_tpmshx/main.py:915`）— 依次：保存会话、协作式取消计算并 `_pool.waitForDone(3000)`（`main.py:944-956`）、关闭 detach 窗口、PyVista GL 清理、`signals.disconnect_all()`。

### 计算入口与回写（RunControllerMixin）

- `run_calculation(self)`（`sjtu_tpmshx/ui/mixins/run_controller.py:35`）— 唯一的「▶ 计算」入口（按钮接线于 ui_builders；Ctrl+R 于 `shortcuts.py:32`）。分派顺序：重入守卫 → `_validate_inputs_preflight` → `_preflight_grid` → polygon（`combo_shape.currentIndex()>0` → `_run_polygon_calculation`，主线程运行，`run_controller.py:66-68`）→ 3D（`combo_dim.currentIndex()==1` → `_run_calculation_3d`，`run_controller.py:71-73`）→ 2D 默认。2D 路径要求先 Auto-fill（`self._K_ffA is None` 即弹窗返回，`run_controller.py:76-81`）。
- `_run_calculation_3d(self)`（`run_controller.py:235`）— `_preflight_3d`（Nz≥2 强制、>100k cell 确认弹窗含 RAM 估算 `est_cells*50*8/1e9` GB，`run_controller.py:207-227`）→ `config_from_window(strict=True, force_3d=True)`（`run_controller.py:262-263`）→ orchestrator 启动 + 30 min 硬墙钟看门狗（`_hard_timeout_s = 1800.0`，`run_controller.py:312`）。
- `write_result(self, result)`（`run_controller.py:368`）— `ComputeResult` → 遗留窗口属性适配器。3D 模式直接发布 dataclass 为 `self._result_3d` 后返回（`run_controller.py:422-426`）；2D 模式展开 fields 为 `_compute_results` dict、`T_fA/T_fB/T_s`（加 `[np.newaxis]` 兼容形状，`run_controller.py:454-460`）、闭包系数 `_K_ff*/_h_v*/_rho_*/_mu_*`（`run_controller.py:468-475`）、zone 统计。未收敛时在 warnings 头部插入中文告警（`run_controller.py:393-397`）。调用方：`_2d_worker` / `_3d_worker` 闭包（`run_controller.py:119`、`296`）。
- orchestrator signal 处理器：`_on_orch_started`（`run_controller.py:491`）、`_on_orch_finished`（`run_controller.py:524`，3D 分支区分「求解成功但渲染失败」：`_3d_view_ready` 独立于结果存在性，`run_controller.py:628`）、`_on_orch_error`（`run_controller.py:712`）、`_on_orch_cancelled`（`run_controller.py:766`）。接线处：`main.py:194-203`。

### UI 状态 → cfg（ui/window_config.py，移植时最重要的接口）

- `config_from_window(window, *, strict=False, force_3d=None) -> ComputeConfig`（`sjtu_tpmshx/ui/window_config.py:407`）— 唯一读取 `window.le_*` / `window.combo_*` 的模块（模块 docstring，`window_config.py:1-10`）。全程 duck-typed（`getattr` + `text()`/`currentText()` 探测），刻意不 import Qt，headless 测试可传普通 stub（`window_config.py:8-9`、`24-41`）。`strict=True` 时 `_validate_required_widgets` 汇总抛 `ValueError`（`window_config.py:149-232`；非空文本必须可解析为有限数，nan/inf 拒绝）。调用方：`run_controller.py:88-92`（2D）、`run_controller.py:260-264`（3D）、`ui/quick_design_panel.py` 等。
- `CONFIG_FIELDS: tuple[FieldSpec]`（`window_config.py:95-130`）— 标量字段单一登记表：dataclass 槽位 ↔ 控件名 ↔ 解析类型（'float'|'int'|'temp'）↔ 必填集合。新增标量字段的规定入口。特殊行（`special=True`）：`fluid_B.u_mps` 空白时继承 `fluid_A.u_mps`（`window_config.py:466-470`）；`Lz_m` 控件缺失时为 None（2D 标志）。
- 子读取器：`_read_partial_bc(window, side) -> PartialBCConfig`（`window_config.py:273`；side='B' 无 combo 时默认 `dir=3` 即 -y；3D z-partial 四值原子式全有或全无，`window_config.py:310-328`）；`_read_zone_input`（`window_config.py:332`，chk_zones 勾选时经 `ui.zone_table.build_zone_config` 预解析 ZoneConfig，使 Pipeline 层不触 Qt 表格）；`_read_feature_flags`（`window_config.py:382`，`variable_rho_cp` 控件缺失时默认 True）；`_read_extrap_policy`（`window_config.py:399`）。
- 温度统一经 `_temp_in_K`（`window_config.py:254`）回调窗口的 `_temp_to_K`，保证 cfg 恒为 Kelvin。
- TPMS 类型白名单：非 'Diamond'/'Gyroid' 一律回落 'Gyroid'（`window_config.py:433-435`）。

### 流体输入与遗留 BC dict（FluidInputMixin）

- `_auto_fill_fluid(self, fluid)`（`sjtu_tpmshx/ui/mixins/fluid_input.py:41`）— 先 `compute_tpms()`，再调 `solvers.tpms_calc.compute`（`fluid_input.py:57-62`）取 Re/Nu/K_ff/ρ/μ，经 `domain.validator.compute_volumetric_htc` 把面 HTC 转体积 HTC（`fluid_input.py:68-69`），结果存窗口属性 `_mu_A/_h_vA/_K_ffA/_rho_A`（`fluid_input.py:87`）并刷新只读标签。调用方：`auto_fill_fluid_a/b`（`fluid_input.py:101-103`，按钮接线在 builders_fluids）。
- `_temp_to_K(self, le) -> float`（`fluid_input.py:155`）— 温度字段读取的唯一正道（K/°C 开关 `self._temp_unit` 感知）；`_set_temp_K`（`fluid_input.py:166`）为写侧对偶。
- `_fluid_config(self, which) -> dict`（`fluid_input.py:350`）— 遗留 per-side BC dict（键 `dir/in_ctr/in_w/out_ctr/out_w` + 可选 z-partial）。现存调用方：`_preflight_grid`（`main.py:810`）与 polygon 路径；Pipeline 路径已改用 `_read_partial_bc`。
- `_update_tout(self, t_idx)`（`fluid_input.py:267`）— 依流向对 `T_fA/T_fB` 场边界做 `np.mean` 得出口温度（UI 层内的数值后处理）。

### 会话/preset（SessionPresetsMixin）

- `_save_session() -> bool` / `_restore_session()`（`sjtu_tpmshx/ui/mixins/session_presets.py:316` / `383`）— payload 结构：`temp_unit` + `line_edits`（文本原样）+ `combos`（索引）+ `checks` + `ui_state` + base64 窗口几何；IO 委托 `SessionManager`。恢复策略有意不完整：fluid/dir 四个 combo 跳过恢复（固定 Shanghai 拓扑，`session_presets.py:428-437`）；Nx/Ny/Nz 无条件重置为 '20' 且置 `_user_edited_grid=True`（`session_presets.py:507-514`）。
- 允许名单：`_SESSION_LINE_EDITS`（33 项，`session_presets.py:231-246`）、`_SESSION_COMBOS`（7 项，`session_presets.py:247-251`）、`_SESSION_CHECKS`（`('chk_zones','chk_wall_refine_3d','chk_var_rhocp')`，`session_presets.py:252`）— preset 应用时过滤任意属性寻址（`session_presets.py:130-132`）。
- `_apply_user_preset(preset)`（`session_presets.py:107`）— 先 `_invalidate_results_for_preset_load()`（清空全部结果缓存与页签，`session_presets.py:59-105`）；fluid combo 的 `setCurrentIndex` 包 `blockSignals` 防止默认值覆写 preset 显式值（`session_presets.py:153-156`）。
- 工作区：`_WORKSPACES = ('A','B','C')`（`session_presets.py:254`），`_switch_workspace`（`session_presets.py:256`）。

### 结果桥（ResultBridgeMixin）

- `_compute_results`（dict，空 dict 视同清空）、`_result_3d`、`_has_results_2d/_has_results_3d/_has_results`（bool；**setter 写 True 是 no-op，写 False 会清空对应缓存结果**——历史踩坑点，`sjtu_tpmshx/ui/mixins/result_bridge.py:48-63`）、`_drawn_tabs`（getter 返回副本，就地 `.add` 不回写，须整体赋值或 `cache.mark_drawn`，`result_bridge.py:75-88`）。

### 其他

- `Main_Menu.compute_tpms(self) -> bool`（`sjtu_tpmshx/main.py:556`）— 纯几何计算（ε、A₀、D_h、K_ss）+ 依 D_h 的网格建议（3D 走 `domain.validator.suggest_grid_3d`，2D 走 `adaptive_grid`；`_user_edited_grid=True` 时不覆写，`main.py:599-618`）。调用方：`_auto_fill_fluid`、TPMS 面板按钮。
- `IOActionsMixin.save_config / load_config`（`sjtu_tpmshx/ui/mixins/io_actions.py:133/182`）— 独立的扁平 JSON 模式（键 "L"/"u_A"/"pipeA_in_ctr"…），与 ComputeConfig 及 session payload 均**不是**同一模式，移植时勿混淆。
- `ShortcutsMixin._setup_shortcuts`（`sjtu_tpmshx/ui/mixins/shortcuts.py:26`）— 全部快捷键经 `_track_shortcut` 注册进 SignalRouter 以便 closeEvent 批量断开。

## 关键配置项与开关

| 项 | 默认值 | 定义处 |
| --- | --- | --- |
| `Main_Menu.__version__` | "1.5.0" | `sjtu_tpmshx/main.py:44` |
| `_temp_unit` | 'K' | `sjtu_tpmshx/main.py:160` |
| `_active_workspace` | 'A'（marker 缺失/损坏时） | `sjtu_tpmshx/main.py:217` |
| `_MAX_RECENT_RUNS` | 5 | `sjtu_tpmshx/main.py:1404` |
| `_FLUID_DEFAULTS`（Air/Water/sCO₂ 的 u/T/P 默认） | Air u=20, Water u=0.15, sCO₂ P=8 MPa | `sjtu_tpmshx/main.py:641-645` |
| Shanghai 预设字段值（工况 8） | L=0.182, H=Lz=0.042, Lcell=7.0 mm, t=0.6 mm, Nx=Ny=Nz=20 等 | `sjtu_tpmshx/main.py:368-407` |
| `_BUILTIN_PRESETS` | 3 个 Shanghai 变体 | `sjtu_tpmshx/ui/mixins/session_presets.py:15-19` |
| 3D 硬墙钟预算 `_hard_timeout_s` | 1800 s | `sjtu_tpmshx/ui/mixins/run_controller.py:312` |
| 3D 大网格确认阈值 | est_cells > 100_000 | `sjtu_tpmshx/ui/mixins/run_controller.py:207` |
| wall-refine 每轴 pad | +16（仅勾选 `chk_wall_refine_3d` 时计入估算） | `sjtu_tpmshx/ui/mixins/run_controller.py:179-181` |
| `CONFIG_FIELDS` 各字段 UI 兜底默认 | L=0.182, H=0.042, Nx=30, Ny=60, u_A=5.0, T=300 K, Lcell=7.0, t=0.6, k_s=16.0, Nz=1, P_in=101325 | `sjtu_tpmshx/ui/window_config.py:95-130` |
| `variable_rho_cp`（可压缩，硬不变量） | True（`chk_var_rhocp` 缺失时保持 True） | `sjtu_tpmshx/ui/window_config.py:387-391` |
| 外推允许 `chk_allow_extrap` | False（控件缺失时） | `sjtu_tpmshx/ui/window_config.py:399-404` |
| `T_s_init` 合法窗口 | [150, 2000] K，越界回 None | `sjtu_tpmshx/ui/window_config.py:451-453` |
| 环境变量 `TPMSHX_PREINIT_3D` | '0'（=1 时启动 500 ms 后预热 PyVista） | `sjtu_tpmshx/main.py:268` |
| 环境变量 `TPMSHX_DISABLE_3D_PANEL` / `QT_QPA_PLATFORM=offscreen` | 未设（设置后跳过 3D 面板，置 `_vis3d_import_error`） | `sjtu_tpmshx/ui/builders_canvas.py:534-538` |
| 环境变量 `TPMSHX_EAGER_3D_SLICES` | '0'（=1 时 3D 完成即预计算 2D 切片） | `sjtu_tpmshx/ui/plot_3d_results.py:177` |
| 全量 `TPMSHX_*` 旋钮清单（权威索引） | — | `sjtu_tpmshx/domain/compute_config.py:45-102` |
| 点文件：`.theme` / `.density` / `.accent` / `.first_run_done` / `.session_timeline.jsonl` | 启动读取（均按 `main.py` 包根解析）于 `main.py:1559-1591`；写入于 `appearance.py:29-33/77-82/138-143`（`.theme/.density/.accent` 各自用 `os.path.dirname(os.path.abspath(__file__))`，`__file__` 是 `appearance.py` 自身，落在 `ui/mixins/` 而非 `main.py` 包根——与启动读取路径不一致，见下方「已知不足」）、`main.py:1032-1036`（`.first_run_done`，与 main.py 同目录，读写一致）、`run_history.py:38`（`.session_timeline.jsonl`，锚定 `parents[2]` 到包根，读写一致） | 见左 |

## 边界·假设·适用范围

- **单位约定**：内部物理恒为 K / Pa / m；TPMS 单胞 `le_Lcell` 与壁厚 `le_t` 为 **mm**（`window_config.py:113-116` 字段名 `L_cell_mm`/`t_wall_mm`；帮助文本 `main.py:1203-1209`）。速度为孔隙内 interstitial 速度（帮助文本 `main.py:1215-1217`）。温度显示可 K/°C 切换，但所有计算路径必须经 `_temp_to_K` 读取（`main.py:156-160` 注释、`fluid_input.py:155`）。
- **方向编码**：`_DIR_MAP = {0:'+x',1:'-x',2:'+y',3:'-y',4:'+z',5:'-z'}`（`sjtu_tpmshx/main.py:630`）；combo 索引即方向整数（`fluid_input.py:336-338`）。
- **流体类型能力矩阵（UI 强制）**：Fluid A 仅 Air 与 sCO₂，Water-A 条目被禁用（缺不可压 SIMPLE A 路径，`sjtu_tpmshx/ui/builders_fluids.py:148-155`）；Fluid B 支持 Air/Water/sCO₂，默认 Water（`builders_fluids.py:179`）。sCO₂ 仅 Diamond L=7/t=0.6 标定，其他晶格在求解器层抛 `NotImplementedError`（tooltip 声明，`builders_fluids.py:190-198`；求解器侧行为本章未验证）。
- **数值限制（UI 预检强制）**：3D 要求 Nz≥2（`run_controller.py:195-203`）；u > `VV_VELOCITY_LIMIT_MS` 只提示不阻断（V&V 域外，`run_controller.py:155-163`）；t=0.6 mm 是 ConstDF-v1 训练窗 [0.3,0.5] 之外的已知硬外推（帮助文本 `main.py:1206-1209`）。
- **2D 计算的前置态**：2D 入口硬性要求 `_K_ffA/_K_ffB` 非 None（即用户点过 Auto-fill，`run_controller.py:76-81`）。注意这只是门槛检查：Pipeline2D 从 cfg 自行重算闭包系数，`write_result` 再把重算值回写窗口属性（`run_controller.py:466-471` 注释）。
- **preset/session 的单位陷阱**：预设温度按 Kelvin 书写，写入时按当前显示单位换算（`main.py:408-424`）；session 恢复时若保存于 °C，先原样恢复再 +273.15 并强制切回 K（`session_presets.py:404-427`）。
- **无 headless 求解入口**：本层是纯 GUI；服务器批处理应绕过 `Main_Menu`，直接构造 `ComputeConfig`（`config_from_window` 接受非 Qt stub 对象，但更直接的是走 `domain.compute_config` + pipelines——另章）。

## 可扩展接口

- **Mixin 组装点**：新增行为切片 = 新建 `ui/mixins/*.py` + 在 `mixins/__init__.py` 导出 + 插入 `Main_Menu` 基类列表（`main.py:117-121`）。约束：方法只经 `self` 依赖窗口，禁止 import 时依赖 `main`。
- **新增标量配置字段**：在 `CONFIG_FIELDS` 登记一行 `FieldSpec` 即同时接好读取与 strict 校验（`window_config.py:69-130`）；跨字段/组合语义用 `special=True` 并在 `config_from_window` 显式处理。
- **控件构建 DI**：`FieldFactory` + `set_default_factory`（`main.py:189-190`）——builders 经工厂取主题化控件，替换工厂即可换样式来源。
- **信号治理**：`SignalRouter.connect/adopt`（`main.py:184`、`ui_builder.py:175-185`）登记所有连接，closeEvent 批量断开；新连接应走此路。
- **UI 钩子透传给求解器**：Pipeline 构造参数 `ui_hooks={'live_residuals':…, 'iter_label_cb':…}`（2D，`run_controller.py:107-111`）/ `{'iter_cb':…}`（3D，`run_controller.py:290-291`）；`progress_cb` 写 `_compute_progress` 供轮询计时器渲染。
- **环境变量**：本层直接消费 `TPMSHX_PREINIT_3D`（`main.py:268`）、`TPMSHX_DISABLE_3D_PANEL`（`builders_canvas.py:537`）、`TPMSHX_EAGER_3D_SLICES`（`plot_3d_results.py:177`）、`QT_QPA_PLATFORM`（offscreen 探测，`builders_canvas.py:535`、`main.py:1014`）；求解器侧旋钮总表在 `domain/compute_config.py:45-102`。
- **i18n 脚手架**：入口块加载 `i18n/sjtu_tpmshx_<locale>.qm`（若存在，`main.py:1541-1554`）；当前代码库为英/中混排硬编码字符串，未实际提取 .ts（注释自述，`main.py:1537-1540`，未验证是否有任何 .qm 产物）。
- **拖放加载**：整窗接受 `.json` preset 拖放（`main.py:291`、`305-343`），仅应用第一个文件，识别 `line_edits` 或 `presets` 两种载荷形状。

## 已知不足与 TODO

代码内无 `TODO`/`FIXME` 字面标记（ui/ 全目录 grep 仅命中 tooltip 文本中的 `NotImplementedError` 字样，`builders_fluids.py:137/192`）。以下为代码注释自证的结构性欠账：

- **双结果存储的迁移只做了一半**：`ResultCache` 为新代码而设，遗留属性（`_compute_results/_recent_runs/_has_results_*`）「将在后续阶段增量迁移」（构造注释，`main.py:207-210`）；`_drawn_tabs` getter 的就地 `.add` 不回写陷阱仍在（`result_bridge.py:75-84`）。
- **`_has_results_3d` setter 会销毁结果**：写 False 清空缓存的 3D `ComputeResult`；U1 修复后页签就绪改用独立旗标 `_3d_view_ready`，但桥 setter 的破坏性语义保留（`result_bridge.py:57-63`、`run_controller.py:605-628` 长注释）。改造此层时极易复发「渲染失败即丢结果」回归。
- **SolverConfig 多数旋钮 UI 未暴露**：「remaining knobs keep dataclass defaults; UI does not surface them yet (audit deferred)」（`window_config.py:456-458`）。
- **主题/密度/强调色切换需重启进程**（`os.execv`）：活体重建被明确放弃（QMatplotlib、PyVista GL、undo 栈持有构建期快照，`appearance.py:123-128`）。
- **温度滑块为遗留死代码路径**：`update_graph_from_slider` 中 `t = 0  # steady-state only; slider is legacy`（`main.py:1467-1473`）。
- **ETA 预测已删除**（两处：按钮 ETA `run_controller.py:838-839`，3D `_tick_3d` 注释 `run_controller.py:326-333`）——线性 cell-scaling 模型对高 u/密网格严重低估，勿复装。
- **2D 头部残差 sparkline 只画 Fluid A**（`ui_builder.py:106-108` 注释）。
- **save_config/load_config 的 JSON 模式陈旧**：不含 3D z-partial、zones、flags（对比 `_SESSION_LINE_EDITS` 全集；`io_actions.py:139-175` 键表），注释中 `#"transA": removed` 为已删分支残迹（`io_actions.py:169/174`）。
- **`_maybe_show_onboarding` 的 offscreen 守卫**：无显示环境下跳过模态但仍写 `.first_run_done`（CI 挂死修复，`main.py:1010-1016`）。

## 服务器移植注意

- **本层整体依赖 PySide6 GUI**，Linux 服务器无显示时需 `QT_QPA_PLATFORM=offscreen`；代码已有两处 offscreen 感知：跳过 3D PyVista 面板（`builders_canvas.py:535-538`）与跳过首启模态（`main.py:1014`）。matplotlib 后端在 import 早期硬设 `matplotlib.use("QtAgg")`（`main.py:18`）——headless 复用任何会 import `main` 的代码都会拉起 Qt 依赖。
- **不要经 UI 层做批量计算**：数值路径的纯数据入口是 `ComputeConfig`（`domain/compute_config.py`）+ `Pipeline2D/3D`（`controllers/compute_pipeline.py`）；`ui/window_config.py` 刻意无 Qt import，可用 stub 对象离线构造 cfg（`window_config.py:8-9`），但字段兜底默认（如 Nx=30/Ny=60）与 UI 预设值（Nx=Ny=Nz=20）不一致（`window_config.py:100-103` vs `main.py:394-396`），脚本化时必须显式给全字段。
- **双 import 模式**：`main.py` 启动时把包目录与其父目录都插入 `sys.path`（`main.py:9-14`），mixin 对 `main` 的惰性解析也依次尝试 `"main"` 与 `"sjtu_tpmshx.main"` 两个模块名（`io_actions.py:24`、`run_history.py:47`）。服务器上固定用 `python -m sjtu_tpmshx.main` 一种方式，避免同一模块被双载。
- **包目录必须可写**：`.first_run_done`（`main.py:1032-1036`）与 `.session_timeline.jsonl`（`run_history.py:37-38`，`parents[2]` 锚定包根）确实写在 `main.py` 包根旁，与启动读取路径（`main.py:1559-1591`）一致；但 `.theme/.density/.accent`（`appearance.py:29-33/77-82/138-143`）用的是 `os.path.dirname(os.path.abspath(__file__))`，`__file__` 指 `appearance.py` 自身，实际写入 `ui/mixins/` 而非包根——与 `main.py:1559-1591` 的读取路径不一致（代码层面的路径缺陷，非本文档笔误；效果是主题/密度/强调色的 execv 重启后大概率读不到刚写的值）。会话/preset 文件经 `SessionManager`（`controllers/session_manager.py:50`）不受影响。只读安装（系统 site-packages）会静默丢这些持久化（多为 best-effort try/except）。
- **进程自重启用 `os.execv(sys.executable, [sys.executable] + sys.argv)`**（`appearance.py:62/112/183`）：Linux 语义正常，但注意它替换进程映像，任何包装脚本/监控需容忍。
- **线程与并行**：求解在 `ComputeOrchestrator` 的线程池（closeEvent `waitForDone(3000)`，`main.py:953-955`）；几何/surrogate 预热在 daemon `threading.Thread`（`main.py:545-548`）；大量 `QTimer` 轮询（进度 200 ms、按钮 500 ms、残差 120 ms）要求 Qt 事件循环存活。取消是协作式的——JIT 内层循环不可中断，只在 epoch 边界检查 token（`run_controller.py:820-823` 注释）。
- **编码**：文件 IO 显式 `encoding='utf-8'`（如 `main.py:319`、`session_presets` 经 SessionManager）；UI 字符串含大量中文（按钮「取消 · 0.0s」、诊断摘要等，`run_controller.py:840/1108-1126`），Linux 终端/日志管道需 UTF-8 locale。字体链首选 Fira Sans/Inter，全部缺失时退回系统默认并打印告警（`main.py:1502-1511`）——服务器容器常无这些字体，仅影响观感。
- **PyVista/VTK**：3D 面板懒初始化（`main.py:1414`）且渲染失败不丢数值结果（`run_controller.py:664-675`）；无 GPU/GL 的服务器直接设 `TPMSHX_DISABLE_3D_PANEL=1` 即可保留全部求解与导出能力。
- **路径处理**：本层用 `os.path.join`/`pathlib`，未发现硬编码盘符或反斜杠（`run_history.py:37` 用 `Path(__file__).resolve().parents[2]` 锚定包根）；「未验证」：`ui/` 其余非本章文件是否全部如此。
