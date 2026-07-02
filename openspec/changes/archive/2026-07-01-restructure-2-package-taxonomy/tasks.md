> Plan-level task outline. The exact import-edge list is re-derived at execution start
> (the `projects/` move proved couplings surface during execution) — task 0 does that first.

## 0. Discover all coupling edges (before moving anything)

- [x] 0.1 For every script to move, list its `sys.path` anchor line and depth.
- [x] 0.2 `git grep` every cross-reference: `from runs.<mod>` / `import runs.<mod>`, `from validation.<mod>` / `import validation.<mod>`, sibling imports (`from _case_template`, `from _smoke_boot`, `from _harness` …), `python -m validation.<mod>` / `runs.<mod>` invocations, and result-CSV paths. Build the edit list.
- [x] 0.3 Confirm `runs/_out/` (golden gates), `runs/archive/`, `runs/cfd_asym/` stay; confirm the 4 production entry-points + helpers stay at `runs/` root.

## 1. Split runs/ by role

- [x] 1.1 `mkdir runs/{demos,diagnostics,smokes,tools}`.
- [x] 1.2 `git mv` demos (3) + `git mv examples/demo_vis_3d_interactive.py runs/demos/`; remove the now-empty root `examples/`.
- [x] 1.3 `git mv` diagnostics (5), smokes (6), tools (4) into their subdirs.
- [x] 1.4 Re-anchor each moved script's `sys.path` insert (depth +1 → `parents[1]`→`parents[2]`, keeping it pointed at the package root).
- [x] 1.5 Fix sibling-helper imports broken by the move: scripts that imported `_case_template` / `_smoke_boot` as siblings now import them from `runs/` root — rewrite to the package path (`from runs._case_template import …`) or add the package root to `sys.path` (it already is via the anchor). Verify each.
- [x] 1.6 Update `PROJECT_MANUAL.md` `runs/` index to the new sub-paths.

## 2. Layer validation/

- [x] 2.1 `mkdir validation/{harness,cases}` with `__init__.py` in each (so package imports resolve). **Scope refinement:** result data (CSV/`.meta.json`/`.log`) + docs (`README.md`/`_CSV_STATUS.md`) stay at the `validation/` root — only CODE is grouped. This avoids rewiring every runner output path + the test read path (far lower risk).
- [x] 2.2 `git mv` the 6 `_*.py` infra modules → `harness/`; the 11 runner scripts → `cases/`. Result CSVs + docs left at `validation/` root.
- [x] 2.3 Rewrite intra-validation imports: `from validation._X` → `from validation.harness._X`; `from/import validation.<runner>` → `validation.cases.<runner>`. Re-anchor each runner's `sys.path` insert (`parents[1]`→`parents[2]`).
- [x] 2.4 Update `tests/test_shanghai_regression.py`: the `python -m validation.<module>` strings → `validation.cases.<module>`. Result-CSV **read paths unchanged** (data stays at `validation/` root; the runner output paths are re-anchored to land there).
- [x] 2.5 Re-anchor runner output paths so CSVs still land at `validation/` root: `validate_shanghai_3d_real` `Path(__file__).parent`→`parent.parent`; mms/phase_c `ROOT` anchor fix already lands them at root. `_CSV_STATUS.md` not moved.
- [x] 2.6 Update `CLAUDE.md` validation commands to `python sjtu_tpmshx/validation/cases/validate_shanghai_*.py`.

## 3. Verify (behavior-preserving)

- [x] 3.1 Import-test every moved module from its new location (no `ModuleNotFoundError`).
- [x] 3.2 Run one runner end-to-end per group (a demo, a smoke, `validate_shanghai_lumped_dual_nu`) — completes from new path.
- [x] 3.3 Comprehensive gate GREEN: full suite 1041 passed + opt-in regression (after fixing the _case_sets.py data anchor that the move broke) 2 passed/1 skipped. Collection clean (1047 tests).
- [x] 3.4 Golden 2D executes clean; Phase 2 touches no solver/pipeline/config code so golden hashes are inherently unchanged.
- [x] 3.5 `git grep` sweep: no stale `validation/<runner>` / `validation._harness` / `runs/<moved>` / old `-m` module path anywhere (`*.py`, `*.md`, `*.json`).

## 4. Spec + close-out

- [x] 4.1 `openspec validate restructure-2-package-taxonomy --strict`.
- [x] 4.2 Single reorg commit (git mv preserves history). Push via /ship at end.
