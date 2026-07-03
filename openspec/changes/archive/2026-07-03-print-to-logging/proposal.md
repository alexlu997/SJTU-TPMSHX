# Change: print-to-logging

## Why

~250 `print()` calls across the production packages: no level filtering, no
optional timestamps, and stdout block-buffering causes the recurring
"python -u or the run looks hung" trap. Zero `logging` usage repo-wide.

## What Changes

1. `sjtu_tpmshx/logutil.py`: `get_logger(name)` under a `tpmshx` root.
   - Handler resolves **sys.stdout per record** (`_StdoutHandler`) so the
     GUI solve-log viewer's `redirect_stdout` capture keeps working — this
     is the load-bearing constraint of the whole change.
   - Default format = bare message (output byte-compatible with the old
     prints); `TPMSHX_LOG_TS=1` adds `HH:MM:SS level name:` prefix.
   - Level via `TPMSHX_LOG_LEVEL` (default INFO). Per-record flush retires
     the block-buffering trap for converted output.
2. Convert library-path prints in solvers/pipelines/df_surrogate/
   optimization/core/ui to `_log.info/warning/error`, preserving message
   text and existing `verbose` gates.

## Exclusions (prints stay)

- Inside `@njit` functions — numba nopython cannot call logging.
- `if __name__ == '__main__':` / CLI entry paths — printed output IS the UX.
- runs/, validation/, tests/, demo scripts.

## Impact

Default output unchanged (same strings, same stream). No numerics → golden
2D/3D bit-identical. New capabilities: env-level filter, timestamps, flush.
