# solvers — 2D SIMPLE + 能量
生成日期 2026-07-10，基于 commit f33d30e 附近的 master

> 本文档所有断言均以代码为唯一真源，逐条附 file:line（行号对应上述 commit 的工作区文件）。目标读者为在 **Windows Server 2022** 服务器上移植/改造本库的编码代理。

## 定位与功能

本模块是自研 Python 可压缩 SIMPLE/LTNE TPMS 换热器求解器的 2D 部分，覆盖 7 个文件：

- **`sjtu_tpmshx/solvers/simple_solver.py`** — 2D 稳态 SIMPLE 求解器（交错网格，多孔介质 Darcy-Forchheimer 阻力），生产默认为可压缩 ideal-gas ρ=ρ(P,T) + 质量通量入口（`sjtu_tpmshx/solvers/simple_solver.py:6-7`）。动量物理为 Navier-Stokes + Brinkman 多孔阻力，D-F（ConstDF-v1）是唯一阻力闭合，旧 friction-factor 形式已删除（`sjtu_tpmshx/solvers/simple_solver.py:11-18`）。
- **`sjtu_tpmshx/solvers/_kernels_simple_2d.py`** — 全部 2D SIMPLE numba 核 + 压力 Poisson 稀疏直接解基础设施，2026-07-03 从 simple_solver.py 逐字迁出（`sjtu_tpmshx/solvers/_kernels_simple_2d.py:1`），并在 simple_solver.py 内重导出以保持旧导入路径可用（`sjtu_tpmshx/solvers/simple_solver.py:55-75`）。
- **`sjtu_tpmshx/solvers/_kernels_2d.py`** — 共享 numba 辅助核，仅含 MINMOD 限制器 `minmod`（`sjtu_tpmshx/solvers/_kernels_2d.py:11-27`）。
- **`sjtu_tpmshx/solvers/_solve_common.py`** — 2D/3D 共用的 SIMPLE 外循环早退判据 `LowReExit`（`sjtu_tpmshx/solvers/_solve_common.py:20`）。
- **`sjtu_tpmshx/solvers/anderson_acceleration.py`** — SIMPLE 外层 Picard 迭代的 Type-II Anderson 加速（`sjtu_tpmshx/solvers/anderson_acceleration.py:27`）。注意：当前仅 3D 求解器接入，2D 未接入（见「可扩展接口」）。
- **`sjtu_tpmshx/solvers/ltne_energy.py`** — 全域稳态双流体 LTNE（Ta/Tb/Ts 三温）能量求解器，胞元耦合 Gauss-Seidel（`sjtu_tpmshx/solvers/ltne_energy.py:1-20`）。
- **`sjtu_tpmshx/solvers/threads.py`** — Numba 线程池运行时控制（`sjtu_tpmshx/solvers/threads.py:1-17`）。

调用链概貌：`pipelines/stages_2d.py`、`optimization/evaluator.py`、`validation/cases/validate_shanghai_aligned.py` 构造 `SIMPLESolver`（分别见 `sjtu_tpmshx/pipelines/stages_2d.py:479,493`、`sjtu_tpmshx/optimization/evaluator.py:252,301`、`sjtu_tpmshx/validation/cases/validate_shanghai_aligned.py:118`）；`pipelines/solve_2d.py:423,1058` 与 `optimization/evaluator.py:560` 调用 `solve_full_domain`；`ltne_energy_3d.py` 的 Nz==1 快速路径委托给 2D `solve_full_domain`（`sjtu_tpmshx/solvers/ltne_energy_3d.py:22,29`）。

## 文件一览

| 文件 | 行数 | 一行职责 |
|---|---|---|
| `sjtu_tpmshx/solvers/simple_solver.py` | 1382 | `SIMPLESolver` 类（2D 交错网格 SIMPLE/SIMPLER 外循环、可压缩密度更新、质量通量入口、网格生成、单流体冻结速度温度解）+ 便捷函数 |
| `sjtu_tpmshx/solvers/_kernels_simple_2d.py` | 1021 | 全部 `@njit` 动量扫掠核（`_sweep_u/v_jit_df`）、SIMPLER 伪速度核、压力 Poisson CSR 组装 + scipy 直接解、修正核、质量残差核、单流体温度核 |
| `sjtu_tpmshx/solvers/_kernels_2d.py` | 27 | `minmod` 限制器（`@njit(inline='always')`），供全部 SOU 延迟修正核共用 |
| `sjtu_tpmshx/solvers/_solve_common.py` | 86 | `LowReExit` — 速度静止/残差平台早退判据，2D/3D 单一真源，纯 Python 保位一致 |
| `sjtu_tpmshx/solvers/anderson_acceleration.py` | 153 | `AndersonSIMPLE` Type-II 加速器 + `stack_state`/`unstack_state` 状态向量打包 |
| `sjtu_tpmshx/solvers/ltne_energy.py` | 920 | `solve_full_domain`（双流体三温 LTNE）+ 串行核 `_gs_full_chunk` + 红黑并行核 `_gs_full_chunk_rb` |
| `sjtu_tpmshx/solvers/threads.py` | 52 | Numba 线程数三层控制（`NUMBA_NUM_THREADS` 硬上限 / `TPMSHX_NUM_THREADS` 运行时 / `set_solver_threads` GUI 旋钮） |

## 公开接口

### SIMPLESolver（`sjtu_tpmshx/solvers/simple_solver.py:235`）

