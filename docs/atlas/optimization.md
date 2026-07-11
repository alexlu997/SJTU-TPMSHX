# optimization
生成日期 2026-07-10，基于 commit f33d30e 附近的 master。

> 溯源约定：所有 `file:line` 相对仓库根的 `sjtu_tpmshx/` 包目录（如 `optimization/evaluator.py:404` 即 `sjtu_tpmshx/optimization/evaluator.py` 第 404 行）。所有断言均已在代码中核实；无法核实处明确标注「未验证」。

## 定位与功能

`sjtu_tpmshx/optimization/` 是连续场 TPMS 换热器设计的多目标贝叶斯优化（BO）栈，共 6 个文件，四层结构：

1. **单设计评估器**：`evaluator.py`（2D）把 16 维决策向量解码为 L(x,y)/t(x,y) 连续场，跑 SIMPLE×2（双流体）+ LTNE 能量方程 + 变密度外循环，返回 `(−Q, dP, mass)`；`evaluator_3d.py`（3D）以相同返回契约包装 `core.evaluators.evaluate_3d`。
2. **BO 引擎**：`optimizer_qnehvi.py` 用 BoTorch qNEHVI（q-Noisy Expected Hypervolume Improvement）驱动双目标（最大化 Q、最小化 dP）优化，含 Sobol 初始化、GP 拟合、HV 平台早停、CSV checkpoint。
3. **多种子编排**：`parallel_runner.py` 用 `ProcessPoolExecutor`（spawn）并行跑 M 个独立 BO 种子并合并 Pareto 前沿。
4. **下游导出**：`export_ntop_csv.py` 把 Pareto 解转成 nTop「Scalar Field from Grid Data」可摄入的 L/t 场 CSV。

定性约束（`domain/compute_config.py:198-204`，`OptimizerConfig` docstring）：本模块的评估预算是 **cheap screening**，产出的是设计**排名（rankings）**而非可引用数值；最终 Pareto 选点必须经生产管线（遵守 `SolverConfig`）重算。

## 文件一览

| 文件 | 职责 |
|---|---|
| `optimization/__init__.py` | 空文件（0 字节），仅作包标记。 |
| `optimization/evaluator.py` | 2D 连续场单设计评估器：决策向量 → SIMPLE×2 + LTNE + ρ(T) 外循环 → `(−Q, dP+penalty, mass)`；含 `DEFAULT_CONFIG`、port-BC / per_cell_K / cf_aniso 旋钮、病态设计 dp_cap 拒绝。共 661 行。 |
| `optimization/evaluator_3d.py` | 3D 评估器：包装 `core.evaluators.evaluate_3d`（沿 z 拉伸 2D 场），Q 归一化为 W/m 使 3D Pareto 与 2D 同轴可比；含 `DEFAULT_CONFIG_3D` fast-mode 预设。共 155 行。 |
| `optimization/optimizer_qnehvi.py` | qNEHVI BO 主循环：Sobol 初始化 → 每目标一个 GP（SingleTaskGP 或 SAAS）→ `optimize_acqf` 选候选 → 批量评估（可 joblib 并行）→ HV 追踪 + 早停 + Pareto CSV。共 554 行。 |
| `optimization/parallel_runner.py` | 多种子编排器：M 个 spawn 子进程各跑一个 `run_qnehvi` 种子，末端 `_merge_paretos` 取并集非支配前沿；含 CLI。共 283 行。 |
| `optimization/export_ntop_csv.py` | Pareto 行 → nTop ScalarField CSV（`Lfield.csv`/`tfield.csv`，坐标 mm）+ `provenance.json`；含 CLI。共 291 行。 |

## 公开接口

