# 循环状态（STATE）

- iteration: 48 ——**P1.8b F2 撤垫片毕（`79e5c21`，全门绿+golden 位同）：导入迁移主体 W0–F2 全部完成**
- next: **P1.8b F3 = P1.5 尾巴**（run_stack_3d 五阶段函数文件级迁移 →
  run_stack_3d_stages.py，保 re-export 面 + golden 位同；此为迁移波次唯一余项，
  做完即可归档 openspec 变更并勾 ROADMAP P1.8b）。若 Alex 另有优先级
  （候选池 A2/B/C/D），F3 可延后——它不阻塞任何事
- in_progress: 无（iter 48 已收）
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
