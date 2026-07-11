# tests — 测试覆盖地图
生成日期 2026-07-11，基于 commit f33d30e 附近的 master

## 定位与功能

`sjtu_tpmshx/tests/` 是本仓库唯一的 pytest 套件根，由仓库根的 `pytest.ini`（`pytest.ini:15`）通过 `testpaths = sjtu_tpmshx/tests` 锁定收集范围，防止裸 `pytest` 误入 `.claude/worktrees/` 下的仓库副本。套件共 **151 个文件**：`sjtu_tpmshx/tests/` 下 135 个 `test_*.py` + 1 个 `conftest.py`，加上子目录 `sjtu_tpmshx/tests/design/` 下 15 个 `test_*.py`（后者是 `sjtu_tpmshx/design/`——一个独立的 10kW 换热器选型/CLI 子模块——的单元测试，复用同一个顶层 `conftest.py` 做 `sys.path` 引导，未见独立的 `design/conftest.py`）。

与本文档强相关但**不在 pytest 收集范围内**的两个"golden 位一致门禁"脚本位于 `sjtu_tpmshx/runs/_out/_golden_2d.py` 和 `sjtu_tpmshx/runs/_out/_golden_3d.py`（文件头注释明确写 "Not a pytest"，`runs/_out/_golden_2d.py:16`）；它们是手动 CLI 脚本，由 `.claude/commands/check.md` 描述的验收流程调用，只有在人为触发时才跑。测试目录内确实还有"回归"字样的 pytest 文件（`test_shanghai_regression.py`），但那是另一件事——对生产验证脚本（`validation/cases/...`）的 subprocess 包装 + 数值容差断言，不是 bit-identical 位比较。

测试运行的标准入口是 `.claude/commands/check.md`（`/check` skill），而非本文档要精读的对象；本文档只编目"有什么测试、怎么分组、跑门有哪些已知坑"。

## 文件一览（按主题分组，每组给代表性文件；不逐个精读全部 151 个）

### A. Golden / 位一致回归门禁（不在 pytest 内，人工调用）
- `sjtu_tpmshx/runs/_out/_golden_2d.py` — Pipeline2D 两个代表 cfg（air-air + air/water-B 交叉流）× headline 标量 + 每个输出场 SHA-256；`--check` 模式做差异比对。
- `sjtu_tpmshx/runs/_out/_golden_3d.py` — 3D 对应版本（先于 2D 版本存在，见 `runs/_out/_golden_2d.py:3` 注释）。

### B. pytest 内的"数值回归/钉定"测试（bit-level 或近 bit-level pin，但走 pytest）
- `sjtu_tpmshx/tests/test_df_backend_registry.py` — DF backend（`gamma_df` / `rbf`）在 Shanghai gate 点（L=7.0, t=0.6）的 (K, cF) 精确浮点值钉定（`test_df_backend_registry.py:23`），标记 `_CI = pytest.mark.skipif(CI==true, ...)`（`test_df_backend_registry.py:33`）——**同机器 ULP 门禁，跨平台/跨标定源会漂移，故 CI 上跳过**。
- `sjtu_tpmshx/tests/test_df_projection_equivalence.py` — 同类同机器 ULP 门禁（第 54 行同样定义 `_CI` skipif）。
- `sjtu_tpmshx/tests/test_evaluator_frozen_values.py` — `evaluate_design` / `evaluate_design_3d` 的 (Q_neg, dP, mass) 输出钉定，`rel=1e-12`（非精确 `==`），标记 `pytest.mark.slow`（`test_evaluator_frozen_values.py:35`），docstring 称"同 capture/check 约定 as runs/_out/_golden_3d.py"。
- `sjtu_tpmshx/tests/test_shanghai_regression.py` — **opt-in、默认跳过**的 Shanghai 16-case 端到端验证（3 条：legacy 2D 已 retired/skip 占位、`test_shanghai_3d_baseline`、`test_shanghai_lumped_paper`），靠 `TPMSHX_RUN_SHANGHAI_REGRESSION=1` 环境变量开启（`test_shanghai_regression.py:44-51`），每条约 6 分钟，通过 subprocess 跑 `validation.cases.*` 模块并对 CSV 输出做 RMSRE 容差断言（dP baseline 5.28%±5%，Q baseline 3.21%±10%，见第 181-190 行）。

