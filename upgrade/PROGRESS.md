# 进度日志（PROGRESS）

每轮一段：`## iter N · 日期 · 条目`，正文写"做了什么 / 验证证据 / 下一步"。重基准条目用 **⚠** 高亮。

## iter 14 · 2026-07-20 · P1.5 D 缝 ✅（`b6ce215`）

- 指标/场提取段（202 行）→ `_extract_3d_metrics`（36 输入 → 25 名 bundle），
  工具一次成型（成熟度可见：零试错 apply）
- _run_3d_stack ~1150 行；门禁 suite 1250+10 绿、golden 位同 ×2
- 下一步：P1.5 E 缝（裁决+组装尾段），随后只剩最难的 C 缝

## iter 13 · 2026-07-20 · P1.5 B 缝 ✅（`ddf9c64`）

- h_v 机械群（5 闭包 + 初始场，186 行）→ `_build_hv_machinery` 工厂（23 显式输入，
  闭包捕获工厂形参；6 名 bundle 含跨缝可调用 _build_hv_local_3d）
- 工具两级进化并回同步：作用域感知（闭包内 return/形参不误计）+ 嵌套 def/lambda
  形参归位（A0/Dh 泄漏）——试运行两轮迭代出正确输入集才 apply
- _run_3d_stack ~1350 行；门禁 suite 1250+10 绿、golden 位同 ×2
- 下一步：P1.5 D 缝（指标/场提取，近纯函数段）

## iter 12 · 2026-07-20 · P1.5 A 缝 ✅（`9fcdbcc`）

- 415 行 setup/build 段**零手抄**抽出为 `_build_3d_problem(cfg)`（AST 名字流算 80 名状态包，
  文本手术逐字节搬移，收发元组同名单生成）；_run_3d_stack 1955→~1540 行
- 两次现场教训：①条件绑定名（19 个）触发 UnboundLocalError——工具加定赋值分析一次修全；
  ②一个源码标记 wiring 测试随迁（断言意图不变，指向新家）
- 手术工具入库 runs/tools/seam_surgery_3d.py，B/D/E 缝改常量复用
- 门禁：suite 1250+10 绿 / 0 败（重跑全量）、golden 位同 ×2
- 下一步：P1.5 B 缝（h_v 闭包群提升）

## iter 11 · 2026-07-20 · P1.4 契约测试 ✅（`6c727dc`）

- 六条评估器↔管线有意差异 → 机器断言（legacy 默认 / B 冻结 / 整形隔离 / 不路由 /
  2D choke 双向现状 / **D3 绊线**——rho_inlet_ref 四处在缺席断言，决议必触发）
- 主规则入档：Pareto 选点须经 Pipeline 复核；处置规则：绝不删断言了事
- 途中修正一次自己的断言（choke 词汇出现在管线注释里——改为 raise 语义断言）
- 门禁：suite 1250+10 绿 / 0 败（+6 契约测试）
- 下一步：P1.5 run_stack_3d 五缝拆分（A 缝先行）

## iter 10 · 2026-07-20 · P1.3 切片 C → **调查升级为 D3**（docs-only，无码）

- 现场核实推翻切片前提：不是"评估器缺参数"，是 **2D/3D 管线自身 G 口径不一致**——
  2D 显式钉物理 ρ(T_in,P_in)·u；3D 求解器根本没有 rho_inlet_ref 旋钮，首解捕获
  ρ(T_in,P_out_seed)，且评估器与自己的 choke 种子自相矛盾
- 量化（1D 种子，冻结测试点）：2D 亏 **7.38%**、3D 亏 **19.30%**；validate 用 ρ(T_in,P_in)
  换算实验 ṁ ⇒ 3D 管线系统性低于实验吞吐，偏差已被 γ_df 锚定部分吸收（标定纠缠）
- **D3 登记**（选项 a 全线物理 G / b 现状 / c 分维一致过渡；建议 c 先行 + a 立项调查）；
  P1.3-C 标 BLOCKED；openspec D4、审计报告 §2 同步修正
- 教训沉淀：连续第三轮"现场核实改写条目"（P1.2 已修、P1.3-B 范围、P1.3-C 升级）——
  协议 §1-2a 这步的价值已自证
- 下一步：P1.4 evaluator 契约测试（G 口径差异记"待决 D3"，不锁方向）

## iter 9 · 2026-07-20 · P1.3 切片 B ✅（`2ea1d37`）

- 3D 评估器 post-solve envelope 门上线：与生产管线同判据（压力地板 + 逐格 Mach），
  失败走既有 NaN+invalid → BO 罚值通道，零新语义
- **范围修正**：2D 管线自身无 post-solve 门（ledger O1）——2D 侧要不要引入是物理政策，
  登记 **DECISIONS D2**（循环建议 c 维持现状），不替 Alex 决定
