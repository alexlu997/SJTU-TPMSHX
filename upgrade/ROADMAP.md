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

## Phase 1 — 架构（Alex 指定的最高优先级）**主线完成 2026-07-20（iter 6-20）**
（**Phase 1 全清**（iter 49）：P1.8b 七轮收官——全库包名风格、135 引导块退役、垫片生灭闭环）

- [x] P1.1 架构审计（iter 6：工具+文档，见 `docs/ARCHITECTURE-AUDIT-2026-07.md`）：实测 import 图
      （3 违规 + main↔ui 环）、双 evaluator 真相（2D/3D 各对自家管线，HANDOFF §2a/§3a 部分过时）、
      run_stack_3d 五缝、sys.path 5 模式约百处、可变态 a/b/c/d 分级（两个 W7b 同族潜伏隐患）。
      P1.3-P1.9 已按审计重写
- [x] P1.2 正确性架构债（iter 7 验证收案，无码可写）：HANDOFF §1 两缺陷**均已在上游修复**
      （max_outer_ltne 自 `8ea7ce5` 活、压力字面量 2026-07-11 改真实转发，_CSV_STATUS.md:315
      记载）且已被 `test_validate_pipeline_runner_wiring.py` 四断言锁死；本轮实跑 19 个
      锁定测试全绿（6.13s）作为证据。审计报告 §0/§6 勘误同步
- [x] P1.3 评估器 envelope 权威统一 + post-solve 门（**关账 iter 42**——四子项全数有归属，
      末两项经 D2/D3 决策裁定，无剩余代码工作）：
      ① envelope 权威 import ✓ iter 8（`7cbeee1`，弃手抄代数与本地 R_AIR）；
      ② post-solve 门：3D ✓ iter 9，2D → **D2(c) 裁定刻意不加**（已知边界已文档化）；
      ③ `rho_inlet_ref`：2D ✓ iter 41（`20031ba`，D3(c)，冻结值位同），3D → **D3(c) 裁定
      刻意不动**（候选 A2 调查范围，绊线 4 断言守门）；
      ④ 警告注册表重置 ✓ iter 8（`7cbeee1`）——落在 qnehvi **战役级**（`_reset_warn_registries`，
      测试钉住粒度决策：500 评估战役内仍去重，镜像 ComputePipeline.run；原条目"评估器入口"
      字面被有意收窄，iter 42 核实 qnehvi 为评估器唯一批量调用方，一次性脚本属新进程无陈旧态）。
      "Pareto 选点须经 Pipeline 复核后引用数字"已入契约（P1.4）
- [x] P1.4 evaluator 契约测试（`6c727dc`，iter 11）：六条有意差异固化为机器断言 + D3 绊线；
      主规则"Pareto 须经 Pipeline 复核"入档；openspec D5 节（并入 evaluator-envelope-authority
      变更而非新开——同能力域，偏离原"openspec change"字面已记）
- [x] P1.5 run_stack_3d 五缝拆分（**关账 iter 42**——实质工作五缝全收官 iter 12-16
      （C ✓ `2549a79`）：_run_3d_stack 1955→156 行纯编排器，每步 golden 位同；
      两个收尾切片均有归属：mega-tuple 数据类化 ✓ P2.0（`d0238e6`），五函数文件级
      迁移已并入 P1.8b 波次（同属大搬迁，当时明记）。勾选框此前留空系账目滞后，
      本条无独立剩余工作量。stages_3d re-export 兼容层照旧必须保持）
- [x] P1.6 缓存与 env 卫生（`7d70227`，iter 17）：`compute_geometry` 返回浅拷贝、`_phi_grid` 冻结
      writeable=False（两个 W7b 同族潜伏隐患，照 _FIELD_CACHE 标杆）；`TPMSHX_CHI_S` 改 per-call
      （import 冻结影响 K_ss）；`_LAPLACIAN_AMG_CACHE` 只读性查证 + reset 钩；各配 W7 风格测试。
      全程 golden 位同
- [x] P1.7 死路径清理（`dd598d9`，iter 18）：smooth_df.py AIR_XLSX_DEFAULT 显式守卫；
      runs/tools|diagnostics|cfd_asym 的 D:\ 与 C:\Users\ALEX 参数化（archive/ 只标注 frozen）。
      sys.path 引导**不零星清理**（回归面大收益负），等 P1.8 结构性根治
