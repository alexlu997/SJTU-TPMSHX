# pipelines
生成日期 2026-07-10，基于 commit f33d30e 附近的 master

## 定位与功能

`sjtu_tpmshx/pipelines/` 是 2D/3D 计算管线的 stage 函数层：接收 `domain.compute_config.ComputeConfig`，驱动 SIMPLE（动量/压力）与 LTNE（三温能量）求解器栈，产出 `domain.compute_result.ComputeResult`。该层设计为 Qt-free / matplotlib-free（`sjtu_tpmshx/pipelines/__init__.py:1`），由 `controllers/compute_pipeline.py` 的 `Pipeline2D` / `Pipeline3D` 按 parse → build_fields → run_solvers → finalize 四相驱动（2D 调用点 `sjtu_tpmshx/controllers/compute_pipeline.py:172-193`，3D `:213-232`）。层次约束：`controllers/` 与 `ui/` 可以 import `pipelines/`，但 `pipelines/` 不得 import `runs/` 或 `controllers/`（`sjtu_tpmshx/pipelines/__init__.py:6-8`）。

除 GUI 管线外，`_run_3d_stack`（`sjtu_tpmshx/pipelines/run_stack_3d.py:346`）也被 validation / runs / tests 直接调用（如 `sjtu_tpmshx/validation/cases/validate_shanghai_3d_real.py:464` 注明它就是 GUI 驱动的同一套栈）。

## 文件一览

| 文件 | 行数 | 职责（一行） |
|---|---|---|
| `__init__.py` | 9 | 包 docstring：层次约束与四相驱动模式说明（`sjtu_tpmshx/pipelines/__init__.py:1-9`） |
| `_stage_common.py` | 87 | 2D/3D 共享的非核（kernel-free）脚手架：域尺寸单位防火墙、surrogate 外推域检查、`safe_float`、几何三元组（`sjtu_tpmshx/pipelines/_stage_common.py:28,42,66,79`） |
| `stages_2d.py` | 815 | 2D 四相 stage 函数：`_parse_inputs_cfg` / `_build_fields_cfg` / `_run_solvers_cfg` / `_finalize_cfg`，并 re-export `solve_2d` 中的实现（`sjtu_tpmshx/pipelines/stages_2d.py:43-46`） |
| `solve_2d.py` | 1341 | 2D 求解引擎：外层 SIMPLE↔LTNE 耦合循环 `_run_solvers`、焓平衡 `_enthalpy_balance_2d`、Richardson Q、压力后处理、window shim（`sjtu_tpmshx/pipelines/solve_2d.py:14,109,218,324,644`） |
| `stages_3d.py` | 375 | 3D 四相 stage 函数（parse/passthrough/run/finalize）+ 对 flux_3d/grid_3d/run_stack_3d 的 verbatim re-export（`sjtu_tpmshx/pipelines/stages_3d.py:59-74`） |
| `stages_3d_helpers.py` | 535 | 纯 numpy 帮助函数：方向→轴映射、面切片、staggered↔real 坐标重映、流向出口通量平衡、χ_B 参与场三种构建器（`sjtu_tpmshx/pipelines/stages_3d_helpers.py:10,88,116,195,320,381,493`） |
| `grid_3d.py` | 169 | 3D 网格/轴映射/分区场构建：`_resolve_axis_map` / `_build_zone_fields_3d` / `_build_grid_3d` / `_solver_spacings`（`sjtu_tpmshx/pipelines/grid_3d.py:15,79,120,159`） |
| `flux_3d.py` | 270 | 3D 面通量后处理与粗糙度施加：`_face_flux_weights` 及其派生的 T_out/h_out/m_dot 加权、`_apply_roughness_KcF` / `_apply_roughness_h_v`（`sjtu_tpmshx/pipelines/flux_3d.py:46,111,142,215,235,253`） |
| `run_stack_3d.py` | 2107 | 3D 主栈 `_run_3d_stack`：SIMPLE3D(A/B 并行) + LTNE3D 外循环、包络门、守恒诊断、结果 dict 组装；禁止 import `stages_3d`（防环，`sjtu_tpmshx/pipelines/run_stack_3d.py:4-6`） |

## 公开接口

命名均为下划线前缀，但它们是 controllers/tests/validation 实际消费的接口（re-export 契约由 `sjtu_tpmshx/tests/test_pipeline_reexports.py` 锁定，未逐行验证该测试内容）。

### 2D 管线（stages_2d.py + solve_2d.py）

