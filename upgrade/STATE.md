# 循环状态（STATE）

- iteration: 58 ——**候选 D 立项对话轮（Alex 2026-07-22）：方向与边界四点拍板，
  章程化写入 ROADMAP D-0..D-4**
- next: D-0 溯源审计（下一 tick 开工；候选 D 全串行批到位，关键决策点仍停下问 Alex）
- in_progress: 无（iter 58 = 章程轮，docs-only）
- 候选 D 边界（Alex 2026-07-22 四点拍板，原文见 PROGRESS iter58 段）：
  ①全串行 a→b 一次批到位；②CFD 拟合 (K,cF)、试件实验标定 γ，**上海 16 例退出
  标定转纯盲考卷**；③sCO2 γ 并入但排空气侧重锚之后；④UQ 要（γ 后验 + Δp 预测带）
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
