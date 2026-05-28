"""Shanghai 16-case validation regression tests (opt-in, slow).

Per audit 2026-05-28 H3: previously only legacy 2D was guarded by CI
(via `validation/test_shanghai_regression.py` CLI form — now deleted
since its target `validation.legacy.validate_shanghai` was retired
2026-05-06). Now 3 production validation paths are covered:

  test_shanghai_2d_legacy    — `validation.legacy.validate_shanghai`
                               (legacy 2D, baseline 2026-04-17 refined grid)
  test_shanghai_3d_baseline  — `validation.validate_shanghai_3d_real`
                               (production 3D Nz=3 default)
  test_shanghai_lumped_paper — `validation.validate_shanghai_lumped_dual_nu`
                               (paper baseline ε-NTU cross-flow)

These tests are SLOW (~6 min each) and OPT-IN. Default pytest run skips
them. To enable:

    # Shell (env var)
    TPMSHX_RUN_SHANGHAI_REGRESSION=1 pytest tests/test_shanghai_regression.py -v

    # PowerShell
    $env:TPMSHX_RUN_SHANGHAI_REGRESSION = '1'
    pytest tests/test_shanghai_regression.py -v

Baseline values are pinned per the audit report (vault/reports/engineering/
2026-05-28-validation-correctness-audit-CN.html §H3). If a deliberate
solver change shifts numbers, update the BASELINE_* constants below and
the audit report's "current baseline" entries.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[1]
_DATA_ROOT = _ROOT.parent / 'data'

# Skip all tests in this module unless explicitly opted in.
_RUN_REG = os.environ.get(
    'TPMSHX_RUN_SHANGHAI_REGRESSION', '0').lower() in ('1', 'true', 'yes')

pytestmark = pytest.mark.skipif(
    not _RUN_REG,
    reason=("Slow Shanghai regression — set "
            "TPMSHX_RUN_SHANGHAI_REGRESSION=1 to enable"),
)


# ── Helpers ──────────────────────────────────────────────────────────

def _run_subprocess(module: str, *args, timeout: int = 1200) -> tuple:
    """Run module via subprocess, return (returncode, stdout, stderr)."""
    cmd = [sys.executable, '-u', '-m', module, *args]
    proc = subprocess.run(
        cmd, cwd=str(_ROOT), capture_output=True, text=True,
        timeout=timeout, encoding='utf-8', errors='replace',
    )
    return proc.returncode, proc.stdout, proc.stderr


def _rmsre_from_pct(arr) -> float:
    """RMSRE from a pre-computed percent-error array (sqrt(mean(e^2)))."""
    arr = np.asarray(arr, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    return float(np.sqrt(np.mean(arr ** 2)))


# ── 1. Legacy 2D Shanghai validation (retired 2026-05-06) ────────────

@pytest.mark.skip(reason=(
    "validation.legacy.validate_shanghai retired 2026-05-06 fix #5; "
    "production paths are now lumped_dual_nu (paper baseline) and "
    "3d_real (3D LTNE) — see two tests below. Kept as skip placeholder "
    "to document the deliberate scope change."))
def test_shanghai_2d_legacy():
    """[RETIRED] Legacy 2D Shanghai dP regression.

    The legacy module ``validation.legacy.validate_shanghai`` no longer
    exists in the codebase (retired 2026-05-06 fix #5). The original CLI
    form in ``validation/test_shanghai_regression.py`` was also deleted
    in this audit batch since its subprocess target was broken.

    Replaced by the two new tests below (3D + lumped). Marked skip so
    pytest discovery still surfaces the deliberate retirement.
    """
    pass


# ── 2. Production 3D Shanghai validation ─────────────────────────────

def test_shanghai_3d_baseline():
    """Production 3D Shanghai validation (Nz=3 default grid).

    Baselines (2026-05-28, post audit-quick-wins PR refactor):
      RMSRE_dP = 41.19%
      RMSRE_Q  =  2.85%

    Note: memory cites Nz=10 baseline (dP 44.74% / Q 2.91%) which is the
    production analysis grid. This test uses Nz=3 default for speed
    (each case ~25 s on Nz=3 vs ~3 min on Nz=10). If you want Nz=10 in
    CI, pass `--nz 10` and update baselines.

    Tolerance: ±3% relative on dP, ±10% relative on Q.
    """
    import pandas as pd
    rc, stdout, stderr = _run_subprocess(
        'validation.validate_shanghai_3d_real',
        '--suffix', '_pytest_h3',
        timeout=1500)
    assert rc == 0, (
        f"validate_shanghai_3d_real failed (rc={rc}):\n"
        f"STDERR:\n{stderr[-2000:]}")

    csv_path = _ROOT / 'validation' / 'shanghai_3d_baseline_pytest_h3.csv'
    assert csv_path.exists(), f"output CSV not found: {csv_path}"
    df = pd.read_csv(csv_path)

    rmsre_dP = _rmsre_from_pct(df['err_dP%'])
    rmsre_Q = _rmsre_from_pct(df['err_Q%'])

    BASELINE_DP = 41.19
    BASELINE_Q = 2.85
    tol_dp = 0.03
    tol_q = 0.10
    assert abs(rmsre_dP - BASELINE_DP) < BASELINE_DP * tol_dp, (
        f"3D RMSRE_dP drift: {rmsre_dP:.2f}% vs baseline "
        f"{BASELINE_DP}% (tol ±{tol_dp*100:.0f}%)")
    assert abs(rmsre_Q - BASELINE_Q) < BASELINE_Q * tol_q, (
        f"3D RMSRE_Q drift: {rmsre_Q:.2f}% vs baseline "
        f"{BASELINE_Q}% (tol ±{tol_q*100:.0f}%)")


# ── 3. Paper baseline ε-NTU lumped ───────────────────────────────────

def test_shanghai_lumped_paper():
    """Paper baseline ε-NTU lumped Q_air prediction (cross-flow primary).

    Baseline (memory project_lumped_dual_nu_baseline, 2026-04-29):
      Q_air RMSRE cross-flow ≈ 1.71%

    Cross-flow is the primary Shanghai topology (air ⊥ water). The
    `err_air_xf` CSV column is the matching error per case.

    Tolerance: ±10% relative on RMSRE.
    """
    import pandas as pd
    rc, stdout, stderr = _run_subprocess(
        'validation.validate_shanghai_lumped_dual_nu', timeout=600)
    assert rc == 0, (
        f"validate_shanghai_lumped_dual_nu failed (rc={rc}):\n"
        f"STDERR:\n{stderr[-2000:]}")

    csv_path = _DATA_ROOT / 'shanghai_lumped_dual_nu.csv'
    assert csv_path.exists(), f"output CSV not found: {csv_path}"
    df = pd.read_csv(csv_path)

    assert 'err_air_xf' in df.columns, (
        f"Expected 'err_air_xf' column missing. Got: {list(df.columns)}")
    rmsre = _rmsre_from_pct(df['err_air_xf'])

    BASELINE = 1.71
    tol = 0.10
    assert abs(rmsre - BASELINE) < BASELINE * tol, (
        f"Lumped Q_air RMSRE drift: {rmsre:.2f}% vs baseline "
        f"{BASELINE}% (tol ±{tol*100:.0f}%)")
