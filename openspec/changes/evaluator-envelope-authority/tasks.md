# Tasks — evaluator-envelope-authority

## 契约测试（P1.4，iter 11；设计见 design.md D5）
- [x] tests/test_evaluator_pipeline_contract.py 六断言（legacy 默认 / B 冻结 / 整形隔离 /
      不路由 / 2D choke 双向现状 / D3 绊线）

## 切片 A（iter 8）
- [x] core/evaluators.py 三处种子 → `predict_outlet_p_sq`（冷 A、冷 B、热重播种）
- [x] `R_AIR = R_AIR_DEFAULT` 别名（保 `__all__` 兼容）
- [x] optimizer_qnehvi `_reset_warn_registries` + run_qnehvi 入口调用
- [x] tests/test_evaluator_envelope_authority.py（位同断言 + 源码 wiring + 重置 wiring）
- [x] 门禁：全套 suite + golden 位同

## 切片 B（iter 9；范围修正见 design D3）
- [x] 3D：`_post_solve_gate_3d` + evaluate_3d 接 invalid 通道
- [x] 2D：**不做**——2D 管线自身无 post-solve 门（ledger O1），政策问题转 DECISIONS D2
- [x] 假求解器单元测试 ×3（clean / 超音速 / 地板钳制）+ wiring 断言

## 切片 C（**BLOCKED on DECISIONS D3**——iter 10 发现管线间 G 口径不一致 + 标定纠缠）
- [ ] 待 D3 拍板后按选项执行（(c)：仅 2D 评估器 + frozen 2D 重基准；(a)：另立 ledger 级调查）
- [ ] 文档契约："Pareto 选点须经 Pipeline 复核"落 README/手册相应节（不依赖 D3，可随 P4 做）
