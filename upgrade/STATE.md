# 循环状态（STATE）

- iteration: 43 ——**P1.8b W0 身份垫片毕（`88b63e9`，全门绿+golden 位同），P1.8b 波次进行中**
- next: **P1.8b W1 = tests/ 73 文件迁移**（删 sys.path 引导块 + 顶层导入 → `sjtu_tpmshx.*`；
  §10 委托：子代理机械执行分批，Fable 复核提交；波门 = 全套 + golden 位同 + 身份测试 +
  tpmshx-run 冒烟 + tests/ 内 sys.path 零残留 grep）。台账：openspec
  p18b-import-style-migration tasks.md。后续 W2 validation+df_surrogate → W3 runs+ui
  → W_final 库内改写+撤垫片
- in_progress: 无（iter 43 已收）
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
