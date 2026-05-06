"""Benchmark harness for SJTU-TPMSHX A (performance subproject).

Measures:
  1. Cold import of solve_full (with __pycache__ cleared)
  2. Warm import of solve_full (3 runs, take min)
  3. validate_shanghai.py wall time (3 runs, take median)
  4. batch_runner.run_batch on 50 Shanghai-Case-1-like cases, serial
  5. batch_runner.run_batch on 50 Shanghai-Case-1-like cases, parallel

Writes results JSON to benchmark_a_results.json and prints a
human-readable summary. Uses baseline from benchmark_a_baseline.json
(captured in Task 1) for before/after comparison.

Run with:
    cd D:/Postgraduate/均质化/SJTU-TPMSHX/sjtu_tpmshx
    python benchmark_a.py
"""
import json
import os
import shutil
import statistics
import subprocess
import sys
import time

import numpy as np


def _run(args, cwd='.'):
    """Run a subprocess and return wall time in seconds."""
    t0 = time.perf_counter()
    subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    return time.perf_counter() - t0


def measure_cold_import():
    """Clear __pycache__ and measure fresh import time."""
    if os.path.exists('__pycache__'):
        shutil.rmtree('__pycache__')
    return _run([sys.executable, '-c', 'import solve_full'])


def measure_warm_import():
    """Measure best-case (cached) import time, 3 runs, take min."""
    _run([sys.executable, '-c', 'import solve_full'])  # prime
    times = [_run([sys.executable, '-c', 'import solve_full']) for _ in range(3)]
    return min(times)


def measure_validate_shanghai():
    """Measure legacy validate_shanghai.py wall time, 3 runs, take median.

    Path updated 2026-05-06 (fix #5 cleanup): validate_shanghai.py moved to
    validation/legacy/. Benchmark target preserved for historical
    comparability of the v1.0.x baseline.
    """
    script = '../validation/legacy/validate_shanghai.py'
    times = [_run([sys.executable, script]) for _ in range(3)]
    return statistics.median(times)


def _make_50_cases():
    """Shanghai Case 1 template, u_air linearly scanned [3, 25] m/s, 50 points."""
    u_values = np.linspace(3.0, 25.0, 50)
    return [{
        'tpms': 'Gyroid',
        'L_cell_mm': 7.0,
        't_wall_mm': 0.6,
        'K_S': 16.0,
        'L_dom': 0.231,
        'H_dom': 0.042,
        'N_UNITS': 36,
        'A_flow_per_unit': 18.0565e-6,
        'u_air': float(u),
        'T_Ain_C': 126.0,
        'T_Bin_C': 18.1,
        'T_Bout_C': 23.6,
        'P_Ain_gauge_Pa': 1156.0,
    } for u in u_values]


def measure_batch(max_workers):
    """Run batch_runner on 50 cases and return wall time."""
    from runs.batch_runner import run_batch
    cases = _make_50_cases()
    t0 = time.perf_counter()
    _ = run_batch(cases, max_workers=max_workers)
    return time.perf_counter() - t0


def main():
    print('--- SJTU-TPMSHX A benchmark ---')
    print('1. Measuring cold import...')
    cold = measure_cold_import()
    print(f'   cold: {cold:.3f} s')

    print('2. Measuring warm import (3 runs, min)...')
    warm = measure_warm_import()
    print(f'   warm: {warm:.3f} s')

    print('3. Measuring validate_shanghai.py (3 runs, median)...')
    val = measure_validate_shanghai()
    print(f'   validate_shanghai: {val:.3f} s')

    print('4. Measuring 50-case batch (serial)...')
    batch_serial = measure_batch(max_workers=1)
    print(f'   serial: {batch_serial:.3f} s')

    n_workers = max(1, (os.cpu_count() or 2) - 1)
    print(f'5. Measuring 50-case batch (parallel, {n_workers} workers)...')
    batch_parallel = measure_batch(max_workers=n_workers)
    print(f'   parallel: {batch_parallel:.3f} s')

    results = {
        'import_solve_full_cold_s': round(cold, 3),
        'import_solve_full_warm_s': round(warm, 3),
        'validate_shanghai_s_median': round(val, 3),
        'batch_50_serial_s': round(batch_serial, 3),
        'batch_50_parallel_s': round(batch_parallel, 3),
        'parallel_workers': n_workers,
    }
    if batch_parallel > 0:
        results['parallel_speedup'] = round(batch_serial / batch_parallel, 2)

    # Load baseline for comparison
    try:
        with open('benchmark_a_baseline.json') as f:
            baseline = json.load(f)
        results['baseline'] = baseline
        results['speedup_validate_shanghai'] = round(
            baseline['validate_shanghai_s_median'] / val, 2)
    except FileNotFoundError:
        pass

    with open('benchmark_a_results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print()
    print('--- Results JSON ---')
    print(json.dumps(results, indent=2))

    print()
    print('--- A acceptance criteria ---')
    ok1 = val <= 8.0
    print(f'[1] validate_shanghai.py <= 8 s: {ok1} (actual: {val:.2f} s)')
    ok2 = results.get('parallel_speedup', 0) >= 4.0
    print(f'[2] parallel speedup >= 4x: {ok2} (actual: {results.get("parallel_speedup", "n/a")}x)')
    if ok1 and ok2:
        print('A ACCEPTANCE PASS')
        return 0
    else:
        print('A ACCEPTANCE FAIL')
        return 1


if __name__ == '__main__':
    sys.exit(main())
