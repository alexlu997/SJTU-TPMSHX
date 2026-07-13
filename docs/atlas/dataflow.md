# 端到端调用链与架构流
生成日期 2026-07-11，基于 commit f33d30e 附近的 master

> 本册目标读者：将在 **Windows Server 2022** 服务器上移植/改造本库的另一个编码代理。所有断言均以代码为唯一真源，附 `file:line` 溯源（行号对应本 commit 附近的工作树，移植后可能漂移）。无法在代码中直接核实处标注「未验证」。本册不重复其他分册（`docs/atlas/controllers.md`、`pipelines.md`、`solvers-2d.md`、`solvers-3d.md`、`df-surrogate.md`、`validation.md`、`ui-core.md`、`runs.md`）的文件级细节，只画**跨模块的端到端数据流**。

## 定位与功能

本仓库存在 **三条并行、互不调用的计算入口链**，全部最终落到同一套数值核心（`solvers/`）与同一个 D-F 闭包（`df_surrogate/`），但装配路径完全不同。移植/改造时最容易犯的错误，是把其中一条链的行为误当成"求解器的通用行为"。

1. **UI 交互链**（`main.py` → `ui/mixins/run_controller.py` → `controllers/` → `pipelines/`）：唯一驱动 `controllers.compute_pipeline.Pipeline2D` / `Pipeline3D` 的入口，也是唯二被 golden 位相同回归门（`runs/_out/_golden_2d.py` / `_golden_3d.py`）直接复用的路径。
2. **2D/3D 优化器评估链**（`optimization/evaluator.py::evaluate_design`、`core/evaluators.py::evaluate_3d`）：**不经过 `controllers/` 或 `pipelines/`**，直接在评估函数内部构造 `SIMPLESolver` / `SIMPLESolver3D` + 调 `solve_full_domain` / `solve_full_domain_3d`，是 qNEHVI Pareto 生产脚本（`runs/run_production_qnehvi*.py`、`runs/run_3d_qnehvi_fast.py`、`runs/run_port_dim_retest.py`）的唯一路径。这是与 pipelines 链**代码重复但物理等价（未逐行比对，未验证是否 100% 一致）**的第二套装配逻辑。
3. **validation/cases 门禁链**：既有直接调 `SIMPLESolver3D` 的"kernel-direct"跑法（如 `validate_shanghai_3d_real.py::_run_one_case`），又有显式复用 UI 同款 `Pipeline3D`（同文件 `_run_one_case_pipeline`，`--runner pipeline` 参数选择）的"生产路径"跑法——两者是**故意保持不同的物理路径**，用于交叉验证，不能混淆（`validation/cases/validate_shanghai_3d_real.py:467-471`）。

三条链的共同下游是 `solvers/`（SIMPLE 动量 + LTNE 能量外循环耦合）与 `df_surrogate/`（D-F 闭包 K/c_F 注入），但耦合循环的**驱动位置**不同：链 1 用共享的 `solvers/coupling_skeleton.run_outer_coupling` 骨架；链 2（2D 优化器）用评估函数内联的 `for outer_it in range(n_rho_loops)` 循环（`optimization/evaluator.py:557`），未复用 `coupling_skeleton`。

## 文件一览（跨模块，仅列本册追踪路径涉及的文件；单文件职责见对应分册）

