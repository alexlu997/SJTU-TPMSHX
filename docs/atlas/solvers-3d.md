# solvers — 3D
生成日期 2026-07-10，基于 commit f33d30e 附近的 master

本文覆盖 `sjtu_tpmshx/solvers/` 下的 3D 求解器族：`simple_solver_3d.py`、`_kernels_simple_3d.py`、`_kernels_ltne_3d.py`、`ltne_energy_3d.py`、`ltne_enthalpy_3d.py`、`coarse_bootstrap_3d.py`、`coupling_skeleton.py`。所有断言均以代码为准并附 file:line；无法在代码中直接核实处标注「未验证」。

## 定位与功能

3D 求解器族实现多孔介质均匀化 TPMS 换热器的稳态低 Mach 可压缩流动 + 三温度 LTNE 传热：

- **动量/连续（SIMPLE）**：`SIMPLESolver3D`（`sjtu_tpmshx/solvers/simple_solver_3d.py:329`）在 3D staggered MAC 网格上解 Brinkman-Forchheimer 动量方程 + 压力修正方程（PPE）。生产默认为可压缩 ideal-gas ρ=ρ(P,T)（`fluid_type='ideal_gas'`，`sjtu_tpmshx/solvers/simple_solver_3d.py:475`），配 mass-flux inlet。连续方程离散为 ∇·(ε·ρ·u)=0 —— PPE 与质量残差接收 `rho_eps_field = ρ·ε`（`sjtu_tpmshx/solvers/simple_solver_3d.py:854-855, 899, 912`）；动量算子本身不带 ε 权重（模块头注释 `sjtu_tpmshx/solvers/simple_solver_3d.py:29-32`，与代码一致：动量 kernel 中 ε 仅经 μ_eff=μ/ε 与可选 use_eps 分支进入）。
- **能量（LTNE）**：`solve_full_domain_3d`（`sjtu_tpmshx/solvers/ltne_energy_3d.py:427`）解三温度 (Ta, Tb, Ts) 稳态 LTNE 方程组，7 点 Laplacian（调和平均面导热）+ 一阶迎风 + minmod SOU 延迟修正，Gauss-Seidel 逐胞耦合更新。
- **焓形式能量（sCO2）**：`ltne_enthalpy_3d.py` 为变 cp 流体（sCO2 跨拟临界线）提供以比焓 h 为主变量的保守 LTNE 内核（模块 docstring `sjtu_tpmshx/solvers/ltne_enthalpy_3d.py:1-22`）。
- **加速**：`coarse_bootstrap_3d.py` 提供半分辨率粗网格热启动（Phase C）；`coupling_skeleton.py` 提供 2D/3D 共享的外层 SIMPLE↔LTNE Picard 循环骨架与收敛判据。

3D 压力锚定方式是「outlet-anchored」：PPE 在 j=Ny-1 出口行钉死 Pp=0（`sjtu_tpmshx/solvers/simple_solver_3d.py:157-163`；kernel 侧 `cell_kind==1 → diag=1, rhs=0`，`sjtu_tpmshx/solvers/_kernels_simple_3d.py:750-752`），P 场为相对 `P_ref_abs`（出口绝对压力锚，默认大气压 `P_atm`，`sjtu_tpmshx/solvers/simple_solver_3d.py:540-543`）的 gauge 压力。这与 2D 的 inlet-anchored 相反，是 choke envelope 守卫主要作用于 3D 的原因（CLAUDE.md 硬不变量；envelope 检查本身在 `solvers/envelope.py`，由 pipeline 调用，见下）。

生产调用链：`pipelines/run_stack_3d.py` 构建两个 `SIMPLESolver3D`（流体 A `sjtu_tpmshx/pipelines/run_stack_3d.py:545`，流体 B `:633`），外层循环（`run_outer_coupling`，`sjtu_tpmshx/pipelines/run_stack_3d.py:1595`）中交替调用 `solve_full_domain_3d`（`:1258`）与 SIMPLE 重解，属性（ρ、μ）随 T 场回馈。

坐标约定：P 为 (Nx,Ny,Nz) 胞心，u/v/w 为 (Nx+1,Ny,Nz)/(Nx,Ny+1,Nz)/(Nx,Ny,Nz+1) 面量（`sjtu_tpmshx/solvers/simple_solver_3d.py:575-578`）；SIMPLE 的主流方向固定为 j 轴（inlet 在 j=0，outlet 在 j=Ny-1），流体方向到求解器轴的映射由调用方以转置完成（`sjtu_tpmshx/solvers/simple_solver_3d.py:45-51`，映射实现在 `pipelines/grid_3d.py`）。LTNE 的方向码 dir_code ∈ {0=+x, 1=−x, 2=+y, 3=−y, 4=+z, 5=−z}（`sjtu_tpmshx/solvers/_kernels_ltne_3d.py:202-208`）。

## 文件一览

| 文件 | 职责（一行） |
|---|---|
| `sjtu_tpmshx/solvers/simple_solver_3d.py` | `SIMPLESolver3D` 类 + SIMPLE 外循环：PPE 稀疏结构/PyAMG 求解、可压缩密度更新（含压力 clip）、mass-flux inlet、coarse bootstrap 接入、Anderson/低 Re 早退；kernel 从 `_kernels_simple_3d` re-export（`:110-129`） |
| `sjtu_tpmshx/solvers/_kernels_simple_3d.py` | 3D SIMPLE 全部 Numba kernel：u/v/w 动量 GS sweep（串行 + red-black 并行）、PPE 装配、压力/速度修正、质量残差；从 `simple_solver_3d.py` 原样拆出（`:1-2`） |
| `sjtu_tpmshx/solvers/ltne_energy_3d.py` | 3D 三温度 LTNE 驱动 `solve_full_domain_3d`：ε 分拆契约、Nz=1 委托 2D、Helmholtz 面通量投影、严格守恒证书、收敛判据；kernel 从 `_kernels_ltne_3d` re-export（`:311-332`） |
| `sjtu_tpmshx/solvers/_kernels_ltne_3d.py` | 3D LTNE Numba kernel：staggered 面速度保守内核（串行 `_gs_full_chunk_3d_stag` + red-black `_stag_rb`）、legacy 胞心内核 `_gs_full_chunk_3d`、SOU 限制器、inlet/outlet BC 辅助 |
| `sjtu_tpmshx/solvers/ltne_enthalpy_3d.py` | Option B 焓形式 3D LTNE（sCO2/水/空气混合流股）：njit 焓 GS 内核 + CoolProp 属性驱动层 + pipeline 适配器 |
| `sjtu_tpmshx/solvers/coarse_bootstrap_3d.py` | Phase C 粗网格热启动：半分辨率 SIMPLE 粗解 → 三线性插值 (u,v,w,P) 注入细网格初值 |
| `sjtu_tpmshx/solvers/coupling_skeleton.py` | 2D/3D 共享外层耦合循环骨架 `run_outer_coupling` + 收敛判据 `OuterConvergence` |

