# 循环状态（STATE）

- iteration: 39 ——**Phase 4 全部完成（P0–P4 五阶段主线全绿）**
- next: 收尾轮（ROADMAP 末节两项合并为一轮做：①合并前清单——upgrade/ 目录处置方案、
  与 master 合并策略（rebase 优先）、给 Alex 的终审报告；②Phase 5 候选池评审选单——
  A/B/C/D 四池附工作量与风险注记，连同 D2/D3 待决一起交 Alex 拍板。产出 = 终审报告文档
  （建议 upgrade/FINAL-REPORT.md + 进度页链接）+ PushNotification；收尾轮后循环转
  待命模式：不拆定时器但每 tick 只查 DECISIONS-NEEDED 有无新 `已决`，有则执行对应项）
- in_progress: 无
- armed_at: 2026-07-20（job c87569d6——Alex 暂停/恢复 loop 时重建（ef9566f6 已删）；>5 天须按 §8 重建 → 下个窗口 2026-07-25 前）
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
