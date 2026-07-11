# 移植交接问答 — SJTU-TPMSHX → Windows Server 2022

日期 2026-07-11。基于 `worktree-codebase-atlas-doc @ aacebef`（= `master@f33d30e` + 3 个文档 commit）。

**证据分级约定**（贯穿全文）：

- **【实测】** — 跑过/查过产物，有可复现的输出。
- **【代码事实】** — 读了可执行代码，附 `file:line`。不是注释、不是 docstring。
- **【自述假设】** — 代码注释 / commit message / 文档里的说法。**未经验证**，只说明作者当时怎么想。
- **【无证据】** — 查了，找不到。
- **【需人答】** — 代码里不可能有答案，只有你知道。

---

## 1. `--runner pipeline` 的 `max_outer` 丢弃 + `pressure_clip_hits`/`pressure_state_valid` 硬编码

### 结论：**是遗漏，不是有意忽略。而且第二个问题比第一个严重。**

### 1a. `max_outer` 被静默丢弃 —— 【代码事实】

- `--runner` 只有两个取值：`kernel`（默认）/ `pipeline`（`validate_shanghai_3d_real.py:537-541`）。
- `--max-outer` 默认 4（`:555-556`，`MAX_OUTER = 4` 在 `:72`）。
- **kernel 分支：生效。** `:596` → `_run_one_case(..., max_outer=args.max_outer)` → `:186` → `:324` `for outer in range(max_outer_local)`。
- **pipeline 分支：接收后丢弃。** `:590` 传给 `_run_one_case_pipeline(..., max_outer=args.max_outer)`，函数签名 `:461-462` 声明了这个形参，**但函数体 `:463-531` 从未再引用它**。`:503` 构造 `SolverConfig(Nx=..., Ny=..., Nz=...)` —— **`max_outer_ltne` 没写进去**。
- 后果链（全部已验证）：`SolverConfig.max_outer_ltne` 保持默认 `None`（`domain/compute_config.py:186`）→ `stages_3d.py:194` 映射进 cfg dict 时传 `None` → `run_stack_3d.py:380-381` `if cfg.get('max_outer_ltne') is not None:` 条件不成立 → `_max_outer` 保持 `_MAX_OUTER = 5`（`run_stack_3d.py:246`）。
- **管线恒定跑 5 次外迭代，而横幅 `:580` 却打印用户传入的值（默认 4）。**

**为什么是遗漏而不是设计** —— git 历史给出了明确因果：

- `--max-outer` 是 2026-04-21（`911edca3`）加的，当时只有 kernel runner。
- pipeline runner 是 2026-06-13（`9150ef6`）加的，把已存在的 flag 接进了新分支的签名，但没接进 `SolverConfig`。
- 关键：**当时接进去也没用。** commit `8ea7ce5`（2026-07-09，"R3 — split optimizer budget from solver knobs"）的 message 【自述假设】明说：*"The six SolverConfig fields (tol_simple/max_iter_simple/**max_outer_ltne**/outer_tol_K/...) carried the OPTIMIZER's cheap-eval budget **while being consumed by nothing else** — the production pipelines hardcoded their own values"*。
- `8ea7ce5` 把这个旋钮真正接通了（改了 `compute_config.py` / `run_stack_3d.py` / `solve_2d.py` / `stages_3d.py`），**但没有回补 `validate_shanghai_3d_real.py` 的调用点**。
- 【代码事实】全文件无任何 `TODO`/`FIXME`/"尚未接线" 标记（已 grep）。没有任何注释自述这是有意为之。

### 1b. `pressure_clip_hits: 0` / `pressure_state_valid: 1` —— 【代码事实】，这条更严重

- **kernel 分支：真实计算**（`:454-457`）：
  ```python
  'pressure_clip_hits': int(getattr(sA, '_p_clip_hits', 0)),
  'pressure_state_valid': bool(((sA.P_ref_abs + sA.P) >= 1.0e3).all()
                               and ((sA.P_ref_abs + sA.P) <= 10.0e6).all()),
  ```
- **pipeline 分支：字面量硬编码**（`:529-530`）：`'pressure_clip_hits': 0, 'pressure_state_valid': 1,`
- **下游后果**（`:609-625`）：`valid_mask = np.array([bool(r['pressure_state_valid']) for r in results])` → `bool(1)` 恒 True → **pipeline 模式下 `n_invalid` 恒为 0，`:635-638` 的"排除 pressure-invalid case"逻辑永远是空操作。RMSRE 口径的压力有效性过滤在 pipeline 下完全失效。**
- 而同文件 `:605-608` 的注释【自述假设】写着：*"RMSRE口径 must exclude pressure-invalid cases … Count + list them so the exclusion is auditable, **never silent**."* —— **声明的意图与 pipeline 分支的实际行为直接矛盾。**

### 1c. 为什么不读 Pipeline3D 的 envelope diagnostics？—— 因为部分读不到，部分是没读

Pipeline3D **确实产出**这些诊断（`run_stack_3d.py:1964-2009`）：`envelope_valid`（`:1997`）、`envelope_reasons`（`:1998`）、`envelope_warnings`（`:1999`）、`p_clip_hits`（`:2000`）、`solver_converged`（`:2006`）。

但转发到 `ComputeResult` 时**漏了一个**（`stages_3d.py::_finalize_3d_cfg`）：

| raw 字段 | 转发到 ComputeResult？ |
|---|---|
| `envelope_warnings` | ✅ `:359` → `warnings` |
| `envelope_valid` | ✅ `:369` → `diagnostics` |
| `envelope_reasons` | ✅ `:370` → `diagnostics` |
| `solver_converged` | ✅ `:291` → `converged` |
| **`p_clip_hits`** | ❌ **不在 `ComputeResult` 的任何槽位**（`diagnostics` dict 见 `:361-374`） |

而 validate 的 pipeline 分支（`:515-517`）只读了两个标量：
```python
result = Pipeline3D(cc).run()
dP_sim = result.dP_A_Pa
Q_sim  = result.Q_W
```
**`result.warnings` / `result.diagnostics` / `result.converged` 一次都没被读。** 管线算出来的 envelope 判据在这条分支上全部落地即丢弃。

即：`pressure_clip_hits` 拿不到（`ComputeResult` 没这个字段，需要先补 `stages_3d.py` 的转发）；`pressure_state_valid` **本来可以**用 `result.diagnostics['envelope_valid']` 填（已转发），**但没读**。

