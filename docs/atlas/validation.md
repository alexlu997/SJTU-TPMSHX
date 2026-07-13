# validation

生成日期 2026-07-11，基于 commit f33d30e 附近的 master

## 定位与功能

`sjtu_tpmshx/validation/` 是求解器的 V&V（Verification & Validation）子系统，职责分两类：

1. **Validation（对标实验）**：将求解器预测的 Δp / Q 与上海电气（Shanghai Electric）16 工况实验台账比对，产出 RMSRE 等误差统计，并为 CI/pytest 提供可重复的数值门禁（gate）。核心入口 `cases/validate_shanghai_3d_real.py` 是 CLAUDE.md 明确指定的"代理后端变更"门禁脚本。
2. **Verification（数值方法自证）**：MMS（Method of Manufactured Solutions，`cases/mms_*`）、ASME V&V 20 Phase C 的 Roache GCI 网格收敛（`cases/phase_c_gci.py`）、3D LTNE 守恒律 / 二热力学定律审计（`cases/audit_3d_conservation.py`）、以及斜流各向异性 Forchheimer 系数标定工单（`cf_aniso/`）。

`harness/` 是被多个 case 脚本共享的基础设施（规格对象、Excel 加载、误差指标、CSV 溯源头、log-log 阶数拟合、网格扫描循环），`_CSV_STATUS.md` 是本目录下所有 Shanghai CSV 产物的"单一数字真源"索引——任何引用 CSV 里数字前必须先查它。

## 文件一览

| 路径 | 职责 |
|---|---|
| `validation/README.md` | 人类可读的入口索引：canonical baseline 表、复现清单、legacy 目录说明 |
| `validation/_CSV_STATUS.md` | Shanghai 3D CSV 产物的数字溯源表——哪个 CSV 对应哪个"时代"(era)/哪次修复，哪些已过时 |
| `validation/chi_s_homogenization.csv` | χ_s(拓扑, t/L) 单胞均质化拟合表（B2 工单产物），被 `solvers/tpms_props.chi_s_eff` 消费（本模块外） |
| `validation/mms_phase_a3_*.csv(.meta.json)` | Phase A.3 h-加密 MMS 原始误差 + 拟合阶数（`_provenance` 写出，含 sidecar meta） |
| `validation/mms_phase_a4_*.csv(.meta.json)` | Phase A.4 边界分区 MMS 误差 + 拟合阶数 |
| `validation/mms_phase_b4_orders.csv` | Phase B4 守恒型（conservative）高阶核的观测阶数 |
| `validation/phase_c_gci*.csv(.meta.json)` | Phase C Roache GCI 结果 + tol 扫描 |
| `validation/shanghai_3d_baseline*.csv` | 历次 Shanghai 3D 门禁跑的 dP/Q 原始逐工况结果（无 provenance header，见下方"已知不足"） |
| `harness/_harness.py` | `SpecimenSpec`（冻结 dataclass，几何派生量 eps/eps_A/D_h/A_0）+ `load_cases_df`（Excel 工况表统一加载） |
| `harness/_case_sets.py` | 具体样本规格工厂：`shanghai_spec()` / `d76_spec()`，以及 Excel 路径常量 `SHANGHAI_XLSX` / `D76_XLSX` |
| `harness/_metrics.py` | `rmsre_from_pct` / `err_stats_pct` —— 误差统计公式的唯一实现 |
| `harness/_mms_driver.py` | `run_grid_sequence`：MMS 多网格扫描的公共计时循环骨架 |
| `harness/_order_fit.py` | `fit_order_loglog`：log-log 最小二乘拟合观测阶数 p_obs（4 个历史实现的统一版本） |
| `harness/_provenance.py` | CSV 溯源头（`# script/commit/date` 注释行 + `.meta.json` sidecar）读写工具 |
| `cases/validate_shanghai_3d_real.py` | **生产门禁脚本**：Shanghai 16 工况 3D SIMPLE+LTNE 验证，含 CLI 门禁（exit code） |
| `cases/validate_shanghai_aligned.py` | Shanghai 2D 验证，与 UI `run_calculation.py` 逐步对齐（`if __name__` 守卫仅包住工况循环/SIMPLE 求解/xlsx 写出——见下方"边界·假设"，import 时仍执行 stdout 重编码 + 粗糙度模式打印） |
| `cases/validate_shanghai_lumped_dual_nu.py` | 论文 baseline：集总参数 ε-NTU + 双侧 Nu 相关式的前向预测（不泄漏 T_out） |
| `cases/mms_3d_air_air.py` | Phase A.2 单网格 MMS 核心：sympy 符号推导流形解 + 直接驱动 3D LTNE 核 `_gs_full_chunk_3d_stag` |
| `cases/mms_phase_a3_h_refine.py` | Phase A.3：5 网格 h-加密，拟合观测阶数 p_obs，硬门禁 |
| `cases/mms_phase_a4_boundary.py` | Phase A.4：按入口/出口/侧壁/内部分区统计误差与阶数，硬门禁 |
| `cases/mms_phase_b4_order.py` | Phase B4：守恒型（`conservative=1`）高阶核的阶数验证 |
| `cases/phase_c_gci.py` | Phase C：Roache GCI（C.1）+ 迭代收敛审计（C.2）+ tol 敏感性（C.3），驱动生产管线 `pipelines.stages_3d._run_3d_stack` |
| `cases/audit_3d_conservation.py` | 只读诊断：6 个合成测试拓扑（T1-T6 全面/偏置/隔离等）+ Phase 2a/2c/3/4/5（一/二热力学定律、质量守恒、边界通量），无硬 CLI 门禁默认但含内部 assert |
| `cases/audit_partial_b_ltne.py` | **归档性质**只读一次性审计（partial-B LTNE P1-P7），问题已于 2026-05-14 修复，仅作历史参考 |
| `cases/verify_pareto_3d.py` | 独立 3D 复核：把优化器 2D Pareto 解的 L(x,y)/t(x,y) 场沿 z 挤出，跑 3D 全栈校验 Q/dP 偏差 |
| `cf_aniso/README.md` | 斜流 Forchheimer 方向因子标定工单说明（中文，工单尚未完成，`cf_aniso` 系数仍默认 0） |
| `cf_aniso/fit_cf_aniso.py` | 方向分辨单胞 CFD 结果 → `cf_aniso` 系数拟合脚本（读取用户提供的 results.csv，非 gitignored 数据） |
| `cf_aniso/results_template.csv` | 拟合脚本期望的输入列模板（尚未填充实验/CFD 数据） |

