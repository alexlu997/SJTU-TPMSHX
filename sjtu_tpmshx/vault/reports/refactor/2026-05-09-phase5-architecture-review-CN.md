# Phase 5.2 — Architecture Review + Refactor List

**日期**: 2026-05-09
**前置**: Phase 5.1 cProfile 已确认 88% 时间在 C 层 (SuperLU + numba), Python 重构无速度收益
**用户决策**: A (架构清理 + type hint + 测试补全, **不动算法/性能**)

## 0. 仓库总览

| 类 | 文件数 | 总行 | 备注 |
|---|---|---|---|
| solvers/ | 22 | 11,580 | 含 simple_solver 1673, solve_full_3d 1742, simple_solver_3d 1528 |
| df_fit/ | 35+ | ~8,000 | 大量探索脚本 (用户已标 6 dead-end) |
| validation/ | 50+ | ~12,000 | 大量 diag/test 脚本 + 旧 csv snapshots |
| ui/ | 27 | 10,181 | ui_builders 2232, panel_vis_3d 1454, optimize_panel 845 |
| runs/ | 11 | ~5,500 | run_calculation 1436, run_calculation_3d 2431 |
| tests/ | 多 | — | 41 test 通过, 但覆盖不全 |

**总 ~40k 行 Python**, 单仓 quasi-monorepo。

## 1. 死代码 / 探索脚本归档清单

[信心: 高] 标 ★ = 用户 memory 明示 dead-end

### 1.1 df_fit/ — 6 死路探索 (★ 全部归档)

```
fit_nu_v2_simple.py            ★ Kim 改造 v2
fit_nu_v3_aggressive.py        ★ Kim 改造 v3
fit_nu_v3_best.py              ★
fit_nu_v3_sa_unified.py        ★ EG-DIP Gompertz
fit_nu_v4_brainstorm.py        ★ v4 探索 (production 是 v4.1, 在 surrogate_v3.py)
fit_nu_cfd4.py                 ★
fit_nu_exp_v3.py               ★
fit_nu_form_sweep.py
fit_nu_single_stream.py        — 仅在 docstring + legacy 引用
fit_df_per_geom.py             ★ 3-param D-F 死路
fit_gyroid_F7.py
fit_physical_formula.py
analyze_nu_v41.py              — v4.1 已 production, 分析脚本可归档
audit_cfd3_excel.py            — Excel audit, 一次性
audit_cfd4.py
audit_excel_columns.py
audit_excel_u_re.py
audit_nu_convention.py
augment_shanghai.py
build_notion_blocks.py
compare_logspace_forms.py
diag_nu_t06_extrap.py          — t=0.6 外推诊断, 已结题
diag_nu_t06_v2.py
dump_xlsx_split.py
dump_xlsx_to_md.py
eval_arms.py                   ★
eval_user_form.py
```

**保留 (production active)**:
- `predict.py` — ConstDF-v1 surrogate (主线)
- `surrogate_v3.py` — RBF dP closure
- `surrogate_domain.py` — domain check
- `residual_correction.py` — 1 validation 引用
- `train_surrogate.py` — surrogate 训练入口
- `load_data.py` — tests + validation

去向: `vault/archive/df_fit_explorations_2026-05/` (按主题分: nu_fits/ + audits/ + dumps/)

### 1.2 validation/ — diag 脚本归档

去向: `vault/archive/validation_diag_2026-05/`

