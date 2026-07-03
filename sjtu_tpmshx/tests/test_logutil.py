"""logutil locks (openspec print-to-logging).

The load-bearing property: the handler resolves sys.stdout PER RECORD, so
the GUI solve-log viewer's ``contextlib.redirect_stdout`` capture sees log
records exactly as it saw the old ``print()`` output. A plain
``StreamHandler(sys.stdout)`` would bind the original stream and silently
bypass the capture — that regression is what these tests pin.
"""
from __future__ import annotations

import contextlib
import io
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from logutil import get_logger  # noqa: E402


def test_logger_output_visible_under_redirect_stdout():
    log = get_logger('tests.capture')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        log.info("[capture-check] hello %d", 42)
    assert "[capture-check] hello 42" in buf.getvalue()


def test_default_format_is_bare_message():
    log = get_logger('tests.fmt')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        log.info("[fmt-check] plain")
    # Bare message + newline — no level/name/timestamp prefix by default.
    lines = [l for l in buf.getvalue().splitlines() if 'fmt-check' in l]
    assert lines == ["[fmt-check] plain"]


def test_level_filter_suppresses_info():
    log = get_logger('tests.level')
    root = logging.getLogger('tpmshx')
    old = root.level
    try:
        root.setLevel(logging.ERROR)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            log.info("[level-check] should not appear")
            log.error("[level-check] should appear")
        out = buf.getvalue()
        assert "should not appear" not in out
        assert "should appear" in out
    finally:
        root.setLevel(old)


def test_no_duplicate_into_stdlib_root(capfd=None):
    """tpmshx root has propagate=False — records must not reach the stdlib
    root logger (which could double-print once an app configures it)."""
    root = logging.getLogger('tpmshx')
    get_logger('tests.prop')          # ensure configured
    assert root.propagate is False
    assert any(type(h).__name__ == '_StdoutHandler' for h in root.handlers)