| 文件 | 在本流程中的角色 |
|---|---|
| `sjtu_tpmshx/main.py` | UI 主窗口 + 程序入口（`main.py:1523` 附近 `if __name__=='__main__'`） |
| `sjtu_tpmshx/ui/window_config.py` | Qt 控件 → `ComputeConfig` 唯一转换器 |
| `sjtu_tpmshx/ui/mixins/run_controller.py` | UI 计算入口：`run_calculation`（2D）/ `_run_calculation_3d`（3D），worker 闭包构造 `Pipeline2D`/`Pipeline3D` 并驱动 `ComputeOrchestrator` |
| `sjtu_tpmshx/controllers/compute_orchestrator.py` | QThreadPool 后台线程生命周期，emit started/progress/finished/error/cancelled |
| `sjtu_tpmshx/controllers/compute_pipeline.py` | `ComputePipeline` ABC + `Pipeline2D`/`Pipeline3D`：build_fields→run_solvers→finalize 三相驱动 |
| `sjtu_tpmshx/domain/compute_config.py` | `ComputeConfig` 输入契约（dataclass 树） |
| `sjtu_tpmshx/domain/compute_result.py` | `ComputeResult` 输出契约（dataclass） |
| `sjtu_tpmshx/pipelines/stages_2d.py` | 2D 四相 stage 函数 + re-export `solve_2d` 实现 |
| `sjtu_tpmshx/pipelines/solve_2d.py` | 2D 引擎主体 `_run_solvers`：`_step_2d`/`_post_2d` 闭包 + `_compute_Q_richardson` |
| `sjtu_tpmshx/pipelines/stages_3d.py` | 3D 四相 stage 函数 + verbatim re-export `run_stack_3d`/`grid_3d`/`flux_3d` |
| `sjtu_tpmshx/pipelines/run_stack_3d.py` | 3D 主栈 `_run_3d_stack`：`_outer_step_3d`/`_outer_post_3d` 闭包 |
| `sjtu_tpmshx/solvers/coupling_skeleton.py` | 2D/3D 共享外循环骨架 `run_outer_coupling` + `OuterConvergence` |
| `sjtu_tpmshx/solvers/simple_solver.py` / `simple_solver_3d.py` | SIMPLE 动量/连续求解器（2D/3D） |
| `sjtu_tpmshx/solvers/ltne_energy.py` / `ltne_energy_3d.py` | LTNE 三温能量求解器（2D/3D） |
| `sjtu_tpmshx/solvers/envelope.py` | 可压缩有效性包络：`check_compressible_envelope`（预解 choke 检查）+ `gate_solution`（解后 Mach/正压校验） |
| `sjtu_tpmshx/df_surrogate/predict.py` | D-F 闭包推断入口 `predict_K_cF`/`predict_K_cF_vec`，backend 选择（`gamma_df`/`rbf`） |
| `sjtu_tpmshx/optimization/evaluator.py` | 2D 优化器评估函数 `evaluate_design`（独立于 pipelines 的第二套装配） |
| `sjtu_tpmshx/optimization/evaluator_3d.py` / `sjtu_tpmshx/core/evaluators.py` | 3D 优化器评估函数 `evaluate_design_3d`（薄包装）→ `evaluate_3d`（直接建 `SIMPLESolver3D`） |
| `sjtu_tpmshx/optimization/optimizer_qnehvi.py` | qNEHVI BO 循环：调 `evaluator_fn`（默认 `evaluate_design`，可换 `evaluate_design_3d`），落盘 `opt_runs/` |
| `sjtu_tpmshx/runs/run_production_qnehvi*.py` / `run_3d_qnehvi_fast.py` / `run_port_dim_retest.py` | 生产入口脚本：装配 `config` dict → 调 `run_qnehvi` |
| `sjtu_tpmshx/validation/cases/validate_shanghai_3d_real.py` | 门禁脚本：`_run_one_case`（kernel-direct）与 `_run_one_case_pipeline`（`ComputeConfig`→`Pipeline3D`） |
| `sjtu_tpmshx/runs/_out/_golden_2d.py` / `_golden_3d.py` | golden 位相同门：`_golden_2d.py` 调 `Pipeline2D(cfg).run()`；`_golden_3d.py` 调更底层的 `_run_3d_stack(cfg)`（不经 `Pipeline3D`，见下文说明） |

## 公开接口（端到端链路，函数级 file:line）

### 链 1a — 2D UI → Pipeline2D（完整调用链）

1. 用户点击"Compute" → `Main_Menu.run_calculation`（mixin 方法，位于 `sjtu_tpmshx/ui/mixins/run_controller.py`，本文件内入口约 `:70` 起）。
2. 主线程一次性读取全部 Qt 控件：`config_from_window(self, strict=True, force_3d=False)`（`sjtu_tpmshx/ui/mixins/run_controller.py:88-91`，实现在 `sjtu_tpmshx/ui/window_config.py:407-485`，未逐行核实）→ 产出 `ComputeConfig`。
3. 构造 worker 闭包 `_2d_worker(cfg, cancel_token, progress_cb)`（`run_controller.py:96-120`），内部 `Pipeline2D(compute_cfg, progress_cb=..., cancel_token=..., ui_hooks={...}).run()`（`run_controller.py:100-113`）。
4. `self.compute.start('2d', _2d_worker, cfg={})`（`run_controller.py:123`）→ `ComputeOrchestrator.start`（`sjtu_tpmshx/controllers/compute_orchestrator.py:243-271`）把 worker 派发到私有 `QThreadPool`（`setMaxThreadCount(1)`，`compute_orchestrator.py:190-210`）。
5. 后台线程执行 `Pipeline2D.run()`（ABC 方法，`sjtu_tpmshx/controllers/compute_pipeline.py:108-126`）：
   - `build_fields()` → `pipelines.stages_2d._parse_inputs_cfg(self.cfg)`（`compute_pipeline.py:174`，实现 `sjtu_tpmshx/pipelines/stages_2d.py:80-243`）后 `_build_fields_cfg(...)`（`compute_pipeline.py:175-177`，实现 `stages_2d.py:246-620`）。
   - `run_solvers(fields)` → `pipelines.stages_2d._run_solvers_cfg(...)`（`compute_pipeline.py:183-186`，实现 `stages_2d.py:623-666`），内部经 `_PipelineWindowShim`（`sjtu_tpmshx/pipelines/solve_2d.py:109-215`）适配旧 window 接口后调用 `_run_solvers(shim, cfg, fields)`（`stages_2d.py:648`，实现 `sjtu_tpmshx/pipelines/solve_2d.py:644-1341`）——**这是 2D 外循环主体**，见下节。
   - `finalize(raw, fields)` → `pipelines.stages_2d._finalize_cfg(raw, self._parsed)`（`compute_pipeline.py:190-193`，实现 `stages_2d.py:669-808`）组装 `ComputeResult`。
