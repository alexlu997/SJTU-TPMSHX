# Tasks

## 1. Config + deps
- [x] 1.1 `pytest.ini`: testpaths, --strict-markers, slow/fast markers, parallel + PYTHONHASHSEED doc
- [x] 1.2 requirements.txt: pytest-xdist

## 2. Measure + mark
- [x] 2.1 Full-suite `-n auto --dist loadscope --durations=40` run (PYTHONHASHSEED=0) — green: 1086 passed / 4 skipped / 1 xpassed in 261 s (vs 975 s serial)
- [x] 2.2 Mark measured whales `slow` by role: a0_richardson (79 s study), warmstart (53 s quality), parallel_matches_serial (49 s equivalence); invariant gates (conservation, asym δ=0) kept unmarked
- [x] 2.3 Collect verified: fast subset 1056/1091, slow 35 (was 32); bare `pytest` collects only sjtu_tpmshx/tests
- [x] 2.4 (was 3.2) Final full parallel gate green: 1086 passed in 242.8 s (4:02)

## 3. Docs
- [x] 3.1 CLAUDE.md: "Before claiming done" gate updated to `$env:PYTHONHASHSEED="0"; pytest sjtu_tpmshx/tests/ -q -n auto --dist loadscope`