### evaluator.py
- **`DEFAULT_CONFIG: dict`** — `optimization/evaluator.py:88-195`。所有评估旋钮的单一默认源；`run_qnehvi` 以 `{**EVAL_DEFAULT_CONFIG, **(config or {})}` 合并（`optimization/optimizer_qnehvi.py:229`）。
- **`evaluate_design(x, cfg=None, fc=None, *, verbose=False, compute_cfg=None) -> (Q_neg, dP, mass)`** — `optimization/evaluator.py:404-408`。`x` 为 (16,) 决策向量（提供 `fc: ContinuousFieldConfig` 时被忽略，此时 `x` 可传 `None`，见 `optimization/evaluator.py:651-655` 冒烟用法）；`compute_cfg`（严格类型 `ComputeConfig`）的重叠字段垫底、显式 `cfg` dict 绝对优先（`optimization/evaluator.py:431-435`）。返回 `Q_neg = −Q`（W/m 深度）、`dP = dP_A+dP_B+制造性罚项`（Pa）、`mass`（kg/m）。调用方：`optimizer_qnehvi._eval_worker` 默认（`optimization/optimizer_qnehvi.py:67-68`）、`runs/run_m1_uniform_vs_graded.py:90`、`runs/run_m2_rerank_m1.py:49`、`tests/test_a3_conservative_ltne_2d.py:130`。
- `_compute_cfg_to_evaluator_dict(compute_cfg) -> dict` — `optimization/evaluator.py:374-401`。`ComputeConfig` → 评估器 flat dict 的映射；预算三键取自 **optimizer 块**：`compute_cfg.optimizer.max_iter_simple / tol_simple / outer_tol_K`（`optimization/evaluator.py:398-400`）。
- `_resolve_grid(cfg, fc)` — `optimization/evaluator.py:201-210`。`Nx/Ny=None` 时用场均值 (L,t) 的 `D_h` 走 `adaptive_grid`。被 `runs/run_m1_uniform_vs_graded.py:37` 跨模块引用。

### evaluator_3d.py
- **`DEFAULT_CONFIG_3D: dict`** — `optimization/evaluator_3d.py:42-73`。继承 `DEFAULT_CONFIG` 再叠 3D 专属键与 fast-mode 预算覆盖。
- **`evaluate_design_3d(x, cfg=None, *, compute_cfg=None) -> (Q_neg_per_m, dP_total, mass_per_m)`** — `optimization/evaluator_3d.py:103-154`。经 `core.evaluators.evaluate_3d` 中转（import 见 `optimization/evaluator_3d.py:36`；`core/evaluators.py:108` 为实现，`core/evaluators.py:54` 的 `__all__` 导出）。Q、mass 均除以 `Lz` 归一（`optimization/evaluator_3d.py:150-152`）。病态时**抛异常**，由 BO worker 捕获打 dp_cap（`optimization/evaluator_3d.py:18-19`）。调用方：`runs/run_3d_qnehvi_fast.py:96`（`evaluator_fn=`）、`ui/optimize_panel.py:694-696`、`runs/smokes/smoke_3d_eval.py:63`、`tests/test_audit_round2_fixes.py:70-90`。

### optimizer_qnehvi.py
- **`run_qnehvi(config=None, n_init=32, n_iter=24, q_batch=2, seed=42, verbose=True, save_dir=None, progress_cb=None, hv_tol=0.01, hv_window=3, n_jobs=1, evaluator_fn=None) -> dict`** — `optimization/optimizer_qnehvi.py:160-171`。返回 `{'X','F','history_X','history_F','n_evals','save_dir'}`，`F` 为 min-form `(−Q, dP)`（`optimization/optimizer_qnehvi.py:460-475`）。torch/botorch/gpytorch 在函数体内延迟 import（`optimization/optimizer_qnehvi.py:211-227`）。调用方：`runs/run_production_qnehvi.py:32`、`runs/run_port_dim_retest.py:206`、`runs/run_m1_uniform_vs_graded.py:304`、`runs/run_3d_qnehvi_fast.py:89`、`ui/optimize_panel.py:110`、`parallel_runner.py:79`。
- `_eval_worker(x, cfg, dp_cap, evaluator_fn=None) -> (Q, dP_clamped, err_or_None)` — `optimization/optimizer_qnehvi.py:55-81`。模块顶层（loky pickle 要求）；异常 / 非有限值 → `(1e-6, dp_cap, msg)`；dP clip 到 `[1.0, dp_cap]`（`optimization/optimizer_qnehvi.py:74`）。
- `progress: dict` / `request_cancel()` / `clear_cancel()` — `optimization/optimizer_qnehvi.py:87-106`。进程内全局进度（count/total/best_Q/phase/hv/hv_hist）与取消标志，UI 消费；BO 循环每迭代边界检查取消（`optimization/optimizer_qnehvi.py:343-346`）。
- `hv_plateau_detected(hv_hist, hv_tol, hv_window) -> bool` — `optimization/optimizer_qnehvi.py:132-144`。纯数值早停判据，暴露为模块级以便单测。
- `_pareto_mask_max(Y) -> mask` — `optimization/optimizer_qnehvi.py:112-129`。最大化语义非支配掩码，O(N²)；虽带下划线但被 `parallel_runner.py:110`、`runs/run_port_dim_retest.py:50`、`runs/run_m1_uniform_vs_graded.py:38` 跨模块使用。
- `_save_pareto_csv(path, X, F_min)` — `optimization/optimizer_qnehvi.py:147-154`。CSV 列约定 `x0..x{D-1},Q_W_per_m,dP_Pa`，是 `export_ntop_csv.export_pareto_row` 反解列数的依据。

