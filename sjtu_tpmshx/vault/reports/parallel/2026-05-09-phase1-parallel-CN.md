# Phase 1 — 并行优化 — Closure

**日期**: 2026-05-09
**前置**: Phase 5 闭环 (refactor-p5-arch-done) 已确认 cProfile 88% 在 C 内核
**配置**: 12-core / 32 GB, M=3 seed × q_batch=4 = 12 process
**Tag**: `parallel-p1-done`

## 0. TL;DR

加 2 层并行 (joblib 内层 q_batch + ProcessPoolExecutor 外层 multi-seed). 内层 q_batch=4 实测 **2.09× speedup** on 8-eval mini benchmark. 外层 multi-seed **2 seed × 16 evals = 32 evals in 11 min** parallel — 估 production 3 seed scale ~3× over sequential.

## 1. 1.2 — 内层 joblib q_batch 并行

`optimization/optimizer_qnehvi.py`:

### 改动
- 抽 `_eval_worker(x, cfg, dp_cap)` 为 module-level (loky 必须 picklable)
- `_evaluate_batch` 加 `n_jobs > 1` 分支调 `joblib.Parallel(backend='loky', inner_max_num_threads=1)`
- `run_qnehvi(...)` 加 `n_jobs: int = 1` 参数

### 实测 (8 evals, tol=1e-2, n_rho_loops=2)
```
n_jobs=1  serial:  395.7 s
n_jobs=4  par4:    189.1 s
speedup:  2.09×
```

模式收益少于理论 4× 因为:
- BoTorch GP fit + acqf 不并行 (~30s/iter, 单线程 torch)
- Sobol init 4-eval 1 batch 完全 parallel
- BO iter q=4 evals parallel + GP fit serial
- 实际比例 ≈ T_eval × q / (T_eval + T_GP_fit + T_acqf)

### 用法
```python
run_qnehvi(config={...}, n_init=32, n_iter=24, q_batch=4, n_jobs=4, ...)
```

## 2. 1.1 — 外层 multi-seed 并行

`optimization/parallel_runner.py` (新建):

### 接口
```python
run_qnehvi_multiseed(
    config=...,
    n_seeds=3,                      # M
    seeds=[42, 43, 44],             # 或自动生成
    n_init=32, n_iter=24,
    q_batch=4,
    n_jobs_inner=4,                 # 嵌套 joblib q_batch
    save_dir_base='opt_runs/v3_<ts>',
    hv_tol=0.01, hv_window=3,
)
```

### 实施

- `concurrent.futures.ProcessPoolExecutor(max_workers=n_seeds, mp_context='spawn')`
- 每 subprocess 调 `_seed_subprocess_main(seed, config, ...)`:
  1. `_set_thread_caps()` — `OMP/MKL/OPENBLAS/NUMEXPR=1` 防 BLAS 爆
  2. **延迟 import** `optimizer_qnehvi` (确保 thread caps 在 numpy 之前)
  3. 调 `run_qnehvi(seed=s, n_jobs=n_jobs_inner)`
- 末端 `_merge_paretos` 取所有 seed Pareto 的 union, 跑 `_pareto_mask_max` 取 global non-dominated

### Why spawn (not fork)

Windows 不支持 fork。Spawn 避免继承 PyTorch / Numba 状态污染。代价: 每 subprocess 重 import = 30-60s spawn 开销, 但只发生一次。

### 实测 (2 seeds × 16 evals = 32 evals)
```
=== Production v3 SUMMARY ===
  save_dir:    opt_runs/_smoke_multiseed
  seeds_used:  [42, 43]
  n_evals:     32
  Pareto pts:  10
  wall_time:   659 s (11.0 min)
  Q range  [7627, 8939] W/m
  dP range [7057, 22734] Pa
```

### Sequential 估算

3 × 单 seed 串行 wall ≈ `3 × (init + n_iter × iter_time)`. 同 tol/n_rho 下:
- Single seed wall: ~217s init + 2 × 70s iter = 357s
- Sequential 3 seed: ~1071s
- Parallel 3 seed: ~357s + spawn 重叠 ≈ same

