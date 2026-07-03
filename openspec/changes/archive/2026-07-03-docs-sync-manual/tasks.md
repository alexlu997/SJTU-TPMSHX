# Tasks

## 1. PROJECT_MANUAL.md
- [x] 1.1 Architecture diagram + data-flow: runs/run_calculation* → pipelines/stages_*
- [x] 1.2 New §6.10 pipelines/ (stages_2d, stages_3d + helpers); §6.11 runs/ actual inventory (root/demos/smokes/diagnostics/tools/cfd_asym/archive); drop batch_runner
- [x] 1.3 solvers: envelope.py, asym_split.py, asym_geometry.py entries
- [x] 1.4 df_surrogate: backend/gamma_df/smooth_df registry + kappa_asym/ingest_cfd_kappa (accuracy checked against module docstrings)
- [x] 1.5 mixins table (+appearance, +session_presets), MRO, line counts, panel_vis_3d
- [x] 1.6 tests §6.13: ~120 files, pytest.ini, parallel run example; renumber 6.11→6.12→6.13
- [x] 1.7 Directory map: pipelines/, cfd_asym/, archive/, tests count

## 2. README.md + misc
- [x] 2.1 Test commands → parallel xdist form (matches CLAUDE.md gate)
- [x] 2.2 solvers layout line: asym_split/asym_geometry
- [x] 2.3 controllers/__init__.py: Phase 4 TODO → done (domain/validator.py)
