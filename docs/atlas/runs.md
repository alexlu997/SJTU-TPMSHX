# runs — 入口脚本目录

生成日期 2026-07-11，基于 commit f33d30e 附近的 master

## 定位与功能

`sjtu_tpmshx/runs/` 是本仓库的**脚本层**：可直接 `python -u runs/xxx.py` 或
`python -u -m runs.xxx` 执行的入口点集合，不是可复用的库代码（除极少数被其他
脚本 import 的助手函数外）。按 `PROJECT_MANUAL.md:632-648`（6.11 节）的既有
定位：

- **计算主路径不在这里** —— GUI「计算」按钮的真正编排已迁到
  `pipelines/stages_2d.py` / `pipelines/run_stack_3d.py`
  （`PROJECT_MANUAL.md:610-628`），`runs/` 只保留生产优化入口、演示、诊断、
  UI 冒烟、CFD 工具链脚本。
- **例外**：`runs/polygon_calc.py` 的 `run_polygon_calculation` 是多边形域
  CFD 编排的真实生产入口，被 `ui/mixins/run_controller.py:344`
  （`self._run_polygon_calculation()` → `from runs.polygon_calc import
  run_polygon_calculation`）直接调用——这是本目录中唯一由 UI 生产代码
  `import` 的模块（其余脚本都是命令行独立执行）。
- 子目录划分（本次编目范围，全 49 个 `.py`）：
  - 根目录（14 个）：生产优化入口、benchmark、`polygon_calc.py`、
    `_case_template.py` / `_smoke_boot.py` 两个助手模块。
  - `_out/`（2 个，仓库根 `.gitignore:86`——不是 `sjtu_tpmshx/.gitignore`（该文件仅 19 行，无此条目）——整目录 gitignored）：golden 位级回归门。
  - `archive/`（11 个）：冻结的一次性历史诊断，多数带 `⚠ ARCHIVAL` 头注。
  - `demos/`（4 个）：3D 演示 / 可视化，无 Qt 依赖（`demo_vis_3d_interactive.py`
    除外，用 PyVista 交互窗口）。
  - `diagnostics/`（5 个）：asym-porosity 几何 Phase-0/0.5 扫描（纯几何，无 CFD）。
  - `smokes/`（6 个）：offscreen Qt / 计算管线端到端冒烟。
  - `tools/`（5 个）：CFD 工况簿 Excel 生成、HTML 报告渲染、图表再生脚本。
  - `cfd_asym/`（3 个）：PyFluent 批跑 + κ 后处理（跑在另一台 CFD 机器上）。

## 文件一览（每文件一行职责）

### 根目录

