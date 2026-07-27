"""Central logging for the sjtu_tpmshx production packages (print→logging,
openspec change print-to-logging, 2026-07-03).

Usage::

    from sjtu_tpmshx.logutil import get_logger
    _log = get_logger(__name__)
    _log.info("[3D grid] %s", summary)

Design constraints (do not "simplify" these away):

1. **Handler writes to sys.stdout, resolved PER RECORD.** The GUI solve-log
   viewer captures solver output via ``contextlib.redirect_stdout`` in
   ``controllers/compute_orchestrator.py``. A plain
   ``StreamHandler(sys.stdout)`` binds the stream object at handler-creation
   time, so redirected runs would silently miss every log record. The
   ``_StdoutHandler`` below reads ``sys.stdout`` dynamically, keeping the
   capture path byte-identical with the old ``print()`` behaviour.

2. **Default format is the bare message.** Existing output carries its own
   tags (``[3D grid]``, ``[Coupling n]``, ``[qNEHVI]`` …) and scripts /
   humans eyeball it; the default render is therefore indistinguishable
   from the old prints. Set ``TPMSHX_LOG_TS=1`` for
   ``HH:MM:SS level name: message``.

3. **Level from env** ``TPMSHX_LOG_LEVEL`` (DEBUG/INFO/WARNING/ERROR,
   default INFO). Solver per-iteration traces keep their existing
   ``verbose`` gates — the env level filters on top, it does not replace
   them.

4. **StreamHandler flushes per record**, which retires the "python -u or
   stdout block-buffers and the run looks hung" trap for everything that
   goes through logging.
"""
from __future__ import annotations

import logging
import os
import sys

_ROOT_NAME = "tpmshx"
_configured = False


class _StdoutHandler(logging.StreamHandler):
    """StreamHandler whose stream is ALWAYS the current sys.stdout.

    Required so ``contextlib.redirect_stdout`` (GUI solve-log capture)
    sees log records; see module docstring #1.
    """

    def __init__(self):
        # Parent __init__ assigns self.stream; the property below ignores it.
        super().__init__(sys.stdout)

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, value):  # noqa: D401 - deliberate no-op
        pass


def _configure_root():
    global _configured
    if _configured:
        return
    root = logging.getLogger(_ROOT_NAME)
    if not root.handlers:
        h = _StdoutHandler()
        if os.environ.get("TPMSHX_LOG_TS", "0") == "1":
            fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
            h.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
        else:
            h.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(h)
    level_name = os.environ.get("TPMSHX_LOG_LEVEL", "INFO").upper()
    root.setLevel(getattr(logging, level_name, logging.INFO))
    root.propagate = False   # never duplicate into the stdlib root logger
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Namespaced logger under the ``tpmshx`` root (configured on first use).

    ``name`` is usually ``__name__``; a leading package path is kept so
    ``TPMSHX_LOG_LEVEL`` filtering can later grow per-module knobs via the
    standard logging hierarchy. A leading ``sjtu_tpmshx.`` is stripped so
    logger names stay ``tpmshx.<subsystem>...`` regardless of import style —
    the taxonomy must not encode packaging history (P1.8b F2: modules now
    execute under package-qualified names; without this, every logger would
    have become ``tpmshx.sjtu_tpmshx.*`` and name-anchored consumers broke).
    """
    _configure_root()
    return logging.getLogger(f"{_ROOT_NAME}.{name.removeprefix('sjtu_tpmshx.')}")
