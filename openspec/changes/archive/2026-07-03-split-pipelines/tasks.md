# Tasks

## 1. 3D split
- [x] 1.1 flux_3d.py (246) + grid_3d.py (159) + run_stack_3d.py (2024) — line-slice verbatim, all 7 moved segments git-blob IDENTICAL
- [x] 1.2 stages_3d.py 2713→357; re-export block (54 externally-reachable names verified)

## 2. 2D split
- [x] 2.1 solve_2d.py (1235) — 6 segments git-blob verbatim
- [x] 2.2 stages_2d.py 2001→781; re-export block (10-name probe OK)

## 3. Gates
- [x] 3.1 test_import_dag + pipeline wiring locks 22/22; run_stack_3d/solve_2d pull no stages_* (no cycles)
- [x] 3.2 Golden 2D + 3D bit-identical (PASS both, PYTHONHASHSEED=0)
- [x] 3.3 Full parallel suite green — 1095 passed / 4 skipped / 1 xpassed in 5:33
- [x] 3.4 PROJECT_MANUAL §6.10 rewritten to the 8-module layout table
