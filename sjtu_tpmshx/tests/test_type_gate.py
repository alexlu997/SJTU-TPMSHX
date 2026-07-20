"""P2.2 standing gate: mypy (loose profile) is clean on the CORE surface.

Scope = mypy-core-files.txt at the repo root (envelope authority, the
compute_pipeline seam, domain config/result, configs loader, CLI, version
leaf). Widening the circle = append to that list and get it to zero in the
same commit. Config lives in pyproject [tool.mypy].
"""
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_PKG = _REPO / 'sjtu_tpmshx'


def test_mypy_core_surface_clean():
    r = subprocess.run(
        [sys.executable, '-m', 'mypy', '@../mypy-core-files.txt',
         '--config-file', '../pyproject.toml'],
        capture_output=True, text=True, timeout=600, cwd=str(_PKG))
    assert r.returncode == 0, "mypy findings:\n" + r.stdout[-2000:]