6. worker 收到 `ComputeResult` 后 `self.write_result(result)`（`run_controller.py:119`，实现约 `run_controller.py:368-489`）把 dataclass 字段拷贝回遗留 window 属性，经 `ResultBridgeMixin` 桥接到 `controllers.result_cache.ResultCache`（`sjtu_tpmshx/ui/mixins/result_bridge.py:22-88`，未逐行核实）。**结果不落盘到文件，仅进程内 UI 状态**——除非用户手动触发 `IOActionsMixin` 的导出（CSV/NPZ，`ui/mixins/io_actions.py:56`）。

### 链 1b — 3D UI → Pipeline3D（结构镜像链 1a，关键差异点）

1. `Main_Menu._run_calculation_3d`（`ui/mixins/run_controller.py` 约 `:250` 附近起）→ `config_from_window(self, strict=True, force_3d=True)`（`run_controller.py:260-263`）。
2. `_3d_worker` 闭包构造 `Pipeline3D(compute_cfg, ..., ui_hooks={'iter_cb': ...})`（`run_controller.py:281-297`）。
3. `self.compute.start('3d', _3d_worker, cfg={'est_cells': est_cells_r})`（`run_controller.py:300`）。
4. `Pipeline3D.build_fields()` → `_parse_inputs_3d_cfg`（`sjtu_tpmshx/pipelines/stages_3d.py:96-201`）→ `_build_fields_3d_cfg`（`stages_3d.py:204-212`，**纯 passthrough**，3D 无独立 build 相）。
5. `Pipeline3D.run_solvers(fields)` → `_run_solvers_3d_cfg`（`stages_3d.py:215-246`）把 progress/cancel/iter 回调塞进 cfg dict 的 `_progress_cb`/`_cancel_check`/`_iter_cb` 键（`stages_3d.py:235-241`），套用 Phase A/B/C 加速旗标 `_apply_phase_flags(cfg)`（`stages_3d.py:244`，实现见 `pipelines/run_stack_3d.py:86-102`），最终 `_run_3d_stack(cfg)`（`stages_3d.py:246`，实现 `sjtu_tpmshx/pipelines/run_stack_3d.py:346-2107`）——**这是 3D 外循环主体**，见下节。
6. `Pipeline3D.finalize(raw, fields)` → `_finalize_3d_cfg`（`stages_3d.py:249-375`）组装 `ComputeResult`；`Main_Menu.write_result` 发布为 `window._result_3d`（`stages_3d.py:24-25` 模块 docstring 记述，未在本次逐行核实调用点）。

### 链 2a — 2D 优化器评估（qNEHVI 生产脚本）

1. 生产脚本 `runs/run_production_qnehvi.py::main`（`:29-56`）装配纯 dict `config`（求解器容差、`n_rho_loops`、`dp_cap_pa` 等，无 `ComputeConfig`），调 `run_qnehvi(config=..., n_init=32, n_iter=24, ..., save_dir='opt_runs/production_v1')`（`run_production_qnehvi.py:32-53`）。
2. `optimization/optimizer_qnehvi.py::run_qnehvi`（`:160-` 起，未标注确切结束行）默认 `evaluator_fn = evaluate_design`（`optimizer_qnehvi.py:67-68`，来自 `optimization/evaluator.py`）；每个候选点经并行/串行 `_eval_worker` 调 `evaluator_fn(x, cfg)`（`optimizer_qnehvi.py:72, 298-300`）。
3. `optimization/evaluator.py::evaluate_design(x, cfg, ...)`（`:404-635`）：
   - `from_decision_vector(x, ...)` → `ContinuousFieldConfig`（`evaluator.py:462-475`），`fc.build_grid_arrays(...)` 产出每格 K_ff/h_v/eps 数组（`evaluator.py:484-489`）。
   - `_build_simple_A`/`_build_simple_B`（`evaluator.py:231-334`）**直接构造 `SIMPLESolver`**（不经 `pipelines.stages_2d._build_fields_cfg`），内部经 `override_simple_K_cF`（`evaluator.py:272, 326`，来自 `solvers/df_projection.py`）覆盖 D-F 系数。
   - `sA.solve(...)` / `sB.solve(...)`（`evaluator.py:495-500`）跑 SIMPLE 动量。
   - **内联外循环**（不复用 `coupling_skeleton`）：`for outer_it in range(n_rho_loops)`（`evaluator.py:557-613`），每轮 `solve_full_domain(...)`（`evaluator.py:560-572`，来自 `solvers/ltne_energy.py`）后视 `n_rho_loops>1` 更新 ρ 场并重解 SIMPLE（`evaluator.py:604-613`）——与链 1a 的 `_step_2d`/`_post_2d` 逻辑**同构但物理上独立实现**（未逐行比对是否数值等价）。
   - 目标提取：`Q_total = _enthalpy_q(...)`（`evaluator.py:616`）、`dP_A/B = extract_dP_from_simple(sA/sB)`（`evaluator.py:617-618`，来自 `solvers/df_projection.py`），返回 `(-Q_total, dP_objective, mass)`（`evaluator.py:635`）。
