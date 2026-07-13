# solvers — 闭合关系与物性
生成日期 2026-07-10，基于 commit f33d30e 附近的 master

> 本文档所有事实性断言均以代码为唯一真源，逐条附 file:line（相对仓库根 `sjtu_tpmshx/` 前缀）。行号对应本 worktree 当前文件状态；移植后若行号漂移，请以符号名（函数/常量名）重新定位。文档、注释中与代码不符的说法已标注。

## 定位与功能

本模块群位于 `sjtu_tpmshx/solvers/`，为 SIMPLE/LTNE 求解器提供**闭合关系（closure）与物性（properties）层**，包括：

- **Nu 关联式单一来源**（air / water / sCO2 三条谱系）：`nu_correlations.py`。
- **可压缩有效性包络守卫**：`envelope.py` —— 预解 choke 检查 + 后解 Mach / 正压守卫，三档模式 `raise`/`warn`/`off`（`sjtu_tpmshx/solvers/envelope.py:34`）。
- **非对称孔隙率（offset-isosurface δ）分相**：`asym_geometry.py`（体素 / marching-cubes 几何量）与 `asym_split.py`（2D/3D 管线共用的 ε 分配比，维度无关）。
- **表面粗糙度修正**：`roughness.py`（f 侧默认乘子 1.0，防止与实验锚定 cF 双重计数）。
- **流体物性**：`fluid_props.py`（per-fluid 原语注册表 + Nu 分派）、`tpms_props.py`（air/water 关联式 + χ_s，叶子模块）、`sco2_props.py`（CoolProp Span-Wagner 后端）。
- **TPMS 几何**：`tpms_geometry.py`（体素化 ε、A_0、D_h）。
- **集总闭合量计算入口**：`tpms_calc.py`（`compute()` 返回 ε/A_0/D_h/Re/Nu/K_df/cF_df/dP_per_L/H_sf/K_ff/K_ss/ρ/μ/k_f）。
- **设计场 → SIMPLE 1D/2D K/cF 数组投影**：`df_projection.py`。

任务重点之一 **cf-aniso 斜流方向因子**的实装不在上列文件内，而在 `sjtu_tpmshx/solvers/simple_solver.py:432-440`（属性定义，默认 0.0）与 `sjtu_tpmshx/solvers/_kernels_simple_2d.py:287-293` 等四处动量核分支，详见「可扩展接口」节。

## 文件一览

| 文件 | 一行职责 |
|---|---|
| `sjtu_tpmshx/solvers/nu_correlations.py` | Nu 关联式唯一权威：`NU_COEFFS`（air 3p 幂律 ×1.28 粗糙度）、`WATER_NU_COEFFS`（water 直接 CFD 拟合）、`SCO2_NU_COEFFS`（D-7-6 实验，仅 Diamond），含各自 Re 拟合窗与 one-shot 外推警告 |
| `sjtu_tpmshx/solvers/envelope.py` | 可压缩包络守卫：`ChokedFlowError`、预解 1D choke 检查、后解 正压/Mach 有效性门，三档模式 |
| `sjtu_tpmshx/solvers/asym_split.py` | δ 偏移等值面 per-side ε 分配比（2D/3D 共用）：`_asym_split_A` / `_per_side_eps_override` / `_eps_sides_for_run` |
| `sjtu_tpmshx/solvers/asym_geometry.py` | 非对称几何原语：`eps_sides`、voxel/marching-cubes 单侧比表面积 `a0_sides{,_mc,_richardson}`、`dh_sides`、贯通性 `percolates_z`、`find_delta_max` |
| `sjtu_tpmshx/solvers/roughness.py` | 粗糙度模式（baseline / norris_1a / bhatti_shah_1b）：f 侧与 Nu 侧增强因子 + env 解析；前两档均为 1.0 |
| `sjtu_tpmshx/solvers/fluid_props.py` | `FluidModel` 注册表（air/water/sco2）：ρ/cp/μ/k/Nu/enthalpy 原语分派 + `flow_model()` |
| `sjtu_tpmshx/solvers/sco2_props.py` | sCO2 物性 CoolProp 后端：标量 lru_cache + 向量化场查询 + 内容键场缓存 + T(h,P) 反演 |
| `sjtu_tpmshx/solvers/tpms_calc.py` | 集总闭合量编排器 `compute()`（lru_cache + DF-backend env 键）；Yan[6] water-Gyroid Nu；`C_DISP`；fluid 校验 |
| `sjtu_tpmshx/solvers/tpms_geometry.py` | TPMS 体素几何：φ 隐函数（Diamond/Gyroid）、C(t/L) 标定、ε/A_0/D_h 计算与退化守卫 |
| `sjtu_tpmshx/solvers/tpms_props.py` | 叶子模块（仅依赖 stdlib/numpy/tpms_geometry）：air/water 物性关联式、χ_s 均质化拟合、`geometry()` |
| `sjtu_tpmshx/solvers/df_projection.py` | 2D/3D 设计几何（grid_cells / sigmoid 场）→ SIMPLE 流向 K/cF 数组投影；加密网格构造；dP 提取 |

## 公开接口

### nu_correlations.py