- [x] P1.8 打包地基（`827bee9`，iter 19）：pyproject + tpmshx-run CLI + controllers 惰性导出
      （接缝零 Qt 实证；工作 venv 未动）
- [x] P1.8b 导入风格迁移波次（**iter 43-49 七轮收官**：W0 垫片→W1 tests 141→W2 validation+df 31→W3 runs+ui 32→F1 库内 78→F2 撤垫片 28→F3 P1.5 尾巴；openspec 已归档；
      `p18b-import-style-migration` 三件套为波次台账）：
      **W0 ✓ iter 43**——身份垫片（新建 `sjtu_tpmshx/__init__.py`：自举 + 前插
      meta-path finder，双风格同对象；exec_module 恢复规范 __spec__ 防 reload 降级）
      + 身份测试 7 断言 + venv editable（--no-deps，pip check 净）+ pyproject 注记改写。
      垫片使后续迁移**顺序无关**（设计 D1）。
      余波：W1 tests 73 文件 → W2 validation+df_surrogate 24 → W3 runs+ui 36
      （§10 委托候选）→ W_final 库内 165 模块改写+撤垫片+P1.5 尾巴并入。
      每波门：全套+golden 位同+身份测试+tpmshx-run 冒烟+波内 sys.path 零残留
- [x] P1.9 分层违规裁决（`c43c7db`，iter 20）：两修（polygon_calc 迁 ui、_version 叶子）
      两裁（SANCTIONED 清单内置理由）；test_import_layering 常驻套件 + /check §2b；
      VIOLATIONS = 0

## Phase 2 — 代码质量

（本 Phase 起按 PROTOCOL §10 模型分层：机械项派 Sonnet 5/Opus 子代理执行 + Fable 5 复核提交；判断型 Fable 5 直做）

- [x] P2.0 数据类化（`d0238e6`，iter 21——**§10 委托首战成功**：Sonnet 执行/Fable 复核签发）；
      文件级迁移（五阶段函数 → run_stack_3d_stages.py）并入 P1.8b 波次一起做（同属大搬迁）
- [x] P2.1 ruff lint 引入（`121413d` 机械波 + `6e65487` 语义波，iter 22）：F+E9 清零、
      三真雷（QInputDialog/coord_inspector/_直跑块）、门面豁免两教训、lint 门常驻
- [x] P2.1b F841 清偿（`581e790`，iter 23）：52+5 级联逐案（净 −46 行死代码），全量执法开启
- [x] P2.1c ruff format 评估（iter 25，纯评估轮）：**裁决 = 不做全库 format**。
      实测四条硬证据：①359/370 文件、−20.5k/+38.9k 行（87k 行包 ~45% 搅动，blame/考古链毁）；
      ②atlas 2355 处 file:line 引用（376 文件）全面腐蚀；③wiring 测试 23 处 quoted marker 中
      ≥3 处引号敏感断言直接断（调参变体 quote=single+line-length=200 仍 360 文件重排，救不回）；
      ④merge-to-master diff 被排版噪声淹没，破坏"每个 diff 可审"承诺。
      **未来若做的三前置**：atlas 引用改锚点式或同波重基线；wiring marker 全改 AST/标识符级；
      在 master 合并后作为独立 format-only 提交 + .git-blame-ignore-revs 登记。现行策略照旧：
      F+E9 管真错误，排版跟随周边风格（CLAUDE.md 约定）。
- [x] P2.2 mypy 宽松档核心面门（`464076d`，iter 24）：七文件圈（envelope/compute_pipeline/
      domain 配置结果/configs/_version/cli）清零 + test_type_gate 常驻；扩圈 = 加清单同 commit 清零
- [x] P2.3 死代码处置（iter 26，盘点轮）：**零处置需要，未立 D 条目**。
      zone_config 104 引用/17 文件、zone_table 87 引用/8 文件——"DEPRECATED"仅指优化器路径，
      UI Define-zones 标签页全活，头注已准确；runs/archive README 的 frozen+死路径声明
      P1.7 已备。全库孤儿模块扫描（165 个库模块）：3 个嫌疑全为相对导入误报
      （_kernels_ltne_3d ← ltne_energy_3d:322、builders_sidebar/skeleton ← builders_canvas），
      **0 真孤儿**；13 个未被导入者均为 V&V/构建入口脚本（正常）。细粒度死代码由
      ruff F 门持续执法。未来孤儿检查应挂 audit_import_graph（真图，正确处理相对导入），
      不用正则探针。
