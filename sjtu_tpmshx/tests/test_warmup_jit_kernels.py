"""E1 (full-debug audit 2026-06-28): the module-import JIT warmup must compile
the DEFAULT-path staggered LTNE kernels, not just the legacy cell-centered one.

conservative_ltne defaults True -> the production 3D LTNE solve dispatches
_gs_full_chunk_3d_stag (or _stag_rb for >30k cells). _warmup_jit() only called
the legacy _gs_full_chunk_3d, so the first real 3D run still paid the multi-
second numba compile of the stag kernel — defeating the warmup's purpose.

Verified in a CLEAN subprocess: a numba dispatcher's `.signatures` is populated
per-process only when the function is actually specialized. Import alone (which
runs _warmup_jit) must leave the stag kernels with >=1 signature.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _probe(symbol: str) -> subprocess.CompletedProcess:
    code = (
        "from solvers import ltne_energy_3d as M;"
        f"sig=getattr(M.{symbol}, 'signatures', None);"
        "print('NSIG', 0 if sig is None else len(sig))"
    )
    return subprocess.run([sys.executable, '-c', code],
                          capture_output=True, text=True, cwd=str(ROOT))


def _nsig(symbol: str) -> int:
    r = _probe(symbol)
    line = [ln for ln in r.stdout.splitlines() if ln.startswith('NSIG')]
    assert line, f"probe failed for {symbol}: {r.stderr[-800:]}"
    return int(line[0].split()[1])


def test_warmup_compiles_default_stag_kernel():
    assert _nsig('_gs_full_chunk_3d_stag') >= 1, \
        "default-path staggered LTNE kernel not pre-compiled by _warmup_jit"


def test_warmup_compiles_stag_rb_kernel():
    assert _nsig('_gs_full_chunk_3d_stag_rb') >= 1, \
        "red-black staggered LTNE kernel (>30k cells) not pre-compiled"


def test_warmup_still_compiles_legacy_cc_kernel():
    # Regression: the legacy cc kernel must stay warmed too (fallback path).
    assert _nsig('_gs_full_chunk_3d') >= 1
