# 仓库基础设施与环境
生成日期 2026-07-11，基于 commit f33d30e 附近的 master

## 定位与功能

本册覆盖 SJTU-TPMSHX 仓库的"非物理内核"部分：依赖清单、测试/CI 配置、顶层辅助目录（`scripts/`
`benchmarks/` `models/` `data/` `openspec/` `projects/` `poc/` `reports/` `opt_runs/`
`.claude/commands/`）、环境变量旋钮，以及 Windows 相关的平台假设。目标读者是准备把该仓库搬到
Linux 服务器上运行/改造的另一个 AI 代理——因此重点是**移植时必须知道、否则会踩坑**的事实，而不是
复述 `PROJECT_MANUAL.md` 已经讲过的物理内容。

仓库是研究/学位论文代码（`README.md:13` 状态徽章 `research / dissertation`），托管在
`github.com/alexlu997/SJTU-TPMSHX`（`README.md:17`），默认分支 `master`。**当前 worktree
（`.claude/worktrees/codebase-atlas-doc`）是本次任务的隔离副本**，缺少被 `.gitignore` 排除的大文件
（`data/`、`models/*.joblib` 等）——本文中凡涉及这些文件是否存在的断言，均以只读方式核对了原始
checkout `D:\Postgraduate\Homogenize\SJTU-TPMSHX`（未做任何写入）。

## 文件一览

| 路径 | 职责 |
|---|---|
| `requirements.txt` | 运行时 Python 依赖清单（数值栈 + 代理模型 + 绘图 + GUI + IO + 测试），标注版本下限 |
| `pytest.ini` | pytest 配置：`testpaths` 锁定收集范围、`--strict-markers`、`slow`/`fast` marker 注册 |
| `README.md` | 面向 GitHub 首页的项目介绍：headline 指标、安装/运行命令、V&V 结果表、仓库目录树 |
| `PROJECT_MANUAL.md` | 项目说明书（人类+AI 共读）：术语表、架构、逐文件 API 索引、全局约定与陷阱（第 8 节） |
| `AGENTS.md`（仓库根） | 与 `CLAUDE.md` 内容几乎一致的 agent 导读（供非 Claude 系代理读取）；**存在过期路径引用**（见「已知不足」） |
| `.github/workflows/ci.yml` | GitHub Actions：ubuntu-latest 上跑 headless pytest 子集（`-m "not slow"`） |
| `scripts/port_retest_pull.sh` | 本地脚本：从 PyFluent 服务器 scp 拉回一批优化器复测结果并打印判决表 |
| `scripts/port_retest_server.sh` | Linux 服务器启动脚本：clone 主仓 + 私有数据仓、装 venv/依赖、四臂并行跑优化器复测 |
| `scripts/port_retest_server.ps1` | 同上的 Windows Server / PowerShell 变体 |
| `benchmarks/benchmark_snapshot_a.md` / `benchmark_snapshot_b.md` | 历史性能基准快照（文字报告） |
| `benchmarks/profiling/` | cProfile 性能剖析脚本（`profile_*.py`），产物 gitignore |
| `benchmarks/archive/benchmark_a.py` | 冻结的历史基准脚本（目标脚本已删除，不可运行，仅存档） |
| `models/`（仓库根，gitignore） | 存放 `df_surrogate_diamond.joblib` / `df_surrogate_gyroid.joblib`（历史 RBF 代理模型快照，见「已知不足」） |
| `data/`（仓库根，绝大部分 gitignore） | 实验原始数据 Excel + 已生成的验证用 CSV/xlsx |
| `data/raw_data/`（gitignore） | DF 代理训练/复现用的原始 CFD + 实验 Excel（`试验记录表_整理版.xlsx` 等） |
| `openspec/config.yaml` | openspec 项目上下文占位配置（`context:`/`rules:` 均未填写） |
| `openspec/changes/` | 进行中 / 已归档的规范变更提案（`archive/`、`df-coeffs-cfd-refit/`） |
| `openspec/specs/` | 已落地能力的规范文档（`repo-ci`、`arch-b-c-e`、`compute-contracts` 等 16 个能力目录） |
| `projects/624-Retrodict/` `703-sCO2-D76/` `704-Aircooler-10kW/` | 协作交付项目：只放调用 `sjtu_tpmshx` 包的驱动脚本，不含求解器代码 |
| `poc/` | 概念验证脚本（1D LTNE 严格守恒 / enthalpy option B） |
| `reports/README.md` | 按话题（非按日期）组织的报告索引，文件名保留 `YYYY-MM-DD-` 前缀 |
| `reports/<topic>/` | 计算结果、图、CSV（`constdf-v1`、`shanghai-validation`、`m1_uniform_vs_graded` 等 6 个子目录） |
| `opt_runs/qnehvi_3d_20260513_175108/` | 唯一被 git 追踪的历史优化器跑（config.json + history/pareto CSV）；新跑输出 gitignore |
| `.claude/commands/check.md` | `/check` 技能定义：pytest 全量门 + golden bit-identical 门 + 验证 case 命令清单 |
| `.claude/commands/ship.md` | `/ship` 技能定义：push → 开 PR → rebase-merge，网关到测试套件 |
| `.claude/commands/opsx/*.md` | openspec 工作流子命令（apply/archive/explore/propose/sync） |
| `devlog.md`（仓库根） | 纯人工可读开发日志，倒序记录逐日改动/方程变更；非 AI 移植必读，但可作改动历史索引 |
| `assets/`（仓库根） | README 配图（PNG/SVG），唯一生产者是 `runs/tools/plot_grid_convergence.py`（`plot_grid_convergence.py:1` 顶部 docstring 明示输出 `assets/grid-convergence.png`） |

