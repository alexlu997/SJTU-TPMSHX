# solvers — 场生成与网格
生成日期 2026-07-10，基于 commit f33d30e 附近的 master

本篇覆盖 `sjtu_tpmshx/solvers/` 下 7 个文件：`continuous_field.py`、`sigmoid_field.py`、`sigmoid_field_3d.py`、`polygon_fvm.py`、`unstructured_mesh.py`、`grid_schema.py`、`zone_config.py`。所有断言均以代码为唯一真源，附 file:line 溯源；无法在代码中核实之处显式标注「未验证」。

## 定位与功能

这一组模块负责把「空间上变化的 TPMS 几何设计」变成求解器可消费的**逐单元物性数组**（per-cell property arrays），以及提供一条独立的多边形域非结构网格 FVM 支线。共有三代/三类 ε 场表达方式并存：

1. **ContinuousFieldConfig（现役，优化器路径）** — `sjtu_tpmshx/solvers/continuous_field.py:221`。以 4×4 控制点（可 Y 镜像，16-D 决策向量）的双三次 B-spline 插值生成连续 L(x,y)、t(x,y) 场，再经量化查询 `tpms_calc.compute` 组装成物性数组。qNEHVI 优化器 2D/3D 评估器均走此路径（`sjtu_tpmshx/optimization/evaluator.py:68`、`sjtu_tpmshx/core/evaluators.py:45`）。
2. **Sigmoid 场（旧优化器表达，UI Pareto 复算保留）** — `sjtu_tpmshx/solvers/sigmoid_field.py:240`（2D，36-D 决策向量）、`sjtu_tpmshx/solvers/sigmoid_field_3d.py:102`（3D，108-D）。2D 版仍被 UI Compute 路径在「grid 分区 + pareto_x_decision」时调用（`sjtu_tpmshx/pipelines/stages_2d.py:163-177`）；3D 版仅被 `sjtu_tpmshx/ui/demo_vis_3d.py:41` 与测试调用，生产 3D 优化路径改用 `core/evaluators._build_3d_arrays`（2D 场沿 z 均匀拉伸，`sjtu_tpmshx/core/evaluators.py:61-102`）。
3. **ZoneConfig 离散分区（对优化器已废弃，UI Compute「分区定义」保留）** — `sjtu_tpmshx/solvers/zone_config.py:58`。模块头部明确声明 DEPRECATED FOR OPTIMIZER USE（`sjtu_tpmshx/solvers/zone_config.py:4-15`），仅供 UI Compute 路径的分区表使用；UI 侧注释同样确认该保留意图（`sjtu_tpmshx/ui/builders_canvas.py:905-908`）。

`grid_schema.py` 钉住上述 2D 构建器的输出契约；`unstructured_mesh.py` + `polygon_fvm.py` 是独立的多边形域三角网格 FVM 支线（Darcy-Forchheimer 速度 + LTNE 能量），仅由 UI 的多边形计算入口触达（`sjtu_tpmshx/ui/mixins/run_controller.py:343-345` → `sjtu_tpmshx/runs/polygon_calc.py:22`）。

### 连续 ε 场 / 分区配置进入求解器的四条路径

| 路径 | 场构建 | 进入求解器的方式 |
|---|---|---|
| 优化器 2D | `from_decision_vector` → `ContinuousFieldConfig.build_grid_arrays`（`sjtu_tpmshx/optimization/evaluator.py:463,484`） | `arrays['eps_arr']` 转置后写入 `SIMPLESolver.eps_field`（A 侧转置 `sjtu_tpmshx/optimization/evaluator.py:264-268`；B 侧 y 翻转 `sjtu_tpmshx/optimization/evaluator.py:321-323`）；K/c_F 经 `override_simple_K_cF` 按行投影（`sjtu_tpmshx/optimization/evaluator.py:272-273`），`cfg['per_cell_K']=True` 时改用逐单元 `set_K_cF_field`（`sjtu_tpmshx/optimization/evaluator.py:276-278`） |
| 优化器 3D | 同一 2D 场经 `_build_3d_arrays` 沿 z 拉伸（`sjtu_tpmshx/core/evaluators.py:83-101`） | `project_fields_to_streamwise_K_cF_3d` 投影 K/c_F（`sjtu_tpmshx/core/evaluators.py:152-154`） |
| UI Compute 分区 | 1D 分区 → `ZoneConfig.build_structured_arrays`；grid 分区 → `ZoneConfig.build_grid_arrays` 或（选中 Pareto 解时）`sigmoid_field.build_continuous_arrays`（`sjtu_tpmshx/pipelines/stages_2d.py:150-211`） | `za['eps_arr']` 坐标变换后写入 `SIMPLESolver.eps_field`（`sjtu_tpmshx/pipelines/stages_2d.py:528-532`）；y 轴 1D 分区时 `zone_config` 直接传入 `SIMPLESolver`，其 `__init__` 按行调用 `predict_K_cF_vec` 生成 `_K_arr/_cF_arr`（`sjtu_tpmshx/solvers/simple_solver.py:390-408`）；其余含 `L_field/t_field` 的 za 经 `override_simple_K_cF` 覆写（`sjtu_tpmshx/pipelines/stages_2d.py:540-544`） |
| 多边形域 | `zone_config.build_unstructured_arrays`（y 向 1D 分区投影到三角单元，`sjtu_tpmshx/solvers/polygon_fvm.py:875-895`） | 逐单元 K/c_F 由 `predict_K_cF_vec` 生成后传入 Darcy 求解器 |

注意：UI Compute 路径对**离散**分区数组做 `gaussian_filter(sigma=2.0)` 平滑（`sjtu_tpmshx/pipelines/stages_2d.py:213-220`），`axis=='continuous'`（sigmoid 场）跳过平滑。

