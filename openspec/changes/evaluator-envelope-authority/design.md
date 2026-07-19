# Design — evaluator-envelope-authority

## D1 种子权威（切片 A）

`envelope.predict_outlet_p_sq` 的实现是
`float(P_in)**2 − 2.0·float(R)·float(T)·float(C)·float(L)`（envelope.py:59-60），与
evaluators 的内联 `P_inA**2 − 2.0*R_AIR*T_inA*C_A*L_dom` **同一运算顺序、同一常数**，
对已是 float 的实参 `float()` 为无操作 ⇒ 逐位等价。C_est 的组装（`μG/K + cF·G²` 带
`max(K,1e-16)` 守卫）留在调用方——它是评估器对"均值几何"的选择，不属于 envelope 的职责。

R_AIR 保留在 `__all__`（`verify_pareto_3d.py:74` 在用），赋值改
`R_AIR = R_AIR_DEFAULT`，注释注明权威所在。

## D2 警告注册表重置粒度（切片 A）

**每战役（run_qnehvi 入口）**，不是每评估：
- 每评估重置 ⇒ N 评估战役最多 N 条同类警告——BO 场景下是日志洪水；
- 不重置 ⇒ 跨战役闩死（当前缺陷）；
- 每战役 = "一次用户动作一套去重"，与 `ComputePipeline.run`（compute_pipeline.py:120-123）
  同粒度。惰性 import 放函数体内，保持 optimizer 模块导入的轻量惯例（torch 同理）。

## D3 post-solve 门语义（切片 B，未实施）

- 位置：solve 返回后、目标整形前；
- 机制：对评估器手里的解字段跑与 `gate_solution` 同判据（Mach、最小绝对压），
  失败 → 3D 走既有 `invalid=True + invalid_reason` 通道（wrapper 已映射罚值），
  2D 走既有 choke-catch 的 `(−1e-6, dp_cap, mass)` 罚值——**复用两条已存在的罚值通道，
  不新增语义**；
- **不 raise**：ChokedFlowError 语义留给预解（2D 已有）；post-solve 失败是"解出来但非物理"，
  BO 需要的是有界坏值而非中断；
- 判据入参从评估器现有字段构造，若字段不足（如 3D 无 Mach 场缓存）则按
  `assess_solution_validity` 需要的最小集补采，禁止为门禁改动求解路径。

## D4 rho_inlet_ref（切片 C，未实施）

口径对齐 stages_2d:475（入口密度 = ρ(T_in, P_in_abs)）。2D 默认 `n_rho_loops` 路径上惰性
（等温快路无感）；3D var-ρ 外循环可能移动 `test_evaluator_frozen_values` 的 rel=1e-12 锁
⇒ 实施轮按 PROTOCOL §5：根因（本设计）+ 全 V&V 重跑 + `!` commit + DECISIONS 登记。

## 验证

- 切片 A：suite 全绿（frozen-values 数字锁未动即证位同）+ golden 位同 +
  `test_evaluator_envelope_authority.py` 四断言；
- 切片 B：构造 choke 邻域工况的 invalid 映射测试（tiny grid）；
- 切片 C：frozen-values 若动，重基准流程 + 新旧值并记。
