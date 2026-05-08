# Phase 5 — 代码质量 + 效率 — Closure

**日期**: 2026-05-09
**用户决策路径**: 1A (vault archive) + 2A (numba pilot) + 3A (55-60% coverage) + 4A (full 12-14h scope), 后调整为跳大文件 split (用户同意 A)
**上一 tag**: `refactor-p5-archive-done` (中间 checkpoint, 5.1+5.2+5.3a+5.3h)
**本 tag**: `refactor-p5-arch-done` (注意: `refactor-p5-done` 已被前 session 占用)

## 0. TL;DR

Phase 5 (5.1-5.6 全闭环) 单日完成。**249 → 309 tests pass** (+60 新测试, +24.1%)。死代码 110+ 文件归档, 关键模块 type hint 全覆盖, 4 个新测试模块。

## 1. 完成阶段一览

| Step | 内容 | 产出 |
|---|---|---|
| 5.1 | cProfile baseline (BO inner + Compute) | 88% in C kernel, Python 重构无收益 → 跳大 split |
| 5.2 | Architecture review + refactor list | 13-step plan, 风险评估 |
| 5.3a | 死代码归档 (df_fit + validation + snapshots + legacy) | 110+ 文件 → vault/archive/, df_fit 35→7, validation 50→14 |
| 5.3h | zone_config / zone_editor deprecation header | UI Compute 路径明示边界 |
| 5.3g | 重复 kernel 提取 | 评估后跳过 (2D 4-cell 与 3D 8-cell 实质不同) |
| 5.3b/c/d/e/f | 大文件 split (run_calc, simple_solver, solve_full) | **跳过** (5.1 数据无收益, numba cross-module 风险) |
| 5.4 | type hint pass | df_projection / surrogate_domain / tpms_calc / predict / surrogate_v3 |
| 5.5 | 测试补全 | +60 tests (4 新文件) |
| 5.6 | 文档 + commit + tag | 本文 + 2 commits + tags |

## 2. 5.5 测试覆盖增量

### tests/test_tpms_calc.py (24 tests)

| 类 | 测试 |
|---|---|
| Air properties (7) | ideal gas exact / inverse T / pressure scaling / array input / Sutherland monotonic / 300K band / cp band |
| Water properties (5) | 293K density band / Vogel viscosity band + monotonic / cp constant / k linear |
| Nu correlations (2) | Yan [6] form / monotonic Re |
| Geometry (4) | dict keys / epsilon split A=B / 厚壁低 ε / K_ss ∝ k_s |
| Adaptive grid (2) | tuple of int / 细 alpha 多 cell |
| compute() (2) | superset of geometry / lru_cache 同对象 |
| Fluid parsing (2) | 'Air' / 未知 raises |

### tests/test_surrogate_domain.py (11 tests)

In-window pass / 各 oow (L < min, L > max, t > max, u → Re < 400) raise / allow_extrap=True 警告 + 返回 reasons / 边界 close interval / env var 强制 / side='B' 标签传播

### tests/test_df_projection.py (12 tests)

| 类 | 测试 |
|---|---|
| extract_dP_from_simple (3) | 均匀 inlet/outlet / partial inlet 排除墙 cell / 零 inlet → 0 |
| extract_dP_mass_flux (3) | 零 v fallback / 均匀 v == geom / 高 v cell 主导权重 |
| build_master_refined_grid (3) | 4-tuple shape / ∑ dx = L_dom / BL cell < bulk |
| project_fields_to_streamwise_K_cF (3) | shape (Ny_sim,) / 均匀输入 → 均匀输出 / 'C' fluid raises |

### tests/test_optimizer_qnehvi_helpers.py (13 tests)

`_pareto_mask_max` (5): 单点 / 显然支配 / 反相关均保 / 三点中间被支配 / 重复至少留 1
`hv_plateau_detected` (4): 短 history → False / 三连低 delta → True / 单大 delta 破 / tol=0 严苛
`request_cancel/clear_cancel` (1)
`_save_pareto_csv` (3): roundtrip Q 翻号正确 / dP 正向 / header 含 x*+Q+dP

