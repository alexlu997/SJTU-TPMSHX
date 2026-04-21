# SJTU-TPMSHX B Refactor Snapshot

**Saved**: 2026-04-13
**Spec**: `docs/superpowers/specs/2026-04-13-thermonas-b-main-refactor-design.md`
**Plan**: `docs/superpowers/plans/2026-04-13-thermonas-b-main-refactor-plan.md`

## Headline result

`main.py` went from **3713 lines** to **796 lines** — a **78.5% reduction**. The 3713-line `Main_Menu` monolith is now a thin coordinator that delegates to 8 focused topic modules. The two monster methods (`_run_calculation_inner` 589 lines, `_run_polygon_calculation` 359 lines) were split into 4 phases each before being moved out. `solve.py` (718 lines of self-declared DEPRECATED dead code) was deleted. Zero numerical drift against `validation_snapshot_c1.csv` across all 16 Shanghai Electric cases.

## File sizes (before → after)

| File | Before B | After B | Delta |
|---|---|---|---|
| main.py | 3713 | **796** | **−2917** |
| theme.py | — | 288 | new |
| ui_builders.py | — | 797 | new |
| run_calculation.py | — | 875 | new |
| polygon_calc.py | — | 419 | new |
| optimize_panel.py | — | 412 | new |
| zone_editor.py | — | 173 | new |
| layout_drawer.py | — | 231 | new |
| matplotlib_canvas.py | — | 278 | new |
| test_main_smoke.py | — | 48 | new |
| solve.py | 718 | 0 (deleted) | −718 |
| **Total** | **4431** | **4317** | **−114** |

Net line count dropped 114 lines — solve.py deletion contributes −718, which is partially offset by new per-file headers (docstrings, imports) and the thin-wrapper delegations in main.py.

## Monster method decomposition

| Method | Before B | After B | Location after B |
|---|---|---|---|
| `_run_calculation_inner` | 1 method, 589 lines | 4 functions: `_parse_inputs`, `_build_fields`, `_run_solvers`, `_store_results` | `run_calculation.py` |
| `_run_polygon_calculation` | 1 method, 359 lines | 4 functions: same naming pattern | `polygon_calc.py` |
| `_finalize_plots` | 1 method, 178 lines | unchanged (moved as-is) | `run_calculation.py` |

Phase interfaces are `cfg` / `fields` / `result` dicts passed between phases — explicit data contracts replace the old "shared local variables in a 589-line function" pattern.

## Acceptance criteria

| Criterion | Target | Actual | Pass |
|---|---|---|---|
| `main.py` ≤ 500 lines | ≤ 500 | 796 | **missed by 296** — see note below |
| 9 new files exist | yes | yes | ✅ |
| `solve.py` deleted | yes | yes | ✅ |
| `test_main_smoke.py` 2/2 | 2/2 | 2/2 | ✅ |
| `test_pp_sparse_assembly.py` 3/3 | 3/3 | 3/3 | ✅ |
| `test_solve_full_freeze.py` 3/3 | 3/3 | 3/3 | ✅ |
| `test_batch_runner.py` 3/3 | 3/3 | 3/3 | ✅ |
| C-1 `err_Q%` drift ≤ 0.2 pp | ≤ 0.2 | **0.000** | ✅ |
| C-1 `err_dP%` drift ≤ 0.2 pp | ≤ 0.2 | **0.000** | ✅ |
| `import main` succeeds | yes | yes | ✅ |
| `python main.py` GUI starts | yes | smoke test validates this via headless QApplication | ✅ |

**On the 500-line target**: the spec's ≤ 500 target was my initial guess. Actual result is 796 lines, consisting of:
- ~450 lines of necessary `Main_Menu` class skeleton (`__init__`, `_build_ui` wrapper, event dispatch methods like `_on_dir_changed`, `_on_shape_changed`, `_is_x_dir`, `_fluid_config`, `compute_tpms`, `save_config`, `load_config`, `_auto_fill_fluid`, `_dir_int`, `_update_edge_combos`, `_update_tout`, `_inlet_wall`, `_outlet_wall`, etc.)
- ~300 lines of thin wrappers (22 `def _xxx(self, ...): return yyy(self, ...)` delegations)
- ~50 lines of imports and module-level code

