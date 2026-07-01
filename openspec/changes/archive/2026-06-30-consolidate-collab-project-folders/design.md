# Design — consolidate collaboration project folders

## Context

The repo mixes two kinds of files under `sjtu_tpmshx/`: **shared solver machinery** (the package: `solvers/`, `pipelines/`, `df_surrogate/`, `design/`, plus the test suite and the canonical Shanghai V&V) and **per-collaboration driver scripts** that merely *call* that machinery to size or evaluate one partner's heat exchanger. The second kind has leaked into `validation/` and `runs/` next to the first, so a collaboration deliverable (e.g. everything for partner 703's D-7-6 sCO2 PCHE) is neither grouped nor distinguishable. `624-Retrodict/` is the one project that got it right — a self-contained folder. This change generalizes that pattern.

## Decisions

### D1 — `projects/` umbrella, not repo root (user-chosen)

All three projects live under a new top-level `projects/`, and `624-Retrodict` moves in too, so the root stays uncluttered and every collaboration deliverable is found in one place. `projects/` is a plain directory, **not** a Python package — no `__init__.py`; nothing imports across it.

Rejected — each project as its own root folder (matching where 624 sits today): keeps the root cluttered as projects accumulate, which is the complaint that triggered this.

### D2 — 703 and D-7-6 are one project, not two

The 703 evaluation *is* the D-7-6 cell study (user: "703的评估我们就是用的 D-7-6 这个 TPMS 的晶胞类型以及对应的参数"). So `validate_sco2_d76*.py` (the Nu-closure experimental gate against D-7-6 data) and `validate_sco2_703*.py` / `size_sco2_703.py` / the precooler scripts (the engineering sizing + 3D/coupled field runs) are facets of the **same** deliverable and share one folder, `projects/703-sCO2-D76/`. No separate `d76/` folder and no broad `sCO2/` umbrella.

### D3 — Move drivers only; shared code, tests, poc, and Shanghai V&V stay

The invariant that makes this safe and reversible: **a project folder contains entry-point scripts that import the package, never package internals.**

- **Solver / closure code stays.** sCO2-enthalpy LTNE (`solvers/ltne_enthalpy_3d.py`), the generalized 3D Fluid-A path (`pipelines/stages_3d.py`), and `df_surrogate/predict.py` carry `703`/sCO2 strings but are shared features, not deliverables.
- **Tests stay in `sjtu_tpmshx/tests/`** (user-confirmed). They validate shared core; the golden gates and the mandated "run the full pytest suite before done" workflow depend on their location. Moving them buys self-containment at the cost of breaking discovery — not worth it.
- **`poc/` stays** — `tests/test_ltne_enthalpy_1d_optionB.py` imports `poc_1d_ltne_enthalpy_optionB`, so the PoC is test infrastructure.
- **Shanghai V&V stays** — `CLAUDE.md` lists `validate_shanghai_*.py` as the canonical validation commands and the `shanghai_3d_baseline*.csv` files are referenced baselines. Relocating them breaks documented workflows. Shanghai is the headline benchmark, not a partner deliverable.

### D4 — The one real hazard: the package `sys.path` anchor

Every mover bootstraps imports with `Path(__file__).resolve().parents[1]` (one script uses `_HERE.parent.parent`) and inserts that on `sys.path`. From `sjtu_tpmshx/validation/foo.py` that path is `sjtu_tpmshx/` — the package dir — which is why `from solvers ...` works. After moving to `projects/703-sCO2-D76/foo.py`, `parents[1]` becomes `projects/`, and every `from solvers ...` / `from pipelines ...` raises `ModuleNotFoundError`.

Fix — anchor to the package by **repo-root-relative** path, not by a fixed depth that assumes the old parent:

```python
# before (in sjtu_tpmshx/validation/):
_ROOT = Path(__file__).resolve().parents[1]            # == sjtu_tpmshx/
# after (in projects/703-sCO2-D76/):
_ROOT = Path(__file__).resolve().parents[2] / "sjtu_tpmshx"
```

This is the only code edit the reorg requires, and it is mechanical and per-file. The spec captures the *general* form of the rule (D5) so the next moved script gets it right without re-deriving.

**Why repo-root data reads are safe without edits:** both `sjtu_tpmshx/validation/` and `projects/703-sCO2-D76/` are *exactly two directories below the repo root*. Any path a script builds toward repo-root `data/raw_data/D-7-6-sCO2/` (e.g. `validate_sco2_d76.py`) is therefore unchanged by the move. Only a path built relative to `sjtu_tpmshx/` *specifically* would need touching, and the scans found none among the movers.

### D5 — Write the convention down

The point of a spec here is not the one-time move but preventing the re-scatter. The `collaboration-project-layout` capability states: project deliverables go in `projects/<NNN>-<Name>/`; shared code / tests / Shanghai V&V never move in; a moved entry point anchors its package import to the repo root so it runs from anywhere. New partner work then has an obvious home.

## Risks / trade-offs

- **A moved driver silently fails to import.** Mitigation: task 6.1 runs every moved script headless from its new path before the change is considered done; 6.3 runs the full suite to prove the package itself is untouched.
- **A stale doc/path reference is missed.** Mitigation: task 6.4 greps every script/folder name across `*.md`/`*.py`/`*.json` and requires each hit to point at the new `projects/...` path. Known hit set is small (PROJECT_MANUAL.md:592–593).
- **History opacity.** Using `git mv` (not delete+add) preserves blame/log across the relocation.
- **Folder names are a convention, easily renamed.** `703-sCO2-D76` / `704-Aircooler-10kW` mirror `624-Retrodict`'s `NNN-Name`; rename before archiving if the team prefers another label.

## Open questions

- Should redundant Shanghai snapshots (`shanghai_3d_baseline_*.csv`, ~25 variants) be pruned? Out of scope here — flagged as a separate cleanup so this change stays a pure, reversible relocation.
- Are there collaboration projects beyond 624 / 703 / 704? The scan surfaced only these three plus the (non-collaboration) Shanghai anchor; add folders the same way if more exist.