## 文件一览

| 文件 | 一行职责 |
|---|---|
| `sjtu_tpmshx/solvers/continuous_field.py` | 16-D B-spline 控制点 → 连续 L/t 场 → 量化散播生成逐单元物性数组（现役优化器表达） |
| `sjtu_tpmshx/solvers/sigmoid_field.py` | 36-D 分区控制点的 2D sigmoid paint-over 混合场 + GeometryLUT（ε、A_0 查表）；AIR-ONLY 物性构建器 |
| `sjtu_tpmshx/solvers/sigmoid_field_3d.py` | 108-D 决策向量的 3D 张量积 sigmoid 场；仅 demo/测试消费，非生产 3D 路径 |
| `sjtu_tpmshx/solvers/grid_schema.py` | 2D 网格数组构建器的输出契约（键名、shape、dtype）校验 |
| `sjtu_tpmshx/solvers/zone_config.py` | 离散 Zone 分区（1D 带 / 2D 矩形格）物性数组构建；优化器已废弃，UI Compute 保留 |
| `sjtu_tpmshx/solvers/unstructured_mesh.py` | 任意多边形域三角网格生成（constrained Delaunay，带 scipy 回退）、连通性与边界分类 |
| `sjtu_tpmshx/solvers/polygon_fvm.py` | 三角网格上的 Darcy-Forchheimer 速度解 + LTNE 三温 Gauss-Seidel 能量解（含一个未被生产调用的 SIMPLE 变体） |

## 公开接口

### continuous_field.py

- `decision_dim(n_ctrl_x=4, n_ctrl_y=4, symmetric_y=True) -> int` — `sjtu_tpmshx/solvers/continuous_field.py:56`。决策向量长度 `2·n_ctrl_x·⌈n_ctrl_y/2⌉`（对称时）；默认布局 = 16。调用方：`sjtu_tpmshx/runs/run_port_dim_retest.py:51`、`optimization/optimizer_qnehvi.py`。
- `decision_bounds(...) -> (lb, ub)` — `sjtu_tpmshx/solvers/continuous_field.py:68`。上下界来自 ConstDF-v1 训练凸包 `TRAIN_L=(4.0, 8.0)`、`TRAIN_T=(0.3, 0.5)` mm（定义于 `sjtu_tpmshx/df_surrogate/_domain.py:13-14`，在 `sjtu_tpmshx/solvers/continuous_field.py:50` 导入为 `DEFAULT_L_BOUNDS/DEFAULT_T_BOUNDS`）。
- `decode_decision_vector(x, ...) -> (L_full, t_full)` / `encode_decision_vector(...)` — `sjtu_tpmshx/solvers/continuous_field.py:84` / `:124`。布局 `[L_half_flat, t_half_flat]`；`symmetric_y` 时 y 下半镜像补全（奇数 My 去缝行，`sjtu_tpmshx/solvers/continuous_field.py:110-114`）。`encode` 不校验输入对称性（docstring，`sjtu_tpmshx/solvers/continuous_field.py:129-131`）。
- `props_from_Lt_fields(L_field, t_field, tpms_type, k_s, u_A, u_B, T_inA, T_inB, P_in=101325.0, *, quant_L=0.05, quant_t=0.01) -> dict` — `sjtu_tpmshx/solvers/continuous_field.py:146`。将 (L, t) 量化到 (0.05, 0.01) mm 格，对每个唯一对调用两次 `tpms_calc.compute`（A/B 侧，`sjtu_tpmshx/solvers/continuous_field.py:198-199`），布尔掩码散播。返回 9 个物性数组 + `n_unique`（`sjtu_tpmshx/solvers/continuous_field.py:208-214`）。调用方：`ContinuousFieldConfig.build_grid_arrays`（`sjtu_tpmshx/solvers/continuous_field.py:337`）与 3D 构建器 `sjtu_tpmshx/core/evaluators.py:78-81`——2D/3D 共享同一量化+散播实现。
- `ContinuousFieldConfig`（dataclass）— `sjtu_tpmshx/solvers/continuous_field.py:221`。字段：`ctrl_x/ctrl_y`（控制点坐标 [m]）、`L_ctrl/t_ctrl`（(Mx,My) [mm]）、`tpms_type`、`k_s`、`L_domain/H_domain` [m]、`spline_order=3`、`L_bounds/t_bounds`。`__post_init__` 构建两个 `scipy.interpolate.RectBivariateSpline`，阶数被钳到 `min(spline_order, M-1)`（`sjtu_tpmshx/solvers/continuous_field.py:269-275`）；每轴至少 2 个控制点（`sjtu_tpmshx/solvers/continuous_field.py:265-267`）。
  - `evaluate_grid(Nx, Ny, dx_arr=None, dy_arr=None)` — `sjtu_tpmshx/solvers/continuous_field.py:288`。在单元中心求值并 clip 到 bounds（`sjtu_tpmshx/solvers/continuous_field.py:310-311`）；支持非均匀网格（由 dx_arr/dy_arr 累加得单元中心）。
  - `build_grid_arrays(Nx, Ny, u_A, u_B, T_inA, T_inB, P_in=101325.0, ...) -> dict` — `sjtu_tpmshx/solvers/continuous_field.py:316`。输出经 `validate_grid_arrays` 校验（`sjtu_tpmshx/solvers/continuous_field.py:341-357`），`zone_id` 全 0、`axis='continuous'`、附 `L_field/t_field/cache_size`。调用方：`sjtu_tpmshx/optimization/evaluator.py:484`、`sjtu_tpmshx/runs/run_m1_uniform_vs_graded.py:168`。
  - `manufacturability_penalty(grad_threshold=0.5, ratio_bounds=(0.035, 0.20), weight_grad=100.0, weight_ratio=1000.0) -> float` — `sjtu_tpmshx/solvers/continuous_field.py:361`。软惩罚：控制点间 |ΔL| 超过 `0.5·L_avg` 及 t/L 越界（`DEFAULT_RATIO_BOUNDS` 定义于 `sjtu_tpmshx/solvers/continuous_field.py:53`）。
