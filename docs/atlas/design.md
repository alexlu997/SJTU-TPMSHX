# design

生成日期 2026-07-11，基于 commit f33d30e 附近的 master

## 定位与功能

`sjtu_tpmshx/design/` 是一套独立于主 SIMPLE/LTNE 生产管线（`solvers/simple_solver*.py`）之外的**快速反向定尺工具**：给定一批换热工况（热/冷侧流体、进口温压、流量、Q 或 dT、ΔP 上限），在 {拓扑, 晶胞尺寸 l, 壁厚 t, 迎风宽 s, 流向长 Lx} 参数空间中求满足冷却与压降约束的 min-体积构型。模块 docstring 自称"均质化框架内的反向定尺"（`sjtu_tpmshx/design/__init__.py:1`）。

关键设计前提（未验证之处已标注）：

- **能量求解与动量解耦**：`forward.py` 直接调用 `solvers/ltne_energy_3d.py` 的 `solve_full_domain_3d`（`solvers/ltne_energy_3d.py:427`）求 LTNE 温度场，但速度场是由 `mdot/(ρ·A_flow)` 解析算出的**恒定 plug 速度**（`forward.py:55,118-126`），并非 SIMPLE 迭代动量解——`forward.py:1` 明确写"无 SIMPLE 动量, plug 速度"。
- **压降与温度场解耦**：ΔP 不是从动量方程解出，而是用 `df_surrogate/predict.py` 的解析 Darcy-Forchheimer 关联式单独算（`forward.py:70-89` `dP_fracs`），与 LTNE 能量解互不反馈。
- **未接入 `solvers/envelope.py` 的 choke/正压守卫**：对 `sjtu_tpmshx/design/*.py` 全文 grep "envelope|choke|ChokedFlow" 只命中一处纯注释性变量名 `sizing.py:16`（"Build envelope"，指构建体积上限，非阻塞流上限），未发现对 `check_compressible_envelope`/`gate_solution` 的调用（已核实：grep 结果见上）。即该工具没有主管线的低马赫合法性守卫；`predict_dP_compressible` 走等温可压缩 D-F 一维解析式，但调用侧不做马赫数/出口绝压检查。
- 该工具是稳态、**常物性（分段常数，可选入口态或均温两趟）ε-NTU 式**估算，非逐场耦合 CFD；`fluids.py:53` docstring 自陈"design 工具是常物性 ε-NTU，对 sco2 变-cp/近临界本就粗糙"。

调用方（生产/UI/CLI 三处）：
- CLI：`sjtu_tpmshx/design/cli.py`（`run()` 为入口，`if __name__ == "__main__"` 块见 `cli.py:70-71`）。
- GUI：`sjtu_tpmshx/ui/quick_design_panel.py`（QThread worker 里懒加载 `design.cases/sizing/select/optimize/report`，见 `ui/quick_design_panel.py:81-105,462`）。
- 项目脚本：`projects/704-Aircooler-10kW/aircooler_conservative_check.py`、`projects/704-Aircooler-10kW/predict_aircooler_10kw.py` 直接 `import design.sizing as SZ` 等（外部脚本用相对包名 `design.xxx`，说明这些脚本运行时以 `sjtu_tpmshx/` 为 sys.path 根——**未验证** sys.path 具体注入方式，本次未打开各脚本头部/`conftest.py` 逐行核实）。

## 文件一览

| 文件 | 职责（一行） |
|---|---|
| `__init__.py` | 仅含包 docstring，无导出符号（`design/__init__.py:1`）。 |
| `cases.py` | `DesignCase` dataclass + xlsx/csv 多行工况表 loader（`load_cases`）。 |
| `fluids.py` | design 工具的物性/Nu 薄适配层，转发到 `solvers.fluid_props` 注册表与 `solvers.nu_correlations`，不自带任何物性数据。 |
| `forward.py` | 给定完整几何+工况正向求 (T_out, Q, ΔP, Re)：`forward()` + 解析 ΔP 的 `dP_fracs()`。 |
| `sizing.py` | 核心定尺算法：对固定 (topo,l,t) 求 min-V 的 (s, Lx)——`size_fixed_cell()`；含 `solve_Lx()`、`t_target()` 等内部子程序。 |
| `select.py` | 在 {topo×l×t} 离散节点网格上枚举跑 `size_fixed_cell`，可用 `joblib` 跨候选并行，取 Pareto 标记。 |
| `optimize.py` | 从枚举最优出发，对连续 (l,t) 做 Nelder-Mead warm-start 精修（"ZONED-OPT Stage B 单模块退化"）。 |
| `report.py` | 把设计结果列表写成双 sheet Excel（构型汇总 + 工况明细），CLI/UI 共用。 |
| `cli.py` | argparse 命令行入口，`auto`（枚举选胞元）/`fixed`（指定胞元只定外形）两种模式。 |

