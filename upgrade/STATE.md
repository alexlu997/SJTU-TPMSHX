# 循环状态（STATE）

- iteration: 51 ——**C-1 线程钳制时序修复毕（`6fc752b`，全门绿+golden 位同），HANDOFF §6b 闭案**
- next: **C-2 = 候选 C 余项盘点轮**（性能纵深还有什么值得做：以 P3.1 census 的
  durations 谱 + benchmarks/profiling 基建为底，按"profile 先行、禁拍脑袋"纪律
  列候选与量级预估，产出=盘点报告+建议排序，交 Alex 拍板；无明显标的则 C 收官回待命）
- in_progress: 无（iter 51 已收）
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
