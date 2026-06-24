"""Runtime control of the Numba thread pool used by the parallel energy kernels
(`@njit(parallel=True)` red-black GS) and any other parallel `@njit` code.

Three control layers, all funnelling through `set_solver_threads`:

  * ``NUMBA_NUM_THREADS`` (native Numba env) — the HARD CAP, fixed before Numba
    initialises. Set it in the shell/launcher to bound the pool (e.g. leave
    cores free). The active count can never exceed it.
  * ``TPMSHX_NUM_THREADS`` (project env) — the runtime active count for
    headless / script / batch runs (validation, optimizer) where there is no
    GUI. Read once at import via `init_from_env`. Unset → Numba default
    (all cores, up to the cap).
  * `set_solver_threads(n)` — the runtime knob the GUI "CPU cores" spinbox calls.

Note: the count is GLOBAL to Numba, so it governs every `parallel=True` kernel
(energy GS, pressure assembly, …), not only the energy solve.
"""
import os

import numba


def max_threads() -> int:
    """Hard upper bound = Numba's compiled pool size (all logical cores, or the
    `NUMBA_NUM_THREADS` env if it was set before Numba initialised)."""
    return int(numba.config.NUMBA_NUM_THREADS)


def get_solver_threads() -> int:
    """The active thread count Numba will use for the next parallel kernel."""
    return int(numba.get_num_threads())


def set_solver_threads(n: int) -> int:
    """Set the active thread count, clamped to ``[1, max_threads()]``.

    Returns the value actually applied (after clamping)."""
    n = max(1, min(int(n), max_threads()))
    numba.set_num_threads(n)
    return n


def init_from_env() -> int:
    """Apply ``TPMSHX_NUM_THREADS`` if set (the headless/script knob). No-op on
    unset/invalid → leaves the Numba default. Returns the active count."""
    raw = os.environ.get("TPMSHX_NUM_THREADS", "").strip()
    if raw:
        try:
            return set_solver_threads(int(raw))
        except ValueError:
            pass
    return get_solver_threads()
