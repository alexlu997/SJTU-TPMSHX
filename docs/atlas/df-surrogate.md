# df_surrogate
生成日期 2026-07-10，基于 commit f33d30e 附近的 master

> 本文档所有断言均以代码为唯一真源，每条附 file:line 溯源（行号对应上述 commit 附近的工作树）。无法在代码中核实的内容一律标注「未验证」。

## 定位与功能

`sjtu_tpmshx/df_surrogate/` 是 Darcy-Forchheimer（D-F）压降闭包的代理模型包：输入 TPMS 几何参数 (tpms_type, L_mm, t_mm, eps_f)，输出渗透率 K [m²] 与 Forchheimer 惯性系数 c_F [1/m]，供 SIMPLE 求解器的多孔阻力源项 `μ/K·u + ρ·c_F·|u|·u` 使用（消费端示例：`sjtu_tpmshx/solvers/_kernels_simple_2d.py:161-170`）。

包内含两个可切换 backend（`gamma_df` 与 `rbf`，注册表在 `sjtu_tpmshx/df_surrogate/backend.py:34`），一个 1D 可压缩等温 D-F 压降公式（`P_out² = P_in² − 2·R·T·(μG/K + c_F·G²)·L`，`sjtu_tpmshx/df_surrogate/predict.py:278-279`），以及若干后置修正层（末端标定 override、sCO2 有效 c_F 标度、非对称 κ 修正、可选残差学习修正）。

**核心不变量（与仓库 CLAUDE.md 一致，已在代码核实）：两个 backend 的 c_F 均已内嵌 SLM 表面粗糙度，下游严禁再叠乘摩擦/粗糙度系数。** 实现位置见「边界·假设·适用范围」节。

## 文件一览

| 文件 | 职责（一行） |
|---|---|
| `__init__.py` | 仅 docstring，无导出（`sjtu_tpmshx/df_surrogate/__init__.py:1`） |
| `backend.py` | backend 注册表 + 抽象基类 `DFBackend`；`gamma_df` / `rbf` 两个适配器及其各自的向量化路径与 K clamp 语义 |
| `predict.py` | 对外推断 API（`predict_K_cF` 等）、backend 选择（env `TPMSHX_DF_METHOD`）、末端标定 override 层、`SCO2_CF_SCALE`、choke 处理 |
| `gamma_df.py` | 生产默认模型 `GammaDF`：c_F = 光滑 CFD 基面 × 实验锚定粗糙度因子 γ；K = CFD-refit 渗透率面（2026-06-30 起） |
| `surrogate_v3.py` | `rbf` backend 的模型 `SurrogateV3`：对实验 Δp 做可压缩 WLS 标定后 RBF 插值；含 `eval_shanghai` / `eval_loo` 评估器与 `plhub_gp` 实验分支 |
| `smooth_df.py` | 光滑壁（无粗糙度）D-F 模型 `SmoothDF`（水+空气 CFD 40 几何拟合）及其预构建表的重建脚本 |
| `residual_correction.py` | 可选残差学习层：在 (log₁₀Re, eps_f) 空间 RBF 拟合 rbf baseline 的相对残差，乘性修正 dP，不改 K/c_F |
| `kappa_asym.py` | 非对称孔隙率（ε_A ≠ ε_B）每侧 κ 修正的运行时表：`X_asym = κ_X(r)·X_sym`，默认恒等 |
| `ingest_cfd_kappa.py` | 从外部 Fluent 每侧批跑 CSV 拟合 κ_K(r)/κ_cF(r) 单调插值表并注册到 `kappa_asym` |
| `load_data.py` | 从训练 Excel 读 f-Re 训练数据 + 附加几何量 + 上海数据防泄漏三重守卫 |
| `_domain.py` | 训练窗口常数单一真源（TRAIN_L/T/RE 及离散节点），纯常数零 import |
| `surrogate_domain.py` | 训练窗口点检查 `check_surrogate_domain_at_point`（越界 raise 或 warn） |
| `build_prebuilt_surrogate.py` | 在有原始 Excel 的机器上把标定结果序列化为 `_prebuilt/*.csv` 的一次性脚本 |
| `_prebuilt/` | 4 个已提交 CSV：`Diamond_surrogate_ref.csv` / `Gyroid_surrogate_ref.csv`（各 12 几何标定点）、`df_cfd_coeffs.csv`（40 几何 CFD-refit K/cF）、`smooth_df_coeffs.csv`（40 几何 SmoothDF 系数） |

## 公开接口

### backend 注册/切换机制（`backend.py`）

