# controllers
生成日期 2026-07-10，基于 commit f33d30e 附近的 master；
**2026-07-20 收编 upgrade/loop 分支漂移**（见文末收编节；正文失准处标 ⟨07-20 更新⟩）

## 定位与功能

`sjtu_tpmshx/controllers/` 是 UI（PySide6 主窗口 `main.py` / `ui/`）与计算流水线（`pipelines/stages_2d.py` / `stages_3d.py`）之间的控制器层。它源自 2026-05-06 的 `main.py` god-class 重构（`sjtu_tpmshx/controllers/__init__.py:1-9`），承担四类横切职责：

1. **求解线程生命周期**（`ComputeOrchestrator`）：以 Qt 原生 QThreadPool + QRunnable + Signal 模式在后台线程运行求解器，提供重入保护、协作式取消、进度/完成/错误/取消信号、per-mode ETA 历史与 stdout/stderr 日志捕获（`sjtu_tpmshx/controllers/compute_orchestrator.py:1-18`）。
2. **计算流水线契约**（`ComputePipeline` ABC 及 `Pipeline2D` / `Pipeline3D`）：把 2D/3D 计算统一为「`ComputeConfig` 入 → `ComputeResult` 出」的三阶段纯适配器（build_fields → run_solvers → finalize），不读任何 Qt 控件、不写任何 Qt 属性（`sjtu_tpmshx/controllers/compute_pipeline.py:1-44`）。
3. **结果与状态聚合**（`ResultCache`）：集中存放 2d / 3d / poly 三种模式的结果 payload、dirty 位、已绘制 tab 集合与最近运行环形队列（`sjtu_tpmshx/controllers/result_cache.py:1-31`）。
4. **持久化与信号登记**（`SessionManager` / `SignalRouter`）：会话/预设 JSON 的原子读写与 schema 版本戳；Qt signal/slot 连接的集中登记与批量断开（`sjtu_tpmshx/controllers/session_manager.py:1-35`，`sjtu_tpmshx/controllers/signal_router.py:1-37`）。

数据流（已在代码中核实）：`ui/mixins/run_controller.py` 在主线程调用 `ui.window_config.config_from_window` 一次性读取全部 Qt 控件生成 `ComputeConfig`（`sjtu_tpmshx/ui/mixins/run_controller.py:88-94`, `260-266`），然后把闭包 worker 交给 `ComputeOrchestrator.start()`；worker 在后台线程内构造 `Pipeline2D` / `Pipeline3D` 并 `run()`（`sjtu_tpmshx/ui/mixins/run_controller.py:96-123`, `281-300`）；流水线内部转调 `pipelines/stages_2d.py` / `stages_3d.py` 的 `_*_cfg` 阶段函数（`sjtu_tpmshx/controllers/compute_pipeline.py:171-193`, `212-232`）。

历史注意：契约类型已于 2026-07-02 迁出本包——`ComputeConfig` / `ComputeResult` 在 `domain/`，window 采集适配器在 `ui/window_config.py`，ThemeManager 在 `ui/theme_manager.py`；本包只保留编排/状态控制器（`sjtu_tpmshx/controllers/__init__.py:11-14`）。

## 文件一览

| 文件 | 职责（一行） |
|---|---|
| `sjtu_tpmshx/controllers/__init__.py` | 包出口 ⟨07-20 更新（P1.8）：四类改 **PEP 562 惰性 `__getattr__`** 导出——`import controllers.compute_pipeline` 不再拉起任何 Qt（cli/headless 场景零 Qt 导入的关键一环）；访问 `controllers.ComputeOrchestrator` 等属性时才真正 import⟩。`compute_pipeline` 仍不在 `__all__`，调用方直接 `from controllers.compute_pipeline import …`。 |
| `sjtu_tpmshx/controllers/compute_orchestrator.py` | 求解线程生命周期 QObject：QThreadPool 派发、CancelToken、started/progress/finished/error/cancelled 信号、stdout+stderr tee 捕获（上限 500 KB）、per-mode ETA 历史。 |
| `sjtu_tpmshx/controllers/compute_pipeline.py` | 三阶段流水线 ABC + `Pipeline2D` / `Pipeline3D` 具体实现 + `pipeline_for` 维度分发工厂；本包内唯一 Qt-free 的文件（import 仅 abc/typing/domain，`compute_pipeline.py:45-51`）。 |
| `sjtu_tpmshx/controllers/result_cache.py` | 按模式（2d/3d/poly）存结果 payload + dirty 位 + drawn-tabs 集合 + 最近运行 ring（默认 5 条），带 `results_changed` / `recent_pushed` 信号。 |
| `sjtu_tpmshx/controllers/session_manager.py` | 会话（.last_session*.json）、用户预设（.user_presets.json）、活动 workspace 标记（.workspace）的磁盘持久化；原子写 + 损坏文件隔离 + schema_version=1 版本戳。 |
| `sjtu_tpmshx/controllers/signal_router.py` | Qt signal/slot 连接的中央登记表：`connect` / `adopt` 登记、`disconnect_all` 批量断开、weakref 保护已析构 sender。 |

