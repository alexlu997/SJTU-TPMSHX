# 进度日志（PROGRESS）

每轮一段：`## iter N · 日期 · 条目`，正文写"做了什么 / 验证证据 / 下一步"。重基准条目用 **⚠** 高亮。

## iter 43 · 2026-07-21 · P1.8b W0 身份垫片 ✅——**双风格同对象，迁移从此顺序无关**（`88b63e9`）

- Alex 拍板"启动 P1.8b"。W0 = openspec 三件套 + 身份垫片 + venv editable
- **垫片核心**：新建 `sjtu_tpmshx/__init__.py`（原 namespace 包）——自举 + 前插
  meta-path finder，`sjtu_tpmshx.X` 与顶层 `X` 解析为同一模块对象 ⇒ 双风格混用
  无法再产生双状态（warn 注册表/logutil logger/缓存），W1..Wn 任意顺序任意粒度安全
- 实现抓到两个 CPython 实测坑：① reload 后类对象换新使 isinstance 判重失效 → finder
  装双份（改类属性标记判重）；② import 机制在 create/exec 之间把被别名模块的
  `__spec__` 改绑为包名 spec（`reload(solvers)` 会静默降级 no-op）→ exec_module 恢复
- 身份测试 7/7；editable 后**包外任意 cwd 也拿到同一对象**（新能力）；pip check 净
- **门史（一红一假红，均已记档）**：首轮红 = mypy "found twice"（新 __init__ 使上溯
  出双模块名，静态世界的双风格问题）→ `explicit_package_bases = true`（cwd 基底位同
  语义）；重跑套件绿但 golden 步骤路径误写 validation/（正确 runs/_out/）→ 单步补跑
  **PASS 位同**；补跑 exit 1 系 **PS 5.1 stderr 包装假红**（求解器日志走 stderr 被
  2>&1 包成 ErrorRecord），以判定行为准——环境备忘新坑
- 门证据：套件 **1275+4skip（18:57）/ 10 绿**（+7 = 身份测试）+ golden **位同 PASS**
- 下一步：W1 tests/ 73 文件迁移（§10 委托子代理 + 复核）

## iter 42 · 2026-07-21 · P1.3/P1.5 关账 ✅——**前提修正：#4 早已落地，零代码**（docs-only）

- Alex 批准原建议（"补做 #4 警告注册表 + 关账"），开工核实即推翻前提：**#4 已于
  iter 8（`7cbeee1`）随 P1.3-A 落地**——qnehvi `_reset_warn_registries()` 战役入口调用，
  测试 `test_qnehvi_campaign_resets_warn_registries` 钉住粒度决策（per-campaign：
  500 评估战役内仍去重，镜像 ComputePipeline.run；per-design 反而会刷屏）
- 循环误报根因：iter 41 答疑时只 grep 两个评估器文件本身，漏了上一层 qnehvi 战役
  入口——**"评估器入口"字面被 iter 8 有意收窄为"战役入口"且有测试背书**，本轮核实
  qnehvi 为评估器唯一批量调用方（一次性脚本=新进程，注册表无陈旧态），收窄成立
- 关账：P1.3 勾选（四子项决议映射：①iter 8 ②iter 9+D2(c) ③iter 41 D3(c) ④iter 8
  战役级）；P1.5 勾选（数据类化 ✓ P2.0，文件级迁移归 P1.8b，无独立余量）；
  Phase 1 头部余留注记改为"仅 P1.8b 波次"
- 验证：docs-only（ROADMAP/STATE/PROGRESS/progress.html），零代码零门，免套件有据
- 下一步：回待命。P1 真余量收敛为 P1.8b 一项，与 Phase 5 候选池 A2/B/C/D 同级待拍板

## iter 41 · 2026-07-20 · D2(c)+D3(c) 执行 ✅——**双前提修正、零重基准**（`20031ba`）

- Alex 拍板（"可以，按你的建议开始吧"）：D2=(c) 现状+文档化、D3=(c) 分维一致先行 +
  (a) 立为候选 A2。本轮执行两条已决
- **前提修正 ①（D3）**：背景里"2D uniform 亏 7.38%"是 **1D 种子算术假象**——2D 捕获回退
  发生在压力场建立之前（simple_solver.py solve() 头注），捕获值=构造密度=ρ(T_in,P_in)，
  评估器一直钉的就是物理 G。实测冻结两元组**位同零移动**（+0.00% 全项），预备的 §5
  重基准未动用 ⇒ 改动性质=语义加固（防未来重建/复用模式漂移），非数值修复
