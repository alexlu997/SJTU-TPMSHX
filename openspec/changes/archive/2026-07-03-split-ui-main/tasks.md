# Tasks

## 1. Mixin extraction (verbatim moves, byte-verified vs HEAD blob)
- [x] 1.1 ui/mixins/shortcuts.py (139) — ShortcutsMixin
- [x] 1.2 ui/mixins/io_actions.py (321) — IOActionsMixin; __version__/_git_commit_hash resolved lazily (acyclic, run_history precedent)
- [x] 1.3 ui/mixins/result_bridge.py (89) — ResultCache property bridges incl. no-op-True setter trap comments
- [x] 1.4 main.py 2018→1544; MRO = 13 mixins; dead imports pruned

## 2. Builders
- [x] 2.1 ui/builders_sidebar.py (149, sha-verified) + builders_canvas 1343→1206 with relative-style re-export

## 3. Gates + docs
- [x] 3.1 main smoke + hygiene 31/31 (both agents independently green)
- [x] 3.2 Full parallel suite green — 1095 passed / 4 skipped / 1 xpassed in 5:07
- [x] 3.3 PROJECT_MANUAL: +3 mixin rows, 13-mixin MRO, main.py ~1540, declined-split records (panel_vis_3d / build_canvas_area monolith)

## 4. openspec hygiene (bonus, same batch)
- [x] 4.1 7 legacy main specs repaired: stray "## ADDED Requirements" delta headers → ## Purpose + ## Requirements; `openspec validate --all` now 17/18 (only the user's active df-coeffs-cfd-refit change remains, untouched)