## 公开接口

### CancelToken（`sjtu_tpmshx/controllers/compute_orchestrator.py:37-62`）
- 基于 `threading.Event` 的协作式取消旗标。`is_set()`（`compute_orchestrator.py:46`）、`cancel()`（`compute_orchestrator.py:58`）、`reset()`（`compute_orchestrator.py:61`）。
- **`cancelled` property**（`compute_orchestrator.py:49-56`）：流水线层以 `getattr(token, 'cancelled', False)` 探测取消（见 `compute_pipeline._check_cancel`）；此 property 缺失时 cfg 路径上取消曾是静默 no-op（B2 2.1a 修复，注释自述，行为在 `compute_pipeline.py:102-106` 可核实）。

### ComputeOrchestrator（`sjtu_tpmshx/controllers/compute_orchestrator.py:151`）
- 信号（类级声明，`compute_orchestrator.py:182-186`）：`started(str mode)`、`progress(int)`、`finished(dict)`、`error(str message, str log)`、`cancelled(str log)`。worker 线程 emit 时由 Qt 自动 marshal 到 GUI 线程（注释断言，`compute_orchestrator.py:283-288`）。
- `__init__(parent=None, max_threads=1)`（`compute_orchestrator.py:190-210`）：私有 QThreadPool，`setMaxThreadCount(1)` —— 同时只跑一个求解。
- `start(mode, worker_fn, cfg) -> bool`（`compute_orchestrator.py:243-271`）：mode 必须 ∈ {'2d','3d','poly'}（否则 `ValueError`，`compute_orchestrator.py:258-259`）；已在运行则返回 False（重入拒绝，`compute_orchestrator.py:256-257`）。worker_fn 签名 `worker_fn(cfg: dict, cancel_token: CancelToken, progress_cb: Callable[[int], None]) -> dict`（`compute_orchestrator.py:246-249`）。
- `cancel()`（`compute_orchestrator.py:273-281`）：置位 token，不强杀线程（注释称强杀会破坏 numba 状态）。
- 自省：`is_running()` / `current_mode()` / `last_result()` / `last_error()` / `last_log()` / `last_elapsed()`（`compute_orchestrator.py:214-230`）；`eta_seconds(mode)` 返回该模式最近 ≤10 次墙钟耗时（deque maxlen=10，`compute_orchestrator.py:206-210`）的中位数（`compute_orchestrator.py:232-239`）。
- `ComputeOrchestrator.CancelledError` = 模块级 `_CancelledError` 的 re-export（`compute_orchestrator.py:140-145`, `188`）。worker 抛该异常 → emit `cancelled`；抛其他异常 → emit `error`（`_ComputeRunnable.run`，`compute_orchestrator.py:129-137`）。
- 日志捕获：`_ComputeRunnable.run` 用 `_Tee` 同时 redirect stdout **和 stderr**（stderr 承载 `warnings.warn` 降级通道，2026-07-07 W1b 修复，`compute_orchestrator.py:112-123`）到终端 + StringIO，日志截断至 500 KB（`compute_orchestrator.py:127`）。
- 调用方：`main.py` 构造并接线五个信号（`sjtu_tpmshx/main.py:193-203`）；`ui/mixins/run_controller.py:123`（2D）与 `:300`（3D）调用 `self.compute.start(...)`；单元测试 `sjtu_tpmshx/tests/test_compute_orchestrator.py:32`。

