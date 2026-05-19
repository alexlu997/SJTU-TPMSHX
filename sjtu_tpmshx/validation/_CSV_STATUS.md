# Shanghai 3D validation CSV provenance — READ BEFORE CITING ANY CSV

> Codex 2026-05-19 review point #5: old CSVs in this dir are mutually
> inconsistent (different ε-contract eras + roughness eras). This file is
> the single source of truth for which numbers are live vs obsolete.
> Do **not** rename the CSVs (report/scripts reference them by name) —
> consult this table instead.

| CSV | dP RMSRE | Q RMSRE | Era | Status |
|-----|----------|---------|-----|--------|
| `shanghai_3d_baseline.csv` (5/19, regenerated post-#6) | 44.74% | 2.91% | full-ε fix, baseline roughness, **#6 cols present** | **AUTHORITATIVE / CURRENT** — 20 cols incl `pressure_state_valid`; 16/16 valid, 0 clip hits; summary prints valid/invalid split |
| `shanghai_3d_baseline_post-fix-mass-cons-Nz10.csv` (5/15) | 47.02% | 2.22% | **ε double-halved (ε_full/4) bug** | OBSOLETE — superseded numbers, see `vault/.../regression_report.md` header |
| `shanghai_3d_baselineNz10_norris_1a.csv` (5/13) | 24.15% | 3.61% | **old f-multiplier era** (norris_1a still applied f≈1.46 friction) | OBSOLETE — `norris_1a` is now a baseline no-op alias (`solvers/roughness.py`); 24.15% is double-counted-friction, do NOT cite |
| other `shanghai_3d_baseline*Nz10*`, `*post-fix-norris1a*`, `*bhatti_shah*`, `*z20*`, `*fine_Nx40*` | — | — | mixed pre-ε-fix / experiment branches | OBSOLETE for headline; trajectory only |

## Current authoritative numbers (post ε-fix, Option A, Nz=10)
- **3D LTNE conditional (water-temp prescribed): dP 44.74% / Q 2.91%** — `shanghai_3d_baseline.csv`. This is a CONDITIONAL prediction (uses experimental `T_Bout` for `Tb_prescribed`; water side frozen) — NOT a clean no-leak temperature prediction.
- **Clean no-leak Q (paper baseline): Q_air 1.71%** — lumped dual-Nu ε-NTU (`validate_shanghai_lumped_dual_nu.py`), ε-bug independent.
- dP residual ~45% = entrance口径 + t=0.6/L=7 geometry differential, non-separable from Shanghai data (see `vault/reports/methodology/2026-05-15-Q-dP-state-audit-CN.md` §4 + memory `feedback_dp_gap_attribution`).

## To produce the FINAL validation output
Run `validate_shanghai_3d_real.py --nz 10` (env with numba+scipy). New CSV
will carry `pressure_clip_hits` + `pressure_state_valid` columns and the
summary will print the valid/invalid case split (Codex #6 follow-up). On
Shanghai n_invalid is expected = 0, so the headline numbers should match
44.74/2.91 — but the run makes the口径 auditable.