无 `examples/` 子目录（已用 `find` 核实：`sjtu_tpmshx/design/` 下仅上述 8 个 `.py` 文件 + `__pycache__`）。

## 公开接口

- **`DesignCase`**（dataclass，`design/cases.py:9-15`）：字段 `case,hot_fluid,T_in_h,P_in_h,mdot_h,cold_fluid,T_in_c,P_in_c,mdot_c,Q,dPlim_h,dPlim_c,dT`。单位：T[K]、P[Pa]（**已从输入表的 kPa 转换**，见下）、mdot[kg/s]、Q[W]、dPlim 为 ΔP/P_in 无量纲分数。调用方：`sizing.py`、`forward.py`、`select.py`、几乎所有 `tests/design/*`。

- **`load_cases(path: str) -> list[DesignCase]`**（`design/cases.py:89-93`）：按扩展名 `.csv`→`_load_csv`，其余→`_load_xlsx`（默认走 xlsx 分支，非严格校验后缀白名单——**未验证**对 `.xls` 等其它后缀的行为，代码直接 `openpyxl.load_workbook(path, ...)`，非 xlsx 格式的实际报错由 openpyxl 内部产生）。必备列见 `_BASE`（`cases.py:18-19`），duty 列 `Q_kW`/`dT_h_K` 至少一个（`_check_duty_cols`, `cases.py:49-51`）。`P_in_h_kPa`/`P_in_c_kPa` 读入后 ×1e3 转 Pa（`cases.py:40,43`），`Q_kW` ×1e3 转 W（`cases.py:45`）。`case` 列为空的行被跳过（`_row_to_case`, `cases.py:31-32`）。调用方：`cli.py:39`、`ui/quick_design_panel.py:81`。

- **`forward(case, topo, l, t, s, Lx, arrangement="cross", init=None, k_s=K_STEEL, prop_model="const", tol=LTNE_TOL, height=None) -> ForwardResult`**（`design/forward.py:96-154`）：给定完整几何跑一次 LTNE 能量解 + 解析 ΔP，返回 `ForwardResult(T_out_hot, T_out_cold, Q_hot, Q_cold, dP_hot_frac, dP_cold_frac, Re_hot, Re_cold, fields)`（`forward.py:44-49`）。`fields=(Ta,Tb,Ts)` 供 warm-start 续解。`prop_model="mean"` 时跑两趟（入口物性→出口温→均温物性 warm-start 重解），`prop_model="const"` 只跑一趟入口物性（默认，最快）。ΔP **始终**用入口物性算（`forward.py:102,153` 注释："保守安全"）。调用方：`sizing.py` 的 `solve_Lx`/`size_fixed_cell`、`optimize.py`（间接经 `size_fixed_cell`）、`tests/design/test_forward.py`、`tests/design/test_prop_model.py`、`tests/design/test_height_decouple.py`。

- **`dP_fracs(case, topo, l, t, s, Lx, arrangement="cross", height=None) -> (dP_h_frac, dP_c_frac)`**（`design/forward.py:70-89`）：纯解析 Darcy-Forchheimer（不触发 LTNE 解），按流体分派可压（air）/不可压（其余）。调用方：`sizing.py` 的 `_maxnorm_dP`/`_min_Lx_for_dP`、`projects/704-Aircooler-10kW/predict_aircooler_10kw.py`。

- **`size_fixed_cell(cases, topo, l, t, arrangement="cross", rho_s=RHO_S, k_s=K_STEEL, prop_model="const", height=None) -> Design`**（`design/sizing.py:135-286`）：核心定尺算法——对给定 (topo,l,t)，用黄金分割搜 s∈[s_lo, S_MAX]，每个候选 s 的 Lx = max(冷却所需 Lx, 满足两侧 ΔP 所需 Lx)，取 V=s·sz·Lx 最小的可行解；s-搜索阶段只用单个"cooling-governing"工况做代理以省算力（`sizing.py:145` `cool_gov = max(cases, key=_cool_proxy)`），找到 s* 后对**全部**工况做终验。返回 `Design` dataclass（`sizing.py:80-92`）。调用方：`select.py` 的 `enumerate_select`、`optimize.py` 的 `warm_start_joint`、`cli.py`、`ui/quick_design_panel.py`、`tests/design/test_sizing_outer.py` 等。