## 公开接口

- `validate_shanghai_3d_real.main()` — CLI 入口。关键参数：`--runner {kernel,pipeline}`（**默认 `pipeline`，2026-07-12 起** —— 本卷旧文曾记"默认 kernel"，已过期）、`--nx/--ny/--nz`（默认 20/10/3）、`--gate-dp`（默认 12.0）、`--gate-q`（默认 6.0）、`--no-gate`。返回 `1`（gate fail）或 `0`。
- `_run_one_case(ci, df, Nx_u, Ny_u, Nz_u, ...)` — kernel-direct 跑法主体（水侧冻结 `Tb_prescribed`）。**2026-07-12 起不再是门禁 runner**，经 `--runner kernel` 保留以复现冻结水侧时代数字（5.28/3.21）。
- `_run_one_case_pipeline(ci, df, Nx_u, Ny_u, Nz_u, ...)` — 生产路径跑法（`ComputeConfig` → `Pipeline3D`，水侧真实求解）。**2026-07-12 起是 gate runner（默认）**，门禁值 4.88/2.12（F2 默认下）。CSV 后缀逻辑随之反转：现在 **kernel** 侧输出加 `_kernel` 后缀，pipeline 输出写 canonical 名。
- `shanghai_spec() -> SpecimenSpec` / `d76_spec() -> SpecimenSpec` — 规格工厂，`sjtu_tpmshx/validation/harness/_case_sets.py:27,48`。调用方：`validate_shanghai_3d_real.py`（顶层 `SPEC = shanghai_spec()`）、`validate_shanghai_aligned.py`（经 `ComputeConfig` 间接引用相同基线）。
- `SpecimenSpec`（frozen dataclass）— `sjtu_tpmshx/validation/harness/_harness.py:22`；`__post_init__`（`_harness.py:45`）用 `solvers.tpms_calc.geometry` 派生 `eps/eps_A/D_h/r_h/A_0`，callers 永不自行重算这些派生量。
- `load_cases_df(xlsx_path) -> pd.DataFrame` — 统一 Excel 工况表加载（`sheet_name='Sheet1', header=None, skiprows=2`，纯位置 `iloc` 访问），`sjtu_tpmshx/validation/harness/_harness.py:55`。调用方：所有 Shanghai/D76 case 脚本。
- `rmsre_from_pct(err_pct) -> float` / `err_stats_pct(err_pct) -> (rmsre, bias, max_abs)` — `sjtu_tpmshx/validation/harness/_metrics.py:23,32`。调用方：`validate_shanghai_3d_real.py:628`、`validate_shanghai_lumped_dual_nu.py:274`、`validate_shanghai_aligned.py:365`。
- `fit_order_loglog(h_arr, err_arr, *, err_floor=0.0, min_points=2) -> OrderFitResult` — `sjtu_tpmshx/validation/harness/_order_fit.py:34`。调用方：`mms_phase_a3_h_refine.py`、`mms_phase_a4_boundary.py`、`mms_phase_b4_order.py`、`phase_c_gci.py:58`。
- `run_grid_sequence(grids, run_case, row_builder, *, on_grid=None) -> list[dict]` — `sjtu_tpmshx/validation/harness/_mms_driver.py:18`。调用方：三个 MMS phase 脚本；被 `tests/test_mms_driver.py` 直接测试（未验证：本次未读该测试文件的具体断言）。
- `write_csv_with_provenance(df, path, script, ...)` / `read_csv_with_provenance(path)` / `backfill_provenance(path, script, ...)` — `sjtu_tpmshx/validation/harness/_provenance.py:94,171,129`。调用方：`mms_phase_a3/a4` 写 CSV 时使用；**`validate_shanghai_3d_real.py:655` 没有使用它**（直接 `pd.DataFrame(results).to_csv`），因此 `shanghai_3d_baseline*.csv` 没有 `.meta.json` sidecar（已用 `ls` 核实，见"已知不足"）。
- `run_mms(case, Nx, Ny, Nz, ...) -> dict` — Phase A.2 MMS 核心求解入口，`sjtu_tpmshx/validation/cases/mms_3d_air_air.py:159`。返回字典含 `L2_A/B/s`、`Linf_A/B/s`、`converged`、数值场本身。调用方：`mms_phase_a3_h_refine.py`、`mms_phase_a4_boundary.py`、`mms_phase_b4_order.py`。
- `_run_3d_stack(cfg) -> dict` — **不在本模块内**（定义于 `pipelines/stages_3d.py`，未在本次审阅范围），但 `audit_3d_conservation.py:51`、`audit_partial_b_ltne.py:46`、`phase_c_gci.py:43` 均直接调用它驱动生产管线，是本模块与生产代码的主要耦合点。
- `evaluate_3d(x_decision, cfg, Nx, Ny, Nz, Lz) -> dict` — **不在本模块内**（定义于 `core/evaluators.py`），`verify_pareto_3d.py:47-50` 导入使用，返回 `Q_3D_W/dP_A_Pa/dP_B_Pa/dP_total_Pa/mass_kg`。
- `fit_cf_aniso.main(path)` — `sjtu_tpmshx/validation/cf_aniso/fit_cf_aniso.py:34`。CLI：`python fit_cf_aniso.py results.csv`，输出每 (拓扑,L,t,θ) 的 K/cF、K 各向同性核验、`cf_aniso` 系数拟合（未接入生产代码，产出仅打印到 stdout）。