⚠️ **注意**：硬 choke 不会被这个 bug 掩盖 —— `envelope_mode` 默认 `'raise'`（`run_stack_3d.py:389`），validate 的 `ComputeConfig`（`:494-514`）没改它，所以真 choke 会抛 `ChokedFlowError` 炸出来（脚本没捕获）。**被掩盖的是软信号**：`envelope_warnings`、SIMPLE 未收敛告警（`run_stack_3d.py:1990-1995`）、以及 clip 计数。

### 修复建议（如果要修）

1. `validate_shanghai_3d_real.py:503` → `SolverConfig(..., max_outer_ltne=max_outer)`。**注意：这会改变 pipeline 分支的数值输出**（5 次外迭代 → 用户指定的 4 次），跑分结果会变。
2. `stages_3d.py::_finalize_3d_cfg` 的 `diagnostics` dict 补 `p_clip_hits`。
3. `validate_shanghai_3d_real.py:529-530` 改读 `result.diagnostics.get('envelope_valid')` / `result.diagnostics.get('p_clip_hits')`。

**【无证据】** 这条 bug 是否曾在实跑中掩盖过真实的 clip/choke 事件 —— 静态不可判，需实跑对比。

---

## 2. optimizer 路径完全没有 envelope gate

### 结论：**是实现时漏掉了 optimizer 路径，不是有意的 BO 契约设计。** 但"漏掉"的实际风险比听起来小（见下）。

### 2a. 现状 —— 【代码事实】

对 `sjtu_tpmshx/optimization/*.py` 全目录 grep `envelope|Choked|check_compressible|gate_solution|assess_solution|mach`：

- **`optimization/evaluator.py`（2D 评估器）：0 处 envelope 调用。**
- **`optimization/evaluator_3d.py`（3D 评估器）：0 处。**
- `optimizer_qnehvi.py` / `parallel_runner.py`：0 处。

envelope 只接在管线上（`solve_2d.py:1233,1242`；`run_stack_3d.py:526,618,1413,1568` 预解 + `:1976,1984` 后解）。

**2D optimizer** 的病态处理（`optimization/evaluator.py`）：
- 根本没有可压缩 1D 种子 —— `_build_simple_A`/`_build_simple_B` 直接传 `P_ref_abs=P_inA`（`:260`、`:309`），inlet-anchored，**从不计算 P_out²**。
- `dp_cap_pa` 默认 `1.0e6`（`:177`），终检 `:632-633`：`if not np.isfinite(dP) or dP > dp_cap: return -1e-6, dp_cap, mass`。
- **返回 cap 值（1e6 Pa），不是 NaN、不是 1e9。** `:505-507` 注释【自述假设】："Returning at the dp_cap (rather than 1e9) keeps the input distribution bounded"。
- **无 Mach 检查、无正压检查、无 choke 检查。**

**3D optimizer** 的手写检查（**在 `core/evaluators.py`，不在 `evaluator_3d.py`**）：
- `:211-222` 手写 `P_out_sq = P_in² - 2·R·T·C·L`（`R_AIR = 287.05` 本地常量 `:51`）——**与 `envelope.predict_outlet_p_sq` 是同一代数式，但是复制的，不 import**。
- `:235-252` `if P_out_sq_A <= 0 or P_out_sq_B <= 0:` → 返回全 NaN dict + `'invalid': True`。**不抛错。**
- **它不检查什么（关键）**：`:396-398` 用耦合后 `T_avg` 重算 `P_out_sq_new`，然后 `sA.P_ref_abs = sqrt(max(P_out_sq_new, 1.0e4))` —— **静默钳到地板，无检查无告警**。管线侧同一位置走的是 `_seed_p_ref`（`run_stack_3d.py:1413`），带门。**这就是你说的"没有耦合后的 gate"，确认属实。**
- 而 `core/evaluators.py:224-234` 的注释【自述假设】自称遵循 "strict validation contract"、"validation 工具必须暴露 infeasible" —— **同一文件 `:398` 的耦合后重种子恰恰用了它所批评的静默地板**。
- `evaluator_3d.py:150-152` 直接 `float(res['Q_3D_W'])`，**不读 `res['invalid']`**，NaN 直接穿透。
- 最后被 `optimizer_qnehvi._eval_worker` 兜底（`:69-81`）：`:77-78` `if not (isfinite(Q) and isfinite(dP)): return (1e-6, dp_cap, 'infeasible')`；`:80-81` `except Exception: return (1e-6, dp_cap, repr(e))`。

### 2b. 是遗漏还是设计？—— git 历史说是遗漏

- envelope 引入 commit `b7974e9`（2026-06-25，"feat(robustness): compressible validity-envelope guards (2D+3D)"）。
- 它的 message 【自述假设】**逐条列举了接入面**：*"Pipelines: - stages_3d.py: the 4 P_out^2 seed sites route through _seed_p_ref…; - stages_2d.py: the same post-solve gate."* —— **完全没有提到 optimizer / evaluator / BO / qNEHVI**。
- 后续两个 envelope commit（`db9be79`、`a1b6de4`）的 message 同样不提。全部 commit message 搜 envelope 附近的 `optimi|evaluator|BO|qnehvi` → **零命中**。
- `CLAUDE.md:18` 陈述这条不变量时也不提 optimizer。
- **不是"暂不接 optimizer"这样的显式 defer，而是只字未提。**
- 唯一明确记录这个缺口的是 `docs/atlas/dataflow.md:141`（2026-07-11 写的全景文档，晚于 envelope 各 commit）：明确写"可压缩包络守卫在优化器评估链中**已确认缺失**，仅靠 `dp_cap_pa` 数值钳制"。

**【无证据】** 作者是否曾判断"dp_cap 已足够、不需要 envelope" —— 没有任何注释/commit/文档表态。不推测。

### 2c. 修改它会影响哪些已保存的 Pareto 基线？—— 【实测】预期不影响

被 git 追踪的优化器基线：

| 路径 | 内容 |
|---|---|
| `opt_runs/qnehvi_3d_20260513_175108/` | `config.json` + `history.csv`(62 行) + `pareto_final.csv`(15 行) + 3 个 `pareto_iter*.csv` |
| `reports/m1_uniform_vs_graded/`（7 个 run 目录） | 每目录 `m1_metrics.json`（**钉 HV 数字**）+ `qnehvi_m1/*.csv` + `uniform_*.csv` |

**逐个检查了 8 个被追踪的 `history.csv` 的 dP 列**（`history.csv` 由 `optimizer_qnehvi.py:492` 写全量 `X_np`，不是 Pareto 子集，所以被 cap 的设计**本应**以 `dP_Pa = 1.0e6` 出现）：