- **`solve_Lx(case, topo, l, t, s, arrangement, target=None, k_s=K_STEEL, prop_model="const", seed=None, height=None) -> (Lx, ForwardResult) | (None, None)`**（`design/sizing.py:37-76`）：单工况沿 Lx 方向求根（依赖 T_out_hot(Lx) 单调递减假设），优先 `scipy.optimize.brentq`，若 brentq 因端点同号失败则退回稳健二分（`sizing.py:64-75`）。调用方：`sizing.py` 内部 `_Lx_all`/`_eval_s`、`predict_aircooler_10kw.py`、`tests/design/test_sizing_inner.py`、`tests/design/test_prop_model.py`。

- **`enumerate_select(cases, arrangement="cross", nodes=None, rho_s=RHO_S, n_jobs=1, k_s=K_STEEL, prop_model="const", height=None) -> (results, best)`**（`design/select.py:12-37`）：在 `nodes or NODES`（默认 `{"topo":["Diamond","Gyroid"],"l":[4,5,6,7,8],"t":[0.3,0.4,0.5,0.6]}`，`select.py:9-10`，2×5×4=40 组合）网格上枚举跑 `size_fixed_cell`；`n_jobs!=1` 时用 `joblib.Parallel(backend="loky")` 跨候选并行（`select.py:29-34`）。`results` 含全部候选（含不可行），`best` 取可行件中 min-V。调用方：`cli.py:48`、`ui/quick_design_panel.py:96`、`tests/design/test_enumerate_parallel.py`、`tests/design/test_select.py`。

- **`pareto_tags(designs) -> dict[id(Design), list[str]]`**（`design/select.py:39-50`）：只在可行件中标 `"min-V"/"min-wt"/"min-dP"` 三个 tag（对应 `d.V`/`d.weight`/`d.dP_hot_max` 最小者）。调用方：`report.py:52`、`ui/quick_design_panel.py:126`。

- **`warm_start_joint(cases, baseline: Design, arrangement="cross", maxiter=20, rho_s=RHO_S, k_s=K_STEEL, prop_model="const", height=None) -> Design`**（`design/optimize.py:14-42`）：从枚举最优 warm-start，`scipy.optimize.minimize(method="Nelder-Mead")` 在训练凸包内（`df_surrogate/_domain.py` 的 `TRAIN_L`/`TRAIN_T`，即 l∈[4,8]mm, t∈[0.3,0.5]mm，见 `optimize.py:12`）对连续 (l,t) 求 min-V；不可行或不优于 baseline 一律回退 baseline（`optimize.py:40-41`）。调用方：`cli.py:53`（`--refine` opt-in）、`ui/quick_design_panel.py:100`、`tests/design/test_optimize.py`。

- **`write_xlsx(path, results) -> (n_total, n_feasible, n_detail_rows)`**（`design/report.py:50-61`）：双 sheet 输出——"构型汇总"（每构型一行，含不可行，见 `summary_rows`）+ "工况明细"（构型×工况，只含可行件的 `d.percase`，见 `detail_rows`）。调用方：`cli.py:58`、`ui/quick_design_panel.py:462`（导出按钮）。

- **CLI `run(argv=None) -> int`**（`design/cli.py:19-71`）：`--mode {auto,fixed}`，`fixed` 需 `--cell "topo,l,t"`，`auto` 可选 `--nodes "topo:l:t"` + `--refine`。`--jobs` 默认 `-1`（全核）。

## 关键配置项与开关

