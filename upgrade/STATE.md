# 循环状态（STATE）

- iteration: 74
- 本轮（74）：**D-2b-3 γ_HX 水侧 + 气/水跨流体对照（`7ea25ec`）**——
  新增 `gamma_hx_water.py`。水侧 γ_HX D **2.44** / G **2.18**（vs 气侧
  D 1.08 / G 1.23）。两条结论（审计 §11）：①**G/D 序反号**（水 0.89 / 气
  1.15）⇒ γ_HX 不是纯拓扑常数，iter 73 那对数不可当拓扑参数写进合成面；
  ②水/气 ×2 的首要嫌疑是**水侧 A_flow 口径**（表内通道数 34 气 / 28 水，
  气侧工具按"对称芯同几何"推广给了水侧）——反解 A_water = 0.626×/0.733×
  A_air，标称 28/34 只吃掉一半 ⇒ **DECISIONS D8 待数据方**。
  顺带检出原始表两处缺陷：G 工况1 Δp = −48.4 Pa（负压差）、D 工况10/11
  除 ṁ 外逐位相同（复制粘贴）。
- iteration 73 ——**R1-R3 三轮批（Alex 2026-07-23 解除暂停指示"提交 master +
  恢复循环做 R1-R3"，2026-07-25 会话内连续完成）**：
  - R1 `54c9ed2`+`bc0f6da`：master `7ebdf6e`（水/sCO2 Nu 重拟至修正 CFD 上传，
    循环受托提交）合入 + γ_Nu 重冻 D 1.807/G 1.125（G 混杂解除，纯粗糙度因子）+
    金门 water_b 重采（air_air 位同）+ 数据底座同步。台账 NU-REFIT-0723、D7。
  - R2 `8190ccc`：dev 表切修正 Um 基，u 不变量 + (u_o/u_n)² 双重验证，
    LOO 反而更优（D cF 12.5→9.6%）。
  - R3 `d7d9a1d`：γ_spec/γ_HX 重跑三结论重验——**"×1.26 拓扑无关"推翻**
    （D 1.08/G 1.23 分化）、Diamond 双层改写为"试件面基本单独闭合"、
    G 对上海残差 ×1.296 量级确认（假说与 D-2c 盲考裁决法不变）。audit §10。
- in_progress: 无（iter 74 已收）
- next: **D-2b-4 双层合成面（γ_spec × γ_HX）+ UQ 后验带**——**水侧腿
  BLOCKED on D8**（水侧 A_flow 口径未证实前不闭合）；**气侧腿可做**，但
  写法必须改：γ_HX 按拓扑常数固化已被 iter 74 证否（G/D 序反号），合成面
  改为"气侧标定 + 带宽吃掉拓扑不稳定性"。之后 **D-2b-5 sCO2 腿**（γ_f hot
  7.0-7.9 vs 双层合成；sCO2 f 侧重提 K 面 + sco2_df cF 在新导出 + γ_f 重冻，
  tripwire 现绿、f 侧 CFD 基未动）→ **D-2c 上海盲考**（只用气侧/上海，
  不受 D8 影响，可照原计划推进）
- 候选 D 边界（Alex 2026-07-22 四点拍板，原文见 PROGRESS iter58 段）：
  ①全串行 a→b 一次批到位；②CFD 拟合 (K,cF)、试件实验标定 γ，**上海 16 例退出
  标定转纯盲考卷**；③sCO2 γ 并入但排空气侧重锚之后；④UQ 要（γ 后验 + Δp 预测带）
- 模型（Alex 2026-07-25）：主循环 **Opus**、暂停 Fable——见 PROTOCOL §10。
  **iter 74 起 Opus 5 型号已可用，本轮实跑 = Claude Opus 5 (1M context)**，
  Alex 原话"用 opus 5"至此字面落地（§10 的"新型号出现即跟进"生效）。
- armed_at: 2026-07-25（iter 74，job `5e52a278`，规格同下）。
  **注意**：本轮由**后台作业会话**重建定时器——cron 是 session-only，
  后台作业结束时会随会话消失。若下一轮没自动跑，按 §8 在前台会话说
  "继续升级循环"重建即可（磁盘状态齐全，不丢进度）。
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
