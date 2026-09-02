# Fast-tier suite runner — DEV INNER LOOP ONLY, NOT THE VERIFICATION GATE.
#
# P3.1 (2026-07-20): excludes the 21 `heavy` tests (call >= 30s in the
# durations census upgrade/logs/p31-durations.log — 1.7% of tests carrying
# 89% of call-compute; manifest: sjtu_tpmshx/tests/_fast_tier_manifest.txt,
# applied by tests/conftest.py at collection). Everything else is identical
# to run_tests_server.ps1. Measured wall ~1 min vs ~19 min full.
#
# "Before claiming done" remains the FULL suite (run_tests_server.ps1) —
# the heavy set is exactly the 3D conservation/BC/asym integration tests
# that catch real physics regressions. Fast green means "keep typing",
# never "ship".
#
# `slow` marker semantics untouched (CI skip-list, hand-curated).

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
$py = Join-Path $repo ".venv\Scripts\python.exe"

$venvHome = (Select-String -Path (Join-Path $repo ".venv\pyvenv.cfg") -Pattern '^home = (.+)$').Matches[0].Groups[1].Value
if ($venvHome -match 'Anaconda') {
    throw "venv is built from Anaconda ($venvHome) — PySide6 will crash (0xc0000139). Rebuild: C:\Python312\python.exe -m venv .venv"
}

$env:PYTHONHASHSEED = "0"
$env:OMP_NUM_THREADS = "1"; $env:OPENBLAS_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"; $env:NUMEXPR_NUM_THREADS = "1"
$env:NUMBA_NUM_THREADS = "1"
$env:QT_QPA_PLATFORM = "offscreen"

Set-Location $repo

Write-Host "=== FAST TIER (-m 'not heavy') — dev feedback, NOT the gate ===" -ForegroundColor Yellow
& $py -u -m pytest sjtu_tpmshx/tests/ -q -n 32 --dist worksteal -m "not heavy"

if ($LASTEXITCODE -eq 0) {
    Write-Host "FAST TIER green — run scripts/run_tests_server.ps1 before claiming done." -ForegroundColor Green
} else {
    Write-Host "FAST TIER FAILED — pytest exit=$LASTEXITCODE" -ForegroundColor Red
    exit 1
}
