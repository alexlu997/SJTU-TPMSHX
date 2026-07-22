# 循环状态（STATE）

- iteration: 63 ——**D-2sc-3 γ_Nu 接线收案（`11289db`）：sCO2 Nu 升级为窗内
  HX 级修正（幅值制，双消费点，Nu 单源合规）；Gate A 复臂物理触发器已满足、
  机械债揭出（projects/703 死导入+XLSX 路径）**
- next: D-2sc-4 Gate A 复臂——①validate_sco2_d76.py 导入迁移（projects/703
  未进 P1.8b 波，死导入被 try/skip 吞成虚绿）②XLSX 路径修（D-7-6-sCO2/…V1
  → 平铺 D-7-6实验数据-sCO2.xlsx，先核同源性）③GOLD 6 例实跑判 15% 门
  ④过则解除 skip。完成后 D-2sc 全收案 → 水/空气阶段（D-2a CF-REFIT）。
  注意：projects/703 其余 9 脚本同样死导入（静默债，随 D-2sc-4 记账不阻塞）
- in_progress: 无（iter 63 已收）
- ⏰ 定时器：armed 07-20，>5 天线 = 07-25——**明日（07-23）过 3 天，下下轮
  前须重建**（CronDelete c87569d6 + CronCreate 同规格，STATE §cron 提示词逐字）
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
