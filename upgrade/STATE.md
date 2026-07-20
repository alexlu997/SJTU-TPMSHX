# 循环状态（STATE）

- iteration: 37
- next: P4.3（CI 增强评估：lint + fast-tier 上 GitHub Actions 的可行性——重测试仍本地；
  评估轮：读现 ci.yml，判断 ruff/mypy/import-layering/fast-tier 四门哪些能在 ubuntu CI 跑
  （注意 heavy manifest 的 nodeid 平台无关性、CI=true 对 ULP 钉定的既有 skip 语义）；
  产出改 ci.yml 的方案或"不改"裁决——**改 ci.yml 本身不触发本地门**（CI 配置不在套件疆域），
  但方案若含 workflow 文件改动需注意绝不 push 红线：改动只入库不推送，Alex 合并后才生效）
- in_progress: 无
- armed_at: 2026-07-20（job ef9566f6，iter 37 重建；>5 天须按 PROTOCOL §8 重建 → 下个窗口 2026-07-25 前）
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