- `nu_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm, *, Pr=Pr_AIR)`（`sjtu_tpmshx/solvers/nu_correlations.py:100`）— air 生产路径，返回 `NU_ROUGHNESS_FACTOR × Nu_smooth`；接受标量或 ndarray Re；**无 Re floor**（与 `nu_vec` 不同，:109-110 明示由调用方自行加 floor）；`eps_f` 形参保留但未使用（:111 `del eps_f`）。调用方：`fluid_props._nu_air`（`sjtu_tpmshx/solvers/fluid_props.py:28`，经 `tpms_calc` 再导出）。
- `nu_vec(tpms_type, Re, L_mm, D_h_mm, *, Re_floor=10.0, Pr=Pr_AIR)`（:123）— 向量路径，Re 下限 10。调用方：`sigmoid_field._nu_vec` 薄封装（`sjtu_tpmshx/solvers/sigmoid_field.py:224-235`）。
- `nu_water_topo(tpms_type, Re, Pr_water)`（:177）— **water 生产路径**，`Nu = c·Re^a·Pr^(1/3)`，`np.maximum(Re, 1.0)` floor（:182）。调用方：`fluid_props._nu_water`（`sjtu_tpmshx/solvers/fluid_props.py:36`）。
- `nu_water_from_Re(...)`（:134）— 遗留 Pr-substitution 路径，**仅供交叉核对/测试**，非生产（:139-141 docstring；生产分派确在 `fluid_props.py:36` 走 `nu_water_topo`，已核实）。
- `nu_sco2_topo(tpms_type, Re, Pr_sco2)`（:227）— sCO2 直接拟合，仅 Diamond；非 Diamond 抛 `NotImplementedError`（:234-237）。调用方：`fluid_props._nu_sco2`（`sjtu_tpmshx/solvers/fluid_props.py:44`）。
- `reset_extrap_warn_registry()`（:68）— 重置 one-shot 外推警告注册表。调用方：`sjtu_tpmshx/controllers/compute_pipeline.py:113-115`（每次管线运行开始时）。

### envelope.py

- `ChokedFlowError(RuntimeError)`（`sjtu_tpmshx/solvers/envelope.py:43`）。
- `predict_outlet_p_sq(P_in, T_in, C_est, L, *, R=287.05)`（:52）— 1D 可压缩 Forchheimer 出口压力平方：`P_out² = P_in² − 2·R·T·C_est·L`，`C_est = μG/K + cF·G²`（docstring :56-57）。
- `check_compressible_envelope(P_out_sq, P_in, *, mode='raise', context='')`（:63）— 预解 choke 门：`P_out_sq > 0` 返回 None；否则 `raise`→抛 `ChokedFlowError`（:86），`warn`→返回消息字符串（:88），`off`→返回 None（:89）；非法 mode 抛 ValueError（:71-73）。调用方：`sjtu_tpmshx/pipelines/run_stack_3d.py:28`（导入）。
- `mach_field_max(vmag, T_field, ...)`（:98）— 逐单元局部声速的保守峰值 Mach（局部低温单元声速更低 → Mach 更高，:102-106）。
- `assess_solution_validity(P_abs_min, vmax, T_ref, *, mach_limit=1.0, ..., ma_max=None)`（:115）— 后解有效性：非有限 P/Mach 显式判失效（NaN 守卫，:132-135、:143-146）；`P_abs_min ≤ PRESSURE_FLOOR_PA·(1+1e-6)` 判出包络（:136-140）；`Ma ≥ mach_limit` 判超声速（:147-149）。
- `gate_solution(P_abs_min, vmax, T_ref, *, mode='raise', dims='3D', ...)`（:153）— 2D/3D 共用后解门；mode 先校验再分派（:167-169），`raise` 且非法场时抛 `ChokedFlowError`（:173-178）。实际调用点：`sjtu_tpmshx/pipelines/solve_2d.py:1233,1242`（A/B 两侧）、`sjtu_tpmshx/pipelines/run_stack_3d.py:1976,1984`（A/B 两侧）；`solve_2d.py:8`/`run_stack_3d.py:28` 仅为 import 行，非调用点。

### asym_split.py

- `_asym_split_A(cfg, tpms_type, Lcell, t_wall)`（`sjtu_tpmshx/solvers/asym_split.py:21`）— side A 占总 ε 的比例；δ=0 直接返回 0.5（:30-32）；δ≠0 时在 `_phi_grid(tpms_type, 128)` 上用 `_C_from_tL` 与 `asym_geometry.eps_sides` 计算 `eA/(eA+eB)`（:33-38）。δ 取 `cfg['delta_levelset']`（φ 单位）。
- `_per_side_eps_override(cfg, tpms_type, Lcell, t_wall, eps)`（:41）— δ=0 返回 `(None, None)`（:51-52，对称路径位同一致）；δ≠0 返回 `(ε·s, ε·(1−s))`，供 ṁ/Q 加权。
- `_eps_sides_for_run(cfg, tpms_type, Lcell, t_wall, eps_arr, eps_f_arr)`（:57）— δ=0 返回**同一个** `eps_f_arr` 对象给两侧（:66-67，位同一致）；δ≠0 按几何比例切分 `eps_arr` 且**保持总量**（:68-69）。
- 调用方：`sjtu_tpmshx/pipelines/stages_3d.py:39`（re-export）、`sjtu_tpmshx/pipelines/run_stack_3d.py:24,497,709,1318,1646`、`sjtu_tpmshx/pipelines/solve_2d.py:800-803`（2D 也用，印证 2D 非对称已实装）。

### asym_geometry.py