### parallel_runner.py
- **`run_qnehvi_multiseed(config=None, n_seeds=3, seeds=None, n_init=32, n_iter=24, q_batch=4, n_jobs_inner=4, save_dir_base=None, hv_tol=0.01, hv_window=3, verbose=True) -> dict`** — `optimization/parallel_runner.py:141-151`。返回 merged `X/F/history_*/n_evals` 加 `seeds_used / per_seed_results / wall_time_s / save_dir`。种子默认 `[42, 43, …]`（`optimization/parallel_runner.py:174-175`）。调用方：`runs/run_production_qnehvi_parallel.py:63`；CLI `python -m optimization.parallel_runner`（`optimization/parallel_runner.py:264-278`）。
- `_merge_paretos(seed_outputs)` — `optimization/parallel_runner.py:102-138`。各种子 Pareto 并集后按 `(Q, −log10 dP)` max-form 再做一次非支配筛选。
- `_seed_subprocess_main(...)` — `optimization/parallel_runner.py:56-99`。子进程入口：先 `_set_thread_caps()` 再重 import（`optimization/parallel_runner.py:72-74`）。单个种子失败仅告警不中断合并（`optimization/parallel_runner.py:206-210`）。

### export_ntop_csv.py
- **`export_decision_vector(x_decision, out_dir, *, Nx_export=100, Ny_export=50, L_domain_m=0.10, H_domain_m=0.05, tpms_type='Diamond', k_s=17.0, n_ctrl_x/n_ctrl_y/symmetric_y=默认, extra_metadata=None) -> dict`** — `optimization/export_ntop_csv.py:133-145`。写 `Lfield.csv`/`tfield.csv`/`provenance.json`。
- **`export_pareto_row(pareto_csv_path, row_index, out_dir, *, decision_dim_expected=None, **kwargs) -> dict`** — `optimization/export_ntop_csv.py:193-198`。决策维度按 `D = row.size − 2` 推断（2026-06-24 修复硬编码 16 的截断 bug，`optimization/export_ntop_csv.py:213-229`）。
- CLI：`python -m optimization.export_ntop_csv --pareto … --row N --out DIR --grid NX NY`（`optimization/export_ntop_csv.py:247-286`）。测试：`tests/test_export_ntop_csv.py`。

## 关键配置项与开关