**`__init__`**（`sjtu_tpmshx/solvers/simple_solver.py:259-276`）：`SIMPLESolver(W, H, Nx, Ny, tpms_type, L_cell_mm, t_mm, eps, r_h, rho, mu, T_in, inlet_lo, inlet_hi, v_inlet, outlet_lo=None, outlet_hi=None, P_ref=0.0, zone_config=None, zone_arrays=None, y_breakpoints=None, fluid_type='ideal_gas', R_gas=287.05, T_field=None, P_ref_abs=None, alpha_rho=0.3, rho_inlet_ref=None, wall_refine=True, n_wall_refine=8, wall_first_cell=0.02e-3, cf_scale=1.0, **_legacy_kw)`。历史 `closure` kwarg 被接受但忽略（`sjtu_tpmshx/solvers/simple_solver.py:277-279`）。调用方见上文调用链。要点：

- **rho_inlet_ref**：入口参考密度，即调用方把 ṁ 换算成 v_inlet 时使用的物理入口密度 ρ(T_in, P_in)。存入 `self._rho_inlet_ref`（`sjtu_tpmshx/solvers/simple_solver.py:290-291`）。传 None 则退化为首次 `solve()` 时从 `rho_field[:,0].mean()` 捕获（`sjtu_tpmshx/solvers/simple_solver.py:761-764`）——该回退在「求解器每外迭代重建 + 入口压力基准」场景下会使目标棘轮式漂移，故 2D pipeline 与 validation 显式传入（`sjtu_tpmshx/pipelines/stages_2d.py:475,486,501`；`sjtu_tpmshx/validation/cases/validate_shanghai_aligned.py:267`；注释论证见 `sjtu_tpmshx/solvers/simple_solver.py:283-289,750-757`）。
- **D-F 系数预计算**：uniform 几何时对 `predict_K_cF(tpms_type, L_cell_mm, t_mm, 0.5*eps)` 取单点并广播到每行（`sjtu_tpmshx/solvers/simple_solver.py:411-415`）；`zone_config` 分区时逐行批量预测，`eps_f_row[j] = 0.5*z_eps`（每流股空隙率 ε_A，`sjtu_tpmshx/solvers/simple_solver.py:394-408`）。即 **2D 动量 K/cF 的查询空隙率是 ε/2（单流股）**。
- **入口边缘 taper + 通量重归一**：部分宽度入口在墙/开口过渡处做 4 胞元指数 taper（`sjtu_tpmshx/solvers/simple_solver.py:459-465`），并以 `_inlet_taper_flux_scale = 几何开口通量/taper 后通量` 重标 `v_inlet_field`，保证 taper 不删除吞吐量（N3 修正，`sjtu_tpmshx/solvers/simple_solver.py:475-481`）；全宽入口 taper 不触发，保位一致。

**`solve(max_iter=3000, tol=1e-6, alpha_u=0.7, alpha_p=0.3, n_inner=2, coupling='simple', simpler_relax_p=1.0, verbose=True, progress_cb=None) -> (converged: bool, iterations: int)`**（`sjtu_tpmshx/solvers/simple_solver.py:703-707`）。要点：

- **质量通量入口目标捕获**：`massflux_inlet` 经 `getattr(self, 'massflux_inlet', True)` 默认开启（`sjtu_tpmshx/solvers/simple_solver.py:758` 与 `:624`）——它**不是构造参数**，而是可在构造后设置的实例属性（关闭示例：`sjtu_tpmshx/validation/cases/validate_shanghai_aligned.py:132` 的 `s.massflux_inlet = False`；默认值有护栏测试 `sjtu_tpmshx/tests/test_invariant_negative_guards.py:108-116`）。目标 `_massflux_target = v_inlet · ρ_ref · _inlet_taper_flux_scale` 仅捕获一次（`not hasattr` 守卫，`sjtu_tpmshx/solvers/simple_solver.py:758-772`），优先用 `_rho_inlet_ref`（`:761-762`）。
- **每外迭代序列**（coupling='simple'）：`_sweep_u_jit_df` → `_sweep_v_jit_df` → `_solve_pp_sparse_fast`（压力修正 Pp）→ `_correct_jit`（`sjtu_tpmshx/solvers/simple_solver.py:860-879`）→ `_update_density()`（`:880`）→ `_mass_res_jit` 残差（`:882`）。收敛判据 `res < tol and it >= 20`（`:897`）。
- **lateral-K 2D 场**：核消耗 2D (Nx,Ny) K/cF 场；未设置 override 时把每行 1D `_K_arr` 沿横向平铺，与历史每行行为位一致（`sjtu_tpmshx/solvers/simple_solver.py:774-784`）。
- **早退**：`LowReExit(self, (self.u, self.v), min_iter=20)`（`sjtu_tpmshx/solvers/simple_solver.py:741`）；`'velocity'`（场静止）返回 converged=True，`'stall'`（残差平台但场仍蠕动）返回 converged=False（`sjtu_tpmshx/solvers/simple_solver.py:914-920`）。退出簿记 `self.exit_reason ∈ {'tol','velocity','stall','max_iter'}` 与 `self.final_res`（`:744-746,901-902,918-919,928-929`）。
- **SIMPLER 分支（实验性）**：`coupling='simpler'` 走 Patankar/Tao 六步（伪速度 `_pseudo_u/v_jit_df` → P 直接解并替换 → 动量 → p' 仅修正速度，α_p=0.0，`sjtu_tpmshx/solvers/simple_solver.py:803-858`）；仅在全宽入出口 ideal-gas 配置上做过基准，partial-BC 未基准（`sjtu_tpmshx/solvers/simple_solver.py:713-718`）。

