# Change: docs-sync-manual

## Why

2026-07-03 docs-drift survey: PROJECT_MANUAL.md still documented the retired
compute orchestration (`runs/run_calculation.py` 2038行 / `run_calculation_3d.py`
2891行 / `batch_runner.py` — none exist; compute moved to `pipelines/stages_2d/`
`stages_3d` + `controllers/compute_orchestrator` in the restructure batches),
omitted two of ten Main_Menu mixins (appearance, session_presets), carried a
stale runs/ inventory (scripts since moved to demos/ smokes/ diagnostics/
tools/ cfd_asym/ archive/), and never described the asym offset-isosurface
family (`solvers/asym_split.py`, `asym_geometry.py`, `solvers/envelope.py`,
`df_surrogate/kappa_asym.py` + `ingest_cfd_kappa.py`, `runs/cfd_asym/`) or the
df backend registry. README test command was 67-file/serial era.

## What Changes

Docs only (+ one stale docstring):
- PROJECT_MANUAL.md: architecture diagram layer 3 runs/→pipelines/; new §6.10
  `pipelines/`; §6.11 runs/ rewritten to the actual inventory; solvers section
  gains envelope/asym_split/asym_geometry; df_surrogate section gains
  backend/gamma_df/smooth_df + kappa_asym/ingest_cfd_kappa; mixins table +
  MRO + line counts refreshed; tests section → ~120 files + pytest.ini note +
  parallel run example; directory map gains pipelines/ + cfd_asym/ + archive/.
- README.md: test commands → parallel form; solvers layout line + asym modules.
- controllers/__init__.py docstring: Phase 4 DomainValidator TODO → done.

## Impact

No code behavior change. No spec deltas (docs describe existing capabilities).
