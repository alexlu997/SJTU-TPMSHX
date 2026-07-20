# 循环状态（STATE）

- iteration: 24
- next: P2.1c（ruff format 评估——先盘点行号腐蚀受影响面：atlas file:line 引用 + 源码标记 wiring 测试断言，再决定做/不做/怎么做；纯评估轮，产出决策记录，可能与 P4.1 同轮）
- in_progress: 无
- armed_at: 2026-07-19（job d7888157；>5 天须按 PROTOCOL §8 重建；Alex 当日把节奏 25 分钟 → 15 分钟）
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