### DEFAULT_CONFIG（2D，`optimization/evaluator.py:88-195`）
| 键 | 默认值 | 定义处 | 说明 |
|---|---|---|---|
| `L_domain` / `H_domain` | 0.10 / 0.05 m | `evaluator.py:90-91` | 实坐标 x=A 流向，y=B 流向 |
| `Nx` / `Ny` | None | `evaluator.py:92-93` | None → `adaptive_grid`（`evaluator.py:201-210`） |
| `grid_alpha` | 0.8 | `evaluator.py:94` | 自适应网格密度因子 |
| `tpms_type` / `k_s` / `rho_s` | 'Diamond' / 17.0 / 2700.0 | `evaluator.py:97-99` | |
| `u_A` / `u_B` | 10.0 / 10.0 m/s | `evaluator.py:102-103` | 间隙（interstitial）速度 |
| `T_inA` / `T_inB` | 350 / 300 K | `evaluator.py:104-105` | |
| `P_inA` / `P_inB` | 101325 Pa | `evaluator.py:106-107` | |
| `dir_A` / `dir_B` | 0（+x）/ 3（−y） | `evaluator.py:111-112` | 方向码 0=+x,1=−x,2=+y,3=−y |
| `ports_A` / `ports_B` | None | `evaluator.py:122-123` | None = 整面（full-face）进出口，M0–M3 实验条件；元组 `(in_lo,in_hi,out_lo,out_hi)` [m] 开启 port 型局部 BC |
| `per_cell_K` | False | `evaluator.py:129` | False=按行流向投影（M0–M3 所用）；True=逐格 (L,t)→(K,cF) 预测，port-BC 路由研究必需（`evaluator.py:124-128`、`evaluator.py:213-228`） |
| `cf_aniso` | 0.0 | `evaluator.py:139` | 斜向流 Forchheimer 方向因子 `cF_eff = cF·(1+cf_aniso·4nx²ny²)`；0=各向同性、逐位等同旧版（`evaluator.py:130-138`） |
| `max_iter_simple` / `tol_simple` | 5000 / 1e-3 | `evaluator.py:142-143` | 1e-3 有明确理由：交叉流 B 侧残差平台，收紧至 1e-5 导致 Sobol 探索期 100% 拒绝（`evaluator.py:143-152`） |
| `max_iter_energy` / `tol_energy` | 5000 / 0.5 K | `evaluator.py:153-154` | |
| `n_rho_loops` | 3 | `evaluator.py:155` | 1=等温 ρ 快路径；3=ConstDF-v1 基线，理想气体 ρ(T) 外循环（可压缩硬约束） |
| `drho_tol` / `rho_relax` | 0.01 / 0.7 | `evaluator.py:161-162` | 外循环收敛判据 / ρ Picard 欠松弛 |
| `n_ctrl_x` / `n_ctrl_y` / `symmetric_y` | 4 / 4 / True | `evaluator.py:165-167` ← `solvers/continuous_field.py:40-42` | 决策维 D = 2·n_ctrl_x·⌈n_ctrl_y/2⌉ = **16**（`solvers/continuous_field.py:56-65`） |
| `L_bounds` / `t_bounds` | (4.0, 8.0) / (0.3, 0.5) mm | `evaluator.py:168-169` ← `df_surrogate/_domain.py:13-14`（经 `solvers/continuous_field.py:50` 别名 `TRAIN_L`/`TRAIN_T`） | = surrogate 训练窗；出窗则 K 被钳到 1e-8 → SIMPLE 崩、100% 拒绝（`solvers/continuous_field.py:44-49`） |
| `spline_order` | 3 | `evaluator.py:170` | |
| `penalty_enabled` / `penalty_weight` | True / 1.0 | `evaluator.py:173-174` | 制造性罚项加到 dP 目标（`evaluator.py:621-623`） |
| `dp_cap_pa` | 1.0e6 | `evaluator.py:177` | dP 硬上限；超限设计按 cap 值返回而非 1e9（该对比明确见于拒绝早退注释 `evaluator.py:505-507`），保持 GP 输入分布有界（`evaluator.py:177-183`、终检 `evaluator.py:632-633`） |
| `reject_unconverged` | False | `evaluator.py:184` | True 时 SIMPLE 未收敛即按 cap 返回；代码内 `.get` 回退值已与默认对齐为 False（历史 bug 修复注记 `evaluator.py:509-516`） |

### DEFAULT_CONFIG_3D 增量（`optimization/evaluator_3d.py:42-73`）
`Nx_3d=30, Ny_3d=12, Nz_3d=6`（`evaluator_3d.py:47-49`），`Lz=0.042 m`（上海 HX 深度，`evaluator_3d.py:50`），`max_outer_3d=2, outer_tol_K=0.5, alpha_outer=0.6`（`evaluator_3d.py:51-53`）；并覆盖 2D 预算为 `max_iter_simple=300, tol_simple=1e-2, max_iter_energy=1000`（`evaluator_3d.py:57-59`）；`roughness_mode='norris_1a'`（摩擦侧 no-op，勿加乘子——DF 闭合已含 SLM 粗糙度）、`roughness_eps_um=100.0`（仅 bhatti_shah_1b 用，`evaluator_3d.py:71-72`）。

### run_qnehvi 引擎旋钮
`n_init=32, n_iter=24, q_batch=2, seed=42, hv_tol=0.01, hv_window=3, n_jobs=1`（`optimization/optimizer_qnehvi.py:160-171`）。`cfg['gp_model']`：默认 `'single_task'`（SingleTaskGP + ARD MLE），设 `'saas'` 切 SAAS 全贝叶斯 GP（NUTS；d≥30 高维选项，实测 36-D vanilla 前沿劣于 16-D），配套 `saas_warmup=128 / saas_samples=128 / saas_thin=16`（`optimization/optimizer_qnehvi.py:352-374`）。qNEHVI 采样器 128 QMC 样本、`optimize_acqf` `num_restarts=10, raw_samples=256`（`optimization/optimizer_qnehvi.py:402-417`）。BO 内部目标为 max-form `(Q, −log10 dP)`——log 变换是 v2 的关键加固，令 dP 4 个量级压入 [3,6]（`optimization/optimizer_qnehvi.py:267-283`、`306-307`）。HV 参考点 = 逐目标 min − 0.1·span（`optimization/optimizer_qnehvi.py:334-336`）。

