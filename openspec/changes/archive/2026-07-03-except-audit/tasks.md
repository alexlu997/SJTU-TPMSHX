# Tasks

## 1. Behavior fixes (silent → loud, fallback kept)
- [x] 1.1 stages_3d `_mass_weighted_T_out` / `_mass_weighted_h_out` / `_simple_mass_flow`: warn on exception fallback
- [x] 1.2 optimizer_qnehvi GP-fit failure: verbose-gated print → unconditional warnings.warn

## 2. Narrowing
- [x] 2.1 stages_2d residual harvest → (AttributeError, TypeError); Q_net arithmetic → TypeError

## 3. Deliberate sites documented
- [x] 3.1 compute_orchestrator _Tee, ltne_energy_3d warmup, sigmoid_field LUT cache, optimizer progress_cb ×2

## 4. Gates
- [x] 4.1 Golden 2D + 3D --check bit-identical (PASS both)
- [x] 4.2 Full parallel pytest suite green — 1091 passed / 4 skipped / 1 xpassed in 4:35
