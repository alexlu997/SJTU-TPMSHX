# Tasks

## 1. Extract
- [x] 1.1 `pipelines/_stage_common.py`: validate_domain_dims / surrogate_extrap_reasons / safe_float / geometry_props
- [x] 1.2 stages_2d: firewall + extrap guard + headline safe_float + props triple → shared
- [x] 1.3 stages_3d: firewall + extrap guard + local _safe_float def + props triple → shared

## 2. Gates
- [x] 2.1 Golden 2D + 3D --check PASS before refactor (baseline valid)
- [x] 2.2 Golden 2D + 3D --check PASS after refactor (bit-identical)
- [x] 2.3 Full parallel pytest suite green — 1086 passed / 4 skipped / 1 xpassed in 4:04