- `_parse_inputs_cfg(compute_cfg: ComputeConfig) -> dict`（`sjtu_tpmshx/pipelines/stages_2d.py:80`）。Phase 1。校验流体类型（`:99-103`）、surrogate 外推域（`:113`）、域尺寸防火墙（`:130`）、构建 zone 数组（`:150-211`，异常时回退 uniform 并追加 warning `:205-210`）。返回的 cfg dict 键见 `:222-243`，其中 `'compute_cfg'` 存放原始 ComputeConfig（`:242`），`'eps'` 是全 ε（`:147`）。调用方：`Pipeline2D.build_fields`（`sjtu_tpmshx/controllers/compute_pipeline.py:174`）。
- `_build_fields_cfg(cfg: dict, *, live_residuals: dict|None) -> dict`（`sjtu_tpmshx/pipelines/stages_2d.py:246`）。Phase 2。构建能量网格 `energy_dx/energy_dy`（全宽 BC 且无 zone 时用 4 壁 Brinkman-BL 细化网格 `:348-360`，否则对齐均匀网格 `:361-363`），随后**就地改写 `cfg['N_x']/cfg['N_y']` 为有效网格数**（细化可扩栅，`:369-372`）并把 zone 数组重采样到有效网格（`:415`）。返回 fields dict：`energy_dx/energy_dy/_x_breaks/_y_breaks/_run_simple/simple_warnings`（`:614-619`）。`_run_simple` 是捕获全部局部量的闭包（`:421`），内部构建 `SIMPLESolver2D`（`solvers.simple_solver.SIMPLESolver`，`:479-503`），mass-flux inlet 的参考密度 `rho_inlet_ref = P_in_abs/(287.05·T_in)` 仅对 `fluid_type=='ideal_gas'` 传入（`:475-476`）。
- `_run_solvers_cfg(cfg, fields, *, progress_cb, cancel_token, ui_hooks) -> dict`（`sjtu_tpmshx/pipelines/stages_2d.py:623`）。Phase 3。用 `_PipelineWindowShim` 适配旧的 window 接口后调用 `_run_solvers(shim, cfg, fields)`（`:646-648`），并把 shim 上被回写的 zone 统计与物性（`_shim_rho_A` 等）转入 result dict（`:651-665`）。注意：`cancel_token` 目前是被动的——`_run_solvers` 内循环不轮询取消（`:637-641` docstring）。
- `_finalize_cfg(raw: dict, fields: dict) -> ComputeResult`（`sjtu_tpmshx/pipelines/stages_2d.py:669`）。Phase 4。注意第二参数 `fields` 实际接到的是 parsed cfg dict（调用方 `sjtu_tpmshx/controllers/compute_pipeline.py:193` 传 `self._parsed`）。计算按质量流加权的出口温度（`:695-729`），`converged` 取 `raw.get('solver_converged', False)`——缺键即判不收敛（fail-safe，`:752`）。`diagnostics['mode']='2d'`（`:802`）。
- `_run_solvers(window, cfg, fields) -> dict`（`sjtu_tpmshx/pipelines/solve_2d.py:644`）。2D 引擎主体：外层耦合循环由 `solvers.coupling_skeleton.run_outer_coupling` 驱动（step=`_step_2d` `:897`，post=`_post_2d` `:1163`，调用 `:1173-1174`）。每轮 step：A/B 两个 SIMPLE 在两条 OS 线程上并行解（`:933-958`，njit/spsolve 释放 GIL）→ `solve_full_domain`（LTNE 2D，`:1058-1070`）→ NaN 守卫（`:1077-1097`）→ 以质量通量加权 Δρ + ΔTa/ΔTb/ΔTs 双判据收敛（`:1141-1153`）。post 对 ρ / ρ·cp 场做 α=0.7 欠松弛（`:1168-1171`）。返回 dict 键见 `:1311-1340`，其中 `'solver_converged' = coupling_converged and not simple_warnings`（`:1326`）。
- `_enthalpy_balance_2d(...) -> float`（`sjtu_tpmshx/pipelines/solve_2d.py:14`）。质量守恒焓平衡 Q=ṁ·(T_in_avg−T_out_avg)；`eps_side` 参数（N1 修正）表示**逐侧**空隙率——速度为 interstitial，物理面质量通量为 ε_side·ρ·|u|·A（`:29-34`）；sCO2 传 `enthalpy_fn/rho_fn/P_ref` 走真焓路径（`:80-95`）。
- `_compute_Q_richardson(...)`（`sjtu_tpmshx/pipelines/solve_2d.py:324`）。2× 细化网格重解 + 逐侧 Richardson 外推；4× 权重放在细网格值上（历史命名倒置的修正说明见 `:518-529`）；Richardson 失败时有无条件 1D 平板均值兜底路径（`:579-634`，触发时置 `richardson_warn=True` 并追加 warning）。
- `_compute_pressure_2d(simpA, simpB, dir_A, dir_B, P_inA, P_inB, window)`（`sjtu_tpmshx/pipelines/solve_2d.py:218`）。管道加权（inlet_frac/outlet_frac）压力参考；`dP = P_ref_inlet − P_out_gauge`（`:269-270`）。
- `_PipelineWindowShim(compute_cfg, progress_cb, iter_label_cb)`（`sjtu_tpmshx/pipelines/solve_2d.py:109`）。cfg-only 路径下模拟 window：构造时按侧重跑 `tpms_calc.compute` 预填 `_rho_A/_mu_A/_K_ffA/_K_ss/_h_vA` 等（`:148-179`），`__setattr__` 钩子把 `_compute_progress`/`_iter_label_now` 写转发为回调（`:202-215`）。

### 3D 管线（stages_3d.py + run_stack_3d.py）