| 文件 | 用途 / 关键参数 / 状态 |
|---|---|
| `__init__.py` | 空，使 `runs/` 成为可 `import` 的包（子目录本身均无 `__init__.py`，见下）。 |
| `_case_template.py` | `build_cfg(...)` — `_run_3d_stack` 的规范 cfg 模板（Gyroid 7.0/0.5, Shanghai 0.182×0.042×0.042 m），供 demo/smoke 共用，避免几何默认值漂移多处不同步；**`_golden_3d.py` 故意不用它**（gate 要与被测代码零共享）。仍可跑（被 5 个脚本 import）。 |
| `_smoke_boot.py` | `get_app()` — 在任何 PySide6 import 前设 `QT_QPA_PLATFORM=offscreen` + 包根入 `sys.path`；所有 `smokes/*.py` 的强制导入顺序前提。仍在用。 |
| `benchmark_simpler_2d.py` | SIMPLE vs SIMPLER 2D 耦合性能基准（40×80、80×160 两网格），附 cProfile 阶段占比。openspec `simpler-coupling-2d` 任务 1.2/4.1 的产出脚本，可跑，非 CI 门。 |
| `benchmark_sou_3d.py` | 3D 动量二阶迎风 (SOU) 开/关网格收敛对比，固定 K/c_F 隔离对流格式本身。openspec `solver-efficiency-r1-r4` 任务 4.3，可跑。 |
| `polygon_calc.py`（430 行） | **生产入口**：多边形域 CFD 编排，`run_polygon_calculation(window)` 拆 4 阶段（`_parse_inputs` → `_build_fields` → `_run_solvers` → `_store_results`）。详见「公开接口」。 |
| `run_3d_qnehvi_fast.py` | 3D qNEHVI Pareto 快速跑：`evaluator_3d.evaluate_design_3d` 接入 `optimizer_qnehvi.run_qnehvi`，Shanghai Nz=10 校验工况；n_init=32/n_iter=80/q_batch=2，注释估计 ~13 s/eval、总 45–75 min。可跑。 |
| `run_m1_uniform_vs_graded.py`（351 行） | **M1 里程碑**：均匀 (L,t) 网格扫掠 vs 16 维连续场 qNEHVI 的 Pareto 对照（`ZONED-OPTIMIZATION-PLAN-CN.md` §六）。导出 `run_uniform_sweep`/`hv_2d_max`/`dominated_fraction`/`steepest_gradients`/`CFG_M1` 供 `run_m2_rerank_m1.py`、`run_port_dim_retest.py` 复用。`--fast`/`--ctrl {4,6}`/`--saas`/`--seed` CLI。可跑，需 `PYTHONHASHSEED=0`。 |
| `run_m2_rerank_m1.py` | **M2 门 3**：用 VANS 修正后的评估器重跑 M1 graded Pareto 解，量化 (Q,dP) 排名漂移；直接 import `run_m1_uniform_vs_graded.CFG_M1`。可跑。 |
| `run_port_dim_retest.py`（256 行） | **IDEA-PORT-DIM 复测**：端口 BC（Park 2026 Fig.4 类比，方形域+单端口对角交叉）下重新检验高维 ε 场是否有收益；复用 `run_m1_uniform_vs_graded` 的 `run_uniform_sweep` 等函数，前提 `per_cell_K=True` + `symmetric_y=False`（32/72 维）。`--ctrl {4,6} --seed N [--fast]`。可跑，结论限定为维数相对比较，非绝对 Q/dP 标定值。 |
| `run_production_qnehvi.py` | **生产级 2D 优化入口**：`optimizer_qnehvi.run_qnehvi`，n_init=32/n_iter=24/q_batch=2/seed=42，`n_rho_loops=3`（可压缩 ρ(T) 耦合开）、`dp_cap_pa=1e6`、`penalty_enabled=True`。输出 `opt_runs/production_v1/`。估计 45–75 min。 |
| `run_production_qnehvi_parallel.py` | 生产 v3 多种子并行版：`optimization.parallel_runner.run_qnehvi_multiseed`，默认 3 seeds × q_batch=4 = 12 并发 SIMPLE 求解，CLI `--seeds/--n_init/--n_iter/--q_batch/--n_jobs/--tol/--rho_loops`。输出 `opt_runs/production_v3_<timestamp>/`。 |

### `_out/`（gitignored，本地 golden gate）

| 文件 | 用途 |
|---|---|
| `_golden_2d.py` | 2D `Pipeline2D` 位级回归门：跑 `air_air`/`water_b` 两个 `ComputeConfig` 场景，比对标量 + 字段 SHA-256。`python -u runs/_out/_golden_2d.py [file.json \| --check file.json]`。 |
| `_golden_3d.py` | 3D `_run_3d_stack` 位级回归门：`air_air`/`water_b`/`asym_b`（`delta_levelset=0.6`）三场景。同样 capture/`--check` 用法。`.claude/commands/check.md:36-40` 记录了标准调用序列。 |

### `archive/`（冻结诊断，多数带 ⚠ ARCHIVAL 头注）

