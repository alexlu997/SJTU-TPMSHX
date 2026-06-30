> Plan-level outline. The exact extraction map is finalized after a dedicated read of
> stages_3d.py at execution start (task 1). Hard gate throughout: golden 3D bit-identical.

## 1. Map the extraction (read-only first)

- [ ] 1.1 Read `pipelines/stages_3d.py`; list every top-level helper with its inputs/outputs and whether it is pure (no closure over stage-local state) — only pure, self-contained helpers are safely extractable.
- [ ] 1.2 Cluster them: field-builders / flux-temperature-duty / solver-setup / profiling. Note any `@njit` kernels (must move with decorator + exact signature) and any helper referenced from outside `stages_3d.py` (`git grep "stages_3d\."`).
- [ ] 1.3 Capture the pre-split golden 3D snapshot: `python -u sjtu_tpmshx/runs/_out/_golden_3d.py golden_3d_pre.json` (and 2D).

## 2. Extract, one cluster at a time (bit-identical after each)

- [ ] 2.1 Create `pipelines/stages_3d_fields.py`; move the field-builder cluster verbatim; add imports back into `stages_3d.py`. Run golden 3D → must equal `golden_3d_pre.json`. If drift, revert this cluster.
- [ ] 2.2 Repeat for `pipelines/stages_3d_flux.py` (flux/temperature/duty helpers) → golden check.
- [ ] 2.3 Repeat for `pipelines/stages_3d_solve.py` (solver-setup/outer-loop) → golden check.
- [ ] 2.4 Leave `_run_3d_stack` + the public stage entry in `stages_3d.py` (now thin orchestration).
- [ ] 2.5 After each move, run the fast unit slice touching 3D (`pytest sjtu_tpmshx/tests/ -q -k "3d or stages or shanghai"`).

## 3. Naming pass

- [ ] 3.1 `git grep` for any remaining module/file not lowercase-snake; rename via `git mv` + fix imports (expect few/none — Phase 1 handled the directory cases).

## 4. Verify + close-out

- [ ] 4.1 Golden 2D **and** 3D bit-identical vs the pre-split snapshots (the hard gate).
- [ ] 4.2 Full `pytest sjtu_tpmshx/tests/ -q` green; opt-in `TPMSHX_RUN_SHANGHAI_REGRESSION=1` regression green; Shanghai 3D Δp/Q unchanged vs README headline.
- [ ] 4.3 `numerical-auditor` review of the diff (read-only) to confirm no evaluation-order change slipped in.
- [ ] 4.4 `openspec validate restructure-3-code-layer --strict`.
- [ ] 4.5 Single refactor commit. Defer push/archive until user OKs. **If any golden gate cannot be made bit-identical, abandon the split — do not re-baseline the golden to accommodate a readability refactor.**