- `from_decision_vector(x, tpms_type, k_s, L_domain, H_domain, ...) -> ContinuousFieldConfig` — `sjtu_tpmshx/solvers/continuous_field.py:406`。控制点沿两轴等距分布。调用方：`sjtu_tpmshx/optimization/evaluator.py:463`、`sjtu_tpmshx/core/evaluators.py:139`、`sjtu_tpmshx/optimization/export_ntop_csv.py:90`。
- `uniform_field(L_mm, t_mm, ...)` — `sjtu_tpmshx/solvers/continuous_field.py:439`。均匀场构造器（对照/测试用），多个测试消费（如 `sjtu_tpmshx/tests/test_evaluator_frozen_values.py:147`）。

### sigmoid_field.py

- `sigmoid_field_2d(XF, YF, ctrl_inlet, ctrl_outlet, val_uniform, y_trans_in, y_trans_out, width_x=0.05, width_y=0.02)` — `sjtu_tpmshx/solvers/sigmoid_field.py:48`。3×3 入口区 + 均匀区 + 3×3 出口区共 7 层沿 y 的 paint-over sigmoid 混合（y 边界公式 `sjtu_tpmshx/solvers/sigmoid_field.py:90-97`）；sigmoid 指数被 clip 到 ±50 防溢出（`sjtu_tpmshx/solvers/sigmoid_field.py:29`）。
- `GeometryLUT(tpms_type, L_range=(4.0, 8.0), t_range=(0.3, 0.5), n_L=41, n_t=21, N=256, cache_dir=None)` — `sjtu_tpmshx/solvers/sigmoid_field.py:104`。ε(L,t)、A_0(L,t) 双线性查表；磁盘缓存 `.npz` 文件名含 N（体素分辨率），`_load` 校验 tpms_type/N/L_vals/t_vals 不匹配即重算（`sjtu_tpmshx/solvers/sigmoid_field.py:126-127`、`:167-187`）。插值器 `bounds_error=False, fill_value=None` → 范围外线性外推（`sjtu_tpmshx/solvers/sigmoid_field.py:134-139`）。`query(L_arr, t_arr)` 形状无关（`sjtu_tpmshx/solvers/sigmoid_field.py:189`）。
- `get_geometry_lut(tpms_type, **kwargs)` — `sjtu_tpmshx/solvers/sigmoid_field.py:205`。进程内单例缓存，key 含全部 kwargs（W7 修复，`sjtu_tpmshx/solvers/sigmoid_field.py:214-219`）。
- `_nu_vec(tpms_type, Re, eps, L_mm, D_h_mm)` — `sjtu_tpmshx/solvers/sigmoid_field.py:224`。5 参遗留签名薄包装，`eps` 被忽略，委托 `nu_correlations.nu_vec`（`sjtu_tpmshx/solvers/sigmoid_field.py:234-235`）；被 `sigmoid_field_3d.py:25` 与 `validation/cases/validate_shanghai_3d_real.py:100` 复用。
- `build_continuous_arrays(x, L0, t0, y_trans_inlet, y_trans_outlet, Nx, Ny, L_domain, H_domain, tpms_type, k_s, u_A, u_B, T_inA, T_inB, lut, P_in=101325.0, ..., allow_extrap=None, fluid_type='air') -> dict` — `sjtu_tpmshx/solvers/sigmoid_field.py:240`。x 为 36 维 `[L1,t1,...,L18,t18]`（入口 9 区 + 出口 9 区）。**AIR-ONLY**：`fluid_type != 'air'` 抛 `NotImplementedError`（`sjtu_tpmshx/solvers/sigmoid_field.py:330-334`）。Re 下限 10（`sjtu_tpmshx/solvers/sigmoid_field.py:343-344`）；`K_ss = chi_s_eff(type, ε)·(1−ε)·k_s`（`sjtu_tpmshx/solvers/sigmoid_field.py:363-364`）；返回 `eps_f_arr = eps_arr/2`、`axis='continuous'`（`sjtu_tpmshx/solvers/sigmoid_field.py:369,379`）。生产调用方：`sjtu_tpmshx/pipelines/stages_2d.py:167-176`。

### sigmoid_field_3d.py

- `sigmoid_field_3d(XF, YF, ZF, ctrl_inlet, ctrl_outlet, val_uniform, ...)` — `sjtu_tpmshx/solvers/sigmoid_field_3d.py:57`。3×3×3 控制立方的张量积 paint-over（x→z→y）。
- `build_continuous_arrays_3d(x, L0, t0, ..., Nx, Ny, Nz, L_domain, H_domain, D_domain, ..., lut, ...) -> dict` — `sjtu_tpmshx/solvers/sigmoid_field_3d.py:102`。x 必须为 (108,)，否则 `ValueError`（`sjtu_tpmshx/solvers/sigmoid_field_3d.py:133-134`）；同样 AIR-ONLY（`sjtu_tpmshx/solvers/sigmoid_field_3d.py:198-202`）；返回全 (Nx,Ny,Nz) 数组、`axis='continuous_3d'`（`sjtu_tpmshx/solvers/sigmoid_field_3d.py:243`）。调用方仅 `sjtu_tpmshx/ui/demo_vis_3d.py:41,174` 及测试 `tests/test_sigmoid_field_3d.py` —— 非生产 3D 优化路径。

