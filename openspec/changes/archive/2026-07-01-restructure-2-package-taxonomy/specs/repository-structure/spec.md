## ADDED Requirements

### Requirement: Run scripts are grouped by role

Scripts under `sjtu_tpmshx/runs/` SHALL be grouped by role into subdirectories — production entry-points (and shared helpers / golden gates) at the `runs/` root, and `runs/demos/`, `runs/diagnostics/`, `runs/smokes/`, `runs/tools/` for the respective categories — rather than all flat in `runs/`.

#### Scenario: A new demo script is placed by role

- **WHEN** a new demonstration script is added
- **THEN** it goes in `runs/demos/`, not loose in `runs/` alongside production entry-points

#### Scenario: Production entry-points stay shallow

- **WHEN** a user looks for the runnable production scripts (optimizer drivers, the polygon pipeline)
- **THEN** they are at the `runs/` root, not buried in a role subdirectory

### Requirement: Validation separates reusable harness from runner scripts

`sjtu_tpmshx/validation/` SHALL group its code by role: reusable test infrastructure in `validation/harness/` and runner scripts in `validation/cases/`, rather than flat in one directory. Result data (CSV baselines, `.meta.json` sidecars, logs) and status docs remain discoverable at the `validation/` root, and a runner that moves into `cases/` keeps writing its outputs to that root (its output-path anchor is adjusted so the result location does not change).

#### Scenario: Harness code is importable as a subpackage

- **WHEN** a runner or test needs shared validation utilities
- **THEN** it imports them from `validation.harness.<module>` (a real subpackage with `__init__.py`)

#### Scenario: Runner output location is preserved across the move

- **WHEN** a runner is moved from `validation/` into `validation/cases/`
- **THEN** its result CSV still lands at the `validation/` root (the output path is re-anchored), so the baseline files and the tests that read them are unaffected

### Requirement: A relocated script re-anchors its package path

When a script is moved to a different directory depth, it SHALL re-anchor its `sys.path` package insert to resolve the package/repo root from its new location, rather than relying on a fixed `parents[N]` that assumed the old depth. Moving a script SHALL NOT change what it computes.

#### Scenario: Moved script still imports the package

- **WHEN** a script that inserted `Path(__file__).resolve().parents[1]` (the package root) is moved one level deeper
- **THEN** its anchor is updated to `parents[2]` (or an equivalent package-root resolution) and the script imports successfully and produces its prior output from the new location