**`_update_density()`**（`sjtu_tpmshx/solvers/simple_solver.py:540`）：ideal-gas 时 ρ=P_abs/(R·T)，P_abs 裁剪到 [1 kPa, 10 MPa]（`:579`）；裁剪触发时同步下限存储的 gauge 压力场（`:583-585`，硬不变量——防负绝压进入动量源）；ρ 以 `alpha_rho`（默认 0.3，`:270`）欠松弛混合（`:592-593`）；随后调用 `_apply_massflux_inlet()`（`:595`）。

**`_apply_massflux_inlet()`**（`sjtu_tpmshx/solvers/simple_solver.py:597`）：逐胞元 `v_inlet_field = _massflux_target / max(rho_field[:,0], 1e-9)`（`:628-630`），`self.v_inlet` 保留为横向均值供诊断（`:631`）。禁用或目标未捕获时为 no-op（`:624-626`）。该机制把速度入口的可压缩正反馈（dP↑→ρ↑→dP↑）转为负反馈，是 Shanghai Δp 网格收敛的关键（`sjtu_tpmshx/solvers/simple_solver.py:602-609`）。

**其它方法**：`set_K_cF_field(K2d, cF2d)` 每胞元 D-F override，形状必须 (Nx,Ny)（`sjtu_tpmshx/solvers/simple_solver.py:684-701`）；`update_rho_field`（`:535`）；`update_T_field`（`:633`，ideal-gas 时经 Sutherland `_refresh_mu_from_T`，`:673-681`）；`solve_temperature(K_ff, K_ss, h_v, rho_cp_f, T_in, T_other=None, h_v2=0.0, ...)` 单流体冻结速度 LTNE（`:1007-1044`，注意此处传给核的是**全 ε** `self.eps`，`:1035`，与 ltne_energy 的减半路径无关）；`detect_uniform_boundary(threshold=0.045)`（`:1079`）；`get_exit_profile`（`:1135`）；`_enforce_mass_conservation`（`:958`，部分出口的事后全局质量重标，opt-out 属性 `enforce_outlet_mass_balance`，`:981`）；静态方法 `solve_outlet_transition`（`:1164`）；模块级 `solve_transition_zone`（`:1230`）。网格生成函数：`_aligned_grid`（`:82`）、`build_wall_refined_1d`（`:139`）、`build_inlet_stretched_1d`（`:172`，opt-in，未接入默认路径，`:182-185`）。

### 动量/压力核（`sjtu_tpmshx/solvers/_kernels_simple_2d.py`）

- **`_porous_src_df(umag, K, cF, mu, rho)`**（`sjtu_tpmshx/solvers/_kernels_simple_2d.py:159-173`）：线性化多孔阻力系数 `mu/K + rho·cF·|u|`；`umag < 1e-10` 时退化纯 Darcy。
- **`_sweep_u_jit_df` / `_sweep_v_jit_df`**（`sjtu_tpmshx/solvers/_kernels_simple_2d.py:193-197` / `:328-332`）：x/y 动量 GS 扫掠。含：M2 VANS ∇ε 通量面比 r_f = ε_f/ε_CV（均匀 ε 时全部恒为 1.0，位一致，`:204-211,227-237`）；N4 实际邻点距扩散导度（`:239-249`）；SOU 延迟修正 `_sou_corr_u_x/u_y/v_x/v_y`（`:25,59,88,117`，N2 修正：west/south 面限制器乘 west/south 面通量使修正可望远镜求和，`:13-23`）；Brinkman 墙惩罚 `_WALL_PENALTY_BASE=1e3`、`_WALL_PENALTY_EFOLD=1.5`（`:155-156`），在阻塞入/出口面 8 胞元内施加 `BASE·frac⁴·exp(−EFOLD·(dist−1))·aP_nat`（`:299-310`）；侧壁 no-slip（v 扫掠 `De=2μ_e·dyj/dxi`，`:373-382`）。u 节点 K/cF 取横跨两胞元算术平均（`:278-279`），v 节点保留 streamwise 单点取值 `K_arr[i, jc]`（`:405-418`）。cf_aniso ≠ 0 时 `cF_eff = cF·(1 + a·4nx²ny²)`（`:287-293`）。出口 v 外推守恒 ε·ρ·v（`:444-461`）。
- **`_pseudo_u_jit_df` / `_pseudo_v_jit_df`**（`:476-479` / `:573-576`）：SIMPLER 伪速度 û/v̂ = (Σa_nb·φ_nb + SOU)/aP0（无压力源、无欠松弛）；系数块与 `_sweep_*_jit_df` 有**逐行一致契约**——改任一核必须同步另一核（`sjtu_tpmshx/solvers/_kernels_simple_2d.py:470-474`）。
- **压力 Poisson**：`_build_pp_sparsity_pattern(Nx, Ny, outlet_frac)` 预构 CSR（每胞元 5 槽 [diag,E,W,N,S]；`j==Ny-1 且 outlet_frac>0.01` 的胞元为 Pp=0 参考点，`sjtu_tpmshx/solvers/_kernels_simple_2d.py:691-759`）；`_assemble_pp_data_jit`（`@njit`，`:762-830`）；`_solve_pp_sparse_fast` 用 `scipy.sparse.linalg.spsolve` 直接解（`:833-859`，`:852-855` 复制 indices/indptr 防 spsolve 原地重排损坏缓存）。
- **`_correct_jit`**（`:864-904`）：P += α_p·Pp（跳过出口参考胞元）、u/v 速度修正、重施 BC；出口 v 按 ε·ρ·v 守恒规则重写（`:891-904`）。
- **`_mass_res_jit`**（`:908-934`）：残差 = 各横截面质量通量相对入口通量的最大偏差。
- **`_solve_temp_jit`**（`:938-1021`）：单流体+固体温度 GS（供 `SIMPLESolver.solve_temperature`），对流通量用**全 ε**：`Fe = eps·rho_cp_f·u·dy`（`:966-969`）。

