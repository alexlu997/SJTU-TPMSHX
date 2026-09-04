# SJTU-TPMSHX architecture

This is the current architectural and physical contract for the repository.
Historical audits and reports explain how the project reached this state, but
they do not override the running code or this document.

## Runtime flow

```text
UI -> controllers -> pipelines -> solvers / df_surrogate
                    |          -> domain / configs
                    -> ComputeResult -> UI / validation / optimization
```

- `domain/` owns typed input and result contracts and is Qt-free.
- `configs/` owns packaged case configuration.
- `solvers/` owns geometry, fluid properties, closures, SIMPLE, and LTNE
  numerical implementation.
- `df_surrogate/` owns Darcy-Forchheimer prediction and its packaged tables.
- `pipelines/` converts `ComputeConfig` into solver calls and assembles
  `ComputeResult`.
- `controllers/` coordinates pipelines for GUI and headless callers.
- `ui/` owns PySide6 and PyVista presentation only.
- `validation/` and `runs/` are executable research and verification tools,
  not alternative production implementations.

The GUI entry point is `python -m sjtu_tpmshx.main`; the installed headless
entry point is `tpmshx-run`.

### UI structure

- `ui/builders_canvas.py` assembles the visible geometry, result, and
  optimization workbench. `build_canvas_area()` only coordinates its named
  same-file builders.
- `ui/mixins/tab_view.py` owns workbench availability and routing, including
  the 2D/3D result switch. Hidden widgets are not used as navigation state.
- `ui/panel_vis_3d.py` owns the PyVista presentation. Its constructor delegates
  toolbar, controls, viewport, state, and timer setup to focused methods while
  rendering behavior stays in the same widget class.

## Physical invariants

These constraints protect demonstrated solver behavior. Change them only as an
explicit numerical-model change with directly relevant validation.

1. **Compressible air.** Air uses the ideal-gas density path. Do not replace it
   with a constant-density or isothermal shortcut.
2. **Porosity is split once.** Symmetric LTNE callers pass the full porosity;
   the energy solver forms the two half-porosity streams. For an offset
   isosurface, `solvers/asym_split.py` computes the upstream `eps_A`/`eps_B`
   split, whose sides sum to the full porosity, and the kernel does not halve
   those values again.
3. **Mass-flux inlet.** Compressible air uses the mass-flux inlet in both 2D
   and 3D. Solver velocities are interstitial, not superficial.
4. **Darcy-Forchheimer ownership.** `df_surrogate.predict_K_cF()` remains the
   pure geometry baseline: one water+sCO2 CFD table for both sides and every
   fluid. Base K0 and cF0 depend only on topology, L, and t, are bilinearly
   interpolated inside 4–8 mm by 0.3–0.6 mm, and never depend on Re or fluid.
   The UI exposes exactly two production methods. **CFD smooth-wall** is the
   default and is V2-compatible. **Experiment calibration** applies one fixed,
   reviewed effective correction per side after pipeline assembly and before
   pressure seeding/SIMPLE; K/cF stay fixed for the solve. The selector routes
   to a dataset whose campaign, boundary, pressure-drop definition, and
   geometry match the run. It is not evidence of fluid-intrinsic D-F physics.
   Differences may absorb pressure-tap location, contractions/expansions,
   manifolds/distribution regions, whole-HX losses, flow-area/channel-count
   definitions, instrument zero, and data reduction; these contributions are
   not separately modelled. Without a same-rig comparison they must not be
   attributed to fluid. `gamma_df` and `rbf` remain research modes.
5. **Nusselt ownership.** Air, water, and sCO2 coefficient tables live only in
   `solvers/nu_correlations.py`.
6. **Compressible envelope.** `solvers/envelope.py` rejects operating points
   without a steady subsonic solution. Do not bypass that result by widening a
   pressure clip or forcing a numerical answer.