## 公开接口

### SIMPLESolver3D（`sjtu_tpmshx/solvers/simple_solver_3d.py:329`）

- `__init__(Lx, Ly, Lz, Nx, Ny, Nz, rho, mu, T_in, v_inlet, eps=1.0, K_arr=None, cF_arr=None, P_ref_abs=None, alpha_u=0.5, alpha_p=0.2, pyamg_rebuild_every=100, pyamg_rebuild_drift_thresh=0.05, use_coarse_bootstrap=None, fluid_type='ideal_gas', R_gas=287.05, alpha_rho=0.3, dx_arr=None, dy_arr=None, dz_arr=None)`（`sjtu_tpmshx/solvers/simple_solver_3d.py:466-478`）。`K_arr`/`cF_arr` 形状 (Ny, Nz)（`:570-572`）；`v_inlet` 标量或 (Nx, Nz) 数组（`:507-516`）；`dx_arr` 等为非均匀网格间距（E1，`:489-500`）。调用方：`pipelines/run_stack_3d.py:545,633`、`core/evaluators.py:261,275`、`validation/cases/validate_shanghai_3d_real.py:291`、`ui/demo_vis_3d.py:105`。
- `solve(max_iter=3000, tol=1e-6, n_inner=1, verbose=False, cancel_check=None) -> (converged: bool, iterations: int)`（`sjtu_tpmshx/solvers/simple_solver_3d.py:708`）。质量残差为最大单胞 |∇·(ε·ρ·u)| 除以入口质量流量（A2 归一化，`:910-921`；参考量 `_inlet_mass_flux`，`:647-658`，退化无流动情形回退 1.0 保持绝对残差）。退出原因写入 `self.exit_reason` ∈ {'tol','velocity','stall','max_iter','cancelled'}（`:834-835, 986, 996, 999-1001`）；'velocity'（场静止）按 converged=True 返回，'stall' 返回 False（`:990-997`）。**⚠️ `tol` 不是本求解器的收敛判据 —— 见「已知不足」第 10 条。真正在检测收敛的是 LowReExit 的 velocity 判据。**
- `_update_density()`（`sjtu_tpmshx/solvers/simple_solver_3d.py:603-645`）：可压缩密度更新，见「关键配置项」与「边界·假设」。
- `_apply_massflux_inlet()`（`sjtu_tpmshx/solvers/simple_solver_3d.py:660-682`）：重设 `v_inlet_field = _massflux_target / ρ_inlet`（`:681-682`），把入口从固定速度改为固定质量通量 G=ρ·v；`_massflux_target` 在 solve() 首次进入时按（给定 v × 初始 ρ）捕获一次并跨 warm restart 复用（`:731-737`）。
- `apply_outlet_taper(n_taper=8, min_frac=0.2)`（`sjtu_tpmshx/solvers/simple_solver_3d.py:364-371`）：出口面 8 胞指数 taper（生成函数 `_build_outlet_frac_taper`，`:303-326`）。pipeline 中对流体 A 施加后再与 partial 掩码相乘（`sjtu_tpmshx/pipelines/run_stack_3d.py:567-568`）。
- `outlet_frac` property/setter（`sjtu_tpmshx/solvers/simple_solver_3d.py:380-390`）：任何对 `outlet_frac` 的写入自动重建布尔掩码 `outlet_mask_ij = (outlet_frac > 0.5)`，保证 v-sweep 门控与 `_correct_jit_3d` 的 BC 重施一致（单一真源，`:373-379`）。
- ΔP 提取（三个 staticmethod）：`extract_dP_weighted`（几何开面积权重胞心差，`:392-407`）、`extract_dP_face_extrap`（1.5·P₀−0.5·P₁ 二阶外推到面，`:409-443`；生产 3D 管线用它，`sjtu_tpmshx/pipelines/run_stack_3d.py:1753,1777`）、`extract_dP_mass_flux_weighted`（ρ·|v| 质量通量权重，`:445-464`）。
- `update_T_field(T_field)`（`sjtu_tpmshx/solvers/simple_solver_3d.py:684-706`）：外层非等温耦合刷新 T 场并重算 μ(T)、μ_eff=μ/ε。

### 3D SIMPLE kernels（`sjtu_tpmshx/solvers/_kernels_simple_3d.py`）

- `_sweep_u_jit_df_3d` / `_parallel`（`:243` / `:280`）、`_sweep_v_jit_df_3d` / `_parallel`（`:480` / `:511`）、`_sweep_w_jit_df_3d` / `_parallel`（`:672` / `:703`）：动量 GS sweep；并行版为 red-black 着色 `(i+j+k)%2` + `prange`（`:275-279`）。共享胞体 `_u_cell_df_3d`（`:89`）/`_v_cell_df_3d`（`:309`）/`_w_cell_df_3d`（`:538`），`inline='always'`。多孔阻力线性化 `Sp = μ/K + ρ·c_F·|U|`（`_porous_src_df_3d`，`:50-58`）。注意 v-sweep 的参数顺序与 u/w 不同（`v_inlet_field` 插在 `d_v` 之后、`eps_field` 在 `rho_field` 之后，见 warmup 注释 `sjtu_tpmshx/solvers/simple_solver_3d.py:1041-1051`）。
- `_assemble_pp_3d`（`:731`）：7 点 PPE CSR 装配；出口钉死行 `cell_kind==1 → diag=1, rhs=0`（`:750-752`）；aP<1e-30 的退化行同样钉死（`:794-799`）。
- `_correct_jit_3d`（`:818`）：压力修正 `P += alpha_p·Pp`（跳过出口钉死胞，`:828-830`）+ 面速度修正 + BC 重施。出口 v 外推按 ε·ρ·v 守恒（均匀 ε 列保持原 ρ 比式以维持 golden 位同一，分支在 `:866-878`；`_v_bc_3d` 同逻辑 `:461-473`）。
- `_mass_res_jit_3d`（`:891`）：最大单胞散度绝对值；solve() 传入的 `rho_field` 实参是 ε·ρ（`sjtu_tpmshx/solvers/simple_solver_3d.py:910-912`）。

### PPE 求解（模块级函数）