4. `run_qnehvi` 用返回的 `(Q_neg, dP, mass)` 驱动 qNEHVI 采集函数（BoTorch，未在本次核实其内部），每 5 轮存检查点 `_save_current_pareto(...)`（`optimizer_qnehvi.py:450, 505-521`），结束时 `_save_pareto_csv(os.path.join(save_dir,'pareto_final.csv'), ...)` / `'history.csv'`（`optimizer_qnehvi.py:491-492`），`config.json` 序列化（`optimizer_qnehvi.py:250`）——**全部落盘到 `opt_runs/<save_dir>/`**，与链 1 的"仅进程内 UI 状态"形成对照。

### 链 2b — 3D 优化器评估（qNEHVI 生产脚本）

1. `runs/run_3d_qnehvi_fast.py::main`（`:30-100`）装配 `cfg` dict（含 `Nx_3d/Ny_3d/Nz_3d`、`max_outer_3d`、`roughness_mode` 等），调 `run_qnehvi(config=cfg, ..., evaluator_fn=evaluate_design_3d, save_dir='opt_runs/qnehvi_3d_<ts>')`（`run_3d_qnehvi_fast.py:88-97`）。
2. `optimization/evaluator_3d.py::evaluate_design_3d`（`:103-` 起）是薄包装，内部 `from core.evaluators import evaluate_3d as _evaluate_3d_dict`（`evaluator_3d.py:36`，模块头注释称经由 `core.evaluators` 中立层避免 `optimization`↔`validation` 反向导入，`evaluator_3d.py:32-36`）。
3. `core/evaluators.py::evaluate_3d`（`:108-` 起）**直接构造 `SIMPLESolver3D`**（`core/evaluators.py:261, 275`）+ 调 `solve_full_domain_3d`（`core/evaluators.py:343`）——与链 1b 的 `_run_3d_stack` 是**第三套独立实现**（未逐行比对与 `run_stack_3d._outer_step_3d`/`_outer_post_3d` 是否数值等价）。
4. 落盘位置同链 2a：`opt_runs/qnehvi_3d_<timestamp>/{pareto_final,history,pareto_iterNNNN}.csv` + `config.json`。

### 链 3 — validation/cases 门禁（3D 双跑法）

1. CLI 入口 `validation/cases/validate_shanghai_3d_real.py::main`（`:534-`），`--runner` 参数选择跑法，取值 `{'kernel','pipeline'}`，**默认 `'kernel'`**（`validate_shanghai_3d_real.py:537-538`）——即 CI 门禁默认跑 kernel-direct（`_run_one_case`），不是 `Pipeline3D` 生产路径；`--runner pipeline` 才切到与 GUI 同款的 `_run_one_case_pipeline`（`:538-541`）。
2. **kernel-direct 跑法** `_run_one_case(...)`（`:168-`）直接构造 `SIMPLESolver3D` + 调 `solve_full_domain_3d`（`validate_shanghai_3d_real.py:43-46` 顶层 import），冻结水侧线性 `Tb_prescribed` 剖面（docstring 用词，`:461-465`，未逐行核实"冻结"实现）——是 CI 门禁跑法。
3. **production 跑法** `_run_one_case_pipeline(ci, df, Nx_u, Ny_u, Nz_u, ...)`（`:461-531`）：显式构造 `ComputeConfig`（`FluidConfig`/`GeometryConfig`/`SolverConfig`/`PartialBCConfig`，`:494-514`）后 `result = Pipeline3D(cc).run()`（`:515`）——与链 1b **完全同一条 `Pipeline3D` 路径**，模块 docstring 自述"the exact stack the GUI drives"（`:463-465`）。
4. 结果落盘：`pd.DataFrame(results).to_csv(out_path, ...)`（`:655`），`out_path = Path(__file__).parent.parent / csv_name`（`:654`）即 `sjtu_tpmshx/validation/shanghai_3d_baseline<suffix>.csv`；`--runner pipeline` 自动在文件名追加 `_pipeline` 后缀防止覆盖 kernel-direct 基线（`:650-653`）。gate 判定 `gate_fail = (rmsre_dP > args.gate_dp) or (rmsre_Q > args.gate_q)`（`:660`），进程退出码 0/1（`:664`）。

