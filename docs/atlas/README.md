# Atlas 索引

生成日期 2026-07-11，基于 commit f33d30e 附近的 `master`。
**2026-07-20 起随 upgrade/loop 分支滚动收编**：已收编卷在其头部标注并附文末"2026-07 升级分支收编"节
（进度：`tests.md`、`repo-infra.md` ✓ iter 34；`pipelines.md`、`controllers.md`、`core-domain.md`、
`optimization.md` ✓ iter 35——⚠ pipelines 卷的 run_stack_3d 行号为拆分前旧值，见该卷头注；
`ui-core.md`、`runs.md`、`solvers-2d.md`、`solvers-closures.md` + PROJECT_MANUAL §6 增量索引 ✓ iter 36。
**P4.1 收案**：未收编卷（dataflow/design/df-surrogate/solvers-3d/solvers-fields-mesh/ui-widgets/
validation）经盘点无分支级失准；HANDOFF ✓ iter 39（文首状态总更新表 + 三节行内戳，原文证据链不动）；ui-widgets/dataflow 的 run_controller
行号引用受 P2.5a 位移影响者极少且方向可循，未逐一标注。）

本目录（`docs/atlas/`）是 2026-07 的代码库历史快照，保留当时的逐文件证据与迁移记录。当前结构和约束以 `docs/architecture.md` 与运行代码为准。

## 与 `PROJECT_MANUAL.md` 的关系

`PROJECT_MANUAL.md` 第 6 节提供当前概览；本 atlas 仅作为更细粒度的历史证据。两处描述冲突时，以 `docs/architecture.md` 和运行代码为准。

## 建议阅读顺序

先读 `dataflow.md` 建立全局函数级调用链地图，再读 `repo-infra.md` 了解移植前必须打点的依赖/环境变量/数据文件，之后按需下钻具体子系统册。

## 分册一览

| 册 | 定位 | 核查（confirmed/checked，fixed） |
|---|---|---|
| [`dataflow.md`](./dataflow.md) | 端到端调用链与架构流（先读这本，建立全局地图） | 25/26，修正 1 |
| [`repo-infra.md`](./repo-infra.md) | 仓库基础设施与环境（移植前必读） | 17/27，修正 14 |
| [`core-domain.md`](./core-domain.md) | configs + core + domain | 36/38，修正 2 |
| [`controllers.md`](./controllers.md) | controllers | 29/30，修正 1 |
| [`pipelines.md`](./pipelines.md) | pipelines | 40/40，修正 0 |
| [`solvers-2d.md`](./solvers-2d.md) | solvers — 2D SIMPLE + 能量 | 29/30，修正 1 |
| [`solvers-3d.md`](./solvers-3d.md) | solvers — 3D | 34/38，修正 4 |
| [`solvers-closures.md`](./solvers-closures.md) | solvers — 闭合关系与物性 | 31/32，修正 1 |
| [`solvers-fields-mesh.md`](./solvers-fields-mesh.md) | solvers — 场生成与网格 | 39/42，修正 3 |
| [`df-surrogate.md`](./df-surrogate.md) | df_surrogate | 28/28，修正 0 |
| [`optimization.md`](./optimization.md) | optimization | 41/42，修正 1 |
| [`design.md`](./design.md) | design | 24/33，修正 9 |
| [`ui-core.md`](./ui-core.md) | ui — 主窗口与 mixins | 27/28，修正 1 |
| [`ui-widgets.md`](./ui-widgets.md) | ui — 其余组件 | 28/29，修正 1 |
| [`validation.md`](./validation.md) | validation | 28/31，修正 3 |
| [`tests.md`](./tests.md) | tests — 测试覆盖地图 | 27/29，修正 2 |
| [`runs.md`](./runs.md) | runs — 入口脚本目录 | 25/27，修正 2 |

## 各册摘要

### dataflow.md — 端到端调用链与架构流（先读这本，建立全局地图）

梳理三条互不调用的计算入口链（UI→Pipeline2D/3D、优化器评估器直连solvers、validation双跑法），函数级file:line溯源2D SIMPLE-first/3D LTNE-first外循环结构、cfg dict生命周期，并发现2处文档/代码不一致（coupling_skeleton docstring误述3D追踪场；golden_3d实为_run_3d_stack而非Pipeline3D）。

### repo-infra.md — 仓库基础设施与环境（移植前必读）

梳理依赖清单分级（硬/软/隐藏依赖）、env变量旋钮清单、数据文件依赖面、scripts/服务器部署样例，及AGENTS.md路径过期、models/.joblib疑似死文件、torch/botorch缺失于requirements.txt等移植风险点。

### core-domain.md — configs + core + domain

已产出 configs/core/domain 三包图谱：ComputeConfig 树与默认值（variable_rho_cp=True、envelope_mode='raise'）、evaluate_3d 契约、validator 纯函数、TPMSHX_* 注册表；澄清 fluid_type='ideal_gas' 默认实位于 solvers 层；含移植 import 布局陷阱。

