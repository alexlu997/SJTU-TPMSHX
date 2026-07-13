---
description: Pre-"done" verification gate for SJTU-TPMSHX — full pytest suite (+ golden bit-identical diff). Run before claiming work is complete.
argument-hint: "[golden]  (add 'golden' to also run the bit-identical field gate)"
allowed-tools: Bash(cd:*), Bash(python:*), Bash(python -m pytest:*), Bash(pytest:*)
---

Run the solver's **"before claiming done"** verification and report PASS/FAIL **with evidence**. Do not claim the work is complete, commit, or open a PR until the pytest gate passes. Evidence before assertions — show the real counts, never "mostly passing".

All commands run from the repo root `/d/Postgraduate/Homogenize/SJTU-TPMSHX`. Use `python -u` so stdout doesn't block-buffer and look hung.

## 1. Full pytest suite (the standing gate — always run)

The golden gate alone does NOT cover every closure branch, so the full suite is mandatory.

Parallel is the default (~4.5 min vs ~16 min serial). `PYTHONHASHSEED=0` must be set **in the shell**, not in pytest config — the 3D pipeline output is hash-seed sensitive and cannot be pinned from `pytest.ini`.

```powershell
$env:PYTHONHASHSEED="0"; pytest sjtu_tpmshx/tests/ -q -n auto --dist loadscope
# ⚠ 128核服务器上 -n auto 会超额订阅卡死（实测 2026-07-13）：用 scripts/run_tests_server.ps1（-n 64 worksteal + 顺序敏感模块串行，~11 min）
```

Serial equivalent (git-bash):

```bash
cd /d/Postgraduate/Homogenize/SJTU-TPMSHX && PYTHONHASHSEED=0 python -u -m pytest sjtu_tpmshx/tests/ -q
```

- Expected: all pass (≈1245+ passed, a few skipped — count grows with the suite; anything FAILED is the signal, not the total). Report the exact **passed / failed / skipped** counts.
- If anything FAILS: list the failing test ids + the assertion line. Diagnose — do not hand back a green verdict on a red suite.

## 2. Golden bit-identical gate (only when `golden` arg is passed, around a specific change)

`runs/_out/` is gitignored — the baseline json is **local and must be captured BEFORE the change** to mean anything. Workflow:

```bash
# capture baseline BEFORE editing (stash/checkout the pre-change tree first):
python -u sjtu_tpmshx/runs/_out/_golden_2d.py golden_2d.json
python -u sjtu_tpmshx/runs/_out/_golden_3d.py golden_3d.json
# ...make the change, then diff:
python -u sjtu_tpmshx/runs/_out/_golden_2d.py --check golden_2d.json   # → GOLDEN-2D: PASS (bit-identical) / FAIL
python -u sjtu_tpmshx/runs/_out/_golden_3d.py --check golden_3d.json   # → GOLDEN-3D: PASS / FAIL
```

- A FAIL = output fields changed. Classify it as **(a) a real regression** (fix it) or **(b) an intentional re-baseline** (state which fields moved and why). Never silently accept a FAIL.
- If no baseline json exists, say so — a golden check with no pre-change baseline is meaningless; don't fabricate a pass.

## 3. Validation cases (run when a closure / surrogate / solver path changed)

```bash
# Lumped ε-NTU dual-Nu (current paper baseline):
python -u sjtu_tpmshx/validation/cases/validate_shanghai_lumped_dual_nu.py
# 3D real solver (SIMPLE, mass-flux inlet) — the surrogate-backend gate:
python -u sjtu_tpmshx/validation/cases/validate_shanghai_3d_real.py
```

## Gotchas (baked in so they aren't re-derived each run)

- Run from the **repo root**, not `sjtu_tpmshx/`. A `cd sjtu_tpmshx` followed by a relative path drifts the persistent cwd and breaks later `solvers` imports.
- On `ModuleNotFoundError: solvers`, prepend `PYTHONPATH="$PWD/sjtu_tpmshx"` to the command.
- Don't run other heavy jobs (a second validation, a polling loop) concurrently — parallel numba/Qt processes cause flaky hard-exits that look like test failures but aren't.

## Report format

One line per gate (✅/❌ + counts or PASS/FAIL hashes), then a single final verdict line: `READY` only if pytest is fully green.