- `_REGISTRY: dict[str, type]`（`sjtu_tpmshx/df_surrogate/backend.py:34`）与实例缓存 `_CACHE`（键 `(tpms_type, method)`，`backend.py:35`）。
- `register(name)` 类装饰器（`sjtu_tpmshx/df_surrogate/backend.py:38-44`）；`available_methods()`（`backend.py:47`）；`get_backend(tpms_type, method)` 返回缓存实例，未知 method 抛 `ValueError`（`backend.py:51-61`）。
- `class DFBackend(ABC)`（`sjtu_tpmshx/df_surrogate/backend.py:64`）：接口 `(L_mm, t_mm, eps_f) → (K, c_F)`；`predict_vec` 通用回退为逐元素循环（`backend.py:80-89`）；`__getattr__` 把未知属性透传给被包裹模型供诊断（`backend.py:91-93`）。
- **当前注册的 backend 只有两个**：`@register('gamma_df') class GammaBackend`（`sjtu_tpmshx/df_surrogate/backend.py:96-114`，向量化 = 按唯一 (L, t) 对缓存标量预测）与 `@register('rbf') class RBFBackend`（`backend.py:117-133`，向量化 = 原生批量 RBF 求值 + backend 内部 K clamp `K_min=1e-8`，见 `backend.py:131`）。测试守卫 `assert set(available_methods()) == {'gamma_df', 'rbf'}`（`sjtu_tpmshx/tests/test_df_backend_registry.py:88`）。
- **`cfd_refit` 不是现存 backend**：曾短暂存在，2026-06-30 其 K 面被折入 `gamma_df` 后移除（测试注释 `sjtu_tpmshx/tests/test_df_backend_registry.py:86-87`；`sjtu_tpmshx/domain/compute_config.py:86` 仍写「gamma_df | rbf | cfd_refit…」，属过时文档，以注册表为准）。
- 注册契约（docstring 约定，非代码强制）：新 backend 或默认切换必须过 Shanghai 3D 门（`validation/cases/validate_shanghai_3d_real.py`）+ D_7_6 门；仅训练域指标不作数（`sjtu_tpmshx/df_surrogate/backend.py:16-22`）。

### 推断 API（`predict.py`）

- `predict_K_cF(tpms_type, L_mm, t_mm, eps_f, method=None) -> (K, c_F)`（`sjtu_tpmshx/df_surrogate/predict.py:196-208`）。c_F 无条件经过 override 层 `_apply_override`（`predict.py:208`）——但 override 表当前为空（见下）。调用方：`sjtu_tpmshx/solvers/simple_solver.py:43`、`sjtu_tpmshx/solvers/tpms_calc.py:57`、`sjtu_tpmshx/pipelines/run_stack_3d.py:26,492`、`sjtu_tpmshx/solvers/polygon_fvm.py:29`、`sjtu_tpmshx/main.py:540`（启动预热）、验证脚本等。
- `predict_K_cF_vec(tpms_type, L_arr, t_arr, eps_arr, method=None)`（`sjtu_tpmshx/df_surrogate/predict.py:211-242`）：形状无关（broadcast 后 ravel，按 backend 各自的 `predict_vec` 求值再 reshape）。**向量化路径不经过标量 override 层**（`predict.py:92-93` 注释；`test_df_backend_registry.py:48-50`）。调用方：`sjtu_tpmshx/optimization/evaluator.py:221`、`sjtu_tpmshx/solvers/df_projection.py:16`、`sjtu_tpmshx/pipelines/run_stack_3d.py:476`、`sjtu_tpmshx/solvers/simple_solver.py:43`。
- `predict_dP(...)` 不可压 D-F（`sjtu_tpmshx/df_surrogate/predict.py:245-253`）；`predict_dP_compressible(..., strict=False, method=None)` 1D 可压缩等温 D-F（`predict.py:256-319`）。choke（P_out²≤0）时：`strict=True` 返回 NaN，默认返回 P_in 并发一次性 warning（`predict.py:280-295`）。调用方：`sjtu_tpmshx/design/forward.py:9,66`。
- `reset_choke_warn_registry()`（`sjtu_tpmshx/df_surrogate/predict.py:64-67`）：重置一次性 choke warning 注册表；调用方 `sjtu_tpmshx/controllers/compute_pipeline.py:114-116`（每次 pipeline 运行开始）。
- `SCO2_CF_SCALE = 3.39`（`sjtu_tpmshx/df_surrogate/predict.py:140`）：sCO2 有效 c_F 乘子（D-7-6 全耦合场标定）。**注意：这不是在 predict_K_cF 内部生效的，由消费方自行乘**：`sjtu_tpmshx/pipelines/solve_2d.py:921-923`、`sjtu_tpmshx/pipelines/run_stack_3d.py:515-516,609-610`、`sjtu_tpmshx/solvers/tpms_calc.py:57`。仅 Diamond 7/0.6 单几何标定，跨 (L, t) 迁移性代码注释明示 UNVERIFIED（`predict.py:137-139`）。

### GammaDF（`gamma_df.py`，生产默认模型）