### C. Solver 数值单元测试（2D/3D SIMPLE 核、动量/压力/守恒）
`test_simple_solver_3d.py`、`test_simpler_coupling_2d.py`、`test_pp_sparse_assembly.py`、`test_project_div_free.py`、`test_momentum_sou_telescoping.py`、`test_sou_conservation.py`、`test_kernels_2d_equiv.py`、`test_rb_energy_2d_equiv.py`、`test_rb_energy_equiv.py`、`test_zsym_3d_conservative.py`、`test_conservation_3d_energy.py`、`test_mass_flow_consistency_3d.py`、`test_nonuniform_simple_3d.py`、`test_wall_refine_3d.py`、`test_inlet_stretched_grid.py`、`test_inlet_taper_mass.py`、`test_pressure_floor.py`、`test_pressure_invalid_flag.py`、`test_anderson_simple.py`、`test_pyamg_dynamic_rebuild.py`、`test_dp_face_extrap_order.py`、`test_dp_direction_invariance.py`、`test_3d_direction_invariance.py`、`test_3d_reverse_mirror.py`、`test_sco2_3d_reverse_massflow.py`、`test_re_convention.py`、`test_solver_efficiency.py`、`test_solver_threads.py`、`test_solver_knobs_r3.py`、`test_coarse_bootstrap_3d.py`、`test_finalize_3d_result_sync.py`、`test_orch_finished_3d_state.py`、`test_massflux_inlet_3d.py`。（本组未逐文件精读，按文件名 + 目录约定归类；核实需要读各文件本身，标注**未验证**。）

### D. LTNE / 双温 / porosity 分裂闭合测试
`test_ltne_energy_3d.py`、`test_ltne_energy_freeze.py`、`test_ltne_enthalpy_1d_optionB.py`、`test_ltne_enthalpy_3d.py`、`test_a3_conservative_ltne_2d.py`、`test_chi_s_homogenization.py`、`test_chi_b_reverse_mirror.py`、`test_m2_vans_eps_momentum.py`、`test_m2b_vans_eps_momentum_3d.py`、`test_eps_contract_3d.py`、`test_eps_outlet_bc_3d.py`、`test_enth_mode_eps_override.py`、`test_q_enth_b_partial_b.py`、`test_partial_bc_ghost_b.py`、`test_asym_porosity_2d.py`、`test_asym_porosity_3d.py`、`test_asym_geometry.py`。对应 CLAUDE.md 的"ε 只在一处折半"不变量与非对称 δ 分支。

### E. DF/Nu 闭合与代理模型（surrogate）测试
`test_gamma_df.py`、`test_smooth_df.py`、`test_df_backend_registry.py`、`test_df_overrides.py`、`test_df_projection.py`、`test_df_projection_equivalence.py`、`test_nu_correlations.py`、`test_predict_K_cF_vec_batch.py`、`test_surrogate_domain.py`、`test_tpms_calc.py`、`test_tpms_geometry_n128.py`、`test_order_fit.py`，以及依赖本地实验数据的两个特例：`test_load_data_no_shanghai.py`、`test_cache_and_source_guards.py`（见下方"data/raw_data 依赖"专节）。

### F. 包络（choke/Mach 守卫）与鲁棒性/输入校验
`test_envelope.py`、`test_envelope_hardening.py`、`test_envelope_integration_2d.py`、`test_envelope_integration_3d.py`、`test_invariant_negative_guards.py`、`test_robustness_gates.py`、`test_closure_guards.py`、`test_domain_validator.py`、`test_field_validation_order.py`、`test_preflight.py`、`test_run_controller_preflight.py`、`test_audit_round2_fixes.py`、`test_review_fixes.py`。对应 CLAUDE.md 的 `solvers/envelope.py` choke 守卫不变量。

