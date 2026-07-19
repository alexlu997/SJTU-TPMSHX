# 升级路线图（ROADMAP）

排序即优先级，从上往下做。勾选 = 完成（附 commit 短哈希）。BLOCKED 条目跳过并在 DECISIONS-NEEDED.md 说明。
一条 ≈ 一轮的量；太大的先拆再做。P1.1 审计完成后**回填细化**后续条目是预期行为。

## Phase 0 — 安全网（架构手术前的地基）

- [ ] P0.1 基线快照：写 `upgrade/BASELINE.md`——suite 精确计数、`--durations` 前 15、
      golden_3d --check 结果、`validate_shanghai_3d_real.py` 与 `validate_shanghai_lumped_dual_nu.py`
      的 headline 数字（Δp / Q / RMSRE）、`pip freeze` 指纹。此后所有"数字没变"的断言都对照它。
      ⚠ 长命令输出必须 `| Tee-Object 日志文件` 落盘后读文件——PowerShell 后台任务捕获会丢
      pytest 进度流的尾巴（2026-07-19 两次实测，靠 exit code 才判的绿）
- [ ] P0.2 依赖锁定：`requirements-lock-server.txt`（本机验证过的 80 包冻结，torch==2.11.0+cpu
      需注明 pytorch cpu 索引）入库；`requirements.txt` 头注说明三档清单
      （裸 requirements / constraints-devbox-2026-07-11 / server lock）各自的用途与适用机器；
      写明 torch/botorch 栈不在 requirements.txt 的事实（HANDOFF §9e）
- [ ] P0.3 raw_data 静默回退改响亮：`df_surrogate/surrogate_v3.py:156` 的 `_log.info` 回退
      升级为 `_log.warning` + 显著横幅（找不到 Excel 校准源 = 数字口径变化，必须喊出来）；
      加数据仓钉扎记录 `data/raw_data/.data-repo-pin`（记 SJTU-TPMSHX-data 的 commit，HANDOFF §8）。
      验证：suite + golden 位同（行为只在缺数据场景变化）
- [ ] P0.4 测试基建入库：`scripts/run_tests_server.ps1` 提交进仓库；给 `golden_3d.json` 建
      meta 侧车 `golden_3d.meta.json`（生成 commit / env 指纹 / 日期——HANDOFF §9 "零版本记录"）；
      golden json 本体是否入库 → DECISIONS-NEEDED 问 Alex
- [ ] P0.5 文档纠偏：`.claude/commands/check.md` 死路径 `D:\Postgraduate` → `E:\LWH`、
      补 server runner 指引；HANDOFF §9d 的 CI=true 精确门语义写进 `pytest.ini` 头注

## Phase 1 — 架构（Alex 指定的最高优先级）

- [ ] P1.1 架构审计：产出 `docs/ARCHITECTURE-AUDIT-2026-07.md`——
      实测 import 依赖图（写脚本生成，别靠目测）；分层现状（数值核心已 Qt-free 是重要资产，写清楚
      controllers/compute_pipeline.py 这个接缝）；**双 evaluator 分歧清单**（core/evaluators.py 578 行
      vs optimization/evaluator.py 799 行，逐能力 diff）；run_stack_3d.py 2380 行职责分解图；
      sys.path munging 清单（main.py:9-14、df_surrogate/load_sco2_cfd.py 等）；模块级可变全局态清单
      （_geom 缓存 bug 的同族隐患）。**产出 P1 子项细化，回填本路线图**
- [ ] P1.2 正确性架构债（HANDOFF §1）：`validate_shanghai_3d_real.py` `--runner pipeline` 丢
      `max_outer`（:461-531，SolverConfig 缺 max_outer_ltne 字段）；`pressure_clip_hits` /
      `pressure_state_valid` 是硬编码字面量（:529-530）→ 压力有效性过滤静默 no-op。
      修透传链 `stages_3d._finalize_3d_cfg` → ComputeResult。
      ⚠ 可能改 validate 脚本输出口径 → 按 PROTOCOL §5 走
- [ ] P1.3 优化器 envelope 门（HANDOFF §2）：`optimization/evaluator.py` 接入
      `envelope.check_compressible_envelope` / `gate_solution`；choked 点的处理策略
      （罚值 vs 排除 vs 约束）是行为设计 → 走 openspec change
- [ ] P1.4 evaluator 契约统一（HANDOFF §3）：第一步加**契约测试**把 core/evaluators.py 与
      optimization/evaluator.py 的现有分歧显式锁定（暴露差异而非掩盖）；第二步收敛单一权威 + 薄适配。
      大项（预计 2-3 轮），openspec change
- [ ] P1.5 run_stack_3d.py（2380 行）分解：按既有 stages_3d 边界拆阶段模块，行为位同；
      每拆一块过一次全门禁再拆下一块
- [ ] P1.6 路径与引导统一：`df_surrogate/smooth_df.py:56` AIR_XLSX_DEFAULT（D:\ 死路径，
      rebuild-only 资产未迁移）加显式守卫与说明；runs/tools|diagnostics|cfd_asym 里的
      `D:\` 与 `C:\Users\ALEX` 死路径参数化（runs/archive/ 只标注 frozen 不改）；
      sys.path munging 收敛
- [ ] P1.7 pyproject.toml 打包 + headless CLI entry points（把 compute_pipeline 接缝正式化为
      对外入口；requirements 三档随之收编）
- [ ] （P1.1 审计后回填）

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
- [ ] P4.4 HANDOFF-windows-server.md 刷新（§1-3 修复后如实改写）

## 收尾（触发时机：Phase 4 完成，或 Alex 喊停）

- [ ] 合并前清单：upgrade/ 目录处置方案、与 master 的合并策略（预期 master 只会有 Alex 的
      小改动，rebase 优先）、给 Alex 的终审报告
