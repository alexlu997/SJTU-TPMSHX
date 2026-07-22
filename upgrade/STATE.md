# 循环状态（STATE）

- iteration: 67 ——**D-2a-2 候选面 LOO 考卷收案（`12cee5c`）：dev 基 G 侧
  cF 1.5%/K 2.5%（比 core 再砍半），D 侧面本征粗糙（12.5% med，尾部优于
  core）；γ 修正结构性不进 CFD 对比（Alex 确认点已答）——D-2a 全收案**
- next: D-2b 前置复核——col47 试件锚 L4/L6 异常（06-30 发现：L4 t 趋势
  反转、L6 3-4× 尖峰，L6 是现行可信层！）：用试验记录表原始 col43/47 +
  闭式反演逐试件复核，裁定可信层重划（L6/L8 还是仅 L8 还是别的），
  这决定 D-2b 纯试件重锚的锚点集设计。产出 = 复核证据 + 锚层裁定提案
  （若推翻 L6 需 Alex 知会——γ 面重建的地基）
- next: D-2a-2 cF/K 候选面（dev 表 → log-TPS，LOO 考卷 vs SmoothDF 基 vs
  core 基；复用 06-30 的 LOO 门槛设计——"cF LOO ≪ gamma_df 面 87/122%"）。
  注意池：col47 锚 L4/L6 异常（06-30 发现）直接冲击 D-2b 可信层设计，
  D-2b 开工前须复核该发现（试验记录表 col43/47 原始数据 vs 2-stage 面）
- next: 水/空气阶段开工——D-2a CF-REFIT 收尾（原始水 CFD 两段法提 cF
  〔K 已做〕，log-TPS 面，与 SmoothDF 基同考卷对比）。剩余尾账不阻塞：
  projects/703 其余 9 脚本死导入（静默债）、G_7_6/D_7_6 CFD 补算触发器、
  L4/L5 粗糙壁仲裁触发器
- in_progress: 无（iter 64 已收）
- 候选 D 边界（Alex 2026-07-22 四点拍板，原文见 PROGRESS iter58 段）：
  ①全串行 a→b 一次批到位；②CFD 拟合 (K,cF)、试件实验标定 γ，**上海 16 例退出
  标定转纯盲考卷**；③sCO2 γ 并入但排空气侧重锚之后；④UQ 要（γ 后验 + Δp 预测带）
- armed_at: 2026-07-22（job 8f180729——iter 64 收轮时重建，旧 c87569d6 已删；
  >5 天须按 §8 重建 → 下个窗口 2026-07-27 前）
- cron_spec: `7,22,37,52 * * * *`
- 基点：master `4b32da4`（含 sCO2 光滑壁闭合提交）；分支 `upgrade/loop`

## cron 提示词（重建定时器时逐字使用）

```
【升级循环】执行一轮 SJTU-TPMSHX 升级迭代。工作目录 E:\LWH\SJTU-TPMSHX-upgrade（若当前会话不在其中，用 EnterWorktree 的 path 参数进入）。严格按 upgrade/PROTOCOL.md 执行：先读 upgrade/STATE.md，恢复中断项或开始下一条 ROADMAP 条目，过验证门后本地提交并更新状态文件。一轮只做一项，绝不 push，绝不写主检出 E:\LWH\SJTU-TPMSHX。
```

## 环境备忘（详情见 PROTOCOL §2）

- venv 底座 C:\Python312（torch 装自 pytorch cpu 索引：`torch==2.11.0+cpu`）
- 测试唯一入口：`scripts\run_tests_server.ps1`
- 每轮开工断言：`data\raw_data\试验记录表_整理版.xlsx` 存在