### G. MMS（人为解法验证）
`test_mms_driver.py`、`test_mms_b4_conservative_order.py`、`test_mms_phase_a3_gates.py`、`test_mms_phase_a4_gates.py`。

### H. 编排 / pipeline / compute-config / 场工厂
`test_compute_config.py`、`test_compute_config_roundtrip.py`、`test_compute_orchestrator.py`、`test_compute_pipeline.py`、`test_pipeline_2d_smoke.py`、`test_pipeline_3d_e2e.py`、`test_pipeline_reexports.py`、`test_pipeline_ui_hooks.py`、`test_field_factory.py`、`test_field_unit_helpers.py`、`test_grid_schema.py`、`test_continuous_field.py`、`test_sigmoid_field.py`、`test_sigmoid_field_3d.py`、`test_coupling_skeleton.py`、`test_evaluator_3d_conservative.py`、`test_evaluator_sanity.py`、`test_port_evaluator.py`、`test_headline_q_air_side.py`。

### I. sCO2 专项
`test_sco2_field_cache.py`、`test_sco2_numerical_audit_2026_06_28.py`、`test_sco2_phase_a.py`（其中 `test_gate_a_d76_gold_duty` 依赖仓库内 `projects/703-sCO2-D76/validate_sco2_d76.py` 及外部 D-7-6 实验 xlsx，任一缺失即 `pytest.skip`，`test_sco2_phase_a.py:94-103`）、`test_sco2_phase_c.py`、`test_sco2_temperature_field.py`。

### J. 优化器（qNEHVI / 面板接线）
`test_optimize_panel_wiring.py`、`test_optimizer_qnehvi_helpers.py`。

### K. UI（PySide6/Qt，headless offscreen）
`test_quick_design_dialog.py`、`test_quick_design_panel_wiring.py`、`test_theme_manager.py`、`test_ui_layout_hygiene.py`、`test_stylesheet_braces.py`、`test_signal_router.py`、`test_session_manager.py`、`test_main_smoke.py`、`test_main_resultcache_bridges.py`、`test_io_actions.py`、`test_ts_init.py`。全部依赖 `conftest.py` 里的 `QT_QPA_PLATFORM=offscreen` 全局设置（见"服务器移植注意"专节）。

### L. 架构守卫 / 基础设施
`test_import_dag.py`（每个探针 fork 一个全新解释器子进程验证模块导入方向，见下）、`test_math_symbols.py`、`test_logutil.py`、`test_result_cache.py`、`test_fluid_props.py`、`test_fluid_registry_migration.py`、`test_fluid_type_validation.py`、`test_bc_to_dict.py`、`test_export_ntop_csv.py`、`test_warmup_jit_kernels.py`、`test_provenance.py`、`test_shanghai_baseline_config.py`、`test_simple_wall_bc.py`。

### M. `design/` 子包（10kW 选型 CLI，独立于主 SIMPLE 求解器）
`sjtu_tpmshx/tests/design/test_cases.py`、`test_cli.py`、`test_converge_fast.py`、`test_csv_loader.py`、`test_enumerate_parallel.py`、`test_fluids.py`、`test_forward.py`、`test_height_decouple.py`、`test_material_density.py`、`test_optimize.py`、`test_prop_model.py`、`test_select.py`、`test_sizing_inner.py`、`test_sizing_outer.py`、`test_wall_thickness_nodes.py`。被测代码是 `sjtu_tpmshx/design/{cases,cli,fluids,forward,optimize,report,select,sizing}.py`。

## 公开接口（关键函数/类：签名要点 + file:line + 调用方）

