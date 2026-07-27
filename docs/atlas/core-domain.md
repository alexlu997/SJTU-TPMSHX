# configs + core + domain
生成日期 2026-07-10，基于 commit f33d30e 附近的 master；
**2026-07-20 收编 upgrade/loop 分支漂移**（见文末收编节；正文失准处标 ⟨07-20 更新⟩）

> 溯源约定：所有 `file:line` 相对仓库内 `sjtu_tpmshx/` 包目录（即 `sjtu_tpmshx/domain/compute_config.py:337` 写作 `domain/compute_config.py:337`）。本文所有断言均已在代码中逐条核实；无法核实处显式标注「未验证」。

## 定位与功能

这三个包构成求解器栈的「契约层 + 中性层」，全部 Qt-free：

- **`configs/`** — 集中式参数加载。当前只承载 Shanghai 16-case 基准（Gyroid 换热器实验）的 canonical 几何/域参数 JSON 及其加载函数（`configs/__init__.py:1-6` 模块 docstring 说明其动机是消除多脚本硬编码）。
- **`core/`** — 中性层共享模块。当前唯一成员 `core/evaluators.py` 是 3D LTNE 设计评估器（`evaluate_3d`），供 BO 优化器（`optimization/evaluator_3d.py:36`）与 CLI 验证脚本（`validation/cases/verify_pareto_3d.py:47`）共同 import，从而打破历史上 optimization→validation 的反向依赖（`core/evaluators.py:1-9`）。
- **`domain/`** — 领域契约层：
  - `domain/compute_config.py` — 严格类型化的 `ComputeConfig` dataclass 树，是 UI 层以下所有 solver/pipeline/validation 入口的统一配置对象（`domain/compute_config.py:1-12`）；模块 docstring 同时是全仓 `TPMSHX_*` 环境变量旗标的注册表（`domain/compute_config.py:42-103`）。
  - `domain/compute_result.py` — 单次 pipeline 计算的输出契约 `ComputeResult`。
  - `domain/validator.py` — 纯函数校验（几何/网格建议/管口 BC/单位解析/方向映射）。

## 文件一览

| 文件 | 行数 | 职责（一行） |
|---|---|---|
| `configs/__init__.py` | 44 | `load_shanghai_baseline()`：读同目录 `shanghai_baseline.json` 返回 dict |
| `configs/shanghai_baseline.json` | 27 | Shanghai canonical 参数：Gyroid, L_cell=7.0 mm, t=0.6 mm, k_s=16, L_dom=0.182 m, H_dom=0.042 m, Lz=0.042 m（`configs/shanghai_baseline.json:9-21`） |
| `core/__init__.py` | 6 | 仅 docstring，声明中性层定位 |
| `core/evaluators.py` | 639 ⟨07-20 更新；原 433。P1.3：choke 种子/超音速判定全部改走 `solvers/envelope` 权威（`from solvers.envelope import ...` :46，`R_AIR = R_AIR_DEFAULT` :59 仅作兼容再导出）；新增 `_post_solve_gate_3d` :66（解后 Mach+正压门，失败 → NaN+invalid dict 保留真实几何质量）；`_build_3d_arrays` 现 :98、`evaluate_3d` 现 :145，本卷旧行号（:51/:61/:108-123）均漂移⟩ | 3D 设计评估器 `evaluate_3d` + 逐体素物性数组构建 `_build_3d_arrays` + 解后有效性门 |
| `domain/__init__.py` | 63 | re-export `validator` 的全部公开函数（`domain/__init__.py:39-50`） |
| `domain/compute_config.py` | 533 | `ComputeConfig` dataclass 树 + JSON 双格式适配 + `TPMSHX_*` env 注册表 docstring |
| `domain/compute_result.py` | 75 | `ComputeResult` 输出 dataclass（headline 标量 + fields/coeffs/props/residuals 等子字典） |
| `domain/validator.py` | 449 | 网格建议、几何/管口校验、单位解析、方向→壁面映射，均为纯函数 |

## 公开接口

### configs

- **`load_shanghai_baseline() -> dict[str, Any]`**（`configs/__init__.py:16`）— 返回键 `_meta` / `geometry` / `domain`（/ `_excluded`）的 dict。调用方（grep 核实）：`validation/harness/_case_sets.py:30`、`validation/cases/validate_shanghai_aligned.py:59`、`validation/cases/validate_shanghai_lumped_dual_nu.py:66`、`runs/archive/cross_check_water_nu.py:52`、`tests/test_shanghai_baseline_config.py`。