### grid_schema.py

- `GRID_ARRAY_KEYS` — `sjtu_tpmshx/solvers/grid_schema.py:22-27`。9 个必备键：`eps_arr, eps_f_arr, K_ffA_arr, K_ffB_arr, K_ss_arr, h_vA_arr, h_vB_arr, r_h_arr, A_0_arr`。
- `validate_grid_arrays(d, Nx, Ny, *, where) -> dict` — `sjtu_tpmshx/solvers/grid_schema.py:30`。校验各键存在、ndarray、shape=(Nx,Ny)、float64；`zone_id` 整型 (Nx,Ny)；`axis` 键存在；违反即 `ValueError` 列出全部问题。仅两个构建器调用：`ZoneConfig.build_structured_arrays`（`sjtu_tpmshx/solvers/zone_config.py:168-196`）与 `ContinuousFieldConfig.build_grid_arrays`（`sjtu_tpmshx/solvers/continuous_field.py:341`）。**`ZoneConfig.build_grid_arrays`（grid 矩形模式）与两个 sigmoid 构建器的返回字典未经此校验**（`sjtu_tpmshx/solvers/zone_config.py:305-320`、`sjtu_tpmshx/solvers/sigmoid_field.py:366-380`、`sjtu_tpmshx/solvers/sigmoid_field_3d.py:230-244` 均直接 return 裸 dict）。该模块只覆盖 2D (Nx,Ny) 形状，3D 数组无对应契约校验。

### zone_config.py

- `Zone(name, y_frac_start, y_frac_end, L_mm, t_mm)` — `sjtu_tpmshx/solvers/zone_config.py:45`。`props_A/props_B` 由 `compute_properties` 填充。
- `ZoneConfig(zones, tpms_type, k_s)` — `sjtu_tpmshx/solvers/zone_config.py:58`。
  - `validate()` — `sjtu_tpmshx/solvers/zone_config.py:66`。分区须无缝覆盖 [0,1]；限幅 `L_mm ∈ [1, 20]`、`t_mm ∈ [0.1, 2.0]`（`sjtu_tpmshx/solvers/zone_config.py:90-93`）——比 ConstDF-v1 训练域宽得多，越出训练域由 surrogate 侧另行处理。
  - `compute_properties(u_A, u_B, T_inA, T_inB, P_in=101325.0)` — `sjtu_tpmshx/solvers/zone_config.py:99`。逐区调用 `tpms_calc.compute`（必须先于 build_* 调用，否则 `RuntimeError`，`sjtu_tpmshx/solvers/zone_config.py:127`）。
  - `build_structured_arrays(Nx, Ny, H, axis='y') -> dict` — `sjtu_tpmshx/solvers/zone_config.py:112`。1D 分区带沿 y 或 x 复制成 (Nx,Ny) 数组，输出经 grid_schema 校验并附 `zone_params` 列表。调用方：`sjtu_tpmshx/pipelines/stages_2d.py:201`。
  - `build_grid_arrays(Nx, Ny, L, H, grid_cells, tpms_type, k_s, u_A, u_B, T_inA, T_inB, P_in=101325.0, dx_arr=None, dy_arr=None)`（staticmethod）— `sjtu_tpmshx/solvers/zone_config.py:201`。2D 矩形分区（`grid_cells` 每项含 x0/x1/y0/y1/L/t）；未被任何矩形覆盖的单元**静默回退到 grid_cells[0] 的物性**（`sjtu_tpmshx/solvers/zone_config.py:289-303`）；返回 `axis='grid'` + `y_bounds/x_bounds`。调用方：`sjtu_tpmshx/pipelines/stages_2d.py:180`。
  - `build_unstructured_arrays(cell_centers_y, n_cells, H) -> dict` — `sjtu_tpmshx/solvers/zone_config.py:324`。按单元中心 y 坐标做 1D 分区查找，输出 1D 数组。调用方：`sjtu_tpmshx/solvers/polygon_fvm.py:875`。
  - `single_zone(L_mm, t_mm, tpms_type, k_s)`（staticmethod）— `sjtu_tpmshx/solvers/zone_config.py:408`。
- `compute_zone_statistics(...)` / `format_zone_report(...)` — `sjtu_tpmshx/solvers/zone_config.py:422` / `:504`。逐区温度/速度/压力统计（可 cell_area 加权），后处理用；调用方 `sjtu_tpmshx/pipelines/solve_2d.py:294-306`。
- 另有直接接收 `ZoneConfig` 实例的消费者：`SIMPLESolver.__init__(zone_config=...)` 按行生成 `_K_arr/_cF_arr`（`sjtu_tpmshx/solvers/simple_solver.py:390-408`，仅 y 轴 1D 分区时由 `sjtu_tpmshx/pipelines/stages_2d.py:451,497` 传入）。

### unstructured_mesh.py