### golden 位相同门（复用链 1，不新增装配逻辑）

`runs/_out/_golden_2d.py` 与 `_golden_3d.py` 是回归快照，但两者复用的层级**不一致**：`_golden_2d.py` 复用链 1a 的完整 `Pipeline2D(cfg).run()`（`runs/_out/_golden_2d.py:28, 66`，`cfg` 是 `ComputeConfig`）；`_golden_3d.py` 复用的是**更底层的 `_run_3d_stack`，不经过 `Pipeline3D`**——`from pipelines.stages_3d import _run_3d_stack`（`runs/_out/_golden_3d.py:20`）、`r = _run_3d_stack(cfg)`（`:77`，此处 `cfg` 是普通 dict，不是 `ComputeConfig`）。也就是说 2D golden 门验证的是"链 1a 整条路径"（含 `_parse_inputs_3d_cfg` 之外，因为 2D 有独立 build 相），3D golden 门只验证"`_run_3d_stack` 内核"，**不覆盖** `_parse_inputs_3d_cfg`/`_finalize_3d_cfg` 这两个 3D stage 层——两者对 `ComputeResult` 装配是否正确没有 golden 覆盖。两个门都对输出的标量 + 场做 SHA-256 前 16 位哈希（`_golden_2d.py:54-71`）。改动 `pipelines/` 或 `solvers/` 前必须本地先跑 `--check` 捕获基线（gitignored，见 `.claude/commands/check.md:32`，未在本次读取该文件核实）。

## 关键配置项与开关（默认值 + 定义处 file:line）

| 配置项 | 默认值 | 定义处 | 作用 |
|---|---|---|---|
| `ComputeConfig.is_3d` | `Nz>=2` 判定，无独立开关 | `sjtu_tpmshx/domain/compute_config.py:374-377` | `pipeline_for()`（`controllers/compute_pipeline.py:235-247`）据此在 `Pipeline2D`/`Pipeline3D` 间分派 |
| `ComputeConfig.envelope_mode` | `'raise'` | `domain/compute_config.py:370` | 传入 `_parse_inputs_cfg`/`_parse_inputs_3d_cfg` 的 `cfg['envelope_mode']`（`pipelines/stages_2d.py:231`、`pipelines/stages_3d.py:182`），控制 choke 检测行为 |
| `_MAX_COUPLING`（2D 外循环上限） | `10` | `sjtu_tpmshx/pipelines/solve_2d.py:689` | 可被 `SolverConfig.max_outer_ltne` 覆盖（`solve_2d.py:696-699`） |
| `_DT_TOL_K`（2D 外循环温度收敛容差） | `1.0` K | `solve_2d.py:691` | 可被 `SolverConfig.outer_tol_K` 覆盖（`solve_2d.py:700-701`） |
| `_MAX_OUTER`（3D 外循环上限） | `5` | `pipelines/run_stack_3d.py:246`（re-export 于 `pipelines/stages_3d.py:69`） | 可被 `cfg['max_outer_ltne']` 覆盖（`run_stack_3d.py:380-381`），或按 `sweep_profile` 预设覆盖（`:363-376`，`'fast_sweep'`→3,`'full_validate'`→5） |
| `_OUTER_TOL`（3D 外循环温度容差） | `0.5` K | `run_stack_3d.py:247`（re-export `stages_3d.py:69`），可被 `cfg['outer_tol_K']` 覆盖（`:382-383`） | 同上 |
| `cfg['sweep_profile']` | `None`（走模块级默认，全诊断） | `run_stack_3d.py:359, 363-376` | `'fast_sweep'`（15³ 网格，`_max_outer=3`）/ `'full_validate'`（`_max_outer=5`，`_ltne_max_iter=50000`） |
| `n_rho_loops`（2D 优化器外循环轮数） | `3`（`DEFAULT_CONFIG`，ConstDF-v1 基线） | `optimization/evaluator.py:155`（`DEFAULT_CONFIG` 定义处，已是 `3`）；`evaluator.py:534` 另有 `cfg_full.get('n_rho_loops', 1)` 的 `.get` 兜底值 `1`，但 `cfg_full` 恒含 `DEFAULT_CONFIG` 故此兜底实际不可达；生产脚本 `runs/run_production_qnehvi.py:41` 显式传 `3`，与默认值一致（非覆盖） | `>1` 时启用 ρ(T) 可压缩耦合迭代（`evaluator.py:557-613`） |
| `TPMSHX_DF_METHOD` env / `_DF_DEFAULT` | `"gamma_df"` | `sjtu_tpmshx/df_surrogate/predict.py:169`（`_DF_DEFAULT`）、`:173-175`（`_resolve_method` 优先级：显式 method 参数 > env > 默认） | 切换 D-F 闭包 backend（`gamma_df` vs `rbf`） |
| `dp_cap_pa` | `1.0e6` Pa | 优化器 cfg，生产脚本显式设（`runs/run_production_qnehvi.py:45`），评估函数内读取 `cfg_full.get('dp_cap_pa', 1.0e6)`（`optimization/evaluator.py:508`） | 未收敛/发散设计的目标钳制上限 |
| `reject_unconverged` | `False` | `optimization/evaluator.py:516`（`.get(...,False)` 回退，注释明示与 `DEFAULT_CONFIG` 对齐修复过一次不一致） | `True` 时 SIMPLE 未收敛直接短路返回惩罚目标 |
| `ComputeOrchestrator` 线程数 | `max_threads=1` | `sjtu_tpmshx/controllers/compute_orchestrator.py:190-210`（`setMaxThreadCount(1)`） | 同时只跑一个求解任务；2D 内部另有独立的 A/B 两线程并行（`solve_2d.py:933-958`），与此非同一层 |
| `_emit_audit`（3D） | `False` | `pipelines/run_stack_3d.py:2043`（`cfg.get('_emit_audit', False)`） | `True` 时额外深拷贝并导出 `_audit_*` 系列诊断字段（面速度/掩码/系数场），供 `validation/cases/audit_partial_b_ltne.py` 消费；关闭时省去深拷贝开销 |