- `eps_sides(phi, C, delta=0.0)`（`sjtu_tpmshx/solvers/asym_geometry.py:18`）— `eps_A = mean(φ < δ−C)`（得益/气侧），`eps_B = mean(φ > δ+C)`（挤压/液侧）；返回 `(eps_A, eps_B, eps_A+eps_B)`。
- `a0_sides(phi, C, delta, L_m, N)`（:43）— voxel 面数法单侧比表面积，含 `_AREA_CORRECTION = 1.553`（:15，与 `tpms_geometry._A0_from_C` 内常量一致，:84 已核实同值）。
- `a0_sides_mc(...)`（:60）— marching-cubes 精确版（`skimage.measure` 函数内延迟导入 :69）；`a0_sides_richardson(...)`（:85）— 三网格 Richardson 外推，默认 `Ns=(96,144,216)`。
- `dh_sides(...)`（:118）— `D_h = 4·ε_side / A0_side`；`percolates_z(mask)`（:133）— 沿 z 贯通性（`scipy.ndimage.label`）；`wall_thickness(...)`（:143）；`find_delta_max(phi, C, dstep=None)`（:154）— 两侧均贯通的最大 |δ|。
- 调用方：`asym_split.py:34-37`、`sjtu_tpmshx/pipelines/run_stack_3d.py:873`、`sjtu_tpmshx/pipelines/solve_2d.py:821`、`runs/diagnostics/asym_*.py`、`runs/tools/asym_build_cfd_*.py`。

### roughness.py

- `f_enhancement(Re, mode='baseline', eps_um=None, D_h_mm=None)`（`sjtu_tpmshx/solvers/roughness.py:101`）— `baseline` 与 `norris_1a` 均返回 1.0（:107-121；norris_1a 2026-05-14 起退化为别名，防双重计数）；`bhatti_shah_1b` 返回 `f_haaland/f_petukhov`（:122-126），缺 `eps_um`/`D_h_mm` 抛 ValueError（:123-124）。
- `nu_extra_factor(...)`（:130）— 在既有 ×1.28 之上的额外 Nu 乘子；`bhatti_shah_1b` 返回 `f_gain^0.68 / 1.28`（:140-143）。
- `apply_to_K_cF(K, cF, f_gain)`（:147）— `K/f_gain, cF×f_gain`。
- `resolve_mode_from_env(default='baseline')`（:156）— 读 `TPMSHX_ROUGH_MODE` / `TPMSHX_ROUGH_EPS_UM`（默认 '100' μm，:164-165）。
- 调用方：`sjtu_tpmshx/pipelines/flux_3d.py:19-20`、`sjtu_tpmshx/core/evaluators.py:166-189`、`sjtu_tpmshx/validation/cases/validate_shanghai_3d_real.py:47-48`、`validate_shanghai_aligned.py:37-38`。

### fluid_props.py

- `FluidModel` frozen dataclass（`sjtu_tpmshx/solvers/fluid_props.py:63-85`）：`rho/cp/mu/k` 签名统一为 `(T[, P])`；`nu` 签名 `(tpms, Re, eps_f, L_mm, D_h_mm, Pr)`；`embeds_roughness` 标志（:80，water/sco2 为 True → 禁止叠加 air 粗糙度模式）；`enthalpy`（:85，仅 sCO2 非 None）。
- `FLUIDS` 注册表（:88-119）：`air` compressible=True（ideal-gas）；`water` compressible=False；`sco2` compressible=False（Phase A，:108-110 注释：ΔP/P<2%，可压缩为 Phase B）。
- `get(fluid)`（:122）— 大小写不敏感查表，未知流体抛 ValueError；`flow_model(fluid)`（:130）— 返回 `'ideal_gas'`（compressible）或 `'incompressible'`。
- `_sco2_prop(key)`（:47）— P=None 时抛 ValueError（:55-58，防 CoolProp 隐晦报错）。
- 调用方：`sjtu_tpmshx/solvers/tpms_calc.py:275-276`（函数级导入，因 fluid_props 模块级 import tpms_calc，存在单向延迟以避免环）。

### sco2_props.py

- `sco2_prop(key, T_K, P_Pa)`（`sjtu_tpmshx/solvers/sco2_props.py:41`）— 标量→`_prop` lru_cache(4096)（:34-38）；数组→单次向量化 PropsSI，T/P broadcast（:62-66）。
- `sco2_temperature(h, P)`（:95）/ `sco2_temperature_field(h, P)`（:175）— T(h,P) 反演（Span-Wagner 固定 P 下 h 单调，enthalpy-form 3D LTNE 核用）。
- `sco2_field(key, T_K, P_Pa)`（:131）— 内容键（`T.tobytes()`）场缓存，容量 16（:122-123），返回只读数组（:145 `writeable=False`，意外原地改写会 fail-loud）；`clear_field_cache()`（:126）。
- 派生场函数 `sco2_density_field/sco2_cp_field/sco2_rho_cp_field/sco2_enthalpy_field/sco2_viscosity_field/sco2_conductivity_field`（:152-195）。
- CoolProp 缺失时导入不报错，首次调用抛 ImportError（:19-28 import guard）。

### tpms_calc.py