| 文件 | 用途 / 状态 |
|---|---|
| `cross_check_water_nu.py` | 水侧 Nu 关联式交叉核对：Wakao-Kaguei / Dittus-Boelter / Yan[6] 与本项目 `nu_water_from_Re`（Pr-替换）对照，出 PNG+CSV。未标 ARCHIVAL，理论仍可跑（依赖 `data/raw_data/`，worktree 下可能缺失）。 |
| `diag_ab_imbal.py` | Shanghai 砖形 3D、`T_inB=342K` 场景下 4 种能量指标（Q_A_enth/Q_B_enth/Q_sA_int/Q_sB_int）不平衡诊断。未标 ARCHIVAL，可跑；依赖 `runs._case_template.build_cfg`。 |
| `diag_df_model_zoo.py` | D-F 系数代理模型「动物园」对比（RBF/GP/Huber 等）在 LOO/LOLO/Shanghai 三种指标下的表现，纯实验不影响生产默认值。可跑。 |
| `diag_rbf_feature_ablation.py` | `SurrogateV3` 特征空间消融（原始 vs z-score 标准化 vs 降到 (L,t) 两特征）。可跑，纯诊断。 |
| `diag_shanghai_3d_n20_case1.py` | **⚠ ARCHIVAL**（2026-05-14 历史快照）：Shanghai case1 3D 20³ 网格字段导出诊断，所查 bug（ε 双减半/partial-B ghost/mass-flow）已修复（commits 02f091c / d80fbb1）。仅供参考，不建议常规重跑。 |
| `diag_shanghai_3d_n20_render.py` | **⚠ ARCHIVAL** 同批次；PyVista 体渲染。**导入路径已失效**：`from runs.diag_shanghai_3d_n20_case1 import (...)`（`archive/diag_shanghai_3d_n20_render.py:24`）指向 `runs.diag_shanghai_3d_n20_case1`，但该模块已随本次目录整理迁至 `runs.archive.diag_shanghai_3d_n20_case1` ——**当前会 `ModuleNotFoundError`**（未验证是否有人已手工改过，本次核查未见更新）。 |
| `diag_shanghai_flow_topology.py` | **⚠ ARCHIVAL** 同批次；流场拓扑审计（对角交叉 vs Brinkman 过度均质化）。同一历史问题已修复，仅参考。 |
| `diag_shanghai_partial_b_compare.py` | **⚠ ARCHIVAL** 同批次；`partial_B_closure='none'` vs `'per_cell_chi_b'` 的 ghost-heating 对比。仅参考。 |
| `nu_eps_vs_dhl_diag.py` | 诊断现行 Nu 关联式 `(D_h/L)` 能否用 ε 替换；结论（2026-06-05，脚本注释内）：对称数据 `corr(ε, D_h/L)≈0.999` 共线，分不出谁是真驱动，**不改生产**。可跑（依赖 `data/raw_data/试验记录表_整理版.xlsx`）。 |
| `phase_b_postprocess.py` | **⚠ 不可直接跑**：输入 CSV `validation/limit_cases_3d_air_air.csv` 已不存在（生成它的驱动脚本已废弃）；仅保留 LTE 门重分类逻辑供参考。 |
| `validate_d76_3d.py` | D_7_6 试样 3D dP 验证门（Diamond L7/t0.6，17 组 Re 423–8069）；`predict.py _OVERRIDES` cF=454.3 标定后 RMSRE ~14%。**头注 usage 字符串已过期**：写的是 `python -m validation.cases.validate_d76_3d`，但仓库里并无 `validation/cases/validate_d76_3d.py`（已核实不存在），该模块实际只存在于 `runs/archive/` 下；若要跑需按其真实位置 `python -m sjtu_tpmshx.runs.archive.validate_d76_3d` 调用（未验证是否仍可正常执行）。 |

### `demos/`

| 文件 | 用途 |
|---|---|
| `demo_3d_air_air.py` | 3D air-air 演示：直接调 `pipelines.stages_3d._run_3d_stack`（不经 Qt），用 `_case_template.build_cfg(Nx=30, Ny=20, Nz=5)`，打印 Q/ΔT/dP 等指标 + Agg 后端 PNG。可跑。 |
| `demo_3d_cube_air_air.py` | 同上但真立方体 50×50×50 mm、20³ 网格，用于对比 4.3:1:1 砖形与等长流程的 LTNE 差异。可跑。 |
| `demo_3d_cube_volume.py` | 用 PyVista 离屏体渲染（volume/triple-slice/iso）复用 `demo_3d_cube_air_air.build_cube_cfg`。需设 `PYVISTA_OFF_SCREEN=true`（脚本已在 import 前设置）。可跑。 |
| `demo_vis_3d_interactive.py` | PyVista **交互窗口**（非离屏），Shanghai case8 字段 + 可拖拽切片；键盘控制 `f`/`1`/`2`/`3`/`s`/`r`/`q`；支持 `--test`（离屏冒烟）/ `--real-aspect`。需要真实显示环境，服务器上默认只能用 `--test`。 |

### `diagnostics/`（asym-porosity 几何 Phase-0/0.5，纯几何无 CFD）

| 文件 | 用途 |
|---|---|
| `asym_a0_convergence.py` | 极端偏移 δ 下 A0（界面面积）网格收敛诊断：voxel vs marching-cubes、Richardson 3-网格外推。可跑。 |
| `asym_geometry_report_html.py` | 读 `asym_geometry_scan` 产出的 CSV → 自包含 HTML（手绘 SVG）报告，输出到桌面固定路径 `C:\Users\ALEX\Desktop\...html`（Windows 路径写死）。 |
| `asym_geometry_scan.py` | Phase 0 驱动：扫偏移 δ，测 ε_A/ε_B/A0/D_h/壁厚/z 方向连通性，出 CSV + 闸门判定，输出到 `runs/_out/asym_geom_scan_2026-06-05.csv`。 |
| `asym_porosity_preview.py` | 生成「不同 δ 孔隙率分配」预览图（base64 内嵌），写入桌面 HTML 占位符 `C:\Users\ALEX\Desktop\...html`（Windows 路径写死）。 |
| `asym_target_scan.py` | Phase 0.5：给定目标 (A%, B%, solid%) 反解 (C, δ)，出每侧 ε/A0/D_h + 连通性判定。可跑。 |

### `smokes/`（UI / 管线端到端离屏冒烟）

