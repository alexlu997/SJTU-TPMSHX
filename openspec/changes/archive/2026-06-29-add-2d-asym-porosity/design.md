## Context

The 3D path already implements asymmetric per-side porosity end-to-end (`pipelines/stages_3d.py`): `_asym_split_A` derives the geometry split ratio from the offset δ, `_eps_sides_for_run` splits total ε into (ε·s, ε·(1−s)), the kernel receives `eps_A` / `eps_B` and consumes them without re-halving, and `_per_side_eps_override` / `eps_side_override` weight the dP/Q duty extraction by the per-side void.

The 2D path lags: the kernel (`solvers/ltne_energy.py`) takes a single `eps_f_arr` (= ε/2 symmetric) used in the convective terms of both fluids; `solve_full_domain` raises `NotImplementedError` for ε_A ≠ ε_B (`:645`); and `pipelines/stages_2d.py` has no δ plumbing at all. This change ports the settled 3D pattern down to 2D, where parameter sweeps over δ are affordable.

The relevant `eps_f_arr` usages in the 2D kernel are purely convective: the FxA pre-compute (`_gs_full_chunk:117`) and fluid-A convection (`:159,:175-176`) for side A; fluid-B convection (`:253,:266-267`) for side B; the same pattern in `_gs_full_chunk_rb`. Diffusion uses `K_ffA_arr` / `K_ffB_arr`, which already bake in per-side ε upstream, so the diffusion stencil needs no change.

## Goals / Non-Goals

**Goals:**
- 2D `solve_full_domain` accepts ε_A ≠ ε_B and weights each fluid's convection by its own void fraction.
- The 2D pipeline derives (ε_A, ε_B) from δ and weights dP/Q duty per-side.
- δ=0 stays bit-identical (golden 2D + Shanghai 2D unchanged).
- Reuse the 3D geometry-split source of truth rather than re-deriving it.

**Non-Goals:**
- Changing the 3D path (it is the reference, untouched).
- Defining a new δ / offset-isosurface geometry (reuse `_asym_split_A`).
- CFD validation of the asymmetric closure (P1-CFD, separate change).
- **The optimizer 2D path (`optimization/evaluator.py` `evaluate_design`) — OUT OF SCOPE.** It is a *separate* `solve_full_domain` caller that does not read `delta_levelset`. A manual δ sweep is achieved by looping Pipeline2D over δ values (which this change enables). Driving δ as an *optimization variable* would need the same per-side plumbing in `evaluate_design`, but optimization is gated (Q/dP-stability-first workflow), so it is a documented follow-up, not part of this change.
- UI changes — δ has no GUI knob; it stays programmatic (see Resolved Decisions).

## Decisions

- **D1 — Single source for the split ratio (RESOLVED: hoist).** Hoist `_asym_split_A`, `_per_side_eps_override`, and `_eps_sides_for_run` out of `stages_3d` into a neutral `solvers/asym_split.py`; both `stages_2d` and `stages_3d` import from there. *Why not "2D imports stages_3d":* `stages_3d` imports the heavy `SIMPLESolver3D` (numba 3D kernels), so a 2D→3D import would drag the entire 3D solver into every 2D run. The split ratio is geometry-derived and dimension-agnostic, so a shared `solvers/` home is the correct one. *Alternative:* a 2D-only split function → rejected (drift risk between 2D and 3D split definitions).
- **D2 — Per-side ε lives in TWO spots: the kernel's convective term + the pipeline's K_ff build.**
  - *(a) Kernel:* split `eps_f_arr` → `eps_fA_arr` / `eps_fB_arr` for the convection coefficients (Fx/Fy) and the FxA SOU pre-compute. The kernel's **diffusion stencil is unchanged** — it consumes `K_ffA_arr` / `K_ffB_arr` as given.
  - *(b) Pipeline:* the 2D pipeline MUST rebuild `K_ffA` / `K_ffB` per-side at δ≠0. **2D convention caveat (RESOLVED during apply 2026-06-29):** unlike 3D — where the symmetric `K_ffA = eps_fA_arr·k = (ε/2)·k` — the 2D symmetric `K_ff = ε·k_f` uses the **FULL** ε (`tpms_calc.py:506`), and the same array is fed to both channels. So the literal `K_ffA = ε_A·k = ε·s·k` would HALVE 2D diffusion at δ→0 (s→0.5 ⇒ (ε/2)·k ≠ the current ε·k), a factor-2 discontinuity. Instead apply the per-side redistribution factor to the existing symmetric baseline: `K_ffA = K_ff_sym · (ε_A / (ε/2)) = K_ff_sym · 2s`, `K_ffB = K_ff_sym · 2(1−s)`. This is **bit-identical at δ=0** (factor=1 at s=0.5), **continuous** as δ→0, and uses the **same 2s / 2(1−s) factor** as the convective term (kernel gets eps_A=ε·s, eps_B=ε·(1−s) vs the symmetric ε/2). It is the faithful 2D analog of 3D's *relative* redistribution (3D likewise scales its (ε/2)·k symmetric baseline by 2s); only the symmetric baseline differs (a pre-existing 2D/3D convention gap this change does NOT alter).
  - The solid `K_ss = (1−ε)·k_s` is **untouched**: the split only redistributes fluid ε between A and B, so total fluid ε — and thus the solid fraction 1−ε — is invariant.
  - *Alternative:* re-derive ε inside the kernel diffusion stencil → rejected (double-counts the ε already in K_ff).