- `_parse_inputs_3d_cfg(compute_cfg) -> dict`（`sjtu_tpmshx/pipelines/stages_3d.py:96`）。Lz 缺省 0.042 m（`:107-108`）；域尺寸/网格数校验（`:113-121`）；退化的 B 侧 BC（PartialBCConfig 默认 in_w=out_w=0 经 `bc_to_dict(side='B')` 返回 None）会用 `side='A'` 回退重建为全面 BC，防止两流体解静默变成 A-alone（`:142-155`）。返回 dict 键见 `:177-201`（含 `delta_levelset`、R3 求解器 knob 四项、`compute_cfg` 本体）。
- `_build_fields_3d_cfg(parsed) -> dict`（`sjtu_tpmshx/pipelines/stages_3d.py:204`）。**纯 passthrough**（`return parsed`，`:212`）——3D 无独立 build 相，仅为保持 Pipeline ABC 契约对称。
- `_run_solvers_3d_cfg(parsed, fields, *, progress_cb, cancel_token, iter_cb) -> dict`（`sjtu_tpmshx/pipelines/stages_3d.py:215`）。浅拷贝 cfg（`:232`，因 `_run_3d_stack` 会改写少量键），注入 `_progress_cb/_cancel_check/_iter_cb`（`:236-241`），套 `_apply_phase_flags`（`:244`），然后 `return _run_3d_stack(cfg)`（`:246`）。
- `_finalize_3d_cfg(raw, fields) -> ComputeResult`（`sjtu_tpmshx/pipelines/stages_3d.py:249`）。ComputeResult 组装见 `:285-375`；`diagnostics['mode']='3d'`（`:366`）；warnings 来自 `raw['envelope_warnings']`（`:359`）。渲染/导出契约由 `tests/test_finalize_3d_result_sync.py` 锁定（`:264-265` docstring，测试内容未逐行验证）。
- `_run_3d_stack(cfg: dict) -> dict`（`sjtu_tpmshx/pipelines/run_stack_3d.py:346`）。3D 主栈，流程：sweep profile 解析（`:359-376`）→ 网格 `_build_grid_3d`（`:415`）→ 硬网格数上限（`:424-433`）→ 轴映射（`:436`）→ D-F surrogate `predict_K_cF`（zoned 走 `predict_K_cF_vec`，`:474-504`）→ 粗糙度施加（`:509`）→ P_ref 1D 种子 + 预解 choke 门 `_seed_p_ref`（`:526,618`）→ SIMPLE3D A/B 构建后**并行**初解 `_run_two_simple_parallel`（`:664`；A-alone 走串行 `:679`）→ K_ff/K_ss/h_v 场构建（`:711-733,901-911`）→ `run_outer_coupling(step=_outer_step_3d, post=_outer_post_3d)`（`:1595-1596`）。step 内：局部 Re 重建 h_v（`:1028`）、partial-B closure 分派（`:1072-1145`）、staggered 面速度提取 + 出流平衡（`:1175-1212`）、`solve_full_domain_3d`（`:1258-1299`）、可选焓形式 LTNE（`:1311-1337`）。post 内：Ta/Tb 回传 SIMPLE 密度场（欠松弛 α=0.6，`:1394-1400`）、P_ref 重播种（`:1408-1449`）、SIMPLE 温启重解（cap 600，`:1456,1575`）。指标提取：`Q = Q_enthalpy_A`（A 侧对流焓为唯一 headline duty，`:1732-1751`）、`dP = extract_dP_face_extrap(sA)`（`:1753`）、后置包络门（`:1964-1989`）、`solver_converged`（`:2006-2009`）。直接调用方：`_run_solvers_3d_cfg`、`validation/cases/validate_shanghai_3d_real.py`、`runs/_out/_golden_3d.py`、多个 tests/demos（grep 名单 46 文件）。
- `_run_two_simple_parallel(sA, sB, *, max_iter=2000, tol=None, cancel_check=None)`（`sjtu_tpmshx/pipelines/run_stack_3d.py:184`）。两条 OS 线程并行解 A/B；两线程 join 后再抛第一个异常；cancel 以 `InterruptedError` 上抛（`:234-242`）。
- `_conservation_diagnostics_3d(...) -> dict`（`sjtu_tpmshx/pipelines/run_stack_3d.py:259`）。能量/质量守恒 + BC 层剔除的 interior 修正指标；失败时 warn + NaN，不静默（`:283-290`）。

### 3D 帮助函数（被 run_stack_3d 与外部 tests 消费）

- 方向编码单一来源：`dir_code` 0=+x 1=-x 2=+y 3=-y 4=+z 5=-z；`_stream_axis`/`_dir_is_reverse`/`_inlet_index`/`_outlet_index`/`_face_slice`（`sjtu_tpmshx/pipelines/stages_3d_helpers.py:10-37`；设计说明 `sjtu_tpmshx/pipelines/flux_3d.py:208-214`）。approach-(a) 反向约定：solver 恒在 j=0 注入，反向流体的空间翻转只发生在速度/χ/P 的 real 坐标变换里，掩模不换位（`sjtu_tpmshx/pipelines/stages_3d_helpers.py:78-85,104-113,176-183`；`sjtu_tpmshx/pipelines/flux_3d.py:69-73`）。
- `_solver_velocity_to_real` / `_solver_staggered_to_real`（`sjtu_tpmshx/pipelines/stages_3d_helpers.py:88,116`）：SIMPLE3D solver 坐标 → real 坐标（cell-center / staggered 面），反向流沿流向轴翻转 + 流向分量取负。
- `_balance_stream_outflow(faces, axis_map, coef, dx, dy, dz)`（`sjtu_tpmshx/pipelines/stages_3d_helpers.py:195`）：出口面通量重缩放使 ∮F·n=0，`coef = eps_f·ρcp`；仅不可压（或 variable_rho_cp 下的可压）路径调用（`sjtu_tpmshx/pipelines/run_stack_3d.py:1199-1212`）。
- χ_B 构建器三种：`_build_chi_B_union_extrude`（`:320`）、`_build_chi_B_mass_flux_threshold`（`:381`，H8）、`_build_chi_B_velocity_threshold`（`:493`）。
- `_face_flux_weights(solver, dir_code, face, eps_mode, chi_face, eps_f_per_side, eps_side_override)`（`sjtu_tpmshx/pipelines/flux_3d.py:46`）：统一面通量权重。`eps_mode='ltne'` 时优先用 `eps_side_override`（已分侧、不再减半，`:87-92`），否则乘 `0.5·eps_field`（`:94-97`），两者皆无则要求 `eps_f_per_side`（`:99-102`）。`_mass_weighted_T_out`/`_mass_weighted_h_out`/`_simple_mass_flow` 均委托它（`:111,142,215`），异常时回退朴素均值/0 并发 warning（不再静默，`:131-139,225-232`）。

### 共享脚手架（_stage_common.py）