## 关键配置项与开关

- `--runner {kernel,pipeline}`，**默认 `pipeline`（2026-07-12 起）** — gate runner = 生产 `Pipeline3D` 双求解路径（水侧真解、F2 收敛默认）；`kernel` 保留复现冻结水侧时代数字。本卷旧文（"默认 kernel、pipeline 不参与门禁数值"）随 gate 切换作废。
- `--gate-dp` 默认 `12.0`，`--gate-q` 默认 `6.0`。阈值刻意宽松（当前 Nz=3 门禁实测 RMSRE_dP≈4.88% / RMSRE_Q≈2.12%，F2 默认；kernel 时代为 5.28/3.21），只拦截"数量级级别"的代理后端回归，不拦截调参噪声。
- `--nx/--ny/--nz` 默认 `20/10/3` — `validate_shanghai_3d_real.py:546-548`；Nz=3 是速度优化的门禁网格（非网格收敛网格），网格收敛研究见 `_CSV_STATUS.md` 的 A1 行（Nz 更大时 dP 误差会上升到 ≈10%）。
- `--max-outer` 默认 `MAX_OUTER=4` — `validate_shanghai_3d_real.py:72,555`；SIMPLE↔LTNE 外层耦合迭代数，比 2D 版本（`validate_shanghai_aligned.py:52` `_MAX_COUPLING=10`，非 8）少（3D 求解更慢）。`OUTER_TOL=0.5`（K）、`ALPHA_T=0.6` 同一处定义（`:73-74`）。
- `pytest` 侧门禁：`tests/test_shanghai_regression.py::test_shanghai_3d_baseline` 通过子进程调用 `validate_shanghai_3d_real`（`--suffix _pytest_h3`），断言 `BASELINE_DP=4.88`（容差 ±5%）、`BASELINE_Q=2.12`（容差 ±10%）——2026-07-13 随 F2 默认重基线（切换史：5.28/3.21 冻结水侧 → 4.93/2.12 管线化 → 4.88/2.12 F2）。该测试默认跳过，需 `TPMSHX_RUN_SHANGHAI_REGRESSION=1` 才运行。
- `TPMSHX_DF_METHOD=rbf` — 环境变量，切换 D-F 代理后端为 rbf 参考路径（默认 `gamma_df`）；`_CSV_STATUS.md` 记录 rbf 参考值 Nz=3 dP 7.19%/Q 3.22%，Nz=10 dP 8.69%/Q 3.33%（未在本模块代码内定义该环境变量的读取点，读取逻辑在 `df_surrogate/` 内，未验证具体 file:line）。
- `--disp-c` 默认 `0.0` — B4 热弥散系数敏感性旋钮，`K_ff += C·ρ·cp·|u|·D_h`，`validate_shanghai_3d_real.py:217-223,543-545`；`0.0` = 生产行为（研究台账结论：C_DISP=0 是正确值，见用户 memory，未在本次代码审阅中复核）。
- `--profile {uniform,parabolic,edge}` + `--eta` — 入口速度剖面形状敏感性分析旋钮，`validate_shanghai_3d_real.py:132-165,551-554`；默认 `uniform, eta=0.0`（生产行为）。
- `envelope_mode` — **不在本文件内定义**（`solvers/envelope.py`），但 `_run_one_case` 的 `pressure_state_valid` 字段（`validate_shanghai_3d_real.py:455-457`）依赖该守护是否触发过 P_abs clip；RMSRE 统计口径显式排除 `pressure_state_valid=False` 的工况（`:609-625`），并把排除列表打印出来（不静默丢弃）。
- `resolve_mode_from_env()`（来自 `solvers/roughness.py`）— 粗糙度修正模式（baseline / norris_1a / bhatti_shah_1b），`validate_shanghai_3d_real.py:235`、`validate_shanghai_aligned.py:41`；默认 `baseline`（未在本次审阅中确认默认值来源 file:line，标记未验证）。
- `TPMSHX_SIMPLE_TOL` — 环境变量，`phase_c_gci.py` 的 C.3 tol 敏感性扫描通过 `_patched_env` 临时覆写，扫描值 `{1e-3, 1e-5, 1e-7}`，门禁 `range/|Q_finest| < 1%`。**2026-07-13 起该扫描显式钉 `convergence_mode='legacy'`**（env + cfg 双保险）：f2 默认下 `tol_simple` 不参与退出判定，三档会逐位相同、"饱和"变空洞通过；f2 侧的对应证据是 `reports/f2_pricing_3d.csv` 的 `mom_tol` 分档。

