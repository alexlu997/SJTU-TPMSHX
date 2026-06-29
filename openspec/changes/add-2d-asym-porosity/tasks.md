## 1. Baseline capture (golden safety)

- [x] 1.1 Capture the 2D golden baseline before any edit: `python -u sjtu_tpmshx/runs/_out/_golden_2d.py golden_2d_pre.json`
- [x] 1.2 Record the current Shanghai 2D RMSRE (dP 8.35% / Q 2.51%) as the regression reference

## 2. Phase 1 — kernel parity (TDD)

- [x] 2.1 Write failing unit test: `solve_full_domain` with ε_A ≠ ε_B (ε_A + ε_B ≤ ε) runs without `NotImplementedError` and conserves energy
- [x] 2.2 Write failing unit test: `solve_full_domain` with ε_A = ε_B = ε/2 reproduces the symmetric single-`eps_f_arr` result bit-identically
- [x] 2.3 Split `_gs_full_chunk` `eps_f_arr` → `eps_fA_arr` / `eps_fB_arr` (FxA pre-compute + fluid-A convection use fA; fluid-B convection uses fB)
- [x] 2.4 Mirror the same split in `_gs_full_chunk_rb`
- [x] 2.5 Replace the `NotImplementedError` branch in `solve_full_domain`: build `eps_fA` / `eps_fB`, pass both; symmetric passes the same array to both sides; keep the `eps_A + eps_B ≤ ε` guard
- [x] 2.6 Run the two unit tests → green
- [x] 2.7 Verify golden 2D bit-identical at δ=0: `python -u sjtu_tpmshx/runs/_out/_golden_2d.py --check golden_2d_pre.json`
- [x] 2.8 Full pytest (`/check`) green

## 3. Phase 2 — pipeline drive (TDD)

- [x] 3.1 Hoist `_asym_split_A` / `_per_side_eps_override` / `_eps_sides_for_run` from `stages_3d` into a new neutral `solvers/asym_split.py`; update `stages_3d` to import from there (per design D1)
- [x] 3.2 Verify 3D golden bit-identical after the hoist (pure relocation, no behavior change)
- [x] 3.3 Write failing test: a δ≠0 2D config runs end-to-end through Pipeline2D and conserves (AB energy balance within tolerance)
- [x] 3.4 Add the 2D δ split plumbing in `stages_2d` using the hoisted helpers (δ≠0 → ε·split; δ=0 → ε/2 symmetric)
- [x] 3.5 Build `K_ffA` with ε_A and `K_ffB` with ε_B in `stages_2d` when δ≠0 (K_ff = ε·k_f, `tpms_calc:506`; mirror 3D `K_ffA = eps_fA_arr * k_A`). δ=0 → unchanged symmetric K_ff. `K_ss` is left untouched (1−ε invariant). **2D caveat (resolved):** symmetric 2D K_ff uses FULL ε, so per-side uses the proportional `2s`/`2(1−s)` factor (= ε_side/(ε/2)), bit-identical at δ=0 — see design D2(b)
- [x] 3.6 Thread `eps_A` / `eps_B` into the `solve_full_domain` call from `stages_2d` (δ≠0 → per-side; δ=0 → None / symmetric)
- [x] 3.7 Add per-side ε weighting to the 2D dP/Q extraction (mirror `eps_side_override`); confirm h_v / interface-area handling matches the 3D asym path exactly (design risk). **Verified against 3D (numerical-auditor):** 3D DOES scale h_v per-side at δ≠0 via an always-on geometry ratio (`stages_3d._hv_side_geom_ratio`, =1.0 at δ=0), so 2D now mirrors it (`_hv_side_geom_ratio_2d` → `h_vA/B_local × ratio`, main + refined solve). Per-side **dP** (Darcy-Forchheimer κ) is the opt-in CFD κ layer — 3D's default `kappa_KcF` returns (1,1) with no table, so symmetric K_df/cF here matches the 3D default; per-side dP κ is P1-CFD (out of scope)
- [x] 3.8 Run the δ≠0 pipeline test → green
- [x] 3.9 Verify golden 2D bit-identical at δ=0 through the pipeline path
- [x] 3.10 Shanghai 2D regression: confirm RMSRE dP / Q unchanged (dP 8.35% / Q 2.51% — exact match)
- [x] 3.11 Full pytest (`/check`) green

## 4. Close-out

- [x] 4.1 Update the solver `CLAUDE.md` ε-invariant note: 2D now supports asymmetric ε_A ≠ ε_B via the `eps_A` / `eps_B` hooks (remove the "2D raises NotImplementedError" caveat)
- [x] 4.2 `openspec validate add-2d-asym-porosity --strict`
- [ ] 4.3 Commit to the solver repo; archive the change with `openspec archive add-2d-asym-porosity`