- `class GammaDF(tpms='Gyroid', smooth=None)`（`sjtu_tpmshx/df_surrogate/gamma_df.py:113-145`）：仅支持 Diamond/Gyroid，否则 `ValueError`（`gamma_df.py:118-119`）。构造时：(a) 建 `SmoothDF` 光滑基面；(b) 实例化 `SurrogateV3` 取实验锚点 c_F（col47 约定，`gamma_df.py:126-129`）；(c) 只用 L∈{6,8} 可信层锚点拟合 γ 的 t 方向模型（`_TRUSTED_L=(6,8)`，`gamma_df.py:86`）；(d) Gyroid 用 `GATE_CF_G7=534.8` 做 L7 上海标定点（`gamma_df.py:85,141-142`）；(e) 从 `_prebuilt/df_cfd_coeffs.csv` 建 CFD-refit K 面（log 空间 thin-plate-spline over (log L, log t)，`gamma_df.py:93-110,145`）。
- `predict(L_mm, t_mm, eps_f=None) -> (K, c_F)`（`sjtu_tpmshx/df_surrogate/gamma_df.py:246-256`）：**`eps_f` 形参仅为接口兼容，被忽略**——几何由 (L, t) 内部推导；`cF = cf_smooth(L,t) × gamma(L,t)`（`gamma_df.py:255`），K 来自 CFD-refit 面（`gamma_df.py:253-254`）。因此 `GammaBackend.predict_vec` 只按唯一 (L, t) 对缓存（`backend.py:108-113`），eps 数组不参与。
- `gamma(L_mm, t_mm)`（`sjtu_tpmshx/df_surrogate/gamma_df.py:209-217`）：L 先 clip 到 [4, 8]；L≥6 走可信区（Gyroid 过 (L6, L7标定, L8) 的 log 二次；Diamond L6→L8 log 线性，`gamma_df.py:196-203`）；L≤5 走 flat6 + `max(1,·)` 地板（地板仅在低 L 外推区，`gamma_df.py:205-207`）；5<L<6 线性混合。`lowL_band` 给 L≤5 的 (1, Colebrook 外推) 声明带（`gamma_df.py:219-243`）。

### SurrogateV3（`surrogate_v3.py`，`rbf` backend 的模型）

- `class SurrogateV3(tpms='Gyroid', K_min=None, *, method='rbf', clip_margin=0.1, standardize=False, features=(...))`（`sjtu_tpmshx/df_surrogate/surrogate_v3.py:126-166`）。`method` 只允许 `('plhub_gp', 'rbf')`（`surrogate_v3.py:103,131-132`）；`plhub_gp`（Huber 幂律趋势 + GP Matern 残差）是训练域指标优胜但被端到端证伪的对照分支，未接入 backend 注册表（`surrogate_v3.py:13-27`）。
- 双数据源：训练 Excel 存在时走 `_build()`（权威标定），否则回退 `_build_from_prebuilt()` 读已提交 CSV（`sjtu_tpmshx/df_surrogate/surrogate_v3.py:156-166,379-400`）；来源写入 `self._source` 并记日志。CSV 回退时 `rows_df` 为空 → 残差修正路径不可用（`surrogate_v3.py:383-385,396`）。
- 标定算法（`_build`，`sjtu_tpmshx/df_surrogate/surrogate_v3.py:168-283`）：逐几何对 raw dP（col43）+ G=ρ·v（col12×col13，`surrogate_v3.py:203-205`）做可压缩 WLS `(P_in²−P_atm²)/(2RT·L_ch) = μG/K + c_F·G²`（`surrogate_v3.py:239-243`）；乘边界效应系数 alpha（`c_F×α`、`K/α`，`surrogate_v3.py:245-247`）；c_F 地板 1.0（`surrogate_v3.py:252`）；L=8 剔除 Re<1600（`surrogate_v3.py:216`）；对 log₁₀K / log₁₀c_F 建 cubic RBF（smoothing=0.1，`surrogate_v3.py:366`）。通道长 `L_ch = K_S_CELLS·L_mm·1e-3`，`K_S_CELLS=10`（`surrogate_v3.py:80,235`）。
- `predict` 标量路径 K clamp 到 `K_min`（rbf 默认 1e-8，`sjtu_tpmshx/df_surrogate/surrogate_v3.py:83,139-140,435`）。
- `dump_prebuilt(path=None)` 全精度（`%.17g`）序列化标定点（`sjtu_tpmshx/df_surrogate/surrogate_v3.py:402-414`）。
- 评估器：`eval_shanghai(model)`（上海 16 工况，A_FLOW=36×18.0565e-6 m²、L_DOM=0.182 m 硬编码常数，`sjtu_tpmshx/df_surrogate/surrogate_v3.py:485-538`）、`eval_loo(model)`（留一几何，`surrogate_v3.py:541-604`）——两者都依赖 gitignored 原始 Excel。

### SmoothDF（`smooth_df.py`）

- 模型形式 `dp/L = μu/K + ρ·B·(Re/1000)^(−m_lat)·u²`（`sjtu_tpmshx/df_surrogate/smooth_df.py:3`）。`predict_K_B` / `predict_cF(Re)` / `predict_dpdl` / `predict_dP`（`smooth_df.py:100-135`）。构造需要 `_prebuilt/smooth_df_coeffs.csv`，缺失则 `FileNotFoundError`（`smooth_df.py:76-79`）；B 残差 RBF 带数据凸包外的 trust-region 衰减（`smooth_df.py:107-111`）。作用域为光滑壁 CFD，明确不是生产粗糙面模型（`smooth_df.py:24-29`）。GammaDF 只消费其 c_F 形状（K 已改由 CFD-refit 面提供）。
- 重建 CLI：`python -m df_surrogate.smooth_df [--air-xlsx PATH]`（`sjtu_tpmshx/df_surrogate/smooth_df.py:215-231`），依赖两份 raw Excel（见「数据文件依赖」）。