- `conftest.py` 无自定义 fixture 函数，只做两件全局副作用：
  - `os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')`（`sjtu_tpmshx/tests/conftest.py:33`）——必须在任何 PySide6 import 之前执行，靠 pytest 在收集测试前加载 `conftest.py` 的时机保证；调用方：整个套件里所有 UI 相关 `test_*.py`（隐式依赖，各文件无需自行设置）。
  - `sys.path.insert(0, str(ROOT))`，`ROOT = Path(__file__).resolve().parents[1]` 即 `sjtu_tpmshx/`（`conftest.py:35-37`）——让 `solvers`、`optimization`、`df_surrogate`、`controllers`、`runs`、`ui`、`design` 等顶层包可以在任意子进程/独立文件里被 import，不必每个测试文件自带 `sys.path` 引导（文件头注释列出了已有引导的例外：`test_3d_direction_invariance.py`、`test_compute_orchestrator.py`、`test_ltne_energy_3d.py`，见 `conftest.py:9-12`）。
  - 进程级 `QApplication(['pytest', '-platform', 'offscreen'])` 单例预热（`conftest.py:49-57`），`try/except Exception: pass` 包裹以兼容无 PySide6 的哨兵 CI 环境。
- `runs/_out/_golden_2d.py` / `runs/_out/_golden_3d.py` 的 CLI 契约（非 Python API，是命令行脚本）：
  - `python -u runs/_out/_golden_2d.py` → 打印 JSON（capture 模式）
  - `python -u runs/_out/_golden_2d.py golden.json` → capture + 写文件
  - `python -u runs/_out/_golden_2d.py --check golden.json` → 与文件比对，PASS/FAIL
  （`runs/_out/_golden_2d.py:12-14`）；调用方是人类操作员，通过 `.claude/commands/check.md` 描述的手动工作流触发，不由 pytest 自动调用。
- `test_shanghai_regression.py::_run_subprocess(module, *args, timeout=1200)`（`test_shanghai_regression.py:56`）——本文件内部辅助函数，用 `sys.executable -u -m <module>` 子进程方式跑 `validation.cases.*` 脚本，`encoding='utf-8', errors='replace'` 捕获 stdout/stderr；仅供本文件三个测试函数调用。
- `test_import_dag.py::_probe(code)`（`test_import_dag.py:20-23`）——`subprocess.run([sys.executable, '-c', code], cwd=_PKG, ...)`，在全新解释器里 exec 一段探针代码并断言 `returncode == 0`；仅供本文件内多个 `test_*_is_*` 断言调用，用于验证模块导入方向（例：`test_df_surrogate_is_below_the_kernel`，`test_import_dag.py:26-35`，断言 `df_surrogate.predict` 不会把 `solvers.tpms_calc`/`solvers.simple_solver` 拉进 `sys.modules`）。

## 关键配置项与开关（默认值 + 定义处 file:line）

