# Design — DF coefficients re-fit from raw CFD

## D1. One consistent convention (the root fix)

All `(K, c_F)` come from `dp/L = μ·u/K + ρ·c_F·u²` with **u = interstitial velocity**, **dp = core pressure drop / core length**, **Re = ρ·u·D_h/μ**, `D_h = 4·ε_A/A_0`. Verified the water CFD `Um`/`dp_core`/`Lcore` already satisfy `Re = ρ·Um·Dh/μ`. The air CFD `速度/m/s` (col13) + `Pressureloss_TPMS` (col43) are reduced the same way. The experimental Δp is reconciled to core-only before any roughness fit (the col47 anchors' inconsistency — wrong t-trend, L6 spike — is exactly a convention break we are removing).

## D2. c_F extraction (well-conditioned)

Forchheimer dominates over Re 100–50 000, so a per-geometry 2-term least squares on `[μu, ρu²]` recovers `c_F` at R² ≈ 0.99. Keep `c_F` **Re-independent** (geometric) — the constant-`c_F` fit already nails the full sweep; do not reintroduce `smooth_df`'s `B·(Re/1000)^{-m}` unless LOO shows a systematic residual. This is the dominant, trustworthy coefficient.

## D3. K extraction (ill-conditioned → regularized)

`K` is the small Darcy term; the raw per-geometry fit scatters 24× in `K/Dh²`. Strategy (lit-confirmed):
1. **Better extraction form**: regress `(Δp/L)/u = μ/K + (ρ·c_F)·u` (divide by u → kills the heteroscedasticity that lets high-Re points dominate K), with **u normalized to u/u_max** (cuts the [u,u²] condition number) and **NNLS** (K, c_F > 0; OLS often returns an unphysical negative Darcy intercept). Optionally weight by 1/y² (relative-error fit).
2. **Per-geometry Re-coverage check via the Forchheimer number** `Fo = K·ρ·c_F·u/μ`: fit `c_F` from the high-Re plateau (Fo ≫ 1) and `K` from the low-Re Darcy region (Fo ≪ 0.1); flag geometries whose sweep never reaches a plateau (then that coefficient is not identifiable and falls back to the prior).
3. Regularize the `K(L,t)` surface with a physical prior `K ≈ C·L²·(a + b·ε_A)` (Kozeny–Carman / lit form), per topology, plus a smoothed multiplicative residual — **uses the per-geometry information** the current `Dh²`-only trend throws away (the fix for the low-Re water-Δp under-prediction).

## D4. High-accuracy interpolation surface (the user's target)

Grid is **regular 5 (L) × 4 (t) per topology**. Lit-confirmed recipe:
- **Fit in log space**: interpolate `log K`, `log c_F` (cross decades → near-linear + positivity guaranteed) over transformed inputs **(log L, log t)** (since `K ∝ L²`, `c_F ∝ 1/Dh` are ~linear in log–log). This single step is the biggest anti-oscillation lever.
- **Primary interpolant: anisotropic Matérn-5/2 GP** (separate length scales for L, t; small nugget to absorb CFD noise; gives calibrated uncertainty, composes with the roughness layer). **Fallback: thin-plate spline** (`r²log r`, no shape parameter → deterministic, non-oscillatory) when the GP hyperparameters are unstable on 20 points.
- **Avoid**: untuned multiquadric RBF and global high-order tensor polynomials (Runge oscillation).
- Selected by **leave-one-geometry-out** RMSRE on `c_F` (and `K`), whichever of GP / TPS wins. **Acceptance: c_F LOO RMSRE materially below the current gamma_df 2.5 %/2.6 %, now over all 40 geometries.**

Optionally make ε the primary kernel variable (`(L,t)→ε_A` analytic map, interpolate vs (ε, L)) since lit reports `K`, `c_F` collapse better on ε — compare LOO against the (log L, log t) basis and keep the winner.

## D5. Air ↔ water cross-check / pool

`(K, c_F)` are geometric, so air-CFD and water-CFD must agree per matching geometry. Water already spans Re 100–50 000 (covers both regimes), so water alone can anchor the smooth surface; air is the **independent confirmation** (and the only high-Re check for cells the water sweep under-resolves). If a geometry disagrees beyond ~10 %, treat it as a convention/mesh flag, not data to average blindly.

## D6. Roughness factor from experiments (multi-fidelity discrepancy)

Three rough-wall geometries: `D_7_6` (air), `G_7_6`/`D_7_6` (water). Model roughness as a **multiplicative** discrepancy γ_cF = c_F,rough / c_F,smooth (and γ_K). With only 3 anchors this is a per-topology scalar (or a mild trend), not a surface — analogous to the air-Nu ×1.28. **Blocker to resolve first:** the experimental Δp convention (core-only vs total/manifold; prototype channel count N≈28–34) — see `[[d76-cannot-calibrate-nu]]`. Until reconciled, report γ with its convention caveat; do not bake an unreconciled factor into the default.

> **PHYSICS CONSTRAINT (2026-07-01 correction).** `K`, `c_F` are **geometric** (fluid enters the DF law only via μ/ρ/u), so there is exactly ONE (K, c_F) per geometry — **never a fluid-specific `γ_water` ≠ `γ_air`** (that would push a fluid-dependence into a geometric coefficient). The air↔water Δp discrepancy is therefore only ever (a) a **convention artifact** (reconcile a_flow / core-vs-total / N → both fluids collapse onto the same c_F), or (b) a genuine **Re-dependence** `c_F(Re)` / `γ(Re)` — a single geometric curve that air (high Re) and water (low Re) sample at different Re, jointly constraining it. The roughness γ is likewise geometric (a `γ(Re)` at most), shared by both fluids. Order: fix the convention first (kills the artifact, likely most of the water gap); only if a residual survives, fit ONE `c_F(Re)` from pooled air+water — not two coefficient sets.

## D7. Validation gates (acceptance)

- Per-geometry LOO `c_F` RMSRE (primary target) and `K` LOO over the 40 CFD geometries.
- End-to-end water Δp RMSRE on `7-6-Water-dp` (G/D 7-6) — should improve markedly vs gamma_df 0.33/0.63×.
- Air Δp sanity vs `试验记录表` / `D_7_6`.
- **Shanghai 3D headline (`validate_shanghai_3d_real`) must not regress** before any default switch (hard invariant).
- Full pytest green; golden gates bit-identical unless an intentional, stated re-baseline.

## Risks

- `K` may stay weakly identified even after regularization — acceptable if water Δp and the gates pass; document the residual `K` uncertainty.
- Experiment convention may block a clean roughness factor — then ship the smooth-CFD surface (already a strict improvement over col47) and defer roughness.
- A backend swap risks the headline Δp — gated explicitly; default stays `gamma_df` until proven.
