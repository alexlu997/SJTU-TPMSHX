# 循环状态（STATE）

- iteration: 53 ——**D4(a) 毕（`7061836`，全门 7:44+golden 位同），next=(c) profile**
- next: **D4(c) = profile 轮（(b) 前置）**：①wall_refine 异常解剖（refined 447.7s vs
  uniform 0.6s @288 基格——拉伸网格上 pp/AMG/GS 谁吃掉了 wall；cProfile+分段计时）；
  ②AMG 网格（>32k）生产解的 pp 占比测量（rtol_dyn 复活收益上限）。产出=测量报告
  → (b) 实装方案。之后 (b) AMG rtol_dyn 复活（§5 重基准已授权）
- in_progress: 无（iter 53 已收）
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
