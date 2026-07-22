# 循环状态（STATE）

- iteration: 61 ——**D-2sc-1 证据包收案（`349f466`）：D6 已决（Alex 轮中快裁 hot，
  证据坐实），Δ 子选择 = hot-free**
- next: D-2sc-2 产线接线切片——γ_f^hot(Re) 乘进 sCO2 cF 产线路径
  （`predict.sco2_cf_scale` 层，Re_in 锚定与现行模式同构），窗守卫强制
  （exam_sco2.assert_in_window，窗外回落光滑壁+警告——设计见 D6/审计 §4），
  air/water 位同证明（golden 双维 + Shanghai untouched）+ 新测试；
  γ_Nu(Re) 修正入产线评估顺带排下一切片
- in_progress: 无（iter 61 已收）
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