- **dp_cap（1e6）命中数 = 0。一行都没有。**
- dP 最大值：3D run `1.95e4 Pa`；2D m1 各 run `~1.10e4–1.23e4 Pa`。
- 全部 `P_in = 101325 Pa` → `dP/P_in ≤ 0.19`，**离 choke 条件（dP → P_in）很远**。
- 4 组 frozen 元组（`tests/test_evaluator_frozen_values.py:122-136`，rel=1e-12）的 dP 在 `5.86e3 – 1.82e4 Pa`，同样远离 choke。

→ **追踪的基线里没有任何设计点落在 choke 区，也没有任何一个走到 dp_cap 兜底。** 若 gate 是纯附加（`envelope.py:22-23` 自称 "Nothing here changes an in-envelope solve"），这些基线**预期不变**。

**但要注意两个不对称**：
- **3D**：`ChokedFlowError` 是 `RuntimeError` 子类，若在 optimizer 路径抛出，会被 `_eval_worker:80-81` 的 `except Exception` 接住 → 返回 `(1e-6, dp_cap, repr(e))`。**对已 choke 的 3D 设计，加门后的数值元组与现状相同。**
- **2D**：目前完全无 choke 检测，choke 工况会返回一个**有限但错误**的 dP。加门会**改变**这些点的返回值。当前基线里没有这种点，但**换 seed / 换 bounds 后 BO 是否会进入 choke 区，代码无法判定**【无证据】。

**【无证据】** `m1_metrics.json` 的 HV 数字的完整生成链路（是否会重跑 optimizer、是否复用 `evaluator.py` 的 dp_cap 路径）未端到端追踪。

**没有任何测试钉 HV / Pareto CSV 数字**（grep `tests/` 的 `opt_runs|m1_metrics|hypervolume|pareto_final` → 只有合成 CSV 的冒烟测试）。`m1_metrics.json` 与 `opt_runs/` 的 CSV 是**纯数据产物，无断言**。真正会被 gate 变更打破的是 `test_evaluator_frozen_values.py`（rel=1e-12，4 组元组）——但仅当 gate 改变了这 4 个具体设计点的返回值，而它们远离 choke，所以**预期不变**。

---

## 3. optimizer evaluator 与 Pipeline 是否应数值一致？

### 结论：**代码里没有"应该一致"的契约，而且它们目前确实不一致。哪条是权威取决于你想验收什么。**

### 3a. 已知的实现分歧 —— 【代码事实】

| 维度 | Pipeline（`run_stack_3d.py`） | optimizer（`core/evaluators.py::evaluate_3d`） |
|---|---|---|
| 预解 choke 门 | `_seed_p_ref` → `check_compressible_envelope`（4 个种子点：`:526,618,1413,1568`） | 手写复制的代数式（`:211-222`），返回 NaN dict，不抛错 |
| **耦合后重种子** | 走 `_seed_p_ref`（`:1413`），**带门** | `:396-398` `max(P_out_sq_new, 1.0e4)` **静默钳地板，无门** |
| 后解 gate（Mach/正压） | `gate_solution`（`:1976,1984`） | **无** |
| B 侧 var-ρ 重种子 | 有（`:1568`） | **无** |
| 外迭代次数 | `_MAX_OUTER = 5`（`run_stack_3d.py:246`），可被 `max_outer_ltne` 覆盖 | 由 optimizer cfg 传入 |

**这不是"近似"，是不同的代码路径**，各自演进。`evaluator_3d.py` 只是 `core/evaluators.evaluate_3d` 的薄包装（`:135-154`）。

### 3b. "应不应该一致" —— 代码里查不到契约

**【无证据】** 仓库里没有任何测试断言"optimizer evaluator 与 Pipeline 在同一输入下数值一致"（grep 未找到 cross-path parity 测试）。没有文档写明允许的近似及其误差上限。

**能找到的最接近的东西**是 `validate_shanghai_3d_real.py` 的 `--runner kernel|pipeline` 双跑机制 —— 但它对比的是 **kernel gate runner vs Pipeline3D**，**不是 optimizer evaluator vs Pipeline**。而且其 docstring【自述假设】明说：*"Deliberately a DIFFERENT physics path from `_run_one_case`"*、*"the gate runner stays kernel-direct; this runner exists so the production path is scored against the same truth table"*、*"Do not silently swap the gate."* —— 即：**作者明确知道两条路径不同，并有意保持 kernel 为 gate**。

### 3c. 服务器验收应以哪条为权威？—— 我的建议（不是代码事实）

- **物理正确性/验收 → Pipeline**（`validate_shanghai_3d_real.py --runner kernel` 是当前的 gate，README/`_CSV_STATUS.md` 的 5.28%/3.21% 就是它产出的）。它有完整的 envelope 门、conservative LTNE 内核、B 侧重种子。
- **optimizer evaluator → 只作为 BO 的廉价评估器**，它的数值不应被当作物理结果引用。Pareto 前沿选出来的点，**应该用 Pipeline 重解一遍**再报数（memory 里记录的 blind-spot audit R3 结论正是这样：*"optimizer block = rankings only, Pareto picks re-solve via production pipeline"*）。
- **如果你要求两者一致**：那 `core/evaluators.py:396-398` 的静默地板必须先改成走 `_seed_p_ref`，否则在接近 choke 的设计上两条路径会系统性分叉。

**【需人答】** 你是否**要求**两者一致？如果不要求，允许的近似和误差上限需要你来定 —— 代码里没有这个契约，我不能替你定。

---

## 4. Windows Server 的实际运行目标

### 【需人答】—— 代码里不可能有答案。

我能提供的只是**约束条件**（【代码事实】），供你判断：

- **GUI 不是必需**：核心求解器 / 优化器 / 验证脚本全部有 CLI 入口，不 import Qt（`solvers/` 7 个文件 grep `PySide6|Qt` 零命中）。`runs/`、`validation/cases/`、`optimization/` 都是纯 CLI。
- **但 GUI 能跑**：`QT_QPA_PLATFORM=offscreen` 是跨平台机制（Windows/Linux 注册方式相同）。`tests/conftest.py:33` 的 offscreen setdefault + `:49-57` 的预实例化 `QApplication` 修复，动机本来就是 **Windows 无显示器时 exit code 9 崩溃**（`conftest.py:16-19` 注释原文）。所以无交互桌面会话下也能跑。
- **PyVista/VTK 3D 渲染在无 GPU 的服务器上未验证**【无证据】。
- **当前的部署脚本 `port_retest_server.ps1` 假设的是交互式 PowerShell 会话**（见 Q7），既不是计划任务也不是服务。