### LowReExit（`sjtu_tpmshx/solvers/_solve_common.py:20`）

`LowReExit(solver, vels, min_iter)`，每外迭代恰好调用一次 `check(vels, res, it) -> None | 'velocity' | 'stall'`（`sjtu_tpmshx/solvers/_solve_common.py:62`）。判据：(B) `max|Δv|/scale < vtol` → 'velocity'；(A) 残差在窗口内改善 < stall_ratio 且场近静止（10×vtol）→ 'stall'（`:26-32,67-82`）。参数经 `getattr` 从求解器实例读取，默认 `lowre_early_exit=True, lowre_vel_tol=1e-4, lowre_stall_window=30, lowre_stall_ratio=1e-3`（`:53-56`）。位一致契约：纯 Python、无 numba/fastmath，golden 2D+3D 位一致是合并门槛（`:9-13`）。

### AndersonSIMPLE（`sjtu_tpmshx/solvers/anderson_acceleration.py:27`）

`AndersonSIMPLE(m=5, K=3, beta=1.0, cond_max=1e10)`（`sjtu_tpmshx/solvers/anderson_acceleration.py:43-48`）。接口：`push(x, gx)` 记录迭代对（`:63`）；`candidate(gx_picard) -> (x_new, applied)` Type-II 外推 `x = G(x_k) − (dX+dR)@γ`，γ 由 `lstsq(dR, r_curr)` 求得（`:68-118`，`:109`）；条件数 > cond_max 或非有限值时跳过（`:93-99,113-115`）；`maybe_rollback` 残差上升即回滚 Picard（`:120-126`）。`stack_state(u,v,w,P)`/`unstack_state`（`:129-153`）。**接入点：仅 3D** —— `sjtu_tpmshx/solvers/simple_solver_3d.py:804-809` 经 `getattr(self, 'use_anderson', False)`（默认关闭）实例化并在外循环中使用（`:925-976`）；**2D `SIMPLESolver.solve()` 未接入 Anderson**（`sjtu_tpmshx/solvers/simple_solver.py:703-930` 全程无引用；已核实）。质量守恒警告：Anderson 混合不保 ∇·(ρu)=0，调用方必须在每次 Anderson 步后追加一次压力修正投影（`sjtu_tpmshx/solvers/anderson_acceleration.py:7-14`）。

### solve_full_domain（`sjtu_tpmshx/solvers/ltne_energy.py:608`）

`solve_full_domain(L, H, Nx, Ny, T_inA, T_inB, K_ffA, K_ffB, K_ss, h_vA, h_vB, rho_cp_fA, rho_cp_fB, epsilon, ucA, vcA, ucB, vcB, dir_A, dir_B, T_inA_profile=None, T_inB_profile=None, max_iter=50000, tol=1e-6, progress_cb=None, return_info=False, Ta_init=None, Tb_init=None, Ts_init=None, dx_arr=None, dy_arr=None, inlet_mask_A=None, inlet_mask_B=None, Tb_prescribed=None, eps_A=None, eps_B=None, q_rel_tol=None, conv_chunk=None, use_sou_B=False)`（`sjtu_tpmshx/solvers/ltne_energy.py:608-625`）。返回 `(Ta, Tb, Ts)` 或加 info dict。调用方：`sjtu_tpmshx/pipelines/solve_2d.py:423,1058`、`sjtu_tpmshx/optimization/evaluator.py:560`、`sjtu_tpmshx/solvers/ltne_energy_3d.py:29`（Nz==1 委托）。

**ε 减半的确切位置（硬不变量）**：当 `eps_A is None and eps_B is None`（默认对称路径），`eps_f_arr = 0.5 * epsilon`（标量分支 `sjtu_tpmshx/solvers/ltne_energy.py:696`，数组分支 `:698-699`），且 `eps_fA_arr` 与 `eps_fB_arr` 指向**同一数组对象**以保证 δ=0 位一致（`:700-701`）。因此**调用方必须传全 ε**；把预先减半的值传入对称路径会二次减半（历史 bug，见仓库 CLAUDE.md 硬不变量）。

**eps_A/eps_B 私有 hook（非对称 δ 例外）**：注释明确「private hooks, NOT a public API」（`sjtu_tpmshx/solvers/ltne_energy.py:687-693`）。两者必须同时给出（`:703-704`），需满足 `eps_A + eps_B ≤ epsilon + 1e-9`（`:708-712`），核直接消费、**不再减半**（`:717-718`）。上游拆分在 `sjtu_tpmshx/solvers/asym_split.py`（2D 入口：`sjtu_tpmshx/pipelines/solve_2d.py:430,1070` 传入）。

