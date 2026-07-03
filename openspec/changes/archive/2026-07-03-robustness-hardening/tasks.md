# Tasks

## 1. Input gates
- [x] 1.1 ComputeConfig.validate() + from_dict/from_json wiring
- [x] 1.2 _validate_required_widgets finite+positive (temp exempt from raw-text sign)
- [x] 1.3 blur handler "Must be finite"
- [x] 1.4 validate_geometry wired into _preflight_grid; core-field parse failures abort preflight; T_s_init fix + range

## 2. Convergence verdict
- [x] 2.1 ComputeResult.converged + solver_converged in 2D/3D raw dicts (3D = last-outer LTNE semantics)
- [x] 2.2 write_result warning prepend + 诊断摘要 "收敛" row

## 3. Resource / lifecycle / persistence
- [x] 3.1 _run_3d_stack cell cap (TPMSHX_MAX_CELLS_3D / cfg override) + UI RAM estimate in large-grid dialog
- [x] 3.2 closeEvent waitForDone(3000) after cooperative cancel
- [x] 3.3 session + preset corrupt-JSON quarantine (.corrupt-<ts>)

## 4. Gates
- [x] 4.1 tests/test_robustness_gates.py 13/13
- [x] 4.2 Targeted affected tests 46/46 (compute_config/review_fixes/closure_guards/main_smoke)
- [x] 4.3 Golden 2D + 3D bit-identical
- [x] 4.4 Full parallel suite green — 1108 passed / 4 skipped / 1 xpassed in 4:16
