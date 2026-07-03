# Change: robustness-hardening

## Why

2026-07-03 robustness survey (15 findings): NaN/inf typed into input
fields passed BOTH validation gates; a diverged SIMPLE solve displayed
Q/dP indistinguishably from a good one; `validate_geometry` was defined +
tested but never called in production; `ComputeConfig.from_json` did zero
validation (script/optimizer path bypassed every UI gate); the 3D run
path had no memory guard beyond a blind Yes/No dialog; corrupt session
JSON silently reverted the workspace AND was clobbered by the next save;
closeEvent never joined the worker.

## What Changes

1. **Finite/positive at three choke points**: `_validate_required_widgets`
   (window strict boundary — temp fields exempt from the raw-text sign
   check, °C may be negative), the blur handler (`Must be finite`), and
   new `ComputeConfig.validate()` called by `from_dict`/`from_json`
   (direct dataclass construction stays permissive for tests).
2. **First-class convergence verdict**: `ComputeResult.converged`; 2D =
   coupling converged AND no SIMPLE stall; 3D = no SIMPLE stall AND final
   LTNE pass converged. Non-converged runs get a prepended user warning +
   诊断摘要 row; default True keeps old payloads permissive.
3. **3D cell cap**: `_run_3d_stack` raises above 2M cells (override via
   `TPMSHX_MAX_CELLS_3D` / `cfg['max_cells_3d']`); the UI large-grid
   dialog now shows a working-RAM estimate.
4. **validate_geometry wired into `_preflight_grid`** (hard nonsense →
   critical modal, soft findings merge into the preflight report);
   preflight core-field parse failures abort instead of running against
   a phantom L=0 domain; `T_s_init` 0.0-K coercion fixed + 150–2000 K
   sanity range.
5. **closeEvent**: bounded `waitForDone(3000)` after the cooperative
   cancel. **Session/preset corruption**: quarantined to
   `<name>.corrupt-<ts>` instead of silent default + clobber.

## Impact

No numerics: golden 2D/3D bit-identical. New locks:
tests/test_robustness_gates.py (13). Behavior deltas are all
reject-earlier / warn-louder.
