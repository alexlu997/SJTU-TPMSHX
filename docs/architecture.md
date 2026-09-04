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
4. **Darcy-Forchheimer ownership.** Production uses one water+sCO2 CFD table
   for both sides and every fluid. K and cF depend only on TPMS topology, L,
   and t; values inside the 4–8 mm by 0.3–0.6 mm grid are bilinearly
   interpolated. They must not depend on Re or fluid type. `gamma_df` and
   `rbf` remain explicit research modes.
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
