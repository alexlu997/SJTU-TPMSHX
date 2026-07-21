# 循环状态（STATE）

- iteration: 46 ——**P1.8b W3 毕（`1f0e689`，32 文件，全门绿+golden 位同），仅剩 W_final**
- next: **P1.8b W_final**（库内 165 模块顶层→包名改写 + 撤垫片 + tests/design 15 文件
  余量 + P1.5 尾巴〔五阶段函数迁 run_stack_3d_stages.py〕+ mypy 基底换仓库根 +
  pyproject/atlas 注记收尾）。**量级最大，建议拆两轮**：F1=库内改写+design 余量
  （垫片在位保安全）；F2=撤垫片+尾巴+文档（须全库双风格残留 grep 零后才撤）。
  波门同前 + F2 加"身份测试改撤除断言"
- in_progress: 无（iter 46 已收）
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
