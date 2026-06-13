"""Frozen-value regression for the 2D + 3D continuous-field evaluators.

Pins the exact (Q_neg, dP, mass) outputs of ``evaluate_design`` (2D) and
``evaluate_design_3d`` (3D) on fixed decision vectors, captured on master
BEFORE the B3 C7 shared-quantization dedup. C7 moves the per-cell
(L, t) quantization key from Python ``round()`` to ``np.round`` inside the
shared ``solvers.continuous_field.props_from_Lt_fields`` helper; both are
round-half-even and should agree on the 0.05/0.01-quantized grid, but a
key shift of 1e-4 mm would feed different ``tpms_calc.compute`` inputs and
move the result at >=1e-6. This test is the gate that catches exactly
that — the NON-UNIFORM cases exercise the multi-unique-pair scatter path
(a uniform field has cache_size==1 and would not gate the rounding).

rel=1e-12 (not exact ==): same-machine numba is deterministic, but the
tolerance absorbs trailing-ULP float-repr noise while still catching any
rounding-key / ordering change (which moves results far above 1e-12).
Same capture/check convention as runs/_out/_golden_3d.py. If a different
CI machine trips this on FMA/thread-count variance, relax to rel=1e-9.

Marked ``slow`` (each eval is a full SIMPLE x2 + LTNE solve).
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

warnings.filterwarnings('ignore', category=UserWarning)

from solvers.continuous_field import uniform_field
from optimization.evaluator import evaluate_design
from optimization.evaluator_3d import evaluate_design_3d

pytestmark = pytest.mark.slow

_REL = 1e-12

# Lighter solver settings (mirror tests/test_evaluator_sanity.py:_FAST_CFG).
_FAST_CFG = {'max_iter_simple': 800, 'tol_simple': 1e-3,
             'max_iter_energy': 1500, 'tol_energy': 0.5, 'n_rho_loops': 1}

_CFG_3D = {'Nx_3d': 10, 'Ny_3d': 6, 'Nz_3d': 3, 'max_outer_3d': 2,
           'max_iter_energy': 800, 'tol_energy': 0.5}

# Non-uniform 16D decision vector: [L_flat(8), t_flat(8)] (mm), L > t.
# n_ctrl=(4,4) symmetric_y → 8 L + 8 t. Spatially-varying ⇒ many unique
# quantized (L, t) pairs ⇒ exercises the scatter rounding C7 touches.
_X_NONUNIF = np.array([5.0, 6.0, 7.0, 8.0, 5.5, 6.5, 7.5, 6.0,
                       0.40, 0.45, 0.50, 0.55, 0.42, 0.48, 0.52, 0.46])

# ── frozen outputs captured on master pre-C7 (2026-06-13) ──
_FROZEN_2D_UNIFORM = (-8577.196126819217, 11140.595170866562,
                      3.446685791015626)
_FROZEN_2D_NONUNIF = (-8031.512050066764, 8246.633586006588,
                      3.6729327392578126)
_FROZEN_3D_UNIFORM = (-8030.108755476857, 16636.495632326456,
                      6.323593139648438)
_FROZEN_3D_NONUNIF = (-10109.32410315642, 5629.39740745782,
                      3.675970458984375)


def _assert_tuple(got, frozen, label):
    assert len(got) == len(frozen), f"{label}: arity {len(got)} != {len(frozen)}"
    for i, (g, fz) in enumerate(zip(got, frozen)):
        assert float(g) == pytest.approx(fz, rel=_REL), (
            f"{label}[{i}] drifted: got {float(g)!r} vs frozen {fz!r}")


def test_frozen_2d_uniform():
    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0, L_domain=0.10, H_domain=0.05)
    got = evaluate_design(x=None, cfg=dict(_FAST_CFG), fc=fc)
    _assert_tuple(got, _FROZEN_2D_UNIFORM, '2D-uniform')


def test_frozen_2d_nonuniform():
    got = evaluate_design(x=_X_NONUNIF.copy(), cfg=dict(_FAST_CFG))
    _assert_tuple(got, _FROZEN_2D_NONUNIF, '2D-nonuniform')


def test_frozen_3d_uniform():
    x_u = np.concatenate([np.full(8, 4.0), np.full(8, 0.6)])
    got = evaluate_design_3d(x_u, dict(_CFG_3D))
    _assert_tuple(got, _FROZEN_3D_UNIFORM, '3D-uniform')


def test_frozen_3d_nonuniform():
    got = evaluate_design_3d(_X_NONUNIF.copy(), dict(_CFG_3D))
    _assert_tuple(got, _FROZEN_3D_NONUNIF, '3D-nonuniform')