- `validate_domain_dims(pairs)`：任何域尺寸 > `_DOMAIN_MAX_M = 10.0` m 即 ValueError（防 mm/m 单位滑移，`sjtu_tpmshx/pipelines/_stage_common.py:25-39`）。
- `surrogate_extrap_reasons(compute_cfg, allow_extrap)`：双侧 surrogate 训练域检查；ImportError→[]，ValueError 故意上抛（`:42-63`）。
- `safe_float(v)`：None/非数 → nan（`:66-76`）。`geometry_props(compute_cfg)`：(ε, D_h, A_0)（`:79-87`）。

## 关键配置项与开关

### cfg dict 字段生命周期

**2D**：`ComputeConfig` → `_parse_inputs_cfg` 产出 cfg dict（键：`L,H,N_x,N_y,dx,dy,u_A,u_B,T_inA,T_inB,T_s_init,cfgA,cfgB,dir_A,dir_B,envelope_mode,tpms_type,Lcell,t_wall,k_s,eps,r_h,zone_config,za,z_axis,fluid_A,fluid_B,warnings_list,extrap_reasons,compute_cfg`，`sjtu_tpmshx/pipelines/stages_2d.py:222-243`）。`_build_fields_cfg` **原地改写** `cfg['N_x']/['N_y']`（`:371-372`）；`_run_solvers` 原地 append `cfg['warnings_list']`（`sjtu_tpmshx/pipelines/solve_2d.py:970-973,1176-1181`）；`_finalize_cfg` 的 `fields` 形参即该 parsed dict。注意 `dx/dy` 键在 build 后**过期**（真实网格是 `energy_dx/energy_dy`），无人再读。

**3D**：`_parse_inputs_3d_cfg` 产出的 dict 同时是 fields（passthrough）；`_run_solvers_3d_cfg` 浅拷贝后注入 `_progress_cb/_cancel_check/_iter_cb` 与 Phase 旗标（`sjtu_tpmshx/pipelines/stages_3d.py:232-244`）；`_run_3d_stack` 在 `fast_sweep` profile 下再浅拷贝并压 `Nx/Ny/Nz ≤ 15`（`sjtu_tpmshx/pipelines/run_stack_3d.py:368-371`）。`_run_3d_stack` 还接受大量未经 parse 相的可选键（脚本调用方直接塞）：`sweep_profile,partial_B_closure,chi_B_*,m4_*,disp_C_A/B,conservative_ltne,strict_mass_balance,force_cc_ltne,ltne_alpha_T,ltne_enthalpy_*,mms_S_*_field,audit_*,max_cells_3d,_emit_audit,_verbose_diag,_case_label`。

### 数值默认值（定义处）

| 项 | 默认 | 定义处 |
|---|---|---|
| 2D 外耦合上限 `_MAX_COUPLING` | 10 | `sjtu_tpmshx/pipelines/solve_2d.py:689` |
| 2D Δρ 容差 `_COUPLING_TOL` | 0.01 | `sjtu_tpmshx/pipelines/solve_2d.py:690` |
| 2D ΔT 容差 `_DT_TOL_K` | 1.0 K | `sjtu_tpmshx/pipelines/solve_2d.py:691` |
| 2D 耦合欠松弛 `_ALPHA_COUP` | 0.7 | `sjtu_tpmshx/pipelines/solve_2d.py:692` |
| 2D SIMPLE tol（auto） | partial 5e-4 / full 1e-5，cap 10000 | `sjtu_tpmshx/pipelines/stages_2d.py:555-556` |
| 2D LTNE tol/max_iter | 水侧 1.0/12000，否则 0.5/5000 | `sjtu_tpmshx/pipelines/solve_2d.py:1035-1037` |
| 3D 外耦合上限 `_MAX_OUTER` | 5 | `sjtu_tpmshx/pipelines/run_stack_3d.py:246` |
| 3D 外耦合 ΔT 容差 `_OUTER_TOL` | 0.5 K | `sjtu_tpmshx/pipelines/run_stack_3d.py:247` |
| 3D 物性欠松弛 `_ALPHA_T` | 0.6 | `sjtu_tpmshx/pipelines/run_stack_3d.py:248` |
| 3D SIMPLE tol（auto） | 1e-5 | `sjtu_tpmshx/pipelines/run_stack_3d.py:77` |
| 3D SIMPLE cap：初解 / 外循环重解 | 2000 / 600 | `sjtu_tpmshx/pipelines/run_stack_3d.py:679,1456` |
| 3D LTNE max_iter / tol / alpha_T | 20000（full_validate 50000）/ 1e-5 / 0.7 | `sjtu_tpmshx/pipelines/run_stack_3d.py:364-375,1268,1270` |
| 3D 网格数硬上限 | 2,000,000 | `sjtu_tpmshx/pipelines/run_stack_3d.py:424-426` |
| wall_refine 参数 | n_refine=8, first_cell=0.02 mm, growth=1.8 | `sjtu_tpmshx/pipelines/grid_3d.py:142`（2D 同参 `sjtu_tpmshx/pipelines/stages_2d.py:356`） |
| R_AIR | 287.05 | `sjtu_tpmshx/pipelines/run_stack_3d.py:245` |
| UI 粗糙度模式 | `'norris_1a'`（摩擦侧 no-op） | `sjtu_tpmshx/pipelines/flux_3d.py:35` |
| `partial_B_closure` | `'none'`（χ_B≡1） | `sjtu_tpmshx/pipelines/run_stack_3d.py:1072` |
| `chi_B_method`（closure 开启时） | `'mass_flux_threshold'` | `sjtu_tpmshx/pipelines/run_stack_3d.py:1102` |
| `chi_B_kernel_threshold` | 0.0（无核级掩模） | `sjtu_tpmshx/pipelines/run_stack_3d.py:1223` |
| `conservative_ltne` / `strict_mass_balance` | True / True | `sjtu_tpmshx/pipelines/run_stack_3d.py:1199,1228` |
| `variable_rho_cp` | True（env 可覆盖） | `sjtu_tpmshx/pipelines/run_stack_3d.py:946-950` |
| `disp_C_A` / `disp_C_B`（热弥散） | 0.0（关闭） | `sjtu_tpmshx/pipelines/run_stack_3d.py:720-721` |
| `envelope_mode` | `'raise'` | `sjtu_tpmshx/pipelines/run_stack_3d.py:389`；2D `sjtu_tpmshx/pipelines/solve_2d.py:1226` |
| `ltne_enthalpy_mode` | False（sCO2 双侧 counterflow-x 门控） | `sjtu_tpmshx/pipelines/run_stack_3d.py:1248-1253` |

