# 2026-07 upgrade closeout

This is the retained summary of the completed `upgrade/loop` campaign. The
working protocol, progress timeline, temporary tools, and intermediate decision
files were removed from the active tree after completion; Git history preserves
their full text.

## Delivery

- Work ran from 2026-07-19 through 2026-07-27.
- PR #48 merged `upgrade/loop` into `master` with merge commit `5580df6`.
- The campaign covered packaging, import layering, pipeline separation,
  validation contracts, solver performance, and D-F/sCO2 calibration work.
- The production numerical changes were kept in separate commits so their
  rationale remains recoverable from Git history.

## Lasting outcomes

- `ComputeConfig` and `ComputeResult` define the Qt-free compute contract.
- The 2D and 3D production paths run through their pipeline classes.
- `run_stack_3d.py` became a thin entry point over staged implementation.
- Ruff, mypy, import-layering, and pytest gates were added to the repository.
- Package-qualified `sjtu_tpmshx.*` imports became the repository convention.
- The sCO2 CFD update completed the Gyroid L=8 geometry column and refreshed
  the corresponding fitted coefficients.

Current architecture and physical invariants are maintained in
[`../architecture.md`](../architecture.md). Calibration evidence that remains
scientifically useful is retained in
[`../DF-CALIBRATION-AUDIT-2026-07.md`](../DF-CALIBRATION-AUDIT-2026-07.md).

## Open questions recorded at closeout

These were unresolved when the campaign ended; this list is historical, not a
claim that they remain open today.

- D8: water-side flow area/channel count for the 7-6 specimen.
- D9: sCO2 pressure-tap locations and whether mass flow is total or per side.
- D10: which inlet/outlet orientation represents the delivered product.
- D12: provenance of the boundary-effect coefficient alpha.
- D13: independent confirmation of the updated Gyroid L=8 CFD trend.