| 文件 | 用途 |
|---|---|
| `smoke_3d_eval.py` | 计时 `evaluate_design_3d` 单次评估（fast-mode 预设 Nx=30,Ny=12,Nz=6,max_outer=2），据此估算 BO 预算是否可行（≤5 min/eval 判据）。 |
| `smoke_ui_2d_pipeline.py` | 离屏端到端 2D 计算冒烟：起 `Main_Menu` → 自动填充双流体 → 强制 2D → 走真实 Compute 路径（`run_calculation → ComputeOrchestrator → Pipeline2D → write_result → finalize_plots`），自动应答所有 QMessageBox（含实例级 `.exec()` monkeypatch，脚本注释记载曾因漏补丁挂起 20 分钟）。 |
| `smoke_ui_3d_modes.py` | 3 种粗糙度模式（baseline/norris_1a/bhatti_shah_1b）对比 + water-B 路径粗糙度跳过校验，直调 `_run_3d_stack`。 |
| `smoke_ui_3d_pipeline.py` | 离屏端到端 3D 计算冒烟，同 2D 版但走 `_run_calculation_3d`；强制 `TPMSHX_EAGER_3D_SLICES=1` 让 2D 中切片渲染器离屏也跑（PyVistaQt 体渲染面板本身无法离屏初始化，脚本容忍此失败）。 |
| `smoke_ui_offscreen.py` | 基础 Qt 离屏冒烟：构造 `Main_Menu`、枚举按钮、切 tab、点几个非破坏性按钮，捕获未处理异常。 |
| `smoke_ui_screenshots.py` | 离屏截图：全窗口 + 切 2D/3D 模式后的窗口截图，写入 `vault/diagrams/ui_screenshots_2026-05-13/`（Windows 相对路径，写死日期目录名）。 |

### `tools/`

| 文件 | 用途 |
|---|---|
| `asym_build_cfd_design_xlsx.py` | Phase-1 asym-porosity CFD **设计矩阵** → 样式化 Excel（`runs/_out/asym_cfd/asym_cfd_design_matrix.xlsx`）；Diamond/Gyroid、L=5mm/t=0.4mm、split r∈{1,1.5,...,3.5}。 |
| `asym_build_cfd_worklist_xlsx.py` | Phase-1 CFD **工况簿**（复用既有 water-cfd-raw 域约定），输出到工作区级目录 `D:/Postgraduate/asym-porosity-data/asym_cfd_worklist.xlsx`（Windows 绝对路径写死，workspace 级 gitignore）。 |
| `asym_plan_to_html.py` | 把 vault 里的 Markdown 计划文档渲染成学院模板 HTML（base64 内嵌图片，读写路径均为 Windows 绝对路径写死：`D:\Postgraduate\vault\...` / `C:\Users\ALEX\Desktop\...`）。 |
| `homogenize_chi_s.py` | 单胞周期均质化数值求解 TPMS 骨架有效热导率 χ_S（闭合 `solvers/tpms_props.py` 里的 TODO）；`--selftest` / `--sweep` 两个 CLI 模式，含全固体/层合上下界/三轴各向同性自检。 |
| `plot_grid_convergence.py` | 重新生成 README 用的 `assets/grid-convergence.png`（A1 网格收敛研究，16³→128×64×32 全轴 r=2 加密），读取 `validation/cases/validate_shanghai_3d_real.py --suffix` 产出的按网格 CSV。 |
| `render_3d_styles.py` | 3D 输出「样式展览」：per-field 生成 publication_4panel/presentation_large/volume_tuned/iso_3level PNG + rotate.mp4 + interactive.html，示范 5~6 种渲染风格。 |

### `cfd_asym/`（跑在另一台 CFD 机器上，PyFluent）

| 文件 | 用途 |
|---|---|
| `asym_ntop_expressions_html.py` | 生成 nTop Evaluate-Expression 表达式（φ 场公式 + solid/void_A/void_B 布尔式）的离线 HTML，输出到 `C:\Users\ALEX\Desktop\asym-ntop-expressions.html`（Windows 路径写死）。 |
| `asym_postproc_kappa.py` | Phase-1 asym-porosity CFD **后处理**：读 PyFluent 结果 CSV → 按 (tpms,split,side) 拟合 Darcy-Forchheimer (K,c_F) → 相对对称锚点算 κ 自比值表；CLI `results.csv [--register]`（`--register` 写入 `kappa_asym.set_kappa_table`）。 |
| `asym_pyfluent_runner.py` | Phase-1 asym-porosity **CFD 批跑编排骨架**：`import ansys.fluent.core as pyfluent`，本仓库环境不含该依赖，**只在 CFD 机器上跑**（脚本自注「orchestration skeleton — runs on the Fluent machine, not here」）。CLI `--worklist --mesh-dir --out --procs`。 |

