# Tasks

## 1. Kernel moves (verbatim, byte-verified vs HEAD blobs)
- [x] 1.1 _kernels_simple_2d.py (862) + simple_solver.py 2116→1285 (19 names re-exported)
- [x] 1.2 _kernels_simple_3d.py (834, 18 kernels) + simple_solver_3d.py 1797→998
- [x] 1.3 _kernels_ltne_3d.py (1178, 20 kernels incl. inline='always' helpers) + ltne_energy_3d.py 2111→971; ε contract untouched (pure line move)

## 2. Gates
- [x] 2.1 getattr probes (23/19/26 names) + py_compile + cross-module smoke solves converged (2D (True,20), 3D (True,10), LTNE warmup OK)
- [x] 2.2 Golden 2D + 3D bit-identical (PASS both, PYTHONHASHSEED=0)
- [x] 2.3 Full parallel suite green — 1095 passed / 4 skipped / 1 xpassed in 5:08
- [x] 2.4 PROJECT_MANUAL solvers section: kernel-module note + refreshed line counts
