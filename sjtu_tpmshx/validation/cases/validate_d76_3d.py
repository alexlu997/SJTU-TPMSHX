"""D_7_6 specimen 3D pressure-drop validation.

The Diamond L=7 mm / t=0.6 mm SLM specimen is an independent check on
Darcy-Forchheimer extrapolation beyond the Shanghai Gyroid cases.  The water
side is straight-through, so this runner reports heat duty but gates only the
air-side pressure drop.

Usage::

    python -m sjtu_tpmshx.validation.cases.validate_d76_3d
"""
from __future__ import annotations

import argparse
import sys

import numpy as np

from sjtu_tpmshx.validation.cases import validate_shanghai_3d_real as shanghai
from sjtu_tpmshx.validation.harness._case_sets import (
    D76_EXCLUDE,
    D76_N_CASES,
    D76_XLSX,
    d76_spec,
)
from sjtu_tpmshx.validation.harness._harness import load_cases_df
from sjtu_tpmshx.validation.harness._metrics import rmsre_from_pct


def run_validation(nx: int = 20, ny: int = 10, nz: int = 3) -> dict:
    """Run all valid D_7_6 cases and return pressure-drop error metrics."""
    spec = d76_spec()
    df = load_cases_df(D76_XLSX)
    excluded = sorted(case + 1 for case in D76_EXCLUDE)

    print(
        f"D_7_6 3D validation (Diamond L=7 t=0.6, eps={spec.eps:.4f}, "
        f"D_H={spec.D_h * 1000:.3f} mm, A_FLOW={spec.a_flow_m2 * 1e6:.0f} mm2)"
    )
    print(f"Grid {nx}x{ny}x{nz}; cases 1-{D76_N_CASES} excl {excluded}\n")

    errors = []
    for ci in range(D76_N_CASES):
        if ci in D76_EXCLUDE:
            continue
        result = shanghai._run_one_case(
            ci,
            df,
            nx,
            ny,
            nz,
            wall_refine=False,
            profile_kind="uniform",
            profile_eta=0.0,
            max_outer=shanghai.MAX_OUTER,
            spec=spec,
        )
        valid = bool(result["pressure_state_valid"])
        errors.append((ci + 1, result["err_dP%"], valid))
        print(
            f"Case {ci + 1:2d}: dP {result['dP_exp']:.0f}/{result['dP_sim']:.0f} "
            f"({result['err_dP%']:+.1f}%)  [P-valid={valid}]"
        )

    valid_errors = np.array(
        [error for _, error, valid in errors if valid and np.isfinite(error)]
    )
    invalid_count = sum(1 for _, _, valid in errors if not valid)
    rmsre_dp = rmsre_from_pct(valid_errors) if valid_errors.size else float("nan")
    bias = float(valid_errors.mean()) if valid_errors.size else float("nan")
    result = {
        "rmsre_dP": rmsre_dp,
        "bias": bias,
        "n_valid": len(valid_errors),
        "n_invalid": invalid_count,
    }
    print(
        f"\nRMSRE_dP = {rmsre_dp:.2f}%   bias = {bias:+.1f}%   "
        f"valid {len(valid_errors)}/{len(errors)}"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nx", type=int, default=20)
    parser.add_argument("--ny", type=int, default=10)
    parser.add_argument("--nz", type=int, default=3)
    parser.add_argument(
        "--gate-dp",
        type=float,
        default=25.0,
        help="fail when pressure-drop RMSRE exceeds this percentage (default 25)",
    )
    parser.add_argument("--no-gate", action="store_true", help="report only")
    args = parser.parse_args()

    result = run_validation(args.nx, args.ny, args.nz)
    if args.no_gate:
        return 0
    failed = (
        result["n_invalid"] > 0
        or result["n_valid"] != D76_N_CASES - len(D76_EXCLUDE)
        or not np.isfinite(result["rmsre_dP"])
        or result["rmsre_dP"] > args.gate_dp
    )
    print(
        f"GATE {'FAIL' if failed else 'PASS'}: RMSRE_dP "
        f"{result['rmsre_dP']:.2f}% (limit {args.gate_dp:.1f}%)"
    )
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