## 公开接口

- `run_polygon_calculation(window) -> None` — `sjtu_tpmshx/runs/polygon_calc.py:22`；调用方 `sjtu_tpmshx/ui/mixins/run_controller.py:344`。内部按 4 阶段私有函数 `_parse_inputs`/`_build_fields`/`_run_solvers`/`_store_results` 编排（同文件），是本目录唯一的生产级公开入口。
- `build_cfg(*, tpms_type='Gyroid', Lcell=7.0, t_wall=0.5, ..., **overrides) -> dict` — `sjtu_tpmshx/runs/_case_template.py:22`；调用方：`demos/demo_3d_air_air.py:24`、`demos/demo_3d_cube_air_air.py:23`、`demos/demo_3d_cube_volume.py:31`、`smokes/smoke_ui_3d_modes.py:16`、`archive/diag_ab_imbal.py:34`。`_out/_golden_3d.py` **不** 使用它（`_case_template.py:8-10` 注明是刻意隔离）。
- `get_app() -> QApplication` — `sjtu_tpmshx/runs/_smoke_boot.py:17`；调用方全部 `smokes/*.py`（`smoke_ui_2d_pipeline.py:35` 等）；模块导入本身（`import runs._smoke_boot`）先于任何 PySide6 import 完成，才能让 `QT_QPA_PLATFORM=offscreen` 生效（`_smoke_boot.py:13`）。
- `run_uniform_sweep(cfg, L_vals, t_vals, n_jobs) -> np.ndarray`、`hv_2d_max(front_QdP, ref) -> float`、`dominated_fraction(uni_front, grad_front) -> float`、`steepest_gradients(X_pareto, cfg) -> dict`、`CFG_M1: dict` — 均在 `sjtu_tpmshx/runs/run_m1_uniform_vs_graded.py`（分别 96/119/136/149 行附近，`CFG_M1` 49 行）；调用方：`run_m2_rerank_m1.py:26`（`CFG_M1`）、`run_port_dim_retest.py:53-55`（4 个函数）。
- `main(cases, path, check) -> None`（隐式，`_out/_golden_2d.py:77` / `_out/_golden_3d.py:87`）— CLI 位级回归门，`python -u runs/_out/_golden_2d.py [file] [--check file]`；`_capture(cfg)`（`_golden_2d.py:65`）/ `_capture(label, cfg)`（`_golden_3d.py:76`）对每个标量字段做 SHA-256 哈希比对，非其他脚本的可复用接口。
- `mesh_path(mesh_dir, tpms, split_r, side) -> Path` — `sjtu_tpmshx/runs/cfd_asym/asym_pyfluent_runner.py:35`；仅本文件内部使用，供 CFD 机器上跑时定位 nTop 导出的网格文件命名约定 `{tpms}_r{split_r:g}_{side}.msh`。

## 关键配置项与开关

- `QT_QPA_PLATFORM=offscreen` — 默认由 `_smoke_boot.py:13` 的 `os.environ.setdefault` 设置；所有 `smokes/*.py` 依赖此项在服务器无显示环境下跑通。
- `TPMSHX_EAGER_3D_SLICES=1` — `smokes/smoke_ui_3d_pipeline.py:19` 主动设置，强制 `finalize_plots_3d` 跑 2D 中切片渲染（否则该分支惰性跳过）。
- `PYVISTA_OFF_SCREEN=true` — `demos/demo_3d_cube_volume.py:18`、`tools/render_3d_styles.py:21` 在 `import pyvista` 前设置；`pv.OFF_SCREEN = True` 双保险同一行下方再设一次。
- `TPMSHX_DF_OVERRIDES=0` — `archive/validate_d76_3d.py:13` 文档提到用它复现"未标定覆盖"下的失败模式（67.4% RMSRE），验证 `df_surrogate/predict.py` 的 `_OVERRIDES` 表确实是必需修正，非本文件定义，只是调用点。
- `n_rho_loops`（默认 3，生产优化脚本硬编码）— `run_production_qnehvi.py:41`、`run_m1_uniform_vs_graded.py:62`、`run_port_dim_retest.py:76` 均显式设为 3，注释标注"compressible baseline (hard invariant)"，呼应 `CLAUDE.md` 的可压缩硬不变量。
- `dp_cap_pa=1.0e6` / `reject_unconverged=False` / `penalty_enabled=True` — 生产优化三件套（`run_production_qnehvi.py:45-47`、`run_3d_qnehvi_fast.py:69-71`），BO 侧对不收敛/极端 dP 设计的容错与罚分开关。
- `--ctrl {4,6}` — `run_m1_uniform_vs_graded.py:167`、`run_port_dim_retest.py`（复用）：控制网格切分 4×4(=16维)/6×6(=36维)，M3 门2 用来测高维退化。
- `per_cell_K=True` / `symmetric_y=False` — `run_port_dim_retest.py:85-86`，注释标注"缺一不可"的实验前提（逐胞横向阻力 + 破坏 y 镜像对称使决策维数翻倍）。
- `sweep_profile='fast_sweep'` / `use_adaptive_amg_tol=True` — `smokes/smoke_ui_3d_modes.py:35-36`，仅该冒烟使用的加速开关，非全局默认（未在本次范围内验证其在 `pipelines/` 里的实现细节，标记未验证）。

