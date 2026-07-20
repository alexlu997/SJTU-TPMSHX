# 循环状态（STATE）

- iteration: 35
- next: P4.1c（atlas 外围域收编：ui-core（run_results mixin + polygon_calc 迁入）/
  runs（tools 三件 + polygon_calc 迁出）/ solvers 卷小修（threads advisory / tpms_geometry
  拷贝语义 / chi_s 每调用读取——分布在 solvers-2d/3d/closures/fields-mesh 四卷，逐卷
  grep 定位受影响段）/ PROJECT_MANUAL §6 对齐；完成后 P4.1 整项收案）
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