### R3 求解器 knob 优先级

env > `SolverConfig` > 维度专属 auto。2D：`sjtu_tpmshx/pipelines/stages_2d.py:550-565`（SIMPLE tol/max_iter）与 `sjtu_tpmshx/pipelines/solve_2d.py:696-701`（`max_outer_ltne`/`outer_tol_K`）。3D：`sjtu_tpmshx/pipelines/run_stack_3d.py:71-83`（`_simple_tol_default`/`_simple_max_iter`）与 `:380-383`（knob 覆盖 sweep profile 预设）。

### asym ε（offset-isosurface δ）在管线中的 upstream split 位置——两条管线的分侧点

硬不变量：`solvers/ltne_energy.py` 对称路径在内部把全 ε 减半；asym 路径必须在管线 upstream 分好侧、kernel 不再减半。几何 split 比 s 的单一来源是 `solvers/asym_split.py`（`_asym_split_A` :21，`_per_side_eps_override` :41，`_eps_sides_for_run` :57）。

**2D**（`sjtu_tpmshx/pipelines/solve_2d.py`）：
1. 分侧比计算：`_split_A_2d = _asym_split_A_2d({'delta_levelset': δ}, ...)`，δ 来自 `cfg['compute_cfg'].geometry.delta_levelset`（`:800-804`）；相对 ε/2 基线的系数 `_epsfac_A = 2s`、`_epsfac_B = 2(1−s)`（`:805-806`）。
2. 主能量解：δ≠0 时 `_Kffa_use = K_ffA_src·2s`、`_epsA_use = ε_src·s`，作为 `eps_A/eps_B` kwarg 传给 `solve_full_domain`；δ=0 时传 None → kernel 走对称内部减半路径，逐位一致（`:1050-1070`）。
3. h_v 分侧几何比 `_hv_side_geom_ratio_2d`（δ=0 时恰为 1.0，`:817-851`），乘在 local-Re h_v 上（`:1026-1028`）。
4. duty 提取：`_compute_Q_richardson` 中 `eps_side = ε·s`（A）/ `ε·(1−s)`（B）直接进焓平衡（`:489-511`）；1D 兜底同样乘 `ε_mean·s`（`:607-609`）。
5. 2D K_ff 用全 ε（`solvers/tpms_calc.py:506` 附近，本文档未逐行验证该行号），因此 2D 分侧缩放全部相对 ε/2 基线取 `2s / 2(1−s)`（设计注释 `sjtu_tpmshx/pipelines/solve_2d.py:789-799`）。

**3D**（`sjtu_tpmshx/pipelines/run_stack_3d.py`）:
1. K/cF：非 zoned 路径按 `kappa_KcF(tpms, ε·s, 0.5ε)` 得逐侧 κ 修正（δ=0 时 κ=1 逐位一致；zoned 路径不做 asym split，`:489-502`）。
2. 逐侧单通道空隙率场：`eps_fA_arr, eps_fB_arr = _eps_sides_for_run(cfg, ...)`（δ=0 时二者就是对称 `eps_f_arr = eps_arr/2` 同一对象，`:704-710`）；`K_ffA = eps_fA_arr·k_A`、`K_ffB = eps_fB_arr·k_B`（`:711-712`）；外循环 post 的 K_ff 刷新同样用 `eps_fA_arr/eps_fB_arr`（`:1480-1483,1503`）。
3. LTNE kernel：`eps_A/eps_B` kwarg **仅当 δ≠0 才传**，δ=0 省略 kwarg → kernel 对称 0.5·ε 默认路径（`:1289-1297`）；kernel 消费已分侧值、不再减半。
4. 出流平衡投影系数逐侧：`coef = eps_fA_arr·ρcp_A` / `eps_fB_arr·ρcp_B`（`:1207-1212`）。
5. duty/m_dot 提取：`_per_side_eps_override(cfg, ...)` 给出 `eps_side_override`（δ=0 返回 None → `_face_flux_weights` 走对称 `0.5·eps_field`；δ≠0 直接乘已分侧 ε_side，`:1641-1651`；`sjtu_tpmshx/pipelines/flux_3d.py:87-97`）。
6. h_v 分侧几何比 `_hv_side_geom_ratio`（δ=0 恒 1.0，`:869-897`）。

### 环境变量（管线层读取）

