# 循环状态（STATE）

- iteration: 57 ——**C8 打靶循环收案（`0519587` 特性 + 定价归档）：能力 opt-in 入库，
  默认翻转被定价否决（γ_df 锚点吸收旧口径偏置，翻转前置=候选 D γ 重锚，D5 记岔路），
  循环回待命模式**
- next: 【待命模式】每 tick：①扫 DECISIONS-NEEDED 新 `已决`→执行；②看本文件 next 是否被
  Alex 改写（候选池余量：B 科研支撑 / D D-F 系数方法【含 C8 翻转前置 + golden air-B
  工况点处置，见 D5】/ D4 尾账两枚）；③均无→静默吸收。照常维护 §8 定时器
  （armed 07-20，>5 天须重建→窗口 2026-07-25 前）
- in_progress: 无（iter 57 已收）
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