## 边界·假设·适用范围

- **单位**：K / Pa / m，但 TPMS 胞元尺寸 `L_cell_mm`/`t_wall_mm` 是 mm（`ComputeConfig.geometry`，`domain/compute_config.py:134-155` 附近，未逐字段核实行号）——三条链的 cfg 装配处均需手动 `/1000` 或依赖 `tpms_geometry()` 内部换算，混用是常见移植 bug 源。
- **cfg dict 是弱类型的"第二契约"**：`ComputeConfig`（强类型 dataclass）只存在于链 1 与链 3 的 production 跑法；一旦进入 `_parse_inputs_cfg`/`_parse_inputs_3d_cfg`，就退化为普通 `dict`（`pipelines/stages_2d.py:222-243`、`pipelines/stages_3d.py:177-201`），下游 `_build_fields_cfg`/`_run_solvers` 之间通过约定键名（如 `'compute_cfg'`、`'eps'`、`'zone_config'`）传递，**没有 schema 校验**——键名拼写错误只在运行时以 `KeyError`/`None` 静默传播暴露。链 2（优化器）的 `cfg`/`cfg_full` 是完全独立的扁平 dict（`DEFAULT_CONFIG` 合并用户覆盖，`optimization/evaluator.py:433-435`），键名集合与链 1 的 cfg dict**不兼容**（如链 2 用 `'L_domain'`/`'H_domain'`，链 1 用 `'L'`/`'H'`，见 `evaluator.py:480` vs `stages_2d.py:223`）——移植时若尝试"统一 cfg 格式"必须先确认改的是哪条链。
- **2D 与 3D 外循环的求解顺序相反**：2D 是 SIMPLE-first（`_step_2d` 先解 SIMPLE A/B 再解 LTNE，`solve_2d.py:907-1070`），3D 是 LTNE-first（`_outer_step_3d` 先解 LTNE 再在 `_outer_post_3d` 里重解 SIMPLE，`run_stack_3d.py:1005-1360` vs `:1362-1593`）——`coupling_skeleton.py` 模块头注释明确记述这一差异是有意保留的（`solvers/coupling_skeleton.py:18-23`），不是待统一的技术债。
- **收敛判据结构相同，追踪字段实际也相同——但 `coupling_skeleton.py` 的模块 docstring 与代码不一致**：`OuterConvergence` 2D 追踪 `('Ta','Tb','Ts')` 温度场 + 质量通量加权 Δρ 作为 `extra`（`solve_2d.py:863, 1151-1153`）；3D 的 `_outer_conv = OuterConvergence(tol_T=_outer_tol, track=('Ta', 'Tb', 'Ts'))`（`run_stack_3d.py:965`）**同样追踪三个场、无 extra**——`solvers/coupling_skeleton.py:12, 55` 的文档字符串写"3D tracks ('Ta',)"，与 `run_stack_3d.py:965` 的实际调用参数**不符**（文档过时，代码为准）。移植时以 `run_stack_3d.py:965` 为准，不要相信 `coupling_skeleton.py` 的 docstring 原文。
- **D-F 闭包注入点在 2D/3D 之间不对称**：2D 的 K/c_F 由 `SIMPLESolver.__init__` **内部**调用 `predict_K_cF`/`predict_K_cF_vec`（`solvers/simple_solver.py:406-419`）；3D 的 K_arr/cF_arr 由调用方（`run_stack_3d.py:476-504`、`core/evaluators.py`）**外部**预测后以数组形式传入 `SIMPLESolver3D(K_arr=..., cF_arr=...)`（`run_stack_3d.py:545-548`）。移植时若把 2D 的"调用方传参"模式套到 3D 上（或反之）会导致重复计算或漏算。
- **优化器评估链与 pipelines 链的物理等价性未被回归测试锁定**：链 1（`pipelines.solve_2d._run_solvers`）与链 2（`optimization.evaluator.evaluate_design`）各自内联实现外循环，共享同一批底层 `solvers/` 函数但装配代码完全独立——**未发现**有测试断言两者在同一 cfg 下产出位相同或近似相同结果（未验证是否存在此类测试；若移植时"优化"了其中一条链的耦合逻辑，另一条不会自动同步）。
- **compute_orchestrator 的 `max_threads=1` 是跨模式互斥，不是并发上限**：GUI 一次只能跑一个 2D/3D/poly 计算（`compute_orchestrator.py:190-210` 的 `setMaxThreadCount(1)`），但 2D pipeline 内部会在同一次求解里对 A/B 两侧开两个 OS 线程并行跑 SIMPLE（`solve_2d.py:933-958`，注释称 njit/spsolve 释放 GIL）——这是两个不同粒度的并行控制，互不冲突但容易被误读为矛盾。
- **可压缩包络守卫覆盖链 1，不覆盖链 2 的优化器评估函数**：`check_compressible_envelope`/`gate_solution` 在 `pipelines/run_stack_3d.py:526-527, 1976-1989` 与 `pipelines/solve_2d.py:1230-1247` 都有调用；`grep -n "envelope\|gate_solution" optimization/evaluator.py core/evaluators.py` **零匹配**——两个优化器评估函数（2D `evaluate_design`、3D `evaluate_3d`）完全不调用 `solvers/envelope.py` 的任何函数，仅靠 `dp_cap_pa` 数值钳制（`optimization/evaluator.py:508, 632-633`）兜底高 Δp/发散设计。这意味着优化器在探索到 choke 工况（Δp 逼近或超过入口绝对压力）时，SIMPLE 可能已经在内部产出负压/超音速场（`solvers/simple_solver.py`/`simple_solver_3d.py` 的 `_update_density` 压力 clip 仍会生效,但不会像链 1 那样显式抛 `ChokedFlowError` 或标记 `envelope_valid=False`），该设计点只是被 `dP > dp_cap_pa` 的数值阈值滤掉，而非被物理判据识别。