- [x] P2.4 异常与日志策略（iter 27，盘点轮）：**已在政策内，零代码批次**。
      全库 0 裸 except；核心三目录（solvers/pipelines/controllers）28 处 except Exception
      逐处分类全为存证故意（warmup 尽力 ×3、能力探测、**2026-07-03 已有 except-audit**
      的放响 fallback ×6、线程错误捕获重抛、回调护栏 ×5、traceback 打响 ×3）；
      库内 144 处 print 实测 0 处在活求解路径（95 处 __main__ 区 + 其余在
      _self_test()/main()/demo 函数——分类探针的"活路径"桶系统性高估，逐函数复核归零）。
      **ui 的 273 处 except Exception 移交 P2.5 章程**（GUI 防御捕获政策随减脂轮就地处理）。
- [x] P2.5 GUI 巨物减脂（iter 28 测绘 + iter 29 单刀完成）：**mixin 架构本身判定健康**——
      AST 交叉引用矩阵显示耦合低（多数 mixin 依赖 0–3 个同伴；zone_panel/io_actions 零 fan-in
      枢纽仅 shortcuts/session_presets/main），13-mixin 分层不动。真靶标唯 run_controller
      1215 行，四责任区：启动/预检 ~315、orch 信号处理 ~305（_on_orch_finished 独占 188 行）、
      结果呈现 ~370（write_result 122 行）、计算 UI 状态 ~250。保护面：3 个直击测试
      （finalize_3d_result_sync / orch_finished_3d_state / run_controller_preflight）+ 17 Qt 测试。
  - [x] P2.5a 切结果呈现区（`86b12e4`，iter 29）：五方法逐字节（AST 比对 HEAD 位同）→
        RunResultsMixin 328 行，run_controller 1215→912，MRO 插位 + 冒烟全解析；
        套件 1258+10 绿、golden 位同、直击三测试绿——**单刀即收**，Phase 2 完
  - [x] ui 273 处 except Exception 政策（P2.4 移交）：**存量不动**（Qt 防御捕获合法，273 站
        改写的 churn 风险 >> 收益）；新代码要求 logutil 记录。政策即此行，不另立扫改波次。

## Phase 3 — 性能（profile 先行，禁拍脑袋；benchmarks/profiling 有既有基建）

- [x] P3.1 suite fast-tier（`53431bb`，iter 30）：census 265 测点定阈 30s——21 测试
      （1.7%）承载 89% 计算量；manifest+conftest 动态 heavy 标（零测试文件改动）+
      run_tests_fast.ps1 实测 **56s vs 全量 19min（20×）**；slow 语义未碰；
      红线三处写死：快档绿 ≠ 过门
- [x] P3.2 大网格线程建议（`547b7d0`，iter 31）：recommend_solver_threads +
      并行分派点一次性 advisory（三静默分支；**池零自动改动**——prange 归约序无门保护，
      设计约束写死）；测试 +3；logutil tpmshx. 前缀教训入档
- [x] P3.3 BO 核预算工具化（`e233460`，iter 32）：_resolve_core_budget 钳制 [1,cpu]+
      来源标签+启动 INFO（多臂可审计）；超机预算钳制（堵超订残留口）；env 索引补录；
      测试 +7——**Phase 3 完**

## Phase 4 — 文档与交付

- [x] P4.1 atlas 漂移收编 **✓ 收案 iter 36**（iter 33 盘点：**DRIFT.md 从未存在**——前提
      修正为"分支漂移直接写回卷 + 各卷收编节"；三域三轮共收编 10 卷 + PROJECT_MANUAL §6
      增量索引 + README 滚动状态；未收编 7 卷经盘点无分支级失准，HANDOFF 单列 P4.4）：
  - [x] P4.1a 基建域（`433eb2b`，iter 34）：tests/repo-infra 两卷失准就地改正
        （151→162 文件、marker+heavy、conftest 三副作用、-n auto→双跑脚本、threads 路径
        笔误、pyproject 断言过时）+ 文末收编节；README 滚动状态注记；修正标 ⟨07-20 更新⟩
  - [x] P4.1b 架构域（`0fad954`，iter 35）：四卷收编——pipelines（重组映射表+⚠旧行号
        声明）/ controllers（PEP 562+cli 消费方）/ core-domain（evaluators 639 行新结构+
        D3 绊线）/ optimization（P3.3 预算段重写+BLAS 时序缺陷"仍未修"注记留 Phase 5）
  - [x] P4.1c 外围域（`006e99f`，iter 36）：ui-core（14 mixin/912+328 行/write_result 迁址）/
        runs（polygon_calc "唯一 UI import 例外"条目消除、tools 5→8）/ solvers-2d
        （threads 102 行+P3.2 机制）/ solvers-closures（chi_s "导入时读取一次"过时断言改正+
        geometry 缓存拷贝语义收编节）/ PROJECT_MANUAL §6 节首增量索引（含 cli.py 撞名辨析）
      （HANDOFF 卷单列 P4.4 不并入；各轮 docs-only 门）
