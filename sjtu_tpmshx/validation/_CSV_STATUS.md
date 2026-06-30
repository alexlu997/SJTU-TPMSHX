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
| `shanghai_3d_baseline_nz10_massflux.csv` (6/09) | **8.69%** | **3.33%** | rbf backend + mass-flux inlet, **Nz=10** | **rbf Nz=10 reference** — gamma_df Nz=10 has NOT been measured yet. |
| `shanghai_3d_baseline_pytest_h3.csv` (regenerated per run) | — | — | whatever HEAD defaults are | scratch output of `tests/test_shanghai_regression.py::test_shanghai_3d_baseline` (opt-in); pinned values live in the test (9.82/3.20 since v1.4.0, tol ±5%/±10%). |
| `shanghai_3d_baselineplhub_switch.csv` (gitignored) | 7.19% | — | rbf era snapshot | referenced in `df_surrogate/surrogate_v3.py` docstring (smooth-trend K comparison); kept for that citation. |

> **2026-06-30 cleanup:** the obsolete / trajectory-only snapshots were removed
> (25 files: 14 gitignored scratch + 11 git-tracked). The tracked ones —
> `*Nz10_postGfix*`, `*post-fix-mass-cons*`, `*Nz10_norris_1a*`, `*Nz10_baseline*`,
> `*bhatti_shah*`, `*_Nz10*`, `*phase7_h8_nz10*`, `*z20*`, `*fine_Nx40*` — are
> recoverable from git history before commit `<this cleanup>` if a trajectory
> number is ever needed. Only the 4 live rows above + the plhub snapshot remain.

## Current authoritative numbers (v1.4.0, 2026-06-12)
- **Production default (gamma_df backend), Nz=3: dP 9.82% / Q 3.20%** —
  `shanghai_3d_baseline.csv`. DF surrogate default = GammaDF multi-fidelity
  (`df_surrogate/gamma_df.py`) since 2026-06-12; gamma_df **Nz=10 not yet
  measured**.
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