- `compute(tpms_type, L_cell_mm, t_mm, u, T_in_K, P_in_Pa, k_s, fluid_type='air') -> dict`（`sjtu_tpmshx/solvers/tpms_calc.py:376`）— 公开入口，包装 `_compute_cached`（lru_cache 4096，:220）。W7 修复（:384-399）：缓存键并入 `TPMSHX_DF_METHOD`/`TPMSHX_DF_OVERRIDES` env 状态（:396-397），且返回浅拷贝防缓存污染（:398-399）。`compute.cache_clear`/`cache_info` 转接（:404-405）。
- `_compute_cached` 内部要点：`eps_A = 0.5·eps`（:311，Nu 走单流 ε_A）；`Re = ρ·u·D_h/μ`（:294，D_h 基、interstitial u、真实入口密度）；`K_df, cF_df = predict_K_cF(tpms, L, t, eps/2)`（:334-335，D-F 闭合喂 ε/2）；sCO2 时 `cF_df ×= SCO2_CF_SCALE`（:341-342；`SCO2_CF_SCALE = 3.39` 定义于 `sjtu_tpmshx/df_surrogate/predict.py:140`）；`dP_per_L = μu/K + ρ·cF·u²`（:343，interstitial 形式）；**`K_ff = eps · k_f`（:350，用 FULL ε）**；`K_ss = chi_s_eff·(1−eps)·k_s`（:353）。
  - ⚠ 顶层 `CLAUDE.md` 所引「`tpms_calc:506`」为拆分（arch-b-c-e batch B，:45-49 注释）前的旧行号；本文件现仅 419 行，FULL-ε K_ff 实际在 `sjtu_tpmshx/solvers/tpms_calc.py:350`。「2D K_ff 用 FULL ε、3D 用 ε/2·k」的对比后半句涉及 3D 管线，不在本模块内，本文档未核实。
- `nu_water_gyroid_yan6(Re, Pr)`（:68）— `0.471·Re^0.627·Pr^(1/3)`，Yan 2024 [6]，验证范围 150<Re<3000，AM 粗糙度已内嵌（:88-90）；现仅交叉核对用（:134-135）。
- `parse_fluid_type(combo)`（:109）— **接受 Qt QComboBox**（GUI 耦合，服务器端勿用）；`validate_fluid_type(fluid_type, side)`（:122）— 不在 `_SUPPORTED_FLUIDS = {'air','water','sco2'}`（:106）内抛 `NotImplementedError`（:141-147）。
- `adaptive_grid(L_domain, H_domain, D_h, alpha=0.4)`（:199）— 目标 dx/D_h 网格尺寸。
- `_RE_FIT_RANGE_BY_FLUID`（:173-177）— per-fluid Re 警告窗（air/water/sco2 各自窗口，:300-306 使用）。

### tpms_geometry.py

- `compute_geometry(tpms_type, L_mm, t_mm, N=128)`（`sjtu_tpmshx/solvers/tpms_geometry.py:190`，lru_cache 4096）— 返回 `{epsilon, epsilon_A, epsilon_B, A_0, D_h}`；`epsilon_A = epsilon_B = 0.5·ε`（:221-222）；`D_h = 4·ε_A/A_0`（:229，等价旧式 2ε/A_0）；校验 `2t ≥ L` 抛 ValueError（:211-212）；近退化几何（ε≤1e-9 / A_0≤0 / D_h≤0）fail-loud（:236-240）。
- `_phi_grid(tpms_type, N)`（:59，lru_cache 4）— [0,2π]³ φ 网格，与 L 无关；Diamond/Gyroid 隐函数 :38-48。
- `_C_from_tL(tpms_type, t_over_L)`（:142）— `C = a·(t/L) + b·(t/L)²`，系数 `_C_COEFFS`（:136-139，12 点 CAD 标定，标定误差 <0.5%）。
- `_A0_from_C`（:74）— voxel 面数法，含面积校正常量 1.553（:84-85）。
- 调用方：`tpms_calc._compute_cached`（:265 经 `_tpms_geom` 别名）、`tpms_props.geometry`（`sjtu_tpmshx/solvers/tpms_props.py:239`）、`asym_split`（`_phi_grid`/`_C_from_tL`，`sjtu_tpmshx/solvers/asym_split.py:33`）。

### tpms_props.py（叶子模块：仅 stdlib/numpy/tpms_geometry，`sjtu_tpmshx/solvers/tpms_props.py:13-14`）

- air：`air_viscosity`（Sutherland，:89）、`air_conductivity`（:96）、`air_density`（理想气体 `P·M/(R·T)`，:102，P 默认 101325）、`air_cp`（多项式，:108）。
- water：`water_density`（:118）、`water_viscosity`（Vogel/Andrade `2.414e-5·10^(247.8/(T−140))`，分母下限 10 K 防溢出，:126-145）、`water_conductivity`（:148）、`water_cp` 常数 4182（:155-158）。
- `chi_s_eff(tpms_type, eps)`（:192）— 固相导热迂曲度 `χ_s = c0 + c1·(1−ε)`，拟合系数 `_CHI_S_FIT = {'Diamond': (0.5446, 0.3765), 'Gyroid': (0.5630, 0.3292)}`（:182-185）；env `TPMSHX_CHI_S` 常数覆盖一切（:186、:198-201）。遗留常量 `CHI_S`：env 设定值，否则 1.0（:189，仅 import 向后兼容；生产 K_ss 走 `chi_s_eff`）。
- `geometry(tpms_type, L_cell_mm, t_mm, k_s, chi_s=None, N=128)`（:207）— 几何 + `K_ss = χ·(1−ε)·k_s`（:248）。
- `tpms_calc` 将本模块全部符号 verbatim 再导出（`sjtu_tpmshx/solvers/tpms_calc.py:50-56`），旧 import 路径 `from solvers.tpms_calc import ...` 不受影响。

### df_projection.py