- [x] P4.2 README/手册数字口径复核（`978c066`，iter 37）：**数字零漂移**——全部 headline
      （1.73/≈10/≈3/4.88/2.12/8.62/2.49/p_obs≥2.07）与 BASELINE 实测一致；修正的是
      平台行（+Server 2022）与测试命令区（服务器双跑脚本+56s 快档入 README/手册）
- [x] P4.3 CI 增强（`f6b6a5a`，iter 38）：**评估变抓虫**——lint/type 门测试无 skip 守卫，
      现行 CI 未装 ruff/mypy，合并后必红；install 补装即修且 CI 从此真执法三静态门；
      "not heavy" 剔 21 重测试（CI=smoke/静态层定位，物理回归归本地全量门）；
      选择表达式本地验证 1223/59 反选；只入库不推送
- [x] P4.4 HANDOFF 刷新（`312ac37`，iter 39）：体例裁决 = **原文证据链零改写**，文首挂
      16 行状态总更新表（§1/§2/§3/§8a/§9a/§9b/§10 已解或过时；§5/§6 部分解；§4/§7 仍开放）
      + 三节行内戳；AGENTS.md 尾巴收案（基点树即不存在）——**Phase 4 完**

## Phase 5 候选池（未章程化——收尾时 Alex 挑选，Alex 2026-07-20 批准立项）

候选≠承诺：不计入完成度，挑中者才展开成正式条目。三池按性质分：

- [ ] 候选 A · D3 后果链（研究/标定级，**等 D3 拍板解锁**）：
      A1 = (c) 2D 评估器 ρ_ref 对齐自家管线 + frozen 两元组重基准（~7% 级，1–2 轮，循环可执行）；
      A2 = (a) G 口径全线统一调查——3D 求解器 rho_inlet_ref 旋钮、golden_3d 重基准、
      γ_df 重锚评估、Shanghai 3D 重验证（台账级，先立证伪方案条目，跨多轮多决策点）
- [ ] 候选 B · 物理/闭合研究支援（**循环转"备证据+排队拍板"模式**，节奏由 Alex 定）：
      B1 = sCO2 实验 γ 锚定（等实验数据落地，ledger SCO2-CFD 重启触发）；
      B2 = D2 落地（若拍板 a/b）；B3 = 台账想法池按需支援
- [ ] 候选 C · 性能纵深（profile 先行，接 P3 浅层三件）：
      C1 = 全管线 profile 战役（3D 热点图、numba kernel 审计、内存带宽——纯测量零数值风险，2–3 轮）；
      C2 = 依 C1 证据的优化波次（可能触发 golden 重基准，每波过 §5）；
      C3 = 大网格并行策略实测（线程 sweep + 默认值证据化）
