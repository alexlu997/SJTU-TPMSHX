# 循环状态（STATE）

- iteration: 49 ——**P1.8b F3 毕（`0816d9f`）：七轮全波次收官，ROADMAP 全清（含 P1.8b）**
- next: **A2 = 3D 物理 G 统一调查**（Alex 2026-07-21 拍板，D3(a)）。第一轮 = 立证伪方案
  （in-repo openspec change：什么证据能证明/推翻"统一物理 G 后 Shanghai headline 在
  γ 重锚后不劣化"；前置三件套评估=golden 重基准流程、Shanghai 重验证预算、γ_df 纠缠
  分析）+ 量化侦察（frozen 点+Shanghai 16 案例的 G 亏空谱）。绊线 4 断言是门。
  A2 后 → C 性能纵深（parallel_runner BLAS 计时缺陷首项）
- in_progress: 无（iter 49 已收）
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