### 残差修正（`residual_correction.py`，默认关闭）

- `get_corrector(tpms) -> ResidualCorrector`（缓存单例，`sjtu_tpmshx/df_surrogate/residual_correction.py:201-205`）；`ResidualCorrector.correction(Re, eps_f)` 返回 clamp 到 ±0.6 的乘性修正 g（`residual_correction.py:168-179`，`_G_CLAMP=0.6`:62，RBF thin_plate_spline smoothing=1.0:66,154-157）。
- **backend 匹配守卫**：修正是对 rbf baseline 拟合的，`predict_dP_compressible` 仅当解析出的 method 为 `'rbf'` 时才应用（`sjtu_tpmshx/df_surrogate/predict.py:301-319`，判断在 `predict.py:307`）；独立入口 `predict_dP_compressible_corrected` 强制 `method='rbf'` 建 baseline（`residual_correction.py:238`）。
- 构建需要 `SurrogateV3.rows_df`（原始 Excel 训练行）；点数 <10 直接 `RuntimeError`（`sjtu_tpmshx/df_surrogate/residual_correction.py:148-150`）→ 无原始数据环境（含 CI）此层不可用。

### 非对称 κ（`kappa_asym.py` + `ingest_cfd_kappa.py`）

- `kappa_KcF(tpms_type, eps_side, eps_sym, *, enabled=None) -> (κ_K, κ_cF)`（`sjtu_tpmshx/df_surrogate/kappa_asym.py:39-53`）：三重恒等守卫——env 关（默认）、无 κ 表、r≈1（|eps_side−eps_sym|<1e-12）都返回 (1.0, 1.0)。调用方：`sjtu_tpmshx/pipelines/run_stack_3d.py:499-502`（乘在 `predict_K_cF` 输出上）；2D 侧未接（`sjtu_tpmshx/pipelines/solve_2d.py:814-816` 注释确认 2D 保持对称 K/cF）。
- `set_kappa_table` / `has_table` / `clear`（`sjtu_tpmshx/df_surrogate/kappa_asym.py:56-67`）。**κ 表是模块级内存 dict `_KAPPA`（`kappa_asym.py:29`），不持久化**——每个进程必须重新 `ingest()`。
- `ingest(path)`（`sjtu_tpmshx/df_surrogate/ingest_cfd_kappa.py:54-85`）：读 Fluent 每侧 CSV（列 `tpms, L_mm, t_mm, eps_side, eps_sym, K_cfd, cF_cfd`，`ingest_cfd_kappa.py:5`），以 `predict_K_cF(tpms, L, t, eps_sym)` 为对称锚计算比值，拟合线性插值（端点平延、强制 r=1→κ=1 锚点，`ingest_cfd_kappa.py:37-51`）后注册。CLI：`python -m df_surrogate.ingest_cfd_kappa results.csv`（`ingest_cfd_kappa.py:88-92`）。数据生产端在 `sjtu_tpmshx/runs/cfd_asym/asym_postproc_kappa.py:118`。

### 训练窗口（`_domain.py` + `surrogate_domain.py`）

- 常数：`TRAIN_L=(4.0, 8.0)`、`TRAIN_T=(0.3, 0.5)`、`TRAIN_RE=(400.0, 16000.0)`、`TRAIN_L_NODES=(4,5,6,8)`、`TRAIN_T_NODES=(0.3,0.4,0.5)`（`sjtu_tpmshx/df_surrogate/_domain.py:13-19`）。消费方：`sjtu_tpmshx/design/optimize.py:12`、`sjtu_tpmshx/solvers/continuous_field.py:50`、`sjtu_tpmshx/domain/validator.py:16`、`sjtu_tpmshx/ui/optimize_panel.py:226` 等。
- `check_surrogate_domain_at_point(tpms_type, L_mm, t_mm, k_s, u, T, P=101325.0, side='A', allow_extrap=False, fluid='air')`（`sjtu_tpmshx/df_surrogate/surrogate_domain.py:26-111`）：越界时 `allow_extrap=False` 抛 `ValueError`，否则 warn 并返回 reason 列表；`fluid='sco2'` 时用 CoolProp 真实物性算 Re（延迟 import，`surrogate_domain.py:73-82`）。调用方：`sjtu_tpmshx/pipelines/_stage_common.py:53`。

## 关键配置项与开关

