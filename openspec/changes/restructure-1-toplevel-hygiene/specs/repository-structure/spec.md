## ADDED Requirements

### Requirement: Directory and module names use lowercase-snake

Repository directories and Python module/package names SHALL use lowercase letters with underscores (e.g. `df_surrogate`, `opt_runs`), except the sanctioned `projects/<NNN>-Name/` deliverable folders (which use the `NNN-Name` convention) and conventional uppercase root markers (`README.md`, `LICENSE`). Ad-hoc capitalization (e.g. a `Pic/` directory) is a violation.

#### Scenario: A new directory follows the convention

- **WHEN** a new directory is added under the repo root or inside the package
- **THEN** it is named lowercase-snake (or `NNN-Name` if it is a `projects/` deliverable), not PascalCase or mixedCase

#### Scenario: Stray-cased directory is corrected

- **WHEN** a directory like `Pic/` exists
- **THEN** it is removed or renamed to a lowercase-snake equivalent

### Requirement: The package root holds source, not loose assets or caches

The package root (`sjtu_tpmshx/`) SHALL NOT contain loose binary assets (images, lookup-table caches) or tooling lockfiles. Branding/image assets live under an `assets/` subtree; regeneratable caches live next to the code that writes them (the loader's `cache_dir`); tooling artifacts live with their tool (e.g. `.claude/`).

#### Scenario: Branding asset placement

- **WHEN** the UI needs a logo or banner image
- **THEN** the image is stored under `sjtu_tpmshx/assets/` and referenced by a path anchored on the package root, not loose at the package root

#### Scenario: Orphan cache is not committed at the package root

- **WHEN** a lookup-table or similar cache file appears at the package root with no loader referencing it there
- **THEN** it is treated as orphan output and removed (the live cache regenerates into the loader's `cache_dir`)

### Requirement: Runnable scripts guard execution with `__main__`

Every Python file intended to be run as a script SHALL guard its top-level executable body with `if __name__ == "__main__":` (delegating to a `main()` function), so that importing the module has no side effects (no file writes, no solves).

#### Scenario: Importing a script module is side-effect-free

- **WHEN** a script module such as a validation runner is imported (not executed)
- **THEN** no output file is written and no computation runs — the body executes only under the `__main__` guard

### Requirement: Regeneratable outputs are gitignored, not committed

Regeneratable run outputs (optimizer run dirs, rendered figures, profiling snapshots, scratch CSVs) SHALL be gitignored rather than tracked, except a deliberately-kept reference explicitly documented in `.gitignore` (e.g. one archived `opt_runs/` reference run). Non-regeneratable reference data (experimental truth tables, canonical validation baselines, pre-built surrogate coefficients) MAY be tracked.

#### Scenario: A new optimizer run is not committed

- **WHEN** an optimizer or demo produces a fresh output directory
- **THEN** it is covered by a `.gitignore` rule and stays out of version control

#### Scenario: An intentionally kept reference is documented

- **WHEN** a single output run is deliberately tracked as an archived reference
- **THEN** the `.gitignore` carries a comment explaining the exception, so the tracked-vs-ignored state is not ambiguous
