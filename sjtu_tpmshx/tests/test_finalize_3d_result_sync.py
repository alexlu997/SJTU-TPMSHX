"""G1 anti-drift guard: _finalize_3d_cfg's ComputeResult must stay in sync with
the _run_3d_stack raw result dict.

The 3D path carries two result representations: the raw dict (the LIVE carrier,
stored on window._result_3d, consumed by ui/plot_3d_results.finalize_plots_3d)
and the ComputeResult dataclass (built by _finalize_3d_cfg, consumed by the C4
Pipeline3D). They can silently DRIFT — add/rename a key in the raw dict and
forget to map it in _finalize_3d_cfg, and nothing catches it (test_compute_
pipeline only exercises the ABC with stubs, never the real mapping).

This test runs a real (small) 3D solve, builds both representations, and asserts
the ComputeResult faithfully surfaces the raw dict's headline scalars + key
fields. It does NOT migrate the live UI to ComputeResult — that full
unification is the deliberate C4 ComputePipeline effort (the raw dict stays the
live carrier). This guard just locks the adapter contract so the two cannot
diverge unnoticed. 2026-06-09 G1.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controllers.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig,
    PartialBCConfig, ExtrapPolicy, FeatureFlags,
)
from controllers.compute_pipeline import ComputeResult
import runs.run_calculation_3d as R


def _small_air_air_cfg():
    """Tiny air-air cross-flow case (8x8x4) — fast, exercises both fluids."""
    return ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=8.0, T_in_K=420.0, P_in_Pa=150000.0),
        fluid_B=FluidConfig(type='air', u_mps=10.0, T_in_K=320.0, P_in_Pa=101325.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.6,
                                k_s_W_mK=16.0, L_dom_m=0.10, H_dom_m=0.042,
                                Lz_m=0.030),
        solver=SolverConfig(Nx=8, Ny=8, Nz=4),
        bc_A=PartialBCConfig(dir=0, in_ctr=0.021, in_w=0.042,
                             out_ctr=0.021, out_w=0.042),
        bc_B=PartialBCConfig(dir=3, in_ctr=0.021, in_w=0.042,
                             out_ctr=0.021, out_w=0.042),
        extrap=ExtrapPolicy(allow=True),
        flags=FeatureFlags(wall_refine_3d=False),
    )


def test_finalize_3d_result_matches_raw():
    cc = _small_air_air_cfg()
    parsed = R._parse_inputs_3d_cfg(cc)
    raw = R._run_3d_stack(parsed)
    result = R._finalize_3d_cfg(raw, parsed)

    assert isinstance(result, ComputeResult)

    # ── headline scalars: ComputeResult must equal the raw dict source ──
    assert result.Q_W == pytest.approx(raw.get('Q_total', raw.get('Q')))
    assert result.dP_A_Pa == pytest.approx(raw.get('dP_A', raw.get('dP')))
    assert result.dP_B_Pa == pytest.approx(raw['dP_B'])
    assert result.T_out_A_K == pytest.approx(raw.get('T_out_A', raw.get('T_A_out')))
    assert result.T_out_B_K == pytest.approx(raw.get('T_out_B', raw.get('T_B_out')))

    # ── field arrays: same values surfaced under the ComputeResult keys ──
    field_map = {'Ta': 'Ta', 'Tb': 'Tb', 'Ts': 'Ts',
                 'P_fA': 'P_Pa', 'P_fB': 'P_Pa_B',
                 'ucA': 'uc_real', 'vcA': 'vc_real', 'wcA': 'wc_real',
                 'vmag_A': 'vmag', 'vmag_B': 'vmag_B'}
    for k_res, k_raw in field_map.items():
        assert k_res in result.fields, f"ComputeResult.fields missing {k_res!r}"
        a = result.fields[k_res]
        b = raw.get(k_raw)
        if b is None:
            assert a is None, f"{k_res}: result has value but raw {k_raw} is None"
        else:
            np.testing.assert_array_equal(np.asarray(a), np.asarray(b),
                                          err_msg=f"{k_res} != raw[{k_raw}]")

    # ── residuals dict surfaces the conservation diagnostics faithfully ──
    for key in ('Q_enthalpy_A', 'Q_enthalpy_B', 'Q_net',
                'energy_imbalance_rel', 'mass_imbalance_rel_A'):
        assert key in result.residuals, f"residuals missing {key!r}"
        rv = raw.get(key)
        if rv is not None and np.isfinite(float(rv)):
            assert result.residuals[key] == pytest.approx(float(rv)), key