| 开关 | 默认值 | 定义处 | 语义 |
|---|---|---|---|
| `_DF_DEFAULT` | `"gamma_df"` | `sjtu_tpmshx/df_surrogate/predict.py:169` | 全局默认 backend（2026-06-12 由 rbf 切换） |
| env `TPMSHX_DF_METHOD` | 未设 → `_DF_DEFAULT` | `sjtu_tpmshx/df_surrogate/predict.py:172-179` | 全局 backend 选择；每次调用时读取；per-call `method=` 参数优先 |
| env `TPMSHX_DF_RESIDUAL_CORR` | `"0"`（关） | `sjtu_tpmshx/df_surrogate/predict.py:71-77` | 开残差学习修正（仅 rbf backend 生效，`predict.py:307`；需原始 Excel） |
| env `TPMSHX_DF_OVERRIDES` | 未设 → 启用 | `sjtu_tpmshx/df_surrogate/predict.py:112-113` | **on/off 布尔开关**（设 `"0"` 关闭 override 层）；override 表本体是硬编码 dict `_OVERRIDES`，当前为空（`predict.py:96-106`）。注意 `sjtu_tpmshx/domain/compute_config.py:88-89` 将其描述为「JSON per-geometry override table」，与实现不符，以代码为准 |
| env `TPMSHX_ASYM_KAPPA` | `"0"`（关） | `sjtu_tpmshx/df_surrogate/kappa_asym.py:32-36` | 激活非对称每侧 κ 修正（还需先 ingest κ 表） |
| env `TPMSHX_ALLOW_EXTRAP` | 未设（关） | `sjtu_tpmshx/df_surrogate/surrogate_domain.py:65-66` | 训练窗口越界从 raise 降级为 warn |
| `SCO2_CF_SCALE` | `3.39` | `sjtu_tpmshx/df_surrogate/predict.py:140` | sCO2 有效 c_F 乘子（消费方自乘，非 predict 内部） |
| `K_MIN` | `1e-8` | `sjtu_tpmshx/df_surrogate/surrogate_v3.py:83` | rbf backend 的 K 下限 clamp（gamma_df 无 clamp，`backend.py:11-14`）；plhub_gp 分支解析为 1e-12（`surrogate_v3.py:139-140`） |
| `GATE_CF_G7` | `534.8` | `sjtu_tpmshx/df_surrogate/gamma_df.py:85` | Gyroid L7/t0.6 上海标定 c_F（gamma_df 门点与 rbf 构造性一致） |
| `RE_REF` | `2530.0` | `sjtu_tpmshx/df_surrogate/gamma_df.py:84` | γ 锚点求值的参考 Re（生产窗口 400–16000 的几何均值） |
| `_G_CLAMP` / `_RBF_SMOOTHING` | `0.6` / `1.0` | `sjtu_tpmshx/df_surrogate/residual_correction.py:62,66` | 残差修正 clamp 与 RBF 平滑 |
| `_L8_RE_MIN` | `1600.0` | `sjtu_tpmshx/df_surrogate/load_data.py:66` | L=8 几何剔除过渡区低 Re 样本（surrogate_v3 内独立复刻于 `surrogate_v3.py:216`） |
| `R_AIR` | `287.05` | `sjtu_tpmshx/df_surrogate/predict.py:57`（另 `surrogate_v3.py:79`、`residual_correction.py:57` 各有一份） | 空气气体常数 |

### 数据文件依赖

| 文件 | 定义处 | 状态 | 用途 |
|---|---|---|---|
| `data/raw_data/试验记录表_整理版.xlsx`（仓库根） | `sjtu_tpmshx/df_surrogate/surrogate_v3.py:85`、`load_data.py:45` | gitignored；主 checkout 存在，worktree 缺失（已核实） | SurrogateV3 权威标定源（sheet `Gyroid_汇总`/`Diamond_汇总`/`边界效应系数`） |
| `data/raw_data/water-cfd-raw.xlsx` | `sjtu_tpmshx/df_surrogate/smooth_df.py:52` | gitignored | SmoothDF 重建（水 CFD） |
| `D:\Postgraduate\server-pyfluent\Air\Cfd-air-raw-old-new.xlsx` | `sjtu_tpmshx/df_surrogate/smooth_df.py:55-56` | **仓库外硬编码 Windows 绝对路径** | SmoothDF 重建（空气 CFD）；可 `--air-xlsx` 覆盖 |
| `data/raw_data/20260401-上海电气天然气加热器实验工况.xlsx` | `sjtu_tpmshx/df_surrogate/surrogate_v3.py:487-488` | gitignored | 仅 `eval_shanghai` 评估用 |
| `_prebuilt/Diamond_surrogate_ref.csv`、`Gyroid_surrogate_ref.csv` | `sjtu_tpmshx/df_surrogate/surrogate_v3.py:95-99` | **已提交**（各 12 几何行，列 `L_mm,t_mm,eps_f,K,c_F`） | 无 Excel 时重建 SurrogateV3 RBF |
| `_prebuilt/df_cfd_coeffs.csv` | `sjtu_tpmshx/df_surrogate/gamma_df.py:93` | **已提交**（40 行，列 `tp,L,t,K,cF,eps_A,Dh`） | GammaDF 的 CFD-refit K 面（运行时必需） |
| `_prebuilt/smooth_df_coeffs.csv` | `sjtu_tpmshx/df_surrogate/smooth_df.py:51` | **已提交**（40 行，列 `tp,L,t,ef,Dh,logK,logB,m_lat,n_fluids`） | SmoothDF 系数表（GammaDF 构造必需） |

结论：仅推断（gamma_df 与 rbf 两个 backend）在无任何 raw Excel 的干净 clone 上可运行（`_prebuilt/*.csv` 已提交）；重标定、残差修正、`eval_shanghai`/`eval_loo` 需要 gitignored 数据。

