## ADDED Requirements

### Requirement: Source files avoid god-file accumulation

A single source file SHOULD NOT grow into a god-file that mixes top-level orchestration with dozens of helper functions. When it does, the cohesive helper clusters SHALL be extracted into sibling modules, leaving the public entry point as a thin orchestrator. Cohesive large files (solver kernels, UI panels, audits) and intentional framework compositions (the Qt mixin `main.py`) are exempt.

#### Scenario: Helper clusters are extracted from a pipeline god-file

- **WHEN** a pipeline module accumulates many pure helper functions alongside its stage flow
- **THEN** the helpers are moved into sibling modules (e.g. `*_fields`, `*_flux`, `*_solve`) and the stage module imports them, keeping its public entry thin

### Requirement: A code-layer refactor is behavior-preserving

Extracting helpers or renaming modules for readability SHALL NOT change any numerical result. Such a refactor SHALL be gated on the golden 2D/3D snapshots remaining bit-identical and the Shanghai baseline Δp/Q unchanged; if bit-identity cannot be preserved, the refactor is abandoned rather than the golden re-baselined.

#### Scenario: Extraction preserves the golden

- **WHEN** a helper cluster is moved out of `stages_3d.py`
- **THEN** the golden 3D snapshot is bit-identical to the pre-split snapshot; if it differs, that extraction is reverted

#### Scenario: Golden is never re-baselined to fit a refactor

- **WHEN** a readability refactor would change the golden numbers
- **THEN** the refactor is abandoned, not accommodated by editing the golden baseline
