"""Worker-process thread caps — deliberately a LIGHT leaf module (os only).

Why this file exists (HANDOFF §6b / candidate C, fixed 2026-07-21):

The multi-seed orchestrator spawns workers with ProcessPoolExecutor("spawn").
A spawned child must IMPORT the module that defines any callable it receives
before it can unpickle it — and ``optimization.parallel_runner`` imports
numpy at module top. OpenBLAS reads ``OPENBLAS_NUM_THREADS`` at library-load
time (numpy import), so a cap set inside the worker FUNCTION body — however
early — runs after the library already sized its pool. The old guard was
therefore a timing no-op for OpenBLAS, and its list was missing
``NUMBA_NUM_THREADS`` entirely (this project's 2D hotspots are numba
``parallel=True`` kernels, not BLAS).

The fix: pass ``set_worker_thread_caps`` from THIS module as the executor's
``initializer``. Unpickling it imports only this file (os), so the caps land
in the child's environment before numpy/numba ever load. Keep this module
free of numpy/scipy/numba/torch imports — that is its entire purpose.
"""
import os

_CAP_KEYS = ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
             'NUMEXPR_NUM_THREADS', 'NUMBA_NUM_THREADS')


def set_worker_thread_caps() -> None:
    """Hard-pin per-worker library thread pools (default 1).

    Hard set, not setdefault: the guard exists to stop oversubscription, so
    a stray ``OMP_NUM_THREADS=8`` exported for the parent shell must NOT
    multiply into M seeds × q_batch workers × 8 threads. Raising the cap is
    an explicit act: set ``TPMSHX_WORKER_THREADS=<n>``.
    """
    n = os.environ.get('TPMSHX_WORKER_THREADS', '1')
    try:
        n = str(max(1, int(n)))
    except ValueError:
        n = '1'
    for k in _CAP_KEYS:
        os.environ[k] = n
