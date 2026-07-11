# Shanghai 3D validation CSV provenance — READ BEFORE CITING ANY CSV

> Codex 2026-05-19 review point #5: old CSVs in this dir are mutually
> inconsistent (different ε-contract eras + roughness eras). This file is
> the single source of truth for which numbers are live vs obsolete.
> Do **not** rename the CSVs (report/scripts reference them by name) —
> consult this table instead.

| CSV | dP RMSRE | Q RMSRE | Era | Status |
|-----|----------|---------|-----|--------|
| `shanghai_3d_baseline.csv` (7/06, regenerated) | **5.28%** | **3.21%** | **gamma_df (CFD-refit K) + mass-flux inlet + face-extrap Δp + A2 criteria, Nz=3 gate grid** | **CURRENT canonical (gate grid 20×10×3)** — trajectory: 9.82 (6/12 v1.4.0, cell-centre Δp + smooth-trend K) → 5.05 (6/30 face-extrap Δp) → 5.28 (6/30 CFD-refit K) → 5.28 (7/06 A2 normalized-residual criteria; gate-grid RMSRE unchanged, per-case values shift at the 1e-3 level). Pinned in `tests/test_shanghai_regression.py`. |
| `shanghai_3d_baseline_a1_{16x8x4,32x16x8,64x32x16,128x64x32}.csv` (7/06, **gitignored**) | 5.19 / 6.46 / 8.09 / 8.70% | 3.44 / 3.07 / 2.94 / 2.88% | same era as canonical; all-axis r=2 grids | **A1 grid-convergence study** — per-case Richardson (finest triplet): Δp floor ≈9.6% (median p 1.59, 12/16 extrapolable), Q ≈2.8% (p 1.23). Source of the README grid-converged ≈10% headline + `assets/grid-convergence.png`. Regenerate: `validate_shanghai_3d_real.py --nx N --ny N/2 --nz N/4 --suffix _a1_NxN/2xN/4`, then `runs/tools/plot_grid_convergence.py`. |
| `shanghai_3d_baseline_gammadf_routing_check.csv` (6/12) | **7.19%** | **3.22%** | rbf backend + mass-flux inlet, Nz=3 | **rbf reference** (pre-v1.4.0 default; also the bit-identical routing regression check). Reproduce: `TPMSHX_DF_METHOD=rbf`. |
| `shanghai_3d_baseline_nz10_massflux.csv` (6/09) | **8.69%** | **3.33%** | rbf backend + mass-flux inlet, **Nz=10** | **rbf Nz=10 reference** (opt-in `TPMSHX_DF_METHOD=rbf`). |
| `shanghai_3d_baseline_gammadf_nz10.csv` (6/30) | **12.06%** | **3.30%** | gamma_df (smooth-trend K era) + mass-flux inlet, cell-centre Δp, Nz=10 | **SUPERSEDED as README headline source (7/06)** — README now quotes the grid-converged ≈10% floor from the A1 rows above. Kept as the 6/30 Nz=10 cell-centre snapshot (its face-extrap counterpart, 7.03%, was the old README ★; CSV not retained). |
| `shanghai_3d_baseline_pytest_h3.csv` (regenerated per run) | — | — | whatever HEAD defaults are | scratch output of `tests/test_shanghai_regression.py::test_shanghai_3d_baseline` (opt-in); pinned values live in the test (5.28/3.21 since 6/30 CFD-refit K; unchanged by 7/06 A2, tol ±5%/±10%). |
| `shanghai_3d_baselineplhub_switch.csv` (gitignored) | 7.19% | — | rbf era snapshot | referenced in `df_surrogate/surrogate_v3.py` docstring (smooth-trend K comparison); kept for that citation. |

> **2026-06-30 cleanup:** the obsolete / trajectory-only snapshots were removed
> (25 files: 14 gitignored scratch + 11 git-tracked). The tracked ones —
> `*Nz10_postGfix*`, `*post-fix-mass-cons*`, `*Nz10_norris_1a*`, `*Nz10_baseline*`,
> `*bhatti_shah*`, `*_Nz10*`, `*phase7_h8_nz10*`, `*z20*`, `*fine_Nx40*` — are
> recoverable from git history before commit `<this cleanup>` if a trajectory
> number is ever needed. Only the 4 live rows above + the plhub snapshot remain.