- **前提修正 ②（D2）**：背景里"2D 管线从未有过 choke 守卫"失实——solve_2d 自 2026-06-25
  起有解后可压有效性门（与 3D 同款三档）；真正无解后门的只有 2D 评估器，(c) 更稳
- 改动：evaluator.py 双侧补显式 `rho_inlet_ref=ρ(T_in,P_in)`；绊线契约更名
  post_d3c 并新增 4 断言守候选 A2 之门（3D 评估器/求解器禁长旋钮）；DECISIONS D2/D3
  回写"执行+前提修正"；atlas optimization 卷收编
- 3D 侧刻意不动：19.30% 出口基准 G 亏空**真实成立**（首次真解后捕获，机理与 2D 不同），
  候选 A2 立项理由不变
- 门证据：套件 **1268+4skip（12:45）/ 10 绿** + golden **位同 PASS**（日志 upgrade/logs/iter41-*）；
  契约 6/6 绿；ruff 绿。吸收 tick ×3（跑门期间）
- 下一步：回待命模式（候选 A2/B/C/D 待 Alex 拍板启动）

## iter 40 · 2026-07-20 · 收尾轮 ✅——**ROADMAP 全清，循环转待命**

- 终审认证门（HEAD 含全部 82 提交）：**1268+4skip / 10 绿（10:40）+ golden 位同**——
  分支盖"可合并"戳，日志 upgrade/logs/final-*
- `upgrade/FINAL-REPORT.md`：一页摘要（七大交付表）、合并指南（本地 master 未动可快进；
  远端核对流程；CI 首跑预期；upgrade/ 目录三选一处置建议 a 原样合入）、
  D2/D3 + Phase 5 四池选单（规模/风险/依赖注记）、开放项六条、待命模式说明
- 待命模式启动：tick 只查新 `已决` 与 STATE next 改写，无事静默；定时器照常 §8 维护
- **循环全程战报**：40 轮 / 两日 / 29 正式条目 + 2 插单全清；零红灯、零重基准、
  golden 全程位同；套件 +23 至 1268；四常驻门；真雷 6 处修复；4 次证据确凿的
  零改动裁决；2 次前提坍塌纠正（DRIFT.md/死代码）；D1 已决执行、D2/D3 备齐待拍板

## iter 39 · 2026-07-20 · P4.4 HANDOFF 刷新 ✅（`312ac37`）——**Phase 4 收官，主线全绿**

- 体例裁决：HANDOFF 是 07-11 的**证据快照**（问答体+证据分级），改写原文会毁证据链——
  改为文首挂 16 行"状态总更新表"（问题→现状→证据 commit）+ §1/§2/§3 三节结论行内戳
- 对账结果：§1 上游已修（P1.2）、§2 已解（aa3f477+P1.3 双层）、§3 契约已立且分歧升 D3、
  §8a/§9a/§9b 已解（data-repo.pin/golden 入库/锁 83 包）、§9c 被锁文件取代、
  §5 部分超越（**本循环即 Server 2022 实跑证据**：1268 绿 × 数十轮）、§6 部分解
  （BLAS 时序缺陷留 Phase 5 候选 C）、§10 过时（atlas 已入 master）、§4/§7 仍开放
- AGENTS.md 尾巴收案：基点树 git 历史均无此文件（当年开发机未跟踪文件），无可修对象
- **Phase 0–4 主线全部完成**（iter 1–39，39 轮：P0 安全网 5 项、P1 架构 9 项、
  P2 质量 8 项、P3 性能 3 项、P4 文档 4 项 + 中途插单进度页/候选池）
- 下一步：收尾轮（合并前清单 + Phase 5 选单 + 终审报告）

## iter 38 · 2026-07-20 · P4.3 CI 增强 ✅（`f6b6a5a`）——评估变抓虫

- **发现真缺陷**：test_lint_gate/test_type_gate 是无 skip 守卫的 subprocess 调用（有意——
  门不许静默消失），而现行 ci.yml 不装 ruff/mypy → **分支合并 master 后 CI 必红**。
  这把 P4.3 从"可选增强评估"升格为"必修"
