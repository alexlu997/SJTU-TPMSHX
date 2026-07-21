# 循环状态（STATE）

- iteration: 45 ——**P1.8b W2 毕（`59ee773`，31 文件，全门绿+golden 位同+Shanghai headline 位同），波次进行中**
- next: **P1.8b W3 = runs/ 35 + ui/ 1 迁移**（§10 委托；runs/ 直跑脚本多，逐个
  py_compile+可冒烟者冒烟；archive/ 冻结区只注记不迁移。波门 = 全套 + golden 位同 +
  身份测试 + tpmshx-run 冒烟 + 波内 sys.path 零残留白名单核对）。后续 W_final =
  库内 165 模块改写 + 撤垫片 + design 余量 + P1.5 尾巴
- in_progress: 无（iter 45 已收）
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