## 公开接口

本册涉及的多是配置/脚本而非 Python API，"接口"指命令行入口与配置契约：

- `pytest sjtu_tpmshx/tests/ -q -n auto --dist loadscope`（并行门，`pytest.ini:8` 注释 + `README.md:153`）——
  调用方：`.claude/commands/check.md:16`、CI（单进程变体）。
- `python sjtu_tpmshx/validation/cases/validate_shanghai_lumped_dual_nu.py` /
  `validate_shanghai_3d_real.py`（`README.md:142,145`）——headline 数字复现入口，调用方：`/check` 第 3 步。
- `bash scripts/port_retest_pull.sh <user>@<server>`（`scripts/port_retest_pull.sh:4`）——本地拉回服务器
  优化器复测结果；期望远端路径 `${PORT_WORKDIR:-~/tpmshx-port}/SJTU-TPMSHX/reports/port_dim_retest`
  （`scripts/port_retest_pull.sh:9`）。
- `bash scripts/port_retest_server.sh [status]` / `powershell -File scripts/port_retest_server.ps1 [status]`
  （`scripts/port_retest_server.sh:5-6`）——服务器端一次性 clone+装依赖+四臂并行启动脚本，是本仓库
  **目前唯一的、经过验证的 Linux 服务器部署样例**（含私有数据仓拼接、venv、torch/botorch 补装）。
- `sjtu_tpmshx/df_surrogate/threads.set_solver_threads(n)` / `init_from_env()`
  （`sjtu_tpmshx/solvers/threads.py:34,43`）——运行时 Numba 线程数旋钮，GUI 的 "CPU cores" spinbox
  调用 `set_solver_threads`，无界面批跑靠 `TPMSHX_NUM_THREADS` 走 `init_from_env`。

## 关键配置项与开关

按“定义处 file:line”列出（**未特别标注默认值的均以 grep 到的字面量为准，未跑代码验证运行期实际值**）：

