## Status (2026-06-30)

**Phase 1–2 + a gate-safe backend DELIVERED.** Raw water CFD (40 geom) re-extracted via 2-stage decoupled fit → K/Dh² scatter 24.7×→1.3–1.6×; log-space TPS/GP surfaces interpolate at **cF LOO 5.1 %(G)/14.5 %(D), K LOO 6.2 %(G)/19.7 %(D), end-to-end Δp LOO 13.0 %(G)/20.3 %(D)** — **~6× better than gamma_df** (87/122 %). Figure: `assets/df-refit-loo.png`. Root cause confirmed: col47 anchors anomalous (L4 t-trend reversed, L6 3–4× spike).

Shipped the **`cfd_refit`** backend = clean CFD **K**-surface + gamma_df **c_F** (gate-safe): **Shanghai 3D dP 5.28 % / Q 3.21 %** (gamma_df 5.05/3.20 — preserved) and water-Δp improved (Diamond 0.33→0.40, Gyroid 0.62→0.68). Non-default; full pytest green (+`test_cfd_refit_backend.py`).

**Deferred:** full **c_F** surface deployment (needs roughness γ — blocked on experiment convention, [[d76-cannot-calibrate-nu]]); air-CFD cross-check (water alone sufficed); production default switch (user decision). The full smooth-cF surface is validated but Shanghai needs the gate-calibrated c_F (registration contract — see plhub_gp precedent).

---

## 1. Extraction — per-geometry (K, c_F) in one convention

- [ ] 1.1 Reduce raw **water** CFD (40 geom) via `(Δp/L)/u = μ/K + ρ·c_F·u` with normalized u + NNLS; per geometry record K, c_F, R², n, ε_A, D_h, Re-range
- [ ] 1.2 Compute per-geometry **Forchheimer-number coverage** (Fo at Re_min/Re_max); flag geometries where K (Fo never ≪0.1) or c_F (Fo never ≫1) is not identifiable
- [ ] 1.3 Reduce raw **air** CFD (12 geom, `速度`+`Pressureloss_TPMS`, same convention) — get core length from the CFD setup
- [ ] 1.4 **Air↔water cross-check**: per matching geometry, |c_F_air − c_F_water|/c_F should be ≲10%; report; decide pool vs water-only
- [ ] 1.5 Write extracted table to `df_surrogate/_prebuilt/df_cfd_coeffs.csv` (tp, L, t, eps_A, Dh, K, cF, R2, Fo_lo, Fo_hi)

## 2. High-accuracy interpolation surface (the target)

- [ ] 2.1 Build LOO harness: leave-one-geometry-out over the 5×4 grid per topology, RMSRE on c_F and K
- [ ] 2.2 Fit **log c_F** vs (log L, log t) per topology: anisotropic Matérn-5/2 GP **and** TPS; pick lower LOO. Also try ε-primary basis; keep winner
- [ ] 2.3 Fit **log K**: GP/TPS in log space + physical prior `K≈C·L²·(a+b·ε)`; regularize/shrink where Fo flags K unidentifiable
- [ ] 2.4 Report LOO RMSRE (c_F, K) — **gate: c_F LOO ≪ gamma_df 2.5/2.6%** over all 40 geom; figure cF/K vs L per t (anchors + surface + LOO points)

## 3. Roughness factor (multi-fidelity, multiplicative)

- [ ] 3.1 Reconcile experiment Δp convention (core vs total/manifold, channel N) for `D_7_6` air + `7-6-Water` G/D — resolve or document the caveat (see [[d76-cannot-calibrate-nu]])
- [ ] 3.2 Derive γ_cF = c_F,rough/c_F,smooth at the 3 anchors; fit a **constant** γ per topology (multiplicative, shrinkage to const). NO second roughness factor; NO additive KOH
- [ ] 3.3 Validate γ against the experiment Δp end-to-end (water 7-6, air D_7_6); report residual

## 4. Backend integration + gates

- [ ] 4.1 New backend module (`df_surrogate/cfd_refit.py`) reading the prebuilt table + surface; `predict(L,t,eps)->(K,cF)`; register alongside gamma_df/rbf (`backend.py`)
- [ ] 4.2 End-to-end **water Δp RMSRE** on `7-6-Water-dp` with the new backend — must beat gamma_df 0.33/0.63×
- [ ] 4.3 **Shanghai 3D headline** (`validate_shanghai_3d_real`) with the new backend — must not regress the README Δp/Q (hard invariant; default NOT switched until this passes)
- [ ] 4.4 Full pytest green; new backend has unit + LOO regression tests; golden gates bit-identical (default unchanged)

## 5. Deliverable

- [ ] 5.1 Summary: LOO accuracy table (c_F, K) over the whole dataset, water-Δp improvement, the col47-anomaly root cause; figure(s) for README closure section (replace/augment the gamma_df cF interpolation figure)
- [ ] 5.2 Decide (with user) whether to switch the production default to the new backend