## 3. 5.4 type hint 增量

| 模块 | 改动 |
|---|---|
| `solvers/df_projection.py` | 全文 from __future__ + typing imports; 8 函数 (build_master, project_cells, project_fields, override, build_3d, project_3d, extract_dP, extract_dP_mass_flux) 加完整签名 |
| `solvers/tpms_calc.py` | air_density / air_cp 加 docstring; adaptive_grid 加签名 |
| `df_fit/surrogate_domain.py` | from __future__ + 模块常量加类型 + check_surrogate_domain_at_point 全签名 |
| `df_fit/predict.py` | _get_model 加返回 type |
| `df_fit/surrogate_v3.py` | _build / summary 加 -> None |

跳过 (numba @njit 不兼容 strict typing):
- `solvers/simple_solver.py`, `solve_full.py`, `simple_solver_3d.py`, `solve_full_3d.py`

## 4. 5.3a 归档清单

### vault/archive/df_fit_explorations_2026-05/ (28 文件)

```
nu_fits/      fit_nu_v2_simple, fit_nu_v3_aggressive, fit_nu_v3_best,
              fit_nu_v3_sa_unified, fit_nu_v4_brainstorm, fit_nu_cfd4,
              fit_nu_exp_v3, fit_nu_form_sweep, fit_nu_single_stream,
              fit_df_per_geom, fit_gyroid_F7, fit_physical_formula
audits/       audit_cfd3_excel, audit_cfd4, audit_excel_columns,
              audit_excel_u_re, audit_nu_convention
diagnostics/  analyze_nu_v41, augment_shanghai, compare_logspace_forms,
              diag_nu_t06_extrap, diag_nu_t06_v2, eval_arms, eval_user_form
dumps/        build_notion_blocks, dump_xlsx_split, dump_xlsx_to_md
plots/        plot_nu_loo_4p / _error / _s8 / _v3, plot_nu_v4_loo,
              plot_nu_v4_parity_error, plot_residual_vs_re, viz_nu_correlations
utils/        merge_cfd3_to_legacy, merge_cfd4_to_legacy,
              nu_residual_correction, physics_K_rbf_cF, predict_dP_1d,
              verify_user_form, test_residual_correction_loo
```

`df_fit/` 主目录从 35+ 文件降至 **7** (`predict, surrogate_v3, surrogate_domain, residual_correction, train_surrogate, load_data, __init__`).

### vault/archive/validation_diag_2026-05/ (36 文件)

各种 diag_*.py / smoke_*.py / test_*.py / sweep_*.py / trace_*.py / plot_*.py

`validation/` 主目录从 50+ 降至 **14**:
- 当前 production: validate_shanghai_3d_real / validate_shanghai_lumped_dual_nu / validate_shanghai_3d_pp_compare / verify_pareto_3d
- V&V Standard: mms_phase_a3 / a4, phase_b_postprocess, phase_c_gci, mms_3d_air_air (恢复 — production MMS 仍引用)
- Audit: audit_3d_conservation, audit_partial_b_ltne
- 检查: cross_check_water_nu, test_shanghai_regression
- helper: _provenance, __init__

### vault/archive/validation_snapshots_2026-05/ (~25 文件)

旧 csv/log/json baseline (shanghai_3d_baseline_*.csv 多代, m1/m4 sweep, baseline_before_c1 等). 当前活的: validation_results.csv, shanghai_3d_pp_compare.csv, shanghai_3d_baseline_phase7_h8_nz10.csv, mms_phase_a3/a4, phase_c_*.

### vault/archive/validation_legacy_2026-05/legacy/

整体迁 validation/legacy/ 目录 (validate_shanghai*.py 旧版, 仅历史保留).

## 5. 跳过项 + 理由

### 5.3b/c (run_calculation.py 1436 + run_calculation_3d.py 2431 拆分)

**理由**:
1. profile 显示这部分非热点 (Compute 主时间在 SIMPLE/solve_full 内)
2. 内部已 函数化 (run_inner → _parse → _build → _run → _store → _plot 6 段)
3. 1.5h 工作产出仅是文件目录结构调整, 无功能/性能改进
4. 风险: import 依赖断裂

