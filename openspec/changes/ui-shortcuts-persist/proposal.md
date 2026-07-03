# Change: ui-shortcuts-persist

## Why

2026-07-03 UI survey — the 方案三 workbench (3 visible tabs 几何布局|结果|优化)
left the keyboard/palette layer on the retired 5-tab set, and session restore
loses workbench state:

- `main.py` Ctrl+1–5 still bind layout/temp/pres/vel/3d; 优化 has no shortcut;
  Ctrl+2/3/4 land on now-hidden sub-views. `_cycle_tab` walks the same
  retired order.
- Shortcut cheat sheet (`dialogs._SHORTCUT_ROWS`) lists "Tab — Temperature …
  Ctrl+2" etc.
- Command palette tab entries are English ("Show Pareto tab") while the
  toolbar is Chinese (优化).
- `field_menu.py` context action "Revert to Shanghai default" + status
  message bypass the preset de-branding (ui.fmt.preset_display).
- Tab tooltips render bilingual ("几何布局 tab (Shift+click …)").
- Session restore: last active tab, left-panel collapse, and the 2D|3D
  result-view choice are not persisted.

## What Changes

1. Shortcuts: Ctrl+1 几何布局, Ctrl+2 结果 (resolves via `_result_view`),
   Ctrl+3 优化, Ctrl+4 toggles 2D|3D inside 结果; Ctrl+5 retired.
   `_cycle_tab` walks ('layout','result','pareto') with result-family
   current-tab mapping.
2. Cheat sheet rows match the visible workbench.
3. Palette tab entries in Chinese with English keywords kept for search.
4. field_menu action/status → 算例工况 wording (Chinese chrome).
5. Tab tooltips fully Chinese.
6. `_save_session` payload gains `ui_state` {active_tab, left_collapsed,
   result_view}; `_restore_session` re-applies (best-effort, falls back
   to layout when the saved tab is gated off).
7. Locks in test_ui_layout_hygiene.py.

## Impact

UI-only; no solver path. Full parallel suite + updated hygiene locks green.
