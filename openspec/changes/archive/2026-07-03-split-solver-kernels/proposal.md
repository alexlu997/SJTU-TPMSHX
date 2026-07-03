# Change: split-solver-kernels

## Why

The three largest solver files interleave numba kernels with the Python
driver layer: simple_solver.py (~2100), ltne_energy_3d.py (~2110),
simple_solver_3d.py (~1800). Kernels are pure JIT functions with zero class
state — a natural seam. Splitting isolates the hot numerics for review and
cuts each file roughly in half.

## What Changes

Verbatim line-slice moves (byte-verified against HEAD blobs), full
re-export from the original modules (tests import kernels directly, e.g.
`from solvers.simple_solver import _sweep_u_jit_df`):

- `solvers/_kernels_simple_2d.py` ← all 2D SIMPLE @njit kernels +
  pressure-Poisson infra (+ _WALL_PENALTY_* constants).
- `solvers/_kernels_simple_3d.py` ← all 3D SIMPLE @njit kernels.
- `solvers/_kernels_ltne_3d.py` ← all 3D LTNE @njit kernels (incl.
  inline='always' helpers, moved together with their callers as numba
  requires). ε-split contract text untouched (verbatim move).
- Originals keep: grid builders, solver classes, python drivers
  (solve_full_domain_3d etc.), warmup, and a commented re-export block.

## Impact

- Compiled IR per kernel unchanged (same decorators/flags); numba cache
  recompiles once per new module. Golden 2D/3D must stay bit-identical
  (PYTHONHASHSEED=0); rb-equivalence and asym δ=0 bit-identity tests
  provide additional coverage.
- External import surface unchanged via re-exports.