```
diag_3d_field_physics.py       — 3D 调试, 已结
diag_3d_vs_2d_nz1.py
diag_4d_metric_sweep.py
diag_bc_layer_test.py          — Path 0' 调试, 已结 (memory)
diag_columns.py
diag_fullface_baseline.py
diag_kmin_sweep.py             — t=0.6 调试
diag_near_wall_BL.py
diag_noniso_case8.py
diag_rbf_t06.py
dp_1d_compressible.py          — 1D 简化, 已替为完整 SIMPLE
dump_simple_case16.py
nu_error_analysis_shanghai.py
post_q_dual_side.py
posthoc_residual_correction.py — residual 校正死路 (memory)
reverse_fit_KcF.py
smoke_3d_dir_variants.py
smoke_ui_3d_tab.py
sweep_air_air_robustness.py
sweep_m1_falsification.py
sweep_m4_baseline.py
sweep_m4_corrected.py
test_diamond_surrogate.py      — 移 tests/ 或归档
test_heating_symmetry.py
test_refined_vs_uniform.py
test_wall_refined.py           — wall_refine OFF 后无意义
trace_dp_full.py
trace_dp_shanghai_df.py
validate_chi_b_subset.py
viz_wall_refined_flow.py       — wall_refine OFF
water_nu_yan.py                — Nu Yan [6] 已 production
plot_phase2a_attribution.py
plot_shanghai_3d_errors.py
plot_shanghai_q_v41.py
audit_cfd3_excel.py
limit_cases_3d_air_air.py     — 一次性极限 case
mms_3d_air_air.py             — A.2 single-grid (A.3/A.4 是当前)
```

**保留 (production validation)**:
- `validate_shanghai_3d_real.py` ★
- `validate_shanghai_lumped_dual_nu.py` ★ (论文 baseline)
- `validate_shanghai_3d_pp_compare.py` (Phase C SF)
- `verify_pareto_3d.py` (option 1)
- `audit_partial_b_ltne.py` (Phase 2 partial-B)
- `audit_3d_conservation.py`
- `mms_phase_a3_h_refine.py`, `mms_phase_a4_boundary.py`, `phase_c_gci.py` (V&V Standard)
- `phase_b_postprocess.py`, `phase_c_tol_sweep.py` (V&V)
- `cross_check_water_nu.py`
- `nu_error_analysis_shanghai.py` (论文用)
- `test_shanghai_regression.py` (回归)
- `_provenance.py` (元数据 helper)

### 1.3 stale csv / json snapshots

去向: `vault/archive/validation_snapshots_2026-05/` (15+ 个 .csv)

```
shanghai_3d_baseline*.csv (~15 个 — 各 phase 历史 baseline)
m1_falsification_sweep.log
m4_corrected_sweep.json
m4_sweep_fast.json
baseline_before_c1.csv
shanghai_3d_full_ltne_*.csv  (~4 个)
limit_cases_3d_air_air.csv
sweep_air_air_robustness.csv
shanghai_chi_b_subset_v3.log
```

**保留**:
- `validation_results.csv` (canonical baseline)
- `shanghai_3d_pp_compare.csv` (Phase C 当前)
- `shanghai_3d_baseline_phase7_h8_nz10.csv` (production v1)
- `phase_c_gci.csv`, `phase_c_tol_sweep.csv`
- `mms_phase_a3_h_refine.csv`, `mms_phase_a4_boundary.csv`

### 1.4 validation/legacy/ — 已经是 legacy 目录, 整体移动

`validation/legacy/` (已存在) → `vault/archive/validation_legacy_2026-05/`

## 2. solvers/simple_solver.py 1673 行 拆分

[信心: 高]

19 functions/class。结构 (从 grep 输出):

| 行段 | 内容 | 拆向 |
|---|---|---|
| 40-225 | 通用 numba kernel (SOU corr, umag, porous_src) | `simple_solver/kernels.py` |
| 230-403 | momentum sweep kernels (`_sweep_u/v_jit_df`) | `simple_solver/momentum.py` |
| 405-580 | PP sparsity + assembly + spsolve | `simple_solver/sparse_pp.py` |
| 584-650 | correct + mass residual kernels | `simple_solver/correct.py` |
| 653-738 | temperature kernel (legacy single-stream, ★ 检查是否仍用) | `simple_solver/temp.py` 或删 |
| 745-825 | grid helpers (`_aligned_grid`, `build_wall_refined_1d`) | `simple_solver/grid.py` |
| 830-1516 | `SIMPLESolver` class | `simple_solver/core.py` |
| 1521-1562 | `solve_transition_zone` | `simple_solver/__init__.py` |
| 1645-end | `_warmup_jit` | `simple_solver/__init__.py` |

⚠ **numba `@njit` 模块级 cache 能跨文件**: 如果 kernel 之间互相 njit-call, 需保持同模块或显式 import。先实测一个 split, 验证 numba cache 行为。