其余要点：冷启动种子 Ta=T_inA、Tb=T_inB、Ts=0.5(T_inA+T_inB)（`sjtu_tpmshx/solvers/ltne_energy.py:766-768`，旧全场 mid-T 种子曾在 partial-inlet 冻结胞元上造成 ~12-18% Q_A 虚拟热源，`:758-765`）；`Tb_prescribed` 钉定水侧温度场（freeze_Tb=1，`:770-779`）；收敛为块式 AND 判据——每 `conv_chunk`（默认 500，`:815`）次 GS 扫掠后检查 Q_B 相对变化 < `q_tol = min(tol*2e-3, 1e-3)`（`q_rel_tol=None` 时，`:820`）且 max|ΔTa|,|ΔTb|,|ΔTs| < 0.01 K（`:821,856-861`），Q_cur = Σ h_vB·(Ts−Tb)·dA（`:845`）。

### GS 核 `_gs_full_chunk` / `_gs_full_chunk_rb`（`sjtu_tpmshx/solvers/ltne_energy.py:85` / `:368`）

- **`_gs_full_chunk`**（`@njit(cache=True)`，串行）：胞元耦合 GS，每胞元依次更新 Ta → Ts → Tb（`sjtu_tpmshx/solvers/ltne_energy.py:93`）；扫掠方向 i 随 bc_A、j 随 bc_B（`:121-131`）。A3（2026-07-06）保守化：上风基通量用带符号共享面通量 Fe = 0.5(F_P + F_E)，两侧胞元施加同一面通量从而全局望远镜求和；净流出**故意不加入 aP**（温度形式）——2D 胞元中心插值速度的离散 div(F) 非零，保留 net_out 会使均匀温度场不再是不动点（`:96-108`）。部分宽度入口胞元为数值正则化（frac>0.99 钉 T_in；0.01<frac<0.99 线性混合内邻点），非物理面通量 BC（`:163-186`）。内部收敛 break 阈值 max_chg < 1e-10（`:362-363`）。
- **`_gs_full_chunk_rb`**（`@njit(cache=True, parallel=True)`，`prange`）：红黑（i+j 奇偶）棋盘并行孪生核；同色胞元独立更新，2-away 的 SOU 模板读扫掠开始时的快照 `Ta_snap`/`Tb_snap`（唯一同色依赖，`:377-384,407-408,466-467,549-550`）。
- **核选择**：`_use_rb = _RB_ENERGY_2D and (Nx*Ny > _RB_ENERGY_2D_GATE)`（`sjtu_tpmshx/solvers/ltne_energy.py:828-829`）。`_RB_ENERGY_2D = False`（模块级默认关闭）、`_RB_ENERGY_2D_GATE = 30_000`（`:604-605`）——2D RB 核收敛场与串行可差 ~0.1 K（强对流工况），故默认串行；3D 对应开关默认开启（`:596-603`）。
- **SOU B 侧**：`sou_B` 门控（`solve_full_domain(use_sou_B=False)` 默认关），B 侧延迟修正即使在面一致望远镜形式下仍振荡（残差平台 ~1 K），默认关闭的精度代价 < 0.4% Q（`:109-117,322-333`）。

### threads（`sjtu_tpmshx/solvers/threads.py`）

`max_threads()`（`:23`，= `numba.config.NUMBA_NUM_THREADS`）；`get_solver_threads()`（`:29`）；`set_solver_threads(n)` 钳位 [1, max]（`:34-40`）；`init_from_env()` 读 `TPMSHX_NUM_THREADS`（`:43-52`），在 `sjtu_tpmshx/solvers/__init__.py:10` 包导入时调用一次。线程数对 Numba 全局生效，管辖所有 `parallel=True` 核（`sjtu_tpmshx/solvers/threads.py:15-16`）。

## 关键配置项与开关