- BC 码常量 — `sjtu_tpmshx/solvers/unstructured_mesh.py:17-22`：`BC_INTERIOR=0, BC_WALL=1, BC_INLET_A=2, BC_OUTLET_A=3, BC_INLET_B=4, BC_OUTLET_B=5`。
- `TriMesh.from_polygon(vertices, max_area=None, n_edge_pts=20)`（staticmethod）— `sjtu_tpmshx/solvers/unstructured_mesh.py:56`。优先用第三方 `triangle` 库做 constrained Delaunay（选项 `pq30a{max_area}`，最小角 30°，`sjtu_tpmshx/solvers/unstructured_mesh.py:87`）；**任何异常都静默回退**到 scipy Delaunay + 多边形裁剪（`sjtu_tpmshx/solvers/unstructured_mesh.py:93-95` 的裸 `except Exception`，`_fallback_mesh` 定义于 `:175`）。顶点须 CCW 顺序（`inlet_normal` 的内法向公式依赖 CCW，`sjtu_tpmshx/solvers/unstructured_mesh.py:158-168`）。
- `TriMesh.set_pipes(pipes)` — `sjtu_tpmshx/solvers/unstructured_mesh.py:109`。在多边形边上按分数区间 [frac_start, frac_end] 标注 inlet/outlet BC。
- 网格属性：`nbr/face_len/face_nx/face_ny/dCF/bc_type` 均为 (N_cells, 3) 数组（`sjtu_tpmshx/solvers/unstructured_mesh.py:39-46`）；边界面默认 `BC_WALL`（`sjtu_tpmshx/solvers/unstructured_mesh.py:320`）。
- 预置形状：`rectangle/regular_polygon/hexagon/octagon` — `sjtu_tpmshx/solvers/unstructured_mesh.py:351-377`。

### polygon_fvm.py

- `solve_velocity_darcy(mesh, tpms_type, L_mm, t_mm, eps, r_h, rho, mu, T_in, u_in, edge_in, bc_inlet, bc_outlet, max_iter=30, tol=1e-3, verbose=True, K_arr=None, cF_arr=None, **_ignored)` — `sjtu_tpmshx/solvers/polygon_fvm.py:318`。直接解 ∇·(D∇P)=0（D=1/R，R=μ/K+ρ·c_F·|u|），Picard 迭代更新 R（欠松弛 0.7/0.3，`sjtu_tpmshx/solvers/polygon_fvm.py:492`）；均匀几何时 K/c_F 来自 `predict_K_cF(tpms_type, L, t, eps/2)`（`sjtu_tpmshx/solvers/polygon_fvm.py:343-345`）；单元速度上限钳到 20× 入口速度（`sjtu_tpmshx/solvers/polygon_fvm.py:430`）。**这是多边形路径的生产速度求解器**（`solve_polygon_domain` 对 A/B 两流体均调用它，`sjtu_tpmshx/solvers/polygon_fvm.py:898-907`）。
- `solve_velocity_simple(...)` — `sjtu_tpmshx/solvers/polygon_fvm.py:510`。Brinkman-Forchheimer SIMPLE（collocated + Rhie-Chow）变体；docstring 自述仅适用于均匀几何、分区场景应改用 Darcy（`sjtu_tpmshx/solvers/polygon_fvm.py:517-519`）。**仓内未发现任何调用方**（仅定义，grep 全库无引用）——保留代码，非生产路径。
- `solve_energy(mesh, face_Un_A, face_Un_B, K_ffA, K_ffB, K_ss, h_vA, h_vB, rho_cp_fA, rho_cp_fB, epsilon, T_inA, T_inB, max_iter=50000, tol=1e-6, progress_cb=None)` — `sjtu_tpmshx/solvers/polygon_fvm.py:735`。LTNE 三温（Ta/Tb/Ts）Gauss-Seidel（numba `_energy_sweep`，`sjtu_tpmshx/solvers/polygon_fvm.py:611`）；**标量 epsilon 在内部减半为 eps_f = ε/2**（`sjtu_tpmshx/solvers/polygon_fvm.py:761-765`），与主 LTNE 路径「调用方传完整 ε」约定一致；数组输入亦除以 2（`:764-765`），调用方须传总 ε。
- `solve_polygon_domain(mesh, tpms_type, L_mm, t_mm, eps, D_h, rho_A, mu_A, rho_B, mu_B, T_inA, T_inB, u_A, u_B, edge_inA, edge_inB, K_ffA, K_ffB, K_ss, h_vA, h_vB, cp_f, A_0=None, ..., zone_config=None, **_ignored)` — `sjtu_tpmshx/solvers/polygon_fvm.py:842`。完整流程：Darcy×2 + LTNE 能量。`zone_config` 非 None 时经 `build_unstructured_arrays` + `predict_K_cF_vec` 生成逐单元 K/c_F/物性（`sjtu_tpmshx/solvers/polygon_fvm.py:867-895`）；`A_0` 非 None 时按局部 |u| 重算 h_v（`_compute_local_hv`，Re 下限 `_RE_FLOOR=800`，`sjtu_tpmshx/solvers/polygon_fvm.py:796,800-839`）。唯一生产调用方：`sjtu_tpmshx/runs/polygon_calc.py:163`（← UI `sjtu_tpmshx/ui/mixins/run_controller.py:343-345`）。

## 关键配置项与开关

