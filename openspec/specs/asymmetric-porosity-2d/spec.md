# asymmetric-porosity-2d Specification

## Purpose
TBD - created by archiving change add-2d-asym-porosity. Update Purpose after archive.
## Requirements
### Requirement: 2D LTNE kernel accepts distinct per-side void fractions

The 2D LTNE solver `solve_full_domain` SHALL accept distinct per-side single-channel void fractions ε_A and ε_B and route them through both Gauss-Seidel kernel variants (the lexicographic `_gs_full_chunk` and the red-black `_gs_full_chunk_rb`), weighting each fluid's convective transport by its own channel void fraction. It SHALL NOT raise `NotImplementedError` when ε_A ≠ ε_B.

#### Scenario: Asymmetric split solves without error

- **WHEN** `solve_full_domain` is called with ε_A ≠ ε_B that satisfy ε_A + ε_B ≤ ε at every cell
- **THEN** the solver runs to convergence and returns fluid-A, fluid-B, and solid temperature fields without raising

#### Scenario: Per-side weighting is applied in the kernel

- **WHEN** a cell has ε_A > ε_B
- **THEN** fluid A's advective coefficient in that cell is scaled by ε_A and fluid B's by ε_B (not by a shared ε/2)

#### Scenario: Over-allocation is still rejected

- **WHEN** ε_A + ε_B exceeds ε at any cell
- **THEN** `solve_full_domain` raises `ValueError` (the existing total-void guard is preserved)

### Requirement: Symmetric input is bit-identical to the legacy path

For the symmetric case (ε_A = ε_B = ε/2, i.e. offset δ=0) the solver SHALL produce output fields bit-identical to the existing single-`eps_f_arr` path, so that the 2D golden gate and the Shanghai 2D baseline are unchanged.

#### Scenario: Zero offset reproduces the golden baseline

- **WHEN** the offset δ=0 (symmetric porosity, no per-side override supplied)
- **THEN** every output field hash equals the pre-change 2D golden baseline (bit-identical)

### Requirement: Per-side void fractions conserve total porosity

The per-side void fractions derived from the offset δ SHALL sum to the configured total porosity ε at every cell, so the split neither creates nor destroys void fraction.

#### Scenario: Geometry split preserves the total

- **WHEN** the geometry split ratio s = split_A is applied to total ε
- **THEN** ε_A = ε·s and ε_B = ε·(1−s), and ε_A + ε_B = ε at every cell

### Requirement: 2D pipeline derives per-side porosity from the offset δ

The 2D pipeline SHALL derive ε_A and ε_B from the offset-isosurface δ (`cfg['delta_levelset']`) using the same geometry split ratio as the 3D pipeline, and pass them to `solve_full_domain`. When δ=0 it SHALL pass the symmetric ε/2 to both sides.

#### Scenario: Nonzero offset drives an asymmetric run

- **WHEN** `cfg['delta_levelset'] ≠ 0`
- **THEN** the pipeline computes (ε_A, ε_B) = (ε·split_A, ε·(1−split_A)) and the 2D run uses asymmetric per-side porosity end-to-end

#### Scenario: Zero offset uses the symmetric path

- **WHEN** `cfg['delta_levelset'] = 0`
- **THEN** the pipeline passes ε/2 to both sides and the run is bit-identical to the current 2D path

### Requirement: 2D duty extraction weights mass flux by per-side void

The 2D dP/Q duty extraction (mass flow, mass-weighted outlet temperature/enthalpy) SHALL weight each side's mass flux by that side's void fraction (ε_A for A, ε_B for B) when δ≠0, consistent with the per-side porosity handed to the kernel, so that ṁ_A / ṁ_B and the resulting duty are physical on the asymmetric geometry.

#### Scenario: Asymmetric duty weighting

- **WHEN** δ≠0 and the per-side outlet mass flux is computed
- **THEN** side A is weighted by ε_A and side B by ε_B, and ṁ_A / ṁ_B reflect the actual per-channel void fraction (not a shared ε/2)

