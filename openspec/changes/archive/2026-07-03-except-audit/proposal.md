# Change: except-audit

## Why

2026-07-03 survey: 31 broad `except Exception` sites in production code,
~13 silent. Silent swallowing = features degrade with no trace (the class of
bug already fixed once in pipeline-stage-dedup: 2D extrap guard swallowed
AttributeError → extrapolation warnings silently disabled). Audited every
site in solvers/pipelines/controllers/domain/df_surrogate/optimization/core;
UI best-effort guards (session restore etc.) are by design and out of scope.

## What Changes

Behavior (4 sites — silent degradation now surfaces):
- `stages_3d._mass_weighted_T_out` / `_mass_weighted_h_out` /
  `_simple_mass_flow`: exception fallbacks (naive mean / ṁ=0) KEPT but now
  emit warnings — an exception there means `_face_flux_weights` broke and
  T_out/Q are quietly wrong.
- `optimizer_qnehvi` GP-fit failure: was verbose-gated print — production
  runs continued on an UN-FIT GP silently. Now always warns.

Narrowed (2 sites): stages_2d residual harvest → (AttributeError, TypeError);
Q_net arithmetic → TypeError.

Documented as deliberate (5 sites): orchestrator _Tee stream guards,
LTNE JIT warmup (both 2D+3D), sigmoid_field LUT-cache load, optimizer
progress_cb guards, _eval_worker penalty-tuple design (already err-carrying).

Verdict on the rest: not silent (traceback + user-visible warning + fallback
— zone config, Richardson Q, 1D fallback) or correct import guards
(sco2_props CoolProp).

## Impact

No numerics change → golden 2D/3D must stay bit-identical. Warnings appear
only on paths that were previously silently broken.