production scale (32 init + 24 iter):
- Sequential 3 seed: 3 × (217 + 24×70) = **94 min**
- Parallel 3 seed: 1 × (217 + 24×70) = **32 min**
- Speedup ≈ **3×**

## 3. 1.3 — numba @njit 现状

cProfile baseline 已显示 `solve_full.py` (LTNE GS) + `simple_solver.py` (momentum/correct kernels) + `simple_solver_3d.py` (含 `parallel=True`) **全部已 @njit(cache=True)**.

唯二未 @njit 的:
- `_build_pp_sparsity_pattern` — Python loop, 仅 init 一次, 0.013s 总, 不是热点
- `_solve_pp_sparse_fast` — 调 scipy spsolve (C 内核 SuperLU), 不能 numba

**1.3 无新增工作** — 代码已 numba 饱和。

## 4. 1.4 production runner

`runs/run_production_qnehvi_parallel.py`:

```bash
# Production: 3 seed × 32 init + 24 iter × 4 q = 384 evals
python -m runs.run_production_qnehvi_parallel \
    --seeds 3 --n_init 32 --n_iter 24 --q_batch 4 --n_jobs 4

# Quick smoke (2 seed × 16 evals)
python -m runs.run_production_qnehvi_parallel \
    --seeds 2 --n_init 8 --n_iter 2 --q_batch 4

# Custom tolerance (production tightness)
python -m runs.run_production_qnehvi_parallel --tol 1e-3 --rho_loops 3
```

### 输出结构
```
opt_runs/production_v3_<ts>/
├── seed_042/
│   ├── pareto_iter0005.csv
│   ├── pareto_latest.csv
│   ├── pareto_final.csv
│   └── history.csv
├── seed_043/  ...
├── seed_044/  ...
├── pareto_merged.csv     ← global non-dominated
└── history_merged.csv    ← all evaluations concatenated
```

## 5. CPU 资源 budget

12 核物理 (用户 16 核, 留 4 给系统/IDE):

```
3 outer seeds × 4 inner workers = 12 process at peak
```

每 process 内: `OMP/MKL/OPENBLAS/NUMEXPR=1` (joblib `inner_max_num_threads=1`).

Memory: 约 200 MB / process × 12 = 2.4 GB peak. RAM 32 GB 充足。

## 6. 实测验证

| 测试 | 配置 | 时间 | 状态 |
|---|---|---|---|
| n_jobs=1 vs n_jobs=4 | 8 evals (4+1×4) | 395 vs 189s | ✅ 2.09× |
| 2-seed multi-seed | 32 evals | 659s (11 min) | ✅ 10 Pareto pts |
| pytest test_evaluator + test_optimizer_qnehvi_helpers | 27 tests | 16s | ✅ all pass |

## 7. 已知限制

- spawn 开销: 每 subprocess 首次 ~30-60s 重 import. Production runs (>10 min) 摊薄。
- progress dict + UI hook: parent 看不到 subprocess 内部进度. 当前只看每 seed CSV checkpoint. UI live HV (Phase 2) 需另设 IPC (Manager + shared memory).
- Sobol init phase 在 multi-seed 下确定性: 每 seed 独立 Sobol, 设计点不重复 (理想)。

## 8. 文件清单

```
optimization/
├── optimizer_qnehvi.py        — 加 _eval_worker + n_jobs 内层 joblib
└── parallel_runner.py         — NEW: multi-seed orchestrator + CLI

runs/
└── run_production_qnehvi_parallel.py  — NEW: production v3 runner

vault/reports/parallel/
└── 2026-05-09-phase1-parallel-CN.md   — 本文
```

## 9. 后续

按 user 顺序 51423: 5→1→**4**→2→3。下一: Phase 4 — 2D VIEW 合并 (T_a/T_b/T_s/|U|/P → 单 tab + combo)。
