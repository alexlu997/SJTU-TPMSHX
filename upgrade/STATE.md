# 循环状态（STATE）

- iteration: 70 ——**D-2b-2 气侧收案（`68b45fa`）：γ_HX 两拓扑一致 ×1.26
  （几何无关坐实）；Diamond 双层完全闭合（3.04 vs 3.10）；Gyroid 残差
  ×1.29（假说：534.8 旧栈伪迹 vs 样机差异——D-2c 盲考裁决）。
  ⏸ **循环暂停（Alex 2026-07-22 原话："完成这步后请先暂停"）**——
  定时器已拆（8f180729 已删），恢复时按 §8 重建**
- next: 【暂停中】恢复后 = D-2b-3：①水侧 γ_HX（7-6-Water-dp，注意 G 表
  负压差坏点/传感器地板）②跨流体一致性（γ_HX_air ×1.26 vs γ_HX_water）
  ③sCO2 γ_f 跨域对照（hot 7.0-7.9 / cold 3.3-4.2 vs 双层合成）④双层合成
  面 + 上海盲考准备（D-2c）
- in_progress: 无（iter 70 已收）
- next: D-2b 实施（依 §8 架构，除非 Alex 改向）：①γ_specimen(L,t) 纯试件
  面（dev 基，L6/L8 锚，t 模型照 gamma_df v4 结构）②γ_HX 用 7-6 HX 双流体
  实验标定（含任务 3.1 口径调和）③贝叶斯后验（UQ）④对照组 = 纯试件方案
  ⑤上海 16 盲考跑分（两方案并排）。规模 2-3 轮，先 ①+④
- next: D-2a-2 cF/K 候选面（dev 表 → log-TPS，LOO 考卷 vs SmoothDF 基 vs
  core 基；复用 06-30 的 LOO 门槛设计——"cF LOO ≪ gamma_df 面 87/122%"）。
  注意池：col47 锚 L4/L6 异常（06-30 发现）直接冲击 D-2b 可信层设计，
  D-2b 开工前须复核该发现（试验记录表 col43/47 原始数据 vs 2-stage 面）
- next: 水/空气阶段开工——D-2a CF-REFIT 收尾（原始水 CFD 两段法提 cF
  〔K 已做〕，log-TPS 面，与 SmoothDF 基同考卷对比）。剩余尾账不阻塞：
  projects/703 其余 9 脚本死导入（静默债）、G_7_6/D_7_6 CFD 补算触发器、
  L4/L5 粗糙壁仲裁触发器
- in_progress: 无（iter 64 已收）
- 候选 D 边界（Alex 2026-07-22 四点拍板，原文见 PROGRESS iter58 段）：
  ①全串行 a→b 一次批到位；②CFD 拟合 (K,cF)、试件实验标定 γ，**上海 16 例退出
  标定转纯盲考卷**；③sCO2 γ 并入但排空气侧重锚之后；④UQ 要（γ 后验 + Δp 预测带）
- armed_at: 2026-07-22（job 8f180729——iter 64 收轮时重建，旧 c87569d6 已删；
  >5 天须按 §8 重建 → 下个窗口 2026-07-27 前）
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
