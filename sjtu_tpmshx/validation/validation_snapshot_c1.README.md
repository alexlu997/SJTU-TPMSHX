# C-1 Validation Snapshot

**Saved**: 2026-04-13
**Source**: `validate_shanghai.py` after C-1 spec changes
**Spec**: `docs/superpowers/specs/2026-04-13-thermonas-c1-audit-water-fixed-bc-design.md`
**Plan**: `docs/superpowers/plans/2026-04-13-thermonas-c1-audit-water-fixed-bc-plan.md`

## What this snapshot represents

16 Shanghai Electric test cases (上海电气天然气加热器实验工况) run through the SJTU-TPMSHX
prediction model after the C-1 fixes:

1. **Prototype-scale dimensioning** — `A_FLOW = 36 × 18.0565e-6 m²`, `m_air` from
   Excel column `c5` (样机空气流量), `m_water` from column `c7`.
2. **Water side frozen** — SIMPLE solver for fluid B deleted; `Tb_prescribed`
   constructed as a linear interpolation between measured `T_w_in` (c24) and
   `T_w_out` (c25) along the water flow direction.
3. **Perfect water-side coupling** — `h_vB = 1e10 W/(m³·K)` so the solid
   temperature tracks `Tb_prescribed` exactly. Eliminates the water side as a
   confounding factor, exposing the air-side model's real accuracy.
4. **Uniform air velocity field for temperature solver** — `ucA = u_A` scalar
   override, bypassing a SIMPLE/solve_full velocity convention mismatch that
   inflated effective NTU by 3× and cost ~13 percentage points at high Re.
   SIMPLE still runs and provides `dP_A_sim` (unchanged from pre-C-1 baseline).

## Final accuracy

| Metric | Value |
|---|---|
| **max \|err_Q%\|** | **21.8% (Case 16)** |
| cases within ±5% | Cases 1–7 (low to mid Re) |
| cases within ±10% | Cases 1–10 |
| cases within ±25% | all 16 |
| dP_air_sim vs pre-C-1 baseline | bit-identical (C-1 did not touch the momentum solver) |

## Error profile

Clean monotone-in-Re error (with one experimental outlier at Case 12):

```
Re < 3000 (Cases 1–5):        err_Q% = −0.5% to −2.3%   ← model nearly perfect
Re 4000–7000 (Cases 6–11):    err_Q% = −4.6% to −12%    ← linear degradation
Re > 8000 (Cases 13–16):      err_Q% = −15.6% to −21.8% ← systematic under-prediction
```

Case 12 shows `err_Q% = −7.2%` which is anomalously small compared to its
neighbours (Case 11 = −12%, Case 13 = −15.6%). The corresponding `Q_exp = 2536 W`
is also ~10% lower than Case 11's `Q_exp = 2780 W` despite higher flow rate and
Re, strongly suggesting a measurement issue in that specific experimental run
rather than a model quirk.

## Known unresolved issues (out of C-1 scope)

- **`err_dP%` low-Re bias** (+50% at Case 1 → +1% at Case 16, monotone):
  — the Gyroid f-Re correlation is validated for Re ∈ [600, 30000] but Cases
  1–3 operate below 600 (Re = 526, 1002, 1480). Extrapolated f gives a
  too-high pressure drop at low Re. **→ C-2**

- **`err_Q%` systematic under-prediction at high Re** (−15% to −22%):
  — correlates with `T_Ain` dropping from 150°C to 97°C (Cases 9–16 have
  roughly constant u_A but declining `T_Ain`). Likely the Gyroid Nu correlation
  has a temperature or Re range where `A₀ × H_sf` systematically underestimates
  the effective volumetric heat transfer coefficient. **→ C-3**

- **`solve_full.py` line 285–292**: the outlet BC copy block for `bc_B=1` is
  (probably) correct for the −x flow direction convention, but the whole block
  has not been audited for consistency with the dir_B encoding. Not reached in
  the Shanghai validation (which uses `dir_B=3`). **→ C-3**

- **SIMPLE / solve_full velocity convention mismatch**: SIMPLESolver returns
  velocities ~3× larger than `m_dot/(ρ·A_FLOW)`. Bypassed with a uniform-u
  override in `validate_shanghai.py` as a C-1 workaround. Root cause is a
  porosity / eps_f double-count that requires reading both code paths.
  **→ C-3**

- **`eps_f = ε/2` hard-code** (`solve_full.py:358`): two-fluids-share-pores
  assumption, not audited against the physical Gyroid geometry. **→ C-3**

## Regression contract

Before merging any C-2 / C-3 / A / B / D work, run `python validate_shanghai.py`
and diff the result against this file. Any case drifting by more than **±2%**
on `err_Q%` or `err_dP%` must be explained in the changing PR / commit message.

Quick regression check:

```bash
cd D:/Postgraduate/均质化/SJTU-TPMSHX/sjtu_tpmshx
python -c "
import pandas as pd, numpy as np
old = pd.read_csv('validation_snapshot_c1.csv')
new = pd.read_excel(r'D:/Postgraduate/均质化/SJTU-TPMSHX/data/shanghai_validation.xlsx', engine='openpyxl')
for col in ['err_Q%', 'err_dP%']:
    d = np.abs(pd.to_numeric(new[col], errors='coerce') - pd.to_numeric(old[col], errors='coerce'))
    print(f'{col}: max drift = {d.max():.2f} percentage points')
    assert d.max() < 2.0, f'{col} regressed by more than 2pp'
print('C-1 regression OK')
"
```
