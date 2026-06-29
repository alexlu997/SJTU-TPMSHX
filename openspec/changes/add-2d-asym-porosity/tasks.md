## 1. Baseline capture (golden safety)

- [ ] 1.1 Capture the 2D golden baseline before any edit: `python -u sjtu_tpmshx/runs/_out/_golden_2d.py golden_2d_pre.json`
- [ ] 1.2 Record the current Shanghai 2D RMSRE (dP 8.35% / Q 2.51%) as the regression reference

## 2. Phase 1 — kernel parity (TDD)

- [ ] 2.1 Write failing unit test: `solve_full_domain` with ε_A ≠ ε_B (ε_A + ε_B ≤ ε) runs without `NotImplementedError` and conserves energy
- [ ] 2.2 Write failing unit test: `solve_full_domain` with ε_A = ε_B = ε/2 reproduces the symmetric single-`eps_f_arr` result bit-identically
- [ ] 2.3 Split `_gs_full_chunk` `eps_f_arr` → `eps_fA_arr` / `eps_fB_arr` (FxA pre-compute + fluid-A convection use fA; fluid-B convection uses fB)
- [ ] 2.4 Mirror the same split in `_gs_full_chunk_rb`
- [ ] 2.5 Replace the `NotImplementedError` branch in `solve_full_domain`: build `eps_fA` / `eps_fB`, pass both; symmetric passes the same array to both sides; keep the `eps_A + eps_B ≤ ε` guard
- [ ] 2.6 Run the two unit tests → green
- [ ] 2.7 Verify golden 2D bit-identical at δ=0: `python -u sjtu_tpmshx/runs/_out/_golden_2d.py --check golden_2d_pre.json`
- [ ] 2.8 Full pytest (`/check`) green

## 3. Phase 2 — pipeline drive (TDD)

- [ ] 3.1 Hoist `_asym_split_A` / `_per_side_eps_override` / `_eps_sides_for_run` from `stages_3d` into a new neutral `solvers/asym_split.py`; update `stages_3d` to import from there (per design D1)
- [ ] 3.2 Verify 3D golden bit-identical after the hoist (pure relocation, no behavior change)
- [ ] 3.3 Write failing test: a δ≠0 2D config runs end-to-end through Pipeline2D and conserves (AB energy balance within tolerance)
- [ ] 3.4 Add the 2D δ split plumbing in `stages_2d` using the hoisted helpers (δ≠0 → ε·split; δ=0 → ε/2 symmetric)
- [ ] 3.5 Build `K_ffA` with ε_A and `K_ffB` with ε_B in `stages_2d` when δ≠0 (K_ff = ε·k_f, `tpms_calc:506`; mirror 3D `K_ffA = eps_fA_arr * k_A`). δ=0 → unchanged symmetric K_ff. `K_ss` is left untouched (1−ε invariant)
- [ ] 3.6 Thread `eps_A` / `eps_B` into the `solve_full_domain` call from `stages_2d` (δ≠0 → per-side; δ=0 → None / symmetric)
- [ ] 3.7 Add per-side ε weighting to the 2D dP/Q extraction (mirror `eps_side_override`); confirm h_v / interface-area handling matches the 3D asym path exactly (design risk)
- [ ] 3.8 Run the δ≠0 pipeline test → green
- [ ] 3.9 Verify golden 2D bit-identical at δ=0 through the pipeline path
- [ ] 3.10 Shanghai 2D regression: confirm RMSRE dP / Q unchanged
- [ ] 3.11 Full pytest (`/check`) green

## 4. Close-out

- [ ] 4.1 Update the solver `CLAUDE.md` ε-invariant note: 2D now supports asymmetric ε_A ≠ ε_B via the `eps_A` / `eps_B` hooks (remove the "2D raises NotImplementedError" caveat)
- [ ] 4.2 `openspec validate add-2d-asym-porosity --strict`
- [ ] 4.3 Commit to the solver repo; archive the change with `openspec archive add-2d-asym-porosity`