### OptimizerConfig 与 env>config>auto（R3 拆分，2026-07-07）
- **`OptimizerConfig`**（dataclass，`domain/compute_config.py:197-210`）：`max_outer_ltne=4, outer_tol_K=0.5, max_iter_simple=800, tol_simple=1e-2, alpha_T=0.7`。仅供评估器 cheap screening；与 `SolverConfig`（生产管线四旋钮，`domain/compute_config.py:186-193`，`None`=用维度内建 auto 值）职责分离。
- 消费点：2D `_compute_cfg_to_evaluator_dict` 取 `compute_cfg.optimizer.{max_iter_simple, tol_simple, outer_tol_K}`（`optimization/evaluator.py:398-401`）；3D 另取 `optimizer.{max_outer_ltne→max_outer_3d, outer_tol_K, alpha_T→alpha_outer}`（`optimization/evaluator_3d.py:97-99`）。
- **优先级链**（生产管线侧，非 optimization/ 内部）：env `TPMSHX_SIMPLE_TOL` > SolverConfig > auto（`domain/compute_config.py:174-175` 文档；实际读取在 `pipelines/stages_2d.py:563` 与 `pipelines/run_stack_3d.py:72`）。粗糙度扫描 escape hatch：env `TPMSHX_ROUGH_MODE`（读取 `solvers/roughness.py:164`；`optimization/evaluator_3d.py:93-96` 注明旧 `solver.rough_mode` 透传已删）。**注意：optimization/ 六个文件自身不读取任何 `TPMSHX_*` env**（grep 核实），这两个 env 影响的是 3D 评估链深处的 roughness 与生产管线。
- 评估器内 cfg 合并优先级：显式 `cfg` dict > `compute_cfg` 映射 > `DEFAULT_CONFIG`（`optimization/evaluator.py:431-435`；3D 同构 `optimization/evaluator_3d.py:124-128`）。

## 边界·假设·适用范围

- **单位**：域尺寸 m、T K、P Pa；TPMS 胞元 L 与壁厚 t 为 **mm**（决策向量、CSV 导出均 mm，`optimization/export_ntop_csv.py:99-104`）。Q 为 W/m（每米 HX 深度）、mass kg/m。速度为间隙（interstitial）速度（仓库全局约定）。
- **双侧均按空气评估**：2D 评估器无水侧 dispatch，`fluid_type_A/B` 非 air 仅发 `RuntimeWarning` 并照跑空气——水侧组合的排名不可信（`optimization/evaluator.py:451-459`）。
- **可压缩耦合**：默认 `n_rho_loops=3` 的 SIMPLE↔energy 理想气体 ρ(T) 外循环是可压缩硬约束的体现；注释记载弃用会使 Shanghai 3D dP RMSRE 17.83%→38.88%（`optimization/evaluator.py:522-533`，数值出自注释，具体 RMSRE 未在本次核跑验证）。
- **Q 的定义**：`Q = Σ h_vB·(Ts−Tb)·dA` 体积换热公式（`optimization/evaluator.py:359-368, 616`），dP 目标含制造性罚项（`optimization/evaluator.py:621-628`）——直接引用 dP 数值时需注意其非纯压降。
- **排名非量值**：`OptimizerConfig` docstring 明确 cheap 预算只产排名（`domain/compute_config.py:200-204`）；port 型局部 BC 的绝对数值未经实验标定（ledger IDEA-PORT-VALID，`optimization/evaluator.py:119-121`）；`cf_aniso` 的取值必须来自方向分辨单胞 CFD（`validation/cf_aniso/` worklist），手设值只可 ± 扫描做结论稳健性检查（`optimization/evaluator.py:135-138`）。
- **B5 ∇ε 失效域——已闭合（2026-07-09 M2/M2b）**：早期版本的 2D 动量方程不含 ∇ε 项，陡 ε 梯度设计（连续场 BO 的典型赢家）落在闭合失效域。现 2D 动量核已离散 ε-DIVIDED VANS 形式——每个通量面带 `r_f = ε_f/ε_CV` 因子乘 F_f 与 D_f，压力项无需因子、DF 阻力不动，均匀 ε 时逐位（bit-identical）还原旧场（`solvers/_kernels_simple_2d.py:203-211`；3D 对应 `solvers/_kernels_simple_3d.py:99-100`；回归门 `tests/test_m2_vans_eps_momentum.py:1`、`tests/test_m2b_vans_eps_momentum_3d.py:1`；冻结值重基线注记 `tests/test_evaluator_frozen_values.py:116-117` 明确引用 ledger B5）。M1 赢家已在修正后求解器下重排名（`runs/run_m2_rerank_m1.py:1-8`）。**旧说法「evaluator.py:202 为 B5 失效域标注」已过时**：当前 `optimization/evaluator.py:201-210` 是 `_resolve_grid`，代码中已无该失效域注记（本仓库 grep「B5/∇ε」于 optimization/ 无命中）。
- **病态设计处理**：dP 非有限或超 `dp_cap_pa` → 返回 `(-1e-6, dp_cap, mass)`（`optimization/evaluator.py:632-633`）；worker 层异常/NaN（3D choke，P_out²≤0）→ `(1e-6, dp_cap, 'infeasible')`（`optimization/optimizer_qnehvi.py:75-81`）。3D 评估器不设 warn 模式，靠抛异常 + worker 兜底（`optimization/evaluator_3d.py:18-19`）。
- **决策空间即 surrogate 训练窗**：L∈[4,8] mm、t∈[0.3,0.5] mm（`df_surrogate/_domain.py:13-14`）；`ContinuousFieldConfig.evaluate_grid` 对样条越界值做 clip（`solvers/continuous_field.py:310-311`）。
- **坐标/轴换约定**（移植改造时最易错）：SIMPLE-A 内部轴与实坐标转置（SIMPLE-y=real-x，`optimization/evaluator.py:231-238`）；SIMPLE-B 流向为 −y，j=0 对应 real y=H，y 非对称场必须翻转推送 ε 与 K/cF（2026-07-10 orientation fix，`optimization/evaluator.py:312-323`、`optimization/evaluator.py:328-331`）——M0–M3 全部 `symmetric_y=True` 故历史结果不受影响。