| 配置项 | 默认值 | 定义处 | 说明 |
|---|---|---|---|
| `S_MAX` | `0.450` m | `sizing.py:21` | 迎风边上限；**在 import 时**从 env `TPMSHX_BUILD_S_MAX` 读取（非运行时可变），注释指出这是为了让 `loky` spawn 的子进程（重新 import 模块）能继承父进程在 import 前设置的宽松上限——运行期修改模块全局 `SZ.S_MAX` 不会传播到已 spawn 的 worker（`sizing.py:16-19`，引用审计 `r2-runs-01`）。 |
| `LX_MAX` | `0.450` m | `sizing.py:22` | 流向长度上限，同上 env 覆盖机制（`TPMSHX_BUILD_LX_MAX`）。 |
| `N_MIN` | `4` | `sizing.py:23` | 每方向最少晶胞数（均质化前提下界），决定 `s_lo = max(0.010, N_MIN*l/1000)`（`sizing.py:146`）。 |
| `SIZING_TOL` | `1e-4` | `sizing.py:25` | 定尺搜索期 LTNE 残差容差（松），终点用 `LTNE_TOL`（紧）收紧——"渐进收紧"策略。 |
| `LTNE_TOL` | `1e-5` | `forward.py:14` | 终点 LTNE 收敛阈；`forward()` 默认参数。 |
| `GOLDEN_IT` | `10` | `sizing.py:26` | min-V over s 的黄金分割迭代步数。 |
| `S_REFINE_TOL` | `0.004` m (4mm) | `sizing.py:27` | s 区间收敛阈，达到即提前退出黄金分割循环。 |
| `N_DP` | `40` | `sizing.py:28` | `_min_Lx_for_dP` 内定 Lx 的解析 ΔP 扫描点数（升序扫描找首个达标点）。 |
| `DP_DEGEN_FRAC` | `0.30` | `sizing.py:14` | 单侧归一化压损超过此值 → 标记"退化"警告（压降接近进口压，可能超音速/迎风缩崩前兆），**只是告警标记，不改变可行性判定**（见 `sizing.py:279-280` 只 `warns.add(...)`，未 return False）。 |
| `GEOM_N` | `128` | `forward.py:26` | TPMS 几何体素化分辨率；注释给出 N=128 vs 256 的 eps 漂移<0.08%、A_0 漂移<0.5%，代价是内存 8×↓，专为并行枚举场景（各进程独立 `lru_cache`，N=256 会导致 16 进程 MemoryError）设计。 |
| `_ARR["cross"]` | `dirB=2, ny=NY_CROSS(40), nz=1, alpha=0.7, maxit=8000, qtol=SIZING_QTOL(1e-4), chunk=SIZING_CHUNK(100)` | `forward.py:37-38` | 叉流用 2D 内核（Nz=1，塌维），欠松弛 α=0.7，配 G2 自适应早停。 |
| `_ARR["counter"]` | `dirB=1, ny=1, nz=2, alpha=0.3, maxit=20000, qtol=None, chunk=None` | `forward.py:39-40` | 逆流走 3D 内核（Nz=2）+ 低 α=0.3 欠松弛阻尼；早停参数刻意留 `None`（内核默认），注释称小 chunk 在欠松弛慢漂场景下实测 3.3K 误判早停偏差（`forward.py:34-35`）。 |
| `NX, NY_CROSS` | `60, 40` | `forward.py:13` | 叉流内核网格分辨率。 |
| `K_STEEL` | `16.0` W/(m·K) | `forward.py:12` | 默认固体热导率（304 不锈钢），可被 `k_s` 参数覆盖。 |
| `RHO_S` | `7900.0` kg/m³ | `sizing.py:78` | 默认固体密度（304SS）。 |
| `NODES`（枚举网格） | `{"topo":["Diamond","Gyroid"],"l":[4,5,6,7,8],"t":[0.3,0.4,0.5,0.6]}` | `select.py:9-10` | 默认 2×5×4=40 构型；注释指出 l=7/t=0.6 超出闭合训练节点 `{4,5,6,8}`/`{0.3,0.4,0.5}`，属外推低置信（`select.py:7-8`）。 |
| CLI `--rho-s` | `7900.0` | `cli.py:29` | 同 `RHO_S`。 |
| CLI `--k-s` | `16.0` | `cli.py:31` | 同 `K_STEEL`。 |
| CLI `--prop-model` | `const` | `cli.py:33` | `const`=入口温物性（快，默认）；`mean`=均温两趟（消大-ΔT 偏置，约 1.5× 耗时）。 |
| CLI `--jobs` | `-1`（全核） | `cli.py:35` | 枚举并行核数，走 `joblib loky`。 |
| UI 默认物性模型 | 中文下拉"均温"（控件缺失兜底值） | `ui/quick_design_panel.py:39` | **与 CLI 默认不同**：CLI 默认 `const`。`_gather_inputs` 在控件缺失时回退字符串 `"均温"`→映射为 `mean`（`quick_design_panel.py:38-40`）；**未验证**实际 UI 面板下拉框的初始选中项是否也是"均温"，只核实了代码里"控件缺失时的兜底默认值"。 |
| UI 默认布置 | `counter`（逆流，控件缺失兜底值） | `ui/quick_design_panel.py:51` | **与 CLI 默认不同**：CLI `--arrangement` 默认 `cross`（`cli.py:26`）。 |