### ComputePipeline ABC（`sjtu_tpmshx/controllers/compute_pipeline.py:64`）
- `__init__(cfg: ComputeConfig, progress_cb=None, cancel_token=None, ui_hooks=None)`（`compute_pipeline.py:90-100`）。`cancel_token` 是鸭子类型——任何带 `cancelled` 属性的对象（`compute_pipeline.py:76-79`, `102-106`）。
- `run() -> ComputeResult`（`compute_pipeline.py:108-126`）：先重置两个一次性告警注册表（`solvers.nu_correlations.reset_extrap_warn_registry` + `df_surrogate.predict.reset_choke_warn_registry`，`compute_pipeline.py:113-116`），随后 3 阶段依次执行，阶段间检查取消，progress_cb 在 20/90/100% 触发（`compute_pipeline.py:119`, `122`, `125`）。取消抛本模块的 `CancelledError`（`compute_pipeline.py:57-58`，注意与 orchestrator 的 `_CancelledError` 是**不同类**，run_controller 中显式做了转换，`sjtu_tpmshx/ui/mixins/run_controller.py:112-118`）。
- 抽象方法：`build_fields()` / `run_solvers(fields)` / `finalize(raw, fields)`（`compute_pipeline.py:130-141`）。

### Pipeline2D（`sjtu_tpmshx/controllers/compute_pipeline.py:147`）
- 三阶段委托 `pipelines.stages_2d` 的 `_parse_inputs_cfg` / `_build_fields_cfg` / `_run_solvers_cfg` / `_finalize_cfg`；import 刻意放在方法内（懒加载，避免 GUI 冷启动时拉起 numba JIT，`compute_pipeline.py:168-171`）。`_parse_inputs_cfg` 的产物缓存在 `self._parsed` 供后两阶段使用（`compute_pipeline.py:163-165`, `174`）。
- ui_hooks 消费：`live_residuals`（传给 `_build_fields_cfg`，`compute_pipeline.py:175-177`）、整个 `ui_hooks` dict 传给 `_run_solvers_cfg`（`compute_pipeline.py:183-186`）。
- 调用方：GUI 2D worker（`sjtu_tpmshx/ui/mixins/run_controller.py:100`）、金标脚本 `sjtu_tpmshx/runs/_out/_golden_2d.py:28`、测试（`sjtu_tpmshx/tests/test_pipeline_2d_smoke.py:27`、`test_asym_porosity_2d.py:117`、`test_envelope_integration_2d.py:22`、`test_invariant_negative_guards.py:79`、`test_solver_knobs_r3.py:112`）、外部项目脚本 `projects/703-sCO2-D76/validate_sco2_703_coupled.py:96`。

### Pipeline3D（`sjtu_tpmshx/controllers/compute_pipeline.py:196`）
- 委托 `pipelines.stages_3d` 的 `_parse_inputs_3d_cfg` / `_build_fields_3d_cfg` / `_run_solvers_3d_cfg` / `_finalize_3d_cfg`（`compute_pipeline.py:212-232`）。ui_hooks 消费：仅 `iter_cb`（`compute_pipeline.py:225`）。
- 调用方：GUI 3D worker（`sjtu_tpmshx/ui/mixins/run_controller.py:285`）、上海 3D 基线门脚本的 production-path runner（`sjtu_tpmshx/validation/cases/validate_shanghai_3d_real.py:477`, `515`）、`sjtu_tpmshx/tests/test_pipeline_3d_e2e.py:25`。

### pipeline_for（`sjtu_tpmshx/controllers/compute_pipeline.py:235-247`）
- 工厂：`cfg.is_3d` 为真返回 `Pipeline3D`，否则 `Pipeline2D`。`is_3d` 定义为 `int(self.solver.Nz) >= 2`（`sjtu_tpmshx/domain/compute_config.py:374-377`）。调用方 ⟨07-20 更新⟩：**`sjtu_tpmshx/cli.py`（tpmshx-run）是其正式生产消费方**（P1.8 起，headless 入口按 cfg 维度分发），此外是测试（`test_compute_pipeline.py:176-185`、`test_pipeline_2d_smoke.py:143-147`、`test_pipeline_ui_hooks.py:39`）；GUI 路径仍不用它（run_controller 直接按按钮分支实例化具体类）。