## 边界·假设·适用范围

- 单位约定沿用全仓惯例：几何 L/t 常以 **mm** 传参（如 `build_cfg(Lcell=7.0, t_wall=0.5)`——`_case_template.py:22-23`），域尺寸 L/H/Lz 与压力/温度用 SI（m/Pa/K）；混用是常见坑（`CLAUDE.md` Gotchas 已提示）。
- 速度均为**interstitial**（孔隙内）速度，所有 `u_A`/`u_B` 参数（如 `run_m1_uniform_vs_graded.py:56-57` 的 10.0/5.0 m/s）不可与 superficial 速度混用。
- `runs/archive/` 下带 `⚠ ARCHIVAL` 头注的 4 个诊断脚本（`diag_shanghai_3d_n20_case1.py`、`diag_shanghai_3d_n20_render.py`、`diag_shanghai_flow_topology.py`、`diag_shanghai_partial_b_compare.py`）所调查的历史 bug（ε 双减半 / partial-B ghost-heating / mass-flow）**均已在生产代码修复**（commits 02f091c / d80fbb1，据脚本头注，未在本次任务范围内逐一回溯 diff 验证——标记未验证但头注一致且来自 4 个独立文件，可信度较高）；这些脚本的数值结论不代表当前代码行为。
- `phase_b_postprocess.py` 依赖的输入 CSV 在当前 checkout 下**确认不存在**（`ls`/`find` 已核实 `validation/limit_cases_3d_air_air.csv` 缺失），不可直接运行。
- `archive/validate_d76_3d.py` 头注里的运行命令 `python -m validation.cases.validate_d76_3d`（第 19 行）与文件实际所在包路径不符——**已核实** `sjtu_tpmshx/validation/cases/` 下无 `validate_d76_3d.py`，该文件只存在于 `runs/archive/`；按当前路径应为 `python -m sjtu_tpmshx.runs.archive.validate_d76_3d`（此路径本身能否跑通未验证，`archive/` 无 `__init__.py`，依赖 Python 3 隐式命名空间包机制）。
- 桌面/vault 绝对路径写死是本目录多个脚本的通用模式（非 bug，是作者本机工作流的既有约定）：`C:\Users\ALEX\Desktop\...html`（`diagnostics/asym_geometry_report_html.py:10`、`diagnostics/asym_porosity_preview.py:26`、`cfd_asym/asym_ntop_expressions_html.py:29`）、`D:\Postgraduate\vault\...`（`tools/asym_plan_to_html.py:18-19`）、`D:/Postgraduate/asym-porosity-data/...`（`tools/asym_build_cfd_worklist_xlsx.py` 头注第 20 行）——移植到服务器时这些路径**必须改写**，否则脚本会尝试写入不存在的 Windows 盘符。
- `cfd_asym/asym_pyfluent_runner.py` 硬依赖 `ansys.fluent.core`（PyFluent），本仓库/服务器环境按 `CLAUDE.md` 明确不装 Fluent；该脚本**设计上就不在本仓库环境执行**，只是把编排代码托管在这里。
- `demos/demo_vis_3d_interactive.py` 默认需要真实显示环境（非 `--test` 模式），服务器无头环境下只能用 `--test`（离屏冒烟分支，未在本次核查中逐行验证其离屏路径是否覆盖全部功能）。

## 可扩展接口

