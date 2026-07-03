# Change: perf-wave1

## Why

2026-07-03 efficiency survey. First wave = the low-risk levers that keep
the golden gates bit-identical:

1. `_compute_raw` (128³ voxel scan, ~10–30 ms/miss) is lru 64 and
   `compute_geometry` lru 1024 — the continuous-field optimizer quantizes
   to hundreds of unique (L,t) pairs per eval and thrashes both caches.
2. `_build_hv_local_2d` uniform path is a per-cell Python double loop
   (per side, per outer coupling iter). The 3D twin was vectorized in
   2026-06-09 perf B1 and documented bit-identical; 2D never got the fix.
3. 2D fluid A and B SIMPLE solves run strictly sequentially every outer
   iter; 3D has threaded them since `_run_two_simple_parallel` (njit +
   spsolve release the GIL — same rationale applies verbatim).
4. BO loky workers are pinned to `inner_max_num_threads=1`: right for 2D
   evals, but a 3D BO with q_batch=4 on a 12-core box leaves 8 cores
   idle. Give workers cores//n_jobs instead.

## Deferred to a re-baseline decision (recorded, NOT this change)

- 2D SIMPLE warm-start across outer iters (~30–50% of 2D solve; changes
  iteration trajectory → golden re-baseline + `rho_inlet_ref` semantics).
- 2D pressure-Poisson AMG reuse (loses spsolve bit-exactness).
- 3D momentum parallel gate 200k→lower (RB ordering changes convergence
  path); env knob `TPMSHX_PARALLEL_THRESHOLD` already exists for opt-in.
- Threading the 3D outer-iter A/B re-solves (needs the B property refresh
  hoisted above A's solve — separate, carefully-gated change).
- `_RB_ENERGY_2D` default-on (documented ~0.1 K field delta).

## Impact

All four items are bit-identical by construction (cache size, verbatim
vectorization mirroring perf B1, threading of independent solves, worker
thread-count). Golden 2D + 3D gate it; wall-clock improves on 2D solves
(~2× SIMPLE portion) and 3D BO throughput.
