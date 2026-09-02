# Full-suite runner for the 128-core EPYC server (E:\LWH).
#
# Strategy (v2, 2026-07-13): single phase, `-n 64 --dist worksteal`.
#   * `pytest.ini` recommends `--dist loadscope`, but that pins whole modules
#     to one worker. The duration outliers cluster in a few modules
#     (test_conservation_3d_energy: 1291s+1103s serialized = 40-min tail;
#     test_partial_bc_ghost_b: 1576s; test_asym_porosity_3d: 1607s), so
#     loadscope's wall-clock floor is the biggest module sum (~40 min).
#     worksteal distributes per-test and rebalances stragglers → floor is
#     the slowest single TEST (~21.5 min on this 2.25 GHz Zen 3).
#   * loadscope's purpose (per pytest.ini) is fixture EFFICIENCY — keeping
#     module-scoped surrogate/MMS fixtures on one worker. Under worksteal
#     they rebuild on several workers: redundant compute, not a correctness
#     issue, and 128 cores absorb it.
#   * A v1 of this script split by the `slow` marker — WRONG: the marker is
#     the CI skip-list, not a duration census. The heaviest tests
#     (conservation_3d_energy, partial_bc_ghost_b, asym_porosity_3d) are
#     unmarked, so the "fast" phase inherited the whole 40-min tail.
#
# Every test grid is far below TPMSHX_PARALLEL_THRESHOLD (200k cells; max
# observed is 20^3 = 8k), so numba prange never engages — one compute thread
# per worker is CORRECT, and default thread counts thrash (measured:
# 7 CPU-hours wasted at -n 32 with 128-thread pools per worker).
#
# The venv MUST be built from C:\Python312 (python.org CPython), never
# Anaconda — PySide6's abi3 forwarder crashes (0xc0000139) otherwise.

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
$py = Join-Path $repo ".venv\Scripts\python.exe"

$venvHome = (Select-String -Path (Join-Path $repo ".venv\pyvenv.cfg") -Pattern '^home = (.+)$').Matches[0].Groups[1].Value
if ($venvHome -match 'Anaconda') {
    throw "venv is built from Anaconda ($venvHome) — PySide6 will crash (0xc0000139). Rebuild: C:\Python312\python.exe -m venv .venv"
}

$env:OMP_NUM_THREADS = "1"; $env:OPENBLAS_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"; $env:NUMEXPR_NUM_THREADS = "1"
$env:NUMBA_NUM_THREADS = "1"
# Headless server — Qt tests need the offscreen platform plugin.
$env:QT_QPA_PLATFORM = "offscreen"

Set-Location $repo

Write-Host "=== Full suite (-n 64 worksteal) ===" -ForegroundColor Cyan
& $py -u -m pytest sjtu_tpmshx/tests/ -q -n 64 --dist worksteal --durations=15

if ($LASTEXITCODE -eq 0) {
    Write-Host "READY — suite green." -ForegroundColor Green
} else {
    Write-Host "FAILED — pytest exit=$LASTEXITCODE" -ForegroundColor Red
    exit 1
}
