# cProfile baseline (Phase 5.1)

**日期**: 2026-05-09
**关联**: Phase 5 (代码质量 + 效率) 起点
**脚本**: `benchmarks/profiling/profile_evaluator.py`, `profile_compute.py`
**数据**: `benchmarks/profiling/{eval,compute}_baseline.prof`

## 0. TL;DR

代码已在 C 层 (88% 时间在 SuperLU + numba JIT)。Python 级优化空间 < 5%。**速度大幅提升必须靠并行 (Phase 1)**, 不是 Python 重写。

## 1. 测试场景

| 场景 | 几何 | tol_simple | n_rho_loops | 用途 | wall/eval |
|---|---|---|---|---|---|
| BO inner | 100×50 mm air-air | 1e-2 | 2 | 优化器内循环 | **0.37 s** |
| Compute | Shanghai 182×42 mm | 1e-3 | 3 | UI Compute, 1 design | **0.76 s** |

均匀 L=6 mm / t=0.4 mm 中位设计, post-warmup。

## 2. 热点分布 (Compute 场景, 0.759 s 总)

| rank | 函数 | tottime [s] | % | 类型 |
|---|---|---|---|---|
| 1 | `scipy.sparse._dsolve._superlu.gssv` | 0.341 | **45%** | C 内核 (SuperLU) |
| 2 | `solve_full_domain` | 0.328 | **43%** | numba `@njit` ★ |
| 3 | `simple_solver.SIMPLESolver.solve` | 0.025 | 3% | Python 包装 |
| 4 | `_build_pp_sparsity_pattern` | 0.013 | 2% | Python loop (init 一次) |
| 5 | `_update_density` | 0.004 | 0.5% | numpy vectorized |
| 其余 | ... | < 0.05 | < 7% | dispatch 开销 |

★ `solve_full.py` 已用 `@njit(cache=True)` 在 `_sou_corr_x`, `_sou_corr_y`, `_gs_full_chunk` 三 kernel; cProfile 看不见 JIT 内部 (opaque), 但 0.328s 全在 C 层。

## 3. spsolve 分解 (Compute 场景)

| 操作 | tottime/call | calls | total |
|---|---|---|---|
| `gssv` (LU + back-sub) | 2.84 ms | 120 | 0.341 s |
| `csr_sort_indices` | 0.03 ms | 120 | 0.004 s |
| sparse `__init__` | 0.06 ms | 120 | 0.007 s |
| `sum_duplicates` | 0.01 ms | 120 | 0.001 s |

**结论**: SuperLU 自身占 spsolve 总时间的 ~96%。CSR 装配开销 (~10 ms) 可忽略。

## 4. 优化空间分析

### 已饱和 (无 Python 级优化)

| 项 | 状态 | 备注 |
|---|---|---|
| `solve_full_domain` GS-LTNE | numba `@njit(cache=True)` | 代码已是 best-effort |
| spsolve (gssv) | C 内核 SuperLU | scipy 默认 |
| numpy vector ops | 全程向量化 | _update_density, build_grid_arrays |

### 边际可优 (< 5% 总时间)

| 项 | 现状 | 可能改 | 估收益 |
|---|---|---|---|
| `_build_pp_sparsity_pattern` | Python loop + idx() × 20k | 改 numpy fancy index | -0.013 s (init 一次) |
| sparse `__init__` | 每 spsolve call 重建 CSR | **缓存 CSR 结构, 仅更新 data** | -0.005 s/call × 120 = -0.6 s/eval ★ |
| spsolve 重复符号分解 | gssv 每 call 全 LU | `splu()` 一次 + `solve()` × N | -10-30%? 需测 |

★ **唯一中等收益机会**: PP 矩阵稀疏 pattern 在 SIMPLE 内部不变, 系数随 u, v 改; 改 `_solve_pp_sparse_fast` 复用 CSR 容器 (只改 `.data`) 可省 CSR 构造 + sort_indices, 估省 ~5-7% 总时间 (~50 ms/Compute call)。

### 算法级 (大改, 投入产出比低)

| 项 | 改 | 估收益 | 风险 |
|---|---|---|---|
| spsolve → CG/BICGSTAB | 迭代解 PP | 大网格 +30%; 当前 ~450 cell 反而慢 | 高 (SPD 性质要保) |
| GS-LTNE → multigrid | smoother + 多重网格 | 大网格 +50%; 当前小网格无收益 | 高 (开发 1-2 周) |
| Anderson 加速外循环 | Picard ρ 用 Anderson | 5-15% (n_rho_loops 收敛快) | 中 |

## 5. 并行化前景 (Phase 1)

单 eval 0.37 s (BO) → 80 evals × 3 seed = 240 evals, 单线 ~89 s。

| 方案 | 实测/估算 | 总 wall |
|---|---|---|
| 单 process, 单 seed | 0.37 × 80 = 30 s | 30 s |
| joblib q_batch=4 | 4× speedup | 7.5 s × 1 seed |
| + multi-seed M=3 | 12 process | 7.5 s |
| + numba `@njit` simple_solver | (已是 vectorized numpy, 提升 < 5%) | ~7 s |

**Phase 1 是真正的速度杀手锏**, 不是 5.1 的 Python 重构。

## 6. Phase 5.2 建议输出

基于 5.1 数据, 5.2 (架构 review) 重点不在 hot path 速度, 而在:

1. **代码组织**: simple_solver.py 1528 行单文件 → 拆成 5-6 模块 (kernels / BC / sparse / Picard / API)
2. **死代码删**: f-Re 残留 (memory note 提过)、未用 import
3. **重复 kernel 提取**: 多处的 inlet_frac taper, wall_mask, get_wall_masked_velocity 散在 simple_solver / run_calculation / 3D solver
4. **CSR 缓存** (4. 节中等收益): 改 `_solve_pp_sparse_fast` 复用容器; 5-7% 收益
5. **类型 hint** (5.4 任务) 借此 review 一并加

## 7. 数据归档

```
benchmarks/profiling/
├── profile_evaluator.py       — BO inner profile script
├── profile_compute.py         — Shanghai Compute profile script
├── eval_baseline.prof         — pstats binary (BO)
├── eval_baseline_top30.txt    — cumulative top-30 (BO)
├── eval_baseline_tottime.txt  — self-time top-20 (BO)
├── eval_baseline_callees.txt  — call tree (BO)
├── eval_baseline_run.log
├── compute_baseline.prof      — pstats binary (Compute)
├── compute_baseline_top30.txt
├── compute_baseline_tottime.txt
├── compute_baseline_callees.txt
└── compute_baseline_run.log
```

打开 .prof: `python -m pstats benchmarks/profiling/compute_baseline.prof` 或 `pip install snakeviz; snakeviz <file>` (浏览器可视)。

## 8. 验证

| Compute 结果 | 值 |
|---|---|
| Q | 8107.3 W/m |
| dP | 17238.4 Pa |
| 数值 | 与 production_v1 Pareto 同区间 |

baseline 设计 (uniform L=6 t=0.4) 落在已知 Pareto 内, 数据可信。
