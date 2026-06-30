---
description: Ship the current branch — push, open a PR to the repo's default branch, and rebase-merge it (with branch cleanup). Gated on the test suite when one is present.
argument-hint: "[no-merge]   (stop after opening the PR; don't merge)"
---

Ship the current feature branch end-to-end. Report **each step with evidence**; on ANY failure, STOP and do **not** merge. Each git/gh step still goes through the normal permission prompt — this command does not pre-grant anything.

Resolve up front:
- `BRANCH` = `git branch --show-current`
- `ROOT`   = `git rev-parse --show-toplevel`
- `BASE`   = repo default branch: `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name` (fallback `master`)

## 1. Preconditions
- If `BRANCH` == `BASE` → **STOP**: "on the base branch, nothing to ship."
- `git status -s`: untracked scratch is fine, but **uncommitted *tracked* edits → ask the user before continuing** — they may not belong in this PR.

## 2. Test gate (mandatory when a suite exists)
- If `$ROOT/sjtu_tpmshx/tests/` exists:
  ```
  cd "$ROOT" && python -u -m pytest sjtu_tpmshx/tests/ -q
  ```
  On `ModuleNotFoundError: solvers`, prepend `PYTHONPATH="$ROOT/sjtu_tpmshx"`. Report exact **passed / failed / skipped**. **Any failure → STOP** (no push, no PR, no merge) and diagnose.
- Else: note "no test suite detected — skipping gate" and continue.

## 3. Push + open PR
- `git push -u origin "$BRANCH"`
- `gh pr create --base "$BASE" --fill`  (title/body auto-filled from the branch commits). Capture the **PR URL + number**.

## 4. Merge  (SKIP this whole section if the `no-merge` arg is present)
- `git checkout "$BASE" && git pull --ff-only`
- `gh pr merge <PR#> --rebase --delete-branch`   (linear history; removes local + remote branch)
- `git pull --ff-only`, then show `git log --oneline -3`.

## 5. Report
One line per step (✅/❌ + counts/URL), then a final verdict line:
- `SHIPPED` — merged to `BASE`
- `PR OPEN (no-merge)` — PR created, not merged
- `ABORTED — <reason>` — a gate failed; nothing merged