- [ ] 候选 D · D-F 系数获取方法（Alex 2026-07-20 提出；**2026-07-22 立项对话拍板边界，
      全串行批到位**）：CFD 拟合 (K, cF) 光滑基 + 试件实验标定 γ；**上海 16 例退出标定、
      转纯盲考卷**（现行 L7=534.8 上海标定点退役 ⇒ 头条重新定义为盲预测精度、预期变大）；
      UQ 是交付物；sCO2 并入排后。**硬约束不变**：①换默认前过 Shanghai 3D 门（现在是盲测
      语义）；②DF 已含 SLM 粗糙度，绝不双计乘子；③台账先查后回写；④C8 翻转 = D-3 交付物
      （D5 岔路 (a)，打靶 ON 成为新验证口径的一部分）。关键决策点（换默认、γ_f 锚选侧、
      golden air-B 换点）停下问 Alex：
  - [x] D-0 溯源审计（`0dd90af`，iter 79）：col47 提取式钉到 file:line ——
        **闭式反演不穿求解器**（surrogate_v3.py:244-249）、**水平口径入锚**
        （:246 出口恒钉 1 atm，入锚 dP/P_atm 最大 0.815 => 承重）；试件台账是
        **唯一一张两类缺陷都为零**的表；**实质发现 = alpha（边界效应系数）主导
        gamma_spec 的几何形状**（D 占 t 斜率 73%，G 的 t 平坦是 alpha 相消出来的、
        L6 走向因 alpha 变号）=> 水平无害但**形状有害**，§12.2 的 shape-contrast
        带不覆盖 alpha 的出处风险 => **DECISIONS D12**。审计 §15。
        （534.8 出身已由 iter 77 的 §14 答完；余下三小项无独立结论价值，
        随各轮已就地消化）
  （**2026-07-22 Alex 二次拍板：sCO2 先行**——CFD 数据最厚 + subst.v2 修正关联式现成
  （γ_f(Re)=Γ₀·Re^Δ，实验/CFD 同形幂律相除，仅窗内、cold 侧禁外推）；方法论在 sCO2
  打样后平移水/空气。四护栏：修正只落 cF 提取步（γ_f×D-F 非 D-F 形，K 守水锚）；
  Δ 作 UQ 变体（自由 vs 0）；hot/cold 量化后再裁；Diamond 承重 G 侧标注混杂。
  方法卫生：D-7-6/G-7-6 既是标定源不再当盲考，sCO2 域内只做 LOO/holdout+反向检验，
  真盲考在水/空气阶段）
  - [x] D-1sc sCO2 考卷基建（`0ba9bcd`，iter 60）：LOO/holdout 纪律 + 窗内守卫 +
        窗内守卫（实验 Re 窗外拒绝外推）+ 现行光滑基跑分基准；主检出侧 v2-v5/subst
        系列脚本差异收编（worktree 分叉后 compare_exp_vs_cfd.py 已更新）
  - [ ] D-2sc sCO2 γ_f 修正试点（1-2 轮）：hot/cold/合并三变体 × Δ{自由,0} →
        修正 cF 面 + 贝叶斯后验 + Δp 预测带 → **选侧证据包交 Alex 裁**；
        γ_Nu(Re) 修正入产线评估顺带；G 侧 CFD 基线外推混杂标注在案
  - [ ] D-2a cF 光滑基升级（水/空气，1-2 轮）：CF-REFIT 收尾——原始水 CFD 两段法
        提 cF（K 已做），log-TPS 面，与 SmoothDF 基同考卷对比
  - [ ] D-2b γ 重锚（水/空气）：纯试件锚（无上海点），Gyroid L 方向照
        Diamond 模式重建；新口径（打靶 ON）下重跑考卷；γ 后验 + Δp 带（UQ）；
        顺带检验 sCO2 试点的"γ 几何无关"假设（空气 γ(L,t) 面 vs 7/0.6 单点）
    - [x] D-2b-1 γ_specimen 候选面（`6e64e87`，iter 69；R3 `d7d9a1d` 重跑）
    - [x] D-2b-2 γ_HX 气侧（`68b45fa`，iter 70；R3 `d7d9a1d` 重裁决）
    - [x] D-2b-3 γ_HX 水侧 + 气/水跨流体对照（`7ea25ec`，iter 74）：水 D 2.44 /
          G 2.18 vs 气 D 1.08 / G 1.23；**G/D 序反号** ⇒ γ_HX 不是纯拓扑常数；
          水/气 ×2 的首要嫌疑 = 水侧 A_flow 口径 → **DECISIONS D8 待数据方**
    - [x] D-2b-4 双层合成面 + UQ 带**气侧腿**（`3981f0f`，iter 75）：
          γ_total = γ_spec(L,t)×γ_HX；UQ 改为"HX 钉水平 + γ_spec 只提供形状"
          （两层强反相关，独立相乘会重复计入）；LOO 裁决 per_topo 双赢
          （medAPE 3.5% vs pooled 5.9%，带宽 1.22 vs 1.49）。顺带查出气侧
          亦有仪表地板案 + D 表重复行（与水表同址），修后中位不动、σln
          塌缩 4-6×。**水侧腿仍 BLOCKED on D8**
    - [ ] D-2b-4w 双层合成面**水侧腿** —— BLOCKED on D8（水侧 A_flow 口径）
    - [x] D-2b-5a 三流体 cF 反演对照（`983822a`，iter 76）：剥掉闭合层直接从
          原始测量反演 cF —— air 430/401、water 1340/829、sCO2 1522/1512（1/m）。
          **sCO2/气 ×3.5/×3.8 且 A 不变**（同 A_flow，cF ∝ A² 精确约掉）⇒
          D8 那类面积解释对本腿不适用；Re 外推/光滑基不匹配/K 选择亦排除。
          气侧反演复现 §12 双层面（吻合 1-3%）。⇒ **DECISIONS D9**
    - [ ] D-2b-5b γ_f 并入双层合成面 —— **BLOCKED on D9**（跨流体统一 γ 面
          在 D9 答复前搁置：强行合成 = 把系统偏差固化成物理）
    - [x] D-2b-5c sCO2 f 侧重提 + γ_f 重冻（`16a10ef`，iter 78，**§5 重基准**）：
          预制表重建至 07-23 修正导出（几何 D 15→20 / G 12→17，例数 7000→9799，
          B 中位 −10.6%）；base-swap 绊线按设计炸响，γ_f 四常数重导（非放宽容差）。
          **dexp 降幅与 pooled m 降幅精确抵消 ⇒ 生产消费的乘积全窗变化 ≤0.02%**；
          真变化在其它几何（光滑基 −8…−13%，= 新 CFD 的信息）。
          **(7,0.6) 从域外外推变插值节点**。全 V&V 绿、空气/水认证面零影响。
          ⇒ DECISIONS D11 [已重基准-待复核]；台账 SCO2-F-REFIT-0725
  - [x] D-2c 上海 16 例真盲考（`4adaddc`，iter 77）：双层合成面（零上海输入）
        盲预测上海 16 —— **16/16 全例偏低、偏置 −24.7%、RMSRE 25.3%**，Q 不动
        （2.10% vs 2.11%，纯阻力）。裁决 **(ii) 成立**，且钉到具体原因：考卷
        （20260401）与 γ_HX 锚（20260407 **调换进出口**）是**同一台样机同一组
        工况**，实测 Δp 比中位 **1.274** —— 与盲考因子 1.328、iter 73 残差
        ×1.296 三数同源 ⇒ **γ_HX 依赖流向**，两个锚各自都对。⇒ **DECISIONS D10**
  - [ ] D-2c' 方法对比矩阵（现行 γ 面 vs refit 基 vs 物理化 Ergun 族 vs 贝叶斯
        标定，同考卷打分 + 外推稳健性）—— 盲考基建已就位（shanghai_blind_exam.py
        的 backend 注册法可复用），但**打分口径须先由 D10 定方向**
  - [ ] D-3 换默认提案（1 轮 + Alex 拍板）：证据表 → §5 `!` 重基准（含打靶默认翻转、
        golden air-B 工况点处置 D5(c)、README headline 重述为盲验证口径）