| 配置 | 默认值 | 定义处 | 说明 |
|---|---|---|---|
| `massflux_inlet` | True（getattr 回退，非构造参数） | `sjtu_tpmshx/solvers/simple_solver.py:624,758` | 质量通量入口，硬不变量；护栏测试 `sjtu_tpmshx/tests/test_invariant_negative_guards.py:108-116` |
| `rho_inlet_ref` | None（→ 首解时从 rho_field[:,0] 捕获） | `sjtu_tpmshx/solvers/simple_solver.py:271,290-291,761-764` | 2D pipeline/validation 必须显式传入 |
| `fluid_type` | 'ideal_gas' | `sjtu_tpmshx/solvers/simple_solver.py:266` | 非 'ideal_gas' 时 `_update_density` 为 no-op（`:557-558`） |
| `alpha_rho` | 0.3 | `sjtu_tpmshx/solvers/simple_solver.py:270` | ρ 欠松弛 |
| `R_gas` | 287.05 J/(kg·K) | `sjtu_tpmshx/solvers/simple_solver.py:267` | 空气 |
| `wall_refine` / `n_wall_refine` / `wall_first_cell` | True / 8 / 0.02e-3 m | `sjtu_tpmshx/solvers/simple_solver.py:272-274` | 生产路径传 False（`:246-251`）；外部 2D 场或非全宽入出口时自动禁用（`:311-314`） |
| `cf_scale` | 1.0 | `sjtu_tpmshx/solvers/simple_solver.py:275,421-422` | sCO2 用流体相关 Forchheimer 标度 |
| `cf_aniso` | 0.0（实例属性） | `sjtu_tpmshx/solvers/simple_solver.py:440` | 斜流 Forchheimer 方向因子；0 时核跳过分支、位一致 |
| `solve()` 缺省 | max_iter=3000, tol=1e-6, alpha_u=0.7, alpha_p=0.3, n_inner=2, coupling='simple' | `sjtu_tpmshx/solvers/simple_solver.py:703-707` | |
| `enforce_outlet_mass_balance` | True（getattr） | `sjtu_tpmshx/solvers/simple_solver.py:981` | V&V 可关闭事后重标 |
| `lowre_early_exit` / `lowre_vel_tol` / `lowre_stall_window` / `lowre_stall_ratio` | True / 1e-4 / 30 / 1e-3（getattr） | `sjtu_tpmshx/solvers/_solve_common.py:53-56` | 2D min_iter=20（`sjtu_tpmshx/solvers/simple_solver.py:741`） |
| `_WALL_PENALTY_BASE` / `_WALL_PENALTY_EFOLD` | 1e3 / 1.5 | `sjtu_tpmshx/solvers/_kernels_simple_2d.py:155-156` | 编译期常量，2D/3D 共用 |
| `_RB_ENERGY_2D` / `_RB_ENERGY_2D_GATE` | False / 30_000 | `sjtu_tpmshx/solvers/ltne_energy.py:604-605` | 2D 红黑并行能量核默认关 |
| `solve_full_domain` 缺省 | max_iter=50000, tol=1e-6, use_sou_B=False, conv_chunk=None(→500), q_rel_tol=None(→min(tol·2e-3,1e-3)) | `sjtu_tpmshx/solvers/ltne_energy.py:617-625,815,820` | |
| `_CONV_TRACE` | None | `sjtu_tpmshx/solvers/ltne_energy.py:591` | 诊断用收敛轨迹，生产为零开销 |
| Anderson（仅 3D） | use_anderson=False, m=5, K=3 | `sjtu_tpmshx/solvers/simple_solver_3d.py:804-809`；类默认 `sjtu_tpmshx/solvers/anderson_acceleration.py:43` | |
| `TPMSHX_NUM_THREADS` / `NUMBA_NUM_THREADS` | 未设→Numba 默认 | `sjtu_tpmshx/solvers/threads.py:43-52,23-26` | 后者须在 Numba 初始化前设置 |

## 边界·假设·适用范围

- **单位**：K / Pa / m；但 TPMS 胞元尺寸 `L_cell_mm` 与壁厚 `t_mm` 为 **mm**（构造参数命名即注明，`sjtu_tpmshx/solvers/simple_solver.py:260`；`wall_first_cell` 为 m，`:274`）。
- **速度约定**：u、v 全程为 **interstitial（孔内平均）速度**，非 superficial；入口 BC `v_inlet = ṁ/(ρ·A_void)`，A_void = ε_f·A_total；D-F 面元的 K、cF 是已吸收 ε_f 因子的有效 interstitial 系数，不等于教科书 Darcy/Forchheimer 值（`sjtu_tpmshx/solvers/simple_solver.py:27-38`）。
- **可压缩为必需**：默认 ideal-gas ρ=P_abs/(R·T)（`sjtu_tpmshx/solvers/simple_solver.py:557-593`）；P_abs 运行包络裁剪 [1 kPa, 10 MPa]（`:579`）。2D 为入口锚定（高 Δp 抬升入口压力，罕见 choke）——3D 才是 choke 高发区（仓库 CLAUDE.md；本模块无 envelope 守卫代码，守卫在 `solvers/envelope.py`，本文件未核查其接线，标注：2D solve() 内未发现 envelope 调用，已核实 `sjtu_tpmshx/solvers/simple_solver.py:703-930` 无引用）。
- **网格**：交错网格，P (Nx,Ny) 胞元中心、u (Nx+1,Ny) x 面、v (Nx,Ny+1) y 面（`sjtu_tpmshx/solvers/simple_solver.py:24-25`）；支持非均匀 dx_arr/dy_arr，核直接消费 1D 逐胞元数组（`sjtu_tpmshx/solvers/simple_solver.py:182-185`）。主流方向为 +y（入口 j=0，出口 j=Ny）。
- **数值格式**：一阶上风 + MINMOD SOU 延迟修正（动量与能量）；压力方程为稀疏直接解（scipy spsolve），非迭代；能量为胞元耦合 GS。
- **离散一致性代价**：LTNE 温度形式（net_out 不入 aP）以保均匀温度场不动点为先（`sjtu_tpmshx/solvers/ltne_energy.py:101-108`）；空间变 ε 时 interstitial 形式与均质化 BFNS 推导有偏差（B5 台账结论，`sjtu_tpmshx/solvers/simple_solver.py:34-38`），M2 已在动量核加入 VANS ε-ratio 面因子部分弥合（`sjtu_tpmshx/solvers/_kernels_simple_2d.py:204-211`）。
- **`_check_uniform` 阈值** 0.045（4.5%，≈ HX 教科书 5% 标准，`sjtu_tpmshx/solvers/simple_solver.py:1057,1087`）。

## 可扩展接口

