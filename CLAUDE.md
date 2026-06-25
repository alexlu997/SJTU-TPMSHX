# SJTU-TPMSHX — agent guide

Custom Python compressible SIMPLE/LTNE TPMS heat-exchanger solver. NOT Fluent, NOT OpenFOAM — follow this repo's own conventions.

## Read first (canonical docs — don't duplicate them here)
- **`PROJECT_MANUAL.md`** — start here. Glossary (名词表) + directory map + per-file API index + physics one-pager. Written for both humans and AI agents.
- **`README.md`** — headline results, install / run commands, V&V table.
- Research notes and experiment reports are kept in a **separate vault outside this repository** (this package is a sub-repo of a larger research workspace). The in-repo `reports/` holds computed CSV / figures, not the report archive.

## Hard invariants — violating these causes real regressions
- **Compressible is required.** Air uses ideal-gas ρ=ρ(P,T) — the code default (`variable_rho_cp=True` in `controllers/compute_config.py`, `fluid_type='ideal_gas'`). Removing compressibility roughly doubled the Shanghai 3D Δp error in the compressibility-fix benchmark; it is the single biggest correctness lever. Never substitute isothermal as a "simplification".
- **Porosity ε is split in ONE place.** `solvers/ltne_energy.py` halves total ε internally to ε_A = ε_B = ε/2. **Callers pass the FULL ε.** The `eps_A` / `eps_B` kwargs are private hooks — passing pre-halved values double-halves (historical bug). Don't.
- **Mass-flux inlet is the air-inlet default in BOTH 2D and 3D** (`massflux_inlet=True`, default via `getattr`, in `solvers/simple_solver.py` and `simple_solver_3d.py`). It holds the inlet ρ·v at the physical throughput instead of fixing v, removing a compressible velocity-inlet positive-feedback (dP↑→ρ↑→dP↑) that otherwise makes Δp drift with the grid. It is what makes Shanghai Δp grid-convergent (2D RMSRE 35.8%→8.4%, ≈ 3D; 3D was 17.4%→7.2%). 2D passes the reference inlet density explicitly via `rho_inlet_ref` (the pipeline recreates the solver each outer iter, so a rho_field-based capture would ratchet). Don't revert to velocity-inlet.
- **The DF closure already accounts for SLM surface roughness — never add a friction / roughness multiplier (it double-counts).** Both backends bake it in: the default `gamma_df` as an experiment-anchored γ over a smooth-CFD base (`cF = cF_smooth × γ`), the opt-in RBF path as a direct fit to experimental Δp. (Default verified: `df_surrogate/predict.py` `_DF_DEFAULT="gamma_df"`.)
- **Nu coefficients have a single source:** `solvers/nu_correlations.py` → `NU_COEFFS` (air) / `WATER_NU_COEFFS` (water). Never duplicate them elsewhere.
- **A surrogate-backend change must reproduce the Shanghai 3D baseline before it becomes default** (target = the README headline Δp / Q; gate script `validation/validate_shanghai_3d_real.py`). Past candidates regressed Δp by roughly an order of magnitude.

## Before claiming "done"
- Run the **full** pytest suite, not just the golden gate — golden configs don't cover every closure branch:
  ```
  pytest sjtu_tpmshx/tests/ -q
  ```
- Golden gates `sjtu_tpmshx/runs/_out/_golden_2d.py` and `_golden_3d.py` (local — `runs/_out/` is gitignored) must stay bit-identical unless you intentionally re-baseline.
- Long runs: use `python -u …` or stdout block-buffers and the run looks hung.

## Validation commands
- Lumped ε-NTU dual-Nu (current paper baseline):
  `python sjtu_tpmshx/validation/validate_shanghai_lumped_dual_nu.py`
- 3D real solver (SIMPLE, mass-flux inlet):
  `python sjtu_tpmshx/validation/validate_shanghai_3d_real.py`

## Gotchas
- The DF surrogate package is **`df_surrogate/`** (renamed from `df_fit/`; older commits / external notes may still use the old name).
- Units are K / Pa / m — **but TPMS cell size and wall thickness are in mm**. Common trap.
- Velocities are **interstitial** (in-pore) throughout; mixing in a superficial velocity is a bug.
- The current default surrogate backend (gamma_df vs rbf) and the headline Shanghai Δp / Q numbers drift between revisions — verify in code or the latest report before quoting them.

## Git
This repo: `github.com/alexlu997/SJTU-TPMSHX`, default branch **master**. Commit / push only when asked.