| 配置项 | 默认值 | 定义处 |
|---|---|---|
| `DEFAULT_N_CTRL_X / DEFAULT_N_CTRL_Y` | 4 / 4 | `sjtu_tpmshx/solvers/continuous_field.py:40-41` |
| `DEFAULT_SYMMETRIC_Y` | `True` | `sjtu_tpmshx/solvers/continuous_field.py:42` |
| `DEFAULT_L_BOUNDS / DEFAULT_T_BOUNDS` | (4.0, 8.0) / (0.3, 0.5) mm | `sjtu_tpmshx/df_surrogate/_domain.py:13-14`（`continuous_field.py:50` 导入） |
| `DEFAULT_RATIO_BOUNDS`（t/L） | (0.035, 0.20) | `sjtu_tpmshx/solvers/continuous_field.py:53` |
| `quant_L / quant_t`（量化步长） | 0.05 / 0.01 mm | `sjtu_tpmshx/solvers/continuous_field.py:151-152`（`build_grid_arrays` 同默认，`:322-323`） |
| `spline_order` | 3（双三次；实际阶被钳到 M-1） | `sjtu_tpmshx/solvers/continuous_field.py:247,269-270` |
| `manufacturability_penalty` 权重 | grad_threshold=0.5, weight_grad=100, weight_ratio=1000 | `sjtu_tpmshx/solvers/continuous_field.py:362-365` |
| GeometryLUT 网格 | L_range=(4,8), t_range=(0.3,0.5), n_L=41, n_t=21, N=256 | `sjtu_tpmshx/solvers/sigmoid_field.py:111-112` |
| GeometryLUT 缓存目录 | `cache_dir=None` → **包内 solvers/ 目录** | `sjtu_tpmshx/solvers/sigmoid_field.py:118-119` |
| sigmoid 过渡宽度 | width_x=0.05, width_y=0.02（3D 加 width_z=0.05） | `sjtu_tpmshx/solvers/sigmoid_field.py:51`、`sigmoid_field_3d.py:60,108-110` |
| `allow_extrap`（kwarg）/ 环境变量 `TPMSHX_ALLOW_EXTRAP` | None → 读 env（'1'/'true'/'yes' 生效）；否则 clip L∈[4,8]、t∈[0.3,0.5] | `sjtu_tpmshx/solvers/sigmoid_field.py:303-321`、`sigmoid_field_3d.py:171-189` |
| `fix_L / fix_t` | False（固定 L 或 t 为 L0/t0，只优化另一变量） | `sjtu_tpmshx/solvers/sigmoid_field.py:246`、`sigmoid_field_3d.py:111` |
| `fluid_type` | 'air'（非 air 抛 NotImplementedError） | `sjtu_tpmshx/solvers/sigmoid_field.py:248,330-334`、`sigmoid_field_3d.py:113,198-202` |
| sigmoid 构建器 Re 下限 | 10.0 | `sjtu_tpmshx/solvers/sigmoid_field.py:343-344`、`sigmoid_field_3d.py:209-210` |
| `_RE_FLOOR`（polygon 局部 h_v） | 800.0 | `sjtu_tpmshx/solvers/polygon_fvm.py:796` |
| Zone 限幅 | L_mm ∈ [1,20]、t_mm ∈ [0.1,2.0] | `sjtu_tpmshx/solvers/zone_config.py:90-93` |
| `TriMesh.from_polygon` | max_area=None（按包围盒估算）、n_edge_pts=20、triangle 选项 `pq30…` | `sjtu_tpmshx/solvers/unstructured_mesh.py:56,85-87` |
| Darcy 迭代 | max_iter=30, tol=1e-3, R 欠松弛 0.7/0.3, 速度钳 20×u_in | `sjtu_tpmshx/solvers/polygon_fvm.py:321,430,492` |
| polygon SIMPLE 迭代 | max_iter=2000, tol=1e-5, alpha_u=0.5, alpha_p=0.2 | `sjtu_tpmshx/solvers/polygon_fvm.py:513-514` |
| LTNE 能量 | max_iter=50000, tol=1e-6, 500 次/块 | `sjtu_tpmshx/solvers/polygon_fvm.py:739,775` |
| 环境变量 `TPMSHX_CHI_S` | 未设置；设置后以常数覆盖逐类型拟合的 χ_s | 解析于 `sjtu_tpmshx/solvers/tpms_props.py:186`，`chi_s_eff` 定义于 `sjtu_tpmshx/solvers/tpms_props.py:192`，经 `sjtu_tpmshx/solvers/tpms_calc.py:51` 再导出；sigmoid 构建器引用见 `sjtu_tpmshx/solvers/sigmoid_field.py:363-364` |

## 边界·假设·适用范围

- **单位约定**：域尺寸、控制点坐标、面积均为 m；**TPMS 晶胞 L 与壁厚 t 为 mm**（`sjtu_tpmshx/solvers/continuous_field.py:229-232` docstring；`zone_config.py:50-51`）。温度 K，压力 Pa。速度为 interstitial（in-pore）约定（`sjtu_tpmshx/solvers/polygon_fvm.py:20-22`）。
- **ε 拆分约定**：本组构建器输出 `eps_arr` = 总 ε，`eps_f_arr` = 每流体侧 ε。`ContinuousFieldConfig`/`ZoneConfig` 路径的 `eps_f_arr` 取自 `tpms_calc.compute` 的 `epsilon_A`（`sjtu_tpmshx/solvers/continuous_field.py:201`、`zone_config.py:157,285`）；sigmoid 路径直接 `eps_arr/2`（`sjtu_tpmshx/solvers/sigmoid_field.py:369`、`sigmoid_field_3d.py:233`）。polygon 能量求解器内部把传入 ε 减半（`sjtu_tpmshx/solvers/polygon_fvm.py:761-765`）——**调用方一律传完整 ε**，与仓库硬不变量一致。
- **AIR-ONLY 限制**：两个 sigmoid 构建器硬编码空气 ρ/μ/k/Nu，非 air 流体直接抛错（`sjtu_tpmshx/solvers/sigmoid_field.py:330-334`、`sigmoid_field_3d.py:198-202`）。`ContinuousFieldConfig` 路径经 `tpms_calc.compute` 取物性（流体假设取决于 tpms_calc，超出本篇范围）。polygon 的 `_compute_local_hv` 同样硬编码空气物性且用 `P_atm`（`sjtu_tpmshx/solvers/polygon_fvm.py:812-813`）。
- **surrogate 训练域**：ConstDF-v1 训练凸包 L∈[4,8] mm、t∈[0.3,0.5] mm、Re∈[400,16000]（`sjtu_tpmshx/df_surrogate/_domain.py:13-15`）。越出后 `predict_K_cF` 将 K 钳到 1e-8 地板，导致 SIMPLE 收敛崩溃、设计被整批拒绝（注释警告，`sjtu_tpmshx/solvers/continuous_field.py:44-49`）。GeometryLUT 越界为线性外推（`sjtu_tpmshx/solvers/sigmoid_field.py:134-139`），与 clip/allow_extrap 机制配合。
- **B-spline 过冲**：样条可在边界附近越过控制点值，故 `L_at/t_at/evaluate_grid` 求值后一律 clip 到 bounds（防御性钳制，`sjtu_tpmshx/solvers/continuous_field.py:234-236,280-286,310-311`）。
- **polygon FVM 的物理范围**：不可压缩（`∇·U = 0`，`sjtu_tpmshx/solvers/polygon_fvm.py:8`）、常物性；与主 2D/3D SIMPLE 的可压缩 ideal-gas 路径**不同**——多边形支线不承担 Shanghai 验证基线，仅作任意形状域的示意计算。Darcy 求解器忽略 Brinkman 粘性项（纯 ∇·(D∇P)=0，`sjtu_tpmshx/solvers/polygon_fvm.py:326-329`）。
- **网格假设**：`TriMesh` 要求多边形顶点 CCW；三角形网格每单元恰 3 面（数组第二维硬编码 3）。`build_structured_arrays` 分区查找对最后一格用 fallback 到末区（`sjtu_tpmshx/solvers/zone_config.py:139-140`）。