## 可扩展接口

- **`evaluator_fn` 钩子（qNEHVI 引擎的评估器接入点）**：`run_qnehvi(..., evaluator_fn=None)` 默认 2D `evaluate_design`；传入满足 `(x, cfg) -> (Q_neg, dP, mass)` 契约的函数即可换评估后端——3D 接入即 `evaluator_fn=evaluate_design_3d`（`optimization/optimizer_qnehvi.py:62-68, 171`；实例 `runs/run_3d_qnehvi_fast.py:89-96`、`ui/optimize_panel.py:694-699`）。
- **`fc` kwarg**：`evaluate_design(..., fc=ContinuousFieldConfig)` 绕过 decode 直接给场（sanity 测试用，`optimization/evaluator.py:406, 415-416`）。
- **`compute_cfg` kwarg**：2D/3D 均接受严格类型 `ComputeConfig` 垫底（audit C3，`optimization/evaluator.py:408`、`optimization/evaluator_3d.py:105`）。
- **`gp_model='saas'` 分支**：高维（d≥30）预留的 SAAS 全贝叶斯 GP，NUTS 拟合失败时告警继续（`optimization/optimizer_qnehvi.py:352-380`）。
- **port-BC / per_cell_K / cf_aniso 三旋钮**：见上表；port 开启时会把 SIMPLE 的 `inlet_frac` 作为 `inlet_mask_A/B` 传给能量求解器（`optimization/evaluator.py:548-554, 571`；`SIMPLESolver.inlet_frac` 定义 `solvers/simple_solver.py:455`，`set_K_cF_field` 定义 `solvers/simple_solver.py:684`，`cf_aniso` 属性 `solvers/simple_solver.py:440`）。
- **UI 钩子**：`progress_cb(count, total, progress_dict)` 每批评估与每迭代各触发（回调异常被刻意吞掉以保 45–75 min 长跑，`optimization/optimizer_qnehvi.py:311-317, 437-442`）；`request_cancel()`（`optimization/optimizer_qnehvi.py:100-102`）。
- **env 变量**：optimization/ 自身不读 env；线程上限 env（`OMP/MKL/OPENBLAS/NUMEXPR_NUM_THREADS`）由 `parallel_runner._set_thread_caps` 以 `setdefault` 写入（`optimization/parallel_runner.py:44-53`）；内层 joblib 用 `inner_max_num_threads = cpu_count // workers` 分摊 numba 线程（joblib ≥ 1.5 传播为 `NUMBA_NUM_THREADS`，`optimization/optimizer_qnehvi.py:286-298`）。深层 escape hatch：`TPMSHX_ROUGH_MODE`（`solvers/roughness.py:164`）、`TPMSHX_SIMPLE_TOL`（生产管线，`pipelines/stages_2d.py:563`）。
- **`_BC_LOG_DONE` once-per-process 日志**：解析后的 BC（ports/per_cell_K）每进程打印一次，防止「实验配置整面」被误传为「求解器只支持整面」（`optimization/evaluator.py:81-82, 440-448`）。

## 已知不足与 TODO

