"""Pytest fixtures + sys.path bootstrap for sjtu_tpmshx tests.

Several test modules import top-level packages (`solvers`, `optimization`,
`df_fit`, `controllers`, `runs`, `ui`, etc.) without their own sys.path
boilerplate. When those tests are run individually (e.g. in subprocess
from a CI runner) they fail with ModuleNotFoundError because pytest's
auto-rootdir does not add `sjtu_tpmshx/` to sys.path.

Some test files do have the boilerplate (test_3d_direction_invariance.py,
test_compute_orchestrator.py, test_solve_full_3d.py). Running the
full suite in one process incidentally populates sys.path via those
modules, which masked the issue. Per-file subprocess runs surfaced it.

This conftest.py injects the package root once per pytest session.

2026-05-09 Phase Qt-headless fix: also forces ``QT_QPA_PLATFORM=offscreen``
*before* any test module imports PySide6. Without this, full-suite runs
on Windows would crash with exit code 9 once the first test instantiated
QApplication on the default 'windows' platform plugin (no display avail).
The individual Qt test files set this same env var via
``os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')``, but `setdefault`
is a no-op when Qt has already been initialised by a prior import in the
same process. Setting it here at conftest load time guarantees it lands
before any PySide6 module is imported.
"""
import os
import sys
from pathlib import Path

# Must run BEFORE any PySide6 import — pytest loads conftest.py at session
# start, before collecting tests, so this env var is in place for every
# subsequent test_*.py import.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]   # ...sjtu_tpmshx/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# 2026-05-09 — Eagerly instantiate a process-wide QApplication so that:
#   1. The first Qt-touching test doesn't pay the platform-plugin
#      bootstrap cost mid-test (improves CI determinism).
#   2. A prior test that calls QCoreApplication([]) (e.g.
#      test_compute_orchestrator) cannot leave an incompatible application
#      instance that blocks the next test from creating a real QApplication.
#   3. The 'offscreen' platform is locked in BEFORE any test_*.py decides
#      whether to call QApplication([]) — guarantees no GUI window pops.
# Skipped silently when PySide6 is unavailable (rare; sentinel CI envs).
try:
    from PySide6.QtWidgets import QApplication as _QApp
    if _QApp.instance() is None:
        # The argv list intentionally includes the offscreen flag so the
        # platform plugin selection is unambiguous even if a sub-test
        # fiddles with os.environ later in the session.
        _QApp(['pytest', '-platform', 'offscreen'])
except Exception:
    pass