- 假求解器单元测试 ×3 + wiring（8/8）；期间修了一处测试断言字符串错误（supersonic ≠ Mach）
- 门禁：suite 1244+10 绿 / 0 败、golden 位同、frozen-values 未动（健康工况零影响实证）
- 下一步：P1.3 切片 C（rho_inlet_ref）——第一个预期动数字的切片，§5 重基准流程伺候

## iter 8 · 2026-07-19/20 · P1.3 切片 A ✅（`7cbeee1`）

- 三处手抄 1D D-F 种子代数收归 `envelope.predict_outlet_p_sq`（位同：同式同序同常数 +
  frozen-values rel=1e-12 未动实证）；R_AIR 改权威别名
- BO 战役入口重置 extrap/choke 警告注册表（每战役粒度，设计理由记 openspec D2）
- openspec 变更 evaluator-envelope-authority 落档（切片 B/C 设计已定：post-solve 门复用
  罚值通道不 raise；rho_inlet_ref 预期动数字走 §5）
- 门禁：suite 1240+10 绿 / 0 败（+4 新守卫）、golden 位同
- 下一步：P1.3 切片 B（post-solve 门）

## iter 7 · 2026-07-19 · P1.2 验证收案 ✅（docs-only）

- **现场核实推翻条目前提**：HANDOFF §1 的两个缺陷（max_outer 静默丢弃、压力有效性字面量）
  **均已在上游修复**（`8ea7ce5` + 2026-07-11 波），且 `test_validate_pipeline_runner_wiring.py`
  四断言已锁死——连"读 CAP 冒充实际迭代数"的细节（07-12 发现）都有断言
- 本轮证据：实跑 19 个锁定测试（wiring + truth-table）全绿 6.13s；无码可写，收案
- 勘误：审计报告 §0/§6 曾转述 HANDOFF §1 为"仍在"——已改；P4.4 列明 HANDOFF 三处确认过时
- **协议进化**：§1 新增"开工先现场核实条目前提"步骤（本轮的教训制度化）
- 下一步：P1.3 评估器 envelope 权威统一（真·未修的缺口，审计 §2 已核实）

## iter 6 · 2026-07-19 · P1.1 架构审计 ✅（`2426861` 工具, `0aa775e` 报告）—— **Phase 1 开篇**

- 三路取证：AST import 图（新工具入库，34 核心边、3 违规 + main↔ui 环）+ 双 evaluator 逐能力
  diff + run_stack_3d 解剖/可变态清单（两个只读侦察兵，file:line 全核对到当前代码）
- **修正性发现**：双 evaluator 是 2D/3D 两个 BO 评估器（不是同物两版）；HANDOFF §2a 预解、
  §3a 热重播种两行已过时（aa3f477 修过）；真缺口是 post-solve gate 双缺 + 3D 手抄 envelope
  代数 + rho_inlet_ref 双缺；run_stack_3d 无重复但单函数 1955 行（五缝已标）；
  两个 W7b 同族潜伏缓存隐患（compute_geometry 共享 dict、_phi_grid 未冻结）
- 产出 `docs/ARCHITECTURE-AUDIT-2026-07.md`（后续 P1 的工作底稿，与 HANDOFF 冲突以它为准）；
  **P1.3-P1.9 已按审计重写回填**
- 另：Alex 调频定时器 25→15 分钟档（job d7888157，7/22/37/52）
- 下一步：P1.2 正确性债（HANDOFF §1，唯一没被审计推翻的原条目）

## iter 5 · 2026-07-19 · P0.5 文档纠偏 + D1 执行 ✅（`c4cccb7`, `059d306`）—— **Phase 0 收官**

- **D1（Alex 拍板：a）**：golden_3d.json（2 KB）入库，meta 侧车同步，重基准规矩定为
  "json+meta 同 commit 带 `!`"
- /check：死路径 D:\Postgraduate → 中性仓库根表述；runner 入库注记；§2 按 D1 改写
  （3D 直接 --check 入库基线；2D 仍本地捕获）
- pytest.ini 头注：128 核 -n auto 警告 + CI=true 精确门语义（HANDOFF §9d 收编进配置现场）
- 验证：strict-markers 收集 + 定点 1 passed；meta json 解析过
- **Phase 0 安全网 5/5 完成**（基线快照、依赖锁、响亮回退、测试基建、文档纠偏）；
  下一步 P1.1 架构审计（Phase 1 开篇）

## iter 4 · 2026-07-19 · P0.4 测试基建入库 ✅（`6521ba7`）