- `_build_pp_sparsity_3d(Nx, Ny, Nz, outlet_mask_ij)`（`sjtu_tpmshx/solvers/simple_solver_3d.py:132`）：预计算 CSR indptr/indices/cell_base/cell_kind；出口钉死仅支持 j=Ny-1 行（docstring 自述 "For MVP we use j=Ny-1 only"，`:138-139`）。
- `_solve_pp_amg(...)`（`sjtu_tpmshx/solvers/simple_solver_3d.py:182`）：N>`_AMG_GATE` 且 PyAMG 可用时走 `pyamg.ruge_stuben_solver(A, max_coarse=200)` 预条件 BiCGStab（`rtol=rtol_dyn, maxiter=200`，`:259, 274`），失败回退 spsolve 且保留缓存 hierarchy（`:279-287`）；否则直接 spsolve（`:291-292`）。**求解前必须 `A.sort_indices(); A.sum_duplicates()` 规范化**（`:226-227`）——非规范 CSR 会静默构出劣质 AMG hierarchy（历史 "cold-start" 假象的真因，注释 `:218-225`）。hierarchy 重建：cadence（`pyamg_rebuild_every`）+ 对角线 L2 漂移触发（`drift_thresh`，`:241-255`）。

### solve_full_domain_3d（`sjtu_tpmshx/solvers/ltne_energy_3d.py:427-454`）

签名要点：`solve_full_domain_3d(L, H, D, Nx, Ny, Nz, T_inA, T_inB, K_ffA, K_ffB, K_ss, h_vA, h_vB, rho_cp_fA, rho_cp_fB, epsilon, ucA, vcA, wcA, ucB, vcB, wcB, dir_A, dir_B, ..., alpha_T=0.7, eps_A=None, eps_B=None, ufA=None, ..., conservative_ltne=False, q_rel_tol=None, conv_chunk=None) -> (Ta, Tb, Ts[, info])`。调用方：`pipelines/run_stack_3d.py:1258`、`core/evaluators.py:343`、`design/forward.py:130`（Nz=1 路径）、`validation/cases/validate_shanghai_3d_real.py:341`。

- **ε 分拆契约（硬不变量）**：`epsilon` 传**总孔隙率 ε_full**；`eps_A`/`eps_B` 均为 None 时内部做唯一一次减半 `eps_fA = 0.5·ε`，且 `eps_fB` 与 `eps_fA` 绑定同一数组对象（`sjtu_tpmshx/solvers/ltne_energy_3d.py:543-550`）。显式 `eps_A`/`eps_B`（asym δ 路径）为单通道值、**不再减半**直接消费，必须成对给出，并校验 `eps_A+eps_B ≤ epsilon+1e-9`（`:551-559`）。调用侧预减半会导致 ε/4 double-halving（docstring `:462-472`；回归测试 `tests/test_eps_contract_3d.py`）。
- **Nz == 1 快速路径**：squeeze z 轴委托 2D `solvers.ltne_energy.solve_full_domain`，声明位同一（`:483-495`，`_delegate_to_2d` `:339`）。
- **kernel 派发**：传入 staggered 面速度（ufA/vfA/wfA + ufB/vfB/wfB 全非 None）→ staggered 内核；否则 legacy 胞心内核（`:665-667, 723-750`）。`conservative_ltne=True` 强制要求 staggered 面速度，否则 `ValueError`（`:671-674`）。staggered 内核再按网格规模选串行/red-black：`_RB_ENERGY=True` 且 N>`_RB_ENERGY_GATE`(30000) 用 `_gs_full_chunk_3d_stag_rb`（`:423-424, 724-726`）。
- **conservative 路径预处理**：对两侧面速度做 Helmholtz/MAC 无散投影 `_project_faces_div_free`（`:715-719`；函数 `:84-202`，AMG-CG `rtol=1e-10, maxiter=500`，`:177`，失败回退 bordered 直接解 `:179-184`；已近无散场按 `_PROJ_SKIP_TOL=1e-9` 相对阈值跳过 `:152-155`）。
- **收敛判据**：按 chunk（默认 250 sweep，`:652`）迭代，AND 门 =（相对 ΔQ_B < q_tol）且（max|ΔT| < `T_abs_tol=0.01 K`）（`:657-658, 774-783`）；`q_tol = max(tol·10, 1e-4)`，可由 `q_rel_tol` 覆盖（`:657`）。
- **info 字典**（`return_info=True`）：converged/iterations/residual/delegated_to_2d（`:789-794`）；conservative 时附严格守恒证书 `eps_A_strict`/`eps_B_strict`（及 cellmax 版），由 `_conservation_residual_sum` 在收敛场上评估保守离散残差（`:795-814`；函数 `:213-301`；分母下限 `_Q_FLOOR_W=1.0`，`:210`）。
- 初值：Ta/Tb 各自钉在自己的入口温度、Ts 取中值（2026-04-24 修正，`:616-627`）；`Tb_prescribed` 冻结 B 场（`freeze_Tb`，`:629-635`）。
- 守恒探针：`energy_balance_3d`（`:851-863`）、`mass_balance_3d`（`:866-917`）。

### 3D LTNE kernels（`sjtu_tpmshx/solvers/_kernels_ltne_3d.py`）

- `_gs_full_chunk_3d_stag`（`:255`）：串行 staggered 保守内核。入口胞 Dirichlet：frac>0.99 直接钉值、0.01<frac≤0.99 按 frac 混合邻胞（`:290-298`）；conservative==1 时 aP 加符号净出流项 `net_out=(F_e−F_w)+(F_n−F_s)+(F_t−F_b)`（Patankar 保守形式，`:386-387`），SOU 用面共享通量版 `_sou_face_*_cons`（telescoping 守恒，`:383-385`；注释 `:369-382`）；否则胞局部 `_sou_corr_*_3d` 且 aP 不含 net_out（`:389-405`）。χ_B ghost-skip：`chi_B_arr[i,j,k] < chi_B_kernel_threshold` 的胞跳过 Tb 更新（H6，`:471-478`）。每 sweep 末施加出口零梯度 `_apply_outlet_3d`（`:574-576`；函数 `:1152-1177`），内层 `max_chg<1e-10` 提前跳出（`:578-579`）。
- `_gs_full_chunk_3d_stag_rb`（`:584`）：red-black `prange` 并行孪生；SOU 触及 2 胞外（同色）故从 sweep 起始快照 `Ta_snap`/`Tb_snap` 读取（`:597-614, 621-622, 702-704`）——只改迭代路径不改收敛不动点（docstring 声明，收敛值与串行一致；「verified」为注释断言，未在本次独立复核，视作未验证）。
- `_gs_full_chunk_3d`（`:931`）：legacy 胞心速度内核（`force_cc_ltne` 回退路径）；胞局部迎风 F=ε·ρcp·|u_c|·A，构造上单胞 NET_OUT=0（`:995-1016`）。
- SOU 辅助：`_va_limit`（minmod，`:13-23`）、胞局部 `_sou_corr_x/y/z_3d`（`:26-94`）、面共享 `_sou_face_x/y/z_cons`（`:111-176`）、全场 `_sou_field_cons`（守恒证书用，`:180-194`）。
- BC 辅助：`_is_inlet`/`_inlet_frac`/`_inlet_val`/`_inlet_neighbor`（`:202-237`）、`_is_bc_face_inlet`/`_is_bc_face_outlet`/`_ifrac_at_face`/`_Tin_at_face`（`:873-923`；后四者当前仅被导出，未在本模块内核中使用——re-export 清单见 `sjtu_tpmshx/solvers/ltne_energy_3d.py:311-332`）。

