"""
tests/test_optimizer_3d_dispatch.py — Phase 1 Week 4 dispatch routing

Verify:
  1. test_cfg_dim_route       — cfg['dim']=3 routes _eval_worker → evaluate_3d (mocked)
  2. test_vector_shape        — 108 vs 36 vector length enforcement
  3. test_grid_resolve_3d     — _resolve_grid_3d returns 3-tuple
  4. test_make_problem_3d     — pymoo Problem n_var == 108 under dim=3
  5. test_auto_max_workers    — worker count rules match spec

No CFD runs here (fast; just dispatcher unit tests).
"""

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_cfg_dim_route():
    from optimization import optimizer as opt_mod
    calls = {'2d_evaluate': 0, '2d_richardson': 0, '3d': 0}

    def fake_eval(x, cfg=None):
        calls['2d_evaluate'] += 1
        return -1.0, 10.0, 0.0

    def fake_rich(x, cfg=None):
        calls['2d_richardson'] += 1
        return -1.0, 10.0, 0.0

    def fake_3d(x, cfg=None):
        calls['3d'] += 1
        return -2.0, 20.0, 0.0

    with patch.object(opt_mod, 'evaluate', fake_eval), \
         patch.object(opt_mod, 'evaluate_richardson', fake_rich), \
         patch.object(opt_mod, 'evaluate_3d', fake_3d):

        # 2D path with Richardson
        opt_mod._eval_worker((np.zeros(36), {'dim': 2}, True))
        # 2D path without Richardson
        opt_mod._eval_worker((np.zeros(36), {'dim': 2}, False))
        # 3D path — must not call 2D regardless of use_richardson flag
        opt_mod._eval_worker((np.zeros(108), {'dim': 3}, True))
        opt_mod._eval_worker((np.zeros(108), {'dim': 3}, False))

    assert calls['2d_evaluate'] == 1, calls
    assert calls['2d_richardson'] == 1, calls
    assert calls['3d'] == 2, calls
    print(f"test_cfg_dim_route PASS {calls}")


def test_vector_shape():
    from optimization.optimizer import evaluate_3d
    # Wrong length 36 → ValueError
    try:
        evaluate_3d(np.zeros(36), {'dim': 3})
    except ValueError as e:
        assert '(108' in str(e) or '108' in str(e), f"wrong err msg: {e}"
        print("test_vector_shape PASS (36 rejected)")
        return
    except Exception as e:
        print(f"  unexpected: {type(e).__name__}: {e}")
    raise AssertionError("evaluate_3d should have rejected 36-d vector")


def test_grid_resolve_3d():
    from optimization.optimizer import _resolve_grid, _resolve_grid_3d
    cfg = {
        'L_domain': 0.10, 'H_domain': 0.05, 'Lz': 0.02,
        'tpms_type': 'Diamond', 'L0': 6.0, 't0': 0.3, 'k_s': 17.0,
    }
    g2 = _resolve_grid(cfg)
    assert len(g2) == 2, f"_resolve_grid must return 2-tuple, got {g2}"

    g3 = _resolve_grid_3d(cfg)
    assert len(g3) == 3, f"_resolve_grid_3d must return 3-tuple, got {g3}"
    Nx, Ny, Nz = g3
    assert Nx > 0 and Ny > 0 and Nz > 0, g3
    assert Nz >= 3, f"Nz floor of 3 not held: {g3}"

    # Explicit Nz override
    g3b = _resolve_grid_3d({**cfg, 'Nz': 7})
    assert g3b[2] == 7, g3b
    print(f"test_grid_resolve_3d PASS (2D={g2}, 3D={g3}, override={g3b})")


def test_make_problem_3d():
    from optimization.optimizer import _make_problem
    prob2 = _make_problem({'dim': 2})
    prob3 = _make_problem({'dim': 3})
    assert prob2.n_var == 36, prob2.n_var
    assert prob3.n_var == 108, prob3.n_var
    assert prob3.n_obj == 2
    assert len(prob3.xl) == 108 and len(prob3.xu) == 108
    # Per-zone bounds alternating
    assert prob3.xl[0] == 4.0 and prob3.xu[0] == 8.0  # L
    assert prob3.xl[1] == 0.3 and prob3.xu[1] == 0.5  # t
    print(f"test_make_problem_3d PASS (n_var 2D={prob2.n_var}, 3D={prob3.n_var})")


def test_auto_max_workers():
    from optimization.optimizer import _auto_max_workers
    # 2D default
    assert _auto_max_workers({'dim': 2}) == 3
    # explicit override
    assert _auto_max_workers({'dim': 3, 'max_workers': 5}) == 5
    # 3D small grid
    base = {
        'dim': 3, 'L_domain': 0.1, 'H_domain': 0.05, 'Lz': 0.02,
        'tpms_type': 'Diamond', 'L0': 6.0, 't0': 0.3, 'k_s': 17.0,
        'Nx': 20, 'Ny': 15, 'Nz': 5, 'mem_budget_gb': 12.0,
    }
    w_small = _auto_max_workers(base)
    assert w_small == 2, f"small grid expected 2, got {w_small}"

    # 3D large grid → 1
    big = {**base, 'Nx': 200, 'Ny': 100, 'Nz': 40}
    w_big = _auto_max_workers(big)
    assert w_big == 1, f"big grid expected 1, got {w_big}"

    # Memory budget overflow → 1
    tiny_budget = {**base, 'Nx': 300, 'Ny': 200, 'Nz': 200, 'mem_budget_gb': 0.1}
    w_mem = _auto_max_workers(tiny_budget)
    assert w_mem == 1, f"mem overflow expected 1, got {w_mem}"
    print(f"test_auto_max_workers PASS (2D=3, small=2, big=1, mem=1)")


if __name__ == '__main__':
    test_cfg_dim_route()
    test_vector_shape()
    test_grid_resolve_3d()
    test_make_problem_3d()
    test_auto_max_workers()
    print("\nAll optimizer 3D dispatch tests PASS")