| 变量/开关 | 默认值 | 定义处 | 作用 |
|---|---|---|---|
| `PYTHONHASHSEED` | 未设置时不确定 | 必须在**外部 shell** 设置为 `0`（`pytest.ini:9-13`、`.github/workflows/ci.yml:26`） | 3D 管线输出对哈希种子敏感（字典/集合迭代序影响运算顺序），无法从 `pytest.ini` 内部注入（解释器启动时已决定） |
| `QT_QPA_PLATFORM` | `offscreen`（CI 强制，`.github/workflows/ci.yml:27`）；测试内 `setdefault('offscreen')`（`sjtu_tpmshx/tests/conftest.py:33`） | 同上 | Qt 无头运行；Windows 有显示器时默认走 `windows` 插件，无头/Linux 必须 offscreen |
| `TPMSHX_NUM_THREADS` | 未设置→Numba 默认（全核，受 `NUMBA_NUM_THREADS` 硬顶） | `sjtu_tpmshx/solvers/threads.py:46` | 无界面批跑（验证/优化器）用的运行期活跃线程数旋钮 |
| `NUMBA_NUM_THREADS` | Numba 原生环境变量，需在 Numba 初始化**前**设置 | `sjtu_tpmshx/solvers/threads.py:6-8`（docstring） | 线程池硬上限 |
| `OMP_NUM_THREADS` / `MKL_NUM_THREADS` / `OPENBLAS_NUM_THREADS` / `NUMEXPR_NUM_THREADS` | 子进程内 `setdefault('1')` | `sjtu_tpmshx/optimization/parallel_runner.py:44-53` | 防止多进程（ProcessPoolExecutor）内 BLAS 超订 |
| `TPMSHX_DF_METHOD` | `_DF_DEFAULT = "gamma_df"`（2026-06-12 由 `rbf` 切换而来） | `sjtu_tpmshx/df_surrogate/predict.py:169`（常量定义）、`:175`（读取环境变量覆盖） | 选择 D-F 代理后端：`gamma_df`（默认）或 `rbf`（历史默认，D7 外推被证伪） |
| `TPMSHX_DF_OVERRIDES` | `"1"`（开） | `sjtu_tpmshx/df_surrogate/predict.py:113` | 是否启用代理覆盖层 |
| `TPMSHX_DF_RESIDUAL_CORR` | `"0"`（关） | `sjtu_tpmshx/df_surrogate/predict.py:77` | 是否启用残差学习修正层 |
| `TPMSHX_ASYM_KAPPA` | `'0'`（关，非 `'0'/''/'false'/'False'` 即开） | `sjtu_tpmshx/df_surrogate/kappa_asym.py:36` | 非对称 κ 修正 |
| `TPMSHX_ALLOW_EXTRAP` | 关（几何超训练窗口时代理默认把 K 钳到地板） | `sjtu_tpmshx/df_surrogate/surrogate_domain.py:65` | 显式放行代理外推 |
| `TPMSHX_ROUGH_MODE` | 由调用方传入的 `default` 参数决定，无独立硬编码默认 | `sjtu_tpmshx/solvers/roughness.py:164` | 表面粗糙度修正模式（据 `PROJECT_MANUAL.md:248` 该模块本身"默认关"） |
| `TPMSHX_ROUGH_EPS_UM` | `'100'` | `sjtu_tpmshx/solvers/roughness.py:165` | 粗糙度特征尺寸 (μm) |
| `TPMSHX_CHI_S` | 未设置→用按类型线性拟合；设置则常量覆盖一切（含拟合） | `sjtu_tpmshx/solvers/tpms_props.py:186,196` | 固体导热迂曲度 χ_s 的legacy 常量覆盖开关 |
| `TPMSHX_SIMPLE_TOL` | 未设置→用管线内建默认容差 | `sjtu_tpmshx/pipelines/run_stack_3d.py:72`、`sjtu_tpmshx/pipelines/stages_2d.py:563` | 覆盖 SIMPLE 收敛容差 |
| `TPMSHX_PROFILE_3D` | `'0'`（关） | `sjtu_tpmshx/pipelines/run_stack_3d.py:151` | 3D 管线内嵌性能剖析开关 |
| `TPMSHX_MAX_CELLS_3D` | `'2000000'`（200 万网格单元，理由：注释明说 200³=8M cells 是 OOM 而非慢，script/optimizer 路径此前"unguarded"，故加此硬顶） | `sjtu_tpmshx/pipelines/run_stack_3d.py:418-426` | 3D 网格单元数上限保护，超限直接报错而非静默跑爆内存 |
| `TPMSHX_VAR_RHOCP` | 未设置→用代码默认（`variable_rho_cp=True`） | `sjtu_tpmshx/pipelines/run_stack_3d.py:946` | 覆盖可压缩 ρ/cp 开关（**违反硬不变量的入口，不要用它关闭可压缩**） |
| `TPMSHX_SCO2_COMPRESSIBLE` | 空字符串（非 `'1'/'true'/'yes'` 即关） | `sjtu_tpmshx/pipelines/run_stack_3d.py:1381,1420` | sCO2 支路可压缩开关（Phase A，独立于空气路径） |
| `TPMSHX_2D_MASSFLUX` | `'1'`（开，与硬不变量"mass-flux 入口默认"一致） | `sjtu_tpmshx/validation/cases/validate_shanghai_aligned.py:131` | 仅见于该验证脚本；设 `'0'` 退回 velocity-inlet（**不要在生产路径这样做**，见 `CLAUDE.md` 硬不变量） |
| `TPMSHX_BUILD_S_MAX` / `TPMSHX_BUILD_LX_MAX` | `"0.450"` / `"0.450"` | `sjtu_tpmshx/design/sizing.py:21-22` | `design/` 定尺工具的几何上限（米） |
| `TPMSHX_LOG_LEVEL` | `"INFO"` | `sjtu_tpmshx/logutil.py:78` | 日志级别 |
| `TPMSHX_LOG_TS` | `"0"`（关） | `sjtu_tpmshx/logutil.py:72` | 日志是否带时间戳 |
| `TPMSHX_EAGER_3D_SLICES` | 由 smoke 脚本设 `'1'` | `sjtu_tpmshx/runs/smokes/smoke_ui_3d_pipeline.py:19` | 触发 2D 切片渲染器 |
| `PYVISTA_OFF_SCREEN` | 由离屏渲染脚本设 `'true'` | `sjtu_tpmshx/runs/demos/demo_3d_cube_volume.py:18`、`sjtu_tpmshx/runs/tools/render_3d_styles.py:21` | pyvista 离屏渲染 |
| `QT_REDUCED_MOTION` | 未设置→动画默认开 | `sjtu_tpmshx/ui/panel_vis_3d.py:919` | UI 减少动效偏好 |
| `PORT_WORKDIR` | `~/tpmshx-port`（Linux）/ `$HOME\tpmshx-port`（Windows） | `scripts/port_retest_pull.sh:9`、`scripts/port_retest_server.sh:16`、`scripts/port_retest_server.ps1:16` | 服务器复测工作目录 |
| `TPMSHX_DEBUG` | 未设置 | `solvers/simple_solver_3d.py:1059`（消费）、`domain/compute_config.py:57`（登记） | 3D 求解器 debug 打印开关 |
| `TPMSHX_DISABLE_3D_PANEL` | `'0'` | `ui/builders_canvas.py:537`、`ui/mixins/run_controller.py:625` | 跳过 PyVista 3D 面板（headless/offscreen/GL 失败时的软降级路径） |
| `TPMSHX_PARALLEL_THRESHOLD` | `'200000'` | `solvers/simple_solver_3d.py:79-81` | 红黑（red-black）prange 并行化的单元数下限门槛 |
| `TPMSHX_PHASE_A` / `TPMSHX_PHASE_B` / `TPMSHX_PHASE_C` | `'1'` / `'0'` / `'0'` | `pipelines/run_stack_3d.py:90,96-100` | 3D SIMPLE 加速三阶段独立开关（docstring 明示单独测试用） |
| `TPMSHX_PREINIT_3D` | `'0'` | `main.py:268` | 启动时预热 3D 面板 |
| `TPMSHX_RUN_SHANGHAI_REGRESSION` | `'0'` | `tests/test_shanghai_regression.py:45` | opt-in 长耗时验证门（默认跳过，CI 不跑） |
| `QT_ENABLE_HIGHDPI_SCALING` | `setdefault('1')`（`main.py:1529`，即未设置时视为开） | `main.py:1529` | Qt 高 DPI 缩放 |

