# Change: split-pipelines

## Why

stages_3d.py (~2530 lines) and stages_2d.py (~1900 lines) are god-modules:
the cfg boundary (parse/build/run/finalize), the solver engine loop, flux
postprocessing, and grid builders all live in one file each. Navigation and
review cost is high; every external consumer (tests, runs/, validation/)
imports internals directly from the god-module.

## What Changes

Verbatim code moves (float order untouched), with FULL re-export from the
original modules so every existing `from pipelines.stages_3d import X`
keeps working:

- `pipelines/flux_3d.py` ← _resolve_ui_roughness, _face_flux_weights,
  _mass_weighted_T_out, _mass_weighted_h_out, _sco2_hv_local_field,
  _simple_mass_flow, _apply_roughness_KcF, _apply_roughness_h_v
- `pipelines/grid_3d.py` ← _resolve_axis_map, _build_zone_fields_3d,
  _build_grid_3d, _solver_spacings
- `pipelines/run_stack_3d.py` ← _seed_p_ref, _simple_tol_default,
  _apply_phase_flags, _apply_accel_flags, _prof_3d_enabled,
  _prof_res_trace, _run_two_simple_parallel, M4 partial-BC block,
  _conservation_diagnostics_3d, _run_3d_stack
- `pipelines/solve_2d.py` ← _enthalpy_balance_2d, _PipelineWindowShim,
  _compute_pressure_2d, _apply_zone_stats_2d, _compute_Q_richardson,
  _run_solvers
- stages_3d.py / stages_2d.py keep the cfg boundary (parse/build/
  run_solvers_cfg/finalize) + re-export blocks.

## Impact

- Import graph stays a DAG (flux_3d/grid_3d are leaves under solvers;
  run_stack_3d/solve_2d import them; stages_* import all and re-export).
- No numerics: golden 2D + 3D must stay bit-identical (PYTHONHASHSEED=0).
- External import surface unchanged (re-exports locked by the full suite —
  tests import ~15 internal names directly).