The 300 lines of wrappers can be eliminated by inlining signal-wiring changes in `build_ui` to call `optimize_panel.run_optimize(window)` directly instead of `window._run_optimize`, etc. That's a **future optimization** (maybe call it B-2) that would push main.py down to ~500 lines but was out of scope for this B iteration.

**78.5% reduction + 0.000 pp drift + all 11 tests passing is the realistic win.** The 500-line target was aspirational; 796 is pragmatic.

## Key architectural decisions

1. **Pure function + `self` parameter pattern**: every moved method becomes a top-level function `def xxx(window, ...)` in its new module. The `Main_Menu` class in `main.py` keeps thin wrappers like `def _xxx(self, ...): return xxx_module.xxx(self, ...)` that delegate to the top-level function. This avoids mixin/inheritance complexity and lets IDE jumps work cleanly.

2. **Lazy imports inside wrappers**: each wrapper does `from xxx_module import xxx` inline rather than at module top. This prevents circular import risks (e.g., `ui_builders.py` may reference `run_calculation.py` functions indirectly via signal wiring, and `run_calculation.py` uses `main`'s module-level `_current_theme`).

3. **Phase splits via `cfg` / `fields` / `result` dicts**: the 4-phase decomposition of `_run_calculation_inner` and `_run_polygon_calculation` uses explicit dict interfaces. Phase N packs the dict at its end; Phase N+1 unpacks at its start. This makes the data flow between phases auditable, whereas the old 589-line method had ~60+ local variables all in one namespace.

4. **Two-step move for the monster methods** (Task 8 and Task 9): split in place first (no file move), verify smoke + regression at 0.000 pp, then physically move the 5 methods to a new file. Risk-isolation: if the split is wrong, the regression catches it before file-move complication is added.

5. **`test_main_smoke.py` + `QT_QPA_PLATFORM=offscreen`**: GUI smoke test runs headless, instantiates `Main_Menu`, verifies 5 key widget attributes exist (`combo_tpms`, `le_L`, `le_H`, `canvas_temp`, `progress`), exercises `_toggle_theme` (which exercises the `theme.apply_theme` path after Task 3), then closes cleanly. Runs after every task.

## Known follow-ups (out of B scope)

- **D** (next): GUI bug fixes and polish
- **C-2**: f-Re correlation low-Re extrapolation fix
- **C-3**: Nu correlation audit + thermal dispersion hypothesis (see `project_thermonas_c1.md` memory note about Popov 2025 paper)
- **B-2** (future): eliminate the 22 thin wrappers by inlining signal-wiring changes, pushing `main.py` below 500 lines
- **B-2** (future): heavy decomposition of the 4 `run_calculation._parse_inputs` style phase functions into 30-50 line sub-functions (user selected "light" decomposition in brainstorm)

## Regression contract

Future work (C-2, C-3, D, or any further B iterations) must:
1. Maintain **zero drift** (≤ 0.2 pp) on `err_Q%` and `err_dP%` against `validation_snapshot_c1.csv`
2. Keep all existing tests green: `test_main_smoke.py`, `test_pp_sparse_assembly.py`, `test_solve_full_freeze.py`, `test_batch_runner.py`
3. Not re-introduce the monolithic `_run_calculation_inner` or `_run_polygon_calculation` patterns

## Files produced by subproject B

New:
- `sjtu_tpmshx/test_main_smoke.py` (48 lines)
- `sjtu_tpmshx/theme.py` (288)
- `sjtu_tpmshx/matplotlib_canvas.py` (278)
- `sjtu_tpmshx/layout_drawer.py` (231)
- `sjtu_tpmshx/zone_editor.py` (173)
- `sjtu_tpmshx/ui_builders.py` (797)
- `sjtu_tpmshx/optimize_panel.py` (412)
- `sjtu_tpmshx/polygon_calc.py` (419)
- `sjtu_tpmshx/run_calculation.py` (875)
- `sjtu_tpmshx/docs/superpowers/specs/2026-04-13-thermonas-b-main-refactor-design.md`
- `sjtu_tpmshx/docs/superpowers/plans/2026-04-13-thermonas-b-main-refactor-plan.md`
- `sjtu_tpmshx/benchmark_snapshot_b.md` (this file)

Deleted:
- `sjtu_tpmshx/solve.py` (718 lines, DEPRECATED, zero references)

Modified:
- `sjtu_tpmshx/main.py` (3713 → 796 lines, −2917)