> 上表并非全仓穷尽——`sjtu_tpmshx/domain/compute_config.py` 模块 docstring（约 :50-103）本身即是一份代码内的
> `TPMSHX_*` 环境变量权威登记表，与本表存在部分重叠但各自独立维护，另见 [core-domain.md](./core-domain.md)
> 的「TPMSHX_\* 注册表」一节；求解器/UI 层还有零星分册各自提过一次的旋钮（如 `solvers-3d.md`、
> `ui-core.md`、`ui-widgets.md`、`tests.md`、`validation.md`），本表与 core-domain 注册表互为交叉参考，
> 不保证互相去重——批量审计全部旋钮时两处都要查。

pytest 侧开关：`pytest.ini:17-19` 注册两个 marker——`slow`（重量级真实求解测试，CI 用 `-m "not slow"`
排除）、`fast`（廉价冒烟子集，需显式 `-m fast` opt-in）。`--strict-markers`（`pytest.ini:16`）使未注册
marker 在收集期报错而非静默通过。

## 边界·假设·适用范围

- **Python 版本**：README 声明"Tested on Python 3.11 / 3.12, Windows 11. Linux should work; macOS
  untested"（`README.md:108`）；CI 实际用 3.12（`.github/workflows/ci.yml:32`）。仓库内**未发现**
  `python_requires` 或 `pyproject.toml`/`setup.py` 版本硬约束（未验证是否存在于仓库其它未检索位置）。