### ResultCache（`sjtu_tpmshx/controllers/result_cache.py:41`）
- `MODES = ('2d', '3d', 'poly')`（`result_cache.py:48`）；信号 `results_changed(str)` / `recent_pushed(dict)`（`result_cache.py:51-52`）。
- `set_result(mode, payload)`：payload 非 None 时置 dirty 并**清空全部 drawn-tabs**（`result_cache.py:76-90`）；`get_result` / `clear` / `has_results` / `has_any_results` / `is_dirty` / `mark_clean`（`result_cache.py:92-125`）；tab 追踪 `mark_drawn` / `is_drawn` / `get_drawn_tabs` / `replace_drawn_tabs` / `clear_drawn`（`result_cache.py:129-145`）；最近运行 `push_recent`（浅拷贝入 ring，`result_cache.py:149-157`）/ `get_recent` / `replace_recent` / `clear_recent`（`result_cache.py:159-168`）。ring 容量 `max_recent=5`（`result_cache.py:54-55`）。
- 调用方：`main.py:212` 实例化为 `self.cache`；旧属性名（`_compute_results` / `_result_3d` / `_has_results*` / `_drawn_tabs`）经 `sjtu_tpmshx/ui/mixins/result_bridge.py:1-13` 的 property 桥透明委托到 ResultCache（对照表见 `result_cache.py:6-14`）。注意：对照表中的 `_recent_runs` **未**走该桥——它仍是 `ui/mixins/run_history.py:62-64` 惰性持有的普通 deque，与 ResultCache 的 recent ring 并存（`main.py:207-210` 注释自认 legacy attrs "stay in place"）。

### SessionManager（`sjtu_tpmshx/controllers/session_manager.py:50`）
- 常量：`SCHEMA_VERSION = 1`（`session_manager.py:47`）、`VALID_WORKSPACES = ('A', 'B', 'C')`（`session_manager.py:73`）。信号 `session_loaded(str, dict)` / `session_saved(str)` / `presets_changed()` / `workspace_changed(str)`（`session_manager.py:75-78`）。
- `__init__(base_dir=None, parent=None)`：base_dir 默认 `Path(__file__).resolve().parents[1]` = 包目录 `sjtu_tpmshx/`（`session_manager.py:80-86`）。
- 路径：`session_path(ws)` → workspace A 用遗留名 `.last_session.json`，B/C 用 `.last_session_<ws>.json`（`session_manager.py:94-102`）；`presets_path()` → `.user_presets.json`（`session_manager.py:104-105`）；`workspace_marker_path()` → `.workspace`（`session_manager.py:107-108`）。
- `load_session(ws)`：文件缺失/损坏返回 None；JSON 解析失败时把文件改名隔离为 `<name>.corrupt-<ts>`（`session_manager.py:112-149`）；旧文件缺 `schema_version` 字段则注入 0（`session_manager.py:136`）。
- `save_session(payload, ws)`：加 `schema_version=1` 戳后原子写（写 `.tmp` → flush → fsync（容忍失败）→ `os.replace`，`session_manager.py:151-198`）。
- `load_user_presets() -> list` / `save_user_presets(list) -> bool`（`session_manager.py:202-236`）。
- `get_active_workspace()`：marker 缺失/非法回落 'A'（`session_manager.py:240-249`）；`set_active_workspace(ws)` 亦原子写（`session_manager.py:251-281`）。
- 调用方：`main.py:211` 实例化为 `self.sm`，`main.py:217` 启动时读活动 workspace。

### SignalRouter（`sjtu_tpmshx/controllers/signal_router.py:60`）
- `connect(signal, slot, tag='', sender=None) -> bool`：连接失败（TypeError/RuntimeError）返回 False 不抛（`signal_router.py:80-101`）；sender 以 weakref 持有，供断开时跳过已析构控件（`signal_router.py:96`, `141-146`）。
- `adopt(...)`：登记已连接的对，供增量迁移（`signal_router.py:103-114`）。
- `disconnect_one(tag) -> int` / `disconnect_all() -> int`（幂等，`signal_router.py:118-139`）；`count()` / `tags()` / `clear()`（`signal_router.py:160-170`）。
- 信号 `connection_added(str)` / `connection_removed(str)`（`signal_router.py:71-72`）。
- 调用方：`main.py:184` 实例化为 `self.signals`；`main.py:194-203` 用其接线 orchestrator 的五个信号。注意 docstring 自述（`signal_router.py:22-26`）signal 参数可为 `(sender, signal_name)` 二元组做延迟查找——**代码中未见对二元组形态的任何处理逻辑**（`connect` 直接调用 `signal.connect(slot)`），该说法未验证/疑为文档陈旧。

