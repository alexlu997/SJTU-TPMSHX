# 升级路线图（ROADMAP）

排序即优先级，从上往下做。勾选 = 完成（附 commit 短哈希）。BLOCKED 条目跳过并在 DECISIONS-NEEDED.md 说明。
一条 ≈ 一轮的量；太大的先拆再做。P1.1 审计完成后**回填细化**后续条目是预期行为。

## Phase 0 — 安全网（架构手术前的地基）✅ 完成于 2026-07-19（iter 1–5）

- [x] P0.1 基线快照（`2c51eca`，iter 1）：写 `upgrade/BASELINE.md`——suite 精确计数、`--durations` 前 15、
      golden_3d --check 结果、`validate_shanghai_3d_real.py` 与 `validate_shanghai_lumped_dual_nu.py`
      的 headline 数字（Δp / Q / RMSRE）、`pip freeze` 指纹。此后所有"数字没变"的断言都对照它。
      ⚠ 长命令输出必须 `| Tee-Object 日志文件` 落盘后读文件——PowerShell 后台任务捕获会丢
      pytest 进度流的尾巴（2026-07-19 两次实测，靠 exit code 才判的绿）
- [x] P0.2 依赖锁定（`abaa348`，iter 2）：`requirements-lock-server.txt`（本机验证过的 80 包冻结，torch==2.11.0+cpu
      需注明 pytorch cpu 索引）入库；`requirements.txt` 头注说明三档清单
      （裸 requirements / constraints-devbox-2026-07-11 / server lock）各自的用途与适用机器；
      写明 torch/botorch 栈不在 requirements.txt 的事实（HANDOFF §9e）
- [x] P0.3 raw_data 静默回退改响亮（`cdbe14e`，iter 3；pin 改放仓库根 data-repo.pin——data/ 整目录 gitignore 所致）：`df_surrogate/surrogate_v3.py:156` 的 `_log.info` 回退
      升级为 `_log.warning` + 显著横幅（找不到 Excel 校准源 = 数字口径变化，必须喊出来）；
      加数据仓钉扎记录 `data/raw_data/.data-repo-pin`（记 SJTU-TPMSHX-data 的 commit，HANDOFF §8）。
      验证：suite + golden 位同（行为只在缺数据场景变化）
- [x] P0.4 测试基建入库（`6521ba7`，iter 4；golden json 本体 → DECISIONS D1 待决）：`scripts/run_tests_server.ps1` 提交进仓库；给 `golden_3d.json` 建
      meta 侧车 `golden_3d.meta.json`（生成 commit / env 指纹 / 日期——HANDOFF §9 "零版本记录"）；
      golden json 本体是否入库 → DECISIONS-NEEDED 问 Alex
- [x] P0.5 文档纠偏（`059d306` + D1 执行 `c4cccb7`，iter 5）：`.claude/commands/check.md` 死路径 `D:\Postgraduate` → `E:\LWH`、
      补 server runner 指引；HANDOFF §9d 的 CI=true 精确门语义写进 `pytest.ini` 头注

## Phase 1 — 架构（Alex 指定的最高优先级）

- [x] P1.1 架构审计（iter 6：工具+文档，见 `docs/ARCHITECTURE-AUDIT-2026-07.md`）：实测 import 图
      （3 违规 + main↔ui 环）、双 evaluator 真相（2D/3D 各对自家管线，HANDOFF §2a/§3a 部分过时）、
      run_stack_3d 五缝、sys.path 5 模式约百处、可变态 a/b/c/d 分级（两个 W7b 同族潜伏隐患）。
      P1.3-P1.9 已按审计重写
- [x] P1.2 正确性架构债（iter 7 验证收案，无码可写）：HANDOFF §1 两缺陷**均已在上游修复**
      （max_outer_ltne 自 `8ea7ce5` 活、压力字面量 2026-07-11 改真实转发，_CSV_STATUS.md:315
      记载）且已被 `test_validate_pipeline_runner_wiring.py` 四断言锁死；本轮实跑 19 个
      锁定测试全绿（6.13s）作为证据。审计报告 §0/§6 勘误同步
- [ ] P1.3 评估器 envelope 权威统一 + post-solve 门（**A ✓ iter 8；B ✓ iter 9；
      C → BLOCKED on D3**——iter 10 发现 2D/3D 管线 G 口径不一致 + γ_df 标定纠缠
      （亏空 7.4%/19.3%），升级为标定级决策，见 DECISIONS D3 与 openspec D4 修正）：
      3D 评估器改 import `envelope.predict_outlet_p_sq`（弃 :224,230 手抄代数与本地 R_AIR）；
      两评估器补 post-solve `gate_solution`（失败→invalid/罚值的语义设计走 openspec）；
      补传 `rho_inlet_ref`（对齐 stages_2d:546,561）；评估器入口 reset 警告注册表
      （对齐 compute_pipeline:120-123）。"Pareto 选点须经 Pipeline 复核后引用数字"写入文档契约
