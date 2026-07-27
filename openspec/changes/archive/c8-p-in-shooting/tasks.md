# 任务清单

- [x] T1 golden-2D 现场基线捕获（HEAD，改码前）→ job tmp/golden_2d_pre_c8.json
- [x] T2 3D：`_outer_post_3d` A/B 侧打靶分支 + knob 读取 + 结果诊断键
- [x] T3 2D：`_pipe_weighted` 提级、`_run_simple(p_shoot_prev=)`、`_step_2d` 传参、
      结果诊断键（教训重演：raw dict 键必须转发进 `_finalize_cfg` diagnostics，
      否则 ComputeResult 消费方全盲——与 2026-07-12 envelope_valid 同款）
- [x] T4 测试 `test_p_in_shooting.py`：8 条——更新式代数（不动点/一发命中/choke 地板）、
      3D ON 命中 spec 且优于 OFF、3D 真 choke 必 raise（新能力锁定）、2D ON 双侧命中、
      水侧 NaN 豁免（12³ 工况点选择教训：1D 预检的 P² 耗尽非线性，u=25 估算即 choke）
- [x] T5 门：套件 1284+10 绿（3:34）+ golden-3D 位同 + golden-2D（对 T1 基线）位同
- [x] T6 提交 `0519587`（knob OFF，行为位同）
- [x] T7 定价实测（见 design §6）：3D case12 起 in-model choke、完成的 11 例误差
      单调劣化 +2~9.4pp；2D RMSRE_dP 8.62→10.73%；golden-3D ON 15³ 亦 choke
- [x] T8 裁定 = **不翻默认**（证据一致反对，非"混"）：γ_df 锚点吸收了旧口径的
      压力水平偏置，翻转须与候选 D 的 γ 重锚同波。DECISIONS D5 登记岔路 +
      重启触发；能力以 opt-in 形态保留收案