## 可扩展接口

- **构建器输出契约（backend 注册点的事实标准）**：任何新的场构建器只要产出 `GRID_ARRAY_KEYS` + `zone_id` + `axis` 的 (Nx,Ny) float64 dict 并通过 `validate_grid_arrays`（`sjtu_tpmshx/solvers/grid_schema.py:30`），即可作为 drop-in producer 接入 2D 管线（模块 docstring 明言此意图，`sjtu_tpmshx/solvers/grid_schema.py:1-15`）。
- **`props_from_Lt_fields` 的 `quant_L/quant_t` 关键字**：调粗/调细量化步长以换取 `tpms_calc.compute` 调用次数（`sjtu_tpmshx/solvers/continuous_field.py:151-152`）。
- **`evaluate_grid(dx_arr, dy_arr)`**：非均匀网格挂钩（`sjtu_tpmshx/solvers/continuous_field.py:288-306`）；sigmoid 构建器同样接受 `dx_arr/dy_arr(/dz_arr)`（`sjtu_tpmshx/solvers/sigmoid_field.py:247`、`sigmoid_field_3d.py:112`）。
- **`GeometryLUT(cache_dir=...)`**：重定向磁盘缓存位置（`sjtu_tpmshx/solvers/sigmoid_field.py:112,118-119`）；`get_geometry_lut(**kwargs)` 支持自定义 L_range/t_range/n_L/n_t/N 的独立单例（`sjtu_tpmshx/solvers/sigmoid_field.py:205-219`）。
- **环境变量**：`TPMSHX_ALLOW_EXTRAP`（绕过 L/t clip，`sjtu_tpmshx/solvers/sigmoid_field.py:306-308`）；`TPMSHX_CHI_S`（χ_s 常数覆盖，解析于 `sjtu_tpmshx/solvers/tpms_props.py:186`，`chi_s_eff` 定义于 `sjtu_tpmshx/solvers/tpms_props.py:192` 并经 `sjtu_tpmshx/solvers/tpms_calc.py:51` 再导出）。
- **私有 kwargs / 预留参数**：`solve_velocity_darcy(K_arr=, cF_arr=)` 逐单元闭塞系数注入（成对提供否则 `ValueError`，`sjtu_tpmshx/solvers/polygon_fvm.py:340-342`）；`solve_polygon_domain(zone_config=, A_0=)` 二选一的空间变 h_v 机制（`sjtu_tpmshx/solvers/polygon_fvm.py:910-923`）；各 polygon 求解器签名尾部 `**_ignored` 吞掉多余关键字（`sjtu_tpmshx/solvers/polygon_fvm.py:323,515,850`）——移植时注意拼错的 kwarg 不会报错。`SIMPLESolver.__init__` 的 `**_legacy_kw` 同理并显式丢弃 `closure`（`sjtu_tpmshx/solvers/simple_solver.py:276-279`）。
- **`_nu_vec` 遗留 5 参签名**：为 `sigmoid_field_3d` 与旧测试保留的兼容层（`sjtu_tpmshx/solvers/sigmoid_field.py:224-235`），新代码应直接用 `nu_correlations.nu_vec`。

## 已知不足与 TODO

