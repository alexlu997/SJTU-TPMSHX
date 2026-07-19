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

## D3 post-solve 门语义（切片 B，**范围修正后仅 3D**——iter 9 实施）

- **范围修正（iter 9 现场核实）**：post-solve 门只有 **3D 管线**有（run_stack_3d:2151-2164）；
  **2D 管线自己没有**（stages_2d 无 gate_solution 调用；ledger O1"2D 从未有 choke 守卫"，
  预解也是 clip 不 raise）。给 2D 评估器加门 = 评估器领先自家管线的物理政策
  → 转 DECISIONS-NEEDED **D2** 由 Alex 拍板，本变更不做。
- 3D 实施：`core/evaluators._post_solve_gate_3d(sA, sB, Ta, Tb)`——
  与生产门同判据（min 绝对压 vs clip 地板 + 逐格 Mach@局域温度，双侧）；
  `assess_solution_validity` 直调（天然不 raise）；|v| 取模框架不变 ⇒ 双侧各在自家
  solver 系中心化三分量，实系 T 场用 ρ/LTNE 管路的同款自逆变换映射入 solver 系；
- 失败 → 既有 NaN+invalid 契约（与冷/热 choke 同形 dict；质量保真实几何值）——
  verify_pareto 排除、BO wrapper 映射有界罚值，零新语义。

## D4 rho_inlet_ref（切片 C —— **BLOCKED，前提坍缩为 DECISIONS D3**）

iter 10 现场核实推翻本节原设计："补传即对齐"的前提不成立——**2D 与 3D 管线自身的 G 口径
就不一致**（2D 显式物理 ρ(T_in,P_in)；3D 求解器无此旋钮、首解捕获 ρ(T_in,P_out_seed)），
且 3D 口径与 validate 的实验 ṁ→u 换算相悖（亏空 2D 冻结点 7.38% / 3D 冻结点 19.30%），
已被 γ_df 标定部分吸收。统一方向是标定级决策 → `upgrade/DECISIONS-NEEDED.md` **D3**。
本变更的切片 C 冻结，待 D3 拍板后按其选项执行（(c) 时仅动 2D 评估器 + frozen 2D 重基准）。

## D5 契约测试（P1.4，iter 11）

`tests/test_evaluator_pipeline_contract.py` 把审计 §2 的"有意差异"逐条固化为机器断言
（主规则：**Pareto 选点须经 Pipeline 复核后方可引用数字**；评估器是廉价筛选层）：
legacy 收敛默认（签名 introspect）、B 侧冻结（日志标记）、目标整形只在评估器、
不路由 Pipeline、2D choke"评估器 raise / 管线 clip"现状双向钉住（raise **语义**缺席而非
词汇缺席——stages_2d 注释里有该词）、G 口径差异 D3 绊线（四处 rho_inlet_ref 在/缺席断言，
任一变动即触发，强制与 D3 决议同 commit 更新）。断言失败的处置规则写在模块 docstring：
修代码（事故漂移）或改契约+openspec 同步（有意决议），**绝不删断言了事**。

## 验证

- 切片 A：suite 全绿（frozen-values 数字锁未动即证位同）+ golden 位同 +
  `test_evaluator_envelope_authority.py` 四断言；
- 切片 B：构造 choke 邻域工况的 invalid 映射测试（tiny grid）；
- 切片 C：frozen-values 若动，重基准流程 + 新旧值并记。
