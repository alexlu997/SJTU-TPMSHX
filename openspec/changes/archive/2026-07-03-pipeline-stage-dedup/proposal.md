# Change: pipeline-stage-dedup

## Why

2026-07-03 code-quality survey: the 2D/3D pipeline stages carry copy-pasted
non-kernel scaffolding (the comments even cross-reference each other):

- `_DOMAIN_MAX_M = 10.0` unit-slip firewall duplicated verbatim
  (`stages_2d` parse / `stages_3d._parse_inputs_3d_cfg`).
- Both-side surrogate training-domain guard duplicated — with DIVERGENT
  error handling: 2D swallowed `AttributeError` (a broken guard silently
  disabled extrapolation warnings), 3D swallowed `ImportError` only.
- `_safe_float` existed only in the 3D finalize; the 2D finalize used bare
  `float(raw['Q_total'])` which crashes on an explicit None headline.
- The `(epsilon, D_h, A_0)` props-slot triple re-derived identically at both
  ComputeResult assembly sites.

Kernel unification stays rejected (numba stencils genuinely differ) — this
extracts Qt-free, kernel-free glue only.

## What Changes

New `pipelines/_stage_common.py`: `validate_domain_dims`,
`surrogate_extrap_reasons` (ImportError → skip, ValueError propagates — the
2D AttributeError hush is removed), `safe_float`, `geometry_props`. Both
stages import it; 2D headline scalars now go through `safe_float`.

## Impact

- No numerics touched → golden 2D + 3D gates must stay bit-identical
  (checked before AND after).
- Behavior deltas (intentional, hardening only): 2D no longer silently
  swallows a broken extrap guard; 2D None headline → nan instead of
  TypeError crash.