- **cfg-override 模式**：`_case_template.build_cfg(**overrides)`（`_case_template.py:34/62`）把任意额外关键字原样落进 cfg dict（`cfg.update(overrides)`），是 `sweep_profile`/`partial_B_closure`/加速 flag 等实验性开关的统一注入点，新脚本可继续用这个模式而不用改模板签名。
- **`evaluator_fn` 注入**：`run_3d_qnehvi_fast.py:96` 把 `evaluate_design_3d` 作为 `evaluator_fn` 参数传给 `optimizer_qnehvi.run_qnehvi`，说明该优化器主循环支持替换评估器（2D `evaluate_design` vs 3D `evaluate_design_3d`）——为后续新增评估器（如更高保真度求解）留了挂点（具体 `run_qnehvi` 签名细节属于 `optimization/` 模块，未在本次范围内核实全部形参）。
- **κ 表注册钩子**：`cfd_asym/asym_postproc_kappa.py` 的 `--register` CLI flag（第 26 行文档）把拟合出的 κ(r) 表写入 `kappa_asym.set_kappa_table`（`solvers/kappa_asym`，未在本模块范围内核实其函数签名），是外部 CFD 标定数据接入生产求解器的注册点。
- **DF 代理模型可插拔**：`archive/diag_df_model_zoo.py` 里的 `ZOO` 列表（模型工厂函数集合）演示了 `SurrogateV3`-兼容接口可以被任意 `.fit(ref)`/`.predict(query)` 的实现替换而不改调用方代码，是 `df_surrogate` 后端切换机制在脚本层的验证样例（非生产开关本身，生产开关是 `df_surrogate/predict.py` 的 `_DF_DEFAULT`）。
- **粗糙度模式并列**：`smokes/smoke_ui_3d_modes.py` 的 `run_with_mode(label, mode, eps_um=100, **kw)`（第 40 行起）把 `roughness_mode` 作为字符串开关传入 `_run_3d_stack`，示范新增粗糙度模型只需在 `solvers/roughness.py` 里注册新分支 + 在此脚本加一行调用。

## 已知不足与 TODO

- **确认的死链接导入**：`archive/diag_shanghai_3d_n20_render.py:24` `from runs.diag_shanghai_3d_n20_case1 import (...)` —— 该模块实际路径是 `runs.archive.diag_shanghai_3d_n20_case1`（本次目录整理后的位置），当前直接跑会 `ModuleNotFoundError`（未实测执行，但路径不存在是确认事实：`find sjtu_tpmshx/runs -name diag_shanghai_3d_n20_case1.py` 只在 `archive/` 下命中一份）。
- **`phase_b_postprocess.py` 不可直接跑**：依赖的 `validation/limit_cases_3d_air_air.csv` 已确认不存在于当前 checkout；头注自己也承认（第 3-8 行）"kept for reference... not runnable as-is"。
- **`archive/validate_d76_3d.py` 头注 usage 过期**：写的模块路径 (`validation.cases.validate_d76_3d`) 不存在，真实位置是 `runs/archive/`；未验证按新路径能否跑通（依赖的 `validation.cases.validate_shanghai_3d_real`、`validation.harness._case_sets` 是否仍导出同名符号本次未核实）。
- **`solvers/tpms_props.py` 的 χ_S TODO**：`tools/homogenize_chi_s.py` 头注称"closing the TODO at solvers/tpms_props.py CHI_S"，本次范围未进入 `solvers/` 核实该 TODO 当前状态（是否已切换为调用 `homogenize_chi_s.py` 的产出、还是仍是文献值占位）——**未验证**，值得下一个负责 `solvers/` 模块的核查者确认。
- **`archive/` 内多个脚本无 ARCHIVAL 头注但同样是一次性诊断**（`cross_check_water_nu.py`、`diag_ab_imbal.py`、`diag_df_model_zoo.py`、`diag_rbf_feature_ablation.py`、`nu_eps_vs_dhl_diag.py`）：目录约定（`PROJECT_MANUAL.md:634`「一次性诊断脚本冻结在 runs/archive/」）与脚本自身状态不完全一致——这几个理论上仍可跑，但缺少统一的"是否仍代表当前生产行为"标注，容易被误当作权威结论引用。
- **`PROJECT_MANUAL.md` 6.11 节的文件清单已过期**：对照实际 49 个文件，`run_m1_uniform_vs_graded.py`/`run_m2_rerank_m1.py`/`run_port_dim_retest.py`（M0-M4 优化器路线图相关，`optimizer-roadmap` 记忆条目）、`tools/homogenize_chi_s.py`、`tools/plot_grid_convergence.py`、`archive/` 下多份诊断脚本均未列入 `PROJECT_MANUAL.md:636-648` 的表格——本文档可视为该节的补全/更新素材。
- **`diagnostics/` 与 `archive/` 命名边界的历史遗留**：`diagnostics/asym_*` 系列（几何 Phase-0/0.5）与 `archive/diag_*` 系列（Shanghai 历史 bug 诊断）功能上都是"诊断脚本"，但前者是当前 asym-porosity 工作的活跃产出、后者是冻结历史快照——目录名 `diagnostics/` vs `archive/` 承担了这个区分，命名本身未在代码里强制，纯约定（不是缺陷，但移植时容易被按字面误合并）。

## 服务器移植注意