| 变量 | 作用 | 读取处 |
|---|---|---|
| `TPMSHX_SIMPLE_TOL` | 覆盖 2D/3D SIMPLE 压力修正 tol（最高优先级） | `sjtu_tpmshx/pipelines/stages_2d.py:563`；`sjtu_tpmshx/pipelines/run_stack_3d.py:72` |
| `TPMSHX_PHASE_A` / `_B` / `_C` | 加速旗标：A 默认开（=0 关），B/C 默认关（=1 开） | `sjtu_tpmshx/pipelines/run_stack_3d.py:95-100` |
| `TPMSHX_VAR_RHOCP` | `0/1` 显式覆盖 `variable_rho_cp`（否则 cfg 默认 True） | `sjtu_tpmshx/pipelines/run_stack_3d.py:946-950` |
| `TPMSHX_MAX_CELLS_3D` | 覆盖 3D 网格数上限（默认 2e6） | `sjtu_tpmshx/pipelines/run_stack_3d.py:424-426` |
| `TPMSHX_PROFILE_3D` | `=1` 开 3D 逐解剖析（或包根放 `.profile_3d` 空文件） | `sjtu_tpmshx/pipelines/run_stack_3d.py:143-158` |
| `TPMSHX_SCO2_COMPRESSIBLE` | 实验性 sCO2 局部压密度路径（仅物性侧） | `sjtu_tpmshx/pipelines/run_stack_3d.py:1381,1420` |
| （粗糙度 env） | `_resolve_ui_roughness` 委托 `solvers.roughness.resolve_mode_from_env` | `sjtu_tpmshx/pipelines/flux_3d.py:38-40`（具体变量名在 solvers 层，未验证） |

## 边界·假设·适用范围

- **单位**：K / Pa / m，但 `L_cell` 与 `t_wall` 为 **mm**（`_parse_inputs_cfg` 直接以 mm 传给 `tpms_geometry`，`sjtu_tpmshx/pipelines/stages_2d.py:143-146`）。域尺寸 > 10 m 直接 ValueError（`sjtu_tpmshx/pipelines/_stage_common.py:25`）。
- **速度均为 interstitial**（孔内），面质量通量须乘 ε_side（`sjtu_tpmshx/pipelines/solve_2d.py:29-34`；`sjtu_tpmshx/pipelines/flux_3d.py:85-103`）。
- **可压缩为必需**：air 走 ideal-gas ρ=ρ(P,T)（3D `sjtu_tpmshx/pipelines/run_stack_3d.py:1379`；2D 经 `fluid_props.flow_model` 分派 `sjtu_tpmshx/pipelines/solve_2d.py:917-918`）。
- **包络（choke）门**：预解 1D P² 种子检查（`sjtu_tpmshx/pipelines/run_stack_3d.py:53-64,525-527`）+ 后置 Mach/正压门（3D `:1964-1989`；2D `sjtu_tpmshx/pipelines/solve_2d.py:1221-1247`）。`envelope_mode='raise'|'warn'|'off'`。不得通过移除该门"修复" ChokedFlowError。
- **流体支持矩阵**：2D 支持 air/water/sCO2（`validate_fluid_type` 拦不支持项，`sjtu_tpmshx/pipelines/stages_2d.py:99-103`）；2D zoned 仅 air-air，否则 NotImplementedError（`:58-77`）。3D fluid A 不支持 water（NotImplementedError，`sjtu_tpmshx/pipelines/run_stack_3d.py:457-459`）；fluid B 支持 air/water/sCO2。
- **3D headline Q 只取 A 侧对流焓** `Q_enthalpy_A`；`Q_enthalpy_B`、`Q_solid_B` 均为诊断（`sjtu_tpmshx/pipelines/run_stack_3d.py:1732-1751`）。sCO2 双侧时 A/B 焓失衡 >10% 会 warn "3D coupled Q 不可信，用 2D"（`:1716-1730`）。
- **3D zoned 几何是 2D 设计沿 z 的均匀 extrusion**，不支持沿 z 变化（`sjtu_tpmshx/pipelines/grid_3d.py:85-91`）。
- **DF closure 已含 SLM 粗糙度**：`norris_1a` 对摩擦是 no-op、Nu ×1.28 已烘焙在 tpms_calc air-Gyroid（`sjtu_tpmshx/pipelines/flux_3d.py:27-35`）；water/sCO2 经 `embeds_roughness` 旗标跳过（`:241-243,260-261`）。切勿再加摩擦/粗糙度乘子。
- **平滑仅用于显示**：partial-BC 下速度/温度/压力的 gaussian_filter 平滑只产出 `*_disp` 副本或显示重绑定，物理量（Q、焓平衡）一律吃 raw 场（`sjtu_tpmshx/pipelines/solve_2d.py:977-997,1188-1208`）。
- **2D `_finalize_cfg` 的 `r_dP_A/r_dP_B` 恒为 nan**（`_run_solvers` 不产出，`sjtu_tpmshx/pipelines/stages_2d.py:786-787`）。
- **`_balance_stream_outflow` 仅限不可压（或 variable_rho_cp 可压）**——对纯可压强推 ∮(εu)=0 会破坏速度场（实测 +300% Q 误差，`sjtu_tpmshx/pipelines/run_stack_3d.py:1191-1198`）。

## 可扩展接口