**风险**: 拆 numba 文件可能丢失 `cache=True` 优势 (首次 import 重编译)。如果发现, 不拆 kernels 这部分, 只拆 SIMPLESolver class。

## 3. simple_solver_3d.py 1528 行 → 同样拆

[信心: 中]

19 functions, 结构类似 2D 但加 z 维度。等 2D 拆分验证通过后, 复制 pattern。

## 4. solve_full_3d.py 1742 行 → 拆

[信心: 中]

LTNE 3-temperature 3D solver, 比 2D 复杂 3 倍。同 simple_solver 拆法:
- `solve_full_3d/kernels.py` — `@njit` GS kernel
- `solve_full_3d/sparse_assembly.py` — 矩阵装配
- `solve_full_3d/api.py` — 公共接口

## 5. run_calculation.py 1436 行 → 拆

[信心: 高]

已是 函数化 ("_parse_inputs", "_build_fields", "_run_solvers", "_store_results", "plot_*")。

| 函数段 | 行 | 拆向 |
|---|---|---|
| `run_calculation_inner` | 60-67 | `runs/run_calculation/__init__.py` |
| `_parse_inputs` | 68-258 | `runs/run_calculation/parse.py` |
| `_build_fields` | 260-587 | `runs/run_calculation/build.py` |
| `_run_solvers` | 588-1157 | `runs/run_calculation/run.py` |
| `_store_results` | 1158-1187 | `runs/run_calculation/store.py` |
| `plot_temperature_3panel` + helpers | 1188-end | `runs/run_calculation/plot.py` |

run_calculation_3d.py 同上 (2431 行).

## 6. main.py 4847 行 → 不动 (Phase 1 已部分重构)

[信心: 中]

main.py 已有 ComputeOrchestrator 抽出 (`refactor-p1-done` tag)。Phase 5 不再动 main.py, 留给 Phase 2-5 of main.py refactor (vault/reports/refactor/2026-05-06-main-py-refactor-plan-CN.md)。

## 7. 重复 kernel 提取

[信心: 中]

| 函数 | 出现位置 | 提取 |
|---|---|---|
| `inlet_frac` 4-cell taper | simple_solver.py + simple_solver_3d.py | `solvers/_common/inlet_frac.py` |
| `get_wall_masked_velocity` 8-cell mask | simple_solver.py + 3D 版 | `solvers/_common/wall_mask.py` |
| Brinkman penalty exponential | 多处散落 | `solvers/_common/brinkman.py` |
| `_porous_src_df` D-F 闭包 | simple_solver.py + fvm_solver.py | 已在 `df_fit/predict.py`, 检查重复 |

⚠ **不强行共享**: 2D/3D 算子物理上不同 (z 项), 共享会造成 if-else 分支增加。仅提取**纯 1D** taper 函数。

## 8. zone_config.py / zone_editor.py — 保留 (deprecation header)

[信心: 高]

UI Compute path 仍用 ZoneConfig (`runs/run_calculation.py:211`)。**不删**。

加 docstring 头:
```python
"""
zone_config.py — DEPRECATED for optimizer use; kept for UI Compute path only.

Optimizer uses solvers.field_param.ContinuousFieldConfig (4×4 + Y-mirror = 16-D).
This module retains the manual zone-table data path used by the UI's "Define
zones" tab. New code should prefer ContinuousFieldConfig.
"""
```

## 9. type hint 全覆盖 (5.4 任务) — 范围

[信心: 高]

**严覆盖** (mypy --strict):
- `solvers/field_param.py` ✓ 已有
- `solvers/df_projection.py`
- `solvers/tpms_calc.py`
- `optimization/evaluator.py` ✓ 已有
- `optimization/optimizer_qnehvi.py`
- `optimization/export_ntop_csv.py`
- `df_fit/predict.py`
- `df_fit/surrogate_v3.py`
- `df_fit/surrogate_domain.py`

**宽松** (允许 `Any` for window/Qt):
- `ui/*.py`
- `runs/*.py`
- `validation/*.py`

**跳过** (numba 不兼容 strict typing):
- `solvers/simple_solver.py` 内 `@njit` kernels
- `solvers/solve_full.py` 同上
- `solvers/simple_solver_3d.py`
- `solvers/solve_full_3d.py`