- `project_cells_to_streamwise_K_cF(grid_cells, tpms_type, k_s, Ny_sim, fluid, streamwise_dx=None)`（`sjtu_tpmshx/solvers/df_projection.py:46`）— 2D grid_cells → SIMPLE 1D `(Ny_sim,)` K/cF；fluid A 为 +x 流向、fluid B 为 −y 流向（SIMPLE y 轴翻转，:87）；喂给 surrogate 的是 `epsilon/2`（:105）。
- `project_fields_to_streamwise_K_cF(...)`（:143）— sigmoid 场版本，同样 `epsilon/2`（:177）；逐单元循环保持浮点求值顺序（gate-pinned，:169-170 注释）。
- `override_simple_K_cF(sim, ...)`（:183）— 投影后原地覆写 `sim._K_arr[:]`/`sim._cF_arr[:]`（:209-210）；grid_cells 与 L_field 均为 None 时 no-op（:196-197）。
- `build_master_refined_grid(...)`（:21）/ `build_master_refined_grid_3d(...)`（:213）— 壁面加密张量网格（基于 `simple_solver.build_wall_refined_1d`）。
- `project_fields_to_streamwise_K_cF_3d(...)`（:234）— 3D 场 → `(Ny_sim, Nz_sim)` K/cF，最近邻重采样。
- `extract_dP_from_simple(s)`（:277，几何开口面积加权）/ `extract_dP_mass_flux_from_simple(s)`（:293，ρ|v| 加权，零质量流退回前者 :312-313）。
- 生产原则（:8-9 模块 docstring）：生产 dP 严格走 SIMPLE，不允许解析公式绕过。

## 关键配置项与开关

| 配置/常量 | 默认值 | 定义处 | 说明 |
|---|---|---|---|
| `NU_COEFFS` | Diamond `{c:0.0944, a:0.8273, d:0.226}`；Gyroid `{c:0.126, a:0.7898, d:0.2409}` | `sjtu_tpmshx/solvers/nu_correlations.py:57-60` | air 3p 幂律；改 Nu 只改此 dict |
| `NU_ROUGHNESS_FACTOR` | 1.28 | `nu_correlations.py:48` | SLM Sa≈31 μm Nu 增强，仅 air |
| `Pr_AIR` / `NU_RE_FIT_RANGE` / `NU_LAM_FLOOR` | 0.72 / (400, 16000) / 4.36 | `nu_correlations.py:47,49,50` | 4.36 为局部-Re h_v 路径 Nu 下限（2D/3D 共用，消费点 `pipelines/solve_2d.py:706`、`pipelines/run_stack_3d.py:739`） |
| `WATER_NU_COEFFS` / `WATER_NU_RE_RANGE` | Diamond `{c:0.3427, a:0.6626}`；Gyroid `{c:0.4445, a:0.6361}` / (100, 50000) | `nu_correlations.py:155-159` | water 直接 CFD 拟合（生产） |
| `SCO2_NU_COEFFS` / `SCO2_NU_RE_RANGE` | Diamond `{c:0.28, a:0.75}` / (9000, 41000) | `nu_correlations.py:209-212` | 仅 Diamond，far-from-critical |
| `ENVELOPE_MODES` | `('raise','warn','off')` | `sjtu_tpmshx/solvers/envelope.py:34` | 由 `cfg['envelope_mode']` 驱动；ComputeConfig 默认 `'raise'`（`sjtu_tpmshx/domain/compute_config.py:370`），2D/3D 管线消费点 `pipelines/solve_2d.py:1226`、`pipelines/run_stack_3d.py:389` |
| `PRESSURE_FLOOR_PA` | 1.0e3 | `envelope.py:40` | 后解门的正压下限（镜像 `_update_density` 压力 clip 下界，:36-39 注释；镜像关系未在 simple_solver 内逐行核实） |
| `R_AIR_DEFAULT` / `GAMMA_AIR` | 287.05 / 1.4 | `envelope.py:31-32` | 干空气 |
| `cfg['delta_levelset']` | 0.0（`cfg.get(..., 0.0)`） | `sjtu_tpmshx/solvers/asym_split.py:30,51,66` | δ 偏移（φ 单位）；0 = 对称路径位同一致 |
| 粗糙度模式 env | `TPMSHX_ROUGH_MODE='baseline'`、`TPMSHX_ROUGH_EPS_UM='100'` | `sjtu_tpmshx/solvers/roughness.py:164-165` | 仅 air；`bhatti_shah_1b` 才用 eps_um |
| `TPMSHX_CHI_S` | 未设（走 per-type 拟合） | `sjtu_tpmshx/solvers/tpms_props.py:186` | 常数覆盖 χ_s 拟合（模块导入时读取一次，进程内改 env 不生效） |
| `C_DISP` | 0.0 | `sjtu_tpmshx/solvers/tpms_calc.py:196` | 流体相热弥散系数；B4 证据判定保持 0（>0 与拟合 Nu 双重计数，:186-195 注释） |
| `SCO2_CF_SCALE` | 3.39 | `sjtu_tpmshx/df_surrogate/predict.py:140` | sCO2 有效 cF 乘子；`tpms_calc.py:341-342` 集总路径应用 |
| `cf_aniso` | 0.0 | `sjtu_tpmshx/solvers/simple_solver.py:440`；cfg 默认 `sjtu_tpmshx/optimization/evaluator.py:139` | 斜流 Forchheimer 方向因子，见下节 |
| `compute()` 缓存 env 键 | `TPMSHX_DF_METHOD` / `TPMSHX_DF_OVERRIDES` | `sjtu_tpmshx/solvers/tpms_calc.py:396-397` | DF backend 切换进 lru 键，防 A/B 比较串缓存 |
| 体素分辨率 N | 128 | `tpms_geometry.py:155,191`；`tpms_props.py:208` | N=256→128（内存 ×1/8；ε 漂移 <0.3%、A_0 <1%，:222-227 注释） |
| 物性温度警告窗 | air (200,1100)K、air-cp (250,1000)K、water (273.15,363.15)K | `sjtu_tpmshx/solvers/tpms_props.py:37-39` | 出窗 one-shot UserWarning；water >373.15 K 另发两相警告（:47,:51-65） |

