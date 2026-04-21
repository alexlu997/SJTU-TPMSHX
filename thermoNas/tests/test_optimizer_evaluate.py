"""Smoke test for optimizer.evaluate — ensures the end-to-end evaluation
chain (decision vector → sigmoid field → SIMPLE → dP/Q extraction) works
for a uniform baseline and returns values in the expected physical range.
"""
import sys
import os
import warnings
from pathlib import Path

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

warnings.filterwarnings('ignore')

import numpy as np

from optimization.optimizer import evaluate, DEFAULT_CONFIG


def test_evaluate_uniform_baseline():
    """Uniform design vector → finite positive Q, dP, mass in sane ranges."""
    cfg = dict(DEFAULT_CONFIG)
    cfg.update({
        'tpms_type': 'Gyroid',
        'L_domain': 0.05, 'H_domain': 0.03,
        'L0': 6.0, 't0': 0.4,
        'u_A': 4.0, 'u_B': 3.0,
        'T_inA': 500.0, 'T_inB': 350.0,
        'wall_refine': False,
    })
    x = np.tile([cfg['L0'], cfg['t0']], 18)
    Q_neg, dP, mass = evaluate(x, cfg)
    Q = -Q_neg

    assert np.isfinite(Q) and Q > 0, f"Q must be positive finite, got {Q}"
    assert np.isfinite(dP) and dP > 0, f"dP must be positive finite, got {dP}"
    assert np.isfinite(mass) and mass > 0, f"mass must be positive finite, got {mass}"
    # Sanity bounds for this small Gyroid configuration
    assert 100 < Q < 1e5, f"Q = {Q:.1f} outside sane range [100, 1e5] W/m"
    assert 10 < dP < 1e5, f"dP = {dP:.1f} outside sane range [10, 1e5] Pa"
    assert 0.01 < mass < 100, f"mass = {mass:.3f} outside sane range"
    print(f"test_evaluate_uniform_baseline PASS (Q={Q:.1f}, dP={dP:.1f}, mass={mass:.3f})")


def test_evaluate_fast_mode_smoke():
    """fast_mode=True → finite positive Q, dP, mass + deviation from full
    within acceptance window (Q < 5%, dP < 10%)."""
    cfg = dict(DEFAULT_CONFIG)
    cfg.update({
        'tpms_type': 'Gyroid',
        'L_domain': 0.05, 'H_domain': 0.03,
        'u_A': 4.0, 'u_B': 3.0,
        'T_inA': 500.0, 'T_inB': 350.0,
        'wall_refine': False,
    })
    x = np.tile([cfg['L0'], cfg['t0']], 18)
    Qf_neg, dPf, mf = evaluate(x, {**cfg, 'fast_mode': False})
    Qfa_neg, dPfa, mfa = evaluate(x, {**cfg, 'fast_mode': True})
    Qf, Qfa = -Qf_neg, -Qfa_neg

    for v, name in ((Qfa, 'Q'), (dPfa, 'dP'), (mfa, 'mass')):
        assert np.isfinite(v) and v > 0, f"fast {name} not positive finite: {v}"
    q_err = abs(Qfa - Qf) / Qf * 100
    dp_err = abs(dPfa - dPf) / dPf * 100
    assert q_err < 5.0, f"fast Q error {q_err:.2f}% exceeds 5%"
    assert dp_err < 10.0, f"fast dP error {dp_err:.2f}% exceeds 10%"
    print(f"test_evaluate_fast_mode_smoke PASS "
          f"(Q Δ {q_err:.2f}%, dP Δ {dp_err:.2f}%)")


def test_evaluate_deterministic():
    """Same x + cfg → identical (Q, dP, mass) across two calls (no hidden state)."""
    cfg = dict(DEFAULT_CONFIG)
    cfg.update({
        'tpms_type': 'Diamond',
        'L_domain': 0.04, 'H_domain': 0.03,
        'u_A': 3.0, 'u_B': 3.0,
        'T_inA': 450.0, 'T_inB': 300.0,
        'wall_refine': False,
    })
    x = np.tile([6.0, 0.35], 18)
    r1 = evaluate(x.copy(), cfg)
    r2 = evaluate(x.copy(), cfg)
    for a, b, name in zip(r1, r2, ('Q_neg', 'dP', 'mass')):
        assert abs(a - b) / max(abs(a), 1e-12) < 1e-6, \
            f"evaluate not deterministic on {name}: {a} vs {b}"
    print("test_evaluate_deterministic PASS")


if __name__ == '__main__':
    test_evaluate_uniform_baseline()
    test_evaluate_deterministic()
    test_evaluate_fast_mode_smoke()
    print("\nAll optimizer evaluate tests PASS")
