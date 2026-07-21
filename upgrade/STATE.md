# 循环状态（STATE）

- iteration: 55 ——**D4(b)-1 毕（曲线+裁定 30k→2k），next=(b)-2 实装+重基准**
- next: **D4(b)-2 实装+§5 重基准**：①改 _AMG_GATE=2000（注释引曲线数据）②§5 流程：
  改前 HEAD 捕获 golden 基线→改后重捕获→json+meta 同 commit 带 `!`③验证矩阵=全套件+
  golden 新基线自证+Shanghai 3D gate（headline 应位同：600 格在 LU 侧）+conservation
  六案例+wall_refine 计时对比+partial-BC 40³ 挂死构型试跑④顺手核 bcg_t 双计疑点
- in_progress: 无（iter 55 已收）
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