### domain/compute_config.py

- **`ComputeConfig`**（`domain/compute_config.py:342`）— 复合配置。字段：`fluid_A`/`fluid_B`（`FluidConfig`）、`geometry`、`solver`、`optimizer`、`bc_A`/`bc_B`、`zones`、`extrap`、`flags`、`envelope_mode`。方法：
  - `from_json(path)`（`domain/compute_config.py:385`）/ `to_json(path)`（`domain/compute_config.py:398`，`asdict`+`json.dumps` UTF-8）。
  - `from_dict(data)`（`domain/compute_config.py:459`）— 支持两种布局：canonical（含 `fluid_A`/`fluid_B`/`solver` 任一键，`domain/compute_config.py:473`）与 legacy Shanghai baseline（`geometry`+`domain` 键，`domain/compute_config.py:510-524`）。两条路径最后都调 `.validate()`。
  - `validate()`（`domain/compute_config.py:406`）— 仅在 `from_dict`/`from_json` 边界调用；直接 dataclass 构造保持宽松（`domain/compute_config.py:411-414` docstring，行为与实现一致）。拒绝非有限或 ≤0 的几何/流体标量（`domain/compute_config.py:443`）及 <1 的 Nx/Ny/Nz（`domain/compute_config.py:454`）。
  - `is_3d` property（`domain/compute_config.py:374-377`）— `int(self.solver.Nz) >= 2` 时走 3D 网格。
  - 主要调用方：`controllers/compute_pipeline.py:50`、`pipelines/stages_2d.py:27`、`pipelines/stages_3d.py:35`、`ui/window_config.py:16`（UI 适配器 `config_from_window`，定义于 `ui/window_config.py:407`）、`validation/cases/validate_shanghai_3d_real.py:474` 及大量测试。
- **`bc_to_dict(bc, L_dom, H_dom, *, side='A', with_z=False)`**（`domain/compute_config.py:237`）— `PartialBCConfig` → legacy 求解器 BC dict。A/B 两侧行为**有意不对称**：`side='B'` 且 `in_w<=0 and out_w<=0` 返回 `None`（`domain/compute_config.py:265-266`），下游 `_run_3d_stack` 将其读作「无 B 流体的单流体运行」；`side='A'` 的退化 BC 回退为全断面 inlet/outlet（`domain/compute_config.py:270-272`）。调用方：`pipelines/stages_2d.py:27`、`pipelines/stages_3d.py:35`、`tests/test_bc_to_dict.py:9`。
- 其余 dataclass：`FluidConfig`（`domain/compute_config.py:124`）、`GeometryConfig`（:133）、`SolverConfig`（:155）、`OptimizerConfig`（:196）、`PartialBCConfig`（:213）、`ZoneInputConfig`（:281）、`ExtrapPolicy`（:307）、`FeatureFlags`（:321）。全部经 `__all__` 导出（`domain/compute_config.py:527-533`）。

### domain/compute_result.py

- **`ComputeResult`**（`domain/compute_result.py:15`）— headline 标量 `Q_W`/`dP_A_Pa`/`dP_B_Pa`/`T_out_A_K`/`T_out_B_K`（:26-30），收敛判据 `converged: bool = True`（:37），子字典 `fields`/`coeffs`/`props`/`residuals`/`zones`/`warnings`/`extrap_reasons`/`diagnostics`（:43-72）。调用方：`controllers/compute_pipeline.py:51`、`pipelines/stages_2d.py:28`、`pipelines/stages_3d.py:36`。

### core/evaluators.py