## 可扩展接口（hooks、backend 注册点、私有 kwargs、env 变量、预留分支）

- **`ComputePipeline` ABC 的 3 相契约**（`controllers/compute_pipeline.py:64-141`）是唯一稳定的第三方接入点：任何新计算模式只需实现 `build_fields`/`run_solvers`/`finalize` 三个方法并注册进 `pipeline_for()`（`compute_pipeline.py:235-247`）的 `cfg.is_3d` 分派逻辑（目前是二选一，新增第三分支需要改这里）。
- **`ui_hooks` dict**（`ComputePipeline.__init__`，`compute_pipeline.py:93-100`）：`'live_residuals'`（2D 残差 sparkline）、`'iter_label_cb'`（2D 迭代标签）、`'iter_cb'`（3D 迭代回调）三个已用键；新增 UI 侧通道可以继续往这个 dict 加键而不改 ABC 签名。
- **`evaluator_fn` 注入**（`optimization/optimizer_qnehvi.py::run_qnehvi` 的 `evaluator_fn` 形参，`optimizer_qnehvi.py:171`，默认 `evaluate_design`）：这是 qNEHVI 循环唯一的可插拔点，`run_3d_qnehvi_fast.py:97` 用它换成 `evaluate_design_3d`——新增第三种评估器（如水侧 2D 评估器）只需实现同签名 `(x, cfg) -> (Q_neg, dP, mass)` 并在生产脚本里传入。
- **`df_surrogate.backend.register(name)` 装饰器**（`sjtu_tpmshx/df_surrogate/backend.py:38-44`）：新增 D-F backend 的注册点；`TPMSHX_DF_METHOD` env 变量（`predict.py:169-175`）是运行时切换开关。
- **`cfg['partial_B_closure']`**（`run_stack_3d.py:1072`，取值 `'none'`/`'m4_effective_area'`/`'per_cell_chi_b'`）：部分宽度 B 侧入口的 ghost-cell 处理策略分派，是一个仍在迭代的物理选项分支（`'per_cell_chi_b'` 试过又在 2026-05-14 回退，见 `run_stack_3d.py:1061-1071` 注释）。
- **`cfg.get('ltne_enthalpy_mode', False)`**（`run_stack_3d.py:1248-1257`）：sCO2 变 cp 焓形式 LTNE 的可选替代求解路径（`solvers/ltne_enthalpy_3d.py`），默认关闭，仅在双侧变 cp 流体 + 特定流向组合时触发（`_enth_gate` 条件，`run_stack_3d.py:1248-1253`）。
- **`compute_cfg.geometry.delta_levelset`**（非对称偏移等值面 δ）：`_asym_split_A`/`_per_side_eps_override`/`_eps_sides_for_run`（`solvers/asym_split.py`，被 `pipelines/stages_3d.py:38-40` 与 `pipelines/solve_2d.py:800` 共同引用）是 2D/3D 共享的非对称孔隙率分裂钩子，δ=0 时保证位相同（多处注释反复强调，如 `solve_2d.py:796`、`run_stack_3d.py:494`）。
- **`cfg['_emit_audit']` / `cfg['ports_A']`/`['ports_B']`**：分别是 3D 审计导出开关（`run_stack_3d.py:2043`）与端口式局部 BC 开关（`optimization/evaluator.py:551-554`，`IDEA-PORT-DIM` 相关，见 `runs/run_port_dim_retest.py`）——后者是链 2 特有，**未验证**链 1/链 3 是否有等价机制。
- **环境变量一览（本次核实到的）**：`TPMSHX_DF_METHOD`（D-F backend 切换，`predict.py:175`）、`TPMSHX_MAX_CELLS_3D`（3D 网格胞元数硬上限，默认 200 万，`run_stack_3d.py:424-426`）、`TPMSHX_SCO2_COMPRESSIBLE`（sCO2 opt-in 可压缩路径，`run_stack_3d.py:1381, 1420-1421`）。`TPMSHX_NUM_THREADS`（numba 线程数，见 `solvers/threads.py`，本册未逐行核实）。