**需要你回答**：纯无头批跑（优化/验证）？RDP 下开 GUI？计划任务？Windows Service？**是不是 Server Core**（这决定 GUI 能不能用、字体在不在 —— `ui/panel_vis_3d.py:662-663` 硬编码 `C:\Windows\Fonts\msyh.ttc`，Server Core 精简字体下可能没有）？

---

## 5. `port_retest_server.ps1` 是否曾在真实服务器跑通？

### 结论：**无任何实跑证据。四个查证方向全部落空。**

| 查证方向 | 结果 |
|---|---|
| `reports/port_dim_retest/` 被 git 追踪？ | ❌ `git ls-files \| grep port` 只有 3 个脚本 + `run_port_dim_retest.py`，**零产物** |
| 是不是"跑了但被 gitignore"？ | ❌ **不是**。`.gitignore:13` 只忽略 `reports/figs/`；`reports/port_dim_retest/` **是可提交的**（对照：`reports/m1_uniform_vs_graded/` 就被追踪着）。**没提交 ≠ 被忽略，是根本不存在** |
| 原 checkout 磁盘上有吗？ | ❌ `find . -iname "*port_dim*"` 只命中 3 份源码；`find . -name "port_metrics.json"` **零命中**；`~/tpmshx-port` 本机不存在 |
| git log 有跑通记录？ | ❌ 相关 commit 只有 `581d312`（port-BC 接线）、`342be77`（cf-aniso）、`56f3b9d`（脚本本身）。**没有任何 commit 提到跑通/结果回收/结果数字** |

**旁证**：`.ps1` 于 **2026-07-10 22:43** 提交，今天 2026-07-11 —— 脚本诞生不足一天。`reports/` 下有 `m1_uniform_vs_graded/`、`shanghai-validation/` 等真实产物目录，**唯独没有 `port_dim_retest/`**。

→ **所以你问的服务器 CPU/RAM、pip freeze、日志、墙钟时间、失败记录：全部无。这套四臂从未真正跑过。** `.sh` 变体同理无实跑证据。

atlas `repo-infra.md` 里对此的措辞已经订正为"**两个脚本均未经过真实服务器实跑验证**"。

---

## 6. 四臂 × `--jobs 8` × NUMBA/OMP/MKL=8 的依据

### 结论：**无 benchmark 依据。而且 `--jobs 8` 对长阶段（BO）根本不起作用，实际会 4× 超订。**

### 6a. "64 核" —— 【自述假设】，无区分，无依据

原文三处（全部在 `.ps1` 和它的 commit message）：
- `port_retest_server.ps1:10-11`：*"64 核机器四臂并行 + 每臂 jobs=8, 预计墙钟 ~4-7 h"*
- `port_retest_server.ps1:61`：*"四臂并行 (64 核: 每臂 8 线程 + joblib 8)"*
- commit `56f3b9d` message：*"adapted for Windows Server 2022 / 64 cores: … 8 threads + jobs=8 per arm"*

**物理核 vs 逻辑处理器：没有任何区分**（三处都只写 "64 核 / 64 cores"，全仓 grep 无 "physical"/"logical"/"HyperThreading"/"SMT"/"超线程" 字样）。

**benchmark 依据：【无证据】。** 没有指向任何 benchmark 报告/commit/实测数字的引用。`benchmarks/` 下的快照是求解器性能，与线程配额或 64 核选型无关，且未被这些脚本引用。"8 线程 + jobs=8" 看起来是 `64/4/2` 这类心算配额。

### 6b. 嵌套超订 —— 【代码事实】，问题比你想的更具体

**关键发现 1：`--jobs 8` 只影响均匀扫掠，不影响 BO。**

`run_port_dim_retest.py` 里 `--jobs` **只被消费一次**：
```python
# :194
uni = run_uniform_sweep(cfg, L_vals, t_vals, a.jobs)     # ← --jobs 唯一去处（45 点扫掠，~8 min）
# :206-210
res = run_qnehvi(config=cfg, ..., n_jobs=min(q_batch, 2), ...)   # ← BO 阶段写死 = 2，与 --jobs 无关
```
**BO 阶段（占 4-7 h 的绝大部分）的并行度是写死的 2，`--jobs 8` 对它毫无影响。** `.ps1` 注释里"每臂 jobs=8"对总墙钟几乎没意义 —— 这是注释与代码的实质错配。

**关键发现 2：BO 阶段会覆盖脚本设的线程数，且不知道有 4 个臂。**

`optimizer_qnehvi.py:287-297`：
```python
_workers = min(n_jobs, B)                                   # = 2
_inner   = max(1, (os.cpu_count() or 4) // _workers)        # :293 → 64 // 2 = 32 (!)
results = Parallel(n_jobs=_workers, backend='loky',
                   inner_max_num_threads=_inner)(...)       # :294-297
```
- `os.cpu_count()` 看到整机 64 核，**它不知道另外还有 3 个臂在跑**。
- `inner_max_num_threads=32` 是**显式参数 → 覆盖脚本 export 的 8**（joblib 1.5.3 `_parallel_backends.py:229-242` 实测：显式参数 > 父进程 env）。
- `optimizer_qnehvi.py:290-292` 的注释【自述假设】自承设计意图（*"perf-wave1 (2026-07-03): was pinned to 1 … Share the cores across workers instead"*）—— **它假设整机只有一个 BO 进程，而四臂脚本恰好违反了这个假设**。

**线程总账（64 核 Windows Server，`.ps1`）：**

| 阶段 | 每臂进程 | 每进程线程 | 每臂 | × 4 臂 | 对 64 核 |
|---|---|---|---|---|---|
| A 均匀扫掠（~8 min） | 8（joblib，`--jobs 8`） | 8（脚本 env 赢） | 64 | **256** | **4× 超订** |
| B qNEHVI BO（4-7 h） | 2（写死 `min(q_batch,2)`） | 32（`cpu_count()//2`，覆盖脚本的 8） | 64 | **256** | **4× 超订** |

线程确实会落地：2D LTNE 能量核是 `@njit(cache=True, parallel=True)`（`solvers/ltne_energy.py:368`），`solvers/threads.py:6-8` 明确 `NUMBA_NUM_THREADS` 是 "HARD CAP, fixed before Numba initialises" —— loky 通过 env 设它，每个 worker 真会开 32 条 numba 线程。

