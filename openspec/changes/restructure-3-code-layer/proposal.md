## Why

**Phase 3 of the 3-phase restructure — the code layer.** The dead-code and boundary audits came back remarkably clean: single-sourced invariants intact, no circular deps, no commented-out dead code, essentially no orphan functions. So the code-layer work collapses to **one** genuine target plus a naming pass:

- `pipelines/stages_3d.py` is **3243 lines** — the only true god-file. It mixes the 3D pipeline stage flow (parse cfg → build fields → run solvers → finalize) with **50+ helper functions** (flux/temperature/roughness/solver-setup/profiling). Everything else in the top-10-largest list is cohesive (solver kernels, UI panels, audits) and stays. `main.py` (2696 lines) is an intentional Qt mixin composition — left alone.
- A final naming/consistency pass to retire any remaining stragglers and lock the `repository-structure` naming requirement.

This phase is **optional and deferrable**: it improves navigability of the 3D pipeline but carries the most regression risk of the three, because `stages_3d.py` is in the compressible-solver hot path that the golden gates and the Shanghai baseline pin. It is gated hard on **golden 2D/3D bit-identical**.

## What Changes

- **Decompose `pipelines/stages_3d.py`** by extracting cohesive helper clusters into sibling modules (candidate split, finalized after a dedicated read at execution):
  - `pipelines/stages_3d_fields.py` — field construction (ε / K / property-array builders).
  - `pipelines/stages_3d_flux.py` — flux / temperature / duty extraction helpers.
  - `pipelines/stages_3d_solve.py` — solver-setup + outer-loop plumbing.
  - keep the top-level stage orchestration (`_run_3d_stack` and the public entry) in `stages_3d.py`, now thin.
  - The split is **pure relocation of functions** — no logic change, no signature change. `numba @njit` kernels keep their decorators and signatures (cross-module `njit` calls are fine; a one-time cold recompile is expected).
- **Naming pass**: rename any remaining module/file that violates the lowercase-snake rule (the audit found directories, handled in Phase 1; confirm no module-name stragglers remain) and finalize the `repository-structure` naming requirement as enforced.

## Capabilities

### Modified Capabilities

- `repository-structure`: add the code-layer requirements — a single source file SHOULD not grow into a god-file mixing orchestration with dozens of helpers; helper clusters are extracted into sibling modules while keeping the public stage entry thin; such a split must be behavior-preserving (golden bit-identical).

## Impact

- **Code:** `pipelines/stages_3d.py` (shrinks to orchestration) + 2–3 new `pipelines/stages_3d_*.py` helper modules; import updates in the (few) callers of any helper that was previously reached as `stages_3d.<helper>` (most are module-private and only referenced within `stages_3d`).
- **Hard gate — golden bit-identical.** Per CLAUDE.md, `runs/_out/_golden_3d.py` (and 2D) must stay bit-identical, and the Shanghai 3D baseline (the README headline Δp/Q) unchanged. This is the make-or-break check; any drift means the extraction altered evaluation order and must be reverted.
- **No behavior, dependency, or numeric change** intended — this is a readability refactor of one file.
- **Deferrable:** if risk appetite is low, Phases 1–2 deliver most of the structural win; Phase 3 can be skipped or postponed without blocking them.
- **Out of scope:** touching `main.py`'s mixin design; any solver/closure logic change; splitting the cohesive large files (solver kernels, UI panels, audits).
