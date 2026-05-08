# Legacy Shanghai Validation Scripts

**Status:** Historical / DO NOT use for new work.
**Moved:** 2026-05-06 (fix #5 — validate_shanghai cleanup).
**Reason:** Drift, redundancy, or superseded by canonical baselines in `../`.

For new validation work, use:
- `../validate_shanghai_lumped_dual_nu.py` (论文 baseline, Q 1.71%)
- `../validate_shanghai_3d_real.py` (3D production, Q 2.29%)

---

## Per-script status

### `validate_shanghai.py` (legacy 2D, single-Nu, water 1e10 shortcut)
- **Why kept:** benchmark target (`benchmarks/benchmark_a.py` measures wall time vs this), regression test (`validation/test_shanghai_regression.py`).
- **Known issue:** water-side h_v hard-coded to 1e10 (forces T_wall = T_water), not physical.
- **Superseded by:** `validate_shanghai_aligned.py` (h_vB from real tpms_compute) → eventually `validate_shanghai_lumped_dual_nu.py` (论文 baseline).

### `validate_shanghai_aligned.py` (mirror of run_calculation 2D path)
- **Why kept:** historical reference for run_calculation.py audit.
- **Status:** Superseded by `validate_shanghai_lumped_dual_nu.py` for paper validation; UI run_calculation 2D path itself is the production for interactive use.

### `validate_shanghai_lumped.py` (single-Nu lumped)
- **Why kept:** comparison vs dual-Nu — shows Q error went from ~2.10% → 1.71% with water-side Yan correlation.
- **Superseded by:** `validate_shanghai_lumped_dual_nu.py`.

### `validate_shanghai_lumped_v3.py` (S8 closed-form + Gradient Boosting)
- **Why kept:** documents the "6 surrogate dead ends" exploration (per project memory: 3-param D-F / Kim K_1 / Kim v1/v2 / v2 4D MLP / EG-DIP / S8 GB). All abandoned.
- **Status:** Dead end. ConstDF-v1 + Nu v4.1 ×1.28 won.

### `validate_shanghai_3d.py` (Phase 1 Week 4 MVP, no LTNE coupling)
- **Why kept:** 3D solver MVP smoke; shows Level 0 (Nz=1 delegate) + Level 1 (Nz=5 uniform extrude) + Level 1.5 (Richardson convergence).
- **Superseded by:** `validate_shanghai_3d_real.py` (Phase 1b-b 2026-04-20 with full non-iso coupling).

### `validate_shanghai_3d_full_ltne.py` (Phase 7-2 full LTNE B-side)
- **Why kept:** experimental — replaces frozen Tb_prescribed with full SIMPLE-B + LTNE 3-temperature coupling. Cross-flow unmixed-unmixed.
- **Status:** Future work (only relevant if Shanghai geometry has partial-B; currently full-face A/B). H8 ghost-pin validated separately.

### `validate_shanghai_3d_streamfunction.py` (P7 streamfunction-pressure drop-in)
- **Why kept:** documents the streamfunction-pressure formulation P3-P7 closure.
- **Known result:** Shanghai dP 47% (worse than SIMPLE 38% by 8 pp). Per memory: P-recovery via 1D axial Brinkman integration assumes plug flow; 3D lateral velocity breaks the assumption. **NOT a drop-in SIMPLE replacement for dP.** Method appendix only.
- **Future work:** Fix #2 — rewrite P-recovery as full 3D Pressure-Poisson `∇²P = ∇·(μ∇²v − ρ∇·(vv) − F_brinkman)`.

---

## DO NOT add new files here

If a new variant is needed:
1. First ask: can a flag/option on the canonical baseline cover this? (preferred)
2. If genuinely new: add to `../`, document in `../README.md`, deprecate when superseded.
3. Move here only when retired with clear "superseded by" reference.
