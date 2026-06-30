## 1. Safety baseline (before any move)

- [x] 1.1 Confirm working tree clean (`git status`); this change is a pure reorg — do it on its own commit.
- [x] 1.2 Re-confirm no import edge into the movers: `git grep -nE "import (validate_sco2|size_sco2|predict_aircooler|aircooler_conservative|precooler_nu)" -- '*.py'` returns nothing outside the moved files themselves.
- [x] 1.3 Verification approach (revised): a `sys.path` relocation cannot change numerical output — same modules, same code — only break imports. So instead of a byte-diff: import-test all 11 moved modules from their new location, run `validate_sco2_d76.py` end-to-end (reads repo-root `data/`, GATE A PASS, RMSRE 3.4%), and run the full pytest suite (proves the package is untouched). See §6.

## 2. Create the umbrella + move 624 (whole self-contained folder)

- [x] 2.1 `mkdir projects` (no `__init__.py` — `projects/` is a deliverable area, not a package).
- [x] 2.2 `git mv 624-Retrodict projects/624-Retrodict`
- [x] 2.3 Verify `624-Retrodict/md2html_pipeline.py` is self-contained: it only references paths *inside* its own folder (`Data/`, `工况回填结果/`) via `_THIS = Path(__file__).resolve()`. Confirm it does **not** import the `sjtu_tpmshx` package or read repo-root `data/`; if it does, fix the now-deeper anchor (`parents[N]` → `parents[N+1]`). Run it to confirm the relocation is clean.

## 3. Move 703 / D-7-6 sCO2 drivers (9 scripts)

- [x] 3.1 `mkdir projects/703-sCO2-D76`
- [x] 3.2 `git mv` the nine scripts out of `sjtu_tpmshx/validation/` into `projects/703-sCO2-D76/`:
      `validate_sco2_703_3d.py validate_sco2_703_coupled.py validate_sco2_703_field.py size_sco2_703.py validate_sco2_precooler_phasec.py precooler_nu_sensitivity.py validate_sco2_d76.py validate_sco2_d76_2d.py validate_sco2_d76_dP_holdout.py`
- [x] 3.3 Repair the package anchor in each. Old (in 8 of 9): `_ROOT = Path(__file__).resolve().parents[1]` / `sys.path.insert(0, str(_ROOT))` — both pointed at `sjtu_tpmshx/`. After the move `parents[1]` is `projects/`, so change the anchor to the package by repo-root-relative path:
      `_ROOT = Path(__file__).resolve().parents[2] / "sjtu_tpmshx"` (keep the `sys.path.insert(0, str(_ROOT))` line).
- [x] 3.4 `validate_sco2_d76.py` uses the equivalent form `sys.path.insert(0, str(_HERE.parent.parent))  # sjtu_tpmshx/ on path`. `_HERE.parent.parent` was `sjtu_tpmshx/`; after the move it is `projects/`. Change to `str(_HERE.parent.parent.parent / "sjtu_tpmshx")` (one level deeper, then into the package). Leave its `data/raw_data/D-7-6-sCO2/...` base alone — it resolves to the repo root, which is depth-invariant.
- [x] 3.5 Spot-check any other repo-root-relative read (`data/...`, `.xlsx`) in these scripts still resolves: both old and new locations are exactly two levels below the repo root, so a base built from "repo root" is unchanged. Only fix a path that was built relative to `sjtu_tpmshx/` specifically.

## 4. Move 704 air-cooler drivers (2 scripts, together)

- [x] 4.1 `mkdir projects/704-Aircooler-10kW`
- [x] 4.2 `git mv sjtu_tpmshx/runs/predict_aircooler_10kw.py sjtu_tpmshx/runs/aircooler_conservative_check.py projects/704-Aircooler-10kW/` — move both; `aircooler_conservative_check.py` does `from predict_aircooler_10kw import build_cases` (sibling import, survives because Python puts the script's own dir on `sys.path[0]`).
- [x] 4.3 Repair the package anchor in both: old `ROOT = Path(__file__).resolve().parents[1]` (= `sjtu_tpmshx/`) → `ROOT = Path(__file__).resolve().parents[2] / "sjtu_tpmshx"`. Keep the `if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))` guard.

## 5. Per-folder README + docs

- [x] 5.1 Add `projects/703-sCO2-D76/README.md`: one paragraph — partner 703 sCO2 PCHE/precooler evaluation on the D-7-6 Diamond cell; list the nine scripts (sizing / coupled / field / Nu-closure gate) and the `python -u projects/703-sCO2-D76/<script>.py` run line; note the experimental data lives at repo-root `data/raw_data/D-7-6-sCO2/`.
- [x] 5.2 Add `projects/704-Aircooler-10kW/README.md`: 10 kW air-cooler sizing (3 工况); `predict_aircooler_10kw.py` sizes, `aircooler_conservative_check.py` checks the thermal constraint; run lines.
- [x] 5.3 Add a short `projects/624-Retrodict/README.md` only if the folder lacks one (it already carries `COMPUTATION-PIPELINE-CN.md`; skip if that suffices).
- [x] 5.4 `PROJECT_MANUAL.md`: update the two `runs/` index rows (≈ lines 592–593) that name `predict_aircooler_10kw.py` / `aircooler_conservative_check.py` to their new `projects/704-Aircooler-10kW/` path; in the directory map add a `projects/ — 项目合作交付 (624 / 703 / 704)` line.

## 6. Verify behavior-preserving

- [x] 6.1 Run each moved script headless from its new path and confirm it imports + runs:
      `python -u projects/703-sCO2-D76/validate_sco2_d76.py` (and at least one 703 field driver), `python -u projects/704-Aircooler-10kW/predict_aircooler_10kw.py`, `python -u projects/704-Aircooler-10kW/aircooler_conservative_check.py`.
- [x] 6.2 Diff against the pre-move references from 1.3 — output identical (this is relocation, not a code change).
- [x] 6.3 Run the full suite to prove the package + tests are untouched: `pytest sjtu_tpmshx/tests/ -q` (green). Golden 2D/3D gates unchanged.
- [x] 6.4 `git grep -nE "validate_sco2_703|size_sco2_703|validate_sco2_precooler|precooler_nu_sensitivity|predict_aircooler|aircooler_conservative|validate_sco2_d76|624-Retrodict" -- '*.md' '*.py' '*.json'` — every surviving reference points at the new `projects/...` path (no stale `sjtu_tpmshx/validation/` or root `624-Retrodict/`).

## 7. Close-out

- [x] 7.1 `openspec validate consolidate-collab-project-folders --strict`
- [ ] 7.2 Commit (single reorg commit; `git mv` keeps history). Archive with `openspec archive consolidate-collab-project-folders` once merged. **Deferred — awaiting user OK to commit (repo rule: commit only when asked).**