- **`evaluate_3d(x_decision, cfg, *, Nx=40, Ny=16, Nz=16, Lz=0.042, max_outer=3, outer_tol_K=0.5, alpha_outer=0.6, max_iter_simple=800, tol_simple=1e-2, max_iter_energy=2000, tol_energy=0.5, roughness_mode=None, roughness_eps_um=None, convergence_mode='legacy', verbose=True) -> dict`**（`core/evaluators.py:108-123`）— 对单个决策向量运行 3D LTNE 评估，返回键 `Q_3D_W` / `dP_A_Pa` / `dP_B_Pa` / `dP_total_Pa` / `mass_kg` / `Lz_m` / `grid`。注意 **`cfg` 是原始 dict 而非 `ComputeConfig`**，键名为 `L_domain`/`H_domain`/`u_A`/`u_B`/`T_inA` 等，与 `ComputeConfig` 命名体系不同。调用方：`optimization/evaluator_3d.py:36`（BO 筛选，`legacy`）、`validation/cases/verify_pareto_3d.py`（Pareto 复核，显式 `'f2'`）。
- **C10（2026-07-12，台账）三处修复**：① LTNE 对流 ρcp 改用 SIMPLE **本地** ρ——A 侧用重解后的 `sA.rho_field`（转置回真实坐标），B 侧用 `sB.rho_field` 原样（y 镜像、**不做 T 回暖**：冻结 B 的 `ρ_cold·u_cold` 才是 SIMPLE-B 实际守恒的质量通量）。旧码 `air_density(Ta/Tb, P_in)` 全域按**进口压**取密度，即生产管线 2026-06-09 `variable_rho_cp` 修掉的旧行为；实测钉定设计上 Q 差 **23.3% / 10.5%**（dP、mass 逐位不变）。② `sB.eps_field` 装载补 y 镜像（sB 是 reverse-y，j=0=真实 y=H；`symmetric_y=True` 下镜像=恒等，故此前不可见）。③ 两侧 `_mu_eff_field` 随逐胞 `eps_field` 刷新（生产模式；只动 nonuniform dP ~1.4e-7 相对量）。**`convergence_mode='f2'` 是复核档**：报数用途必须传 `'f2'` 并消费 `invalid` 旗标；`legacy` 档的 dP/Q 禁止当物理结果引用（函数内注释）。**收敛真值表（2026-07-13，codex 复核）**：返回 dict 现含 `simple_A/B_converged`（末次解裁决）、`ltne_inner_converged`（末次 inner pass）、`outer_converged`（到 cap = False，"未验证"按未收敛计）、`finite` 与合取 `converged`——此前三次 `solve()` 的返回值全被弃置、未收敛照常出数；invalid dict 亦带 `converged: False` 与**真实几何质量**（原 NaN）。`verify_pareto_3d` 显式 `max_outer=12` + 真值表门（exit 3 ≠ choke 的 2）。评估器与生产管线的既知残差（B 侧冻结单解、无后解 Mach 门）见台账 [O2]/[C10]/[O1]。
- **`_build_3d_arrays(fc, Nx, Ny, Nz, ...) -> dict`**（`core/evaluators.py:61`）— 逐体素数组（eps, K_ffA/B, K_ss, h_vA/B, A_0, eps_A），由 2D 连续场沿 z 均匀拉伸得到；虽带下划线仍列入 `__all__`（`core/evaluators.py:54`）供自定义外层循环调用。
- **`R_AIR = 287.05`**（`core/evaluators.py:51`）— 空气气体常数，用于 1D Darcy-Forchheimer 可压 seed。

### domain/validator.py

- `suggest_grid_2d(L_dom, H_dom, D_h, alpha=0.4)`（`domain/validator.py:41`）与 `suggest_grid_3d(..., max_cells=50_000, wall_refine_pad=16)`（:59）— 由域尺寸和水力直径 D_h 建议网格；3D 版在 wall-refine 加 pad 后总胞数封顶 50 k（:87-89）。
- `validate_geometry(...) -> List[Warning]`（:95）— 硬规则 raise（尺寸 ≤0、3D 缺 Lz），软规则 warn：t/L>0.10 或 <0.05 视为外推（:126-135）、L_cell 大于最小域尺寸判 error（:141-146）、Shanghai 几何 (L=7, t=0.6) 提示外推点（:148-153）。
- `geometry_extrapolation_warning(L_cell_mm, t_mm)`（:158）— (L, t) 落在训练网格 {4,5,6,8}×{0.3,0.4,0.5} mm 外时返回 warning；训练节点常量来自 `df_surrogate/_domain.py:18-19`（`TRAIN_L_NODES=(4.0,5.0,6.0,8.0)`、`TRAIN_T_NODES=(0.3,0.4,0.5)`）。
- `compute_volumetric_htc(A_0, H_sf)`（:181）— h_v = A_0 × H_sf，面 HTC [W/(m²·K)] → 体 HTC [W/(m³·K)]。
- `wall_for_dir(d, role)`（:208）/ `cross_axes_for_dir(d)`（:223）— 流向索引 0..5（0=+x 1=-x 2=+y 3=-y 4=+z 5=-z，:211）到壁面名/横向轴标签。
- `validate_pipe_config(cfg, L_dom, H_dom, Lz_dom=None, is_3d=False)`（:237）— 管口 BC dict 的中心±半宽越界/宽度非正检查，含 3D z-partial 字段（:286-305）。
- `parse_unit_value` / `parse_field_value` / `format_unit_value`（:327 / :430 / :415）+ 常量表 `FIELD_UNITS`（:376）、`POSITIVE_FIELDS`（:399）、`COUNT_TOKEN_WHITELIST`（:410）— UI 单位解析的领域层实现。
- `Warning` dataclass（:22-32，code/message/severity）— 与内建 `Warning` 同名，`domain/__init__.py:49` re-export 时改名为 `DomainWarning`。