## 边界·假设·适用范围

- **单位约定**：`DesignCase` 内部一律 K/Pa/(kg/s)/W；输入 xlsx/csv 表列名标注 `_kPa`/`_kW` 后缀，loader 显式做单位换算（`cases.py:40,43,45`）。晶胞尺寸 `l`、壁厚 `t` 全程用 **mm**（贯穿 `sizing.py`/`forward.py`/`select.py`/`cli.py` 的 `l,t` 参数），而几何/流道尺寸 `s`、`Lx`、`height` 用 **m**——两套量纲在同一调用链里混用（例如 `cli.py:64-65` 用 `s*1e3`/`Lx*1e3` 打印 mm），是常见踩坑点（对齐仓库 CLAUDE.md 的"TPMS cell size and wall thickness are in mm"提示）。
- **速度是 interstitial（孔隙内）速度**：`_hvol()` 里 `u = mdot/(p.rho*A_flow)`，`A_flow = eps_A*span1*span2` 已扣除孔隙率（`forward.py:54-55`），符合仓库"velocities are interstitial"硬约定。
- **能量-动量强耦合被绕开（design 专属简化，非主管线行为）**：如"定位与功能"节所述，`forward()` 用解析 plug 速度喂给 LTNE 能量方程，ΔP 单独用解析 D-F 算，二者不迭代耦合、不共享收敛判据。这是有意的性能取舍（docstring 自陈"无 SIMPLE 动量"），意味着 design 工具给出的 T_out/Q 与 ΔP 在物理上是**弱自洽**的——若某工况处于强可压缩/近临界状态，二者可能不再互相一致。**未验证**这种解耦在何种 Re/ΔP 范围内引入多大误差；代码里没有交叉校核。
- **无 choke/正压合法性守卫**：不调用 `solvers/envelope.py`；`predict_dP_compressible` 走等温可压缩 D-F 一维解析式，调用侧（`design/forward.py`/`design/sizing.py`）未做马赫数或出口绝压检查。**未在本次审阅范围内逐行核实** `df_surrogate/predict.py:256` 附近 `predict_dP_compressible` 内部对 `P_out²<0` 情况的处理方式。
- **叉流 vs 逆流的迎风面积几何依赖不同**：叉流冷侧迎风 = Lx·sz（随 Lx 变化，`forward.py:82-84`），故 `sizing.py` 文档强调"冷侧 dP 紧时须加厚 Lx，不能只取冷却最小值"（`sizing.py:2-3`）；逆流冷侧迎风 = s×sz（与 Lx 无关，`forward.py:85-86`）。两种布置在 `_ARR` 里走不同数值内核（2D vs 3D，见上表），这是注释里记录的**已知的、经过实证的必要设计**（`forward.py:28-35` 记录了逆流走 2D 内核会出极限环、水出口 347↔357K 跳变、能量不平衡 7-33% 的实证）。
- **Nu/ΔP 关联式的验证域外推**：`fluids.nu_re_window(fluid)` 给出各流体的 Re 拟合窗（air `(400,16000)`、water 拓扑专属、sco2 `(9000,41000)` 仅 Diamond），`sizing.py:274-278` 在终验阶段检查全部工况的 Re 是否落在窗内，超出则在 `Design.validity` 里打 `"热Re↓外推"` 等标记，**但不阻止该构型被判定为可行**——只是信息性标注，不改变 `feasible` 布尔值。
- **sCO2 支持标记为"粗糙"**：`fluids.py:53` 明确称 design 工具对 sco2 变物性/近临界处理粗糙，正式定尺应改用 `projects/703-sCO2-D76/size_sco2_703.py`（焓基）。`fluid_nu()` 对 sco2 的 `nu_sco2_topo` 拟合域标注为"仅 Diamond"（`fluids.py:12,26-27`），**未在本次审阅中打开 `nu_sco2_topo` 实现逐行核实其对非 Diamond 拓扑的具体报错/回退行为**。
- **构建体积上限 450mm 是 AM（增材制造）工艺约束，非物理约束**：`S_MAX`/`LX_MAX` 默认 0.450m，来自"AM build limit"注释（`sizing.py:20`），可用环境变量放宽（见配置表），`projects/704-Aircooler-10kW/predict_aircooler_10kw.py` 有"预测模式：放开 450mm AM 包络"的用法示例（该脚本头部注释要求**必须在 `import design.sizing` 之前**设置环境变量，因为读取发生在模块 import 时）。
- **s-loop 用单工况代理，非全工况联合优化**：`size_fixed_cell` 的黄金分割搜索阶段只用 `_cool_proxy()`（0-D 无解代理，`sizing.py:94-98`）选出的"cooling-governing"工况做 LTNE 迭代，其余工况的 ΔP 靠解析式检查（`_maxnorm_dP`），只有找到 s* 之后才对全部工况做一次终验（`_allK`）；若终验发现 s* 处不可行（governing 代理与全工况边界有缝隙），代码用指数扩张+二分补救（`sizing.py:230-257`），这是**已知的近似算法，非精确联合优化**（注释自陈见 `sizing.py:226-229`）。