- **D3 — Bit-identical δ=0 by passing the same array to both sides.** When symmetric, pass the one `eps_f_arr` object as both `eps_fA_arr` and `eps_fB_arr`, so the arithmetic is unchanged. Mirrors 3D's `eps_fA_arr = eps_fB_arr = eps_f_arr` at δ=0. This is what keeps the golden gate green.
- **D4 — Keep the `eps_A` / `eps_B` private-hook signature.** Replace the `NotImplementedError` branch in `solve_full_domain` with: build `eps_fA` / `eps_fB`, pass both to the kernel; keep the `eps_A + eps_B ≤ ε` guard. The full-ε contract for the default (symmetric) path is unchanged.

## Risks / Trade-offs

- **numba JIT signature change recompiles the kernel** → one-time cold compile on first run; verified by `/check` (full pytest), not a correctness risk.
- **δ=0 bit-identical regression** → Mitigation: capture the 2D golden baseline BEFORE the change and gate on `--check` bit-identical before merge.
- **Shanghai 2D RMSRE drift** → Mitigation: run the Shanghai 2D validation, confirm dP 8.35% / Q 2.51% unchanged.
- **FxA SOU pre-compute uses eps_f** → must be split to use `eps_fA` (side A keeps SOU); side B uses 1st-order convection (no SOU), so only its convection coefficient needs `eps_fB`.
- **Per-side interfacial coupling h_vA / h_vB and interface area under δ** → Mirror the 3D asym path's fidelity EXACTLY: split total ε between A/B and (per D2) build K_ffA/K_ffB per-side. **RESOLVED during apply (verified against `stages_3d`, numerical-auditor 2026-06-29):** 3D DOES adjust h_v per side under δ — `stages_3d._hv_side_geom_ratio` (lines ~2048-2090) derives a per-side ratio from the offset-δ wetted area (`asym_geometry.a0_sides`) and per-side D_h (`dh_sides`), always-on and exactly 1.0 at δ=0. So 2D mirrors it: `stages_2d._hv_side_geom_ratio_2d` scales `h_vA_local` / `h_vB_local` (main solve + the refined Q solve) by the same geometry ratio (1.0 at δ=0 ⇒ bit-identical). The residual κ_Nu (CFD-calibrated Nu correction) is left to P1-CFD, as in 3D. **Per-side dP is NOT split here:** 3D's per-side Darcy-Forchheimer split is `kappa_KcF`, which returns (1,1) without a CFD-calibrated κ table — so the 3D *default* dP uses symmetric K_df/cF, which 2D matches. Per-side dP κ is the P1-CFD layer (out of scope).
- **No 2D CFD reference for the asymmetric closure** → out of scope; this change delivers solver capability + conservation, not closure validation.

## Migration Plan

- **Phase 1 (kernel parity):** kernel pair + `solve_full_domain` dispatch + unit tests; gate on golden 2D bit-identical at δ=0.
- **Phase 2 (pipeline drive):** `stages_2d` δ split plumbing + per-side dP/Q weighting; gate on Shanghai 2D regression.
- **Rollback:** the δ=0 path is unchanged, so reverting is removing the new branches — no data or config migration.

## Resolved Decisions

- **δ exposure → programmatic only, no UI (RESOLVED 2026-06-29).** `delta_levelset` is already a `ComputeConfig` field (`controllers/compute_config.py:448`) with no GUI widget — even the 3D path sets it programmatically. 2D matches: δ is set in config/scripts for sweeps; **no UI work in this change**. An interactive δ knob, if ever needed, is a separate change.
- **Split-ratio sharing → hoist to `solvers/asym_split.py` (RESOLVED 2026-06-29).** See D1. Avoids dragging the heavy 3D solver into the 2D import path; the helper is dimension-agnostic geometry.

## Open Questions

(none — both resolved above.)