### 焓形式（`sjtu_tpmshx/solvers/ltne_enthalpy_3d.py`）

- `_gs_enthalpy_sweeps_3d(...)`（`:58`，njit）：h 为主变量的 GS sweep；x 向对流用每列符号质量流量 `FmA_col/FmB_col`（`:107-108`），入口 Dirichlet 半胞导热 + 去除内部面估计（N3 修正，`:115-129`），出口零梯度去掉出口面导热（`:130-138`）；h 迭代量夹在 [h_lo, h_hi] 窗内（`:153-157`）。
- `solve_ltne_enthalpy_3d(Nx, Ny, Nz, Lx, Ly, Lz, eps, k_s, m_dot_A, m_dot_B, h_vA, h_vB, T_inA, T_inB, P, P_B=None, dir_A=0, dir_B=1, fluid_A='sco2', fluid_B='sco2', eps_A_field=None, eps_B_field=None, n_outer=3000, n_sweep=3, omega=0.6, tol=2e-5) -> dict`（`:269-281`）：独立驱动器；CoolProp 的 T(h,P) 逆变换与 cp/k 场每外层迭代刷新一次，njit 内核绝不调 CoolProp（架构声明 `:11-16`）。
- `solve_ltne_enthalpy_3d_pipeline(...) -> (Ta, Tb, Ts, info)`（`:343-360`）：pipeline 适配器，返回契约匹配 `solve_full_domain_3d(return_info=True)`；调用方 `pipelines/run_stack_3d.py:1326`（门控条件 `ltne_enthalpy_mode` + sCO2 双侧 + counterflow-x，`:1245-1248`）。**适用范围限定 counterflow along x（dir 0/1）+ 均匀网格**（docstring `:358-360`；实现上非均匀间距被 `np.mean` 塌成标量，`:362`）。
- `enthalpy_metrics_3d(res, case)`（`:425`）：Q_enthalpy / Q_solid 守恒指标。

### coarse bootstrap（`sjtu_tpmshx/solvers/coarse_bootstrap_3d.py`）

- `bootstrap_simple_3d(solver_fine, max_iter_coarse=200, tol_coarse=1e-3, min_coarse_axis=4, verbose=False) -> info dict`（`:51-76`）。流程：各轴减半（任一粗轴 <4 则跳过，`:77-83`）→ K_arr/cF_arr/v_inlet_field 块平均（`:93-97`）→ zoned ε 块平均（`:101-107`）→ 构建粗 `SIMPLESolver3D`（`:112-126`）→ 粗解（`:139-140`）→ `scipy.ndimage.zoom` 三线性插值 (u,v,w,P) 覆盖细网格场（`:144-147`）→ 重施细网格入口 BC（`:150`）→ ideal_gas 时用插值后的 P 重建 ρ（调 `_update_density`，`:154-155`）。粗解不启用 Anderson（`:137`）。唯一生产调用点：`SIMPLESolver3D.solve()` 内部（`sjtu_tpmshx/solvers/simple_solver_3d.py:751-772`，异常吞掉绝不阻断细解，`:768-772`）。
- 触发条件（solve() 内）：`use_coarse_bootstrap` 为 None 时自动 = `Nx·Ny·Nz > _AMG_GATE`（30000）（`sjtu_tpmshx/solvers/simple_solver_3d.py:748-750`），且仅冷启动（`self.residuals` 为空）时执行（`:751`）。**但生产 pipeline 总是显式赋 bool**：`_apply_accel_flags` 赋 `cfg.get('use_coarse_bootstrap', False)`（`sjtu_tpmshx/pipelines/run_stack_3d.py:112`），cfg 默认由环境变量 `TPMSHX_PHASE_C` 决定（默认 '0' = 关，`:99-100`）——即 pipeline 路径下 auto 分支实际不可达，粗网格热启动默认关闭。

### 外层耦合骨架（`sjtu_tpmshx/solvers/coupling_skeleton.py`）

- `OuterConvergence(tol_T, track=('Ta',))`（`:39-70`）；`check(fields, extra=None, extra_tol=None) -> (converged, deltas)`（`:72-115`）：首次调用 deltas=inf 且必不收敛（`:94-99, 109`），判据 = 所有被跟踪场 max|ΔT|<tol_T AND 所有 extra<extra_tol（`:103-109`），每次调用都复制 prev（`:112-114`）。3D 生产用法：`OuterConvergence(tol_T=_outer_tol, track=('Ta','Tb','Ts'))`（`sjtu_tpmshx/pipelines/run_stack_3d.py:965`；`_OUTER_TOL=0.5` K，`:247`）。注意 `coupling_skeleton.py:55` docstring 写「3D tracks ('Ta',)」，与实际调用不一致——以调用代码为准，docstring 已过时。
- `run_outer_coupling(max_iter, step, post=None) -> (last_iter, converged)`（`:118-177`）：`for it: converged, carry = step(it); 收敛则 break; 否则 post(it, carry)`。调用方：`pipelines/run_stack_3d.py:1595`（3D，`_max_outer` 默认 `_MAX_OUTER=5`，`:246`）、`pipelines/solve_2d.py:1173`（2D）。

## 关键配置项与开关