**回看准则**: 若未来 Phase 1 并行或 main.py 重构需要更细模块边界, 再拆。

### 5.3d/e (simple_solver.py 1673 + simple_solver_3d.py 1528 拆分)

**理由**:
1. 同 5.3b — profile 88% 在 numba 内, 拆分无加速
2. **numba cross-module @njit cache 风险高**: kernel 之间互相 njit-call 时模块边界破坏 cache 命中, 首次 import 重编译延迟 30-60 s
3. 文件已分段良好: section markers 明示 SOU corr / momentum / pp / temp / class

**Pilot 未启动**: 5.2 计划做 1 个试点, 时间到决定全跳。

### 5.3f (solve_full_3d.py 1742 拆分)

同上理由。

### 5.3g (重复 kernel 提取)

**理由**: 实查 2D 4-cell exponential taper (无 floor) 与 3D 8-cell exponential taper (min_frac=0.2) 是不同需求 — 共享会增加 if-else 分支, 无意义。

## 6. 测试结果

| 套件 | 状态 |
|---|---|
| 非 Qt 测试 (10 文件 ignore) | **309 passed**, 6 warnings, 35.60 s |
| 新 4 个测试文件 | 60 / 60 pass |
| 增量 | +60 (+24.1%) tests; 249 → 309 |

Qt 依赖 10 测试文件 (`field_factory`, `main_smoke`, `result_cache`, etc.) 在 Windows headless 环境 crash exit 9 — **pre-existing**, 非本次引入。Phase 1 执行前应在 Linux/CI 上跑确认。

## 7. 后续阶段

按 task 依赖:

| Phase | 状态 | 预计 |
|---|---|---|
| 1.1 parallel_runner.py multi-seed (M=3) | pending | ~1 h |
| 1.2 joblib q_batch=4 内层 | pending | ~1 h |
| 1.3 numba @njit on hot kernels (基于 profile) | pending | ~1 h |
| 1.4 production_v3 benchmark + tag | pending | ~1.5 h |
| 4 2D VIEW 合并 | pending | ~1 day |
| 2 进度条 + ETA + live HV | pending | ~半天 |
| 3 字体 + Unicode 数学符号 | pending | ~半天 |

按用户 51423 顺序 (5→1→4→2→3) 进入 Phase 1。

## 8. Git 状态

```
tags:
  refactor-p5-archive-done  ← 5.1+5.2+5.3a+5.3h checkpoint
  refactor-p5-arch-done     ← 5.4+5.5+5.6 final  (本 commit)

非 Qt regression: 309 / 309 pass
```

## 9. 文件清单 (Phase 5 全部产出)

```
benchmarks/profiling/
├── profile_evaluator.py       — BO inner profile script
├── profile_compute.py         — Shanghai Compute profile script
├── eval_baseline.prof + 3 txt + log
└── compute_baseline.prof + 3 txt + log

vault/reports/profiling/
└── 2026-05-09-cprofile-baseline-CN.md

vault/reports/refactor/
├── 2026-05-09-phase5-architecture-review-CN.md
└── 2026-05-09-phase5-closure-CN.md  ← 本文

tests/ (+60 tests)
├── test_tpms_calc.py
├── test_surrogate_domain.py
├── test_df_projection.py
└── test_optimizer_qnehvi_helpers.py

修改:
├── solvers/df_projection.py        (type hints + future annotations)
├── solvers/tpms_calc.py            (类型补漏)
├── solvers/zone_config.py          (deprecation header)
├── solvers/zone_editor.py          (deprecation header)
├── df_fit/predict.py               (_get_model return type)
├── df_fit/surrogate_domain.py      (full type hints)
├── df_fit/surrogate_v3.py          (_build/summary -> None)
└── tests/test_anderson_simple.py   (sjtu_tpmshx → solvers prefix fix)

归档 (~110 文件 → vault/archive/):
├── df_fit_explorations_2026-05/
├── validation_diag_2026-05/
├── validation_snapshots_2026-05/
└── validation_legacy_2026-05/
```