- 修复即增强：install 行 +ruff+mypy（CI 从此真执法 lint/type/layering 三静态门）；
  选择表达式 `not slow` → `not slow and not heavy`（剔 21 个最重 3D 积分测试——CI 定位
  smoke/静态层，物理回归归本地全量门，ULP 钉定 CI=true 本就跳过）
- 验证：manifest nodeid 平台中立性核过（conftest basename 归一）；slow∩heavy 重叠恰 3 文件；
  本地收集 1223/1282（59 反选）、三门测试在子集内。**改动只入库不推送**（红线），
  Alex 合并后 CI 生效
- 插曲：轮中 Alex 暂停 loop（定时器 ef9566f6 删除），恢复时重建为 c87569d6；
  半截工作树跨暂停无损收尾
- 下一步：P4.4 HANDOFF 刷新（Phase 4 最后一项）

## iter 37 · 2026-07-20 · P4.2 数字口径复核 ✅（`978c066`）+ §8 定时器重建

- **复核结论：headline 数字零漂移**——README/PROJECT_MANUAL 的 1.73/≈10/≈3/4.88/2.12/
  8.62/2.49/p_obs≥2.07 全部与 BASELINE.md 实测一致；V&V 叙事自洽（"≈5.3%"是标注清楚的
  旧 runner 门网格历史值；4.93→4.88 等链条均为带日期的沿革记录）。ROADMAP 立项时担忧的
  "1.71/1.73 类问题"不存在
- 真正过时的两处已修：Tested-on 增 **Windows Server 2022**（128 核 EPYC 2026-07 全套
  复验证）；README/手册测试命令区增服务器双跑脚本 + 56s 快档指引（-n auto 128 核卡死
  陷阱从 atlas 提升到用户文档）
- **§8 定时器重建**：d7888157（07-19 布防）→ **ef9566f6**（07-20 重建，spec 不变
  `7,22,37,52 * * * *`），armed_at 更新，下个重建窗口 07-25 前
- 下一步：P4.4（HANDOFF 刷新）——P4.3 CI 评估轮先行

## iter 36 · 2026-07-20 · P4.1c 外围域收编 ✅（`006e99f`+README 补丁）——**P4.1 整项收案**

- ui-core：13→14 mixin（MRO 全列更新）、run_controller 912+run_results 328、write_result
  迁址、行号影响边界（≤350 安全）；收编节含 iter 28 依赖测绘结论与 except 政策
- runs：**"唯一被 UI import 的例外"条目消除**（polygon_calc 迁 ui/）、根目录 14→13、
  tools 5→8（审计/manifest/缝手术三件入册，缝手术标注"一次性工具留档"）
- solvers-2d：threads 52→102 + P3.2 机制全记（含 caplog/tpmshx. 前缀陷阱）；
  solvers-closures：chi_s "导入时读取一次"**过时断言改正**（P1.6 每调用读）+
  geometry 缓存拷贝语义（W7b 防御两件）收编节
- PROJECT_MANUAL §6 节首挂 07-20 增量索引（8 组新增/迁移一句话 + cli.py 与 design/cli.py
  撞名辨析，细节指向 atlas）；atlas README 收案状态 + 摘要区两处回声修正
- 工艺教训：heredoc 传中文 python 脚本再遇 GBK 损坏——改走 Write 工具落盘执行（稳定复现
  的环境约束，已是第二次踩，此后一律 Write+执行）
- **P4.1 战果**：10 卷收编、7 卷盘点判定无分支级失准；三轮 docs-only 全程零代码风险
- 下一步：P4.2 README 数字口径复核

## iter 35 · 2026-07-20 · P4.1b atlas 架构域收编 ✅（`0fad954`，docs-only）

- pipelines.md：run_stack_3d 重组入册的关键决策——**不逐行重标定**（2107→3001 行全漂移），
  改为 ⚠ 头注声明 + 编排链新行号（:586/:1106/:2128/:1339/:1627/:2975）+ 旧行号段→新函数
  归属映射表；"逻辑逐字节未动（golden 位同护航）"是给读者的定心锚
- controllers.md：PEP 562 惰性（cli 零 Qt 的关键一环）、pipeline_for 有了首个生产消费方、
  P2.5a 行号影响面（≤350 不受影响的精确边界）
- core-domain.md：evaluators 433→639 新结构（:46 envelope 导入/:59 R_AIR 再导出/
  :66 后解门/:145 evaluate_3d）；D3 绊线与契约测试入册
