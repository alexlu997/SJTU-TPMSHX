# 循环状态（STATE）

- iteration: 60 ——**D-1sc sCO2 考卷收案（`0ba9bcd`，exam_sco2.py 四题 + 基准冻结）**
- next: D-2sc sCO2 γ_f 修正试点——hot/cold/合并 × Δ{自由,0} 变体 → 修正 cF 面 +
  贝叶斯后验 + Δp 预测带 → 选侧证据包交 Alex。考卷首跑两发现直接进证据包：
  ①hot 函数性稳（LOO 1-2%）cold 幅值可信但函数崩（Re对半 37-48%）；
  ②γ_f/γ_air 超额 ×1.7-4.6 ⇒ 修正含 HX 级系统效应，适用面标"HX 级预测修正"
- in_progress: 无（iter 60 已收）
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
