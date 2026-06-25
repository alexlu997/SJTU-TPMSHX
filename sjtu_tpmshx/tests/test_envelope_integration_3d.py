"""End-to-end envelope guards in the 3D pipeline (_run_3d_stack).

A choked case (Forchheimer dP >= inlet abs pressure) must NOT silently return
converged garbage. Default (envelope_mode='raise') -> ChokedFlowError before/at
the doomed solve; envelope_mode='warn' -> run but flag the result invalid; an
in-envelope case -> valid result, no clip.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs._case_template import build_cfg
from pipelines.stages_3d import _run_3d_stack
from solvers.envelope import ChokedFlowError


def test_choked_case_raises_by_default():
    # 0.7 m cube + 20 m/s air -> dP (~205 kPa) > inlet abs (192 kPa) -> choked.
    # Raises at the pre-solve 1D seed (grid-independent), so 20^3 is cheap.
    cfg = build_cfg(L=0.7, H=0.7, Lz=0.7, Nx=20, Ny=20, Nz=20,
                    u_A=20.0, T_inA=800.0, u_B=10.0, T_inB=400.0)
    with pytest.raises(ChokedFlowError):
        _run_3d_stack(cfg)


def test_choked_warn_mode_returns_flagged_result():
    cfg = build_cfg(L=0.7, H=0.7, Lz=0.7, Nx=12, Ny=12, Nz=12,
                    u_A=20.0, T_inA=800.0, u_B=10.0, T_inB=400.0,
                    envelope_mode='warn', sweep_profile='fast_sweep')
    res = _run_3d_stack(cfg)
    assert res['envelope_valid'] is False
    assert res['envelope_warnings'], "warn mode must surface a choke warning"


def test_in_envelope_case_valid_and_unclipped():
    cfg = build_cfg(L=0.05, H=0.05, Lz=0.05, Nx=12, Ny=12, Nz=12,
                    u_A=8.0, T_inA=800.0, u_B=4.0, T_inB=400.0)
    res = _run_3d_stack(cfg)
    assert res['envelope_valid'] is True
    assert res['p_clip_hits'] == 0
    assert res['envelope_warnings'] == []
