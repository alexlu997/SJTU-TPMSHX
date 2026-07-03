# Tasks

## 1. Locks
- [x] 1.1 test_pipeline_reexports.py — full re-export surface (6 modules, ~60 names)
- [x] 1.2 test_io_actions.py — config round-trip / cancel / no-results
- [x] 1.3 test_logutil.py +2 — TS branch, invalid-level fallback

## 2. Hygiene
- [x] 2.1 Env registry sync: +10 flags, 4 stale helper locations fixed
- [x] 2.2 Stale live-looking refs (~9 sites) fixed; provenance narration kept
- [x] 2.3 Dead imports removed (session_presets, run_history, tab_view, ui_builder, run_stack_3d local)
- [x] 2.4 Type annotations: 25 funcs across the 5 small pipeline modules (agent, TYPE_CHECKING-gated)

## 3. Gates
- [x] 3.1 Targeted: logutil+hygiene+main_smoke+io_actions+reexports 46/46; import-DAG/pipeline/reexports 23/23
- [x] 3.2 Golden 2D + 3D bit-identical (PASS both)
- [x] 3.3 Full parallel suite green — 1119 passed / 4 skipped / 1 xpassed in 4:24