## 可扩展接口

- **`arrangement` 只支持两个字面值 `"cross"/"counter"`**：`_ARR` dict（`forward.py:36-41`）是唯一分派点，新增布置需要同时在 `forward.py` 的 `_ARR`、`dP_fracs`（`arrangement=="cross"` 分支，`forward.py:83-86`）、`cli.py` 的 `choices=["cross","counter"]`（`cli.py:26`）三处添加分支——**没有 backend 注册机制，纯 if/dict 分派**。
- **`prop_model` 只支持 `"const"/"mean"`**：`forward()` 内部 `if prop_model == "mean":`（`forward.py:148`）硬编码两趟逻辑，无插件点；新增第三种物性策略（如多趟迭代收敛）需要改 `forward()` 本体。
- **`height` 参数（矩形迎风）是 opt-in 的"钩子"**：默认 `None`→方形（`sz=s`），非 None 时解耦迎风高度与搜索宽度 `s`（`forward.py:106`、`sizing.py:143-144`）。UI 侧通过复选框 `chk_qd_rect` 控制（`ui/quick_design_panel.py:43-47`），**CLI 没有对应的 `--height` 参数**（已核实 `cli.py` 全文无 `height` 字样），即 CLI 路径始终方形，`height` 目前只能通过直接调用 Python API（`size_fixed_cell(..., height=...)`）或 UI 使用。
- **`init`/`seed` warm-start 续解链**：`forward(init=...)`、`solve_Lx(seed=...)`、`size_fixed_cell` 内部 `state["seed"]` 贯穿 s-loop 与全工况终验（`sizing.py:154,161,215,221`），是性能优化钩子，调用方若绕过 `size_fixed_cell` 直接拼装 `forward`/`solve_Lx` 需自行维护该链条。
- **私有 kwargs / 内部命名约定**：`_hvol`、`_dp_one`、`_cold_outlet`、`_one_pass`（`forward.py`），`_cool_proxy`、`_maxnorm_dP`、`_Lx_all`、`_min_Lx_for_dP`、`_eval_s`、`_dh_min`、`_allK`（`sizing.py`）均为模块内下划线前缀私有函数，非公开 API；但 `tests/design/test_converge_fast.py` 直接导入 `_hvol`、`_ARR`（下划线私有符号被测试直接引用），说明这些"私有"函数实际上是半公开的测试锚点，修改签名需同步改测试（`tests/design/test_converge_fast.py:6`）。
- **环境变量钩子**：`TPMSHX_BUILD_S_MAX`、`TPMSHX_BUILD_LX_MAX`（`sizing.py:21-22`，import 时读取，见上）。design 工具间接依赖的 `predict_dP_compressible`（`design/forward.py:_dp_one` 直接调用）支持 `TPMSHX_DF_RESIDUAL_CORR=1` 残差学习修正开关，该 env var 对 design 路径同样生效（**未在本模块范围内逐行核实其实现细节，属 `df_surrogate` 模块，见其 docstring 提及**）。
- **`nodes` 参数是运行时可覆盖的枚举网格**，非硬编码：`enumerate_select(nodes=...)`、CLI `--nodes "topo:l:t"`（`cli.py:13-17` `_parse_nodes`）、UI 面板文本框（`quick_design_panel.py:57-61`）均可替换默认 `NODES`，是"新增拓扑/网格密度"的标准扩展点，不需要改代码。
- **`fluids.py` 是薄适配层，真正的 backend 注册点在 `solvers/fluid_props.py` 的 `FLUIDS` 字典**（`solvers/fluid_props.py:88`）：design 工具本身不提供新增流体的机制，新增流体需要改 `solvers/fluid_props.py` + `solvers/nu_correlations.py`，design 层会自动透传（`fluids.py:43` `_registry.get(fluid)` 对未知流体 `raise ValueError`）。

