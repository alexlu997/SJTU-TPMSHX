# 升级循环终审报告（upgrade/loop → master）

写给 Alex · 2026-07-20 · 循环 iter 1–40（2026-07-19 播种，两日完成主线）
可视化版：浏览器打开 `upgrade/progress.html`（含逐轮时间线与路线图明细）

## 一页摘要

自迭代循环在 **40 轮内完成 P0–P4 五阶段主线全部 29 个正式条目**（另含进度页、候选池
两次插单），全程零红灯提交、golden 3D 始终位同、无一次重基准。测试套件 1245 → **1268**
（+23，全部是新守卫/契约/机制测试），并新增 lint / type / import-layering / fast-tier
四道常驻质量门。数值口径零漂移（headline 1.73% / 4.88% / 2.12% 复核一致）。

**终审认证门（本轮实测，2026-07-20，HEAD 含全部 82 提交）**：套件双 pass
**1268 passed + 4 skipped / 10 passed**（10:40），`golden_3d --check` **PASS (bit-identical)**
——日志 `upgrade/logs/final-suite.log` / `final-golden3d.log`。分支处于可合并状态。

主要交付（按价值排序，不按时序）：

| 交付 | 内容 | 关键提交 |
|---|---|---|
| 架构手术 | run_stack_3d 1955 行单体 → 156 行编排器 + 五阶段函数 + 四数据类（逐字节搬移，golden 位同护航） | `ddf9c64`…`d0238e6` |
| 评估器可信化 | envelope 权威统一 + 3D 解后 Mach/正压门 + 评估器↔管线六断言契约（D3 绊线） | `6c727dc` 等 |
| 质量门四件套 | ruff（F+E9 全量）/ mypy（核心七文件）/ import 分层审计（SANCTIONED 制）/ fast-tier census | `121413d` `464076d` `c43c7db` `53431bb` |
| 开发体验 | **56 s 快档**（20×）、大网格线程建议、BO 预算可审计、tpmshx-run CLI | `53431bb` `547b7d0` `e233460` `827bee9` |
| 可复现性 | 锁 83 包 + golden json/meta 入库（D1）+ data-repo.pin + 版本单源 | `abaa348` `c4cccb7` 等 |
| 文档对账 | atlas 10 卷收编 + HANDOFF 16 行状态表 + README/手册数字复核 + CI 修复 | `433eb2b` `0fad954` `006e99f` `312ac37` `978c066` `f6b6a5a` |
| 真雷修复 | 3 处 F821 崩溃（Save Preset 即崩等）、W7b 缓存危害、CHI_S reload、CI 合并后必红 | `6e65487` `7d70227` `f6b6a5a` |

## 分支状态与合并指南

- 分支 `upgrade/loop` @ 本地，领先基点 `4b32da4`（= 本地 master）**82 提交**，未推送。
- **本地 master 自播种起未动 → 可快进合并**。建议流程：
  1. 远端核对：`git fetch origin && git log origin/master -1`——若远端 master 仍是
     `4b32da4`，直接 `git checkout master && git merge --ff-only upgrade/loop`；
     若远端有新提交，先 `git rebase origin/master upgrade/loop` 再走全门后合并。
  2. 合并前最后跑一遍 `scripts/run_tests_server.ps1` + golden --check（本报告的认证门
     即此流程，若你在合并当日执行可直接沿用本轮日志）。
  3. push 后 **CI 会按新 ci.yml 跑**（装 ruff/mypy + not-heavy 选择）——这是分支修过的
     "合并后必红"缺陷（iter 38），预期首跑绿；若红优先怀疑 ubuntu 依赖解析差异。
- **upgrade/ 目录处置**（三选一，建议 a）：
  - (a) **原样合入**（建议）：PROTOCOL/ROADMAP/PROGRESS/DECISIONS/BASELINE/FINAL-REPORT
    加 logs/ 与 progress.html 全套是这次升级的完整审计记录，~小几百 KB 文本；
    tools/render_progress.py 继续可用。
  - (b) 精简合入：只留 FINAL-REPORT.md + PROGRESS.md + DECISIONS-NEEDED.md，logs/ 删除。
  - (c) 不合入：squash 到一个 docs commit，upgrade/ 移出仓库另存。
- 合并**不被 D2/D3 阻塞**：两者是政策决策，现行为已被契约测试如实钉定；拍板后按
  DECISIONS-NEEDED 各选项执行即可（选项工作量见该文件）。

## 待你拍板的事项

**D2 · 2D post-solve 门**（`upgrade/DECISIONS-NEEDED.md`）——循环建议 (c) 维持现状+文档化。

**D3 · G 口径不一致**（重要，标定级）——2D 管线物理 G vs 3D 首解捕获 G，实测吞吐亏
7.38% / 19.30%，已被 γ_df 部分吸收。循环建议 **(c) 分维一致先行 + (a) 全线统一立项调查**。
P1.3-C 与 Phase 5 候选 A 都在等它。

**Phase 5 候选池**（挑 0–N 项；都不挑 → 循环转按需模式）：

| 池 | 内容 | 规模估计 | 风险/依赖 |
|---|---|---|---|
| A · D3 后果链 | A1 = 2D 评估器对齐+冻结点重基准；A2 = G 口径全线统一调查（γ 重锚评估+Shanghai 重验证） | A1: 1–2 轮；A2: 台账级战役（≥10 轮+多决策点） | **等 D3 拍板**；A2 触发 golden/headline 重基准 |
| B · 研究支援 | sCO2 实验 γ 锚定（等数据）、D2 落地、台账想法池 | 按件计，多为 2–5 轮/件 | 循环转"备证据+排队拍板"模式，节奏归你 |
| C · 性能纵深 | C1 profile 战役（纯测量）→ C2 优化波次 → C3 并行策略实测；含 parallel_runner BLAS 时序缺陷修复 | C1: 2–3 轮；C2: 视热点，每波全门 | C2 可能触发 golden 重基准（§5 流程） |
| D · D-F 系数方法调查（你 07-20 提出） | 训练点扩充/物理化模型/贝叶斯标定/多保真融合对比 | 调查 3–6 轮出对比证据；换默认另计 | Shanghai 基线复现门；与 A2 的 γ 锚点耦合，若选 A2 建议排序或合并 |

## 开放项（不阻塞合并，已记档）

- P1.8b 导入风格迁移波次（`sjtu_tpmshx.*` 全库迁移）——已立项未做，规模大，可作 Phase 5 追加候选。
- P1.3-C（评估器 G 对齐）BLOCKED on D3。
- parallel_runner BLAS 钳制时序缺陷（07-12 审计发现，候选 C 内）。
- HANDOFF §4（运行目标）/§7（中断处理）仍开放；port_retest_server.ps1 四臂脚本未整跑。
- 2D golden 无入库基线（仍本地捕获流程；3D 已入库）。
- suite 里 4 个 skip 为数据/环境守卫（raw_data 相关），语义正常。

## 循环待命模式（本轮起）

定时器保留（c87569d6，每 15 分钟）。此后每 tick 只做：读 DECISIONS-NEEDED——出现新
`已决` 即执行对应项并回归正常轮次；无新决策则静默吸收（不产生提交）。你可随时：
拍板 D2/D3、挑 Phase 5 候选（回复"启动候选 X"即可）、或"暂停 loop"拆定时器。
