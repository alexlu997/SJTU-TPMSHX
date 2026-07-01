## Why

**Phase 2 of the 3-phase restructure.** With the edges cleaned (Phase 1), the two real "junk drawers" inside the package are `runs/` and `validation/`:

- `sjtu_tpmshx/runs/` holds **27 loose scripts** mixing production entry-points, demos, diagnostics/probes, UI smoke-tests, and build/export tools — all flat, indistinguishable.
- `sjtu_tpmshx/validation/` mixes V&V **harness code** (`_harness.py`, `_metrics.py`, `_case_sets.py`, …), **runner scripts** (MMS, GCI, Shanghai, audits), **result data** (CSV + `.meta.json` sidecars + `.log`), and **status docs** (`_CSV_STATUS.md`, README) in one flat directory.

The module-boundary audit confirmed the *import layering* is already clean (no inversions, no cycles), so this phase is **taxonomy, not untangling** — group files by role into subdirectories, and repair the path/import references the moves break.

## What Changes

- **Split `runs/` into role subdirectories** (per the audit classification):
  - stays at `runs/` root: production entry-points (`run_3d_qnehvi_fast.py`, `run_production_qnehvi.py`, `run_production_qnehvi_parallel.py`, `polygon_calc.py`), the shared helpers (`_case_template.py`, `_smoke_boot.py`, `__init__.py`), and the existing `_out/` (golden gates — CLAUDE-referenced), `archive/`, `cfd_asym/`.
  - `runs/demos/` ← `demo_3d_air_air.py`, `demo_3d_cube_air_air.py`, `demo_3d_cube_volume.py` (+ fold in the root-level `examples/demo_vis_3d_interactive.py`).
  - `runs/diagnostics/` ← `asym_a0_convergence.py`, `asym_geometry_scan.py`, `asym_target_scan.py`, `asym_porosity_preview.py`, `asym_geometry_report_html.py`.
  - `runs/smokes/` ← `smoke_3d_eval.py`, `smoke_ui_2d_pipeline.py`, `smoke_ui_3d_modes.py`, `smoke_ui_3d_pipeline.py`, `smoke_ui_offscreen.py`, `smoke_ui_screenshots.py`.
  - `runs/tools/` ← `asym_build_cfd_design_xlsx.py`, `asym_build_cfd_worklist_xlsx.py`, `asym_plan_to_html.py`, `render_3d_styles.py`.
- **Layer `validation/`**:
  - `validation/harness/` ← the `_*.py` infrastructure (`_harness`, `_metrics`, `_case_sets`, `_mms_driver`, `_order_fit`, `_provenance`).
  - `validation/cases/` ← the runner scripts (`mms_*.py`, `phase_c_gci.py`, `audit_3d_conservation.py`, `audit_partial_b_ltne.py`, `validate_shanghai_3d_real.py`, `validate_shanghai_aligned.py`, `validate_shanghai_lumped_dual_nu.py`, `verify_pareto_3d.py`).
  - `validation/data/results/` ← result CSVs (the 5 kept `shanghai_3d_baseline*.csv`, `mms_*`, `phase_c_*`, `validation_results.csv`) + their `.meta.json` sidecars + `.log` files.
  - `validation/docs/` ← `README.md`, `_CSV_STATUS.md`.
- **Repair every reference the moves break** (enumerated at execution start, same method as the `projects/` move): the scripts' `sys.path` package anchor (depth changes by one → `parents[1]`→`parents[2]`); intra-validation package imports (`from validation._harness` → `from validation.harness._harness`); sibling-helper imports in `runs/` (`_case_template`, `_smoke_boot`); the `python -m validation.validate_shanghai_3d_real` module path in `tests/test_shanghai_regression.py`; the result-CSV paths in that test; and the `CLAUDE.md` validation commands.
- **Update docs**: `CLAUDE.md` validation-command paths, `PROJECT_MANUAL.md` directory map + the `runs/` / `validation/` file indexes.

## Capabilities

### Modified Capabilities

- `repository-structure`: add the package-internal taxonomy requirements — scripts grouped by role under `runs/<role>/`; validation separated into `harness/` (reusable code) vs `cases/` (runners) vs `data/` (results) vs `docs/`; and the rule that moving a script re-anchors its package `sys.path` insert to the repo/package root rather than a fixed depth.

## Impact

- **High file-count, mechanical churn; behavior-preserving** — like the `projects/` move, a `sys.path` relocation cannot change numerical output, only break imports. Verification is per-script import-test + the full pytest suite + golden gates.
- **CLAUDE-referenced paths change** (validation commands change; golden-gate dir stays put): user approved updating them.
- **Known couplings to handle** (discovered in the audit; full edge-list re-derived at execution): `from validation.size_sco2_703`-style package imports were already fixed when those drivers left in the `projects/` change; remaining intra-`validation` package imports (`_harness`/`_metrics`/`_case_sets`/`_provenance`) need the `harness.` prefix; `test_shanghai_regression.py` invokes runners via `python -m validation.<module>` and reads result CSVs by path.
- **Gates:** every moved script imports from its new path; `pytest sjtu_tpmshx/tests/ -q` green (incl. the opt-in `TPMSHX_RUN_SHANGHAI_REGRESSION=1` regression); golden 2D/3D bit-identical.
- **Out of scope:** code-internal splits (`stages_3d.py` → Phase 3); any change to what a script computes.