- **Windows 绝对路径写死**（详见「边界」节列出的具体文件行号）是本目录最大的移植障碍：`C:\Users\ALEX\Desktop\*.html` 输出（3 处）、`D:\Postgraduate\vault\...` 读入模板（1 处）、`D:/Postgraduate/asym-porosity-data/...` 输出（1 处）——移植前必须逐一改成 Linux 路径或改造成可配置的 CLI 参数/环境变量，否则脚本会在写文件那一步直接抛 `FileNotFoundError`（父目录不存在，Windows 盘符不存在）。
- **PySide6 (Qt) 依赖**：`polygon_calc.py`（`from PySide6.QtWidgets import QApplication, QMessageBox`）、全部 `smokes/*.py`、`_smoke_boot.py` 都硬依赖 PySide6；无显示环境的 Linux 服务器上必须保证 `QT_QPA_PLATFORM=offscreen` 生效（`_smoke_boot.py` 已处理，但顺序敏感——必须在任何 `PySide6` import **之前** 完成，其余脚本若自行 import Qt 需照抄这个模式）。`polygon_calc.py` 本身不设置该变量（它假设由调用方/GUI 主进程已经在正常窗口环境里跑），服务器上若要单测这条链需要额外包一层类似 `_smoke_boot` 的引导。
- **PyVista 3D 渲染依赖 VTK 的离屏/GPU 后端**：`demos/demo_3d_cube_volume.py`、`demos/demo_vis_3d_interactive.py`、`tools/render_3d_styles.py`、`archive/diag_shanghai_3d_n20_render.py` 均用 `pyvista`；Linux 服务器上离屏渲染通常需要装 `xvfb` 或 VTK 的 OSMesa 软件渲染后端，`PYVISTA_OFF_SCREEN=true` 只是告诉 PyVista 不要开真实窗口，不代表底层 OpenGL/Mesa 依赖已经满足（未验证当前 CI/Linux 环境是否已装好；`memory/ci-linux-ui-hang-onboarding.md` 提到过 offscreen guard + shiboken 生命周期坑，是相关的既有教训）。
- **`ansys.fluent.core` (PyFluent) 依赖**：`cfd_asym/asym_pyfluent_runner.py` 顶层 `import ansys.fluent.core as pyfluent`——这个 import 本身在没装 PyFluent 的机器上会在**模块加载时**就失败（不是函数调用时才失败），所以哪怕只是想 `import` 这个文件做静态分析也需要先装或者跳过它；生产服务器按项目约定本就不装 Fluent（`CLAUDE.md`：本项目求解器与 Fluent 无关），此脚本注定只能在专门的 CFD 机器上跑，移植时应直接跳过/隔离，不必费力适配。
- **`sys.path` 手工 bootstrap 而非包安装**：几乎每个脚本头部都有形如
  `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
  的手工路径注入（层数因子目录深度不同：根目录脚本 2 层 `dirname`，`archive/`/`demos/`
  等子目录脚本 3 层，`tools/`/`diagnostics/` 用 `Path(__file__).resolve().parents[2]` 等价写法）——
  这是 `PROJECT_MANUAL.md:654` 提到的 Batch-5（2026-06-10）重构遗留约定：`poc/`/`benchmarks/`/
  `examples/`/`opt_runs/` 迁出包外后，脚本靠自举 `sys.path` 而非 `pip install -e .` 定位
  `sjtu_tpmshx` 包根。移植到 Linux 时目录层数不变则这些相对 `dirname`/`parents[N]` 计算应该
  照常工作（纯路径运算，无 Windows 特定 API），但若移植时**改变了 `runs/` 相对包根的嵌套深度**
  （例如拍平子目录），所有这些硬编码层数都要重新核对。
- **编码**：`archive/diag_df_model_zoo.py:31` 等脚本显式 `sys.stdout.reconfigure(encoding="utf-8")`
  以应对 Windows 控制台默认 GBK 编码打印中文/希腊字母乱码；Linux 服务器终端通常默认 UTF-8，
  这行在 Linux 上是无害空操作，不需要删除也不会出问题。
- **并行/线程环境变量**：`run_production_qnehvi_parallel.py` 头注（第 5 行）要求
  "OMP/MKL thread caps = 1 to prevent BLAS oversubscription"；**脚本本身**确实未见对应赋值，
  但该要求由其调用的 `optimization/parallel_runner.py` 落实——`_set_thread_caps()`（约第 44
  行）在每个 seed 子进程入口 `_seed_subprocess_main` 里、导入 numpy/scipy 重型依赖**之前**对
  `OMP_NUM_THREADS`/`MKL_NUM_THREADS`/`OPENBLAS_NUM_THREADS`/`NUMEXPR_NUM_THREADS` 做
  `os.environ.setdefault(...,'1')`，头注与实现并不矛盾，只是落地在被调用模块而非本脚本文件内。