- **依赖分级**（据 `requirements.txt` 与代码内 import 方式核实，而非仅按注释）：
  - **硬依赖（无 try/except 保护，import 失败即整包不可用）**：`numpy` `scipy` `pandas` `sympy`
    （`requirements.txt:6-9`）；`numba`——在 `solvers/simple_solver.py:42`、`simple_solver_3d.py:58`、
    `ltne_energy.py:23`、`ltne_energy_3d.py:27`、`_kernels_*.py` 等处均为顶层 `from numba import njit`
    **无 ImportError 兜底**，是求解器内核的真正硬依赖；`PySide6`——`main.py:20-21` 顶层硬 import
    （GUI 入口 + 多个 controller/pipeline 测试也在模块顶部无门 import Qt，`openspec/specs/repo-ci/spec.md`
    印证）；`openpyxl`（Excel IO）；`pytest`/`pytest-xdist`（测试）；`scikit-image`（asym-porosity
    marching cubes，`requirements.txt:37`）。
  - **软依赖 / 运行时可选（有 `try/except ImportError` 兜底）**：`pyamg`——`solvers/simple_solver_3d.py:62-66`
    显式 `try: import pyamg; _HAS_PYAMG = True; except ImportError: _HAS_PYAMG = False`，缺失时退回
    `bicgstab`（非 AMG 路径），`solvers/ltne_energy_3d.py:58` 则是**无保护的函数内 `import pyamg`**（延迟
    到调用 AMG 缓存构建函数时才会因缺失而报错，与 `simple_solver_3d.py` 的全局兜底不是同一处保护，
    **存疑**：3D 能量求解的 AMG 路径是否有等价降级，需要读该函数调用方逻辑确认）。
  - **场景性可选、requirements.txt 未强制但代码路径需要**：`scikit-learn`（`requirements.txt:15`
    标注"D-F surrogate: Huber trend + GP residual"——经代码核实，默认 `gamma_df` 后端
    [`gamma_df.py`/`smooth_df.py`] **未 import sklearn**，只有历史 `rbf` 后端 [`surrogate_v3.py`]
    才用得到；即**默认生产路径实际不需要 scikit-learn**，requirements.txt 未区分这层）；`joblib`
    （同理，主要给 `rbf` 后端 + `design/select.py:29` 的并行枚举 + `optimizer_qnehvi.py` 的
    `joblib.Parallel` 用，`gamma_df` 默认路径不依赖它做模型加载——见「已知不足」关于 `.joblib`
    死代码的记录）；`CoolProp`（仅 `solvers/sco2_props.py`、`solvers/ltne_enthalpy_3d.py` import，
    只影响 sCO2 项目分支，空气/水路径不需要）；`pyvista`/`pyvistaqt`（仅 3D 可视化面板
    `ui/panel_vis_3d.py:34` 等顶层硬 import，**无 try/except**；CI 刻意不装，靠测试侧
    `skipif`/`importorskip` 门跳过——`openspec/specs/repo-ci/spec.md` 明文"pyvista SHALL NOT 安装"）。
  - **requirements.txt 标注"可选"但实际另有隐藏必需依赖**：`torch`（`requirements.txt:31-32` 注释为
    "GPU surrogate inference (commented; only needed for D-F training)"，且被注释掉未启用）；但
    `optimization/optimizer_qnehvi.py:213-227` 在函数体内**惰性 import** `torch` `botorch`
    `gpytorch`——qNEHVI 多目标优化器模块**运行时必需** torch/botorch/gpytorch，而这三者**均未出现在
    `requirements.txt`**（仅 `torch` 以注释形式提及，`botorch`/`gpytorch` 完全未提）。`scripts/port_retest_server.sh:48-49`
    与 `.ps1:58-59` 均额外单独 `pip install torch --index-url .../cpu` + `pip install botorch gpytorch`，
    印证这是已知的、靠脚本外挂补齐的缺口，而非文档疏漏。
