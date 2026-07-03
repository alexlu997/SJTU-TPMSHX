# Tasks

## 1. Shortcuts (乙)
- [ ] 1.1 main.py: Ctrl+1/2/3 → layout/result/pareto; Ctrl+4 → `_toggle_result_view`; drop Ctrl+5 + temp/pres/vel binds
- [ ] 1.2 tab_view.py: `_toggle_result_view` helper (result-family aware, gated no-op)
- [ ] 1.3 main.py `_cycle_tab`: ('layout','result','pareto') + result-family current mapping
- [ ] 1.4 dialogs.py `_SHORTCUT_ROWS`: workbench rows
- [ ] 1.5 command_palette.py: Chinese tab entries (+ result entry), English keywords kept
- [ ] 1.6 field_menu.py: 恢复算例工况默认值 action + status message
- [ ] 1.7 builders_canvas.py: tab tooltips fully Chinese; tooltips on 结果/2D|3D seg buttons

## 2. Persistence (丙)
- [ ] 2.1 session_presets.py `_save_session`: ui_state {active_tab (family key), left_collapsed, result_view}
- [ ] 2.2 session_presets.py `_restore_session`: re-apply best-effort (result_view → left panel → active_tab)

## 3. Locks + gate
- [ ] 3.1 test_ui_layout_hygiene.py: cheat-sheet rows lock, palette-Chinese lock, field_menu no-Shanghai source lock, ui_state save/restore round-trip
- [ ] 3.2 Full parallel suite green
