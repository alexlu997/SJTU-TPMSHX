# C8 打靶循环：把解出的进口绝对压钉到用户指定的 P_in

## Why

`P_ref_abs` 是**出口**绝对压（ledger C8，CLAUDE.md 硬不变量 #7）：pp 方程把出口 pin 在
表压 0，故 出口绝对压 ≡ P_ref_abs，进口绝对压 = P_ref_abs + Δp_solved。

两个维度的生产管线都从 1D 可压缩 Forchheimer 闭式（`envelope.predict_outlet_p_sq`）
**估算**这个出口锚。但 1D 估算的 Δp ≠ 求解器实际解出的 Δp，于是**实现的进口绝对压
≠ 用户指定的 P_in**。实测（ledger C8，上海 case 16，2D 生产管线）：

    指定进口 304746 Pa，解出进口 288980 Pa —— 差 5.2%（≈16 kPa）

进口压差 5.2% ⇒ 全场密度水平偏低 ~5% ⇒ 可压缩 Δp 系统性偏高（Δp ∝ 1/ρ）。误差随
Δp/P_in 放大——低 Δp 工况可忽略，高 Δp 工况到百分之几量级。3D 同构（外循环重种子
`run_stack_3d_stages._outer_post_3d` 仍是 1D 闭式，只是随 T_avg 刷新，从不用解出的 Δp）。

ledger C8 遗留原文："**用打靶循环把种子迭代到进口压对上，两维都能再降一截误差——未做**"。
Alex 2026-07-22 点名启动（候选池 C8）。

## What Changes

- 两维生产管线的**外循环重种子**新增打靶模式：用**上一轮解出的 Δp**（各维各自的
  报告口径——3D `extract_dP_face_extrap`，2D pipe-weighted 格心差）按 P² 形式反解
  新的出口锚：

      P_out²_new = P_in_spec² − [(P_ref_old + Δp_solved)² − P_ref_old²]

  不动点 = 实现进口压恰为 P_in_spec；P² 形式吸收密度-水平反馈（1D 理想物理下一发命中，
  真实场 1–2 发进入 0.1% 级）。
- 3D 走既有 `_seed_p_ref` 同一 choke 门与地板（envelope_mode 一致）；2D 保持既有
  无守卫姿态（O1：clip 1e4 地板，不新增 raise）。
- 不可压缩侧（水 / sCO2 Phase-A）不打靶（ρ 冻结，压力水平不进物理——既有豁免不变）。
- 旋钮：cfg `p_in_shooting` > env `TPMSHX_P_IN_SHOOT` > 默认。**本变更先以默认 OFF
  入库（knob off 逐位同），实测定价后再单独 `!` 提交翻默认**（若证据支持）。
- 诊断（无条件，knob 无关）：结果字典新增 `P_in_realized_A/B`、`P_in_shoot_resid_A/B`
  （可压缩侧），让 OFF 模式的既有偏差首次可见。
- 优化器 evaluator **不打靶**（O2 约定：evaluator 只出排名，Pareto 报数须经生产管线
  重解——分歧清单加一行，不加代码）。

## Impact

- knob OFF（本提交）：golden-2D / golden-3D 逐位同；全套件绿；无任何数字移动。
- knob ON（后续默认翻转时）：golden 双维可压缩侧 dP/Q 移动（§5 重基准流程）；
  上海 2D/3D 门数字预期向好或持平（打靶消除的是**系统性**进口压偏差）；
  若实测变差 → 不翻默认，DECISIONS 报 Alex。