## 边界·假设·适用范围

- **单位**：几何 `L_cell_mm`/`t_wall_mm` 为 mm，其余（域尺寸 `L_dom_m` 等）为 SI（m/K/Pa）——与仓库总约定一致。
- **实验工况表列约定（硬编码位置）**：`validate_shanghai_3d_real.py` 用纯位置 `df.iloc[ci, N]` 读取 Excel 列（如 `m_air=col5`, `T_Ain_C=col28`, `P_Ain_g=col30`, `P_Aout_g=col31`, `Q_exp=col33`, `T_Bin_C=col24`, `T_Bout_C=col25`, `m_water=col7`），`validate_shanghai_3d_real.py:190-208`。**这些列号没有名字，Excel 表结构一旦改动（插列/换 sheet）会静默读错数据而不报错**——移植时必须先核对目标 Excel 是否列结构一致。
- **水侧冻结只存在于 kernel 跑法**：`_run_one_case`（`--runner kernel`，**非门禁**）不解水侧 SIMPLE，只用 `Tb_prescribed` 沿流向线性插值；**门禁（默认 pipeline）水侧真实求解**——2026-07-12 起本条与旧文相反。
- **RMSRE 统计口径排除"压力无效"工况**：`pressure_state_valid` 要求全场 `1e3 Pa ≤ P_abs ≤ 10e6 Pa`（`validate_shanghai_3d_real.py:455-457`）；若全部工况都被判无效，代码会退回全量统计但打印不可信标记（`:619-625`）。
- **Re>600 过滤逻辑存在但未在当前代码路径实际生效**：注释提到"2D 惯例"的 Re 过滤（`validate_shanghai_3d_real.py:616`），但 `u_arr` 计算之后未见到实际按 Re 过滤 case 的代码——**未验证/存疑**，需要在具体 diff 中确认是否只是历史注释残留。
- **`audit_partial_b_ltne.py` 是归档快照**：脚本头部明确写"ARCHIVAL... not for routine CI runs"（`audit_partial_b_ltne.py:3-7`），诊断的问题已于 2026-05-14（closure 默认改 'none'）及 commit `02f091c`（ε 双重减半修复）解决，保留仅供历史参考，不应作为当前行为的证据来源。
- **D_7_6 相关脚本已不在本目录**：`d76_spec()` 仍在 `harness/_case_sets.py:48` 定义并引用 `D76_XLSX`（`20260609-水直空气侧-D_7_6.xlsx`），但驱动脚本 `validate_d76_3d.py` 实际位于 `sjtu_tpmshx/runs/archive/validate_d76_3d.py`（不在 `validation/` 内），`D76_EXCLUDE = frozenset({11})` 记录了工况 11 因传感器数据重复而被排除在 dP 门禁外（`harness/_case_sets.py:23-24`）。
- **cf_aniso 工单尚未完成**：`cf_aniso/README.md` 与 `fit_cf_aniso.py` 是"待填充"的标定工作流——`results_template.csv` 已预填 45 行算例矩阵（拓扑/L/t/θ/u_sup）但 CFD 实测列（dP/L、ρ、μ）无数据，`cf_aniso` 系数在生产代码（`optimization/evaluator.py` 的 `DEFAULT_CONFIG['cf_aniso']`，不在本模块内）仍默认 0；本次未验证该默认值当前是否仍为 0（README 写"值本身仍默认 0"，属于文档断言，未在生产代码中核实 file:line）。
- **MMS 硬门禁的精度期望按边界区域分层**：入口（Dirichlet）要求 `L2 < 1e-12`（机器精度级），出口（Neumann，一阶单侧差分）只要求 `p_obs ≥ 0.8`，内部要求 `p_obs ≥ 1.8`（`mms_phase_a4_boundary.py:20-25,182-230`）——这是数值方法本身的阶数上限，不是求解器 bug。