## 关键配置项与开关

### dataclass 默认值（定义处均在 `domain/compute_config.py`）

| 配置项 | 默认值 | 定义处 |
|---|---|---|
| `FluidType` Literal | `'air' \| 'water' \| 'sco2'` | `domain/compute_config.py:114` |
| `FluidConfig.type` | `'air'` | `domain/compute_config.py:127` |
| `FluidConfig.u_mps` / `T_in_K` / `P_in_Pa` | 5.0 / 300.0 / 101325.0 | `domain/compute_config.py:128-130` |
| `GeometryConfig.tpms` | `'Gyroid'`（Literal `'Diamond'\|'Gyroid'`，:115） | `domain/compute_config.py:141` |
| `GeometryConfig.L_cell_mm` / `t_wall_mm` | 7.0 / 0.6（**毫米**） | `domain/compute_config.py:142-143` |
| `GeometryConfig.k_s_W_mK` / `L_dom_m` / `H_dom_m` | 16.0 / 0.182 / 0.042 | `domain/compute_config.py:144-146` |
| `GeometryConfig.Lz_m` | `None`（= 2D 运行标志；3D 必须给出） | `domain/compute_config.py:147`，语义见 :137-139 |
| `GeometryConfig.delta_levelset` | 0.0（非对称孔隙率 offset-isosurface δ，0 = 对称 50/50 bit-identical） | `domain/compute_config.py:152` |
| `SolverConfig.max_outer_ltne` / `outer_tol_K` / `max_iter_simple` / `tol_simple` | 均 `None`（= 使用维度内建值；R3 rewire 2026-07-07。env 层仅 `tol_simple` 有：`TPMSHX_SIMPLE_TOL` 优先级 env > config > auto（`domain/compute_config.py:174-176` docstring、读取点 `pipelines/run_stack_3d.py:72`）；其余三项为 config > auto，见 :157-184 docstring） | `domain/compute_config.py:186-189` |
| `SolverConfig.Nx` / `Ny` / `Nz` | 30 / 60 / 1 | `domain/compute_config.py:190-192` |
| `SolverConfig.T_s_init_K` | `None`（回退 legacy seed 0.5·(T_inA+T_inB)，:183-185 docstring） | `domain/compute_config.py:193` |
| `OptimizerConfig`（优化器廉价评估预算，只产 ranking 不产可引用数字） | `max_outer_ltne=4, outer_tol_K=0.5, max_iter_simple=800, tol_simple=1e-2, alpha_T=0.7` | `domain/compute_config.py:206-210` |
| `FeatureFlags.wall_refine_3d` | `False` | `domain/compute_config.py:336` |
| **`FeatureFlags.variable_rho_cp`** | **`True`**（3D LTNE 能量核用 SIMPLE 局部压力 ρ(P_local,T) 而非入口压力；2026-06-09 起默认开；docstring 标注 hard invariant，勿默认关闭） | `domain/compute_config.py:337`（docstring :328-333） |
| `FeatureFlags.temp_unit` | `'K'` | `domain/compute_config.py:338` |
| `ComputeConfig.envelope_mode` | `'raise'`（可压有效域守卫：`'raise'` → ChokedFlowError；`'warn'` → 跑但标 `envelope_valid=False`；`'off'` → legacy 静默） | `domain/compute_config.py:370`（注释 :366-369） |

`variable_rho_cp` 的消费点（grep 核实）：`pipelines/stages_3d.py:189`（`ComputeConfig` → 3D cfg dict）、`pipelines/run_stack_3d.py:950`（`cfg.get('variable_rho_cp', True)`）。`envelope_mode` 的消费点：`pipelines/stages_3d.py:182`、`pipelines/stages_2d.py:231`、`pipelines/solve_2d.py:1226`、`pipelines/run_stack_3d.py:389`。