- [x] C8 打靶循环（台账 C8 遗留，Alex 2026-07-22 点名；iter 57，`0519587` 特性 +
      归档定价）：两维实测阻力 P² 重种子实装（opt-in，OFF 位同，测试 8 条，
      真 choke 检测新能力锁定）；**默认翻转被定价否决**——γ_df 锚点吸收了旧口径
      压力水平偏置（3D case12 起 in-model choke、2D RMSRE 8.62→10.73），
      翻转前置 = 候选 D γ 重锚（DECISIONS D5 记岔路；A2 同构耦合律第二例）
- [ ] 都不挑 → 循环转按需模式：拆定时器，Alex 手动触发，PROTOCOL/状态文件原地保留可随时复活

## 收尾（触发时机：Phase 4 完成，或 Alex 喊停）

- [x] 合并前清单 + 终审报告（iter 40）：`upgrade/FINAL-REPORT.md`——认证门 1268+10 绿/
      golden 位同、82 提交可快进合并指南、upgrade/ 目录三选一处置（建议原样合入）、
      开放项清单；合并不被 D2/D3 阻塞
- [x] Phase 5 候选池评审选单（同报告内）：A/B/C/D 四池附规模与风险注记，连同 D2/D3
      一并交 Alex；循环转待命模式（tick 只查新 `已决`）