- **数据文件依赖**（移植到无这些文件的服务器时的影响面）：
  - `data/raw_data/试验记录表_整理版.xlsx`——DF 代理**训练**入口 `df_surrogate/load_data.py:45`、
    `surrogate_v3.py:85` 的默认路径；缺失时**只影响重新训练/重新生成 `_prebuilt/*.csv`**，不影响
    默认 `gamma_df` 推理（其只读 `df_surrogate/_prebuilt/df_cfd_coeffs.csv` 等**已入库**的 CSV，
    `gamma_df.py:93`）。
  - `data/raw_data/water-cfd-raw.xlsx`——`smooth_df.py:52` 的水侧 CFD 原始数据，同上只影响重训练。
  - `data/raw_data/20260401-上海电气天然气加热器实验工况.xlsx`——被 `ui/demo_vis_3d.py:59-62`、
    `runs/archive/diag_df_model_zoo.py:450` 等**演示/诊断脚本**读取；`ui/demo_vis_3d.py:62` 有一条
    **写死的 Windows 绝对路径**兜底（见「服务器移植注意」）。
  - `data/shanghai_lumped_dual_nu.csv`——`validate_shanghai_lumped_dual_nu.py:259` 读取，是**已入库
    文件**（非 `data/raw_data/`），headline Q RMSRE 1.71% 验证入口的必需数据，**随仓库自带**。
  - `df_surrogate/smooth_df.py:55` 的 `AIR_XLSX_DEFAULT` 指向仓库**外部**的绝对路径
    `D:\Postgraduate\server-pyfluent\Air\Cfd-air-raw-old-new.xlsx`——这是空气侧 smooth-CFD 原始数据，
    只用于（罕见的）重新生成 `smooth_df_coeffs.csv`，**不在本仓库版本控制范围内，也不在 `data/`
    目录下**；移植到服务器且需要重跑这条训练路径时必须额外提供该文件或改路径。
  - `models/df_surrogate_diamond.joblib` / `df_surrogate_gyroid.joblib`——按本次代码检索，**当前代码
    中未找到任何 `joblib.load` 调用读取这两个具体文件**（`main.py:513` 附近只有指代"joblib 模型"的
    注释和对 `predict_K_cF` 的warm-up 调用，该调用默认走 `gamma_df` 后端，不触碰 `.joblib`）。这两个
    文件疑似是历史 `rbf`/`plhub_gp` 代理的训练产物快照，其**再生脚本 `df_fit/train_surrogate.py` 已在提交
    `6c3998a`（"diag: active fraction threshold sweep for Brinkman audit"）被删除**——`git log --diff-filter=D`
    核实（此前误记为 `b0822dd`，该提交实为不相关的 `df_fit/` → `df_surrogate/` 重命名）。**存疑，未完全验证**——只在
    本次检索范围内确认了 `predict.py`/`gamma_df.py`/`smooth_df.py`/`surrogate_v3.py` 无引用，不排除
    `runs/archive/` 或其它未逐一读取的脚本仍引用它。
  - `opt_runs/qnehvi_3d_20260513_175108/`——**已入库**的一次历史优化器跑（`config.json` +
    `history.csv` + `pareto_*.csv`），供对照参考，非运行必需。

## 可扩展接口

- **D-F 代理后端注册表**：`df_surrogate/backend.py:29-33` 提供 `register(name)` 类装饰器 + 全局
  `_REGISTRY` 字典，新增后端只需 `@register("xxx")` 一个 `DFBackend` 子类；`predict.py:175` 通过
  `TPMSHX_DF_METHOD` 环境变量或 `method=` 参数选择后端。**新增/切换默认后端的强制流程**写在
  `backend.py:17-24`（REGISTRATION CONTRACT）：必须过 Shanghai 3D Nz=3 门 + D_7_6 门，训练域指标
  不算数（有 plhub_gp 反面案例：训练域 LOO 32.1→11.8% 但端到端 dP RMSRE 62.79%）。
- **私有 kwargs 钩子**：`solvers/ltne_energy.py` 的 `eps_A`/`eps_B`（`CLAUDE.md` 硬不变量已述，本册
  不重复）；`envelope_mode` 三态开关（`'raise'`/`'warn'`/`'off'`，定义于 `solvers/envelope.py`，
  由 `cfg['envelope_mode']` 驱动）。
- **openspec 工作流**：`openspec/config.yaml` 的 `context:`/`rules:` 字段目前**均为占位注释、未填写**
  （`openspec/config.yaml:3-14`），是留给未来会话补充项目级 AI 上下文的挂钩点；`openspec/changes/`
  与 `openspec/specs/` 是 spec-driven 变更流程的标准两阶段（提案 → 归档/落地规范）。
- **`.claude/commands/opsx/*.md`**：`apply.md`/`archive.md`/`explore.md`/`propose.md`/`sync.md` 五个
  子命令，对应 openspec 变更生命周期的五个阶段，是可复用的 slash-command 挂钩点。
- **服务器复测四臂脚本的参数化点**：`scripts/port_retest_server.sh` 的 `launch() { local tag=...}`
  函数按 `<ctrl> <seed>` 组合启动（当前硬编码 `4 7`/`4 123`/`6 7`/`6 123`，调用处在
  `scripts/port_retest_server.sh:77-80`），是往这套复测框架追加新臂（新 ctrl 维度或新 seed）的天然
  扩展点；`.ps1` 变体的 `Launch` 函数同构（`scripts/port_retest_server.ps1:69-80`）。
- **线程数三层旋钮**：`NUMBA_NUM_THREADS`（硬顶）→ `TPMSHX_NUM_THREADS`（脚本层）→
  `set_solver_threads(n)`（运行时/GUI 层），三层设计写在 `solvers/threads.py:1-17` docstring，是
  未来加新的批跑入口时应遵循的既有约定，而非需要新开一套线程控制。

## 已知不足与 TODO

- **`AGENTS.md`（仓库根）与 `CLAUDE.md` 内容基本重复，但存在一处过期路径差异**：`AGENTS.md:22` 写
  "Commands ... live in `/check` (`.Codex/commands/check.md`)"，而实际文件在
  `.claude/commands/check.md`（本仓库当前的实际目录，已用 `ls` 核实）。这是双文档同步维护时遗漏的
  路径重命名残留，**未验证**是否为唯一差异点（未做逐行 diff）。
