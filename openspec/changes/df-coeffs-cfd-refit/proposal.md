## Why

The Darcy–Forchheimer coefficients (`K`, `c_F`) the solver runs on are built by `gamma_df` from the **`_prebuilt/*_surrogate_ref.csv` ("col47") anchors**, which a fresh re-extraction from the raw CFD shows to be **internally inconsistent**:

- **Diamond L4** col47 `c_F` *decreases* with wall thickness (346→283→239) — physically backwards; the raw water CFD *increases* (382→459→593, thicker wall → higher drag).
- **Diamond L6** col47 `c_F` spikes to 610–649 (and `K` to ~2e-8), 3–4× off the smooth L5→L7 trend (raw water CFD: 168→210, sitting cleanly between L5≈300 and L7≈120). `gamma_df` fits its roughness factor γ from exactly these L6/L8 anchors.

Meanwhile `smooth_df` forces **`K` onto a single-parameter `Dh²` trend** (`logK = 2·logDh + b0K`), which we measured at **53 % RMSRE** vs the per-geometry CFD; the raw per-geometry `K` (24× spread in `K/Dh²`) is discarded. This crude `K` is invisible in the air production window (Re 400–16k, Darcy share 1–6 %) but **under-predicts the water-side Δp** (Re 100–1100, Darcy share 9–28 %) by up to 3× (`gamma_df` Diamond 0.33×, rbf 0.69× vs the `7-6-Water-dp` experiment).

We now have a far better, **unused** foundation: the **raw water CFD** (`data/raw_data/water-cfd-raw.xlsx`, 40 geometries = 2 topologies × 5 cell sizes × 4 wall thicknesses, Re 100–50 000, `dp_core`). A per-geometry Forchheimer fit gives clean `(K, c_F)` at **R² median 0.994** with monotone, physical trends. Plus raw air CFD (`试验记录表` Pressureloss) and rough-wall experiments (`D_7_6` air, `7-6-Water` water).

## What Changes

- **Re-extract `(K, c_F)` per geometry from the raw CFD** in ONE consistent convention (interstitial velocity `Um`, core `dp/L`, `Re = ρ·Um·Dh/μ`): `dp/L = μ·u/K + ρ·c_F·u²`. Water = 40 geometries; air = 12 geometries (cross-check). `c_F` from the full Re sweep (Forchheimer-dominated, well-conditioned); `K` from the low-Re subset / Forchheimer-intercept with a physical prior (ill-conditioned, regularized).
- **Replace the col47 anchors + `Dh²`-K trend** with a high-accuracy interpolated surface `(K, c_F)(L, t, topology)` fit to the 5×4 grid per topology (interpolation method selected by leave-one-out accuracy — TPS / RBF / GP, see design).
- **Pool / cross-validate air vs water CFD** (the coefficients are geometric → must agree; water pins the low-Re Darcy `K`, air confirms the high-Re `c_F`).
- **Roughness correction** from the rough-wall experiments as a documented multiplicative factor γ_cF (and γ_K) where the experimental convention can be reconciled — otherwise flagged, not silently fit.
- Land as a **new selectable DF backend** (registered alongside `gamma_df` / `rbf`), default unchanged until it passes every gate.

## Capabilities

### New Capabilities

- `df-coeffs-cfd-refit`: a Darcy–Forchheimer coefficient model derived directly from the raw per-geometry CFD in a single consistent convention, with leave-one-out interpolation accuracy as the acceptance metric, plus an experiment-anchored roughness factor.

## Impact

- **Code**: new `df_surrogate/` extraction + surface modules and a registered backend; `df_surrogate/_prebuilt/` regenerated coefficient table. No change to the solver momentum source (still consumes `(K, c_F)`).
- **Gates**: per-geometry LOO `c_F` RMSRE (target ≪ the current 2.5 % gamma_df trusted-LOO, now over 40 geometries not 6); `K` LOO; end-to-end water-Δp RMSRE on `7-6-Water-dp`; **Shanghai 3D headline must not regress** (`validate_shanghai_3d_real`).
- **Non-breaking**: production default stays `gamma_df` until the new backend passes all gates; switch is a separate, gated decision (CLAUDE.md: a surrogate-backend change must reproduce the Shanghai 3D baseline before it becomes default).
- **Out of scope**: changing the Nu correlations; the air ×1.28 roughness; the asymmetric-δ per-side κ.