- optimization.md：P3.3 重写"BO 内层线程"段；**诚实注记**：本卷 07-12 审计指出的
  parallel_runner BLAS 钳制时序缺陷分支未修（与 numba 主热点不相干，留 Phase 5 候选）
- 下一步：P4.1c 外围域（ui-core/runs/solvers 小修/PROJECT_MANUAL §6），P4.1 收案

## iter 34 · 2026-07-20 · P4.1a atlas 基建域收编 ✅（`433eb2b`，docs-only）

- tests.md 六处失准就地改正：文件数 151→162、marker 两→三（+heavy）、conftest 两→三件
  副作用、`-n auto loadscope`+"≈1037" → 双跑脚本+1268+10 现况、"精读 151"回声；
  文末收编节：五常驻门/fast-tier 机制/golden 入库(D1)/双脚本/计数沿革
- repo-infra.md 五处改正含一处**原生错误**（threads 包路径笔误 df_surrogate→solvers，
  非漂移是笔误）+"未发现 pyproject"过时断言；文件表 +7 行；收编节：打包地基/CLI/
  质量门四件套/锁 83 包/环境变量新增/upgrade 目录
- 打法定型：失准处就地改正标 ⟨07-20 更新⟩（保考古线索），结构性新增进文末收编节；
  atlas README 加滚动收编状态行
- 下一步：P4.1b 架构域四卷

## iter 33 · 2026-07-20 · P4.1 atlas 盘点 ✅（docs-only，前提修正）——Phase 4 开张

- **前提坍塌（第二例，处置同 P2.3）**：ROADMAP 所称 DRIFT.md 全库不存在——播种时臆想
  产物，漂移只活在提交信息/PROGRESS 里。章程修正：不造间接层，直接写回卷
- 盘点：分支 vs 基点 4b32da4 共 164 文件变更；结构性漂移 = 新文件 15（pyproject/cli/
  _version/run_results/五守卫测试/三工具/双脚本等）+ 结构性改动（run_stack_3d 拆分、
  controllers 惰性、evaluators 权威、threads advisory、geometry 拷贝语义）
- 受影响卷映射（合计 3571 行，可控）：三域三轮——P4.1a 基建（repo-infra/tests/README）、
  P4.1b 架构（pipelines/controllers/core-domain/optimization）、P4.1c 外围
  （ui-core/runs/solvers 小修/PROJECT_MANUAL §6）；HANDOFF 单列 P4.4
- 下一步：P4.1a

## iter 32 · 2026-07-20 · P3.3 BO 核预算 ✅（`e233460`）——**Phase 3 收官**

- _resolve_core_budget 提取：钳制 [1, cpu_count] + 来源标签四态；并行启动一行 INFO
  （workers × inner × 预算来源）——多臂并发（port_retest 四臂类）从此可审计
- 默认/合法路径行为逐字节不变；唯一语义变化 = 超机预算钳制（堵 07-11 超订 bug 残留口）；
  env 索引补录 TPMSHX_BO_CORE_BUDGET（此前缺失）
- 测试 +7（解析矩阵全分支，helpers 19 绿）；门禁 1268+4skip / 10 绿（10:45）、golden 位同
- **Phase 3 完**（fast-tier 20×、线程建议、BO 预算——三项全数落地，iter 30–32 三轮）
- 下一步：P4.1 atlas 漂移收编（先盘点 DRIFT 存量 + 升级分支自身新漂移）

## iter 31 · 2026-07-20 · P3.2 线程建议 ✅（`547b7d0`）

- recommend_solver_threads（min(64, 逻辑核/2, 池上限)；本机 64/128）+ warn_if_default_pool
  一次性建议，挂 simple_solver_3d 并行分派真分支；三静默分支（env 已设/GUI 已调低/小机器）
- 设计约束写死：**绝不自动改池**——prange 归约序变更位移且生产网格无 golden 覆盖，
  advisory-only；不变量护栏两审零物理接触
- 测试 +3（1258→1261）；教训入档：logutil 挂 `tpmshx.` 前缀根且 propagate=False，
  caplog 失明 → 直挂模块 logger；快档 dogfood 首战 45s 抓获开发中真失败