## 关键配置项与开关

| 配置 | 默认值 | 定义处 | 说明 |
|---|---|---|---|
| `ComputeOrchestrator(max_threads=…)` | 1 | `sjtu_tpmshx/controllers/compute_orchestrator.py:190-196` | 求解线程池并发上限；注释明示重活单跑。 |
| 日志捕获上限 | 500_000 字符 | `sjtu_tpmshx/controllers/compute_orchestrator.py:127` | 三个出口（finished/cancelled/error）均截断。 |
| ETA 历史深度 | deque maxlen=10 / mode | `sjtu_tpmshx/controllers/compute_orchestrator.py:206-210` | 供 `eta_seconds` 取中位数。 |
| 合法 mode 集 | `('2d','3d','poly')` | `compute_orchestrator.py:258`、`result_cache.py:48` | 两处各自硬编码。 |
| progress 刻度 | 20 / 90 / 100 % | `sjtu_tpmshx/controllers/compute_pipeline.py:119,122,125` | ABC `run()` 固定三档；求解器内部更细进度经 ui_hooks/progress_cb 另行上报。 |
| `ResultCache(max_recent=…)` | 5 | `sjtu_tpmshx/controllers/result_cache.py:54-55` | 最近运行 ring 容量。 |
| `SessionManager(base_dir=…)` | 包目录 `sjtu_tpmshx/` | `sjtu_tpmshx/controllers/session_manager.py:84-86` | 会话/预设/marker 文件全部落在包目录内（dot-files）。 |
| `SCHEMA_VERSION` | 1 | `sjtu_tpmshx/controllers/session_manager.py:47` | 会话与预设 payload 的版本戳；v0（无字段）读入时自动注入。 |
| workspace 集合 | `('A','B','C')` | `sjtu_tpmshx/controllers/session_manager.py:73` | 非法值抛 ValueError / 读取回落 'A'。 |
| `ComputeConfig.envelope_mode` | `'raise'` | `sjtu_tpmshx/domain/compute_config.py:366-370` | 非本包定义但经流水线透传；控制可压缩有效域守卫行为（raise/warn/off）。 |

## 边界·假设·适用范围

- **线程模型**：`ComputeOrchestrator` 依赖 Qt 信号跨线程 auto-marshal 把回调送回 GUI 线程（`compute_orchestrator.py:283-288`）；无 Qt 事件循环时信号不会派发到接收方（测试 `tests/test_compute_orchestrator.py` 的具体处理方式未在本文核实——未验证）。
- **取消是协作式的**：worker 只在自设的检查点（epoch 边界 / 三阶段边界）观察 token；`cancel()` 不中断正在运行的 numba kernel（`compute_orchestrator.py:273-281`，`compute_pipeline.py:102-106`）。存在**两个同名异类的 CancelledError**（`compute_orchestrator.py:140` 私有类 vs `compute_pipeline.py:57` 模块类）；orchestrator 只把前者路由到 `cancelled` 信号，后者若外泄会被当作错误弹窗——GUI worker 已显式转换（`ui/mixins/run_controller.py:114-118`, `294-295`），移植者新增调用点时必须同样转换。
- **Pipeline 是纯 cfg→result 适配器**：不读 `window.le_*`、不写 Qt（docstring 断言 `compute_pipeline.py:35-36`；两个实现的方法体确实只触碰 `pipelines.stages_*` 函数与 `self._parsed`）。Qt 控件读取集中在主线程的 `config_from_window`（`sjtu_tpmshx/ui/window_config.py:407-416`）。**例外**：GUI worker 闭包在 worker 线程里调用 `self.write_result(result)` 与 `setattr(self, '_compute_progress', …)`（`ui/mixins/run_controller.py:104,119`, `287,296`）——这是 run_controller 的约定而非 controllers 包的，属主窗口属性写而非 Qt 绘制调用；其线程安全性依赖 write_result 的实现，本文未逐层核实（未验证）。
- **单位/物理**：controllers 层不做任何单位换算与物理计算；单位约定（K/Pa/m、TPMS 单元尺寸 mm）与可压缩不变量属 `domain/` 与 `solvers/` 层，经 `ComputeConfig` 原样透传。
- **`ComputePipeline.run()` 有副作用**：每次运行重置全局一次性告警注册表（`compute_pipeline.py:113-116`），并发多 pipeline 共享该全局状态（生产路径 orchestrator 限并发 1，规避了该问题；脱离 orchestrator 并行跑多个 pipeline 时注册表互踩——推断，未验证）。
- **ResultCache payload schema-free**：存 caller 给的任意 dict（`result_cache.py:149-156`），不做校验；跨模式共享一个 drawn-tabs 集合，任一模式 set_result 会清掉所有 tab 的已绘标记（`result_cache.py:88-89`）。
- **会话文件容错**：损坏 JSON 被隔离改名而非删除（`session_manager.py:141-149`）；所有写盘走 write-tmp-then-`os.replace`，要求 tmp 与目标同文件系统（`session_manager.py:151-172`）。

