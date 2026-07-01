# Design — Phase 3: code layer (god-file split)

## Context

The code-layer audit found the package clean: one true god-file (`pipelines/stages_3d.py`, 3243 lines, 50+ helpers), everything else cohesive, `main.py` an intentional mixin design. So Phase 3 is narrow: decompose that one file, plus a trivial naming pass. It is the riskiest phase because `stages_3d.py` is in the compressible 3D hot path the golden gates and Shanghai baseline pin — hence the hard, repeated golden-bit-identical gate.

## Key decisions

### D1 — Extract pure helpers only, leave orchestration in place
Only helpers that are pure (no closure over stage-local mutable state, inputs/outputs explicit) move out. The stage flow (`_run_3d_stack` and the public entry) stays in `stages_3d.py`, which becomes a thin orchestrator that imports from the new sibling modules. A helper that closes over loop-local state is left where it is — forcing it out would change semantics.

### D2 — One cluster at a time, golden-gated after each
The extraction is incremental: move one cohesive cluster, then assert golden 3D bit-identical before the next. This bounds any regression to the single cluster just moved and makes revert trivial. A big-bang move would make any drift impossible to localize.

### D3 — numba is the subtle hazard
`@njit` kernels must move with their decorator and exact signature; calling an `njit` function across modules is fine but triggers a one-time cold recompile (expected, not a regression). The risk is accidentally changing a default argument, a global captured at jit time, or the order of array operations during the copy — any of which can perturb the last ULPs and fail bit-identical. The per-cluster golden check (D2) catches this immediately.

### D4 — The golden gate is non-negotiable; abandon over re-baseline
If a cluster cannot be extracted bit-identical, the correct action is to **revert that extraction**, not to re-baseline the golden snapshot. A readability refactor must never move the numbers. This is stated explicitly in tasks 2.x and 4.5, and a `numerical-auditor` pass (4.3) double-checks the diff for evaluation-order changes.

### D5 — Deferrable by design
Phases 1–2 deliver the bulk of the structural win (clean top-level, asset hygiene, role-grouped runs/, layered validation/). Phase 3 is a quality-of-life improvement to one file. If the golden gate proves fragile or risk appetite drops, Phase 3 can be postponed indefinitely without undermining 1–2.

## Risks / trade-offs

- **Last-ULP drift from the copy → golden fails.** Mitigation: incremental per-cluster golden checks; verbatim move (no edits to logic); numerical-auditor review.
- **A helper reached as `stages_3d.<helper>` from another module breaks.** Mitigation: task 1.2 greps `stages_3d.` before moving; re-export from `stages_3d.py` if any external caller exists.
- **Diminishing returns vs risk.** Accepted and surfaced: D5 makes the phase explicitly optional.

## Out of scope
`main.py` redesign; any solver/closure/kernel logic change; splitting cohesive large files.