### 求解器级 `fluid_type`（易混淆，重要）

`ComputeConfig` 中的 `FluidConfig.type`（`'air'/'water'/'sco2'`）**不是**求解器构造参数 `fluid_type`。后者取值 `'ideal_gas'`（可压）或 `'incompressible'`，默认 `'ideal_gas'`，定义在 `solvers/simple_solver.py:266`（2D）与 `solvers/simple_solver_3d.py:475`（3D），不在 domain 层；由 `FluidConfig.type` 到 `fluid_type` 的映射经 `solvers/fluid_props.py:132-133`（按流体的 `compressible` 属性）。顶层 CLAUDE.md 把「`fluid_type='ideal_gas'` 默认」笼统归到 `domain/compute_config.py` 名下，代码事实是它位于 solvers 层——移植时以本节 file:line 为准。

### `TPMSHX_*` 环境变量注册表

全仓 env 旗标的清单以 docstring 形式维护在 `domain/compute_config.py:42-103`（含默认值与读取点；「加旗标 = 加一行」约定）。注意该 docstring 是**人工同步的文档**而非代码，读取逻辑在各自模块内（本次已抽查核实 `variable_rho_cp`/`envelope_mode` 两项；其余条目的读取点位置未逐一验证，引用前请对注册表列出的模块 grep 确认）。与本三包直接相关的：`TPMSHX_VAR_RHOCP`（UI checkbox 为主，env 为覆盖；`domain/compute_config.py:79-80`）。

### `from_dict` 的 legacy 容错

旧 JSON 中的 `solver.alpha_T` / `solver.rough_mode` 键被静默丢弃并发 `warnings.warn`（R3 拆分遗留，`domain/compute_config.py:481-486`）；`RoughMode` Literal 类型别名仍保留并导出（`domain/compute_config.py:116`、:528）但 `SolverConfig` 已无对应字段。

### `evaluate_3d` 的独立默认值

`core/evaluators.py:111-122`：网格 Nx=40, Ny=16, Nz=16, Lz=0.042 m；外层 max_outer=3, outer_tol_K=0.5 K, alpha_outer=0.6；SIMPLE max_iter=800, tol=1e-2；能量方程 max_iter=2000, tol=0.5。这些是优化器筛选预算量级，与生产 pipeline 的 `SolverConfig` 无耦合。cfg dict 的可选键默认：`P_inA=101325.0`、`P_inB=P_inA`、`tpms_type='Diamond'`、`k_s=17.0`、`rho_s=2700.0`、`dir_A=0`、`dir_B=3`（`core/evaluators.py:129-136`、:350）。注意 `tpms_type` 默认 `'Diamond'` 与 `GeometryConfig.tpms` 默认 `'Gyroid'` 不一致——两套入口各有默认，勿混用。

## 边界·假设·适用范围

