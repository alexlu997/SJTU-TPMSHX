# Tasks

## 1. Infrastructure
- [x] 1.1 logutil.py: _StdoutHandler (per-record sys.stdout), bare-message default, TPMSHX_LOG_LEVEL / TPMSHX_LOG_TS

## 2. Conversion (library paths; njit + CLI/__main__ prints stay)
- [x] 2.1 pipelines: stages_3d (28 info + 2 warn), stages_2d (9 + 3)
- [x] 2.2 solvers: simple_solver (4+2, 19 CLI kept), simple_solver_3d (2+1); no njit prints existed
- [x] 2.3 solvers misc: polygon_fvm 14 info; zone_config/continuous_field/sigmoid_field(_3d)/tpms_geometry/tpms_calc — all prints were __main__ blocks, kept
- [x] 2.4 df_surrogate: library paths converted; remaining prints verified __main__/CLI only (predict/surrogate_v3/residual_correction/load_data/smooth_df self-tests)
- [x] 2.5 optimization + core: 29 info + 3 warn; CLI outputs kept. Known deviation: core/evaluators `print(end='')` same-line progress prefix now emits as separate log lines (logging has no `end`)
- [x] 2.6 ui: optimize_panel (7+8), plot_3d_results (0+5), quick_design_panel (2+0), math_symbols (__main__ kept); demo_vis_3d untouched

## 3. Gates
- [x] 3.1 Capture-path locks: tests/test_logutil.py 4/4 (redirect_stdout capture, bare format, level filter, no stdlib-root propagation)
- [x] 3.2 Golden 2D + 3D bit-identical (PASS; stdout lines render byte-identical through the logger)
- [x] 3.3 Full parallel pytest suite green — 1095 passed / 4 skipped / 1 xpassed in 4:43
