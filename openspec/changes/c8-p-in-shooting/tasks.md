# 任务清单

- [x] T1 golden-2D 现场基线捕获（HEAD，改码前）→ job tmp/golden_2d_pre_c8.json
- [x] T2 3D：`_outer_post_3d` A/B 侧打靶分支 + knob 读取 + 结果诊断键
- [x] T3 2D：`_pipe_weighted` 提级、`_run_simple(p_shoot_prev=)`、`_step_2d` 传参、
      结果诊断键（教训重演：raw dict 键必须转发进 `_finalize_cfg` diagnostics，
      否则 ComputeResult 消费方全盲——与 2026-07-12 envelope_valid 同款）
- [ ] T4 测试 `test_p_in_shooting.py`：更新式代数不动点、3D ON 命中 spec（且优于 OFF）、
      2D ON 命中 spec、不可压缩侧键缺席
- [ ] T5 门：全套件双 pass 绿 + golden-3D --check 位同 + golden-2D --check（对 T1 基线）位同
- [ ] T6 提交（knob OFF，行为位同）
- [ ] T7 定价实测：TPMSHX_P_IN_SHOOT=1 跑上海 2D/3D 验证器 + golden 双维 capture，
      数字对照 BASELINE；OFF 模式 resid 诊断一并记录
- [ ] T8 证据净 → 默认翻转 `!` 提交（§5：golden 双维重基准 + 受影响钉定测试 + 台账回写
      + DECISIONS 登记 + 通知 Alex）；证据混 → DECISIONS 报 Alex 待裁
