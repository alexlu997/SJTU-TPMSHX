## 1. Safety baseline

- [x] 1.1 Clean tree (`git status`); own commit.
- [x] 1.2 Capture a UI-smoke reference (logo/banner currently load): `python -u sjtu_tpmshx/runs/smoke_ui_offscreen.py` → note pass.

## 2. Remove orphan / stale (local, untracked → plain rm, zero git impact)

- [x] 2.1 Confirm untracked: `git ls-files sjtu_tpmshx/lut_*.npz sjtu_tpmshx/nTop_inputs/` returns nothing.
- [x] 2.2 Re-confirm orphan lut: `git grep -n 41x21` and `git grep -n "lut_Diamond\|lut_Gyroid"` show no loader pointing at the package root (loader is `solvers/sigmoid_field.py:123`, cache_dir=`solvers/`, name `…_N{N}.npz`).
- [x] 2.3 `rm sjtu_tpmshx/lut_Diamond_41x21.npz sjtu_tpmshx/lut_Gyroid_41x21.npz`
- [x] 2.4 `rm -r sjtu_tpmshx/nTop_inputs/`  (3 untracked stale files)
- [x] 2.5 `rmdir Pic/`  (empty)

## 3. Remove DEPRECATED scripts (tracked → git rm)

- [x] 3.1 Confirm no importers: `git grep -nE "import .*asym_export_(cfd_cases|stl)|from .*asym_export"` returns nothing outside the two files.
- [x] 3.2 `git rm sjtu_tpmshx/runs/asym_export_cfd_cases.py sjtu_tpmshx/runs/asym_export_stl.py`

## 4. Relocate package-root branding assets

- [x] 4.1 `mkdir -p sjtu_tpmshx/assets/logos` and `git mv` the 4 PNGs (`sjtulogored.png`, `sjtulogosilver.png`, `sjtubannerred.png`, `sjtubannersilver.png`) into it.
- [x] 4.2 Fix `main.py:134` — the icon path `os.path.join(os.path.dirname(__file__), 'sjtulogosilver.png')` → `os.path.join(os.path.dirname(__file__), 'assets', 'logos', 'sjtulogosilver.png')`.
- [x] 4.3 Fix `ui/ui_builders.py:80` — banner path (currently resolves the PNG next to the package root) → point at `assets/logos/`. Mind that `ui_builders.py` lives in `ui/`, so its base dir differs from `main.py`; build the path from the package root (`…/sjtu_tpmshx/assets/logos/`), not `os.path.dirname(__file__)` of `ui/`.
- [x] 4.4 Grep for any other PNG reference: `git grep -nE "sjtulogo|sjtubanner"` — every hit now points at `assets/logos/`.

## 5. Move the tooling lockfile out of the package

- [x] 5.1 Confirm no code reference: `git grep -n "skills-lock"` (expect none in `*.py`).
- [x] 5.2 If tracked: `git mv sjtu_tpmshx/skills-lock.json .claude/skills-lock.json` (or, if `.claude/` is gitignored, `git rm` it and let the tool regenerate). If untracked: `rm` and add `skills-lock.json` to `.gitignore`.

## 6. Fix the validate_shanghai_aligned.py entry-guard bug

- [x] 6.1 Confirm orphan: `git grep -n "validate_shanghai_aligned"` shows only comment references, no import / `-m` invocation.
- [x] 6.2 Wrap the module's top-level executable body in `def main(): …` + `if __name__ == "__main__": main()`, so importing it no longer writes an xlsx. Preserve identical behavior when run as a script.

## 7. Codify the convention (spec)

- [x] 7.1 The `repository-structure` capability spec (this change's `specs/`) records: lowercase-snake dir/module names; `projects/<NNN>-Name/`; no orphan caches/assets loose in the package root (assets under `assets/`); runnable scripts guard with `__main__`; regeneratable outputs gitignored not committed.
- [x] 7.2 Add a one-line `projects/`-style note + the `assets/` location to `PROJECT_MANUAL.md` directory map.

## 8. Verify + close-out

- [x] 8.1 UI smoke green (logo/banner load from new path): `python -u sjtu_tpmshx/runs/smoke_ui_offscreen.py` (and `smoke_ui_screenshots.py` if it renders the banner).
- [x] 8.2 Full suite: `pytest sjtu_tpmshx/tests/ -q` green; golden 2D/3D unchanged.
- [x] 8.3 `git grep` sweep: no dangling reference to a moved/removed file (`sjtulogo`, `sjtubanner`, `lut_*41x21`, `nTop_inputs`, `asym_export_`, `skills-lock`).
- [x] 8.4 `openspec validate restructure-1-toplevel-hygiene --strict`.
- [x] 8.5 Commit (single hygiene commit). **Defer push/archive until the user OKs**, consistent with repo rule.