理由: numba `@njit` 推断类型自身, 显式 hint 反而限制特化路径。

## 10. 测试补全 (5.5 任务) — gap 分析

[信心: 中]

**当前 41 tests** (continuous_field 20, evaluator_sanity 15, export_ntop_csv 6)。

**缺口**:
| 模块 | 当前 | 目标 | 加几 |
|---|---|---|---|
| simple_solver edge cases | 0 直接测 | 8-10 | 边界 BC, 极小 grid, 退化 inlet | 
| simple_solver_3d | 0 | 5-6 | 同 2D 几个核心 |
| solve_full_domain | 0 | 4-5 | 守恒, 1-cell, 单流 | 
| evaluator 3D | 0 | 4 | dim=3 sanity, Lz→0 极限 | 
| field_param | 20 | +5 | manufacturability_penalty 边界 | 
| df_projection | 0 | 4 | extract_dP, override K_cF | 
| tpms_calc | 0 | 5 | air_density Vogel, geometry, adaptive_grid | 
| optimizer_qnehvi | 0 | 3 | hv_plateau, log10 transform, Sobol init |
| ui smoke | 1 | +2 | optimize_panel _gather_cfg, _show_qnehvi_param_dialog |

**目标**: 41 → ~75 tests, 覆盖率从 ~30% → ~55-60% (不追求 70%; UI 测试代价过高)。

## 11. 5.3-5.6 执行顺序

按风险升序:

| 步 | 内容 | 风险 | 估 | 测试通过门 |
|---|---|---|---|---|
| 5.3a | 死代码归档 (1.1, 1.2, 1.3, 1.4) | 低 | 1 h | git mv only, 41/41 pass |
| 5.3b | run_calculation.py 拆分 (5.) | 低 | 1.5 h | 41/41 pass + UI Compute smoke |
| 5.3c | run_calculation_3d.py 拆分 | 低 | 1.5 h | 同 + 3D smoke |
| 5.3d | simple_solver.py 拆分 (2.) | 中 | 2 h | 全 41 + numba cache 验证 |
| 5.3e | simple_solver_3d.py 拆分 | 中 | 1.5 h | 同 |
| 5.3f | solve_full_3d.py 拆分 (4.) | 中 | 1 h | 同 |
| 5.3g | 重复 kernel 提取 (7.) | 低 | 0.5 h | inlet_frac taper 单测 |
| 5.3h | zone_config 加 deprecation header (8.) | 低 | 5 min | 无回归 |
| 5.4 | type hint pass | 低 | 1.5-2 h | mypy 通过 + 41/41 |
| 5.5 | 测试补全 (10.) | 低 | 2-3 h | ~75 tests pass |
| 5.6 | 文档 + commit + tag refactor-p5-done | 低 | 0.5 h | tag |

**总估**: ~12-14 h coding。

## 12. 风险点

| # | 风险 | 缓解 |
|---|---|---|
| 1 | numba `@njit` cache 拆模块后失效 | 5.3d 先做 1 个 split 验证, 失败回退到 "单文件 + 内部分段" |
| 2 | run_calculation 拆分破坏 UI Compute 路径 | 每步跑 UI smoke (启动 → Compute → 关) |
| 3 | 删 df_fit/ 探索脚本影响 SUMMARY.md / CLAUDE.md 引用 | 归档前 grep refs, 更新引用 |
| 4 | 测试覆盖率拉到 55% 时间超出 | 5.5 时间盒 3 h, 不达标也 ship; 缺的 noted in 5.6 |

## 13. 不做项 (确认范围)

- ❌ CSR 缓存 (5-7% 性能, 已选 A 不动算法)
- ❌ ILU + iterative solver
- ❌ multigrid for LTNE GS
- ❌ Anderson acceleration
- ❌ main.py 拆分 (Phase 2+ of refactor-p1, 单独 plan)
- ❌ ui/ 大规模 type hint (window 是 Qt opaque)
- ❌ 删除 zone_config / zone_editor (UI 仍用)

## 14. 下一步

5.3a 死代码归档 (1 h) — 启动。