- **`eps_A` / `eps_B` 私有 hook**（`sjtu_tpmshx/solvers/ltne_energy.py:624,687-718`）：非对称 offset-isosurface δ 的唯一进入方式；上游拆分 `sjtu_tpmshx/solvers/asym_split.py`，pipeline 入口 `sjtu_tpmshx/pipelines/solve_2d.py:430,1070`。
- **`set_K_cF_field(K2d, cF2d)`**（`sjtu_tpmshx/solvers/simple_solver.py:684`）：每胞元 (Nx,Ny) D-F override，供 port-BC 路由研究横向变阻力；1D `_K_arr` 对非核消费者（种子/诊断）保持权威（`:429-434`）。
- **`cf_aniso` 实例属性**（`sjtu_tpmshx/solvers/simple_solver.py:440`）：斜流方向因子标定入口（validation/cf_aniso），默认 0 位一致。
- **`coupling='simpler'` + `simpler_relax_p`**（`sjtu_tpmshx/solvers/simple_solver.py:711-722`）：实验性 SIMPLER 耦合；ρ(P) 反馈振荡时的松弛回退 hook。
- **`Tb_prescribed`**（`sjtu_tpmshx/solvers/ltne_energy.py:648-653,770-779`）：钉定实测水侧温度场做验证。
- **`use_sou_B` / `sou_B`**（`sjtu_tpmshx/solvers/ltne_energy.py:625,329-333`）：B 侧 SOU kill switch，默认关。
- **`_RB_ENERGY_2D` 模块级开关**（`sjtu_tpmshx/solvers/ltne_energy.py:604`）：大 2D 网格显式启用红黑并行能量核。
- **`q_rel_tol` / `conv_chunk`**（`sjtu_tpmshx/solvers/ltne_energy.py:628-636`）：早停调优（设计工具用 1e-4 级）。
- **`progress_cb`**：2D SIMPLE 每 20 迭代回调 (it, res)（`sjtu_tpmshx/solvers/simple_solver.py:885-891`）；LTNE 每 chunk 回调 (done, max_iter)（`sjtu_tpmshx/solvers/ltne_energy.py:842-843`）。
- **Anderson（2D 预留）**：`AndersonSIMPLE` 与 `stack_state` 按 3D 四分量 (u,v,w,P) 设计（`sjtu_tpmshx/solvers/anderson_acceleration.py:129-138`）；2D 若接入需自行组装状态向量并遵守「每 Anderson 步后重投影」契约（`:7-14`）。
- **env 变量**：`TPMSHX_NUM_THREADS`（运行时线程数，`sjtu_tpmshx/solvers/threads.py:43-52`）、`NUMBA_NUM_THREADS`（硬上限，须先于 Numba 初始化）、`TPMSHX_DF_METHOD=rbf`（DF surrogate 后端切换，注释提及 `sjtu_tpmshx/solvers/_kernels_simple_2d.py:166-168`，实现在 df_surrogate/predict.py，本文档未核查该实现）。
- **`build_inlet_stretched_1d`**（`sjtu_tpmshx/solvers/simple_solver.py:172`）：opt-in 流向渐变网格，未接入默认路径但核已兼容非均匀 dx_arr（`:182-185`）。
- **`enforce_outlet_mass_balance = False`**（`sjtu_tpmshx/solvers/simple_solver.py:977-981`）：V&V 关闭事后质量重标。

## 已知不足与 TODO

目标文件内无 TODO/FIXME/NotImplementedError 标记（grep 已核实，7 个文件零命中）。代码注释中记录的已知限制：

1. **B 侧 SOU 固有振荡**：即使面一致望远镜形式，B 侧延迟修正在近等温高 rho_cp 场上残差平台 ~1 K、串行/红黑不动点差 ~0.4 K，默认关闭（`sjtu_tpmshx/solvers/ltne_energy.py:109-117`）。
2. **2D RB 能量核默认关**：RB 收敛场与串行差 ~0.1 K（强对流），且 2D 网格通常低于门槛（`sjtu_tpmshx/solvers/ltne_energy.py:594-604`）。
3. **partial-inlet 温度 BC 是数值正则化**：部分开口胞元 T 由线性混合给出，带内邻点小偏差；注释给出了改写为严格面通量 BC 的路线（`sjtu_tpmshx/solvers/ltne_energy.py:163-171`）。
4. **空间变 ε 的 interstitial 形式偏差**（B5）：对流与 Laplacian 算子在非均匀 ε_f 下偏离均质化 BFNS 推导，扩展 zoned-TPMS 前须复核（`sjtu_tpmshx/solvers/simple_solver.py:34-38`）。
5. **SIMPLER 实验性**：partial-BC 配置未基准（`sjtu_tpmshx/solvers/simple_solver.py:716-718`）。
6. **`_enforce_mass_conservation` 属事后重标**：|scale−1| > 1e-3 提示 pp 方程出口面残差偏松，应收紧 tol 而非依赖重标（`sjtu_tpmshx/solvers/simple_solver.py:973-976`）。
7. **partial-outlet 0.01<frac≤0.5 胞元语义不一致**（已审计为良性）：pp 方程钉压而 v 扫掠视为墙，靠 `_correct_jit` 无条件重写 v[i,Ny] 兜底（`sjtu_tpmshx/solvers/_kernels_simple_2d.py:721-733`）。
8. **Anderson 未接入 2D**：仅 3D 且默认关闭（`sjtu_tpmshx/solvers/simple_solver_3d.py:804-809`）。
9. **legacy `closure` kwarg** 被静默吞掉（`sjtu_tpmshx/solvers/simple_solver.py:277-279`）——移植时不要依赖它。
10. **rho_inlet_ref=None 回退陷阱**：求解器每外迭代重建 + 入口压力基准时目标会棘轮漂移（`sjtu_tpmshx/solvers/simple_solver.py:283-289`）。