- **NotImplementedError（有意的守卫）**：非 air 流体的 zoned/graded 支持是明确的 deferred item——`sjtu_tpmshx/solvers/sigmoid_field.py:331-334`、`sjtu_tpmshx/solvers/sigmoid_field_3d.py:199-202`。
- **`zone_config.py` 整体对优化器废弃**：新优化代码禁止 import `ZoneConfig`（模块头声明，`sjtu_tpmshx/solvers/zone_config.py:4-15`）；仅 UI Compute 分区表消费。
- **`polygon_fvm.solve_velocity_simple` 无调用方**：完整实现保留但 grep 全库无引用；生产多边形路径只用 `solve_velocity_darcy`。`_correct_fields` 上有被注释掉的 `# @njit(cache=True)`（`sjtu_tpmshx/solvers/polygon_fvm.py:239`），即该函数曾计划 numba 化未完成。
- **`ZoneConfig.build_grid_arrays` 静默 fallback**：未被任何矩形覆盖的单元使用 `grid_cells[0]` 的物性且不告警（`sjtu_tpmshx/solvers/zone_config.py:289-303`）。
- **契约校验覆盖不全**：`ZoneConfig.build_grid_arrays`（grid 模式）与两个 sigmoid 构建器返回的 dict 未过 `validate_grid_arrays`（见上文 grid_schema 小节），且 3D (Nx,Ny,Nz) 数组无 schema 校验。
- **`unstructured_mesh.from_polygon` 的裸 except 回退**：`triangle` 库缺失或任何构网异常都静默转 scipy 回退网格（`sjtu_tpmshx/solvers/unstructured_mesh.py:93-95`），两种网格质量差异无日志提示——跨机器结果可比性风险。
- **已删除的遗留路径**：`compute_dP_continuous`（绕过 SIMPLE 的 f-Re dP 提取）2026-04-17 移除，注释留档（`sjtu_tpmshx/solvers/sigmoid_field.py:383-387`）；polygon SIMPLE docstring 提及 legacy f-Re closure 已于 2026-04-19 移除（`sjtu_tpmshx/solvers/polygon_fvm.py:22`）。
- **`encode_decision_vector` 不校验对称性**：非对称输入 + `symmetric_y=True` 不能精确 round-trip（docstring 自认，`sjtu_tpmshx/solvers/continuous_field.py:127-132`）。
- **sigmoid 3D 构建器与生产 3D 路径已分叉**：`build_continuous_arrays_3d` 仅 demo/测试消费；生产 3D 用 `core/evaluators._build_3d_arrays`（z 向拉伸 2D 场）。二者物性组装公式独立维护，修改时须双侧同步（3D builder 的 K_ss/χ_s 注释即为此类同步痕迹，`sjtu_tpmshx/solvers/sigmoid_field_3d.py:222-228`）。
- 范围内 7 个文件中未发现 `TODO`/`FIXME` 字面标记（已 grep 核实）。

## 服务器移植注意

- **GeometryLUT 默认把 `.npz` 缓存写进包目录**（`os.path.dirname(os.path.abspath(__file__))`，`sjtu_tpmshx/solvers/sigmoid_field.py:118-119`）。Linux 上若包装在只读位置（site-packages、只读挂载），首次构建 LUT 会在 `_save` 处抛 PermissionError——传 `cache_dir` 指向可写目录，或预热缓存后随包分发。缓存文件名 `lut_{type}_{n_L}x{n_t}_N{N}.npz`（`sjtu_tpmshx/solvers/sigmoid_field.py:126-127`）。
- **`triangle` 是可选依赖**（纯 C 扩展，Linux wheel 通常可用）。缺失时静默走 scipy 回退网格（`sjtu_tpmshx/solvers/unstructured_mesh.py:93-95`），单元数量与质量不同——如需与 Windows 端 polygon 结果逐位对比，必须两端同装或同缺 `triangle`。
- **numba `@njit(cache=True)`**（`sjtu_tpmshx/solvers/polygon_fvm.py:45,157,301,611`）在源码目录旁写 `__pycache__` 缓存；只读部署时 numba 会回退到临时目录或每次重编译（慢但可用）。首次调用有编译延迟。
- **import 风格混用**：`sigmoid_field.py`/`continuous_field.py`/`zone_config.py` 用包内相对 import（`from .tpms_calc import ...`），而 `sigmoid_field_3d.py`/`polygon_fvm.py` 混用 `from solvers.sigmoid_field import ...` 顶层绝对 import（`sjtu_tpmshx/solvers/sigmoid_field_3d.py:25-27`）以及 `from df_surrogate.predict import ...`（`sjtu_tpmshx/solvers/polygon_fvm.py:29`）。**运行时必须把 `sjtu_tpmshx/` 目录本身放进 sys.path**（使 `solvers`、`df_surrogate`、`logutil` 可作顶层包导入）——不能仅 `pip install` 成 `sjtu_tpmshx.solvers` 形式。
- **Qt/matplotlib 隔离**：本组 solvers/ 文件不 import PySide6；`unstructured_mesh.py` 只用 `matplotlib.path.Path`（无 GUI backend 需求，headless 安全，`sjtu_tpmshx/solvers/unstructured_mesh.py:14`）。多边形管线的 Qt/pyplot 依赖都在 `runs/polygon_calc.py`（`sjtu_tpmshx/runs/polygon_calc.py:11-15`），服务器上不 import 该文件即可避开 GUI 栈。
- **路径处理**：全部用 `os.path.join`/`os.path.dirname`，无硬编码盘符或反斜杠（`sjtu_tpmshx/solvers/sigmoid_field.py:119,126`）——跨平台安全。
- **可复现性**：`props_from_Lt_fields` 用 `np.unique` + `np.round`（round-half-even），确定性；`solve_velocity_simple` 用 `np.random.seed(hash((edge_in, int(u_in*1000))) % 2**32)`（`sjtu_tpmshx/solvers/polygon_fvm.py:533`）——整数 tuple 的 `hash()` 不受 PYTHONHASHSEED 影响，跨进程确定（但该函数无生产调用方）。仓库级 golden gate 另要求 `PYTHONHASHSEED=0`（见 `/check`，与本组文件无直接耦合，未在本篇内逐一核实）。
- **环境变量开关在 Linux shell 下同样生效**：`TPMSHX_ALLOW_EXTRAP=1` 绕过 L/t clip（`sjtu_tpmshx/solvers/sigmoid_field.py:306-308`）——批量脚本移植时注意不要无意继承该变量，否则 LUT/Nu 静默外推（仅 warning）。
- **磁盘缓存一致性**：GeometryLUT 的 `.npz` 校验 tpms_type/N/L_vals/t_vals（`sjtu_tpmshx/solvers/sigmoid_field.py:167-187`），跨机器复制缓存文件是安全的（不匹配即重算）；损坏文件被裸 except 吞掉并重算（`sjtu_tpmshx/solvers/sigmoid_field.py:183-187`，注释标注为有意行为）。