### controllers.md — controllers

controllers 层文档：ComputeOrchestrator（Qt 线程生命周期+取消+日志捕获）、ComputePipeline ABC/Pipeline2D/3D（ComputeConfig→ComputeResult 三阶段纯适配器）、ResultCache、SessionManager、SignalRouter；含调用方、配置默认值、双 CancelledError 陷阱与 Linux 移植注意（PySide6 硬依赖、扁平包名、包目录写盘）。

### pipelines.md — pipelines

pipelines 模块图谱：2D/3D 四相 stage 层（parse/build/run/finalize），驱动 SIMPLE+LTNE 求解栈；覆盖数值默认值、asym ε upstream split、包络门、环境变量与服务器移植注意。

### solvers-2d.md — solvers — 2D SIMPLE + 能量

2D SIMPLE/LTNE 模块图谱：SIMPLESolver 可压缩交错网格求解器、numba 动量/压力核、LowReExit 早退、Anderson（仅3D接入）、ltne_energy 三温 GS 核与 ε 减半不变量、线程控制、默认值表与服务器移植注意。

### solvers-3d.md — solvers — 3D

3D 求解器族文档：SIMPLESolver3D 可压缩 SIMPLE（mass-flux inlet、outlet-anchored PPE、P_abs clip）、三温度 LTNE（ε 分拆契约、conservative staggered 内核、Helmholtz 投影）、焓形式 sCO2 内核、粗网格热启动与外层耦合骨架，含默认值、开关表与移植注意。

### solvers-closures.md — solvers — 闭合关系与物性

已核实并成文 solvers 闭合层 11 个文件：Nu 三谱系单一来源、envelope 三档守卫与 ChokedFlowError、asym δ 分相三函数、K_ff 用 FULL ε（tpms_calc:350，CLAUDE.md 的 :506 已过期）、cf-aniso 方向因子（默认 0，未标定）、物性注册表与移植注意。

### solvers-fields-mesh.md — solvers — 场生成与网格

覆盖 7 个场生成/网格文件：ContinuousFieldConfig（现役 16-D B-spline 优化器表达）、sigmoid 场（UI Pareto 复算保留，AIR-ONLY）、ZoneConfig（优化器废弃、UI Compute 保留）、grid_schema 输出契约、polygon FVM 支线（仅 UI 多边形入口，Darcy+LTNE，SIMPLE 变体无调用方）。含 ε 场进求解器四条路径与服务器移植注意。

### df-surrogate.md — df_surrogate

df_surrogate 模块图谱：D-F 压降闭包代理，gamma_df/rbf 双 backend、1D 可压缩公式、override/κ/残差修正层、训练窗口与防泄漏守卫、_prebuilt CSV 降级链及服务器移植注意。

### optimization.md — optimization

文档描述 sjtu_tpmshx/optimization/ 多目标贝叶斯优化栈：2D/3D 评估器（SIMPLE+LTNE+ρ(T) 外循环，返回 (−Q,dP,mass)）、qNEHVI BO 引擎、多种子并行编排、nTop CSV 导出，含默认配置表、病态设计处理、坐标翻转陷阱与服务器移植注意。

### design.md — design

design 模块为快速反向定尺工具，与主管线解耦，测试用最小 claims 数组。

### ui-core.md — ui — 主窗口与 mixins

该文档描述桌面 GUI 主窗口层：Main_Menu 由 14 个 mixin 多重继承组装（⟨07-20⟩ +RunResultsMixin），config_from_window 为控件到 ComputeConfig 的唯一转换器；覆盖计算入口分派、结果桥、session/preset 恢复策略、默认值表、点文件持久化及服务器移植注意。

### ui-widgets.md — ui — 其余组件

覆盖 sjtu_tpmshx/ui/ 除主窗口与 mixins 外全部组件：页面构建器、matplotlib/PyVista 绘图层、主题系统、纯逻辑模块、后台 QThread 面板；含默认常量、env 开关、headless 移植注意与文档-代码不符点。

### validation.md — validation

梳理validation目录(cases/harness/cf_aniso/_CSV_STATUS)：门禁脚本validate_shanghai_3d_real.py判定逻辑、数字溯源表、MMS/GCI/守恒审计、gitignored数据依赖清单，均附file:line。

### tests.md — tests — 测试覆盖地图

编目 sjtu_tpmshx/tests/ 151文件按主题分组（golden/solver单元/闭合/UI/回归），说明PYTHONHASHSEED并行门禁、data/raw_data缺失导致的skip/ULP陷阱、GBK日志毒化pytest capture的坑。

### runs.md — runs — 入口脚本目录

编目 sjtu_tpmshx/runs/ 全部49个脚本(根/_out/archive/demos/diagnostics/smokes/tools/cfd_asym)，优化器M0-M4系列、golden gate（⟨07-20⟩ polygon_calc 已迁 ui/，生产入口条目撤销），并核实出1处确认死链接导入+2处过期usage文档。