## 可扩展接口

- **`ui_hooks` dict**（`sjtu_tpmshx/controllers/compute_pipeline.py:96-100`）：约定键 `'live_residuals'`（2D 残差 sparkline 缓冲）、`'iter_label_cb'`（2D 外迭代标签回调）、`'iter_cb'`（3D 外迭代回调，签名 `(k, n)`，见 `ui/mixins/run_controller.py:290-291`）。schema 不强制，透传给 stages 层。
- **`cancel_token` 鸭子类型**：任何带布尔 `cancelled` 属性的对象皆可（`compute_pipeline.py:76-79`）；无需依赖 `CancelToken` 类。
- **`worker_fn` 回调协议**（`compute_orchestrator.py:246-251`）：orchestrator 对 worker 内容零假设，任何 `(cfg, cancel_token, progress_cb) -> dict` 可插入，poly 模式即预留通道（mode 合法集含 `'poly'` 但 GUI 目前只用 2d/3d——`run_controller.py:123,300`）。
- **`SessionManager(base_dir=…)`**：docstring 明示未来可指 `~/.sjtu_tpmshx/` 做多 worktree 隔离或 PyInstaller 打包（`session_manager.py:29-33`），测试注入 tmp_path 即走此口。
- **schema 迁移预留分支**：`load_session` 中 `# Future: payload = self._migrate(payload)`（`session_manager.py:137`）。
- **`SignalRouter.adopt`**：为存量裸 `.connect()` 调用点的增量迁移预留（`signal_router.py:103-109`）；docstring 称新代码应优先 `router.connect`（`signal_router.py:34-36`）。
- **`pipeline_for` 工厂**：脚本/适配器不预知维度时的统一入口（`compute_pipeline.py:235-247`）。
- 本包内未发现任何环境变量读取（3D 栈的 env 读取在 `sjtu_tpmshx/pipelines/run_stack_3d.py:92` 附近，不属本包）。

## 已知不足与 TODO

- **C5 悬置**：`Pipeline2D` docstring 明言 stages_2d 的业务逻辑暂留原地、"A future C5 phase will hoist them"（`sjtu_tpmshx/controllers/compute_pipeline.py:152-154`）——即 controllers 与 pipelines 的分层尚未彻底。
- **双 dict 妥协**：legacy 阶段函数消费 `parsed` + `fields` 两个 dict，而 ABC 契约只传一个 `fields`，靠实例属性 `self._parsed` 走私（`compute_pipeline.py:156-161`）；3D 的 `build_fields` 本质是 passthrough（`compute_pipeline.py:199-203`）。
- **legacy 属性桥仍在**：ResultCache 的老属性名经 `ui/mixins/result_bridge.py` property 桥兼容，docstring 称"will migrate incrementally in later phases"（`sjtu_tpmshx/main.py:207-210`，`result_cache.py:16-21`）。
- **SignalRouter 覆盖不全**：docstring 自认 main.py 仍有约 50 处裸 `.connect()` 未经登记（`signal_router.py:3-9`, `34-36`）；且 docstring 宣称的 `(sender, signal_name)` 延迟查找形态在实现中不存在（见上文，疑为文档陈旧）。
- **schema_version 只有戳没有迁移**：v0→v1 无字段变化，`_migrate` 未实现（`session_manager.py:26-28`, `137`）。
- **`_Tee` 广域 except-pass**：刻意为之（except-audit 2026-07-03，`compute_orchestrator.py:90-92`），代价是流写失败静默丢日志行。
- 本包 6 个文件中未发现 `TODO` / `FIXME` / `NotImplementedError` 字面标记（以上条目均来自 docstring 自述的阶段性状态）。

