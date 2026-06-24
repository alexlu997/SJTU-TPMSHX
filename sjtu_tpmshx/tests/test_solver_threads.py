"""Numba thread-count control helper (`solvers/threads.py`)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numba
import solvers.threads as th


def test_clamp_to_max_and_min():
    mx = th.max_threads()
    assert mx >= 1
    assert th.set_solver_threads(10 ** 9) == mx      # over-cap clamps to max
    assert th.get_solver_threads() == mx
    assert th.set_solver_threads(0) == 1             # under clamps to 1
    assert th.set_solver_threads(-5) == 1
    th.set_solver_threads(mx)                         # restore


def test_set_exact_value_within_range():
    mx = th.max_threads()
    target = max(1, mx // 2)
    assert th.set_solver_threads(target) == target
    assert th.get_solver_threads() == target
    assert numba.get_num_threads() == target
    th.set_solver_threads(mx)


def test_init_from_env_honors_project_var(monkeypatch):
    mx = th.max_threads()
    monkeypatch.setenv("TPMSHX_NUM_THREADS", "1")
    assert th.init_from_env() == 1
    # invalid → no change (stays at last value, here 1)
    monkeypatch.setenv("TPMSHX_NUM_THREADS", "garbage")
    assert th.init_from_env() == 1
    monkeypatch.delenv("TPMSHX_NUM_THREADS", raising=False)
    th.set_solver_threads(mx)
