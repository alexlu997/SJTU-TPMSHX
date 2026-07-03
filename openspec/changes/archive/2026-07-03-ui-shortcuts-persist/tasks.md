# Tasks

## 1. Shortcuts (乙)
- [x] 1.1 main.py: Ctrl+1/2/3 → layout/result/pareto; Ctrl+4 → `_toggle_result_view`; drop Ctrl+5 + temp/pres/vel binds
- [x] 1.2 tab_view.py: `_toggle_result_view` helper (result-family aware, gated no-op)
- [x] 1.3 main.py `_cycle_tab`: ('layout','result','pareto') + result-family current mapping
- [x] 1.4 dialogs.py `_SHORTCUT_ROWS`: workbench rows (几何布局/结果/优化 + 2D|3D 切换)
- [x] 1.5 command_palette.py: Chinese tab entries, English keywords kept
- [x] 1.6 field_menu.py: 恢复算例工况默认值 action + status message
- [x] 1.7 builders_canvas.py: tab tooltips fully Chinese; Ctrl+2/Ctrl+4 hints on 结果/2D|3D seg; 3 stray visible "Shanghai" tooltips de-branded (builders_domain ×2, optimize_panel ×1)

## 2. Persistence (丙)
- [x] 2.1 session_presets.py `_save_session`: ui_state {active_tab (family key → 'result'), left_collapsed, result_view}
- [x] 2.2 session_presets.py `_restore_session`: best-effort re-apply (result_view → left panel → active_tab; gated tab falls back via _switch_tab)

## 3. Locks + gate
- [x] 3.1 test_ui_layout_hygiene.py +5: cheat-sheet rows, cycle-skips-legacy, toggle gating, field_menu no-Shanghai source lock, ui_state round-trip
- [x] 3.2 Full parallel suite green — 1091 passed / 4 skipped / 1 xpassed in 4:54 (+ post-tooltip re-run of hygiene+main_smoke 31 passed)
