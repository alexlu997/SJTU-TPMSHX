# Design — Phase 1: top-level + asset hygiene

## Context

Whole-repo audit verdict: the package is healthy where it counts (clean layer hierarchy `ui → controllers → pipelines → solvers/df_surrogate/optimization`; no circular deps; Nu/porosity/geometry single-sourced; no commented-out dead code). The mess is cosmetic + edge: loose assets and orphan cache in the package root, a few empty/stale dirs, two already-DEPRECATED scripts, one import-side-effect bug, and no written layout convention. Phase 1 clears exactly that, risk-free, and lays down the `repository-structure` spec that Phases 2–3 build on.

## Why this is the low-risk slice

The one rule that keeps Phase 1 safe: **nothing the package imports moves.** Assets are data files with at most a path string referencing them; the audit found exactly two such references for the PNGs (`main.py:134`, `ui/ui_builders.py:80`) and zero for the orphan npz. So the blast radius is two edited path strings, verified by a UI smoke. Everything else is deletion of provably-unused files.

## Key decisions

### D1 — The package-root `lut_*.npz` are orphan cache, not data → delete
Loader `solvers/sigmoid_field.py`: `cache_dir` defaults to `os.path.dirname(__file__)` = `solvers/`, filename `lut_{type}_{n_L}x{n_t}_N{N}.npz` (the real cache is `solvers/lut_Diamond_41x21_N256.npz`). The package-root `lut_Diamond_41x21.npz` / `lut_Gyroid_41x21.npz` are the **wrong directory**, **wrong name** (no `_N256`), **untracked**, and `41x21` has **zero** repo references. They are a stale write from an old run. Deleting is local-only; the LUT regenerates into `solvers/` on first use.

### D2 — PNG path from package root, not `__file__`, in `ui_builders.py`
`main.py` sits at the package root, so `os.path.dirname(__file__)` + `assets/logos/` is correct there. `ui/ui_builders.py` sits one level down; its banner reference must resolve to `…/sjtu_tpmshx/assets/logos/`, i.e. anchor on the package root (`os.path.dirname(os.path.dirname(__file__))` or an existing package-root constant), not on `ui/`. This mirrors the Phase-0 `projects/` lesson: a relocation that changes a file's depth must re-anchor its path, not assume the old depth.

### D3 — `skills-lock.json` belongs to tooling, not the package
No `*.py` references it. It is a Claude Code skills lockfile that happened to land in the package root. Move to `.claude/` (or gitignore + remove). This keeps the package root pure source.

### D4 — Fix the entry-guard bug here, not in Phase 3
`validate_shanghai_aligned.py` runs on import (writes xlsx). It is a real correctness defect (the audit's only HIGH finding) and a one-file, self-contained fix, so it rides along with Phase 1 rather than waiting for the code-layer phase. It is an orphan (no importer), so wrapping its body in `main()` + guard cannot break a caller.

### D5 — The spec is the point
Phase 1's lasting value is the `repository-structure` capability: it turns "we tidied up" into "here is the rule, and re-scatter is now a spec violation." Phases 2–3 extend the same capability rather than inventing new ones.

## Risks / trade-offs

- **Relocated PNG fails to load in the real (non-offscreen) UI.** Mitigation: task 8.1 runs the UI smoke; task 4.4 greps every PNG reference. Low risk (2 references, both found).
- **A "DEPRECATED" script is still invoked by a vault note or external script.** Mitigation: task 3.1 greps for importers in-repo; the header itself declares it dead since 2026-06-15; `git rm` keeps it recoverable.
- **Deleting untracked files is unrecoverable.** Accepted: the npz are regeneratable cache and `nTop_inputs/` is stale smoke input — both reproduce from code. Nothing in git history is lost.

## Out of scope (later phases)

- `runs/` subdir split, `validation/` layering, `examples/` fold-in → **Phase 2**.
- `pipelines/stages_3d.py` god-file split, naming-rename sweep of existing modules → **Phase 3**.
- `opt_runs/` tracking model → left as-is (documented intent).
