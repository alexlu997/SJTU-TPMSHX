"""Headless CLI for the compute pipeline (P1.8, 2026-07-20).

Formalizes the Qt-free seam (`controllers/compute_pipeline.py`) as an
installable entry point::

    tpmshx-run path/to/config.json            # solve, print summary
    tpmshx-run config.json --dry-run          # parse + dispatch only
    tpmshx-run config.json --json             # machine-readable summary

In-repo equivalent (no install): ``python -m sjtu_tpmshx.cli ...``.
Config schema: ``domain/compute_config.py`` (``ComputeConfig.from_json``
accepts the canonical schema and the legacy ``configs/shanghai_baseline.json``
shape).

Exit codes: 0 = solved and converged/valid; 2 = solved but the result is
flagged (not converged / envelope-invalid); >0 argparse/IO errors as usual.
"""
from __future__ import annotations

import argparse
import json

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog='tpmshx-run',
        description='Headless SJTU-TPMSHX solve: ComputeConfig JSON in, '
                    'summary out. Qt is never imported.')
    ap.add_argument('config', help='ComputeConfig JSON file '
                                   '(canonical or legacy baseline shape)')
    ap.add_argument('--dry-run', action='store_true',
                    help='parse + validate + pipeline dispatch, no solve')
    ap.add_argument('--json', action='store_true', dest='as_json',
                    help='machine-readable one-line JSON summary')
    args = ap.parse_args(argv)

    from sjtu_tpmshx.domain.compute_config import ComputeConfig
    from sjtu_tpmshx.controllers.compute_pipeline import pipeline_for

    cc = ComputeConfig.from_json(args.config)
    pipe = pipeline_for(cc)
    if args.dry_run:
        info = {'pipeline': type(pipe).__name__,
                'grid': [cc.solver.Nx, cc.solver.Ny, cc.solver.Nz]}
        print(json.dumps(info) if args.as_json
              else f"[dry-run] {info['pipeline']} grid={info['grid']}")
        return 0

    result = pipe.run()
    diag = result.diagnostics or {}
    ok = bool(diag.get('envelope_valid', True)) and bool(
        (diag.get('convergence_detail') or {}).get('outer_converged', True))
    warnings_list: list = list(getattr(result, 'warnings', []) or [])
    summary = {
        'Q_W': getattr(result, 'Q_W', None),
        'dP_A_Pa': getattr(result, 'dP_A_Pa', None),
        'dP_B_Pa': getattr(result, 'dP_B_Pa', None),
        'envelope_valid': diag.get('envelope_valid'),
        'outer_converged': (diag.get('convergence_detail') or {}
                            ).get('outer_converged'),
        'warnings': warnings_list,
    }
    if args.as_json:
        print(json.dumps(summary, ensure_ascii=False, default=str))
    else:
        print(f"Q = {summary['Q_W']} W")
        print(f"dP_A = {summary['dP_A_Pa']} Pa   dP_B = {summary['dP_B_Pa']} Pa")
        print(f"envelope_valid = {summary['envelope_valid']}   "
              f"outer_converged = {summary['outer_converged']}")
        for w in warnings_list:
            print(f"warning: {w}")
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())