| 配置 | 默认值 | 定义处 | 说明 |
|---|---|---|---|
| `fluid_type` | `'ideal_gas'` | `sjtu_tpmshx/solvers/simple_solver_3d.py:475` | 非 'ideal_gas' 时 `_update_density` 直接 return（`:622-623`）——不可压缩路径 |
| `massflux_inlet` | True（`getattr` 默认，无 __init__ 参数） | `sjtu_tpmshx/solvers/simple_solver_3d.py:677, 731` | 关闭需显式 `solver.massflux_inlet = False`（唯一实例：`validation/cases/validate_shanghai_aligned.py:132`）。硬不变量：勿回退 velocity-inlet |
| `alpha_u` / `alpha_p` / `alpha_rho` | 0.5 / 0.2 / 0.3 | `sjtu_tpmshx/solvers/simple_solver_3d.py:471, 477` | 动量 / 压力 / 密度欠松弛 |
| `P_ref_abs` | `P_atm` | `sjtu_tpmshx/solvers/simple_solver_3d.py:540-543` | 出口绝对压力锚。pipeline 用 1D P² 可压缩闭式种子覆盖（`sjtu_tpmshx/pipelines/run_stack_3d.py:518-527`，choke 预检在 `_seed_p_ref`，`:53-64`），并在外层迭代中重算（`:1413`） |
| P_abs clip 区间 | [1 kPa, 10 MPa] | `sjtu_tpmshx/solvers/simple_solver_3d.py:633` | 见「边界·假设」；engagement 计数 `_p_clip_hits`（`:629-631`） |
| `pyamg_rebuild_every` | 100 | `sjtu_tpmshx/solvers/simple_solver_3d.py:472` | AMG hierarchy 固定重建节拍 |
| `pyamg_rebuild_drift_thresh` | 0.05 | `sjtu_tpmshx/solvers/simple_solver_3d.py:473` | 对角线漂移触发重建；≤0 关闭漂移检查（`:239-241`） |
| `use_adaptive_amg_tol` | True（getattr） | `sjtu_tpmshx/solvers/simple_solver_3d.py:892-896` | 内层 BiCGStab rtol = clip(0.05·上轮残差, 1e-7, 1e-3)；关闭则固定 1e-5 |
| `use_sou_momentum` | False（getattr） | `sjtu_tpmshx/solvers/simple_solver_3d.py:793` | 动量 minmod SOU 延迟修正（opt-in；=0 时表达式树与一阶迎风完全一致） |
| `use_anderson` / `anderson_m` / `anderson_K` | False / 5 / 3（getattr） | `sjtu_tpmshx/solvers/simple_solver_3d.py:804-809` | Phase B Anderson 加速（残差变差自动回滚，`:963-971`）；pipeline 侧由 `TPMSHX_PHASE_B` 控制（`sjtu_tpmshx/pipelines/run_stack_3d.py:97-98`） |
| `use_coarse_bootstrap` | None（solver auto）/ False（pipeline） | `sjtu_tpmshx/solvers/simple_solver_3d.py:474, 748-750`；`sjtu_tpmshx/pipelines/run_stack_3d.py:112` | 见上文 coarse bootstrap 条目 |
| `coarse_bootstrap_max_iter` / `_tol` | 200 / 1e-3（getattr） | `sjtu_tpmshx/solvers/simple_solver_3d.py:755-759` | 粗解上限/门槛 |
| `_PARALLEL_CELL_THRESHOLD` | 200000，env `TPMSHX_PARALLEL_THRESHOLD` | `sjtu_tpmshx/solvers/simple_solver_3d.py:80-81` | ≥阈值切 red-black 并行动量 sweep（`:781-788`） |
| `_AMG_GATE` | 30000 | `sjtu_tpmshx/solvers/simple_solver_3d.py:96` | PPE spsolve↔AMG-BiCGStab 分界，兼作 bootstrap auto 门 |
| `alpha_T`（LTNE） | 0.7；`alpha_T_s/_fA/_fB` 可分相覆盖 | `sjtu_tpmshx/solvers/ltne_energy_3d.py:442, 499-505` | 必须 ∈(0,1]，否则 ValueError |
| `conv_chunk` / `q_rel_tol` | 250 / max(tol·10,1e-4) | `sjtu_tpmshx/solvers/ltne_energy_3d.py:652, 657` | chunk 粒度与 Q 相对容差 |
| `T_abs_tol` | 0.01 K（硬编码） | `sjtu_tpmshx/solvers/ltne_energy_3d.py:658` | chunk 间场稳定判据 |
| `conservative_ltne` | 函数签名默认 False；**生产 pipeline 默认 True** | `sjtu_tpmshx/solvers/ltne_energy_3d.py:452`；`sjtu_tpmshx/pipelines/run_stack_3d.py:1228` | True 强制 staggered 面速度 |
| `_RB_ENERGY` / `_RB_ENERGY_GATE` | True / 30000（模块常量） | `sjtu_tpmshx/solvers/ltne_energy_3d.py:423-424` | 能量 GS red-black 并行门 |
| `_CONV_TRACE` | None（模块变量） | `sjtu_tpmshx/solvers/ltne_energy_3d.py:415` | 设为 list 时记录逐 chunk 收敛轨迹（诊断用） |
| `chi_B_kernel_threshold` | 0.0 | `sjtu_tpmshx/solvers/ltne_energy_3d.py:448` | χ_B 低于阈值的胞跳过 Tb 更新（H6 ghost-skip） |
| `envelope_mode`（pipeline cfg） | `'raise'` | `sjtu_tpmshx/pipelines/run_stack_3d.py:389` | 'raise'→ChokedFlowError；'warn'→跑完但 `envelope_valid=False`；'off'→legacy。守卫实现在 `solvers/envelope.py`（`check_compressible_envelope`:63、`gate_solution`:153） |
| 焓求解器 | n_outer=3000, n_sweep=3(独立)/5(pipeline), omega=0.6, tol=2e-5 | `sjtu_tpmshx/solvers/ltne_enthalpy_3d.py:274, 349` | |

环境变量汇总：`TPMSHX_PARALLEL_THRESHOLD`（`sjtu_tpmshx/solvers/simple_solver_3d.py:81`）、`TPMSHX_DEBUG`（warmup 失败告警，`:1059`）、`TPMSHX_PHASE_A/B/C`（`sjtu_tpmshx/pipelines/run_stack_3d.py:95-100`）、`TPMSHX_SIMPLE_TOL`（`:71-77`，优先级 env > cfg > 1e-5）。

## 边界·假设·适用范围