- `pytest.ini` `testpaths = sjtu_tpmshx/tests`（`pytest.ini:15`），`addopts = --strict-markers`（`pytest.ini:16`）；注册的 marker 只有两个：`slow`（`pytest.ini:18`）、`fast`（`pytest.ini:19`）。**未见 `markers` 里注册其他名字**——`--strict-markers` 意味着任何拼错的 `@pytest.mark.xxx` 会直接报错而不是静默通过。
- 并行执行标准命令（`.claude/commands/check.md` 记录，非测试代码本身）：`$env:PYTHONHASHSEED="0"; pytest sjtu_tpmshx/tests/ -q -n auto --dist loadscope`。`PYTHONHASHSEED=0` **必须在 shell 里设置**，不能写进 `pytest.ini`，因为哈希随机化在解释器启动时就已决定，pytest 配置加载得太晚（`pytest.ini` 第 11-13 行注释同样强调这点）。`--dist loadscope` 把同模块的测试（例如共享 module-scope 的 surrogate/MMS fixture）钉在同一个 worker 上，避免跨 worker 重复初始化。`check.md` 记录的期望结果是"≈1037 passed, a few skipped"（**该数字未在本次编目中重新验证**，来自 `.claude/commands/check.md` 文档描述，可能随套件增删而漂移）。
- `TPMSHX_RUN_SHANGHAI_REGRESSION`（默认未设置 → 该文件全体 skip）：控制 `test_shanghai_regression.py` 是否运行，值需为 `'1'/'true'/'yes'`（大小写不敏感，`test_shanghai_regression.py:44-51`）。
- `CI` 环境变量 == `'true'` 时跳过两个同机器 ULP 精确钉定测试文件（`test_df_backend_registry.py:33-35`、`test_df_projection_equivalence.py:54` 附近同名 `_CI` 定义）——即：**这两个文件在 CI 上天然跳过，本地跑门是它们唯一的执行场景**，因此"data/raw_data 缺失导致的 ULP 失败"这个坑只发生在本地/worktree 环境，不会在贴了 `CI=true` 的环境暴露。
- `_RAW_XLSX = ROOT.parent / 'data' / 'raw_data' / '试验记录表_整理版.xlsx'` 判定路径出现在 `test_load_data_no_shanghai.py:29`（同样的 grep 命中还包括 `test_eps_contract_3d.py`、`test_cache_and_source_guards.py`——后两者的具体行号本次未逐一核实，标注**存疑**）——`ROOT` 是 `sjtu_tpmshx/tests` 的 parent 即 `sjtu_tpmshx/`，故完整路径是 `<repo_root>/data/raw_data/试验记录表_整理版.xlsx`。
- `df_surrogate/surrogate_v3.py:85` 定义同一路径为模块级常量 `XLSX`；`SurrogateV3.__init__` 据其存在与否二选一标定源（`_source` 属性取 `'xlsx'` 或 `'prebuilt_csv'`，`surrogate_v3.py:157,162`），两条路径理论上应产出相同 (K, cF)，由 `test_cache_and_source_guards.py::test_df_source_parity`（`test_cache_and_source_guards.py:26-47`）钉住等价性——但**该等价性测试本身在 xlsx 缺失时会 `pytest.skip`**（`test_cache_and_source_guards.py:30-31`），不会在缺数据的 worktree 里验证到"prebuilt CSV 是否仍然对得上"。

## 边界·假设·适用范围

- **单位与路径约定**：与主仓库一致（K/Pa/m，TPMS 尺寸 mm）；测试代码未见破例。
- **平台假设**：完整套件在 Windows（GBK 控制台）与 CI（`test_df_backend_registry.py:32` 注释提到 "libm/FMA differences shift the last ULP on other platforms (measured rel ~1e-13 on ubuntu CI)"，暗示 CI 跑在类 Linux 环境，**未逐一核实 CI 配置文件**）之间存在浮点 ULP 差异，这是显式设计进测试的边界条件，不是 bug。
- **Qt/GUI 测试要求 headless 能力**：`QT_QPA_PLATFORM=offscreen` 必须在任何 PySide6 import 前生效（`conftest.py:16-24` 注释描述了这个时序 gotcha 的历史成因：单测子进程运行会绕过某些顺序假设）。
- **同机器 ULP 门禁的适用范围**：`test_df_backend_registry.py` / `test_df_projection_equivalence.py` 的 `test_golden_point_values_exact` 系列本质是"在本机重现同一份标定数据得到完全一致浮点值"，**不是**跨机器可移植的正确性断言；生产物理正确性由 `test_shanghai_regression.py`（opt-in）和手动 golden 脚本另行把关。
- **opt-in/慢速测试不计入默认快速反馈**：`slow` marker 覆盖至少 14 个文件（`design/test_enumerate_parallel.py`、`design/test_optimize.py`、`test_a3_conservative_ltne_2d.py`、`test_asym_geometry.py`、`test_cache_and_source_guards.py`、`test_evaluator_frozen_values.py`、`test_evaluator_sanity.py`、`test_pipeline_2d_smoke.py`、`test_pipeline_3d_e2e.py`、`test_pyamg_dynamic_rebuild.py`、`test_rb_energy_2d_equiv.py`、`test_rb_energy_equiv.py`、`test_solver_knobs_r3.py`、`test_wall_refine_3d.py`，本次 grep 逐一列出）；`fast` marker 仅 1 个文件（`test_evaluator_sanity.py`）使用，作为"cheap smoke subset"（`pytest.ini:20`，opt-in via `-m fast`）。默认全量跑门（`.claude/commands/check.md` 第 1 节）会执行 `slow` 测试（约 4.5 分钟并行），但**不会**执行 `test_shanghai_regression.py`（需要显式环境变量）也**不会**执行 `runs/_out/_golden_*.py`（不是 pytest 用例，需手动调用）。