- **单位约定**：K / Pa / m 全局，但 TPMS 胞元尺寸 `L_cell_mm` 与壁厚 `t_wall_mm` 是**毫米**（字段名后缀，`domain/compute_config.py:142-143`；UI 单位表也确认 `le_Lcell`/`le_t` 目标单位 mm，`domain/validator.py:385`）。速度为 interstitial（孔内）速度——此约定为仓库级不变量（见 CLAUDE.md），本三包代码中无显式换算点可引证，标注为「继承约定」。
- **ε 契约**：`evaluate_3d` 向 `solve_full_domain_3d` 传**完整** ε（`arrays['eps_arr']`，`core/evaluators.py:347`），kernel 内部做唯一一次减半（Option A 契约，注释 `core/evaluators.py:340-342`；kernel 侧行为本文未复核，属 solvers 篇范围）。上游预减半会导致 ε/4 双重减半的历史 bug。
- **可压有效域**：`evaluate_3d` 先做 1D Darcy-Forchheimer 闭式 seed `P_out² = P_in² − 2·R_AIR·T·C·L`（A 侧 `core/evaluators.py:216`，B 侧 :222）；任一侧 `P_out² ≤ 0` 即判 choked，返回全 NaN + `invalid=True` + `invalid_reason`（`core/evaluators.py:235-252`），这是严格验证契约（不同于求解器值路径的 `max(..., 1e4)` 兜底，见 :225-234 注释）。外层迭代内的 P_ref 更新仍用 `max(P_out_sq_new, 1.0e4)` 地板（`core/evaluators.py:398`）。
- **`max_outer < 1` 直接 `ValueError`**（`core/evaluators.py:305-308`），防止温度场为 None 的隐性崩溃。
- **Q 的积分定义**：`Q_3D = Σ h_vB·(Ts − Tb)·V_cell`，即 B 侧体积换热积分（`core/evaluators.py:419`）；质量 `mass = Σ (1−ε)·rho_s·V_cell`（:423）。
- **粗糙度**：`roughness_mode=None` 时从 env 解析（`solvers.roughness.resolve_mode_from_env`，default `'baseline'`，`core/evaluators.py:165-169`）；非 baseline 时 K_A/=f_gain、cF_A×=f_gain 且 `bhatti_shah_1b` 额外乘 Nu 因子（:185-194）。注释声称水侧粗糙度已含在 `nu_water_topo` 拟合内故不再处理（:163-167）——该声称本文未在水侧代码复核，标注「注释级断言，未验证」。DF 闭合已含 SLM 粗糙度、禁止再乘摩擦系数是仓库级硬不变量（CLAUDE.md）。
- **训练域**：几何外推软边界 t/L ∈ [0.05, 0.10]（`domain/validator.py:126-135`）、训练网格 L∈{4,5,6,8} mm × t∈{0.3,0.4,0.5} mm（`df_surrogate/_domain.py:18-19`）；Shanghai 点 (L=7, t=0.6) 本身即 t 方向外推点（`domain/validator.py:148-153`）。
- **`ComputeConfig.validate()` 只守脚本边界**：直接构造 `ComputeConfig(...)` 不触发校验（测试刻意构造异常配置，`domain/compute_config.py:411-414`）；JSON 路径会拒绝 NaN/Infinity/非正值。

## 可扩展接口

- **`envelope_mode`**（`'raise'/'warn'/'off'`，`domain/compute_config.py:370`）— 批量扫描（不能因单个 choked 工况中止）用 `'warn'`；`'off'` 为 legacy 逃生门。注意 `from_dict` 不校验该字符串取值（`domain/compute_config.py:507` 仅 `data.get`），非法值的下游行为未验证。
- **`GeometryConfig.delta_levelset`**（`domain/compute_config.py:152`）— 非对称孔隙率 hook；δ≠0 时 ε_A≠ε_B，由 `pipelines.stages_3d._eps_sides_for_run` 消费（注释 :148-151；消费点属 pipelines 篇范围，未在本文复核）。
- **`PartialBCConfig` z-overlay**（`in_z_ctr`/`in_z_w`/`out_z_ctr`/`out_z_w`，`domain/compute_config.py:231-234`）— `None` = z 向全断面；`bc_to_dict(with_z=True)` 才附加（:273-277）。
- **`ZoneInputConfig.config: Optional[Any]`**（`domain/compute_config.py:301`）— 承载已解析的 `solvers.zone_config.ZoneConfig` 实例。**注意**：该字段为任意对象时 `to_json` 的 `asdict`+`json.dumps` 链路能否序列化未验证——存疑，移植方序列化含 zones 的配置前先测试。
- **`evaluate_3d` 的 `roughness_mode`/`roughness_eps_um` kwargs**（`core/evaluators.py:120-121`）— 显式传参优先，`None` 回退 env。
- **`from_dict` 双布局**（canonical / legacy Shanghai，`domain/compute_config.py:462-524`）— 生产验证脚本可用同一 JSON 一行切换。
- **`_build_3d_arrays` 公开导出**（`core/evaluators.py:54`）— 供自带外层循环的调用方直接驱动 solver 栈。
- **env 旗标注册点** — 新增 `TPMSHX_*` 旗标的约定入口是 `domain/compute_config.py:42-103` docstring 加一行 + 在目标模块实现读取（调用时读、不缓存，便于测试 monkeypatch，:45-47）。

## 已知不足与 TODO

