# 循环状态（STATE）

- iteration: 73 ——**R1-R3 三轮批（Alex 2026-07-23 解除暂停指示"提交 master +
  恢复循环做 R1-R3"，2026-07-25 会话内连续完成）**：
  - R1 `54c9ed2`+`bc0f6da`：master `7ebdf6e`（水/sCO2 Nu 重拟至修正 CFD 上传，
    循环受托提交）合入 + γ_Nu 重冻 D 1.807/G 1.125（G 混杂解除，纯粗糙度因子）+
    金门 water_b 重采（air_air 位同）+ 数据底座同步。台账 NU-REFIT-0723、D7。
  - R2 `8190ccc`：dev 表切修正 Um 基，u 不变量 + (u_o/u_n)² 双重验证，
    LOO 反而更优（D cF 12.5→9.6%）。
  - R3 `d7d9a1d`：γ_spec/γ_HX 重跑三结论重验——**"×1.26 拓扑无关"推翻**
    （D 1.08/G 1.23 分化）、Diamond 双层改写为"试件面基本单独闭合"、
    G 对上海残差 ×1.296 量级确认（假说与 D-2c 盲考裁决法不变）。audit §10。
- in_progress: 无（iter 73 已收）
- next: **D-2b-3**（原暂停前 next，现全部落在修正数据上）：①水侧 γ_HX
  （7-6-Water-dp.xlsx 未变，试件层用 R2 新 dev cF；注意 G 表负压差坏点/
  传感器地板）②跨流体一致性（空气 γ_HX D 1.08/G 1.23 vs 水侧；sCO2 γ_f
  hot 7.0-7.9 vs 双层合成）③双层合成面（γ_spec × γ_HX，分拓扑不再共享）+
  UQ 后验带 ④D-2c 上海盲考准备。sCO2 f 侧重提（K 面 + sco2_df cF 在新导出）
  + γ_f 重冻排入本序列（tripwire 现绿，f 侧 CFD 基未动）
- 候选 D 边界（Alex 2026-07-22 四点拍板，原文见 PROGRESS iter58 段）：
  ①全串行 a→b 一次批到位；②CFD 拟合 (K,cF)、试件实验标定 γ，**上海 16 例退出
  标定转纯盲考卷**；③sCO2 γ 并入但排空气侧重锚之后；④UQ 要（γ 后验 + Δp 预测带）
- 模型（Alex 2026-07-25）：主循环改用 **Opus**（最新 4.8，无 Opus 5 型号）、
  暂停 Fable——见 PROTOCOL §10。cron 触发的新会话按 Alex /model 默认（已设
  Opus 4.8）自动跑 Opus。本会话若仍 Fable 需 Alex 手动 /model 切。
- armed_at: 【待重建】Alex 2026-07-25 要新开会话续跑，本会话定时器 `649f1bdf`
  已拆——新会话说"继续升级循环"后按 §8 重建（或按 Alex 指示手动逐轮）
- cron_spec: `7,22,37,52 * * * *`
- 基点：master `4b32da4`（R1 起并入 `7ebdf6e` 修正关联式）；分支 `upgrade/loop`

## cron 提示词（重建定时器时逐字使用）

```
【升级循环】执行一轮 SJTU-TPMSHX 升级迭代。工作目录 E:\LWH\SJTU-TPMSHX-upgrade（若当前会话不在其中，用 EnterWorktree 的 path 参数进入）。严格按 upgrade/PROTOCOL.md 执行：先读 upgrade/STATE.md，恢复中断项或开始下一条 ROADMAP 条目，过验证门后本地提交并更新状态文件。一轮只做一项，绝不 push，绝不写主检出 E:\LWH\SJTU-TPMSHX。
```

## 环境备忘（详情见 PROTOCOL §2）

- venv 底座 C:\Python312（torch 装自 pytorch cpu 索引：`torch==2.11.0+cpu`）
- 测试唯一入口：`scripts\run_tests_server.ps1`
- 每轮开工断言：`data\raw_data\试验记录表_整理版.xlsx` 存在