- [x] P1.4 evaluator 契约测试（`6c727dc`，iter 11）：六条有意差异固化为机器断言 + D3 绊线；
      主规则"Pareto 须经 Pipeline 复核"入档；openspec D5 节（并入 evaluator-envelope-authority
      变更而非新开——同能力域，偏离原"openspec change"字面已记）
- [ ] P1.5 run_stack_3d 五缝拆分（审计 §3；**A ✓ iter 12、B ✓ `ddf9c64` iter 13**——
      **五缝全收官 iter 12-16（C ✓ `2549a79`）：_run_3d_stack 1955→156 行纯编排器**；
      余一个收尾切片：mega-tuple 数据类化 + 五函数文件级迁移（可选，见下）；
      每步 golden 位同 + 全套件；stages_3d 的 re-export 面 = raw-cfg 直调方的兼容层，必须保持；
      C 缝需显式耦合态对象保 nonlocal 语义。预计 3-5 轮
- [ ] P1.6 缓存与 env 卫生（审计 §5b/§5d）：`compute_geometry` 返回浅拷贝、`_phi_grid` 冻结
      writeable=False（两个 W7b 同族潜伏隐患，照 _FIELD_CACHE 标杆）；`TPMSHX_CHI_S` 改 per-call
      （import 冻结影响 K_ss）；`_LAPLACIAN_AMG_CACHE` 只读性查证 + reset 钩；各配 W7 风格测试。
      全程 golden 位同
- [ ] P1.7 死路径清理（审计 §4 注）：smooth_df.py AIR_XLSX_DEFAULT 显式守卫；
      runs/tools|diagnostics|cfd_asym 的 D:\ 与 C:\Users\ALEX 参数化（archive/ 只标注 frozen）。
      sys.path 引导**不零星清理**（回归面大收益负），等 P1.8 结构性根治
- [ ] P1.8 pyproject.toml 打包 + editable install + headless CLI entry points（审计 §4 根治：
      装包后分波删除 5 模式约百处引导；compute_pipeline 接缝正式化；requirements 三档收编）
- [ ] P1.9 分层违规裁决（审计 §1）：solvers→df_surrogate 倒置或正式背书、
      domain/validator→df_surrogate、run_controller→runs、main↔ui 环；
      收尾把 `audit_import_graph.py --fail-on-violations` 挂进 /check 或 CI

## Phase 2 — 代码质量

（本 Phase 起按 PROTOCOL §10 模型分层：机械项派 Sonnet 5/Opus 子代理执行 + Fable 5 复核提交；判断型 Fable 5 直做）

- [ ] P2.1 ruff format + lint 引入（配置从宽起步；机械 diff 独立 commit，绝不与语义改动混提交）
- [ ] P2.2 核心公共面类型注解（solvers/pipelines 对外 API）+ mypy 宽松档
- [ ] P2.3 死代码处置：`solvers/zone_config.py`、`ui/zone_table.py`（已标 DEPRECATED）、
      runs/archive/ 标注 frozen；删除类处置先过 DECISIONS-NEEDED
- [ ] P2.4 异常与日志策略统一（logutil 已有基础；清点裸 except / print / 静默 fallback——
      P0.3 的同族问题全库扫一遍）
- [ ] P2.5 GUI 巨物减脂：main.py 13-mixin、ui/mixins/run_controller.py 1213 行
      （GUI 无 golden 保护、依赖 ui 测试，小步慢走，放本 Phase 最后）

## Phase 3 — 性能（profile 先行，禁拍脑袋；benchmarks/profiling 有既有基建）

- [ ] P3.1 suite fast-tier：用 --durations 实测数据定义 duration-based 标记与
      `run_tests_fast.ps1`（**不碰 slow 标记语义**——它是 CI skip 清单不是时长普查，v1 教训在案）
- [ ] P3.2 大网格线程默认值：TPMSHX_NUM_THREADS 探测式建议（≤64 / 单 socket / 带宽瓶颈提示）+ 文档
- [ ] P3.3 BO core budget 工具化（TPMSHX_BO_CORE_BUDGET 既有机制的 ergonomics）

## Phase 4 — 文档与交付

- [ ] P4.1 atlas 漂移收编：DRIFT.md 累计条目写回受影响卷；PROJECT_MANUAL §6 对齐新结构
- [ ] P4.2 README / 手册数字口径复核（1.71/1.73 类问题的当前状态确认）
- [ ] P4.3 CI 增强评估：lint + fast-tier 上 GitHub Actions 的可行性（重测试仍本地）
- [ ] P4.4 HANDOFF-windows-server.md 刷新——已确认过时处：§1 整节（max_outer + 压力字面量，
      已修已锁，iter 7 证据）、§2a 预解 choke（aa3f477 已加 raise→罚值）、§3a 热重播种地板
      （aa3f477 已改严格 NaN）；其余节随 P1 推进逐条核实后改写

## 收尾（触发时机：Phase 4 完成，或 Alex 喊停）

- [ ] 合并前清单：upgrade/ 目录处置方案、与 master 的合并策略（预期 master 只会有 Alex 的
      小改动，rebase 优先）、给 Alex 的终审报告