- **grep 零命中**：`configs/`、`core/`、`domain/` 三包内无 `TODO` / `FIXME` / `NotImplementedError` / `XXX` / `HACK`（本次 grep 核实）。
- **`evaluate_3d` 的 cfg 是裸 dict**，键名体系（`L_domain`/`u_A`/`T_inA`/`k_s`…）与 `ComputeConfig`（`L_dom_m`/`u_mps`/`T_in_K`/`k_s_W_mK`）不互通（`core/evaluators.py:126-136`）；无适配器，移植时勿臆断两者可互换。
- **3D 优化器栈未接 port 型 partial BC**：`evaluate_3d` 中两个 `SIMPLESolver3D` 均为构造默认的全断面 inlet/outlet；注释明确 2D 优化器有 `ports_A/ports_B` 而此处没有，接入需 `run_stack_3d` 的 mask 约定（`core/evaluators.py:257-260`，2026-07-10 注释）。
- **`ZoneInputConfig.config` 的 JSON 逃逸**（见上节）— 存疑，未验证。
- **`RoughMode` Literal 遗留**（`domain/compute_config.py:116`）— `SolverConfig.rough_mode` 已在 R3 移除但类型别名仍导出；粗糙度扫描只剩 `TPMSHX_ROUGH_MODE` env 逃生门（:177-181 docstring）。
- **env 注册表靠人工同步**（`domain/compute_config.py:82-83` 自述 2026-07-03 曾补漏一批——数 :85-103 为 9 条条目、含 11 个旗标）；是否有测试强制同步未验证。
- **`domain/validator.py` 的 `Warning` 类遮蔽内建 `Warning`**（`domain/validator.py:23`）；包外通过 `domain/__init__.py:49` 的 `DomainWarning` 别名使用，包内直接 `Warning` 引用时注意。
- **`suggest_grid_2d` 与 `solvers.tpms_calc.adaptive_grid` 双实现**：docstring 自述为后者的纯 Python 镜像、仅在 `alpha=0.4` 下匹配（`domain/validator.py:44-50`）；两者是否已漂移未验证。

## 服务器移植注意

*目标平台自 2026-07-11 起明确为 Windows Server 2022（不是 Linux）；以下各条已按此复核，纯因「Linux」目标产生的假设已下线或改写，真正跨平台无关的条目不受影响。*