## Current authoritative numbers (v1.4.0, 2026-06-12)
> **2026-06-30 — Δp extraction switched to 2nd-order face extrapolation**
> (`SIMPLESolver3D.extract_dP_face_extrap`, kernel runner / headline path). The old
> cell-centre reduction sampled P ~h/2 inside the inlet/outlet faces (O(h), ~1st-order)
> and *under-predicted* Δp. With the 2nd-order face reduction the **gamma_df** RMSRE_dP is
> **Nz=3 5.05% / Nz=10 7.03%** (was 9.82% / 12.06% cell-centre); Q unchanged (3.20% / 3.30%).
> The `shanghai_3d_baseline*.csv` rows above were generated with the cell-centre reducer
> (historical provenance); regenerate for the face-extrap numbers. The **pipeline** path
> (`stages_3d`, GUI) was ALSO switched to face-extrap — the **golden 3D gate was re-baselined**:
> only the `dP`/`dP_B` scalars and the `P_kPa`/`P_Pa_B` display fields (which are anchored on dP)
> changed; the physics solve (`Ta`/`Tb`/`Ts`/`vmag`/`Q`/`T_out`) is **bit-identical**. The dP
> reduction works for **any** flow direction (±x/±y/±z): `_resolve_axis_map` permutes streamwise
> onto solver axis 1 for all six dirs, and both reducers read that axis.
> **2026-06-30 — grid-converged headline.** An all-axis (r=2: 16/8/4 → 32/16/8 → 64/32/16)
> full-refinement Richardson pins the **grid-converged** gamma_df Δp RMSRE at **≈ 12 %**
> (finest 64-grid measured 9.70%, Richardson limit 12.1%, p_obs≈0.76) and Q at **≈ 3 %**
> (3.43→3.16→3.03%, clean 2nd-order). KEY: the production-grid Δp (Nz=10 face 7.03%) is
> **under-resolved** — both the cell-centre and the face reducers converge to the SAME continuous
> Δp as h→0 (cell-centre grid-converged ~12.8%, face ~12.1%); face-extrap only *accelerates*
> convergence, the floor is the geometry/closure model error (~12%). The README headline now
> quotes the grid-converged ≈12% / ≈3%; the shanghai regression test still pins the production
> Nz=3 value (now 5.28% — see K re-baseline below) as a config-specific guard.
> **2026-06-30 (#2) — gamma_df K re-baselined.** K moved from the SmoothDF D_h² trend (53% RMSRE,
> the +2.6pp vs rbf below) to a CFD-refit per-geometry surface (raw water CFD, 2-stage extraction,
> log-space TPS; `_prebuilt/df_cfd_coeffs.csv`). c_F UNCHANGED. Nz=3 dP **5.05%→5.28%**, Q 3.20→3.21%;
> water-side Δp (7-6 exp) Diamond 0.33→0.40 / Gyroid 0.62→0.68. Grid-converged ≈12% and the README
> headline are c_F-dominated → unchanged (K is a 1–6% Darcy correction in the air window). See
> `df_surrogate/gamma_df.py` K UPDATE + openspec/changes/df-coeffs-cfd-refit.
> **2026-07-06 (#2) — B2 χ_s homogenization fit.** K_ss now uses
> `chi_s_eff(type, ε)` (unit-cell periodic homogenization, ~0.65 at the
> Shanghai point vs the uncalibrated 1.0; `validation/chi_s_homogenization.csv`).
> The kernel gate is **insensitive** (frozen-B + convection-dominated: Q
> shifts ≤0.0002%, RMSRE identical to 2 decimals); evaluator-level Q moves
> 0.1–0.35%. Physical-correctness fix, not a gate-metric fix. The gate
> script previously bypassed χ_s entirely (inline `(1−ε)k_s`) — now wired.
> **2026-07-06 — A2 convergence criteria + A1 grid-study rerun.** The 3D SIMPLE
> mass residual is now inlet-mass-flux-relative (was absolute kg/s), the outer
> gate tracks Ta/Tb/Ts, and stall-exits report converged=False. Gate-grid
> numbers unchanged (5.28/3.21). The A1 rerun (4 grids, 16×8×4 → 128×64×32,
> per-case Richardson on the finest triplet) moves the grid-converged headline
> to **Δp ≈10% (floor 9.6%, median p 1.59) / Q ≈3% (2.8%)** — vs the 6/30
> 3-grid study's ≈12% (p_obs 0.76), which was measured under the old criteria
> and (for the figure) an earlier K; the attribution is mixed, both changed.
- **Production default (gamma_df, 2nd-order face Δp + CFD-refit K + A2 criteria): Nz=3 gate dP 5.28% / Q 3.21% · grid-converged ≈10% / ≈3%**
  (README headline grid-converged ≈10% since 7/06; was ≈12% 6/30–7/06). Cell-centre+Dh²-K (legacy) was 9.82% / 12.06%.
  DF surrogate default = GammaDF multi-fidelity (`df_surrogate/gamma_df.py`) since 2026-06-12.
- **rbf backend reference (`TPMSHX_DF_METHOD=rbf`): Nz=3 dP 7.19% / Q 3.22%,
  Nz=10 dP 8.69% / Q 3.33%** — post 2026-06-04 mass-flux-inlet fix (which cut
  Nz=3 dP 17.43→7.19 by injecting the experimentally-correct air mass flow).
  The gamma_df−rbf gap (+2.6pp) is entirely the smooth-trend K; cF is
  gate-identical (534.8) by construction.
- **Clean no-leak Q (paper baseline): Q_air 1.71%** — lumped dual-Nu ε-NTU
  (`validate_shanghai_lumped_dual_nu.py`), surrogate-independent.
- rbf-side dP residual ~7% = true closure + geometry floor (the old "entrance
  convention" contributor was the velocity-inlet BC bug, fixed 2026-06-04;
  see memory `feedback_dp_gap_attribution`).

## To reproduce
- Nz=3 default (gamma_df): `validate_shanghai_3d_real.py --nz 3`  → 5.28/3.21
- Nz=3 rbf reference:      `TPMSHX_DF_METHOD=rbf` + same command   → 7.19/3.22
- Nz=10 rbf reference:     `TPMSHX_DF_METHOD=rbf` + `--nz 10`      → 8.69/3.33
Both carry `pressure_clip_hits` + `pressure_state_valid`; Shanghai n_invalid=0.
The SIMPLE solver's A+B low-Re early-exit (default on) makes the water-side solve
~24× faster with <0.01% effect on dP/Q (verified 2026-06-02).

⚠️ `--runner pipeline` reported a hard-coded `pressure_clip_hits=0` /
`pressure_state_valid=1` until 2026-07-11, which made its own `n_invalid=0`
vacuous (the exclusion never ran). Fixed to read the real pipeline diagnostics;
the **kernel** gate runner — the one that produced 5.28/3.21 — was always
computing them for real, so the headline numbers are unaffected.

## Environment that reproduces these numbers (2026-07-11)
Until now this file recorded the physics provenance but **no version record**,
so "which numpy/numba produced 5.28/3.21" was unanswerable. Snapshot below is
the dev box; the full `pip freeze` is committed as
`constraints-devbox-2026-07-11.txt` (repo root).

- Python 3.12.10 (MSC v.1943, 64-bit), Windows
- numpy 2.4.4 · scipy 1.17.1 · numba 0.64.0 (llvmlite 0.46.0) · pyamg 5.3.0
- pandas 2.3.3 · joblib 1.5.3 · CoolProp 7.2.0 · PySide6 6.11.0
- torch 2.11.0+cu128 · botorch 0.17.2 · gpytorch 1.15.2 (optimizer stack only)

**Verified**, not merely captured: with `data/raw_data` present, the full suite
is green on this combo — `PYTHONHASHSEED=0 pytest sjtu_tpmshx/tests/ -q -n auto
--dist loadscope` → **1187 passed, 3 skipped, 0 failed**. That run exercised the
strictest pins: the exact-`==` DF golden gates (`test_df_backend_registry`,
`test_df_projection_equivalence`), the `rel=1e-12` frozen evaluator tuples, and
`test_df_source_parity` (XLSX-vs-prebuilt-CSV calibration, `rel=1e-6`) — the
last one normally **skips** for want of the gitignored Excel, so this is the
first recorded confirmation that the two calibration sources have not diverged.

This is *an* environment that reproduces the numbers; there is **no record**
that it is the one they were originally captured on (that record never existed).
Install the server with `pip install -r requirements.txt -c constraints-devbox-2026-07-11.txt`
and reproduce the gate before upgrading anything.

**Porting note:** the exact-`==` DF gates skip only when `CI=true`. On a server
running pytest by hand they *will* run, and cross-machine libm/FMA differences
shift the last ULP (`test_df_backend_registry.py:31` measured rel ~1e-13 on
ubuntu CI). A red there is expected drift, not a port bug — set `CI=true`, or
re-pin on the target machine.
