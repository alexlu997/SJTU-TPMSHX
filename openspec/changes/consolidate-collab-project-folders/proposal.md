## Why

External-collaboration / sizing-evaluation deliverables are scattered across the package instead of living in self-contained per-project folders. The sCO2 PCHE evaluation for partner **703** (which uses the **D-7-6** TPMS cell) has nine driver scripts strewn through `sjtu_tpmshx/validation/`; the **704** 10 kW air-cooler sizing has two scripts in `sjtu_tpmshx/runs/`. Only one project — `624-Retrodict` — is already a clean, self-contained folder (at the repo root). The result is "东一个文件西一个文件": a partner deliverable can't be found, handed off, or archived as a unit, and project drivers are visually indistinguishable from the shared solver V&V harness they sit next to.

This change consolidates each collaboration project into one folder under a new top-level `projects/` umbrella, using `624-Retrodict` as the template, **without moving any shared code**. It also writes down the layout convention so future project files don't re-scatter.

## What Changes

- Create `projects/` and move the three collaboration projects into it as self-contained folders:
  - `projects/624-Retrodict/` — relocate the existing root-level `624-Retrodict/` folder verbatim (工况回填: D-6-4 / D-7-5).
  - `projects/703-sCO2-D76/` — gather the **nine** 703/D-7-6 sCO2 driver scripts now in `sjtu_tpmshx/validation/`:
    `validate_sco2_703_3d.py`, `validate_sco2_703_coupled.py`, `validate_sco2_703_field.py`, `size_sco2_703.py`, `validate_sco2_precooler_phasec.py`, `precooler_nu_sensitivity.py`, `validate_sco2_d76.py`, `validate_sco2_d76_2d.py`, `validate_sco2_d76_dP_holdout.py`.
  - `projects/704-Aircooler-10kW/` — gather the **two** air-cooler scripts now in `sjtu_tpmshx/runs/`:
    `predict_aircooler_10kw.py`, `aircooler_conservative_check.py` (move together — the second imports the first as a sibling).
- Fix the one import line each moved script needs. Every mover anchors the package onto `sys.path` via `Path(__file__).resolve().parents[1]` — which was `sjtu_tpmshx/` and becomes `projects/` after the move. The repair: anchor to the package by repo-root-relative path, `parents[2] / "sjtu_tpmshx"`, so the script still resolves `from solvers ...` etc. from its new home. (`validate_sco2_d76.py` uses the equivalent `_HERE.parent.parent` form — same one-line fix.) Repo-root data reads such as `data/raw_data/D-7-6-sCO2/` are **depth-invariant** — `sjtu_tpmshx/validation/` and `projects/703-sCO2-D76/` are both exactly two levels under the repo root — so they are unaffected.
- Add a one-line `README.md` to each new project folder (what the project is, which cell/condition, how to run its scripts).
- Update the two stale entries in `PROJECT_MANUAL.md` (the `runs/` file index, lines 592–593) that name the moved air-cooler scripts, and add a short "projects/ — collaboration deliverables" pointer to the directory map.
- **Behavior-preserving relocation only.** No numerical code, no closure, no kernel, no test is touched. Each moved script produces the identical result it did before the move.

## Capabilities

### New Capabilities

- `collaboration-project-layout`: the convention that each external-collaboration / sizing-evaluation project lives in one self-contained `projects/<NNN>-<Name>/` folder; that shared solver code, the test suite, and the canonical Shanghai V&V never relocate into a project folder; and that a moved entry-point script stays runnable by anchoring its package import to the repo root rather than to a fixed directory depth.

## Impact

- **Moved (entry-point scripts + one folder), 11 scripts + 1 folder:** see the file list above. All are leaf scripts — `git grep` confirms nothing in the package or test suite imports any of them, so the moves break no import edge except each script's own package anchor (repaired in the same task).
- **Explicitly NOT moved (stays put):**
  - Package internals — `solvers/`, `pipelines/`, `df_surrogate/`, `design/`, `core/`, `domain/`. A project folder holds *drivers that call the package*, never package code. (Several `*_703` / sCO2 references live in `solvers/ltne_enthalpy_3d.py`, `pipelines/stages_3d.py`, `df_surrogate/predict.py` — these are shared closure features, not deliverables.)
  - **The entire `sjtu_tpmshx/tests/` suite** — `test_sco2_*.py` and friends exercise shared core; golden gates and the "run the full pytest suite" close-out workflow depend on their location. They stay. (User-confirmed.)
  - **`poc/`** — `tests/test_ltne_enthalpy_1d_optionB.py` does `import poc_1d_ltne_enthalpy_optionB`; the PoC is effectively test infrastructure, not a deliverable.
  - **The canonical Shanghai V&V** — `validate_shanghai_*.py` plus the `shanghai_*.csv` baselines. `CLAUDE.md` hard-references these paths as validation commands; relocating them would break documented workflows. They stay in `validation/`.
  - **The numerical V&V harness** — MMS / GCI / `phase_c_*` files in `validation/` are method verification, shared, not project-specific.
  - **`reports/`** — DF-surrogate method reports and figures, not collaboration deliverables.
- **Docs:** `PROJECT_MANUAL.md` directory map + `runs/` index updated; new per-folder `README.md` × 3.
- **No new dependencies. No behavior change.** Verification is per-script: run each moved script headless from its new location and confirm it still imports and produces its prior output.
- **Out of scope:** moving tests/poc/shanghai (decided against, above); any change to the scripts' physics or output; deleting or merging redundant `shanghai_3d_baseline_*.csv` snapshots (separate cleanup).