- **grep 核实：optimization/ 六文件内无 `TODO`/`FIXME`/`XXX`/`NotImplementedError` 标记**。以下为代码注释自述或结构性欠账：
- 水侧 dispatch 缺失：2D 评估器一律按空气跑，非 air 选择仅告警（M0 注记，`optimization/evaluator.py:451-459`）。
- `evaluator_3d` 经 `core.evaluators` 中转层解 optimization→validation 依赖倒挂，函数「physical move pending future cleanup」（`optimization/evaluator_3d.py:33-36`）。
- port-BC 绝对数值未实验标定（`optimization/evaluator.py:119-121`）；`cf_aniso` 标定 worklist 未完成（`optimization/evaluator.py:135-138`）；3D 优化栈（core/evaluators.py）仍仅整面 BC（`optimization/evaluator.py:46-47` docstring 声明，core 侧未逐行核验——未验证）。
- `run_qnehvi` 写 `config.json` 时只保留 int/float/str/bool/None 标量（`optimization/optimizer_qnehvi.py:250-253`）——tuple 值（`L_bounds`、`t_bounds`、`ports_A/B`）**不会**进存档，复现需另行记录。
- `export_ntop_csv` 的域尺寸/TPMS 类型/控制点网格默认值须与优化 cfg 人工保持一致（`optimization/export_ntop_csv.py:11-19` 声明「must match the optimizer cfg」），`provenance.json` 只记录不校验。CSV 行序对 nTop 的兼容性是经验断言（"empirically robust across nTop 4.x and 5.x"，`optimization/export_ntop_csv.py:115-117`），未验证于其他版本。
- `_pareto_mask_max` 为 O(N²) 双循环（`optimization/optimizer_qnehvi.py:118-129`），eval 数上千时合并开销可感（性能项，非正确性）。
- `progress` 为进程内全局 dict；多种子模式下各子进程各有一份、父进程不聚合（`parallel_runner._seed_subprocess_main` 调 `run_qnehvi` 时未传 `progress_cb`，`optimization/parallel_runner.py:79-90`），跨种子实时进度不可用。
- 每种子 HV 参考点由各自初始样本决定（`optimization/optimizer_qnehvi.py:334-336`），跨种子的 HV 数值不可直接比较（合并只用非支配掩码，不受影响）。

## 服务器移植注意

> 目标平台已确认为 **Windows Server 2022**（不是 Linux）。以下逐条按「不适用 / 需重写 / 保留」重新核实，凡引用代码事实的地方已用 Grep/Read 复核（file:line 为准）。

