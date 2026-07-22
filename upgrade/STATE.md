# 循环状态（STATE）

- iteration: 64 ——**D-2sc-4 Gate A 复臂收案（`61cb1e2`，GOLD 门 PASS：RMSRE
  4.2% / max 8.1% < 15%）——sCO2 试点（D-1sc..D-2sc-4）全链闭环**
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