## 可扩展接口（hooks、backend 注册点、私有 kwargs、env 变量、预留分支）

- `pytest.ini` 的 `markers` 列表是新增测试分类的唯一注册点；因 `--strict-markers`，新增第三种速度/范围标记（例如某种 "gpu" 或 "network" marker）必须先在此处登记，否则收集期直接报错。
- `TPMSHX_RUN_SHANGHAI_REGRESSION` 与 `CI` 是本次编目中确认的两个"改变测试执行与否"的环境变量开关（前者显式 opt-in 慢速回归，后者隐式 opt-out 同机 ULP 钉定）；`solvers`/`df_surrogate` 里可能另有生产用环境变量（如 CLAUDE.md 提到的 `TPMSHX_DF_METHOD`），但那些是生产代码的开关而非 tests/ 目录本身的开关，**未在本次编目内逐一核实是否也被某个测试文件读取**。
- `test_sco2_phase_a.py::test_gate_a_d76_gold_duty` 用 `importlib.util.spec_from_file_location` 动态加载 `projects/703-sCO2-D76/validate_sco2_d76.py` 而非常规 import（`test_sco2_phase_a.py:96-99`）——这是一个可复用的"跨目录动态加载外部验证脚本 + 检查其 `XLSX` 属性和 `main()` 返回码"模式，若未来要接入其他 `projects/*` 下的验证脚本可参照此写法。
- `test_import_dag.py::_probe(code)`（`test_import_dag.py:20-23`）用全新解释器子进程验证模块导入方向，避免宿主测试进程的 `sys.modules` 缓存污染判断——这是检验"层级/DAG 不变量"的通用模式，可扩展为新增层级探针。

## 已知不足与 TODO（含代码里的 TODO/FIXME/NotImplementedError/被注释掉的分支）

- `test_shanghai_regression.py::test_shanghai_2d_legacy` 用 `@pytest.mark.skip` 永久跳过，docstring 明确这是"故意保留的退役占位符"，用于让 pytest 收集时仍能看到这条历史记录（`test_shanghai_regression.py:75-91`）——不是待修的 bug，是有意的文档化 skip。
- worktree/裸克隆缺少 gitignored 的 `data/raw_data/` 会让若干文件走 `pytest.skip`（`test_load_data_no_shanghai.py`、`test_eps_contract_3d.py`、`test_cache_and_source_guards.py::test_df_source_parity`）或产生 ULP 级精确等值失败（`test_df_backend_registry.py`、`test_df_projection_equivalence.py` 的 `test_golden_point_values_exact` 系列，本地非 CI 环境不跳过）——**根治方案未做**：用户侧沉淀的备忘录（非本仓库代码内容，来自本地 `worktree-rawdata-gate-trap` 记忆条目，不是可 file:line 溯源的代码事实，仅作线索）建议"按标定源分档钉定值"或"测试 fixture 自动定位主检出的 data/ 目录"，但这两种修复目前都不在代码里，实操上需要跑门前手动 `cp -r data <worktree>/data`（约 2.3 MB，出处同上，**未在代码中验证该体积数字**）。
- GBK 控制台下，若日志行包含中文路径（如 `试验记录表_整理版.xlsx` 本体），子进程写 GBK 字节而 pytest 以 UTF-8 读 capture 流会导致后续测试的 teardown 抛 `UnicodeDecodeError`；`surrogate_v3.py:151-154` 已经用注释固化了"库代码日志行必须 ASCII-only"这条规则，但这是**约定而非强制检查**——未见任何自动化 lint/test 去扫描 `_log.info(...)` 调用参数是否可能带中文路径，如果未来有人在别处新增一条打印中文路径的日志，这个坑会复现且难以定位（报错发生在无关测试的 teardown 上，不在出问题的那条日志附近）。**未验证**当前套件里是否还存在其他会打印中文路径的日志点。
- `test_shanghai_regression.py` 里 baseline 常量（`BASELINE_DP = 5.28`、`BASELINE_Q = 3.21`，第 181-182 行）是手工维护的钉定值，docstring 历史区块（第 99-180 行）记录了至少 6 次数值漂移沿革；这类"手工同步 docstring 历史 + baseline 常量"的维护方式容易在下次改动时遗漏更新其中一项——**未验证**是否有自动化机制防止两者失步。
- 本文档未对 C/D/E/F/G/H/I/J/K/L/M 各组的全部文件逐一精读（按任务要求的编目级别），因此各组内单个文件的具体断言、fixture 细节、是否存在跳过条件均**未验证**，仅按文件名与目录位置分类；如需逐文件事实核查，需要另行展开。