## 可扩展接口

- **hooks / 私有 kwargs**：`_run_one_case(..., disp_c=0.0)` 的热弥散旋钮（`validate_shanghai_3d_real.py:170,217-223`）；`_build_inlet_profile(..., kind='uniform', eta=0.0)` 的入口剖面形状钩子（`:132-165`），支持 `'parabolic'`/`'edge'`。
- **backend 注册点（间接）**：`predict_K_cF`（`df_surrogate/predict.py`，不在本模块）通过 `TPMSHX_DF_METHOD` 环境变量切换 `gamma_df`/`rbf` 后端；本模块的门禁脚本对此透明（不感知具体后端选择逻辑），只是消费返回的 `(K, cF)`。
- **env 变量**：`TPMSHX_RUN_SHANGHAI_REGRESSION`（pytest 侧门禁开关）、`TPMSHX_2D_MASSFLUX`（`validate_shanghai_aligned.py:131`，`0` 回退到 legacy 速度入口 BC 用于对比）、`TPMSHX_DF_METHOD`、`TPMSHX_SIMPLE_TOL`、`TPMSHX_DF_RESIDUAL_CORR=1`（README 提到的 `posthoc_residual_correction.py` 开关，**该脚本本次未在磁盘上找到**，标记存疑——`validation/README.md:33` 提及但实际目录 listing 中不存在此文件，可能已删除或改名而 README 未同步）。
- **预留分支 / closure 变体**：`audit_3d_conservation.py` 的 `CASES` 字典（`:323-333`）预留了大量 `partial_B_closure` 变体（`per_cell_chi_b` + `velocity_threshold`/`mass_flux_threshold`，各种 threshold/dilate/smooth 组合）供敏感性研究，是这些 closure 机制的活文档（比生产代码里的默认值更全面地展示了参数空间）。
- **`_run_one_case_pipeline` 作为生产路径的独立复核通道**：刻意设计为与 kernel runner 不同物理路径（真实水侧 SIMPLE vs 冻结 Tb），供"生产路径是否与门禁路径系统性偏离"的检验，`validate_shanghai_3d_real.py:467-471` 注释明确"Do not silently swap the gate"。

