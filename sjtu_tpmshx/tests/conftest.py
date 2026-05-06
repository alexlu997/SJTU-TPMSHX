"""Pytest fixtures + sys.path bootstrap for sjtu_tpmshx tests.

Several test modules import top-level packages (`solvers`, `optimization`,
`df_fit`, `controllers`, `runs`, `ui`, etc.) without their own sys.path
boilerplate. When those tests are run individually (e.g. in subprocess
from a CI runner) they fail with ModuleNotFoundError because pytest's
auto-rootdir does not add `sjtu_tpmshx/` to sys.path.

Some test files do have the boilerplate (test_3d_direction_invariance.py,
test_compute_orchestrator.py, test_pressure_poisson_3d*.py). Running the
full suite in one process incidentally populates sys.path via those
modules, which masked the issue. Per-file subprocess runs surfaced it.

This conftest.py injects the package root once per pytest session.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # ...sjtu_tpmshx/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