- **单位**：K / Pa / m / kg / s；本模块内无 mm（TPMS 胞元尺寸 mm 陷阱在上游 tpms_calc/pipeline，不在此 7 文件内）。速度全部为 interstitial（孔内）约定（`sjtu_tpmshx/solvers/simple_solver_3d.py:26`，CLAUDE.md 硬不变量）。
- **压力为 gauge**：`self.P` 相对 `P_ref_abs`；绝对压力 = `P_ref_abs + P`（`sjtu_tpmshx/solvers/simple_solver_3d.py:624`）。3D 锚在出口（PPE 出口行 Pp=0 钉死），因此高 ΔP 直接压低出口以上游区间的绝对压力——这是 choke envelope 守卫对 3D 关键的原因。
- **`_update_density` 压力 clip（硬不变量）**：P_abs 夹到 [1 kPa, 10 MPa]（`sjtu_tpmshx/solvers/simple_solver_3d.py:633`），且当 clip 实际触发（`_eng` 掩码）时**把存储的 gauge 场 self.P 一并 floor**（`self.P = where(_eng, P_abs_clipped − P_ref_abs, self.P)`，`:636-639`），防止负绝对压力经动量压力梯度源进入下一 sweep；未触发时 self.P 不动 → 包络内解位同一（注释 `:637-638`）。ρ 本身不 clip（clip ρ 违反气体状态方程，`:640-641`），ρ 更新按 `alpha_rho` 欠松弛（`:642-643`）。**不要回退此 floor，也不要用放宽 clip 的方式「修」ChokedFlowError**（CLAUDE.md）。
- **mass-flux inlet 语义**：velocity-inlet + 可压缩 + Forchheimer 是正反馈（dP↑→ρ↑→dP↑，Bug B 记录 `sjtu_tpmshx/solvers/simple_solver_3d.py:663-671`）；固定 G=ρ·v 变为负反馈。目标 G 只在 solve() 首次捕获（`:731-737`），warm restart 不重捕——外层耦合中 ρ 抬升不会使目标漂移。低 ΔP 工况下 ρ≈ρ_ref 故行为≈velocity-inlet（`:670-672`）。
- **动量方程形式**：均匀-每侧-ε 形式，动量算子无 ε 权重、无 ∇ε 源（`sjtu_tpmshx/solvers/simple_solver_3d.py:29-32`）；域内 ε 梯度（zoned）经两处进入：连续算子 ε·ρ（`:845-855`）+ 可选 M2b VANS ε-ratio 因子（仅当 eps_field 真非均匀时 `_use_eps=1`，`:796-800`；kernel 侧 `sjtu_tpmshx/solvers/_kernels_simple_3d.py:167-184`）。研究台账 B5 已标记连续场 ∇ε 失效域——做 zoned ε 前先查台账。
- **数值格式**：动量默认一阶迎风（SOU opt-in）；LTNE 一阶迎风 + minmod SOU 延迟修正。ΔP 网格收敛阶受一阶迎风内格式限制（实测 p≈0.76，面外推只加速常数不改阶，`sjtu_tpmshx/solvers/simple_solver_3d.py:424-431`——该数字来自注释引用的 Shanghai 16/32/64 加密实验，本文未独立复核，标注：引用注释）。
- **fastmath 与位同一**：所有 kernel `fastmath=True`；`use_sou`/`use_eps` 采用「守卫式 +=/×」保证 =0 分支的表达式树不变（否则 fastmath 重结合破坏 golden 位同一，`sjtu_tpmshx/solvers/_kernels_simple_3d.py:99-104, 217-220`；`_v_bc_3d` 的均匀 ε 分支同理 `:455-473`）。
- **LTNE 稳态、无流体压缩功/黏性耗散项**：能量方程见模块头（`sjtu_tpmshx/solvers/ltne_energy_3d.py:6-11`，标注 "steady, incompressible, homogenised porous"——可压缩性经外层耦合以变 ρcp 场进入，而非能量方程内项）。
- **legacy 胞心 LTNE 内核**的已知缺陷：ρ 变化流上 Q_enthalpy↔Q_source 漂移（`sjtu_tpmshx/solvers/ltne_energy_3d.py:662-664`）——生产走 conservative staggered 路径规避。**注意 13-22% AB imbalance 不是这个 legacy 内核的缺陷**：那是 staggered 内核 `_gs_full_chunk_3d_stag` 自身在 `conservative==0`（非守恒）分支里的自述极限（`sjtu_tpmshx/solvers/_kernels_ltne_3d.py:399-404`）；真正的 legacy 胞心内核 `_gs_full_chunk_3d` 反而自述 <1% imbalance（`:1004`），二者不可混同。
- **焓求解器适用范围**：仅 counterflow along x（dir 0/1）、均匀网格、每列均分质量流量（`sjtu_tpmshx/solvers/ltne_enthalpy_3d.py:17-21, 293-294, 358-362`）；h 迭代量夹窗（入口温度 ±40/60 K，按流体下限 `_FL_TLO` floor，`:302-307, 376-381`）。
- **coarse bootstrap 正确性边界**：粗解纯属初值装置，几何系数块平均而非重评 TPMS sigmoid（`sjtu_tpmshx/solvers/coarse_bootstrap_3d.py:12-15`）；细解仍受自身 tol 门约束，最终解正确性不依赖粗解收敛（`:15-16`；粗解不收敛也照样 prolongate，`:139-147`）。

## 可扩展接口

- **私有 kwargs（ε 分拆钩子）**：`solve_full_domain_3d` 的 `eps_A`/`eps_B`（`sjtu_tpmshx/solvers/ltne_energy_3d.py:444`）——asym offset-isosurface δ 的唯一合法入口，上游分拆逻辑在 `solvers/asym_split.py`（CLAUDE.md）。焓求解器对应 `eps_A_field`/`eps_B_field`（`sjtu_tpmshx/solvers/ltne_enthalpy_3d.py:273, 348`）。
- **solver 实例属性开关（无 __init__ 参数，靠 getattr）**：`massflux_inlet`、`use_sou_momentum`、`use_anderson`/`anderson_m`/`anderson_K`、`use_adaptive_amg_tol`、`coarse_bootstrap_max_iter`/`coarse_bootstrap_tol`（各定义处见上表）。pipeline 统一入口 `_apply_accel_flags`（`sjtu_tpmshx/pipelines/run_stack_3d.py:103-114`）。
- **MMS 制造解源项**：`mms_S_A_field`/`mms_S_B_field`/`mms_S_s_field`（`sjtu_tpmshx/solvers/ltne_energy_3d.py:449-451`；默认零数组 = 生产 no-op，`:699-710`）——阶次验证用（`validation/cases/mms_3d_air_air.py` 直接 import staggered 内核，re-export 注释 `:307-310`）。
- **χ_B 闭合钩子**：`chi_B_field` + `chi_B_kernel_threshold`（`sjtu_tpmshx/solvers/ltne_energy_3d.py:447-448`）。
- **cancel/progress 钩子**：SIMPLE `cancel_check`（每 25 外层迭代轮询，`sjtu_tpmshx/solvers/simple_solver_3d.py:842-844`）；LTNE `progress_cb` + `cancel_check`（chunk 间轮询，`sjtu_tpmshx/solvers/ltne_energy_3d.py:752-757`）。
- **enthalpy_mode 路由**：`run_stack_3d.py` 中 `ltne_enthalpy_mode` cfg 门（`sjtu_tpmshx/pipelines/run_stack_3d.py:1245-1248, 1312-1326`）是把 Option B 内核并入生产能量求解的预留分支；`ltne_enthalpy_3d.py:19-21` 声明 cross-flow/offset ε/SOU/staggered/red-black 属 Phase 2.3+ 集成期工作（预留、未实现）。
- **第三消费者插入点**：`run_outer_coupling` docstring 明示当出现 quasi-2.5D 模式时作为统一插入缝（`sjtu_tpmshx/solvers/coupling_skeleton.py:28-30`）。
- **诊断暴露**：`solver._ml_cache`（rebuild/skip/drift/bcg 计数与耗时，`sjtu_tpmshx/solvers/simple_solver_3d.py:238, 248-277`）、`solver._coarse_bootstrap_info`（`:762`）、`solver._p_clip_hits`（`:629-631`）、`ltne_energy_3d._CONV_TRACE`（`:411-415`）。
- **kernel re-export 兼容层**：旧 import 路径 `from solvers.simple_solver_3d import <kernel>` / `from solvers.ltne_energy_3d import _gs_full_chunk_3d_stag` 仍有效（`sjtu_tpmshx/solvers/simple_solver_3d.py:104-129`；`sjtu_tpmshx/solvers/ltne_energy_3d.py:304-332`）。