**`.sh` 变体**：`THREADS = clamp(nproc/4, 1, 4)`（`:60-64`），阶段 A 在 64 核上正好打平（4 臂 × 4 进程 × 4 线程 = 64），**阶段 B 同样 4× 超订**（同一个 `_inner` 覆盖）。⚠️ 另注：`.sh:58` 注释写"每臂 2 线程上限"，代码 clamp 到 **4** —— 注释与代码不符。

**关键发现 3：`parallel_runner.py` 的防超订护栏在这条路径上完全没生效。**

`optimization/parallel_runner.py:44-53` 的 `_set_thread_caps()`（`setdefault('1')`）：
1. **不在这条路径上** —— `run_port_dim_retest.py` 调的是 `run_qnehvi`（单 seed），不是 `run_qnehvi_multiseed`；`_set_thread_caps` 只在 `_seed_subprocess_main`（`:72`）里调。
2. **就算在，脚本也赢** —— `setdefault` 只在 key 不存在时写；脚本已 `export OMP_NUM_THREADS=8` → no-op。
3. **它的列表里根本没有 `NUMBA_NUM_THREADS`**（`:51-52` 只有 OMP/MKL/OPENBLAS/NUMEXPR）—— 而本项目 2D 求解的热点是 numba `parallel=True` 内核，不是 BLAS。**这个护栏漏掉了最要紧的那个变量。**

### 6c. 顺带：ctrl6 臂的真实瓶颈

`n_init = 2*D`（`run_port_dim_retest.py:181`），ctrl6 → D=72 → **144 个初始点**，但 `_evaluate_batch` 只有 2 个 worker → 144 次评估要串 72 轮。**这是 5-7 h 估计的主要来源，且完全不受 `--jobs 8` 影响。**

---

## 7. 中断 / RDP 断线 / 重启 / 重复执行

### 结论：**基本没有处理。`.ps1` 在这方面比 `.sh` 更脆弱。**

| 项 | `.ps1` | `.sh` |
|---|---|---|
| PID 文件 | ❌ 无（PID 只 `Write-Host` 到终端，`:79`） | ❌ 无（`echo pid=$!`，`:74`） |
| 锁文件 / mutex | ❌ 无 | ❌ 无 |
| 幂等检查 | ✅ **仅一处**：日志含 `[PORT] DONE` → skip（`:72-74`） | ✅ 同（`:68-70`） |
| checkpoint / 断点续跑 | ❌ 无 | ❌ 无 |
| 退出码汇总 | ❌ 无（`Start-Process -PassThru` 但**从不读 `$p.ExitCode`**，也无 `-Wait`） | ❌ 无 |
| 日志 | `logs\c{C}s{S}.log` + `.err.log`（分开） | `logs/cXsY.log`（2>&1 合并） |

**checkpoint 的真相**：`optimizer_qnehvi.py:449-450` 每 5 个 BO iter 写 `pareto_iter{NNNN}.csv` + `pareto_latest.csv`。但**全仓没有任何代码读回这些文件做 resume**，`run_port_dim_retest.py` 的 argparse（`:132-153`）也没有 `--resume`。→ **这些 checkpoint 只是取证快照，不能断点续跑。臂崩了就从零重跑（Sobol init 全部重做）。**

**中断 / 断线 / 重启：**
- `.sh`：`nohup ... &`（`:71`）→ 忽略 SIGHUP，**SSH 断线不杀进程** ✅
- `.ps1`：`Start-Process -NoNewWindow -PassThru`。**没有 nohup 等价物、没有 `-WindowStyle Hidden`、没有 `Start-Job`、没有服务、没有计划任务。** `-NoNewWindow` 让子进程**共享父 PowerShell 的控制台**：
  - RDP **断开连接**（会话保留）→ 进程存活 ✅
  - **关掉那个 PowerShell 窗口** → 控制台收到 `CTRL_CLOSE_EVENT`，附着其上的 4 个臂**大概率一起死** ⚠️
  - RDP **注销（logoff）/ 服务器重启** → 会话销毁，4 个臂全死，**无自动重启** ⚠️
  - **因为没有 PID 文件，断线重连后没有记录可用来找回/杀掉这些臂**（只能按进程名猜）⚠️

**重复执行**：
- 臂**已 DONE** → 跳过 ✅（唯一有效的幂等场景）
- 臂**正在跑**（日志无 DONE）→ **没有锁，会再起一套 4 个进程**：
  - `.sh`：`> logs/$tag.log` 截断活进程仍持有 fd 的同一文件（日志变空洞/错乱），且新旧进程写**同一个** `reports/port_dim_retest/ctrlN_seedM/` 输出目录 → **结果互相覆盖**。
  - `.ps1`：`-RedirectStandardOutput` 指向被活子进程独占的文件，大概率抛异常；配合 `$ErrorActionPreference = "Stop"`（`:15`）会让脚本中途 abort（**可能已重启了部分臂**）。

**【无证据】** 仓库里没有任何未提交的 PID/锁/checkpoint 方案（`git status` 干净，无 stash）。

---

## 8. 数据仓 pin / 权威标定源 / 为什么要复制 raw_data

### 8a. `master@f33d30e` ↔ `SJTU-TPMSHX-data` 的对应 commit —— 【无证据】，**无 pin，无记录**

- `port_retest_server.ps1:42-46` clone 数据仓：**无 `-b <branch>`**（对比同文件 `:36` 主仓 clone **有** `-b master`）→ 永远 clone **远端默认分支的 HEAD**；`:45` `git -C $DataRepo pull --ff-only` → 每次跑都更新到最新。**无 `--depth`、无 commit checkout、无 tag。**
- **无 submodule**（仓库根无 `.gitmodules`）。
- **无版本文件**：`grep -rn "SJTU-TPMSHX-data"` 全仓只命中 `port_retest_server.ps1`（3 处）+ 3 份 atlas 文档（描述性文字）。**没有任何 commit SHA / 版本号 / manifest。**
- README、`_CSV_STATUS.md`、openspec、CLAUDE.md 均无对应关系记录。

→ **代码仓 commit ↔ 数据仓 commit 的对应关系在仓库内完全无记录。这是一个真实的可复现性缺口。**

### 8b. 权威标定源应该是 XLSX 还是 tracked prebuilt CSV？—— 代码说 XLSX 是权威，但两条路径可能静默分叉