## 服务器移植注意（Windows 路径/编码/GUI/并行/依赖等平台假设）

- **GBK 编码陷阱是 Windows 专属**，迁移到 Linux 服务器后 GBK/UTF-8 不一致导致的那类 teardown 崩溃预期不会重现（Linux 终端多为 UTF-8），但 `surrogate_v3.py` 里"日志行必须 ASCII-only"的约定本身仍值得保留，因为它同时避免了跨 locale 的类似问题——**未验证** Linux + 非 UTF-8 locale（如某些容器镜像的 `C` locale）是否会有类似风险。
- **Qt offscreen 平台插件**：`conftest.py` 里 `QT_QPA_PLATFORM=offscreen` 的设置是跨平台通用的 PySide6/Qt 机制，理论上 Linux 无显示服务器同样适用；但 Linux 上 `offscreen` 平台插件依赖系统库（典型为 `libxcb-*`、`libEGL`/`libGL` 等），若目标服务器缺这些库，`QApplication(['pytest', '-platform', 'offscreen'])` 可能在 `conftest.py:49-57` 的 `try/except Exception: pass` 里被静默吞掉，导致 K 组全部 Qt/UI 测试在收集或运行时以难以定位的方式失败或被跳过——**未验证**目标服务器的系统库是否齐全，移植前应单独跑一遍纯 UI 测试子集（如 `pytest sjtu_tpmshx/tests/test_ui_layout_hygiene.py -q`）确认。
- **`data/raw_data/` 是本地专有实验数据，gitignored**：Linux 服务器上的全新 checkout 同样会缺失它，触发与本文档"data/raw_data 依赖"专节完全相同的 skip/ULP 失败模式（这不是 Windows 特有问题，是任何"缺该目录的检出"共有的坑）；`projects/703-sCO2-D76/` 下的 D-7-6 实验 xlsx 同理（`test_sco2_phase_a.py:102-103`）。
- **并行 pytest-xdist + `PYTHONHASHSEED=0`**：`-n auto` 在 Linux 上通常等价工作（CPU 核数探测机制不同但语义一致），`PYTHONHASHSEED` 环境变量在两个平台都是解释器启动期决定，行为一致；`--dist loadscope` 无平台相关性。
- **`sys.executable` 子进程模式**（`test_import_dag.py`、`test_shanghai_regression.py::_run_subprocess`、`test_sco2_phase_a.py` 的动态模块加载）在 Linux 上应同样可用，因为都用 `sys.executable` + 标准库 `subprocess`/`importlib`，未见 Windows 专属的 shell 语法或路径分隔符硬编码——**未验证**逐行确认，是基于所读片段的推断。
- **numba JIT（`test_warmup_jit_kernels.py` 文件名暗示存在专门的 JIT 预热测试）**在 Linux 上首次编译耗时分布可能与 Windows 不同（缓存目录、CPU 特性检测不同），但这属于性能而非正确性问题，本次未打开该文件核实其具体断言，**未验证**具体影响幅度。
