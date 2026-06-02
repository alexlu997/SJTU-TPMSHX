# Shanghai 3D validation CSV provenance — READ BEFORE CITING ANY CSV

> Codex 2026-05-19 review point #5: old CSVs in this dir are mutually
> inconsistent (different ε-contract eras + roughness eras). This file is
> the single source of truth for which numbers are live vs obsolete.
> Do **not** rename the CSVs (report/scripts reference them by name) —
> consult this table instead.

| CSV | dP RMSRE | Q RMSRE | Era | Status |
|-----|----------|---------|-----|--------|
| `shanghai_3d_baseline_pytest_h3.csv` (6/02) | **17.32%** | **3.74%** | **post G-fix + RBF cubic s=0.1, Nz=3** | **CURRENT pinned baseline** — `tests/test_shanghai_regression.py::test_shanghai_3d_baseline` asserts these (tol ±5%/±10%). Nz=3 for CI speed (~25 s/case vs ~3 min at Nz=10). |
| `shanghai_3d_baseline.csv` (5/28, pre-G-fix) | 44.74% | 2.91% | full-ε fix, baseline roughness, **pre G-fix (col 48 G) + thin_plate s=0** | **SUPERSEDED by G-fix** — the G-convention + RBF-cubic fix (commits f6146db / 0d3b59a, 5/29) was NOT applied here. 44.74% is the pre-fix Nz=10 number. Kept for trajectory; do NOT cite as current. |
| `shanghai_3d_baseline_nz10_postGfix.csv` (6/02) | **21.49%** | **3.88%** | **post G-fix + RBF cubic s=0.1, Nz=10**, A+B low-Re early-exit | **CURRENT authoritative (Nz=10)** — 16/16 valid, 0 clip; G-fix cut Nz=10 dP from 44.74%→21.49% (−23 pp). max\|err_dP\|=30.5%, Q_net_rel<3.1e-4. |
| `shanghai_3d_baseline_post-fix-mass-cons-Nz10.csv` (5/15) | 47.02% | 2.22% | **ε double-halved (ε_full/4) bug** | OBSOLETE — superseded numbers, see `vault/.../regression_report.md` header |
| `shanghai_3d_baselineNz10_norris_1a.csv` (5/13) | 24.15% | 3.61% | **old f-multiplier era** (norris_1a still applied f≈1.46 friction) | OBSOLETE — `norris_1a` is now a baseline no-op alias (`solvers/roughness.py`); 24.15% is double-counted-friction, do NOT cite |
| other `shanghai_3d_baseline*Nz10*`, `*post-fix-norris1a*`, `*bhatti_shah*`, `*z20*`, `*fine_Nx40*` | — | — | mixed pre-ε-fix / experiment branches | OBSOLETE for headline; trajectory only |

## Current authoritative numbers (post G-fix + RBF cubic s=0.1, 2026-06-02)
- **3D LTNE conditional (water-temp prescribed), Nz=10: dP 21.49% / Q 3.88%** —
  `shanghai_3d_baseline_nz10_postGfix.csv`. CONDITIONAL prediction (experimental
  `T_Bout` for `Tb_prescribed`; water side frozen) — NOT a clean no-leak temp
  prediction. **This replaces the old 44.74%/2.91%**, which was the SAME pipeline
  *before* the G-convention + RBF-cubic surrogate fix (5/29); the G-fix cut Nz=10
  dP by 23 pp.
- **3D LTNE, Nz=3 (CI-pinned):  dP 17.32% / Q 3.74%** —
  `tests/test_shanghai_regression.py::test_shanghai_3d_baseline` (tol ±5%/±10%).
  Nz=3 for CI speed; ~4 pp below Nz=10 = grid effect.
- **Clean no-leak Q (paper baseline): Q_air 1.71%** — lumped dual-Nu ε-NTU
  (`validate_shanghai_lumped_dual_nu.py`), surrogate-independent.
- dP residual ~20% = entrance口径 + t=0.6/L=7 geometry differential, non-separable
  from Shanghai data (see `vault/reports/method/2026-05-15-Q-dP-state-audit-CN.md`
  §4 + memory `feedback_dp_gap_attribution`).

## To reproduce
- Nz=3 (fast, CI):  `validate_shanghai_3d_real.py --nz 3`  → 17.32/3.74
- Nz=10 (headline): `validate_shanghai_3d_real.py --nz 10` → 21.49/3.88
Both carry `pressure_clip_hits` + `pressure_state_valid`; Shanghai n_invalid=0.
The SIMPLE solver's A+B low-Re early-exit (default on) makes the water-side solve
~24× faster with <0.01% effect on dP/Q (verified 2026-06-02).