## 已知不足与 TODO

- **`shanghai_3d_baseline*.csv` 缺 provenance header**：`harness/_provenance.py` 提供了 `write_csv_with_provenance`，但 `validate_shanghai_3d_real.py:655` 直接用 `pd.DataFrame(results).to_csv(...)`，未接入溯源机制——已用 `ls`/`cat` 核实这些 CSV 没有 `.meta.json` sidecar 也没有 `# script:` 头（对比 `mms_phase_a3_h_refine.csv` 等有 sidecar）。这与 `README.md:63` 记录的"Future fix (P1): write commit sha + script version into CSV header"待办一致，尚未落地。
- **`_CSV_STATUS.md` 记录的"Re>600 过滤"注释与代码不完全对应**：见上文"边界·假设"一节，`validate_shanghai_3d_real.py:616-617` 只构造了 `u_arr` 但未见后续按此过滤 RMSRE 计算的分支——**未验证**，需要读 git blame 或更早版本确认这是否已被移除的死代码。
- **`README.md` 提到的 `validate_chi_b_subset.py` 与 `posthoc_residual_correction.py` 在当前 `validation/` 目录树中不存在**（`Bash find` 已核实）——README 索引与实际文件树存在漂移，属于文档维护债务。
- **`audit_partial_b_ltne.py` 属于一次性归档脚本**，理论上应移到类似 `legacy/` 或 `runs/archive/` 的位置（`validate_d76_3d.py` 已经这样处理），但目前仍留在 `cases/` 目录下与生产门禁脚本混放，容易被误当作活跃维护的验证入口。
- **`fit_cf_aniso.py` 的方向分辨 CFD 数据尚未采集**（`cf_aniso/results_template.csv` 已预填 45 行算例矩阵 `case_id/tpms/L_mm/t_mm/theta_deg/u_sup_mps`，但 CFD 实测列 `dpdl_Pa_per_m/rho_kg_m3/mu_Pa_s` 全为空——不是"只有表头"），工单处于"机制已实装、系数未标定"状态（README 自述）；`cf_aniso` 系数默认值 0 是否已在 `optimization/evaluator.py` 落地，本次审阅范围（仅 `validation/`）未验证。
- **`audit_3d_conservation.py` 中 H8（`mass_flux_threshold`）closure 的 max-ref 模式存在已知的按网格调参问题**：代码注释坦承"Max-ref needs per-grid tune for offset partial-B... a robust auto-detect is needed (TODO future work)"（`audit_3d_conservation.py:256-267`），且 percentile-ref 方案（p75）曾导致 T2_H8 出现 `S_gen<0`（违反二热力学定律）而被放弃——这是明确记录在代码注释里的未解决 TODO。
- **`mms_phase_a4_boundary.py` 的 Phase A.3 观测**：全局 L2 阶数 ~2.1，但这是"流形解在所有边界处零梯度"这一构造巧合下的结果（`mms_3d_air_air.py:28-34` 用 cos 函数使 Neumann 边界自动满足），A.4 特意把边界拆开验证是否真的达到方法学预期的分区阶数——出口一阶单侧差分被有意允许只达到 `p_obs≥0.8`，不是 bug。