## 已知不足与 TODO

全文 grep `TODO|FIXME|NotImplementedError|XXX` 在 `sjtu_tpmshx/design/*.py` 内**零命中**（已核实），即代码里没有显式标记的未完成项；以下是从注释/结构里推断出的隐性缺口：

- **CLI 缺少 `--height` 开关**：矩形迎风功能只能通过 UI 或直接 Python API 使用（见"可扩展接口"节），CLI 用户无法从命令行触发。
- **s-loop 单工况代理算法在边界附近需要二次二分补救**（`sizing.py:230-257` 的 `if Lx_star is None:` 分支），代码注释承认这是"governing≈全-K，差几 mm"的已知近似缺口，用指数扩张+12 步二分补到 ~1.5mm 精度，而非从根本上消除代理近似误差。
- **`brentq` 求根失败的兜底二分不校验端点符号**（`sizing.py:64-75` 注释："退回稳健二分 (不校验端点号)"），依赖"T_out 随 Lx 单调递减"假设——若该假设在某工况下不成立（如注释提到的"冷却临界点/小 LMTD"场景），此处逻辑可能给出误导性结果而不报错。
- **能量-动量解耦、无 choke 守卫**（详见"边界·假设"节）是设计工具与主管线（`solvers/simple_solver*.py` + `solvers/envelope.py`）在物理保真度上的系统性差距，属于工具定位使然（追求速度），而非疏漏，但移植/维护者需要清楚这不是主管线的降阶版，二者的收敛判据和合法性保证并不等价。
- **UI 与 CLI 的默认值不一致**（`prop_model` 默认 CLI=`const`/UI=`mean`，`arrangement` 默认 CLI=`cross`/UI=`counter`，见配置表），未见代码注释解释此不一致是否有意——**存疑**，移植时建议向用户确认哪个是"正确"默认。
- **`dPlim_h`/`dPlim_c` 缺乏非零校验**：`sizing.py` 的 `_dh_min`/`_maxnorm_dP` 等函数把 `dPlim_h`/`dPlim_c` 当除数用（如 `sizing.py:105` `dc/c.dPlim_c`），而 `cases.py` 的 `_row_to_case`（`cases.py:29-47`）只做 `float()` 转换、无范围检查——若输入表 `dPlim_h==0`，理论上会触发 `ZeroDivisionError`。**未验证**实际运行时是否有其它路径提前拦截该输入。

## 服务器移植注意

> 目标平台是 **Windows Server 2022**，与开发机同为 Windows（此前一版文档误判为 Linux 移植，本节已按实际目标重新核实）。以下逐条只保留在"Windows → Windows Server"迁移下仍然成立的风险点；纯粹因 Linux 假设而产生的条目已标注不适用。

