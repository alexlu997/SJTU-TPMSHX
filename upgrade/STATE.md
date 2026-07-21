# 循环状态（STATE）

- iteration: 44 ——**P1.8b W1 tests 迁移毕（`140166b`，141 文件，全门绿+golden 位同），波次进行中**
- next: **P1.8b W2 = validation/ 17 + df_surrogate/ 7 迁移**（同 W1 §10 委托模式；
  波门 = 全套 + golden 位同 + 身份测试 + tpmshx-run 冒烟 + 波内 sys.path 零残留 +
  validate_shanghai_3d_real gate 脚本直跑冒烟（validation 侧脚本可独立执行语义不变）。
  台账 openspec p18b tasks.md。后续 W3 runs+ui → W_final 库内+撤垫片+design 余量）
- in_progress: 无（iter 44 已收）
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