- `scripts/run_tests_server.ps1` 入库——官方跑法结束"untracked by choice"状态
- `golden_3d.meta.json` 侧车入库：sha256 4ae326dc… + 认证 commit 4b32da4 + 三次位同记录 +
  环境指纹（HANDOFF §9"golden 零版本记录"缺口关闭；重基准须同 commit 更新侧车）
- **DECISIONS D1 待 Alex**：golden json 本体（2 KB 文本）入库与否，循环建议入库
- 验证：json.tool 解析过、sha256 与在盘一致；无运行时路径变化（免套件，PROTOCOL §4 资产级）
- 下一步：P0.5 文档纠偏（/check 死路径 + pytest.ini CI 语义头注）——P0 收官项

## iter 3 · 2026-07-19 · P0.3 回退改响亮 ✅（`cdbe14e`）

- prebuilt-CSV 标定回退：info → **WARNING + ASCII 横幅**（W6 的 ASCII-only 约束遵守；
  info 在默认 logging 配置下不可见正是陷阱静默的机理）
- `data-repo.pin` 入库（仓库根）：SJTU-TPMSHX-data @ 823847e；原定 data/ 内路径不可版本化，已偏离记档
- 新测试锁定 WARNING 级（tpmshx logger propagate=False，测试里显式挂 caplog.handler）
- 门禁：suite **1236+10 绿 / 4 skip / 0 败**（+1 新测试）、golden **位同**；xlsx 在位行为不变
- 下一步：P0.4 测试基建入库（golden meta 侧车 + runner 入库；golden json 入库与否 → DECISIONS）

## iter 2 · 2026-07-19 · P0.2 依赖锁定 ✅（`abaa348`）

- `requirements-lock-server.txt` 入库：80 包完整闭包（含 BO 栈），--extra-index-url 内置可一条直装，
  指纹与基线同源（76b60e32…）
- `requirements.txt` 三档头注：裸下界 / devbox constraints / server lock 各自用途；
  纠正 torch "Optional/GPU" 过时注释、写明 BO 栈缺席事实（HANDOFF §9e）
- 验证：pip --dry-run 双文件 exit 0（PROTOCOL §4 新增"依赖元数据"行，免套件有据）
- 下一步：P0.3 raw_data 静默回退改响亮（首个碰运行时代码的条目，全门禁伺候）

## iter 1 · 2026-07-19 · P0.1 基线快照 ✅（`2c51eca`）

- 四门证据链（suite → golden → 3D real → lumped）串行跑完全绿，日志落盘 upgrade/logs/p01-*
- 基线数字：套件 1245 绿 / 4 skip / 0 败（10:41 + 9.3s）；golden 位同；3D gate PASS
  （RMSRE_dP 4.88%、RMSRE_Q 2.12%，16/16 valid）；lumped cross-flow vs Q_air 1.73%（与 07-13 口径一致）
- 插曲：validate 运行会改写 tracked 的 shanghai_3d_baseline.csv——本轮 diff 为 ULP 尾噪（1e-13），
  已回退；该"自改写 tracked 产物"设计味道移交 P1.2。skip 3→4 的差异待顺手查明
- 下一步：P0.2 依赖锁定

## iter 0 · 2026-07-19 · 循环启动（人工，Alex 在场）

- 主检出的 sCO2 光滑壁闭合 WIP 先过全套 suite（双 pass exit 0，lastfailed 空）后提交为
  master `4b32da4`（37 文件 +4471），未 push
- worktree 建立：`E:\LWH\SJTU-TPMSHX-upgrade`，分支 `upgrade/loop`，基点 `4b32da4`
- 非跟踪资产复制：`data\`（17 MB，含 raw_data 与 sCO2-CFD）、`golden_3d.json`、
  `scripts\run_tests_server.ps1`
- 环境复刻：venv（C:\Python312 底座）+ 80 包精确冻结（torch==2.11.0+cpu 走 pytorch cpu 索引，
  其余走 PyPI，--no-deps 装完整闭包）
- 就绪门（全部通过，2026-07-19）：`pip check` 无破损依赖；worktree 内全套 suite 双 pass
  exit 0 且 `.pytest_cache` 无 lastfailed（零失败）；`_golden_3d.py --check golden_3d.json`
  位同（链条对 golden 失败有独立 exit 2 出口，走到底即位同）。精确计数因后台输出截断未留存，
  P0.1 重跑时落盘补记
- 决策记录（Alex，2026-07-19）：架构优先；**允许有据重基准**（PROTOCOL §5 的流程约束）；
  全天候 ~25 分钟一轮，撞 5h 限额自动等窗口重置续跑
- 决策补充（Alex，2026-07-19）：P0/P1 用 Fable 5 max 直做；P2 起循环自评——机械项派
  Sonnet 5/Opus 子代理执行、Fable 5 复核+验证+提交，判断项 Fable 5 直做（PROTOCOL §10）
