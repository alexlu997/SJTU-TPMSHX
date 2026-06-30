# Shanghai 3D validation CSV provenance — READ BEFORE CITING ANY CSV

> Codex 2026-05-19 review point #5: old CSVs in this dir are mutually
> inconsistent (different ε-contract eras + roughness eras). This file is
> the single source of truth for which numbers are live vs obsolete.
> Do **not** rename the CSVs (report/scripts reference them by name) —
> consult this table instead.

| CSV | dP RMSRE | Q RMSRE | Era | Status |
|-----|----------|---------|-----|--------|
| `shanghai_3d_baseline.csv` (6/12, v1.4.0) | **9.82%** | **3.20%** | **gamma_df default backend + mass-flux inlet, Nz=3** | **CURRENT canonical (production default)** — DF surrogate default switched rbf→gamma_df 2026-06-12 (commit `fdb49b1`); the +2.6pp vs rbf is entirely the smooth-trend K (cF gate-identical 534.8). File content = the v1.4.0 default full-chain run. |
| `shanghai_3d_baseline_gammadf_routing_check.csv` (6/12) | **7.19%** | **3.22%** | rbf backend + mass-flux inlet, Nz=3 | **rbf reference** (pre-v1.4.0 default; also the bit-identical routing regression check). Reproduce: `TPMSHX_DF_METHOD=rbf`. |
| `shanghai_3d_baseline_nz10_massflux.csv` (6/09) | **8.69%** | **3.33%** | rbf backend + mass-flux inlet, **Nz=10** | **rbf Nz=10 reference** (opt-in `TPMSHX_DF_METHOD=rbf`). |
| `shanghai_3d_baseline_gammadf_nz10.csv` (6/30) | **12.06%** | **3.30%** | **gamma_df default backend + mass-flux inlet, Nz=10** | **README headline source** — current production default at Nz=10, measured 2026-06-30. +~3.4pp dP vs rbf = the gamma_df smooth-trend K; Q gate-identical. Reproduce: `validate_shanghai_3d_real.py --nz 10`. |
| `shanghai_3d_baseline_pytest_h3.csv` (regenerated per run) | — | — | whatever HEAD defaults are | scratch output of `tests/test_shanghai_regression.py::test_shanghai_3d_baseline` (opt-in); pinned values live in the test (9.82/3.20 since v1.4.0, tol ±5%/±10%). |
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
- **Production default (gamma_df, 2nd-order face Δp + CFD-refit K): Nz=3 dP 5.28% / Q 3.21% · Nz=10 dP ~7.2% / Q 3.30% · grid-converged ≈12% / ≈3%**
  (README headline grid-converged ≈12%). Cell-centre+Dh²-K (legacy) was 9.82% / 12.06%.
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
- Nz=3 default (gamma_df): `validate_shanghai_3d_real.py --nz 3`  → 9.82/3.20
- Nz=3 rbf reference:      `TPMSHX_DF_METHOD=rbf` + same command   → 7.19/3.22
- Nz=10 rbf reference:     `TPMSHX_DF_METHOD=rbf` + `--nz 10`      → 8.69/3.33
Both carry `pressure_clip_hits` + `pressure_state_valid`; Shanghai n_invalid=0.
The SIMPLE solver's A+B low-Re early-exit (default on) makes the water-side solve
~24× faster with <0.01% effect on dP/Q (verified 2026-06-02).