- 门禁：1261+4skip / 10 绿（10:32，空载快跑）、golden 位同
- 下一步：P3.3 BO 预算 ergonomics（先现场核实）

## iter 30 · 2026-07-20 · P3.1 fast-tier ✅（`53431bb`）——Phase 3 开张

- census 轮（--durations=0 镜像服务器环境，双 pass）：265 计时测点 / 4620s 计算量；
  阈值扫描 300/120/60/30/20/10/5s 全表——**30s 档最优**：21 测试（1.7%）承载 89% 计算量，
  heavy 全是 3D 积分测试（conservation/partial_bc_ghost_b/asym_porosity 等 6 模块）
- 机制（零测试文件改动）：manifest 入库（生成器可重生）→ conftest 收集期动态 heavy 标
  （basename 归一，调用目录无关）→ run_tests_fast.ps1 排除；反选精确 21
- 实测 **56s vs 19min（20×）**：1237+4skip 46.5s + 串行模块 8.8s，全绿
- 红线三处写死（脚本/marker 文案/manifest 头注）：快档绿 ≠ 过门；slow 语义未碰
- 门禁：双 pass 1258+4skip / 10 绿（18:47）、golden 位同
- 下一步：P3.2 线程默认值

## iter 29 · 2026-07-20 · P2.5a run_controller 单刀 ✅（`86b12e4`）——**Phase 2 收官**

- 五方法（write_result/_finalize_plots/_update_result_summary/_diag_summary_text/
  _show_diag_dialog）逐字节搬至新 RunResultsMixin（AST 比对 HEAD 五方法体位同）；
  run_controller 1215→912 行，头注清单 18→13 并注明去向；MRO 插位紧随 RunController
- 冒烟：五方法经 Main_Menu MRO 全解析至新 mixin、旧 mixin 不再定义；ruff 绿；
  唯一模块级依赖 TOAST_MS_SHORT 随迁
- 门禁：双 pass 1258+4skip / 10 绿（19:03）、golden 位同、直击三测试
  （finalize_3d_result_sync/orch_finished_3d_state/run_controller_preflight）绿
- 轮中插曲（用户请求，两个独立 docs 提交）：进度页 render_progress.py + progress.html
  入库（d7c948b，PROTOCOL §9 增每轮重渲）；Phase 5 候选池立项（f8b06d9，Alex 批准，
  三池选单，候选不计完成度）
- **Phase 2 全线完成**（P2.0 数据类化 / P2.1+b+c lint 三波 / P2.2 类型门 / P2.3 死代码 /
  P2.4 异常日志 / P2.5 GUI 减脂——iter 21–29，其中四轮为证据确凿的零改动裁决）
- 下一步：P3.1 fast-tier（先取 --durations 数据）

## iter 28 · 2026-07-20 · P2.5 首轮：mixin 依赖测绘 ✅（docs-only，章程收窄）

- AST 交叉引用矩阵（14 文件：13 mixin + main）：**耦合低，架构判定健康**——多数 mixin
  依赖 0–3 个同伴，zone_panel/io_actions 零 fan-in，枢纽 shortcuts(用7)/session_presets(用6)/
  main(用7)。原设想"13-mixin 是巨物问题"被证据推翻：mixin 分层本身是合理的责任划分
- 真靶标唯 run_controller 1215 行（20 方法），四责任区测绘：启动/预检 35–350、
  orch 信号处理 495–801（_on_orch_finished 528–716 独占 188 行）、结果呈现 351–494+1003–1165、
  计算 UI 状态 802–1002+1166–1215。保护面 3 直击测试 + 17 Qt 测试，无 golden
- 章程裁决：**只切一刀**（P2.5a 结果呈现区 → run_results.py，1215→~845）；ui 273 except
  存量不动（churn 风险>>收益），新代码 logutil——政策一行即收，不立扫改波次
- 下一步：P2.5a 执行（Fable 直做——方法搬移涉 MRO/keep-alive 判断，不派机械子代理）

## iter 27 · 2026-07-20 · P2.4 异常/日志策略 ✅（盘点轮，docs-only，零批次）

- 人口普查：0 裸 except；400 处 except Exception（ui 独占 273 = 68%）；库内 print 144
- 核心三目录 28 处逐站分类：全为存证故意——发现 **2026-07-03 已做过一轮 except-audit**
  （sigmoid_field/flux_3d 留有审计注释，静默 fallback 当时已放响）；余为 warmup 尽力型（注释在）、
  CoolProp 能力探测、线程 err[i] 捕获后重浮、UI 回调护栏（吞对：坏回调不该杀数值解）、
  traceback 打响型。无 P0.3 族潜伏故障