- **平台无关性良好（Windows→Windows Server 迁移基本无成本）**：六文件路径均用 `os.path.join`，无 GUI import（UI 是 `ui/optimize_panel.py` 反向依赖本模块，服务器无交互桌面会话环境下 optimization/ 可独立使用）。原表述曾以「无硬编码 Windows 路径」佐证跨平台性——**这条已不适用（同为 Windows，无需处理）**：路径分隔符 `/` vs `\`、大小写敏感文件系统这类 Linux↔Windows 差异在 Windows→Windows Server 迁移里不存在，六文件里也确未见 `os.sep`/裸分隔符硬编码脆弱点。日志经 `logutil.get_logger`（`optimization/evaluator.py:77-79` 等），文件内日志文本为 ASCII——与目标平台无关，仍是好习惯，保留。
- **多进程**：`parallel_runner` 显式用 `spawn` 上下文（`optimization/parallel_runner.py:194-195`），源码注释原文为「Default fork on Linux works too but spawn is portable + safer under nested loky workers」（`optimization/parallel_runner.py:191-193`）。**该注释里的 Linux/fork 对比在 Windows Server 上不成立，但不是风险，而是自动消失**：CPython 的 `multiprocessing` 在 Windows 上从未实现 `fork` 启动方式（无 `fork()` 系统调用，只有 `spawn`），显式 `mp.get_context('spawn')` 与 Windows 平台本就唯一可用的方式一致——没有「不小心继承 fork」这条退路可选，迁移无需改动，**保留 spawn 调用**。内层 joblib 用 loky 后端（`optimization/optimizer_qnehvi.py:294-298`）；loky/`concurrent.futures` 在 Windows 下同样只能走 spawn，与本仓库显式设置的行为一致（loky 内部实现未在本仓库代码中检验——未验证，但为 Python 多进程平台约束的通识）。
- **线程超订**：BLAS/OpenMP 线程钳制必须发生在 numpy import **之前**（`optimization/parallel_runner.py:47-50`）；子进程入口先 `_set_thread_caps()` 再重 import（`optimization/parallel_runner.py:72-74`）。独立调用 `run_qnehvi(n_jobs>1)` 时调用方需自行先设 `OMP_NUM_THREADS=1`/`MKL_NUM_THREADS=1`（docstring 要求，`optimization/optimizer_qnehvi.py:193-199`）。此条与操作系统无关，Windows Server 上机制相同，无需改写。
- **重依赖延迟加载**：torch/botorch/gpytorch 仅在 `run_qnehvi` 体内 import（`optimization/optimizer_qnehvi.py:211-227`），评估器仅需 numpy + numba 链（经 solvers/）；joblib 仅 `n_jobs>1` 时 import（`optimization/optimizer_qnehvi.py:286`）。服务器最小安装可先不装 botorch 只跑评估器；torch/botorch/gpytorch/joblib/numba 均有官方 Windows wheel，`pip install` 直装即可，不需要任何 apt 等价物或编译工具链（`scripts/port_retest_server.ps1:57-59` 已验证走的就是纯 `pip install` 路径：CPU 版 torch + botorch/gpytorch）。
- **可复现性**：仓库运行习惯 `PYTHONHASHSEED=0 OMP_NUM_THREADS=1 python -u`（实例 `runs/run_m2_rerank_m1.py:11-12`），这是 POSIX shell 的行内环境变量写法，**PowerShell 不支持 `VAR=val cmd` 语法，需重写**：Windows Server 上应写成 `$env:PYTHONHASHSEED = "0"; $env:OMP_NUM_THREADS = "1"; python -u ...`（逐条 `$env:` 赋值后再起子命令）。本仓库 `scripts/port_retest_server.ps1:63-67` 已是这个约定的现成范例（`$env:PYTHONHASHSEED`/`$env:PYTHONPATH`/`$env:OMP_NUM_THREADS` 等逐条赋值），服务器批跑可直接照抄该模式。长跑必须 `python -u`（stdout 块缓冲会假死）——这条与操作系统无关，Windows 下重定向到文件/日志时同样会块缓冲，保留。golden 门的 `PYTHONHASHSEED=0` 要求见 `.claude/commands/check.md`（本模块未直接受 golden 钉定，但 `tests/test_evaluator_frozen_values.py` 冻结了评估器数值，重基线历史见其 116-128 行注记）。
- **数据文件**：本目录不直接读数据文件，但评估链深处 `df_surrogate` 标定依赖 gitignored `data/raw_data`——fresh checkout/worktree 缺该目录时 DF 标定回退 CSV，钉定测试出 ULP 级差异（经验教训，来自项目 memory，代码级根因未在本次核验——未验证）。此条与 Linux/Windows 无关，Windows Server 上同样成立：`scripts/port_retest_server.ps1:42-49` 就是先 clone 私有数据仓再 `Copy-Item` 拼进 `data/raw_data` 来规避这个坑。
- **CSV/JSON 输出（GBK 风险方向反转，需重写）**：`save_dir` 相对 cwd 自动命名（`optimization/optimizer_qnehvi.py:239-241`），服务器批跑建议显式传绝对路径。`np.savetxt`（`optimization/optimizer_qnehvi.py:154`）与 `open(..., 'w')` 写 `config.json`（`optimization/optimizer_qnehvi.py:250-253`）均**未显式传 `encoding=`**，走 Python/OS 默认编码（`locale.getpreferredencoding()`）。原表述「无 GBK 问题」隐含的前提是「迁移到 Linux 后默认 UTF-8 locale 自然规避」——**目标改成 Windows Server 后这个前提不成立，方向要反过来**：中文区域设置的 Windows Server 默认代码页通常仍是 GBK/CP936，不是 UTF-8，这个坑不会自然消失。本模块目前能侥幸不出编码错误，纯粹是因为写出内容恰好是 ASCII——CSV 表头 `x0,...,Q_W_per_m,dP_Pa` + 数值，`config.json` 的键值已被 `optimization/optimizer_qnehvi.py:250-253` 的 `int/float/str/bool/None` 白名单限制在 ASCII 范围内——不是「平台层面无 GBK 问题」的结论。评估链同一条依赖树上已经真实踩过这坑：`df_surrogate/surrogate_v3.py:151-155` 的代码注释原文记录「the Excel path contains Chinese characters; on a GBK-console Windows a subprocess writes them as GBK bytes while pytest reads its capture stream as UTF-8 — one such line poisons the capture and EVERY later test teardown dies with UnicodeDecodeError（found the hard way, 2026-07-07）」。迁移到 Windows Server 时建议：涉及非纯 ASCII 内容的文件 I/O（尤其新增输出）一律显式传 `encoding='utf-8'`，不要依赖系统区域设置；subprocess/pytest 捕获流同理，不能假定与终端代码页一致。