## 服务器移植注意

- **Numba JIT 缓存**：所有核为 `@njit(cache=True)`；缓存目录（源码目录旁 `__pycache__`）必须可写，否则每进程冷编译（首个真实调用 ~15-60 s，`sjtu_tpmshx/solvers/ltne_energy.py:878-881`）。`simple_solver.py` 与 `ltne_energy.py` 在**模块导入时**各执行一次 `_warmup_jit()` 预编译（`sjtu_tpmshx/solvers/simple_solver.py:1354,1382`；`sjtu_tpmshx/solvers/ltne_energy.py:875,920`），失败静默吞掉、不阻塞导入。
- **线程控制**：`NUMBA_NUM_THREADS` 必须在 Numba 初始化前于 shell/launcher 设定（硬上限，`sjtu_tpmshx/solvers/threads.py:6-8`）；`TPMSHX_NUM_THREADS` 在 `solvers` 包导入时应用（`sjtu_tpmshx/solvers/__init__.py:10`）。线程数全局生效于所有 `parallel=True` 核。注意 2D 能量核默认走串行 `_gs_full_chunk`（`_RB_ENERGY_2D=False`），多核对本模块 2D 路径收益有限。
- **导入路径假设**：`simple_solver.py` 顶层 `from df_surrogate.predict import predict_K_cF, predict_K_cF_vec`（`sjtu_tpmshx/solvers/simple_solver.py:43`）与 `from logutil import get_logger`（`:47`）都是**顶层包/模块导入**——`sjtu_tpmshx/` 目录本身必须在 sys.path 上（包内相对导入与顶层导入混用），移植时不能简单 `pip install` 成独立包而不处理该布局。
- **依赖**：numpy、numba、scipy（`sparse` + `spsolve`，即 SuperLU；`sjtu_tpmshx/solvers/_kernels_simple_2d.py:687-688`）。压力方程是稀疏直接解，大网格内存随 Nx·Ny 增长，服务器上超大 2D 网格需留意 spsolve 填充内存。
- **确定性/golden 门**：`_solve_common.py` 明确「纯 Python、无 numba/fastmath、位一致契约」（`sjtu_tpmshx/solvers/_solve_common.py:9-13`）；本仓库 golden 门要求 `PYTHONHASHSEED=0`（仓库约定，见 `.claude/commands/check.md`；本文件层面未验证其作用机理）。移植目标为 Windows Server 2022（与开发机同为 Windows），但「同 OS」不等于「同二进制环境」：若服务器上的 BLAS 版本或 CPU 微架构（AVX2/AVX-512 等指令集，影响 SIMD 向量化路径）与开发机不同，`spsolve`/numba 浮点结果的位一致性**未验证**——golden 基线在 Windows 开发机上建立，跨机器复跑前不要假设逐位相同（应先用数值容差比对，必要时在服务器上重新钉基线，而非直接复用开发机的 golden CSV 做 bit-identical 断言）。
- **无人值守 / 无显示器运行**（原「平台无关性」一条：因移植目标已从 Linux 改为同为 Windows 的 Server 2022，「无 Windows 专属路径」这类跨 OS 对比已不适用，故删除，改述服务器上实际相关的风险点）：本模块 7 个文件（Read/Grep 复核）无直接文件 I/O、代码中无 `encoding=` 假设；日志经 `logutil.get_logger`——handler 直写 `sys.stdout` 且格式串固定为纯消息文本（`sjtu_tpmshx/logutil.py:76`），7 个文件内 grep 中文字符零命中，故日志内容为 ASCII，不受 Windows Server 中文区域设置下 GBK/CP936 默认代码页影响（该编码坑在本模块范围内不成立；仓库其他模块若有中文日志/文件读写仍需按仓库备忘单独核查）。GUI 依赖仅为单向反向调用：`sjtu_tpmshx/ui/builders_domain.py:277-310` 调用本模块的 `set_solver_threads`，本模块自身不 import 任何 Qt/PySide 符号（grep 复核零命中），在 Server Core 等无交互式桌面会话的环境下可直接后台运行，无需 `QT_QPA_PLATFORM=offscreen` 之类的 Qt 平台插件配置（那是 `ui/` 模块的关注点，不在本文档范围）。数据文件（data/raw_data 等 gitignored 大文件）不被本模块直接读取，但上游 `df_surrogate.predict` 的标定链可能依赖（本文档未核查；worktree 缺该数据时 DF 标定可能回退 CSV，见仓库备忘）。
- **测试锚点**：`sjtu_tpmshx/tests/test_invariant_negative_guards.py`（massflux 默认 ON 护栏）、`test_a3_conservative_ltne_2d.py`（GS 核）、`test_asym_porosity_2d.py`（eps_A/eps_B hook）、`test_simpler_coupling_2d.py`、`test_m2_vans_eps_momentum.py`、`test_inlet_taper_mass.py`、`test_solver_threads.py`、`test_anderson_simple.py`。