**【代码事实】** `df_surrogate/surrogate_v3.py:156-166`：
```python
if XLSX.exists():
    self._source = 'xlsx'
    self._build()                 # authoritative: calibrate from Excel
else:
    self._source = 'prebuilt_csv'
    self._build_from_prebuilt()   # fallback: committed calibrated CSV
```
`XLSX = _PROJECT / "data" / "raw_data" / "试验记录表_整理版.xlsx"`（`:85`）。

- **不抛异常，只打一条 `_log.info`。** 程序继续跑，数字可能不同。**这就是"缺 raw_data → 静默回退 CSV"的确切机制。**
- 该分支**同时影响 rbf 和 gamma_df**（gamma_df 经 `gamma_df.py:126-129` 构造 `SurrogateV3` 拿 γ 锚点）。
- 注释【自述假设】（`:87-94`）："The Excel path stays authoritative when the data is present" —— 即两条路径**不是对等的**，**Excel 是权威**。

**两条路径是否 bit-identical？**
- 注释【自述假设】**声称是**：`dump_prebuilt` docstring（`:404-405`）"Full float precision so the CSV-rebuilt RBF is bit-identical to the Excel-built one"（`float_format="%.17g"`，`:413`）。
- **测试只保证 rel=1e-6**：`tests/test_cache_and_source_guards.py:26-47` `test_df_source_parity` 用 `pytest.approx(rel=1e-6)`，**且在缺 XLSX 的机器上直接 skip**（`:30-31`）→ **在 CI / 缺数据的机器上，这个守卫根本不运行。正是最需要它的场景下不跑。**
- 注释还自述了风险（`:150-152`，W6 2026-07-07）："the two paths can silently diverge if the local Excel is edited without regenerating the committed CSV, and the production GammaDF anchor derives from this instance."

**我的建议**（不是代码事实）：**服务器上以 tracked prebuilt CSV 为权威**（可复现、随 commit 走、无外部依赖），除非你需要重标定。理由：XLSX 没有 pin、没有 hash 校验、数据仓无版本对应，用它做权威源等于把 golden 数字挂在一个不受版本控制的外部文件上。**但这需要你先确认 CSV 确实是当前 XLSX 的忠实导出**（跑一次 `test_df_source_parity`，它在有数据的机器上会跑）。

### 8c. 为什么部署脚本必须复制 raw_data，而 gamma_df 推理"不依赖"它？—— **这个前提是错的，gamma_df 间接依赖它**

**【代码事实】** gamma_df 的推理链读 **3 个数据源**：

| 数据源 | file:line | git 状态 |
|---|---|---|
| `_prebuilt/df_cfd_coeffs.csv` → K 面 | `gamma_df.py:93,102` | ✅ 追踪 |
| `_prebuilt/smooth_df_coeffs.csv` → c_F smooth 基底 | `smooth_df.py:51,80` | ✅ 追踪 |
| **`SurrogateV3(tpms)` → γ 锚点** | `gamma_df.py:126-129` | **← 这里分叉到 XLSX** |

调用链（已全程验证）：
`run_port_dim_retest.py` → `optimization.evaluator` → `solvers.tpms_calc.compute` → `df_surrogate.predict.predict_K_cF`（`predict.py:196-208`）→ `get_backend(tpms, "gamma_df")` → `GammaBackend._build`（`backend.py:98-100`）→ `GammaDF(tpms)` → `gamma_df.py:126-129` 构造 `SurrogateV3` → **`surrogate_v3.py:156` 的 `XLSX.exists()` 分支**。

→ **有 raw_data：γ 锚点走 Excel 重标定。无 raw_data：走 committed CSV。** 脚本注释【自述假设】说的正是这个（`port_retest_server.ps1:47`：*"拼装标定数据 (主仓 data/ 是 gitignored 的; 缺它 DF 代理会静默回退 CSV 标定)"*）。

**所以复制 raw_data 不是多余的，是会改变标定源的。** 只是：
- `run_port_dim_retest.py` **只需要 `试验记录表_整理版.xlsx` 一个文件**（不读 Shanghai/D76/water-cfd-raw 那些）。`Copy-Item -Recurse` 整个 `raw_data/`（`ps1:49`）复制了全部 10 个文件，其中 9 个对这条命令多余（但对后续可能跑的 validation gate 有用）。
- **"复制 raw_data 到底会不会让数字变化" —— 【无证据】**。注释声称 bit-identical，测试只验到 rel=1e-6，且该测试在缺数据机器上 skip。

⚠️ **CI 注释里有一处与代码事实出入**：`.github/workflows/ci.yml:6-9` 写 *"the default gamma_df surrogate backend only reads the tracked `df_surrogate/_prebuilt/` CSVs, so solver tests run fully"* —— 这句**只在 CI 语境下成立**（CI 上 XLSX 永远不存在）。作为一般性陈述它是错的。

### 8d. ⚠️ `.ps1` 的一个高风险行为（【代码事实】+ 【无证据】的组合）