## 边界·假设·适用范围

- **单位**：L_mm、t_mm 为 mm（常见陷阱：其余量纲为 SI，K [m²]、c_F [1/m]、P [Pa]、T [K]）。函数签名见 `sjtu_tpmshx/df_surrogate/predict.py:196-198,256-276`。
- **速度约定为 interstitial（孔内）**：G = ṁ/A_void，标定所得 K/c_F 是「有效 interstitial」系数而非教科书 superficial 形式，禁止混用（`sjtu_tpmshx/df_surrogate/surrogate_v3.py:29-37`，训练 G=ρ·v 溯源 `surrogate_v3.py:189-205`）。
- **eps_f 为单通道孔隙率 ε/2**（`sjtu_tpmshx/df_surrogate/load_data.py:152`、`surrogate_v3.py:251`；3D pipeline 调用 `predict_K_cF(..., 0.5*eps)` 见 `sjtu_tpmshx/pipelines/run_stack_3d.py:492`）。GammaDF 忽略此参数（`gamma_df.py:247-250`）。
- **粗糙度已内嵌，禁止叠乘**：(a) gamma_df 的 c_F = 光滑 CFD 基面 × γ，γ 锚点直接取实验（SLM 粗糙试件）与光滑面之比（`sjtu_tpmshx/df_surrogate/gamma_df.py:3,24,131-133`，相乘在 `gamma_df.py:255`）；(b) rbf 直接对实验 Δp 标定（`surrogate_v3.py:206,239-247`）。pipeline 侧的呼应实现：`solvers/roughness.py` 的摩擦增强因子对 `baseline`/`norris_1a` 模式均返回 1.0（`sjtu_tpmshx/solvers/roughness.py:101-119`），即 `run_stack_3d.py:509-510` 的 `_apply_roughness_KcF` 在默认与 norris_1a 模式下对 K/cF 是恒等操作。γ 绑定当前 SLM 打印批次，工艺变更需重标定（`gamma_df.py:50-51`）。
- **几何域**：Diamond/Gyroid 两种 tpms 类型（`sjtu_tpmshx/df_surrogate/gamma_df.py:118-119`；rbf 侧由 `_prebuilt` CSV 覆盖范围决定）。训练窗口 L∈[4,8] mm、t∈[0.3,0.5] mm、Re∈[400,16000]（`_domain.py:13-15`）；gamma 求值时 L clip 到 [4,8]、t 在 [0.3,0.5] 外线性延拓（`gamma_df.py:210,30-31`）；CFD-refit K 面在 5×4 (L,t) 网格外靠 TPS 外推（`gamma_df.py:56-58` docstring 声明，未见额外守卫）。
- **1D 可压缩公式假设等温理想气体（空气 R=287.05）**，choked（P_out²≤0）无实数解——默认路径返回 P_in 兜底并 warn 一次，strict 路径返回 NaN（`sjtu_tpmshx/df_surrogate/predict.py:278-295`）。此公式不适用于水/sCO2（水侧走不可压 `predict_dP`，见 `sjtu_tpmshx/design/forward.py:61-66`）。
- **防泄漏硬约束**：训练集含 t=0.6 mm 或 L=7.0 mm 行、或数据路径含 shanghai/上海 时 `load_all()` 抛 `ValueError`（`sjtu_tpmshx/df_surrogate/load_data.py:164-207,210-221`）——上海 16 工况是预测目标，不许进训练。
- **两条标定链**：`load_data.py`（col47 摩擦压损）供研究脚本；`surrogate_v3._build`（col43 raw dP × α 边界效应系数）是生产 RBF 的实际标定路径。两者读同一 Excel 但列不同——移植时勿混淆。
- 已验证精度声明（docstring 记载，本次未复跑，引用需注明出处）：gamma_df 可信层 LOO 2.5%/2.6%、D7 盲测 454.2 vs ~454（`gamma_df.py:42-47`）；rbf Shanghai 3D dP 7.19%/Q 3.22% 为历史基线，最新门数字随修订漂移，以 `sjtu_tpmshx/validation/_CSV_STATUS.md` 为准（`predict.py:23` 亦如此指示）。

## 可扩展接口

