# compute-contracts Delta — split-solver-kernels

## ADDED Requirements

### Requirement: Solver kernel modules split from driver layer
numba 内核 SHALL 与 Python 驱动层分模块：`solvers/_kernels_simple_2d.py`（2D SIMPLE 内核 + 压力泊松装配）、`solvers/_kernels_simple_3d.py`（3D SIMPLE 内核）、`solvers/_kernels_ltne_3d.py`（3D LTNE 内核，inline='always' 助手与调用者同模块）。原模块（simple_solver / simple_solver_3d / ltne_energy_3d）SHALL 保留求解器类、网格构建器、Python 驱动与 warmup，并全量 re-export 迁出内核名（外部 import 面零变更）。拆分 SHALL 为逐字搬移；ε-split 契约文本 SHALL NOT 有任何改动。

#### Scenario: Kernel import surface unchanged
- **WHEN** 测试执行 `from solvers.simple_solver import _sweep_u_jit_df`（或其余内核直连 import）
- **THEN** import 成功且行为与拆分前一致

#### Scenario: Golden bit-identical across the kernel split
- **WHEN** 金档 2D/3D --check 在拆分后运行（PYTHONHASHSEED=0）
- **THEN** PASS (bit-identical)

#### Scenario: Warmup still compiles cross-module
- **WHEN** `import solvers.ltne_energy_3d`（模块级 _warmup_jit() 触发）
- **THEN** 无异常（跨模块 JIT 编译成立）
