# Change: maintainability-closeout

## Why

2026-07-03 maintainability survey: the big splits left closeout debt —
the re-export surfaces (~50 names) were locked only incidentally; the
self-declared central TPMSHX_* env registry was missing 10 flags (4
undocumented anywhere); ~10 comments still pointed at deleted files /
stale line numbers as if live; dead imports from the splits; logutil's
TS/level-fallback branches untested; io_actions (config save/load) 0%
tested; the small cfg-boundary pipeline modules had 0/25 annotated
functions.

## What Changes

- `tests/test_pipeline_reexports.py`: locks the FULL re-export surface of
  stages_2d/stages_3d/simple_solver/simple_solver_3d/ltne_energy_3d/
  builders_canvas (~60 names, parameterized).
- `tests/test_io_actions.py`: save/load config JSON round-trip, cancel
  no-op, no-results export dialog.
- `tests/test_logutil.py` +2: TPMSHX_LOG_TS formatter branch, invalid
  TPMSHX_LOG_LEVEL → INFO fallback.
- Env registry (`domain/compute_config.py` docstring): +10 missing flags
  (DF_METHOD, DF_OVERRIDES, ASYM_KAPPA, NUM_THREADS, SCO2_COMPRESSIBLE,
  MAX_CELLS_3D, BUILD_S_MAX/LX_MAX, 2D_MASSFLUX, LOG_LEVEL/LOG_TS); 4
  stale helper locations fixed (stages_3d → run_stack_3d).
- Stale live-looking refs fixed (~9 sites): run_calculation*.py pointers
  in ui/builders_fluids, ui/builders_domain, core/evaluators, .gitignore,
  ltne_energy(+_3d), solve_2d, run_stack_3d. "Moved out of / formerly"
  provenance narration kept as-is.
- Dead imports removed: session_presets (json, os), run_history/tab_view/
  ui_builder (Qt), run_stack_3d (`nu_from_Re` local).
- Type annotations: 25 functions across _stage_common / grid_3d / flux_3d
  / stages_2d / stages_3d (TYPE_CHECKING-gated imports, no cycles).

## Impact

Comment/test/annotation-only + import removals — no behavior change.
Golden 2D/3D must stay bit-identical (ltne_energy files were comment-
touched → invariant hook demands the check).
