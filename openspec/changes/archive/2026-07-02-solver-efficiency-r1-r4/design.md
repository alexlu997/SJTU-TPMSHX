# Design: solver-efficiency-r1-r4

## Context

- 2D `solve()`（`simple_solver.py:1298`）唯一退出判据 = 绝对质量残差 < tol（+20 iter 下限）。横流/低速工况残差平台在 tol 之上 → 燃尽 max_iter。实测：golden air-air 管线 6 次 solve 中 3 次燃尽 10000 iter（B 侧），场早已静止。
- 3D `solve()`（`simple_solver_3d.py:1488-1506, 1641-1671`）已有成熟解：(A) 平台失速窗口 + (B) 速度增量判据，都门控在速度稳定性上（"场还在动就绝不早退"）。默认 on。
- `_update_density`（2D）每外迭代分配 4+ 个临时数组，占管线 7.3%。
- 3D 动量为 7 点一阶迎风（`_u/v/w_cell_df_3d`）；2D 动量有 SOU minmod 延迟修正（N2 审计后的 telescoping 面通量口径）。

## Goals / Non-Goals

**Goals:** R1 移植（默认 on，行为与 3D 逐参数一致）；R2 bit-identical 微优化；R3 证据（只测）；R4 opt-in SOU + 网格收敛证据。代码精简：R1 照抄 3D 语义不发明新机制；R4 用共享 helper 消除 9 份方向重复。

**Non-Goals:** 不改 3D 流动/能量求解器数值路径（R4 flag 默认 off）；不做相对残差判据改革（early-exit 已覆盖症状，判据语义改革影响全部工况，另议）；不实施 R3 发现的候选优化（先证据后立项）。

## Decisions

### D1 — R1 逐参数照抄 3D，属性名复用
`lowre_early_exit`（默认 True）、`lowre_vel_tol`（1e-4）、`lowre_stall_window`（30）、`lowre_stall_ratio`（1e-3），`getattr` 读取（与 3D 相同）。2D 差异仅两点：无 w 场；早退路径必须走 2D 特有的 `_enforce_mass_conservation()` 收尾（与现有收敛路径一致）。下限沿用 2D 的 `it >= 20`（3D 是 10；2D 现行严格判据就是 20，保持一致）。

### D2 — R1 golden 重基线流程
先 R2（bit-identical，用现有基线 `--check` 验证），后 R1，重捕获 golden。声明变化性质：所有场哈希变（退出迭代点提前），标量变化应在收敛容差内（对照打印新旧标量相对差，dP/Q 预期 <0.5%）。门槛：`validate_shanghai_aligned.py` RMSRE ≈ README 基准 8.4%（±0.5pp）+ 全量 pytest + 管线墙钟前后对比。

### D3 — R2 最小化：只消热点分配，不做 buffer 乒乓
`P_abs`、`rho_new` 用持久缓冲 + `out=` 运算；α 混合保持原表达式结构（IEEE 加乘交换律保证 bit-identical）；`self.rho_field` 重绑语义不变（调用方持旧引用的行为与现状相同）。R1 落地后此项收益本就缩水（迭代数 100×↓），不过度工程。

### D4 — R4 SOU 形式与精简
minmod SOU 延迟修正，2D N2 telescoping 口径（西/南/底面 limiter × F_lo，东/北/顶面 × F_hi）。**共享标量核**：单个 `@njit` helper 完成"一根轴上 5 点 stencil + 双向通量 → 修正量"（含缺邻居→limiter=0 的边界退化），u/v/w × x/y/z 的 9 个组合只做 stencil 取值（交错偏移不同），不重复限幅逻辑。flag `use_sou_momentum` 经 solver 属性 → 内核参数（int 0/1），false 分支数值零变化 → golden 3D 必须 PASS。
**替代方案（否决）**：幂律 diflow——改动更小但仍一阶精度上限，且与 2D 口径不一致；9 份完整方向 helper——冗余。

### D5 — R3/R4 证据交付
R3：gate 配置（20×10×3, kernel runner）cProfile 2 个 case，输出 SIMPLE-3D / AMG(spsolve) / LTNE-3D / 其余 的 cumtime 表 → `reports/solver-efficiency-r1-r4/CONCLUSIONS.md`，附行动建议（阈值：单阶段 >40% 才值得立项）。
R4：同一小型 3D 配置 2-3 档网格，SOU on/off 的 dP 网格序列 → 同一报告；"扶正为默认"须另立 change（动 Shanghai 3D 基线）。

## Risks / Trade-offs

- [R1 早退过早] → 判据门控在速度稳定性（照抄 3D，3D 已验证"只在场静止后触发"）；Shanghai 2D RMSRE 门槛兜底。
- [R1 重基线掩盖真回归] → R2 先行并独立 golden 验证；R1 diff 限于退出判据块，重基线时打印新旧标量相对差留痕。
- [R4 SOU 边界处理错误] → 复用 2D 语义 + 对拍测试：3D 单 xy 平面配置下与 2D SOU 修正逐点一致（或至少解析构造场下修正量对拍）；flag off 时与 pre-R4 输出 ULP 级等价（实施中发现：fastmath 内核加 `use_sou` 分支即触发重编译指令重排，flag off 场漂移 1e-16~1e-14 相对量级；严格 bit-identity 需复制 3 份 cell body ≈300 行，违背精简约束 → 改为数值证据 + 有意重基线，spec 已同步修订）。
- [golden 3D 跨进程非确定（实施中发现）] → 3D stack 输出依赖 PYTHONHASHSEED（dict/set 迭代序影响某处运算顺序）；golden 3D 捕获/校验必须固定 `PYTHONHASHSEED=0`（同进程内确定，2D gate 不受影响）。已记入报告；根因定位另立事项。
- [R3 小网格剖析不代表大网格] → 报告中声明适用范围（gate 配置即 headline 来源，优先优化它是对的）。

## Migration Plan

R2 → golden check → R1 → golden 重捕获 + Shanghai 2D 验证 → R3 剖析 → R4（flag off）→ golden 3D check → 基准 → 全量 pytest。回滚：R1/R2 为独立小 diff，可单独 revert；R4 flag off 即禁用。

## Open Questions

- R1 之后 B 侧若仍偶发平台外真不收敛（速度未静止），early-exit 不触发——那是另一个真问题（横流配置收敛性），届时以 R3 同款证据流程另立 change。
