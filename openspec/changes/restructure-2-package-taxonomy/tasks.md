> Plan-level task outline. The exact import-edge list is re-derived at execution start
> (the `projects/` move proved couplings surface during execution) — task 0 does that first.

## 0. Discover all coupling edges (before moving anything)

- [ ] 0.1 For every script to move, list its `sys.path` anchor line and depth.
- [ ] 0.2 `git grep` every cross-reference: `from runs.<mod>` / `import runs.<mod>`, `from validation.<mod>` / `import validation.<mod>`, sibling imports (`from _case_template`, `from _smoke_boot`, `from _harness` …), `python -m validation.<mod>` / `runs.<mod>` invocations, and result-CSV paths. Build the edit list.
- [ ] 0.3 Confirm `runs/_out/` (golden gates), `runs/archive/`, `runs/cfd_asym/` stay; confirm the 4 production entry-points + helpers stay at `runs/` root.

## 1. Split runs/ by role

- [ ] 1.1 `mkdir runs/{demos,diagnostics,smokes,tools}`.
- [ ] 1.2 `git mv` demos (3) + `git mv examples/demo_vis_3d_interactive.py runs/demos/`; remove the now-empty root `examples/`.
- [ ] 1.3 `git mv` diagnostics (5), smokes (6), tools (4) into their subdirs.
- [ ] 1.4 Re-anchor each moved script's `sys.path` insert (depth +1 → `parents[1]`→`parents[2]`, keeping it pointed at the package root).
- [ ] 1.5 Fix sibling-helper imports broken by the move: scripts that imported `_case_template` / `_smoke_boot` as siblings now import them from `runs/` root — rewrite to the package path (`from runs._case_template import …`) or add the package root to `sys.path` (it already is via the anchor). Verify each.
- [ ] 1.6 Update `PROJECT_MANUAL.md` `runs/` index to the new sub-paths.

## 2. Layer validation/

- [ ] 2.1 `mkdir validation/{harness,cases,data/results,docs}` with `__init__.py` in `harness/` and `cases/` (so package imports resolve).
- [ ] 2.2 `git mv` the 6 `_*.py` infra modules → `harness/`; the runner scripts → `cases/`; result CSV + `.meta.json` + `.log` → `data/results/`; `README.md` + `_CSV_STATUS.md` → `docs/`.
- [ ] 2.3 Rewrite intra-validation imports: `from validation._harness` → `from validation.harness._harness` (and `_metrics`/`_case_sets`/`_mms_driver`/`_order_fit`/`_provenance`). Re-anchor each runner's `sys.path` insert.
- [ ] 2.4 Update `tests/test_shanghai_regression.py`: the `python -m validation.<module>` module strings → `validation.cases.<module>`; the result-CSV read paths → `validation/data/results/`.
- [ ] 2.5 Update any result-CSV write path inside the runners (e.g. `--suffix` output landing) to `data/results/`, and the `_CSV_STATUS.md` location note.
- [ ] 2.6 Update `CLAUDE.md` validation commands to `python sjtu_tpmshx/validation/cases/validate_shanghai_*.py`.

## 3. Verify (behavior-preserving)

- [ ] 3.1 Import-test every moved module from its new location (no `ModuleNotFoundError`).
- [ ] 3.2 Run one runner end-to-end per group (a demo, a smoke, `validate_shanghai_lumped_dual_nu`) — completes from new path.
- [ ] 3.3 `pytest sjtu_tpmshx/tests/ -q` green; then the opt-in `TPMSHX_RUN_SHANGHAI_REGRESSION=1 pytest sjtu_tpmshx/tests/test_shanghai_regression.py -q` green (proves the `-m validation.cases.*` rewrite + result paths).
- [ ] 3.4 Golden 2D/3D bit-identical.
- [ ] 3.5 `git grep` sweep: no stale `validation/<runner>` / `validation._harness` / `runs/<moved>` / old `-m` module path anywhere (`*.py`, `*.md`, `*.json`).

## 4. Spec + close-out

- [ ] 4.1 `openspec validate restructure-2-package-taxonomy --strict`.
- [ ] 4.2 Single reorg commit (`git mv` preserves history). Defer push/archive until user OKs.
