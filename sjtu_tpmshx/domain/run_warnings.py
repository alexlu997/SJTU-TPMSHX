"""Run-local closure warnings, independent of Python's global warning filters."""
from contextlib import contextmanager
from contextvars import ContextVar


_current = ContextVar('run_warnings', default=None)
_cache_records = ContextVar('cached_warnings', default=None)


def current_warnings():
    return _current.get()


@contextmanager
def warning_scope(records):
    """Install a run/worker's dict, or None for standalone warning behavior."""
    token = _current.set(records)
    try:
        yield records
    finally:
        _current.reset(token)


def record_warning(key, message, *, extrap=False):
    """True means this run owns the warning, including an already-seen key."""
    cached = _cache_records.get()
    if cached is not None:
        cached.setdefault(key, (message, extrap))
    records = _current.get()
    if records is None:
        return False
    records.setdefault(key, (message, extrap))
    return True


@contextmanager
def cache_warning_records(records):
    """Inside lru_cache, retain source notices even on a standalone cache miss.

    Recording here does not take ownership: standalone warning emission and
    its once-per-session registries still run at their original call sites.
    """
    token = _cache_records.set(records)
    try:
        yield records
    finally:
        _cache_records.reset(token)


def merge_warnings(target, sources):
    """Merge joined workers in caller-specified order, retaining first events."""
    if target is not None:
        for source in sources:
            for key, value in source.items():
                target.setdefault(key, value)