`.ps1:49` `Copy-Item -Recurse -Force <data-repo>/raw_data <repo>/data\` —— **第二次执行时的行为不确定**：目标 `data\raw_data` 已存在时，PowerShell 有把源目录嵌套成 `data\raw_data\raw_data` 的已知行为（版本相关）。**静态不可判定，需实测。**

若真的嵌套，而 `.ps1` **又缺** `.sh:52-56` 那个 `data/raw_data` 存在性 FATAL 检查 → **会静默回退到 CSV 标定，四臂照跑不误，产出的数字和第一次跑不一样，而且没有任何告警。** 这是本次调查里**风险最高的一处**。

建议：给 `.ps1` 补上 `.sh` 那个 FATAL 检查（`.sh:52-56` 的等价物），或者用 `robocopy` / 显式 `Copy-Item $src\* $dst` 避免嵌套歧义。

---

## 9. 产生 golden/headline 数字的版本组合

### 9a. 仓库里的记录 —— 【无证据】，**零版本记录**

grep 全仓（`*.py`/`*.md`/`*.yml`/`*.ini`）搜 `numpy[=><]`、`scipy 1.`、`pip freeze`、`captured on`、`环境.*版本`：

- `README.md:108`："Tested on **Python 3.11 / 3.12, Windows 11**" —— 泛化说明，**不绑定具体 golden 数字**
- `requirements.txt:2-3`："Versions reflect the development environment as of 2026-05-07; minor upgrades should be safe" —— 【自述假设】，无实测支撑
- `test_df_backend_registry.py:31`："captured on **the Windows dev box**" —— 只说机器，**不说版本**
- `test_evaluator_frozen_values.py:4,52`："captured on master **pre-C7 (2026-06-13)**" —— 只说 commit 时代，**不说版本**
- **`_CSV_STATUS.md`（89 行全读）**：记录了极详尽的**物理/算法沿革**（5.28/3.21 的漂移轨迹 9.82→5.05→5.28、复现命令），但 **零个包版本、零个 Python 版本、零个环境记录**。它的 "To reproduce"（`:83-86`）只给命令行 flag。

→ **golden 数字的版本组合在仓库内完全无记录。**

### 9b. 依赖约束现状 —— 【代码事实】，**三重无 pin**

1. **`requirements.txt` 全部 `>=` 下限，零个 `==`，零个上限**：
   `numpy>=2.0` `scipy>=1.13` `pandas>=2.0` `sympy>=1.13` `pyamg>=5.2` `joblib>=1.3` `numba>=0.60` `scikit-learn>=1.5` `matplotlib>=3.8` `pyvista>=0.45` `pyvistaqt>=0.11` `PySide6>=6.7` `openpyxl>=3.1` `CoolProp>=6.4` `pytest>=8.0` `pytest-xdist>=3.5` `scikit-image>=0.24`（`torch>=2.2` 被注释掉了）
2. **`requirements.txt` 不含优化器栈** —— 两个部署脚本都额外 `pip install torch --index-url .../cpu` + `pip install botorch gpytorch`（`ps1:57-59`），**这三个连 `>=` 都没有，永远装 PyPI 最新**。
3. **CI 装的是手写的更窄子集，也全无版本约束**（`ci.yml:41-44`，14 个包）。

**无 lock / constraints / pyproject / poetry.lock / Pipfile.lock / environment.yml / pip freeze 快照** —— 全部不存在（`git ls-files` 已确认）。

### 9c. 【实测】开发机环境快照 —— 我现在给你

**Python 3.12.10** (tags/v3.12.10:0cc8128, Apr 8 2025) [MSC v.1943 64 bit (AMD64)]，Windows。

关键包：
```
numpy==2.4.4          scipy==1.17.1         pandas==2.3.3        sympy==1.14.0
numba==0.64.0         llvmlite==0.46.0      pyamg==5.3.0         joblib==1.5.3
scikit-learn==1.8.0   scikit-image==0.26.0  matplotlib==3.10.8
pyvista==0.47.1       pyvistaqt==0.11.4     PySide6==6.11.0      shiboken6==6.11.0
openpyxl==3.1.5       CoolProp==7.2.0
torch==2.11.0+cu128   botorch==0.17.2       gpytorch==1.15.2
pytest==9.0.3         pytest-xdist==3.8.0
```
完整 187 行 `pip freeze` 已存为 **`constraints-devbox-2026-07-11.txt`**（本 worktree 根目录）。

⚠️ **重要限定**：这是**今天的开发机环境**，**没有任何记录证明它就是产出 golden 数字（5.28%/3.21%、rel=1e-12 钉定值）的那套**。`requirements.txt` 自述的开发环境是 **2026-05-07** 的，而这些包（numpy 2.4.4、numba 0.64、torch 2.11）明显更新。

**但是**：我刚在这个环境里跑了全量 pytest（含 golden 位一致门 + DF 钉定值），结果见下方「实测验证」一节 —— 这把它从"某个环境"升级为"**经验证能复现当前 golden 值的环境**"。这是你现在能拿到的最强锚点。

### 9d. 【代码事实】版本/平台敏感的测试处理 —— 移植时会踩

**(1) 精确 `==` 门靠 `CI=true` 环境变量 skip：**

`tests/test_df_backend_registry.py:30-35`：
```python
# Same-machine bit-repro gate: the pinned values are exact float comparisons
# captured on the Windows dev box; libm/FMA differences shift the last ULP on
# other platforms (measured rel ~1e-13 on ubuntu CI). Skip off-machine.
_CI = pytest.mark.skipif(__import__('os').environ.get('CI') == 'true', ...)
```
守卫的是 `_GOLDEN` 字典（`:22-27`），断言是**裸 `==`**（`:43-44`）。`test_df_projection_equivalence.py:52-56` 同理。

⚠️ **移植风险**：**这些门只在 `CI=true` 时 skip。Windows Server 上手动跑 `pytest` 不会设 `CI=true` → 这些精确 `==` 门会照常跑**，而此时数据源（XLSX vs CSV，见 Q8）和 CPU 微架构都可能与捕获时不同 → **大概率红**。

**(2) 放宽容差 + 预留降级方案：**

`tests/test_evaluator_frozen_values.py:14-18`：
> *"rel=1e-12 (not exact ==): same-machine numba is deterministic… **If a different CI machine trips this on FMA/thread-count variance, relax to rel=1e-9.**"*

`_REL = 1e-12`（`:37`）。**降级方案是手工改常数，无自动机制。** 该文件整体 `pytest.mark.slow`（`:35`）→ **CI（`-m "not slow"`）根本不跑它**。

**(3) Shanghai 回归**：`BASELINE_DP=5.28` / `BASELINE_Q=3.21`，容差 ±5% / ±10%（`test_shanghai_regression.py:181-190`）—— 物理漂移量级，对版本不敏感。但**默认 skip，需 `TPMSHX_RUN_SHANGHAI_REGRESSION=1`**，且依赖 gitignored 的 Shanghai xlsx。

### 9e. 我的建议

1. 把 `constraints-devbox-2026-07-11.txt` 纳入仓库，服务器用 `pip install -r requirements.txt -c constraints-devbox-2026-07-11.txt` 装，**先复现 golden，再考虑升级**。
2. 服务器上第一次跑 pytest 时**显式设 `CI=true`**（或临时改 skipif 条件），否则那两个精确 `==` 门会因为 ULP 差异红掉 —— **那是预期行为，不是移植 bug**。
3. 长期：给 `_CSV_STATUS.md` 补一行"golden 数字的捕获环境"。这个缺口是 codex 最容易被绊倒的地方。

---

## 10. atlas 分支 `aacebef` 是否可合入？

### 10a. 分支状态 —— 【实测】

`worktree-codebase-atlas-doc` 相对 `master` 领先 3 个 commit，**全部是文档，零代码改动**：
```
aacebef docs(atlas): 服务器移植语境订正——目标平台 Linux → Windows Server 2022
9b7e26b docs(readme): 修正 3 处过期/失实断言 + 联动数字
8c2b946 docs: 全景代码库 atlas（17 册）+ vault 交叉核对 + agent-skills 配置
```
PR **#47**，已从 draft 转正式，`state=OPEN`。**内容上已完成，可以合。**

⚠️ 唯一的例外：`9b7e26b` 动了 `README.md` 和 `assets/hero-{light,dark}.svg`（headline 数字修正）—— 这不是纯文档，是**面向外部的项目门面**，值得你亲自看一眼再合。

### 10b. 主 checkout 的未提交内容 —— **不是同一批，而且会和 PR #47 撞车** ⚠️

`git status` on `master`（主 checkout）显示：
```
 M CLAUDE.md
