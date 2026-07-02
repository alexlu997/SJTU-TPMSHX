# Proposal: simpler-coupling-2d

## Why

用户提出三个问题：(1) pysimpler（Tao `Main95.f` 的 numpy 蒸馏版，已发布 PyPI `pysimpler-fvm`）是否完善；(2) 是否应把该 SIMPLE 求解器打包成 C++ 库接入 sjtu_tpmshx 以提升计算效率；(3) 有无更好的方案。

调研结论（决策记录，本 proposal 即为该记录）：

1. **pysimpler 完善度** — 作为教学/参考包已完善：4 个验证门全过（导热制造解 err≈5.6e-15、Re=100 方腔 vs Ghia）、CI 绿、文档站、PyPI v0.1.0。作为生产 CFD **有意**不完善（scope 决定，非缺陷）：常 ρ/μ（不可压）、均匀 Cartesian 网格、纯 Python 三重循环、动量方程无 S_C/S_P 源项钩子、无 3D、无收敛驱动器。补齐这些等于重写一个生产求解器 —— 而 sjtu_tpmshx 已经有了。
2. **不接代码、不 C++ 化** — sjtu_tpmshx 生产求解器（`solvers/simple_solver.py` / `simple_solver_3d.py`）在物理与性能两方面都远超 pysimpler：Numba njit 编译动量扫掠（文档实测 ~50-100× vs 纯 Python）、2D 压力修正稀疏直接解 / 3D AMG、可压缩 ρ(P,T)（repo #1 硬约束）、D-F 闭包、LTNE、质量流量入口、choke envelope。pysimpler 是常密度不可压 —— 接入即违反硬约束；C++ 化 pysimpler 得到的仍是缺必需物理的求解器，等于用 C++ 重写 simple_solver.py，预期收益（Numba → C++ 约 1.2-2×）远小于成本（Windows 工具链、pybind11 双语言维护、golden + Shanghai 基线全量重验证）。
3. **更好的方案（本 change 实施）** — 移植 pysimpler 的**算法**而非代码：SIMPLER 耦合（伪速度 → 压力方程直接解 P → p' 只修正速度）。pysimpler 方腔基准实测外迭代 405→121（3.3×↓）。2D 生产求解器每外迭代已做一次稀疏**直接**解，P 方程与 p' 方程系数矩阵**同构**（同一 ρ·A·d 五点 stencil）→ 一次 LU 分解、两次回代，SIMPLER 的第二次椭圆解近乎免费；若外迭代数按 Tao 比例缩减，净收益可观。以 opt-in 模式实施，默认路径 bit-identical，实测定收益。

## What Changes

- **决策记录**：pysimpler 保持独立教学包（不动）；不引入其代码、不做 C++ 端口。理由如上。
- **新增 opt-in 耦合模式**：`SimpleSolver2D.solve(..., coupling='simpler')`。默认 `'simple'`，默认路径代码不动 → golden 2D bit-identical。
- **新增 Numba 内核**：伪速度 û/v̂ 装配（动量系数、无压力梯度源，单遍 Jacobi 式求值，同时填 d_u/d_v）。现有扫掠内核不改。
- **压力方程复用 PP 机制**：`_assemble_pp_data_jit` 以 û/v̂ 为面速度装配 RHS（系数不变），splu 一次分解，P 方程与 p' 方程两次回代。P 直接替换（Tao 式，不加 α_p 松弛）；若可压缩耦合振荡则回退为带松弛替换（design.md 记录触发条件）。
- **p' 修正复用 `_correct_jit`**：`alpha_p=0.0` 自然跳过 P 修正（SIMPLER 只修速度）。
- **基准脚本**：Shanghai 风格 2D 配置，SIMPLE vs SIMPLER：外迭代数、墙钟时间、收敛场一致性（Δp、速度场相对差）。
- **验收门**：full pytest + golden 2D bit-identical（默认路径）+ 基准报告。若 SIMPLER 墙钟加速 < 1.3× 或场不一致 → 记录负结果，模式标注 experimental（负结果也是有效交付）。

## Capabilities

### New Capabilities
- `simpler-coupling-2d`: 2D 生产求解器的 opt-in SIMPLER 压力-速度耦合模式（伪速度压力方程 + LU 复用 + 仅速度 p' 修正），含默认路径不变性与基准验收要求。

### Modified Capabilities

（无 — 默认 SIMPLE 行为、API 默认值、golden 基线均不变。）

## Impact

- **代码**：`sjtu_tpmshx/solvers/simple_solver.py`（新内核 + solve 分支）；新基准脚本（`sjtu_tpmshx/runs/` 下）；新测试（`sjtu_tpmshx/tests/`）。
- **不受影响**：3D 求解器（本 change 不动；若 2D 实测 ≥1.3× 加速，另立 change 推广到 3D/AMG）、DF 闭包、LTNE、Nu 相关、pipelines 默认行为。
- **依赖**：无新增（scipy splu 已在依赖内）。
- **风险**：可压缩 ρ(P) 反馈 + 质量流量入口与"P 直接解"的相互作用未经验证 —— 这正是实验要回答的问题；失败路径已定义（负结果记录）。