## 已知不足与 TODO

代码中（本 7 文件）无 `TODO`/`FIXME`/`NotImplementedError` 标记；以下为代码可核实的自述限制与观察项：

1. **PPE 出口钉死仅支持 j=Ny-1 行**：`_build_pp_sparsity_3d` docstring 自述 "Phase 1 pins k=Nz-1 too if provided. For MVP we use j=Ny-1 only"（`sjtu_tpmshx/solvers/simple_solver_3d.py:136-139`）——SIMPLE 的主流方向被硬绑定到 j 轴，其他朝向由调用方转置解决。
2. **`use_sou_momentum` 收益从未量化**（模块头自述，`sjtu_tpmshx/solvers/simple_solver_3d.py:12-14`），默认关闭。
3. **coarse bootstrap 不同步 partial 掩码**：粗 solver 在 `sjtu_tpmshx/solvers/coarse_bootstrap_3d.py:112-126` 构建时未传 `inlet_frac`/`outlet_frac`（保持 `__init__` 默认全 1，`sjtu_tpmshx/solvers/simple_solver_3d.py:592-593`），也未镜像 `use_sou_momentum`/`massflux_inlet` 等 getattr 属性——partial-outlet 构型的粗解按全宽出口求解。对最终解正确性无影响（仅初值），但热启动质量对 offset-outlet 构型可能打折。未见测试覆盖此点（未验证其实际影响量级）。
4. **staggered 内核非守恒分支的 13-22% AB imbalance**（不是 legacy 胞心内核）：`_gs_full_chunk_3d_stag` 在 `conservative==0` 时，NET_OUT 各修正变体均失稳后被接受为离散极限（`sjtu_tpmshx/solvers/_kernels_ltne_3d.py:399-404`）；真正的 legacy 胞心内核 `_gs_full_chunk_3d` 自述 <1% imbalance（`:1004`）。生产以 conservative staggered 路径（`conservative==1`）替代。
5. **焓求解器为验证态部分实现**：cross-flow、offset ε、SOU、staggered 面通量、red-black 并行未实现，计划折入 `ltne_energy_3d` 的 `enthalpy_mode` 路由（`sjtu_tpmshx/solvers/ltne_enthalpy_3d.py:17-21`）；pipeline 版把非均匀网格间距按均值塌成标量（`:362`）。`_T_LO, _T_HI = 240.0, 420.0`（`:30`）在文件内未见其他引用（疑似遗留常量，未验证是否有外部消费者）。
6. **`coupling_skeleton.py` docstring 过时**：`:51-55` 写 2D tol 1.0 / 3D track ('Ta',)，实际 3D 用 `tol_T=0.5, track=('Ta','Tb','Ts')`（`sjtu_tpmshx/pipelines/run_stack_3d.py:247, 965`），2D 也用 `track=('Ta','Tb','Ts')`（`sjtu_tpmshx/pipelines/solve_2d.py:863`）。以调用代码为准。
7. **`_is_bc_face_inlet`/`_is_bc_face_outlet`/`_ifrac_at_face`/`_Tin_at_face`**（`sjtu_tpmshx/solvers/_kernels_ltne_3d.py:873-923`）标注为 "2026-04-26 strict-conservation refactor" 遗产，在当前内核中未被调用，仅经 re-export 保留。
8. **red-black 能量内核与串行收敛到同一不动点**为注释断言（"verified"，`sjtu_tpmshx/solvers/_kernels_ltne_3d.py:606-614`），本文未独立复核（Q/dP 一致性有 golden gate 侧面保证，位级 field 一致性无保证——两者迭代路径不同）。
9. Anderson 加速（Phase B）自述 "Off-by-default for safety... until full-sweep validated"（`sjtu_tpmshx/solvers/simple_solver_3d.py:803-804`；`sjtu_tpmshx/pipelines/run_stack_3d.py:90-91`）。
10. **`self.final_res` 是出口 pin 伪迹，零收敛信息；`tol=1e-5` 是死钮（实测，2026-07-12，台账 C6）。改它之前必读。**
    - **机制**：`_build_pp_sparsity_3d:158` 把出口整行标 `cell_kind=1`，`_assemble_pp_3d:750` 据此把这些格的**连续性方程替换成 `Pp=0`** —— 从未被求解（标准 SIMPLE 压力基准做法，2D `_kernels_simple_2d.py:735` 同构，本身不是 bug）。而 `:910` 算残差用的 `rho_eps_field` 正是 `:897` 的 `_solve_pp_amg` 刚刚**精确求解过** `div(ρε·u)=0` 的那份数组（`:908` 的 `_update_density` 之前），**故在所有被求解的格上残差按构造 ≈0**（实测剔掉出口行后 `final_res = 2.9e-17`）。两者相加 ⇒ **报出来的数 100% 是出口行未被修正的横向散度**。
    - **实测印证**（上海生产管线，20×10×3）：① 任何工况从未以 `'tol'` 退出，全走 velocity 判据；② `max_iter` 2000→6000（×3）残差**逐位不动**（7.86e-4→7.86e-4）；③ 地板只随 **Nz** 变，Nx/Ny ×4 无变化（Nz 决定出口面横向网格）；④ 方向分解：主流向 `Σ|Fy|/ṁ=4.6e-6`（被出口 v-BC 外推 `_kernels_simple_3d.py:870` 精确望远镜掉），横向 `Σ|Fx|/ṁ=4.2e-3`、`Σ|Fz|/ṁ=1.3e-2`。
    - **不要这样"修"**：单纯在 `_mass_res_jit_3d` 里跳过出口行 → 残差变成恒等 0，`tol` 在最小迭代数处即触发，**动量场未收敛就退出**（实测上海 case 1 的 dP 偏 −2.1%）。**连续性比动量收敛得快**，而本求解器**不跟踪动量残差**，故 mass-`tol` 只可能提前退出。
    - **两条被认可的路**（均需 V&V + golden 重基线）：(F1) 把口径改成「更新后的 ρ + 只统计被求解的格」，**仅作诊断**，退出仍由 velocity 判据主导；(F2) 补一个动量残差，两者 AND（正统 SIMPLE）。
    - **与 2D 的口径差**：2D `_mass_res_jit`（`_kernels_simple_2d.py:909`）量的是**截面积分通量** `max_j |Σᵢ ρv·dx − Q_in|/Q_in`，逐格横向失衡在面内互相抵消、看不见；3D 量的是**逐格散度**，严格更强。**两者被喂同一个 `tol`。** 这也是为什么 2D 的 `_enforce_mass_conservation`（`simple_solver.py:958`）移植到 3D 是**实测无效**的：它恰好把 2D 那个积分量掐到零，是给那个口径量身定做的（3D 实测 `scale=1.000194`，且出口面残差 99.97% 是散乱抵消，`|Σ|/Σ|·| = 0.03%`）。