- **import 布局是最大陷阱**：全仓以 `sjtu_tpmshx/` 目录本身为 sys.path 根，import 语句**不带** `sjtu_tpmshx.` 前缀——`from domain.compute_config import ComputeConfig`（`pipelines/stages_3d.py:35`）、`from configs import load_shanghai_baseline`（`validation/harness/_case_sets.py:30`）、`from core.evaluators import evaluate_3d`（`optimization/evaluator_3d.py:36`）。脚本自行插入 ROOT，如 `validation/cases/verify_pareto_3d.py:41-43`（`parents[2]` → `sjtu_tpmshx/` 目录）。移植时保持该布局或全量重写 import，不能只改一半。
- **编码安全（GBK 坑不会因换到 Windows Server 而消失，反而是重点复核项）**：三包所有 JSON I/O 显式 `encoding='utf-8'`（`configs/__init__.py:40`、`domain/compute_config.py:395`、:401-404）；因为这个 `encoding` 是显式常量而非依赖 `locale.getpreferredencoding()` 推断值，它本就与操作系统区域设置无关，旧稿「Linux 默认 locale 下无问题」的表述其实是伪因果，已核实并删除——这条 JSON I/O 路径在任何平台、任何代码页下都安全。真正的风险在**日志/终端输出编码**：`logutil.py` 的 `_StdoutHandler`（`logutil.py:45-58`）直接写 `sys.stdout`、不做任何编码兜底；`core/evaluators.py:237` 的日志行含上标字符 `²`（`P_out²_A`、`Pa²`），本次核实 `'²'.encode('gbk')` 确实抛 `UnicodeEncodeError`（对照 `'—'.encode('gbk')` 不报错，说明不是所有非 ASCII 字符都中招，需按字符核实而非一概而论）。中文区域设置的 Windows Server 控制台默认代码页即为 936（GBK/CP936），若未覆盖，该日志行会直接抛异常崩溃，而不只是仓库已知的「GBK 中文日志污染 pytest capture」（那是更窄的一种表现，见 memory）。仓库内已有同类防护先例但本三包未覆盖：`df_surrogate/predict.py:328` 显式 `sys.stdout.reconfigure(encoding='utf-8')`；`logutil.py` 与 `core/evaluators.py` 均无对应处理。服务器部署建议：进程级设 `PYTHONUTF8=1`（或 `PYTHONIOENCODING=utf-8`）环境变量，或在入口脚本对 `sys.stdout`/`sys.stderr` 做同样的 `reconfigure`。`shanghai_baseline.json` 的 `_meta` 含中文字符串（`configs/shanghai_baseline.json:3-7`）本身只走文件 I/O（已确认显式 utf-8），不受此项影响。
- **路径分隔符对比不适用（同为 Windows，无需处理）**：旧稿「无 Windows 路径硬编码」一条是为核查跨到 Linux 后的路径分隔符风险而写；目标改为 Windows Server 后开发端与服务器端同为 Windows，该项差异已不存在，原有 `pathlib`（`configs/__init__.py:13`、`domain/compute_config.py:110`）核查事实仍真，但不再构成移植风险，故不再作为注意事项列出。与该条绑在一起、且与操作系统无关、仍然成立的一件事单独保留：**与 gitignored 大文件解耦**——`shanghai_baseline.json:5` 的 `data/raw_data/...xlsx` 字段仅是出处注记，加载函数不读该文件（`configs/__init__.py:39-41` 只读同目录 JSON），故服务器上全新 clone 时若 `data/raw_data`（gitignored）尚未同步，不影响本三包功能（同类陷阱见 memory「Worktree raw_data gate trap」）。
- **GUI 解耦已完成但依赖方向要看清**：`domain/` 与 `configs/` 是 Qt-free 纯 stdlib（`domain/compute_config.py:10-12` 自述只依赖 stdlib+typing——已核实其 import 块 :105-111）；例外是 **`domain/validator.py:16` import 了 `df_surrogate._domain`**（训练节点常量），剥离 domain 层时必须连带。`core/evaluators.py` 则重依赖 `solvers/`（`SIMPLESolver3D`、`solve_full_domain_3d`、`tpms_calc` 物性）与 `logutil`（`core/evaluators.py:35-48`），import 即触发 numba 编译链——服务器需装 numba 且首次调用有 JIT 预热开销。
- **可复现性**：golden 门要求 `PYTHONHASHSEED=0`（仓库级约定，见 `.claude/commands/check.md`；本三包无直接哈希序依赖，未验证具体敏感点）。
- **无 GUI 服务器的推荐入口**：`ComputeConfig.from_json`（`domain/compute_config.py:385`）绕开全部 Qt/UI 层直达 pipelines；`FeatureFlags`/`ZoneInputConfig` docstring 里提到的 `window.chk_*` 只是字段来历说明，不是运行时依赖。
- **并行/线程**：本三包自身无线程逻辑；numba 线程数经 `TPMSHX_NUM_THREADS`（注册表 `domain/compute_config.py:92-93`，读取在 `solvers/threads.py`，未在本文复核）。

## 2026-07 升级分支收编（upgrade/loop，2026-07-20）

- **core/evaluators.py envelope 权威统一**（P1.3-A/B）：三处 choke 种子改调
  `envelope.predict_outlet_p_sq`、判定改 `assess_solution_validity`/`mach_field_max`；本地
  `R_AIR` 变 `R_AIR_DEFAULT` 兼容再导出；新增 `_post_solve_gate_3d`（solver-frame vmag 中心化
  0.5·(u[:-1]+u[1:])、T 场 transpose(1,0,2)/[:, ::-1, :] 映射；失败返回 NaN+invalid 但保留真实
  几何质量供 BO 质量目标）。常驻守卫：`test_evaluator_envelope_authority.py`。
- **契约测试**（P1.4）：`test_evaluator_pipeline_contract.py` 把评估器 vs 生产管线的六条有意
  差异固化为机器断言，含 **D3 绊线**（G 口径不一致——2D 管线显式 ρ(T_in,P_in) vs 3D 首解捕获
  ρ(T_in,P_out_seed)，实测吞吐亏 7.38%/19.30%，待 Alex 决策，upgrade/DECISIONS-NEEDED.md D3）。
- **compute_config.py**：env 注册表 docstring 扩容（+`TPMSHX_BO_CORE_BUDGET`、
  `TPMSHX_NUM_THREADS` 建议机制注记——:42-103 行段已漂移）；P2.2 类型注解修正三处
  （物理默认值零变动）；该文件在 mypy 核心七文件圈内。
- **邻域新文件**（不属本卷三包但契约相关）：`sjtu_tpmshx/_version.py`（版本单源，pyproject
  dynamic 指向）、`sjtu_tpmshx/cli.py`（ComputeConfig.from_json → pipeline_for 的 headless 入口）。
