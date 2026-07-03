# Change: split-ui-main

## Why

Last of the large-file splits. main.py (~1900 lines) still carries three
extractable responsibility groups on the Main_Menu god-class; ui/
builders_canvas.py (~1350) hosts the result-sidebar trio beside the canvas
builder monolith.

## What Changes

Verbatim method moves into new mixins (MRO extended; behavior identical):
- `ui/mixins/shortcuts.py` (ShortcutsMixin): _track_shortcut,
  _setup_shortcuts, _keyboard_set_fluid, _cycle_density, _cycle_tab,
  _scrub_recent.
- `ui/mixins/io_actions.py` (IOActionsMixin): _export_results, save_config,
  load_config, _copy_figure_clipboard, _export_figure.
- `ui/mixins/result_bridge.py` (ResultBridgeMixin): the ResultCache
  property bridges (_compute_results, _result_3d, _has_results_2d/3d,
  _has_results, _drawn_tabs).
- `ui/builders_sidebar.py`: _build_result_sidebar, refresh_result_sidebar,
  update_result_sidebar_visibility (builders_canvas re-exports — mixins
  import them from builders_canvas today).

## Declined (documented, not an oversight)

- `panel_vis_3d.py` (~1660): one cohesive Qt widget class, no non-Qt seam
  (decision reaffirmed from arch-b-c-e E).
- `build_canvas_area` monolith (~1050-line builder fn): nested closures
  capture local Qt state; carving it risks silent wiring breaks for pure
  line-count gains. Sidebar trio extracted; the rest stays.
- `run_controller.py` / `optimize_panel.py`: cohesive single-purpose
  modules under their capability specs.

## Impact

UI-only; no solver path. Hygiene locks + main smoke + full parallel suite
gate it. MRO grows by three mixins (documented in PROJECT_MANUAL).
