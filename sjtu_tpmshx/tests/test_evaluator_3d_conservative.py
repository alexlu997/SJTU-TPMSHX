"""Guard: the 3D optimizer/Pareto evaluator runs on the conservative kernel.

core.evaluators.evaluate_3d historically called solve_full_domain_3d directly
with cell-centred velocities and conservative_ltne defaulting False — i.e. it
bypassed the production _run_3d_stack default flip (B-plan B5) and silently used
the legacy non-conservative cell-local-|u_c| kernel. That left a consistency
gap: the UI/production path solved with strict conservation while the optimizer
ranked designs with a different (non-conservative) kernel.

evaluate_3d now extracts the full SIMPLE staggered faces (A via transpose,
B mirror-along-y with the stream component negated — the divergence-preserving
transform) and passes conservative_ltne=True, so the optimizer uses the SAME
strict-conservation solver as the UI. This smoke locks that path in: a tiny 3D
design must run end-to-end and return finite, physical Q/dP/mass.
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optimization.evaluator_3d import evaluate_design_3d


def test_evaluator_3d_runs_conservative_kernel():
    # decision layout = [L_ctrl(8), t_ctrl(8)] mm for n_ctrl=(4,4) symmetric_y;
    # L > t for valid pore space.
    x = np.concatenate([np.full(8, 4.0), np.full(8, 0.6)])
    Q_neg_per_m, dP_total, mass_per_m = evaluate_design_3d(
        x, {'Nx_3d': 10, 'Ny_3d': 6, 'Nz_3d': 3,
            'max_outer_3d': 2, 'max_iter_energy': 800, 'tol_energy': 0.5})

    assert np.isfinite(Q_neg_per_m), "Q non-finite — conservative 3D solve failed"
    assert np.isfinite(dP_total) and dP_total > 0.0, f"dP_total={dP_total} not > 0"
    assert np.isfinite(mass_per_m) and mass_per_m > 0.0, f"mass={mass_per_m} not > 0"
    # Heat duty must be non-trivial (B carries energy through the conservative
    # kernel); Q_neg_per_m is −Q, so |Q| > 0.
    assert abs(Q_neg_per_m) > 1.0, f"|Q|/m={abs(Q_neg_per_m)} implausibly small"
