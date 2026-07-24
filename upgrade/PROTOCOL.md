# 升级循环协议（PROTOCOL）

本文件是自主升级循环的执行契约。**每轮迭代的第一步是重读本文件与 STATE.md**——上下文可能已被摘要压缩，磁盘上的这份才是真源。

## 0. 身份与边界

- 工作区：`E:\LWH\SJTU-TPMSHX-upgrade`（git worktree，分支 `upgrade/loop`，基点 master `4b32da4`）
- **主检出 `E:\LWH\SJTU-TPMSHX` 一律不写**；`E:\LWH\vault` 只读（唯一例外见 §5e 台账回写）
- **绝不 `git push`**；绝不动 master；提交只落在 `upgrade/loop`
- `data\`、`golden_3d.json`、`scripts\run_tests_server.ps1` 是从主检出手工复制的非跟踪资产，勿删勿改语义
- 会话模型/思考强度由 Alex 的 /model 决定，循环不假设也不更改

## 1. 每轮流程（一轮 = 一项）

1. 读 `upgrade/STATE.md`：若 `in_progress` 非空 → 先按 §6 恢复
2. 从 `upgrade/ROADMAP.md` 取**第一个**未勾选且未标 BLOCKED 的条目；把本轮目标写入 STATE.md `in_progress`
   —— **开工先现场核实条目前提**（文档会过时、代码在前进，HANDOFF/审计/路线图皆可能滞后）：
   前提已不成立 → 本轮转"验证 + 锁定 + 记账"，跑现有锁定测试留证据、勘误相关文档，绝不硬做
3. 实现（时刻对照 §3 红线）
4. 过 §4 验证门 → `git commit`（§7 风格）→ 勾选 ROADMAP 条目（附 commit 短哈希）→ PROGRESS.md 追加一段 → 清空 `in_progress`、`iteration` +1
5. 条目太大做不完一轮 → 把**已验证**的切片提交为阶段性 commit，剩余拆成子条目写回 ROADMAP（拆分也是产出）
6. 卡住 / 需要 Alex 决策 → `DECISIONS-NEEDED.md` 登记（背景+选项+循环的建议），条目标 BLOCKED，跳下一条；**绝不空转等待**
7. 每轮结束核对定时器（§8），然后自然结束本轮回复

## 2. 环境（每轮开工 30 秒自检）

- venv：`.venv\Scripts\python.exe`，底座必须 `C:\Python312`（查 `pyvenv.cfg` 的 home 行；Anaconda 底座会让 PySide6 崩 0xc0000139）
- **断言存在：`data\raw_data\试验记录表_整理版.xlsx`**——缺失 = surrogate 会静默回退到预构建 CSV，数字无警告地改变；立即停手写 DECISIONS
- 测试**只用** `scripts\run_tests_server.ps1`（自带 PYTHONHASHSEED=0、五个线程变量钉 1、QT_QPA_PLATFORM=offscreen、双 pass 策略；~11 分钟）；禁 `-n auto`（128 核超订死锁实测）
- 长跑用 `python -u`（否则块缓冲看着像挂死）；从仓库根跑；**不并发第二个重活**（并发 numba/Qt 进程会产生像测试失败的假死）

## 3. 硬红线（违反 = 真回归；源自仓库 CLAUDE.md，重构触及时逐条自查）

物理/数值不变量（详情见仓库根 `CLAUDE.md`，此处是清单不是替代）：
1. 可压缩 ideal-gas ρ(P,T) 是默认且必需——永不"简化"为等温
2. ε 只在 `solvers/ltne_energy.py` 一处减半；调用方传全 ε；非对称路径经 `solvers/asym_split.py` 上游拆分
3. 质量流量入口（massflux inlet）是两个维度的空气侧默认——不许回退 velocity-inlet
4. DF 闭合已含 SLM 粗糙度——**永不**外加摩擦/粗糙度乘子（双重计入）
5. Nu 系数单一来源 `solvers/nu_correlations.py`（NU_COEFFS / WATER_NU_COEFFS / SCO2_NU_COEFFS）——不许复制到别处
6. envelope/choke 守卫（`solvers/envelope.py`）不许拆、不许放宽 P_abs clip、不许对 ChokedFlowError"返回个数字"
7. `P_ref_abs` = **出口**绝对压（两个维度），种子来自 `envelope.predict_outlet_p_sq`，永不用 P_in
8. surrogate 换默认后端必须先过 `validation/cases/validate_shanghai_3d_real.py` 上海 3D 门

循环自身红线：
9. 不动 `devlog.md`（已废弃）；不动 `openspec/changes/archive/`；不重写 git 历史
10. 任何文件移动/改名/公共签名变更 → `docs/atlas/DRIFT.md` 追加一行（格式：`日期 | 旧位置 → 新位置 | commit`）。atlas 是 2026-07-11 快照，17 卷 file:line 引用靠 DRIFT.md 记账，Phase 4 统一收编
11. 测试基线 JSON（`tests/_data_df_projection_baseline.json`、`validation/*.meta.json`）只能经 §5 流程动

## 4. 验证门（按改动类别，证据先于结论）

| 改动类别 | 必跑 |
|---|---|
| 任何代码/测试改动 | `scripts\run_tests_server.ps1` 双 pass 全绿（exit 0） |
| 触及 solvers/ pipelines/ df_surrogate/ design/ optimization/ 数值路径 | 上行 + `python -u sjtu_tpmshx\runs\_out\_golden_3d.py --check golden_3d.json` 位同 |
| 触及闭合/surrogate/物性 | 上两行 + `validate_shanghai_3d_real.py` 与 `validate_shanghai_lumped_dual_nu.py`，数字对照 `upgrade/BASELINE.md` |
| 纯 docs / upgrade/ 协议文件 | 免测，commit 注明 docs-only |
| 依赖元数据的注释级改动（requirements* 头注、锁文件新增，无运行时路径） | 免套件，但须 pip --dry-run 解析通过 + 指纹核对，证据入 commit |
| 独立工具/诊断脚本（不被包或测试导入，如 runs/tools/audit_*） | 免套件，但须在 venv 实际运行成功（exit 0），证据入 commit |

- 报告**真实计数**（passed/failed/skipped），禁"基本通过"
- 红了就修或回退，绝不在红套件上宣称完成；连续 2 轮修不绿 → stash + DECISIONS + 跳条目

## 5. 数值重基准（Alex 2026-07-19 授权"有据重基准"）

默认仍是**位同**。重基准必须同时满足：
a) 根因写清到 file:line 级；
b) 全套 suite + golden --check + §4 第三行两个 validate 全部重跑并留下数字；
c) 重基准**独立成 commit**，类型带 `!`（如 `fix(solver)!:`），正文列出哪些字段动了多少、为何合理；
d) `DECISIONS-NEEDED.md` 登记为 `[已重基准-待复核]`；PROGRESS.md 高亮；
e) 向台账 `E:\LWH\vault\reports\_research-ledger-CN.md` 追加条目并署名"升级循环"——这是 vault 唯一允许的写入。

## 6. 中断恢复（5h 限额把上一轮杀在半路时）

- `STATE.md in_progress` 非空且工作树脏：
  - 改动完整可验证 → 直接走 §4 门禁收尾提交；
  - 否则 `git stash push -u -m "iter-<N>-interrupted"` → 该条目从头重做（stash 是证据，不许 drop）
- 定时器每 ~25 分钟触发；撞限额的那次触发失败**无害**，窗口重置后下一次触发自动续跑——机制不需要你维护，只需保证每轮收尾干净（状态都在磁盘/分支上）

## 7. 提交风格（沿用仓库惯例）

- 中文 conventional commits：`fix(solver):` / `feat(pipelines):` / `refactor(ui):` / `docs:` / `test:` / `chore(upgrade):`
- 重基准加 `!`；正文引用 ledger / HANDOFF 编号；行为不变的重构注明"golden 位同"
- 结尾一律：`Co-Authored-By: <当前会话模型> <noreply@anthropic.com>`——**署名跟随实际运行模型**（Alex 2026-07-25 起主会话切 Opus，见 §10；此前轮次署 Claude Fable 5，为如实历史不追改）
- **容量级变更**（新行为/新能力设计，如 P1.3 choke 罚值策略）：先写 `openspec/changes/<id>/`（proposal.md + design.md + tasks.md），实现后随实现 commit 一起归档——沿用仓库 spec-driven 流程；纯重构/修 bug/文档直接提交

## 8. 定时器自维护

- 会话内 cron 规格：`7,22,37,52 * * * *`（每 15 分钟档，Alex 2026-07-19 由 25 分钟档调频），提示词全文存于 STATE.md
- 每轮结束：`CronList` 查活任务；无任务、或 STATE.md `armed_at` 距今 > 5 天（cron 7 天自动过期）→ 重建（CronDelete 旧 + CronCreate 新）并更新 `armed_at`
- 会话死掉（服务器重启/终端关闭）后的复活：在 worktree 目录新开 Claude 会话说"继续升级循环"——本协议 + STATE.md + 用户记忆里的 sjtu-tpmshx-upgrade-loop 条目承载全部上下文

## 9. 通报

- Phase 完成、DECISIONS-NEEDED 出现新条目、或发生重基准 → ToolSearch 加载 `PushNotification` 推送 Alex 一句话摘要
- `PROGRESS.md` 是 Alex 的阅读界面：每轮一段"做了什么 / 证据 / 下一步"，写人话，别写流水账
- **进度页**（Alex 2026-07-20 要求）：每轮收尾簿记后运行
  `python upgrade/tools/render_progress.py` 重渲 `upgrade/progress.html`
  （<1s，解析状态文件+git，浏览器打开即看；重渲产物随簿记一并提交）

## 10. 模型分层（Alex 2026-07-19 指示；2026-07-25 改用 Opus）

**主会话模型（Alex 2026-07-25 更新）**：主循环改用 **Opus**（当前最新 = Opus 4.8；
Alex 原话"用 opus 5、暂不用 fable"——picker 无 Opus 5 型号，按最新 Opus 4.8 落地，
新型号出现即跟进）。**暂停 Fable 主循环**。cron 触发的是新会话，其模型 = Alex 的
`/model` 默认（已设 Opus 4.8），故自主轮自动跑在 Opus 上；本会话若仍为 Fable，
需 Alex 在本会话 `/model` 手动切（模型只能 Alex 改，循环改不了）。

- **P0 / P1：主循环（Opus）直接执行**，不委托。
- **P2 起（P3/P4 同理）**：每条开工时自评"机械型 vs 判断型"：
  - **机械型**（格式化扫、批量类型注解、模式化替换、文档扫尾等有明确模式可循的）→
    用 Agent 工具派子代理执行：默认 `model: "sonnet"`，中等复杂度用 `model: "opus"`
    （Agent 工具 model 参数只认家族名 sonnet/opus/haiku/fable，"opus"路由到最新 Opus）；
    **主循环（Opus）审 diff + 跑全部验证门 + 提交**。执行子代理只改文件，
    **不许提交、不许跑全套测试**（重活并发违反 §2，验证权归主循环）
  - **判断型**（行为/接口设计、无测试保护的重构如 P2.5、任何触及 §3 红线清单的）→
    Opus 主循环直接执行
  - 分类拿不准 → 按判断型处理（宁贵勿险）
- 委托提示词必须包含：具体文件清单、改动模式与例子、相关红线摘录、"完成后报告改动清单，不提交"
- 主会话模型由 Alex 的 /model 决定；若 Alex 主动降档，审查质量随之变化，循环不干预、不擅自改档