- **`models/*.joblib` 疑似死文件**：见上「数据文件依赖」一节，当前生产默认路径（`gamma_df` 后端）
  不读取它们，且再生脚本已删除。移植服务器时**大概率不需要**这两个文件，但因未做全仓库穷举式引用
  搜索（只搜了 `df_surrogate/` 和 `main.py`），标记为存疑而非确定死代码。
- **`ltne_energy_3d.py:58` 的 `import pyamg` 无 try/except 保护**，而同为 AMG 使用方的
  `simple_solver_3d.py:61-66` 有 `_HAS_PYAMG` 显式降级。两处对 pyamg 缺失的容错行为不一致，若服务器
  环境未装 `pyamg`，3D 能量求解走到 AMG 缓存构建函数时会直接抛 `ImportError` 而非降级——**未验证**
  该函数是否有上层调用方在选择 AMG 路径前先检查可用性（未追踪调用链）。
- **`torch`/`botorch`/`gpytorch` 是 qNEHVI 优化器模块的运行时硬依赖，但完全不在 `requirements.txt`
  的可安装项里**（`torch` 仅以注释形式存在且被注释掉；`botorch`/`gpytorch` 未提及）。只有
  `scripts/port_retest_server.sh`/`.ps1` 这两个"临时"服务器脚本知道要额外装它们
  （`scripts/port_retest_server.sh:39-40`）。这是一个真实的依赖清单缺口：任何不经过这两个脚本、直接
  `pip install -r requirements.txt` 后尝试跑优化器模块的人会在 `optimizer_qnehvi.py:213` 处遇到
  `ModuleNotFoundError`。
- **`benchmarks/archive/benchmark_a.py` 已确认不可运行**（`openspec/specs/repo-ci/spec.md:18` 明文
  "目标脚本已删除"），仅作历史存档，**不要**尝试直接执行它。
- **`df_surrogate/smooth_df.py:55` 的 `AIR_XLSX_DEFAULT` 硬编码指向仓库外的 Windows 绝对路径**
  （`D:\Postgraduate\server-pyfluent\Air\Cfd-air-raw-old-new.xlsx`），这是本仓库中**最直接的
  Windows-only 路径假设**，服务器移植若需要重跑这条 smooth-CFD 训练路径，必须显式传入
  `air_xlsx=` 参数（`smooth_df.py:190` 的 `build_table(air_xlsx: Path = AIR_XLSX_DEFAULT)`
  签名支持覆盖）或修改常量。
- **`ui/demo_vis_3d.py:62` 有一条写死的 Windows 绝对路径兜底**（"rename-proof legacy fallback"注释），
  当相对路径 `ROOT.parent/'data'/'raw_data'/...` 找不到文件时退回
  `Path(r'D:\Postgraduate\Homogenize\SJTU-TPMSHX\data\raw_data\...')`——这条兜底在非 Windows / 非该
  开发机路径下必然也失败，等价于该演示脚本在其它机器上没有数据时会直接抛异常，**不是** TODO 注释
  但功能等价于"未做真正的跨机兜底"。
- **`openspec/config.yaml` 的 `context:`/`rules:` 从未填写**（仍是模板占位注释），意味着 openspec
  自动化流程目前拿不到任何项目专属上下文提示——不是错误，但是一个尚未利用的扩展点。
- 未在本册范围内找到显式的 `# TODO` / `# FIXME` 注释或被注释掉的功能分支（本册聚焦
  `requirements.txt`/`pytest.ini`/`README.md`/`AGENTS.md`/`scripts/`/`benchmarks/`/`models/`/`data/`/
  `openspec/`/`projects/`/`poc/`/`reports/`/`opt_runs/`/`.claude/commands/` 这些非求解器路径本身，
  求解器内部的 TODO/NotImplementedError 请查其它分册）。

## 服务器移植注意

- **唯一已验证的 Linux 部署路径就是 `scripts/port_retest_server.sh`**（`scripts/port_retest_server.sh`
  全文）：clone 主仓（public）+ 私有数据仓 `SJTU-TPMSHX-data`（含 `raw_data/`）→ venv → 装
  `requirements.txt` → 额外装 CPU 版 torch + botorch/gpytorch → 拼装 `data/raw_data` →
  设 `PYTHONHASHSEED=0`、`PYTHONPATH=$REPO/sjtu_tpmshx`、`OMP/MKL/NUMBA_NUM_THREADS` → 后台四臂并行跑
  `runs/run_port_dim_retest.py`。这套脚本本身对"服务器缺 gitignored 数据会怎样"有防御性检查
  （`scripts/port_retest_server.sh:52-56`：`data/raw_data` 不存在则 `FATAL` 直接退出，而不是静默用
  CSV 标定回退——对应用户记忆中的"worktree raw_data gate trap"）。
