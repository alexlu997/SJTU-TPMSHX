## ADDED Requirements

### Requirement: Each collaboration project is one self-contained folder

Every external-collaboration / sizing-evaluation project SHALL live in a single self-contained folder `projects/<NNN>-<Name>/`, where `<NNN>` is the project code and `<Name>` a short descriptive slug (mirroring the existing `624-Retrodict` layout). A project's driver scripts, project-specific inputs, and per-project README SHALL reside together in that folder, so the project can be found, handed off, or archived as a unit.

#### Scenario: A project's deliverables are grouped

- **WHEN** a collaboration project (e.g. 703's D-7-6 sCO2 PCHE evaluation) has driver scripts
- **THEN** all of those scripts live under one `projects/<NNN>-<Name>/` folder, not interleaved with shared solver V&V under `sjtu_tpmshx/validation/` or `sjtu_tpmshx/runs/`

#### Scenario: New partner work has an obvious home

- **WHEN** a new collaboration or sizing evaluation begins
- **THEN** it is placed in a new `projects/<NNN>-<Name>/` folder rather than as loose files inside the package

### Requirement: Shared code, tests, and canonical V&V never relocate into a project folder

The project folders SHALL contain only entry-point scripts that *call* the package. Shared solver code (`solvers/`, `pipelines/`, `df_surrogate/`, `design/`, `core/`, `domain/`), the entire `sjtu_tpmshx/tests/` suite, the test-imported `poc/` fixtures, and the canonical Shanghai V&V (`validate_shanghai_*.py` and the `shanghai_*` baselines) SHALL remain in their existing locations.

#### Scenario: Shared closure feature is not a deliverable

- **WHEN** package code (e.g. `solvers/ltne_enthalpy_3d.py`) contains project-named strings because a project exercises that closure
- **THEN** that code stays in the package and is NOT moved into the project folder

#### Scenario: Tests and Shanghai V&V stay put

- **WHEN** the reorg moves a project's driver scripts
- **THEN** `sjtu_tpmshx/tests/`, `poc/`, and `validate_shanghai_*.py` / `shanghai_*.csv` are untouched, so golden gates, full-suite pytest discovery, and the documented Shanghai validation commands keep working

### Requirement: A moved entry-point script stays runnable from its new location

A driver script relocated into a project folder SHALL anchor its package import to the repository root rather than to a fixed parent depth, so it resolves `from solvers ...` (and siblings) from the new path. Repository-root-relative data reads, being depth-invariant for folders at the same level, SHALL continue to resolve without edits.

#### Scenario: Package import survives the move

- **WHEN** a script that did `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))` (resolving to `sjtu_tpmshx/`) is moved into `projects/<NNN>-<Name>/`
- **THEN** its anchor is changed to `Path(__file__).resolve().parents[2] / "sjtu_tpmshx"` and the script imports the package successfully when run from the new location

#### Scenario: Repo-root data read is unaffected

- **WHEN** a moved script reads a repository-root path such as `data/raw_data/D-7-6-sCO2/...`
- **THEN** the read still resolves, because the new folder sits at the same depth below the repository root as the old one

### Requirement: The relocation is behavior-preserving

Moving a project's files SHALL NOT change any numerical result, closure, kernel, or test. The only permitted edit is the per-script package-import anchor required by the move; running a moved script from its new location SHALL produce the same output it produced before.

#### Scenario: Output is identical after the move

- **WHEN** a moved driver script is run headless from `projects/<NNN>-<Name>/`
- **THEN** its output matches the pre-move reference capture, and the full `pytest sjtu_tpmshx/tests/` suite stays green
