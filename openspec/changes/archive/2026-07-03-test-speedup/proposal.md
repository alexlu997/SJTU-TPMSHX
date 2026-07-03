# Change: test-speedup

## Why

Full local pytest suite (the repo's "done" gate) takes ~16 min single-process
(1086 passed / 975 s). Survey findings (2026-07-03, three explore agents):

- pytest-xdist not used; suite looks parallel-safe (tempfile-unique paths,
  monkeypatch env per-process, read-only shared baselines, no os.chdir).
- No pytest config file at all: `slow` / `fast` markers unregistered, nothing
  pins collection away from `.claude/worktrees/` repo copies.
- Several heavyweight real-solve test modules are UNMARKED, so the local
  `-m "not slow"` fast path diverges from what CI runs.
- PYTHONHASHSEED footgun: 3D pipeline output is hash-seed sensitive (CI pins
  `PYTHONHASHSEED=0` job-level); a local parallel run without it risks
  golden-diff flakiness, and nothing documents this outside ci.yml.

## What Changes

1. Add `pytest.ini`: `testpaths`, `--strict-markers`, register `slow`/`fast`,
   document the parallel invocation + PYTHONHASHSEED requirement.
2. Add `pytest-xdist` to requirements.txt.
3. Mark measured whales `slow` by ROLE, not raw duration: research-study /
   redundant-equivalence tests (>~45 s with cheap sibling coverage) get the
   mark; invariant gates (strict energy conservation, asym δ=0 bit-identity)
   stay in CI regardless of cost. Measured on the full `-n auto` durations
   run: `test_a0_richardson_thin_side_beats_coarse` (79 s),
   `test_warmstart_not_worse_than_baseline` (53 s),
   `test_parallel_matches_serial` (49 s). The originally-suspected
   `test_solver_efficiency` / `test_simpler_coupling_2d` did not even make
   the top-40 — left unmarked.
4. Update `CLAUDE.md` gate command to the parallel invocation.

## Non-goals

- CI workflow stays single-process (`-m "not slow" --timeout=600
  --timeout-method=thread`); parallelizing CI interacts with the
  thread-mode-timeout hang diagnosis and is deferred.
- No solver/UI code changes; no golden re-baselining.

## Impact

- Full local gate: ~16 min → target ≤ ~6 min wall on this box.
- Local fast path `-m "not slow"` matches CI's subset semantics.
