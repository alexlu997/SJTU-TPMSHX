"""Smoke tests for batch_runner: serial and parallel execution of simple cases.

Run with:
    cd D:/Postgraduate/均质化/ThermoNAS/thermoNas
    python test_batch_runner.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np


def _make_shanghai_like_case(u_air: float) -> dict:
    """Build a self-contained case dict equivalent to Shanghai Case 1 with a
    varied u_air (air inlet velocity). Used as a reference smoke-test case."""
    return {
        'tpms': 'Gyroid',
        'L_cell_mm': 7.0,
        't_wall_mm': 0.6,
        'K_S': 16.0,
        'L_dom': 0.231,
        'H_dom': 0.042,
        'N_UNITS': 36,
        'A_flow_per_unit': 18.0565e-6,
        'u_air': u_air,
        'T_Ain_C': 126.0,
        'T_Bin_C': 18.1,
        'T_Bout_C': 23.6,
        'P_Ain_gauge_Pa': 1156.0,
    }


def test_run_single_case_returns_finite_Q():
    """A single case should return a finite Q_sim value, no NaN."""
    from runs.batch_runner import run_single_case
    case = _make_shanghai_like_case(u_air=3.92)
    result = run_single_case(case)
    assert 'Q_sim' in result, f"missing Q_sim: {result}"
    assert np.isfinite(result['Q_sim']), f"Q_sim not finite: {result}"
    assert result['Q_sim'] > 0, f"Q_sim not positive: {result}"
    print(f"test_run_single_case_returns_finite_Q PASS (Q_sim={result['Q_sim']:.1f})")


def test_run_batch_serial_10_cases():
    """run_batch with max_workers=1 should behave like a plain map."""
    from runs.batch_runner import run_batch
    cases = [_make_shanghai_like_case(u_air=u) for u in np.linspace(3, 22, 10)]
    results = run_batch(cases, max_workers=1)
    assert len(results) == 10
    Q_values = [r['Q_sim'] for r in results]
    assert all(np.isfinite(q) and q > 0 for q in Q_values), f"bad Q values: {Q_values}"
    print(f"test_run_batch_serial_10_cases PASS (Q range: {min(Q_values):.0f}..{max(Q_values):.0f} W)")


def test_run_batch_parallel_10_cases():
    """run_batch with max_workers=2 should give identical results to serial."""
    from runs.batch_runner import run_batch
    cases = [_make_shanghai_like_case(u_air=u) for u in np.linspace(3, 22, 10)]
    results_serial = run_batch(cases, max_workers=1)
    results_parallel = run_batch(cases, max_workers=2)
    for i, (s, p) in enumerate(zip(results_serial, results_parallel)):
        assert abs(s['Q_sim'] - p['Q_sim']) < 1.0, \
            f"case {i}: serial Q={s['Q_sim']:.2f}, parallel Q={p['Q_sim']:.2f}"
    print("test_run_batch_parallel_10_cases PASS")


if __name__ == '__main__':
    test_run_single_case_returns_finite_Q()
    test_run_batch_serial_10_cases()
    test_run_batch_parallel_10_cases()
    print("\nAll batch_runner tests PASS")
