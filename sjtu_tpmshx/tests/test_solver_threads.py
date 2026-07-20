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


# ── P3.2: recommendation + one-shot advisory ─────────────────────────────────

def test_recommend_within_bounds():
    rec = th.recommend_solver_threads()
    assert isinstance(rec, int)
    assert 1 <= rec <= min(64, th.max_threads())


def _fake_big_box(monkeypatch, active=128, cap=128, rec=32):
    """Simulate an unpinned many-core machine without touching numba."""
    monkeypatch.setattr(th, "get_solver_threads", lambda: active)
    monkeypatch.setattr(th, "max_threads", lambda: cap)
    monkeypatch.setattr(th, "recommend_solver_threads", lambda: rec)
    monkeypatch.setattr(th, "_advised_default_pool", False)
    monkeypatch.delenv("TPMSHX_NUM_THREADS", raising=False)


class _Capture:
    """logutil's package root sets propagate=False (deliberate), so pytest's
    caplog (root-logger handler) never sees these records — attach a handler
    directly to the module logger instead."""

    def __init__(self):
        import logging
        self.records = []
        # logutil namespaces under the `tpmshx.` root (get_logger docstring)
        self._lg = logging.getLogger('tpmshx.solvers.threads')
        self._h = logging.Handler()
        self._h.emit = self.records.append

    def __enter__(self):
        self._lg.addHandler(self._h)
        return self

    def __exit__(self, *exc):
        self._lg.removeHandler(self._h)


def test_advisory_fires_once_on_unpinned_default(monkeypatch):
    _fake_big_box(monkeypatch)
    with _Capture() as cap:
        assert th.warn_if_default_pool(1_000_000) == 32
        assert th.warn_if_default_pool(1_000_000) == 32   # second call silent
    hits = [r for r in cap.records if "TPMSHX_NUM_THREADS" in r.getMessage()]
    assert len(hits) == 1
    assert "Advisory only" in hits[0].getMessage()


def test_advisory_silent_when_pinned_or_small(monkeypatch):
    # user pinned the env → silent
    _fake_big_box(monkeypatch)
    monkeypatch.setenv("TPMSHX_NUM_THREADS", "32")
    with _Capture() as cap:
        th.warn_if_default_pool(1_000_000)
    assert not cap.records
    # active lowered below cap (GUI spinbox) → silent
    _fake_big_box(monkeypatch, active=16, cap=128, rec=32)
    with _Capture() as cap:
        th.warn_if_default_pool(1_000_000)
    assert not cap.records
    # small machine: cap == rec → silent
    _fake_big_box(monkeypatch, active=8, cap=8, rec=8)
    with _Capture() as cap:
        th.warn_if_default_pool(1_000_000)
    assert not cap.records
