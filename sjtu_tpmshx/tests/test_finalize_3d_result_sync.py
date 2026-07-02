"""Anti-drift guard: _finalize_3d_cfg's ComputeResult must faithfully
surface every value the _run_3d_stack raw dict produces AND every key the
3D renderer / CSV-NPZ export consume.

Since B3 C5 (2026-06-13) the ComputeResult is the SINGLE 3D result carrier:
``Main_Menu.write_result`` publishes it as ``window._result_3d`` and
``ui/plot_3d_results`` reads ``res.fields`` / the dataclass attributes.
The old raw-dict ``diagnostics['raw_3d']`` carrier is gone. A key dropped
or renamed in _finalize_3d_cfg would silently blank the 3D view / export
(offscreen smokes cannot populate the PyVista panel to catch it).

This test runs a real (small) 3D solve, builds the raw dict + the
ComputeResult, asserts the ComputeResult surfaces the raw headline scalars
+ field arrays faithfully, and locks the full render/export key contract.
Originally 2026-06-09 G1 (dual-representation sync); upgraded to the
single-carrier contract guard in B3 C5.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig,
    PartialBCConfig, ExtrapPolicy, FeatureFlags,
)
from domain.compute_result import ComputeResult
import pipelines.stages_3d as R


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

    # ── B3 C4/C5: ComputeResult carries the full render/export contract
    # and is now the SINGLE carrier (raw_3d dict retired). New slots must
    # equal their raw counterparts.
    np.testing.assert_array_equal(
        np.asarray(result.fields['L_mm']), np.asarray(raw['L_mm']),
        err_msg="fields['L_mm'] != raw['L_mm']")
    assert result.props['u_A_in_mps'] == pytest.approx(raw['u_A'])
    assert result.props['T_in_A_K'] == pytest.approx(raw['T_in'])
    assert result.diagnostics['_max_outer'] == raw['_max_outer']
    assert result.diagnostics['mode'] == '3d'

    # ── B3 C5: the raw_3d carrier is GONE — the ComputeResult is what
    # window._result_3d now holds. Lock the FULL render/export contract:
    # every key ui/plot_3d_results.finalize_plots_3d +
    # _render_2d_slices_from_3d + main._export_results consume must be
    # present (fields arrays + dataclass scalars). If a future change
    # drops one, the 3D view / export silently blanks — this guard
    # catches it without a live PyVista panel.
    assert 'raw_3d' not in result.diagnostics, (
        "raw_3d carrier must be retired (B3 C5)")
    _fields_consumed = {
        'Ta', 'Tb', 'Ts', 'vmag_A', 'vmag_B',
        'P_fA', 'P_fB', 'L_mm',
        'dx', 'dy', 'dz', 'Lx', 'Ly', 'Lz', 'dir_A', 'dir_B',
        'ucA', 'vcA', 'wcA', 'ucB', 'vcB', 'wcB',
    }
    missing_f = _fields_consumed - set(result.fields)
    assert not missing_f, (
        f"ComputeResult.fields lost renderer keys: {sorted(missing_f)}")
    _diag_consumed = {'_ltne_info', '_max_outer', 'mode'}
    missing_d = _diag_consumed - set(result.diagnostics)
    assert not missing_d, (
        f"ComputeResult.diagnostics lost keys: {sorted(missing_d)}")
    # Scalars the renderer + export read off the dataclass / props.
    for attr in ('Q_W', 'dP_A_Pa', 'dP_B_Pa', 'T_out_A_K', 'T_out_B_K'):
        assert hasattr(result, attr), f"ComputeResult missing {attr}"
    assert 'u_A_in_mps' in result.props and 'T_in_A_K' in result.props


def test_finalize_3d_forwards_envelope_and_simple_warnings():
    """U2 (audit 2026-06-28): _run_3d_stack collects envelope/choke messages AND
    the explicit SIMPLE non-convergence warning on the raw dict, but the finalize
    stage hard-coded warnings=[] and dropped them — so a 3D run with an
    under-resolved SIMPLE solve or an envelope_mode='warn' flag reached the UI
    with no indication (the 2D pipeline DOES surface these). Finalize must
    forward raw['envelope_warnings'] to ComputeResult.warnings and carry
    envelope_valid/reasons into diagnostics."""
    raw = {
        'envelope_warnings': [
            'SIMPLE momentum solve did not converge to tol at: A',
            'Choked/supersonic flow: predicted outlet vacuum.',
        ],
        'envelope_valid': False,
        'envelope_reasons': ['[A] supersonic: Ma_max = 1.20 >= 1'],
    }
    result = R._finalize_3d_cfg(raw, {'extrap_reasons': []})
    assert any('did not converge' in w for w in result.warnings), \
        'SIMPLE non-convergence warning dropped at finalize'
    assert any('Choked' in w for w in result.warnings), \
        'envelope/choke warning dropped at finalize'
    assert result.diagnostics.get('envelope_valid') is False
    assert result.diagnostics.get('envelope_reasons')