- print 双层复核：95/144 在 __main__ 区；分类探针"活路径 49 处"系统性高估——逐函数核查
  全在 _self_test()/main()/demo（residual_correction 13 处全在 _self_test:263、
  surrogate_v3 11 处全在 main:619、predict 2 处在演示函数、parallel_runner 1 处是 CLI 输出）。
  **活求解路径 print = 0**
- 处置：ui 273 处移交 P2.5 章程（GUI 域政策，随减脂就地办）；无独立代码批次立项——
  连续第三轮"零改动"裁决，佐证历史审计（06-16 死代码、07-03 except、P0.3、P2.1/b）
  已把卫生欠账付清，Phase 2 剩余价值集中在 P2.5
- 下一步：P2.5 首轮（mixin 依赖测绘）

## iter 26 · 2026-07-20 · P2.3 死代码处置 ✅（盘点轮，docs-only，零处置）

- 命名靶标现场核实全部"活"：zone_config（104 引用/17 文件，ZoneInputConfig 是 2D 计算路径
  活数据结构）、zone_table（87 引用/8 文件，UI Define-zones 全套）——头注"DEPRECATED for
  optimizer use"语义准确，无需动；runs/archive frozen 声明 P1.7 已备
- 全库孤儿扫描（自写只读探针，165 库模块）：16 未导入者中 13 为入口脚本（正常），
  3 个模块嫌疑逐一复核全为**相对导入误报**（探针正则不识 `from .X import`）：
  _kernels_ltne_3d(1178 行) ← ltne_energy_3d:322；builders_sidebar ← builders_canvas:19；
  skeleton ← builders_canvas:1079（函数内惰性导入）。**0 真孤儿，0 删除候选，未立 D 条目**
- 方法论记录：未来孤儿检查挂 audit_import_graph 的真导入图做（正确处理相对/惰性导入），
  正则探针只配当一次性初筛；细粒度死代码（死名/死导入）已由 ruff F 门持续执法
- 下一步：P2.4 异常与日志策略（先盘点分类）

## iter 25 · 2026-07-20 · P2.1c ruff format 评估 ✅（纯评估轮，docs-only）

- **裁决：不做全库 format（本分支阶段性关闭）**。全部探测只读（--check/--diff），零代码改动
- 硬证据：①`ruff format` 影响 359/370 文件、3214 hunk、−20517/+38878 行（包总 87369 行，
  ~45% 搅动）；②atlas file:line 引用 2355 处 / 376 个唯一文件路径，全面腐蚀；③12 个测试文件
  读源码断言，23 处 quoted marker 中 ≥3 处引号敏感（`e_info.get('converged'`、
  `cfg.get('outer_anderson', False)`、`'p_clip_hits'`——format 把 ' 翻成 " 即断）+
  长表达式 marker（`_ALPHA_T * rho_new + ...`）有反流断裂风险；④调参救不回：
  quote-style=single + line-length=200 仍 360 文件重排（搅动源自缩进/空格/尾逗号归一）
- 附带成本盘点：git blame 断代（ledger/报告溯源链依赖 file:line 考古）；numba 磁盘缓存
  一次性全失效（无害）；merge-to-master diff 被排版噪声淹没（升级分支"每个 diff 可审"承诺破）
- 未来重启三前置（写入 ROADMAP 条目）：atlas 锚点化或同波重基线；marker 全改 AST/标识符级；
  master 合并后独立 format-only 提交 + .git-blame-ignore-revs
- 下一步：P2.3 死代码处置（先盘点，删除项过 DECISIONS-NEEDED）

## iter 24 · 2026-07-20 · P2.2 mypy 核心面门 ✅（`464076d`）

- 宽松档 [tool.mypy] + 七文件核心面清单（envelope/compute_pipeline/domain 配置结果/
  configs/_version/cli）清零：compute_config 3 处注解性修正（异构 dict 先声明后分支赋值、
  gate-check 循环变量改名破类型合一、补 Tuple 导入）+ cli warnings_list 收窄——零物理默认值变动