- **私有 kwargs（asym 钩子）**：`solve_full_domain` / `solve_full_domain_3d` 的 `eps_A/eps_B`——仅供 δ≠0 的 upstream 分侧路径使用；对称路径必须传 None/省略（`sjtu_tpmshx/pipelines/solve_2d.py:1055-1070`；`sjtu_tpmshx/pipelines/run_stack_3d.py:1289-1297`）。`_face_flux_weights` 的 `eps_side_override` 同理（`sjtu_tpmshx/pipelines/flux_3d.py:87-92`）。
- **partial_B_closure 分派点**：`'none'` / `'m4_effective_area'`（legacy 0D）/ `'per_cell_chi_b'`（χ_B 场），新 closure 在 `sjtu_tpmshx/pipelines/run_stack_3d.py:1072-1145` 增分支；χ_B 构建方法在 `cfg['chi_B_method']` 分派（`:1102-1129`）。
- **回调钩子**：cfg 内 `_progress_cb`（0-100 int）、`_cancel_check`（→bool，仅在外循环间隙轮询，`sjtu_tpmshx/pipelines/run_stack_3d.py:1010-1014`）、`_iter_cb(outer, n_outer)`（`sjtu_tpmshx/pipelines/stages_3d.py:236-241`）。2D 经 shim 的 `__setattr__` 转发（`sjtu_tpmshx/pipelines/solve_2d.py:202-215`），`live_residuals` dict 供 UI sparkline（`sjtu_tpmshx/pipelines/stages_2d.py:577-583`）。
- **MMS 源项注入**：`cfg['mms_S_A_field'/'mms_S_B_field'/'mms_S_s_field']`（默认 None，供 V&V，`sjtu_tpmshx/pipelines/run_stack_3d.py:1233-1235`）。
- **审计导出**：`cfg['_emit_audit']=True` 时深拷贝导出 SIMPLE 面阵列/掩模/K/ε/ρcp/χ（默认关闭，代价大，`sjtu_tpmshx/pipelines/run_stack_3d.py:2043-2106`）；`cfg['audit_zero_K_ffB_at_outlet']` H2 诊断钩（`:1153-1171`）。
- **sweep_profile**：`'fast_sweep'`（15³、3 外循环、紧凑 CSV 行日志）/ `'full_validate'` / None（`sjtu_tpmshx/pipelines/run_stack_3d.py:359-376,1817-1830`）。
- **流体注册表**：物性/Nu/flow_model 均经 `solvers.fluid_props.get(name)` 分派，新流体在 solvers 层注册，管线自动跟随（`sjtu_tpmshx/pipelines/solve_2d.py:674-679`；`sjtu_tpmshx/pipelines/run_stack_3d.py:456-464`）。
- **保留分支/退路开关**：`conservative_ltne=False` 回退 legacy cell-local kernel（`sjtu_tpmshx/pipelines/run_stack_3d.py:1224-1228`）；`force_cc_ltne`（被 conservative_ltne 覆盖，`:1271-1281`）；`ltne_enthalpy_mode`（sCO2 焓形式 LTNE，`:1248-1253,1311-1337`）。

## 已知不足与 TODO

- `NotImplementedError` 两处：2D zoned 非 air（`sjtu_tpmshx/pipelines/stages_2d.py:73`）；3D water Fluid A（`sjtu_tpmshx/pipelines/run_stack_3d.py:458`）。
- Phase A/B/C 加速旗标"UI checkbox TBD"，目前仅 env 入口（`sjtu_tpmshx/pipelines/run_stack_3d.py:87`）。
- 2D `cancel_token` 被动——求解器内循环不轮询取消，最坏等一整轮（`sjtu_tpmshx/pipelines/stages_2d.py:637-641`）；3D 只在外循环边界可取消（`sjtu_tpmshx/pipelines/run_stack_3d.py:1010-1012`）。
- 3D 可压反向流（constant-ρcp kernel）的严格守恒是已知的 kernel 级限制，`_balance_stream_outflow` 明确不覆盖（`sjtu_tpmshx/pipelines/run_stack_3d.py:1191-1198`）。
- sCO2 3D 耦合 duty / 冷侧出口不可信（残余焓-cpT 差，>10% 失衡即 warn；完整修复=焓形式 kernel，`sjtu_tpmshx/pipelines/run_stack_3d.py:1706-1730`）。
- 反向流密度帧修正（#5）门控在 sCO2：air/water 反向流保留 legacy 镜像帧（误差在已接受的 B 侧失衡内；通用修复需全量再验证，`sjtu_tpmshx/pipelines/run_stack_3d.py:1519-1535,1371-1373`）。
- `per_cell_chi_b` 曾试作默认后回退（Shanghai 部分-B 下掩模失真 + 7% 质量失衡），生产默认 `'none'`，partial-B 物理待重审（`sjtu_tpmshx/pipelines/run_stack_3d.py:1062-1071,1216-1222`）。
- 壁面 BL 均质化 h_v 高估问题（Q_sA 超 NTU 上界 5-25%）标注为超出当前范围的研究项（`sjtu_tpmshx/pipelines/run_stack_3d.py:922-932`）。
- 热弥散 `disp_C_*` 的 D_h 用均匀胞元几何，zoned 逐格化被注释为待办（`sjtu_tpmshx/pipelines/run_stack_3d.py:717-719`）。B4 结论：C_DISP=0 是正确默认（与拟合 Nu 双计），不要贸然开启（来源为研究台账，未在本包代码内验证）。
- `_build_partial_masks` 的 cross2 语义与 UI 标签（`in_z_*`）在 ±z 流向下不符，注释预留未来 UI relabel（`sjtu_tpmshx/pipelines/stages_3d_helpers.py:48-49`）。
- 3D zoned 路径不做 asym split（uniform-only-δ 例外，`sjtu_tpmshx/pipelines/run_stack_3d.py:489-490`）。

## 服务器移植注意