## 已知不足与 TODO

- 三条入口链存在**重复的外循环实现**（`pipelines/solve_2d.py` 的 `_step_2d`/`_post_2d` vs `optimization/evaluator.py` 的内联 `for outer_it` vs `pipelines/run_stack_3d.py` 的 `_outer_step_3d`/`_outer_post_3d` vs `core/evaluators.py` 的另一套 3D 内联循环）——`solvers/coupling_skeleton.py` 只被链 1（2D 与 3D 的 pipelines 路径）复用，链 2（两个优化器评估函数）完全没有复用它。docstring 未显式声明这是待办，但从架构一致性角度看是明显的重复代码风险点（**观察性判断，非代码内 TODO**）。
- `validate_shanghai_3d_real.py::main` 的 `--runner` 默认值确认是 `'kernel'`（`:538`），**不是** `Pipeline3D` 生产路径——CI 门禁跑的是 kernel-direct 冻结-B 实现，GUI 生产路径的数字要显式加 `--runner pipeline` 才会核对，两者长期可能不同步而不自知（这不是待办本身，而是需要读者记住的架构事实）。
- 可压缩包络守卫（`solvers/envelope.py`）在优化器评估链（链 2a/2b）中**已确认缺失**（见上文"边界"节倒数第二条）——如果优化器在设计空间探索中命中 choke 区域,仅靠 `dp_cap_pa` 数值钳制而非物理判据拦截，可能让 BO 在不可行域附近产生误导性梯度信息。这是一个可核实的改进点，而非未验证猜测。
- `solvers/coupling_skeleton.py` 模块 docstring（`:12, 55`）关于"3D 只追踪 Ta"的描述与实际代码（`run_stack_3d.py:965` 追踪 `Ta/Tb/Ts`）不符，是一处需要修正的过时注释（已在"边界"节指出）。
- `ui/mixins/run_controller.py` 里 2D worker 注释明示 `cancel_token` 目前是被动的——`_run_solvers` 内循环不轮询取消（`pipelines/stages_2d.py:637-641` docstring）；3D 侧在 `_outer_step_3d` 开头有 `_cancel_check()` 轮询（`run_stack_3d.py:1013-1014`），因此**2D 和 3D 的取消响应粒度不一致**（2D 只能在相边界取消，3D 可以在每个外循环迭代边界取消）——不是 bug,但移植时如果只照抄一侧的取消逻辑会引入行为差异。
- `runs/_out/_golden_3d.py` 只验证 `_run_3d_stack` 内核（`:20, 77`），不像 `_golden_2d.py` 那样验证完整 `Pipeline3D`——`_parse_inputs_3d_cfg`/`_finalize_3d_cfg` 两个 3D stage 层缺少 golden 位相同覆盖，是一个可考虑补齐的回归盲区（**观察性判断，非代码内 TODO**）。
