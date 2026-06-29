## Why

The solver already supports asymmetric per-side porosity (ε_A ≠ ε_B from an offset-isosurface δ) in 3D, but the 2D LTNE kernel raises `NotImplementedError` on any ε_A ≠ ε_B (`solvers/ltne_energy.py:645`). This blocks using the fast 2D path — the optimizer, quick-design tool, and Shanghai 2D validation — to screen or sweep the offset-porosity design variable. Parameter sweeps over δ are only affordable in 2D, so the gap forces every δ study onto the ~order-of-magnitude slower 3D solver.

## What Changes

- Extend the 2D LTNE Gauss-Seidel kernel (`_gs_full_chunk` + the red-black `_gs_full_chunk_rb`) to carry distinct per-side void fractions ε_A, ε_B in the **convective** terms (FxA SOU pre-compute + Fx/Fy). The kernel's diffusion stencil is unchanged — it consumes `K_ffA_arr` / `K_ffB_arr` as given.
- `solve_full_domain` accepts ε_A ≠ ε_B instead of raising `NotImplementedError`; the `eps_A + eps_B ≤ ε` guard is kept.
- Add δ → (ε_A, ε_B) split plumbing to the 2D pipeline (`pipelines/stages_2d.py`), mirroring the 3D `_eps_sides_for_run` / `_per_side_eps_override`.
- In the pipeline, build `K_ffA` / `K_ffB` with the per-side ε_A / ε_B (since `K_ff = ε·k_f`, `tpms_calc:506`; mirror 3D `K_ffA = eps_fA_arr * k_A`). The solid `K_ss = (1−ε)·k_s` is unchanged — the split conserves total ε, so the solid fraction 1−ε is invariant.
- 2D dP/Q duty extraction weights per-side mass flux by the per-side void fraction (mirror of the 3D `eps_side_override`).
- **Non-breaking**: at δ=0 (every current production config) the result is bit-identical — the symmetric ε/2 split, the 2D golden gate, and the Shanghai 2D baseline are untouched.

## Capabilities

### New Capabilities

- `asymmetric-porosity-2d`: per-side void-fraction (ε_A ≠ ε_B) support across the 2D LTNE kernel, pipeline, and duty extraction, driven by the offset-isosurface δ — including the requirement that δ=0 stay bit-identical to the legacy symmetric path.

### Modified Capabilities

(none — `openspec/specs/` has no existing capability; the preserved symmetric behavior is captured as a bit-identical scenario inside the new capability rather than as a delta.)

## Impact

- **Code**: `solvers/ltne_energy.py` (kernel pair + `solve_full_domain` dispatch); `pipelines/stages_2d.py` (δ split plumbing + per-side dP/Q weighting); tests under `sjtu_tpmshx/tests/`.
- **Hard invariant preserved**: "porosity ε is split in ONE place" still holds — asymmetric uses the sanctioned `eps_A` / `eps_B` private hooks (split upstream in the pipeline, kernel consumes them without re-halving), exactly as 3D already does. The default symmetric path still halves ε once inside `solve_full_domain`.
- **Gates**: 2D golden bit-identical at δ=0; Shanghai 2D RMSRE (dP 8.35% / Q 2.51%) unchanged.
- **No new dependencies.** numba kernel signature change triggers a one-time cold recompile.
- **Out of scope**: CFD validation of the asymmetric closure (P1-CFD, tracked separately) and any optimizer objective change.
