# 循环状态（STATE）

- iteration: 38
- next: P4.4（HANDOFF-windows-server.md 刷新：已确认过时处——§1 整节（max_outer + 压力
  字面量，iter 7 证据"上游均已修复"）、§2a 预解 choke（aa3f477 已加 raise→罚值）、
  §3a 热重播种地板（aa3f477 已改严格 NaN）；其余节逐条核实后改写；另核 AGENTS.md
  过期路径是否同步（P4.1a 收编节留的尾巴）；docs-only，完成后 Phase 4 收官 → 收尾轮）
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