7. **Pressure reference.** `P_ref_abs` is the outlet absolute pressure; the
   SIMPLE pressure field is gauge pressure relative to it.
8. **Units.** Runtime quantities use K, Pa, and m unless the name says
   otherwise. TPMS cell size and wall thickness use mm.
9. **Port boundary.** `ComputeConfig.validate()` normalizes both ports and
   calls the shared validator. 2D supports every ±x/±y direction; 3D also
   supports ±z, with both transverse extents validated against the correct
   domain axes.
10. **True-enthalpy ownership.** Any ordered fluid pair containing sCO2 uses
    the conservative enthalpy kernel. It consumes SIMPLE's signed staggered
    face mass flows and computes duty from boundary enthalpy fluxes; it must
    not reconstruct a full-face x-flow from a scalar mass rate.
11. **Current V2 limit.** sCO2 zones and offset level sets remain rejected;
    air/water-only runs retain their existing temperature-form kernels.
12. **Experiment-correction applicability.** Air uses only the core-specimen
    L=6..8 mm, t=0.3..0.5 mm interpolation domain; t=0.6 is not extrapolated.
    sCO2 uses only D/G-7-6 hot-side `ok_dp` evidence, keeps K=K0, and is
    HX-effective: uniform symmetric core, no zones, delta, other L/t, or
    independent cold-side fit. Its measured inlet-velocity windows are
    0.5905..2.5731 m/s (Diamond) and 0.6209..2.5022 m/s (Gyroid). The fitted
    D-F parameters are a porous-region
    closure and may be used with valid custom port centres, widths, and every
    solver-supported flow direction; only the full-face x-direction calibration
    boundary has direct experimental evidence. The
    water+air D/G-7-6 experiment consists of two complete, disconnected TPMS
    networks with
    full-face inlets and delta=0. Water and air therefore use the same
    topology-derived single-side flow area (D 5.94e-4 / G 6.50e-4 m²), with no
    28/34 channel-count scale or geometric-face shortcut. After excluding
    G/water case 1 (`dp_nonphysical`) and D/water cases 10/11
    (`duplicate_row`), the production water fit uses the declared high-flow
    window `u>=0.10 m/s`; lower-flow valid records remain reported as outside
    scope. Fixed-K0 water RMSRE is 6.84% D / 0.93% G with sF 4.8928 / 4.1989.
    The measured upper bounds are 0.2541 / 0.2232 m/s. Matching HX-air uses its
    own sF 1.8024 / 2.0120 and measured velocity windows. `ComputeConfig`
    selects each side independently, allowing all nine ordered air/water/sCO2
    pairs and every valid 2D/3D flow direction. A mixed pair may therefore combine
    corrections from different campaigns; that is a model composition, not joint
    experimental validation of the pair. Each HX-effective side still requires its
    own velocity window, the matching 0.182 x 0.042 x 0.042 m domain, and delta=0.
    Custom inlet/outlet positions and sizes remain supported. Every active side
    must match its own applicability rules; there is no silent fallback.

## Extension points

- Add a fluid through `solvers/fluid_props.py`; keep its Nu implementation in
  `solvers/nu_correlations.py` and pass it through the existing pipeline.
- Add a user-facing configuration field to the `domain/compute_config.py`
  dataclasses first, then adapt it once at the UI boundary.
- Add a solver behavior behind an existing configuration boundary only when a
  current use case requires it. Do not introduce a factory or interface for a
  single implementation.
- Keep one production path per dimension. Validation code must call that path
  unless it is explicitly testing a lower-level kernel.

## Local data

Raw data is intentionally outside Git and is resolved relative to the
repository:

```text
data/raw_data/
├── *.xlsx
├── sCO2-CFD/
│   ├── Diamond/
│   └── Gyroid/
└── CO2-CFD/
    ├── Diamond/
    └── Gyroid/
```

Do not rename dataset directories without first updating the loader that names
that exact path. Generated reports must not become a second source of truth for
raw measurements.