- **backend 注册点**：`@register('name')` 装饰 `DFBackend` 子类即可加入注册表（`sjtu_tpmshx/df_surrogate/backend.py:38-44`）；需实现 `_build(tpms_type)`，可选覆写 `predict_vec`。切默认前必须过双门（`backend.py:16-22` 契约 + `sjtu_tpmshx/tests/test_df_backend_registry.py` 的金值守卫）。
- **override 层**：`predict._OVERRIDES` dict（`sjtu_tpmshx/df_surrogate/predict.py:96-106`）为未来 core-clean 末端标定预留（局部高斯影响域 log 混合，τ_L=0.5 mm、τ_t=0.08 mm、w<0.05 硬零，`predict.py:107-109,143-158`）；当前为空，机制保留。
- **κ 表注册**：`kappa_asym.set_kappa_table(tpms, kK_fn, kcF_fn)`（`sjtu_tpmshx/df_surrogate/kappa_asym.py:56-58`）+ env `TPMSHX_ASYM_KAPPA=1`；`clear()` 供测试隔离。
- **SurrogateV3 实验 kwargs**（仅研究用，非生产路径）：`method='plhub_gp'`、`standardize`、`features` 子集、`clip_margin`（`sjtu_tpmshx/df_surrogate/surrogate_v3.py:117-146`）。
- **GammaDF 注入点**：构造参数 `smooth=` 可替换 SmoothDF 实例（`sjtu_tpmshx/df_surrogate/gamma_df.py:116-121`）。
- **残差修正**：`ResidualCorrector(tpms, smoothing, g_clamp)` 参数可调（`sjtu_tpmshx/df_surrogate/residual_correction.py:87-93`）；`clear_cache()`（`residual_correction.py:208-210`）。
- **诊断透传**：backend 未知属性透传被包裹模型（`._rbf_K`、`.K_min`、`.summary()`，`sjtu_tpmshx/df_surrogate/backend.py:91-93`）——新 backend 也自动获得此行为。
- 模块级缓存（进程内、无失效机制）：`backend._CACHE`（`backend.py:35`）、`gamma_df._K_SURFACE_CACHE`（`gamma_df.py:94`）、`residual_correction._CORRECTOR_CACHE`（`residual_correction.py:198`）、`kappa_asym._KAPPA`（`kappa_asym.py:29`）、`smooth_df._geom` 默认参 dict 缓存（`smooth_df.py:61`）。

## 已知不足与 TODO

- `K_MIN = 1e-8` 注释自称 TEMPORARY：「lowered from 1e-7 to let L>=5 use real K. Revisit later.」（`sjtu_tpmshx/df_surrogate/surrogate_v3.py:83`）。该 clamp 曾把 L4/L5 真实 K≈1e-9 抬到地板，是 rbf LOO 误差主因（`backend.py:12-14`）。
- gamma_df open item：L4/L5 γ 仲裁待 rough-wall CFD（`sjtu_tpmshx/df_surrogate/gamma_df.py:70-71`）；L≤5 区仅 flat6 + max(1,·) 地板的最小延拓，带 `lowL_band` 声明不确定带（`gamma_df.py:36-40,219-243`）。
- 已知开放问题（注释记载）：纯 RBF 在 Diamond L7/t0.6 对试件总 dP 过预测约 1.86×（`sjtu_tpmshx/df_surrogate/predict.py:103-105`）；D_7_6 曾入表的 override (454.3) 因约定不符（total-dP vs core-only）当日回退，表现为空（`predict.py:99-106`）。
- `SCO2_CF_SCALE=3.39` 为单几何（Diamond 7/0.6）标定，跨 (L,t) 迁移为显式假设、UNVERIFIED（`sjtu_tpmshx/df_surrogate/predict.py:137-139`）。
- 训练数据 L=4 行的 v13 与 m/(ρ·20·A6) 漂移可达 ~16%（其余几何 <0.5%），标定注释自曝（`sjtu_tpmshx/df_surrogate/surrogate_v3.py:200-202`）。
- 残差修正层在无原始 Excel 环境（CI/干净 clone）不可用（`rows_df` 为空 → <10 点 `RuntimeError`，`sjtu_tpmshx/df_surrogate/surrogate_v3.py:383-385` + `residual_correction.py:148-150`）。
- 文档漂移两处（本次核实）：`sjtu_tpmshx/domain/compute_config.py:86` 仍列 `cfd_refit` 为可选 method（实际注册表无，`tests/test_df_backend_registry.py:88`）；`compute_config.py:88-89` 把 `TPMSHX_DF_OVERRIDES` 描述为 JSON 表（实际是 on/off 开关，`predict.py:112-113`）。
- `eval_shanghai` 内 A_FLOW/L_DOM 常数与 `configs/shanghai_baseline.json` 需人工同步（注释自认「if the JSON drifts, this constant must follow」，`sjtu_tpmshx/df_surrogate/surrogate_v3.py:491-495`）。
- 向量化路径不过 override 层（`sjtu_tpmshx/df_surrogate/predict.py:92-93`）——表为空时无差异，一旦入表则标量/向量路径在 override 邻域内不一致，属设计取舍而非 bug。
- 模块内未发现 `TODO`/`FIXME`/`NotImplementedError` 标记（已 grep 核实；上述条目均来自注释性自述）。

## 服务器移植注意

