## Why

A whole-repo structure audit (3 read-only passes: dead-code, module-boundary, naming/artifact) found the package is fundamentally healthy — clean import layering, single-sourced invariants (Nu / porosity / geometry), almost no dead code. The clutter is at the **edges**: orphan cache + branding PNGs loose in the package root, a couple of empty/stale directories, two scripts already marked DEPRECATED, one validation script missing its `__main__` guard, and no written-down layout/naming convention to stop re-scatter.

This is **Phase 1 of a 3-phase restructure** (1 = top-level + asset hygiene, low risk; 2 = package-internal taxonomy; 3 = code layer). Phase 1 is deliberately the zero-/low-risk slice: it touches no import path the package depends on, only relocates assets (with their two loader references) and removes provably-unused files. It also creates the `repository-structure` capability that Phases 2–3 extend.

## What Changes

- **Remove orphan / stale (local, untracked — zero git impact):**
  - `sjtu_tpmshx/lut_Diamond_41x21.npz`, `sjtu_tpmshx/lut_Gyroid_41x21.npz` — orphan cache. The real loader (`solvers/sigmoid_field.py:123`) reads from `cache_dir = solvers/` with name `lut_{type}_{nL}x{nt}_N{N}.npz` (e.g. `lut_Diamond_41x21_N256.npz`); these package-root files are the wrong directory, wrong name (no `_N256`), untracked, and `41x21` has zero code references. Regenerates on demand into `solvers/`.
  - `sjtu_tpmshx/nTop_inputs/` — 3 untracked stale smoke-input files (`smoke_v3_mid/`), nothing tracked, abandoned.
  - `Pic/` — empty directory (PascalCase outlier).
- **Remove DEPRECATED scripts (tracked → `git rm`, after confirming no importers):**
  - `sjtu_tpmshx/runs/asym_export_cfd_cases.py`, `sjtu_tpmshx/runs/asym_export_stl.py` — both header-marked DEPRECATED 2026-06-15.
- **Relocate loose package-root branding assets** into `sjtu_tpmshx/assets/logos/` (4 PNGs: `sjtulogored/silver.png`, `sjtubannerred/silver.png`), and fix the **two** loader references: `main.py:134` (window icon) and `ui/ui_builders.py:80` (banner). Both currently build the path from `os.path.dirname(__file__)`; repoint to `assets/logos/`.
- **Move `sjtu_tpmshx/skills-lock.json` out of the package** — it is a Claude Code tooling artifact with no code reference; relocate to `.claude/` (or gitignore + remove). The package root should hold code, not tooling locks.
- **Fix the one real bug** the audit found: `validation/validate_shanghai_aligned.py` (372 lines) executes at import — no `if __name__ == "__main__":` guard — so importing it writes an xlsx as a side effect. Wrap its top-level body in a `main()` + guard. (It is an orphan: not imported anywhere; referenced only in a comment.)
- **Codify the convention** as the new `repository-structure` capability: lowercase-snake directory/module names; the `projects/<NNN>-Name/` rule (already live); no orphan caches or assets loose in the package root (assets live under an `assets/` subtree); runnable scripts must guard execution with `__main__`; regeneratable outputs are gitignored, not committed.

## Capabilities

### New Capabilities

- `repository-structure`: durable repo-layout + naming conventions (directory naming, package-root asset placement, runnable-script entry-guard requirement, output-artifact hygiene). Phases 2–3 add package-taxonomy and code-layer requirements to this same capability.

## Impact

- **Code edits (3 files):** `main.py` + `ui/ui_builders.py` (asset path → `assets/logos/`); `validation/validate_shanghai_aligned.py` (`__main__` guard).
- **Moved:** 4 PNGs (`git mv` → `assets/logos/`), `skills-lock.json` (→ `.claude/`).
- **Deleted:** 2 untracked orphan npz, 1 untracked stale dir, 1 empty dir (all local, no git history change); 2 tracked DEPRECATED scripts (`git rm`, recoverable from history).
- **opt_runs/ left as-is** (user-confirmed: the one tracked run is an intentional, comment-documented archived reference — not a defect).
- **Gates:** full `pytest sjtu_tpmshx/tests/ -q` green; golden 2D/3D gates untouched; a UI smoke (`runs/smoke_ui_offscreen.py` or `smoke_ui_screenshots.py`) to confirm the relocated logo/banner still load after the path edits.
- **No new dependencies. No import path the package depends on is moved** (assets are data, not modules). **Out of scope:** all package-internal reorg (runs/ split, validation/ layering → Phase 2) and code-layer work (stages_3d split → Phase 3).
