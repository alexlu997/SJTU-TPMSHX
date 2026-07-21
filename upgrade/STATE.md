# 循环状态（STATE）

- iteration: 50 ——**A2 调查即关闭（`ff99e92`，前提证伪，零求解器改动），next=C**
- next: **C = 性能纵深**（Alex 已拍板）。首项 = parallel_runner BLAS 上限计时缺陷
  （FINAL-REPORT 候选池 C / HANDOFF §6 部分解遗留）。第一轮 = 现场核实缺陷现状
  （HANDOFF 表述 vs 代码）+ 复现测量 + 修复或裁决。后续 C 项按 profile 先行纪律
- in_progress: 无（iter 50 已收）
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
