"""SJTU-TPMSHX solver package.

On first import, honour the ``TPMSHX_NUM_THREADS`` env var (the headless/script
knob for the parallel energy kernels). No-op unless the var is set, so normal
runs keep Numba's default (all cores). The GUI sets the count at runtime via
``solvers.threads.set_solver_threads``.
"""
from . import threads as _threads

_threads.init_from_env()