- **路径可移植性（不涉及 Linux，同为 Windows 无需处理跨 OS 路径分隔符/大小写敏感问题）**：pipelines 九个文件内无硬编码盘符或绝对路径；唯一文件系统访问是 `.profile_3d` 旗标文件，用 `os.path` 相对包根拼接（`sjtu_tpmshx/pipelines/run_stack_3d.py:154-157`），换到服务器上不同盘符/安装目录（例如部署在服务器的 `C:\...` 而非开发机的 `D:\Postgraduate\...`）不受影响。
- **Qt-free 契约**：本层不 import Qt/matplotlib（各模块 docstring 声明，`sjtu_tpmshx/pipelines/stages_2d.py:5-7`、`sjtu_tpmshx/pipelines/stages_3d.py:14-15`；import 段核实无 Qt），headless 服务器可直接驱动 `Pipeline2D/3D` 或 `_run_3d_stack`。GUI 相关的 onboarding/offscreen 问题在 ui 层，不在此包。
- **并行模型 = OS 线程 + GIL 释放**：2D A/B SIMPLE（`sjtu_tpmshx/pipelines/solve_2d.py:933-958`）与 3D `_run_two_simple_parallel`（`sjtu_tpmshx/pipelines/run_stack_3d.py:184-242`）依赖 numba njit 与 PyAMG/BiCGStab/spsolve 释放 GIL，用 `threading.Thread`（非 `multiprocessing`）跑两个求解实例（`run_stack_3d.py:199,222-223`）。不依赖 `fork()` 语义——这一点对 Windows Server 反而是有利因素：Windows 从不支持 POSIX `fork`，`multiprocessing` 在 Windows 上默认走 `spawn`（进程重新导入模块、开销更大），而本层完全不用 `multiprocessing`，纯线程模型在 Windows 开发机与 Windows Server 上行为一致，不需要额外处理。若移植改用无 GIL 释放的求解后端，并行收益归零（正确性不受影响——两实例无共享可变状态）。
- **依赖**：numpy、scipy（`ndimage.gaussian_filter`、`interpolate.RegularGridInterpolator`、`sjtu_tpmshx/pipelines/solve_2d.py:377`）为管线直接依赖；numba/PyAMG/CoolProp（sCO2）经 solvers 层间接依赖。sCO2 路径 import `solvers.sco2_props`（`sjtu_tpmshx/pipelines/run_stack_3d.py:22`）——服务器需装 CoolProp 才能走 sCO2 分支（air/water 路径不触发该 import 的实际调用；模块级 import 本身是否强依赖 CoolProp 取决于 sco2_props 的 import 结构，未验证）。`requirements.txt` 锁定的 `numpy>=2.0`、`scipy>=1.13`、`numba>=0.60`、`pyamg>=5.2`、`CoolProp>=6.4` 在 PyPI 上均发布 Windows 官方 wheel（含 numba 绑定的 llvmlite），Windows Server 上直接 `pip install -r requirements.txt` 即可，不需要编译工具链，也没有 apt 之类的系统包管理器等价物需要操心（版本号已核实，wheel 可用性基于 PyPI 惯例、未逐一实测下载）。
- **位一致（golden gate）敏感项**：golden 3D 需 `PYTHONHASHSEED=0`（repo 约定，见 `.claude/commands/check.md`；未在 pipelines 代码内实现）；numba fastmath 存在 ULP 级平台/机器差异（研究台账记录，未在本包代码内验证）。开发机与服务器同为 Windows，不存在 Linux/Windows 平台差异这一层风险，但仍是两台不同物理机器——NumPy/SciPy 实际绑定的 BLAS 后端（如 MKL vs OpenBLAS）、CPU 指令集（AVX2/AVX-512 等）可能不同，golden 逐位对比仍可能因此失败——先确认数值量级一致再考虑重基线。
- **环境变量清单**（见上表）：服务器批跑脚本须显式管理 `TPMSHX_SIMPLE_TOL`（优先级最高，遗留残值会静默改精度）、`TPMSHX_MAX_CELLS_3D`（默认 2e6 网格上限按 ~50 个 float64 数组估算内存，`sjtu_tpmshx/pipelines/run_stack_3d.py:419-433`）。
- **数据文件**：pipelines 本身不读数据文件，但下游 `df_surrogate.predict` 的标定依赖 gitignored 的 `data/raw_data`——fresh checkout/worktree 缺该目录时 DF 标定回退 CSV，数值有 ULP 级差异（repo 经验记录，未在本包代码内验证）。
- **日志与编码（GBK 坑不会因为目标改成 Windows Server 而消失——此前按 Linux 目标写的判断方向是反的，已订正）**：本层 `_log.info` 输出均为 ASCII（如 `[PROF]`、`[SWEEP-CSV]`、`[ZONE]`），这本身是好事，且在 Windows Server 上依然要保持——本包只要坚持 ASCII-only 日志就不会触发下面这条坑。但 repo 其他层已有实证：中文日志经 subprocess 在 GBK 控制台下以 GBK 字节写出，而 pytest 按 UTF-8 读 capture 流，会以 `UnicodeDecodeError` 污染全部后续测试 teardown（`sjtu_tpmshx/df_surrogate/surrogate_v3.py:151-166` 的注释明确记录了这一机制并因此把该模块的日志强制改成 ASCII-only）。中文区域设置的 Windows Server 2022 默认控制台代码页同样是 GBK/CP936（不是 Linux 的 UTF-8 locale），这个坑**不会随平台切换而消失**，服务器批跑仍需显式处理：打印中文前 `sys.stdout.reconfigure(encoding='utf-8')`（repo 内已有多处这种自救模式，如 `sjtu_tpmshx/df_surrogate/predict.py:328`、`sjtu_tpmshx/ui/math_symbols.py:134`），或整体设 `PYTHONIOENCODING=utf-8` 环境变量（后者未在本仓库代码内实际设置过，是通用 Python 方案，未在本项目验证）。长跑请用 `python -u` 防 stdout 块缓冲假死（repo 约定）。
- **性能剖析**：服务器诊断慢跑首选 `TPMSHX_PROFILE_3D=1`（每个 SIMPLE/LTNE 解的墙钟+迭代数+残差轨迹，零成本关断，`sjtu_tpmshx/pipelines/run_stack_3d.py:117-181`）。
