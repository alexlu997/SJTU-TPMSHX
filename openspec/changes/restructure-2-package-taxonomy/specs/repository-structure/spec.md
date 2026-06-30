## ADDED Requirements

### Requirement: Run scripts are grouped by role

Scripts under `sjtu_tpmshx/runs/` SHALL be grouped by role into subdirectories — production entry-points (and shared helpers / golden gates) at the `runs/` root, and `runs/demos/`, `runs/diagnostics/`, `runs/smokes/`, `runs/tools/` for the respective categories — rather than all flat in `runs/`.

#### Scenario: A new demo script is placed by role

- **WHEN** a new demonstration script is added
- **THEN** it goes in `runs/demos/`, not loose in `runs/` alongside production entry-points

#### Scenario: Production entry-points stay shallow

- **WHEN** a user looks for the runnable production scripts (optimizer drivers, the polygon pipeline)
- **THEN** they are at the `runs/` root, not buried in a role subdirectory

### Requirement: Validation separates harness, runners, data, and docs

`sjtu_tpmshx/validation/` SHALL be layered: reusable test infrastructure in `validation/harness/`, runner scripts in `validation/cases/`, produced result data in `validation/data/results/`, and status/README docs in `validation/docs/` — not flat in one directory.

#### Scenario: Harness code is importable as a subpackage

- **WHEN** a runner needs shared validation utilities
- **THEN** it imports them from `validation.harness.<module>` (a real subpackage with `__init__.py`)

#### Scenario: Result data is separated from code

- **WHEN** a validation runner writes a result CSV
- **THEN** it lands under `validation/data/results/`, not next to the runner source

### Requirement: A relocated script re-anchors its package path

When a script is moved to a different directory depth, it SHALL re-anchor its `sys.path` package insert to resolve the package/repo root from its new location, rather than relying on a fixed `parents[N]` that assumed the old depth. Moving a script SHALL NOT change what it computes.

#### Scenario: Moved script still imports the package

- **WHEN** a script that inserted `Path(__file__).resolve().parents[1]` (the package root) is moved one level deeper
- **THEN** its anchor is updated to `parents[2]` (or an equivalent package-root resolution) and the script imports successfully and produces its prior output from the new location