## 边界·假设·适用范围

- **单位**：K / Pa / m 全局，但 TPMS 胞元 `L_cell_mm` 与壁厚 `t_mm` 为 **mm**（`sjtu_tpmshx/solvers/tpms_calc.py:236-237`）；Nu 关联式内 `D_h_mm/L_mm` 也是 mm 比值（`nu_correlations.py:82`）。速度为 **interstitial（孔内）**（`tpms_calc.py:22,291-293`）。
- **Re/Nu 约定**：`Re = ρ·u·D_h/μ`（D_h 基、单通道 interstitial u）、`Nu = h·D_h/k_f`（`tpms_calc.py:18-36` 模块 docstring；实装 :294、:328）。训练 Excel 的 ×2 只用于单通道→总质量流换算，不进 Re 定义（:25-29）。
- **ε 拆分约定**：双连通 sheet HX 两股流均分 void，`ε_A = ε_B = ε/2`（`tpms_geometry.py:217-222`）；`D_h = 4·ε_A/A_0`（:224-229）。`A_0` 为**单侧**比表面积（`tpms_calc.py:247-250` 返回值注释），h_v = A_0×H_sf 不双计。
- **K_ff（2D 集总路径）用 FULL ε**：`K_ff = eps·k_f`（`tpms_calc.py:350`），而 D-F 闭合 `predict_K_cF` 喂 ε/2（:334-335）——两者刻意不同，移植时不得"统一"。
- **可压缩包络**：稳态低 Mach 求解器仅在 Forchheimer ΔP < 入口绝对压力时有效；出包络时不存在稳态解，必须改工况而非放宽守卫（`envelope.py:1-24` 模块 docstring + 顶层 CLAUDE.md 硬不变量）。【2026-07-13 更新】「2D inlet-anchored / 3D outlet-anchored」的旧说法已被证明是 **2D 生产 bug 的症状描述**（台账 C8，2026-07-12 修复）：两维的契约相同——`P_ref_abs` = 出口绝对压，一维可压缩闭式播种；该"差异"不存在。
- **粗糙度不双计**：DF 闭合的 cF 训练自真实 SLM 实验 ΔP，已隐含 Sa 摩擦贡献；f 侧任何额外乘子都是双重计数（`roughness.py:9-37` 推导链）。×1.28 仅在 air Nu 侧；water（`nu_water_topo` smooth-CFD 拟合 + Yan[6] 内嵌粗糙度）与 sCO2（D-7-6 实验内嵌）都不得再乘（`fluid_props.py:80,:96,:106,:116` `embeds_roughness` 标志；`roughness.py:69-70`）。
- **sCO2 适用范围**：Phase A = far-from-critical（Pr≈0.8）、incompressible ρ(T,P_in)（`fluid_props.py:108-110`）；Nu 仅 Diamond、Re∈[9e3, 4.1e4]（`nu_correlations.py:204-212`）；近伪临界线（cp 尖峰）明确不适用（:207-208）。
- **water dP 为工程占位**：D-F surrogate 仅用 air 数据训练，water 侧 K/cF 无物理标定；water 的 Q 严谨（`nu_water_topo`）、dP 仅工程估计（`tpms_calc.py:99-105,:135-139` 注释；代码层面 `predict_K_cF` 调用确实不区分 water，:334-335）。
- **几何有效域**：`compute_geometry` 强制 `2t < L`（`tpms_geometry.py:211`），近退化（t→L/2）fail-loud（:236-240）；C(t/L) 标定表覆盖 L∈{4,5,6,8} mm、t∈{0.3,0.4,0.5} mm（:108-131），域外为外推（未验证精度）。
- **asym voxel A0 精度**：`a0_sides` 的 1.553 校正常数仅在 δ=0 附近标定，极端 δ 应改用 `a0_sides_mc` / `a0_sides_richardson`（`asym_geometry.py:65-68,:88-92` docstring；单网格 N=128 挤压侧可低约 3%，据 :90-91 注释，未独立复核）。
- **警告为 one-shot 且模块级可变状态**：`_EXTRAP_WARNED`/`_WATER_NU_WARNED`/`_SCO2_NU_WARNED`（`nu_correlations.py:65,164,214`）与 `_range_warnings_emitted`（`tpms_props.py:41`）跨调用持久；长会话第二次运行需 `reset_extrap_warn_registry()`（仅覆盖 air 外推注册表）。

## 可扩展接口

