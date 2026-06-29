## Context

The 3D path already implements asymmetric per-side porosity end-to-end (`pipelines/stages_3d.py`): `_asym_split_A` derives the geometry split ratio from the offset δ, `_eps_sides_for_run` splits total ε into (ε·s, ε·(1−s)), the kernel receives `eps_A` / `eps_B` and consumes them without re-halving, and `_per_side_eps_override` / `eps_side_override` weight the dP/Q duty extraction by the per-side void.

The 2D path lags: the kernel (`solvers/ltne_energy.py`) takes a single `eps_f_arr` (= ε/2 symmetric) used in the convective terms of both fluids; `solve_full` raises `NotImplementedError` for ε_A ≠ ε_B (`:645`); and `pipelines/stages_2d.py` has no δ plumbing at all. This change ports the settled 3D pattern down to 2D, where parameter sweeps over δ are affordable.

The relevant `eps_f_arr` usages in the 2D kernel are purely convective: the FxA pre-compute (`_gs_full_chunk:117`) and fluid-A convection (`:159,:175-176`) for side A; fluid-B convection (`:253,:266-267`) for side B; the same pattern in `_gs_full_chunk_rb`. Diffusion uses `K_ffA_arr` / `K_ffB_arr`, which already bake in per-side ε upstream, so the diffusion stencil needs no change.

## Goals / Non-Goals

**Goals:**
- 2D `solve_full` accepts ε_A ≠ ε_B and weights each fluid's convection by its own void fraction.
- The 2D pipeline derives (ε_A, ε_B) from δ and weights dP/Q duty per-side.
- δ=0 stays bit-identical (golden 2D + Shanghai 2D unchanged).
- Reuse the 3D geometry-split source of truth rather than re-deriving it.

**Non-Goals:**
- Changing the 3D path (it is the reference, untouched).
- Defining a new δ / offset-isosurface geometry (reuse `_asym_split_A`).
- CFD validation of the asymmetric closure (P1-CFD, separate change).
- Optimizer objective / UI changes beyond passing δ through to the 2D solve.

## Decisions

- **D1 — Single source for the split ratio (RESOLVED: hoist).** Hoist `_asym_split_A`, `_per_side_eps_override`, and `_eps_sides_for_run` out of `stages_3d` into a neutral `solvers/asym_split.py`; both `stages_2d` and `stages_3d` import from there. *Why not "2D imports stages_3d":* `stages_3d` imports the heavy `SIMPLESolver3D` (numba 3D kernels), so a 2D→3D import would drag the entire 3D solver into every 2D run. The split ratio is geometry-derived and dimension-agnostic, so a shared `solvers/` home is the correct one. *Alternative:* a 2D-only split function → rejected (drift risk between 2D and 3D split definitions).
- **D2 — Per-side ε only in the convective term.** Split `eps_f_arr` → `eps_fA_arr` / `eps_fB_arr` for the convection coefficients (Fx/Fy) and the FxA SOU pre-compute. Diffusion stays via `K_ffA_arr` / `K_ffB_arr`. *Alternative:* re-derive ε inside the diffusion stencil → rejected (K_ff already carries it; would double-count).
- **D3 — Bit-identical δ=0 by passing the same array to both sides.** When symmetric, pass the one `eps_f_arr` object as both `eps_fA_arr` and `eps_fB_arr`, so the arithmetic is unchanged. Mirrors 3D's `eps_fA_arr = eps_fB_arr = eps_f_arr` at δ=0. This is what keeps the golden gate green.
- **D4 — Keep the `eps_A` / `eps_B` private-hook signature.** Replace the `NotImplementedError` branch in `solve_full` with: build `eps_fA` / `eps_fB`, pass both to the kernel; keep the `eps_A + eps_B ≤ ε` guard. The full-ε contract for the default (symmetric) path is unchanged.

## Risks / Trade-offs

- **numba JIT signature change recompiles the kernel** → one-time cold compile on first run; verified by `/check` (full pytest), not a correctness risk.
- **δ=0 bit-identical regression** → Mitigation: capture the 2D golden baseline BEFORE the change and gate on `--check` bit-identical before merge.
- **Shanghai 2D RMSRE drift** → Mitigation: run the Shanghai 2D validation, confirm dP 8.35% / Q 2.51% unchanged.
- **FxA SOU pre-compute uses eps_f** → must be split to use `eps_fA` (side A keeps SOU); side B uses 1st-order convection (no SOU), so only its convection coefficient needs `eps_fB`.
- **No 2D CFD reference for the asymmetric closure** → out of scope; this change delivers solver capability + conservation, not closure validation.

## Migration Plan

- **Phase 1 (kernel parity):** kernel pair + `solve_full` dispatch + unit tests; gate on golden 2D bit-identical at δ=0.
- **Phase 2 (pipeline drive):** `stages_2d` δ split plumbing + per-side dP/Q weighting; gate on Shanghai 2D regression.
- **Rollback:** the δ=0 path is unchanged, so reverting is removing the new branches — no data or config migration.

## Resolved Decisions

- **δ exposure → programmatic only, no UI (RESOLVED 2026-06-29).** `delta_levelset` is already a `ComputeConfig` field (`controllers/compute_config.py:448`) with no GUI widget — even the 3D path sets it programmatically. 2D matches: δ is set in config/scripts for sweeps; **no UI work in this change**. An interactive δ knob, if ever needed, is a separate change.
- **Split-ratio sharing → hoist to `solvers/asym_split.py` (RESOLVED 2026-06-29).** See D1. Avoids dragging the heavy 3D solver into the 2D import path; the helper is dimension-agnostic geometry.

## Open Questions

(none — both resolved above.)