- **硬编码绝对路径（机器相关，不是操作系统相关）**：`AIR_XLSX_DEFAULT = D:\Postgraduate\server-pyfluent\Air\Cfd-air-raw-old-new.xlsx`（`sjtu_tpmshx/df_surrogate/smooth_df.py:55-56`）是开发机上的本地路径。Windows Server 与开发机同为 Windows，反斜杠/盘符路径语法本身不是问题；但这条路径大概率在服务器上根本不存在（不同机器、不同盘符布局）。仅 SmoothDF 重建 CLI 用到，需要用 `--air-xlsx PATH` 显式传入服务器上 Excel 的实际路径（CLI 解析见 `smooth_df.py:221-222`）；日常推断（predict / 评估）不构造该对象，不触发。
- **中文路径/sheet 名 + GBK 编码坑（同为 Windows 不会消失，需重点核实）**：训练 Excel 文件名与 sheet 名含中文（`试验记录表_整理版.xlsx`、`Gyroid_汇总`、`边界效应系数`，`sjtu_tpmshx/df_surrogate/surrogate_v3.py:85,173,179`）。这不是"移植到 Linux 后自然消失"的问题——目标 Windows Server 若沿用中文区域设置，系统默认代码页大概率仍是 GBK/CP936，与开发机同源，风险原样保留。代码里已有的防御：日志行刻意保持 ASCII（`surrogate_v3.py:151-155` 注释记载的是一次实测事故：GBK 控制台下的中文日志毒化了 pytest capture 流，导致后续所有 teardown 报 `UnicodeDecodeError`）；各 CLI 入口在 `main()` 里显式 `sys.stdout.reconfigure(encoding="utf-8")`（`surrogate_v3.py:612-615`、`smooth_df.py:217`、`predict.py:328`、`residual_correction.py:307`、`load_data.py:243` 等）。`pandas.read_excel(engine="openpyxl")` 读取的是 xlsx 内部 XML（UTF-8），不经过系统代码页，不受影响。移植到服务器后仍需核实（未验证）：无人值守/服务方式启动、stdout 被重定向到文件或管道而非附着于真实控制台时，`sys.stdout.reconfigure` 是否仍按预期生效；若今后新增 subprocess 调用并捕获其输出，需显式指定 `encoding='utf-8'`（或 `errors='replace'`），不要依赖系统默认代码页。
- **import 约定**：包内用顶层 `from df_surrogate.xxx import ...` / `from solvers.tpms_props import ...`（非 `sjtu_tpmshx.` 前缀），依赖各模块自行 `sys.path.insert(0, sjtu_tpmshx根)`（`sjtu_tpmshx/df_surrogate/surrogate_v3.py:63-71`、`load_data.py:37-39`、`smooth_df.py:43-45`）。移植时保持 `sjtu_tpmshx/` 在 sys.path 或从该目录启动。import 方向由 `sjtu_tpmshx/tests/test_import_dag.py` 锁定（df_surrogate 只 import `solvers.tpms_props`，不得反向）。
- **金值测试是"同机器"锁定，不是"同操作系统"锁定**：`test_df_backend_registry.py` 的精确浮点金值是在 Windows 开发机上捕获的；跳过逻辑的注释原文写的是"libm/FMA 差异，ubuntu CI 实测 rel~1e-13"（`sjtu_tpmshx/tests/test_df_backend_registry.py:30-32`），即该 1e-13 数字是针对 Linux CI 机器测得的，不是"Windows vs Linux"这个二元判断本身。移植目标 Windows Server 与开发机同为 Windows（同一套 numpy/scipy Windows wheel、同一 CRT），理论上更接近位对齐，但只要服务器 CPU 型号/FMA 支持与开发机不同，最后一位 ULP 仍可能漂移——不能假定"同为 Windows 就必然位对齐"（未验证，建议部署后实测一次该测试）。跳过判据只认环境变量 `CI=='true'`，与操作系统无关（`test_df_backend_registry.py:33-35`）；服务器 CI/无人值守跑批场景按需设置。若不设置且末位 ULP 失败，不代表移植失败——判断标准仍是"结果物理上是否合理"，而非这条 exact-equality 测试。
- **数据可用性两级降级**：无 `data/raw_data/` 时 SurrogateV3 自动回退 `_prebuilt/*.csv`（`sjtu_tpmshx/df_surrogate/surrogate_v3.py:156-166`），docstring 声明 CSV 重建与 Excel 标定 bit-identical（`surrogate_v3.py:402-407`；等价性由 `sjtu_tpmshx/tests/test_cache_and_source_guards.py:29-38` 钉定，该测试需 Excel 在场才有意义）。残差修正与评估器无降级路径。
- **第三方依赖**：numpy、pandas、scipy（`RBFInterpolator`/`least_squares`/`brentq`）、scikit-learn（`SmoothDF.__init__` 无条件 import `HuberRegressor`，`sjtu_tpmshx/df_surrogate/smooth_df.py:85` → **gamma_df backend 运行时必需 sklearn**；plhub_gp 分支另需 GP 模块）、openpyxl（仅 Excel 路径）、可选 CoolProp（仅 `surrogate_domain` 的 sco2 分支，`surrogate_domain.py:73-82`）。
- **进程级状态**：backend/κ/corrector 缓存与 choke warning 注册表均为模块级进程内状态；multiprocessing 场景每个 worker 独立重建（首次构建 GammaDF 会读 3 个 CSV + 拟合，秒级），κ 表必须每进程重新 ingest。env `TPMSHX_DF_METHOD` 在每次调用时读取（`sjtu_tpmshx/df_surrogate/predict.py:172-179`），但已实例化的 backend 按 (tpms, method) 缓存不会失效。
- 本包无 GUI 依赖（不 import Qt）；`_domain.py` 被 `ui/` 消费但方向是 ui→df_surrogate。