- test_type_gate 常驻（subprocess mypy @清单，cwd=包目录与顶层导入约定一致）；check.md §2a2 入册；
  锁文件 80→83 包（ruff/mypy 入锁）
- 门禁：suite 1258+10 绿 / 4 skip（19:06，负载偏高段）、golden 3D 位同、
  mypy "Success: no issues found in 7 source files"
- 流程：开工首个 Edit 即 STATE 标记（iter 23 教训，本轮已守）；轮中撞 /compact 一次，
  后台门任务跨压缩存活、凭 task 通知收轮
- 勘误：iter 22/23（及 pyproject 内 P2.1/P2.2 溯源注释）曾误记日期 2026-07-21，git 时间戳
  实为 07-20——PROGRESS 本轮已改；pyproject 注释留待下次正当编辑该文件时顺手改（避免
  纯注释改动空耗一轮套件）
- 下一步：P2.1c ruff format 评估（纯评估轮）

## iter 23 · 2026-07-20 · P2.1b F841 清偿 ✅（`581e790`）＊日期按 git 时间戳修正（原误记 07-21）

- 52 处初判 + 5 处级联全清（净 −46 行）：死解包/死拉取/jit 内核死载入（A/B 侧 ef ×4，
  golden 位同护航）/标量旧方案遗骸（T_avgA/B）/整死 if-else（stages_2d 行均孔隙率）/
  U_sf 超表速度残迹；Qt keep-alive 语义保全（app→_app）、副作用调用去名留调
- pyproject 移除 F841 ignore——**全量执法开启**；批量手术脚本逐行断言护航零失配
- 流程小疵自纠：开工漏写 in_progress 标记（连续第二次，iter 8 后再犯）——收尾时发现，
  下轮起开工首个 Edit 必须是 STATE 标记
- 门禁：suite 1257+10 绿、golden 位同
- 下一步：P2.2 类型注解

## iter 22 · 2026-07-20 · P2.1 ruff lint 门 ✅（`121413d` 机械 + `6e65487` 语义）＊日期按 git 时间戳修正（原误记 07-21）

- 352 发现 → 0：238 自动修 + 7 F821 逐案（**三真雷**：Save Preset 即崩的缺导入、
  pin 分支未定义变量、直跑块引用已亡测试）+ F841 缓议 P2.1b + format 单列 P2.1c
- 两次红灯全是仓库防御工事的胜利：tests/design 收集崩抓住 tpms_calc 门面被删、
  test_pipeline_reexports 锁面测试抓住 stages_2d——门面豁免清单由实证驱动补齐；
  41 文件被删名属性引用全扫零受害
- lint 门常驻 + /check §2a + 锁刷新（81 包，指纹 0e079835f744709…完整值此处存档）
- 门禁：suite 1257+10 绿（第三跑）、golden 位同
- 下一步：P2.1b F841 人审

## iter 21 · 2026-07-20/21 · P2.0 数据类化 ✅（`d0238e6`）—— **§10 委托首战**

- Sonnet 子代理执行（80/6/22/25 字段四数据类 + 五签名坍缩 + 解包块；自带 AST 交叉核验），
  Fable 复核（diff 定点审：残差全在允许模式内、零函数体泄漏）+ 门禁 + 签发
- 委托模式验证成功：规格逐名指定 + 禁改函数体 + 禁跑套件禁提交 → 执行方零歧义返工
- 门禁：suite 1256+10 绿、golden 位同 ×2；文件级迁移并入 P1.8b
- 下一步：P2.1 ruff（继续委托模式）

## iter 20 · 2026-07-20 · P1.9 分层裁决 ✅（`c43c7db`）—— **Phase 1 主线收官**

- 两修：polygon_calc（Qt 耦合 UI 代码）迁回 ui/；__version__ 抽 _version.py 叶子
  （ui→main 环消除，pyproject 转 dynamic 版本单源）
- 两裁：solvers↔df_surrogate 闭合边界互依对、domain→_domain 叶子常量——SANCTIONED
  清单内置工具（附理由），报告单列
- 层级门常驻：test_import_layering 进套件、/check §2b；**VIOLATIONS = 0**
- 门禁：suite 1256+10 绿、golden 位同；19 分钟套件尖峰确认为瞬时负载（本轮回落 10:31）
- **Phase 1 战报（iter 6-20）**：审计 → 验证收案 ×1 → envelope 权威+门 ×2 切片 →
  契约测试 → 五缝拆解（1955→156）→ 缓存卫生 → 死路径 → 打包 → 分层裁决；
  全程 golden 位同、零带病提交；待决 D2/D3 不阻塞
