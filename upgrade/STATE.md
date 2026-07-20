# 循环状态（STATE）

- iteration: 40 ——**收尾轮完成，ROADMAP 全清，循环转待命模式**
- next: 【待命模式】每 tick 流程：①读 upgrade/DECISIONS-NEEDED.md——出现新 `已决` →
  按该条目选项执行（恢复正常轮次纪律：STATE 标记/全门/簿记）；②读本文件 next 是否被
  Alex 改写（Alex 可直接写"启动候选 X"）；③均无 → 静默吸收，不产生提交、不回复长文。
  待命期间照常维护 §8 定时器（armed_at 超 5 天重建）。终审报告：upgrade/FINAL-REPORT.md
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
