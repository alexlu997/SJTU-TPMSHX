# Tasks

## 1. Levers
- [x] 1.1 tpms_geometry lru: _compute_raw 64→2048, compute_geometry 1024→4096
- [x] 1.2 _build_hv_local_2d uniform path vectorized (2D port of 3D perf-B1; zoned per-cell path untouched)
- [x] 1.3 2D A/B SIMPLE solves threaded (2D port of _run_two_simple_parallel; errors re-raised after both join)
- [x] 1.4 BO loky inner_max_num_threads = cores // n_jobs (was 1)

## 2. Deferred (recorded in proposal — re-baseline decisions, NOT this change)
- [x] 2.1 2D warm-start / 2D PP-AMG / momentum-gate default / 3D re-solve threading / _RB_ENERGY_2D — documented with rationale

## 3. Gates
- [x] 3.1 Golden 2D + 3D bit-identical (PASS both — the decisive proof for 1.2 + 1.3)
- [x] 3.2 Full parallel suite green — 1119 passed / 4 skipped / 1 xpassed in 4:27
- [x] 3.3 2D wall-clock spot-check: golden-2D --check = 9.1 s post-change (two full cfg solves incl. import/JIT; threaded A/B + vectorized hv live on that path). Stash-based before/after aborted — stashing mid-gate would have poisoned the running suite.