## 服务器移植注意

- **PySide6 是硬依赖，且 headless 流水线也躲不开**：`controllers/__init__.py:15-18` 无条件 import 四个 Qt 类，其中 `compute_orchestrator.py:31`、`result_cache.py:38`、`session_manager.py:44`、`signal_router.py:44` 均顶层 `from PySide6.QtCore import …`。因此即使只 `from controllers.compute_pipeline import Pipeline2D`（本身 Qt-free），Python 仍先执行包 `__init__` 而拉起 PySide6。**Windows Server 上同样必须安装 PySide6**——这条不因目标机也是 Windows 而消失；`QtCore` 的 QObject/Signal 不要求交互式桌面会话，但若同进程后续起 QApplication（本包 `compute_orchestrator.py` 内部即会），仍需 `QT_QPA_PLATFORM=offscreen`。该 env var 是 Qt 自带的跨平台 headless 开关，不是 Linux/X11 专属手法，本仓库已在两侧都验证过同一套机制：CI 在 `ubuntu-latest` 上以 job-level env 设置（`.github/workflows/ci.yml:27`），而 `sjtu_tpmshx/tests/conftest.py:33` 则专门在 **Windows** 开发机上于任何 PySide6 import 之前 `os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')`（`conftest.py:16-19` 注释明言动机：Windows 下无显示时默认 `'windows'` 平台插件会以退出码 9 崩溃）。Windows Server 无人值守跑批（服务/计划任务）时按同一 env var 配置即可，无需也没有 DISPLAY / X11 等价物可配。若要彻底去 Qt，需改 `__init__.py` 为懒 import 或直接以文件路径旁路包 `__init__`。
- **扁平顶层包名**：import 形如 `from domain.compute_config import ComputeConfig`（`compute_pipeline.py:50-51`）、`from pipelines.stages_2d import …`（`compute_pipeline.py:171`）——包以 `controllers` / `domain` / `pipelines` 等顶层名互相引用，运行时要求 `sjtu_tpmshx/` 目录本身在 `sys.path`（外部脚本示例：`projects/703-sCO2-D76/validate_sco2_703_coupled.py:45` 也是这样引用的）。移植时不要改写成 `sjtu_tpmshx.controllers` 风格，或需全库统一改。
- **会话文件写入包目录**：`SessionManager` 默认把 `.last_session*.json` / `.user_presets.json` / `.workspace` 写进 `sjtu_tpmshx/` 包目录（`session_manager.py:84-86`, `94-108`）。服务器上若包安装在只读位置（site-packages、只读挂载）写入会失败（`save_session` 返回 False 而非抛错，`session_manager.py:182-198`），需构造时传 `base_dir` 指向可写目录。
- **原子写依赖 `os.replace` 同文件系统语义**：`session_manager.py:172`；tmp 文件由 `path.with_suffix(path.suffix + '.tmp')` 生成，与目标天然同目录、同卷，`os.replace` 两端语义一致；fsync 失败被容忍（`session_manager.py:166-171`，注释自称"部分虚拟文件系统上不可用"，本就是跨平台兜底，不是专为 Linux 写的）。Windows Server 上真正需要留意的等价场景不是 NFS，而是 `base_dir` 若被指向 SMB 网络映射盘符或 OneDrive/云同步目录——这类路径上 `fsync` 可能不可用、`os.replace` 跨盘时会直接抛 `OSError`（Windows 下"跨卷"比 Linux 更容易触发，因为盘符切换即换设备）；只要部署时 tmp 与目标保持同目录（现状即如此），基本不会踩到（未验证：本文未在真实 SMB/OneDrive 挂载上实测该失败模式）。
- **`sys.__stderr__ = None` 兼容是真实风险，且换到 Windows Server 后依旧成立（不是"迁到别的系统就消失"的 Windows 遗留问题）**：`_Tee` 容忍 `sys.__stderr__` / `sys.__stdout__` 为 `None`（`compute_orchestrator.py:117-118`，注释）——原是为 `pythonw.exe`（无控制台）写的兜底，但 Windows Server 上以 Windows 服务、计划任务或其他无 console 附着的方式启动进程时同样会遇到这两个流为 `None` 或不可写，该兜底继续必要，不能因为服务器还是 Windows 就当作历史包袱删掉。仍需注意：tee 写的是 `sys.__stdout__` / `sys.__stderr__`（解释器启动时绑定的原始流），而非运行期可能被替换的 `sys.stdout` / `sys.stderr`——若服务器部署方案在外层用服务包装/子进程再重定向 `sys.stdout`，`_Tee` 捕获不到那层重定向（未验证：本文未在 Windows 服务/计划任务的无 console 会话中实测 `sys.__stdout__` 的具体取值）。
- **编码——这个坑换到 Windows Server 不会消失，反而要重点提防**：会话/预设读写本身是安全的，`session_manager.py` 的每处文件 I/O 都显式 `encoding='utf-8'`（`session_manager.py:122`, `163`, `208`, `246`, `265`，已逐行核实），不依赖系统区域设置。但风险点在 `compute_orchestrator.py` 的 `_Tee`：它把 worker 产生的原始文本（求解器 `warnings.warn` / stdout 日志，可能含中文）直接 tee 到 `sys.__stdout__` / `sys.__stderr__`（`compute_orchestrator.py:97-109, 119-120`），**没有显式 encoding**。当这两个流不是交互式控制台（例如 Windows Server 上以服务/计划任务方式启动、stdout 被重定向到文件或管道）时，CPython 会退回到 `locale.getpreferredencoding()`；中文区域设置的 Windows Server 该值默认是 `cp936`（GBK）而非 UTF-8。一旦写入触发 `UnicodeEncodeError`，`_Tee.write` 的 `except Exception: pass` 防护（`compute_orchestrator.py:97-102`，本身是刻意为之的 except-audit 设计）会把这个失败**静默吞掉**——不报错，只是这一行日志凭空消失，GUI/solve-log 查看器不会有任何提示。这与"迁移出 Windows 后 GBK 问题自然消失"的方向相反，需要按仓库已知的 GBK 坑（研究台账 / blind-spot audit 记录的"GBK 中文日志毒化 pytest capture"同源问题）持续提防（未验证：本文未在真实中文区域设置的 Windows Server 无 console 会话上复现该编码失败，机制推断自 CPython 非终端场景的 encoding 回退规则与上述 except-pass 设计的组合）。
- **并行**：orchestrator 池并发=1（`compute_orchestrator.py:196`）；服务器批量跑请绕开 orchestrator 直接多进程驱动 `Pipeline2D/3D`（validation 脚本即此模式，`sjtu_tpmshx/validation/cases/validate_shanghai_3d_real.py:477-515`），但注意 `run()` 会重置进程内全局告警注册表（`compute_pipeline.py:113-116`）——多进程各自独立无冲突，同进程多线程并行会互踩。
- **复现性**：golden 门要求 `PYTHONHASHSEED=0`（repo 约定，见 `/check`；非本包代码——未在本包核实），批量脚本移植时保留该环境变量。

