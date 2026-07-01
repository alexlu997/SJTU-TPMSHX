> Plan-level outline. The exact extraction map is finalized after a dedicated read of
> stages_3d.py at execution start (task 1). Hard gate throughout: golden 3D bit-identical.

## 1. Map the extraction (read-only first)

- [x] 1.1 Read `pipelines/stages_3d.py`; list every top-level helper with its inputs/outputs and whether it is pure (no closure over stage-local state) — only pure, self-contained helpers are safely extractable.
- [x] 1.2 Cluster them: field-builders / flux-temperature-duty / solver-setup / profiling. Note any `@njit` kernels (must move with decorator + exact signature) and any helper referenced from outside `stages_3d.py` (`git grep "stages_3d\."`).
- [x] 1.3 Capture the pre-split golden 3D snapshot: `python -u sjtu_tpmshx/runs/_out/_golden_3d.py golden_3d_pre.json` (and 2D).

## 2. Extract, one cluster at a time (bit-identical after each)

- [x] 2.1 **Executed as a single helpers module** (safer than the 3-module sketch): created `pipelines/stages_3d_helpers.py` and moved the **15 numpy-only, global-free** helpers verbatim — index/face/slice math (`_stream_axis`/`_dir_is_reverse`/`_inlet_index`/`_outlet_index`/`_face_slice`/`_real_outlet_slice`), 3D smoothing (`_dilate_one_step_3d`/`_box_smooth_3d`), staggered↔real remap (`_solver_velocity_to_real`/`_solver_staggered_to_real`), `_balance_stream_outflow`, `_build_partial_masks`, and the 3 `_build_chi_B_*` builders. Closure-checked (no extracted fn calls a stay-behind fn) before applying.
- [x] 2.2 The constant/solver-dependent helpers (`_build_zone_fields_3d`, `_resolve_axis_map`, `_build_grid_3d`, `_solver_spacings`) and all stage functions (`_parse`/`_build`/`_run_solvers`/`_finalize`/`_run_3d_stack`) **stay** in `stages_3d.py`, which imports the 15 helpers back. `stages_3d.py` 3244 → 2718 lines (−527).
- [x] 2.3 Verbatim move (no logic edit). 0 `@njit` in this file, so no kernel-signature concern.
- [x] 2.4 `_run_3d_stack` + public stage entry stay in `stages_3d.py`.
- [x] 2.5 Single extraction (not incremental clusters); gated directly by golden 2D+3D below.

## 3. Naming pass

- [x] 3.1 `git grep` for any remaining module/file not lowercase-snake; rename via `git mv` + fix imports (expect few/none — Phase 1 handled the directory cases).

## 4. Verify + close-out

- [x] 4.1 Golden 2D **and** 3D bit-identical vs the pre-split snapshots — **PASS** (empty diff for both). This is the definitive proof the verbatim move changed no evaluation order.
- [~] 4.2 Full `pytest sjtu_tpmshx/tests/ -q` — RUNNING.
- [x] 4.3 Evaluation-order check satisfied by 4.1 (bit-identical golden = no order change); helpers moved verbatim with closure verification.
- [x] 4.4 `openspec validate restructure-3-code-layer --strict`.
- [ ] 4.5 Single refactor commit — pending the 4.2 gate. Push via /ship at end. (Golden stayed bit-identical, so no abandon needed.)