- **CI（`.github/workflows/ci.yml`）是另一个已验证的 headless Linux 基线**，但只覆盖 `-m "not slow"`
  子集，且**刻意**不装 `pyvista`、不碰任何 gitignored 资产（`.github/workflows/ci.yml:6-9` 注释 +
  `openspec/specs/repo-ci/spec.md`）。它安装的依赖子集（`.github/workflows/ci.yml:42-44`）比
  `requirements.txt` 更窄：明确排除了 `pyvista`/`pyvistaqt`，也不装 `pytest-xdist`（CI 单进程跑，
  `timeout-method=thread` 用于诊断挂起）。
- **GBK / 编码陷阱**：多个 df_surrogate 训练脚本在 `__main__` 分支显式
  `sys.stdout.reconfigure(encoding="utf-8")`（如 `predict.py:328`、`smooth_df.py:217`、
  `surrogate_v3.py:613`），原因见 `surrogate_v3.py:152-153` 注释——Windows 下 GBK 控制台的子进程会用
  GBK 字节写中文，而 pytest 用 UTF-8 读捕获流，二者不一致会导致捕获乱码/编码异常。移植到 Linux（默认
  UTF-8 locale）时这个特定问题消失，但**若服务器 locale 非 UTF-8**（少数精简容器镜像），同样的
  `reconfigure` 调用仍是必要的防御，不应删除。
- **Qt 离屏运行**：`sjtu_tpmshx/tests/conftest.py:33` 在会话开始时 `os.environ.setdefault('QT_QPA_PLATFORM',
  'offscreen')`，并在 `conftest.py:50-55` 提前实例化一个进程级 `QApplication(['pytest', '-platform',
  'offscreen'])`（`_QApp.instance() is None` 时才建），这是 2026-05-09 为解决"Windows 下无显示器时首次
  `QApplication` 实例化以 exit code 9 崩溃"而加的修复；在无头 Linux 服务器上该逻辑同样必要（CI 已用
  `QT_QPA_PLATFORM: offscreen`，`.github/workflows/ci.yml:27`），**不要**假设 Linux 无头环境不需要它。
- **路径分隔符 / 大小写**：`data/raw_data` 等相对路径拼接均用 `pathlib.Path`（如 `load_data.py:45`
  `_PROJECT_ROOT.parent / "data" / "raw_data" / "试验记录表_整理版.xlsx"`），因此**跨平台分隔符本身
  是安全的**；真正的风险点是上面列出的两处**写死盘符路径**（`smooth_df.py:55`、`demo_vis_3d.py:62`），
  两者都不在核心求解器/生产路径上（分别是训练脚本默认值、演示脚本兜底），但会在对应功能被触发时
  于非 Windows 环境报路径不存在。
- **并行度假设**：`scripts/port_retest_server.sh:60-61` 按 `nproc/4` 动态算每臂线程数（`THREADS`，夹在
  `[1,4]`），`.ps1` 变体则硬编码 `8`（假设 64 核机器四臂并行、每臂 8 线程，`scripts/port_retest_server.ps1:65-67`
  代码 + `:10-11` 注释）。移植到核数显著不同的服务器时，`.ps1` 的硬编码线程数不会自适应，需要人工按核数调整；
  `.sh` 变体的 `nproc`-based 公式相对更可移植。
- **`PYTHONPATH` 陷阱**：`/check` 文档（`.claude/commands/check.md`）与 `conftest.py:1-24` 都记录了
  同一个坑——直接单独跑某个 `sjtu_tpmshx/` 下的脚本/测试文件（尤其是子进程/CI runner 单独调用某个
  文件）会因 `sjtu_tpmshx/` 未加入 `sys.path` 而 `ModuleNotFoundError: solvers`；正确姿势是从仓库根
  跑（`pytest.ini` 的 `testpaths` 假设），或显式 `PYTHONPATH="$PWD/sjtu_tpmshx"`。
- **`.claude/worktrees/` 目录本身被 `.gitignore` 排除**（`.gitignore` 末尾块），且 `pytest.ini`
  的 `testpaths = sjtu_tpmshx/tests` 就是为了防止裸 `pytest` 意外收集到这些 worktree 副本里的测试
  （`pytest.ini:3-5` 注释）——在服务器上如果也采用 worktree 隔离开发，需要保留这条 `testpaths` 约束。