- **cf-aniso 斜流方向因子**（2026-07-10，2D）：`cF_eff = cF·(1 + a·ξ4)`，`ξ4 = 4·u_x²·u_y²/|u|⁴`（最低阶立方对称不变量；轴向流 ξ4=0，45° 最大）。属性 `SIMPLESolver.cf_aniso` 默认 0.0（`sjtu_tpmshx/solvers/simple_solver.py:432-440`），传入四个 numba 核：`_sweep_u_jit_df`（`sjtu_tpmshx/solvers/_kernels_simple_2d.py:287-293`）、`_sweep_v_jit_df`（:411-417）、`_pseudo_u_jit_df`（:541-547）、`_pseudo_v_jit_df`（:639-645）；`a=0` 时分支跳过、位同一致（:287 `if cf_aniso != 0.0`）。配置入口：`cfg['cf_aniso']`（`sjtu_tpmshx/optimization/evaluator.py:139,281,332`）与 CLI `run_port_dim_retest.py:169-170`。轴向流对任何 a 值不变（on-axis cF 即标定锚点，不与 γ 粗糙度锚双计，`simple_solver.py:435-437` 注释）。标定流程：`sjtu_tpmshx/validation/cf_aniso/fit_cf_aniso.py`（`cF(θ)/cF(0)−1 = a·ξ4(θ)` 最小二乘）；**当前默认 0.0 = 未标定**，量产引用非零值前须先跑方向分辨单胞 CFD。Darcy K 保持各向同性（立方对称 ⇒ K∝I，`_kernels_simple_2d.py:284-285` 注释）。
- **asym per-side ε 私有 hooks**：`ltne_energy` 的 `eps_A`/`eps_B` kwargs（本模块外）由 `_eps_sides_for_run` 在**上游**切分后喂入，切分定义单一来源即 `asym_split.py`；对称路径调用方必须传 FULL ε（顶层 CLAUDE.md 硬不变量；本模块内可核实的部分：δ=0 时 `_eps_sides_for_run` 原样返回 `eps_f_arr`，`asym_split.py:66-67`）。
- **粗糙度 backend 分支**：`bhatti_shah_1b` 为预留的 Re 依赖模式（Haaland/Norris），经 env `TPMSHX_ROUGH_MODE` 激活，无需改代码（`roughness.py:122-126,156-166`）。
- **流体注册点**：新增流体 = 在 `FLUIDS` 加一个 `FluidModel` 条目（`fluid_props.py:1-4` 模块 docstring 及 :88-119）；`flow_model()` 自动给出 SIMPLE 的 `fluid_type` 字符串。
- **χ_s 覆盖**：env `TPMSHX_CHI_S`（常数）> per-type 拟合（`tpms_props.py:186-204`）；`geometry(chi_s=...)` 显式实参优先级最高（:240-241）。
- **DF backend env**：`TPMSHX_DF_METHOD` / `TPMSHX_DF_OVERRIDES` 被 `predict_K_cF` 每次调用读取（据 `tpms_calc.py:388-392` 注释；predict.py 内部实现未在本文档逐行核实），并已纳入 `compute()` 缓存键（:396-397）。
- **K/cF 场覆写**：`SIMPLESolver.set_K_cF_field()` / `_K_field2d` per-cell 覆写（`simple_solver.py:424-431`，lateral-K）；1D 层面则用 `df_projection.override_simple_K_cF`（`df_projection.py:183`）。
- **C_DISP**：预留的热弥散项 `K_ff += C_DISP·ρcp·|u|·D_h`（`tpms_calc.py:351-352`），当前恒为 0；重启条件见 :186-195 注释（须与 Nu 同步重拟合）。

## 已知不足与 TODO

- 范围内 11 个文件 grep `TODO|FIXME|XXX|HACK` **无命中**（2026-07-10 核实）；不足以注释与 `NotImplementedError` 形式存在：
- `nu_sco2_topo` 非 Diamond 抛 `NotImplementedError`（`nu_correlations.py:234-237`）——sCO2 只有 D-7-6 单几何数据，禁止借用其他拓扑系数。
- `validate_fluid_type` 对 `_SUPPORTED_FLUIDS` 之外流体抛 `NotImplementedError`（`tpms_calc.py:141-147`）。
- `roughness.py` 整体标注 PROVISIONAL / EXPECTED-TO-CHANGE（:4）；3D Shanghai dP 残差归因于 (a) t=0.6mm 超出 ConstDF-v1 训练域 t∈{0.3,0.4,0.5}、(b) Shanghai Sa 未独立测量（:28-36 注释，属分析性论断，未验证）。
- `SCO2_CF_SCALE=3.39` 为单几何（Diamond 7/0.6）标定，向其他 (L,t) 的迁移**未验证**（`df_surrogate/predict.py:137-139` 注释明示）。
- `cf_aniso` 默认 0.0 = 未标定；`validation/cf_aniso/` 为标定 worklist，尚无生产系数。
- water dP 闭合为 air-fit 占位（`tpms_calc.py:99-105`），无 water 标定 K/cF。
- `nu_from_Re` 的 `eps_f` 形参为死参（:111 `del eps_f`，仅签名兼容）。
- 遗留三谱系 water Nu 并存（`nu_water_topo` 生产、`nu_water_from_Re` 与 `nu_water_gyroid_yan6` 仅交叉核对，`nu_correlations.py:147-154`）——移植时勿误选遗留路径。
- `CHI_S` 遗留常量（1.0）仍可被 import（`tpms_props.py:189`），与生产 `chi_s_eff` 拟合值不一致，仅为兼容保留。
- χ_s 拟合薄壁偏差：t/L≲0.05 时壁仅 ~4 voxel，拟合值比连续极限低 ~2%（`tpms_props.py:174-180` 注释，未独立复核）。
- `asym_geometry.py` 自述为 PoC（Phase 0）（:2-9 docstring），但 `_asym_split_A` 已将其 `eps_sides` 接入生产管线（`asym_split.py:33-38`）——docstring「不修改任何生产路径」已过时。
- `find_delta_max` 不约束物理最小壁厚（~0.3 mm 可制造性延后至 STL 阶段，`asym_geometry.py:157-159`）。

## 服务器移植注意（Windows Server 2022）