## 服务器移植注意

1. **import 路径假设**：本包混用相对 import（`from ._kernels_simple_3d import ...`）与顶层绝对 import——`from solvers.ltne_energy import solve_full_domain`（`sjtu_tpmshx/solvers/ltne_energy_3d.py:29`）、`from logutil import get_logger`（`sjtu_tpmshx/solvers/simple_solver_3d.py:68`）。后者要求 `sjtu_tpmshx/` 目录本身在 `sys.path` 上（以 `solvers`、`logutil` 为顶层模块运行），不是 `pip install` 后的 `sjtu_tpmshx.solvers` 命名空间。移植时保持运行目录/`PYTHONPATH` 约定，或全面改相对 import（改动面大，勿轻动）。
2. **依赖**：numpy、numba（njit/prange/fastmath）、scipy（sparse、spsolve、bicgstab、cg、ndimage.zoom）为硬依赖；**pyamg 为可选**（`sjtu_tpmshx/solvers/simple_solver_3d.py:62-66`，缺失时大网格 PPE 落到 spsolve，慢但可用；但 `ltne_energy_3d._laplacian_amg_cache` 在 conservative 投影路径**函数内硬 import pyamg**，`sjtu_tpmshx/solvers/ltne_energy_3d.py:58`——生产 conservative_ltne=True 下 pyamg 实际必需）。**CoolProp 是 `ltne_enthalpy_3d.py` 的模块级硬 import**（`:38`）——无 CoolProp 的环境 import 该模块即失败；`run_stack_3d` 对它是惰性 import（`sjtu_tpmshx/pipelines/run_stack_3d.py:1312`），仅 enthalpy_mode 触发。
3. **import 即 JIT 预热**：两个模块在 import 时跑 warmup 编译全部 kernel（`sjtu_tpmshx/solvers/simple_solver_3d.py:1065`；`sjtu_tpmshx/solvers/ltne_energy_3d.py:972`），首次 import 需数十秒 CPU；均 best-effort 吞异常（`:1057-1062` / `:968-969`）。numba `cache=True` 会在包目录写 `__pycache__` 磁盘缓存——只读文件系统/容器需允许写或设 `NUMBA_CACHE_DIR`。
4. **并行与确定性**：并行 kernel 用 numba `prange`，线程数由 numba 运行时（`NUMBA_NUM_THREADS`）决定；red-black 设计保证结果不随线程数变（同色胞只读异色邻居 + SOU 快照，`sjtu_tpmshx/solvers/_kernels_simple_3d.py:275-279`；`sjtu_tpmshx/solvers/_kernels_ltne_3d.py:597-614`）。golden 位同一门要求 `PYTHONHASHSEED=0`（repo `/check` 约定）。fastmath 位级结果依赖 numba/LLVM 版本与 CPU 指令集——目标机虽同为 Windows（开发机 Windows 11 → Windows Server 2022，不是跨 OS 迁移），但服务器的 CPU 型号/指令集（例如是否支持 AVX-512）与 numba/LLVM 版本大概率与开发机不同，golden hash 仍可能不再逐位一致，应按数值容差重基线而非追位同一（推断项：基于 fastmath 语义，未在目标 Windows Server 机器上实测）。
5. **无跨平台适配面，但并行阈值仍需按服务器硬件重调**：本 7 文件本身无路径分隔符/大小写敏感文件系统/GUI 依赖相关代码，迁移目标同为 Windows（Server 2022 而非 Linux）——这一层不适用（同为 Windows，无需处理）。真正需要关注的是 `_PARALLEL_CELL_THRESHOLD=200000` 与 `_AMG_GATE=30000`，两者是开发机 8 核桌面上的经验分界（`sjtu_tpmshx/solvers/simple_solver_3d.py:73-81, 90-96`），与目标平台是否 Linux 无关，只取决于服务器实际核数/CPU；核数不同时前者可经 `TPMSHX_PARALLEL_THRESHOLD` 重调，AMG 门无 env 开关，需改代码。
6. **内存**：PPE 走 spsolve 的分支（<30k 胞，或 pyamg 缺失/BiCGStab 失败回退）做稀疏 LU，3D 大网格下 fill-in 内存开销显著（注释 `sjtu_tpmshx/solvers/simple_solver_3d.py:93-94`）；服务器上跑大网格务必确保 pyamg 就位。
7. **日志（GBK 编码坑不会因迁移到 Windows Server 而消失，需重点处理）**：经 `logutil.get_logger`（`sjtu_tpmshx/solvers/simple_solver_3d.py:68-70`），Handler 直写 `sys.stdout`、未显式指定 encoding（`sjtu_tpmshx/logutil.py:45-62` `_StdoutHandler`，逐条读取当前 `sys.stdout` 以兼容 GUI 的 `redirect_stdout` 捕获）——实际写出编码取决于运行环境的控制台代码页/locale。repo 记忆记录过一次真实事故：中文文件路径经 subprocess 以 GBK 字节写出、pytest 按 UTF-8 读 capture，导致连续 teardown 抛 `UnicodeDecodeError`（blindspot-audit 2026-07-07）。目标 Windows Server 与开发机同为 Windows，若采用中文区域设置，系统默认代码页通常仍是 GBK/CP936（未验证目标服务器是否已启用「Beta: 使用 UTF-8 支持全球语言」选项）——**这个坑原样保留、不会随迁移到服务器自动消失，需要主动处理**：日志行须保持 ASCII-only（沿用既有仓库规则），或在批处理入口显式设置 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`，不要依赖控制台默认代码页。本 7 文件内仅 `sjtu_tpmshx/solvers/simple_solver_3d.py:764, 772, 981` 三处 `_log.*` 调用，格式串本身是 ASCII，但 `:772` 的 `{exc}` 插值透传下游异常文本——若下游异常消息含中文路径（本仓库工作区常见），该行仍可能违反 ASCII-only 规则、触发同一陷阱（未验证是否已实际发生）。