- **不适用（同为 Windows，无需处理）**：Excel I/O 用 `openpyxl`（`cases.py:6`；`report.py` 经 `pandas.ExcelWriter(engine="openpyxl")`，`report.py:58`），符合仓库约定"Excel: always engine='openpyxl'"，纯 Python 依赖，不涉及任何平台判断，无需为移植改动。
- **CSV 读取假定纯 UTF-8-with-BOM，GBK 坑不会因为留在 Windows 而消失，反而是中文 Windows Server 上的真实风险**（`cases.py:72` 硬编码 `encoding="utf-8-sig"`，已核实 `cases.py` 全文只有这一处 `open()` 调用，无编码探测/回退逻辑）。中文区域设置下用 Excel 另存为传统"CSV（逗号分隔）"而非"CSV UTF-8"时，实际写出的字节流是系统 ANSI 代码页（简体中文 Windows 下即 GBK/cp936），不是 UTF-8——此时 `encoding="utf-8-sig"` 会在非 ASCII 字符处直接抛 `UnicodeDecodeError`，而不是静默乱码，容易在服务器批处理里被误判为"数据坏了"而非编码问题。这与是否迁移到 Linux 无关，只要工况表来自 Windows 环境下的传统 CSV 导出就会出现；建议要么在操作规程里明确要求"另存为 CSV UTF-8"，要么在 `_load_csv` 增加 `utf-8-sig` 失败后回退 `gbk` 的探测（当前未实现）。**未验证**：CLI/UI 上游是否已有独立的编码校验拦截此类输入。
- **`joblib` + `loky` 的 import-顺序约束在 Windows Server 上是刚性要求，不是"两种平台都凑合能用"**（`select.py:29-34`；`sizing.py:16-19` 注释：env var 必须在 import `design.sizing` 之前设置，才能被 `loky` spawn 出的子进程继承）。Windows（含 Windows Server）没有 `fork()`，`multiprocessing`/`loky` 在其上只能用 `spawn`，子进程必然重新 `import design.sizing` 并在导入时经 `os.environ.get(...)` 重新读一次环境变量后冻结到模块全局（`sizing.py:21-22`）——这恰好满足该约束的前提条件，因此实现在 Windows Server 上按设计正确工作，不需要为移植改动代码；但若调用方在同一进程内先 `import design.sizing` 再改 `os.environ`，改动依然不会传给已经 spawn 出去的 worker（这是该约束本身的含义，与目标平台无关，Linux 对比已不再必要，故删去）。
- **无 GUI 强依赖，适配无交互桌面会话的 Windows Server**：`design/` 目录本体不 `import PySide6`/Qt（已用 grep 核实 `design/*.py` 无 `PySide6`/`Qt` 字样）；GUI 集成层在 `sjtu_tpmshx/ui/quick_design_panel.py`，该文件把 `from PySide6.QtCore import QThread, Signal` 放在函数体内懒加载（`ui/quick_design_panel.py:69`）。因此只要走 CLI（`design/cli.py`）或直接 Python API，`design/` 包在无显示会话的 Windows Server（含 Server Core 或无人值守跑批）上可直接使用，不涉及任何 Qt 显示层，这一点与目标是 Windows Server 还是 Linux 服务器无关。若未来调用链确实要经过 `ui/quick_design_panel.py` 触碰 Qt，仓库已有的 `QT_QPA_PLATFORM=offscreen` 约定（已用 grep 核实见于 `main.py`、`tests/conftest.py` 及多个 `runs/smokes/*.py`）是 Qt offscreen 平台插件的标准环境变量，Windows 与 Linux 上注册机制相同，**不是 Linux/X11 专属方案**，可直接沿用，不需要为 Windows Server 另写处理。
- **不适用（同为 Windows，无需处理）**：`cases.py`/`sizing.py`/`select.py`/`report.py` 用 `os.path.splitext`/相对导入，未见反斜杠或盘符路径字面量——原文档此处是在提防"路径分隔符在 Linux 上不兼容"的风险，既然开发机与目标机同为 Windows，这一路径分隔符对比已不成立，直接删去对比性描述；`sizing.py:21-22` 的 `TPMSHX_BUILD_S_MAX` 等环境变量读取方式不受影响。
- **依赖链核实：`design/` 直接依赖只是 `scipy.optimize`（`brentq`/`minimize`）与 `numpy`，但 `forward.py` 经 `solvers.ltne_energy_3d.solve_full_domain_3d`（`forward.py:8`）间接引入 `numba`（`ltne_energy_3d.py:27` `from numba import njit, prange`）与可选的 `pyamg`（`ltne_energy_3d.py:58` `import pyamg`）——不只是"scipy/numpy 这两个标准包"**。已核实仓库根目录 `requirements.txt` 锁定版本且明确标注"Tested on Windows 11 + Python 3.11/3.12"：`numpy>=2.0`、`scipy>=1.13`、`pyamg>=5.2`、`numba>=0.60`；这几个包在 PyPI 均发布 Windows amd64 wheel（`numpy`/`scipy`/`pyamg` 是纯二进制 wheel，`numba` 自带打包好的 `llvmlite`，不需要本机另装 LLVM 工具链），因此在 Windows Server 2022 上 `pip install -r requirements.txt` 预期可直接装好，不存在 apt 等价物这类概念，也通常不需要额外编译工具链。**未验证**：本次未在 Windows Server 2022 实机执行安装做二次确认；若目标机 Python 版本落在 3.11/3.12 之外，或是 ARM64 版 Windows Server，需要重新核实这几个包的 wheel 覆盖范围。
- **并行进程数默认 `-1`（全核）**：`select.py` 的 `n_jobs=-1` 语义由 `joblib` 决定（通常映射为可用 CPU 核数），在虚拟机/共享服务器环境下可能需要显式限制核数以避免与其他任务抢占 CPU——这是运维层面的注意事项，非代码缺陷，与具体是哪种服务器操作系统无关。