- **GUI 耦合点**：`tpms_calc.parse_fluid_type` 直接接收 Qt `QComboBox`（`tpms_calc.py:109-119`）；headless 服务器改传内部字符串键（'air'/'water'/'sco2'），勿 import 任何 UI。本模块群其余文件无 Qt 依赖。
- **依赖**：numpy（全部）；scipy.ndimage（`asym_geometry.py:12`）；scikit-image 为**延迟导入**（仅 `a0_sides_mc` 内 :69，不装也能跑 voxel 路径）；CoolProp 为**可选**（`sco2_props.py:19-28` import guard，缺失时仅 sCO2 路径首次调用抛 ImportError）；numba（`_kernels_simple_2d.py` 的 `njit(cache=True)`，须保证 `__pycache__` 目录可写，否则每进程重编译）。
- **环境变量清单**（本模块群读取）：`TPMSHX_ROUGH_MODE`、`TPMSHX_ROUGH_EPS_UM`（`roughness.py:164-165`，每次调用读取）；`TPMSHX_CHI_S`（`tpms_props.py:186`，**模块导入时读取一次**，运行中改 env 不生效）；`TPMSHX_DF_METHOD`、`TPMSHX_DF_OVERRIDES`（`tpms_calc.py:396-397`，进缓存键）。项目 golden gate 另要求 `PYTHONHASHSEED=0`（`/check` 约定，本模块内未核实其敏感点）。
- **lru_cache 均为进程内**：`_phi_grid`（`tpms_geometry.py:59`）、`_compute_raw`（:154）、`compute_geometry`（:189）、`_compute_cached`（`tpms_calc.py:220`）、`_prop`（`sco2_props.py:34`）。multiprocessing worker 间不共享——并行 BO 每进程各存 N³ φ 网格（N=128 约 16 MiB/type，`tpms_props.py:222-227`）；per-process sweep 改物性需在**每个 worker 内** `compute.cache_clear()`（`tpms_calc.py:402-404`，B4 props-cache 教训）。
- **模块级可变状态**：各警告注册表（`nu_correlations.py:65,164,214`；`tpms_props.py:41,48`）与 `_FIELD_CACHE`（`sco2_props.py:122`）非线程安全（无锁）；多线程求解器（`solvers/threads.py` 存在，未核实其与这些注册表的交互）下警告可能重复或丢失，但不影响数值。
- **路径/编码**：本模块群无硬编码绝对路径（复核 `[a-zA-Z]:\` 模式在 `nu_correlations.py`/`envelope.py`/`asym_split.py`/`asym_geometry.py`/`roughness.py`/`fluid_props.py`/`sco2_props.py`/`tpms_calc.py`/`tpms_geometry.py`/`tpms_props.py`/`df_projection.py` 中无命中），迁到另一台 Windows Server 主机不受影响；无文件 I/O（除 `fit_cf_aniso.py` 用 `pd.read_csv(path)` 读 CSV，属 validation 脚本——已核实 pandas 2.3.3 环境下 `read_csv` 的 `encoding` 参数默认即为 `'utf-8'`，不随系统区域设置漂移，此处无 GBK 风险）。源码含 UTF-8 中文/希腊字母 docstring（如 `asym_geometry.py`、`df_projection.py`），Python 3 源码编码默认 UTF-8（PEP 3120），与运行时 OS locale 无关，不构成解析风险——**此前「移植到 Linux 后 locale 设为 UTF-8、风险更低」的判断前提已不成立，且 GBK 编码坑本身不会因为目标是 Windows Server 而消失，需要反过来重估**：本模块群当前运行时文本已核实为纯 ASCII（`nu_correlations.py:91-95`、`tpms_calc.py:302`、`tpms_props.py:61-65,79-85` 的 `warnings.warn` 消息均无中文；`tpms_calc.py:61` 定义的 `_log = get_logger(__name__)` 在本文件内**无调用点**，不产生日志文本），故本模块群眼下不会触发该坑。但同仓库 `df_surrogate/surrogate_v3.py:151-155` 注释记录的真实先例——中文区域设置的 Windows 下控制台代码页为 GBK/cp936，subprocess 以 GBK 字节写出中文而 pytest 按 UTF-8 读捕获流，一行中文即可让此后所有测试的 teardown 抛 `UnicodeDecodeError`——本质是 Windows 控制台代码页问题（与 Linux/Windows 之分无关，纯粹是该主机区域设置），Windows Server 2022 若同为中文区域设置会原样复现，且不会随平台从「假设的 Linux」改为「实际的 Windows Server」而减轻。若日后给本模块群的 `_log`/`print` 加中文内容，应比照仓库既有模式：入口脚本启动时 `try: sys.stdout.reconfigure(encoding='utf-8')`（如 `ui/demo_vis_3d.py:30`，多处 `df_surrogate/*.py` 与 `validation/cases/*.py` 同款），或在无交互式控制台的 Windows Server 服务/计划任务里预先设置 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8` 环境变量（等价于交互式会话下的 `chcp 65001`，未验证在计划任务场景下的具体生效方式）。
- **数值位同（bit-identical）敏感点**：`df_projection.project_fields_to_streamwise_K_cF` 的逐单元循环刻意保持求值顺序（:169-170）；`_eps_sides_for_run` δ=0 返回同一对象（`asym_split.py:66-67`）；cf_aniso=0 / C_DISP=0 / cf_scale=1 分支跳过。golden gate 回归前不要"顺手向量化"这些循环。
- **不得移除/放宽的守卫**（顶层 CLAUDE.md 硬不变量，代码锚点已核实）：`ChokedFlowError` 与三档 `envelope_mode`（`envelope.py:43,:34`；默认 `'raise'`，`domain/compute_config.py:370`）；压缩性（air `compressible=True`，`fluid_props.py:90`）；粗糙度不叠加（`roughness.py` f 侧 1.0）；Nu 系数单一来源（`nu_correlations.py:57,156,210`）。
