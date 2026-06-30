# Design — Phase 2: package-internal taxonomy

## Context

`runs/` (27 flat scripts) and `validation/` (harness + runners + data + docs, flat) are the two in-package junk drawers. The boundary audit confirmed imports are already cleanly layered, so this is **grouping by role**, plus repairing the references the moves break. The method is the one proven by the `projects/` consolidation: discover every coupling edge first, move with `git mv`, re-anchor `sys.path`, rewrite broken package/sibling imports, update CLAUDE/test invocations, then import-test + full pytest + golden.

## Key decisions

### D1 — What stays at `runs/` root
Production entry-points (`run_*`, `polygon_calc`), shared helpers (`_case_template`, `_smoke_boot`, `__init__`), and the existing `_out/` golden gates / `archive/` / `cfd_asym/`. Rationale: entry-points are the things users actually invoke (keep them shallow); helpers are imported by scripts across several of the new subdirs (keeping them at the root means one import target, not N); `_out/` is CLAUDE-referenced and must not move.

### D2 — The `sys.path` re-anchor (the recurring hazard)
Every script bootstraps with `Path(__file__).resolve().parents[N]` pointed at the package root. Moving a script from `runs/foo.py` to `runs/demos/foo.py` increases its depth by one, so `parents[1]` (was package root) becomes `runs/`. Fix: bump to `parents[2]` (or anchor on a located package root), exactly as the `projects/` move did. This is mechanical and per-file, and the import-test catches any miss.

### D3 — Sibling vs package imports
Two breakage classes, both surfaced in task 0:
- **`runs/` sibling helpers:** a moved demo that did `from _case_template import …` (sibling) no longer sits next to `_case_template`. Rewrite to the package path `from runs._case_template import …` (resolves via the package root on `sys.path`).
- **`validation/` package imports:** runners do `from validation._harness import …`. After `_harness` moves to `validation/harness/`, rewrite to `from validation.harness._harness import …`. `harness/` and `cases/` get `__init__.py` so they are import-resolvable subpackages.

### D4 — The test is the integration gate for the validation move
`tests/test_shanghai_regression.py` invokes runners as `python -m validation.<module>` (subprocess) and reads result CSVs by path. It is the single highest-signal check that the validation reorg is correct end-to-end — both the `-m validation.cases.<module>` rewrite and the `data/results/` path. Its opt-in flag (`TPMSHX_RUN_SHANGHAI_REGRESSION=1`) is run explicitly in task 3.3.

### D5 — `examples/` folds into `runs/demos/`
The single root-level `examples/demo_vis_3d_interactive.py` is a demo; it belongs with the other demos. Folding it removes a one-file top-level directory. Its only references are `PROJECT_MANUAL.md:626` and a comment in `ui/vis3d_constants.py` — both updated.

## Risks / trade-offs

- **Wide mechanical churn → a missed edge breaks a script silently.** Mitigation: task 0 enumerates edges up front; task 3.1 import-tests *every* moved module; task 3.5 greps for any stale path. This is the same protocol that made the `projects/` move clean.
- **`-m` module-path or result-CSV path missed in the test.** Mitigation: task 3.3 runs the opt-in regression explicitly (not just the default suite, which skips it).
- **Golden gates reference a moved script.** Mitigation: D1 keeps `_out/` and all golden-referenced entry-points at `runs/` root; task 3.4 verifies bit-identical.

## Out of scope
Code-internal splits (`stages_3d.py`) → Phase 3. No script's computation changes.