- 下一步：Phase 2 开工，P2.0 = §10 委托首战

## iter 19 · 2026-07-20 · P1.8 打包地基 ✅（`827bee9`）

- pyproject（extras 分组、包数据、诚实的 P1.8b 注记）+ tpmshx-run headless CLI
  （--dry-run 实测 Pipeline2D）+ controllers PEP 562 惰性导出（接缝零 Qt 实证）
- 一次性 venv editable 安装冒烟全过；**工作 venv 未动**（循环环境稳定优先）
- P1.8b 立项（导入风格全库迁移 + 引导分波删除 + venv 转 editable——§10 委托候选）
- 门禁：suite 1255+10 绿、golden 位同
- 下一步：P1.9 分层违规裁决（P1 收官项）

## iter 18 · 2026-07-20 · P1.7 死路径清理 ✅（`dd598d9`）

- smooth_df rebuild 死路径：显式 FileNotFoundError 守卫（溯源+修法）+ env 覆盖口
- 4 工具脚本 Desktop/D:\ → env 覆盖 + runs/_out 默认；vault 输入指向现实布局
- archive/ 增补"死路径故意不改"证据链声明（尊重既有 frozen README）
- 门禁：suite 1255+10 绿、golden 位同。注意：全量套件连续三轮 ~19 分钟
  （高负载 or 用例增长），P3.1 fast-tier 优先级↑
- 下一步：P1.8 pyproject 打包（P1 尾声）

## iter 17 · 2026-07-20 · P1.6 缓存与 env 卫生 ✅（`7d70227`）

- 两个 W7b 潜伏炸弹拆除：compute_geometry 共享 dict → 浅拷贝入口；_phi_grid 共享
  ndarray → writeable=False（写入即炸）
- TPMSHX_CHI_S 改 per-call（import 冻结的 K_ss reload 隐患）；AMG 缓存补 reset 钩子
- +5 守卫测试；chi_s 优先级测试从"patch 模块全局"改为 setenv——旧写法正是冻结
  逼出的变通，佐证修复价值
- P1.5 收尾评估定案：五缝判完成；数据类化+文件迁移降为 **P2.0**（首个 §10 委托候选）
- 门禁：suite 1255+10 绿（重跑全量）、golden 位同；invariant-guard 钩子首次触发（合规）
- 下一步：P1.7 死路径清理

## iter 16 · 2026-07-20 · P1.5 C 缝 ✅（`2549a79`）—— **五缝收官**

- 最难一缝的解法："整块搬移"（状态初始化+闭包+驱动 730 行同走）让 nonlocal 域内自洽，
  预想的"显式耦合态对象"根本不需要
- nonlocal 重绑名（Ta/Tb/Ts/chi_B/h_v 场/K_ffB）= **in-out 双身份**：初值形参进、终值 bundle 出
  ——工具为此补最后两刀（条件 import 首现、nonlocal 输入合成），全程 golden 当场纠错
- **_run_3d_stack：1955 → 156 行**（build→hv→outer→extract→verdict 纯编排）；
  又一个源码断言随迁（test_outer_anderson）
- 门禁：suite 1250+10 绿（重跑全量）、golden 位同 ×2
- 五缝总账（iter 12-16）：五段共 ~1930 行逐字节搬移，零行为漂移（每步 golden 位同），
  工具从朴素块搬移进化出七项静态分析能力，全程由门禁当场纠错、零带病提交

## iter 15 · 2026-07-20 · P1.5 E 缝 ✅（`694e5fa`）——工具毕业考

- 裁决尾段（401 行）→ `_assemble_3d_verdict`（81 输入 → _result；return 留守）
- 工具连修三个静态分析盲区（每个都由 golden/运行时当场揪出，零带病提交）：
  AugAssign 隐式 load、先读后绑 in-out（顺序敏感首现）、嵌套推导式作用域（抑制集穿线）；
  Nonlocal 自由变量支持顺手装上（C 缝前置）
- _run_3d_stack **1955 → ~750 行**；门禁 suite 1250+10 绿、golden 位同 ×2
- 下一步：P1.5 C 缝（最难的外循环闭包，8 nonlocal）

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
