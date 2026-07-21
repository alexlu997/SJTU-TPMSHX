# 循环状态（STATE）

- iteration: 54 ——**D4(c) 毕（pp LU 重分解 89.4% 实锤），next=(b) 实装**
- next: **D4(b) 实装**：第一步=中带成本曲线（2k/5k/12k/20k/30k 格：LU 单次 vs AMG 单次
  vs 迭代+复用预条件），据线定方案（AMG 门下调 / 分解缓存 / 中带迭代）；第二步=实装+
  全门+golden（大概率 §5 重基准，已授权）；验证矩阵含 wall_refine 构型与 partial-BC
  40×40×20 挂死构型
- in_progress: 无（iter 54 已收）
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