## 服务器移植注意

（目标平台核实为 **Windows Server 2022**，不是 Linux——先前撰写本节时对移植目标有误判，以下逐条按代码事实重新核对。）

- **GBK 编码坑：不会因为"迁移到服务器"而消失，是持续生效的真实风险**（原判断方向有误，已反向修正）——`sys.stdout.reconfigure(encoding='utf-8')` 在 `cases/*.py` 全覆盖（已逐个 grep 核实）：`validate_shanghai_3d_real.py:25`、`validate_shanghai_aligned.py:24`、`validate_shanghai_lumped_dual_nu.py:104`、`audit_3d_conservation.py:46`、`audit_partial_b_ltne.py:41`、`mms_3d_air_air.py:50`、`mms_phase_a3_h_refine.py:34`、`mms_phase_a4_boundary.py:46`、`phase_c_gci.py:38`，用于修正控制台默认 GBK/CP936 代码页导致的中文打印崩溃。目标机仍是 Windows（Windows Server 2022），中文区域设置下控制台默认代码页依旧是 GBK/CP936，不会因为"服务器"变成 UTF-8 locale——这段修正**必须保留**，不是可以删除的平台兼容遗留代码。子进程解码路径已经显式规避了同一个坑：`tests/test_shanghai_regression.py:60-63` 的 `subprocess.run(..., encoding='utf-8', errors='replace')` 显式指定 UTF-8 解码而不依赖系统默认代码页，迁移到 Windows Server 后应保持这一写法。**未验证**：`validation/` 目录内是否还有非 stdout/subprocess 的文件读写（例如不带 `encoding=` 参数的 `open()`）隐含依赖系统默认 encoding，未做全目录扫描。
- **`ROOT = Path(__file__).resolve().parents[N]` 与 `harness/_case_sets.py:15` 的 `_DATA = _PKG_ROOT.parent / 'data' / 'raw_data'`**：源端、目标端都是 Windows，"pathlib 路径拼接跨平台"这层对比已不成立，不必再强调；真正的风险是这条路径拼接依赖仓库外层目录结构（`sjtu_tpmshx/` 的上一级要有 `data/raw_data/`），迁移到 Windows Server 时必须确认该相对目录关系保持不变，或改用绝对路径/环境变量注入。
- **Excel 数据文件是 gitignored 的（`data/`），worktree 环境中默认不存在**——本次审阅的 worktree（`.claude/worktrees/codebase-atlas-doc`）确认 `ls data` 报错 "No such file or directory"，而原始 checkout（`D:/Postgraduate/Homogenize/SJTU-TPMSHX/data/raw_data/`）确实存在 `20260401-上海电气天然气加热器实验工况.xlsx` 等文件。**依赖 gitignored 数据的 case**：`validate_shanghai_3d_real.py`（`SHANGHAI_XLSX`）、`validate_shanghai_aligned.py`（同）、`validate_shanghai_lumped_dual_nu.py`（同）、`harness/_case_sets.d76_spec()`（`D76_XLSX`）。**不依赖 gitignored 数据的 case**：所有 `mms_*`（纯符号构造流形解）、`phase_c_gci.py`（合成配置 `make_T2`/`make_T4_H8`）、`audit_3d_conservation.py`（合成 T1-T6）、`audit_partial_b_ltne.py`（合成 CASE1）、`verify_pareto_3d.py`（读取用户指定的 `pareto_final.csv`，非本仓库自带数据）、`cf_aniso/fit_cf_aniso.py`（读取用户提供的 results.csv）。Windows Server 上若只 `git clone`/`git pull` 而不同步 `data/`，Shanghai/D76 相关 case 会在 Excel 读取处直接抛 `FileNotFoundError`——本仓库 `scripts/` 下已有现成的 Windows Server 变体 `port_retest_server.ps1`（已用 `ls scripts/` 核实与 Linux 端 `port_retest_server.sh` 并存），其做法是 clone 私有数据仓 `SJTU-TPMSHX-data` 并拼进 `data/raw_data`，入口/参数（`-Mode run|status` 对应 `.sh` 的位置参数 `[空]|status`）与 `.sh` 版一致，服务器移植时直接复用即可，不需要另写。
- **子进程调用假设 `sys.executable` 在 PATH 且脚本以模块形式可导入**：`tests/test_shanghai_regression.py:56-63` 用 `subprocess.run([sys.executable, '-u', '-m', module, ...], cwd=str(_ROOT), ...)`，`-u`（无缓冲）已经遵循仓库长跑脚本约定；这条在 Windows Server 上同样成立，与 Linux/Windows 差异无关——`cwd=_ROOT`（即 `sjtu_tpmshx/`）意味着模块导入路径依赖从该目录启动 `python -m validation.cases.xxx`，只要 Windows Server 上保持相同的相对导入结构即可。
- **`sympy.lambdify(..., 'numpy')` 在 `mms_3d_air_air.py:136-141` 生成的函数依赖 numpy 广播**，是纯 Python/numpy 逻辑，无平台相关性；但符号推导本身（`sp.diff`/`sp.cos`）在大网格 + `case='all'` 时可能耗时较长（脚本内建了 5000 次外迭代 + 50 inner GS 的默认值，`mms_3d_air_air.py:160-162`），Windows Server 如果 CPU 核数/时钟频率与本地开发机不同，需要相应调整 `--max_outer`/`--inner` 或接受更长运行时间，不是正确性问题。
- **无 GUI 依赖**：本模块所有脚本均为纯 CLI/CSV 输出，未见 tkinter/PySide/PySide6/Qt 等 UI 库导入（已用 `Grep` 核实 `validation/` 目录零命中）。Windows Server（尤其 Server Core，或无 RDP 交互会话的无人值守批处理场景）同样没有交互式桌面会话，但因为本模块压根不触碰 GUI 库，不涉及 `QT_QPA_PLATFORM=offscreen` 之类的 headless 插件配置——那属于仓库内其他使用 PySide6 的模块（不在本 `validation/` 范围）的移植关注点，若排查到那些模块，需确认其使用的是 Qt 官方跨平台的 `offscreen` 平台插件写法（Windows/Linux 机制相同），而非任何暗示"仅 Linux 有效"的方案。
- **并行/多进程**：本次审阅未见 `validation/` 目录内使用 `multiprocessing`/`joblib` 等并行库（未系统性 grep 确认，标记未验证）；MMS 数值核心 `_gs_full_chunk_3d_stag`（`solvers/ltne_energy_3d.py`，不在本模块）可能使用 numba 并行优化及磁盘缓存，属于依赖模块的移植关注点——numba 缓存目录（Windows 上通常落在 `%LOCALAPPDATA%` 下的用户 profile，本地开发机与服务器账户的 profile 路径不同，但这是"不同 Windows 账户"而非"Linux vs Windows"的差异）是否会影响服务器批跑，不在本次 `validation/` 模块审阅范围内，**未验证**。