## 2026-07 升级分支收编（upgrade/loop，2026-07-20）

- **`__init__.py` 改 PEP 562 惰性导出**（P1.8）：模块级不再 import 四个 Qt-coupled 控制器，
  `__getattr__` 按属性访问惰性解析——`controllers.compute_pipeline` 可在零 Qt 环境导入
  （cli.py 与 headless 测试依赖此性质）。对既有调用方透明（属性访问语义不变）。
- **新消费方 `sjtu_tpmshx/cli.py`**（tpmshx-run，P1.8）：`ComputeConfig.from_json` →
  `pipeline_for(cc)` → `pipe.run()`；`--dry-run` 只做 parse+分发；exit 2 = solved-but-flagged
  （envelope_valid 或 outer_converged 为假）。
- **run_controller.py 呈现区外迁**（P2.5a）：write_result/_finalize_plots/_update_result_summary/
  _diag_summary_text/_show_diag_dialog 五方法逐字节迁至 `ui/mixins/run_results.py`
  （RunResultsMixin，MRO 紧随 RunControllerMixin）。本卷所引 run_controller 行号 ≤350 的
  （数据流/worker/信号接线段）不受影响；>350 的已漂移。orchestrator 侧接口零变化。
- 本卷正文其余断言（CancelToken 鸭子类型、双 CancelledError 转换、_Tee 500KB、ETA deque、
  SessionManager/SignalRouter）经抽查仍准确；signal_router.py 分支内仅 lint 级修饰。