?? .agents/
?? .codex/
?? .planning/
?? AGENTS.md
?? docs/            ← 只含 docs/agents/{domain,issue-tracker,triage-labels}.md
```

**关键发现**：主 checkout 上的 `CLAUDE.md` 修改 + `docs/agents/` **是 `/setup-matt-pocock-skills` 的另一次独立运行产物**，和 PR #47 里的**是同一件事的两个副本，措辞不同**。

对比（主 checkout 未提交版 vs PR #47 已提交版）：
```diff
-Issues live in this repo's GitHub Issues, via the `gh` CLI.        ← 主 checkout
+Issues live in this repo's GitHub Issues (`gh` CLI).               ← PR #47
-Default five canonical roles (`needs-triage`/`needs-info`/...)     ← 主 checkout
+Default five-role vocabulary (`needs-triage`, `needs-info`, ...)   ← PR #47
```
→ **合 PR #47 之后，主 checkout 的这份未提交改动会变成冲突/重复。建议：合 PR 之前先在主 checkout `git checkout -- CLAUDE.md && rm -rf docs/agents`（丢弃那份副本），或者反过来只保留一份。**

`.agents/` `.codex/` `.planning/` `AGENTS.md` —— **不是我产出的**（PR #47 没碰这些），看起来是 codex 或其他工具的脚手架。**【需人答】** 这些是你要提交的吗？

---

## 实测验证（本次新增证据）—— Q9 的锚点

【实测】把 `data/`（2.8 MB，9 个 xlsx）从主 checkout 复制进 worktree（绕开 worktree 缺 gitignored 数据的已知陷阱），在上述 **Python 3.12.10 + numpy 2.4.4 + scipy 1.17.1 + numba 0.64.0 + pyamg 5.3.0** 环境下：

```
$ PYTHONHASHSEED=0 pytest sjtu_tpmshx/tests/ -q -n auto --dist loadscope
1187 passed, 3 skipped, 113 warnings in 341.42s (0:05:41)      # exit 0
```

**全量通过，零失败。** 且关键的钉定门**确实跑了、没被 skip**（单独复跑确认，27 passed）：

| 测试 | 断言强度 | 本次结果 |
|---|---|---|
| `test_df_backend_registry.py` | **裸 `==`**（exact float，`_GOLDEN` 字典 `:22-27`） | ✅ 跑了并通过（本机无 `CI=true`，skipif 不触发） |
| `test_df_projection_equivalence.py` | **裸 `==`**（`K.tolist() == K_ref`） | ✅ 同上 |
| `test_evaluator_frozen_values.py` | **rel=1e-12**（4 组 `(Q,dP,mass)` 元组） | ✅ 跑了并通过（`slow` 标记，全量跑时不排除） |
| `test_cache_and_source_guards.py::test_df_source_parity` | XLSX vs prebuilt CSV，rel=1e-6 | ✅ **跑了并通过** —— 平时在缺数据的机器上 skip，这次因为复制了 data 而真正执行 |

**这条证据的含义**：
1. `constraints-devbox-2026-07-11.txt` 里的版本组合**经验证能复现当前 golden 值**（包括最严的 exact-`==` 门）。这是你现在能拿到的最强的可复现性锚点 —— 虽然仍**无法证明它就是当初捕获这些值的那套版本**（那个记录不存在，见 9a）。
2. **XLSX 标定路径与 committed CSV 路径在 rel=1e-6 内一致**（`test_df_source_parity` 首次在有数据的环境下被验证通过）。这部分回答了 Q8b：两条标定源目前**没有发生静默分叉**。但注意它只验到 1e-6，而 golden 门是 exact `==` —— 这两个精度量级之间的余量没有测试覆盖。
3. 反过来说：**服务器上如果 pytest 红了，大概率是版本漂移或数据源不同，而不是移植 bug** —— 因为在这套版本 + 有数据的条件下它是全绿的。

---

## 汇总：需要你回答的 / 需要决策的

| # | 问题 | 为什么只有你能答 |
|---|---|---|
| Q4 | Windows Server 的运行形态（无头批跑 / RDP+GUI / 计划任务 / Service？是否 Server Core？） | 部署意图，代码里没有 |
| Q3 | 是否**要求** optimizer evaluator 与 Pipeline 数值一致？若不要求，允许的误差上限是多少？ | 这是验收标准，我不能替你定 |
| Q8b | 服务器上以 XLSX 还是 tracked CSV 为权威标定源？ | 取决于你是否需要在服务器上重标定 |
| Q10b | 主 checkout 的 `.agents/` `.codex/` `.planning/` `AGENTS.md` 是否要提交？ | 不是我产出的 |

## 汇总：建议优先修的（按风险排序）

| 优先级 | 问题 | 位置 |
|---|---|---|
| **P0** | `.ps1` 缺 raw_data 存在性 FATAL 检查 + `Copy-Item -Recurse` 二次执行可能嵌套 → **静默回退 CSV 标定，产出不同数字且无告警** | `port_retest_server.ps1:49`（补 `.sh:52-56` 的等价检查） |
| **P0** | pipeline runner 的 `pressure_state_valid` 硬编码 1 → **RMSRE 的压力有效性过滤完全失效** | `validate_shanghai_3d_real.py:529-530` |
| **P1** | 四臂 × BO 阶段 = **4× 线程超订**（`_inner = cpu_count()//2` 不知道有 4 个臂） | `optimizer_qnehvi.py:293` |
| **P1** | `.ps1` 无 PID 文件 / 无 nohup 等价物 → 关窗口/logoff 杀掉所有臂，且**无法找回** | `port_retest_server.ps1:75-79` |
| **P2** | pipeline runner 的 `max_outer` 静默丢弃（横幅还打印用户传入的值） | `validate_shanghai_3d_real.py:503` |
| **P2** | optimizer 路径无 envelope gate（当前基线不受影响，但换 seed/bounds 后无保护） | `core/evaluators.py:396-398` |
| **P3** | 数据仓无 pin、golden 数字无版本记录 | 无 submodule / `_CSV_STATUS.md` |
